#!/usr/bin/env bash
# 스테이징된 수집분을 커밋하고, 다른 워크플로와 겹쳐도 지지 않게 밀어 넣는다.
#
# 왜 있는가 — 2026-08-27부터 GitHub 스케줄러가 예약 실행을 2~5시간씩 밀어내면서,
# 몇 시간씩 떨어져 있던 수집 워크플로들이 같은 몇 분 안에 밀려 나오기 시작했다.
# 맨 `git push` 는 그 순간 원격이 앞서 있으면 그대로 죽고, 그 실행이 모은 데이터는
# 러너와 함께 버려진다. 실제 실패 — 09-01 US·09-02 KR·09-03 KR,
# 전부 `! [rejected] main -> main (fetch first)`.
#
# 쓰는 법: 파일을 `git add` 한 뒤 `bash scripts/ci/push_with_retry.sh "커밋 메시지"`.
# 스테이징된 변경이 없으면 조용히 0으로 끝난다(그 자체는 정상이다).
#
# **재시도는 push 거절에만 건다.** rebase 충돌·인증 실패·네트워크 실패를 다시 밀어
# 봐야 같은 곳에서 죽고, 충돌은 `.git/rebase-merge` 를 남겨 다음 네 번의 pull 까지
# 같은 이유로 죽인 뒤 「원격이 앞서 있다」는 엉뚱한 사인을 남긴다. 그래서 pull 이
# 실패하면 진행 중인 rebase 를 되돌리고 그 자리에서 끝낸다 — 다음 수집이 다시 만든다.
set -uo pipefail

msg="${1:?커밋 메시지가 필요하다}"
sleep_unit="${PUSH_RETRY_SLEEP:-5}"

abort_rebase_if_any() {
  local d
  d="$(git rev-parse --git-path rebase-merge)"
  local e
  e="$(git rev-parse --git-path rebase-apply)"
  if [ -d "$d" ] || [ -d "$e" ]; then
    echo "rebase 중간 상태를 되돌린다" >&2
    git rebase --abort || true
  fi
}

if git diff --cached --quiet; then
  echo "변경 없음 — 커밋 생략"
  exit 0
fi

git commit -m "$msg" || exit 1

for attempt in 1 2 3 4 5; do
  # --autostash: 수집 스크립트가 남긴 스테이징 안 된 파일이 rebase 를 막지 않게.
  if ! git pull --rebase --autostash; then
    abort_rebase_if_any
    echo "pull --rebase 실패 — 충돌이거나 원격에 닿지 못했다. 재시도하지 않는다." >&2
    exit 1
  fi
  if git push; then
    exit 0
  fi
  if [ "$attempt" -lt 5 ]; then
    echo "push 거절 ${attempt}/5 — 그 사이 원격이 또 앞서 나갔다. 다시 rebase 한다." >&2
    sleep $((attempt * sleep_unit))
  fi
done

echo "push 실패 — 5회 재시도 동안 원격이 계속 앞서 있었다." >&2
exit 1
