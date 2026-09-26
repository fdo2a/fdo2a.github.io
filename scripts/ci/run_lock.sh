#!/usr/bin/env bash
# 루틴 선점 잠금 — 같은 날 US 루틴이 여러 개 떠도 작성은 하나만 한다.
#
#   bash scripts/ci/run_lock.sh acquire us-2026-09-26 [stale_minutes=180]
#     exit 0  잠금을 잡았다 → 진행
#     exit 3  다른 런이 잡고 있다(신선함) → 아무것도 하지 말고 끝낸다
#     exit 4  원격을 확인하지 못했다 → 진행하지 않는다(안전 쪽)
#   bash scripts/ci/run_lock.sh release us-2026-09-26
#
# 원리: `refs/heads/locks/<name>` 을 부모 없는 빈 커밋으로 만든다. 같은 이름의 ref 는 한 번만
# 생긴다 — 둘째 런의 push 는 non-fast-forward 로 거절된다. 잡은 런이 한도로 죽으면 잠금이
# 남으므로, stale_minutes 가 지난 잠금은 --force-with-lease 로 원자적으로 넘겨받는다
# (두 런이 동시에 넘겨받으려 해도 하나만 이긴다).
#
# 왜: 2026-09-26 US 루틴이 푸시 웹훅으로 새벽에 10번 떴고 넷이 동시에 작성했다. 기존 가드는
# 중복 「발행」만 막고 병렬 「작성」은 못 막아, 넷이 5시간 한도를 함께 태웠다.
set -u
cmd=${1:?acquire|release}
name=${2:?lock name}
stale=${3:-180}
ref="refs/heads/locks/${name}"
remote=${RUN_LOCK_REMOTE:-origin}

case "$cmd" in
acquire)
  tree=$(git mktree </dev/null) || exit 4
  sha=$(git -c user.name=routine-lock -c user.email=routine-lock@users.noreply.github.com \
        commit-tree "$tree" -m "lock ${name} $(date -u +%FT%TZ) pid $$") || exit 4
  if git push -q "$remote" "${sha}:${ref}" 2>/dev/null; then
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
      echo "run_lock: took over ${name} (previous holder silent for ${age} min)"
      exit 0
    fi
    echo "run_lock: another run took over ${name} first — stop"
    exit 3
  fi
  echo "run_lock: ${name} held by another run for ${age} min — stop"
  exit 3
  ;;
release)
  git push -q "$remote" ":${ref}" 2>/dev/null
  echo "run_lock: released ${name}"
  exit 0
  ;;
*)
  echo "usage: run_lock.sh acquire|release <name> [stale_minutes]" >&2
  exit 2
  ;;
esac
