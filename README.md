# GTD — personal Getting-Things-Done assistant

A personal assistant built on David Allen's GTD method, in four steps:

1. **Capture** — one "stuff" inbox for everything, from any channel ← *in progress*
2. **Clarify & organize** — decision engine: trash / reference / someday; or next action, delegate, defer, project
3. **Engage** — dashboard of what to do next and how
4. **Reflect** — feedback on how you're doing

Design: [`docs/design/01-stuff-inbox.md`](docs/design/01-stuff-inbox.md)

## Step 1 quick start

```bash
pip install -e .                       # needs only PyYAML
export GTD_HOME=~/gtd-data             # where your stuff lives (not in this repo)

gtd capture "call dentist about the crown" -t life
gtd capture https://youtu.be/abc123 --note "for the Q4 talk"
gtd capture ~/Desktop/Screenshot.png
gtd capture ~/Downloads/message.eml    # an email saved from Gmail
pbpaste | gtd capture -                # anything from stdin

gtd ls                                 # human-readable inbox
gtd show 20260928T1430                 # one item (id prefix works)
gtd render                             # writes INBOX.md + inbox.html to $GTD_HOME
```

Each item is a folder: `$GTD_HOME/stuff/YYYY/MM/<id>-<slug>/item.md`, plus an
`attachments/` folder. Every change is appended to `$GTD_HOME/events.jsonl`.

Run the tests: `python3 -m unittest -v`
