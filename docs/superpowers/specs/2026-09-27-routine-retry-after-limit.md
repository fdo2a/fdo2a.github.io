# 한도 해제 뒤 재시작 — 재시도 루틴 (2026-09-27)

## 지시와 계기

사용자: 「한도가 풀린뒤 재시작하는 장치를 추가해」. 9/25 US 런이 브리프를 발행하고(16:19Z) 1분 뒤 STEP 3.5
(뉴스·산업 브리프)에서 `rate_limit: rejected (five_hour)` 로 죽었다. 다시 띄울 장치가 없었고, 손으로 다시 돌려도
STEP 0-1 가드가 「already published」로 멈춰 STEP 3.5 에 닿지 못했다. 그 전까지는 일회성 Resume 트리거를 손으로
만들었다(9/23·9/24).

## 구조

- **본 루틴은 그대로** 두고 **재시도 루틴**을 따로 둔다(푸시 웹훅이 붙지 않는다). 3시간 간격 — 5시간 창 안에서 두 번은
  기회가 온다.
  - US: `30 2,5,8,11,14,17,20 * * 2-6` UTC (11:30 … 다음날 05:30 KST)
  - KR: `0 0,3,6,12,15,18,21 * * 1-6` UTC (21:00 … 다음날 15:00 KST)
  - 주간: `0 9,12,15,18,21 * * 6` UTC (토 18:00 … 일 06:00 KST) — 본 런(토 15:00 KST)보다 먼저 뜨지 않는다.
- 재시도 프롬프트의 첫 단계는 `python3 scripts/ci/routine_due.py <us|kr|weekly>` 다. `DUE` 가 아니면
  **오케스트레이터를 읽지 않고** 끝난다 — 할 일이 없는 재시도가 오케스트레이터를 읽으면 그것이 한도를 태운다.
- `DUE` 면 본 루틴 프롬프트와 같은 일을 한다. 잠금·가드는 오케스트레이터가 다시 판정한다.

## routine_due 판정

1. **기대 세션을 먼저 정한다** — US 뉴욕 −17h, KR 서울 −16h에서 주말과 **휴장일 달력**(`data/market_holidays.json`)을
   거슬러 올라간 마지막 거래일. 주간은 그 US 세션의 ISO 주. 데이터에 적힌 날짜로 DONE 을 정하면 수집이 밀린 날
   어제 글을 보고 끝나 오늘 글이 영영 안 나온다(설계 검토 #1).
2. 그 세션의 글이 다 있으면 `DONE`. US 는 `posts/` 와 `news/` 둘 다, KR 은 `kr/posts/`, 주간은 US·KR 둘 다.
3. 그 세션 키의 잠금이 stale 기준(US·KR 120분, 주간 180분)보다 젊으면 `BUSY`. 아니면 `DUE` — 최종 선점은
   `run_lock.sh acquire` 다.
4. 주간은 **남은 시장의** 집계가 없거나 불완전하면 `WAIT` — 주간 루틴은 집계를 다시 만들지 않는다.
5. fetch 실패는 `DUE` — 틀려도 오케스트레이터 가드가 막는다. DONE 으로 보내면 글이 조용히 빠진다.

**휴장은 달력으로만 판정한다.** 첫 구현은 「기대 세션 18:00 뒤 수집기 커밋이 있는데 데이터가 이전」을 휴장으로
봤는데, 시세가 늦게 붙은 거래일도 같은 모양이라 글을 조용히 건너뛴다(구현 검토 #2). 달력에 없는 휴장일은 DUE 로
떨어져 재시도가 헛돌 뿐이고, 거래일을 잘못 넣으면 그날 글이 빠지므로 **거래소 공지로 확인한 날만** 넣는다.
US 는 NYSE 2026·2027, KR 은 2026(2027 은 대체공휴일 공고 전). 임시공휴일이 지정되면 추가한다.

잠금 이름 규칙은 `routine_due.lock_name` 한 곳에 있고 `run_lock.sh key` 가 그것을 부른다.

## 재시도 트리거 프롬프트

본 루틴과 같은 환경·모델·도구로 만든다. 프롬프트는 판정 단계 뒤에 **본 루틴 프롬프트 원문**을 붙인다:

> You are the RETRY run for <the daily US morning brief | the daily KR evening brief | the weekly US + KR recap>.
> It fires every 3 hours after the main run and exists only to finish work that a usage limit cut short.
> Step 1 — in the repository, run exactly: `git pull -q origin main; python3 scripts/ci/routine_due.py <us|kr|weekly>`
> and read its single output line. Step 2 — unless that line starts with `DUE`, stop now: do not read any other file,
> do not run anything else, do not send a PushNotification; reply with the line and end. Stop the same way if the
> script is missing or fails. Step 3 — only on `DUE`, do exactly what the main routine does: <본 루틴 프롬프트 원문>

## 오케스트레이터 변경

- US STEP 0-1: 브리프만 있고 뉴스 글이 없으면 STEP 3.5 만 — 입력은 브리프 발행 커밋에서 복원(codex #3).
  `research_notes.md` 는 사라졌으므로 ③·④ 업계 뉴스 층은 비운다(작성자 지시문이 허용한다).
- KR STEP 0: 잠금(`kr-<서울 −16h>`)·멱등 가드·커밋 직전 재확인 신설(codex #4).
- 주간 STEP 0: 잠금(`weekly-<KEY>`, 작성 전·커밋 전 갱신)·둘 다 있으면 종료·하나만 있으면 남은 시장만(집계도 남은 쪽만).
- 커밋 직전 재확인은 `pull` 이 아니라 `fetch` + `git cat-file -e` — 작업 중 변경과 충돌하지 않는다. push 거절 뒤
  목록·sitemap 충돌은 원격 판을 받고 이 날짜 항목만 다시 넣는다(구현 검토 #7).
- US 복원 명령은 뉴스 파일이 없을 때 빈 파일을 남기지 않는다(`|| rm -f`, 구현 검토 #5).

## 비용

할 일이 없는 재시도는 시스템 프롬프트 + 짧은 프롬프트 + 명령 두 번이다. 주당 US 35·KR 42·주간 5회.
실측 전 추정이며, 비싸면 간격을 늘린다(4시간 이상은 5시간 창 안에서 한 번뿐이라 복구가 하루 밀릴 수 있다).

## 검토 안 된 가정

- 로컬 Claude 세션과 클라우드 루틴이 같은 5시간 창을 쓰는지는 확인하지 않았다.
- 한도가 풀리지 않은 채 뜬 재시도는 첫 모델 호출에서 죽는다(토큰 없음) — 9/26 런 기록으로 보이지만 과금 방식은
  확인하지 않았다.
