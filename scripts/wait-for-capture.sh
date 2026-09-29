#!/usr/bin/env bash
# Wait (at most 25 min, to stay under background time limits) for the next
# :15 / :45 UTC check; then report whether the data repo moved since BASE.
#   scripts/wait-for-capture.sh [DATA_DIR]   → prints CHANGED, UNCHANGED or WAIT
DATA=${1:-/home/user/gtd-inbox}
base=$(git -C "$DATA" rev-parse HEAD)
m=$(date -u +%-M); s=$(date -u +%-S)
if [ "$m" -lt 15 ]; then w=$(( (15-m)*60 - s )); elif [ "$m" -lt 45 ]; then w=$(( (45-m)*60 - s )); else w=$(( (75-m)*60 - s )); fi
if [ "$w" -gt 1500 ]; then sleep 1500; echo WAIT; exit 0; fi
sleep "$w"
remote=$(git ls-remote https://github.com/dydy0539/gtd-inbox refs/heads/main | cut -f1)
[ "$remote" != "$base" ] && echo "$(date -u +%H:%M) CHANGED" || echo "$(date -u +%H:%M) UNCHANGED"
