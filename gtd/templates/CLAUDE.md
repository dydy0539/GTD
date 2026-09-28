# GTD inbox — private data repo

This repo is my GTD "stuff" inbox (Step 1: capture), managed by the code at
https://github.com/dydy0539/GTD. One folder per item under
`stuff/YYYY/MM/<id>-<slug>/item.md`; `INBOX.md` is the readable list.

## When I say "add to my inbox: …", "capture …", "save this for later"

```bash
pip install --quiet "git+https://github.com/dydy0539/GTD"
export GTD_HOME="$PWD"
gtd capture "<exactly what I said, or the URL>" --via claude -n "<why, if I said>"
gtd sync -m "capture: claude"
```

- This is a data repo: commit captures straight to the default branch, no PRs.
- Capture only. Don't decide or reorganize anything (that is Step 2).
- Never edit the `## Content` of existing items and never delete items.
- If you can't push here but have the Gmail connector, email the text to the
  `capture_address` in `rules.yaml` instead. The scheduled job picks it up.

## Useful
- `gtd ls` shows what's in the inbox
- `gtd gmail sync --dry-run` checks what the Gmail rules would do (needs GMAIL_* env)
