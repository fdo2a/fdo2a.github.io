#!/usr/bin/env bash
# Japan daily starts right after the KR brief lands (user instruction 2026-10-27) — in ONE tool call.
#
# Polls `routine_due.py kr` once a minute. DONE means the KR post for KR's session is on
# origin/main — on a Korean holiday KR's session is an earlier, already-published day, so
# DONE comes back at once and Japan does not wait for a post that will never come.
# Call it with the Bash tool's timeout raised to 600000 ms; the orchestrator repeats it.
#
#   bash scripts/ci/wait_for_kr.sh [max_seconds=540]
#
# exit 0 = KR published (prints the DONE line) · 2 = still not published at max_seconds
set -u
MAX=${1:-540}
DUE=${ROUTINE_DUE:-python3 scripts/ci/routine_due.py}
STEP=${WAIT_STEP:-60}
END=$(( $(date +%s) + MAX ))
while :; do
  LINE=$($DUE kr 2>/dev/null | head -n 1)
  case "$LINE" in
    DONE*) echo "$LINE"; exit 0 ;;
  esac
  [ "$(date +%s)" -lt "$END" ] || { echo "KR 아직 미발행: ${LINE:-판정 실패}"; exit 2; }
  /bin/sleep "$STEP"
done
