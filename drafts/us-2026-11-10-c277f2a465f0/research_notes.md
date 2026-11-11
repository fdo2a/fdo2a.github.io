# research_notes.md — US 모닝브리프 2026-11-10 (화) 세션

- 시세·금리·장중·지표의 정본은 워크스페이스에 커밋본으로 복사된 파일이다(`market_data.json` report_date 2026-11-10, complete=true, missing=[]; generated 2026-11-11 08:18 KST, 커밋 c83610b). 이 노트는 그 수치를 다시 수집하지 않았고, 웹 리서치(원인·해석·기대치)만 더한다.
- 데이터 기준일: 주식·업종 ETF·종목 = 2026-11-10 종가(Yahoo). 금리 = 네이버 국채 종가 2026-11-10(17:05 ET, 전 만기 동일 기준일, `spread_2s10s_aligned: true`). FRED 대조용 `yields_fred` 는 2026-11-09 기준(1영업일 랙). FX·원자재 = `close_1600_et`(뉴욕 16:00 ET 30분봉 컷).
- 차트: `yield_curve.png` 는 Actions 산출물을 그대로 사용(오늘 11/10 vs 1주 전 11/03, 네이버 전 만기 동일 기준일). 재생성하지 않았다.
- 웹 환경: WebFetch 는 DNS 차단(aa.com.tr ENOTFOUND)으로 쓰지 못했다. 웹 근거는 전부 WebSearch 결과 요약이며, 원 URL은 각 항목과 증거 파일(`research/us/evidence/ba92a972…`, 원본 `.research-drafts/us/2026-11-10/web_session.md`)에 있다. 웹 요약끼리 종가·등락률이 다를 때는 정본 파일 값을 쓴다.

---

## ① 시황 동인 (장중 스윙 포함)

**한 줄**: 10월 소비자물가가 헤드라인·근원 모두 예상을 0.1%p 웃돌고(전월 대비 0.4%·0.3% vs 다우존스 예상 0.3%·0.2%) 연준 인사들이 12월 인상, 나아가 50bp까지 거론하면서 2년물이 급등했다. 주식은 엔비디아 이틀째 급락(-5.474%)과 기술주 약세로 소폭 내렸지만, 금리 충격치고는 지수 낙폭이 작았다.

- 정본 종가: S&P 500 7,520.93(-0.384%), 나스닥 25,065.875(-0.742%), 다우 52,231.891(-0.301%), 러셀 2000 2,821.375(-0.684%). 성장(IVW) -0.804%, 가치(IVE) +0.117%. `price_context.moves` 기준 S&P 500 밴드는 「미미」(-0.42배), 나스닥·러셀 「보통」, **10년물(+2.32배)·30년물(+2.11배)·DXY(+1.82배)·금(-1.95배)은 「큼」**. 오늘 가격의 무게중심은 주식이 아니라 금리·달러·금이다.
- 업종: 기술(XLK) -1.153%가 최하위, 금융(XLF) +0.517%·에너지(XLE) +0.436%·커뮤니케이션(XLC) +0.373%·헬스케어(XLV) +0.292%가 위. 24/7 Wall St.도 「기술 부진, 금융·커뮤니케이션 주도」로 요약했다([24/7 Wall St.](https://247wallst.com/cards/us-stocks-closed-lower-technology-lags-while-financials-and-communication-servic-spy-market-explainer-01m73qyjzbtvqd6e7bax73kfa0)).
- 보도된 동인: Reuters(Yahoo 게재)는 「뜨거운 물가와 연준 발언이 금리 우려를 키우며 월가가 후퇴했다」고 전했고, 시장이 12월 최소 25bp 인상을 가격에 넣었다(전날 84%)고 보도됐다. 같은 보도는 2년물 상승폭이 2025년 4월 이후 최대라고 했다([Yahoo/Reuters](https://finance.yahoo.com/markets/stocks/articles/p-500-dow-futures-climb-102635174.html), [Star Advertiser/AP](https://www.staradvertiser.com/2026/11/10/breaking-news/wall-street-falls-as-hot-inflation-fuels-fed-rate-hike-fears/)). Yahoo 라이브는 「핫 CPI가 인상 확률을 키우고 엔비디아가 급락」으로 제목을 달았다([Yahoo live](https://finance.yahoo.com/markets/article/stock-market-today-tuesday-november-10-dow-sp-500-nasdaq-inflation-data-cpi-090627830.html)).
- **장중 궤적(intraday.json 30분봉, 정본)**: S&P 500 시가 7,513.09 → 10:00 봉 고가 7,543.92(시가 대비 +0.41%) → 12:30 봉 저가 7,470.43(-0.57%) → 종가 봉 7,522.27로 저점에서 회복. 나스닥도 10:00 고가 25,286.38(+0.95%) → 12:30 저가 24,816.69(-0.92%) → 25,069.79. 러셀은 10:30 저가. 엔비디아는 13:00 봉 고가 178.67 뒤 15:00 봉 저가 165.89(시가 대비 -4.65%)로 **오후에 밀렸다** — 지수 회복과 반대 방향.
  - 개장: S&P 500이 개장 직후 -0.49%, 10년물 4.96%로 보도됐다([JournalArta](https://journalarta.com/en/2026/11/10/stock-market-today-sp-500-slips-0-49-and-nasdaq-0-61-at-the-open-as-10-year-yield-climbs-to-4-96/)). 30분봉 시가와 10:00 고가 사이 반등의 원인을 짚은 보도는 찾지 못했다.
  - 정오 저점 → 오후 회복: 「S&P 500·다우가 정오 손실 일부를 되찾았다」, 14:07 10년물 4.996%라는 보도가 있으나 회복을 특정 뉴스(13:00 10년물 입찰 포함)와 연결한 보도는 찾지 못했다([mlq.ai](https://mlq.ai/news/us-stocks-fall-and-treasury-yields-jump-at-the-open-after-hot-october-cpi/), [TheStreet](https://thestreet.com/stock-market-today/stock-market-today-dow-jones-sp-500-nasdaq-updates-nov-10-2026)). TheStreet Pro의 「강한 10년물 입찰 뒤 손실 축소」 기사는 34일 전 기사로 확인돼 오늘 재료가 아니다. → 오후 회복 원인은 **미확정**.
- 유가: 브렌트가 장중 8월 이후 처음 90달러 아래(저가 89.16달러)로 내렸다가 회복했다. 트럼프 대통령의 「이란 전쟁이 머지않아 끝날 수 있다」 발언이 재료로 보도됐다(CNBC, 수집 요약 `news/2026-11-10.json`). 정본 16:00 ET 컷: WTI 86.34(-0.827%), 브렌트 91.87(-1.023%). CNBC 기사 속 마감가(브렌트 91.49·WTI 86.04)는 시각 기준이 달라 쓰지 않는다. 천연가스 3.308(+3.149%).
- 달러·엔·금: DXY 102.256(+0.571%), USD/JPY 158.801(+0.578%, 14:30 봉 고가 158.85), EUR/USD 1.117(-0.536%), USD/KRW 1,342.03(+0.125%). Bloomberg는 달러 지수의 9월 이후 최대 상승을 전했다([Bloomberg](https://www.bloomberg.com/news/articles/2026-11-10/dollar-set-for-best-day-since-september-as-cpi-lifts-hike-bets)). 금 4,038.8(-2.696%): 00:30 봉 고가 4,136.4 → 11:30 봉 저가 4,020.8. Reuters는 금 하락을 CPI가 달러·금리를 끌어올린 결과로 설명했다([Mining.com/Reuters](https://www.mining.com/web/gold-price-falls-nearly-3-as-cpi-tops-forecasts-lifting-dollar-and-yields/)).
- 정치: 백악관은 중간선거의 물가 반발에도 관세를 밀고 나가겠다고 했다(CNBC). 하원은 헤그세스 국방장관 탄핵 절차 표결을 시작했고, 공화당은 하원 원내대표에 짐 조던, 상원 원내대표에 존 튠을 뽑았다(CNBC). 뉴욕 연은 가계부채 보고서: 3분기 HELOC 잔액 +230억 달러로 2005년 이후 최대 증가(CNBC). 이 재료들을 지수 움직임과 연결한 보도는 찾지 못했다.
- 장 마감 뒤: 코어위브 3분기 매출 36.6억 달러(+168%, 예상 35.4억), 연간 매출 전망 약 133억 달러로 상향, 수주잔고 약 1,325억 달러. 시간외 등락은 +11%에서 -4.5%까지 흔들린 뒤 약 +2%로 보도됐다([CNBC](https://www.cnbc.com/2026/11/10/coreweave-crwv-q3-earnings-report-2026.html), [CNBC movers](https://cnbc.com/2026/11/10/stock-market-movers-live-updates.html), [Stocktwits](https://stocktwits.com/news-articles/markets/equity/crwv-stock-climbs-6-after-hours-as-132-b-revenue-backlog-reinforces-ai-compute-demand-nbis-iren-tick-higher/cNGuwW0R9JL)). 회사채 금리 15~16% 부담은 여전하다고 CNBC가 전했다.

## ② 채권·금리 맥락

- 정본(네이버 17:05 ET, 2026-11-10 동일 기준일): 2Y 4.727%(+18.0bp), 5Y 4.805%(+14.6bp), 10Y 4.983%(+12.1bp), 30Y 5.349%(+9.3bp). 2s10s 25.6bp(전날 31.5bp), 5s30s 54.4bp. 1주 전(11/03) 대비: 2Y +11.3bp, 5Y +6.2bp, 10Y +3.3bp, 30Y +2.5bp(차트 `yield_curve.png`). FRED 대조값(`yields_fred`, 11/09): 2Y 4.56, 10Y 4.88, 2s10s 32bp — 오늘 값이 아니다.
- **베어 플래트닝**: 단기물이 가장 많이 올랐다. 웹 보도도 2년물 +17~19bp(4.73% 부근), 10년물 장중 5% 돌파 뒤 4.98~4.99% 마감, 2s10s 32→25bp 평탄화로 같은 그림이다([cappnotes](https://cappnotes.substack.com/p/closing-look-tuesday-november-10), [Investing.com](https://www.investing.com/news/economy-news/us-treasury-yields-surge-as-hot-cpi-revives-fed-tightening-bets-93CH-5016707)).
- 연준 발언(모두 11/10):
  - 월러 이사: 10월 물가가 나아져도 12월 8~9일 회의에서 25bp 인상을 지지하고, 더 뜨거우면 50bp 인상을 검토해야 한다고 했다([Yahoo](https://finance.yahoo.com/economy/article/feds-waller-leans-toward-quarter-point-rate-hike-in-december-open-to-50-basis-points-090000672.html), [investingLive](https://investinglive.com/central-banks/fed-s-waller-says-a-half-point-rate-hike-in-december-may-be-needed-if-core-cpi-comes-in-hot/)). investingLive는 월러가 발표 전 0.3%를 더 큰 인상의 문턱으로 짚었다고 전했다.
  - 로건 댈러스 연은 총재: 「최소 두 차례 25bp 인상」이 필요하며 빠르게 움직여야 할 수 있다고 했다(Reuters via [Investing.com](https://investing.com/news/economy-news/feds-logan-calls-for-two-more-rate-hikes-possibly-rapidly-5016235)).
  - 슈미드 캔자스시티 연은 총재: 현 금리가 「상당히 완화적」이라고 했다([Seeking Alpha](https://seekingalpha.com/news/4670010-kansas-city-feds-schmid-sees-no-major-economic-restriction-from-policy)).
  - BofA 이코노미스트는 10월 동결이 정책 실수로 보인다고 했다(CNBC CPI 기사 요약).
- **10년물 입찰(auctions.json 정본)**: 420억 달러 신규 발행(직전 10/07 390억 달러), 응찰률 2.46배(최근 6회 평균 2.60, -0.14), 간접 61.2%(평균 76.6%, -15.4%p), 직접 29.0%, 딜러 9.8%(평균 7.5%, +2.3%p), 낙찰 금리 5.02%, 판정 「수요 약함」. WI 금리 원천이 없어 테일은 미산출(`tail_status: no_wi_source`). 웹 보도: 딜러 인수 약 10%로 5월 이후 최대([cappnotes](https://cappnotes.substack.com/p/closing-look-tuesday-november-10)). 다음 입찰: 30년물 250억 달러 11/12 13:00 ET.
  - 해석상 주의: 장기물 수요가 약했는데도 커브는 평탄해졌다. 장기물 공급 부담이 오늘 커브를 지배했다면 가팔라졌어야 하므로, 오늘 커브는 공급보다 정책 경로가 지배했다고 보는 편이 관측과 맞는다. 다만 입찰 시각(13:00) 전후 금리 반응은 일간 종가만으로 측정할 수 없다.
- 실질금리·기대인플레(`yield_drivers`, FRED 랙): 10년 실질 2.66%(11/09, 5일 +4bp), 5년 기대인플레 2.25%(11/10, 5일 -14bp). 이 값들은 각자의 관측 창을 설명하며 오늘 CPI 충격을 설명하는 데 쓰지 않는다.
- 11/11(수) 재향군인의 날: 채권시장 휴장, 주식시장 개장. 금리 판단의 다음 관측은 11/12 네이버 종가다.

## ③ 메모리/DRAM 뉴스 (둘째 글 「뉴스·산업 브리프」 재료)

- 정본: 마이크론 725.11(-1.097%), 웨스턴디지털 289.20(-0.200%), 시게이트 501.62(-0.893%). 한국(11/10 KST 종가): 삼성전자 198,900원(+4.739%), SK하이닉스 1,212,000원(+6.690%).
- 한국: 코스피 5,239.13(+4.39%)로 마감했고 9거래일 만에 매수 사이드카가 발동됐다. 원인은 11/9 미국 반도체 반등(필라델피아 반도체 +6.85%)과 유가 하락으로 보도됐다([Seoul Economic Daily](https://en.sedaily.com/market/2026/11/10/samsung-sk-hynix-lead-kospi-44-percent-rebound-past-5200), [FinanceFeeds](https://financefeeds.com/kospi-jumps-4-4-as-samsung-and-sk-hynix-rebound-after-buy-sidecar/)). 한국 종가는 미국 11/9 세션의 전이이며 미국 11/10 세션과 동시 상관이 아니다.
- 미국 메모리 3사의 11/10 고유 재료는 찾지 못했다. 직전 맥락: 11/9 마이크론 +6%, 시게이트·웨스턴디지털 +11%; 마이크론 351.6억 달러 자사주 매입이 12/9 시작([24/7 Wall St. 11/9](https://247wallst.com/investing/2026/11/09/micron-rises-6-as-bulls-tout-its-bargain-valuation-and-buyback-firepower-seagate-and-western-digital-jump-11/)). 카운터포인트는 11/5 메모리 가격이 여전히 오른다고 했다([FourWeekMBA](https://fourweekmba.com/ai-memory-stocks-fell-up-to-26-while-dram-prices-kept-rising/)).
- MLCC(정본 `mlcc`): 무라타 +6.91%, 다이요유덴 +4.74%, 삼성전기 +4.63%(모두 11/10 아시아 종가). 무라타의 데이터센터 수요 기반 중장기 전망 상향 기사가 수집 요약에 있다(Yahoo/Simply Wall St 계열, 투자 판단 결론 없음).

## ④ AI 인프라 뉴스 (둘째 글 재료)

- 정본: 마벨 154.39(-0.136%), 코히어런트 214.66(-4.676%), 루멘텀 585.57(-1.776%), GE 버노바 797.04(-3.895%), 버티브 194.22(-3.118%).
- **소프트뱅크 손상**: 소프트뱅크는 미국 AI 데이터센터(오하이오 파이크 카운티 포함)용 발전설비 환불 불가 선급금과 계약 수정에 37억 달러 손상을 반영했고(약 28.5억 선급금 + 8.8억 계약 수정·정산으로 보도), 회계 2분기 약 70억 달러 순손실을 냈다. CFO는 오하이오를 축소하지 않으며 프로젝트가 조달 방식을 포함해 「철저한 재검토」를 받고 있고 손실은 일시적이라고 했다. 향후 구매에서 최대 21억 달러 리베이트 권리가 있다고 했다([TipRanks](https://www.tipranks.com/news/softbank-group-sftby-posts-q2-loss-after-3-7b-data-center-writedown), [Quartz](https://qz.com/softbank-quarterly-loss-us-data-center-write-down-111026), [Yahoo](https://finance.yahoo.com/technology/ai/articles/softbank-logs-7-billion-loss-065612363.html)). 오하이오 부지는 오픈AI와 8GW·20년 임대 계약이 있다고 보도됐다.
- 반응: GE 버노바는 개장 직후 최대 9.8% 내렸고([Seeking Alpha](https://seekingalpha.com/news/4669839-ge-vernova-falls-nearly-10-percent-after-softbank-revises-ai-data-center-plans)), Reuters는 6% 넘는 하락을 뜨거운 CPI·엔비디아 조사·오하이오 문제와 함께 전했다([Galveston/Reuters](https://galvnews.com/news_reuters/business/nvidia-selloff-deepens-adding-to-ai-jitters/article_95f0511c-4756-585a-a687-740be05f8dfb.html)). 24/7 Wall St.는 「AI 전력주가 월요일 반등을 되돌렸다」(버티브 -4%, 퀀타 -2%)고 했다([24/7](https://247wallst.com/investing/2026/11/10/ge-vernova-declines-6-as-ai-power-stocks-give-back-mondays-rally-vertiv-drops-4-quanta-services-slides-2/), [TIKR](https://www.tikr.com/blog/ge-vernova-falls-4-as-softbanks-ohio-data-center-undergoes-a-thorough-reassessment)). 정본 종가는 GE 버노바 -3.895%로 장중 저점에서 상당 부분 회복했다(장중 시각별 수치는 intraday.json 대상이 아니어서 미확인).
- 코히어런트: ChartMill이 -5.77%(212.21)를 전했으나 세션 날짜가 불분명하다. 고유 재료는 찾지 못했다.
- 버티브·GE 버노바의 11/5~11/9 기업 발표: GE 버노바의 독일 풍력 터빈 3기 수주(11/9, 조건 미공개) 외에 실적·가이던스·인수합병 발표는 찾지 못했다([Benzinga](https://benzinga.com/trading-ideas/movers/26/11/63028775/ge-vernova-lands-wind-turbine-order-with-20-year-service-deal), [Motley Fool](https://www.fool.com/investing/2026/11/10/ge-vernova-vertiv-and-bloom-energy-just-lost-10-to/)).
- 코어위브(①) 실적은 장 마감 뒤라 오늘 종가에 들어 있지 않다.

## 움직인 종목의 이유 (movers.json `groups`, 등락률은 파일 값이 정본)

| id | 묶음 | 정본 등락 | 원인(출처) |
|---|---|---|---|
| g1 | 반도체·하락 — 엔비디아(NVDA) | -5.47%, 168.89 | 이틀째 하락. 황 CEO의 직원 대상 사과 이메일과 중국 간첩 지목 인물과의 불륜 의혹, 이사회 독립 조사, 산호세 연방법원 증권 집단소송(11/9 제기, 집단 기간 2025-10-09~2026-11-08), 슈머 원내대표의 국가안보 비판. 시가총액 장중 4조 달러 하회. 야크빌 아이브스는 유임 가능성 85%로 봤다([CNBC](https://www.cnbc.com/2026/11/10/nvidia-nvda-jensen-huang-affair-chinese-spy.html), [Yahoo](https://finance.yahoo.com/markets/stocks/articles/nvidia-190-billion-stock-rout-195036390.html), [24/7](https://247wallst.com/investing/2026/11/10/nvidia-and-jensen-huang-just-got-sued-by-shareholders-over-his-ties-to-a-suspected-spy/)) |
| g2 | 시스템 소프트웨어·하락 — 마이크로소프트(MSFT) | -2.2%, 533.16 | 앤트로픽이 스프레드시트 앱을 포함한 Claude 업무용 도구를 내놓는다는 Bloomberg 보도·발표가 엑셀·오피스 경쟁 우려로 읽혔다([StreetInsider](https://www.streetinsider.com/Investing/Microsoft+stock+falls+as+Anthropic+takes+aim+at+Excel+and+workplace+software/27322131.html), [Invezz](https://invezz.com/sg/news/2026/11/10/why-is-microsoft-stock-falling-2percent-today/)) |
| g3 | 반도체·상승 — 브로드컴(AVGO) | +3.91%, 331.98 | 엔비디아 악재 속 경쟁사로의 이동 연장(11/9 +8.78%에 이어). BofA는 AMD·브로드컴·마벨이 엔비디아의 혼란에서 이득을 볼 수 있다고 했다([Yahoo](https://finance.yahoo.com/markets/stocks/articles/stock-market-today-nov-10-223502212.html), [24/7](https://247wallst.com/investing/2026/11/10/nvidia-falls-4-as-board-probe-of-jensen-huang-weighs-on-shares-amd-and-broadcom-gain-3/)) |
| g4 | 종합 소매·상승 — 아마존(AMZN) | +1.48%, 270.87 | **확인된 재료 없음(11/10 기준)**. 검색은 11/9 재료(JPMorgan 애널리스트 포커스 리스트 편입, AWS 성장)만 돌려줬다([Invezz 11/9](https://invezz.com/sg/news/2026/11/09/why-amazon-shares-are-up-over-3percent-on-monday/)). 링의 드론·로봇 공개(CNBC 11/10)를 주가와 연결한 보도는 찾지 못했다 |
| g5 | 바이오·하락 — 모더나(MRNA) | -6.75%, 250.83 | 11/6 3분기 실적 뒤 급등과 11/9 52주 신고가(280.80) 뒤 차익 실현·밸류에이션 부담으로 보도됐다. TradingKey는 호흡기 백신 판매 전개에 대한 회의를 들었다([Investing.com](https://www.investing.com/news/stock-market-news/why-is-moderna-stock-sliding-today-93CH-5016154), [MarketBeat](https://www.marketbeat.com/instant-alerts/price-moderna-nasdaq-mrna-shares-down-68-time-to-sell-2026-11-10/), [TradingKey](https://www.tradingkey.com/news/market-movers/262298992-market-movers-mrna-20261110)). 단일 촉매는 확인되지 않았다 |

## ⑤ 경제지표 4축 표

Actual/Previous = `econ_indicators.json`(FRED 확정치, 출처 'FRED'). Forecast·발표일은 최근 발표분만 웹. 오래된 기준월 지표는 Forecast 공란, 발표일은 기준월로 갈음.

| 축 | 지표 | Actual | Forecast | Previous | 발표일 / 기준월 |
|---|---|---|---|---|---|
| 물가 | CPI MoM | 0.35% (BLS 발표 반올림 0.4%) | 0.3% (다우존스, [CNBC](https://www.cnbc.com/2026/11/10/cpi-inflation-report-october-2026.html)) | 0.65% | 2026-11-10 / 2026-10 |
| 물가 | Core CPI MoM | 0.30% | 0.2% (다우존스, 같은 출처) | 0.33% | 2026-11-10 / 2026-10 |
| 물가 | PPI Final Demand MoM | 1.34% | — | 0.47% | 기준월 2026-09 |
| 물가 | PCE Price Index YoY | 3.65% | — | 3.44% | 기준월 2026-09 |
| 물가 | Core PCE YoY | 3.12% | — | 3.03% | 기준월 2026-09 |
| 물가 | Michigan 1-Yr Inflation Exp | 4.6 | — | 4.0 | 기준월 2026-09 |
| 고용 | Nonfarm Payrolls (chg, 천 명) | 165 | 59 (다우존스, 11/6 게시 보고서 인용) | 60 | 2026-11-06 / 2026-10 |
| 고용 | Unemployment Rate | 4.1% | — | 4.2% | 2026-11-06 / 2026-10 |
| 고용 | Avg Hourly Earnings MoM | 0.37% | — | 0.26% | 2026-11-06 / 2026-10 |
| 고용 | Initial Jobless Claims | 189,000 | — | 195,000 | 주간, 기준 2026-10-31 |
| 고용 | Initial Claims 4-wk MA | 194,750 | — | 197,000 | 기준 2026-10-31 |
| 고용 | Continuing Jobless Claims | 1,718,000 | — | 1,695,000 | 기준 2026-10-24 |
| 고용 | JOLTS Job Openings (천) | 7,523 | — | 7,190 | 기준월 2026-09 |
| 활동 | Real GDP QoQ ann. | 3.4% | — | 2.2% | 기준 2026Q3(관측일 2026-07-01) |
| 활동 | Industrial Production MoM | 0.66% | — | 0.06% | 기준월 2026-09 |
| 활동 | Durable Goods Orders MoM | 1.91% | — | 0.14% | 기준월 2026-09 |
| 활동 | Factory Orders MoM | 1.84% | — | 0.33% | 기준월 2026-09 |
| 활동 | Construction Spending MoM | -1.85% | — | 1.98% | 기준월 2026-09 |
| 활동 | Housing Starts (천) | 1,221 | — | 1,288 | 기준월 2026-09 |
| 활동 | New Home Sales (천) | 676 | — | 680 | 기준월 2026-09 |
| 활동 | Existing Home Sales | 3,990,000 | — | 3,930,000 | 기준월 2026-09 |
| 활동 | Trade Balance (십억 달러) | -105.05 | — | -105.74 | 기준월 2026-09 |
| 활동 | Philly Fed Manufacturing (해부만, 점수 밖) | 20.9 | — | 37.8 | 기준월 2026-10 |
| 소비 | Retail Sales MoM | 0.77% | — | 1.29% | 기준월 2026-09 |
| 소비 | Michigan Consumer Sentiment | 48.1 | — | 51.7 | 기준월 2026-09 |
| 비FRED | ISM 서비스업 PMI(10월) | 54.5 | 54.8 | — | 2026-11-04 (11/4·11/6 게시 보고서 표 값 재사용, 이번 회차 재검색 안 함) |
| 비FRED | ADP 민간고용(10월) | +86K | +75K | +86K(게시 표 값 그대로; 직전치 동일 표기는 원 표의 값) | 2026-11-04 (게시 보고서 표 값 재사용) |

- `macro_metrics.json`: 국면 산출 상태 ok, 성장 점수 0.1, 물가 점수 0.451. CPI 발표문(tier 1)의 `momentum_z` CPI MoM 1.863, Core CPI MoM 1.273.
- FRED 계산치 0.35%와 BLS 발표 0.4%의 차이는 반올림 차이다(지수 수준에서 계산). 본문 헤드라인은 BLS 발표치 0.4%·0.3%를 쓰고, 표의 Actual은 FRED 값이다.
- ISM 제조업(11/2 발표)은 7일 창 밖이라 생략. S&P Global PMI·CB 소비자신뢰·뉴욕 연은 1년 기대인플레는 최근 7일 내 발표를 확인하지 못해 생략.

## ⑥ 시장 해석·FedWatch

- 컨센서스 대비: 헤드라인·근원 모두 +0.1%p 상회(다우존스 0.3%·0.2%, CNBC). ING는 「뜨거운 물가가 12월 인상 명분을 강화했다」고 했고, 중고차 -1.2%에도 의료 상품·교통 서비스(0.8%)·주거비(0.3%)가 물가를 끌어올렸다고 짚었다(ING THINK, 수집 요약). AP 계열 보도는 3개월 연속 예상 상회라고 했다([Star Advertiser](https://www.staradvertiser.com/2026/11/10/breaking-news/u-s-inflation-rises-more-than-expected-for-3rd-straight-month/)). 발표 전 단일 기관 예측: TD 헤드라인 0.30%, 근원 0.21%([FXStreet](https://www.fxstreet.com/news/united-states-october-inflation-seen-cooling-td-securities-202610191339)).
- **FedWatch·정책 확률(출처마다 다름, 같은 상품 동시점 비교 아님)**:
  - 발표 전: 12월 인상 확률 84%(11/9, Reuters via Yahoo).
  - 발표 뒤: 25bp 89%·50bp 11%(CME FedWatch, [IBTimes](https://www.ibtimes.com/hotter-cpi-raises-odds-december-fed-rate-hike-3809599)); 50bp 확률 0%→10.5%(Reuters via [Euronext](https://live.euronext.com/en/financial-news/us-yields-rise-stocks-fall-inflation-data-boosts-odds-larger-december-rate-hike)); 50bp 14%(한 출처); 인상 100%·50bp 1.4%([MPA](https://www.mpamag.com/us/mortgage-industry/industry-trends/fed-rate-hike-odds-hit-100-as-waller-floats-bigger-december-move/596880)); Kalshi 약 97%([cappnotes](https://cappnotes.substack.com/p/closing-look-tuesday-november-10)).
  - 공통 결론: 12월 25bp 인상은 사실상 완전 반영 쪽으로 이동했고, 50bp가 0%에서 대략 10~14%로 생겼다. 정확한 수치는 관측 시각이 달라 하나로 확정하지 않는다. OIS 경로는 확보하지 못했다.
- 시장 서사: investingLive는 「핫 CPI가 더 큰 인상을 테이블에 올렸다」, 2년물 주도·달러 전면 강세·금은 약세로 정리했다([investingLive](https://investinglive.com/news/investinglive-americas-fx-news-wrap-10-nov-it-s-a-wrap-hot-us-cpi-puts-a-bigger-fed-hike-in-play/)). Axios는 「인상(들)에 대비하라」([Axios](https://www.axios.com/2026/11/10/federal-reserve-rate-hikes)).
- 주식 반응의 크기: 2년물이 2025년 4월 이후 최대로 오른 날 S&P 500은 -0.384%(밴드 「미미」), VIX는 -0.46pt였다(`price_context`). 지수 하락의 상당 부분은 엔비디아 하나에 몰렸고(정본 g1), 금융·에너지·헬스케어는 올랐다. 금리 충격이 주식 전반의 할인율 매도로 번졌다는 증거는 이날 약하다.

## ⑦ 미확정 항목

1. 장중 10:00 고점 이후 12:30 저점까지 하락, 12:30 이후 회복의 원인 — 특정 뉴스와 연결한 보도를 찾지 못했다. 13:00 10년물 입찰과의 연결은 보도되지 않았다.
2. FedWatch 정확한 수치 — 출처·시각마다 다르다(25bp 89~100%, 50bp 1.4~14%). 하나로 확정하지 않는다. OIS 경로 미확보.
3. 10년물 입찰 테일 — WI 금리 원천이 없어 미산출.
4. 아마존(g4) 11/10 상승 원인 — 확인된 재료 없음.
5. 코히어런트 -4.676%의 고유 원인 — 미확인.
6. GE 버노바·버티브의 장중 시각별 수치 — intraday.json 대상이 아니어서 웹 보도(최대 -9.8%)만 있다.
7. 비FRED 지표: ISM 서비스업·ADP는 앞선 게시 보고서 표 값 재사용(재검색 안 함). S&P Global PMI·CB·뉴욕 연은 기대인플레는 최근 7일 발표 미확인으로 생략.
8. 10월 CPI 전년 대비 — BLS가 2025년 10월 자료 부재로 발표하지 않았다. 9월 3.7%는 CNBC 인용 직전 값이며 10월 전년 대비로 쓰면 안 된다.

## ⑧ 신규 발표 해부

### 소비자물가(CPI) — BLS, 2026년 10월 (발표 2026-11-10 08:30 ET)

- 원문 도달: **예**. `releases/index.json` report_date 2026-11-10, status complete, key `cpi` ok:true·verified:true(identity·period·value 확인), 경로 `releases/cpi.txt`. 원문 URL https://www.bls.gov/news.release/cpi.nr0.htm (U.S. Bureau of Labor Statistics).
- 헤드라인: CPI-U 계절조정 전월 대비 **+0.4%**(9월 +0.6%). 근원(식품·에너지 제외) **+0.3%**로 「9월·8월과 같다」. FRED: 0.35% / 0.30%.
- **원문 인용 세부(기여도 문장 그대로)**:
  - "The index for shelter rose 0.3 percent in October, accounting for over thirty percent of the monthly all items increase." — 주거비가 헤드라인 상승의 30% 넘게 만들었다.
  - "The food index increased 0.5 percent in October, as the food at home index rose 0.4 percent and the food away from home index increased 0.5 percent." 식품은 9월 0.0%에서 0.5%로 뛰었다(외식 내 full service meals +0.7%, 소고기 +0.9%, 스낵 +1.0%).
  - "The index for energy increased 0.7 percent over the month following a 5.2-percent increase in September." 휘발유 +1.0%(9월 +9.1%), 단 계절조정 전 휘발유는 -0.7%. 전기 +0.9%, 도시가스 -0.8%.
  - 근원 세부: 숙박(lodging away from home) +0.6%(9월 +2.0%), 오락 +0.8%(9월 +0.5%), 자동차보험 +0.7%, 의료 +0.3%(병원 서비스 +0.8%, 의사 서비스 +0.4%, 처방약 +0.3%), 신차 +0.2%. 하락은 "used cars and trucks declined 1.2 percent in October after rising 0.7 percent in September" 와 통신 -0.1%.
  - 자가주거비(OER) +0.3%, 임대료 +0.2%.
- `components`(FRED·원문 일치 확인분, 재대조 불필요): 에너지 0.7, 식품 0.5, 주거비 0.3, 중고차 -1.2, 의료 0.3, 휘발유 1.0(모두 %, 전월 대비).
- **Table A 6개월 궤적(계절조정 전월 대비, 원문 표)**:
  - 헤드라인: 5월 0.5 → 6월 -0.4 → 7월 0.1 → 8월 0.4 → 9월 0.6 → 10월 0.4
  - 근원: 5월 0.2 → 6월 0.0 → 7월 0.2 → 8월 0.3 → 9월 0.3 → 10월 0.3 (3개월 연속 0.3)
  - 에너지 제외 서비스: 0.3 → 0.0 → 0.2 → 0.3 → 0.4 → 0.3
  - 교통 서비스: -0.6 → -0.3 → 0.3 → 0.5 → 0.6 → **0.8** (4개월 연속 가속)
  - 주거비: 0.3 → 0.1 → 0.1 → 0.3 → 0.4 → 0.3
  - 의료 상품(계절조정 안 함): -0.7 → -0.2 → -0.6 → -0.2 → -0.7 → **0.5**
  - 휘발유 12개월(계절조정 전): +37.4% — 원문 표에서 12개월 변화가 나온 몇 안 되는 항목. 신차 12개월 +0.7%, 중고차 -3.3%.
- **수정폭·특이 요인**:
  - CPI-U·CPI-W는 발표 시 확정(계절조정치는 5년 소급 수정 대상, 연 1회). 이번 발표에 전월치 수정은 없다.
  - **BLS는 2025년 10월 조사 자료를 예산 공백(셧다운)으로 수집하지 못해, 대부분 지수의 10월 12개월 변화를 발표하지 않았다.** 10월 전년 대비 수치는 모형 추정일 뿐 공식 값이 아니다.
  - 표준오차: 헤드라인 1개월 변화의 표준오차 0.04%p(원문 기술 노트) — 0.4%는 컨센서스 0.3%와 통계적으로 구분되는 폭이다(95% 범위 ±0.08%p).
  - 계절조정 전 헤드라인 +0.2%, CPI-W +0.1%, C-CPI-U +0.2%(계절조정 안 함).
  - 다음 CPI(11월분): 2026-12-10(목) 08:30 ET — 12월 8~9일 FOMC 뒤다. 따라서 12월 회의 전 마지막 CPI가 이번 발표다.
- **시장·연준 관점**: 헤드라인 상회를 에너지만으로 설명할 수 없다. 에너지는 9월 5.2%에서 0.7%로 크게 식었는데 식품(0.5%)과 서비스(교통 서비스 0.8%, 숙박·오락·자동차보험)가 그 자리를 채웠고, 근원이 3개월 연속 0.3%라 「에너지 충격이 걷히면 물가가 식는다」는 경로를 약하게 만든다. 12월 회의 전 마지막 CPI가 이 구성으로 나온 점이 2년물 주도 상승과 50bp 확률 등장을 설명하는 근거가 된다. 중고차 -1.2%·통신 하락은 상품 쪽 완화 신호지만 서비스 가속을 상쇄할 크기는 아니다.

## ⑨ 연준 이벤트 반응

- `fed/events.json`: events 빈 목록 — `fresh: true`·`tier: 1` 이벤트 없음. 이 절은 해당 없음. (월러·로건·슈미드 발언은 tier 1 이벤트가 아니며 ②에 출처와 함께 적었다.)

---

## 운용 판단 브리핑

**오늘 커버리지 요약과 공백**: 주식은 소폭 하락(밴드 미미)인데 금리·달러·금은 밴드 「큼」이다. 오늘의 사건은 10월 CPI 상회 → 단기물 주도 베어 플래트닝 → 12월 인상 완전 반영·50bp 확률 등장이다. 주식 쪽은 엔비디아 고유 위험(이틀째)과 AI 전력설비(소프트뱅크 손상)로 할인이 좁혀졌고, 금융·에너지·헬스케어가 받쳤다. 공백: 장중 정오 저점·오후 회복의 원인, FedWatch 동시점 수치, OIS, 10년물 테일, 아마존 상승 원인, 비FRED 지표 일부.

### 핵심 질문 1 — 물가 상회 뒤 평탄화는 12월 인상 경로가 굳는 신호인가

- 관측: 네이버 2Y 4.727%(+18.0bp), 10Y 4.983%(+12.1bp), 2s10s 31.5→25.6bp(-5.9bp). 10년물 입찰 간접 61.2%(평균 76.6%), 딜러 9.8%, 응찰률 2.46배 「수요 약함」. DXY +0.571%(큼), 금 -2.696%(큼).
- 기대 근거(날짜 있음): 서베이 — 다우존스 헤드라인 0.3%·근원 0.2%(CNBC, 11/10 발표 전). 시장가격 — 12월 인상 확률 11/9 84%(Reuters via Yahoo) → 11/10 발표 뒤 25bp 89~100%, 50bp 1.4~14%(출처·시각 다름; IBTimes·Euronext/Reuters·MPA·Kalshi via cappnotes). 같은 상품 동시점 비교가 아니다.
- 해석: 원문 구성(근원 3개월 연속 0.3%, 교통 서비스 4개월 연속 가속, 식품 반등)은 에너지 완화가 헤드라인을 끌어내리는 경로를 약하게 만들어 12월 인상을 굳힌다. 장기물 입찰 수요가 약했는데도 커브가 평탄해진 것은 공급보다 정책 경로가 커브를 지배했다는 쪽 관측이다.
- 대안: (a) 고용(11/6)과 CPI가 연속으로 상회한 뒤 단기물 포지션 정리가 과장된 하루 반응 — 11/12 이후 2년물이 되돌리면 이쪽. (b) 성장 우려에 따른 장기물 수요 — 오늘은 주식이 거의 안 빠져 근거가 약하다.
- 촉매·기한: 11/11 채권 휴장 → 11/12 네이버 종가·30년물 입찰(250억 달러, 13:00 ET) → 11/13 네이버 종가에서 기존 판단(us-2026-11-06-payrolls-front-end-flattening-vs-riskoff) 판정. 12월 8~9일 FOMC가 최종 촉매. 11월 CPI는 FOMC 뒤(12/10).
- 반증: 11/13 2s10s가 11/6 33.7bp 대비 +5.82bp 이상 가팔라지면 약화(원장 기준 그대로). 현재 -8.1bp로 지지 기준을 넘었지만 판정일 전이다.
- 투자 관련성(조건부): 현금·단기채 슬리브 쪽 참조 금리(미 2년물)가 0.18%p 올랐다는 사실 자체가 펀드 1단계(정책) 판단 재료다. 테마 관점에서 금융(XLF +0.517%)은 단기 금리 상승 날 상대적으로 버텼다 — 금융 테마의 가격 근거가 하루 강화됐지만 한 세션 관측이다. 실행 표현(커브 플래트너, 금융 대 기술 상대가치 등)은 비용(롤·캐리·스프레드)과 독자 보유 제약이 없어 평가하지 않는다. 신규 아이디어 없음이 기본값.

### 핵심 질문 2 — AI 공급망 안에서 할인이 기업 고유 위험으로 좁혀지는가

- 관측: 엔비디아 -5.474%(이틀 누적 vs S&P 500 차이 -5.090%p), 브로드컴 +3.91%, 마이크로소프트 -2.2%(앤트로픽 업무 도구), GE 버노바 -3.895%·버티브 -3.118%(소프트뱅크 손상), 코히어런트 -4.676%, 마벨 -0.136%. XLK -1.153%. 장중 엔비디아는 오후 15:00 봉 저가, 지수는 12:30 저가 뒤 회복 — 엔비디아 고유 재료가 지수와 따로 움직였다.
- 기대 근거: 보도 서사만 있다(Reuters·CNBC·24/7·BofA·야크빌 아이브스 85% 유임). 옵션 내재변동성·포지셔닝·수주 컨센서스 등 가격 기반 기대는 **미확보 — 기대 격차는 측정되지 않았다**.
- 해석(신규 판단 us-2026-11-10-ai-power-softbank-order-risk): 소프트뱅크가 발전설비 환불 불가 선급금을 상각하고 계약을 수정한 것은 전력설비 공급사 수주 잔고의 질을 의심하게 만드는 첫 공개 사례이고, 그 할인은 하루로 끝나지 않는다.
- 대안: 금리 충격에 따른 고배수 성장주 매도와 선거 뒤 고변동 되돌림. 코어위브의 실적·전망 상향(장 마감 뒤)은 AI 수요 쪽 반대 증거다. 소프트뱅크 CFO는 오하이오 축소가 아니라고 했다.
- 구분하는 관측: 금리가 안정되는데도(2년물 누적 상승이 작음) 두 종목이 계속 뒤처지면 수주 위험 쪽, 금리 안정과 함께 따라잡으면 금리 대안 쪽. 원장 기준: 11/10→11/17 (버티브·GE 버노바 평균 − S&P 500) ≤ -9.28%p 지지, ≥ +9.28%p 약화, 그 사이 판정 불가. 2년물 누적 +25bp 이상이면 메커니즘 판정 불가.
- 촉매·기한: 오하이오 재검토 후속 보도, 다른 개발사의 조달 변경, 의회 데이터센터 일정. 11/17 장 마감 뒤 엔비디아 실적은 구간 밖.
- 투자 관련성(조건부): 전력망·전력설비 테마와 반도체 테마의 가격 근거를 분리해서 봐야 한다는 재료다 — 반도체 안에서는 엔비디아 고유 위험과 경쟁사 수혜가 갈렸고, 전력설비는 고객 조달 위험이라는 새 쟁점이 생겼다. 오늘 사실은 전력설비 테마의 가격 근거를 약화시키는 쪽이고, 반도체 테마는 종목 간 분산이 커졌을 뿐 테마 전체의 약화 증거는 아니다. 기준선의 9.28%p 폭은 최근 변동성이 커서 넓다 — 판정 불가로 끝날 가능성이 크다는 한계를 안고 있다. 실행 비용·독자 노출은 미제공.

### 원장 연결

- 회차: **us-2026-11-10-daily-cycle**
- 신규 판단: us-2026-11-10-ai-power-softbank-order-risk (insight, watch, prospective=true, test_start 2026-11-11 09:30 ET, deadline 2026-11-17 16:00 ET)
- 오늘 닫힌 판단: us-2026-11-04-datacenter-politics-power-overreaction → 리뷰 us-2026-11-10-datacenter-politics-power-overreaction-review (방향 판정 불가, 메커니즘 판정 불가, closed; 차이 -2.724%p, 구간 ±6.45%p)
- 미결(unresolved 사유 기록): us-2026-11-05-ai-chip-crash-degross-vs-rerating(11/12), us-2026-11-06-payrolls-front-end-flattening-vs-riskoff(11/13), us-2026-11-09-nvidia-governance-discount-persist(11/16)
- 정본 입력 필드: `market_data.json` indices/sectors/memory/ai_infra/yields/spread_2s10s_bp, `data/history/market.jsonl`, `auctions.json` today[nominal-10y], `releases/cpi.txt`, `macro_metrics.json` headline_releases[cpi], `intraday.json`, `movers.json` groups g1~g5.
- 증거(커밋 대상): `research/us/evidence/` 7bc2befa…(market.jsonl), 9b23397c…(market_data.json), 20e1603f…(auctions.json), c2656e9e…(cpi.txt), 456cbea3…(news 11/10), ba92a972…(웹 세션 요약).

---

## 학습·복기

### 이전 질문 (같은 시장 직전 게시물)

- 경로: `posts/2026-11-09.html` (날짜 2026-11-09), 섹션 `data-learning="daily"`, `data-research-cycle="us-2026-11-09-daily-cycle"`.
- 그 블록이 다룬 질문·조건·기한:
  1. 엔비디아 지배구조 할인(11/9 신규): 11/9→11/16 엔비디아 − S&P 500 ≤ -3.89%p 지지 / ≥ +3.89%p 약화. 기한 11/16 종가.
  2. 반도체 급락 포지션 축소 과잉 하락(11/5): 11/5→11/12 XLK − S&P 500 ≥ +3.38%p 지지. 2년물 누적 ±25bp 초과 시 판정 불가. 기한 11/12 종가.
  3. 전력설비 선거 다음 날 급락 과잉 반응(11/4): 11/4→11/10 버티브·GE 버노바 평균 − S&P 500 ≥ +6.45%p 지지. 기한 11/10 종가.
  4. 고용 뒤 2년물 주도 평탄화(11/6): 11/6→11/13 2s10s 변화 ≤ -5.82bp 지지. 기한 11/13 네이버 종가. 10월 CPI(11/10)가 첫 근거.
- 그 블록이 예고한 다음 관측: 「11월 10일 08:30(ET) 10월 소비자물가가 금리 판단의 첫 근거를 주고, 같은 날 종가에서 전력설비 판단 … 결론이 나온다」.

### 오늘 결과 (원장과 일치)

- 3번(전력설비, 11/4): **판정 불가로 닫힘**. 차이 -2.724%p(구간 ±6.45%p 안). 11/9 +0.358%p에서 지지하려면 하루 +6.1%p가 더 필요했는데 오히려 -3.1%p 벌어졌다. 마지막 날 소프트뱅크 손상·CPI라는 새 재료가 겹쳐 원래 쟁점(정치 할인)으로 구간을 설명할 수 없다. 방향도 메커니즘도 확인되지 않았다 — 실패가 아니라 결론 없음이며, 새 쟁점은 별도 판단으로 넘겼다.
- 4번(금리, 11/6): CPI가 예정대로 나왔고 2s10s 25.6bp로 11/6 대비 -8.1bp — 판정일 전에 이미 지지 기준을 넘었다. 주식이 거의 안 빠진 날 단기물이 이끈 평탄화라 안전자산 대안과 구분되는 관측이 처음 나왔다. 판정은 11/13.
- 1번(엔비디아, 11/9): 첫 세션 차이 -5.090%p로 지지 기준을 넘었다. 판정은 11/16. 이틀 하락이 같은 재료(조사·소송·정치)의 연장이라 방향은 맞지만, 실적(11/17) 기대 되돌림 가능성은 남아 있다.
- 2번(반도체, 11/5): 차이 +1.748%p로 11/9 +2.566%p에서 후퇴. 2년물 누적 +25.0bp로 제외 기준 경계(「넘으면」 판정 불가, 현재는 넘지 않음). 11/12 네이버 종가가 제외 여부를 가른다.

### 오늘의 재료 질문

- 관측: 2년물 +18.0bp(2025년 4월 이후 최대 상승 보도)인 날 S&P 500 -0.384%, VIX -0.46pt. 하락의 중심은 엔비디아 -5.474%였고 금융·에너지·헬스케어는 올랐다 — 금리 충격에 주식 전반이 「무반응」에 가까웠다.
- 가설: 시장은 12월 인상을 이미 84% 반영하고 있었고(11/9), CPI는 확률을 완전 반영 쪽으로 밀었을 뿐 경로 자체를 바꾸지 않아 주식 할인율 충격이 작았다.
- 대안: 지수가 버틴 것은 금리 무반응이 아니라 업종 회전(기술 → 금융·방어) 때문이고, 성장주(IVW -0.804%)는 실제로 금리에 반응했다. 성장·가치 격차 -0.92%p가 이쪽 관측이다.
- 구분 증거: 11/12 이후 2년물이 더 오를 때 IVW−IVE 격차가 같은 방향으로 벌어지는지. 50bp 확률이 커지는 날 S&P 500 전체 반응이 커지는지.

### 계산 (재현 가능)

- 질문: 오늘 커브 평탄화의 크기.
- 입력: `market_data.json` → `yields['2Y'].bp` = 18.000, `yields['10Y'].bp` = 12.100 (단위 bp, 네이버 2026-11-10 vs 2026-11-09, 전 만기 동일 기준일); 검산용 `yields['2Y'].level` 4.727, `yields['10Y'].level` 4.983, `spread_2s10s_bp` 25.6, 11/9 2s10s 31.5bp(`data/history/market.jsonl` 11/09 행: 2Y 4.547, 10Y 4.862).
- 공식: 2s10s 변화 = 10Y 변화 − 2Y 변화 (bp).
- 명령: `python3 -c "print(12.1-18.0, round((4.983-4.727)*100,1), round((4.862-4.547)*100,1))"`
- 결과: -5.9bp (25.6bp − 31.5bp = -5.9bp로 일치).
- 정렬 확인: 두 다리 모두 네이버 17:05 ET 같은 날, 같은 만기 정의(2년·10년 지표물), 같은 비교 창(1영업일).

### 다음 시험

- 관측 조건: 11/12 네이버 2년물 종가가 4.727%에서 더 오르는지(인상 경로 고착), 되돌리는지(하루 과잉 반응), 그리고 같은 날 IVW−IVE 격차의 방향. 시계: 11/12(수) 미국 정규장·채권 마감(11/11 채권 휴장). 30년물 입찰 11/12 13:00 ET(auctions.json `next`).
- 지지: 2년물 추가 상승과 성장주 상대 약세가 함께 나오면 「업종 회전이 금리를 흡수」 대안이 지지된다. 2년물이 오르는데 IVW−IVE가 평평하면 「이미 반영」 가설이 지지된다.
- 이 재료 질문은 원장에 등록하지 않았다(기존 금리 판단과 겹침). 원장 판정은 위 4개 판단과 신규 1개의 기준만 쓴다.
