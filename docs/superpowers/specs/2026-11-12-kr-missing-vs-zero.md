# KR 수집기 — 못 읽은 값 ≠ 0, 지수 등락률 검증 (2026-11-12)

## 왜

KR 수집기가 못 읽은 값을 0 으로 채웠다. 지수 등락률(`fluctuationsRatio`)을 못 읽으면 `0.0`, 수급 주체 하나를 못 읽으면 그 주체가 `0`(세 주체가 모두 0 일 때만 행을 버렸다), 거래대금·거래량·시총을 못 읽으면 `0`. 종가 `"nan"` 은 `float()` 를 통과했고 `close <= 0` 검사는 NaN 에 거짓이다. 수집기는 지수 하나만 있어도 `complete=True` 였고(`indices` 가 비었는지만 봤다), 수급은 한 시장만 있어도 코어를 통과했다(`any`).

발행 사고는 0건이었다(10/28-11/10 스냅샷 20행, 원장 역산 잔차 최대 0.005%p). 잠재 위험이다. 출발은 「NONE 은 0 과 구분」「기존 분석값을 읽은 것만으로 독립 검증이 아니다」를 이 수집기에 대 본 결과다.

재수집도 같은 꼴로 값을 지웠다. `us/history.append_jsonl(upsert=True)` 는 같은 날짜 행을 통째로 바꾼다 — 한 지수를 못 읽은 재수집이 원장의 그 지수를 지운다. `period.upsert_session` 도 세션을 통째로 바꿔, 거래대금 수집이 실패한 재실행이 앞 실행의 `_sessions[D].top_value` 를 빈 값으로 덮는다.

## 사용자 결정(2026-11-12, 바꾸지 않는다)

1. 수집기가 못 읽은 값은 0 이 아니라 결측이다.
2. 지수 등락률을 못 읽었거나 검증하지 못한 날은 KR 브리프를 발행하지 않는다(`complete=false`). 계산값으로 채워 싣지 않는다. 검증 불가로 진짜 보합일이 하루 막히는 것은 받아들인 비용이다(루틴의 재수집이 integration 이 따라온 뒤 다시 판정한다).
3. 검증은 같은 응답 안 비교가 1차다. `mismatch` 차단은 약 10거래일 관찰 뒤 사람이 설정으로 켠다(날짜 자동 전환 없음).
4. 2026-10-17 에 기각한 「직전 종가 연속성 검사」를 되살리지 않는다 — 원장은 판정 입력이 아니다.
5. 범위 밖: 일본·US 수집기, 폐지된 program/intraday 파서, 「전 거래일 기준」 라벨 문구, KR 발행본 숫자 대조 게이트.

## 무엇을 하나

**숫자 읽기** — `kr/parse.num_or_none`: 쉼표·`+` 제거. `None`·`""`·`"-"`·변환 불가·NaN·±Infinity·bool → `None`. `"0"`·`"0.00"` 은 관측된 0.

**지수** — `fetch_index` 는 `{close, change_pct, trade_date, prev_diff}`(R·D 는 None 가능, C 가 None·≤0 이면 예외). `fetch_index_ohlc` 는 `flow_bizdate`(integration `dealTrendInfo.bizdate`)를 더한다 — `kr_intraday.json` 에는 싣지 않는다. 판정은 `kr/index_check.check_pct(C, R, D, integ, report_date, mode)`:

| # | 조건 | status | 발행 |
|---|---|---|---|
| 1 | R 없음 | `ratio_missing` | 차단 |
| 2 | 기준 전일 종가: `Pb=C−D`(유한 양수), 아니면 integration `Pi`, 둘 다 없으면 | `unverified` | 차단 |
| 3 | `|R − (C/P−1)·100| > 0.01` | `mismatch` | 설정 `warn` 이면 통과, `block` 이면 차단 |
| 4 | 일치, 보합 아님 | `ok` | 통과 |
| 5 | 일치, 보합(`|R|<0.01`), `|C−Pi| ≤ 0.01` | `ok_flat` | 통과 |
| 6 | 일치, 보합, Pi 가 어긋나고 세션 표식 맞음 | `flat_contradicted` | 차단 |
| 7 | 일치, 보합, 그 밖 | `flat_unverified` | 차단 |

- 세션 표식 `matched` = `flow_bizdate == report_date` 이고 `low−0.01 ≤ C ≤ high+0.01`. 차단 상태의 **이름만** 고른다(6·7 은 둘 다 차단) — 대리 지표라는 약점이 판정을 틀리게 만들지 못한다.
- R=0·D=0 으로 함께 오는 가짜 보합은 3 을 통과하지만 5 를 못 넘어 첫날부터 막힌다. 5 의 거짓 통과는 integration 이 우연히 오늘 종가와 0.01pt 안일 때뿐이다(받아들인 잔여 위험).
- `cross_note`: Pb·Pi 가 둘 다 있고 matched 인데 0.01pt 넘게 다르면 기록·경고만.
- TOL 0.01%p 근거: R 반올림 반폭 0.005 + C·D 반올림분(코스닥 700 기준 약 0.0015).
- 11/12 실측(KOSPI basic C 5,342.73 · R −0.61 · D −32.63, integration lastClosePrice 5,375.36 = C−D) → `ok`.

**원장 가드와 진짜 보합일(codex 구현 검토 1회 #1)** — 2026-10-17 가드(`history.ledger_conflicts`)는 「다른 날과 모든 지수 종가가 같으면 한 세션이 두 날짜에 적혔다」로 멈춘다. 진짜 보합일은 여기에 걸린다. 종가 중복만 걸렸고 **두 지수 모두** 이 실행에서 `ok_flat` 이면서 `matched`(integration 이 이 세션 값이라는 표식)이면 그 검사만 건너뛴다(`verified_flat`). 이른 날짜 문제는 그대로 막는다. 한 지수만 남은 실행은 보합이 검증돼도 멈춘다 — 증거가 약하고 그 실행은 어차피 발행할 수 없어(complete=false) 재수집을 기다리는 쪽이 보수적이다.

**업종 상승 종목 수(구현 검토 1회 #2)** — `riseCount`·`totalCount` 를 못 읽으면(또는 전체 0) `breadth=None`. `leadership.flag_leadership` 은 None 을 판정하지 않는다(`liquidity_backed=None`, `leading=False`, note 없음 — 좁은 상승으로도 주도로도 부르지 않는다). 중앙값은 읽은 값만으로 잰다.

**설정** — `config/kr_index_check.json` `{"format": "kr-index-check/1", "mismatch": "warn"}`. 없으면 warn(`missing_default`), 깨졌거나 모르는 값이면 block(`invalid_block`) — 오타가 차단을 조용히 끄지 않게. 켜는 절차: `python3 scripts/kr/index_check.py --report`(origin/main 의 실행 manifest 로 거래일·실행별 status 표, 읽기 전용)로 10거래일 이상 mismatch·cross_note 0건을 사람이 확인한 뒤 `block` 으로 바꿔 커밋. 같은 커밋에서 `scripts/kr/tests/test_index_check.py::test_committed_config_is_warn` 을 고친다(커밋된 값을 고정하는 시험은 이것 하나다 — 수집 전 시험이 빨개지면 그날 수집이 멈춘다).

**완결성** — `indices` 는 코스피·코스닥 **둘 다** 종가·등락률이 수이고 status 가 차단이 아닐 때만 통과. 아니면 기존 토큰 `"indices"`(새 토큰 없음 — `KR_ORCHESTRATOR.md` 의 허용 목록이 그대로 맞는다). 차단이어도 `indices.<지수>.change_pct` 는 네이버 값 그대로(None 포함). 종가는 원장에 들어간다.

**수급** — `flows.classify_row` → `ok`(세 주체 모두 수, 하나 이상 0 아님)·`zero`(관측된 0 셋: 휴장·미래·미게시 당일)·`partial`·`unreadable`(bizdate 불일치 포함). `sources.walk_market_flows` 는 지금처럼 하루씩 거슬러 가되 **첫 ok 행 앞에서** unreadable·partial 을 만나면 `blocked="unreadable_before_latest"`(남은 최근 행을 「전 거래일」이라 부를 수 없다). 첫 ok 행보다 오래된 날은 그 날만 빼고 진단에 남긴다(주간 집계가 잠정/결측 일수로 센다). 요청 실패는 진단을 실은 `FlowsFetchError`. `fetch_market_flows` 는 list 반환 그대로. 수집기 `flows_ok` 는 **두 시장 모두**(`any` → `all`) — 「코어 표에 구멍이 있으면 발행 중단」과 맞춘다. 18:00 에 당일이 `zero` 이고 앞 거래일이 ok 면 지금처럼 「전 거래일 기준」으로 발행한다.

**거래대금** — `fetch_top_value_stats` → `(rows, {rows, dash, bad, dash_top100})`. `-`·빈 값은 거래 없음(dash), 그 밖의 변환 불가는 bad — 둘 다 순위에서 뺀다. 예외: bad > max(5, 1%), dash > 30%(실측 약 7%), 시총 순 처음 100행 중 dash+bad > 5(실측 0), 시장 행 0. 정규화 표에서 거래대금 > 0 행이 10개 미만이면 `top_value=[]`(결측). 묶음 거래량은 구성원 하나라도 None 이면 None. dash 비율 15% 초과는 경고만.

**재수집 병합(있던 값을 지우지 않는다만 더한다)**
- 원장: `kr/history.merge_index_record(existing, new)` — 지수별로 new 에 유한 양수 종가가 있으면 그 값, 없으면 existing. 수집기가 `append_jsonl(upsert=True)` 전에 합친다. 수집기는 발행 여부를 보지 않는다.
- 주간: `kr/period.merge_session(existing, new)` — new 에 없는 시장의 flows 는 existing 유지(flows 가 비지 않으면 `flows_note` 를 뺀다). 업종 묶음(industry + leading_industries)은 new industry 가 비었으면 둘 다 existing, 아니면 둘 다 new(빈 leading 도 그대로 — 주도 업종이 없는 날은 정상). 거래대금 묶음은 new 가 비었으면 existing, 아니면 통째 교체. `upsert_session` 과 `versions_kr.merge_week` 미발행 가지가 같은 함수를 쓴다. 당일 잠정 수급은 애초에 세션에 들어오지 않으므로(`session_from`) 잠정치가 확정치를 덮는 경로는 없다.
- 모드별: shadow 는 수집기 출력 그대로(오늘과 다른 점은 못 읽은 지수의 기존 값을 지우지 않는 것 하나 — 새 자동 보완 경로가 아니다). enforce·발행됨은 그대로 P 값, 빈 지수는 빈 채(「Never auto-fill a published gap」). enforce·미발행 + 승격이면 `merge_ledger` 의 미발행·「P 못 찾음」 가지가 `merge_index_record` 로 합치고 승격이 맨 마지막.

**기록과 알림**
- `kr_market_data.json.checks` = `{index_pct: {mode, config_status, KOSPI, KOSDAQ}, flows: {시장: {state, faults}}, top_value: {rows, dash, bad, dash_top100, positive_rows} | {error}}`. 작성자는 본문에 옮기지 않는다. `kr_flows.json[시장].diagnostics`.
- 실행 manifest(`common/versions.reconcile`)에 `checks` 전체 사본 + `field_status` 요약 — 기록만. manifest 는 실행마다 추가만 되므로 같은 날 뒤 정상 재수집이 고정 경로를 덮어도 앞 실행의 기록이 남는다. 알림과 `--report` 는 이것만 읽는다.
- 당일 저녁: 차단은 complete=false → 루틴이 멈추고 미발행 감시(`review/publish_watch._collection_note`)가 빠진 코어와 status 를 고정 문구로 붙인다.
- 다음 날 09:00 이후: `verify_digest` 가 origin/main `versions/kr/` 최근 3거래일 폴더의 manifest checks 로 줄을 낸다(경고 포함). 폴백만 있는 날은 「판 기록 없이 올라간 수집 N건」 + `kr_market_data.json` 보완. 읽기 실패는 한 줄. 키 (거래일|항목|status)는 요약에 실린 줄만 제출본에 싣고, 접수 확인 뒤 `kr_checks_seen` 에 기록(14일 보관). enforce 보류(push 없음)는 원격에 없어 Actions `::warning::` 만.

## 남는 한계

- 시총 100위 밖·전체 30% 미만의 거래대금 부분 장애는 구분할 수 없다(네이버가 「거래 없음」과 「값 없음」을 같은 `-` 로 준다). 통계를 매 실행 남기고 15% 초과는 경고.
- 진짜 보합일에 integration 이 늦거나 실패하면 그 실행은 막힌다(재수집이 푼다).
- 네이버가 휴장일을 `"0"` 이 아니라 빈 값으로 주기 시작하면 연휴 뒤 첫날이 `unreadable_before_latest` 로 막힌다(닫힌 쪽 실패).
- shadow 의 발행일 재수집 자동 보완은 이 변경 전과 같은 상태로 남는다(보호는 enforce 의 몫, 전환은 사용자 확인).

## 배포 뒤 확인

- 첫 Actions 실행: 사전 시험 통과, `checks.index_pct` 두 지수 ok(차이 ≤ 0.01), `mode=warn/ok`. top_value 통계 dash 약 150·bad 0·dash_top100 0, 수급 faults 없음, complete=true, `missing` 은 전과 같다. 그날 발행 정상, 주간 `_sessions` 이어짐.
- 연휴 직후 1회(휴장일 수급이 여전히 `"0"` 인지).
- 10거래일 `--report` 로 mismatch·cross_note 0건 → 사용자에게 block 전환 여부 보고.

설계 이력(v1-v3.2, codex 설계 검토 5회): `../plan.md` 2026-11-12 절.

When changing this: read this spec before touching `scripts/kr/index_check.py`, `scripts/kr/parse.py`, or the missing-value paths in `scripts/kr/sources.py`·`scripts/kr/flows.py`.
