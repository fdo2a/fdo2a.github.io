# research_notes — US 2026-11-16 (월)

수집 기준: 시세·금리·장중·지표는 Actions 커밋 데이터(`data/market_data.json` generated 2026-11-17 08:18 KST, commit 021199b, `report_date` 2026-11-16, `complete: true`, `missing: []`)를 그대로 쓴다. 이 노트의 웹 항목은 WebSearch 결과 요약만으로 확인했다(WebFetch는 이 세션에서 DNS 차단 — investinglive.com 등 원문 열람 불가). 웹 기사 속 수치는 대부분 장중 스냅숏이라 가격의 정본이 아니다.

- 주식 기준일: 2026-11-16 종가 (지수·섹터·종목 모두 동일)
- 금리 기준일: 2Y/5Y/10Y/30Y 모두 네이버 국채 종가 2026-11-16(17:05 ET, 동일 기준일, `spread_2s10s_aligned: true`). FRED 대조 2s10s 27.0bp(`spread_2s10s_fred_bp`)
- FX·원자재: `close_1600_et` 컷
- 수익률 커브 차트: `yield_curve.png` Actions 생성본 사용. 1주 전 비교점의 `week_ago_date`는 2026-11-06(5행 전 — 11/11 채권 휴장과 11/12 네이버 결측 행 구성 때문으로 보이며 값 그대로 둔다)

---

## ① 시황 동인 (장중 스윙 포함)

**결론: 엔비디아 실적(11/17) 전날, 상무부의 AI 칩 원격 접근 제한 규정이 겹치며 AI 하드웨어가 일제히 팔렸다. 장 초반 반등 시도 없이 오후 저점권으로 밀려 마감했다.**

- 정본: 나스닥 24,509.76(-2.492%), S&P 500 7,416.59(-1.919%), 다우 51,608.17(-1.412%), 러셀 2000 2,742.94(-1.704%). 성장(IVW) -2.624% 대 가치(IVE) -1.045%. 섹터는 XLK -3.242%가 최하위, 상승은 필수소비재 +0.271%·유틸리티 +0.182% 둘뿐.
- Reuters 계열 마감 기사("Wall Street ends sharply lower on AI jitters ahead of Nvidia results, Anthropic IPO", MarketScreener·The Standard·Devdiscourse)는 원인으로 ⓐ 젠슨 황 퇴진 뒤 AI 열기 냉각 ⓑ 중국의 최상위 AI 칩 접근을 막는 새 미국 규정 ⓒ 화요일 엔비디아 실적·이번 주 앤스로픽 상장 대기를 들었다. 반도체지수는 약 5% 하락(기사별 4.6~5.3%)으로 보도됐다.
- **BIS 잠정 최종 규정(11/16)**: 중국·마카오 등 D:5 국가 본사 기업에 연산을 제공하는 데이터센터로의 첨단 칩 수출(집계 TPP 1,200만 초과)에 허가 요구, 인도네시아·말레이시아·싱가포르·태국·브라질 수출에 허가 요구('전용 위험이 평소보다 높은' 국가), 해당국에서 영업하는 미국 본사 기업은 예외, 2025년 1월 AI 확산 규정 공식 폐지, 60일 의견 수렴. 보도는 엔비디아·메가스피드 사건에 대한 트럼프 행정부의 첫 정책 대응으로 묘사했다(TechCrunch, Bloomberg, Nextgov, The Next Web). 매체별로 적용 범위 표현이 다르다.
- Benzinga는 상위 19개 미국 상장 기술주 시가총액이 약 9,600억 달러 줄었고 알파벳이 약 1,350억 달러(-3.8%, 장중) 잃었다고 집계하며 새 허가 규정과 연결했다.
- AP(BNN Bloomberg): 엔비디아는 지난주 -13% 뒤 이날 오후 약 -4%, 10월 고점 대비 30% 이상 아래.
- **장중 궤적(intraday.json 30분봉, ET)**: 선물 갭 S&P 500 -0.63%, 나스닥 -1.19%, 러셀 -0.47%로 하락 출발(session.futures). S&P 500 시가 7,513.98 → 09:30 봉 고점 7,515.60(시가 대비 +0.02%) → 14:30 봉 저점 7,400.15(-1.51%) → 종가 7,420.19. 나스닥 저점 13:30 봉(-1.52%), 러셀 13:30 봉(-1.47%). 엔비디아는 09:30 봉에 163.00(시가 대비 +2.51%)까지 올랐다가 13:30 봉 155.01(-2.51%)로 밀렸다 — 장 초반 반등이 꺾인 것이 이날 유일한 전환점이다. 꺾인 시점의 단일 촉매는 확인하지 못했다. 정오(ET) 워시 의장 연설(⑨)과 시간대가 겹치지만, 보도는 연설 효과를 이미 진행 중이던 AI주 매도와 분리하지 못한다.
- 참여도: '소수가 끌어내림'(동일가중이 SPY보다 0.9%p 덜 하락). 세 지수 모두 저점권 마감(종가 위치 S&P 17, 나스닥 14, 러셀 17).
- 펀드 보드: 시장 국면 '횡보'(10/30부터), 오늘 원판정 '단기 약세'(대기 1세션, 확정에 3세션 필요). SPY 52주 고점 대비 -5.02%로 규칙 문턱(-5.0%)을 넘었다. VIX 22.91(2년 백분위 87.7). 가격 기준 판정이며 이익 수정은 반영하지 않는다.
- 해외: 아시아(11/13 기준 행)·유럽 소폭 약세, 'session.global_close' 정렬 '이어감'.
- 기타 뉴스(news/2026-11-16.json 요약 기반, 재검색 안 함): 시진핑·트럼프·푸틴 3자 회담 목요일 선전(APEC 계기, 미중 무역 휴전 1월 만료 연장 논의 가능, CNBC). 캘리포니아주 오픈AI 제소(CNBC). JP모건 체이스 소비자 금융 소프트웨어 장애·주요 은행 접속 장애(사이버 공격 징후 없음, CNBC·PBS). 유나이티드항공 시스템 장애(CNBC). 백악관, 기관의 의회 증언 사전 승인 메모(PBS). CBS, 러트닉 상무부의 수출통제 집행 공백 증언 보도(1년 넘게 Entity List 추가 없음). 중국 10월 소매·산업생산·투자 일제히 부진(ING).

출처: https://www.marketscreener.com/news/wall-street-slumps-on-ai-jitters-ahead-of-nvidia-results-anthropic-ipo-ce785edfdd8ef425 · https://www.thestandard.com.hk/finance/article/348698/Wall-Street-ends-sharply-lower-on-AI-jitters-ahead-of-Nvidia-results-Anthropic-IPO · https://bnnbloomberg.ca/markets/nasdaq/2026/11/16/stocks-decline-on-tech-sell-off-as-concerns-over-the-nvidia-fallout-persist · https://techcrunch.com/2026/11/16/us-tightens-ai-chip-export-controls-to-deter-chinese-companies-from-accessing-compute-remotely/ · https://www.bloomberg.com/news/articles/2026-11-16/us-moves-to-limit-remote-access-to-advanced-ai-chips · https://www.nextgov.com/artificial-intelligence/2026/11/commerce-department-moves-close-ai-chip-loophole/417255/ · https://www.benzinga.com/markets/equities/26/11/63320949/tech-stocks-960-billion-china-ai-chips-remote-access-rule · https://fool.com/coverage/stock-market-today/2026/11/16/stock-market-midday-nov-16-stocks-slide-as-tech-selling-intensifies-across-the-market

**원유**: WTI 85.53(-3.823%), 브렌트 92.35(-3.932%), 천연가스 3.133(-3.243%). 호르무즈 물동량 회복 신호와 국제에너지기구의 4분기 공급 과잉 전망으로 하락했다고 보도됐다(MarineLink, Business Recorder, ADVFN). 이란 해군은 해협 인근에서 유조선이 기뢰에 닿아 불이 났다고 전했다(Asharq Al-Awsat). 장중 WTI 고점 03:30 봉 89.49 → 13:30 봉 저점 85.34. 금 3,854.5(-0.703%), DXY 103.603(+0.186%), 달러/엔 159.482(-0.192%), 달러/원 1,336.11(+0.085%), 유로/달러 1.0999(-0.253%).
출처: https://www.marinelink.com/news/oil-prices-fall-alongside-recovering-544391 · https://english.aawsat.com/business/5341729-oil-prices-fall-expectations-coming-supply-surplus · https://uk.advfn.com/market-news/article/26325/brent-and-wti-oil-prices-fall-as-iea-predicts-global-supply-surplus

## ② 채권·금리 맥락

- 정본(네이버 종가, 동일 기준일 11/16): 2Y 4.827%(-4.7bp), 5Y 4.935%(-4.6bp), 10Y 5.121%(-3.2bp), 30Y 5.468%(-1.3bp). 2s10s 29.4bp(11/13 27.9bp → +1.5bp), 5s30s 53.3bp. 1주 전 비교점(11/06): 2Y 4.522, 5Y 4.648, 10Y 4.859, 30Y 5.260.
- CNBC(11/16): "Treasury prices catch a small bid as stock market weakens and Warsh says AI might 'disappoint'" — 주식 약세와 워시 발언 속 소폭 매수. 기사 시점 10년물 5.131%(금요일 장중 고점 5.174%), 2년물 4.834%(장중 스냅숏). 12월 25bp 인상은 FedWatch로 대부분 반영. 10월 FOMC 의사록 수요일(11/18) 공개.
- 금리 분해(yield_drivers, FRED 동일자 정렬): 10년 명목 변화는 11/13 기준 실질금리 주도(1일 +5bp, 5일 +31bp 모두 실질). 기대인플레 행은 11/16 값이 있다 — 5년 2.25%(-5bp), 10년 2.20%(-4bp), 5y5y 2.15%(-3bp). 실질금리 행은 11/13이 최신이라 오늘 명목 하락의 분해는 할 수 없다(시차 주의). 기대인플레 하락은 같은 날 WTI -3.8%와 방향이 같다. 명목−실질 차이는 위험·유동성 프리미엄도 담는다.
- 크레딧: HY 3.23%(11/13, 5일 -19bp), IG 0.89%(11/13) — 오늘 주식 급락 이전 값이다.
- 입찰: 이번 주 11/18 20년물 160억 달러, 11/19 10년 물가연동 190억 달러(calendar.json). 지난주 10년물(11/10) 응찰배율 2.46(6회 평균 2.60), 30년물(11/12) 2.36(2.44) 모두 '수요 약함'(auctions.json).
출처: https://www.cnbc.com/2026/11/16/treasury-yields-bonds-inflation.html · https://www.cnbc.com/amp/2026/11/13/treasury-yields-fed-rates.html

## ③ 메모리/DRAM 뉴스 (둘째 글 재료)

- 정본: 마이크론 719.02(-7.618%), 웨스턴디지털 280.93(-4.979%), 시게이트 499.00(-5.544%), 엔비디아 156.14(-4.120%), 삼성전자 196,800(-4.466%), SK하이닉스 1,120,000(-7.895%) — 한국 두 종목은 11/16 서울 장(미국 장보다 먼저 마감). MLCC도 급락: 무라타 -6.22%, 삼성전기 -8.19%, 다이요유덴 -9.99%, 야교 -9.00%.
- 원인 보도: 엔비디아 CEO 퇴진 여파와 AI 지출·데이터센터 투자 재평가가 주된 동인(Invezz, StockStory, TipRanks). 연방 판사가 마이크론·삼성·SK하이닉스의 범용 D램 공급 담합 집단소송 기각 공동 신청을 받아들이지 않았다(GuruFocus via TradingView "Micron Stocks Sink Nearly 7% After Judge Lets DRAM Supply Lawsuit Proceed"). 한 보도는 메모리 칩 가격이 AI 수요로 계속 오르는 와중의 하락이라고 짚었고, 소송은 가격·시장 구조 문제이지 수요 붕괴 자체는 아니라는 평가도 있다.
- 샌디스크 -8.58%(정본 movers): 에버코어 목표가 2,500달러에도 하락, 며칠 뒤 8대 1 액면분할 예정(24/7 Wall St.). 번스타인은 AI 하드웨어가 무차별 매도에 휩쓸렸다며 델·샌디스크가 '부당하게 벌을 받았다'고 평가(AI 서버는 델의 1월 결산 회계연도 영업이익의 11.7%)(BigGo Finance 인용).
출처: https://invezz.com/news/2026/11/16/why-micron-and-sandisk-stocks-are-falling-on-monday/ · https://tradingview.com/news/gurufocus:f72125aae094b:0-micron-stocks-sink-nearly-7-after-judge-lets-dram-supply-lawsuit-proceed · https://stockstory.org/us/stocks/nasdaq/mu/news/why-up-down/micron-sk-hynix-and-sandisk-shares-plummet-what-you-need-to-know · https://247wallst.com/investing/2026/11/16/sandisk-falls-7-as-ai-chip-selloff-hits-memory-stocks-despite-evercores-2500-target-micron-and-western-digital-drop-6/ · https://finance.biggo.com/news/cd05cbde-7e00-44dd-a0c1-ba65c2480338

## ④ AI 인프라 뉴스 (둘째 글 재료)

- 정본: 마벨 145.36(-7.272%), 코히어런트 203.43(-6.748%), 루멘텀 546.00(-8.484%), GE 버노바 763.57(-4.926%), 버티브 188.67(-6.631%).
- 광통신: 장 전 루멘텀 -5.18%, 코히어런트 -5.11%, 마벨 -4.64%, 시에나 -4.11%(Tokenpost, 원인 미기재). TIKR는 코히어런트 -9%·루멘텀 -8%를 엔비디아 경영 혼란과 '임시 CEO 콜레트 크레스가 거래(딜) 확대를 억제할 것'이라는 보도로 설명했다(기사 날짜가 요약에서 불명확 — 11/16 기사로 단정하지 않는다). 마벨은 루멘텀을 약 1,150억 달러 전액 주식 거래로 인수 중이라 루멘텀 주가는 마벨 주가에 크게 연동된다(같은 출처, SEC Form 425 다수 존재).
- 전력설비(버티브·GE 버노바): 11/16 고유 재료는 확인되지 않음. 업종 전반 매도와 동반.
출처: https://www.tokenpost.com/news/investing/58167 · https://www.tikr.com/blog/coherent-sinks-9-lumentum-down-8-as-ai-hardware-stocks-slide-on-nvidia-leadership-turmoil

## 움직인 종목의 이유 (movers.json)

등락률은 movers.json 값이 정본이다.

- **g1 반도체 하락** (엔비디아 -4.12%, 마이크론 -7.62%, AMD -5.58%, 인텔 -7.02%, 마벨 -7.27%): 엔비디아 실적 전날 AI 열기 냉각과 BIS의 중국 원격 접근 제한 규정이 겹친 반도체 매도로 보도됐다(Reuters 계열, 반도체지수 약 -5%). 마이크론은 D램 담합 집단소송 진행 판결이 추가 요인으로 거론(GuruFocus). 출처: 위 ①·③ URL.
- **g2 알파벳 -4.07%**: Benzinga는 새 AI 칩 허가 규정과 함께 상위 기술주 시총 약 9,600억 달러 감소의 일부(알파벳 약 1,350억 달러)로 집계했다. 알파벳 고유 재료는 확인되지 않았다. 출처: https://www.benzinga.com/markets/equities/26/11/63320949/tech-stocks-960-billion-china-ai-chips-remote-access-rule
- **g3 P&G +1.90%**: 확인된 재료 없음(필수소비재 +0.271%로 상승한 두 섹터 중 하나라는 정본 사실만 있다).
- **g4 유나이티드헬스 +1.12%**: 확인된 재료 없음.
- **g5 기술 하드웨어·저장장치 하락** (샌디스크 -8.58%, 델 -6.96%, 시게이트 -5.54%): AI 칩 매도가 메모리·저장장치로 번졌다는 보도(24/7 Wall St.), 번스타인의 '무차별 매도' 평가(BigGo). 출처: ③ URL.

## ⑤ 경제지표 4축 표

Actual/Previous는 `econ_indicators.json`(FRED) 값. 11/16 새 FRED 발표 없음(`macro_metrics.headline_releases`·`new_releases` 비어 있음). Forecast는 최근 발표분만 — 이번 세션에서 새로 검색해 확인한 컨센서스는 없다.

| 지표 | Actual | Forecast | Previous | 발표일 |
|---|---|---|---|---|
| PPI 최종수요 MoM (10월) | +0.35% | +0.4% (11/13 리서치 기록, 이번 세션 재검색 안 함) | +1.41% | 2026-11-13 |
| CPI MoM (10월) | +0.35% | 미확인 | +0.65% | 2026-11-10 |
| Core CPI MoM (10월) | +0.30% | 미확인 | +0.33% | 2026-11-10 |
| 신규 실업수당 청구 (11/7 주간) | 200,000 | 미확인 | 191,000 | 2026-11-12 |
| 신규 청구 4주 평균 (11/7 주간) | 195,250 | — | 195,250 | 2026-11-12 |
| 계속 실업수당 청구 (10/31 주간) | 1,697,000 | 미확인 | 1,717,000 | 2026-11-12 |
| 기존주택판매 (10월) | 375만 | 미확인 | 397만 | 2026-11-12 |
| 비농업 고용 (10월) | +165K | 미확인 | +60K | 2026-11-06 |
| 실업률 (10월) | 4.1% | 미확인 | 4.2% | 2026-11-06 |
| 평균시간당임금 MoM (10월) | +0.37% | 미확인 | +0.26% | 2026-11-06 |
| 필라델피아 연은 제조업 (10월, 점수 밖) | 20.9 | — | 37.8 | 기준월 2026-10 |
| PCE 물가 YoY (9월) | 3.65% | — | 3.44% | 기준월 2026-09 |
| Core PCE YoY (9월) | 3.12% | — | 3.03% | 기준월 2026-09 |
| 소매판매 MoM (9월) | +0.77% | — | +1.29% | 기준월 2026-09 |
| 산업생산 MoM (9월) | +0.66% | — | +0.06% | 기준월 2026-09 |
| 미시간대 소비자심리 (9월) | 48.1 | — | 51.7 | 기준월 2026-09 |
| 미시간대 1년 기대인플레 (9월) | 4.6% | — | 4.0% | 기준월 2026-09 |
| 실질 GDP QoQ 연율 (3분기 기준 행 2026-07) | 3.4% | — | 2.2% | 기준월 2026-07 |
| JOLTS 구인 (9월) | 7,523K | — | 7,190K | 기준월 2026-09 |
| 주택착공 (9월) | 1,221K | — | 1,288K | 기준월 2026-09 |

출처: FRED (`data/econ_indicators.json`). 4축 요약(macro_metrics.axis_summary): 고용 '개선·완만'(일곱 중 다섯 개선), 생산·활동 '악화·완만', 소비 '보합·미미', 물가 '재가속·완만'. 성장 점수 0.065, 물가 점수 0.647.

비FRED 지표: 최근 7일 내 발표된 ISM·S&P Global PMI·ADP·CB·NY Fed 기대인플레는 확인하지 못했다(검색 생략·미발견). 11월 엠파이어스테이트 제조업 조사(뉴욕 연은, 통상 11/16 발표)는 검색에서 결과를 찾지 못했다 — 표에서 생략.

다음 일정(calendar.json): 11/17 08:30 소매판매(10월), 09:15 산업생산, 장 마감 뒤 엔비디아 실적(약 16:20 ET, Pepperstone) / 11/18 08:30 주택착공, 13:00 20년물 입찰, FOMC 의사록(CNBC) / 11/19 08:30 실업수당, 13:00 10년 물가연동 입찰 / 11/20 옵션 만기, 10:00 미시간대.

## ⑥ 시장 해석·FedWatch

- 12월 25bp 인상 확률: Reuters 계열 마감 기사에서 한 매체는 95.7%, 다른 매체는 93.7%(CME FedWatch, 관측 시각 불명). 11/13(금) CNBC는 12월 인상 확률 100%, 그중 25bp 86%·50bp 약 14%로 보도. 11/16 CNBC는 '대부분 반영'으로만 서술. 같은 도구라도 관측 시각과 매체가 달라 11/13→11/16 변화를 같은 기준으로 비교할 수 없다. 1월 회의 확률은 확인하지 못했다.
- 시장 해석: 12월 인상이 거의 반영된 상태라 이날 앞단 -4.7bp는 인상 자체가 아니라 인상 이후 경로(또는 50bp 가능성)의 일부가 위험회피 속에 덜어진 것으로 읽을 여지가 있다. 이 해석은 일간 종가와 보도 성격에서 나온 것이며 OIS·선물 경로로 확인하지 않았다.
- 엔비디아 실적 기대(Pepperstone 11/11 프리뷰): 매출 컨센서스 약 1,088.4억 달러(+90.9% YoY), EPS 2.47달러, 회사 가이던스 1,080억 달러 ±2%(중국 데이터센터 연산 매출 0 가정), 옵션 내재 변동 약 ±10.6%. 이는 단일 종목 기대이지 업종 상대 성과의 가격이 아니다.
- 앤스로픽 상장: 11/18 가격 결정·11/19 나스닥('ANT') 거래 예정, 희망가 70~78달러·8.25억 주(FourWeekMBA·IPOX, 규제 승인 조건부, 최종가 미정).
출처: https://www.marketscreener.com/news/wall-street-slumps-on-ai-jitters-ahead-of-nvidia-results-anthropic-ipo-ce785edfdd8ef425 · https://www.cnbc.com/amp/2026/11/13/treasury-yields-fed-rates.html · https://pepperstone.com/en/analysis/navigating-markets/nvidia-q3-2026-earnings-preview-key-numbers-market-impact-trading-insights/ · https://fourweekmba.com/ai-anthropics-ipo-day-by-day-pricing-18-nov-trading-19-nov/ · https://www.ipox.com/ipo-calendar/anthropic

## ⑦ 미확정 항목

- 11/16 FedWatch 최종 수치: 두 값(95.7%/93.7%)의 관측 시각 불명. 1월 회의 확률 미확인.
- 10월 소매판매(11/17) 컨센서스 미확인. CPI·고용·실업수당 컨센서스는 이번 세션에서 재확인하지 않음.
- 11월 엠파이어스테이트 지수 미확인.
- 장중 반등이 09:30 봉 이후 꺾인 단일 촉매 미확인. 워시 연설(12:00 ET) 효과는 보도로도 분리되지 않음.
- P&G·유나이티드헬스 상승 재료 미확인.
- TIKR의 '크레스 딜 억제' 보도 날짜 불명확.
- WebFetch 차단으로 모든 웹 항목은 검색 요약 기반 — 원문 대조 불가.
- 실질금리·크레딧 행은 11/13이 최신(오늘 분해 불가).

## ⑧ 신규 발표 해부

해당 없음 — `macro_metrics.json`의 `headline_releases`가 비어 있고 `releases/index.json`(report_date 2026-11-16, status complete)의 `releases`도 비어 있다.

## ⑨ 연준 이벤트 반응 — 워시 의장 개회사 (chair-speech-20261116, tier 1, fresh)

원문은 `data/fed/chair-speech-20261116.txt`(https://www.federalreserve.gov/newsevents/speech/warsh20261116a.htm)에 전문이 있다. 여기서는 원문에 없는 것만 적는다.

1. **시각과 시장 반응**: 샌프란시스코 연은 일정표상 개회사는 09:00~09:15 PT = **12:00~12:15 ET**(FRBSF 의제). 30분봉상 S&P 500은 09:30 봉 고점 이후 이미 하락 중이었고 저점은 14:30 봉, 나스닥·러셀·엔비디아 저점은 13:30 봉으로 연설 뒤에 나왔다. 그러나 매도는 개장부터 진행 중이었고 보도(mlq.ai 요약)도 연설 효과와 AI주 자체 매도를 분리하지 못한다고 밝혔다. 국채는 CNBC가 금리 소폭 하락 원인의 일부로 워시 발언을 들었다(10년물 종가 -3.2bp). 연설이 스윙을 만들었다고 단정할 근거는 없다.
2. **시장·기관의 해석**: Yahoo Finance는 "연준이 일자리 감소·주식시장 침체를 포함한 AI '초지능' 시나리오를 모델링한다"는 제목으로, CNBC는 "워시가 AI가 '실망'할 수 있다고 말했다"는 각도로 보도했다. 여러 요약은 연설이 금리 변경이나 단기 정책 전망을 제시하지 않았다는 점을 함께 짚었다(Stocktwits, mlq.ai, SBS).
3. **정책 확률 변화**: 연설 전후를 같은 기준으로 비교한 FedWatch 관측을 확보하지 못했다. 마감 기사 기준 12월 25bp 인상 93.7~95.7%(⑥).
출처: https://www.frbsf.org/?p=446248 · https://www.cnbc.com/2026/11/16/treasury-yields-bonds-inflation.html · https://finance.yahoo.com/economy/policy/articles/fed-modeling-ai-super-intelligence-183644026.html · https://mlq.ai/news/warsh-says-ai-could-lift-growth-cost-jobs-or-disappoint-and-hit-stocks-as-the-fed-studies-three-scenarios/

---

## 운용 판단 브리핑

**오늘의 범위**: AI 하드웨어 전반 급락(반도체·메모리·광통신·전력설비), 원유 -3.8%, 국채 강세(불 스티프닝 1.5bp), 방어 업종만 상승. 새 경제지표 없음. 연준 tier-1 이벤트 1건(정책 신호 없는 연설). 자료 공백은 ⑦.

### 질문 1 — AI 하드웨어 일제 하락: 실적 전 위험 축소인가, 수요·규제 재평가인가 (신규 판단)

- **관측**: XLK -3.242% 대 S&P 500 -1.919%(차이 -1.323%p). 메모리 3종 -5~-7.6%, 광통신 -6.7~-8.5%, 전력설비 -4.9~-6.6%, MLCC 아시아 -6~-10%. 상승 섹터는 필수소비재·유틸리티뿐. 참여도 '소수가 끌어내림', 세 지수 저점권 마감. 같은 날 BIS 원격 접근 제한 규정, 실적 하루 전, 앤스로픽 상장 주간.
- **시장 기대(측정 여부)**: 업종 상대 성과에 대한 측정된 기대는 **알 수 없다**. 엔비디아 단일 종목에는 컨센서스 매출 약 1,088.4억 달러, 옵션 내재 ±10.6%가 보도됐다(Pepperstone 11/11). 언론 서사는 '엔비디아 사태·규제가 AI 거래 전반 할인으로 번진다'다(Reuters·AP).
- **우리 해석**: 이분 사건 직전 노출 축소의 성격이 크다. 규정은 미국 본사 사업자를 예외로 두고, 엔비디아 가이던스는 이미 중국 데이터센터 매출 0을 가정했으며, 번스타인은 무차별 매도로 평가했다. 하락 폭이 소수 대형주에 몰렸다.
- **가장 강한 대안**: 허가 대상 5개국(동남아·브라질)의 데이터센터 수요, 지배구조 조사·의회 감독 지속, 임시 CEO 체제의 거래 축소 보도로 수요 전망 자체가 낮아지는 재평가. 11/5 이후 되돌림 실패, 성장 대 가치 격차 확대가 이쪽 관측이다.
- **구별 관측·시한**: 11/16 종가 대비 11/23 종가 XLK − S&P 500 누적 차이. +3.03%p 이상이면 우리 해석 지지, -3.03%p 이하이면 대안 지지, 사이는 판정 불가. 10년물 누적 -20bp 이하이면 메커니즘 판정 불가(금리 하락발 성장주 반등). 촉매: 엔비디아 실적(11/17 16:20 ET경)·가이던스와 중국 설명, 앤스로픽 가격 결정(11/18)·첫 거래(11/19), BIS 규정 후속.
- **투자 관련성(조건부)**: 반도체·AI 인프라 테마의 가격 근거는 이날 **약해졌다**. 실적 뒤 XLK가 시장을 앞서지 못하면 할인이 수요 재평가라는 쪽으로 무게가 실리고, 이는 반도체·광통신·전력설비 테마 전반의 가격 근거를 더 약하게 한다. 실적 뒤 반등이 넓게(메모리·광통신 동반) 나타나면 위험 축소 해석을 지지한다. **지금 새 아이디어는 없다** — 실적이라는 이분 사건(엔비디아 옵션 내재 ±10.6%)을 앞두고 방향을 세울 측정된 기대가 없고, 실적 하루 뒤 확인이 가능하므로 기다리는 쪽이 낫다. 표현 수단을 논한다면 XLK 대 S&P 500 상대 비교가 가장 단순하지만 XLK는 엔비디아·소프트웨어 비중이 커서 하드웨어 바스켓과의 기초 차이가 있다. 스프레드·차입 비용·보유 종목·위험 한도는 제공되지 않았다.
- **원장**: 신규 가설 `us-2026-11-16-ai-hardware-derisking-vs-policy-reprice` (stage insight, watch, test_start 2026-11-17T09:30-05:00, deadline 2026-11-23T16:00-05:00, 기준값 3.028%p). 초안 `.research-drafts/us/2026-11-16/hypothesis_ai_hardware.json`.

### 질문 2 — 주식 급락일 불 스티프닝: 앞단 인상 기대 완화인가, 장기물 기간프리미엄 경로의 연속인가 (기존 판단 첫 세션)

- **관측**: 2Y -4.7bp, 10Y -3.2bp, 30Y -1.3bp → 2s10s 27.9→29.4bp(+1.5bp). 기대인플레 5년 -5bp·10년 -4bp(11/16), WTI -3.8%. 실질금리 11/16 값 없음.
- **기대**: 12월 25bp 93.7~95.7%(Reuters 계열, 관측 시각 불명). 1월 확률 미확인.
- **해석**: 가팔라짐 방향은 11/13 판단과 같지만 경로가 다르다. 11/13 판단은 장기물 기간프리미엄(베어 스티프닝)을 가정했는데 이날은 10년물이 내린 불 스티프닝이다. 결론일까지 이 상태가 이어지면 메커니즘은 판정 불가가 된다.
- **대안**: 11/17 소매판매가 강하면 1월 인상 반영으로 2년물이 더 올라 평탄화 재개.
- **다음 관측**: 11/17 소매판매 뒤 2년물이 4.827%에서 10년물보다 더 오르는지, 11/18 20년물 입찰 수요와 FOMC 의사록. 결론 11/20 종가.
- **투자 관련성**: 현금·단기채 슬리브와 금리 민감 테마(성장주) 판단의 배경 재료이지 독립 아이디어가 아니다. 하루 관측이라 견해 변경 없음.
- **원장**: 리뷰 초안 `review_curve.json` (`us-2026-11-16-ppi-curve-long-end-steepening-vs-front-end-hikes-review1`).

### 이전 판단 변화 (모든 미결 항목)

| 가설 ID | 시한 | 오늘 상태 | 초안 리뷰 |
|---|---|---|---|
| us-2026-11-09-nvidia-governance-discount-persist | 2026-11-16 16:00 ET (오늘) | **결론: 방향 지지, 메커니즘 판정 불가, 종료**. 11/9→11/16 엔비디아 -12.610% 대 S&P -1.766%, 차이 -10.844%p(기준 -3.89%p 이하). 대체 이동 축(AMD·브로드컴)은 경쟁사가 함께 급락해 맞지 않았고, 할인이 업종 전반으로 번져 지배구조 고유 할인과 분리 불가 | review_nvidia.json (…-review4) |
| us-2026-11-10-ai-power-softbank-order-risk | 2026-11-17 16:00 ET | 차이 -2.141%p(±9.28%p 안, 견해 쪽으로 전환), 2Y 누적 +10.0bp(<+25bp) | review_power.json (…-review4) |
| us-2026-11-11-memory-coreweave-financing-relief-vs-beta-bounce | 2026-11-17 16:00 ET | 차이 -7.760%p, 약화 기준 -8.86%p까지 1.10%p. 2Y 누적 +10.0bp. D램 담합 소송 진행 판결은 판정 불가 사유 아님 | review_memory.json (…-review3) |
| us-2026-11-12-energy-iran-duration-vs-headline-bounce | 2026-11-19 16:00 ET | 차이 +1.321%p(±3.18%p 안, 견해 쪽). 그러나 WTI 누적 -3.834%로 상대 강세는 유가가 아닌 시장 하락 덜함에서 나옴 — 유가 경로는 약해지는 중 | review_energy.json (…-review2) |
| us-2026-11-13-ppi-curve-long-end-steepening-vs-front-end-hikes | 2026-11-20 17:05 ET | 2s10s +1.5bp(±5.07bp 안), 10Y 누적 -3.2bp(불 스티프닝 — 메커니즘 조건 위험) | review_curve.json (…-review1) |

`unresolved`는 비어 있다 — 미결 5건 모두 오늘 새 증거로 리뷰 초안이 있다. 사이클 초안 `cycle.json` (`us-2026-11-16-daily-cycle`).

### 입력 필드·증거 연결

- 가격: `market_data.json` indices/sectors/memory/ai_infra/commodities/yields, `data/history/market.jsonl`(이전 종가), `intraday.json`, `movers.json` groups g1~g5, `market_data.session`(participation, tape, futures), `fund_board.json` market_regime·risk.
- 증거(초안 경로): `.research-drafts/us/2026-11-16/evidence/market_data_2026-11-16.json`(sha256 fc637a45…), `intraday_2026-11-16.json`(63805600…), `web_session_2026-11-16.md`(URL·관측 시각 목록).
- 초안은 scratch 복제 원장에 시험 append해 7건 모두 통과(가설 prospective=True, validate 178건). 실제 `research/us`에는 추가하지 않았다(171건 그대로).
- 독자 제약 공백: 보유 종목·유닛 비중·헤지·위험 한도·레버리지 미제공.

---

## 학습·복기

1. **이전 질문** — `posts/2026-11-13.html`(2026-11-13), 학습 블록 `data-research-cycle="us-2026-11-13-daily-cycle"`.
   - 질문: 생산자물가 뒤 커브가 가팔라진 것(2s10s 27.9bp)을 12월 인상이 거의 반영된 뒤 장기물이 커브를 끄는 신호로 보는가, 1월 인상 반영에 따른 앞단 주도 평탄화 재개인가.
   - 원래 시험 조건: 11/13 2s10s 27.9bp 대비 11/20 종가 변화 +5.07bp 이상 지지, -5.07bp 이하 약화, 사이는 판정 불가. 10년물 누적 변화가 음수면 메커니즘 판정 불가.
   - 시한: 2026-11-20 종가. 직전 글이 남긴 다음 확인: "다음 세션(11월 16일)에는 2년물이 4.874%에서 10년물보다 더 오르는지가 커브 판단을 약하게 할 첫 신호이고, 같은 날 종가로 엔비디아 판단의 결론이 나온다."
   - 오늘 결과: 2년물은 오르지 않고 4.827%로 내렸다(-4.7bp) — 약화 신호는 나오지 않았다. 다만 10년물도 내려(-3.2bp) 메커니즘 조건 쪽 위험이 생겼다. 엔비디아 판단은 결론(위 표).
2. **오늘의 실질 질문** — 질문 1(AI 하드웨어 위험 축소 대 수요·규제 재평가). 대안과 구별 증거는 위 브리핑에 있다. 원인은 단정하지 않는다 — 같은 날 규정·실적 대기·연설이 겹쳤고 일간 종가로는 분리할 수 없다.
3. **계산** (재현 가능, 정본 입력)
   - (a) 2s10s: 입력 `market_data.json` yields(네이버 종가, %) 11/16 2Y 4.827, 10Y 5.121; `data/history/market.jsonl` 11/13 2Y 4.874, 10Y 5.153. 공식 (10Y − 2Y) × 100. 결과 11/16 29.4bp(기존 필드 `spread_2s10s_bp` 29.4와 일치), 11/13 27.9bp, 변화 +1.5bp. 10년물 누적 (5.121 − 5.153) × 100 = -3.2bp. 날짜·만기 정의 동일(전 만기 네이버 동일 기준일).
   - (b) 엔비디아 결론: `data/history/market.jsonl` memory.Nvidia 11/9 178.67 → 11/16 156.14 = -12.610%, indices.S&P 500 7,549.94 → 7,416.59 = -1.766%, 차이 -10.844%p.
   - (c) 신규 가설 기준값: 같은 파일 sectors.Technology·indices.S&P 500, 끝점 10/20~11/16의 20개 5행 구간 (XLK 누적 − S&P 누적) 절댓값 평균 = 3.028%p(양수 7개). 11/11(채권 휴장, 주식 개장) 행 포함.
   - (d) 중간 관측: 전력설비(11/10→11/16) 버티브 -2.858%, GE 버노바 -4.199%, 평균 -3.528%, S&P -1.387%, 차이 -2.141%p. 메모리(11/11→11/16) 마이크론 -11.374%, 웨스턴디지털 -10.335%, 시게이트 -9.556%, 평균 -10.422%, S&P -2.662%, 차이 -7.760%p. 에너지(11/12→11/16) XLE -0.995%, S&P -2.316%, 차이 +1.321%p, WTI -3.834%. 2년물 11/10 4.727 → 11/16 4.827 = +10.0bp.
   - 명령: `python3 /tmp/claude-0/-home-user/9555c37e-810b-5663-a153-064371e014eb/scratchpad/calc.py` (b·d·a), `python3 /tmp/claude-0/-home-user/9555c37e-810b-5663-a153-064371e014eb/scratchpad/base.py` (c). 공식: 누적 = (끝/시작 − 1) × 100.
4. **다음 시험** — 11/17: 소매판매(08:30 ET) 뒤 네이버 2년물이 4.827%에서 10년물보다 더 오르면 커브 판단 약화 신호. 같은 날 종가로 전력설비·메모리 판단 결론. 엔비디아 실적(장 마감 뒤)은 신규 판단의 첫 촉매이며 판정은 11/23 종가. 시각 출처: calendar.json(ET), Pepperstone(실적 16:20 ET).
