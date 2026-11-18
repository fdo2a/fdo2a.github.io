#!/usr/bin/env bash
# 수집 잡이 실패했을 때 국채 16:00 ET 원장(data/yields_1600.json)만 따로 보존한다(2026-11-07).
#
# 원장은 다음 날의 전일比·1주 전 정본이라 그날 값을 잃으면 다음 날 발행이 막힌다. 그런데 실패한 잡의
# 작업 트리에는 미커밋·스테이징된 다른 수집 산출물이 섞여 있고, 로컬 커밋이 push 되지 못했을 수도 있다
# (codex 구현 검토 2회 #2-#4). 그래서 **origin/main 의 깨끗한 worktree** 에서 원격 원장에 이 실행의
# 원장을 `yield_cut.record` 규칙으로 합치고(네이버 기록은 덮지 않는다) 그 파일 하나만 커밋·push 한다.
#
#   bash scripts/ci/preserve_yields_ledger.sh [data/yields_1600.json]
#
# 재시도는 거절된 push 에만 의미가 있다 — 매 회 fetch 로 새 origin/main 에서 다시 합친다.
set -euo pipefail
SRC="${1:-data/yields_1600.json}"
[ -f "$SRC" ] || { echo "preserve_yields_ledger: $SRC 없음 — 할 일 없음"; exit 0; }
REPO="$(git rev-parse --show-toplevel)"
TMP="$(mktemp -d)"
cp "$SRC" "$TMP/local.json"
SLEEP="${PUSH_RETRY_SLEEP:-5}"
trap 'git -C "$REPO" worktree remove --force "$TMP/wt" >/dev/null 2>&1 || true; rm -rf "$TMP"' EXIT
for i in 1 2 3 4; do
  git -C "$REPO" worktree remove --force "$TMP/wt" >/dev/null 2>&1 || true
  git -C "$REPO" fetch -q origin main
  git -C "$REPO" worktree add -q --detach "$TMP/wt" origin/main
  mkdir -p "$TMP/wt/data"
  python3 "$REPO/scripts/us/yield_cut.py" merge "$TMP/wt/data/yields_1600.json" "$TMP/local.json"
  if [ ! -f "$TMP/wt/data/yields_1600.json" ]; then
    echo "preserve_yields_ledger: 원격에도 이 실행에도 원장 내용이 없다"
    exit 0
  fi
  git -C "$TMP/wt" add data/yields_1600.json
  if git -C "$TMP/wt" diff --cached --quiet; then
    echo "preserve_yields_ledger: 원격 원장이 이미 이 실행의 값을 담고 있다"
    exit 0
  fi
  git -C "$TMP/wt" -c user.name='github-actions[bot]' \
      -c user.email='github-actions[bot]@users.noreply.github.com' \
      commit -q -m "data: yields 16:00 ET ledger (preserved after a failed collection)"
  if git -C "$TMP/wt" push -q origin HEAD:main; then
    echo "preserve_yields_ledger: pushed"
    exit 0
  fi
  echo "preserve_yields_ledger: push rejected (attempt $i) — 새 origin/main 에서 다시 합친다" >&2
  sleep $((SLEEP * i))
done
echo "preserve_yields_ledger: 4회 모두 실패" >&2
exit 1
