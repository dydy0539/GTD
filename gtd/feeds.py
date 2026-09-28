"""Feeds funnel: new videos from YouTube channels you follow, new podcast
episodes and blog posts — any RSS/Atom feed. No login or API key needed.

$GTD_HOME/feeds.yaml:

    youtube:                       # handle, channel URL or channel id
      - "@Stratechery"
      - https://www.youtube.com/@AsianometryYT
    feeds:                         # any RSS/Atom feed (podcasts, blogs)
      - https://feeds.megaphone.fm/investlikethebest
    people:                        # new videos featuring someone, on any channel
      - {name: Dylan Patel, priority: normal, tags: [watch, dylan-patel]}
    skip_shorts: true
    priority: low                  # hint for everything captured from feeds
    tags: [watch]

A newly added channel only brings in videos from the last few days, not its
whole back catalogue. Seen entries are remembered in state/feeds.json.
"""
from __future__ import annotations

import csv
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from . import adapters
from .enrich import fetch
from .model import now
from .store import Store

NS = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015",
      "media": "http://search.yahoo.com/mrss/"}
CHANNEL_ID = re.compile(r"UC[\w-]{22}")
NEW_FEED_LOOKBACK = timedelta(days=3)


def youtube_feed_url(channel_id: str) -> str:
    return f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"


def resolve_channel(ref: str, get=fetch) -> str:
    """'@handle', a channel URL or a UC… id → channel id."""
    m = CHANNEL_ID.fullmatch(ref.strip()) or re.search(r"/channel/(UC[\w-]{22})", ref)
    if m:
        return m.group(1) if m.re.groups else m.group(0)
    handle = ref.strip().rstrip("/").split("/")[-1]
    page = get(f"https://www.youtube.com/{handle if handle.startswith('@') else '@' + handle}")
    m = (re.search(r'<link rel="canonical" href="https://www\.youtube\.com/channel/(UC[\w-]{22})"', page)
         or re.search(r'"(?:externalId|channelId)":"(UC[\w-]{22})"', page))
    if not m:
        raise ValueError(f"couldn't find a YouTube channel for {ref!r}")
    return m.group(1)


def _dt(text: str | None) -> datetime | None:
    if not text:
        return None
    from email.utils import parsedate_to_datetime
    try:
        return datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    except ValueError:
        try:
            return parsedate_to_datetime(text)
        except (TypeError, ValueError):
            return None


def parse_feed(xml: str) -> tuple[str, list[dict]]:
    """→ (feed title, entries with id, title, url, published, author)."""
    root = ET.fromstring(xml)
    entries = []
    if root.tag == f"{{{NS['a']}}}feed":  # Atom (YouTube, many blogs)
        title = root.findtext("a:title", "", NS)
        for e in root.findall("a:entry", NS):
            link = e.find("a:link[@rel='alternate']", NS)
            if link is None:
                link = e.find("a:link", NS)
            entries.append({
                "id": e.findtext("yt:videoId", None, NS) or e.findtext("a:id", "", NS),
                "title": e.findtext("a:title", "", NS).strip(),
                "url": link.get("href") if link is not None else "",
                "published": _dt(e.findtext("a:published", None, NS) or e.findtext("a:updated", None, NS)),
                "author": e.findtext("a:author/a:name", "", NS) or title,
            })
    else:  # RSS 2.0 (podcasts, most blogs)
        channel = root.find("channel")
        title = channel.findtext("title", "") if channel is not None else ""
        for it in root.iter("item"):
            enclosure = it.find("enclosure")
            entries.append({
                "id": it.findtext("guid") or it.findtext("link") or it.findtext("title", ""),
                "title": (it.findtext("title") or "").strip(),
                "url": it.findtext("link") or (enclosure.get("url") if enclosure is not None else ""),
                "published": _dt(it.findtext("pubDate")),
                "author": title,
            })
    return title, entries


# ---------- people: new YouTube videos that feature someone, on any channel ----------
SEARCH_URL = "https://www.youtube.com/results?search_query={q}&sp=CAI%253D"  # sorted by upload date
REL_TIME = re.compile(r"(\d+)\s+(second|minute|hour|day|week|month|year)s?\s+ago", re.I)
UNIT = {"second": 1, "minute": 60, "hour": 3600, "day": 86400, "week": 604800,
        "month": 2592000, "year": 31536000}


def _runs(obj) -> str:
    if not isinstance(obj, dict):
        return ""
    return obj.get("simpleText") or "".join(r.get("text", "") for r in obj.get("runs", []))


def _video_renderers(node):
    if isinstance(node, dict):
        if "videoRenderer" in node:
            yield node["videoRenderer"]
        for v in node.values():
            yield from _video_renderers(v)
    elif isinstance(node, list):
        for v in node:
            yield from _video_renderers(v)


def youtube_search(name: str, get=fetch) -> tuple[str, list[dict]]:
    """Newest YouTube videos whose title or description mentions `name`."""
    from urllib.parse import quote_plus
    page = get(SEARCH_URL.format(q=quote_plus(f'"{name}"')))
    m = re.search(r"var ytInitialData\s*=\s*(\{.*?\});\s*</script>", page, re.S)
    if not m:
        raise ValueError("couldn't read YouTube search results")
    data = json.loads(m.group(1))
    entries, needle = [], name.lower()
    for v in _video_renderers(data):
        title = _runs(v.get("title"))
        snippet = " ".join(_runs(s.get("snippetText")) for s in v.get("detailedMetadataSnippets", []))
        snippet += " " + _runs(v.get("descriptionSnippet"))
        if needle not in f"{title} {snippet}".lower():
            continue
        published = None
        rel = REL_TIME.search(_runs(v.get("publishedTimeText")))
        if rel:
            published = now() - timedelta(seconds=int(rel.group(1)) * UNIT[rel.group(2).lower()])
        length = [int(x) for x in _runs(v.get("lengthText")).split(":") if x.isdigit()]
        seconds = sum(n * 60 ** i for i, n in enumerate(reversed(length))) if length else None
        entries.append({"id": v["videoId"], "title": title, "seconds": seconds,
                        "url": f"https://www.youtube.com/watch?v={v['videoId']}",
                        "published": published, "author": _runs(v.get("ownerText")) or "YouTube"})
    return f"YouTube: {name}", entries


def load_config(store: Store) -> dict:
    path = store.home / "feeds.yaml"
    return (yaml.safe_load(path.read_text()) or {}) if path.exists() else {}


def sync(store: Store, get=fetch, *, dry_run: bool = False) -> list[str]:
    cfg = load_config(store)
    state_path = store.home / "state" / "feeds.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    channels = state.setdefault("channels", {})   # ref → channel id
    seen = state.setdefault("seen", {})           # feed url → [entry ids]
    report = []

    # sources: (key in state, loader returning (title, entries), per-source overrides)
    sources = []
    for ref in cfg.get("youtube") or []:
        try:
            channels[ref] = channels.get(ref) or resolve_channel(str(ref), get)
            u = youtube_feed_url(channels[ref])
            sources.append((u, lambda u=u: parse_feed(get(u)), {}))
        except Exception as e:
            report.append(f"  ✗ {ref}  ({e})"[:140])
    for u in cfg.get("feeds") or []:
        sources.append((str(u), lambda u=str(u): parse_feed(get(u)), {}))
    for spec in cfg.get("people") or []:
        spec = {"name": spec} if isinstance(spec, str) else dict(spec)
        name = spec["name"]
        sources.append((f"youtube-search:{name}", lambda n=name: youtube_search(n, get), spec))

    for url, load, opts in sources:
        try:
            feed_title, entries = load()
        except Exception as e:
            report.append(f"  ✗ {url}  ({type(e).__name__}: {e})"[:160])
            continue
        first_time = url not in seen
        known = set(seen.get(url, []))
        for e in entries:
            if e["id"] in known or not e["url"]:
                continue
            known.add(e["id"])
            too_old = first_time and e["published"] and e["published"] < now() - NEW_FEED_LOOKBACK
            is_short = "/shorts/" in e["url"] or (e.get("seconds") is not None and e["seconds"] < 120)
            if too_old or (cfg.get("skip_shorts", True) and is_short):
                continue
            item = adapters.from_url(e["url"], via="feed", title=e["title"][:120] or None)
            item.source.update({"author": e["author"], "feed": feed_title or url,
                                "published": e["published"].isoformat() if e["published"] else None})
            item.source = {k: v for k, v in item.source.items() if v}
            item.tags = list(opts.get("tags") or cfg.get("tags") or [])
            priority = opts.get("priority", cfg.get("priority"))
            if priority and priority != "normal":
                item.extra["hints"] = {"priority": priority, "rule": "feeds.yaml"}
            if not dry_run:
                store.add(item)
            report.append(f"  capture  {item.icon} {e['author'][:25]}: {e['title'][:60]}")
        seen[url] = sorted(known)[-500:]

    if not dry_run and sources:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=1) + "\n")
    return report


def import_takeout(store: Store, csv_path: Path) -> int:
    """Add channels from Google Takeout's YouTube subscriptions.csv to feeds.yaml."""
    path = store.home / "feeds.yaml"
    cfg = load_config(store)
    have = set(map(str, cfg.get("youtube") or []))
    added = []
    with open(csv_path, newline="", encoding="utf-8") as fh:
        for row in csv.reader(fh):
            ids = [c for c in row if CHANNEL_ID.fullmatch(c.strip())]
            if ids and ids[0] not in have:
                title = next((c for c in row[1:] if c and not c.startswith("http") and c != ids[0]), "")
                added.append((ids[0], title))
                have.add(ids[0])
    if added:
        lines = path.read_text() if path.exists() else "youtube:\n"
        if "youtube:" not in lines:
            lines += "\nyoutube:\n"
        block = "".join(f'  - {cid}   # {title}\n' for cid, title in added)
        lines = lines.replace("youtube:\n", "youtube:\n" + block, 1)
        path.write_text(lines)
    return len(added)


def follow(store: Store, ref: str) -> str:
    """Add a YouTube channel (@handle / URL / id) or an RSS feed URL to feeds.yaml."""
    ref = ref.strip()
    path = store.home / "feeds.yaml"
    cfg = load_config(store)
    is_youtube = ref.startswith("@") or "youtube.com/" in ref or bool(CHANNEL_ID.fullmatch(ref))
    key = "youtube" if is_youtube else "feeds"
    if not is_youtube and not ref.startswith("http"):
        raise ValueError("send a YouTube channel (@name or link) or a feed URL")
    if ref in map(str, cfg.get(key) or []):
        return f"Already following {ref}"
    cfg[key] = list(cfg.get(key) or []) + [ref]
    text = path.read_text() if path.exists() else ""
    # keep the file's comments: rewrite only the list we changed
    new_block = f"{key}:\n" + "".join(f"  - {json.dumps(str(v), ensure_ascii=False)}\n" for v in cfg[key])
    pattern = re.compile(rf"(?ms)^{key}:.*?(?=^\S|\Z)")
    text = pattern.sub(lambda _: new_block, text, count=1) if pattern.search(text) else text + "\n" + new_block
    path.write_text(text)
    return f"Following {ref}. New {'videos' if is_youtube else 'entries'} will land in your inbox."
