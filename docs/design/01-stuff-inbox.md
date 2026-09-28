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

### Funnels (decided 2026-09-28)

| # | Funnel | Works on | Good for |
|---|---|---|---|
| 1 | **Email to self**: share → Gmail → `you+gtd@gmail.com` | iPhone, Android, laptop | links, videos, tweets, podcasts, screenshots, voice memos, dictation (keyboard mic), forwarded emails, pasted chats |
| 2 | **Gmail rules**: `rules.yaml` pulls in mail that matters | everywhere (server-side) | email that is itself stuff (boss, clients, bills) |
| 3 | **Claude**: "add to my inbox: …" | Claude app on any device | thinking out loud, longer notes |
| 4 | **CLI**: `gtd capture …` | laptop | files, quick notes while working |

**Why email to self is the main phone funnel.** Every app on iOS and
Android has a share button, and Gmail is on every share sheet. That covers
YouTube, X, podcast apps, the browser, Photos and Voice Memos. Nothing new
has to be installed, it works the same on all three devices, and it
supports attachments. Gmail's plus-addressing means no new account: mail to
`you+gtd@gmail.com` arrives in your own mailbox. The sync recognizes it
and turns it into the right kind of item:

| What you send | Becomes |
|---|---|
| a single link (subject = page/video title) | url / youtube / twitter / podcast item, titled by the subject |
| text + link | link item with your text as the note |
| attachments (screenshot, voice memo, PDF) | one image / audio / file item each, your text as the note |
| a forwarded email | email item keeping the **original** sender and subject; what you wrote above it is the note |
| anything else | text item (dictation, pasted WhatsApp conversation, …) |

A Telegram bot is still an option later, mainly for voice notes with a
reply confirmation. It needs another app, so it is not the default.

### Gmail capture rules (the "priority filter")

`$GTD_HOME/rules.yaml` decides which mail **enters** the inbox and attaches
*hints*. It does not make GTD decisions; those stay in Step 2.

* Precedence: mail to the capture address is always captured, your own sent
  mail is always ignored, then user rules run (first match wins), then
  `default` (`skip`).
* Conditions: `from`, `to`, `subject`, `body`, `text`, `domain`, `channel`,
  `label`, `newsletter`, `has_attachment`. Plain strings match as
  substrings, `/regex/` as regular expressions, and lists match any entry.
* Actions: `capture` or `skip`, plus `priority`, `area` and `tags` hints, and
  `gmail_label` to also label the message in Gmail (this works together
  with `skip`, e.g. "label as Receipts, don't capture").
* Hints are stored as `hints: {priority, area, rule}` in the front matter.
  The views show ❗ for high priority. Priority does **not** reorder the
  inbox: in GTD you process the inbox top to bottom.
* Safe to experiment: `gtd gmail sync --dry-run` prints the decision for
  every new message and changes nothing.

Transport: IMAP with a Gmail **app password** (standard library only, no
Google Cloud project). It searches *All Mail*, so a Gmail filter that
archives your capture mail still gets picked up. Messages are read with
`BODY.PEEK`, so they are not marked read, and captured ones get the Gmail
label `GTD/Captured`. If Google ever blocks app passwords on the account,
the fallback is the Gmail API with OAuth; only `GmailIMAP` would change.

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
| **M1 — Core** | item model, file store, event log, dedupe; adapters: text, url (with youtube/twitter/podcast detection), file, `.eml`; `gtd capture / ls / show / render` | ✅ |
| **M1.5 — Across devices** | private data repo + `gtd init / sync`; email-to-self funnel; Gmail rules + IMAP sync; scheduled GitHub Action | ✅ |
| M2 — Enrichment | `gtd enrich`: fetch + readable text for articles, YouTube transcripts, OCR/vision for images, LLM title+summary | next |
| M3 — More funnels | drop-folder ingest, Telegram bot (optional) | |
| M4 — Audio | Whisper for podcasts and voice memos | |
| M5 — Index | SQLite index + `inbox.html` search/filters (feeds Step 3) | |

Step 2 then reads `status: inbox` items and writes `kind` / `decision`
into the front matter, logging a `clarified` event.

## 8. Decisions

| Question | Decision | Why |
|---|---|---|
| Where does the data live? | A **private GitHub repo** (`gtd-inbox`), separate from this public code repo | Works on laptop (git clone), iPhone and Android (the GitHub app renders `INBOX.md`), and in Claude sessions on any device. Full history. Free scheduled jobs (Actions). The code repo is public, so personal data must never go in it. |
| Main phone funnel? | **Email to self** (`you+gtd@gmail.com`) | Built into every share sheet on iOS and Android, nothing new to install, handles attachments. See §3. |
| Gmail | **Rules file** (`rules.yaml`) applied by a sync job every 30 min | Rules you can read and change, with a dry run to try them. It runs in the cloud, so it works while your laptop is off. |
| Work vs life | **One inbox** (GTD: one collection system for everything). Rules may add an optional `area: work/life` *hint*; nothing is required at capture | Sorting at capture time adds friction, which is exactly what GTD's capture step avoids. Contexts and areas are Step 2's job. |

### How the devices share one inbox

```
 iPhone / Android ──share→ Gmail (+gtd) ─┐
 Gmail (rules.yaml)  ─────────────────────┤  GitHub Action, every 30 min:
                                          ├─▶ gtd gmail sync → gtd sync ──┐
 laptop: gtd capture … ; gtd sync ────────┼───────────────────────────────┤
 Claude (any device): "add to my inbox"───┘                               ▼
                                                              private repo gtd-inbox
                                                   stuff/…  events.jsonl  INBOX.md ← read on any phone
```

Git conflicts are designed out:
* every item is its own folder;
* `events.jsonl` uses git's `union` merge, so appends from different devices are all kept;
* `INBOX.md` is never merged: it is re-rendered after every pull and uses
  absolute dates, so it only changes when items do.
