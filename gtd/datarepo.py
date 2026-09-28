"""The data repo: a private git repo holding $GTD_HOME, synced across devices.

    gtd init ~/gtd-inbox      # scaffold rules, workflow, README into a clone
    gtd sync                  # commit local captures, pull others, re-render, push
"""
from __future__ import annotations

import subprocess
from importlib import resources
from pathlib import Path

from . import render
from .store import Store

GENERATED = "INBOX.md"
SCAFFOLD = {
    "rules.yaml": "rules.yaml",
    "gitattributes": ".gitattributes",
    "gitignore": ".gitignore",
    "capture.yml": ".github/workflows/capture.yml",
    "README.md": "README.md",
    "CLAUDE.md": "CLAUDE.md",
    "feeds.yaml": "feeds.yaml",
}


def init(home: Path) -> list[str]:
    """Write scaffold files that don't exist yet. Returns the paths written."""
    home.mkdir(parents=True, exist_ok=True)
    written = []
    templates = resources.files("gtd") / "templates"
    for src, dest in SCAFFOLD.items():
        target = home / dest
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text((templates / src).read_text())
            written.append(dest)
    if not (home / ".git").exists():
        _git(home, "init", "-q")
        written.append(".git")
    return written


def _git(home: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    res = subprocess.run(["git", *args], cwd=home, capture_output=True, text=True)
    if check and res.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {res.stderr.strip() or res.stdout.strip()}")
    return res


def _commit_if_changed(home: Path, message: str) -> bool:
    if _git(home, "diff", "--cached", "--quiet", check=False).returncode == 0:
        return False
    _git(home, "commit", "-q", "-m", message)
    return True


def _discard_generated(home: Path) -> None:
    """Throw away local INBOX.md changes (it is always re-rendered after pulling)."""
    _git(home, "reset", "-q", "--", GENERATED, check=False)
    (home / GENERATED).unlink(missing_ok=True)
    _git(home, "checkout", "--", GENERATED, check=False)


def _has_remote(home: Path) -> bool:
    return bool(_git(home, "remote").stdout.strip())


def _pull(home: Path) -> None:
    """Rebase onto the remote branch; a freshly cloned empty repo has none yet."""
    if _git(home, "rev-parse", "--abbrev-ref", "@{u}", check=False).returncode == 0:
        _git(home, "pull", "-q", "--rebase")
        return
    _git(home, "fetch", "-q", "origin")
    branch = _git(home, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    if _git(home, "rev-parse", "--verify", "-q", f"origin/{branch}", check=False).returncode == 0:
        _git(home, "branch", "-q", f"--set-upstream-to=origin/{branch}")
        _git(home, "pull", "-q", "--rebase")


def _push(home: Path) -> bool:
    return _git(home, "push", "-q", "-u", "origin", "HEAD", check=False).returncode == 0


def sync(store: Store, message: str = "capture") -> str:
    """Commit local changes, rebase onto the remote, re-render INBOX.md, push."""
    home = store.home
    if not (home / ".git").exists():
        raise RuntimeError(f"{home} is not a git repo — clone your inbox repo and run `gtd init` there")

    # 1. commit captured items; INBOX.md is regenerated after pulling, so drop local edits of it
    _git(home, "add", "-A")
    _discard_generated(home)
    committed = _commit_if_changed(home, message)

    # 2-4. pull others' captures, re-render the readable inbox, push. If someone
    # pushed in between, drop our generated commit and go round again.
    remote = _has_remote(home)
    rendered = False
    for _ in range(3):
        if remote:
            _pull(home)
        (home / GENERATED).write_text(render.as_markdown(list(store.items())), encoding="utf-8")
        _git(home, "add", GENERATED)
        rendered = _commit_if_changed(home, "render INBOX.md")
        if not remote or _push(home):
            break
        if rendered:
            _git(home, "reset", "-q", "--soft", "HEAD~1")
            _discard_generated(home)
    else:
        raise RuntimeError("push kept failing — run `gtd sync` again")
    return "synced" if (committed or rendered) else "nothing new"
