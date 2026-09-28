"""gtd — command line for the stuff inbox.

  gtd capture "call dentist about the crown"
  gtd capture https://youtu.be/abc123 --note "for the Q4 talk"
  gtd capture ~/Desktop/Screenshot.png
  echo "long dictated text" | gtd capture -
  gtd ls
  gtd show 20260928T1430
  gtd render            # writes INBOX.md and inbox.html into $GTD_HOME
  gtd gmail sync --dry-run
  gtd telegram sync
  gtd enrich            # real titles for captured links
  gtd sync              # share with your other devices (private git repo)
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import adapters, datarepo, render
from .rules import Rules
from .store import Store


def cmd_capture(store: Store, a: argparse.Namespace) -> int:
    kw = {"via": a.via, "note": a.note or "", "title": a.title}
    if a.value == ["-"]:
        item, files = adapters.from_text(sys.stdin.read(), **kw), []
    elif a.text:
        item, files = adapters.from_text(" ".join(a.value), **kw), []
    else:
        item, files = adapters.from_any(" ".join(a.value), **kw)
    if a.tag:
        item.tags = a.tag
    item, created = store.add(item, files)
    verb = "Captured" if created else "Already in inbox (recaptured)"
    print(f"{verb}: {item.icon} {item.title}  [{item.id}]")
    return 0


def cmd_ls(store: Store, a: argparse.Namespace) -> int:
    print(render.as_text(list(store.items(status=None if a.all else "inbox"))))
    return 0


def cmd_show(store: Store, a: argparse.Namespace) -> int:
    print((store.path_of(store.get(a.id).id) / "item.md").read_text())
    return 0


def cmd_render(store: Store, a: argparse.Namespace) -> int:
    items = list(store.items())
    out = Path(a.out) if a.out else store.home
    out.mkdir(parents=True, exist_ok=True)
    (out / "INBOX.md").write_text(render.as_markdown(items), encoding="utf-8")
    (out / "inbox.html").write_text(render.as_html(items), encoding="utf-8")
    print(f"Wrote {out / 'INBOX.md'} and {out / 'inbox.html'} ({len(items)} items)")
    return 0


def cmd_gmail_sync(store: Store, a: argparse.Namespace) -> int:
    from .gmail import GmailIMAP, sync

    address = os.environ.get("GMAIL_ADDRESS")
    password = os.environ.get("GMAIL_APP_PASSWORD")
    if not (address and password):
        print("error: set GMAIL_ADDRESS and GMAIL_APP_PASSWORD", file=sys.stderr)
        return 1
    rules = Rules.load(store.home / "rules.yaml")
    box = GmailIMAP(address, password, readonly=not rules.gmail_write)
    try:
        report = sync(store, rules, box, dry_run=a.dry_run, since_days=a.since_days)
    finally:
        box.close()
    title = "Gmail (dry run — nothing saved)" if a.dry_run else "Gmail"
    print(f"{title}: {len(report)} new message(s)")
    print("\n".join(report))
    return 0


def cmd_telegram_sync(store: Store, a: argparse.Namespace) -> int:
    from .telegram import TelegramAPI, sync, token_from_env

    report = sync(store, TelegramAPI(token_from_env()), dry_run=a.dry_run)
    print(f"Telegram{' (dry run — nothing saved)' if a.dry_run else ''}: {len(report)} message(s)")
    print("\n".join(report))
    return 0


def cmd_enrich(store: Store, a: argparse.Namespace) -> int:
    from .enrich import enrich_titles

    report = enrich_titles(store)
    print(f"Enriched {sum(l.lstrip().startswith('✓') for l in report)} item(s)")
    print("\n".join(report))
    return 0


def cmd_init(store: Store, a: argparse.Namespace) -> int:
    written = datarepo.init(store.home)
    print(f"Initialised {store.home}: {', '.join(written) or 'nothing to do'}")
    print("Next: edit rules.yaml, then `gtd sync`.")
    return 0


def cmd_sync(store: Store, a: argparse.Namespace) -> int:
    print(datarepo.sync(store, a.message))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="gtd", description="Capture everything into one inbox.")
    p.add_argument("--home", help="data directory (default $GTD_HOME or ~/gtd-data)")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("capture", aliases=["c"], help="add stuff: text, URL, file, or - for stdin")
    c.add_argument("value", nargs="+")
    c.add_argument("-n", "--note", help="why you are saving this")
    c.add_argument("-t", "--tag", action="append", help="tag (repeatable), e.g. work / life")
    c.add_argument("--title")
    c.add_argument("--via", default="cli", help="funnel it came through (cli, claude, telegram…)")
    c.add_argument("--text", action="store_true", help="force plain-text capture")
    c.set_defaults(fn=cmd_capture)

    l = sub.add_parser("ls", help="list the inbox")
    l.add_argument("-a", "--all", action="store_true", help="include processed items")
    l.set_defaults(fn=cmd_ls)

    s = sub.add_parser("show", help="print one item")
    s.add_argument("id", help="id or unique id prefix")
    s.set_defaults(fn=cmd_show)

    r = sub.add_parser("render", help="write INBOX.md and inbox.html")
    r.add_argument("-o", "--out", help="output directory (default $GTD_HOME)")
    r.set_defaults(fn=cmd_render)

    g = sub.add_parser("gmail", help="Gmail funnel").add_subparsers(dest="gcmd", required=True)
    gs = g.add_parser("sync", help="pull new mail through rules.yaml into the inbox")
    gs.add_argument("--dry-run", action="store_true", help="show decisions, change nothing")
    gs.add_argument("--since-days", type=int, default=2, help="look back this far (default 2)")
    gs.set_defaults(fn=cmd_gmail_sync)

    t = sub.add_parser("telegram", help="Telegram bot funnel").add_subparsers(dest="tcmd", required=True)
    ts = t.add_parser("sync", help="capture new messages sent to your bot")
    ts.add_argument("--dry-run", action="store_true", help="show what would be captured")
    ts.set_defaults(fn=cmd_telegram_sync)

    e = sub.add_parser("enrich", help="look up real titles for captured links")
    e.set_defaults(fn=cmd_enrich)

    i = sub.add_parser("init", help="scaffold the data repo ($GTD_HOME or --home)")
    i.set_defaults(fn=cmd_init)

    y = sub.add_parser("sync", help="commit, pull, re-render INBOX.md, push")
    y.add_argument("-m", "--message", default="capture")
    y.set_defaults(fn=cmd_sync)

    a = p.parse_args(argv)
    try:
        return a.fn(Store(a.home), a)
    except (KeyError, RuntimeError, ValueError) as e:
        print(f"error: {e.args[0]}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
