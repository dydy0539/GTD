"""Enrichment, part 1: real titles for captured links.

Runs after capture (never inside it), so a slow or failing site can't lose
anything. Only replaces placeholder titles like "youtube.com/watch";
titles you gave yourself (e.g. an email subject) are kept.
"""
from __future__ import annotations

import html
import json
import re
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

from .model import Item
from .store import Store

UA = "Mozilla/5.0 (compatible; gtd-inbox/0.1)"
LINK_CHANNELS = {"url", "youtube", "twitter", "podcast"}


def placeholder_title(canonical_url: str) -> str:
    parts = urlsplit(canonical_url)
    return f"{parts.netloc}{parts.path}"[:80]


def fetch(url: str, timeout: float = 10, limit: int = 512_000) -> str:
    req = Request(url, headers={"User-Agent": UA, "Accept-Language": "en"})
    with urlopen(req, timeout=timeout) as resp:
        return resp.read(limit).decode(resp.headers.get_content_charset() or "utf-8", "replace")


def _text(fragment: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def lookup(item: Item, get=fetch) -> dict[str, str]:
    """Return {"title": ..., optionally "author": ...} for a link item."""
    url = item.source.get("canonical_url") or item.source.get("url", "")
    if item.channel == "youtube":
        data = json.loads(get(f"https://www.youtube.com/oembed?format=json&url={quote(url, safe='')}"))
        return {"title": data["title"], "author": data.get("author_name", "")}
    if item.channel == "twitter":
        data = json.loads(get(f"https://publish.twitter.com/oembed?omit_script=true&url={quote(url, safe='')}"))
        tweet = re.search(r"<p[^>]*>(.*?)</p>", data.get("html", ""), re.S)
        text = _text(tweet.group(1)) if tweet else ""
        author = data.get("author_name", "")
        return {"title": f"{author}: {text}"[:120] if text else author, "author": author}
    page = get(url)
    for pattern in (r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)',
                    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:title',
                    r"<title[^>]*>(.*?)</title>"):
        m = re.search(pattern, page, re.I | re.S)
        if m and _text(m.group(1)):
            return {"title": _text(m.group(1))}
    return {}


def enrich_titles(store: Store, get=fetch) -> list[str]:
    report = []
    for item in store.items():
        canon = item.source.get("canonical_url")
        if item.channel not in LINK_CHANNELS or not canon or item.title != placeholder_title(canon):
            continue
        try:
            found = lookup(item, get)
        except Exception as e:  # network, blocked site, bad JSON: keep the placeholder
            report.append(f"  ✗ {item.title}  ({type(e).__name__})")
            continue
        if not found.get("title"):
            continue
        item.title = found["title"]
        if found.get("author"):
            item.source["author"] = found["author"]
        store.save(item)
        store.log("enriched", item.id, enricher="title")
        report.append(f"  ✓ {item.icon} {item.title}")
    return report


# ---------- Enrichment, part 2: read screenshots and photos with Claude ----------
VISION_MODEL = "claude-opus-5"
VISION_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
VISION_PROMPT = """This image was saved to a personal "getting things done" inbox \
(usually a phone screenshot of a chat, a social media post, an article or a receipt). \
Describe it so it can be triaged later without opening the image:
- title: what this is about, max 80 characters, specific (names, companies, tickers), no "Screenshot of".
- summary: 1-3 sentences on the substance and why someone might have saved it.
- text: the important visible text, transcribed faithfully (keep the original language).
- urls: every complete URL visible in the image; leave out partial or cut-off ones."""
VISION_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "summary": {"type": "string"},
        "text": {"type": "string"},
        "urls": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title", "summary", "text", "urls"],
    "additionalProperties": False,
}


def describe_image(client, data: bytes, mime: str) -> dict:
    import base64

    response = client.beta.messages.create(
        model=VISION_MODEL,
        max_tokens=4000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",  # if Opus declines, the API retries on a fallback model
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": VISION_SCHEMA}},
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": mime,
                                         "data": base64.standard_b64encode(data).decode()}},
            {"type": "text", "text": VISION_PROMPT},
        ]}],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("model declined to describe the image")
    return json.loads(next(b.text for b in response.content if b.type == "text"))


def enrich_images(store: Store, client=None) -> list[str]:
    """Title, summary, text and links for captured images that don't have them yet."""
    items = [i for i in store.items() if i.channel == "image" and i.enrichment == "pending"]
    if not items:
        return []
    if client is None:
        import os
        if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
            return [f"  – {len(items)} image(s) waiting: set ANTHROPIC_API_KEY to read them"]
        import anthropic
        client = anthropic.Anthropic()

    report = []
    for item in items:
        mime = item.source.get("mime", "")
        path = store.path_of(item.id) / "attachments" / item.attachments[0] if item.attachments else None
        if mime not in VISION_TYPES or not path or not path.exists():
            item.enrichment = "n/a"
            store.save(item)
            continue
        try:
            found = describe_image(client, path.read_bytes(), mime)
        except Exception as e:  # keep the item as is; retried next run
            report.append(f"  ✗ {item.title}  ({type(e).__name__}: {e})"[:160])
            continue
        if item.title == item.source.get("filename"):  # don't overwrite a caption you wrote
            item.title = found["title"].strip()[:80] or item.title
        item.summary = found["summary"].strip()
        if found["text"].strip():
            item.summary += "\n\n**Text in image:**\n\n" + found["text"].strip()
        if found["urls"]:
            item.source["urls_in_image"] = found["urls"]
            item.summary += "\n\n" + "\n".join(f"- {u}" for u in found["urls"])
        item.enrichment = "done"
        store.save(item)
        store.log("enriched", item.id, enricher="vision", model=VISION_MODEL)
        report.append(f"  ✓ {item.icon} {item.title}")
    return report


def backfill_priority(store: Store) -> list[str]:
    """Apply typed priority markers (!high, "high priority"…) to items captured before they existed."""
    from .adapters import SELF_AUTHORED, apply_priority_markers

    report = []
    for item in store.items():
        if item.via in SELF_AUTHORED and "hints" not in item.extra and apply_priority_markers(item):
            store.save(item)
            report.append(f"  ✓ {'❗' if item.extra['hints']['priority'] == 'high' else '↓'} {item.title}")
    return report
