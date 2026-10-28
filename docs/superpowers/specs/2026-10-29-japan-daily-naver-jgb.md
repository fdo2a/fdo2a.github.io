# 일본 일간 JGB 원천 → 네이버증권 (2026-10-29)

사용자: 「일본 일간 레포트의 채권파트는 네이버증권에서 가져오는걸로 하자」. 주간(`scripts/japan/core.py`)은 MOF 그대로.

## 지금
- `collect_japan_daily._rates` → `daily_rates.jgb_block(WS.fetch_jgb(), prev)` — MOF `jgbcme.csv` 는 다음 도쿄 영업일 게시라 저녁 발행의 JGB 가 **직전 세션** 값. 10/28 발행본은 10/27 값(10년 2.829%)을 실었고, 그날 실제 움직임(네이버 10/28 +3.7bp)은 빠졌다.
- 렌더 캡션 「JGB 는 재무성 커브(다음 영업일 게시) … 오늘 값이 아니다」, 게이트 `_TODAY_RATE` 가 「오늘 … JGB|국채|콜」 무조건 금지, 작성자 지시 「직전 세션 기준」.

## 실측 (2026-10-29 01시 KST, 로컬 — `WS.http_get`, UA 없음)
- `m.stock.naver.com/front-api/marketIndex/prices?category=bond&reutersCode=JP{2,5,10,30}YT%3DRR&page=1&pageSize=60` → `{result:[{localTradedAt, closePrice, fluctuations, ...}]}`. US 파이프라인이 Actions 에서 같은 엔드포인트를 쓴다(`collect_market_data.naver_spot_yields`).
- 4 만기 × 60 행(07-30~10-28): 날짜 집합 동일, 일본 휴일(09-21~23, 10-12) 행 없음. 스탬프 15:14~15:30 JST(15:25 104건, 15:29 65건) = 도쿄 세션 마감.
- MOF 대비 수준 차(네이버 − MOF, bp, 59일): 2Y 중앙 -0.4(-1.7~+0.8), 5Y -1.9(-3.1~-0.3), 10Y -0.4(-4.1~+1.1), 30Y +1.8(-7.5~+7.2). 일간 변화 차: 중앙 ≈0, 최대 |.| 2Y 2.1 · 5Y 2.7 · 10Y 1.2 · 30Y 8.0. 네이버는 지표물(벤치마크) 호가, MOF 는 상수만기 커브라 정의가 다르다.
- 같은 시각 실시간 bondList 는 10년 2.8310(23:44 JST, `marketStatus OPEN` — 런던·뉴욕 시간 호가)이고 `fluctuations` +0.0060 → 기준 2.8250 = `/prices` 의 10/28 15:25 행. 즉 `/prices` 일별 행은 도쿄 마감에서 고정되고 해외 시간 호가는 다음 날 행이 아니라 실시간 값에만 붙는다. `/prices` 사슬(종가 − 등락 = 전 행 종가)은 10/22→10/28 일치.
- 품질 메모: 10/23·10/26 행의 시가·고가·저가가 동일(10Y 2.815/2.823/2.757) — O/H/L 은 믿지 않는다. 종가만 쓴다.

## 설계
1. **원천**: `daily_rates.jgb_naver(series, session)` — `us.naver_yields.parse_prices`/`shared_dates`/`build_curve(expected_date=session)` 재사용(전 만기 한 날짜, 날짜 불일치면 None, 비교일 사이 공백이면 bp None). 어댑터가 `{level,date,bp}` → 기존 계약 `{value, period, prev_period, chg_bp, unit:'%', source:'naver'}` (value 3자리, chg_bp 1자리). `prev_period` 는 `shared_dates` 에서 base 바로 앞(공백이면 None — bp 와 같이).
2. **세션 마감 확인**: base 행의 스탬프 시각이 15:00 JST 이상이어야 한다(장중 행이 마감 전에 잡히는 경우 차단). `parse_prices` 가 시각을 버리므로 어댑터가 원 응답에서 base 날짜 스탬프를 따로 본다.
3. **우선순위·폴백**: 네이버(당일 세션) 전부-아니면-전무 → 실패·세션 행 없음·bp 없음이면 기존 MOF `jgb_block(mof, prev)`(직전 세션, `source:'mof'`). **출처를 섞지 않는다** — 만기 일부만 네이버로 채우지 않고, 네이버 수준과 MOF 수준 사이의 bp 를 절대 만들지 않는다(수준 차가 최대 7.5bp 라 가짜 움직임이 된다).
4. **정합성 점검**: MOF 의 `prev` 행과 네이버의 `prev` 행을 만기별로 비교, 하나라도 |차| > 15bp 면 네이버를 의심(코드 매핑 오류)하고 폴백. MOF 를 못 받으면 점검을 건너뛰고 네이버를 쓴다(상태에 기록).
5. **상태**: `fetch_status.jgb` = 실제로 실린 블록 기준 ok/사유, `fetch_status.jgb_naver` = 'ok' 또는 폴백 사유(빌드 경고에 뜬다).
6. **렌더**: `_t_jgb` 캡션을 `source` 로 가른다. `source` 없거나 'mof' → 지금 문구 그대로(옛 스냅샷 재렌더가 바이트 동일). 'naver' → 「JGB 는 네이버증권(지표물 도쿄 마감 호가), 콜은 일본은행 시계열(최신 관측일). 재무성 커브와는 정의가 달라 수 bp 다를 수 있다. 금리 상승은 빨강.」 꼬리말 출처에 네이버증권 추가(네이버일 때만).
7. **게이트**: `_TODAY_RATE` 를 둘로 — 콜은 계속 금지, JGB·국채는 `jgb.*.period != session` 일 때만 금지. 기준일 날짜 의무(`_period_of`)는 그대로 — 네이버면 period == session 이라 날짜 불필요, 폴백이면 지금처럼 필수.
8. **작성자·문서**: `japan-daily-writer.md` 의 「MOF, 직전 세션 값」 → 「`source` 가 naver 면 당일 도쿄 마감, mof 면 직전 세션 — `period` 가 기준일」. collector docstring, `scripts/japan/CLAUDE.md` 49행, spec `2026-10-27-japan-daily-design.md` 표·§13 에 한 줄.
9. **범위 밖**: 주간 보고서(MOF 유지), 20Y/40Y, 콜금리. 일간 이력 `jp_daily.jsonl` 에는 JGB 가 없어 영향 없음.

## codex 설계 검토 반영 (중대 8·경미 1) — 위와 충돌하면 이 절이 우선

| # | 지적 | 처리 |
|---|---|---|
| 1 | 네 만기에서 같은 날이 통째로 빠지면 `build_curve` 공백 검사가 못 보고 2세션 변화를 「전일」로 찍는다 | 만기마다 세션·직전 세션 행이 **정확히 하나의 유한값**이고 직전 공통일 == 달력의 `prev_session` 이어야 채택 |
| 2 | 스탬프 ≥15:00 만으로는 마감 확정이 아니다 — 2시간 지연이라 16:30 예약 실행은 장중 행을 받는다 | `NAVER_READY = 17:45 JST` 전 수집은 채택하지 않음(세션 다음 날 수집은 통과) |
| 3 | 이른 폴백 후보(complete)를 루틴이 그대로 써서 18:20 에 다시 수집하지 않는다 | 스냅샷 `jgb_recollect: true` → 오케스트레이터 STEP 1-1 이 다시 dispatch |
| 4 | MOF 폴백도 한 날이 빠지면 2세션 bp, 결측 만기가 있어도 `ok` | `jgb_block(holidays=…)` 는 비교 행이 정확히 앞 영업일일 때만 bp. 상태는 완전한 블록만 `ok`, 아니면 `결측 …` |
| 5 | `closePrice="nan"`·같은 날 중복 행 통과 | 위 #1 의 유일·유한 검사, 수준·bp 는 검사한 그 행으로 |
| 6 | MOF 대조 생략 사유 불명 | `fetch_status.jgb_mof_check` = ok / mismatch / skip: 사유. 만기↔코드 고정 매핑 테스트 |
| 7 | 「JGB 금리는 오늘 …」 역순 통과, 만기 일부만 당일인 스냅샷 | 어순 둘 다 검사. 「오늘 콜」 은 항상 금지, 「오늘 JGB」 는 실린 **모든** 행이 period == session 일 때만 허용 |
| 8 | 행별 `source` 와 블록 캡션 충돌, 꼬리말에 재무성이 남는다 | 실린 행이 전부 naver 일 때만 naver 캡션·꼬리말(교체), 아니면 기존 MOF 문구 그대로(옛 스냅샷 바이트 동일) |
| 9 | 옛 발행본 재검토·작성 지시·오케스트레이터 | 10/27·10/28 발행본을 새 게이트로 재검사해 통과. 작성자 지시·오케스트레이터 문구 갱신 |

실측(10/29 02시 KST 로컬, 실제 네이버·MOF): 10/28 세션 2Y 1.898(+1.8bp) · 5Y 2.269(+3.3) · 10Y 2.825(+3.7) · 30Y 3.879(+5.9), MOF 대조 ok. 같은 날 발행본은 MOF 10/27 값(10Y 2.829)을 실었다.

남은 검증 빚: Actions IP 에서 일본 코드 첫 수집(미 국채 코드는 같은 엔드포인트로 Actions 에서 돈다), `/prices` 일별 행이 해외 시간 뒤에도 고정되는지(하루 관측뿐).
