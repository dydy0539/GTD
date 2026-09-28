"""Capture rules: decide which incoming email becomes stuff, and attach hints.

This is a *capture-time* filter, not the Step 2 decision engine. It only
answers "does this enter the inbox?" and adds hints (priority, area, tags)
that the decision engine can use later. Rules live in $GTD_HOME/rules.yaml:

    me: [you@gmail.com]                 # your own addresses
    capture_address: you+gtd@gmail.com  # "email to self" funnel, always captured
    default: skip                       # mail no rule matches: skip | capture
    gmail_write: false                  # true = allow adding Gmail labels
    rules:                              # first match wins, top to bottom
      - name: Boss
        when: {from: boss@work.com}
        then: {priority: high, area: work}
      - name: Newsletters
        when: {newsletter: true}
        then: {action: skip, gmail_label: Newsletters}

`when` conditions are ANDed. A string value matches case-insensitively as a
substring; "/regex/" matches as a regular expression; a list matches if any
entry does; true/false compares booleans.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from email.utils import getaddresses
from pathlib import Path
from typing import Any

import yaml

from .model import Item

CONDITIONS = {
    "from": lambda i: i.source.get("from", ""),
    "to": lambda i: f"{i.source.get('to', '')}, {i.source.get('cc', '')}",
    "subject": lambda i: i.source.get("subject", i.title),
    "body": lambda i: i.content,
    "text": lambda i: f"{i.title}\n{i.content}\n{i.note}",
    "domain": lambda i: _sender(i).rpartition("@")[2],
    "channel": lambda i: i.channel,
    "newsletter": lambda i: bool(i.source.get("newsletter")),
    "has_attachment": lambda i: bool(i.source.get("email_attachments")),
    "label": lambda i: " ".join(i.source.get("gmail_labels", [])),
}
ACTIONS = {"action", "priority", "area", "tags", "gmail_label"}


def _sender(item: Item) -> str:
    addrs = getaddresses([item.source.get("from", "")])
    return addrs[0][1].lower() if addrs else ""


def _matches(spec: Any, value: Any) -> bool:
    if isinstance(spec, list):
        return any(_matches(s, value) for s in spec)
    if isinstance(spec, bool) or isinstance(value, bool):
        return bool(value) == spec
    spec, value = str(spec), str(value)
    if len(spec) > 2 and spec.startswith("/") and spec.endswith("/"):
        return re.search(spec[1:-1], value, re.IGNORECASE) is not None
    return spec.lower() in value.lower()


@dataclass
class Decision:
    action: str  # capture | skip | self-capture
    rule: str
    priority: str | None = None
    area: str | None = None
    tags: list[str] = field(default_factory=list)
    gmail_label: str | None = None

    def apply_hints(self, item: Item) -> None:
        hints = {k: v for k, v in (("priority", self.priority), ("area", self.area)) if v}
        if hints:
            item.extra["hints"] = {**hints, "rule": self.rule}
        item.tags = sorted(set(item.tags) | set(self.tags))


class Rules:
    def __init__(self, cfg: dict | None = None) -> None:
        cfg = cfg or {}
        me = cfg.get("me") or os.environ.get("GMAIL_ADDRESS", "")
        self.me = [m.lower() for m in ([me] if isinstance(me, str) else me) if m]
        self.capture_address = (cfg.get("capture_address") or self._default_capture()).lower()
        self.default = cfg.get("default", "skip")
        # Never change anything in Gmail unless explicitly allowed
        self.gmail_write = bool(cfg.get("gmail_write", False))
        self.rules = cfg.get("rules") or []
        for r in self.rules:
            bad = (set(r.get("when", {})) - set(CONDITIONS)) | (set(r.get("then", {})) - ACTIONS)
            if bad:
                raise ValueError(f"rule {r.get('name')!r}: unknown key(s) {sorted(bad)}")

    def _default_capture(self) -> str:
        if not self.me:
            return ""
        user, _, domain = self.me[0].partition("@")
        return f"{user}+gtd@{domain}"

    @classmethod
    def load(cls, path: Path) -> "Rules":
        return cls(yaml.safe_load(path.read_text()) if path.exists() else {})

    def decide(self, item: Item) -> Decision:
        if self.capture_address and self.capture_address in CONDITIONS["to"](item).lower():
            return Decision("self-capture", "sent to capture address")
        if _sender(item) in self.me:
            return Decision("skip", "sent by me")
        for r in self.rules:
            when = r.get("when", {})
            if all(_matches(spec, CONDITIONS[k](item)) for k, spec in when.items()):
                then = dict(r.get("then", {}))
                tags = then.get("tags", [])
                return Decision(
                    action=then.get("action", "capture"),
                    rule=r.get("name", "unnamed rule"),
                    priority=then.get("priority"),
                    area=then.get("area"),
                    tags=[tags] if isinstance(tags, str) else list(tags),
                    gmail_label=then.get("gmail_label"),
                )
        return Decision(self.default, "default")
