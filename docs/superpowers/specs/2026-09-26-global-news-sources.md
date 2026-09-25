# 뉴스 섹션 — 「글로벌」·「리포트·칼럼」 갈래와 출처 확장 (2026-09-26)

## 사용자 지시 (연속 넷)

1. 「뉴스 섹션에 글로벌 뉴스도 추가하자. 미국, 한국을 제외한 나라 뉴스 중 정책이나 경제에 큰 영향을 준 뉴스로. 대표적으로 일본, 중국, 유럽, 중동 정도」
2. 「뉴스 출처를 로이터나 investing.com 같은 곳에서 가져오는 것도 가능한지 검토해. 단순히 기사만으로 한정하지 말고 레포트나 칼럼도 괜찮아」
3. 「인사이트를 얻을 수 있는 내용이라면 다 좋아」
4. 「두 사이트뿐만 아니라 공신력 있는 기관이라면 다 좋아」

## 출처 실측 (2026-09-26 03시 KST, 로컬 urllib → 403·429 이면 curl_cffi)

뉴스 섹션의 계약은 **본문을 읽고 만든 요약**이다(`us/news.py` 머리말) — 헤드라인만 주는 출처는 쓰지 않는다. 그래서 「피드가 열리는가」와 「본문이 열리는가」를 따로 쟀다.

| 출처 | 피드 | 본문 | 결론 |
|---|---|---|---|
| CNBC World·Europe·Asia | 각 30건 | ○ | 글로벌 |
| Investing.com economy(news_14)·world(news_287) | 각 10건, **pubDate 없음** | ○ `id="article"` 안. **본문이 로이터 전재**(「PARIS, Sept 25 (Reuters) -」) | 글로벌 — 로이터는 이 경로로 받는다 |
| Investing.com 분석 market_overview·forex·commodities·bonds | 각 10건, 당일 | ○ | 리포트·칼럼 |
| Investing.com 분석 Technical·Fundamental·investing_ideas | 8월 초에 멈춤 | — | ✕ |
| Investing.com 121899 | 종목 나열형 위주, 2주에 10건 | — | ✕ |
| Reuters 직접 | 사이트 401(DataDome), `arc/outboundfeeds/news-sitemap` 은 열림(50건/쪽, 지역이 URL 경로에) | urllib 401, curl_cffi 로만 ○ | ✕ — Actions 데이터센터 IP 에서 TLS 위장이 통할지 불확실하고, 같은 기사가 Investing.com 으로 온다 |
| ECB press·blog | 각 15건 | ○ | 글로벌(보도자료)·칼럼(블로그) |
| Bank of England news | 50건 | ○ | 글로벌 — 운영 공지가 섞여 정책 어휘로 거른다 |
| BIS 중앙은행 연설(cbspeeches) | RDF 50건, `dc:date` | ○ | 칼럼 |
| ING THINK | 10건, `dc:date` | ○ | 칼럼 |
| The Guardian business·Al Jazeera·BBC business | ○ | ○ | 글로벌 |
| IMF news·blog·OECD·CFR·Japan Times | 403 | — | ✕ |
| BOJ·Nikkei Asia·DW | 피드 ○ | 본문 0(PDF·유료벽·JS) | ✕ |
| SCMP | ○ | 938자(유료벽 추정) | ✕ |
| PIIE·Brookings | 404 / RSS 아님 | — | ✕ |
| 네이버 뉴스 세계 섹션 101/262·104/231·233·234 | HTML 36건/쪽, `?date=YYYYMMDD` 가 그날 기사만, 시각은 「4시간전」 | ○ `#dic_area`, 기사면 `data-date-time` | KR 글로벌 |

유료벽 매체(Bloomberg·FT·WSJ·Nikkei)는 본문이 없어 같은 이유로 뺐다.

## 설계

- **갈래**: US 에 `global`「글로벌」·`insight`「리포트·칼럼」, KR 에 `global`「글로벌」. 둘 다 섹션 맨 뒤. KR 칼럼은 하지 않았다 — 같은 영문 칼럼이 US 아침판에 이미 실린다.
- **글로벌 판정**: 제목에 지역 **그리고** 제목·요약(KR 은 제목)에 정책·경제 어휘. 공식 기관 피드(ECB·BoE)는 지역을 호스트가 준다. 미·한 단독 기사는 지역어가 없어 자연히 빠진다. 통화 이름(yen·yuan)은 US 에서 지역으로 치지 않는다(「The dollar slides against the yen」 은 매크로). 분류 순서 mlcc → insight 피드 → global → ai → macro.
- **「큰 영향」의 대리 지표**: 정책·경제 어휘 **묶음** 몇 개가 걸렸나. 기계가 영향을 잴 수는 없으니 어휘가 촘촘한 기사를 앞에 둔다. 알려진 한계: 2026-09-26 실측에서 영국 식품 무역적자 기사(무역·적자)가 스위스 금리 동결보다 앞섰다.
- **2단 선정**: 후보(글로벌 8·칼럼 6, 36시간 창, 순위 → 지역 순환, 같은 사건 접기) → 본문 수집(피드 날짜가 없으면 기사면 `datePublished`·`data-date-time`) → `trim()` 이 본문·날짜 창을 통과한 것만 확정(글로벌 4·칼럼 3). **날짜를 수집 시각으로 채우지 않는다** — 못 읽으면 탈락. 요약(유료 호출)은 확정분만.
- **같은 사건**: US 는 제목 단어 자카드 ≥0.5(CNBC·로이터·가디언이 따로 쓴다), KR 은 기존 `dedupe` 의 제목 유사도(주요뉴스가 먼저라 주요뉴스 갈래로 남는다).
- **칼럼 요약**: `news_summary.SYSTEM_ANALYSIS` — 전망·권고를 필자·기관의 견해로 귀속한다. 기사 프롬프트로 요약하면 「엔화는 반등한다」 같은 남의 전망이 사실로 실린다.
- **출처 표기**: 호스트 → 매체명(`us.news.SOURCES`). Investing.com 본문 첫 120자에 「(Reuters) -」 가 있으면 `wire: "Reuters"` — 작성자가 「로이터(Investing.com)」 로 적는다.
- **게이트**: `news_gate.check` 는 그대로, 갈래 목록만 늘었다.

## 오분류 방지 (실제 헤드라인에서)

- 「Gulf」 → 멕시코만. `Gulf states`·`Gulf Cooperation` 만.
- 「fiscal first quarter」(회계연도) → `fiscal` 은 policy·stimulus·deficit 등이 뒤따를 때만.
- 「summit」 → 판다 외교 기사. 뺐다. KR 「회담」 도 만찬·농담 기사라 뺐다.
- KR 한 글자 약칭: 中企(중소기업), 달러의 「러」, 조사 「~이란」, 동사 「가자」.
- KR 「미중 무역협상」 은 中·중국을 쓰지 않는다 → `미·?중` 을 중국으로.
- 칼럼 피드의 종목 나열형(「9 Stocks…」「These 2 Bond ETFs…」「Pre-Market Setups」)은 버린다.
- RSS 정규식이 RDF 의 `<items>` 를 첫 item 으로 읽었다(BIS) → `<item(?:\s[^>]*)?>`.

## 검증

- 로컬 실수집 2026-09-26: US 797건 → 글로벌 4(유럽·중동·중국·일본 각 1, 일본 건은 로이터 전재·기사면 날짜) · 칼럼 3(ING·Investing.com·ECB 블로그). KR 2026-09-25: 세계 섹션 144건 → 적격 37 → 확정 4(중국 미중 무역·중동 호르무즈·유럽 EU 우크라 기금·일본 엔저).
- **Actions IP 에서 새 출처가 열리는지는 첫 수집 로그로 확인한다** — 비-코어라 막히면 `notes` 에 피드별로 남고 그 갈래만 얇아진다.
