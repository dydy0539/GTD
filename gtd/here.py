"""Where you are right now, as a time zone — so "Friday 3pm" means your local 3pm.

Signals, newest wins:
  - the In-tray page records your phone's time zone each time you open it
  - an email to yourself carries your phone's UTC offset (+09:00 → Japan, +08:00 → Singapore)
  - the Telegram bot: /here tokyo, /here singapore, or share your location
Stored in state/here.json; without any signal the GTD_TIMEZONE / TZ setting is used.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .store import Store

PLACES = {
    "Asia/Tokyo": ["japan", "tokyo", "osaka", "kyoto", "jp", "日本", "東京", "大阪"],
    "Asia/Singapore": ["singapore", "sg", "sgp", "新加坡"],
    "Asia/Hong_Kong": ["hong kong", "hongkong", "hk", "香港"],
}
OFFSETS = {timedelta(hours=9): "Asia/Tokyo", timedelta(hours=8): "Asia/Singapore"}
BOXES = [  # (south, north, west, east) → zone, small places first
    ((1.15, 1.48, 103.6, 104.1), "Asia/Singapore"),
    ((22.15, 22.57, 113.8, 114.45), "Asia/Hong_Kong"),
    ((24.0, 45.6, 122.9, 153.99), "Asia/Tokyo"),
]


def _path(store: Store):
    return store.home / "state" / "here.json"


def zone_for(text: str) -> str | None:
    """'tokyo' / 'Singapore' / 'Asia/Tokyo' → an IANA zone, or None."""
    t = text.strip().lower()
    if not t:
        return None
    for zone, words in PLACES.items():
        if t in words or any(w in t for w in words if len(w) > 3):
            return zone
    try:
        ZoneInfo(text.strip())
        return text.strip()
    except (KeyError, ValueError):
        return None


def zone_for_offset(sent_at: str) -> str | None:
    try:
        offset = datetime.fromisoformat(sent_at).utcoffset()
    except (TypeError, ValueError):
        return None
    return OFFSETS.get(offset)


def zone_for_coords(lat: float, lon: float) -> str | None:
    for (s, n, w, e), zone in BOXES:
        if s <= lat <= n and w <= lon <= e:
            return zone
    return None


def get(store: Store) -> dict:
    path = _path(store)
    return json.loads(path.read_text()) if path.exists() else {}


def current(store: Store) -> str:
    from .gcal import default_timezone
    zone = get(store).get("timezone")
    return zone if zone and zone_for(zone) else default_timezone()


def set_here(store: Store, zone: str, source: str, at: str | None = None) -> bool:
    """Record a signal; an older signal never overrides a newer one. True if the zone changed."""
    at = at or datetime.now(timezone.utc).isoformat()
    state = get(store)
    try:
        if state.get("since") and datetime.fromisoformat(at) < datetime.fromisoformat(state["since"]):
            return False
    except ValueError:
        pass
    changed = state.get("timezone") != zone
    path = _path(store)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"timezone": zone, "since": at, "source": source}) + "\n")
    if changed:
        store.log("here", "-", timezone=zone, source=source)
    return changed


def label(zone: str) -> str:
    return zone.split("/")[-1].replace("_", " ")
