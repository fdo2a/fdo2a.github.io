# KR 브리프 — 외국인·기관 장중 수급 전개 설계

작성일: 2026-08-06 · 대상 파이프라인: `fdo2a/fdo2a.github.io` (KR 저녁 마감브리프)

## 배경·목표

지금 §5 수급 섹션은 하루치 **확정 순매수 한 줄**만 다룬다. "외국인 -1조 2,502억 순매도"는 결과일 뿐, 그 매도가 개장 직후부터 일관됐는지 오후에 급반전한 것인지를 구분하지 못한다. 전략 관점에서 실제로 읽어야 하는 건 **언제 방향이 꺾였고 가격이 그걸 따라갔는가**다.

2026-07-29 코스피가 이 차이를 잘 보여준다. 외국인은 10시까지 +2,352억 순매수였다가 11시 30분 +129억으로 되돌렸고, 14시 30분 이후 매도를 급격히 키워 -1조 2,445억으로 정규장을 마쳤다. 같은 시간 코스피는 6,112 → 5,663. "종일 순매도"와는 전혀 다른 그림이다.

**목표**: 장중 누적 순매수 궤적을 결정론적으로 수집해 §5 수급에 서브블록으로 싣고, 방향 전환 시점을 지수 궤적·프로그램 매매와 교차 검증한다.

## 결정 사항 (2026-08-06 사용자 확정)

- 표현 형식: **차트 + 30분 앵커 표 + 서술** 3종 모두.
- 기관 세부 주체: **수집은 전 주체**, 리포트 서술은 **금융투자·연기금등** 두 축만. 표는 개인·외국인·기관계 3열 유지.
- 배치: **§5 수급 안 서브블록** (일별 확정 표 뒤, 프로그램 매매 앞).

## 1. 데이터 소스

`https://finance.naver.com/sise/investorDealTrendTime.naver?bizdate=YYYYMMDD&sosok={01|02}&page=N`

- **누적** 순매수(억원) 스냅샷. 2026-07-29 코스피 기준 09:03~18:06, 182개 시점(약 2~3분 간격), 페이지당 10행 × 37페이지.
- `table.type_1`, 데이터 행은 `<td>` 11개:

  | idx | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 |
  |---|---|---|---|---|---|---|---|---|---|---|---|
  | 헤더 | 시간 | 개인 | 외국인 | 기관계 | 금융투자 | 보험 | 투신(사모) | 은행 | 기타금융기관 | 연기금등 | 기타법인 |
  | 키 | `t` | `individual` | `foreign` | `institution` | `fin_invest` | `insurance` | `trust` | `bank` | `other_fin` | `pension` | `other_corp` |

  헤더는 2행(1행: 시간·개인·외국인·기관계·기관(colspan 6)·기타법인 / 2행: 금융투자~연기금등). 검증: 13:21 행에서 `기관계 21,678 = 14,964 + 397 + 5,573 - 46 - 19 + 809`.
- `bizdate`가 비거나 휴장일이면 헤더만 반환 → 빈 결과로 자연 방어.
- 페이지 범위를 넘기면 마지막 페이지 내용이 반복된다 → **직전 페이지와 동일하면 중단**.
- 인코딩 EUC-KR (`sources.fetch`가 이미 처리).

## 2. 수집 — `scripts/kr/flows_intraday.py` (신규, 순수 함수)

| 함수 | 계약 |
|---|---|
| `parse_intraday_flows(html) -> list[dict]` | `table.type_1`의 11-td 행만 채택. `t`는 `HH:MM` 문자열, 나머지는 int. 파싱 불가 행은 조용히 스킵 |
| `collect_pages(fetch_page, max_pages=45) -> list[dict]` | `fetch_page(n)`을 1부터 호출. 빈 결과 또는 직전 페이지와 동일한 시각 집합이면 중단. 시각 기준 dedupe 후 **시간 오름차순** 정렬 |
| `build_series(rows, anchors=ANCHORS) -> dict` | 정규장 컷 → 앵커 스냅 + extremes + turns + session_last |

### `build_series` 규칙

- **정규장 컷**: `t <= "15:30"`인 행만 궤적으로 쓴다. 15:30 초과(시간외·정정 반영)는 버린다.
- **앵커 스냅**: `ANCHORS = ["09:30","10:00","10:30","11:00","11:30","12:00","12:30","13:00","13:30","14:00","14:30","15:00","15:30"]`. 각 앵커에 **`t <= anchor`인 마지막 관측치**를 붙인다. 해당 관측치가 없으면 그 앵커는 **생략**(보간·창작 금지). 09:00은 첫 관측이 09:03이라 앵커에서 제외.
- **extremes**: 정규장 구간 내 `individual`·`foreign`·`institution` 각각 `{max:{t,v}, min:{t,v}}`. 동률이면 먼저 나온 시각.
- **turns**: 누적값의 **부호 전환**(순매수↔순매도)이 처음 일어난 시각들. `[{t, from, to}]`, `from`/`to`는 `"순매수"|"순매도"`. 0은 전환으로 치지 않는다.
- **session_last**: 정규장 마지막 관측치 전체(세부 주체 포함).
- 메타: `first_t`, `last_t`, `obs_count`.

## 3. 산출 — `kr/data/kr_flows_intraday.json`

```json
{
  "unit": "억원",
  "basis": "장중 누적 순매수 스냅샷 — 확정 일별 수치와 다를 수 있음",
  "date": "2026-07-29",
  "KOSPI": {
    "points": [{"t":"09:30","individual":-7870,"foreign":1983,"institution":5605,
                "fin_invest":3378,"insurance":..., "trust":..., "bank":...,
                "other_fin":..., "pension":..., "other_corp":...}],
    "extremes": {"foreign":{"max":{"t":"10:11","v":2530},"min":{"t":"15:28","v":-12801}},
                 "institution":{...}, "individual":{...}},
    "turns": {"foreign":[{"t":"11:52","from":"순매수","to":"순매도"}],
              "institution":[], "individual":[]},
    "session_last": {"t":"15:30", "...": "..."},
    "first_t": "09:03", "last_t": "15:30", "obs_count": 150,
    "stale": false
  },
  "KOSDAQ": { "...": "동형" }
}
```

`stale`은 `kr_flows.json`의 신선도와 연동한다 — 일별 수급이 전 거래일 기준이면 장중 궤적도 `stale: true`로 표시하고 writer가 "전 거래일 기준" 라벨을 단다.

**비-코어**: `CORE_KEYS`에 넣지 않는다. 실패해도 `complete`를 막지 않고 `missing`에 `flows_intraday`만 기록한다(`econ`·`program`과 동일).

## 4. 차트 — `kr/data/kr_flows_intraday.png`

`scripts/kr/charts.py`에 `render_intraday_flow_chart(series, index_intraday)` 추가.

- 1×2 패널(왼쪽 코스피, 오른쪽 코스닥).
- 좌축: 누적 순매수(억원) 3선 — 외국인 `#0064FF`, 기관 `#00a763`, 개인 `#8B95A1`. 0선은 `#E5E8EB` 실선.
- 우축: 해당 지수 30분봉 궤적을 `#4E5968` 점선으로 오버레이. x축은 앵커 시각 라벨.
- 폰트·여백·스파인 처리는 `_draw_candles`와 동일한 Toss 톤을 따른다.
- 이를 위해 `kr_intraday.json`에 **KOSDAQ 궤적·OHLC를 추가**한다(`fetch_intraday("KOSDAQ")`, `fetch_index_ohlc("KOSDAQ")`). §3 지수&장중 서술도 코스닥 궤적을 쓸 수 있게 된다.

## 5. 리포트 — `.claude/agents/kr-report-writer.md` §5 개정

§5 수급 안에 `<h3>장중 수급 전개</h3>` 서브블록. 위치는 **일별 확정 표·해석 뒤, 프로그램 매매 서브블록 앞**.

- `kr_flows_intraday.png`를 base64 data URI로 `<img style="width:100%">` 임베드 + 캡션(누적 순매수, 억원, 정규장 09:00~15:30, 지수는 우축).
- 표 1개, `.tbl-scroll` 래퍼: `시각 | 코스피 개인·외국인·기관 | 코스닥 개인·외국인·기관` 7열. 값은 `points`에서 그대로.
- 해석 2~3문단:
  1. 외국인 누적선의 **방향 전환 시점**(`turns`)·**극값**(`extremes`)과 §3 지수 30분봉 궤적의 대응. 가격이 수급을 따라갔는지, 어긋났는지를 판정한다.
  2. 기관 궤적을 **금융투자**(프로그램·선물 연계 = 기계적)와 **연기금등**(정책성 장기)으로 갈라 매수 성격을 판정하고, 바로 아래 프로그램 매매 블록과 교차 검증한다.
  3. 정규장 마지막값(`session_last`)에서 확정치로 넘어가며 되돌림이 있었는지, 다음날 무엇을 확인할지.

**금지**:
- 장중 스냅샷을 확정치로 서술 금지. 2026-07-29 코스피 외국인은 15:30 시점 -12,445, 확정 -12,502로 다르다. 확정 수치는 `kr_flows.json`에서만 인용한다.
- 앵커 사이 값 보간·창작 금지. `points`·`extremes`·`turns`에 없는 시각을 언급하지 않는다.
- `stale: true`면 "전 거래일(YYYY-MM-DD) 기준"을 명시한다.
- 데이터가 없으면 서브블록 전체를 생략한다. [확인필요] 마커 금지.

## 6. 발행 게이트 추가

- 앵커 표의 모든 값이 `kr_flows_intraday.json`의 `points`와 1:1 일치.
- 서술에 등장하는 모든 시각이 `points`·`extremes`·`turns`에 실재.
- 장중값과 확정값이 섞이지 않았는지 — §5 일별 표는 `kr_flows.json`, 서브블록은 `kr_flows_intraday.json`.
- §2 전략 코멘트가 장중 전환 시점을 인용했다면 서브블록 값과 대조(선행 요약 대조 규칙의 연장).

## 7. 테스트 (TDD)

`scripts/kr/tests/fixtures/intraday_flows_kospi.html`(실제 페이지 1장) + `test_flows_intraday.py`:

1. 컬럼 매핑 — 기관계 == 세부 6주체 합.
2. 빈 HTML → `[]`.
3. `collect_pages` — 마지막 페이지 반복 시 중단, dedupe, 오름차순 정렬.
4. 앵커 스냅 — `t <= anchor`인 마지막값 채택, 관측 없는 앵커는 생략.
5. 정규장 컷 — 15:31 이후 행이 궤적·extremes에 안 들어감.
6. `turns` — 부호 전환 시각 정확, 0은 전환 아님.
7. `extremes` — max/min 값·시각.

## 8. 워크플로

`.github/workflows/collect-kr-data.yml`의 `git add`에 `kr/data/kr_flows_intraday.png` 추가.

요청 수는 시장당 최대 45페이지, 실측 37 → 총 ~74회 증가(약 15초). Actions 러너에서 문제 없음. 실패는 전부 비-코어로 흡수한다.

## 미결 항목

- 없음.
