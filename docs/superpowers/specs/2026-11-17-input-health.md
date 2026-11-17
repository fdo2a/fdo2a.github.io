# 2026-11-17 — 1a 「자료 누락 차단」: 발행 전 자료 상태 검사

결정 기록은 프로젝트 루트 `plan.md` 2026-11-17 「검증 체계 개선 방향 · 실패 처리 기준표」·「사용자 결정」·「조사·측정」.
이 문서는 검사 쪽(작업 1, 브랜치 `feat/input-health-gate`)의 설계·한계·측정이다. 수집 쪽(작업 2)은 같은 계약 A 를 쓴다.

## 푸는 문제와 풀지 않는 문제

푼다: 검사기가 판정에 쓰는 자료가 없거나, 비었거나, 낡았거나, 수집에 실패했는데도 발행 전 검사가 「발행 가능」을
내던 것. 전에는 `check_movers` 의 「자료 없음·읽기 실패」가 `nothing to check`(exit 0)였고, `check_auction`·
`check_liquidity`·`check_fed`·`check_fund` 는 수집 실패·낡은 책을 「섹션 없이 발행」으로 넘겼고, `check_macro` 는 책이
없으면 부트스트랩, `econ_indicators` 가 없으면 축 표 검사를 건너뛰었고, `check_numbers` 는 위임 자료가 없으면 미검증으로
세고 설정을 못 읽으면 경고 모드였다.

풀지 않는다: 루틴이 검사 규칙·자료·정책 파일·발행 경로를 직접 고쳐 검증을 우회하는 것(권한 분리 단계). 경고의 구조화와
자동 허용 목록(`auto_ok`), 사람 승인 명령, 재시도 상한, record 4 보류, 한 파일 기준표(다음 작업). **이 변경으로 발행
시스템의 안전성이 입증됐다고 쓰지 않는다** — 정의된 시험 사례에서 부적절한 발행 허용이 0건이라는 것뿐이다.

## 네 분류 (`config/prepub_inputs.json`, `prepub-inputs/1`)

| 분류 | 뜻 | 없거나 나쁘면 |
|---|---|---|
| gate | 검사기가 판정에 쓴다 | 그 검사 미완료 → 발행 보류 |
| writer | 작성자만 쓴다 | 막지 않는다. `risk`·`covered_by`(글에 실린 뒤 대조하는 검사기, 없으면 null)를 기록 |
| unused | 작성·검사 모두 안 쓴다 | 막지 않는다 |
| discontinued | 사람이 승인한 수집 중단 | 사유·중단일·영향·`approved_by: "user"`. 없거나 user 가 아니면 설정 오류 |

분류되지 않은 파일이 자료 폴더에 있으면 미완료. 위에서부터 첫 일치, `{date}` = 발행일(KR `news/{date}.json` 만 writer).
조건부 gate(`when`): 연준 원문 `fed/<key>.txt` 는 `fed/events.json` 이 원문을 받았다(`sources[].ok`)고 한 사건만 필수,
나머지 txt 는 unused. 날짜 묶음(`date_ref`): 작업 공간의 `macro.json` 은 직전 책이라 발행일이 아니라
`macro_eval.json` 의 `macro_date` 와 같아야 한다. 작성자 산출 gate(`produced_by: writer` — `macro_next.json`,
`kr_stance_next.json`)와 원장(`ledger` — `macro.json`)은 수집 상태 표시를 요구하지 않는다. `rewritten_by`(유동성 책·표
— `build_liquidity --recompute` 가 수집 뒤 다시 쓴다)는 해시 불일치만 면제하고 `collect` 칸의 조건은 그대로 본다.
`_collect_status.json` 은 적용일 전에는 없어도 되고 적용일부터 필수다(없으면 해시 대조가 조용히 꺼진다).

수집 중단 등록은 KR `kr_flows_intraday.json` 하나 — 「Naver 레거시 페이지 폐지(2026-09-17 SPA 개편), 대체 원천 없음」,
영향 §6 장중 수급 서브블록, `approved_by: user`, `approved_at: 2026-11-17`. 이 등록이 있을 때만
`kr_market_data.missing` 의 `flows_intraday` 를 결측으로 세지 않는다. **잔여 위험: 권한 분리 전에는 루틴이 이 파일을
고쳐 수집 실패를 수집 중단으로 바꿀 수 있다.**

## 자료 상태 (`scripts/verification/inputs.py`)

`assess(policy, market, ctx)` → 파일별 `state`: ok · missing · empty_file · unreadable · stale · failed ·
incomplete_fields · unstamped · changed_after_collect. 옛 칸(`report_date`·`ok`·`error`·`status`·`complete`·`missing`·
`pending`·필수 칸)은 지금부터 강제, `collect`(또는 `_collect_status.json` 의 항목)가 있으면 그 조건(status ok·as_of=발행일·
required_ok·missing 빔·empty≠unknown·대상 목록과 empty 의 일치)도 지금부터 강제. 표시가 없는 것(`unstamped`)은
`inputs.EFFECTIVE`(초기 None) 전에는 경고(조건부 판정의 조건), 그날부터 미완료. 적용일은 작업 2 배포와 첫 수집 확인 뒤
사람이 넣는다.

## 실행기·상태·종료 코드 (`record.py`, `run_gates.py`)

- 검사기마다 `inputs`. 실행기가 먼저 자료 상태를 보고 하나라도 정상이 아니면 검사기를 돌리지 않고 incomplete
  (사유 = 「무엇이·왜」 — 정책의 사람 이름 + state 한국어). 검사기도 스스로 exit 2 — 두 겹.
- 검사 상태 pass·warn·fail·na·incomplete. 옛 판정 불가·일부만 검사·확인 안 된 실행 안 함 → incomplete.
  **na 는 실행기가 직접 확인할 때만**: `na_when`(수집 상태 ok·confirmed_none·`checked ≥ min_checked`·`checked ≥
  ⌈MIN_COVERAGE × expected⌉`) 또는 적용일 전 `legacy_evidence`(근거 목록이 `common.movers.LEGACY_MIN_ITEMS` =
  ⌈0.9 × 60⌉ = 54 행 이상이고 행마다 그날 날짜). 지금 `kr_stock_moves.json` 행에는 날짜가 없어 KR 의 옛 방식 na 는
  나오지 않는다(구현 검토 #1 — 한 행만 있어도 na 였다). 근거가 없으면 미완료. 검사기의 적용일 전 글은 na.
- 글 판정 verified / conditional(경고·노트 조건·옛 방식 na·수집 표시 없음) / incomplete / failed. 우선순위
  failed > incomplete > conditional > verified. 경고는 지금처럼 막지 않는다.
- 종료 코드 check·record 0 발행 가능 / 1 위반 / 2 미완료(설정·도구 오류 포함 — check 만, record 의 도구 오류는 5 그대로).
  위반과 미완료가 함께면 1(미완료 목록도 찍는다). 루틴: exit 2 → 글을 고치지 않고 수집 재실행 1회 → 그래도 2 면 커밋·
  푸시하지 않고 잠금 해제·PushNotification 보류(ORCHESTRATOR·KR_ORCHESTRATOR·STYLE_CLOSE).
- 무결성: 입력 스냅샷의 한도 초과·읽기 실패·전후 불일치 → incomplete. 정책 파일과 `inputs.py` 를 기록의 `generator`
  해시에 넣었다(레포 다이제스트가 `config/` 를 이미 본다 → `verify` 대조 범위).
- 기록 `prepub-record/2`: `inputs_health`(파일별 state·분류, writer 의 risk·covered_by, 수집 중단 목록),
  `summary.{failed,incomplete,na,conditions,inputs}`. 알림(`prepub_view`)은 1판·2판을 모두 읽고, 1판 12건의 알림 문구는
  바꾸기 전과 글자 그대로 같다(`scripts/review/tests/test_prepub_v1_golden.py`).

## 검사기별 입력 (실측 + 정적 읽기 보충)

plan.md 「조사·측정」의 감사 훅 실측에 코드 읽기로 보충한 것: `check_fed` 의 원문 txt(사건 있는 날만), `check_liquidity`
의 발행본 원장(레포 `posts/` — 레포 다이제스트가 본다), `check_price_context` 의 `scorecard.json`(있으면 — 작업 공간에
복사하지 않아 없으면 주장을 막는 쪽), `check_numbers` 의 `config/number_audit.json`·`liquidity/liquidity.json`,
`check_research` 의 연구 원장(레포 — 자료 폴더 밖). 목록은 `config/prepub_gates.json` 의 `inputs`.

## 시험

- 단위: `test_inputs.py`(state 각각·na_when·date_ref·rewritten_by·수집 중단 승인), `test_record.py`(상태·판정 우선순위·
  종료 코드), `test_checker_exit2.py`(검사기 직접 — 실행기 사전 확인이 가리는 둘째 겹), `test_inputs_policy.py`
  (정책·실행 목록 일관성, 기록 12건과 레포 자료 폴더 전 파일의 분류).
- **오류 주입 영구 시험** `test_input_mutations.py`: US 11/12(입찰·유동성 발표·지표 원문)·US 11/16(연준 의장 연설)·
  KR 11/12·11/13 을 발행 커밋과 기록의 입력 참조로 바이트 그대로 복원(해시 대조, 커밋을 못 찾으면 실패)해 gate 파일마다
  삭제·0바이트·깨진 JSON·날짜 하루 전·실패 표시(ok·status·error·collect)·필수 칸 비우기·대상 목록 비우기(empty
  unknown, 그리고 표시 그대로)·수집 표시 제거를 넣는다. 표시 모드(손으로 붙인 `collect`·해시 장부, 적용일 = 발행일)는
  발행 가능 0건, 옛 모드는 옛 칸으로 알 수 없는 변이만 이유와 함께 목록(`LEGACY_UNDETECTABLE` — 표시 없는 빈 대상
  목록, 조건부 판정이어야 한다)에 둔다. writer·unused·discontinued 파일 삭제는 발행 가능(오차단 0), 분류 안 된 파일은 미완료.
- 사고 회귀: KR 11/16(실제로는 종목을 하나도 재지 못한 날 — `kr_stock_moves.json` 0행) → 미완료(전에는 not_run 으로
  발행). 손으로 만든 정상 0건(collect ok·confirmed_none·checked) → na. US `auctions.json` `ok:false` → 미완료(전에는
  경고 뒤 발행).

## 구현 검토 1회차(codex IMPL NO) 수정 — 2026-11-17

| # | 지적 | 고친 것 |
|---|---|---|
| 1 | KR 옛 방식 na 가 한 종목만 있어도 참 | `legacy_evidence.min_items` = `common.movers.LEGACY_MIN_ITEMS`(정책은 `{module, attr}` 로 가리킨다), `date_field` 필수. collect 경로도 `min_coverage` |
| 2 | 적용일 전 빈 대상 목록이 확인 없이 통과 | 막지 않고 `unconfirmed_empty` 조건·알림. 적용일 뒤에는 표시 없음 자체가 막는다 |
| 3 | KR 분봉·수급의 `as_of` 가 실제보다 새것 | 분봉은 마지막 봉의 날짜 보존·그날 봉만, 아니면 `stale:<시장>` 결측. 수급 `as_of` = 두 시장 최신 행 중 이른 날. 직전 거래일 허용 없음(아래 실측, 사용자 결정) |
| 4 | KR 세션이 지난 원자료를 당일 성공으로 | 계산된 창(선물·원달러)·미국 직전 세션(us 달력)·닛케이(jp 달력)·「네 지수 모두 그날 값 없음」으로 판정. 달력 없는 시장 한 곳 지연은 detail |
| 5 | US 경제지표 필수 지표 계산 불가가 성공 | scored 지표의 `no_value` → `missing: no_value:<이름>`·required_ok false. 「미발표」는 no_value 를 만들지 않는다 |
| 6 | 적용일 뒤 `_collect_status.json` 항목이 없어도 통과 | collector·reference gate 파일마다 항목·64자리 sha256(없으면 unstamped). `rewritten_by` 는 해시만 면제 |
| 7 | 정상 0건 일정이 보류 | `require` 칸이 `target` 과 같고 ok·confirmed_none 이면 빈 목록 허용. 표시 없는 빈 일정은 그대로 막는다 |
| 8 | `scorecard.json` 정책 ↔ 등록표 불일치 | `produced_by: reference`(collect 칸 없음 — 생산자 계약), 적용일부터 해시 항목만 |
| 9 | `--recheck` 가 새 글에도, 정정기가 원본 2 를 허용 | `inputs.STRICT_FROM` 전 글에만(`--recheck` 와 같은 꼴인 `check_macro`·`check_sources` 의 `--legacy-releases` 도 — `inputs.legacy_recheck`). 새 일간 글은 0·1 밖 종료를 허용하지 않는다(정정기·윤문기). 재검사하는 검사기들의 exit 2 는 모두 「미완료·못 읽음·사용법 오류」 뜻이다(코드 확인) |
| 10 | 루틴·작성자 문서의 「없으면 섹션 생략」 | 보류 규칙과 맞춤, 「이미 신뢰 가능」 → 「자료 상태 검사를 받는 수집 자료(원천 재대조 아님)」 |
| 11 | 2판 알림 「N/M 통과」가 na 를 통과로 안 셈 | 「필수 검사 N개 중 통과 a · 해당 없음 b」(1판 문구 그대로) |

실측(발행 커밋 기준):
- KR 수급(#3): 2026-10-01~11-16 발행 31일 중 발행 커밋의 `kr_market_data.flows_date` 가 report_date 와 다른 날 0일
  (11/09~11/16 늦은 실행 6일 포함 모두 당일 잠정치). 10/15 글은 발행 커밋의 자료가 이미 10/16 이라 셀 수 없었다.
- KR 세션(#4): 같은 기간 30일 중 아시아 지수 한 곳 이상이 지난 날인 날 10일(국경절·체육의 날·문화의 날 등 휴장),
  넷 모두 지난 날 1일(11/16 — 늦은 실행), 선물·원달러 창 None 0일, 전일 미국장 불일치 0일. 새 규칙으로는 1일(11/16)이 막힌다.
- US 경제지표(#5): 지금 원천에서 CPI YoY·Core CPI YoY 가 2025-10 기준월 결측으로 no_value — **수집 쪽 배포 뒤 첫
  수집부터 econ_indicators·macro_metrics 가 partial 이 되어 US 발행이 막힌다**(2025-11 기준월이 쓰이는 11월 CPI 발표까지).

시험의 한계: 오류 주입 시험(`test_input_mutations.py`)은 손으로 붙인 표시로 돈다 — 수집기의 틀린 성공 표시·틀린
`confirmed_none`·오래된 원천을 오늘로 찍는 오류는 증명하지 못한다(수집 쪽 단위 시험 `kr/tests/test_collect_freshness.py`·
`common/tests/test_movers.py`·`us/tests/test_econ_collect_required.py` 가 그 몫). 바이트를 바꾸지 못한 변이는 세지 않는다
(날짜 칸 없는 옛 자료의 날짜 하루 전, 칸 없는 목록형·txt 의 실패 표시). 표시 모드에 빈 대상 목록(표시는 has_data)을 넣었다.
행렬(US 11/12·11/16, KR 11/12·11/13): 표시 모드 막힘 592/592 → 609/609, 옛 모드 519/545(발행 가능 26) → 523/527(발행
가능 4 — 전부 표시 없는 빈 대상 목록: 입찰 1·연준 사건 1·지표 원문 목록 2, 모두 조건부 판정·`unconfirmed_empty` 조건).

## 구현 검토 2회차(codex IMPL NO) 수정 — 2026-11-17

codex 가 1회차 11건 중 7건 닫힘·4건 일부로 보고, 새 구멍 다섯과 CPI 결측의 처리(D)를 냈다. 지적마다 고치기 전 코드에서
실패하는 시험을 먼저 썼다(`scripts/verification/tests/test_impl_review_r2.py`, `scripts/review/tests/test_impl_review_r2_review.py`,
`scripts/kr/tests/test_session_window.py`, `scripts/common/tests/test_stamp_run.py`).

| # | 지적 | 고친 것 |
|---|---|---|
| F1 높음 | `{"report_date": D, "ok": true}` 인 입찰 책 — `today` 칸이 없는데 「대상 없음 미확인」 조건으로 발행 가능. 검사기도 `book.get('today') or []` | `inputs._health`: `target` 칸이 없거나 list 가 아니면 적용일·표시와 무관하게 `incomplete_fields`. 「표시 없는 **빈 배열**」만 `unconfirmed_empty`. `us/auction_gate.check` 는 `BadBook`, `check_auction`·`check_fed` 는 exit 2(`check_movers` 는 이미 그랬다, `check_liquidity` 에는 대상 목록이 없다). 변이 `drop_target_field`·`target_not_list` 는 두 방식 모두 막힌다 |
| F2 높음 | 선물 봉 둘(09:00·09:30)·환율 봉 하나(09:00)뿐이어도 장중 세션 성공 | `kr.session.WINDOW_END = (15, 0)`: 창의 마지막 봉이 15:00 KST 이후여야 완결, 선물·환율 각각. 못 미치면 `partial`·`incomplete_window:<이름>`, 마지막 봉 시각을 못 읽으면 `:unknown`. 조기 마감·개장 지연 달력이 없어(`market_holidays.json` 은 휴장일만) 다른 마감 시각을 추정하지 않고 기준을 `detail` 에 적는다 |
| F3 높음 | 그날 정상 `kr_session.json` 이 있을 때 둘째 실행의 세션 수집이 예외로 죽으면 stamper 가 옛 파일의 성공·해시를 다시 적는다 | `stamp_collect.py --begin`(잡 시작) + 끝의 stamp 가 파일마다 `run`. 단계는 돌았는데 `collect.collected_at`(칸 없는 참고 파일은 mtime)이 시작 전이면 `status: failed`·`run: failed`·`stale_copy`. 단계 결과는 `COLLECT_STEPS`(`toJSON(steps)`). 적용일부터 막고(`failed`), 그 전에는 조건 `recollect_failed`. 장부를 못 쓰면 실행을 실패로 끝낸다 |
| F4 중간 | 그날 날짜만 든 같은 객체 54개가 옛 종목 근거로 통한다 | `legacy_evidence.id_field`·`value_field`(KR: `name`·`change_pct`) — 식별자가 있고 등락이 유한한 **고유 종목**이 `min_items` 이상일 때만 |
| F5 중간 | `2026-11-16-2026-11-17.html` — `legacy_recheck` 는 첫 날짜, 정정기는 끝 날짜, 윤문기는 정규 경로만 | `inputs.post_date`(basename 전체가 `YYYY-MM-DD.html` 이고 실제 날짜)·`legacy_post` 한 곳. 검사기 넷(`check_fund`·`check_numbers`·`check_macro`·`check_sources`)과 정정기·윤문기가 그것을 부른다. 두 모듈의 사본은 가져오기가 안 될 때만 쓰이고 일치 시험으로 묶었다 |
| F6 (D) | CPI 결측 — 기한부 예외의 **기구** | `accepted_missing`(아래). **실제 정책에는 등록하지 않았다** |
| B-6 | 적용 전에는 날짜 없는 낡은 자료가 조건부 발행 가능 | 그대로다 — `EFFECTIVE` 가 None 인 동안의 한계(잔여 위험) |

**F3 의 판정 규칙.** `run` = `written`(이번 실행이 썼다) / `skipped`(그 단계가 건너뛰었다 — US 둘째 슬롯은 `collect` 의
`outputs.skipped == 'true'`, 나머지 단계는 `outcome: skipped`) / `kept`(단계가 성공하고 일부러 다시 쓰지 않았다 — 요약이
있는 날의 텔레그램 파일 동결, `MAY_KEEP`) / `failed`(단계가 성공·실패로 **돌았는데** 파일이 다시 쓰이지 않았다) / `unknown`
(`--begin` 기록이 없거나 동결 여부를 가를 단계 결과가 없다) / `untracked`(판정 대상이 아닌 작성 재료). 앞선 실행의 `failed` 는
건너뛴·동결·모름 실행이 지우지 못하고, 파일이 실제로 다시 쓰여야 풀린다. 비 JSON 산출물은 생산자 JSON 의 상태를 따른다.
전수로 찾은 「조용히 옛 판이 남는 자리」(읽기 전용 조사): 수집기 안에서 삼키는 예외 셋(`collect_kr_data.py` 세션,
`collect_market_data.py` macro_metrics·scorecard — 사유를 `note_run_failure` 로 남긴다), 쓰지 않고 exit 0
(`collect_fed_events.py` report_date 없음), `continue-on-error` 단계가 쓰기 전에 죽는 경우(`build_calendar`·`build_auctions`·
`eval_macro_regime`·`fetch_telegram`) — 뒤의 둘은 사유 기록 없이 시각 비교로 잡힌다. `fetch_releases`·`build_liquidity` 는
sanitize 단계가 「끝나지 않은 실행」을 다시 적는다. KR enforce 모드의 동결은 stamp **뒤**에 임시 worktree 에서 일어나고
날짜 없는 최상위 경로(`_collect_status.json` 포함)를 원격 판으로 둔다 — 장부와 파일이 같은 판에 머문다.

**F6 의 판정 규칙.** 파일 항목의 `accepted_missing: [{key, ref_period, reason, approved_by, approved_on, expires}]`,
`approved_by` 는 `"user"` 만(수집 중단과 같은 규칙·같은 잔여 위험). 풀어 주는 것은 「일부만 받았다」에서 나온 세 사유
(`collect.status=partial`·`required_ok` false·`missing`)뿐이고, 조건은 넷 모두다: ① `collect.missing` 의 **모든** 키가 등록돼
있다 ② 글 날짜가 `approved_on ≤ 날짜 ≤ expires`(벽시계가 아니라 글 날짜 — 옛 기록을 다시 검증해도 뒤집히지 않는다)
③ 자료가 말하는 기준월 `collect.missing_ref[키]` 가 등록의 `ref_period` 와 같다(자료가 기준월을 말하지 않으면 적용 안 됨)
④ 수집 실패(`failed`)가 아니다. 낡음·해시·표시 없음·`empty: unknown` 은 예외와 무관하게 막는다. 원본 `collect` 는 고치지
않는다. 수집기: `econ_collect` 가 no_value 지표의 기준월(원천의 최신 관측월, 예 `2026-10-01`)을 `missing_ref` 로 싣고,
`macro_metrics_collect` 는 econ 의 결측을 `econ:<키>`·기준월로 그대로 옮긴다(전에는 `econ_indicators` 하나) — 두 파일 모두
같은 키·기준월로 등록해야 풀린다. 등록할 때 쓸 키: `econ_indicators.json` 에 `no_value:CPI YoY`·`no_value:Core CPI YoY`,
`macro_metrics.json` 에 `econ:no_value:CPI YoY`·`econ:no_value:Core CPI YoY`, `ref_period` `2026-10-01`. 기록 조건
`accepted_missing`(승인자·만료일), 알림 「승인된 결측 N건(만료 D)」. **등록은 사용자 결정이다** — 시험이 실제 정책의 등록 0건과,
그 상태에서 CPI 전년 대비 둘이 빠진 US 가 막힌다는 것을 고정한다(`test_cpi_gap_blocks_us_with_the_real_policy_…`).
축 점수(확인만, 고치지 않았다): `us/macro_metrics.compute` 는 `econ_indicators` 의 행만 돈다 — no_value 지표는 행 자체가 없어
`_axis_mean`·`breadth_counts` 가 남은 행으로 평균·개수를 낸다(합성 자료로 돌려 확인: 인플레이션 5행 → 3행, 「빠졌다」는 표시 없음).
예외를 등록하면 그 축이 CPI 전년 대비 없이 계산된다는 것을 글에 드러낼지는 사용자 결정으로 남긴다.

**실측**(origin/main `6b0f62e4` 까지의 이력).
- F1: 대상 목록 칸이 없거나 목록이 아닌 판 0 — auctions 30판·fed/events 53·releases/index 61·calendar 140·movers 46·
  kr_movers 74·kr_index_etf 37·telegram 15(US 7·KR 8). 정상일 오차단 0/456판.
- F2: `kr_session.json` 92판(발행일 54일). 선물 창의 마지막 봉 15:30 이 91판(나머지 1판은 창 자체가 None — 2026-09-07,
  미국 노동절. 이것은 1회차 #4 의 `futures:<이름>` 결측이고 이번 기준과 무관), 환율 92판 전부 15:30. `WINDOW_END` 15:00 으로
  새로 막히는 판 0/92(발행일 0/54). 참고: 창의 **첫** 봉이 09:00 이 아닌 판이 1(2026-09-08, 13:00 시작·봉 6개) — 시작 쪽
  완결성은 이번에 보지 않았다(계획 밖, 잔여 위험).
- F3: 과거 자료로 오차단 비율을 잴 수 없다 — `collect.collected_at` 이 아직 배포되지 않았다. 「수집 커밋에서 그 파일이 바뀌지
  않은 횟수」(KR 42커밋 중 kr_session 6, US 105커밋 중 macro_metrics 2 등)는 같은 내용으로 다시 쓴 것과 못 쓴 것을 가르지
  못해 근거로 쓰지 않았다. **배포 뒤 첫 며칠의 `run` 분포를 보고 `EFFECTIVE` 를 넣어야 한다.**
- 변이 행렬(US 11/12·11/16, KR 11/12·11/13): 표시 모드 698/698 막힘(통과 0), 옛 모드 561/565 막힘 — 통과 4 는 전과 같은
  표시 없는 빈 대상 목록(`target_emptied`: 11/12 fed/events·releases/index, 11/16 auctions·releases/index), 모두 조건부·
  `unconfirmed_empty`. 새 변이: `drop_target_field` 18·`target_not_list` 20(두 방식), `rerun_failed` 51(표시 모드).

## 잔여 위험

- 권한 분리 전에는 루틴이 정책 파일·자료·검사기·이 문서를 고칠 수 있다(분류를 writer 로 바꾸기, 수집 중단 등록 추가,
  `EFFECTIVE` 되돌리기). 기록의 generator 해시·레포 다이제스트가 「바뀌었다」는 것은 남기지만 막지는 않는다.
- **`EFFECTIVE` 가 None 인 동안 1a 는 완료가 아니다.** 적용일 전에는 날짜 칸 없는 자료의 신선도, 목록형·txt 의 수집
  실패, 표시 없는 빈 대상 목록을 알 수 없다. 빈 대상 목록은 막지 않되 기록 `inputs_health.files[*].unconfirmed_empty`,
  글 판정 조건 `unconfirmed_empty`, 알림 「대상 없음 미확인」으로 숨기지 않는다(구현 검토 #2). 적용일 전에 막으면 수집
  쪽 배포 전 모든 날이 멈춘다.
- writer 분류 자료(웹 조사 노트·KR 개별주 등락·기술적 레벨·지표 원문 등)는 검사기가 대조하지 않는다 — 기록에 risk 로만.
- `inputs.STRICT_FROM`(2026-11-17)은 배포일과 같아야 한다 — 그 사이 옛 규칙으로 발행된 글은 새 규칙으로 재검사된다.
- 지난 글 재검사(정정기·윤문기·매일 알림)는 같은 검사기를 그 커밋 자료로 돌린다. 원본의 2 를 허용하지 않는
  `check_fund`(NEVER_TOLERATE)·`check_numbers`(VIOLATION_DIFF·NO_TOLERATE_EXIT2)는 `--recheck` 로 2026-11-17 전 판정을
  쓴다 — 실측: US 10/12·10/21(펀드 partial·unavailable)은 `check_fund` 2, 10/12·10/20·10/21·11/05(유동성 책 전)는
  `check_numbers` 2 였고 `--recheck` 로 옛 결과(0·1)가 돌아온다. `check_macro`·`check_sources` 는 `--legacy-releases`
  가 같은 몫(`check_macro` 는 책·econ·metrics 완화까지). 발행 실행 목록은 두 플래그를 쓰지 않는다(시험이 강제). `--recheck` 는
  `STRICT_FROM` 전 글에만 효과가 있다. 그 전 글은 원본도 2 면 정정기·윤문기가 기존 실패로 허용한다 — 그 게이트는 그
  정정을 검사하지 않는 셈이다(전의 exit 0 과 같은 공백). 그 뒤 글은 허용하지 않는다(구현 검토 #9).
- 실행 목록 설정에 `inputs_policy` 가 없으면 자료 검사를 하지 않는다(시험용 설정 경로). 실제 설정에 있다는 것은 시험이
  강제하지만, 권한 분리 전에는 루틴이 그 칸을 지우는 것을 막지 못한다.
- 표시 모드의 변이 시험은 손으로 만든 표시(`realday.stamp`)로 돈다 — 실제 수집기 산출(작업 2)과의 맞물림은 병합 뒤
  첫 수집에서 확인해야 한다(대조한 것: 수집 쪽 `collect_status.build` 의 모양, `stamp_collect.py` 의 등록표·해시 칸,
  연준 사건의 fresh 기준, 지수 ETF 빈 목록의 confirmed_none).
- **2회차 뒤에 남은 것.** ① 일본 외 아시아 지수(항셍·상해·대만)는 휴장 달력이 없어 한 곳의 지난 날짜를 휴장과 지연으로
  가를 수 없다 — 넷 다 그날 값이 없을 때만 결측이고, 한 곳씩의 지남은 `kr_session.json` 의 `collect.detail`(장부 항목에도
  옮겨진다)에만 남는다. **검증 기록의 조건·알림에는 나오지 않는다.** ② KR 장중 창은 끝만 본다 — 시작이 늦은 창(09:00 이
  아닌 첫 봉)과 KRX 장 시간이 다른 날(수능일 10:00~16:30, 개장 지연)은 가르지 못한다. 미국 휴일 전후로 선물 봉이 비는 날은
  1회차 규칙대로 결측(보류)이다 — 54일 중 1일(2026-09-07). ③ F3 는 워크플로 단계 id·`toJSON(steps)`·`--begin` 에 기대는데
  **워크플로를 실행해 보지 않았다**(YAML 정적 시험뿐). 단계 결과가 `skipped` 인 파일은 옛 판을 그대로 믿는다 — `collect`
  단계가 실패해 뒤 단계가 건너뛰어진 실행은 커밋 단계도 돌지 않아 장부가 남지 않는다는 것에 기댄다. ④ `kept`(텔레그램
  동결)인 날은 그 단계가 삼킨 실패를 가르지 못한다. ⑤ `accepted_missing` 의 `approved_by: "user"` 는 문자열일 뿐이다 —
  권한 분리 전에는 루틴이 등록을 더할 수 있다(수집 중단과 같은 위험). ⑥ 격리 사본에서 `verification` 패키지를 가져올 수
  있는지는 확인하지 못했다(같은 `scripts/` 트리에 있어 될 것으로 보이지만 추정) — 그래서 사본을 남겼다.
