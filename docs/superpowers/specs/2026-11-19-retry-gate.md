# 재시도 판정 게이트 — 판정은 Actions, 세션은 DUE 일 때만 (2026-11-19)

## 계기

2026-11-19 RemoteTrigger list 실측: 재시도 루틴 6개와 일본 주간 MOF 본 루틴이 주 116회 떴다. 거의 전부
`routine_due.py` → `DONE` 으로 2턴·8초 만에 끝났지만, 매번 새 클라우드 세션(시스템 프롬프트·도구, 캐시 없음)을 냈다.
재시도가 있는 이유(5시간·7일 한도로 죽은 런 이어받기, 일본 주간의 MOF 게시 대기)는 그대로 지킨다.
앞 설계: `2026-09-27-routine-retry-after-limit.md`.

## 전달 수단 — API `/fire`

- GitHub 이벤트 트리거는 쓰지 않는다. 문서(code.claude.com/docs/en/routines)가 적은 이벤트는 Pull request·Release·Issue 뿐이고
  필터는 PR 에만 있다. 2026-10-27 실측에서 API 는 `push` 와 엉터리 필터(`{"bogus_field_zz":1}`)를 200 으로 받았고 필터는 무시됐으며,
  API 로는 웹훅 트리거를 지울 수 없었다. Issue 이벤트는 공개 레포에서 누구나 일으킨다.
- GITHUB_TOKEN: GitHub 문서는 「GITHUB_TOKEN 이 일으킨 이벤트는 workflow_dispatch·repository_dispatch 를 빼면 새 워크플로 실행을
  만들지 않는다」고만 적는다. App 웹훅 배달은 문서에 없다(미확인).
- `/fire`: `POST https://api.anthropic.com/v1/claude_code/routines/<trig>/fire`, `Authorization: Bearer <루틴 토큰>`,
  `anthropic-beta: experimental-cc-routine-2026-04-01`, `anthropic-version: 2023-06-01`. 본문 `text` 는 루틴에
  `<routine-fire-payload>`(신뢰하지 않는 자료)로 감싸 전해진다 — 프롬프트가 참조하지 않으므로 기록용이다. 토큰은 루틴마다 하나,
  웹 화면에서만 만든다. 한도: 루틴당 시간당 30회(Run now 와 합산), 계정당 API 100회/시간.

## 구조

- `.github/workflows/retry-gate.yml` — 지금 재시도 슬롯과 같은 시각(정각은 7분 뒤). 일요일 일본 재시도 슬롯은 없다: 일요일 `japan_key`
  는 이틀 전 금요일의 주이고 게시일은 월요일 이후라 언제나 `WAIT` 다(시험이 2026-2027 전 일요일로 확인).
- `scripts/ci/retry_gate.py` — 예약 문자열 → 종류. 종류마다 `routine_due.py <kind>` 를 그대로 부르고, 첫 낱말이 정확히 `DUE` 이고 창 안이면
  쏜다. 판정이 죽으면 쏘지 않고 실패, `/fire` 가 2xx 가 아니면 실패(빨간 실행 = GitHub 메일). 다른 종류는 마저 본다.
- **창** — 예약은 2-5시간 늦는다. 세션은 본 런보다 먼저 넘어가므로(US 17:00 NY / 본 런 17:30, KR 16:00 KST / 18:00) 늦은 틱이 그 틈에 떨어지면
  재시도가 본 런보다 먼저 수집 전 자료로 돈다. 그래서 세션 본 런 시작 + 2시간 전에는 쏘지 않는다: US 17:30 NY(서머타임 따라), KR 18:00 KST,
  일본 일간 18:20 KST, 주간 세션 다음 토요일 15:00 KST. 일본 주간은 MOF 게시일 13:00 KST + 0 — 이 게이트가 본 런 자리다.
- 일본 주간은 재시도 루틴(`trig_019f…`) 하나로 쏜다. MOF 본 루틴(`trig_01Vo5…`)과 모델·도구·소스·Step 1·3 이 글자까지 같고
  (2026-11-19 list 대조), STALE 알림은 서울 시각(21시 이후·게시일 다음 날)으로 정한다. 본 루틴은 끈다.
- 발화 `text` 는 중립 문구다 — 판정 줄을 싣지 않는다(루틴 Step 2 는 낱말 `DUE` 로 멈출지 정한다).
- `force` 인데 토큰이 없으면 `RETRY_GATE_LIVE` 와 무관하게 실패한다(토큰 시험이 초록으로 거짓말하지 않게).
- 토큰 `ROUTINE_FIRE_TOKEN_<KIND>`. 없으면 레포 변수 `RETRY_GATE_LIVE=true` 전에는 경고, 뒤에는 실패 — 토큰보다 먼저 병합할 수 있게.
- 손 실행 `mode`: `check`(기본, 판정만) / `gate` / `force`(판정과 무관하게 발화 — 토큰 시험. 루틴이 스스로 DONE 을 보고 끝난다).
- **판정 앞뒤 세션이 같아야 쏜다.** 자식(`routine_due`)은 fetch 뒤에 시각을 읽는다. 판정 직전·직후의 세션 키(US·KR·일본 일간 세션,
  주간·일본 주간 키)가 다르면 그 판정이 어느 세션 것인지 모르므로 쏘지 않는다. 창은 판정 뒤(발화 직전) 시각으로 본다(codex 구현 검토 #1 —
  15:59:59 KST 에 시작한 KR 틱이 16:00 뒤 오늘 세션 DUE 를 받아 어제 창으로 쏘는 경로).
- 판정 자식에게는 `ROUTINE_FIRE_TOKEN_*` 를 넘기지 않는다. `/fire` 는 리다이렉트를 따라가지 않는다 — urllib 는 3xx 에 Authorization 을
  실어 다른 호스트로 GET 하고 그 200 을 성공으로 읽는다. 3xx·모양이 틀린 응답은 그 종류만 실패다.
- 발화 기록은 두지 않는다. 드문 이중 발화(손 실행 + 예약, 게이트 + 안전망 cron)는 `run_lock.sh` 가 가른다.
- 루틴 프롬프트는 고치지 않는다 — Step 1 재판정이 남아 잘못 쏜 발화는 8초짜리 no-op 이다.

## 안전망

Actions·토큰이 죽으면 복구가 조용히 사라지지 않게, 루틴 쪽에 얇은 cron 을 남긴다 — 게이트 슬롯과 겹치지 않는 시각:
US `45 3 * * 2-6`(12:45 KST), KR `40 16 * * 1-5`(01:40 KST), 일본 주간 재시도 루틴 `CRON_TZ=Asia/Seoul 30 23 * * 1-5`
(21시 이후 STALE 알림 규칙이 산다), 일본 일간 `30 14 * * 1-5`(23:30 KST, 06:00 JST 창 안), 주간 `40 16 * * 6`(일 01:40 KST).
안전망 발화는 게이트가 이미 처리했으면 DONE(또는 BUSY) no-op 이다.

## 한계

- 늦은 예약이 세션 경계를 넘으면 앞 세션의 그 슬롯은 사라진다(예: KR 15:07 KST 틱이 3시간 늦으면 오늘 세션을 보고 창 전이라 끝난다).
  옛 cron 재시도는 claude.ai 스케줄러가 제시각에 띄워 이 손실이 없었다. 앞 세션의 마지막 기회는 안전망 cron 이 제시각에 맡는다 — 안전망 시각은
  모두 세션 경계 전이다(US 12:45 KST, KR 01:40 KST, 일본 일간 23:30 KST, 주간 일 01:40 KST).
- 일본 주간 본 런(게시일 13:00 KST)도 예약 지연을 탄다 — 첫 시도가 몇 시간 늦을 수 있고, Actions 가 멈추면 23:30 KST 안전망이 첫 시도다.
  MOF 게시 시각이 실측되지 않아 13:00 회차도 자주 STALE 로 끝나는 것을 감안해 받아들였다.
- 자료가 끝내 불완전한 날은 슬롯마다 DUE 가 되어 다시 쏜다 — 지금과 같은 빈도다(늘지 않는다).
- 토큰은 AI 가 고칠 수 있는 워크플로에 들어간다. 새면 최악은 고정 프롬프트 세션을 시간당 30회까지 띄우는 것이다. 바꾸려면 웹 화면에서 Regenerate.

When changing this: read this spec before touching `scripts/ci/retry_gate.py` or `.github/workflows/retry-gate.yml`.
