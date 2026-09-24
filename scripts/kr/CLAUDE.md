<!-- 이 파일은 `scripts/kr/` 안의 파일을 건드릴 때 자동으로 로드된다.
     공통 규칙은 site/AGENTS.md. 이 파일 + site/AGENTS.md 가 32,768 B 를 넘으면 꼬리부터 조용히 잘린다. -->

## 한국 시장 마감브리프
평일 저녁 한국 증시 마감브리프, `/kr/` 경로 발행. 설계: `docs/superpowers/specs/2026-07-23-kr-program-technical-design.md`·`2026-08-06-kr-intraday-flows-design.md`. 이력(소스 폐지 경위·실측·사용자 지시): `docs/superpowers/specs/2026-09-24-instruction-history-archive.md` 「scripts/kr/CLAUDE.md」.
- **데이터 소스 = 네이버 m.stock/api.stock JSON API + yfinance.** 레거시 `finance.naver.com/sise/*.naver` 는 2026-09-17 SPA 개편으로 전부 죽었다(410 또는 표 없는 200). **`scripts/kr/sources.py` 의 fetch_* 는 빈 결과를 성공으로 취급하지 않는다 — 비면 예외를 올린다**(조용한 `[]` 가 8거래일 발행을 막았다). 수급 `m.stock/api/index/{KOSPI|KOSDAQ}/trend?bizdate=`(하루 한 행, 10거래일은 날짜를 거슬러 호출, 단위·부호는 레거시와 같다), 거래대금 `m.stock/api/stocks/marketValue/all` 페이지네이션(시총 순이라 전량을 훑어 재정렬, `sosok="0"` 코스피, 백만원). **장중 수급·프로그램 매매·테마는 대체재가 없어 폐지** — 비-코어라 해당 블록만 빠진다.
- **수집 = GitHub Actions** `collect-kr-data.yml`(평일 08:00·08:30 UTC) → `scripts/collect_kr_data.py` + `scripts/kr/` 가 `kr/data/*` 커밋. 수동: `gh workflow run collect-kr-data.yml -f force=true`.
- **산출**: `kr_market_data.json`(지수·complete·flows_date) / `kr_flows.json`(외/기/개 순매수, 억원) / `kr_flows_intraday.json`+png(**현재 항상 결측** — 파이프라인 `flows_intraday.py` 는 대체재가 생기면 그대로 산다: 정규장 ≤15:30, 30분 앵커 13개, 주체별 극값, 최대 절대값 5% 미만 전환은 버림. **장중 스냅샷 ≠ 확정치** — 확정 수치는 `kr_flows.json` 에서만) / `kr_top_value.json`(거래대금 상위 10, **ETF 정규화**: 단일종목 레버리지는 기초자산+방향별 병합, **지수·해외 ETF 제외**(`etf_normalize.DROP_KINDS` — 브랜드·레버리지 수식어·지수명을 걷어낸 잔여물이 비면 지수 상품), 같은 테마 섹터 ETF 는 `THEME_KEYWORDS` 로 테마+방향별 1줄 병합(실패 시 제 이름, 1종이면 원래 이름)) / `kr_index_etf.json`(`etf_normalize.dropped_products()` — 상위 표에서 뺀 지수 ETF 거래대금, §2 `action` 의 유동성 근거로만) / `kr_industry.json`(업종 breadth) / `kr_theme.json`(항상 빈 배열) / `kr_sector.html` / `kr_intraday.json` / `kr_econ.json`(ECOS).
- **핵심 규칙**: ① **수급 신선도** — `flows_date`·`flows_provisional` 로 「당일 잠정 / 전 거래일 기준」 라벨, 당일 수급 창작 금지, 장중 앵커 사이 보간 금지. ② 거래대금 상위 ETF 정규화. ③ 주도 판정은 **거래대금·breadth 크로스체크**(상승률만 X). ④ **정책·정치 촉매 = 수급 다음 주력 섹션** — 하위 블록 3개 이상, 블록마다 사실 → 전달 경로 → 수혜·피해 업종 → 다음 일정·확인 트리거. 당파 논평·선거 예측 금지.
- **작성·발행**: writer `.claude/agents/kr-report-writer.md`, 파이프라인 `.claude/KR_ORCHESTRATOR.md`. report_date 는 `kr_market_data.json` 신뢰. 발행 `/kr/posts/[date].html` + `kr/posts.json` + sitemap. **블로그 한 채널만**(Notion 중지 — 재개 대비: DB "KR Market Brief", data_source_id `d1dcda42-2e15-4080-93a2-b77622e46f3d`).
- **클라우드 루틴**: `trig_01HmSKF1UVXZvQSDk9pzYY8C` — 월~금 18:00 KST(`0 9 * * 1-5` UTC), sonnet-5, **커넥터 없음**(2026-09-24 제거). 루틴 프롬프트는 짧게, 파이프라인은 레포 파일에.
- **일봉 차트**: `scripts/kr/charts.py` → PNG 바이트, `charts.publish()` 가 `kr/assets/kr_charts_{거래일}.png` 로. 같은 날짜에 다른 바이트를 쓰면 `AssetConflict`. 목록은 `kr/data/kr_charts_manifest.json`.
- **ECOS**: 키는 레포 시크릿 `ECOS_API_KEY`(워크플로 env 로만). **키가 URL 경로에 들어가므로 `scripts/kr/econ.py` 의 `scrub()` 를 거치지 않은 URL·예외를 출력하지 않는다.** 항목 코드는 하드코딩하지 않고 `StatisticItemList` 에서 이름으로 해석한다. 비-코어.
- **가격에 반영된 기대**: `kr_econ.json` 의 `expectations` — 정책(국고3년−기준금리)·성장(10년−3년)·신용(회사채AA-−국고3년) 스프레드와 2년 이력 속 위치(`common/standing.py`). `econ.py` 의 `_LOOKBACK` 800일·`_MAX_ROWS` 1000 은 이 계산 때문이다(줄이면 앞쪽이 조용히 잘린다). VKOSPI 는 소스가 없어 채택 불가.
- **독자 = 헤지펀드 매니저**(KR 만). 정본은 writer 머리의 「독자와 역할」.
- **판단 원장**: `kr_stance.json`(어제 판단) → 수집기가 무효화 레벨을 그날 종가로 검산 → `kr_stance_eval.json`(`유효`·`무효화`·`판정불가`) → writer 가 §2 `review` 에서 그 판정을 말하고 `kr_stance_next.json` 을 낸다 → 오케스트레이터 STEP 2.9 가 원장으로 승계. **무효화 조건을 수로 남기는 게 핵심이다.** `scripts/kr/stance.py`·`stance_gate.py`·`scripts/check_kr_stance.py`.
- **판단군 하한 1,800자** (`check_weight.py`, market=kr).
- **오늘의 뉴스 (§12, 2026-09-24)**: `fetch_kr_news.py` (KR 수집 잡의 비-코어 단계) → `kr/data/news/<date>.json`. 원천은 네이버증권 주요뉴스(`m.stock` front-api 는 `mainnews`·`flashnews`·`ranknews` 만 받는다), 본문은 `n.news.naver.com` 의 `#dic_area`. 갈래는 제목 키워드(`macro`→`policy`→`market`→`industry` 우선순위, 해외 증시 마감·생활 기획은 버림), 매체별 재탕은 제목 유사도 ≥0.6 으로 접는다. **본문은 커밋하지 않는다** — 수집 잡이 `us/news_summary.py`(`SYSTEM_KO_SOURCE`, WIF)로 요약만 커밋. 게이트는 US 와 같은 `us/news_gate.check` 를 `check_news.py --market kr` 로(`categories=kr.news.DIGEST_CATEGORIES`). 순수 로직 `scripts/kr/news.py`.
- **미완**: ECOS 월별 지표(CPI·수출입) / 장중 수급·프로그램 매매 대체재 / US 독자 전환 여부.

## 주간·월간 정리 — KR 몫

- **성격**: 그 기간에 발행한 KR 마감브리프의 총정리. **웹 검색·시세 재수집 금지.** 서술은 `kr/posts/*.html`, 성과표는 집계 파일.
- **발행물**: 토요일 `/kr/weekly/<YYYY-Www>.html`, 월 롤오버 다음날 `/kr/monthly/<YYYY-MM>.html`. 키는 `us/period.py` 의 `week_key()`·`month_key()`. 마지막 거래일은 `end_date` 필드다.
- **저장소가 둘이다 — 섞으면 복원이 안 된다.** `kr/data/history/kr_market.jsonl`(지수 종가 원장, `upsert=True`)과 `kr/data/{weekly,monthly}/<KEY>.json` 의 **`_sessions`**(업종·거래대금·수급 세션 원장, `scripts/kr/period.py` 의 `upsert_session()`·`finalize()` — 멱등, 실패한 날은 다음 실행이 메운다). JSONL 만 백업하면 `_sessions` 는 복원되지 않는다.
- **수급은 확정치만 담는다.** `leading` 플래그는 60개 업종 중 30개에 붙으므로 등락률 상위 5개만 남긴다.
- **현황**: KR 주간은 2026-W37 부터 발행 중, 월간은 아직 없다 — 첫 회차는 롤업 표본 부족이 정상이다.
- **고칠 때**: `scripts/kr/period.py` 를 건드리기 전에 `docs/superpowers/specs/2026-08-23-period-reports-design.md` 를 읽는다. 게이트(`check_period.py`)와 작성 사양은 US·KR 공용이다(`scripts/us/CLAUDE.md` 「주간·월간 정리 — US 몫」).
