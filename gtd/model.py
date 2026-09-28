"""The single data model: an Item in the stuff inbox."""
from __future__ import annotations

import re
import secrets
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

CHANNELS = {
    "text": "✏️",
    "chat": "💬",
    "url": "🔗",
    "youtube": "▶️",
    "podcast": "🎧",
    "twitter": "🐦",
    "email": "📧",
    "image": "🖼️",
    "audio": "🎙️",
    "file": "📎",
    "message": "💭",
}


def now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def new_id(ts: datetime | None = None) -> str:
    """Time-sortable, human-readable, collision-resistant id: 20260928T143012-7f3a."""
    ts = ts or now()
    return f"{ts.strftime('%Y%m%dT%H%M%S')}-{secrets.token_hex(2)}"


def slugify(text: str, max_len: int = 40) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text[:max_len].rstrip("-") or "item"


@dataclass
class Item:
    channel: str
    title: str
    content: str = ""
    via: str = "cli"
    source: dict[str, Any] = field(default_factory=dict)
    note: str = ""
    tags: list[str] = field(default_factory=list)
    content_hash: str = ""
    attachments: list[str] = field(default_factory=list)
    status: str = "inbox"
    enrichment: str = "pending"
    summary: str = ""
    id: str = ""
    captured_at: datetime = field(default_factory=now)
    # Fields owned by later steps (decision engine etc.) are preserved untouched.
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.id:
            self.id = new_id(self.captured_at)

    @property
    def icon(self) -> str:
        return CHANNELS.get(self.channel, "•")

    @property
    def folder_name(self) -> str:
        return f"{self.id}-{slugify(self.title)}"

    def front_matter(self) -> dict[str, Any]:
        fm: dict[str, Any] = {
            "id": self.id,
            "captured_at": self.captured_at.isoformat(),
            "channel": self.channel,
            "via": self.via,
            "title": self.title,
            "source": self.source,
            "note": self.note,
            "tags": self.tags,
            "content_hash": self.content_hash,
            "attachments": self.attachments,
            "status": self.status,
            "enrichment": self.enrichment,
        }
        fm.update(self.extra)
        return fm

    @classmethod
    def from_parts(cls, fm: dict[str, Any], content: str, summary: str) -> "Item":
        fm = dict(fm)
        known = {
            k: fm.pop(k)
            for k in list(fm)
            if k in cls.__dataclass_fields__ and k not in ("extra", "content", "summary")
        }
        captured = known.pop("captured_at", None)
        if isinstance(captured, str):
            captured = datetime.fromisoformat(captured)
        return cls(
            **known,
            captured_at=captured or now(),
            content=content,
            summary=summary,
            extra=fm,
        )
