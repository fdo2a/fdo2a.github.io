# research_notes — US 2026-11-09 (월)

- **연구 회차 CYCLE ID: `us-2026-11-09-daily-cycle`** (research/us, validate: valid, 150 records)
- **열린 가설 ID (4건)**
  - `us-2026-11-04-datacenter-politics-power-overreaction` — 판정 11/10 16:00 ET 종가 (unresolved, 중간 관측)
  - `us-2026-11-05-ai-chip-crash-degross-vs-rerating` — 판정 11/12 16:00 ET 종가 (unresolved, 중간 관측)
  - `us-2026-11-06-payrolls-front-end-flattening-vs-riskoff` — 판정 11/13 17:05 ET 네이버 종가 (unresolved, 중간 관측)
  - `us-2026-11-09-nvidia-governance-discount-persist` — **오늘 신규**, 시험 11/10 09:30 ET ~ 11/16 16:00 ET (prospective: true)
- 오늘 review 레코드 없음(`reviewed_ids: []`) — 세 열린 가설 모두 판정 구간 안이라 `unresolved` 사유로 처리.
- 원장 변경은 working tree 에만 있음(커밋 안 함): `research/us/ledger.jsonl` + `research/us/evidence/` 신규 스냅샷. 초안 입력: `.research-drafts/us/2026-11-09/{hyp_nvda.json,cycle.json,web_session.md,...}`.

**데이터 기준**: 주식·섹터·종목 종가 2026-11-09 (Yahoo, `market_data.json` generated 2026-11-10 08:17 KST, complete=true, missing=[]). FX·원자재 16:00 ET 30분봉 컷(`basis: close_1600_et`). 금리 = 네이버 국채 종가(17:05 ET) **전 만기 2026-11-09 동일 기준일**(`spread_2s10s_aligned: true`). FRED 대조값(`yields_fred`)은 2026-11-06. `yield_curve.png` 는 Actions 가 이미 생성(워크스페이스에 있음, 재생성 안 함).

**웹 접근 한계**: WebFetch 는 DNS 차단(sooleader.com, virginiabusiness.com ENOTFOUND)으로 불가. 아래 뉴스·해석은 전부 **WebSearch 결과 요약**에 기반하며 기사 원문을 읽은 것이 아니다. 요약 간 수치가 다른 경우(장중 스냅샷 시각 차이) 정본 파일 값을 우선한다.

---

## ① 시황 동인 (장중 스윙 포함)

**결론**: 선거 뒤 2주간 AI 급락 이후 첫 광범위 반등. S&P 500 +2.346%(7,549.94), 나스닥 +2.741%, 다우 +2.153%, 러셀 2000 +3.148%. S&P 500 기준 4월 이후 최대 상승일로 보도된다(AP). 11개 섹터 ETF 전부 상승(산업재 +3.824%, 기술 +3.727% 선두; 에너지 +0.519%, 필수소비재 +0.899% 후미). 성장(IVW +2.654%) > 가치(IVE +2.034%). `price_context.moves`: S&P 500·러셀 2000 `매우 큼`, 나스닥·VIX·DXY `큼`, USD/KRW `매우 큼`. VIX -5.72pt → 19.92.

**보도된 동인** (출처 요약):
1. **유가 급락 → 인플레 우려 완화**: 트럼프 대통령이 일요일(11/8) CNN 인터뷰에서 협상이 진행되는 한 이란 추가 공습 가능성은 매우 낮다고 말한 뒤 브렌트가 약 5% 하락, 9월 초 이후 최저(Business Standard, LBC/Reuters, Jalopnik). Reuters 계열은 "oil slide eases inflation worries"로 랠리를 설명(MarketScreener/Kitco 헤드라인).
2. **반도체·AI 반등(엔비디아 제외)**: 반도체 지수(SOX) +6% 이상(Reuters), SOXX +7.2%로 7/30 이후 최고의 날(Benzinga). 브로드컴·AMD가 최대 기여(Reuters). 분석가들은 과매도, 유가 하락, 반도체로의 회전을 원인으로 들었다(Yahoo Finance live). 일부 분석가는 지난주 매도를 과잉 반응으로 평가(Reuters via Free Malaysia Today).
3. **엔비디아 단독 약세**: 이사회가 젠슨 황 CEO와 중국 정보기관 연루 의혹 여성과의 관계를 독립이사·외부 법률 자문으로 조사한다고 발표(CNBC, `news/2026-11-09.json`). 엔비디아 -4.270%(178.67), 장중 최대 -8%(Yahoo), S&P 500 대비 2025-01-27 딥시크 이후 최악의 상대 성과(Benzinga), 4/7 이후 최저 종가(Yahoo). Yahoo live 는 "투자자가 엔비디아 지분을 더 넓은 AI 거래로 옮겼다"고 서술.
   - 주의: Reuters 요약 중 "엔비디아가 S&P 500 유일 하락 종목"이라는 문장은 정본 `movers.json`(엑손모빌 -0.69%)과 맞지 않아 사용하지 않는다. 의혹 여성 신원 서술도 매체마다 다르다(CNBC/NYT: 중국 시민·국가안전부 요원 의혹, Benzinga: 싱가포르 데이터센터 임원).
4. 알파벳이 새 TPU 2종 발표로 약 3% 상승했다는 서술은 Yahoo live 요약 1건뿐이고, 별도 검색은 2026년 4월 TPU 8t/8i 발표만 반환 → **미확인, 본문 사용 보류 권고**.

**장중 궤적** (`intraday.json`, 30분봉, ET):
- 선물 갭: S&P +0.62%, 나스닥 +0.83%, 러셀 +1.23% `상승 출발` (`session.futures`).
- S&P 500: 시가 7,422.24 → **11:00 봉 저가 7,376.86(시가 대비 -0.61%)** → 15:00 봉 고가 7,577.39(+2.09%) → 종가 7,549.01. 오전 한 차례 밀린 뒤 오후 내내 오른 형태. 종가 위치 86(`고점권 마감`).
- 나스닥: 저가 09:30 봉(-0.06%), 고가 15:00 봉(+2.30%), 종가 위치 82(`중단 마감`). 러셀 종가 위치 83.
- 엔비디아: 시가 173.04, 저가 09:30 봉 170.24(-1.62%), 고가 10:30 봉 179.92, 종가 178.60 — 갭 하락으로 출발한 뒤 장 초반에 이미 회복, 오후는 횡보.
- WTI: 시가 91.31 → 저가 14:30 봉 85.02(-6.89%) → 16:00 컷 87.06. 하락이 장중 내내 이어진 뒤 마감 전 일부 되돌림.
- 금: 저가 09:00 봉 4,074.9 → 고가 15:00 봉 4,157.7, 16:00 컷 4,151.0(+1.870%).
- S&P 11:00 저점의 촉매를 특정한 보도는 찾지 못함(미확인). 13:00 ET 3년물 입찰 결과(약한 수요) 시점과 오후 상승 사이 인과를 주장한 글(TradingView 아이디어 "Today's 3-Year Notes Auction Is Why The Stock Market Rebounded")은 개인 차트 게시물이라 근거로 쓰지 않는다.
- 참여도: `session.participation` gap_pp -0.1(중립) — 동일가중·시총가중 차이 미미, 광범위 상승과 일치.

**해외 종가** (`session.global_close`): 닛케이 -5.96%·항셍 -1.27%·상해 -1.10%·DAX -1.92%·유로스톡스50 -0.98%는 **기준일 2026-11-06** 행(11/9 값 아님, 이전 세션). FTSE100 +1.02%만 11/9. → 본문에서 11/9 아시아·유럽 반응으로 쓰지 말 것.

**FX·원자재** (16:00 ET 컷): DXY 101.675(-0.592%), EUR/USD 1.1226(+0.718%), USD/JPY 157.889(-0.374%), USD/KRW 1,340.35(-1.686%, 2년 중 이보다 낮았던 날 19일뿐). WTI 87.06(-3.897%), 브렌트 92.82(-5.266%), 천연가스 3.207(+8.016%), 금 4,151.0(+1.870%). FXStreet 헤드라인은 "유가 급락이 달러를 끌어내렸다"고 정리. 천연가스 +8%·원화 -1.7% 고유 원인은 검색 1회로 찾지 못함(미확인).

## ② 채권·금리 맥락

- **네이버 종가 (11/9, 전 만기 동일자)**: 2Y 4.547%(+2.5bp), 5Y 4.659%(+1.1bp), 10Y 4.862%(+0.3bp), 30Y 5.256%(-0.4bp). 2s10s 31.5bp(11/6 33.7bp), 5s30s 59.7bp. 1주 전(11/2) 대비 2Y -3.6bp, 10Y -3.2bp (week_ago 4.583/4.894). → 유가 -5%·주식 급반등 날에 **앞단만 오르고 장기물은 보합 — 베어 플래트닝**.
- FRED 대조(`yields_fred`, 11/6): 2Y 4.51, 10Y 4.86, 2s10s 35bp — 기준일·원천 다름, 본문 비교에 섞지 말 것. `yield_drivers` 실질금리·기대인플레는 11/6 값이라 오늘 충격 설명에 쓰지 않는다.
- **보도**: 10월 CPI(11/10) 앞두고 수익률 소폭 상승(Reuters "TREASURIES-Yields edge up before Tuesday's CPI release", MarketScreener/rallies.ai). 한 보도의 장중 스냅샷 2Y +3.95bp 4.562%, 10Y +1.48bp 4.874% — 정본 아님.
- **12월 FOMC(12/9) 25bp 인상 확률(CME FedWatch, 보도치)**: 85%(금요일 77%에서), 다른 보도 84%(76%에서), Reuters 계열 약 82%. 출처·시각이 서로 달라 같은 상품 동시점 변화로 계산하지 말 것. 11/6 보도치 76.8%(CNBC), 77%(24/7 Wall St.). OIS 경로 미확보.
- 연준 기준금리 3.75~4.00%, 지난달(10/28) 10-2 동결, 두 명 인상 소수의견(보도 요약; 원문 `data/fed/fomc-statement-20261028.txt` 로 확인 가능).
- **3년물 입찰** (`auctions.json`, 13:00 ET): 580억 달러, 낙찰 4.627%, 응찰률 2.53배(최근 6회 평균 2.64, -0.11), 간접 55.5%(평균 63.0, -7.5%p), 직접 35.0%(평균 24.8), 딜러 9.5%(평균 12.2, -2.7%p), `demand_ko: 엇갈림`, 테일은 WI 원천 없어 미산출(`tail_status: no_wi_source`). Investing.com·RTTNews는 "약한/평균 이하 수요"로 보도. "응찰률 2025년 8월 이후 최저·직접 비중 사상 최대"는 검색 요약 서술로, 이력으로 검증하지 않음(본문 사용 시 출처 명기 필요).
- 다음 입찰: 11/10 10년물 420억 달러, 11/12 30년물 250억 달러(각 13:00 ET). 11/11 채권시장 휴장(재향군인의 날, 주식시장은 개장).
- 유동성: `liquidity/` today:false (신규 이벤트 없음).

## ③ 메모리/DRAM 뉴스 (뉴스·산업 브리프 재료)

- 정본: 마이크론 733.15(+6.254%), 웨스턴디지털 289.78(+9.857%), 시게이트 506.14(+9.794%), 샌디스크 +6.16%(movers), 삼성전자 189,900(+0.636%)·SK하이닉스 1,136,000(+0.353%)은 11/9 한국 세션(미국 장 전).
- Reuters: 마이크론 +7% 이상(장중 요약) — 반도체 전반 반등의 일부로 서술. **11/9 메모리 고유 뉴스(가격·공급·실적)는 검색 1회로 찾지 못함.** 11/3 애플 메모리 원가 경고 관련 Benzinga 기사는 11/3 무렵 기사(이전 회차 재료).
- 일본 칼럼(머니포스트, `news` 수집): 메모리는 수급이 빠듯하고 거래처가 넓어 성장 여지가 크다는 견해 — 의견 기사, 참고용.
- MLCC(`mlcc`): 야게오 +9.89%, 월신 +9.86%, 삼성전기 -3.10%, 무라타 +1.04% (각 현지 11/9 세션).

## ④ AI 인프라 뉴스 (뉴스·산업 브리프 재료)

- 정본: 마벨 154.60(+9.490%), 코히런트 225.19(+16.794%), 루멘텀 596.16(+10.689%), GE 버노바 829.34(+7.135%), 버티브 200.47(+9.630%).
- **광학**: 코히런트·루멘텀이 "AI 광학 반등 연장" 속 급등(TIKR/Benzinga: 코히런트 +18%, 루멘텀 +12% 장중; 24/7 Wall St. 장 초반 +13%·+11%). 루멘텀 움직임은 마벨의 전액 주식 인수(11/2 발표: 루멘텀 1주당 마벨 4.5주, 암묵 기업가치 1,150억 달러, 2028년 상반기 종결 예상 — Marvell IR, Investing.com)와 연동된다는 서술. 정본상 루멘텀 +10.689% vs 마벨 +9.490%로 비슷하게 움직임(교환비율 연동과 일치, 인과 단정은 안 함).
- **전력**: 컨스텔레이션 에너지가 11/9 3분기 실적(GAAP EPS 5.19달러, 조정 영업 EPS 5.06달러)과 연간 조정 영업 EPS 가이던스 12.50~12.80달러(이전 11.50~12.50, Earnings Whispers 프리뷰 기준)를 발표, 20년 270MW 계약·구글 원전 협력·DOE 최대 50억 달러 조건부 대출 약정 포함(SEC 8-K, 2026-11-09). TIKR는 GE 버노바 +7%를 "컨스텔레이션 가이던스 상향이 데이터센터 모라토리엄 우려를 덜었다"로 설명(기사 날짜 요약상 미표기, 수치는 정본과 일치). CEG는 선거 뒤 2세션 -9%였다(TIKR 프리뷰). 8-K 가이던스 슬라이드에 "DRAFT" 표기가 있다는 요약 → 수치 인용 시 주의.
- 버티브: 11/9 고유 발표 없음(검색). 인피니언 3년 공급 계약은 11/4 발표.
- GE 버노바: 11/9 고유 발표 검색 결과 없음.
- 정치: 워런 의원이 1월 상원 은행위원장으로 대중국 첨단 AI 칩 수출 통제 강화를 우선 과제로 제시(CNBC). 바클레이즈는 선거 결과가 재생에너지 보조금 정치 간섭 위험을 줄인다고 분석(CNBC 11/7). 굴스비 총재는 AI 데이터센터 투자가 건설 인력·전력·설비 수요를 키워 수요 인플레를 부추긴다고 지적(CNBC CPI 예고 기사).

## 움직인 종목의 이유 (`movers.json` groups)

| id | 묶음 | 원인 한 줄 | 출처 |
|---|---|---|---|
| g1 | 반도체 하락 — 엔비디아 -4.27% | 이사회가 젠슨 황 CEO와 중국 정보기관 연루 의혹 여성 관계에 대한 독립 조사 착수, 장중 최대 -8% | CNBC(news 수집), Yahoo Finance, Benzinga |
| g2 | 반도체 상승 — AMD +13.26%, 브로드컴 +8.78%, 마이크론 +6.25%, 인텔 +5.49%, 마벨 +9.49%, TI +6.62%, ADI +8.55%, 모놀리식 파워 +16.6% | 지난주 SOX -12% 급락 뒤 과매도 반등·유가 하락·엔비디아에서 다른 AI 반도체로의 회전으로 보도. AMD는 오펜하이머 상향(Reuters 계열 요약; 원 노트 미확인). 모놀리식 파워 고유 재료는 확인된 재료 없음 | Reuters(MarketScreener/Kitco/FMT), Yahoo live, Benzinga |
| g3 | 하드웨어·저장장치 상승 — 애플 +2.43%, 샌디스크 +6.16%, 시게이트 +9.79%, 웨스턴디지털 +9.86%, 델 +5.41% | 반도체·AI 하드웨어 전반 반등의 일부로만 보도. 종목 고유 재료는 확인된 재료 없음 | Reuters, Yahoo live |
| g4 | 통합 석유 하락 — 엑손모빌 -0.69% | 트럼프의 이란 추가 공습 가능성 낮음 발언 뒤 브렌트 약 -5%(정본 -5.266%) | Business Standard, LBC/Reuters |
| g5 | 자동차 상승 — 테슬라 +5.54% | 확인된 재료 없음 (검색 2회) | — |

## ⑤ 경제지표 4축 표

Actual/Previous 는 `econ_indicators.json`(FRED), 출처 'FRED'. Forecast·발표일은 최근 발표분만 기재. 오늘(11/9) 새로 나온 FRED 지표 없음(`macro_metrics.headline_releases` 빈 목록).

| 축 | 지표 | Actual | Forecast | Previous | 기준월 / 발표일 |
|---|---|---|---|---|---|
| 고용 | 비농업 고용 (천명) | 165 | 59 (다우존스, 11/6 노트·CNBC) | 60 | 2026-10 / 11/6 |
| 고용 | 실업률 (%) | 4.1 | — | 4.2 | 2026-10 / 11/6 |
| 고용 | 시간당 임금 MoM (%) | 0.37 | — | 0.26 | 2026-10 / 11/6 |
| 고용 | 신규 실업수당 청구 | 189,000 | — | 195,000 | 10/31 주 / 11/5 |
| 고용 | 신규 청구 4주 평균 | 194,750 | — | 197,000 | 10/31 주 |
| 고용 | 계속 청구 | 1,718,000 | — | 1,695,000 | 10/24 주 |
| 고용 | JOLTS 구인 (천건) | 7,523 | — | 7,190 | 2026-09 |
| 활동 | 산업생산 MoM (%) | 0.66 | — | 0.06 | 2026-09 |
| 활동 | 내구재 주문 MoM (%) | 1.91 | — | 0.14 | 2026-09 |
| 활동 | 공장 주문 MoM (%) | 1.84 | — | 0.33 | 2026-09 |
| 활동 | 건설 지출 MoM (%) | -1.85 | — | 1.98 | 2026-09 |
| 활동 | 주택 착공 (천호) | 1,221 | — | 1,288 | 2026-09 |
| 활동 | 신규주택 판매 (천호) | 676 | — | 680 | 2026-09 |
| 활동 | 기존주택 판매 | 3,990,000 | — | 3,930,000 | 2026-09 |
| 활동 | 무역수지 (십억달러) | -105.05 | — | -105.74 | 2026-09 |
| 활동 | 실질 GDP QoQ 연율 (%) | 3.4 | — | 2.2 | 2026 Q3 |
| 활동 | 필라 연은 제조업 | 20.9 | — | 37.8 | 2026-10 (해부만, 점수 밖) |
| 소비 | 소매판매 MoM (%) | 0.77 | — | 1.29 | 2026-09 |
| 소비 | 미시간 소비자심리 | 48.1 | — | 51.7 | 2026-09 |
| 물가 | CPI YoY (%) | 3.72 | — | 3.35 | 2026-09 |
| 물가 | CPI MoM (%) | 0.65 | — | 0.40 | 2026-09 |
| 물가 | Core CPI YoY (%) | 2.57 | — | 2.45 | 2026-09 |
| 물가 | Core CPI MoM (%) | 0.33 | — | 0.29 | 2026-09 |
| 물가 | PPI 최종수요 MoM (%) | 1.34 | — | 0.47 | 2026-09 |
| 물가 | PCE YoY (%) | 3.65 | — | 3.44 | 2026-09 |
| 물가 | Core PCE YoY (%) | 3.12 | — | 3.03 | 2026-09 |
| 물가 | 미시간 1년 기대인플레 (%) | 4.6 | — | 4.0 | 2026-09 |

**다음 발표 — 10월 CPI, 11/10(화) 08:30 ET (BLS)**: 컨센서스 전체 MoM 0.3%, 근원 MoM 0.2%(CNBC 예고 기사, `news` 수집 — 9월 0.6%·0.3%에서 둔화 예상). 10월 전년 대비는 작년 셧다운으로 2025년 10월 가격이 수집되지 않아 BLS가 대부분 지수의 12개월 변화를 발표하지 않는다(CNBC·mlq.ai). 뱅크오브아메리카 추정 전체 3.8%·근원 2.7%(CNBC), 다른 프리뷰 3.9%·2.8%(mlq.ai) — 추정치이지 공식 컨센서스 아님. ING는 전체 MoM 0.3% 예상. EIA 기준 10월 휘발유 가격 4% 넘게 하락(CNBC).

비FRED 지표(ISM·S&P Global·ADP·CB·NY Fed): 이번 회차 검색하지 않음 — 11/9 신규 발표 없음, 최근 7일 내 발표분(ISM 제조업·서비스업 11월 초)은 11/6 회차 리서치에서 다룸. 필요 시 작성 담당이 이전 노트 참조.

## ⑥ 시장 해석·FedWatch

- 12월 인상 확률(보도 FedWatch) 82~85%로 11/6 보도치 76~77%보다 높다(출처·시각 상이). 유가 급락이 인플레 우려를 덜었다는 주식 쪽 서술과 달리, 앞단 금리는 인상 기대 쪽으로 움직였다.
- ING(11/9): 달러 강세는 위험회피가 이어져야 지속, 아니면 조정 위험. 10월 CPI MoM 0.3%가 12월 인상 기대를 뒷받침할 것. 단기 금리차는 오히려 좁혀지고 있다. 실제로 이날 DXY -0.592%(위험선호 회복 + 유가 급락).
- Investing.com 칼럼(11/9 오전): 12월 인상 약 20bp 반영, 근원 0.2%면 달러 상승 여지 제한. (칼럼의 비농업 15.9만 명 수치는 BLS 원문 16.5만 명과 다름 — 사용 금지.)
- CNBC(11/9): 10월 고용 강세의 세 요인 — 경영·과학기술 컨설팅 +17,300명, 임시직 +18,600명 등. 무디스: AI가 챗GPT 이후 순고용 78.6만 명 창출 평가.
- 노동부(11/9) 실업보험 구직활동 요건 강화(주 5건) 규칙안 — 향후 청구 건수 해석에 영향 가능(CNBC). 시장 반응 보도 없음.

## ⑦ 미확정 항목

1. 알파벳 11/9 신규 TPU 발표 — Yahoo live 요약 1건, 교차 확인 실패 → 본문 사용 보류.
2. AMD 오펜하이머 상향 — Reuters 계열 요약에만 있음, 등급 명칭("Buy") 원 노트 미확인 → "상향 보도" 수준으로만.
3. 테슬라 +5.54%, 모놀리식 파워 +16.6%, 메모리 3사, 애플·델 고유 원인 — 확인된 재료 없음.
4. 천연가스 +8.0%, USD/KRW -1.7% 고유 원인 — 미확인.
5. S&P 500 11:00 봉 저점의 촉매 — 미확인.
6. FedWatch 정확한 동시점 수치 — 보도치 82/84/85% 혼재, CME 원 페이지 미접근.
7. 3년물 입찰 "응찰률 2025년 8월 이후 최저·직접 비중 사상 최대" — 검색 요약 서술, 이력 미검증.
8. 비FRED 지표 최근값 — 이번 회차 미검색.
9. 컨스텔레이션 가이던스 이전 범위(11.50~12.50)는 Earnings Whispers 프리뷰 요약, 8-K 슬라이드 "DRAFT" 표기.
10. 젠슨 황 관련 의혹 여성 신원 — 매체별 서술 상이(CNBC/NYT vs Benzinga).

## ⑧ 신규 발표 해부

`macro_metrics.json` 의 `headline_releases` 가 비어 있어 해당 없음(0건). `releases/index.json` 신규 원문 없음.

## ⑨ 연준 이벤트 반응

`fed/events.json` events 빈 목록 — fresh tier-1 이벤트 없음, 해당 없음.

---

## 운용 판단 브리핑

**오늘의 범위와 자료 공백**: 광범위 반등(11개 섹터 전부 상승), 엔비디아 단독 하락, 유가 -4~5%, 달러 약세·원화 급강세, 앞단 금리 상승·평탄화, 3년물 입찰 약한 수요, CPI 전날. 공백: 기사 원문 미독(WebFetch 차단), 옵션·포지셔닝·펀드 흐름·OIS 없음, 여러 종목 고유 원인 미확인(⑦).

### 질문 1 — 반등은 선거 뒤 AI 급락을 과잉 하락으로 확인하는가, 엔비디아 하락은 고유 위험의 가격인가

- **관측**: S&P 500 +2.346%, XLK +3.727%, 버티브 +9.630%, GE 버노바 +7.135%, 코히런트 +16.794%, AMD +13.26%; 엔비디아 -4.270%(S&P 대비 -6.617%p). 11/5 종가 대비 XLK−S&P +2.566%p(H2 지지 기준 +3.38%p까지 0.81%p). 11/4 종가 대비 버티브·GE 버노바 단순평균−S&P +0.358%p(H1, 11/6 -4.990%p에서 개선; 지지에는 11/10 하루 +6.1%p 추가 필요).
- **기대 근거(날짜 있음)**: 보도 서사만 있다 — 11/9 Reuters·Yahoo: 과매도·유가 하락·반도체 회전, 일부 분석가 "지난주는 과잉 반응". 가격 기반 기대(옵션·포지셔닝) **unknown**.
- **해석**: 새 규제 일정이나 하이퍼스케일러의 설비 투자 축소 발언 없이 반등이 나왔다는 점은 H2 기제(포지션 축소 → 후속 재료 부재 시 회복)와 맞는다. 전력 쪽은 컨스텔레이션 가이던스 상향이라는 **고객 측 실적 재료**가 같은 날 있어, 버티브·GE 버노바 반등을 '불확실성 할인 해소'만으로 돌릴 수 없다(전달 경로로는 공존 가능).
- **대안**: 하루 반등은 숏커버링·유가 연동 위험선호일 뿐이고, AI 설비 투자 재평가(규제·자금 조달 부담)는 진행 중 — 11/10 CPI가 뜨거우면 다시 뒤집힐 수 있다. 엔비디아 하락이 "AI 노출은 유지하되 한 종목 위험만 줄이는" 회전이라는 해석과, 대형주 리더십 약화의 시작이라는 해석은 하루 데이터로 구분되지 않는다.
- **촉매/시점**: 11/10 08:30 ET CPI, 11/10 종가(H1 판정), 11/12 종가(H2 판정), 11/16 종가(신규 H4), 11/17 장 마감 뒤 엔비디아 실적.
- **반증**: H1 11/10 차이 ≤ -6.45%p, H2 11/12 차이 ≤ -3.38%p, H4 11/16 엔비디아−S&P ≥ +3.89%p.
- **조건부 활용(테마 관점, 매매 권고 아님)**: 반도체·전력망 테마의 가격 근거는 하루 회복으로 **강화되었으나 판정 전**. 반도체 테마 안에서 엔비디아와 나머지(AMD·브로드컴·메모리)의 분리는 바스켓 구성 시 단일 종목 지배구조 위험을 따로 봐야 한다는 관측으로만 전달. 표현 수단 비교(예: 반도체 ETF 대 엔비디아 상대)는 옵션·차입 비용·유동성 자료가 없어 비용을 평가할 수 없다 — 0이 아니라 **미지**. 독자의 보유·한도 정보 없음.
- 원장: H1 `us-2026-11-04-datacenter-politics-power-overreaction`, H2 `us-2026-11-05-ai-chip-crash-degross-vs-rerating`, H4(신규) `us-2026-11-09-nvidia-governance-discount-persist`.

### 질문 2 — 유가 급락에도 앞단이 오른 것은 CPI 전 인상 기대가 지배한다는 뜻인가

- **관측**: 브렌트 -5.266%, WTI -3.897%인 날 네이버 2Y +2.5bp(4.547%), 10Y +0.3bp, 2s10s 31.5bp(11/6 33.7bp → -2.2bp, H3 판정 구간 ±5.82bp 안). 3년물 응찰률 2.53배(평균 2.64), 간접 55.5%(평균 63.0). DXY -0.592%.
- **기대 근거**: FedWatch 12월 인상 확률 보도치 82~85%(11/9), 76~77%(11/6) — 시각·출처 상이로 변화폭 확정 불가. CPI 컨센서스 MoM 전체 0.3%·근원 0.2%(CNBC 예고).
- **해석**: 유가 하락이 헤드라인 물가 기대를 낮추더라도 연준 인사들이 근원·서비스로의 전이를 우려한다는 보도(CNBC) 속에서, 앞단은 12월 인상 경로를 유지했다. 약한 3년물 입찰도 앞단 상승과 같은 방향이다(원인 단정은 아님: 입찰 수요 약화가 금리 상승의 결과인지 원인인지 일간 종가로는 구분 불가).
- **대안**: 2Y 상승은 11/5 안전자산 매수(-10.4bp)의 되돌림 연장(누적 +7.0bp)일 뿐이고, 주식 급반등 날 안전자산 수요 감소가 앞단을 올렸다. 장기물 보합은 유가 하락(인플레 보상↓)과 위험선호(기간프리미엄↑)가 상쇄된 결과일 수 있다 — 실질·BEI 동일자 자료(11/9) 없음.
- **촉매/시점**: 11/10 CPI·10년물 입찰, 11/12 30년물 입찰, 11/13 네이버 종가(H3 판정).
- **반증**: H3 11/13 2s10s 변화 ≥ +5.82bp.
- **조건부 활용**: 원화 현금·단기채 슬리브 관점에서 USD/KRW 1,340.35(2년 하위 4% 수준)는 기록할 관측이지만 원인 미확인. 금리 판단은 CPI 전까지 **증거 대기**가 기본.
- 원장: H3 `us-2026-11-06-payrolls-front-end-flattening-vs-riskoff`.

### 사전 판단 변화
- H1: 11/6 -4.990%p → 11/9 +0.358%p, 약화 기준에서 크게 멀어졌으나 지지 기준까지 멀다. 판정 11/10.
- H2: 11/6 +1.139%p → 11/9 +2.566%p, 지지 쪽으로 이동, 판정 11/12.
- H3: 첫 관측 -2.2bp, 지지 방향이나 판정 구간 안.
- 신규 H4 등록(엔비디아 지배구조 할인 지속).

---

## 학습·복기

**1. 이전 질문** — `posts/2026-11-06.html` (report_date 2026-11-06), learning block `data-research-cycle="us-2026-11-06-daily-cycle"`.
- 질문: 고용 서프라이즈 뒤 2년물 주도 평탄화는 12월 인상 경로가 굳는 신호인가, 11/5 주식 급락 뒤 안전자산 수요의 되돌림인가.
- 조건: 11/6 2s10s 33.7bp 대비 11/13 2s10s 변화 ≤ -5.82bp 지지, ≥ +5.82bp 약화, 사이 판정 불가; CPI가 11/10에서 밀리거나 네이버 종가 결측 시 판정 불가.
- 기한: 11/13 네이버 종가(17:05 ET). 같은 블록의 다른 열린 판단: 반도체 급락(11/12 종가), 전력설비(11/10 종가). 11/6 블록에서 닫힌 것: 애플 메모리 원가(약화), AI 인프라 FOMC 민감도(확인 기회 없이 닫음), FOMC 뒤 스티프닝(결론 없이 닫음).
- 오늘 상태: 세 열린 판단 모두 판정 구간 안(위 운용 판단 브리핑 수치).

**2. 오늘의 실질 질문** — 엔비디아 단독 하락(S&P 대비 -6.617%p)과 나머지 반도체 급반등의 분리.
- 가설: 결론 시점이 없는 조사와 의회 일정이 핵심 인물 할인을 실적(11/17) 전까지 유지·확대한다.
- 대안: 하루 회전 매도, 이사회 해명·대통령 옹호·실적 기대로 되돌림(장중 시가 173.04 → 종가 178.60 회복이 이 쪽 관측).
- 가를 증거: 11/9 종가 대비 11/16 종가 엔비디아−S&P 500 누적 차이(±3.89%p).

**3. 계산 (재현 가능)**

(a) H4 기준값 — 입력: `data/history/market.jsonl` 의 `memory.Nvidia`, `indices.S&P 500` 일간 종가(2026-07-13~2026-11-09, 84행). 공식: 행 i 에 대해 ((NVDA_i/NVDA_{i-5}−1) − (SPX_i/SPX_{i-5}−1))×100, 마지막 20개 구간(10/6→10/13 … 11/2→11/9)의 절댓값 평균. 결과 **3.889%p**. 11/9 하루 차이: (-4.270) − (+2.346) = **-6.617%p**.

(b) 중간 관측 — 같은 파일:
- H1: 11/4 → 11/9 버티브 -2.471%, GE 버노바 -0.419%, 평균 -1.445%, S&P -1.804%, 차이 **+0.358%p**.
- H2: 11/5 → 11/9 XLK +5.235%, S&P +2.668%, 차이 **+2.566%p**; 2Y 4.477 → 4.547 = **+7.0bp**.
- H3: 2s10s 11/6 (4.859−4.522)×100 = 33.7bp, 11/9 (4.862−4.547)×100 = **31.5bp**, 변화 **-2.2bp** (`market_data.spread_2s10s_bp` 31.5 와 일치, 전 만기 네이버 11/9 동일자).

실행 명령 (repo 루트에서):
```
python3 - <<'EOF'
import json
rows={json.loads(l)['report_date']:json.loads(l) for l in open('data/history/market.jsonl')}
g=lambda d,k,n: rows[d][k][n]; D='2026-11-09'
v=(g(D,'ai_infra','Vertiv')/g('2026-11-04','ai_infra','Vertiv')-1)*100
e=(g(D,'ai_infra','GE Vernova')/g('2026-11-04','ai_infra','GE Vernova')-1)*100
s=(g(D,'indices','S&P 500')/g('2026-11-04','indices','S&P 500')-1)*100; print((v+e)/2-s)
x=(g(D,'sectors','Technology')/g('2026-11-05','sectors','Technology')-1)*100
s=(g(D,'indices','S&P 500')/g('2026-11-05','indices','S&P 500')-1)*100; print(x-s)
y=lambda d: (rows[d]['yields']['10Y']-rows[d]['yields']['2Y'])*100; print(y(D)-y('2026-11-06'))
r=[json.loads(l) for l in open('data/history/market.jsonl')]
nv=[q['memory']['Nvidia'] for q in r]; sp=[q['indices']['S&P 500'] for q in r]
d=[abs((nv[i]/nv[i-5]-sp[i]/sp[i-5])*100) for i in range(5,len(r))][-20:]; print(sum(d)/20)
EOF
```
날짜·만기 정합: 주식은 모두 Yahoo 일간 종가 동일 세션, 금리는 네이버 17:05 ET 전 만기 동일자. 11/11 채권 휴장은 H3 구간 안(보정 안 함).

**4. 다음 시험**
- 11/10 08:30 ET 10월 CPI(BLS) → H3 첫 근거; 근원 MoM이 컨센서스 0.2%를 넘으면 앞단 주도 평탄화(H3) 쪽, 밑돌면 대안 쪽.
- 11/10 16:00 ET 종가 → H1 판정(버티브·GE 버노바 평균−S&P, 11/4 기준 ±6.45%p).
- 11/12 16:00 ET 종가 → H2 판정(XLK−S&P, 11/5 기준 ±3.38%p).
- 11/13 17:05 ET 네이버 종가 → H3 판정(2s10s, 11/6 기준 ±5.82bp).
- 11/16 16:00 ET 종가 → H4 판정(엔비디아−S&P, 11/9 기준 ±3.89%p). 11/17 장 마감 뒤 엔비디아 실적은 구간 밖.
- 실행 포지션 없음 → 성과 측정 불가(performance unavailable).

## 출처 (웹, 전부 WebSearch 요약)
- Yahoo Finance live: https://finance.yahoo.com/markets/live/stock-market-today-monday-november-9-dow-sp-500-nasdaq-nvidia-090535419.html
- Yahoo Finance (Nvidia): https://finance.yahoo.com/markets/article/nvidia-stock-sinks-as-chipmaker-investigates-ceo-jensen-huangs-relationship-with-alleged-chinese-spy-130346548.html
- AP via SooLeader: https://www.sooleader.com/michigan-news-ap/us-stocks-rally-and-claw-back-more-of-last-weeks-losses-as-oil-prices-swing-lower-12994692
- Reuters via MarketScreener: https://www.marketscreener.com/news/wall-st-jumps-back-as-oil-slide-eases-inflation-worries-nvidia-slumps-ce785fd3de81f123 ; Kitco: http://www.kitco.com/news/off-the-wire/2026-11-09/wall-st-jumps-back-oil-slide-eases-inflation-worries-nvidia-slumps
- Free Malaysia Today (Reuters): https://www.freemalaysiatoday.com/category/business/2026/11/10/wall-street-jumps-as-oil-slide-cools-inflation-worries
- Detroit News: https://www.detroitnews.com/story/business/2026/11/09/wall-st-rallies-after-last-weeks-ai-rout-nvidia-falls/92689740007/
- Benzinga: https://www.benzinga.com/markets/equities/26/11/63055270/stock-market-today-nasdaq-100-chip-rebound-nvidia-deepseek ; https://www.benzinga.com/markets/equities/26/11/63046130/nvidia-stock-oversold-jensen-huang-affair-spy-probe
- Business Standard: https://www.business-standard.com/world-news/oil-prices-slide-over-5-as-trump-signals-no-fresh-iran-strikes-amid-talks-126110901602_1.html
- LBC: https://www.lbc.co.uk/article/439654de81084e8bb0b4d81de19e3b75-5Hjdm9p_2/ ; Jalopnik: https://www.jalopnik.com/2311063/oil-prices-fall-trump-loses-will-iran-war-fight/ ; Korea Times: https://www.koreatimes.co.kr/world/20261110/oil-falls-almost-5-as-trump-signals-restraint-on-iran
- FXStreet: https://www.fxstreet.com/news/gold-defies-fed-hike-bets-tops-4-100-as-oil-rout-hits-the-usd-202611092026
- Treasuries/FedWatch: https://www.marketscreener.com/news/treasuries-yields-edge-up-before-tuesday-s-cpi-release-ce785fd3d189f627 ; https://rallies.ai/news/treasury-yields-edge-up-before-tuesdays-cpi-release-1ef540bccd9a7e44 ; https://mlq.ai/news/brent-oil-falls-nearly-6-and-gold-jumps-while-two-year-treasury-yields-climb-before-cpi/ ; https://247wallst.com/investing/2026/11/07/odds-of-a-december-rate-hike-jump-to-77-after-a-blowout-jobs-report/
- 3년물 입찰: https://www.investing.com/news/economy-news/us-3year-treasury-auction-draws-weak-demand-amid-yield-decline-93CH-5013059 ; https://www.rttnews.com/3711991/three-year-note-auction-attracts-below-average-demand.aspx
- CPI 프리뷰: https://www.cnbc.com/2026/11/09/october-cpi-report-2026-inflation.html ; https://mlq.ai/news/october-cpi-preview-economists-expect-inflation-to-cool-as-gasoline-eases-with-no-official-annual-rate/
- 마벨-루멘텀: https://investor.marvell.com/news-events/press-releases/detail/1040/marvell-and-lumentum-to-combine-creating-a-category-leader-in-ai-connectivity
- 광학: https://www.tikr.com/blog/coherent-soars-18-lumentum-up-12-as-ai-optics-rebound-extends-despite-nvidia-turmoil ; https://247wallst.com/investing/2026/11/09/coherent-jumps-13-as-optical-stocks-extend-ai-rebound-lumentum-surges-11-applied-optoelectronics-rises-4/
- 전력: https://www.tikr.com/blog/ge-vernova-soars-7-as-constellation-raises-guidance-easing-data-center-moratorium-fears ; https://www.sec.gov/Archives/edgar/data/0001868275/000186827526000116/ceg-20261109991.htm
- 엔비디아 실적일: https://www.cmelitegroup.com/knowledge-hub/nvidia-earnings-date-fiscal-q3-2027-report-time-guidance-and-expected-move/?nocache=1
- CNBC(수집 요약, `news/2026-11-09.json`): https://www.cnbc.com/2026/11/09/nvidia-jensen-huang-investigation.html , https://www.cnbc.com/2026/11/09/jensen-huang-affair-nvidia-succession.html , https://www.cnbc.com/2026/11/09/nvidia-jensen-huang-china-spy-trump-lobbying.html , https://www.cnbc.com/2026/11/09/trump-jensen-huang-nvidia-chinese-spy.html , https://www.cnbc.com/2026/11/09/elizabeth-warren-senate-banking-agenda.html , https://www.cnbc.com/2026/11/09/october-jobs-report-hiring-by-sector.html , https://www.cnbc.com/2026/11/09/trump-unemployment-work-search-rule.html
- ING: https://think.ing.com/articles/fx-daily-dollar-rally-needs-more-risk-off-fuel/
