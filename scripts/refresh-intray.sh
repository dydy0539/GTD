#!/usr/bin/env bash
# Bring the In-tray page up to date with the data repo.
#
#   scripts/refresh-intray.sh OUT_DIR [DECISIONS_JSON]
#
# Clones/pulls the data repo, applies triage decisions exported from the page
# (if given) and pushes them, then renders OUT_DIR/gtd-in-tray.html.
# Prints CHANGED when the page's items differ from the last published copy
# (recorded with `scripts/refresh-intray.sh OUT_DIR --published`), else UNCHANGED.
set -euo pipefail
OUT=$1
CODE=$(cd "$(dirname "$0")/.." && pwd)
DATA=${GTD_DATA:-/home/user/gtd-inbox}
export GTD_HOME=$DATA PYTHONPATH=$CODE

if [ "${2:-}" = "--published" ]; then
  mv "$OUT/.pending" "$OUT/.published"
  exit 0
fi

[ -d "$DATA/.git" ] || git clone -q https://github.com/dydy0539/gtd-inbox "$DATA"
git -C "$DATA" pull -q --rebase origin main

if [ -n "${2:-}" ]; then
  python3 -m gtd.cli decide "$2"
  if [ -n "$(git -C "$DATA" status --porcelain)" ]; then
    git -C "$DATA" add -A
    git -C "$DATA" commit -q -m "Apply In-tray page decisions"
  fi
  python3 -m gtd.cli sync -m render >/dev/null
fi

mkdir -p "$OUT"
python3 -m gtd.cli render -o "$OUT" --page "$OUT/gtd-in-tray.html" | sed 's/.*(\(.*\) items)/\1 in the in-tray/'
python3 - "$OUT" <<'PY'
import hashlib, json, re, sys
from pathlib import Path
out = Path(sys.argv[1])
page = (out / "gtd-in-tray.html").read_text(encoding="utf-8")
data = json.loads(re.search(r'id="data">(.*?)</script>', page, re.S).group(1).replace("<\\/", "</"))
data.pop("generated", None)  # the items and where you are, not the time of rendering
digest = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
old = (out / ".published").read_text().strip() if (out / ".published").exists() else ""
(out / ".pending").write_text(digest)
print("UNCHANGED" if digest == old else "CHANGED")
PY
