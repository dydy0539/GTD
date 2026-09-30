#!/usr/bin/env bash
# Wait (at most 25 min, to stay under background time limits) for the next
# :15 / :45 UTC check; then report whether a capture run added new items.
#   scripts/wait-for-capture.sh [DATA_DIR]
#   → "NEW <n>" (new items captured), "UNCHANGED" (nothing new), or "WAIT" (check not reached yet)
DATA=${1:-/home/user/gtd-inbox}
base=$(git -C "$DATA" rev-parse HEAD)
m=$(date -u +%-M); s=$(date -u +%-S)
if [ "$m" -lt 15 ]; then w=$(( (15-m)*60 - s )); elif [ "$m" -lt 45 ]; then w=$(( (45-m)*60 - s )); else w=$(( (75-m)*60 - s )); fi
if [ "$w" -gt 1500 ]; then sleep 1500; echo WAIT; exit 0; fi
sleep "$w"
git -C "$DATA" fetch -q origin main 2>/dev/null
new=$(git -C "$DATA" diff --name-only --diff-filter=A "$base" FETCH_HEAD -- stuff 2>/dev/null | grep -c '/item\.md$')
if [ "${new:-0}" -gt 0 ]; then echo "$(date -u +%H:%M) NEW $new"; else echo "$(date -u +%H:%M) UNCHANGED"; fi
