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
