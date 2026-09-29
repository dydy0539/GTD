"""Triage decisions: move items out of the in-tray (or back into it).

The In-tray page records each choice (item id → trash / later / reference /
inbox) in its own small database; `apply()` writes them into the items here,
so the repo stays the single source of truth. Items are never deleted:
"trash" is a status, and anything can be moved back.
"""
from __future__ import annotations

from .store import Store

DECISIONS = {
    "trash": "Trash",
    "later": "Review later",
    "reference": "Archive (reference)",
    "inbox": "Back to in-tray",
}


def project_tag(name: str) -> str:
    return "project:" + "-".join(name.lower().split())


def apply(store: Store, decisions) -> list[str]:
    """`decisions`: {id: "trash"} / {id: {"decision": "trash", "at": ...}} or a list of
    {"id": ..., "decision": ..., "project": ..., "note": ...}; a project adds a
    "project:<name>" tag, a note is appended. Unknown ids and values are reported, not fatal."""
    if isinstance(decisions, dict):
        decisions = [{"id": k, **(v if isinstance(v, dict) else {"decision": v})} for k, v in decisions.items()]
    report = []
    for d in decisions:
        item_id, choice = d.get("id", ""), d.get("decision", "")
        if choice not in DECISIONS:
            report.append(f"  ? {item_id}: unknown decision {choice!r}")
            continue
        try:
            item = store.get(item_id)
        except KeyError:
            report.append(f"  ? {item_id}: no such item")
            continue
        extra = {}
        if d.get("project") and project_tag(d["project"]) not in item.tags:
            item.tags = [*item.tags, project_tag(d["project"])]
            extra["project"] = d["project"]
        if d.get("note") and d["note"] not in item.note:
            item.note = f"{item.note}\n{d['note']}".strip()
            extra["note"] = d["note"]
        if item.status == choice and not extra:
            continue
        before, item.status = item.status, choice
        store.save(item)
        store.log("decided", item.id, decision=choice, previous=before, **extra,
                  **({"at": d["at"]} if d.get("at") else {}))
        report.append(f"  ✓ {DECISIONS[choice]:<20} {item.title}"[:120])
    return report
