import subprocess
import tempfile
import unittest
from email.message import EmailMessage
from pathlib import Path

from gtd import adapters, datarepo
from gtd.gmail import Mail, parse_fetch_meta, sync
from gtd.rules import Rules
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
