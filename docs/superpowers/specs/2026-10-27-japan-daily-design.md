# 일본 일간 마감브리프 — 설계 (2026-10-27)

상태: **구현 완료(브랜치 `jp-daily`), codex 설계·구현 검토 반영.** 계약은 `scripts/japan/CLAUDE.md` 「Japan daily close brief」. 판정 표는 `../plan.md` 「2026-10-27 — 일본 일간」.

## 사용자 요청
1. 「지금 미국이랑 한국 하고 있는걸 일본 버전도 만들어서 보고싶어」
2. 「일본 주간은 미국, 한국 주간처럼 그대로 두고 일간 레포트를 만드는걸 추가하고 싶은거야」
3. 「저녁에 보고싶고 일본 경제를 전반적으로 팔로우업하는걸 목표로 하고싶어」
4. 「주식, 채권, 환율, 매크로, 일본 국내 뉴스 등을 보고싶어」
5. 네 안 중 **A(자산군 순서형, US 일간 배치)** + C 의 규칙 하나: **지표 발표일·BOJ 이벤트일에는 그 절이 위로 올라온다.**
6. 「일본 국내 뉴스에 경제 뉴스를 위주로 만들어」

## 목표 · 비목표 · 반목표
- **목표**: 도쿄 거래일 저녁마다 일본 경제 전반(주식·채권·엔·매크로·국내 경제 뉴스)을 한 편으로 따라간다. 숫자는 전부 코드가 계산하고 작성자는 해석만 한다.
- **비목표**: 일본 주간을 바꾸지 않는다. 일간에서 주간을 롤업하지 않는다(US·KR 과 다른 점 — 일본 주간은 독립 인사이트다). 원자재·해외 증시는 다루지 않는다.
- **반목표**(기술적으로 돌아가도 실패):
  - 전 영업일 JGB·며칠 늦은 콜금리를 「오늘」 숫자처럼 쓰는 것.
  - 컨센서스가 없는데 「예상 상회/하회」라고 쓰는 것.
  - 일간이 주간의 A/B 신호·임계값을 자기 판단처럼 다시 선언해 두 글이 다른 말을 하는 것.
  - 생활·코인 기사가 「경제 뉴스」 자리를 채우는 것.

## 실측 (2026-10-26 월 장 마감 뒤, 10/27 00:04 KST, 로컬 IP)
| 항목 | 결과 |
|---|---|
| yfinance `^N225` 일봉 | **10/26 행 없음**(10/23 까지). 마감 8.5시간 뒤에도 비어 있다 |
| yfinance `.T` 개별주 일봉 | 10/26 행은 있으나 **Close = NaN**(거래량만) — 7203·8035·6758 |
| yfinance `fast_info.lastPrice` | `^N225` 62189.65, 7203.T 3117 — 일경 공식·Yahoo!ファイナンス 표시와 일치. **`previousClose` 는 틀린다**(^N225 62726.83 vs 일봉 10/23 62693.16, 7203 3096 vs 3105) |
| yfinance 5분봉 | 마지막 봉 15:20-15:25 — 종가 경매가 빠져 종가와 다르다(^N225 62285.61) |
| 일경 공식 CSV `indexes.nikkei.co.jp/nkave/historical/nikkei_stock_average_daily_en.csv` | 200(301 리다이렉트 따라감), 10/26 종가 62189.65. **파일 꼬리에 복제·재배포 금지 문구** |
| `^TOPX` | yfinance 에 없음(404). TOPIX 지수 원천 미확보 — 주간은 1306 ETF 를 쓴다 |
| TOPIX-17 업종 ETF 1617-1633 | 17종 모두 `fast_info.lastPrice` 있음. **1629.T 만 283.3**(나머지 1.2만-7.7만) — 확인 필요 |
| MOF JGB 커브 `jgbcme.csv` | 최신 10/23 — **다음 도쿄 영업일 게시**(주간 설계와 같은 사실) |
| BOJ 시계열 API `stat-search.boj.or.jp/api/v1/getDataCode` | 200, **키 불필요**. 콜금리(FM01/STRDCLUCON) 10/22 까지(LAST_UPDATE 20261026) — 약 2영업일 늦다. 이용 고지: 크레디트 문구 필수, 서비스 공개 시 이메일 통지 요청, 과도한 호출 금지 |
| e-Stat API | **appId 없으면 인증 실패** — 등록 필요 |
| Yahoo!ファイナンス 뉴스 | 기존 수집기(`fetch_japan_news.py`)가 Actions 에서 이미 받는다. **끝난 JST 날짜만 동결**, cron 07:00·09:00 **Asia/Tokyo**(YAML 에 `timezone` 선언 — 초안의 「UTC」 기록은 틀렸다) |

## 결정 (「내 판단」 표시가 없는 것은 사용자 결정)

### 1. 독자 · 문체 — 내 판단
US/KR 과 같은 **PM 데스크 문서**: `<body data-register="da">`, `-다`, 용어 풀이 의무 없음, 「전략 코멘트」 헤더, buy-side 금지(`BANNED_LABELS`), 작업 용어 금지. `check_style.py` 그대로.

### 2. 발행 경로 · 시각 — 내 판단
- 글 `japan/daily/<YYYY-MM-DD>.html`, 목록 `japan/daily.json`, 스냅샷 `japan/data/daily/<YYYY-MM-DD>.json`, 이력 `japan/data/history/jp_daily.jsonl`(upsert).
  **`japan/posts/` 에 넣지 않는다** — `review/kinds.py` 가 `japan/posts` 를 `('jp','weekly')`·`MAX_AGE 3`·`japan/data/<KEY>.json` 으로 해석한다.
- `japan/index.html` 은 일간 최신순 + 주간 목록을 함께 보인다. 메뉴 「일본 시장」 링크는 그대로(이미 켜져 있다). sitemap 에 추가.
- **도쿄 거래일 19:00 KST 루틴**(`0 10 * * 1-5` UTC), 재시도 1회 21:00 KST. 휴장은 `data/market_holidays.json` `jp`. KR 18:00 과 한 시간 띄운다.

### 3. 배치 (사용자 결정 A + C 규칙)
평일 순서: **전략 코멘트 → 오늘의 장 → 주식 → 채권 → 엔화 → 매크로 → 일본 경제 뉴스 → 향후 확인 일정.**
- **이벤트일**: `report_date` 에 `japan/data/calendar.json` 의 `tier: major` 일정이 있으면 **매크로 절이 전략 코멘트 바로 다음**으로 온다. major = BOJ 결정회의 결과·전망 보고서, 단칸, 전국 CPI, 도쿄 CPI, GDP 속보, 매월근로통계(임금). 판정은 **코드**(`event_day()`)가 하고 렌더러가 순서를 정한다. 작성자는 순서를 고르지 않는다. 게이트가 순서를 검사한다(주간의 「신호는 코드에 고정」 원칙과 같다).
- 「시장 판단과 복기」(판단 원장)는 **v1 에서 뺀다 — 내 판단.** 토큰과 첫 발행 위험을 줄이려고. v2 후보(KR `stance.py` 를 시장 인자로 일반화).

### 4. 절별 데이터 계약
모든 수치는 스냅샷에서 나오고 **각 값에 `as_of`** 를 붙인다. 본문이 「오늘」을 쓸 수 있는 값은 `as_of == report_date` 인 것뿐이다.

| 절 | 값 | 원천 | 기준 |
|---|---|---|---|
| 주식 — 지수 | 닛케이 225 | yfinance `fast_info.lastPrice` (+ `regularMarketTime` 날짜 = report_date 확인), **일경 공식 CSV 로 대조**(허용 오차 0.01%) | 당일 종가. 전일 종가는 **`previousClose` 쓰지 않고** 자체 이력 → 없으면 일봉의 마지막 비-NaN 행 |
| 주식 — 지수 | TOPIX | **1306 ETF 근사**(주간과 같다), 표에 「TOPIX ETF(1306)」로 표시 | 당일 종가. 실제 TOPIX 지수 원천은 빌더가 JPX 공식에서 찾으면 교체 |
| 주식 — 업종 | TOPIX-17 업종 ETF 1617-1633 | yfinance `fast_info.lastPrice` | 당일 등락률. **이상값(가격이 직전 종가의 ±15% 밖, 1629 류)은 결측 처리**하고 표에서 뺀다 |
| 주식 — 움직인 종목 | 고정 대형주 유니버스(코드 상수, 한국어 표기 사전 포함) | yfinance `fast_info` | `common/movers.py` 재사용(기여 상·하위 + ±5% 묶음). 거래대금 상위는 v1 에서 뺀다(원천 없음) |
| 채권 | JGB 2·5·10·30년, 전일 대비 bp | MOF `jgbcme.csv`(`weekly_sources` 파서 재사용) | **전 영업일 기준** — 본문·표 모두 날짜 라벨 필수 |

> 2026-10-29: JGB 1순위는 네이버증권 당일 도쿄 마감, MOF 는 폴백 — `2026-10-29-japan-daily-naver-jgb.md` 가 이 행과 §13-5 의 JGB 부분을 대체한다.

| 채권 | 무담보 콜 O/N | BOJ API FM01/STRDCLUCON | 최신 관측일 라벨 필수(보통 2영업일 전) |
| 엔화 | USD/JPY, EUR/JPY, 100엔당 원 | yfinance `JPY=X`·`EURJPY=X`·`JPYKRW=X` | **수집 시각 컷(16:30 JST)** 을 라벨로. 등락은 전 거래일 같은 컷 스냅샷 대비, 첫 실행처럼 없으면 등락을 싣지 않는다 |
| 매크로 | 그날 나온 지표 값·전월/전년 대비 | v1: BOJ API(기업물가·서비스물가·단칸·통화량), 달력 | **컨센서스 없음** → 「예상·컨센서스·상회·하회」 금지. 이전 발표치·전년 대비로만 비교 |
| 일본 경제 뉴스 | 갈래별 ≤3 | §6 | 컷 16:30 JST |
| 향후 확인 일정 | 14일 | `calendar.json` | 원출처 확인 일정만(기존 불변식) |

- **`complete`**: 닛케이 종가가 있고 일경 CSV 와 맞으며 `as_of == report_date` 일 때만 참. 아니면 발행하지 않는다. 업종·종목·엔·JGB 결측은 해당 블록만 빠진다(비-코어). **실패한 원천은 `fetch_status` 에 남기고**, 코어 실패는 발행을 막는다(주간 불변식과 같다).
- 일경 CSV 는 **대조에만 쓰고 레포에 커밋하지 않는다**(복제·재배포 금지 문구). 공개 글에는 종가 숫자만 싣는다.

### 5. 수집 — Actions
- `collect-japan-daily.yml` + `scripts/collect_japan_daily.py` + `scripts/japan/daily.py`(순수 로직). cron 07:30 UTC(16:30 JST) 평일. 루틴은 규칙 10② 대로 **수집을 직접 dispatch** 하고 `gh run watch "$RUN" --exit-status` 로 기다린다. 멱등 가드는 수집 **뒤**.
- 커밋은 `bash scripts/ci/push_with_retry.sh`.
- 이력 jsonl 은 매 실행 upsert, 다음 날 아침 수집(또는 다음 실행)이 yfinance 일봉이 채워지면 **어제 종가를 일봉과 대조해 차이를 notes 에 남긴다**(교정은 하지 않는다 — 발행본은 그때 숫자다).

### 6. 일본 경제 뉴스 — 내 판단
- **주간 수집 계약을 건드리지 않는다.** 기존 수집기는 끝난 날만 동결하고 주간이 그 파일을 읽는다. 일간은 별도 파일 `japan/data/news/daily/<date>.json` 을 일간 수집 잡이 **16:30 JST 컷까지의 당일 목록**으로 만든다. 동결 개념 없음 — 그날 저녁 스냅샷이다.
- 선별 로직(`japan/news.py` 의 매체 허용 목록·유료 제외·정례 단신 제외·같은 사건 판정)은 그대로 재사용한다.
- 갈래: **macro → policy → industry → market** 순, 갈래당 ≤3. `global`·`insight` 는 일간에서 뺀다(「국내 경제 뉴스 위주」). 단 일본은행 발표문·총재 발언은 macro 로 들어온다(기존 분류).
- 요약은 기존 `us/news_summary.py`(WIF) 재사용, `summary_problem()` 이 None 인 것만.
- 게이트는 `us/news_gate.check` 를 `check_news.py --market jp-daily` 로(`categories` 인자), KR 과 같은 방식.

### 7. 매크로 — 원천 단계
- **v1**: BOJ API(키 불필요)로 기업물가지수·서비스물가·단칸·통화량, 콜금리. 시리즈 코드는 하드코딩하지 않고 `/getMetadata` 로 이름에서 해석(KR ECOS 와 같은 방식). 호출은 하루 몇 번 이내.
- **v2**: e-Stat(전국·도쿄 CPI, 노동력조사, 가계조사, 매월근로통계), 내각부 GDP. **appId 가 필요하다 — 사용자 몫.**
- 달력 `calendar.json` 에 major 일정을 원출처(총무성·후생노동성·내각부·BOJ) 확인 후 추가하고 `tier` 필드를 붙인다. 확인 못 한 날짜는 넣지 않는다(기존 불변식 — 도쿄 CPI 가 지금 빠져 있는 이유). **v1 의 이벤트일 규칙은 달력에 있는 일정에만 작동한다.**

### 8. 게이트 순서
`apply_readability.py` → **`check_japan_daily.py`(신규)** → `check_news.py --market jp-daily` → `check_readability.py --strict` → `check_style.py`.

`check_japan_daily.py` 가 막는 것:
1. 본문 숫자가 스냅샷 숫자 집합 밖(US `number_sources` 방식, 조·억 정규화 포함).
2. `as_of != report_date` 인 값(JGB·콜금리·엔 컷)을 쓴 문단에 날짜 라벨이 없다. 「오늘 JGB」 류.
3. 절 순서가 `event_day()` 결과와 다르다. 절 유일성·필수 절 누락.
4. 매크로 절의 예상·컨센서스·상회·하회.
5. 주간 신호 어휘(「A 경로·B 경로」, 신호 집계, 임계값 선언).
6. BOJ 크레디트 문구 누락(§10).
7. `<div>` 미닫힘(`readability.section_div_breaks`)은 `check_readability` 가 이미 본다.

### 9. 루틴 · 잠금 · 검토 — 내 판단
- 오케스트레이터 `.claude/JAPAN_DAILY_ORCHESTRATOR.md`, 작성자 `.claude/agents/japan-daily-writer.md`. **모델 sonnet-5, 커넥터 없음**(KR 과 같다).
- `routine_due.py` 에 `decide_jp_daily`(자체 `STALE_MIN 120`, 자체 `lock_name` — 주간 잠금과 공유하지 않는다).
- `review/kinds.py` 에 `'japan/daily': ('jp', 'daily')`, 데이터 경로는 스냅샷 + 일간 뉴스 파일(자기완결 — 러너가 그것만으로 재검사). 시간당 러너의 `DAILY` 에 `jp` 추가 — **codex 호출이 하루 1건 는다.**
- `AGENTS.md` 파이프라인 표에 한 줄, `scripts/japan/CLAUDE.md` 에 일간 절(체인 32,768 B 예산 확인).

### 10. 토큰 예산 — 내 판단
- 작성자 지시문 **≤ 20 KB**(KR 58 KB, US 74 KB 를 복제하지 않는다). 공통 문체는 `STYLE_EXEMPLARS.md` 의 필요한 절만 가리킨다.
- 작성자에게 넘기는 입력은 스냅샷 JSON + 일간 뉴스 파일 + 직전 일간 1편(연속성)뿐. 웹 검색 없음.
- 전략 코멘트는 두세 문단. 서술형 본문 상한은 KR `check_weight` 와 같은 경고만(5,000자).

### 11. 주간과의 관계
- 주간이 「정상화를 이어갈 수 있나」 질문과 A/B 신호를 가진다. 일간은 **서술과 확인 일정**만 한다. 일간이 주간을 인용할 수는 있다(「지난 주간의 신호 집계는 …」은 금지, 링크만).

### 12. 규정 준수
- **BOJ API 크레디트**를 일간 글 꼬리에 그대로 싣는다: 「This service uses the API provided by the "Bank of Japan Time-Series Data Search." The Bank of Japan does not guarantee the content of the service.」(한국어 병기 가능, 영문 원문 유지).
- BOJ 는 서비스 공개 시 `post.rsd17@boj.or.jp` 로 통지를 요청한다 — **외부 전송이라 사용자 결정.**
- 일경 CSV 는 대조 전용(§4).

## 사용자 몫
1. BOJ 통지 이메일을 보낼지(보낸다면 사용자가 직접).
2. v2 매크로를 위한 e-Stat appId 등록 → 레포 시크릿 `ESTAT_APP_ID`.

## 빌더 몫
- 대형주 유니버스 목록과 한국어 표기 사전(도요타 등 표기 통일), `common/movers.py` 인터페이스 맞추기.
- 1629.T 이상값 원인, TOPIX 지수 공식 원천 탐색(스푸핑 없는 공개 경로만).
- BOJ API 시리즈 해석, 달력 major 일정 추가(원출처 URL 필수).
- 스냅샷 스키마 세부, 렌더러 표 형식(US 일간 표 재사용).

## 첫 발행 전 검증
- 도쿄 거래일 16:30-19:00 JST 에 Actions 에서 수집을 돌려 **닛케이 종가를 일경 공식과 대조**, `fast_info` 의 `regularMarketTime` 신선도, 업종 17종 결측, BOJ API·Yahoo 접근(Actions IP)을 확인한다.
- 로컬 초안 1편을 게이트 전부 통과시킨 뒤 사용자에게 보이고, 그다음 루틴을 켠다.

## 단계
- **v1**: 주식·채권·엔·매크로(BOJ API·달력)·경제 뉴스·일정, 이벤트일 규칙, 게이트, 루틴, 검토 러너.
- **v2**: e-Stat 매크로, 판단 원장·복기, 실제 TOPIX 지수, 거래대금 상위.

## 13. codex 설계 검토 반영 (2026-10-27) — **위 절과 충돌하면 이 절이 우선한다**

판정 표는 `../plan.md` 「2026-10-27 — 일본 일간」. 계약만 적는다.

1. **세션 고정.** 루틴이 잠금 **전에** `target_session`(JP 달력 기준 오늘 도쿄 거래일)을 정하고 수집·작성·게이트·커밋 전 단계에 넘긴다. `prev_session` 도 달력으로 정한다. `routine_due.py lock-name` CLI·`STALE_MIN`·세션 함수를 `jp_daily` 로 확장하고, 수집·작성 전후·커밋 직전 renew, 쓰지 않고 끝나는 모든 경로 release, 실패 알림. 주간의 dispatch nonce 방식 재사용. 휴장·주말·자정·120분 경계 테스트.
2. **종가 계약.** 닛케이 `complete` = 일경 공식 CSV 에 `target_session` 행이 있고 `fast_info.lastPrice` 와 0.01% 안. ETF·개별주는 5분봉 마지막 봉의 날짜가 `target_session` 일 때만 `lastPrice` 채택, 아니면 그 종목 제외. 등락률은 `prev_date == prev_session` 인 분모가 있을 때만(값·원천·날짜 보존). 여러 거래일 변화는 양 끝 날짜를 밝힌 별도 항목.
3. **분할·이상값.** ±15% 는 제외가 아니라 재검증 트리거 — 분할·단위·조정 기준을 양 끝에서 맞춘 뒤에도 실패한 것만 결측(사유·유효 업종 수 기록). 1629 는 2026/4/1 수익권 분할이 있다(운용사 고지).
4. **엔 컷.** 5분봉에서 **16:30 JST 에 끝난 봉**의 종가, `basis`·봉 시작/끝·시간대 기록. 없으면 결측. 오늘·`prev_session` 같은 컷이 모두 있을 때만 변화율. `JPYKRW=X` ×100 = 100엔당 원(배수 고정). 주간 USD/JPY 는 16:00 ET 컷이라 값이 다르다 — 표 각주로 표시.
5. **시점 필드.** 값마다 `period`(관측 기간·관측일)·`released`(공표일)·`fetched_at`·`unit`·`freq`. 「오늘」 은 `period == target_session` 인 값만. 매크로는 「오늘 발표」 = `released == target_session` 이고 API 에 그 `period` 가 반영된 경우만; 달력엔 있는데 미반영이면 `pending` 상태로 「발표 예정·미반영」 만 쓴다. JGB bp = 최신 관측일과 그 직전 채권 영업일의 차. 신선도: JGB 는 `prev_session` 보다 오래되면 결측, BOJ 시리즈는 시리즈별 예상 지연(콜 O/N 3영업일)을 넘으면 결측.
6. **달력.** 회의 기간 행과 결과 공표 행(`kind: release`)을 구분한 **일간 overlay** `japan/data/calendar_daily.json`(주간 행의 의미는 건드리지 않는다). 각 행 `source`·`checked_at`. 스냅샷에 당일 이벤트·14일 일정·달력 해시를 고정하고 재검사는 스냅샷만 쓴다. `event_day()` 는 `kind: release` 이고 `tier: major` 인 당일 행만.
7. **발행 스냅샷.** 수집기는 `japan/data/daily/candidate/<date>.json` 만 쓴다(concurrency 그룹으로 직렬화). 발행 단계가 그것을 `japan/data/daily/<date>.json` 으로 복사·커밋하고 `daily.json` 에 커밋 id 를 남긴다. **발행된 날짜는 수집기가 덮지 않는다.** 다음 날 대조는 `japan/data/daily/checks.jsonl` 에 따로. 이력 jsonl 은 발행 스냅샷 기준.
8. **사후 오류(내 판단).** 공표 시차·반올림 차이는 고정. **검증된 오류는 review-gate 정정**(US/KR 과 같은 절차)으로 본문·발행 스냅샷을 고치고, 다음 날 분모는 검증값.
9. **미발행(내 판단).** 21:00 재시도까지 코어가 안 되면 **보충 발행하지 않는다.** 최종 실패 PushNotification, `daily.json` 에 넣지 않음. 수집 후보는 남아 다음 날 분모로 쓰인다(단 2번 규칙대로 `prev_session` 검증).
10. **움직인 종목.** 「지수 기여」 개념을 쓰지 않는다 — 고정 대형주 표본의 등락률 상·하위와 ±5% 묶음만. 일본 어댑터를 두고 `common/movers.py` US/KR 경로는 바꾸지 않는다. 묶음별 원인은 일간 뉴스 파일의 guid 근거가 있을 때만, 없으면 「확인된 재료 없음」. `common.movers.check` 를 신규 게이트에서 호출.
11. **게이트 보강.** `check_japan_daily.py` 가 추가로: `complete`·`target_session`·파일명·스냅샷 날짜 일치, 코어 값 유한·양수, `data-register="da"` 존재, `[확인필요]`·미완 마커, 필수 절·비-코어 결측 블록 공존 규칙. 표는 전부 코드 렌더. 산문 핵심 값(지수·JGB·엔·콜·지표)은 `<span data-ref="필드">` 로 묶어 값·단위·기간 대조, 나머지 숫자는 집합 검사. 뉴스 숫자는 그 guid 요약 안에서만. **컨센서스·예상 비교 금지는 전 절**(조건부 전망 문장은 허용). Playwright 390·1280 `scrollWidth == viewport` 를 발행·정정 양쪽에서.
12. **뉴스.** `check_news.py --market jp-daily` 어댑터가 경로(`japan/data/news/daily/<date>.json`)·절 제목(「일본 경제 뉴스」)을 넘기고, 일본 일간 전용 검사가 갈래 허용(macro·policy·industry·market)·갈래당 ≤3·같은 사건·절 위치·기사 JST 날짜 = `target_session`·16:30 컷을 강제한다. 컷 필터는 후보 상한 **전**. 공식 BOJ 연설은 일간 전용 변환에서만 insight → macro(공유 분류·요약 프롬프트 불변). 일간 갈래 순서는 일간 상수로.
13. **검토 러너.** `kinds.py` 를 시장(`jp`)·디렉터리 section(`japan/daily`)·주기(`daily`)로 나눠 날짜 해석·quota·evidence(발행 스냅샷 + 일간 뉴스)·프롬프트·게이트(`check_japan_daily.py`)·corrector 허용·목록 경로까지 연결. 기존 `japan/posts` 주간의 evidence·gate·신선도 회귀 테스트.
14. **지침 예산.** AGENTS.md 표를 고치기 전에 US leaf 의 이력을 spec 으로 옮겨 여유를 만든다(현재 US 체인 31,727 / 31,744 B). 일간 계약은 기존 `scripts/japan/CLAUDE.md` 에 절로 — 새 leaf·LEAVES 등록 없음.
15. **목록·sitemap.** `japan/index.html` 은 일간 기본 표시 + 주간 탐색, metadata·JSON-LD·소개문 갱신(「매주 일요일」 문구). 날짜 중복 replace·빈 목록. sitemap 은 기존 전 경로 보존, 일간 URL 추가만.
16. **cron.** `collect-japan-daily.yml` 은 `cron: '30 16 * * 1-5'` + `timezone: 'Asia/Tokyo'`. 예약 시각·실행 시각·데이터 컷을 스냅샷에 따로 기록.

### 구현 메모 (2026-10-27)
- Playwright `scrollWidth` 검사는 클라우드 루틴에서 돌지 않는다(US·KR 루틴도 같다 — `check_readability.py` 가 레이아웃 규칙을 본다). 첫 초안(10/26 세션)은 로컬에서 390·1280 모두 통과했다.
- 일본 일간은 검토 러너의 자동 Claude 정정(`DAILY`)에 넣지 않았다 — codex 초안 → 수동 review-gate.
- 자정(JST)을 넘긴 뉴스 수집은 목록 시각이 날짜뿐이라 컷을 증명할 수 없어 기사가 빠진다. 루틴이 19:00 KST 에 직접 띄우므로 평소엔 해당 없음.
