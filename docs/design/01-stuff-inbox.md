# Step 1 — The "Stuff" Inbox

> GTD, *Capture*: get everything out of your head and into **one trusted
> bucket**, with as little friction as possible, without deciding anything yet.

This doc designs Step 1 with Steps 2–4 in mind:

| Step | Name | What it needs from Step 1 |
|------|------|---------------------------|
| 1 | **Capture** (this doc) | — |
| 2 | Clarify & Organize (decision engine) | Every item fully readable as text, with its source kept, in a stable format it can add decisions to |
| 3 | Engage (dashboard) | Stable IDs and links back to the original (email thread, tweet, video timestamp) |
| 4 | Reflect (feedback) | An event log: when things came in, when they were processed, from which channel |

---

## 1. Design principles

1. **Capture never fails and never waits.** Saving the raw input is instant and
   works offline. Slow work (fetching an article, transcribing a podcast, OCR)
   happens afterwards as *enrichment*. If enrichment fails, the item stays in
   the inbox with its raw content, marked `enrichment: failed`.
2. **One bucket, many funnels.** Every channel adds to the same store in the
   same format. A new channel is a small *adapter*. Nothing else changes.
3. **Raw is sacred, derived is disposable.** The original input is never
   edited. Extracted text, summaries and titles are separate and can be
   regenerated when better tools come along.
4. **Plain files first.** Each item is a folder holding a Markdown file with
   YAML front matter, plus its attachments. You can read it without the app,
   open it in Obsidian, grep it, sync it with Dropbox or iCloud, and version it
   with git. A SQLite index can come later for fast queries. It is built from
   the files and can always be rebuilt.
5. **No decisions in Step 1.** Capture only records *what came in and why I
   saved it*. Whether it is actionable, reference or trash is Step 2's job. The
   schema leaves room for those answers but Step 1 never fills them in.
6. **Local-first and private.** Your data lives in `$GTD_HOME` (default
   `~/gtd-data`), not in the code repo. Credentials for channels come from
   environment variables.

---

## 2. The item (the one data model)

An item is a folder:

```
$GTD_HOME/stuff/2026/09/20260928T143012-7f3a-read-this-article-on-agents/
├── item.md            ← human-readable, the source of truth
└── attachments/       ← screenshots, audio, .eml, PDFs, transcripts …
```

`item.md`:

```markdown
---
id: 20260928T143012-7f3a            # sortable by time, readable, unique
captured_at: 2026-09-28T14:30:12+00:00
channel: url                        # text | url | youtube | podcast | file | email | twitter | chat | …
via: cli                            # how it arrived: cli | claude | email-forward | telegram | drop-folder | gmail-sync
title: Building effective agents
source:                             # channel-specific pointer back to the original
  url: https://example.com/agents
  author: …
note: "for the Q4 planning doc"     # what you said when you captured it (optional, very valuable)
tags: []
content_hash: sha256:…              # for dedupe
attachments: [page.html]
status: inbox                       # Step 1 only ever writes "inbox"
enrichment: pending                 # pending | done | failed | n/a
# --- reserved for later steps (Step 1 leaves these empty) ---
# kind: action | project | reference | someday | trash
# decision: {...}
---

## Content

<raw text: the dictation, email body, or extracted article text>

## Summary

<added by enrichment: 1–3 line summary, filled in later>
```

**Why the front matter and the body are separate:** the front matter is for
machines (Step 2 filters and routes on it). The body is for you and the LLM
(Step 2 reads it to decide what to do).

### Channel → what gets stored

| Channel | Raw (kept as-is) | Content (text for reading/deciding) | Link back (`source`) |
|---|---|---|---|
| Dictation / typed / chat with Claude | the text | same | — |
| Web article | URL (+ HTML snapshot) | readable extracted text | url, author, site |
| YouTube | URL | transcript + description | url, channel, timestamp |
| Podcast | episode URL / RSS enclosure | transcript (Whisper) + show notes | feed, episode, timestamp |
| Screenshot / image | the image file | OCR / vision description | original filename, taken_at |
| Gmail | `.eml` or message id | plain-text body + attachments | message_id, thread_id, from, subject |
| Twitter / X | URL (+ screenshot) | tweet / thread text | url, author |
| Messenger (WhatsApp, Telegram, Slack…) | forwarded text / export | same | chat name, sender, time |
| Voice memo | audio file | transcript | recorded_at |

---

## 3. Architecture

```
   funnels (how stuff gets to you)                 adapters                       store
 ┌───────────────────────────────┐        ┌──────────────────────┐        ┌───────────────────┐
 │ CLI  `gtd capture …`          │──┐     │ text                 │        │ stuff/…/item.md   │
 │ Chat with Claude              │  │     │ url  (→ youtube,     │        │ attachments/      │
 │ Share sheet / Telegram bot    │  ├────▶│       twitter,       │──────▶ │ events.jsonl      │
 │ Email forward / Gmail label   │  │     │       podcast)       │ capture│                   │
 │ Drop folder (screenshots,     │  │     │ file (image, audio,  │ (sync, │                   │
 │   voice memos, PDFs)          │──┘     │       pdf, .eml)     │  fast) │                   │
 └───────────────────────────────┘        │ email                │        └─────────┬─────────┘
                                          └──────────────────────┘                  │
                                                                                    ▼
                                          ┌──────────────────────┐        ┌───────────────────┐
                                          │ enrichers (async)    │◀───────│ items with        │
                                          │  fetch+readability   │        │ enrichment:pending│
                                          │  youtube transcript  │───────▶│ fill Content /    │
                                          │  whisper, OCR/vision │        │ Summary / title   │
                                          │  LLM title+summary   │        └─────────┬─────────┘
                                          └──────────────────────┘                  ▼
                                                                          views: `gtd ls`,
                                                                          INBOX.md, inbox.html
```

* An **adapter** turns one kind of input into an item. It is small and does
  no network calls, so capture always works.
* An **enricher** is an optional plugin. It picks up items with
  `enrichment: pending`, adds derived content, and never touches the raw input.
  Heavier dependencies (trafilatura, yt-dlp, whisper, tesseract) are optional
  extras, so the core has none.
* **Funnels** are about *reach*: how an input gets from your phone or laptop to
  an adapter. They are the part you will keep adding to.

### Recommended funnels (least friction first)

1. **Talk to Claude.** "Add to my inbox: call dentist about the crown." Claude
   runs `gtd capture`. This covers dictation, typed notes and "save this
   link". Gmail is already connected to Claude, so it can pull tagged emails
   on request.
2. **Email forward / Gmail label.** Forward anything to a dedicated address,
   or put a `GTD` label on a message. A sync job pulls labeled messages and
   removes the label. Anything with a "share via email" button can then reach
   the inbox: most messenger apps, podcast apps and browsers.
3. **Mobile share sheet → Telegram bot (or iOS Shortcut).** The fastest way to
   capture a tweet, YouTube link, screenshot or voice memo from your phone. The
   bot calls the same adapters.
4. **Drop folder.** A synced folder (iCloud or Dropbox) `~/gtd-drop/`.
   Screenshots and voice memos saved there are picked up by
   `gtd ingest-folder`.

Twitter's API is expensive and messenger apps have no general API, so for
those the plan is *share URL / forward text*, not *sync the whole feed*.
Pulling everything would also flood the inbox, which works against GTD.

---

## 4. Human-readable views

* `gtd ls`: a terminal list grouped by day, with channel icon, age, title and
  a short preview.
* `INBOX.md`: a generated Markdown digest of the same list, readable anywhere
  (GitHub, Obsidian, phone).
* `inbox.html`: a single static page with cards, channel filters and search.
  It is the first building block of the Step 3 dashboard.

Example `gtd ls`:

```
Inbox — 5 items (oldest 3 days)

Today
  ✏️  20260928T143012-7f3a  Call dentist about the crown                        2h
  🔗  20260928T101500-19bc  Building effective agents — example.com  "for Q4"   6h
Fri 26 Sep
  📧  20260926T081122-c0de  Re: contract renewal — from alice@acme.com          2d
  🖼️  20260926T073000-aa01  Screenshot 2026-09-26 at 07.29.58.png              2d
  ▶️  20260925T220410-4be2  How transformers work — youtube.com                3d
```

The age matters. In GTD the inbox should reach zero regularly, so Step 4 will
track how long items wait.

---

## 5. Event log (the hook for Step 4)

Every change to the store is appended to `$GTD_HOME/events.jsonl`:

```json
{"ts": "2026-09-28T14:30:12+00:00", "event": "captured", "id": "20260928T143012-7f3a", "channel": "text", "via": "cli"}
{"ts": "2026-09-28T14:30:15+00:00", "event": "enriched", "id": "…", "enricher": "fetch_url"}
{"ts": "2026-09-29T09:00:00+00:00", "event": "clarified", "id": "…", "kind": "action"}   ← Step 2
{"ts": "2026-10-01T18:00:00+00:00", "event": "completed", "id": "…"}                   ← Step 3
```

Step 4 metrics then come straight from this log: capture volume per channel,
time spent in the inbox, inbox-zero streaks, and completion rate.

---

## 6. Deduplication

* URLs are canonicalized (lower-case host; `utm_*`, `fbclid` and `#fragment`
  removed; `youtu.be` → `youtube.com/watch?v=`).
* `content_hash` = sha256 of the canonical URL, or of the raw text/file bytes.
* Capturing a duplicate **does not create a new item**. It logs a
  `recaptured` event on the existing one, because saving the same thing twice
  signals that it matters. An optional note is appended.

---

## 7. Build plan

| Milestone | Scope | Status |
|---|---|---|
| **M1 — Core** | item model, file store, event log, dedupe; adapters: text, url (with youtube/twitter/podcast detection), file, `.eml`; `gtd capture / ls / show / render` | ✅ this commit |
| M2 — Enrichment | `gtd enrich`: fetch + readable text for articles, YouTube transcripts, OCR/vision for images, LLM title+summary | next |
| M3 — Funnels | Gmail label sync (Gmail API), drop-folder ingest, Telegram bot | |
| M4 — Audio | Whisper for podcasts and voice memos | |
| M5 — Index | SQLite index + `inbox.html` search/filters (feeds Step 3) | |

Step 2 then reads `status: inbox` items and writes `kind` / `decision`
into the front matter, logging a `clarified` event.

## 8. Open questions for you

1. **Where should the data live?** A local folder synced by iCloud or Dropbox
   (simple, private), or a private git repo (history, works well with Claude
   sessions)?
2. **Main phone funnel?** Telegram bot, iOS Shortcut, or email forward?
3. **Gmail:** a dedicated label you apply by hand (recommended, deliberate), or
   rules that auto-capture certain senders?
4. **Work vs life:** one inbox with a `context: work|life` tag (GTD
   recommends one inbox), or two separate stores?
