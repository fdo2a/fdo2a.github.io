# run_lock release — 지우지 않고 `released` 표시로 바꾼다 (2026-10-20)

## 무엇이 있었나

2026-10-19 US 런(`cse_01FGupskMT9rSxeWxvWeFHjN`)은 국채 마감이 안 올라와 쓰지 않고 끝나며
`run_lock.sh release us-2026-10-19` 를 했다. 출력은 「was taken over by another run — left it alone」.

- 22:54 UTC 로컬 세션이 `--force-with-lease=refs/heads/locks/us-2026-10-19:8f46bc4…` 로 지웠고 성공했다.
  원격은 그때까지 **그 런 자신의 잠금(8f46bc4)** 이었다 — 넘겨받은 런은 없었다.
- 레포 activity 로그(9/26-10/20, `refs/heads/locks/*` 129건): **삭제는 그 로컬 1건뿐**, force-push(renew·takeover)
  는 약 93건 통과. 클라우드 루틴의 git 경로는 **ref 삭제 push 만 거부**한다.
- 옛 release 는 push stderr 를 `/dev/null` 로 버리고 실패를 전부 「taken over」로 적었다.
- 결과: 쓰지 않고 끝난 런의 잠금이 원격에 남아 `routine_due.py` 는 BUSY, `acquire` 는 exit 3 —
  stale(US·KR 120분, 주간·일본 240분)까지 재시도가 막힌다. 국채 마감 대기(bdb7f1b) 뒤 포기한 런이
  09:30 KST 재시도를 11:30 까지 밀 수 있었다.

## 결정

| 항목 | 내용 |
|---|---|
| release | ref 삭제 대신 제목 `released <name> <utc> pid <pid> <nonce>` 인 부모 없는 커밋으로 force-with-lease(lease = 우리 SHA). renew 와 같은 push 모양이라 클라우드에서 통과한다 |
| 「잠금 없음」 | ref 가 없거나 끝 커밋 제목이 `released ` 로 시작. `acquire` 는 표시를 lease 로 바로 넘겨받고, `routine_due._lock_age` 는 None(→ DUE) |
| release 종료 코드 | 0 = 풀었다·이미 남의 것·이미 없다, 4 = 원격 확인 실패, **5 = push 거부·잠금이 남았다**. 4·5 는 소유 파일을 남긴다. 오케스트레이터 넷은 4·5 를 조용히 끝내지 말고 PushNotification 으로 보고한다 |
| acquire | lease 실패 뒤 원격 끝을 다시 읽는다 — 그대로면 push 경로의 거부라 exit 4(옛 코드는 3 「another run took over first」), 바뀌었으면 다시 판정(최대 3회) |
| renew | 종료 코드 그대로(실패 = 3 = 쓰지 않는다). 메시지만 「refused (still ours)」와 「no longer ours」로 가른다 |
| nonce | 잠금 커밋에 8바이트 난수 — 다른 컨테이너가 같은 초·같은 pid 로 같은 SHA 를 만들면 둘 다 push 성공으로 보인다 |
| 원격 끝 읽기 | `FETCH_HEAD` 대신 `refs/run_lock/<name>` 로 받아 SHA·제목·시각을 한 커밋에서 읽고, lease 도 그 SHA 로 건다 |

## 하지 않은 것

- 먼저 삭제를 시도하고 실패하면 표시로 내려가는 두 갈래 — 로컬과 클라우드가 다른 길을 탄다.
- 9/26 이후 쌓인 잠금 ref ~34개 정리 — 무해하다. 따로.

## 테스트 (`scripts/common/tests/test_run_lock.py`)

- bare 원격에 `receive.denyDeletes=true` 로 클라우드 거부를 재현한다. 옛 코드에서 「taken over」가 그대로 재현됐다.
- 포기한 런 시나리오: 잡고 → release → `_lock_age` None → `decide_us`·`decide_kr` DUE, 다음 acquire(stale 120) 즉시 0.
- 진짜 경합: pre-receive 훅이 같은 옛 SHA 를 든 lease push 두 개를 붙잡았다 놓는다 — released 표시를 두고 둘이
  경쟁하면 정확히 하나만 0, release 와 stale takeover 가 맞붙으면 어느 순서든 테이커가 잠금을 쥔다(8회 중 5:3 으로 두 순서 모두 관측).
- 거부: 모든 push 를 막는 훅 → release 5·acquire 4, `receive.denyNonFastForwards` → release 5, 원격 없음 → release 4.

## 남은 위험

- **웹훅 되먹임**: 9/26 spec 은 「잠금 브랜치 push 도 웹훅을 부른다」고 적었다. 표시 push 가 런을 띄우면
  acquire → 가드 → release → push 가 돌 수 있다(삭제가 통했어도 같다). 10/7-10/19 실행 목록은 하루 최대 2회로,
  그 사이 잠금 push ~93건이 런을 띄우지 않았다 — 지금은 걸려 있지 않은 것으로 본다. 루틴에 push 웹훅을 다시 걸면 `refs/heads/locks/**` 를 제외한다.
- 옛 코드로 돌던 런은 표시를 살아 있는 잠금으로 읽는다 — 배포 뒤 첫 회차만.
