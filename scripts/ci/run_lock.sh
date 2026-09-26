#!/usr/bin/env bash
# 루틴 선점 잠금 — 같은 세션의 US 루틴이 여러 개 떠도 작성은 하나만 한다.
#
#   KEY=$(bash scripts/ci/run_lock.sh key us)        # us-<세션 날짜>
#   bash scripts/ci/run_lock.sh acquire "$KEY" [stale_minutes=180]
#     exit 0  잡았다 → 진행   exit 3  다른 런이 잡고 있다 → 끝낸다   exit 4  원격 확인 실패 → 진행 안 함
#   bash scripts/ci/run_lock.sh renew "$KEY"          # 살아 있다는 표시(오래 걸리는 단계 앞에서)
#   bash scripts/ci/run_lock.sh release "$KEY"        # 자기가 잡은 잠금만 푼다
#
# 원리: `refs/heads/locks/<name>` 을 부모 없는 빈 커밋으로 만든다. 같은 이름의 ref 는 한 번만
# 생긴다. 잡은 커밋 SHA 를 .git/run_lock_<name> 에 적어 두고, renew·release 는 그 SHA 에 대한
# --force-with-lease 로만 움직인다 — 남이 넘겨받은 잠금을 지우거나 덮지 못한다(codex #2).
# stale_minutes 는 **마지막 갱신** 이후 시간이다(codex #1).
#
# 키(codex #3): 뉴욕 시각에서 17시간을 뺀 날짜 = 그 시각까지 끝났을 수 있는 가장 최근 세션.
# KST 자정을 넘겨도 같은 세션은 같은 이름이다.
#
# 왜: 2026-09-26 US 루틴이 푸시 웹훅으로 새벽에 10번 떴고 넷이 동시에 작성하다 5시간 한도를
# 함께 태웠다. 설계: docs/superpowers/specs/2026-09-26-routine-lock-and-news-freeze.md
set -u
cmd=${1:?key|acquire|renew|release}
remote=${RUN_LOCK_REMOTE:-origin}

if [ "$cmd" = key ]; then
  prefix=${2:?prefix}
  python3 - "$prefix" <<'PY'
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
now = datetime.now(ZoneInfo('America/New_York'))
print(f"{sys.argv[1]}-{(now - timedelta(hours=17)).date().isoformat()}")
PY
  exit 0
fi

name=${2:?lock name}
stale=${3:-180}
ref="refs/heads/locks/${name}"
gitdir=$(git rev-parse --git-dir) || exit 4
own="${gitdir}/run_lock_${name}"

new_commit() {
  local tree
  tree=$(git mktree </dev/null) || return 1
  git -c user.name=routine-lock -c user.email=routine-lock@users.noreply.github.com \
    commit-tree "$tree" -m "lock ${name} $(date -u +%FT%TZ) pid $$"
}

case "$cmd" in
acquire)
  sha=$(new_commit) || exit 4
  if git push -q "$remote" "${sha}:${ref}" 2>/dev/null; then
    echo "$sha" >"$own"
    echo "run_lock: acquired ${name}"
    exit 0
  fi
  old=$(git ls-remote "$remote" "$ref" 2>/dev/null | cut -f1)
  if [ -z "$old" ]; then
    echo "run_lock: push failed and no lock exists — cannot tell, not proceeding" >&2
    exit 4
  fi
  git fetch -q "$remote" "$ref" 2>/dev/null || exit 4
  born=$(git log -1 --format=%ct FETCH_HEAD) || exit 4
  age=$(( ($(date +%s) - born) / 60 ))
  if [ "$age" -ge "$stale" ]; then
    if git push -q --force-with-lease="${ref}:${old}" "$remote" "${sha}:${ref}" 2>/dev/null; then
      echo "$sha" >"$own"
      echo "run_lock: took over ${name} (holder silent for ${age} min)"
      exit 0
    fi
    echo "run_lock: another run took over ${name} first — stop"
    exit 3
  fi
  echo "run_lock: ${name} held by another run (last sign of life ${age} min ago) — stop"
  exit 3
  ;;
renew)
  [ -f "$own" ] || { echo "run_lock: this clone does not hold ${name}" >&2; exit 3; }
  mine=$(cat "$own")
  sha=$(new_commit) || exit 4
  if git push -q --force-with-lease="${ref}:${mine}" "$remote" "${sha}:${ref}" 2>/dev/null; then
    echo "$sha" >"$own"
    echo "run_lock: renewed ${name}"
    exit 0
  fi
  echo "run_lock: ${name} is no longer ours — stop writing" >&2
  exit 3
  ;;
release)
  [ -f "$own" ] || { echo "run_lock: this clone does not hold ${name} — nothing released"; exit 0; }
  mine=$(cat "$own")
  if git push -q --force-with-lease="${ref}:${mine}" "$remote" ":${ref}" 2>/dev/null; then
    rm -f "$own"
    echo "run_lock: released ${name}"
  else
    rm -f "$own"
    echo "run_lock: ${name} was taken over by another run — left it alone"
  fi
  exit 0
  ;;
*)
  echo "usage: run_lock.sh key <prefix> | acquire|renew|release <name> [stale_minutes]" >&2
  exit 2
  ;;
esac
