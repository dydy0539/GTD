"""Adapters: turn one kind of raw input into an Item.

Adapters must be fast and offline — no network calls. Anything slow
(fetching pages, transcripts, OCR) belongs to enrichment.
"""
from __future__ import annotations

import email
import email.policy
import hashlib
import mimetypes
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .model import Item

TRACKING_PARAMS = re.compile(r"^(utm_.*|fbclid|gclid|mc_eid|igshid|si|ref_src)$")
PODCAST_HOSTS = ("podcasts.apple.com", "open.spotify.com/episode", "overcast.fm", "pca.st")


def sha256(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return "sha256:" + hashlib.sha256(data).hexdigest()


def first_line(text: str, max_len: int = 80) -> str:
    line = next((l.strip() for l in text.splitlines() if l.strip()), "")
    return line if len(line) <= max_len else line[: max_len - 1] + "…"


# ---------- text / dictation / chat ----------
def from_text(text: str, *, via: str = "cli", channel: str = "text",
              title: str | None = None, note: str = "", **source) -> Item:
    return Item(
        channel=channel,
        title=title or first_line(text) or "(empty note)",
        content=text.strip(),
        via=via,
        note=note,
        source={k: v for k, v in source.items() if v},
        content_hash=sha256(" ".join(text.split()).lower()),
        enrichment="n/a",
    )


# ---------- URLs: article, youtube, twitter, podcast ----------
def canonical_url(url: str) -> str:
    parts = urlsplit(url.strip())
    host = parts.netloc.lower().removeprefix("www.").removeprefix("m.")
    path = parts.path.rstrip("/") or "/"
    query = [(k, v) for k, v in parse_qsl(parts.query) if not TRACKING_PARAMS.match(k)]
    if host == "youtu.be":
        host, query, path = "youtube.com", [("v", path.strip("/"))], "/watch"
    if host in ("x.com", "twitter.com", "mobile.twitter.com"):
        host, query = "twitter.com", []  # share params only; tweet id is in the path
    return urlunsplit((parts.scheme.lower() or "https", host, path, urlencode(query), ""))


def detect_url_channel(url: str) -> str:
    host_path = url.split("://", 1)[-1]
    if host_path.startswith(("youtube.com/watch", "youtube.com/shorts", "youtube.com/live")):
        return "youtube"
    if host_path.startswith("twitter.com/"):
        return "twitter"
    if host_path.startswith(PODCAST_HOSTS):
        return "podcast"
    return "url"


def from_url(url: str, *, via: str = "cli", note: str = "", title: str | None = None) -> Item:
    canon = canonical_url(url)
    channel = detect_url_channel(canon)
    host = urlsplit(canon).netloc
    return Item(
        channel=channel,
        title=title or f"{host}{urlsplit(canon).path}"[:80],
        content=url.strip(),
        via=via,
        note=note,
        source={"url": url.strip(), "canonical_url": canon, "site": host},
        content_hash=sha256(canon),
        enrichment="pending",  # fetch text / transcript later
    )


# ---------- files: screenshots, voice memos, PDFs, .eml ----------
def from_file(path: Path, *, via: str = "cli", note: str = "", title: str | None = None) -> Item:
    path = Path(path)
    if path.suffix.lower() == ".eml":
        return from_eml(path.read_bytes(), via=via, note=note, keep_file=path, title=title)
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    channel = {"image": "image", "audio": "audio"}.get(mime.split("/")[0], "file")
    taken = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).replace(microsecond=0)
    text = ""
    if mime.startswith("text/"):
        text = path.read_text(encoding="utf-8", errors="replace")
    return Item(
        channel=channel,
        title=title or path.name,
        content=text or f"[{mime}] see attachments/{path.name}",
        via=via,
        note=note,
        source={"filename": path.name, "mime": mime, "file_modified": taken.isoformat()},
        content_hash=sha256(path.read_bytes()),
        enrichment="n/a" if text else "pending",  # OCR / transcription later
    )


def from_eml(raw: bytes, *, via: str = "cli", note: str = "",
             keep_file: Path | None = None, title: str | None = None) -> Item:
    """Parse an RFC 822 message (Gmail 'Download message', forwards, exports)."""
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    body_part = msg.get_body(preferencelist=("plain", "html"))
    body = body_part.get_content() if body_part else ""
    if body_part is not None and body_part.get_content_type() == "text/html":
        body = re.sub(r"<[^>]+>", " ", body)
        body = re.sub(r"[ \t]+", " ", body)
    source = {
        "from": str(msg.get("From", "")),
        "to": str(msg.get("To", "")),
        "subject": str(msg.get("Subject", "")),
        "message_id": str(msg.get("Message-ID", "")).strip("<>"),
    }
    if msg.get("Date"):
        try:
            source["sent_at"] = parsedate_to_datetime(msg["Date"]).isoformat()
        except (TypeError, ValueError):
            pass
    attachments = [p.get_filename() for p in msg.iter_attachments() if p.get_filename()]
    if attachments:
        source["email_attachments"] = attachments
    item = Item(
        channel="email",
        title=title or source["subject"] or "(no subject)",
        content=body.strip(),
        via=via,
        note=note,
        source={k: v for k, v in source.items() if v},
        content_hash=sha256(source["message_id"] or raw),
        enrichment="n/a",
    )
    if keep_file:
        item.attachments.append(keep_file.name)
    return item


def from_any(value: str, **kw) -> tuple[Item, list[Path]]:
    """Best-guess dispatch for `gtd capture <anything>`. Returns (item, files to attach)."""
    v = value.strip()
    if re.match(r"^https?://\S+$", v):
        return from_url(v, **kw), []
    p = Path(v).expanduser()
    if len(v) < 1024 and "\n" not in v and p.is_file():
        return from_file(p, **kw), [p]
    return from_text(v, **kw), []
