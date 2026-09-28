"""Gmail funnel: pull new mail over IMAP, run capture rules, add to the inbox.

Uses Gmail's IMAP extensions (X-GM-RAW search, X-GM-LABELS) with an app
password, so it needs only the standard library, not a Google Cloud project.
Mail is read with BODY.PEEK so nothing gets marked as read. Captured messages
get the Gmail label "GTD/Captured" so you can see in Gmail what went in.

Progress is tracked by IMAP UID in $GTD_HOME/state/gmail.json.
"""
from __future__ import annotations

import imaplib
import json
import re
from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import quote

from . import adapters
from .rules import Rules
from .store import Store

CAPTURED_LABEL = "GTD/Captured"


@dataclass
class Mail:
    uid: int
    raw: bytes
    labels: list[str] = field(default_factory=list)
    thread_id: str = ""


class Mailbox(Protocol):
    uidvalidity: int

    def fetch_new(self, after_uid: int, since_days: int) -> list[Mail]: ...
    def add_label(self, uid: int, label: str) -> None: ...


_LABEL_TOKEN = re.compile(r'"((?:[^"\\]|\\.)*)"|([^\s()]+)')


def parse_fetch_meta(meta: str) -> tuple[list[str], str]:
    labels_m = re.search(r"X-GM-LABELS \((.*?)\)(?: |$)", meta)
    labels = []
    if labels_m:
        for quoted, bare in _LABEL_TOKEN.findall(labels_m.group(1)):
            labels.append((quoted or bare).replace('\\"', '"').replace("\\\\", "\\"))
    thrid = re.search(r"X-GM-THRID (\d+)", meta)
    return labels, thrid.group(1) if thrid else ""


class GmailIMAP:
    """Real mailbox. Searches "All Mail" so filters that skip the inbox still work."""

    def __init__(self, address: str, app_password: str, host: str = "imap.gmail.com") -> None:
        self.imap = imaplib.IMAP4_SSL(host)
        self.imap.login(address, app_password.replace(" ", ""))
        self.imap.select(f'"{self._all_mail()}"')
        self.uidvalidity = int(self.imap.response("UIDVALIDITY")[1][0])
        self._labels_created: set[str] = set()

    def _all_mail(self) -> str:
        _, rows = self.imap.list()
        for row in rows:
            line = row.decode(errors="replace")
            if "\\All" in line:
                return line.rsplit(' "/" ', 1)[-1].strip().strip('"')
        return "[Gmail]/All Mail"

    def fetch_new(self, after_uid: int, since_days: int) -> list[Mail]:
        _, data = self.imap.uid("SEARCH", "X-GM-RAW", f'"newer_than:{since_days}d"')
        uids = sorted(int(u) for u in data[0].split() if int(u) > after_uid)
        mails = []
        for uid in uids:
            _, resp = self.imap.uid("FETCH", str(uid), "(X-GM-LABELS X-GM-THRID BODY.PEEK[])")
            parts = [r for r in resp if isinstance(r, tuple)]
            if not parts:
                continue
            tail = b" ".join(r for r in resp if isinstance(r, bytes))
            meta = (parts[0][0] + b" " + tail).decode(errors="replace")
            labels, thrid = parse_fetch_meta(meta)
            mails.append(Mail(uid, parts[0][1], labels, thrid))
        return mails

    def add_label(self, uid: int, label: str) -> None:
        if label not in self._labels_created:
            self.imap.create(f'"{label}"')  # fails harmlessly if it exists
            self._labels_created.add(label)
        self.imap.uid("STORE", str(uid), "+X-GM-LABELS", f'("{label}")')

    def close(self) -> None:
        try:
            self.imap.logout()
        except (imaplib.IMAP4.error, OSError):
            pass


def _state_path(store: Store):
    return store.home / "state" / "gmail.json"


def sync(store: Store, rules: Rules, mailbox: Mailbox, *, dry_run: bool = False,
         since_days: int = 2) -> list[str]:
    """Process new mail. Returns one human-readable report line per message."""
    path = _state_path(store)
    state = json.loads(path.read_text()) if path.exists() else {}
    after = state.get("last_uid", 0) if state.get("uidvalidity") == mailbox.uidvalidity else 0
    report, last_uid = [], after

    for mail in mailbox.fetch_new(after, since_days):
        last_uid = max(last_uid, mail.uid)
        item = adapters.from_eml(mail.raw, via="gmail")
        item.source["gmail_labels"] = mail.labels
        decision = rules.decide(item)
        subject = item.title[:60]

        if decision.action == "skip":
            report.append(f"  skip     {subject}  ({decision.rule})")
        elif decision.action == "self-capture":
            entries = adapters.from_self_email(mail.raw)
            for new, blobs in entries:
                if not dry_run:
                    new, _ = store.add(new, blobs=blobs)
                report.append(f"  capture  {new.icon} {new.title[:60]}  (email to self)")
        else:
            decision.apply_hints(item)
            if item.source.get("message_id"):
                item.source["link"] = (
                    "https://mail.google.com/mail/u/0/#search/rfc822msgid%3A"
                    + quote(item.source["message_id"], safe="")
                )
            if not dry_run:
                store.add(item)
            flag = " ❗" if decision.priority == "high" else ""
            report.append(f"  capture  {item.icon} {subject}{flag}  ({decision.rule})")

        if not dry_run:
            if decision.action != "skip":
                mailbox.add_label(mail.uid, CAPTURED_LABEL)
            if decision.gmail_label:
                mailbox.add_label(mail.uid, decision.gmail_label)

    if not dry_run and last_uid:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"uidvalidity": mailbox.uidvalidity, "last_uid": last_uid}) + "\n")
    return report
