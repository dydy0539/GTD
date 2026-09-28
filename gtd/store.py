"""File-based store: one folder per item, plus an append-only event log.

Layout under $GTD_HOME:
    stuff/YYYY/MM/<id>-<slug>/item.md
    stuff/YYYY/MM/<id>-<slug>/attachments/...
    events.jsonl
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Iterator

import yaml

from .adapters import SELF_AUTHORED, apply_priority_markers
from .model import Item, now

CONTENT_H = "## Content"
SUMMARY_H = "## Summary"


def default_home() -> Path:
    return Path(os.environ.get("GTD_HOME", Path.home() / "gtd-data")).expanduser()


class Store:
    def __init__(self, home: Path | str | None = None) -> None:
        self.home = Path(home) if home else default_home()
        self.stuff = self.home / "stuff"
        self.events_path = self.home / "events.jsonl"

    # ---------- write ----------
    def add(self, item: Item, files: list[Path] | None = None,
            blobs: dict[str, bytes] | None = None) -> tuple[Item, bool]:
        """Save a new item with attachments from disk (files) or memory (blobs).

        Returns (item, created). Duplicates are recaptured, not re-added.
        """
        if item.via in SELF_AUTHORED:
            apply_priority_markers(item)
        if item.content_hash:
            existing = self.find_by_hash(item.content_hash)
            if existing:
                self._recapture(existing, item.note)
                return existing, False

        folder = self._folder_for(item)
        folder.mkdir(parents=True, exist_ok=False)
        att = folder / "attachments"
        for f in files or []:
            att.mkdir(exist_ok=True)
            shutil.copy2(f, att / f.name)
            if f.name not in item.attachments:
                item.attachments.append(f.name)
        for name, data in (blobs or {}).items():
            att.mkdir(exist_ok=True)
            (att / Path(name).name).write_bytes(data)
            if name not in item.attachments:
                item.attachments.append(Path(name).name)
        self._write(folder, item)
        self.log("captured", item.id, channel=item.channel, via=item.via)
        return item, True

    def save(self, item: Item) -> None:
        """Rewrite an existing item (used by enrichers and later steps)."""
        self._write(self.path_of(item.id), item)

    def log(self, event: str, item_id: str, **data) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        rec = {"ts": now().isoformat(), "event": event, "id": item_id, **data}
        with self.events_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # ---------- read ----------
    def items(self, status: str | None = "inbox") -> Iterator[Item]:
        """All items, newest first, optionally filtered by status."""
        if not self.stuff.exists():
            return
        for md in sorted(self.stuff.glob("*/*/*/item.md"), reverse=True):
            item = self._read(md)
            if status is None or item.status == status:
                yield item

    def get(self, id_prefix: str) -> Item:
        matches = [p for p in self.stuff.glob(f"*/*/{id_prefix}*/item.md")]
        if len(matches) != 1:
            raise KeyError(f"{len(matches)} items match {id_prefix!r}")
        return self._read(matches[0])

    def path_of(self, item_id: str) -> Path:
        matches = list(self.stuff.glob(f"*/*/{item_id}-*"))
        if not matches:
            raise KeyError(item_id)
        return matches[0]

    def find_by_hash(self, content_hash: str) -> Item | None:
        return next(
            (i for i in self.items(status=None) if i.content_hash == content_hash), None
        )

    def events(self) -> list[dict]:
        if not self.events_path.exists():
            return []
        return [json.loads(l) for l in self.events_path.read_text().splitlines() if l]

    # ---------- internals ----------
    def _folder_for(self, item: Item) -> Path:
        ts = item.captured_at
        return self.stuff / f"{ts:%Y}" / f"{ts:%m}" / item.folder_name

    def _recapture(self, item: Item, note: str) -> None:
        if note and note not in item.note:
            item.note = f"{item.note}\n{note}".strip()
            self.save(item)
        self.log("recaptured", item.id, note=note or None)

    @staticmethod
    def _write(folder: Path, item: Item) -> None:
        fm = yaml.safe_dump(
            item.front_matter(), sort_keys=False, allow_unicode=True, width=100
        )
        body = f"---\n{fm}---\n\n# {item.title}\n\n{CONTENT_H}\n\n{item.content.strip()}\n"
        if item.summary:
            body += f"\n{SUMMARY_H}\n\n{item.summary.strip()}\n"
        (folder / "item.md").write_text(body, encoding="utf-8")

    @staticmethod
    def _read(md: Path) -> Item:
        text = md.read_text(encoding="utf-8")
        _, fm_text, body = text.split("---\n", 2)
        fm = yaml.safe_load(fm_text) or {}
        content, summary = body, ""
        if CONTENT_H in body:
            content = body.split(CONTENT_H, 1)[1]
        if SUMMARY_H in content:
            content, summary = content.split(SUMMARY_H, 1)
        return Item.from_parts(fm, content.strip(), summary.strip())
