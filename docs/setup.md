# Setup: one inbox on laptop, iPhone and Android

About 20 minutes. You end up with:
- a **private** GitHub repo `gtd-inbox` holding your stuff (this code repo is public, so data never goes here);
- Gmail pulled in every 30 minutes according to your `rules.yaml`;
- a one-tap "send to my inbox" from any phone's share sheet.

## 1. Create the private inbox repo (laptop)

1. On GitHub: **New repository** → name `gtd-inbox` → **Private** → create (empty, no README).
2. On the laptop:
   ```bash
   pip install "git+https://github.com/dydy0539/GTD"
   git clone https://github.com/<you>/gtd-inbox ~/gtd-inbox
   echo 'export GTD_HOME=~/gtd-inbox' >> ~/.zshrc   # or ~/.bashrc
   export GTD_HOME=~/gtd-inbox
   gtd init          # writes rules.yaml, CLAUDE.md, the scheduled workflow, .gitattributes
   ```
3. Edit `~/gtd-inbox/rules.yaml`: set `me`, `capture_address` (`<you>+gtd@gmail.com`)
   and your own rules (see the comments at the top of the file).
4. `gtd sync` pushes it all to GitHub.

## 2. Connect Gmail

1. Turn on 2-Step Verification for your Google account if it isn't on yet.
2. Create an **app password**: <https://myaccount.google.com/apppasswords>
   (name it "gtd"). Copy the 16 characters.
3. Try your rules without changing anything:
   ```bash
   GMAIL_ADDRESS=<you>@gmail.com GMAIL_APP_PASSWORD='xxxx xxxx xxxx xxxx' \
     gtd gmail sync --dry-run --since-days 7
   ```
   Adjust `rules.yaml` until the capture/skip list looks right.
4. In the `gtd-inbox` repo on GitHub → **Settings → Secrets and variables → Actions**:
   - Secrets: `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`
   - Variables: `TZ` = your time zone, e.g. `America/Los_Angeles`
5. **Actions** tab → *capture* → **Run workflow** once to check it works.
   After that it runs every 30 minutes on its own.
6. Optional (recommended), in Gmail: a filter for `to:(<you>+gtd@gmail.com)` →
   *Skip the Inbox* + *Mark as read*. Your captures then don't clutter your
   email inbox. The sync still finds them.

## 3. Phones (iPhone and Android)

1. Add a contact **"GTD Inbox"** with the email `<you>+gtd@gmail.com`.
2. To capture anything: **Share → Gmail (or Mail) → type "GTD" → Send.**
   - a link / YouTube video / tweet / podcast episode: just send. The subject becomes the title.
   - a screenshot or voice memo: share it the same way. Type a line of text if you want a note.
   - a thought: new email to GTD Inbox and dictate with the keyboard mic.
   - an email: forward it. Anything you write above it becomes the note.
   - a WhatsApp or other messenger conversation: copy it, then paste it into an email (or use the app's *Export chat* option).
3. To **read** your inbox: the GitHub app → `gtd-inbox` → `INBOX.md`.
   Or open `https://github.com/<you>/gtd-inbox/blob/main/INBOX.md` in the
   browser and *Add to Home Screen*.

## 4. Claude

- In a Claude Code session on `gtd-inbox`, say "add to my inbox: …". The
  repo's `CLAUDE.md` tells Claude how.
- In any Claude chat with the Gmail connector, Claude can email the capture
  address instead.

## Daily use on the laptop

```bash
gtd capture "call dentist about the crown"
gtd capture https://example.com/article -n "for the Q4 doc"
gtd ls           # what's in the inbox
gtd sync         # share with the other devices (also pulls in theirs)
```

## 5. Telegram bot (optional second funnel)

1. In Telegram, open a chat with **@BotFather** (the one with the blue check) → send `/newbot`.
2. Give it a display name (e.g. `My GTD Inbox`) and a username ending in `bot`
   (e.g. `yourname_gtd_bot`). BotFather replies with a **token** like `123456:ABC-…`.
3. In the `gtd-inbox` repo → Settings → Secrets and variables → Actions →
   New repository secret: **Name** `TELEGRAM_BOT_TOKEN`, **Secret** the token.
4. Open your new bot in Telegram (link in BotFather's reply) → **Start** → send a test message.
   The first person to message the bot becomes its owner; nobody else can use it.
5. Pin the chat. From now on: **Share → Telegram → your bot**, or forward any message to it.
   It replies "✓ Captured" when the next sync picks it up (within 30 minutes).
