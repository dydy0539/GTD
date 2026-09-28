"""Telegram funnel: a private bot you share things to.

No server: the scheduled job calls getUpdates (Telegram keeps undelivered
messages for 24 hours), captures them, and replies "✓ Captured" in the chat.
The first person to message the bot becomes its owner (saved in
$GTD_HOME/state/telegram.json); anyone else is refused.

    text / dictation         → text item
    a link (+ comment)       → url / youtube / twitter / podcast item, comment = note
    photo, voice, audio,
    video, document          → image / audio / file item, caption = note
    forwarded message        → message item that keeps who wrote it
"""
from __future__ import annotations

import json
import mimetypes
import os
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.request import Request, urlopen

from . import adapters
from .gcal import add_link, event_for
from .model import Item
from .store import Store

API = "https://api.telegram.org"
MAX_DOWNLOAD = 20 * 1024 * 1024  # bot API download limit
MEDIA = {  # message key → (channel, default extension)
    "photo": ("image", ".jpg"),
    "voice": ("audio", ".ogg"),
    "audio": ("audio", ".mp3"),
    "video_note": ("file", ".mp4"),
    "video": ("file", ".mp4"),
    "document": ("file", ""),
}
HELP = ("Send me anything — text, links, screenshots, voice notes, or forward messages — "
        "and it lands in your GTD inbox within ~30 minutes.")


class TelegramAPI:
    def __init__(self, token: str, http: Callable[[str, bytes | None], bytes] | None = None) -> None:
        self.token = token
        self.http = http or self._http

    @staticmethod
    def _http(url: str, body: bytes | None) -> bytes:
        req = Request(url, data=body, headers={"Content-Type": "application/json"} if body else {})
        with urlopen(req, timeout=30) as resp:
            return resp.read(MAX_DOWNLOAD + 1)

    def call(self, method: str, **params: Any) -> Any:
        raw = self.http(f"{API}/bot{self.token}/{method}", json.dumps(params).encode())
        data = json.loads(raw)
        if not data.get("ok"):
            raise RuntimeError(f"Telegram {method}: {data.get('description')}")
        return data["result"]

    def download(self, file_id: str) -> bytes:
        path = self.call("getFile", file_id=file_id)["file_path"]
        return self.http(f"{API}/file/bot{self.token}/{path}", None)

    def reply(self, chat_id: int, text: str) -> None:
        try:
            self.call("sendMessage", chat_id=chat_id, text=text, disable_notification=True,
                      link_preview_options={"is_disabled": True})
        except Exception:
            pass  # a failed confirmation must never lose a capture


def _forwarded_from(msg: dict) -> str:
    origin = msg.get("forward_origin") or {}
    kind = origin.get("type")
    if kind == "user":
        u = origin["sender_user"]
        return " ".join(filter(None, [u.get("first_name"), u.get("last_name")]))
    if kind == "hidden_user":
        return origin.get("sender_user_name", "")
    if kind in ("chat", "channel"):
        chat = origin.get("sender_chat") or origin.get("chat") or {}
        return chat.get("title", "")
    return ""


def message_to_items(msg: dict, api: TelegramAPI) -> list[tuple[Item, dict[str, bytes]]]:
    text = msg.get("text") or ""
    note = msg.get("caption") or ""
    forwarded = _forwarded_from(msg)
    source = {"telegram_message_id": msg["message_id"],
              "sent_at": datetime.fromtimestamp(msg["date"], timezone.utc).isoformat()}
    if forwarded:
        source["forwarded_from"] = forwarded

    for key, (channel, ext) in MEDIA.items():
        if key not in msg:
            continue
        media = msg[key][-1] if key == "photo" else msg[key]  # photo: largest size is last
        name = media.get("file_name") or f"telegram-{msg['message_id']}{ext}"
        mime = media.get("mime_type") or mimetypes.guess_type(name)[0] or "application/octet-stream"
        if key == "document":
            channel = {"image": "image", "audio": "audio"}.get(mime.split("/")[0], "file")
        if media.get("file_size", 0) > MAX_DOWNLOAD:
            item = adapters.from_text(f"[{key} too large for the bot to download: {name}]\n{note}",
                                      via="telegram", title=note or name)
            item.source.update(source)
            return [(item, {})]
        data = api.download(media["file_id"])
        item = Item(channel=channel, title=note.splitlines()[0][:80] if note else name,
                    content=f"[{mime}] see attachments/{name}", via="telegram", note=note,
                    source={**source, "filename": name, "mime": mime},
                    content_hash=adapters.sha256(data), enrichment="pending")
        return [(item, {name: data})]

    if not text:
        return []
    if forwarded:
        item = adapters.from_text(text, via="telegram", channel="message",
                                  title=f"{forwarded}: {adapters.first_line(text, 70)}")
        item.source.update(source)
        return [(item, {})]
    urls = adapters.URL_RE.findall(text)
    if len(urls) == 1:
        item = adapters.from_url(urls[0], via="telegram", note=text.replace(urls[0], "").strip())
    else:
        item = adapters.from_text(text, via="telegram")
    item.source.update(source)
    return [(item, {})]


def _state_path(store: Store):
    return store.home / "state" / "telegram.json"


def sync(store: Store, api: TelegramAPI, *, dry_run: bool = False) -> list[str]:
    path = _state_path(store)
    state = json.loads(path.read_text()) if path.exists() else {}
    offset, owner = state.get("offset", 0), state.get("owner_id")
    report = []

    for update in api.call("getUpdates", offset=offset, timeout=0, allowed_updates=["message"]):
        offset = update["update_id"] + 1
        msg = update.get("message")
        if not msg or msg["chat"].get("type") != "private":
            continue
        sender = msg["from"]["id"]
        if owner is None:
            owner = sender
            if not dry_run:
                api.reply(msg["chat"]["id"], "This bot is now linked to you. " + HELP)
        if sender != owner:
            report.append(f"  refused  message from user {sender} (not the owner)")
            if not dry_run:
                api.reply(msg["chat"]["id"], "Sorry, this is a private inbox.")
            continue
        if (msg.get("text") or "").startswith("/"):
            if not dry_run:
                api.reply(msg["chat"]["id"], HELP)
            continue
        for item, blobs in message_to_items(msg, api):
            if not dry_run:
                item, created = store.add(item, blobs=blobs)
                text = (f"✓ Captured: {item.title}" if created
                        else f"↺ Already in your inbox: {item.title}")
                event = event_for(item) if created else None
                if event:
                    when_ = datetime.fromisoformat(event["start"]).strftime("%a %d %b %H:%M")
                    text += f"\n📅 {when_} · {event['location'][:60]}\nAdd to calendar: {add_link(event)}"
                api.reply(msg["chat"]["id"], text)
            report.append(f"  capture  {item.icon} {item.title[:60]}")

    if not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"offset": offset, "owner_id": owner}) + "\n")
        if offset:  # confirm the processed updates so Telegram stops re-sending them
            api.call("getUpdates", offset=offset, timeout=0, limit=1)
    return report


def token_from_env() -> str:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("set TELEGRAM_BOT_TOKEN")
    return token
