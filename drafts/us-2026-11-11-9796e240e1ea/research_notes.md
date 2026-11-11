# research_notes — US 모닝브리프 2026-11-11 (수, 재향군인의 날)

- 보고서 거래일: 2026-11-11. 주식 정규장은 열렸고 **미국 국채 현물시장은 휴장**이다(`market_data.json` `yields_bond_holiday`: closed 2026-11-11, curve_date 2026-11-10).
- 데이터 기준일: 주식·섹터·메모리·AI 인프라 = 2026-11-11 종가(Yahoo). FX·원자재 = 2026-11-11 16:00 ET 30분봉 컷(`basis: close_1600_et`). 금리 = **네이버 국채 종가 2026-11-10(전 만기 동일 기준일, 17:05 ET)**, 11/11 신규 금리 관측 없음. FRED 대조(`yields_fred`) = 2026-11-09. 기대인플레(T5YIE·T10YIE·5y5y) = 2026-11-10, 실질금리·HY/IG 스프레드 = 2026-11-09, 10년 기간프리미엄 = 2026-11-06.
- 시세 재수집 없음: Actions run 43112635092, commit 3068353(2026-11-11T22:41:14Z), complete=true, missing=[]. 워크스페이스 `market_data.json`·`news/2026-11-11.json` 은 레포 `data/` 와 바이트 동일 확인.
- `yield_curve.png`: Actions 산출물 그대로 사용(재생성 안 함). 휴장일이라 커브 값은 11/10 종가이며 "오늘" 라벨이 11/10을 가리킨다는 점을 작성 담당이 캡션에서 밝혀야 한다.
- 웹 접근: WebSearch만 가능. WebFetch는 DNS 차단(finance.yahoo.com, www.kiplinger.com ENOTFOUND) — 기사 본문은 열지 못했고 검색 요약만 사용했다. 검색 요약은 `.research-drafts/us/2026-11-11/web_session.md` 에 저장해 원장 증거로 넣었다.

---

## ① 시황 동인 (장중 스윙 포함)

**결론: 상승은 거의 전부 개장 갭에서 나왔다.** 11/10 장 마감 뒤 코어위브(CRWV) 3분기 실적(매출 예상 상회, 연간 가이던스 상향)이 AI 설비 투자 자금 조달 우려를 덜었다는 것이 주요 매체의 공통 설명이다(Reuters via MarketScreener "Stocks gain as CoreWeave eases worries; dollar strengthens", AP via Virginia Business, Kiplinger, Yahoo Finance 라이브블로그).

- 지수(정본): 나스닥 25,466.19(+1.60%), S&P 500 7,619.38(+1.31%), 다우 52,486.49(+0.49%), 러셀 2000 2,846.26(+0.88%). 성장(IVW) +1.64% 대 가치(IVE) +0.89%. VIX 17.49(-1.97pt).
- 섹터: 기술(XLK) +3.23%, 에너지 +1.86%, 산업재 +1.33%, 커뮤니케이션 +0.78%, 금융 +0.58%, 필수소비재 +0.46%, 소재 +0.32%, 유틸리티 +0.21%, 헬스케어 +0.04%, 부동산 +0.02%, 임의소비재 -0.05%.
- 개장 갭(session.futures.gap): S&P 500 +0.87%, 나스닥 +1.54%, 러셀 +0.74%. 선물 방향 "상승 출발".
- 장중(intraday.json 30분봉): 세 지수 모두 **09:30 봉이 저점**(시가 대비 S&P -0.19%, 나스닥 -0.49%, 러셀 -0.34%), 고점은 S&P·나스닥 13:30 봉(시가 대비 +0.80%, +0.77%), 러셀 12:30 봉. 이후 밀려 종가는 고점 대비 S&P -0.38%, 나스닥 -0.72%. **시가→종가는 나스닥 +0.05%, S&P +0.41%** — 일간 상승의 대부분이 갭이다. 종가 위치(tape): S&P 61, 나스닥 43, 러셀 69, 모두 "중단 마감".
- 참여도(session.participation): band "소수가 끌어올림", gap_pp -0.52(동일가중이 SPY +1.32%보다 0.52%p 약함). 상승 폭이 소수 대형 반도체에 몰렸다.
- 오후 되밀림의 원인은 확인된 보도가 없다(검색으로 특정하지 못함). 추측하지 않는다.
- 장 마감 뒤: 엔비디아 시간외 -3% 이상 — NYT가 젠슨 황 CEO와 회사 임원 간 두 번째 혼외 관계 의혹을 보도했다(CNBC 22:31 UTC, news 15-ai). 정규장 숫자에는 반영되지 않았다.
- 해외: 닛케이 +2.87%(11/10), 항셍 +0.44%, DAX +1.20%(11/11), 유로스톡스50 +1.04%.
- 정치·정책(news 요약): 캐나다 대사 관세 비용 경고(CNBC), 미시시피 상원 콜롬 4,400표 차 우세(CNBC), 민주당 의회의 행정부 기업 지분 조사 가능성(CNBC), 의회의 젠슨 황 사임 요구와 11/18 증언 요구(하원 3개 위원장 11/4 서한, CNBC). 이란 갈리바프 의장 "호르무즈는 전쟁 이전으로 돌아가지 않는다", 7개항 종전 조건 미국 응답 대기(CNBC).

## ② 채권·금리 맥락

**결론: 11/11은 금리 관측이 없는 날이다. 금리 숫자는 11/10 소비자물가 충격 종가 그대로다.**

- 네이버 11/10 종가(정본): 2년 4.727%(+18.0bp), 5년 4.805%(+14.6bp), 10년 4.983%(+12.1bp), 30년 5.349%(+9.3bp). 2s10s 25.6bp(`spread_2s10s_aligned: true`, 동일 기준일), 5s30s 54.4bp. 1주 전(11/3) 대비 2년 +11.3bp, 5년 +6.2bp, 10년 +3.3bp, 30년 +2.5bp.
- FRED 대조(11/9): 2년 4.56, 10년 4.88 → 2s10s 32.0bp(기준일 다름, 비교용).
- 동인 행(yield_drivers): 5년 기대인플레 2.25%(11/10, 1일 0bp, 5일 -14bp), 10년 기대인플레 2.20%(-2bp, 5일 -10bp), 5y5y 2.15%(-4bp). 실질 5년 2.42%(11/9, +7bp). 10년 기간프리미엄 0.87%(11/6). HY 3.34%(11/9, -8bp), IG 0.91%. 3개월 T-bill 4.06%, SOFR 3.88%(11/9). **이 행들은 11/9~11/10 관측이라 11/11 사건을 설명하지 못한다.**
- 보도: Yahoo 라이브블로그는 11/10 2년물 상승을 2025년 4월 이후 최대 일간 상승으로 전했다. ING FX Daily(11/11 07:50 UTC, news 23-insight)는 CPI 뒤 단기물 +20bp, 2s10s 7bp 평탄화, "베어 플래트닝이 달러를 지지"로 설명했다.
- 입찰: 11/10 10년물 420억 달러, 응찰배율 2.46(6회 평균 2.60), 간접 61.2%(평균 76.6%), 딜러 9.8% — 수요 약함(auctions.json). 11/12 13:00 ET 30년물 250억 달러, 4·8·17주물 입찰 예정(calendar.json).
- `price_context.moves` 의 10Y(^TNX) +0.015pp, 30Y +0.006pp는 Yahoo 지수값으로 현물 휴장일 관측이 아니다 — 금리 변화로 쓰지 않는다.

## ③ 메모리/DRAM 뉴스 (둘째 글 「뉴스·산업 브리프」 재료)

- 정본: 마이크론 811.30(+11.89%), 웨스턴디지털 313.31(+8.34%), 시게이트 551.72(+9.99%), 엔비디아 173.73(+2.87%), 삼성전자 206,000원(+3.57%, KRX 11/11), SK하이닉스 1,277,000원(+5.36%, KRX 11/11). movers: 샌디스크 977.69(+13.69%).
- 원인: 코어위브 실적 뒤 메모리·저장장치가 함께 올랐다(Benzinga "Tech Stocks Add $500 Billion on CoreWeave Results": 마이크론 +10% 시가총액 약 820억 달러 증가, SK하이닉스 미국 상장분 SKHY +8.7%, 샌디스크 +13.2% — 게재 시점 값; TIKR; Invezz 11/11; Seeking Alpha via TradingView). 프리마켓에서 이미 마이크론 약 +6%, 샌디스크 +6% 이상(TipRanks).
- KRX 세션(11/11 KST)은 코어위브 발표(11/10 장 마감 뒤 = 11/11 06:00 KST 무렵) 이후에 열렸다. 같은 재료를 먼저 반영한 것으로 볼 수 있으나 KR 세션의 원인 보도는 확인하지 않았다.
- 바스켓 위치(계산, data/history/market.jsonl): 11/4 종가 대비 마이크론 +2.02%, 웨스턴디지털 -3.25%, 시게이트 -0.96% — 선거 뒤 급락 직전 수준까지 되돌아왔다. 같은 기간 엔비디아 -13.19%, S&P 500 -0.90%.
- MLCC: 무라타 +3.47%, 다이요유덴 +7.32%, 삼성전기 +4.65%(news 01~03-mlcc는 밸류에이션 기사, 당일 재료 아님).
- 메모리 가격·계약 관련 당일 신규 뉴스는 찾지 못했다.

## ④ AI 인프라 뉴스 (둘째 글 재료)

- 정본: 마벨 168.80(+9.33%), 코히런트 234.51(+9.25%), 루멘텀 648.06(+10.67%), GE 버노바 808.24(+1.41%), 버티브 206.51(+6.33%).
- 코어위브: 11/11 +24.71%(2025년 4월 이후 최고 일간 상승률, CNBC news 8-ai; 다른 보도는 19~24.7%로 시점별 차이). 3분기 매출 37억 달러(+168%), 2026년 매출 가이던스 130억~133억 달러, 조정 영업이익 12.75억~13.75억 달러. 이달 초 CDS 11% 초과 → 저금리 자산담보 조달 경로 제시, 신규 자산담보부채 7~7.5% 예상(인트레이터 CEO), 2027년까지 모회사 무담보채 미발행 방침(CNBC news 7·8-ai). 네비어스 +15.44%, 애플라이드 디지털 +7.37%(CNBC).
- 앤스로픽: 다음 주 나스닥 상장 예정(CNBC news 7-ai).
- 광학(루멘텀·코히런트·마벨)·전력(버티브·GE 버노바)의 종목별 11/11 재료는 검색으로 찾지 못했다 — 반도체·AI 하드웨어 전반 반등과 같은 날이라는 것만 확인된다.
- 소프트뱅크 오하이오 발전설비 선급금 손상(11/10) 후속 보도는 찾지 못했다.

## ⑤ 경제지표 4축 표

11/11은 연방 공휴일로 새 발표가 없다(`macro_metrics.json` `new_releases`·`headline_releases` 빈 목록). Actual/Previous는 `econ_indicators.json`(FRED), 출처 'FRED'. Forecast는 최근 발표분 중 원장에 출처가 남은 것만 적는다.

| 축 | 지표 | Actual | Forecast | Previous | 발표일(기준월) |
|---|---|---|---|---|---|
| 물가 | CPI MoM | 0.35% | 0.3%(다우존스, CNBC — 11/10 회차 원장) | 0.65% | 2026-11-10 (10월) |
| 물가 | Core CPI MoM | 0.30% | 0.2%(다우존스, CNBC — 11/10 회차 원장) | 0.33% | 2026-11-10 (10월) |
| 물가 | PPI Final Demand MoM | 1.34% | — | 0.47% | 9월분 |
| 물가 | PCE Price Index YoY | 3.65% | — | 3.44% | 9월분 |
| 물가 | Core PCE YoY | 3.12% | — | 3.03% | 9월분 |
| 물가 | Michigan 1-Yr Inflation Exp | 4.6% | — | 4.0% | 9월분 |
| 고용 | Nonfarm Payrolls | +16.5만 | +5.9만(다우존스 — 11/6 회차 원장) | +6.0만 | 2026-11-06 (10월) |
| 고용 | Unemployment Rate | 4.1% | — | 4.2% | 2026-11-06 (10월) |
| 고용 | Avg Hourly Earnings MoM | 0.37% | — | 0.26% | 2026-11-06 (10월) |
| 고용 | Initial Jobless Claims | 18.9만 | — | 19.5만 | 주간(10/31 주) |
| 고용 | Initial Claims 4-wk MA | 19.475만 | — | 19.7만 | 주간(10/31 주) |
| 고용 | Continuing Claims | 171.8만 | — | 169.5만 | 주간(10/24 주) |
| 고용 | JOLTS Job Openings | 752.3만 | — | 719.0만 | 9월분 |
| 활동 | Real GDP QoQ (ann.) | 3.4% | — | 2.2% | 3분기 |
| 활동 | Industrial Production MoM | 0.66% | — | 0.06% | 9월분 |
| 활동 | Durable Goods MoM | 1.91% | — | 0.14% | 9월분 |
| 활동 | Factory Orders MoM | 1.84% | — | 0.33% | 9월분 |
| 활동 | Construction Spending MoM | -1.85% | — | 1.98% | 9월분 |
| 활동 | Housing Starts | 122.1만 | — | 128.8만 | 9월분 |
| 활동 | New Home Sales | 67.6만 | — | 68.0만 | 9월분 |
| 활동 | Existing Home Sales | 399만 | — | 393만 | 9월분 |
| 활동 | Trade Balance | -1,050.5억 달러 | — | -1,057.4억 달러 | 9월분 |
| 활동 | Philly Fed Mfg(점수 밖) | 20.9 | — | 37.8 | 10월분 |
| 소비 | Retail Sales MoM | 0.77% | — | 1.29% | 9월분 |
| 소비 | Michigan Sentiment | 48.1 | — | 51.7 | 9월분 |

- 축 요약(macro_metrics.axis_summary): 고용 "개선·완만"(일곱 중 다섯 개선), 생산·활동 "악화·완만". 
- 비FRED(ISM·S&P Global·ADP·CB·NY Fed): 최근 7일 안 새 발표가 없어 생략.
- 다음 발표(calendar.json): 11/12 08:30 ET 신규 실업수당, 10:00 기존주택 판매, 13:00 30년물 입찰 / 11/13 08:30 PPI / 11/17 08:30 소매판매, 09:15 산업생산 / 11/18 주택착공 / 11/19 실업수당 / 11/20 지수 옵션 만기. 엔비디아 실적 11/17 장 마감 뒤(원장 11/9 가설 출처).

## ⑥ 시장 해석·FedWatch

- 12월(12/8~9 FOMC) 인상 확률(CME FedWatch, 보도치, **시각·출처마다 다름**): CPI 뒤 25bp 85~90.5%, 50bp 9.5~15.3%, 동결 0%(Steve Hanke X: 25bp 90.5% ← 전날 84.0%, 50bp 9.5% ← 0%; bloomingbit: 50bp 11% ← 1.1%; PANews 50bp 15.3%; Investing.com 88%; Seoul Economic Daily "100%"(25+50 합산)). CNBC(11/11 16:49 UTC, news 6-macro)는 선물시장이 12월 인상을 사실상 확실시, 50bp 확률 15%, 1월까지 4.25~4.5% 도달 확률 60%로 전했다. 현재 기준금리 3.75~4.00%(9월 인상, 10월 동결).
- 연준 발언(11/11, CNBC·Seeking Alpha): 굴스비 "경계선에서 불안한(borderline disturbing) 보고서", 서비스 물가·관세 지속 우려. 월러(발표 전 영국 연설): 근원 0.3% 안팎이면 12월 인상, 그 이상이면 50bp 검토(미시는 0.25%p 인상 지지·그 이상이면 0.5%p 검토로 전함 — 보도 간 문구 차이). 로건 "25bp 2차례 더", 폴슨 "점진적 긴축".
- ING(11/11): 베어 플래트닝 → 달러 강세, DXY 102.85~103.00 저항 재시험, EUR/USD 1.10~1.15 하단 시험 전망.
- **11/11 하루에 FedWatch가 어떻게 움직였는지는 같은 상품의 전후 스냅샷을 확보하지 못했다.** 국채 휴장일이라 정책 경로 변화를 가격으로 확인할 수 없다.
- FX(정본): DXY 102.929(+0.66%, moves.band "큼"), USD/JPY 159.85(+0.66%), EUR/USD 1.109(-0.67%), USD/KRW 1,338.26(-0.28%). 달러 강세 원인: Reuters 헤드라인 "dollar strengthens"(MarketScreener)와 ING의 정책 경로 해석 외에 당일 원인 보도는 확인하지 못했다. 같은 주 유로존 인플레이션 4%(CNBC, 해외 필터로 제외된 기사 제목)는 유로 강세 재료인데도 유로가 약했다 — 이 대조는 관측일 뿐 원인 판정이 아니다. USD/JPY 고점 12:00 봉 159.938, 160 바로 아래.
- 원자재(정본): WTI 86.33(-0.01%; 장중 10:00 봉 고점 88.74 뒤 되밀림), 브렌트 92.49(+0.67%), 천연가스 3.247(-1.84%), 금 3,992.1(-1.16%; 02:00 봉 고점 4,074.7 → 15:00 봉 저점 3,989.6). 유가·금 당일 원인 보도는 찾지 못했다(검색 결과가 8월 이전 기사뿐). 이란 갈리바프 발언(CNBC 21:03 UTC)은 정규장 이후 게재.

## ⑦ 미확정 항목

1. 11/11 국채 금리: 휴장으로 관측 없음 — 결측이 아니라 휴장. 11/12 네이버 종가가 첫 신규 관측.
2. 오후(13:30 이후) 지수 되밀림의 원인: 보도 미확인.
3. 아마존 -1.74%, 델 +11.75%, 반도체 장비(AMAT·LRCX·KLAC)의 종목별 원인: 날짜가 맞는 보도 미확인(아래 g3·g4·g5).
4. 달러 +0.66%·금 -1.16%·브렌트 +0.67%의 당일 원인: 헤드라인 수준 외 미확인.
5. FedWatch 11/11 장중 변화: 같은 상품 전후 스냅샷 없음.
6. 필라델피아 반도체 지수 정확한 종가 등락률: 보도는 약 7~8%(검색 요약), 정본 데이터 없음 — 본문에 숫자로 쓰지 말 것.
7. 엔비디아 Baird 하향(Neutral) 목표가·근거: Yahoo 라이브블로그 요약에만 있고 본문 미확인.
8. 기사 본문 접근 불가(WebFetch DNS 차단): 모든 웹 근거는 검색 요약 수준.

## ⑧ 신규 발표 해부

해당 없음 — `macro_metrics.json` `headline_releases` 가 빈 목록이고 `releases/index.json` 도 `releases: []`(status complete). 11/11 연방 공휴일로 새 발표 없음. 10월 CPI(11/10) 해부는 11/10 회차에서 끝났다.

## ⑨ 연준 이벤트 반응

해당 없음 — `fed/events.json` `events: []`(fresh tier-1 이벤트 없음). 연준 인사 발언은 ⑥에 보도 출처로만 적었다.

## 움직인 종목의 이유 (movers.json, 등락률은 파일 값이 정본)

- **g1 반도체 상승**(엔비디아 +2.87%, 마이크론 +11.89%, AMD +7.32%, 인텔 +7.52%, 마벨 +9.33%, 모놀리식 파워 +8.92%): 코어위브 3분기 실적·가이던스 상향이 AI 수요·자금 조달 우려를 덜며 반도체·메모리가 동반 상승(Reuters via MarketScreener, Benzinga, Seeking Alpha via TradingView). 엔비디아는 직전 2세션 시가총액 약 4,300억 달러 감소 뒤 반등, 같은 날 Baird가 Neutral로 하향(Yahoo 라이브블로그). 인텔·AMD·모놀리식 파워 고유 재료는 확인된 것 없음.
- **g2 시스템 소프트웨어 하락**(마이크로소프트 -2.26%): 앤스로픽의 업무용 도구(Claude Sheets 등) 출시 뒤 이틀째 하락으로 보도(Seeking Alpha "Microsoft tumbles as Anthropic unveils office tools ahead of IPO", TradingKey 11/11, Benzinga 인용 KuCoin: 수요일 -2.34% 게재 시점). 첫 하락은 11/10.
- **g3 종합 소매 하락**(아마존 -1.74%): 확인된 재료 없음.
- **g4 하드웨어·저장장치 상승**(샌디스크 +13.69%, 시게이트 +9.99%, 델 +11.75%, 웨스턴디지털 +8.34%, 슈퍼마이크로 +9.5%): 샌디스크·메모리·저장장치는 코어위브 실적 뒤 동반 급등으로 보도(Benzinga, Invezz 11/11, TIKR). 델·슈퍼마이크로의 11/11 종목별 보도는 확인된 것 없음.
- **g5 반도체 장비 상승**(어플라이드 머티리얼즈 +6.05%, 램리서치 +6.07%, KLA +5.24%): 반도체 전반 반등과 같은 날이라는 것 외에 종목별 재료는 확인된 것 없음.

---

## 운용 판단 브리핑

**넓은 커버리지와 자료 공백.** 하루의 기록은 ①~⑦에 있다. 공백: 금리 신규 관측 없음(휴장), 기사 본문 미열람, 옵션 내재변동성·포지셔닝·펀드 흐름 없음, FedWatch 동일 상품 전후 스냅샷 없음. 독자의 보유·비중·헤지 정보는 받지 않았다.

### 핵심 질문 1 — 코어위브 실적 뒤 메모리·저장장치 급등은 AI 고객 자금 조달 위험의 재평가인가, 휴장일의 고베타 되돌림인가 (테마: 반도체·AI 하드웨어)

- **관측(11/10 대비).** 마이크론·웨스턴디지털·시게이트 단순평균 +10.070%, S&P 500 +1.309%, 하루 차이 +8.761%p(data/history/market.jsonl). 11/4 대비 세 종목은 +2.02%·-3.25%·-0.96%로 선거 뒤 급락 직전 수준까지 회복했고, 엔비디아는 -13.19%로 회복하지 못했다. 지수 상승은 대부분 갭(나스닥 시가→종가 +0.05%)이고 참여도는 "소수가 끌어올림".
- **기대(측정치 아님).** 보도 서사: 코어위브 매출·가이던스 상향과 자산담보 조달 경로(7~7.5%), 2027년까지 무담보채 미발행이 AI 설비 투자 고객의 자금 조달 우려를 덜었다(Reuters·AP·CNBC·Benzinga). 가격 기반 기대(옵션·포지셔닝)는 확보하지 못했다 → 기대 격차는 모른다.
- **해석.** 11/5 급락의 서사 중 하나가 AI 고객의 자금 조달·수익성 의문이었다(11/5 가설의 대안). 코어위브가 그 의문에 직접 답한 첫 대형 고객 실적이라, 메모리 할인의 일부가 걷힌 것으로 읽힌다. 이 경우 국채시장이 다시 열려도 상대 강세가 유지된다.
- **대안.** 휴장일에 금리 신호가 비면서 직전 급락폭이 큰 고베타 종목이 되돌려졌다. 갭으로 오르고 장중에는 고점에서 밀렸으며 참여가 좁았다는 점이 이 대안 쪽 관측이다. 11/12 금리가 11/10 충격을 이어가면(2년물 추가 상승) 메모리가 다시 S&P 500보다 약해진다.
- **가를 관측과 시한.** 11/11 종가 대비 11/17 종가 메모리 3종 평균 − S&P 500. 기준 ±8.86%p(최근 20개 4세션 구간 절댓값 평균). 촉매: 11/12 국채 재개장·30년물 입찰, 11/13 PPI, 11/17 소매판매. 11/17 장 마감 뒤 엔비디아 실적은 구간 밖으로 두었다. 네이버 2년물이 11/10 대비 11/17까지 ±25bp를 넘게 움직이면 메커니즘은 판정 불가.
- **투자 연관성(조건부).** 반도체·메모리 테마 후보의 가격 근거가 "고객 자금 조달 위험 완화"로 강화되는지의 문제다. 지지되면 메모리 테마의 가격 근거가 강화되고, 약화되면 11/11 반등은 금리 국면 속 일회성 되돌림으로 본다. 지금 단계는 관측이며 새 아이디어는 없다. 표현 수단을 논한다면 메모리 3종 대 S&P 500 상대 성과이지만 변동성 차이가 커 상대 비교의 베이시스 위험이 크고, 스프레드·차입·옵션 비용 자료가 없다.
- **원장.** 신규 가설 `us-2026-11-11-memory-coreweave-financing-relief-vs-beta-bounce`.

### 핵심 질문 2 — 엔비디아 지배구조 할인은 반등일에도 유지되는가 (테마: 반도체, 기업 고유 위험)

- **관측.** 엔비디아 +2.87%로 S&P 500(+1.31%)을 앞섰지만 마이크론(+11.89%)·AMD(+7.32%)에 크게 못 미쳤다. 11/9 대비 누적 엔비디아 -2.765%, S&P 500 +0.920%, 차이 -3.685%p — 11/10의 -5.090%p에서 지지 기준(-3.89%p 이하) 안쪽으로 돌아왔다. 장 마감 뒤 NYT의 두 번째 혼외 관계 의혹 보도로 시간외 -3% 이상(CNBC), Baird Neutral 하향(Yahoo), 의회 사임 요구·11/18 증언 요구(CNBC).
- **해석.** 반등일에도 같은 반도체 안에서 엔비디아가 뒤처졌고, 장 마감 뒤 같은 계열 재료가 추가됐다. 지배구조 할인 견해는 유지된다. 다만 정본 누적값은 지지 기준 안쪽으로 돌아왔으므로 판정은 11/16 종가에서 한다.
- **대안.** 하루 회전 매도의 되돌림: 정규장 +2.87%와 장중 저점 대비 회복. 시간외 하락은 정본 종가가 아니므로 11/12 종가로 확인해야 한다.
- **원장.** 검토 `us-2026-11-11-nvidia-governance-discount-persist-review1`(open).

### 기존 판단 변화 (모두 실행 포지션 없음)

- `us-2026-11-05-ai-chip-crash-degross-vs-rerating`: 중간값 XLK +7.378% − S&P 500 +3.612% = **+3.765%p로 지지 기준(+3.38%p 이상)을 처음 넘었다.** 2년물 누적 +25.0bp는 제외 기준(±25bp 초과) 경계 그대로 — 휴장이라 11/12 네이버 종가가 정한다. 검토 `us-2026-11-11-ai-chip-crash-degross-vs-rerating-review1`(open). 판정 11/12 종가.
- `us-2026-11-06-payrolls-front-end-flattening-vs-riskoff`: 휴장으로 새 관측 없음. 2s10s 25.6bp(11/6 대비 -8.1bp) 유지 → cycle unresolved.
- `us-2026-11-09-nvidia-governance-discount-persist`: 위 질문 2. 검토 open.
- `us-2026-11-10-ai-power-softbank-order-risk`: 첫 시험 세션 버티브 +6.328%, GE 버노바 +1.405%, 평균 +3.867%, S&P 500 +1.309%, 차이 **+2.558%p**(판정 구간 ±9.28%p 안). 대안이 예고한 "코어위브 같은 AI 수요 확인 재료"가 첫날 나왔고 방향은 대안 쪽이다. 소프트뱅크 후속 보도는 없다. 검토 `us-2026-11-11-ai-power-softbank-order-risk-review1`(open). 판정 11/17 종가.

### 실행 제약·독자 제약

- 금리 휴장으로 주식 반등과 금리 경로의 관계를 같은 날 확인할 수 없다. 11/12에 금리·입찰·실업수당이 한꺼번에 나온다.
- 상대 성과 표현은 변동성 차이를 보정하지 않는다. 차입·스프레드·옵션 비용 입력이 없어 비용을 0으로 볼 수 없다.
- 독자의 보유·트렌드 유닛 비중·리스크 한도는 알 수 없다. 편입·비중 권고는 하지 않는다.

---

## 학습·복기

### 이전 질문 (posts/2026-11-10.html, 학습 블록만)

- 경로·날짜: `/home/user/fdo2a.github.io/posts/2026-11-10.html`, 2026-11-10, `data-research-cycle="us-2026-11-10-daily-cycle"`.
- 학습 질문(다음 확인): "11월 12일에는 2년물이 4.727%에서 더 오르는지와 성장·가치 격차가 함께 벌어지는지를 본다. 2년물이 오르는데 성장주가 따라 약해지면 업종 회전이 금리를 흡수했다는 설명을, 격차가 평평하면 인상이 이미 반영돼 있었다는 설명을 뒷받침한다."
- 원래 시험 조건·시한: 11/12 네이버 2년물(4.727% 기준)과 성장(IVW)−가치(IVE) 격차, 11/12 종가.
- 오늘 상태: **시한 전, 판정 대상 아님.** 11/11은 채권 휴장이라 2년물 조건을 관측할 수 없다. 참고로 11/11 IVW +1.64% − IVE +0.89% = +0.75%p로 성장이 앞섰지만, 금리 신규 관측이 없는 날이라 질문의 조건(2년물 상승과 동시 관측)에 해당하지 않는다.
- 원장 열린 가설 4건과 시한: 11/5 반도체(11/12 16:00 ET), 11/6 2s10s(11/13 17:05 ET), 11/9 엔비디아(11/16 16:00 ET), 11/10 전력설비(11/17 16:00 ET).

### 오늘의 질문

- 관측: 국채 휴장일, 코어위브 실적 뒤 메모리 3종 평균 +10.070% 대 S&P 500 +1.309%(하루 차이 +8.761%p), 지수 상승 대부분 갭, 참여 좁음.
- 가설: AI 고객 자금 조달 위험 완화에 따른 메모리 할인 축소(재평가) → 11/17까지 상대 강세 유지.
- 대안: 휴장일 고베타 되돌림 → 11/12 금리 재개 뒤 되밀림.
- 가르는 증거: 11/11→11/17 메모리 3종 평균 − S&P 500 누적 차이(±8.86%p), 같은 기간 네이버 2년물(11/10 4.727% 기준) 누적 변화.

### 계산 (재현 가능)

1. 오늘 하루 차이. 입력 `data/history/market.jsonl` `memory.Micron / Western Digital / Seagate`, `indices["S&P 500"]`, 행 2026-11-10·2026-11-11. 값: 마이크론 725.110→811.300, 웨스턴디지털 289.200→313.310, 시게이트 501.620→551.720, S&P 500 7,520.930→7,619.380. 공식: 평균((b/a−1)×100) − (S&P b/a−1)×100. 결과: 평균 +10.070%, S&P 500 +1.309%, **차이 +8.761%p**.
2. 기준값. 같은 파일에서 2026-10-15~2026-11-11에 끝나는 20개 4행 구간(시작 10/9~11/5)의 같은 차이 절댓값 평균 = **8.856%p**(→ 8.86%p).
3. 열린 가설 중간값(같은 파일, 정본 종가): 11/5→11/11 XLK +7.378%, S&P 500 +3.612%, 차이 +3.765%p, 2년물 4.477→4.727 = +25.0bp / 11/6→11/11 2s10s 33.7→25.6 = -8.1bp(11/11 금리 행은 11/10 값 그대로) / 11/9→11/11 엔비디아 178.670→173.730 = -2.765%, S&P 500 +0.920%, 차이 -3.685%p / 11/10→11/11 버티브 +6.328%, GE 버노바 +1.405%, 평균 +3.867%, S&P 500 +1.309%, 차이 +2.558%p.

실행 명령(레포 루트에서):
```
python3 - <<'EOF'
import json
rows=sorted([json.loads(l) for l in open('data/history/market.jsonl')],key=lambda r:r['report_date'])
K=['Micron','Western Digital','Seagate']
f=lambda a,b:(b/a-1)*100
a,b=rows[-2],rows[-1]
m=sum(f(a['memory'][k],b['memory'][k]) for k in K)/3; s=f(a['indices']['S&P 500'],b['indices']['S&P 500'])
print(a['report_date'],b['report_date'],round(m,3),round(s,3),round(m-s,3))
v=[]
for i in range(len(rows)-20,len(rows)):
    a,b=rows[i-4],rows[i]
    v.append(abs(sum(f(a['memory'][k],b['memory'][k]) for k in K)/3-f(a['indices']['S&P 500'],b['indices']['S&P 500'])))
print(round(sum(v)/20,3))
EOF
```
출력: `2026-11-10 2026-11-11 10.07 1.309 8.761` / `8.856`.

날짜·정의 점검: 주식은 모두 Yahoo 일간 종가, 같은 행 날짜. 2년물은 네이버 17:05 ET 종가(11/11 행 = 11/10 값, 휴장). 4행 구간은 4거래일 수익률이다(히스토리 행은 주식 거래일 기준).

### 다음 시험

- 11/12(목): 네이버 2년물이 4.727%에서 어느 쪽으로 움직이는지(11/5 가설의 제외 경계 ±25bp와 이전 학습 질문이 같은 관측을 쓴다), 30년물 입찰(13:00 ET) 간접 비중, 메모리 3종이 11/11 종가를 지키는지. 2년물이 오르는데 메모리가 S&P 500보다 강하면 재평가 쪽, 함께 약하면 고베타 되돌림 쪽 관측이다.
- 시한: 메모리 가설 11/17 16:00 ET 종가(calendar.json·원장 기준, ET).

### 원장 참조

- cycle: `us-2026-11-11-daily-cycle`
- 신규 가설: `us-2026-11-11-memory-coreweave-financing-relief-vs-beta-bounce`
- 검토: `us-2026-11-11-ai-chip-crash-degross-vs-rerating-review1`, `us-2026-11-11-nvidia-governance-discount-persist-review1`, `us-2026-11-11-ai-power-softbank-order-risk-review1`
- unresolved: `us-2026-11-06-payrolls-front-end-flattening-vs-riskoff`(휴장, 새 관측 없음)

---

## 출처 (웹)

- [Yahoo Finance live: chip stock rally rekindles AI trade (11/11)](https://finance.yahoo.com/markets/live/stock-market-today-wednesday-november-11-dow-sp-500-nasdaq-nvidia-treasurys-veterans-day-140638547.html)
- [Kiplinger: Nasdaq Adds 400 Points as CoreWeave Earnings Revive the AI Trade](https://www.kiplinger.com/investing/stocks/nasdaq-adds-400-points-after-coreweave-earnings-stock-market-today)
- [Virginia Business (AP): Stocks end higher as CoreWeave results ease AI spending worries](https://virginiabusiness.com/us-stocks-rise-coreweave-earnings-ai-spending/)
- [MarketScreener (Reuters): Stocks gain as CoreWeave eases worries; dollar strengthens](https://www.marketscreener.com/news/stocks-gain-as-coreweave-eases-worries-dollar-strengthens-ce785edbde80f62d)
- [Kitco off-the-wire 11/11](http://www.kitco.com/news/off-the-wire/2026-11-11/stocks-climb-coreweave-results-ease-ai-spending-concerns)
- [Benzinga: Tech Stocks Add $500 Billion on CoreWeave Results](https://www.benzinga.com/markets/earnings/26/11/63148039/tech-stocks-500-billion-coreweave-results-ai-rally)
- [TIKR: Micron Soars 10%, SK hynix Up 9%](https://www.tikr.com/blog/micron-soars-10-sk-hynix-up-9-as-coreweave-raises-outlook-on-a-breakout-quarter)
- [Invezz 11/11: Micron, Sandisk, SK Hynix surge after CoreWeave](https://invezz.com/sg/news/2026/11/11/micron-sandisk-sk-hynix-stocks-surge-after-coreweave-earnings-heres-why/)
- [TipRanks: AI chip stocks premarket 11/11](https://www.tipranks.com/news/why-are-ai-chip-stocks-nvidia-micron-and-sk-hynix-surging-in-premarket-today-november-11)
- [TradingView (Seeking Alpha): Chip, memory stocks rally after CoreWeave results](https://www.tradingview.com/news/seekingalpha:a64d6c214094b:0-chip-memory-stocks-rally-after-coreweave-results-ease-ai-demand-worries/)
- [Seeking Alpha: Microsoft tumbles as Anthropic unveils office tools](https://seekingalpha.com/news/4669998-microsoft-tumbles-as-anthropic-unveils-office-tools-ahead-of-ipo)
- [TradingKey 11/11: Microsoft shares slip](https://www.tradingkey.com/analysis/stocks/us-stocks/262300289-microsoft-shares-slip-anthropic-office-tools-525-support-november-11-2026-tradingkey)
- [KuCoin flash: Microsoft falls 2.34%](https://www.kucoin.com/news/flash/microsoft-stock-falls-2-34-amid-ai-infrastructure-concerns-and-anthropic-s-new-tools)
- [Investing.com: Fed hike odds 88% after hot CPI](https://www.investing.com/news/economy-news/fed-rate-hike-odds-in-december-at-88-after-hot-cpi-cme-fedwatch-5017585)
- [Steve Hanke on X: FedWatch 90.5% / 9.5%](https://x.com/steve_hanke/status/2120269014018715871)
- [bloomingbit: 50bp odds 11% from 1.1%](https://en.bloomingbit.io/feed/news/124114)
- [PANews: 50bp 15.3%](https://panews.io/articles/01a1c5c2-28c6-7302-95cc-4235cb4a361e)
- [Seoul Economic Daily 11/11](https://en.sedaily.com/world/2026/11/11/december-rate-hike-odds-hit-100-percent-after-hot-us)
- [Seeking Alpha: Goolsbee 'borderline disturbing', Paulson gradual](https://seekingalpha.com/news/4670490-fed-rate-outlook-inflation-goolsbee-paulson)
- [Babypips 11/11: Hot October CPI puts bigger hike on the table](https://www.babypips.com/analysis/headline-us-cpi-october-fed-hike-december-2026-11-11)
- 수집 잡 요약(data/news/2026-11-11.json): CNBC 코어위브·엔비디아 NYT 보도·굴스비·젠슨 황 의회·호르무즈·관세, ING FX Daily, Mish.
