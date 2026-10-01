# In-tray page without a Claude session (Google Drive bridge)

The In-tray page (a claude.ai artifact) and the scheduled capture job meet in a Google Drive
folder, so nothing needs to stay running between them:

```
capture job (GitHub Actions, every 30 min)            In-tray page (claude.ai, phone or Mac)
  1. read newest outbox/taps-*.json  ◀── taps ────────  writes a snapshot of unapplied taps
     apply decisions, edits, ideas, time zone, projects  (decisions, edits, adds, here, projects, logs)
  2. capture Gmail / Telegram / feeds
  3. Telegram: "📥 n new in your In-tray"
  4. write gtd-page.json  ─────────── page data ──────▶  loads it on open (and when you come back)
                                                          clears applied taps, trashes read snapshots
```

The page reads and writes Drive with **your** Google Drive connector; the job uses a Google
**service account** that the folder is shared with.

## One-time setup

1. **Drive folder** — `GTD assistant/` with `gtd-page.json` and an `outbox/` folder. Their ids go in
   `drive.json` in the data repo: `{"page": "<file id>", "outbox": "<folder id>"}`.
2. **Service account** (free) — console.cloud.google.com → create a project → enable the
   *Google Drive API* → IAM & Admin → Service accounts → Create → Keys → Add key → JSON.
3. **Share** the `GTD assistant` folder with the service account's e-mail address as *Editor*.
4. **Secret** — data repo → Settings → Secrets and variables → Actions → `GOOGLE_SERVICE_ACCOUNT_JSON`
   = the whole key file.
5. Open the page on claude.ai and allow Google Drive when it asks.

Until steps 2–4 are done the job skips both Drive steps and the page shows the copy it was published with.
