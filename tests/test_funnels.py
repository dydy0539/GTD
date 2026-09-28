import subprocess
import tempfile
import unittest
from email.message import EmailMessage
from pathlib import Path

from gtd import adapters, datarepo
from gtd.gmail import Mail, parse_fetch_meta, sync
from gtd.rules import Rules
from gtd.model import Item
from gtd.store import Store

ME = "me@gmail.com"
CAPTURE = "me+gtd@gmail.com"


def mail(frm, to, subject, body="", *, attach=None, newsletter=False, msgid=None) -> bytes:
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = frm, to, subject
    m["Message-ID"] = f"<{msgid or abs(hash((frm, subject, body)))}@test>"
    if newsletter:
        m["List-Unsubscribe"] = "<mailto:unsub@news.com>"
    m.set_content(body)
    for name, data, maintype, subtype in attach or []:
        m.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)
    return bytes(m)


RULES = Rules({
    "me": [ME],
    "gmail_write": True,
    "capture_address": CAPTURE,
    "default": "skip",
    "rules": [
        {"name": "Boss", "when": {"from": "boss@work.com"}, "then": {"priority": "high", "area": "work"}},
        {"name": "Receipts", "when": {"subject": ["receipt", "/order #\\d+/"]},
         "then": {"action": "skip", "gmail_label": "Receipts"}},
        {"name": "Good newsletters", "when": {"newsletter": True, "domain": "stratechery.com"},
         "then": {"tags": ["read-later"]}},
    ],
})


class FakeMailbox:
    uidvalidity = 7

    def __init__(self, mails):
        self.mails, self.labels = mails, []

    def fetch_new(self, after_uid, since_days):
        return [m for m in self.mails if m.uid > after_uid]

    def add_label(self, uid, label):
        self.labels.append((uid, label))


class RulesTest(unittest.TestCase):
    def decide(self, raw):
        return RULES.decide(adapters.from_eml(raw))

    def test_rule_order_and_defaults(self):
        self.assertEqual(self.decide(mail("Boss <boss@work.com>", ME, "Q4 plan")).rule, "Boss")
        d = self.decide(mail("shop@x.com", ME, "Your order #123 is confirmed"))
        self.assertEqual((d.action, d.gmail_label), ("skip", "Receipts"))
        d = self.decide(mail("ben@stratechery.com", ME, "Weekly", newsletter=True))
        self.assertEqual((d.action, d.tags), ("capture", ["read-later"]))
        self.assertEqual(self.decide(mail("spam@news.com", ME, "Sale!", newsletter=True)).action, "skip")
        self.assertEqual(self.decide(mail(ME, "friend@x.com", "lunch?")).rule, "sent by me")
        self.assertEqual(self.decide(mail(ME, CAPTURE, "note")).action, "self-capture")

    def test_capture_address_defaults_from_me(self):
        self.assertEqual(Rules({"me": "Yi@Gmail.com"}).capture_address, "yi+gtd@gmail.com")

    def test_unknown_keys_rejected(self):
        with self.assertRaises(ValueError):
            Rules({"rules": [{"name": "x", "when": {"sender": "a"}}]})


class SelfEmailTest(unittest.TestCase):
    def one(self, raw):
        items = adapters.from_self_email(raw)
        self.assertEqual(len(items), 1)
        return items[0]

    def test_shared_link_uses_subject_as_title(self):
        item, _ = self.one(mail(ME, CAPTURE, "How transformers work",
                                "https://youtu.be/abc123\n\nSent from my iPhone"))
        self.assertEqual((item.channel, item.title, item.note), ("youtube", "How transformers work", ""))

    def test_link_with_note(self):
        item, _ = self.one(mail(ME, CAPTURE, "", "for the Q4 doc https://example.com/agents"))
        self.assertEqual((item.channel, item.note), ("url", "for the Q4 doc"))

    def test_dictation(self):
        item, _ = self.one(mail(ME, CAPTURE, "", "Call the dentist about the crown\n-- \nYi"))
        self.assertEqual((item.channel, item.content), ("text", "Call the dentist about the crown"))

    def test_screenshot(self):
        item, blobs = self.one(mail(ME, CAPTURE, "", "flight options",
                                    attach=[("IMG_1.png", b"png", "image", "png")]))
        self.assertEqual((item.channel, item.note, blobs), ("image", "flight options", {"IMG_1.png": b"png"}))

    def test_forwarded_email_keeps_original_sender(self):
        body = ("can you handle this by Fri?\n\n---------- Forwarded message ---------\n"
                "From: Alice <alice@acme.com>\nDate: Fri, 26 Sep 2026\nSubject: Contract renewal\n"
                "To: me@work.com\n\nPlease review the attached contract.")
        item, _ = self.one(mail("me@work.com", CAPTURE, "Fwd: Contract renewal", body))
        self.assertEqual(item.channel, "email")
        self.assertEqual(item.source["from"], "Alice <alice@acme.com>")
        self.assertEqual(item.note, "can you handle this by Fri?")
        self.assertEqual(item.content, "Please review the attached contract.")


class GmailSyncTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_sync(self):
        box = FakeMailbox([
            Mail(1, mail("boss@work.com", ME, "Q4 plan", "draft attached")),
            Mail(2, mail("shop@x.com", ME, "Your receipt")),
            Mail(3, mail(ME, CAPTURE, "Article", "https://example.com/a")),
            Mail(4, mail("random@x.com", ME, "hello")),
        ])
        dry = sync(self.store, RULES, box, dry_run=True)
        self.assertEqual(len(dry), 4)
        self.assertEqual(list(self.store.items()), [])
        self.assertEqual(box.labels, [])

        sync(self.store, RULES, box)
        items = {i.title: i for i in self.store.items()}
        self.assertEqual(set(items), {"Q4 plan", "Article"})
        self.assertEqual(items["Q4 plan"].extra["hints"], {"priority": "high", "area": "work", "rule": "Boss"})
        self.assertIn("rfc822msgid", items["Q4 plan"].source["link"])
        self.assertEqual(items["Article"].via, "email-to-self")
        self.assertEqual(box.labels, [(1, "GTD/Captured"), (2, "Receipts"), (3, "GTD/Captured")])

        # nothing is processed twice
        box.mails.append(Mail(5, mail("boss@work.com", ME, "Follow-up")))
        report = sync(self.store, RULES, box)
        self.assertEqual(len(report), 1)
        self.assertEqual(len(list(self.store.items())), 3)

    def test_read_only_by_default(self):
        rules = Rules({"me": [ME], "capture_address": CAPTURE,
                       "rules": [{"name": "Boss", "when": {"from": "boss@work.com"},
                                  "then": {"gmail_label": "VIP"}}]})
        self.assertFalse(rules.gmail_write)
        box = FakeMailbox([Mail(1, mail("boss@work.com", ME, "Q4 plan")),
                           Mail(2, mail(ME, CAPTURE, "note", "buy milk"))])
        sync(self.store, rules, box)
        self.assertEqual(len(list(self.store.items())), 2)
        self.assertEqual(box.labels, [])  # Gmail untouched

    def test_parse_fetch_meta(self):
        labels, thrid = parse_fetch_meta(
            '5 (X-GM-THRID 1790 X-GM-LABELS ("\\\\Important" "My Label" Work) UID 5 BODY[] {12}'
        )
        self.assertEqual(labels, ["\\Important", "My Label", "Work"])
        self.assertEqual(thrid, "1790")


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


class DataRepoTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.remote = root / "remote.git"
        git(root, "init", "-q", "--bare", "-b", "main", str(self.remote))
        self.laptop, self.phone = root / "laptop", root / "phone"
        git(root, "clone", "-q", str(self.remote), str(self.laptop))
        for repo in (self.laptop,):
            git(repo, "config", "user.email", "t@t"), git(repo, "config", "user.name", "t")
            git(repo, "checkout", "-q", "-b", "main")
        datarepo.init(self.laptop)
        datarepo.sync(Store(self.laptop), "init")
        git(root, "clone", "-q", str(self.remote), str(self.phone))
        git(self.phone, "config", "user.email", "t@t"), git(self.phone, "config", "user.name", "t")

    def tearDown(self):
        self.tmp.cleanup()

    def test_init_scaffold(self):
        for f in ("rules.yaml", ".gitattributes", ".gitignore", ".github/workflows/capture.yml", "CLAUDE.md"):
            self.assertTrue((self.laptop / f).exists(), f)
        Rules.load(self.laptop / "rules.yaml")  # the example must be valid

    def test_concurrent_captures_merge(self):
        laptop, phone = Store(self.laptop), Store(self.phone)
        laptop.add(adapters.from_text("from laptop"))
        phone.add(adapters.from_text("from phone"))
        datarepo.sync(phone)
        datarepo.sync(laptop)  # must rebase over the phone's push, events.jsonl included
        datarepo.sync(phone)
        for store in (laptop, phone):
            self.assertEqual({i.title for i in store.items()}, {"from laptop", "from phone"})
            self.assertEqual(len(store.events()), 2)
            md = (store.home / "INBOX.md").read_text()
            self.assertIn("from laptop", md)
            self.assertIn("from phone", md)
        self.assertEqual(datarepo.sync(laptop), "nothing new")


if __name__ == "__main__":
    unittest.main()


class EnrichTest(unittest.TestCase):
    def test_titles(self):
        from gtd.enrich import enrich_titles

        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            yt, _ = store.add(adapters.from_url("https://youtu.be/abc?si=x"))
            page, _ = store.add(adapters.from_url("https://example.com/post"))
            named, _ = store.add(adapters.from_url("https://example.com/other", title="My own title"))
            broken, _ = store.add(adapters.from_url("https://down.example/x"))

            def fake_get(url):
                if "youtube.com/oembed" in url:
                    return '{"title": "How transformers work", "author_name": "3Blue1Brown"}'
                if "down.example" in url:
                    raise OSError("unreachable")
                return '<html><head><title>Fallback</title><meta property="og:title" content="Agents &amp; tools"></head>'

            report = enrich_titles(store, get=fake_get)
            self.assertEqual(store.get(yt.id).title, "How transformers work")
            self.assertEqual(store.get(yt.id).source["author"], "3Blue1Brown")
            self.assertEqual(store.get(page.id).title, "Agents & tools")
            self.assertEqual(store.get(named.id).title, "My own title")
            self.assertEqual(store.get(broken.id).title, "down.example/x")
            self.assertEqual(sum(l.strip().startswith("✓") for l in report), 2)
            self.assertEqual(enrich_titles(store, get=fake_get)[-1].strip()[0], "✗")  # only the broken one retried


class FakeTelegram:
    """Stands in for api.telegram.org."""

    def __init__(self, updates, files=None):
        self.updates, self.files, self.sent, self.confirmed = updates, files or {}, [], 0

    def __call__(self, url, body):
        import json as _json
        method = url.rsplit("/", 1)[-1]
        if "/file/" in url:
            return self.files[method]
        params = _json.loads(body)
        if method == "getUpdates":
            self.confirmed = max(self.confirmed, params["offset"])
            result = [u for u in self.updates if u["update_id"] >= params["offset"]]
        elif method == "getFile":
            result = {"file_path": params["file_id"]}
        else:
            self.sent.append(params["text"])
            result = {}
        return _json.dumps({"ok": True, "result": result}).encode()


def tg(update_id, user, **msg):
    return {"update_id": update_id, "message": {
        "message_id": update_id, "date": 1790000000, "chat": {"id": user, "type": "private"},
        "from": {"id": user}, **msg}}


class TelegramTest(unittest.TestCase):
    def test_sync(self):
        from gtd.telegram import TelegramAPI, sync

        fake = FakeTelegram([
            tg(1, 42, text="/start"),
            tg(2, 42, text="call the dentist"),
            tg(3, 42, text="for Q4 https://youtu.be/abc"),
            tg(4, 42, photo=[{"file_id": "small", "file_size": 1}, {"file_id": "big", "file_size": 9}],
               caption="flight options"),
            tg(5, 42, voice={"file_id": "v1", "mime_type": "audio/ogg"}),
            tg(6, 42, text="see you at 7", forward_origin={
                "type": "user", "sender_user": {"first_name": "Sam", "last_name": "Lee"}}),
            tg(7, 99, text="let me in"),
        ], files={"big": b"jpeg", "v1": b"ogg"})
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            api = TelegramAPI("TOKEN", http=fake)
            self.assertEqual(len(sync(store, api, dry_run=True)), 6)
            self.assertEqual(list(store.items()), [])

            report = sync(store, api)
            items = {i.channel: i for i in store.items()}
            self.assertEqual(set(items), {"text", "youtube", "image", "audio", "message"})
            self.assertEqual(items["youtube"].note, "for Q4")
            self.assertEqual(items["image"].title, "flight options")
            self.assertTrue((store.path_of(items["image"].id) / "attachments" / "telegram-4.jpg").exists())
            self.assertEqual(items["message"].source["forwarded_from"], "Sam Lee")
            self.assertEqual(items["message"].title, "Sam Lee: see you at 7")
            self.assertIn("refused", report[-1])
            self.assertIn("Sorry, this is a private inbox.", fake.sent)
            self.assertEqual(sum(t.startswith("✓ Captured") for t in fake.sent), 5)
            self.assertEqual(fake.confirmed, 8)

            fake.updates.append(tg(8, 42, text="call the dentist"))
            sync(store, api)
            self.assertEqual(len(list(store.items())), 5)
            self.assertTrue(fake.sent[-1].startswith("↺ Already"))


class PriorityAndVisionTest(unittest.TestCase):
    def test_priority_markers_only_for_things_i_wrote(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            mine, _ = store.add(adapters.from_text("Buy air purifier high priority", via="telegram"))
            self.assertEqual(mine.title, "Buy air purifier")
            self.assertEqual(mine.extra["hints"]["priority"], "high")
            self.assertIn("high priority", store.get(mine.id).content)  # raw kept
            later, _ = store.add(adapters.from_url("https://example.com/x", via="telegram", note="!low someday"))
            self.assertEqual((later.note, later.extra["hints"]["priority"]), ("someday", "low"))
            spam = adapters.from_eml(mail("shop@x.com", ME, "URGENT sale ends today"), via="gmail")
            store.add(spam)
            self.assertNotIn("hints", store.get(spam.id).extra)
            self.assertEqual(store.get(spam.id).title, "URGENT sale ends today")

    def test_backfill_priority(self):
        from gtd.enrich import backfill_priority
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            item = adapters.from_text("Buy air purifier high priority", via="telegram")
            item.via = "old"  # captured before markers existed
            store.add(item)
            loaded = store.get(item.id)
            loaded.via = "telegram"
            store.save(loaded)
            self.assertEqual(len(backfill_priority(store)), 1)
            self.assertEqual(store.get(item.id).title, "Buy air purifier")
            self.assertEqual(backfill_priority(store), [])

    def test_enrich_images(self):
        from types import SimpleNamespace
        from gtd.enrich import enrich_images

        class FakeClaude:
            def __init__(self):
                self.calls = []
                self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

            def create(self, **kw):
                self.calls.append(kw)
                text = ('{"title": "Ibiden sell call in Semiconductor degens chat", '
                        '"summary": "Group chat about Ibiden falling after a GPT sell call.", '
                        '"text": "Ibiden dropping so much", "urls": ["https://x.com/a/status/1"]}')
                return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=text)])

        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            blob = {"telegram-4.jpg": b"\xff\xd8jpeg"}
            shot = Item(channel="image", title="telegram-4.jpg", via="telegram", enrichment="pending",
                        source={"filename": "telegram-4.jpg", "mime": "image/jpeg"}, content_hash="h1")
            captioned = Item(channel="image", title="flight options", via="telegram", enrichment="pending",
                             source={"filename": "telegram-5.jpg", "mime": "image/jpeg"}, content_hash="h2")
            store.add(shot, blobs=blob)
            store.add(captioned, blobs={"telegram-5.jpg": b"\xff\xd8jpeg2"})
            claude = FakeClaude()
            report = enrich_images(store, client=claude)
            self.assertEqual(len(report), 2)
            got = store.get(shot.id)
            self.assertEqual(got.title, "Ibiden sell call in Semiconductor degens chat")
            self.assertEqual(got.enrichment, "done")
            self.assertIn("https://x.com/a/status/1", got.summary)
            self.assertEqual(store.get(captioned.id).title, "flight options")  # caption kept
            self.assertEqual(claude.calls[0]["model"], "claude-opus-5")
            self.assertEqual(enrich_images(store, client=claude), [])  # nothing left to do
