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
    "someday": "Someday / maybe",
    "next": "Next action",
    "done": "Done",
    "inbox": "Back to in-tray",
}


def project_tag(name: str) -> str:
    return "project:" + "-".join(name.lower().split())


def apply(store: Store, decisions) -> list[str]:
    """`decisions`: {id: "trash"} / {id: {"decision": "trash", "at": ...}} or a list of
    {"id": ..., "decision": ..., "project": ..., "category": ..., "note": ..., "calendar": {...}};
    a category files an archived item (extra.category; "" clears it), a project adds a
    "project:<name>" tag, a note is appended, a calendar dict ({start, location, summary})
    changes the item's appointment. Unknown ids and values are reported, not fatal."""
    report = []
    if isinstance(decisions, dict):
        here = decisions.pop("_here", None)
        if here and here.get("timezone"):  # the page's record of your phone's time zone
            from .here import label, set_here, zone_for
            zone = zone_for(here["timezone"])
            if zone and set_here(store, zone, "page", here.get("at")):
                report.append(f"  ✓ 📍 now in {label(zone)} time ({zone})")
        for new in decisions.pop("_adds", None) or []:  # ideas typed straight into the page
            report += _add(store, new)
        decisions = [{"id": k, **(v if isinstance(v, dict) else {"decision": v})} for k, v in decisions.items()]
    for d in decisions:
        item_id, choice = d.get("id", ""), d.get("decision", "")
        if d.get("calendar"):
            report += _reschedule(store, item_id, d["calendar"])
            if not choice:
                continue
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
        if "category" in d and d["category"] != item.extra.get("category", ""):
            if d["category"]:
                item.extra["category"] = d["category"]
            else:
                item.extra.pop("category", None)
            extra["category"] = d["category"]
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


def _reschedule(store: Store, item_id: str, change: dict) -> list[str]:
    from .gcal import reschedule
    try:
        item = store.get(item_id)
    except KeyError:
        return [f"  ? {item_id}: no such item"]
    try:
        changed = reschedule(item, change.get("start"), change.get("location"), change.get("summary"))
    except (ValueError, TypeError) as e:
        return [f"  ? {item_id}: bad appointment change ({e})"]
    if not changed:
        return []
    store.save(item)
    cal = item.extra["calendar"]
    store.log("rescheduled", item.id, start=cal["start"], location=cal["location"])
    where = f" · {cal['location']}" if cal["location"] else ""
    return [f"  ✓ 📅 {cal['summary']} — {cal['start'].replace('T', ' ')}{where}"[:120]]


def _add(store: Store, new: dict) -> list[str]:
    from .adapters import from_text
    text, status = (new.get("text") or "").strip(), new.get("status") or "someday"
    if not text or status not in DECISIONS:
        return []
    item, created = store.add(from_text(text, via="page"))
    if item.status != status:
        item.status = status
        store.save(item)
    store.log("decided", item.id, decision=status, previous="new", **({"at": new["at"]} if new.get("at") else {}))
    return [f"  ✓ {DECISIONS[status]:<20} {item.title}"[:120]] if created else []
