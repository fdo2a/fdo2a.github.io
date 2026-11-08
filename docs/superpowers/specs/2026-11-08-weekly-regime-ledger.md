# 주간 레짐 점검 — 새 발표 원장과 축별 채점 (2026-11-08)

## 왜

US 주간 인사이트의 「경기 국면 점검」(`period_scorecard.regime_check`)은 W40 부터 W45 까지 매주
「판정불가 · 기간 중 신규 발표 없음」이었다. 원인 셋:

1. `macro_metrics.indicators[].released` 로 발표를 골랐는데 **그 필드를 쓰는 코드가 없었다.** 옛
   테스트는 실제 데이터에 없는 모양(소문자 축, `released`)으로 만들어져 통과했다.
2. 주간 빌드(`build_scorecard.py`)는 그날 `macro_metrics.json` 하나만 읽었다 — 표시를 붙였어도
   월요일 발표는 금요일 파일에 없다.
3. 물가 행을 성장축 부호(`개선/악화/보합`)로 채점했다.

git 재생(`data/macro_metrics.json` 커밋 전부)으로 확인한 일간 `new_releases` 의 결함 — 이 작업 범위
밖, 일간에는 그대로 있다:

- 같은 기준월의 **개정을 신규로 센다** — 11/03 내구재 1.84→1.91.
- **같은 날 재실행이 신규를 지운다** — 11/05 를 11/06 09:13 에 다시 돌리자 `[]`(책이 이미 승격돼
  `last_seen` 이 오늘 값).

W45 실제 신규: JOLTS(11/3)·청구 3행(11/5)·고용 3행(11/6). GDP·PCE 는 10/29(W44).

## 원장 `data/history/releases.jsonl` (`us/release_ledger.py`, `scripts/record_releases.py`)

덧붙이기만 한다. 한 실행의 행은 **한 번의 원자적 쓰기**(임시 파일 + `os.replace`). 같은 id 는 거부,
손상된 줄이 있으면 읽기·쓰기 모두 멈춘다(`history.read_jsonl` 처럼 건너뛰면 다음 쓰기가 그 줄을 지운다).

| kind | id | 뜻 | 채점 |
|---|---|---|---|
| `scan` | `scan\|날짜\|run_id` | 그 실행이 받은 지표(`observed: [[이름, 축, role]]`). 실행마다 한 줄 — 재시도가 앞 기록을 덮지 않는다 | — |
| `release` | `이름\|기준기간` | 기준기간이 원장 마지막 상태보다 앞으로 감. 첫 기록이 이긴다 | ○ |
| `revision` | `이름\|기준기간\|rev\|날짜\|run_id` | 같은 기준기간, 값 변경. **GDP 2·3차 추정이 여기** — 속보만 새 발표 | × |
| `baseline` | `이름\|기준기간\|baseline` | 원장이 처음 보는 이름 — 그날 발표였는지 알 수 없다 | × |

- **신규 판정 기준 = 원장 자신의 마지막 상태**(release·revision·baseline). `macro.json.last_seen`
  을 보지 않는다 — 책 승격·재실행·묵은 책과 무관하다.
- **같은 실행의 파일인가**: `market_data`·`econ_indicators`·`macro_metrics` 의 `generated` 가 모두
  같고 report_date 가 같을 때만 쓴다(수집기 한 프로세스가 같은 값을 단다). 아니면 아무것도 안 쓴다 →
  주간에서 수집 누락일. 원장 마지막 scan 보다 앞선 날짜도 거부.
- 기준기간이 뒤로 가면(CSV 폴백 등) 경고만, 행 없음.
- `role`: 지표 행 → 같은 실행의 `econ_indicators` → 기본 `scored`. `anatomy` 는 기록만 하고 채점 안 함.
- `trend` = `macro_metrics` 의 `direction`(3개월·청구 4주 모멘텀). 책이 축 점수=모멘텀으로 움직이므로
  「책을 지지하는가」의 같은 잣대다. 그 달 숫자의 직전 대비(`vs_prev`)와 다르다 — 함께 남긴다.
- `since` = **그 지표가** 마지막으로 관측된 날(전역 직전 수집일이 아니다 — 계열 하나만 빠진 날).
- `gap` = 기준기간이 한 칸(월간 1개월·주간 7일·분기 3개월, `polarity_for` 의 창으로 가린다)보다 많이 감.

### 공식 발표일

`calendar.json` 의 창은 report_date+1 부터라 **어제 파일에 오늘 일정이 있다.** 그래서 기록 단계는
워크플로에서 「Build the next-ten-days calendar」 **앞**에 돈다. 조건(모두): 일정 파일의
report_date < 감지일 ≤ report_date+horizon, 창 (since, 감지일] 안에 `release-<slug>-YYYYMMDD`
**전체 일치**·`confirmed` 일정이 정확히 하나, gap 아님. 아니면 `null`. 같은 날 재실행은 오늘 쓴 일정을
읽어 일치가 없으므로 null — 틀린 날짜가 붙지는 않는다.

## 주간 채점 (`regime_check(macro_rows, ledger_rows, start, end, holidays)`)

1. **기대일** = [start, end] 평일 − `market_holidays.json` `us` 날짜. 채권만 쉬는 날(`us_bond`, 11/11)은
   기대일이다. 휴일표가 없거나 `valid_through` < end → 판정불가.
2. baseline 아닌 scan 이 없는 기대일이 하나라도 있으면 **전체** 판정불가(`missing_days`).
3. 기간 안에 baseline 이 생긴 이름은 그 주 채점에서 빼고 `excluded_new` 에 남긴다(축 전체를 죽이지 않는다 —
   지표를 더한 주마다 성장축이 사라진다).
4. 축의 scored 지표가 **마지막 기대일까지 관측되지 않았으면** 그 축 판정불가(`stale`). 대상은 기간 끝까지
   최근 35일(`RETIRE_DAYS`) 안에 한 번이라도 관측된 이름이다 — 기간 안 관측만 세면 한 주 내내, 직전 수집만
   보면 2주째 빠진 지표가 대상에서 사라진다(codex 구현 2·3회). 35일보다 오래 안 보이면 목록에서 뺀 것으로
   본다. 그래서 **지표를 수집 목록에서 빼면 그 축이 최대 5주 판정불가**가 된다(보수적인 쪽).
   원장 줄 모양(`release_ledger.check_row`: id·kind·날짜·observed 항목·axis/role/trend 문자열·gap 불리언)이
    틀리면 읽기에서 멈추고, 주간은 축마다 「새 발표 기록을 읽지 못했다」.
5. 행은 감지일 ≤ end 만(과거 주를 다시 셀 때 미래가 섞이지 않게). 날짜: 공식일이 있으면 그날, 없으면
   (since, 감지일] 의 모든 날. 전부 기간 안 → 포함, 전부 밖 → 제외, 걸침·since 없음·gap → 그 축 판정불가(`uncertain`).
6. 책 = 그 날짜 **전날까지** 쓰인 마지막 `macro.jsonl` 행(그날 책은 그날 발표를 보고 썼다). 창 안 날짜마다
   책 부호가 다르면 판정불가. 책·축 값이 없으면 `no_book`(0 이 아니다).
7. 축 어휘: 성장(Labor·Activity·Consumption) {개선 +1, 악화 −1, 보합 0} ↔ `regime.growth`, 물가
   {재가속 +1, 둔화 −1, 교착 0} ↔ `regime.inflation`. 그 밖 = `no_trend`.
8. 집계: `scored`(책 ≠ 0) 중 `agree`(같은 부호)·`against`·`flat`. **flat 은 분모에 든다**(책 방향을 지지하지 않음).
   `ratio = agree/scored`, **0.5 포함 정합**. 판정 순서: stale → uncertain → 발표 없음 → no_book 있음 →
   scored > 0 이면 정합/불일치 → 책 0 만 있으면 「기준 보합」+`lean`(up/down/flat) → 그 밖 판정불가.
   한 표 = (이름, 기준기간) 하나. 청구 3행·CPI 4행은 각각 한 표 — 일간 축 폭(「N개 중 K개」)과 같은 셈.
9. 최상위: 판정 축이 모두 정합 → 정합, 모두 불일치 → 불일치, 갈리면 엇갈림, 판정 축이 없고 기준 보합이
   있으면 기준 보합, 그 밖 판정불가. `partial` = 일부 축만 판정.
10. 출력 `prints` 에는 수치(actual·previous)를 넣지 않는다 — 숫자 게이트(`period_gate._numbers`)의 허용
    집합을 넓히지 않는다. 날짜 필드(`missing_days`·`official_date`·`detected_on`)는 `_DATE_FIELDS`.

## 백필

`scripts/backfill_release_ledger.py` — `data/market_data.json` 커밋을 `--first-parent` 시간순으로
재생, 각 커밋의 세 파일 + **부모 커밋의** `calendar.json`. `generated` 불일치 커밋은 건너뛴다. 이미 있는
원장 위에는 쓰지 않는다. 2026-11-08 시드: 252행, 57일(08-17~11-06; 10/21 은 지표 0개 수집이라 빠진다 → W43 판정불가). W45 재생 = 신규 7 + 내구재 개정 1
(정답과 같다). 과거 주간 글은 다시 쓰지 않는다.

W45 를 새 규칙으로 세면: 성장 「기준 보합」(책 교착, 새 발표 7건 중 개선 5·보합 2), 물가 「새 발표 없음」.

## 잔여 위험

- **FRED 가 한 주기를 통째로 늦게 올리면** 이전 기준월 값이 다음 발표의 confirmed 일정과 묶여 공식일이
  한 회차 밀릴 수 있다(codex 2회차 #3, 기각). 그 날짜도 값이 실제로 보이기 시작한 창 안이다.
- 일정이 없거나 FRED 키가 죽은 날은 공식일이 null → 월요일 감지분은 (금, 월] 창이 주 경계에 걸려 그 축이
  판정불가가 된다. 보수적인 쪽이다.
- 원장은 하루 4-6 scan(재시도)을 남겨 1년에 2-3MB 로 자란다.

## codex 검토

설계 1회차 NOT OK(차단 4·중대 10), 2회차 NOT OK(차단 2·중대 7) — 처분표는 `report/plan.md`
「2026-11-08 — US 주간 레짐 점검 수리」.
