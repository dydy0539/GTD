"""Put things with a time and a place on Google Calendar.

Only for things you captured yourself (Telegram, email to self, CLI, Claude).
Every such item gets a one-tap "Add to Google Calendar" link. With a service
account configured (GOOGLE_SERVICE_ACCOUNT_JSON + GOOGLE_CALENDAR_ID) the event
is created directly; the item records the event so it is never added twice.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta
from urllib.parse import quote, urlencode
from zoneinfo import ZoneInfo

from .adapters import SELF_AUTHORED
from .model import Item
from .store import Store
from .when import find, guess_timezone

DEFAULT_MINUTES = 60


def default_timezone() -> str:
    return os.environ.get("GTD_TIMEZONE") or os.environ.get("TZ") or "UTC"


def event_for(item: Item, default_tz: str | None = None) -> dict | None:
    text = "\n".join(filter(None, [item.note, item.content]))
    sent = item.source.get("sent_at")
    ref = datetime.fromisoformat(sent) if sent else item.captured_at
    tz = default_tz or default_timezone()
    # Resolve "Wednesday 2:15pm" against the moment you sent it, in the event's own time zone
    probe = find(text, ref.astimezone(ZoneInfo(tz)).replace(tzinfo=None))
    if not probe:
        return None
    tz = guess_timezone(probe.location, tz)
    found = find(text, ref.astimezone(ZoneInfo(tz)).replace(tzinfo=None))
    rest = found.rest.replace("@", "with ", 1) if found.rest.startswith("@") else found.rest
    place = found.location.split(",")[0].strip()
    summary = " · ".join(filter(None, [rest.splitlines()[0][:60] if rest else "", place])) or "Appointment"
    return {
        "summary": summary,
        "location": found.location,
        "start": found.start.isoformat(timespec="minutes"),
        "end": (found.start + timedelta(minutes=DEFAULT_MINUTES)).isoformat(timespec="minutes"),
        "timezone": tz,
        "description": f"{item.content}\n\n(captured in GTD inbox: {item.id})",
    }


def add_link(event: dict) -> str:
    fmt = lambda s: datetime.fromisoformat(s).strftime("%Y%m%dT%H%M%S")  # noqa: E731
    return "https://calendar.google.com/calendar/render?" + urlencode({
        "action": "TEMPLATE", "text": event["summary"],
        "dates": f"{fmt(event['start'])}/{fmt(event['end'])}", "ctz": event["timezone"],
        "location": event["location"], "details": event["description"],
    })


class GoogleCalendar:
    """Service-account access to one calendar (shared with the service account)."""

    def __init__(self, service_account_info: dict, calendar_id: str) -> None:
        from google.auth.transport.requests import AuthorizedSession
        from google.oauth2 import service_account

        creds = service_account.Credentials.from_service_account_info(
            service_account_info, scopes=["https://www.googleapis.com/auth/calendar.events"])
        self.session = AuthorizedSession(creds)
        self.url = f"https://www.googleapis.com/calendar/v3/calendars/{quote(calendar_id, safe='')}/events"

    def insert(self, event_id: str, event: dict) -> dict:
        body = {
            "id": event_id,
            "summary": event["summary"], "location": event["location"],
            "description": event["description"],
            "start": {"dateTime": event["start"] + ":00", "timeZone": event["timezone"]},
            "end": {"dateTime": event["end"] + ":00", "timeZone": event["timezone"]},
        }
        resp = self.session.post(self.url, json=body)
        if resp.status_code == 409:  # already created on an earlier run
            return self.session.get(f"{self.url}/{event_id}").json()
        resp.raise_for_status()
        return resp.json()

    @classmethod
    def from_env(cls) -> "GoogleCalendar | None":
        info = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
        calendar_id = os.environ.get("GOOGLE_CALENDAR_ID", "").strip()
        if not (info and calendar_id):
            return None
        return cls(json.loads(info), calendar_id)


def event_id_for(item: Item) -> str:
    # Google allows [a-v0-9]; hex digits are a subset. Stable per item → no duplicates.
    return "gtd" + hashlib.sha1(item.id.encode()).hexdigest()


def schedule(store: Store, calendar: "GoogleCalendar | None" = None) -> list[str]:
    report = []
    for item in store.items():
        cal = item.extra.get("calendar")
        if item.via not in SELF_AUTHORED or (cal and cal.get("status") == "added"):
            continue
        event = cal or event_for(item)
        if not event:
            continue
        event = {k: event[k] for k in ("summary", "location", "start", "end", "timezone", "description")}
        record = {**event, "add_link": add_link(event), "status": "proposed"}
        if calendar:
            try:
                created = calendar.insert(event_id_for(item), event)
                record.update(status="added", event_id=created.get("id"), html_link=created.get("htmlLink"))
            except Exception as e:  # keep the proposal + link; retried next run
                report.append(f"  ✗ 📅 {event['summary']}  ({type(e).__name__})")
        if record != cal:
            item.extra["calendar"] = record
            store.save(item)
            store.log("scheduled", item.id, status=record["status"], start=event["start"])
            verb = "added to calendar" if record["status"] == "added" else "calendar link ready"
            report.append(f"  ✓ 📅 {event['summary']} — {event['start'].replace('T', ' ')} ({verb})")
    return report
