import tempfile
import unittest
from pathlib import Path

from gtd import adapters, render
from gtd.cli import main
from gtd.store import Store

EML = b"""From: Alice <alice@acme.com>
To: me@example.com
Subject: Contract renewal
Date: Fri, 26 Sep 2026 08:11:22 +0000
Message-ID: <abc123@acme.com>
Content-Type: text/plain; charset=utf-8

Can you review the attached contract by Friday?
"""


class InboxTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.store = Store(self.home)

    def tearDown(self):
        self.tmp.cleanup()

    def test_text_roundtrip(self):
        item, created = self.store.add(adapters.from_text("Call dentist\nabout the crown", note="urgent"))
        self.assertTrue(created)
        loaded = self.store.get(item.id)
        self.assertEqual(loaded.title, "Call dentist")
        self.assertEqual(loaded.content, "Call dentist\nabout the crown")
        self.assertEqual(loaded.note, "urgent")
        self.assertEqual(loaded.status, "inbox")
        self.assertEqual(loaded.captured_at, item.captured_at)

    def test_url_channels_and_canonicalisation(self):
        cases = {
            "https://youtu.be/abc123?si=xyz": ("youtube", "https://youtube.com/watch?v=abc123"),
            "https://www.youtube.com/watch?v=abc&t=42": ("youtube", "https://youtube.com/watch?v=abc&t=42"),
            "https://x.com/user/status/1?s=20": ("twitter", "https://twitter.com/user/status/1"),
            "https://example.com/post/?utm_source=nl#top": ("url", "https://example.com/post"),
            "https://podcasts.apple.com/us/podcast/x/id1": ("podcast", "https://podcasts.apple.com/us/podcast/x/id1"),
        }
        for url, (channel, canon) in cases.items():
            item = adapters.from_url(url)
            self.assertEqual(item.channel, channel, url)
            self.assertEqual(item.source["canonical_url"], canon, url)

    def test_duplicate_is_recaptured_not_added(self):
        a, _ = self.store.add(adapters.from_url("https://example.com/a?utm_source=x"))
        b, created = self.store.add(adapters.from_url("https://www.example.com/a/", note="again!"))
        self.assertFalse(created)
        self.assertEqual(a.id, b.id)
        self.assertEqual(len(list(self.store.items())), 1)
        self.assertIn("again!", self.store.get(a.id).note)
        self.assertEqual([e["event"] for e in self.store.events()], ["captured", "recaptured"])

    def test_file_capture_copies_attachment(self):
        img = self.home / "Screenshot.png"
        img.write_bytes(b"\x89PNG fake")
        item, files = adapters.from_any(str(img))
        self.assertEqual(item.channel, "image")
        self.store.add(item, files)
        folder = self.store.path_of(item.id)
        self.assertTrue((folder / "attachments" / "Screenshot.png").exists())
        self.assertEqual(self.store.get(item.id).enrichment, "pending")

    def test_eml(self):
        eml = self.home / "msg.eml"
        eml.write_bytes(EML)
        item = adapters.from_file(eml)
        self.assertEqual(item.channel, "email")
        self.assertEqual(item.title, "Contract renewal")
        self.assertEqual(item.source["from"], "Alice <alice@acme.com>")
        self.assertIn("review the attached contract", item.content)

    def test_later_steps_fields_survive_rewrite(self):
        item, _ = self.store.add(adapters.from_text("Plan offsite"))
        item.extra["kind"] = "project"  # as Step 2 would
        self.store.save(item)
        self.assertEqual(self.store.get(item.id).extra["kind"], "project")

    def test_views_and_cli(self):
        main(["--home", str(self.home), "capture", "Buy milk", "-t", "life"])
        main(["--home", str(self.home), "capture", "https://example.com/x", "-n", "read later"])
        items = list(self.store.items())
        text = render.as_text(items)
        self.assertIn("Inbox — 2 items", text)
        self.assertIn("Today", text)
        self.assertIn('"read later"', text)
        self.assertEqual(main(["--home", str(self.home), "render"]), 0)
        self.assertIn("Buy milk", (self.home / "INBOX.md").read_text())
        self.assertIn("<article", (self.home / "inbox.html").read_text())


if __name__ == "__main__":
    unittest.main()
