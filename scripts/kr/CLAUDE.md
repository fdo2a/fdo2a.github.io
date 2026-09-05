<!-- 이 파일은 `scripts/kr/` 안의 파일을 건드릴 때 자동으로 로드된다.
     공통 규칙은 site/AGENTS.md. 이 파일 + site/AGENTS.md 가 32,768 B 를 넘으면 꼬리부터 조용히 잘린다. -->

## 한국 시장 마감브리프 (2026-07-22~)
미국 브리프와 짝을 이루는 **평일 저녁 한국 증시 마감브리프**. `/kr/` 경로로 분리 발행(미국 URL 무손상). 상세는 프로젝트 메모리(kr-market-brief-project) + spec `docs/superpowers/specs/2026-07-23-kr-program-technical-design.md`·`2026-08-06-kr-intraday-flows-design.md` (원래 적혀 있던 `2026-07-22-kr-market-brief-design.md`는 레포에 없다 — 2026-09-05 확인).
- **데이터 소스 = Naver Finance(주) + yfinance(보조)만.** pykrx·키움 API 폐기(2026-07-22 실증: KRX는 해외 IP 미차단이나 pykrx 수급·지수 함수가 버그로 불안정, Naver는 미국 Actions IP에서 전 엔드포인트 작동). Naver HTML은 EUC-KR.
- **수집 = GitHub Actions** `.github/workflows/collect-kr-data.yml`(평일 17:00·17:30 KST = 08:00·08:30 UTC, 마감 후) → `scripts/collect_kr_data.py` + `scripts/kr/` 패키지(TDD, 21 tests)가 `kr/data/*` 커밋. 수동: `gh workflow run collect-kr-data.yml -f force=true`
- **산출**: kr_market_data.json(지수·complete·flows_date) / kr_flows.json(외/기/개 순매수, 억원) / **kr_flows_intraday.json + .png**(장중 누적 순매수 궤적 — 2026-08-06 사용자 지시로 신설. Naver `investorDealTrendTime`이 09:03~18:06 약 180~360개 누적 스냅샷을 주고, `scripts/kr/flows_intraday.py`가 정규장(≤15:30)만 잘라 30분 앵커 13개·주체별 극값·**의미 있는 방향 전환**(그날 최대 절대값의 5% 미만 구간은 개장 직후 잡음이라 버림)으로 가공. 차트는 수급 3선 + 지수 우축 오버레이 2패널. **장중 스냅샷 ≠ 확정치** — 정정 때문에 갈리므로(2026-08-05 코스피 외국인 15:30 +15,116 vs 확정 +14,464) 확정 수치는 kr_flows.json에서만 인용) / kr_top_value.json(거래대금 상위 10, **ETF 정규화** — 단일종목 레버리지는 기초자산+방향별 병합, **지수 관련 ETF·해외 ETF는 제외**. 2026-07-29 사용자 지시로 지수 ETF 버킷 폐기 — 코스피200·코스닥150 추종과 그 레버리지/인버스 모두 `etf_normalize.DROP_KINDS`로 탈락. 판정은 브랜드·레버리지 수식어·지수명을 걷어낸 잔여물이 비면 지수 상품, 남으면 섹터/테마 유지(`TIGER 200 IT`·`TIGER 코스피고배당`은 잔류). **2026-08-06 사용자 지시로 같은 테마 섹터 ETF를 테마+방향별 1줄 병합** — 지수 ETF를 걷어낸 뒤 반도체 ETF가 매일 2~5칸을 쪼개 차지했고(실측 raw 100행엔 9종 1.46조가 들어 있는데 상위 10엔 3종 0.98조만 노출) 셋 다 같은 베팅이라 신호가 죽었다. `THEME_KEYWORDS` 사전 매칭, 실패 시 제 이름 유지(안전 폴백), 병합 1종이면 라벨도 원래 이름. 섹터 ETF를 아예 빼는 안은 기각 — Naver가 업종 단위 거래대금을 안 줘서 리포트에서 업종별 **자금량**이 나오는 곳이 여기뿐이다(§7 업종은 등락률·breadth라 가격 신호)) / kr_industry.json(업종 breadth 주도 크로스체크) / kr_theme.json(**리포트 미사용** — 2026-07-29 테마 섹션 폐지로 비-코어 강등, 수집만 유지) / kr_sector.html(1D~1Y 막대) / kr_intraday.json / **kr_econ.json**(ECOS 한국은행 — 국고채 3년·10년, CD 91일, 회사채 AA- 3년, 기준금리. 2026-07-29 연동 완료)
- **핵심 규칙**: ① **수급 신선도** — 당일 확정치가 18:00에 없을 수 있음 → `flows_date`·`flows_provisional`로 "당일 잠정/전 거래일 기준" 라벨, 당일 수급 창작 금지. 장중 궤적도 같은 규율(`stale`) + 앵커 사이 값 보간 금지. ② 거래대금 상위 ETF 정규화. ③ 멀티기간 수익률은 **거래대금·breadth 크로스체크**로 주도 판정(상승률만 X). ④ **정책·정치 촉매 = 수급 다음가는 주력 섹션**(2026-07-29 사용자 지시로 확대) — 하위 블록 3개 이상, 각 블록에 사실 → 전달 경로(수급/이익/멀티플) → 수혜·피해 업종 → 다음 일정·확인 트리거 4요소. 당파 논평·선거 예측 금지
- **리포트 구조** (2026-07-29 사용자 지시): **전략 코멘트를 헤드라인 바로 다음(§2)으로 전진 배치** — 결론 먼저, 표는 뒤. 선행 요약이라 여기 실린 수치는 아래 표와 1:1 대조가 발행 게이트에 추가됨. **테마 섹션 폐지** — 종목 재료는 특징주, 산업 쏠림은 업종 섹션이 흡수. §5 수급 서브블록 순서는 **일별 확정 → 장중 수급 전개(2026-08-06 신설: 차트+30분 앵커 표+해석 2~3문단, 기관은 금융투자·연기금등 두 축만 서술) → 프로그램 매매**
- **작성·발행**: writer 스펙 `.claude/agents/kr-report-writer.md`, 파이프라인 `.claude/KR_ORCHESTRATOR.md`(공유 규칙은 US brief-report-writer.md 참조). report_date는 `kr_market_data.json` 신뢰. 발행 `/kr/posts/[date].html` + `kr/posts.json` + sitemap. **Notion 발행 중지** (2026-08-18 사용자 지시 — US와 함께, 블로그 한 채널만). (재개 대비 기록: DB "KR Market Brief", data_source_id `d1dcda42-2e15-4080-93a2-b77622e46f3d`)
- **클라우드 루틴 트리거**: `trig_01HmSKF1UVXZvQSDk9pzYY8C` — 월~금 18:00 KST(cron `0 9 * * 1-5` UTC) 실행, 레포 클론 후 `.claude/KR_ORCHESTRATOR.md` 실행. sonnet-5, Notion·PushNotification 연결. 트리거 변경만 RemoteTrigger로(부트스트랩은 짧게, 파이프라인은 레포 파일)
- **일봉 차트**: `scripts/kr/charts.py`가 코스피·코스닥·SK하이닉스·삼성전자 3개월 일봉 캔들 → **PNG 바이트 반환**, `charts.publish()` 가 `kr/assets/kr_charts_{거래일}.png` 로 내보낸다(matplotlib, 상승 녹색/하락 적색). 같은 날짜에 **다른 바이트**를 쓰려 하면 `AssetConflict` — 발행된 그림이 뒤에서 바뀌는 것을 막는다. 만들어진 차트 목록은 `kr/data/kr_charts_manifest.json`. 거래대금 상위는 **레버리지(롱)/인버스(숏) 방향 분리** 병합
- **ECOS 연동** (2026-07-29): 인증키는 레포 시크릿 `ECOS_API_KEY`(워크플로 `env`로만 주입, 로컬 env엔 없음). ECOS는 **키를 URL 경로에 넣으므로** `scripts/kr/econ.py`의 `scrub()`를 거치지 않은 URL·예외를 절대 출력하지 말 것. 항목 코드는 하드코딩하지 않고 `StatisticItemList`에서 이름으로 해석(코드는 통계표 개편 때 바뀌고 오류 시 INFO-200으로 조용히 실패). 비-코어 — 결측이어도 발행 게이트 통과, writer가 해당 행만 뺀다
- **미완/열린 항목**: ECOS 월별 지표(CPI·수출입) 추가 여부


## 주간·월간 정리 — KR 몫 (설계 2026-08-23)

- **성격**: 그 기간에 **발행한 KR 마감브리프들의 총정리**다. 새로 취재하지 않는다 — **웹 검색 금지·시세 재수집 금지.** 본문 서술은 `kr/posts/*.html`, 성과표는 집계 파일로 소스가 갈린다.
- **발행물**: 토요일 `/kr/weekly/<YYYY-Www>.html`, 월 롤오버 다음날 `/kr/monthly/<YYYY-MM>.html`. **키는 기간 식별자다** — `us/period.py` 의 `week_key()`·`month_key()` 를 그대로 쓴다. 마지막 거래일은 `end_date` 필드이지 파일명이 아니다.
- **저장소가 둘이다. 섞으면 복원이 안 된다** (2026-09-06 정정).
  - `kr/data/history/kr_market.jsonl` — **지수 종가 원장**. `collect_kr_data.py` 가 그날 발행본이 인쇄한 값을 쌓는다(`upsert=True`). 성과표의 끝값이 여기서 나온다.
  - `kr/data/{weekly,monthly}/<KEY>.json` 의 **`_sessions`** — 업종·거래대금·수급 **세션 원장**. `scripts/kr/period.py` 의 `upsert_session()` 이 날짜 키로 쌓고 `finalize()` 가 굴린다. 과거 계열이 없어 여기 모으는 것이며, **JSONL 만 백업하면 이쪽은 복원되지 않는다.** 두 번 돌아도 두 번 더해지지 않고, 실패한 날은 다음 실행이 메운다.
- **수급은 확정치만 담는다** — 잠정치는 정정되면서 조용히 틀려진다(일간의 `flows_provisional` 규율과 같다).
- **`leading` 플래그는 60개 업종 중 30개에 붙는다**(2026-08-30 실측) — 등락률 상위 5개만 남긴다.
- **미완** (2026-09-04): **KR 주간·월간은 아직 한 편도 없다** — `kr/weekly/`·`kr/monthly/` 디렉터리 자체가 없으므로 트리거 등록(토 `0 0 * * 6`, 월 `30 0 1,2,28,29,30,31 * *`) 여부를 먼저 확인할 것. 첫 몇 회차는 롤업이 표본 부족으로 나오는 것이 정상이다.
- **고칠 때**: `scripts/kr/period.py` 를 건드리기 전에 `docs/superpowers/specs/2026-08-23-period-reports-design.md` 를 읽는다. 게이트(`check_period.py`)와 작성 사양은 US·KR 공용이라 `scripts/us/CLAUDE.md` 의 「주간·월간 정리 — US 몫」에도 같은 규율이 적혀 있다.
