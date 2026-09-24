#!/usr/bin/env bash
# Block until one GitHub Actions run finishes — in ONE tool call.
#
# Routines used to wait with Monitor/ScheduleWakeup, which wakes the session every
# 10–20 s and re-sends the whole context each time (2026-09-21 China run: dozens of
# turns just to learn "still in progress"). Call this with the Bash tool's timeout
# raised to 600000 ms; if a shorter tool timeout kills it, call it again.
#
#   bash scripts/ci/wait_run.sh RUN_ID [max_seconds=540]
#
# exit 0 = completed/success · 1 = completed, not success · 2 = still running at
# max_seconds · 3 = cannot query (no token, bad run id)
set -u
RUN=${1:?usage: wait_run.sh RUN_ID [max_seconds]}
MAX=${2:-540}
REPO=${GITHUB_REPOSITORY:-fdo2a/fdo2a.github.io}
TOKEN=${GH_TOKEN:-${GITHUB_TOKEN:-}}
[ -n "$TOKEN" ] || { echo "wait_run: no GH_TOKEN/GITHUB_TOKEN" >&2; exit 3; }
END=$(( $(date +%s) + MAX ))
while :; do
  STATE=$(curl -sS --max-time 20 -H "Authorization: token $TOKEN" \
      -H "Accept: application/vnd.github+json" \
      "https://api.github.com/repos/$REPO/actions/runs/$RUN" 2>/dev/null |
    python3 -c 'import json,sys
try:
    d = json.load(sys.stdin)
except ValueError:
    d = {}
if not isinstance(d, dict) or "id" not in d:   # an error body, not a run
    d = {}
print(d.get("status") or "unknown", d.get("conclusion") or "none")')
  STATUS=${STATE% *}; CONCLUSION=${STATE#* }
  if [ "$STATUS" = completed ]; then
    echo "run $RUN completed: $CONCLUSION"
    [ "$CONCLUSION" = success ] && exit 0 || exit 1
  fi
  if [ "$STATUS" = unknown ]; then
    FAILS=$(( ${FAILS:-0} + 1 ))    # consecutive unreadable answers
    [ "$FAILS" -ge 4 ] && { echo "wait_run: cannot read run $RUN" >&2; exit 3; }
  else
    FAILS=0
  fi
  [ "$(date +%s)" -ge "$END" ] && { echo "run $RUN still $STATUS after ${MAX}s"; exit 2; }
  /bin/sleep 15
done
