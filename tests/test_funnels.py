import subprocess
import tempfile
import unittest
import unittest.mock
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
            self.assertIn("held", report[-1])
            self.assertTrue(any(t.startswith("This is a private inbox") for t in fake.sent))
            self.assertEqual(sum(t.startswith("✓ Captured") for t in fake.sent), 5)
            self.assertEqual(fake.confirmed, 8)

            fake.updates.append(tg(9, 42, text="Lunch tomorrow 12pm\nLocation: Lau Pa Sat, Singapore"))
            sync(store, api)
            self.assertIn("Add to calendar: https://calendar.google.com", fake.sent[-1])

            fake.updates.append(tg(11, 42, text="/follow https://www.youtube.com/@Asianometry"))
            sync(store, api)
            self.assertTrue(fake.sent[-1].startswith("Following"))
            self.assertIn("@Asianometry", (store.home / "feeds.yaml").read_text())

            fake.updates.append(tg(12, 42, text="call the dentist"))
            sync(store, api)
            self.assertEqual(len(list(store.items())), 6)
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


class CalendarTest(unittest.TestCase):
    def test_reschedule_from_the_page(self):
        from gtd import cli
        from gtd.decide import apply
        from gtd.gcal import schedule
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            item, _ = store.add(adapters.from_text("Haircut friday at 3pm", via="telegram"))
            item.source["sent_at"] = "2026-09-30T02:04:42+00:00"
            store.save(item)
            schedule(store)
            cal = store.get(item.id).extra["calendar"]
            report = apply(store, {item.id: {"calendar": {
                "start": "2026-10-03T11:30", "location": "Toni&Guy, 391 Orchard Road, Singapore 238872",
                "summary": "Haircut with Mei"}}})
            self.assertEqual(len(report), 1)
            new = store.get(item.id).extra["calendar"]
            self.assertEqual((new["start"], new["end"], new["timezone"], new["summary"]),
                             ("2026-10-03T11:30", "2026-10-03T12:30", "Asia/Singapore", "Haircut with Mei"))
            self.assertIn("20261003T113000", new["add_link"])
            self.assertEqual(store.get(item.id).status, "inbox")        # an edit isn't a decision
            self.assertEqual(apply(store, {item.id: {"calendar": {"start": "2026-10-03T11:30"}}}), [])  # no-op
            schedule(store)                                               # the next run keeps the edit
            self.assertEqual(store.get(item.id).extra["calendar"]["start"], "2026-10-03T11:30")
            self.assertNotEqual(cal["start"], new["start"])

            other, _ = store.add(adapters.from_text("Dinner with Sam", via="telegram"))
            cli.main(["--home", tmp, "reschedule", other.id, "--start", "2026-10-04T19:00"])
            self.assertEqual(store.get(other.id).extra["calendar"]["summary"], "Dinner with Sam")

    def test_day_and_time_without_a_place(self):
        from datetime import datetime
        from gtd import when
        from gtd.gcal import event_for
        now = datetime(2026, 9, 30, 10, 4)  # a Wednesday
        found = when.find("Haircut friday at 3pm", now)
        self.assertEqual((found.start, found.location, found.rest), (datetime(2026, 10, 2, 15, 0), "", "Haircut"))
        self.assertIsNone(when.find("call mum at 3pm", now))        # a time alone: a to-do, not an appointment
        self.assertIsNone(when.find("Q3 revenue up 3% on Friday", now))
        item = adapters.from_text("Haircut friday at 3pm", via="telegram")
        item.source["sent_at"] = "2026-09-30T02:04:42+00:00"
        event = event_for(item, "Asia/Singapore")
        self.assertEqual((event["summary"], event["start"], event["location"]), ("Haircut", "2026-10-02T15:00", ""))

    SOFIA = "地址：The Riverwalk, 20 Upper Circular Road, Singapore 058416\n时间：星期三下午2点15 @🦩sofia"

    def test_when_parser(self):
        from datetime import datetime
        from gtd.when import find
        now = datetime(2026, 9, 28, 16, 40)  # Monday
        f = find(self.SOFIA, now)
        self.assertEqual((f.start, f.rest), (datetime(2026, 9, 30, 14, 15), "@🦩sofia"))
        self.assertEqual(find("Dinner tomorrow 7:30pm\nLocation: Burnt Ends", now).start,
                         datetime(2026, 9, 29, 19, 30))
        self.assertEqual(find("下周三晚上8点 电影\n地点：Jewel Changi", now).start, datetime(2026, 10, 7, 20, 0))
        self.assertEqual(find("場所：渋谷\n金曜日 午後3時 打ち合わせ", now).start, datetime(2026, 10, 2, 15, 0))
        self.assertIsNone(find("Buy tennis balls", now))
        self.assertIsNone(find("call mom at 7pm", now))          # no place → not an appointment
        self.assertIsNone(find("Location: office", now))         # no time

    def test_bad_timezone_setting_does_not_crash(self):
        import os
        from unittest import mock
        from gtd.gcal import default_timezone
        with mock.patch.dict(os.environ, {"TZ": "Asia/Tokyo\r\n", "GTD_TIMEZONE": ""}):
            self.assertEqual(default_timezone(), "Asia/Tokyo")
        with mock.patch.dict(os.environ, {"TZ": "Mars/Olympus", "GTD_TIMEZONE": ""}):
            self.assertEqual(default_timezone(), "UTC")

    def test_schedule(self):
        from gtd.gcal import schedule
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            item = adapters.from_text(self.SOFIA, via="telegram")
            item.source["sent_at"] = "2026-09-28T08:40:00+00:00"  # Monday 16:40 in Singapore
            store.add(item)
            bank = adapters.from_eml(mail("bank@x.com", ME, "Branch visit",
                                          "Address: 1 Raffles Pl, Singapore 048616\nMonday 10am"), via="gmail")
            store.add(bank)

            report = schedule(store)  # no calendar configured → link only
            self.assertEqual(len(report), 1)
            cal = store.get(item.id).extra["calendar"]
            self.assertEqual((cal["start"], cal["timezone"], cal["status"]),
                             ("2026-09-30T14:15", "Asia/Singapore", "proposed"))
            self.assertEqual(cal["summary"], "with 🦩sofia · The Riverwalk")
            self.assertIn("calendar.google.com", cal["add_link"])
            self.assertNotIn("calendar", store.get(bank.id).extra)  # only things I wrote
            self.assertEqual(schedule(store), [])  # nothing changes on the next run

            class FakeCal:
                calls = []
                def insert(self, event_id, event):
                    self.calls.append((event_id, event))
                    return {"id": event_id, "htmlLink": "https://calendar.google.com/event?eid=x"}
            fake = FakeCal()
            schedule(store, fake)
            cal = store.get(item.id).extra["calendar"]
            self.assertEqual(cal["status"], "added")
            self.assertEqual(fake.calls[0][1]["start"], "2026-09-30T14:15")
            schedule(store, fake)
            self.assertEqual(len(fake.calls), 1)  # never added twice
            from gtd import render
            self.assertIn("on your calendar ✓", render.as_markdown(list(store.items())))


YT_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015" xmlns="http://www.w3.org/2005/Atom">
 <title>Asianometry</title>
 <entry><id>yt:video:NEW1</id><yt:videoId>NEW1</yt:videoId><title>The TSMC Story</title>
  <link rel="alternate" href="https://www.youtube.com/watch?v=NEW1"/><author><name>Asianometry</name></author>
  <published>{recent}</published></entry>
 <entry><id>yt:video:SHORT</id><yt:videoId>SHORT</yt:videoId><title>60s on ASML</title>
  <link rel="alternate" href="https://www.youtube.com/shorts/SHORT"/><author><name>Asianometry</name></author>
  <published>{recent}</published></entry>
 <entry><id>yt:video:OLD1</id><yt:videoId>OLD1</yt:videoId><title>Old video</title>
  <link rel="alternate" href="https://www.youtube.com/watch?v=OLD1"/><author><name>Asianometry</name></author>
  <published>2025-01-01T00:00:00+00:00</published></entry>
</feed>"""

PODCAST = """<rss version="2.0"><channel><title>Invest Like the Best</title>
 <item><title>Ep 1</title><guid>ep1</guid><link>https://example.com/ep1</link>
  <pubDate>{recent}</pubDate></item></channel></rss>"""

CHANNEL_PAGE = '<link rel="canonical" href="https://www.youtube.com/channel/UCnrqHxkQx8fpCpBb-1XpQ4w">'


class FeedsTest(unittest.TestCase):
    def test_youtube_and_podcast_feeds(self):
        from datetime import datetime, timedelta, timezone
        from email.utils import format_datetime
        from gtd.feeds import sync

        recent = datetime.now(timezone.utc) - timedelta(hours=5)
        pages = {"yt": YT_FEED.replace("{recent}", recent.isoformat()),
                 "pod": PODCAST.replace("{recent}", format_datetime(recent))}

        def get(url):
            if url == "https://www.youtube.com/@Asianometry":
                return CHANNEL_PAGE
            if "videos.xml?channel_id=UCnrqHxkQx8fpCpBb-1XpQ4w" in url:
                return pages["yt"]
            if url == "https://example.com/pod.rss":
                return pages["pod"]
            raise OSError(url)

        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            (store.home / "feeds.yaml").write_text(
                'youtube: ["@Asianometry"]\nfeeds: ["https://example.com/pod.rss"]\npriority: low\ntags: [watch]\n')
            self.assertEqual(sum("capture" in l for l in sync(store, get, dry_run=True)), 2)
            self.assertEqual(list(store.items()), [])

            report = sync(store, get)
            items = {i.title: i for i in store.items()}
            self.assertEqual(set(items), {"The TSMC Story", "Ep 1"})  # no shorts, no back catalogue
            video = items["The TSMC Story"]
            self.assertEqual((video.channel, video.source["author"], video.tags), ("youtube", "Asianometry", ["watch"]))
            self.assertEqual(video.extra["hints"]["priority"], "low")
            self.assertEqual([l for l in sync(store, get) if "capture" in l], [])  # nothing new next run

            pages["yt"] = pages["yt"].replace("NEW1", "NEW2").replace("The TSMC Story", "ASML deep dive")
            self.assertEqual(sum("capture" in l for l in sync(store, get)), 1)
            self.assertIn("ASML deep dive", {i.title for i in store.items()})

    def test_follow(self):
        from gtd.feeds import follow, load_config
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            (store.home / "feeds.yaml").write_text("# my feeds\nyoutube: []\n\nfeeds: []\nskip_shorts: true\n")
            follow(store, "https://www.youtube.com/@Asianometry")
            follow(store, "@Stratechery")
            follow(store, "https://example.com/pod.rss")
            self.assertTrue(follow(store, "@Stratechery").startswith("Already"))
            cfg = load_config(store)
            self.assertEqual(cfg["youtube"], ["https://www.youtube.com/@Asianometry", "@Stratechery"])
            self.assertEqual((cfg["feeds"], cfg["skip_shorts"]), (["https://example.com/pod.rss"], True))
            self.assertIn("# my feeds", (store.home / "feeds.yaml").read_text())
            with self.assertRaises(ValueError):
                follow(store, "hello")

    def test_import_takeout(self):
        from gtd.feeds import import_takeout, load_config
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            csv_file = store.home / "subscriptions.csv"
            csv_file.write_text("Channel Id,Channel Url,Channel Title\n"
                                "UCnrqHxkQx8fpCpBb-1XpQ4w,http://www.youtube.com/channel/UCnrqHxkQx8fpCpBb-1XpQ4w,Asianometry\n"
                                "UCxxxxxxxxxxxxxxxxxxxxx1,http://www.youtube.com/channel/UCxxxxxxxxxxxxxxxxxxxxx1,Other\n")
            self.assertEqual(import_takeout(store, csv_file), 2)
            self.assertEqual(len(load_config(store)["youtube"]), 2)
            self.assertEqual(import_takeout(store, csv_file), 0)


def _yt_search_page(videos):
    items = [{"videoRenderer": {
        "videoId": vid, "title": {"runs": [{"text": title}]},
        "ownerText": {"runs": [{"text": channel}]},
        "publishedTimeText": {"simpleText": ago}, "lengthText": {"simpleText": length},
        "detailedMetadataSnippets": [{"snippetText": {"runs": [{"text": snippet}]}}]}}
        for vid, title, channel, ago, length, snippet in videos]
    data = {"contents": {"twoColumnSearchResultsRenderer": {"primaryContents": {"sectionListRenderer": {
        "contents": [{"itemSectionRenderer": {"contents": items}}]}}}}}
    import json as _json
    return f"<script>var ytInitialData = {_json.dumps(data)};</script>"


class PeopleSearchTest(unittest.TestCase):
    def test_context_words_for_a_common_name(self):
        from gtd.feeds import youtube_search
        page = _yt_search_page([
            ("b1", "Ben Thompson on Aggregation Theory", "Invest Like the Best", "1 day ago", "1:00:00", "Stratechery's founder"),
            ("b2", "Ben Thompson career highlights", "Rugby Clips", "1 day ago", "10:00", "try of the season"),
            ("b3", "Sharp Tech with Ben Thompson", "Sharp Tech", "2 days ago", "55:00", ""),
        ])
        _, found = youtube_search("Ben Thompson", lambda url: page, ["Stratechery", "Sharp Tech"])
        self.assertEqual([e["id"] for e in found], ["b1", "b3"])
        _, everyone = youtube_search("Ben Thompson", lambda url: page)
        self.assertEqual(len(everyone), 3)

    def test_new_videos_featuring_a_person(self):
        from gtd.feeds import sync
        videos = [
            ("v1", "Dylan Patel on the GPU supply chain", "No Priors", "5 hours ago", "1:12:03", ""),
            ("v2", "AI capex debate", "BG2 Pod", "2 days ago", "58:10", "with Dylan Patel of SemiAnalysis"),
            ("v3", "Dylan Patel in 60 seconds", "Clips", "1 day ago", "0:59", ""),
            ("v4", "Unrelated video", "Someone", "3 hours ago", "10:00", "nothing to see"),
            ("v5", "Dylan Patel 2025 interview", "Old Show", "3 weeks ago", "45:00", ""),
            ("v7", "Dylan Patel undated", "Mystery", "", "45:00", ""),
        ]
        pages = {"html": _yt_search_page(videos)}
        upload = {"v8": "2024-05-01T00:00:00-07:00"}

        def get(url):
            if "results?search_query=%22Dylan+Patel%22" in url:
                return pages["html"]
            vid = url.rsplit("v=", 1)[-1]
            if vid in upload:
                return f'<meta itemprop="uploadDate" content="{upload[vid]}">'
            raise OSError(url)
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            (store.home / "feeds.yaml").write_text(
                "people:\n  - {name: Dylan Patel, priority: normal, tags: [watch, dylan-patel]}\npriority: low\n")
            sync(store, get)
            items = {i.title: i for i in store.items()}
            self.assertEqual(set(items), {"Dylan Patel on the GPU supply chain", "AI capex debate"})
            got = items["AI capex debate"]
            self.assertEqual((got.source["author"], got.tags), ("BG2 Pod", ["watch", "dylan-patel"]))
            self.assertNotIn("hints", got.extra)  # normal priority, not the feeds' low default
            videos.insert(0, ("v6", "Dylan Patel x Dwarkesh", "Dwarkesh Patel", "10 minutes ago", "2:01:00", ""))
            videos.append(("v8", "Dylan Patel 2024 deep dive", "Old Pod", "", "1:30:00", ""))  # undated, old
            videos.append(("v9", "Dylan Patel classic", "Old Pod 2", "", "1:00:00", ""))       # undated, no page
            pages["html"] = _yt_search_page(videos)
            new = [l for l in sync(store, get) if "capture" in l]
            self.assertEqual(len(new), 1)  # only the genuinely new one
            self.assertIn("Dylan Patel x Dwarkesh", new[0])


class SiteTest(unittest.TestCase):
    def test_page_embeds_items_safely(self):
        import json as _json, re as _re
        from gtd import site
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            store.add(adapters.from_text("Buy tennis balls", via="telegram"))
            store.add(adapters.from_text("</script><b>x</b> high priority", via="telegram"))
            store.add(adapters.from_url("https://youtu.be/abc", via="feed", title="The TSMC Story"))
            html = site.page(list(store.items()))
            self.assertTrue(html.startswith("<title>GTD In-tray</title>"))
            self.assertEqual(html.count("</script>"), 2)  # data can't close the script tag early
            data = _json.loads(_re.search(r'id="data">(.*?)</script>', html, _re.S).group(1))
            self.assertEqual(len(data["items"]), 3)
            rec = {r["title"]: r for r in data["items"]}
            self.assertEqual(rec["Buy tennis balls"]["source"], "Telegram")
            self.assertEqual(rec["The TSMC Story"]["source"], "YouTube & feeds")
            self.assertEqual(rec["</script><b>x</b>"]["priority"], "high")
            self.assertTrue(site.document([]).startswith("<!doctype html>"))


class DecideTest(unittest.TestCase):
    def test_apply_page_decisions(self):
        from gtd import cli, site
        from gtd.decide import apply
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            a, _ = store.add(adapters.from_text("junk", via="telegram"))
            b, _ = store.add(adapters.from_text("read this someday", via="telegram"))
            c, _ = store.add(adapters.from_text("wifi password is hunter2", via="telegram"))
            report = apply(store, {a.id: {"decision": "trash", "at": "2026-09-29T08:00:00Z"},
                                   b.id: "later", c.id: {"decision": "reference"},
                                   "nope": "trash", c.id[:-1] + "x": "shred"})
            self.assertEqual(sum(l.lstrip().startswith("✓") for l in report), 3)
            self.assertEqual(sum(l.lstrip().startswith("?") for l in report), 2)
            self.assertEqual(list(store.items()), [])
            self.assertEqual(store.get(b.id).status, "later")
            self.assertEqual(apply(store, [{"id": b.id, "decision": "later"}]), [])  # already applied
            self.assertIn("decided", [e["event"] for e in store.events()])

            cli.main(["--home", tmp, "decide", b.id, "reference", "--project", "Study Transformer",
                      "--note", "study material"])
            b2 = store.get(b.id)
            self.assertEqual((b2.status, b2.tags[-1], b2.note), ("reference", "project:study-transformer", "study material"))
            cli.main(["--home", tmp, "decide", b.id, "later"])

            cli.main(["--home", tmp, "decide", c.id, "inbox"])
            self.assertEqual([i.id for i in store.items()], [c.id])

            page = Path(tmp) / "page.html"
            cli.main(["--home", tmp, "render", "--page", str(page)])
            import json as _json, re as _re
            data = _json.loads(_re.search(r'id="data">(.*?)</script>', page.read_text(), _re.S).group(1))
            self.assertEqual({r["id"]: r["status"] for r in data["items"]}, {b.id: "later", c.id: "inbox"})
            self.assertTrue(set(site.SHOWN) >= {"inbox", "later", "reference"})


class TwoPhonesTest(unittest.TestCase):
    def test_link_second_account(self):
        import re as _re
        from gtd.telegram import TelegramAPI, sync
        fake = FakeTelegram([tg(1, 42, text="from phone one")])
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            api = TelegramAPI("TOKEN", http=fake)
            sync(store, api)                                   # 42 becomes the owner

            import time as _time
            now_ts = int(_time.time())
            fake.updates += [tg(2, 77, text="buy printer ink", date=now_ts),  # phone two, not linked yet: held
                             tg(3, 77, text="/join 000000", date=now_ts)]     # wrong code: refused
            sync(store, api)
            self.assertEqual({i.title for i in store.items()}, {"from phone one"})

            fake.updates.append(tg(4, 42, text="/invite"))
            sync(store, api)
            code = _re.search(r"/join (\d{6})", fake.sent[-1]).group(1)

            fake.updates += [tg(5, 77, text=f"/join {code}"), tg(6, 77, text="call the plumber")]
            sync(store, api)
            self.assertEqual({i.title for i in store.items()},
                             {"from phone one", "buy printer ink", "call the plumber"})  # held message kept

            fake.updates.append(tg(7, 99, text=f"/join {code}"))   # the code works only once
            sync(store, api)
            self.assertEqual(len(list(store.items())), 3)


class HereTest(unittest.TestCase):
    """Where you are decides what "Friday 3pm" means."""

    def test_signals_and_calendar(self):
        import os
        from email.message import EmailMessage as _Msg
        from gtd import here
        from gtd.decide import apply
        from gtd.telegram import TelegramAPI, sync
        from gtd.gcal import event_for
        os.environ.pop("GTD_TIMEZONE", None)
        with tempfile.TemporaryDirectory() as tmp, unittest.mock.patch.dict(os.environ, {"TZ": "Asia/Tokyo"}):
            store = Store(tmp)
            self.assertEqual(here.current(store), "Asia/Tokyo")          # no signal yet: the TZ setting

            # Telegram: /here and a shared location (1790000000 = 2026-09-21)
            fake = FakeTelegram([tg(1, 42, text="hi"), tg(2, 42, text="/here singapore")])
            api = TelegramAPI("TOKEN", http=fake)
            sync(store, api)
            self.assertEqual(here.current(store), "Asia/Singapore")
            self.assertIn("Singapore", fake.sent[-1])
            fake.updates.append(tg(3, 42, location={"latitude": 35.68, "longitude": 139.76}, date=1790000100))
            sync(store, api)
            self.assertEqual(here.current(store), "Asia/Tokyo")
            self.assertEqual({i.title for i in store.items()}, {"hi"})   # commands and locations aren't captured

            # An older signal never overrides a newer one; the page's newer one does
            self.assertFalse(here.set_here(store, "Asia/Singapore", "email", "2026-09-01T00:00:00+08:00"))
            report = apply(store, {"_here": {"timezone": "Asia/Singapore", "at": "2026-09-30T03:00:00Z"}})
            self.assertEqual(here.current(store), "Asia/Singapore")
            self.assertEqual(len(report), 1)

            # A Telegram note is read in the current zone; an email in the sender's offset
            item = adapters.from_text("Haircut friday at 3pm", via="telegram")
            item.source["sent_at"] = "2026-09-30T02:04:42+00:00"
            self.assertEqual(event_for(item, here.current(store))["timezone"], "Asia/Singapore")
            msg = _Msg()
            msg["From"] = msg["To"] = "me@example.com"
            msg["Subject"] = "Dentist"
            msg["Date"] = "Wed, 30 Sep 2026 11:00:00 +0900"
            msg.set_content("Dentist thursday 10:30")
            mail_item = adapters.from_self_email(msg.as_bytes())[0][0]
            self.assertEqual(mail_item.source["sent_at"], "2026-09-30T11:00:00+09:00")
            event = event_for(mail_item, here.current(store))
            self.assertEqual((event["timezone"], event["start"]), ("Asia/Tokyo", "2026-10-01T10:30"))

    def test_zone_names(self):
        from gtd import here
        self.assertEqual(here.zone_for("Tokyo"), "Asia/Tokyo")
        self.assertEqual(here.zone_for(" SG "), "Asia/Singapore")
        self.assertEqual(here.zone_for("Europe/London"), "Europe/London")
        self.assertIsNone(here.zone_for("Narnia"))
        self.assertEqual(here.zone_for_coords(1.29, 103.85), "Asia/Singapore")
        self.assertIsNone(here.zone_for_coords(51.5, -0.1))


class ProjectsBackupTest(unittest.TestCase):
    def test_save_merges_and_deletes(self):
        import json as _json
        from gtd import cli, site
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "export.json"
            f.write_text(_json.dumps({"projects": {"z2": {"name": "Zone 2", "kind": "recurring"},
                                                   "x": {"name": "Old", "kind": "oneoff"}},
                                      "logs": {"l1": {"project": "z2", "amount": 30}}}))
            cli.main(["--home", tmp, "projects", "save", str(f)])
            f.write_text(_json.dumps({"projects": {}, "logs": {"l2": {"project": "z2", "amount": 20}}, "deleted": ["x"]}))
            cli.main(["--home", tmp, "projects", "save", str(f)])
            saved = _json.loads((Path(tmp) / "projects.json").read_text())
            self.assertEqual(set(saved["projects"]), {"z2"})
            self.assertEqual(set(saved["logs"]), {"l1", "l2"})
            page = site.page([])
            self.assertIn('id="proj-view"', page)
            self.assertIn("#projects", page)


class SomedayTest(unittest.TestCase):
    def test_someday_button_and_new_ideas(self):
        import json as _json, re as _re
        from gtd import cli, site
        from gtd.decide import apply
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            a, _ = store.add(adapters.from_text("Learn to sail", via="telegram"))
            report = apply(store, {a.id: "someday",
                                   "_adds": [{"text": "Visit Patagonia", "status": "someday", "at": "2026-10-01T02:00:00Z"},
                                             {"text": "  "}]})
            self.assertEqual(len(report), 2)
            someday = {i.title: i for i in store.items(status="someday")}
            self.assertEqual(set(someday), {"Learn to sail", "Visit Patagonia"})
            self.assertEqual(someday["Visit Patagonia"].via, "page")
            self.assertEqual(list(store.items()), [])                     # out of the in-tray
            page = Path(tmp) / "page.html"
            cli.main(["--home", tmp, "render", "--page", str(page)])
            data = _json.loads(_re.search(r'id="data">(.*?)</script>', page.read_text(), _re.S).group(1))
            self.assertEqual({r["status"] for r in data["items"]}, {"someday"})
            self.assertIn("In-tray page", {r["source"] for r in data["items"]})
            cli.main(["--home", tmp, "decide", a.id, "inbox"])            # and back again
            self.assertEqual([i.title for i in store.items()], ["Learn to sail"])


class ArchiveCategoryTest(unittest.TestCase):
    def test_archive_into_categories(self):
        import json as _json, re as _re
        from gtd import cli
        from gtd.decide import apply
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            a, _ = store.add(adapters.from_text("Morning routine for lower back pain", via="telegram"))
            report = apply(store, {a.id: {"decision": "reference", "category": "Health & fitness"}})
            self.assertEqual(len(report), 1)
            item = store.get(a.id)
            self.assertEqual((item.status, item.extra["category"]), ("reference", "Health & fitness"))
            apply(store, {a.id: {"decision": "reference", "category": "Fitness"}})   # re-file while archived
            self.assertEqual(store.get(a.id).extra["category"], "Fitness")
            apply(store, {a.id: {"decision": "reference", "category": ""}})          # clear
            self.assertNotIn("category", store.get(a.id).extra)
            apply(store, {a.id: {"decision": "reference", "category": "Fitness"}})
            page = Path(tmp) / "page.html"
            cli.main(["--home", tmp, "render", "--page", str(page)])
            data = _json.loads(_re.search(r'id="data">(.*?)</script>', page.read_text(), _re.S).group(1))
            self.assertEqual(data["items"][0]["category"], "Fitness")
