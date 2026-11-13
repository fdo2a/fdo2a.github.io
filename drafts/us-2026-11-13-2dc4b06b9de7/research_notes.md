# research_notes — US 2026-11-13 (금) 세션

수집 담당 메모. 시세는 Actions 커밋(commit cd14521b, generated 2026-11-14 08:31 KST, `complete: true`, `missing: []`)이 정본이며 재수집하지 않았다. 웹 리서치는 2026-11-13 23:00~23:38 UTC WebSearch 요약이다. **WebFetch는 이 세션에서 DNS 차단(cnbc.com, benzinga.com)이라 기사 원문을 열지 못했다** — 아래 웹 출처 문장은 검색 도구 요약에 기댄 것이다.

## 데이터 기준일

| 항목 | 기준 | 비고 |
|---|---|---|
| 주식·섹터·종목 | Yahoo 종가 2026-11-13 | 지수 date 전부 2026-11-13 일치 |
| FX·원자재 | close_1600_et 2026-11-13 | basis 필드 확인 |
| 국채 (yields) | **네이버 종가 17:05 ET, 전 만기 2026-11-13 동일 기준일** | `spread_2s10s_aligned: true`, 2s10s 27.9bp, 5s30s 50.0bp |
| FRED 대조 (yields_fred) | DGS2/5/10/30 2026-11-12 | 2s10s(FRED) 24.0bp — 대조용 |
| yield_drivers | 명목·실질 11/12, 기대인플레 11/13, 기간프리미엄 11/06, HY/IG 11/12 | 랙이 있는 지표는 그 관측창만 설명한다 |
| 수익률 커브 차트 | `yield_curve.png` (Actions 생성, 네이버 기준) 사용 | week_ago 기준일 11/05 (11/11 휴장 행 때문에 5행 전이 11/05) |
| 장중 | intraday.json 30분봉 | |

## ① 시황 동인 (장중 스윙 포함)

**종가**: 나스닥 25,136.27(-0.906%), S&P 500 7,561.67(-0.405%), 다우 52,347.55(+0.096%), 러셀 2000 2,790.49(-0.306%), S&P 500 성장 -0.912% / 가치 +0.199%. 섹터: 기술(XLK) -2.008%로 최하위, 필수소비재 +1.417%, 커뮤니케이션 +1.051%, 에너지 +0.979%, 금융 +0.807%, 헬스케어 +0.543%, 유틸리티 +0.525%, 부동산 +0.023%, 소재 -0.210%, 산업재 -0.390%, 경기소비재 -0.398%. 11개 섹터 중 7개 상승.

**참여도**: session.participation band 「소수가 끌어내림」(gap_pp 0.56, SPY -0.36%). price_context 상 S&P 500 움직임 band 「미미」(multiple -0.43), 나스닥 「보통」(-0.69). 펀드 보드 시장 국면은 「횡보」(2026-10-30부터 11세션, 가격 기준). TheStreet Pro는 주간 S&P 500 구성종목 399개 상승·104개 하락, 주간 S&P 500 +2.5%로 전했다(검색 요약).

**장중 궤적 (intraday.json)**: 선물은 「상승 출발」(갭 S&P +0.32%, 나스닥 +0.17%). PPI(08:30 ET)가 예상보다 낮게 나온 뒤 개장했고 S&P 500·나스닥 고점은 모두 09:30 봉이다. 이후 S&P 500은 10:00 봉 저점 7,499.40(시가 대비 -1.54%), 나스닥은 11:00 봉 저점 24,873.26(-2.11%), 엔비디아는 11:00 봉 저점 158.39(-6.77%)까지 밀렸다가 낙폭을 줄여 마감했다(종가 위치 S&P 50, 나스닥 47 — 「중단 마감」). Benzinga는 「주식이 PPI에 높게 출발했다가 반전했다」고 정리했다. Seeking Alpha는 11:44 ET 필라델피아 반도체지수가 -5.78%였다고 전했고, 종가 기준으로는 -3.4%로 11/5 이후 최악의 하루로 보도됐다(TheStreet Pro 요약). 즉 오전 저점의 촉매는 반도체 매도이고, 오후 회복은 반도체 낙폭 축소와 겹친다(시각 일치까지만 확인, 인과 확정 아님).

**동인**:
- 엔비디아 CEO 사임(11/12) 이튿날 반도체 전반 매도. 엔비디아 -2.01%, AMD -8.75%, 브로드컴 -4.76%(movers.json). 전날 AMD +5.86%·브로드컴 +5.54%로 나타난 「엔비디아→경쟁사 회전」이 하루 만에 되돌려졌다. CNBC는 주간 엔비디아 -11%, AMD +30%, 브로드컴 +24%로 회전을 정리하면서 임시 CEO가 대규모·위험한 조달 거래(생태계 투자)를 지원할 의지가 약할 수 있다는 관측을 전했다(검색 요약; 원문 미확인). Benzinga 제목은 「AMD Sinks 10.5% as Chip Rally Unwinds」(장중 수치).
- HSBC가 엔비디아를 보유로 낮추고 목표가를 365달러→170달러로 내렸다. 근거는 「새 CEO가 정해질 때까지 고전」, 비관 시나리오는 수출 규제로 FY2028 매출이 기준 대비 11% 감소(CNBC·Investing.com·MarketBeat). DA Davidson 목표가 300→200달러(MarketBeat).
- 블룸버그: 수출 금지 엔비디아 칩(H800)이 든 델 서버가 앨리스 황 연관 상하이 데이터센터에서 확인(Seeking Alpha·Benzinga 인용). 기록이 고의적 위반을 입증하지는 않는다고 함. 델 -7.18%(movers.json). CNBC(news 요약)는 의회가 국가안보 사안으로 조사 중이며 공화당 지도부가 황에게 출석을 요구했고, 내년 1월 의회를 장악할 민주당도 조사를 예고해 사안이 장기화할 전망이라고 전했다.
- 시스코 -6.24%: 11/12 장 마감 뒤 1분기(FY27) 실적 — 매출 185억 달러(+24%, 사상 최대), 비GAAP 매출총이익률 65.6%(전년 대비 -250bp, 하드웨어 비중·메모리 비용) — 마진 압박이 매도 사유로 보도(Benzinga, Cisco IR).
- 방어·가치 쪽으로 자금 이동: 필수소비재 +1.417%, 가치 +0.199% vs 성장 -0.912%, 다우 플러스. 이는 업종 등락으로 확인되는 사실이며, 「자금 이동」은 회전율·순유입 자료가 없어 해석이다.
- PPI(아래 ⑧): 헤드라인이 예상보다 낮아 개장 전 지지 재료였으나 연 6.5%로 금리 인하 기대를 되살리지는 못했다.

**그 밖의 시장**: DXY 103.411(+0.237%), EUR/USD 1.1027(-0.309%), USD/JPY 159.788(-0.060%), USD/KRW 1,334.97(+0.013%). WTI 88.93(-0.011%), 브렌트 96.13(+0.042%), 천연가스 3.238(-3.025%), 금 3,881.5(+0.052%, 장중 11:00 봉 저점 3,871.1). Fortune(news 요약)은 비트코인이 하루 4% 넘게 내려 68,500달러까지 밀렸다고 전했다(정본 시세 아님). 아시아 11/12 종가 평균 -0.88%(「이어감」), 유럽 평균 +0.29%(「엇갈림」).

## ② 채권·금리 맥락

**네이버 종가 11/13 (전 만기 동일 기준일)**: 2Y 4.874%(+1.0bp), 5Y 4.981%(+3.6bp), 10Y 5.153%(+5.0bp), 30Y 5.481%(+4.8bp). 2s10s 27.9bp(전일 네이버 기준 23.9bp → +4.0bp 스티프닝), 5s30s 50.0bp. 주간(week_ago 11/05): 2Y 4.477→4.874, 10Y 4.837→5.153.
- 11/6 대비(고용보고서 날): 2Y +35.2bp(4.522→4.874), 10Y +29.4bp(4.859→5.153), 2s10s 33.7→27.9bp(-5.8bp). 한 주 전체로는 앞단 주도 평탄화이고, 결론일 하루만 반대로 가팔라졌다.
- 11/12 네이버 커브는 결측이었다(history 11/12 행은 FRED 2Y 11/10 + Yahoo 스팟). 전일 네이버 기준값은 11/13 행의 bp(전일비)에서 역산한 것: 2Y 4.864, 10Y 5.103.
- CNBC: 10년물이 PPI 뒤 5%를 넘는 수준을 유지했고 장중 5.174%까지 올랐다. 전날(11/12)에도 10년물이 13bp 넘게 급등했다(news 요약). 검색 요약상 2년물은 PPI 직후 오전 4.85%까지 내렸다가 회복했다(장중 수치, 비정본).
- mlq.ai: 국채금리가 2025년 4월 이후 가장 가파른 주간 상승으로 향한다고 보도.
- **입찰 (auctions.json)**: 30년물(11/12, 250억 달러) 응찰배율 2.36(6회 평균 2.44), 간접 68.1%(평균 대비 -2.4%p), 딜러 11.4%(+1.9%p) → 「수요 약함」. 10년물(11/10, 420억 달러) 응찰배율 2.46(평균 2.60), 간접 61.2%(평균 76.6%), 딜러 9.8% → 「수요 약함」. 테일은 WI 출처가 없어 미산출(tail_status no_wi_source). 다음 주 20년물 160억 달러(11/18 13:00 ET), 10년물 190억 달러(11/19 13:00 ET, calendar.json).
- **yield_drivers (FRED, 랙 주의)**: 11/12 10년 실질금리 2.86%(+8bp, 5일 +22bp), 5년 실질 2.64%(+8bp), 10년 기대인플레(T10YIE) 11/13 2.24%(보합, 5일 0bp), 5y5y 2.18%(+1bp). 10년 기간프리미엄 0.87%(11/06 기준 — 이번 주 충격을 설명하지 못함). HY 스프레드 3.20%(-10bp, 11/12), IG 0.89%(-1bp). → 이번 주 장기물 상승은 FRED 기준 실질금리 쪽이고 기대인플레(명목-실질, 위험·유동성 프리미엄 포함)는 거의 안 움직였다. 크레딧 스프레드는 좁아졌다 — 채권 매도 주체를 이것으로 식별할 수는 없다.
- QRA(liquidity.json): 2026Q4 가이던스 문구가 "at least the next several quarters" → "the next several quarters"로 바뀜(쿠폰 증액 가능성 신호로 읽힐 수 있는 문구 변화; 시장 해석 출처는 미확보).
- 베선트 재무장관(CNBC 인터뷰, Al Jazeera 보도): 에너지 공급 충격은 일시적일 수 있으니 연준이 금리를 올리지 말아야 한다고 촉구.

## ③ 메모리/DRAM (둘째 글 재료)

- 정본: 마이크론 778.31(-2.521%), 웨스턴디지털 295.65(-5.000%), 시게이트 528.29(-3.091%), 엔비디아 162.85(-2.010%), 삼성전자 206,000(-0.962%, 11/13 KRX), SK하이닉스 1,216,000(-3.030%). 샌디스크 -5.59%(movers.json).
- 원인 보도: 샌디스크 장중 -8%(약 860달러), 마이크론 -4~5%, 웨스턴디지털 장중 약 -7% — 엔비디아 CEO 퇴진에서 시작된 반도체 매도와 메모리 가격 우려(Motley Fool 「Why Sandisk Stock Is Falling Today」, Invezz 「Why are Micron, SK Hynix, and SanDisk stocks falling on Friday?」, 24/7 Wall St.). Motley Fool은 샌디스크가 지난 한 달 42% 넘게 내렸다고 전함.
- 트렌드포스(11/11 보도, 검색 요약): 4분기 범용 D램 고정거래가 +10~15%(전분기 대비), PC D램 +13~18%(3분기 +18~23%에서 둔화), 구매자가 공급사 호가에 저항, 11월 계약은 소폭 상승 수준 타결 예상. DDR4 현물가는 11/3까지 한 주 -0.09%. (원문 미확인, 수치는 검색 요약)
- 시스코 실적에서 메모리 비용이 매출총이익률 하락 요인으로 언급(한 출처) — 메모리 가격 상승이 수요측 마진 압박으로 나타나는 사례.

## ④ AI 인프라 (둘째 글 재료)

- 정본: 마벨 156.76(-4.676%), 코히어런트 218.15(-6.002%), 루멘텀 596.62(-4.487%), GE 버노바 803.13(-1.877%), 버티브 202.07(-3.611%).
- 마벨 10:10 ET -6.6%(153.60달러) — 엔비디아 리더십 변화가 광통신 파트너에 부담(GuruFocus via TradingView). 엔비디아는 지난 1년 네비우스·마벨·루멘텀·코히어런트·코어위브에 각각 약 20억 달러를 투자했다(Blockonomi 요약). 마벨-루멘텀 전 주식 인수(11/2 발표, 1,150억 달러)의 차익 스프레드가 18%로 벌어졌다는 보도.
- 앤스로픽 IPO: 최종 가격 11/18(EST) 결정, 11/19 거래 예정(규제 승인 조건부; 앤스로픽 IPO 사이트 검색 요약). 르네상스캐피털(11/10): 610억 달러 공모, 시총 1.2조 달러 목표.
- CNBC 요약: 하이퍼스케일러는 상대적으로 버텼다 — 메타 +2.8%, 아마존·알파벳 소폭 하락.
- 마이크로소프트 365·아웃룩 대규모 장애(11/12 13시경 시작)에 대해 11/13 사과, 원인은 네트워크 용량 업그레이드 과정 문제로 추정(news 요약, CNBC).
- 버티브·GE 버노바의 11/13 고유 재료는 검색에서 찾지 못했다.

## 움직인 종목의 이유 (movers.json groups)

| id | 묶음 | 원인 한 줄 | 출처 |
|---|---|---|---|
| g1 | 반도체 하락 — 엔비디아 -2.01%, 브로드컴 -4.76%, AMD -8.75% | 엔비디아 CEO 사임 이튿날 반도체 전반 매도. HSBC 엔비디아 보유 하향(목표가 365→170달러), 델 서버 상하이 유입 보도로 수출통제 우려가 겹쳤고, 전날 엔비디아에서 AMD·브로드컴으로 옮겨 간 회전(주간 AMD +30%, 브로드컴 +24%)이 되돌려졌다는 보도 | Benzinga 11/13 시황, CNBC 11/13 「Nvidia's turmoil is prompting a rotation across chip stocks」, CNBC·Investing.com HSBC 기사 (검색 요약) |
| g2 | 인터랙티브 미디어 상승 — 메타 +2.90% | **확인된 재료 없음** (CNBC 요약은 하이퍼스케일러가 상대적으로 버텼다고만 서술, 메타 고유 원인 미보도) | 검색 1회, 11/13 날짜 기사 없음 |
| g3 | 하드웨어 상승 — 애플 +0.39% | **확인된 재료 없음** | 별도 검색 안 함(지수 기여 상위, 등락 미미) |
| g4 | 하드웨어·스토리지 하락 — 샌디스크 -5.59%, 델 -7.18%, 웨스턴디지털 -5.00% | 델: 블룸버그가 수출 금지 엔비디아 칩이 든 델 서버를 앨리스 황 연관 상하이 데이터센터에서 추적했다고 보도(고의 위반 입증은 아님). 샌디스크·웨스턴디지털: 엔비디아발 반도체 매도와 메모리 가격 우려 | Bloomberg via Seeking Alpha/Benzinga; Motley Fool, Invezz, 24/7 Wall St. |
| g5 | 통신장비 하락 — 시스코 -6.24% | 11/12 장 마감 뒤 FY27 1분기 실적: 매출 사상 최대(185억 달러, +24%)·연간 전망 상향에도 비GAAP 매출총이익률 65.6%(전년 대비 -250bp, 하드웨어 비중·메모리 비용)로 마진 압박이 매도 사유로 보도 | Cisco IR 11/12, Benzinga 11/13 |

등락률은 movers.json 값이 정본이다(보도의 장중 수치와 다름).

## ⑤ 경제지표 4축 표

Actual/Previous는 `data/econ_indicators.json`(FRED, 2026-11-14 08:31 KST) 값 그대로, 출처 FRED. Forecast·발표일은 최근 발표분만 웹. 오래된 기준월은 Forecast 공란, 발표일은 기준월로 갈음.

| 축 | 지표 | Actual | Forecast | Previous | 발표일(기준월) | 출처 |
|---|---|---|---|---|---|---|
| 물가 | PPI 최종수요 MoM | 0.35% | 0.4% (다우존스) | 1.41% | 2026-11-13 (10월) | FRED / 예상: CNBC·StockTitan |
| 물가 | (참고) PPI 최종수요 YoY, 비계절조정 | 6.5% (BLS 원문) | 6.6% | — | 2026-11-13 (10월) | BLS 원문 / 예상: StockTitan 프리뷰 |
| 물가 | (참고) PPI 식품·에너지 제외 MoM | 0.3% (CNBC 보도) | 0.3% | — | 2026-11-13 (10월) | CNBC (FRED 미대조) |
| 물가 | CPI MoM | 0.35% | — | 0.65% | 2026-11-10 (10월) | FRED |
| 물가 | Core CPI MoM | 0.30% | — | 0.33% | 2026-11-10 (10월) | FRED |
| 물가 | PCE Price Index YoY | 3.65% | — | 3.44% | (2026-09) | FRED |
| 물가 | Core PCE YoY | 3.12% | — | 3.03% | (2026-09) | FRED |
| 물가 | Michigan 1-Yr Inflation Exp | 4.6% | — | 4.0% | (2026-09) | FRED |
| 고용 | Initial Jobless Claims | 200,000 | — | 191,000 | 2026-11-12 (11/7 주) | FRED |
| 고용 | Initial Claims 4-wk MA | 195,250 | — | 195,250 | 2026-11-12 (11/7 주) | FRED |
| 고용 | Continuing Jobless Claims | 1,697,000 | — | 1,717,000 | 2026-11-12 (10/31 주) | FRED |
| 고용 | Nonfarm Payrolls (chg) | 165K | — | 60K | 2026-11-06 (10월) | FRED |
| 고용 | Unemployment Rate | 4.1% | — | 4.2% | 2026-11-06 (10월) | FRED |
| 고용 | Avg Hourly Earnings MoM | 0.37% | — | 0.26% | 2026-11-06 (10월) | FRED |
| 고용 | JOLTS Job Openings | 7,523K | — | 7,190K | (2026-09) | FRED |
| 활동 | Industrial Production MoM | 0.66% | — | 0.06% | (2026-09) | FRED |
| 활동 | Durable Goods Orders MoM | 1.91% | — | 0.14% | (2026-09) | FRED |
| 활동 | Factory Orders MoM | 1.84% | — | 0.33% | (2026-09) | FRED |
| 활동 | Construction Spending MoM | -1.85% | — | 1.98% | (2026-09) | FRED |
| 활동 | Housing Starts | 1,221K | — | 1,288K | (2026-09) | FRED |
| 활동 | New Home Sales | 676K | — | 680K | (2026-09) | FRED |
| 활동 | Existing Home Sales | 3,750,000 | — | 3,970,000 | (2026-10) | FRED |
| 활동 | Trade Balance | -$105.05B | — | -$105.74B | (2026-09) | FRED |
| 활동 | Real GDP Growth QoQ (ann.) | 3.4% | — | 2.2% | (2026-Q3, ref 2026-07-01) | FRED |
| 활동 | Philly Fed Manufacturing (해부만, 점수 밖) | 20.9 | — | 37.8 | (2026-10) | FRED |
| 소비 | Retail Sales MoM | 0.77% | — | 1.29% | (2026-09) | FRED |
| 소비 | Michigan Consumer Sentiment | 48.1 | — | 51.7 | (2026-09) | FRED |

주: FRED PPI MoM 0.35%는 지수 수준에서 계산한 값이고 BLS 발표 반올림치는 0.3%다. 「PPI 근원」은 두 정의가 있다 — CNBC가 전한 식품·에너지 제외 0.3%(예상 부합)와 BLS가 본문에 쓴 식품·에너지·무역서비스 제외 0.5%(⑧). 서로 다른 지표라 섞지 말 것.

macro_metrics 축 요약: 고용 「개선·완만」(일곱 중 다섯 개선), 생산·활동 「악화·완만」, 소비 「보합·미미」, 물가 「재가속·완만」(inflation_score 0.647, growth_score 0.065).

비FRED 지표(ISM·S&P Global PMI·ADP·CB·NY Fed SCE): 최근 7일 내 발표분의 Actual/Forecast/Previous는 이번 회차에서 확보하지 못함 → ⑦.

## ⑥ 시장 해석·FedWatch

- CME FedWatch 12월 9일 FOMC 25bp 인상(4.00~4.25%) 확률(보도치, 스냅샷 시각 상이): FXEmpire 89.7%(전일 85%), 50bp 확률 14.5%→10.3%; Al Jazeera 89.4%; CNBC 국채 기사 89%; Kiplinger 약 90%; Tokenpost 발표 전 86%→91%; Mishtalk 25bp 단독 93.7%·50bp 6.3%. 현재 기준금리 3.75~4.00%.
- 1월 회의 추가 인상 확률: CBS가 「50% 이상」이라고만 전함 — 수치 미확보.
- 기관 해석: BofA(바베)는 12·1·3월 매번 25bp 인상, TD는 3회 연속(종전 2회)으로 상향(CBS). PIMCO는 12월·1월 인상이 바람직하고 3월 추가 위험(검색 요약). 월러 이사는 12월 50bp 검토를 주장(CBS). 굴스비 시카고 연은 총재는 물가 상승이 유가·관세를 넘어 여러 품목으로 퍼진다고 우려(CNBC). Babypips: PPI가 12월 인상을 바꾸지 못할 것.
- 해석: 헤드라인 PPI가 예상을 밑돌았는데도 12월 인상 확률은 올랐고 50bp 확률이 내려갔다 → 「크기」 기대는 줄고 「인상 자체」는 굳었다. 2년물은 거의 안 움직이고(+1.0bp) 10년물이 올랐다. OIS 경로는 확보하지 못했다 — FedWatch와 OIS를 같은 측정치로 섞지 말 것.

## ⑦ 미확정 항목

- PPI 헤드라인 외 컨센서스: 「식품·에너지·무역서비스 제외」 컨센서스 미확보. YoY 6.6% 예상은 프리뷰 1곳(StockTitan) 출처.
- CPI(11/10) 컨센서스: 이번 회차에서 재검색하지 않음(Forecast 공란).
- 신규 실업수당(11/12 발표분) 컨센서스: 미확보.
- 비FRED 지표(NY Fed SCE 등) 최근 7일 발표분 수치: 미확보 — 발행 시 생략.
- FedWatch 1월 회의 확률 수치, 발표 전후 동일 시각 스냅샷: 미확보.
- OIS 경로, 커브(2s10s) 포워드·옵션 기대: 미확보.
- 메타(g2)·애플(g3) 원인: 확인된 재료 없음.
- 버티브·GE 버노바 11/13 고유 재료: 확인되지 않음.
- 10년·30년물 입찰 테일: WI 출처 없음.
- 엔비디아 실적 정확한 발표일: 원장 기록상 11/17 장 마감 뒤로 되어 있으나 이번 회차 검색에서 2026년 날짜를 재확인하지 못함(주간 프리뷰 1곳이 「다음 주 엔비디아 실적」만 언급). 작성 시 날짜를 명시해야 하면 「다음 주」로 두거나 원장 기록 인용임을 밝힐 것.
- FOMC 의사록(10/28 회의분) 발표일: 미확인(통상 3주 뒤).
- CNBC 「임시 CEO가 대규모 조달 거래 지원 의지 약할 수 있다」 관측: 검색 요약 1건, 원문 미확인 — 인용 시 「보도된다」 수준으로.

## ⑧ 신규 발표 해부

**생산자물가(PPI) · BLS · 2026년 10월분** — 원문 도달: **예** (`releases/index.json` report_date 2026-11-13, status complete, ppi `ok: true`, verified, impersonate=safari; `releases/ppi.txt`). 원문 URL https://www.bls.gov/news.release/ppi.nr0.htm

- 헤드라인: 최종수요 +0.3%(계절조정, FRED 0.35%), 9월 +1.4%, 8월 +0.4%. 비계절조정 12개월 6.5% — 「the largest 12-month rise since moving up 7.4 percent in November 2022」.
- 교차 검증된 구성(macro_metrics `components`, FRED·원문 일치): 식품·에너지·무역서비스 제외 +0.5%(FRED 0.486). 원문: 「rose 0.5 percent in October, the same as in September. For the 12 months ended in October, prices for final demand less foods, energy, and trade services advanced 4.9 percent.」 (anatomy_status partial — components_short, 이 외 항목은 FRED 교차 확인 없음 → 아래는 원문 서술 인용으로만 쓴다)
- 기여도 귀속(원문 문장 그대로):
  - 「Leading the October advance in final demand prices, the index for final demand goods increased 0.5 percent. Prices for final demand services moved up 0.2 percent.」
  - 재화: 「Over 60 percent of the advance in October is attributable to prices for final demand goods less foods and energy, which moved up 0.5 percent. The index for final demand foods increased 1.3 percent. In contrast, prices for final demand energy edged down 0.1 percent.」 12개월 재화 10.2%(2022년 10월 이후 최대).
  - 서비스: 「Three-fourths of the October rise can be traced to a 2.0-percent increase in prices for final demand transportation and warehousing services.」 무역 마진은 -0.2%. 「Over 80 percent of the October increase in the index for final demand services is attributable to prices for truck transportation of freight, which rose 3.9 percent.」
  - 원문이 이름을 부른 세부: 기초 유기화학 +3.9%, 디젤 -7.9%, 기계·차량 도매 마진 -4.2%, 시스템 소프트웨어·항공 여객 하락.
- 중간재: 가공재 +0.4%(3개월 연속, 12개월 14.6% — 2022년 7월 이후 최대), 비가공재 -3.1%(원유 -10.3%가 주 요인), 중간수요 서비스 +0.6%(12개월 6.8%).
- Table A 최근 6개월(최종수요 MoM, 계절조정): 5월 0.5 / 6월 -0.1 / 7월 0.1 / 8월 0.4 / 9월 1.4 / 10월 0.3. 식품·에너지·무역 제외: 0.8 / 0.2 / 0.4 / 0.3 / 0.5 / 0.5. 최종수요 에너지: 8.2 / -7.2 / -1.5 / 4.2 / 10.0 / -0.1.
- 수정: 각주 「data for June through September have been revised to reflect the availability of late reports and corrections by respondents」. 9월 최종수요 1.4%는 FRED Previous 1.41%와 일치 — 9월 헤드라인 수정폭은 0에 가깝다(원문이 개별 수정폭을 명시하지 않음).
- 특이 요인: 에너지 보합(-0.1%) 속에 디젤 -7.9%·원유 -10.3%가 내렸고, 서비스 상승은 트럭 운송 한 품목에 집중. 무역 마진 하락(-0.2%)이 헤드라인을 눌렀다.
- 시장·연준 관점: 헤드라인이 예상(0.4%)을 밑돈 것은 에너지 보합과 무역 마진 하락 때문이고, 연준이 보는 기조 쪽(식품·에너지·무역 제외 0.5%가 두 달 연속, 식품 1.3%, 운송 2.0%)은 식지 않았다. 에너지 충격이 운송·식품·중간재로 번지는 경로가 원문에서 확인돼, 「일시적 에너지 충격」을 이유로 인상을 반대한 베선트 논리보다 굴스비의 「확산」 우려 쪽 근거에 가깝다. 시장은 12월 인상 확률을 올리고 50bp 확률을 낮췄다(⑥).

## ⑨ 연준 이벤트 반응

`fed/events.json`의 events가 비어 있음(fresh tier-1 이벤트 없음) → 해당 없음.

## 운용 판단 브리핑

**오늘의 범위와 자료 공백**: 지수 하락은 작았고(S&P 500 -0.405%, band 「미미」) 손실은 반도체·AI 하드웨어에 몰렸다(XLK -2.008%, 다우 +0.096%, 11개 섹터 중 7개 상승). 금리는 PPI 뒤 장기물이 더 올라 커브가 하루 4.0bp 가팔라졌다. 자료 공백: OIS·1월 FedWatch 수치·커브 옵션 기대 없음, 기사 원문(WebFetch) 접근 불가, 메타·애플 원인 미확인.

### 질문 1 — 금리: 12월 인상이 반영된 뒤 커브는 장기물이 끄는가 (신규 판단 `us-2026-11-13-ppi-curve-long-end-steepening-vs-front-end-hikes`)
- 관측: 네이버 11/13 2Y 4.874%(+1.0bp), 10Y 5.153%(+5.0bp), 2s10s 27.9bp(+4.0bp). 11/6 이후로는 2Y +35.2bp, 10Y +29.4bp로 앞단 주도. 10·30년물 입찰 모두 「수요 약함」. FRED 10년 실질 +8bp(11/12), 10년 기대인플레 보합.
- 기대 근거(날짜·측정치): CME FedWatch 12/9 FOMC 25bp 인상 89.4~89.7%(11/13 보도치, 전일 85%), 50bp 10.3%. 1월은 「50% 이상」(CBS, 수치 없음). 커브 기대는 **미확인**.
- 해석: 12월은 거의 반영 — 앞단에 남은 재가격은 1·3월 경로뿐. 장기물은 공급(약한 입찰, 다음 주 20년물)·실질금리로 기간프리미엄이 붙는 국면 → 11/20까지 2s10s 스티프닝.
- 대안(가장 강한 것): BofA·TD의 12·1·3월 연속 인상 전망대로 11/17 소매판매 등이 강하면 1월 인상 반영으로 2년물이 다시 앞서 평탄화 재개(최근 20개 5행 구간 중 13개가 평탄화). 반도체 매도가 위험회피로 번지면 장기물 매수 → 불 평탄화.
- 가르는 관측·촉매·기한: 11/13 27.9bp 대비 11/20 네이버 종가 2s10s 변화 ±5.07bp(10/16~11/13 끝 20개 5행 구간 절댓값 평균, 11/12 끝 구간 제외). 10년물 누적이 음수면 메커니즘 판정 불가. 촉매: 11/17 08:30 ET 소매판매, 11/18 13:00 ET 20년물 입찰, 11/19 08:30 ET 실업수당·13:00 ET 10년물(190억 달러) 입찰, FOMC 의사록(날짜 미확인).
- 투자 관련성(조건부, 권고 아님): 테마로는 듀레이션 노출이 큰 성장·장기 현금흐름 테마(소프트웨어·전력망·고밸류 기술)의 할인율 근거와 금융(커브 스티프닝은 순이자마진 근거, 이날 XLF +0.807%)에 닿는다. 표현 수단을 굳이 고르면 커브 스티프너(2년 대비 10년) 같은 상대가치가 방향성 듀레이션보다 질문에 직접 대응하지만, 펀드는 해외주식+원화 단기채 구조라 국채 선물 커브 거래 접근·DV01 매칭·롤·증거금 비용은 **미확인/미보유 입력**이다. 지금은 관찰 단계 — 결론은 11/20.
- 반증: 2s10s가 -5.07bp 이하로 평탄화되면 견해 약화.

### 질문 2 — AI 하드웨어: 엔비디아 고유 할인이 업종 전반으로 번지는가 (기존 판단으로 추적)
- 관측: 엔비디아 -2.01%, AMD -8.75%, 브로드컴 -4.76%, 마벨 -4.676%, 코히어런트 -6.002%, 웨스턴디지털 -5.000%, 시스코 -6.24%, 델 -7.18%; XLK -2.008% vs S&P 500 -0.405%. 전날의 「경쟁사로 회전」이 되돌려졌다.
- 기대 근거: 보도 서사(HSBC 「새 CEO 전까지 고전」, CNBC 회전 서사, 블룸버그 수출통제 보도). 가격 기반 기대(옵션 내재변동성·포지셔닝)는 **미확인**.
- 해석 vs 대안: (a) 엔비디아 리더십 공백이 생태계 투자·수출통제 경로로 AI 하드웨어 전반의 할인으로 번짐(엔비디아 투자처 마벨·코히어런트·루멘텀 동반 하락, 델 수출통제 보도) vs (b) AMD +30%·브로드컴 +24% 주간 급등 뒤의 차익 실현과 다음 주 엔비디아 실적·앤스로픽 IPO(11/18 가격 결정 예정) 앞둔 포지션 정리. 하루 종가로는 가르지 못한다.
- 원장 연결: 엔비디아 지배구조 할인(`us-2026-11-09-nvidia-governance-discount-persist`, 11/16 결론) 현재 -9.010%p로 지지 기준 안쪽; 메모리(`us-2026-11-11-memory-coreweave-financing-relief-vs-beta-bounce`, 11/17) -3.892%p로 되돌림 쪽; 전력설비(`us-2026-11-10-ai-power-softbank-order-risk`, 11/17) +1.861%p. 반도체 테마의 가격 근거는 이날 **약화**, 방어(필수소비재 +1.417%)는 하루치 **강화** — 단 하루 업종 등락이며 순유입 자료 아님.
- 실행 한계: 펀드 보드 VaR·순위는 가격 기반이며 유닛 위험이 아님. 보유·비중 미제공. 신규 아이디어 없음 — 다음 주 엔비디아 실적이 가르는 재료.

### 에너지 (기존 판단 `us-2026-11-12-energy-iran-duration-vs-headline-bounce`)
- 첫날 XLE +0.979% vs S&P 500 -0.405%(+1.384%p)로 견해 방향이나, WTI는 -0.011%로 반대 부호 → 첫날 상대 강세는 유가가 아니라 기술주에서 방어·가치 업종으로의 이동과 겹친다. IEA는 10월 세계 공급 +230만 배럴/일로 분쟁 뒤 첫 공급 과잉이라고 밝힘(CNBC). 결론 11/19.

### 근거 파일·ID
- 정본 입력: `market_data.json`(yields·sectors·memory·ai_infra·commodities·session·price_context·yield_drivers), `intraday.json`, `movers.json`, `auctions.json`, `macro_metrics.json`(headline_releases ppi), `releases/ppi.txt`, `news/2026-11-13.json`, `data/history/market.jsonl`.
- 원장: cycle `us-2026-11-13-daily-cycle`; 신규 hypothesis `us-2026-11-13-ppi-curve-long-end-steepening-vs-front-end-hikes`; reviews `us-2026-11-13-payrolls-front-end-flattening-vs-riskoff-review1`(closed), `us-2026-11-13-nvidia-governance-discount-persist-review3`, `us-2026-11-13-ai-power-softbank-order-risk-review3`, `us-2026-11-13-memory-coreweave-financing-relief-vs-beta-bounce-review2`, `us-2026-11-13-energy-iran-duration-vs-headline-bounce-review1`. 증거 사본: `research/us/evidence/`(웹 요약 원본 `.research-drafts/us/2026-11-13/web_session.md`).

### 이전 판단의 변화와 미결
- 고용 평탄화(11/6) — **판정 불가로 닫음**: -5.80bp vs 기준 -5.82bp(0.02bp 차). 방향은 평탄화 쪽이었으나 결론일 하루가 반대로 움직여 기준선 직전에서 멈췄다. 실행 포지션 없음.
- 엔비디아(11/9) — 지지 기준 안쪽 유지(-9.010%p), 11/16 결론.
- 전력설비(11/10) — 판정 구간 안(+1.861%p), 2년물 조건 +14.7bp(<+25bp), 11/17 결론.
- 메모리(11/11) — 판정 구간 안(-3.892%p), 되돌림 쪽 확대, 2년물 +14.7bp(±25bp 안), 11/17 결론.
- 에너지(11/12) — 첫날 +1.384%p, WTI 반대 부호, 11/19 결론.
- 미결(unresolved) 없음 — 열린 판단 전부에 오늘 검토 기록이 있다.

## 학습·복기

**1. 이전 질문** — `posts/2026-11-12.html`(2026-11-12), 학습 블록(`data-learning="daily"`, cycle `us-2026-11-12-daily-cycle`)의 마지막 확인 과제: 「11월 13일 네이버 국채 종가가 돌아오면 고용 평탄화 판단의 결론과 함께 메모리·전력설비 판단의 2년물 조건도 다시 잴 수 있다.」 원 시험 조건: 고용 평탄화 판단은 11/6 2s10s 33.7bp 대비 11/13 네이버 종가 2s10s 변화가 -5.82bp 이하이면 지지, +5.82bp 이상이면 약화, 그 사이·네이버 결측·기준일 불일치면 판정 불가. 메모리 판단 2년물 조건은 11/10 네이버 4.727% 대비 ±25bp, 전력설비는 +25bp 이상이면 메커니즘 판정 불가. 기한: 11/13 17:05 ET 네이버 종가.
- 결과: 11/13 네이버 종가가 전 만기 동일 기준일로 돌아왔다. 고용 평탄화 -5.80bp → 판정 불가로 닫음. 2년물 누적 +14.7bp → 메모리·전력설비 모두 2년물 조건에 걸리지 않음(메커니즘 판정을 막지 않음).

**2. 오늘의 질문** — 관측: PPI 헤드라인이 예상보다 낮았는데 2년물은 +1.0bp, 10년물은 +5.0bp. 가설: 12월 인상이 90% 안팎 반영된 뒤 커브는 장기물 기간프리미엄이 끈다. 대안: 1월 인상 반영으로 앞단 주도 평탄화 재개(또는 위험회피 불 평탄화). 가르는 증거: 11/20 네이버 2s10s 변화 방향·크기와 10년물 누적 부호.

**3. 계산 (재현 가능)**
- 입력: `data/history/market.jsonl` yields(네이버 종가, %) — 11/06: 2Y 4.522, 10Y 4.859; 11/10: 2Y 4.727; 11/13: 2Y 4.874, 10Y 5.153. 만기 정의 동일(2년·10년 국채), 두 날 모두 네이버 17:05 ET 동일 기준일.
- 공식: 2s10s(bp) = (10Y − 2Y) × 100; 변화 = 2s10s(11/13) − 2s10s(11/06); 2년물 누적(bp) = (2Y(11/13) − 2Y(11/10)) × 100.
- 명령: `python3 -c "print(round((5.153-4.874)*100,1), round((4.859-4.522)*100,1), round(((5.153-4.874)-(4.859-4.522))*100,2), round((4.874-4.727)*100,1))"`
- 결과: 27.9bp, 33.7bp, **-5.80bp**, 2년물 +14.7bp.
- 기준값(신규 판단): 10/16~11/13에 끝나는 20개 5행 구간의 2s10s 변화 절댓값 평균 = **5.070bp**(끝점이 네이버가 아닌 11/12 행인 구간 1개 제외, 10/12 채권 휴장 행·11/11 휴장 행 포함). 20개 중 평탄화 13개.
- 주식 상대 성과(원장 검토용, Yahoo 종가): 엔비디아 11/9→11/13 178.67→162.85 -8.854%, S&P 500 7,549.94→7,561.67 +0.155%, 차이 -9.010%p. 버티브 194.22→202.07 +4.042%, GE 버노바 797.04→803.13 +0.764%, 평균 +2.403%, S&P 500(11/10→) 7,520.93→7,561.67 +0.542%, 차이 +1.861%p. 메모리 11/11→11/13 마이크론 811.30→778.31 -4.066%, 웨스턴디지털 313.31→295.65 -5.637%, 시게이트 551.72→528.29 -4.247%, 평균 -4.650%, S&P 500 7,619.38→7,561.67 -0.757%, 차이 -3.892%p. XLE 11/12→11/13 64.33→64.96 +0.979%, S&P 500 -0.405%, 차이 +1.384%p, WTI 88.94→88.93 -0.011%.

**4. 다음 시험** — 11/20(금) 17:05 ET 네이버 국채 종가의 2s10s가 27.9bp 대비 +5.07bp 이상이면 장기물 주도 판단 지지, -5.07bp 이하면 약화, 사이면 판정 불가. 다음 세션(11/16) 관찰 포인트: 2년물이 4.874%에서 10년물보다 더 오르는지(평탄화 신호). 일정 출처: calendar.json(소매판매 11/17 08:30 ET, 20년물 입찰 11/18 13:00 ET, 실업수당 11/19 08:30 ET, 10년물 입찰 11/19 13:00 ET, 모두 ET).

## 출처 (웹)
- [Benzinga — AMD Sinks 10.5%, Nasdaq 100 Falls 1.7% (11/13)](https://www.benzinga.com/markets/equities/26/11/63259862/stock-market-today-amd-nvidia-chip-selloff-cisco-modine-november-13)
- [Benzinga — This Week On Wall Street](https://www.benzinga.com/markets/market-summary/26/11/63269563/this-week-on-wall-street-nvidia-huang-amd-broadcom-fed-hike)
- [Reuters via MarketScreener — Wall St slides as Nvidia uncertainty drags tech shares lower](https://www.marketscreener.com/news/wall-st-slides-as-nvidia-uncertainty-drags-tech-shares-lower-ce785eded98af723)
- [CNBC — Nvidia's turmoil is prompting a rotation across chip stocks](https://cnbc.com/2026/11/13/nvidia-jensen-huang-affairs-amd-broadcom-tsmc.html)
- [CNBC — HSBC downgrades Nvidia](https://www.cnbc.com/2026/11/13/hsbc-downgrades-nvidia-says-stock-to-struggle-until-new-ceo-named.html)
- [TheStreet Pro — Chips Slide Again, but the S&P 500 Still Ends the Week Up 2.5%](https://pro.thestreet.com/market-commentary/chips-slide-again-but-the-sp-500-still-ends-the-week-up-2-5)
- [Seeking Alpha — Chip stocks slide as Nvidia rebound fades](https://seekingalpha.com/news/4672499-chip-stocks-slide-as-nvidia-rebound-fades)
- [Seeking Alpha — Banned Nvidia chips traced to Alice Huang-linked data center in Shanghai](https://seekingalpha.com/news/4672155-banned-nvidia-chips-traced-to-alice-huang-linked-data-center-in-shanghai---report)
- [Seeking Alpha — Dell Technologies falling 8%](https://seekingalpha.com/news/4672432-dell-technologies-gives-back-some-recent-gains-falling-8)
- [Cisco IR — Cisco Reports First Quarter Earnings](https://investor.cisco.com/news/news-details/2026/CISCO-REPORTS-FIRST-QUARTER-EARNINGS/default.aspx)
- [Motley Fool — Why Sandisk Stock Is Falling Today](https://www.fool.com/investing/2026/11/13/why-sandisk-stock-is-falling-today/)
- [Invezz — Why are Micron, SK Hynix, and SanDisk stocks falling on Friday?](https://invezz.com/news/2026/11/13/why-are-micron-sk-hynix-and-sandisk-stocks-falling-on-friday/)
- [GuruFocus via TradingView — Marvell falls 6.6%](https://www.tradingview.com/news/gurufocus:c655b62ef094b:0-marvell-stocks-fall-6-6-as-lumentum-deal-spread-widens-to-18/)
- [Blockonomi — Nvidia's stakes in Intel and Marvell](https://blockonomi.com/what-jensen-huangs-exit-means-for-nvidias-stakes-in-intel-and-marvell)
- [Renaissance Capital — Anthropic sets terms for $61B IPO](https://www.renaissancecapital.com/IPO-Center/News/122657/anthropic-sets-terms-for-61-billion-ipo-targeting-a-1.2-trillion-market-cap)
- [TrendForce digest — PC DRAM 4Q26](https://cryptobriefing.com/trendforce-pc-dram-prices-rise-4q26/)
- [CNBC — Wholesale prices rose 0.3% in October](https://www.cnbc.com/2026/11/13/ppi-inflation-report-october-2026.html)
- [CNBC — 10-year Treasury yield moves to 5.17%](https://www.cnbc.com/2026/11/13/treasury-yields-fed-rates.html)
- [StockTitan — October 2026 PPI preview](https://www.stocktitan.net/articles/october-2026-ppi-preview-yearly-rate)
- [FXEmpire — Tame PPI fails to lift gold](https://www.fxempire.com/forecasts/article/gold-news-tame-ppi-fails-to-lift-prices-as-rate-hike-fears-persist-1644459)
- [Kiplinger — Nasdaq drops Friday on Nvidia fallout](https://www.kiplinger.com/investing/stocks/nasdaq-drops-friday-on-nvidia-fallout-but-ends-the-week-up-stock-market-today)
- [Mishtalk — PPI further cements a December hike](https://mishtalk.com/economics/produce-price-index-ppi-further-cements-a-december-fed-interest-rate-hike/)
- [Tokenpost — October PPI lifts December hike odds to 91%](https://www.tokenpost.com/news/investing/56743)
- [Al Jazeera — US Treasury warns against rate hikes](https://www.aljazeera.com/economy/2026/11/13/us-treasury-warns-against-rate-hikes-during-us-iran-war-energy-shock)
- [CBS — Inflation isn't going away](https://www.cbsnews.com/news/interest-rates-federal-reserve-inflation/)
- [Babypips — US PPI October 2026](https://www.babypips.com/news/headline-us-ppi-october-2026-producer-prices-annual-inflation-fed)
- [mlq.ai — Treasury yields steepest weekly jump since April 2025](https://mlq.ai/news/treasury-yields-head-for-their-steepest-weekly-jump-since-april-2025-as-gold-sinks-toward-a-one-year-low/)
- [CNBC — Russian crude production rebounds, IEA](https://www.cnbc.com/2026/11/13/russia-oil-exports-iea-diesel-deal.html)
- [BLS — PPI news release](https://www.bls.gov/news.release/ppi.nr0.htm)
