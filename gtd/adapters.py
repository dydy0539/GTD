"""Adapters: turn one kind of raw input into an Item.

Adapters must be fast and offline — no network calls. Anything slow
(fetching pages, transcripts, OCR) belongs to enrichment.
"""
from __future__ import annotations

import email
import html
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


def _plain_body(msg) -> str:
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    body = part.get_content()
    if part.get_content_type() == "text/html":
        body = re.sub(r"(?is)<(style|script)[^>]*>.*?</\1>", " ", body)
        body = re.sub(r"(?i)<br\s*/?>|</p>|</div>", "\n", body)
        body = html.unescape(re.sub(r"<[^>]+>", " ", body))
        body = re.sub(r"[ \t]+", " ", body)
    return body.strip()


def _attachments(msg) -> dict[str, bytes]:
    out = {}
    for part in msg.iter_attachments():
        name = part.get_filename()
        if name:
            out[name] = part.get_payload(decode=True) or b""
    return out


def from_eml(raw: bytes, *, via: str = "cli", note: str = "",
             keep_file: Path | None = None, title: str | None = None) -> Item:
    """Parse an RFC 822 message (Gmail 'Download message', forwards, exports)."""
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    source = {
        "from": str(msg.get("From", "")),
        "to": str(msg.get("To", "")),
        "cc": str(msg.get("Cc", "")),
        "subject": str(msg.get("Subject", "")),
        "message_id": str(msg.get("Message-ID", "")).strip().strip("<>"),
    }
    if msg.get("Date"):
        try:
            source["sent_at"] = parsedate_to_datetime(msg["Date"]).isoformat()
        except (TypeError, ValueError):
            pass
    if msg.get("List-Unsubscribe") or msg.get("List-Id"):
        source["newsletter"] = True
    attachments = list(_attachments(msg))
    if attachments:
        source["email_attachments"] = attachments
    item = Item(
        channel="email",
        title=title or source["subject"] or "(no subject)",
        content=_plain_body(msg),
        via=via,
        note=note,
        source={k: v for k, v in source.items() if v},
        content_hash=sha256(source["message_id"] or raw),
        enrichment="n/a",
    )
    if keep_file:
        item.attachments.append(keep_file.name)
    return item


# ---------- email-to-self: the phone funnel ----------
URL_RE = re.compile(r"https?://[^\s<>\"')\]]+")
BOILERPLATE = re.compile(
    r"(?im)^\s*(sent from my .*|sent from gmail.*|sent from (yahoo )?mail for .*|"
    r"get outlook for .*|sent via .*)\s*$"
)
FORWARD_MARK = re.compile(r"(?m)^-{5,} ?Forwarded message ?-{5,}\s*$|^Begin forwarded message:\s*$")
SUBJECT_PREFIX = re.compile(r"(?i)^\s*((fwd?|fw|re)\s*:\s*)+")


def _clean(text: str) -> str:
    text = text.split("\n-- \n", 1)[0]  # signature
    return BOILERPLATE.sub("", text).strip()


def from_self_email(raw: bytes, *, via: str = "email-to-self") -> list[tuple[Item, dict[str, bytes]]]:
    """Mail you sent to your capture address → inbox items.

    Share-sheet mail from phones is turned into what it really is:
      forwarded email → email item (original sender kept), note = what you wrote above it
      attachments     → one image/audio/file item each (screenshots, voice memos, PDFs)
      a single link   → url/youtube/twitter/podcast item, title = subject
      anything else   → text item (dictation, notes, pasted messenger conversations)
    Returns (item, attachment blobs) pairs; empty mail returns [].
    """
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    subject = SUBJECT_PREFIX.sub("", str(msg.get("Subject", ""))).strip()
    body = _clean(_plain_body(msg))
    blobs = _attachments(msg)

    fwd = FORWARD_MARK.search(body)
    if fwd:
        note, fwd_text = body[: fwd.start()].strip(), body[fwd.end():].strip()
        headers, lines = {}, fwd_text.splitlines()
        while lines and (m := re.match(r"^(From|Date|Subject|To|Cc|Reply-To):\s*(.*)$", lines[0])):
            headers[m.group(1).lower()] = m.group(2).strip()
            lines.pop(0)
        content = "\n".join(lines).strip()
        item = Item(
            channel="email",
            title=headers.get("subject") or subject or "(forwarded email)",
            content=content,
            via=via,
            note=note,
            source={k: v for k, v in {
                "from": headers.get("from"), "to": headers.get("to"),
                "subject": headers.get("subject"), "sent_at_text": headers.get("date"),
                "forwarded": True,
            }.items() if v},
            content_hash=sha256(" ".join(content.split()).lower()),
            enrichment="n/a",
        )
        return [(item, blobs)]

    if blobs:
        out = []
        for name, data in blobs.items():
            mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
            out.append((Item(
                channel={"image": "image", "audio": "audio"}.get(mime.split("/")[0], "file"),
                title=subject if (subject and len(blobs) == 1) else name,
                content=f"[{mime}] see attachments/{name}",
                via=via,
                note=body,
                source={"filename": name, "mime": mime},
                content_hash=sha256(data),
                enrichment="pending",
            ), {name: data}))
        return out

    urls = URL_RE.findall(body)
    if len(urls) == 1:
        rest = body.replace(urls[0], "").strip()
        if rest == subject:
            rest = ""
        return [(from_url(urls[0], via=via, note=rest, title=subject or None), {})]

    if not body and not subject:
        return []
    return [(from_text(body or subject, via=via, title=subject or None), {})]


def from_any(value: str, **kw) -> tuple[Item, list[Path]]:
    """Best-guess dispatch for `gtd capture <anything>`. Returns (item, files to attach)."""
    v = value.strip()
    if re.match(r"^https?://\S+$", v):
        return from_url(v, **kw), []
    p = Path(v).expanduser()
    if len(v) < 1024 and "\n" not in v and p.is_file():
        return from_file(p, **kw), [p]
    return from_text(v, **kw), []
