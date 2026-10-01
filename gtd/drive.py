"""The In-tray page without a Claude session: data and taps travel through Google Drive.

The page (a claude.ai artifact) reads its data from one JSON file in your Drive, and
writes a snapshot of its not-yet-applied taps (decisions, appointment edits, typed ideas,
your time zone, projects) as a new file in an outbox folder. The scheduled job (`gtd run`)
applies the newest snapshot (`pull`) and writes fresh page data back (`push`); the page
then clears what was applied and trashes the outbox files that were read.

drive.json in the data repo names the two Drive objects: {"page": "<file id>",
"outbox": "<folder id>"}. Access is a Google service account
(GOOGLE_SERVICE_ACCOUNT_JSON) that the "GTD assistant" folder is shared with as Editor.
"""
from __future__ import annotations

import hashlib
import json
import os

from .store import Store

API = "https://www.googleapis.com/drive/v3/files"
UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"
KEEP_APPLIED = 400  # remembered tap keys, so a re-read snapshot never applies anything twice


class Drive:
    """Service-account access to the files shared with it."""

    def __init__(self, service_account_info: dict, session=None) -> None:
        if session is None:
            from google.auth.transport.requests import AuthorizedSession
            from google.oauth2 import service_account

            creds = service_account.Credentials.from_service_account_info(
                service_account_info, scopes=["https://www.googleapis.com/auth/drive"])
            session = AuthorizedSession(creds)
        self.session = session

    def list_folder(self, folder_id: str) -> list[dict]:
        """Files in a folder, newest first."""
        resp = self.session.get(API, params={
            "q": f"'{folder_id}' in parents and trashed = false", "orderBy": "createdTime desc",
            "fields": "files(id,name,createdTime)", "pageSize": 100})
        resp.raise_for_status()
        return resp.json().get("files", [])

    def download(self, file_id: str) -> bytes:
        resp = self.session.get(f"{API}/{file_id}", params={"alt": "media"})
        resp.raise_for_status()
        return resp.content

    def upload(self, file_id: str, data: bytes) -> None:
        """Replace a file's content (the file stays owned by you; a service account owns no files)."""
        resp = self.session.patch(f"{UPLOAD}/{file_id}", params={"uploadType": "media"}, data=data,
                                  headers={"Content-Type": "application/json; charset=utf-8"})
        resp.raise_for_status()

    @classmethod
    def from_env(cls) -> "Drive | None":
        info = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
        return cls(json.loads(info)) if info else None


def config(store: Store) -> dict | None:
    path = store.home / "drive.json"
    if not path.exists():
        return None
    cfg = json.loads(path.read_text(encoding="utf-8"))
    return cfg if cfg.get("page") and cfg.get("outbox") else None


def _state_path(store: Store):
    return store.home / "state" / "drive.json"


def load_state(store: Store) -> dict:
    path = _state_path(store)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save_state(store: Store, state: dict) -> None:
    path = _state_path(store)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(state, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    if not path.exists() or path.read_text(encoding="utf-8") != text:
        path.write_text(text, encoding="utf-8")


def to_decisions(snapshot: dict, applied: set[str]) -> tuple[dict, list[str]]:
    """An outbox snapshot → the decisions `decide.apply` takes, skipping taps already applied.

    Returns (decisions, keys); a key names one tap ("decisions/<id>@<at>", "edits/<id>@<at>",
    "adds/<doc id>") so the page knows which of its records it can clear."""
    decisions: dict = {}
    keys: list[str] = []
    for item_id, v in (snapshot.get("decisions") or {}).items():
        key = f"decisions/{item_id}@{v.get('at', '')}"
        if not v.get("decision") or key in applied:
            continue
        decisions[item_id] = {k: v[k] for k in ("decision", "project", "category", "waiting_on", "at") if k in v}
        keys.append(key)
    for item_id, v in (snapshot.get("edits") or {}).items():
        key = f"edits/{item_id}@{v.get('at', '')}"
        if not v.get("start") or key in applied:
            continue
        decisions.setdefault(item_id, {})["calendar"] = {k: v[k] for k in ("start", "location", "summary") if k in v}
        keys.append(key)
    adds = []
    for doc_id, v in (snapshot.get("adds") or {}).items():
        key = f"adds/{doc_id}"
        if not v.get("text") or key in applied:
            continue
        adds.append({k: v[k] for k in ("text", "status", "waiting_on", "at") if k in v})
        keys.append(key)
    if adds:
        decisions["_adds"] = adds
    here = snapshot.get("here") or {}
    if here.get("timezone"):
        decisions["_here"] = {"timezone": here["timezone"], "at": here.get("at", "")}
    return decisions, keys


def pull(store: Store, drive: Drive, cfg: dict) -> list[str]:
    """Apply the newest outbox snapshot from the page. The older ones are superseded by it."""
    from .decide import apply

    state = load_state(store)
    files = drive.list_folder(cfg["outbox"])
    if not files:
        return ["outbox empty"]
    state["outbox_done"] = [f["id"] for f in files]  # the page trashes these once it sees them here
    raw = drive.download(files[0]["id"])
    sha = hashlib.sha256(raw).hexdigest()
    if sha == state.get("outbox_sha"):
        save_state(store, state)
        return ["no new taps"]
    snapshot = json.loads(raw.decode("utf-8"))
    applied = state.get("applied") or []
    decisions, keys = to_decisions(snapshot, set(applied))
    report = apply(store, decisions) if decisions else []
    if "projects" in snapshot:  # the page sends all projects, so missing ones were deleted
        report += save_projects(store, {"projects": snapshot.get("projects") or {}, "logs": snapshot.get("logs") or {}},
                                full=True)
    state["applied"] = (applied + keys)[-KEEP_APPLIED:]
    state["outbox_sha"] = sha
    save_state(store, state)
    return report or ["nothing new to apply"]


def save_projects(store: Store, data: dict, full: bool = False) -> list[str]:
    """Back up the Projects page into projects.json; `full` = data holds every project (drop the rest)."""
    path = store.home / "projects.json"
    old = json.loads(path.read_text()) if path.exists() else {"projects": {}, "logs": {}}
    projects, logs = data.get("projects") or {}, data.get("logs") or {}
    merged = {"projects": {**({} if full else old.get("projects", {})), **projects},
              "logs": {**old.get("logs", {}), **logs}}
    for pid in data.get("deleted") or []:
        merged["projects"].pop(pid, None)
    text = json.dumps(merged, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    if path.exists() and path.read_text() == text:
        return []
    path.write_text(text, encoding="utf-8")
    store.log("projects", "-", projects=len(merged["projects"]), logs=len(merged["logs"]))
    return [f"  ✓ projects backed up: {len(merged['projects'])} project(s), {len(merged['logs'])} session(s)"]


def page_data(store: Store, cfg: dict) -> dict:
    """What the page shows, plus what it needs to tidy up after the job."""
    from . import site
    from .here import current, get

    kept = [i for i in store.items(status=None) if i.status in site.SHOWN]
    here = current(store) if get(store) else ""
    state = load_state(store)
    return {**site.data(kept, here=here), "drive": {"page": cfg["page"], "outbox": cfg["outbox"]},
            "applied": state.get("applied") or [], "outbox_sha": state.get("outbox_sha", ""),
            "outbox_done": state.get("outbox_done") or []}


def push(store: Store, drive: Drive, cfg: dict) -> list[str]:
    """Write the page data to Drive (skipped when nothing but the time changed)."""
    data = page_data(store, cfg)
    digest = hashlib.sha256(json.dumps({k: v for k, v in data.items() if k != "generated"},
                                       sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    state = load_state(store)
    if digest == state.get("page_sha"):
        return ["page data unchanged"]
    drive.upload(cfg["page"], json.dumps(data, ensure_ascii=False).encode("utf-8"))
    state["page_sha"] = digest
    save_state(store, state)
    return [f"page data written ({sum(1 for i in data['items'] if i['status'] == 'inbox')} in the in-tray)"]
