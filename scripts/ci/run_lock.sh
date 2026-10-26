#!/usr/bin/env bash
# 루틴 선점 잠금 — 같은 세션의 US 루틴이 여러 개 떠도 작성은 하나만 한다.
#
#   KEY=$(bash scripts/ci/run_lock.sh key us)        # us-<세션 날짜>
#   bash scripts/ci/run_lock.sh acquire "$KEY" [stale_minutes=180]
#     exit 0  잡았다 → 진행   exit 3  다른 런이 잡고 있다 → 끝낸다
#     exit 4  원격 확인 실패·push 거부 → 진행 안 함
#   bash scripts/ci/run_lock.sh renew "$KEY"          # 살아 있다는 표시(오래 걸리는 단계 앞에서)
#     exit 0  갱신   exit 3  더는 우리 잠금이 아니거나 갱신이 거부·실패했다 → 쓰지 말고 끝낸다
#   bash scripts/ci/run_lock.sh release "$KEY"        # 자기가 잡은 잠금만 푼다
#     exit 0  풀었다·이미 남의 것·이미 없다   exit 4  확인 실패(원격·로컬)   exit 5  push 거부 — 잠금이 남았다
#     (4·5 는 재시도 루틴을 stale 까지 막는다 — 조용히 끝내지 말고 보고한다)
#
# 원리: `refs/heads/locks/<name>` 을 부모 없는 빈 커밋으로 만든다. 같은 이름의 ref 는 한 번만
# 생긴다. 잡은 커밋 SHA 를 .git/run_lock_<name> 에 적어 두고, renew·release 는 그 SHA 에 대한
# --force-with-lease 로만 움직인다 — 남이 넘겨받은 잠금을 지우거나 덮지 못한다(codex #2).
# stale_minutes 는 **마지막 갱신** 이후 시간이다(codex #1).
#
# **release 는 ref 를 지우지 않는다.** 제목이 `released ` 로 시작하는 빈 커밋으로 바꾼다 — 클라우드
# 루틴의 git 경로는 ref 삭제 push 를 거부하고(2026-10-19 US 런, 9/26 이후 삭제는 로컬 1건뿐)
# 갱신 push 는 통과시킨다. acquire 와 routine_due.py 는 released 표시를 「잠금 없음」으로 본다.
# 설계: docs/superpowers/specs/2026-10-20-run-lock-release-marker.md
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
  # 규칙은 routine_due.py 한 곳에 있다 — 재시도 루틴이 확인하는 이름과 어긋나면 살아 있는
  # 런을 못 보고 겹쳐 뜬다. us = 뉴욕 −17h, kr = 서울 −16h, jp_daily = 도쿄 −15h30m.
  prefix=${2:?prefix}
  exec python3 "$(dirname "$0")/routine_due.py" lock-name "$prefix"
fi

name=${2:?lock name}
stale=${3:-180}
ref="refs/heads/locks/${name}"
gitdir=$(git rev-parse --git-dir) || exit 4
own="${gitdir}/run_lock_${name}"
seen="refs/run_lock/${name}"     # 원격 끝을 받아 두는 로컬 ref — FETCH_HEAD 는 다른 fetch 와 섞인다
push_err= read_err=              # set -u: 실패 경로가 읽기 전에 늘 정의돼 있어야 한다

new_commit() {
  # $1 = lock | released. nonce: 서로 다른 컨테이너가 같은 초·같은 pid 로 같은 SHA 를 만들면
  # 둘 다 push 에 성공한 것으로 보인다(codex 설계 검토 #4).
  local tree nonce
  tree=$(git mktree </dev/null) || return 1
  nonce=$(od -An -N8 -tx1 /dev/urandom 2>/dev/null | tr -d ' \n')
  [ -n "$nonce" ] || nonce="${RANDOM}${RANDOM}${RANDOM}"
  git -c user.name=routine-lock -c user.email=routine-lock@users.noreply.github.com \
    commit-tree "$tree" -m "$1 ${name} $(date -u +%FT%TZ) pid $$ ${nonce}"
}

read_tip() {
  # 원격 잠금의 지금 끝 → tip(없으면 빈 값)·tip_subject·tip_time. 확인 못 하면 1.
  # lease 는 제목을 읽은 바로 그 커밋으로 건다(ls-remote 와 fetch 사이에 움직였을 수 있다).
  # 같은 클론의 다른 호출이 $seen 을 덮을 수 있으니 SHA 를 먼저 고정하고 그 커밋에서만 읽는다.
  local out
  tip= tip_subject= tip_time= read_err=
  out=$(git ls-remote "$remote" "$ref" 2>&1) || { read_err=$out; return 1; }
  [ -n "$(printf '%s\n' "$out" | awk -v r="$ref" '$2 == r')" ] || return 0
  out=$(git fetch -q "$remote" "+${ref}:${seen}" 2>&1) || { read_err=$out; return 1; }
  out=$(git rev-parse --verify -q "${seen}^{commit}" 2>&1) || { read_err="cannot resolve ${seen}"; tip=; return 1; }
  tip=$out
  out=$(git log -1 --format='%ct %s' "$tip" 2>&1) || { read_err=$out; tip=; return 1; }
  tip_time=${out%% *}
  tip_subject=${out#* }
}

read_own() {
  # 소유 파일의 SHA. 못 읽거나 SHA 가 아니면 1 — 빈 lease 로 push 하면 실패를 「taken over」로 읽게 된다.
  mine=$(cat "$own" 2>/dev/null) || return 1
  case "$mine" in
  *[!0-9a-f]* | '') return 1 ;;
  esac
  [ ${#mine} -eq 40 ] || [ ${#mine} -eq 64 ]
}

say_err() { [ -n "${1:-}" ] && printf '%s\n' "$1" | sed 's/^/  git: /' >&2; return 0; }

case "$cmd" in
acquire)
  sha=$(new_commit lock) || { echo "run_lock: cannot build a lock commit — not proceeding" >&2; exit 4; }
  # 원격이 움직이면(누가 먼저 넘겨받았다·풀었다) 다시 본다. 세 번이면 경합 중이니 물러난다.
  for attempt in 1 2 3; do
    if push_err=$(git push -q "$remote" "${sha}:${ref}" 2>&1); then
      echo "$sha" >"$own"
      echo "run_lock: acquired ${name}"
      exit 0
    fi
    if ! read_tip; then
      echo "run_lock: cannot read ${name} on ${remote} — not proceeding" >&2
      say_err "$push_err"; say_err "$read_err"
      exit 4
    fi
    if [ -z "$tip" ]; then
      [ "$attempt" -lt 3 ] && continue
      echo "run_lock: push failed and no lock exists — cannot tell, not proceeding" >&2
      say_err "$push_err"
      exit 4
    fi
    case "$tip_subject" in
    released\ *) why="previous run released it" ;;
    *)
      age=$(( ($(date +%s) - tip_time) / 60 ))
      if [ "$age" -lt "$stale" ]; then
        echo "run_lock: ${name} held by another run (last sign of life ${age} min ago) — stop"
        exit 3
      fi
      why="holder silent for ${age} min"
      ;;
    esac
    if push_err=$(git push -q --force-with-lease="${ref}:${tip}" "$remote" "${sha}:${ref}" 2>&1); then
      echo "$sha" >"$own"
      case "$why" in
      previous*) echo "run_lock: acquired ${name} (${why})" ;;
      *) echo "run_lock: took over ${name} (${why})" ;;
      esac
      exit 0
    fi
    expected=$tip
    if ! read_tip; then
      echo "run_lock: cannot read ${name} after a refused push — not proceeding" >&2
      say_err "$push_err"; say_err "$read_err"
      exit 4
    fi
    if [ "$tip" = "$expected" ]; then
      # 아무도 움직이지 않았는데 거부됐다 — 경합이 아니라 push 경로의 거부다(codex 설계 검토 #2).
      echo "run_lock: push refused for ${name} (remote unchanged) — not proceeding" >&2
      say_err "$push_err"
      exit 4
    fi
  done
  echo "run_lock: ${name} kept moving under another run — stop"
  exit 3
  ;;
renew)
  [ -f "$own" ] || { echo "run_lock: this clone does not hold ${name}" >&2; exit 3; }
  read_own || { echo "run_lock: cannot read ${own} — stop writing" >&2; exit 3; }
  sha=$(new_commit lock) || { echo "run_lock: cannot build a renew commit for ${name} — stop writing" >&2; exit 3; }
  if push_err=$(git push -q --force-with-lease="${ref}:${mine}" "$remote" "${sha}:${ref}" 2>&1); then
    echo "$sha" >"$own"
    echo "run_lock: renewed ${name}"
    exit 0
  fi
  # 어느 쪽이든 쓰지 않는다(exit 3). 메시지만 갈라 둔다.
  if read_tip && [ "$tip" = "$mine" ]; then
    echo "run_lock: renew of ${name} was refused (still ours, not renewed) — stop writing" >&2
    say_err "$push_err"
  else
    echo "run_lock: ${name} is no longer ours — stop writing" >&2
  fi
  exit 3
  ;;
release)
  [ -f "$own" ] || { echo "run_lock: this clone does not hold ${name} — nothing released"; exit 0; }
  read_own || { echo "run_lock: cannot read ${own} — NOT released" >&2; exit 4; }
  sha=$(new_commit released) || { echo "run_lock: cannot build a release commit for ${name} — NOT released" >&2; exit 4; }
  if push_err=$(git push -q --force-with-lease="${ref}:${mine}" "$remote" "${sha}:${ref}" 2>&1); then
    rm -f "$own"
    echo "run_lock: released ${name}"
    exit 0
  fi
  if ! read_tip; then
    echo "run_lock: release push for ${name} failed and the remote cannot be read — NOT released" >&2
    say_err "$push_err"; say_err "$read_err"
    exit 4
  fi
  if [ "$tip" = "$sha" ]; then
    # push 는 적용됐는데 클라이언트가 실패로 받았다.
    rm -f "$own"
    echo "run_lock: released ${name}"
  elif [ -z "$tip" ]; then
    rm -f "$own"
    echo "run_lock: ${name} is already gone — nothing to release"
  elif [ "$tip" = "$mine" ]; then
    echo "run_lock: release push for ${name} was refused (remote still holds our lock) — NOT released" >&2
    say_err "$push_err"
    exit 5
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
