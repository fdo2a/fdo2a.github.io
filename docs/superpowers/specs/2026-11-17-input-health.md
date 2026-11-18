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
| F6 (D) | CPI 결측 — 기한부 예외 | `accepted_missing`(아래). 2026-11-17 사용자 승인으로 **예외 하나**를 등록했다(「F6 승인」 절) |
| B-6 | 적용 전에는 날짜 없는 낡은 자료가 조건부 발행 가능 | 그대로다 — `EFFECTIVE` 가 None 인 동안의 한계(잔여 위험) |

**F3 의 판정 규칙.** `run` = `written`(이번 실행이 썼다) / `skipped`(그 단계가 건너뛰었다 — US 둘째 슬롯은 `collect` 의
`outputs.skipped == 'true'`, 나머지 단계는 `outcome: skipped`) / `kept`(단계가 성공하고 일부러 다시 쓰지 않았다 — 요약이
있는 날의 텔레그램 파일 동결, `MAY_KEEP`) / `failed`(단계가 성공·실패로 **돌았는데** 파일이 다시 쓰이지 않았다) / `unknown`
(`--begin` 기록이 없거나 동결 여부를 가를 단계 결과가 없다) / `untracked`(판정 대상이 아닌 작성 재료). 앞선 실행의 `failed` 는
건너뛴·모름 실행이 지우지 못한다 — 그 단계가 다시 돌아 파일을 쓰거나(`written`), 성공하고 동결 파일을 그대로 두어야(`kept`)
풀린다(동결 파일은 그날 다시 쓰이지 않으므로 `kept` 에 실패를 물려주면 재수집으로 풀 길이 없다). 비 JSON 산출물은 생산자
JSON 의 상태를 따른다.
전수로 찾은 「조용히 옛 판이 남는 자리」(읽기 전용 조사): 수집기 안에서 삼키는 예외 셋(`collect_kr_data.py` 세션,
`collect_market_data.py` macro_metrics·scorecard — 사유를 `note_run_failure` 로 남긴다), 쓰지 않고 exit 0
(`collect_fed_events.py` report_date 없음), `continue-on-error` 단계가 쓰기 전에 죽는 경우(`build_calendar`·`build_auctions`·
`eval_macro_regime`·`fetch_telegram`) — 뒤의 둘은 사유 기록 없이 시각 비교로 잡힌다. `fetch_releases`·`build_liquidity` 는
sanitize 단계가 「끝나지 않은 실행」을 다시 적는다. KR enforce 모드의 동결은 stamp **뒤**에 임시 worktree 에서 일어나고
날짜 없는 최상위 경로(`_collect_status.json` 포함)를 원격 판으로 둔다 — 장부와 파일이 같은 판에 머문다.

**F6 의 판정 규칙.** 파일 항목의 `accepted_missing: [{id, key, fred_id, transform, ref_period(YYYY-MM), reason, source,
approved_by, approved_on, expires, impact{affects_checks, sections, scores}}]`, `approved_by` 는 `"user"` 만. 풀어 주는 것은
「일부만 받았다」에서 나온 세 사유(`collect.status=partial`·`required_ok` false·`missing`)뿐이고, 조건은 넷 모두다:
① `collect.missing` 의 **모든** 키가 등록돼 있다 ② 글 날짜가 `expires` 이하다(벽시계가 아니라 글 날짜 — 옛 기록을 다시
검증해도 뒤집히지 않는다. `approved_on` 은 기록용이고 대조하지 않는다 — 보류된 글을 다음 날 승인해도 그 글이 풀려야 한다)
③ 자료가 말하는 **식별자·기준월·원인** `collect.missing_ref[키] = {fred_id, transform, ref_period, lacking}` 이 등록과 같다 —
앞의 셋은 값이 같고, `lacking`(원천에 없는 비교 달)은 정확히 등록된 그 달 하나(3회차 G1). 이름만 같거나 자료가 말하지 않으면
적용 안 됨 ④ 수집 실패(`failed`)가 아니다. 낡음·해시·표시 없음·`empty: unknown` 은 예외와
무관하게 막는다. 원본 `collect` 는 고치지 않는다. 수집기: `collect_econ` 이 no_value 지표의 FRED id·변환·기준월을 남기고
`econ_collect` 가 `missing_ref` 로 싣는다. `macro_metrics_collect`·`eval_macro_regime.eval_collect`·
`fetch_releases.index_collect` 는 윗단의 결측을 접두어(`econ:`·`metrics:`)와 같은 식별자로 그대로 옮긴다 — 결측이 지나가는
파일마다 등록해야 풀린다.

### F6 승인 — 2026-11-17 사용자 결정

**성격.** 「수집 실패 허용」이 아니라 **「공식 기관이 발표하지 않은 지표를 검증 대상에서 조건부로 뺀다」**. 기록·알림 문구도
「승인된 결측 — 원천 미발표」.

**원출처(본체가 확인).** ① BLS 2026-10 CPI 발표문 https://www.bls.gov/news.release/cpi.nr0.htm (USDL-26-1685) — 예산 공백으로
2025-10 조사 자료를 수집하지 못했고, 2025-10 지수가 없는 계열은 2026-10 의 12개월 변화율을 발표하지 못한다. All items·
All items less food and energy 의 12개월 칸은 「-」. ② BLS 일정 https://www.bls.gov/schedule/news_release/cpi.htm — 2026-11
기준월 CPI 는 2026-12-10 08:30 ET. FRED CPIAUCSL 의 2025-10 은 빈칸, 2025-11 은 325.063.

**등록(정확히 하나, 시험이 고정).** id `us-2026-10-cpi-yoy-not-published` · 지표 CPI YoY(`CPIAUCSL`·`yoy_pct`)·Core CPI YoY
(`CPILFESL`·`yoy_pct`) · 기준월 `2026-10` · 승인 user 2026-11-17 · **만료 2026-12-09**(12/10 발표 뒤 첫 글부터 예외 없음,
자동 연장 없음, 2025-10 원자료가 복구된다고 가정하지 않는다). 결측은 네 파일로 옮겨 가므로 네 곳에 같은 id 로 건다(각 두 지표, 모두 8줄):
`econ_indicators.json` 의 `no_value:<이름>` → `macro_metrics.json` 의 `econ:no_value:<이름>` → `macro_eval.json`·
`releases/index.json` 의 `metrics:econ:no_value:<이름>`(`common.collect_status.carry_upstream` — 윗단이 무엇이 빠졌는지
말하면 키와 식별자·기준월을 그대로 옮기고, 말하지 않으면 뭉뚱그린 키 하나라 등록할 수 없다. 전에는 뒤의 두 파일이
`macro_metrics:partial`·`macro_metrics` 로만 적어 예외가 닿지 않았다). 영향 범위: 검사 `check_macro`·`check_fed`·
`check_numbers`·`check_sources`·`check_weight`(그 네 파일을 읽는 검사), 섹션 매크로 진단의 물가 축·경제 지표 표의 두 행, 점수 물가 축 점수·`inflation_score`(레짐의 물가 다리).

**조건과 구현.**
- 대상 고정 — 식별자(FRED id + 변환)와 기준월이 모두 같을 때만. 이름이 비슷한 지표(CPI MoM 등), 같은 이름의 다른 계열,
  다른 기준월은 불일치다. 나머지 지표는 기존 기준 그대로이고 다른 결측이 하나라도 섞이면 예외 없이 보류.
- 대체값 금지 — `_econ_pair` 는 비교 달이 없으면 None 을 돌려 행 자체를 만들지 않는다(추정치·전월값·13개월 변화로 채우지
  않는다). 시험으로 고정했다.
- 공개 기록 — 검증 기록의 조건 `accepted_missing` 에 `ids`·`indicators`(키·FRED id·변환·기준월)·`reason`·`source`·`impact`·
  `approved_on`·`expires`, 알림 한 줄에 예외 ID·제외 지표·승인일·만료일·영향 범위·원인.
- **점수 표시(조건 7).** `us.macro_metrics.with_coverage` 가 `macro_metrics.json` 에 `coverage[축] = {total, used, excluded,
  phrase_ko, sensitivity}` 와 `axis_summary[축].coverage_ko` 를 싣는다(물가 축: 8개 중 6개). 글은 그 축 배지 옆에
  `<span data-axis-coverage="Inflation">8개 중 6개로 산출, 소비자물가 전년비·근원 소비자물가 전년비는 원천 미발표로
  제외</span>` 를 싣고(작성자 지시 `.claude/agents/brief-report-writer.md` §8 (a)), `us/macro_gate._check_coverage` 가 표식·
  개수·지표 이름·「원천 미발표」·숨김 여부를 대조한다(없으면 위반 exit 1, 빠진 지표가 없는 날의 표식도 위반).
- **판단 민감도(조건 8).** `check_macro.coverage_hold` — 빠진 지표가 모두 점수 범위의 아래 끝·위 끝일 때로 그 축 평균을
  다시 내어(`us.macro_metrics.sensitivity`) 방향·강도·레짐 다리(`us.macro.classify`)가 지금과 같은지 본다. 다르면 exit 2,
  사유 「승인된 결측이 판단을 바꿀 수 있음 — 사람 승인 필요」. 자료의 `sensitivity` 칸을 믿지 않고 행으로 다시 계산한다.
  수집 상태가 말하는 빠진 지표와 `coverage` 가 어긋나거나 `coverage` 가 없으면 그것도 보류. **점수에는 코드상 한계가 없다**
  (자기 모멘텀의 표준편차 단위) — 그래서 「양 끝」을 `SENSITIVITY_Z = 3.0` 으로 두었다(2026-10-15~11-16 발행 자료 22일의 모든
  지표에서 |점수| 최대 2.54). **사람 승인 절차는 아직 없다 — 보류로 끝난다.**

**민감도 실측(origin/main 의 발행 자료, 2026-10-15~11-16 22일).** CPI 전년 대비 두 행이 없는 날은 5일(11/10·11·12·13·16)이고
**5일 모두 보류**다. 11/10~12: 지금 재가속(레짐 다리 +1), 아래 끝이면 둔화(−1), 위 끝이면 재가속 뚜렷. 11/13·16: 지금
재가속, 아래 끝이면 둔화·다리 0. 폭을 ±2·±1·±0.5 로 좁혀도 5일 모두 판단이 달라진다(강도까지 볼 때). 강도를 빼고 방향·레짐
다리만 보면 ±0.5 에서만 11/13·16 이 유지된다(2/5). 다른 기준 후보 — 「마지막으로 발표된 그 지표의 점수(2026-09: −0.428·
−0.451)에서 관측된 최대 월간 변화폭(1.064·0.532)만큼」 — 으로도 5일 모두 달라진다(아래쪽에서 교착·다리 0). 두 지표가
들어 있던 11/09 의 물가 축은 교착(0.003)이었고 빠진 11/10 부터 재가속(0.451)이다. **즉 지금 기준으로는 예외를 등록해도
US 는 매일 보류된다** — 자료 층의 보류(등록 전)가 판단 층의 보류로 바뀔 뿐이다. 어느 기준을 쓸지, 사람 승인 절차를 둘지는
사용자 결정이다.

**12/10 뒤.** 2회차까지는 `_econ_pair` 가 「직전」도 바로 앞 달이어야 행을 만들어, 2026-11 CPI 전년 대비가 계산되는데도
(2025-11 있음) 2026-10 전년 대비가 없다는 이유로 행이 빠지고 US 가 2027-01 까지 막힐 것이었다. 3회차 G5 에서 고쳤다(아래).

**권한.** 승인된 예외 목록(`accepted_missing`)은 권한 분리(②) 대상이다 — **지금은 작성 루틴이 이 파일을 고쳐 예외를 더하거나
만료일을 늘릴 수 있다(미해결 위험)**. `approved_by: "user"` 는 문자열일 뿐 사람의 승인을 증명하지 못한다.

**실측**(origin/main `6b0f62e4` 까지의 이력).
- F1: 대상 목록 칸이 없거나 목록이 아닌 판 0 — auctions 30판·fed/events 53·releases/index 61·calendar 140·movers 46·
  kr_movers 74·kr_index_etf 37·telegram 15(US 7·KR 8). 정상일 오차단 0/456판.
- F2: `kr_session.json` 92판(발행일 54일). 선물 창의 마지막 봉 15:30 이 91판(나머지 1판은 창 자체가 None — 2026-09-07,
  미국 노동절. 이것은 1회차 #4 의 `futures:<이름>` 결측이고 이번 기준과 무관), 환율 92판 전부 15:30. `WINDOW_END` 15:00 으로
  새로 막히는 판 0/92(발행일 0/54). 이 54일에는 KRX 조기 마감·개장 지연일이 없다 — 그런 날 선물·환율 봉이 15:30 KST 까지
  이어져 막히지 않으리라는 것은 **추정**이다(선물·환율은 KRX 와 무관하게 거래된다는 데서 나온 것, 실측 아님). 참고: 창의 **첫** 봉이 09:00 이 아닌 판이 1(2026-09-08, 13:00 시작·봉 6개) — 시작 쪽
  완결성은 이번에 보지 않았다(계획 밖, 잔여 위험).
- F3: 과거 자료로 오차단 비율을 잴 수 없다 — `collect.collected_at` 이 아직 배포되지 않았다. 「수집 커밋에서 그 파일이 바뀌지
  않은 횟수」(KR 42커밋 중 kr_session 6, US 105커밋 중 macro_metrics 2 등)는 같은 내용으로 다시 쓴 것과 못 쓴 것을 가르지
  못해 근거로 쓰지 않았다. **배포 뒤 첫 며칠의 `run` 분포를 보고 `EFFECTIVE` 를 넣어야 한다.**
- 변이 행렬(US 11/12·11/16, KR 11/12·11/13): 표시 모드 698/698 막힘(통과 0), 옛 모드 561/565 막힘 — 통과 4 는 전과 같은
  표시 없는 빈 대상 목록(`target_emptied`: 11/12 fed/events·releases/index, 11/16 auctions·releases/index), 모두 조건부·
  `unconfirmed_empty`. 새 변이: `drop_target_field` 18·`target_not_list` 20(두 방식), `rerun_failed` 51(표시 모드).

## 구현 검토 3회차(codex IMPL NO) 수정 — 2026-11-18

| # | 지적 | 고친 것 |
|---|---|---|
| G1 높음 | 승인 예외가 FRED id·변환·기준월만 같으면 걸린다 — 「2025-10 미발표」가 아닌 다른 이력 결측도 통과 | 수집기가 `missing_ref[키].lacking`(그 달을 만드는 데 필요한 비교 달 가운데 원천에 없는 것 — 전년 대비는 12개월 전, 전월 대비·차분은 한 달 전)을 적고, 정책 항목의 `lacking: "2025-10"` 과 **정확히 그 하나**일 때만 일치. 다른 달·여러 달·빈 목록(그 달은 있는데 값이 0 등)·칸 없음은 보류. 네 파일 전파도 같은 칸, 기록·알림에 원인 |
| G2 높음 | 행은 있는데 점수에서 빠진 지표가 결측·산출 범위에 안 잡히고 `total` 이 「쓴 수 + 2」 | `with_coverage(mm, excluded, expected)` — `expected` = ECON 표의 점수 대상. 쓰이지 않은 것을 까닭별로 전부: `no_value`(원천 미발표)·`no_score`(이력 부족, signed_z 없음)·`introduced`(들인 날)·`no_row`(행 없음). `macro_metrics_collect` 가 `no_score:<이름>`·`introduced:<이름>` 을 결측에 싣는다(등록되지 않은 키 — 섞인 날은 예외 미적용). `check_macro.coverage_hold` 는 지표 행에서 직접 점수 결측을 보고 수집 상태·산출 범위와 어긋나면 보류 |
| G3 중간 | `<div hidden>` 안의 산출 범위 표시가 통과 | 글 전체를 파서로 읽어 자신과 모든 상위 요소의 `hidden`·`aria-hidden`·`display:none`·`visibility:hidden`, `open` 없는 `<details>`(summary 밖), `script`·`style`·`template`·`noscript` 안을 숨김으로 본다. 주석 안은 표식 없음. 스타일시트의 클래스로 숨긴 것은 알 수 없다(잔여) |
| G4 높음 | 앞 실행이 `--begin` 뒤 죽으면 다음 실행이 `--begin` 없이 그 열린 기록을 쓴다 | `--begin` 이 실행 ID 를 적고 끝의 stamp 는 **같은 ID** 의 열린 기록만 쓴다(`COLLECT_RUN_ID` → `GITHUB_RUN_ID-ATTEMPT` → 로컬은 `--begin` 이 만든 값을 `--run-id` 로). 없거나 다르면 `run: unknown`. 두 워크플로가 두 단계에 같은 ID 를 넘긴다(정적 시험) |
| G5 (D) | 12월 CPI — 직전값이 없다고 행을 통째로 버린다 | `_econ_pair` 는 최신값이 계산되면 `(Actual, None)` — 행은 만들고 `previous`·`vs_prev` 는 null(더 오래된 달·추정치로 채우지 않는다). 최신값을 못 만들면 전처럼 결측. 표 게이트는 Previous·직전 대비 「—」를 받고 채운 값을 막는다. 축 점수는 이 칸이 아니라 변환된 이력으로 낸다. 작성자 지시 추가 |

하지 않은 것: 사람 승인 절차(E)는 사용자 답 대기 — 민감도 보류는 여전히 보류로 끝난다.

**G2 실측**(origin/main 의 `data/macro_metrics.json`, 발행일 64일 2026-08-17~11-17): 점수 대상 행에 점수가 없던(signed_z None) 날
**0일**(0/64 — 이력 부족은 평소에 흔하지 않았다). 지표를 들인 날은 **1일**(2026-11-09 — Housing Starts·Trade Balance·
Construction Spending MoM·Factory Orders MoM 넷)인데, `introduced` 칸은 2026-11-08 변경부터 있어 그 칸이 있는 자료는 7일
(11/09~11/17)뿐이다 — 분모는 **1/7**(전체로는 1/64). G2 로 새로 partial(보류)이 되는 날은 그 하루다. 들인 지표의 발표 시점을
알 수 없으면(`pending` — 키 없음·조회 실패) 다음 날에도 들인 상태로 남으므로, FRED 키가 죽은 기간에는 하루를 넘겨 보류될 수
있다(이력에서 `pending` 은 0일). 들인 날을 보류로 둘지는 정할 일이다 — 지금은 계획대로 「쓰이지 않은 것은 전부」로 구현했다.

**G5 확인.** 직전 칸을 읽는 곳: `macro_metrics.vs_prev`(None → None), `macro_table_gate`(정본이 None 이면 칸이 「—」여야 하고
직전 대비도 「—」), `anatomy_gate.headline_terms`·`macro_gate.structured_figures`(None 은 건너뛴다), `number_audit`(축 표는
`macro_table_gate` 에 맡긴다). 점수는 `transform_series`(날짜로 맞춘 변환 이력)에서 나오고 표의 직전 칸을 읽지 않는다 —
시험이 같은 이력에 직전 칸만 바꿔 점수가 같음을 확인한다. 다만 **모멘텀은 변환 이력을 위치로 센다**: 빠진 달(2025-10·2026-10
전년 대비)이 있는 계열은 이웃한 두 점이 두 달 떨어져 있을 수 있다(전부터 그랬고 고치지 않았다 — 점수의 계약).
2026-12-10 뒤 상황은 합성 자료로 수집 → 점수 → 수집 상태 넷 → 실제 정책의 자료 판정 → 보류 판정 → 축 표 게이트까지 돌려
예외 없이 통과함을 확인했다(`test_g5_after_december_cpi_us_passes_without_the_exception`). 실제 FRED 응답·실제 글은 아니다.

### 사용자 추가 지시 — 2026-11-18 (3회차에 더함)

**1. 같은 실행인가(G4 강화).** 입력 자료·검사 결과·발행 대상이 한 실행에 속한다는 것을 세 고리로 본다.

| 고리 | 이미 있던 것 | 비어 있어 메운 것 |
|---|---|---|
| 수집 장부 | 파일마다 sha256·`run`, 장부의 `run_id`(G4) | 적용일부터 장부의 `report_date` 가 글 날짜와 같고 `run_id` 가 있어야 한다(아니면 `stale`·`incomplete_fields` — `inputs._health` 의 meta) |
| 검증 기록 | 글 해시 `post.sha256`, 입력 파일마다의 해시 `inputs.files`(장부도 자료 폴더의 파일이라 들어 있다), 검사 코드·레포 원장 해시 | `collect_run` — 이 검사가 읽은 장부의 실행 ID·세션·해시·`checked`(장부가 없으면 `{present: false}`) |
| verify | 글 해시·입력 해시·검사 코드·레포 원장 대조, 입력 뿌리 누락 | 기록의 `collect_run` 과 지금 디스크 장부의 대조 — 다르면 「수집 실행이 다르다」(exit 1, 다시 기록) |

재현 시험(`scripts/verification/tests/test_run_binding.py`): 장부만 새것·입력은 옛것(`changed_after_collect`, 적용일 무관 — 전부터
막혔다), 기록은 옛것·장부는 새 실행, 기록은 옛것·입력은 새것(전부터 막혔다), 기록은 옛것·글은 새것(전부터 막혔다), 장부가
지워지거나 깨짐, 장부 없이 기록한 뒤 장부가 생김, 다른 세션의 장부·실행 ID 없는 장부(적용일부터). verify 의 어긋남은 exit 1
(다시 record — 지금 파일로 검사를 다시 돌린다)이고 미완료(2)가 아니다: 기존 계약을 그대로 두었다. `collect_run` 칸이 없는 옛
기록은 입력 해시 대조만 받는다.

**2. 없는 값의 상태.** 「미발표」로 뭉뚱그리지 않는다 — `us.macro_metrics.MISSING_STATES`.

| 상태 | 뜻 | 판별 |
|---|---|---|
| `not_published` | 원천 기관이 그 값을 내지 않았다 | 원천 응답에 그 달 행이 있고 값이 빈칸(`us.fred.FredClient.blank_dates` — API 의 `.`, CSV 의 빈칸) |
| `not_collected` | 원천에 그 달 자체가 아직 없거나 우리가 그 범위를 받지 않았다 | 응답에 그 달 행이 없다 |
| `collect_failed` | 받으려다 실패했다 | 수집기의 `fetch_failed`(행도 no_value 도 아니다 — 다른 결측 키) |
| `unknown` | 가를 근거가 없다 | 빈칸 정보를 얻지 못했다 — 추정하지 않고 보류 쪽 |

쓰이는 곳: ① no_value 지표의 `missing_ref[키].lacking_why = {달: 상태}` — **승인 예외는 그 달이 `not_published` 일 때만**
(`_accepted`). ② 직전 칸이 null 인 행의 `previous_why` — 표의 Previous 칸은 「— (미발표|미수집|수집 실패|확인 불가)」, 축 표
게이트가 사유를 대조한다(사유 없는 「—」·다른 사유·채운 값은 위반, 사유 칸이 없는 옛 자료의 행은 「—」만). `unknown` 이면
`previous_unknown:<이름>` 이 `collect.missing` 에 들어가 보류. ③ 산출 범위 문장(원천 미발표 / 원천에 비교 달 없음).
한계: 판별은 FRED 응답의 모양에 기댄다 — 「행이 있고 값이 빈칸」을 「기관이 내지 않았다」로 읽는 것은 FRED 의 관례이고,
BLS 발표문을 직접 읽어 확인하는 것이 아니다(2026-10 CPI 는 본체가 발표문으로 따로 확인했다).

**3. 「N개 중 M개」와 실제 계산.** `check_macro.coverage_hold` 가 M(`coverage.used`)을 지표 행에서 다시 세어 대조하고(다르면
보류), N 이 M + 제외 목록 수와 같은지 본다. 글의 표식은 `_check_coverage` 가 `N개 중 M개`·제외 지표 이름·까닭을 대조한다
(`test_hold_when_the_data_cannot_be_judged`, `test_gate_requires_the_visible_coverage_marker`,
`test_g2_gate_finds_unused_rows_even_when_both_records_omit_them`). **N 을 ECON 표의 정의와 대조하는 것은 수집 쪽뿐이다**
(`test_g2_expected_comes_from_the_econ_table`) — 게이트는 ECON 표를 읽지 않는다(수집기 모듈을 게이트 환경에서 가져오지 않는다).

**4. 물가 지표 누락 영향 — 발행일별**(origin/main 의 `data/macro_metrics.json`, 발행일 64일 2026-08-17~11-17, G2 가 새로 보류하는 날).

| 날짜 | G2 로 새로 보류되는 사유 | 판정 |
|---|---|---|
| 2026-08-17 ~ 11-06 (57일) | 없음 | — |
| 2026-11-09 | `introduced` ×4 — Housing Starts·Trade Balance·Construction Spending MoM·Factory Orders MoM 을 들인 날(점수에서 하루 뺀다) | **오차단 쪽** — 네 지표의 자료는 다 받았고 값도 있다. 구성 변경이 혼자 축을 움직이지 못하게 하루 빼는 설계다. 다만 그날 축 점수가 정의된 지표 전부로 나온 것은 아니라는 점에서는 표시 대상이다 |
| 2026-11-10 ~ 11-17 (6일) | 없음(G2 로 새로 생기는 사유는 없다) | 이 6일은 CPI 전년 대비 둘의 no_value 로 이미 보류 대상이다(1회차 #5·민감도) — 실제 결측(BLS 미발표), 정당 |

분모: 새로 보류 1/64(오차단 쪽 1, 정당 0). **판정 불가**: `introduced` 칸은 2026-11-08 변경부터 자료에 있어 그 전 57일은 「들인
날이었는가」를 자료로 가를 수 없다(칸이 있는 7일 중 1일). 「행 자체가 없는 지표(no_row)」는 그날의 ECON 표 구성을 자료가 말해
주지 않아 57일 모두 판정 불가다(지금 ECON 으로 세면 11/09 전의 모든 날에 그날 아직 없던 네 지표가 「없음」으로 나온다 — 실제
결측이 아니다). 점수 없는 행(no_score)은 64일 모두 판정 가능하고 0일이다.

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
- **지금 등록된 예외는 어떤 결과도 바꾸지 않는다.** 12/09 까지는 실측한 날이 모두 민감도 보류(5/5)이고, 12/10 부터는 G5 로
  행이 만들어져 예외 없이 통과한다. 열려 있는 결정은 사람 승인 절차(E)다.
- **3회차 뒤에 남은 것.** ① KR 장중 창 — 조기 마감일·수능일(10:00~16:30)·개장 지연일에 선물·환율 30분봉이 어느 시각까지
  제공되는지 **확인하지 못했다**. 15:00 전에 정상적으로 끝나는 자료라면 오차단이고, 16:30 까지 이어지는 날은 15:30 에서 자른
  창을 완결로 본다. ② 사람 승인 절차가 없다 — 민감도 보류는 풀 길이 없다. ③ `missing_ref`(식별자·기준월·`lacking`)는 수집기가
  적는 자료다 — 원천을 독립적으로 증명하지 않는다. ④ 산출 범위 표시를 스타일시트의 클래스로 숨긴 것은 게이트가 모른다.
  ⑤ 지표를 들인 날은 그 지표가 점수에서 빠져 US 가 보류된다(2026-11-09, `introduced` 칸이 있는 7일 중 1일).
  ⑥ 행 자체가 없는 지표는 수집기의 `coverage`·`collect` 가 말해 줘야 게이트가 안다(게이트는 ECON 표를 읽지 않는다).
  ⑦ 12/10 뒤 통과 확인은 합성 자료·함수 수준이다 — 실제 글을 `run_gates` 로 돌린 것이 아니다.
