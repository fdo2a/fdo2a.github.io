# US 뉴스 매체 넓히기 — 미국 다섯 갈래의 매체 돌려 뽑기 (2026-11-12)

사용자: 「미국 뉴스가 지금 다 cnbc」. 방향 확인(11/12): 갈래마다 CNBC 는 1건을 **목표**로 하고 나머지는 다른
매체로 채운다. 다른 매체가 막히거나 시간이 모자라면 CNBC 로 채운다. 조용한 날은 3건보다 적어도 된다.

코드: `scripts/us/news.py`(`EXTRA_FEEDS`·`identify`·`reconcile`·`same_story`·`candidates`·`lanes`·`confirm`·
`legacy_fill`·`_HOST_BOILERPLATE`), `scripts/fetch_news.py`(`Budget`·`bounded`·`harvest_extra`·`spread_stage`·
`existing_index`). 시험: `scripts/us/tests/test_news_spread.py`, `test_fetch_news_spread.py`,
고정물 `tests/fixtures/same_story_pairs.json`.

## 원인 (실측)

- 미국 다섯 갈래(politics·economy·macro·industry·ai)는 9/23 이후 매 판 15건 중 15건이 CNBC 였다. `FEEDS` 의
  politics·economy·industry·tech·pool 이 전부 CNBC 였고, 유일한 비-CNBC `finance.yahoo.com/news/rssindex` 는
  10/06 부터 404(브라우저 지문으로도 안 열림)였다. 살아 있던 9/25-10/05 에도 0건 — `select()` 가 갈래별 최신
  3건이라 매체를 보지 않았다.
- 본문·요약 단계는 원인이 아니다. 11/05-11/11 다섯 판 합계(MLCC 제외):

| 단계 | CNBC | 다른 매체 |
|---|---|---|
| 후보(미국 다섯 갈래, 11/12 다시 받아 셈) | 191 | 0 |
| 선정 | 84 | 30 (전부 글로벌·리포트 칸) |
| 본문 확보 | 82 | 30 |
| 요약 | 82 | 30 |
| 발행본(`data-news`) | 60 | 25 |

  과거 판의 매체별 후보 수는 복원할 수 없었다(JSON 이 선정분만 남겼다) — 그래서 `funnel` 을 더했다.

## 매체 실측 (2026-11-12, 로컬 Mac, 피드 + 기사 3건 본문)

| 매체 | 결과 | 채택 |
|---|---|---|
| PBS NewsHour(politics·economy), NBC(politics·business), CBS(politics·MoneyWatch), ABC(politics·business), Guardian US(politics·business), Fortune, TechCrunch, Ars Technica, Axios | 피드·본문 ○ | ○ |
| Fox Business(economy·markets), The Verge | ○ — 첫·끝 문단이 안내문 | ○ (`_HOST_BOILERPLATE`) |
| NPR economy | 글 기사 ○. 음성 꼭지는 메뉴 글자와 고지문뿐인 900자 껍데기가 400자 하한을 넘긴다 | ○ (안내문을 걸러 본문 없음으로) |
| NPR politics | 대부분 음성 꼭지 | ✕ |
| Politico | 본문 1.2-1.7천 자, 끝에 뉴스레터 문구 — 일부만 열린다 | ✕ |
| Yahoo Finance 종합(rssindex·topstories) | 404 | ✕ (FEEDS 에서도 삭제) |
| The Hill | 피드 ○, 기사 403 | ✕ |
| MarketWatch·WSJ | 기사 401 | ✕ |
| NYT | 기사 403 | ✕ |
| WaPo | 기사 시간 초과 | ✕ |
| AP | 피드 없음 | ✕ |
| Semafor·Quartz | 본문 짧음·피드 1건 | ✕ |
| Business Insider | ○ 이지만 생활 기사 위주 | ✕ |
| Investing news_25·95 | 피드에 날짜 없음, 유럽 지표·종목 슬라이드 위주 | ✕ |
| Fox 업종별(industrials·energy·healthcare·retail) | 400 | ✕ |
| Guardian 업종별 | 영국 기사 위주 | ✕ |

로컬 실수집(11/12, 요약·지역 필터 없이, 최종 코드): 미국 15칸 = CNBC 3, Fortune 2, CBS 2, Fox Business 2,
Verge·Guardian·NBC·PBS·ABC·NPR 각 1. 글로벌 칸은 예전대로 `FEEDS['global']` 출처뿐. 새 피드 수집 6.2초, 다섯 갈래
확정 9.0초, 본문 실패 0건. 그 실행에서 CBS politics 피드가 한 번 406 을 냈고 `notes` 에 한 줄 남은 채 나머지로 채웠다.
네 번 돌린 실수집에서 CNBC 는 매번 15칸 중 3건이었다.

**Actions IP 에서는 재지 않았다.** 푸시 전에는 잴 방법이 없다. 그래서 막힌 매체가 스스로 빠지고 기록되게 만들었다.
새 매체 18개 피드를 20초 간격으로 두 번 받았을 때 기사 URL 은 전부 같았고 쿼리 문자열이 붙은 URL 은 없었다.

**산업 칸의 한계**: 다른 매체에는 CNBC 같은 업종 전용 피드가 없다. 종합 비즈니스 피드는 「로마노프 팔찌 경매」
「프라다 전시」「메디케어 가입 안내」가 섞여, 제목이 `_INDUSTRY` 낱말에 걸릴 때만 받는다. 산업 칸은 CNBC 비중이
높게 남을 수 있다.

## 구조

1. **피드** — `EXTRA_FEEDS` 18개. `FEEDS` 에 넣지 않았다: `collect_contested.py` 가 `FEEDS` 묶음을 그대로 돌며
   자기 시간 상한을 쓴다. 묶음은 「어떻게 걸러 받나」다: `x_politics`·`x_economy` 는 그 갈래로,
   `x_business` 는 AI·매크로 낱말 또는 `_INDUSTRY`, `x_pool` 은 AI·매크로 낱말만. 의견·영상·라이브·방송 회차는
   분류 **앞**에서 뺀다(`skipped()`). **새 피드의 해외 정책 기사(지역어 + 정책·경제 낱말)는 버린다** —
   글로벌 칸으로 보내면 시간 상한이 없는 예전 길로 본문을 받고(codex 구현 검토 3회차), 미국 갈래로 돌리면
   정치 칸에 「Ukraine … Putin」이 실린다(11/12 실수집). 기존 피드에서 이 규칙은 미국 칸에 해외 정책 기사를
   들이지 않는 그물이었고, 지역 필터(Jev)는 30초 안에 못 물은 행을 그대로 둔다. 글로벌 칸의 출처는
   `FEEDS['global']` 그대로다. 정책 낱말이 없는 해외 기업 기사는 산업·AI 에 남는다(10/28 사용자 결정).
2. **식별** — 새 피드 행의 guid 는 **프래그먼트만 뗀 원 URL**. `reconcile()` 이 지역 필터·dedupe 앞에서 그날
   파일의 guid 와 후보를 직접 대조해, 매체도 URL 도 다른데 guid 가 같은 기사를 하나만 남긴다.
3. **고르기** — `select(…, defer=ROTATE)` 가 미국 다섯 갈래를 건너뛰고, `spread_stage()` 가 갈래마다
   `confirm()` 을 돌린다. 매체별 줄을 돌며 한 바퀴에 매체당 확정 1건, 본문이 안 열리면 같은 줄의 다음 기사,
   확정한 것과 같은 이야기면 건너뜀, 36시간 창(확정은 시각 필수). 본문 실패 행은 `items` 에 넣지 않는다.
4. **시간** — 새 피드 60초, 다섯 갈래 단계 전체 240초(그중 돌려 뽑기 150초). 요청은 `bounded()` 가 데몬
   스레드에서 돌리고 남은 시간만 기다린다. 돌려 뽑기 시간이 끝나면 그 갈래의 남은 자리와 뒤 갈래는
   `legacy_fill()`(기존 피드 최신순, 창 없음)로, 그것도 단계 마감 안에서만. 마감에 걸리면 덜 찬 채로 저장한다.
   한 실행에서 요청이 두 번 실패한 매체는 그 실행에서 더 묻지 않는다(「추출 실패」는 세지 않는다).
5. **기록** — 그날 JSON 의 `funnel`: `categories[갈래][매체] = {candidates, tried, with_body, chosen, fail}`,
   `seconds`, `stopped`, `blocked`, `legacy_filled`, `guid_collisions`. 발행 게이트는 읽지 않는다.

mlcc·global·insight 의 길, 동결(`frozen`), `carry_summaries`, 지역 필터 설정, 요약 호출 수는 그대로다.

## 푸시 뒤 첫 수집에서 볼 것

- `funnel.categories` — 매체별 `fail` 에 `HTTP 403`·`Late`·`TimeoutError` 가 몰린 매체가 Actions 에서 막힌 곳이다.
  `blocked` 에 매일 오르는 매체는 `EXTRA_FEEDS` 에서 뺀다.
- `funnel.seconds` 와 수집 run 의 뉴스 단계 시각 — 지금 4분. 2분 넘게 늘면 `SPREAD_BUDGET`·`STAGE_BUDGET` 을 줄인다.
  **루틴의 `timeout 900` 안에 끝난다는 보장은 없다**(피드 수집·글로벌·칼럼·요약에는 원래 상한이 없다).
- `notes` 의 `x_…` 줄(피드 실패), `extra_time_cap`·`spread_time_cap`·`stage_time_cap`.
- `region_filter.asked/answered` — 정치·경제·매크로 후보가 54-61건에서 200건 안팎으로 는다(`DEADLINE_SHORT` 30초).

## codex 설계 검토 (4회, 전부 DESIGN NOT OK — 지적 13 → 7 → 4 → 2)

회차마다 지적이 좁아졌고, 같은 두 주제(식별·시간)가 되풀이돼 5회차는 돌리지 않고 사용자 확인 뒤 구현했다.
재현 입력은 전부 시험으로 옮겼다. 지적별 결정은 `../plan.md` 2026-11-12 표에 있다. 뼈대만:

- 후보를 미리 6건으로 자르면 전부 403 일 때 CNBC 가 후보에 없다 → 후보 상한 없이 고르면서 본문 확인.
- 본문 전에 같은 사건을 접으면 대체본이 사라진다 → 확정된 기사에 대해서만 접는다.
- 평평한 회전 순서는 건너뛴 뒤 매체 상한을 못 지킨다(A1,B1,C1,A2,B2 에서 B1 이 A1 과 같은 이야기) → 줄 단위.
- 한 바퀴 도중 상한을 넘긴다 → 확정 직후 종료.
- guid: 매체 간 원 guid 충돌 → 전체 유일성 → 그날 파일에만 있는 guid → `_norm_url` 이 `?ref=1`·`?ref=2` 를
  하나로 만든다. 세 번 고친 끝에 「새 피드 guid = 원 URL」과 `reconcile()` 로 정리됐다.
- 시간: 예산 없음 → 60·180초가 실제 상한이 아님 → 옛 길의 재시도 누락 → PDF 요청(`fetch_bytes`)이 마감을 우회.
- 공유 `_BOILERPLATE` 를 넓히면 일본 뉴스·텔레그램·쟁점 수집의 채택이 바뀐다 → 호스트별, `host=` 인자.
- 「짧다」는 지금 추출기로 「추출 실패」와 못 가른다 → `funnel` 사유에서 뺐다.

## codex 구현 검토 (3회차까지 IMPL NOT OK — 지적 3 → 3 → 1)

- 1회: `&` 가 든 guid 는 `&amp;` 로 실려 `summary_violations()` 가 막는다 → 그런 URL 의 기사를 받지 않는다 /
  식별은 둘로 하고 dedupe 가 합친다 → 새 피드 행의 URL 열쇠는 guid / 옛 길이 막힌 매체에 다시 묻는다.
- 2회: 마지막 후보에서 시간이 끝나면 옛 길을 건너뛴다 → `hit or spread.over()` / dedupe 가 `?ref=1`·`?ref=1/` 을
  합친다 → 쿼리가 있으면 글자 그대로 / 병합이 기존 피드 행에 `_extra` 를 채운다 → 그룹에 기존 피드 행이 있으면 뗀다.
- 3회: 새 피드 기사가 글로벌 칸으로 분류되면 상한 없는 예전 길로 본문을 받는다 → 새 피드 행은 글로벌로 안 보낸다.

## 알려진 한계

- **같은 이야기 묶기는 완벽하지 않다.** 고정물 47쌍(같은 이야기 25, 다른 이야기 22)에서 같다고 본 쌍은 전부
  맞았고 같은 이야기 쌍의 84%(21/25)를 잡는다. 「같다」는 사건이 아니라 큰 이야기다 — 엔비디아 CEO 건처럼
  하루에 기사가 수십 건 나오는 이야기는 갈래마다 한 자리만 차지한다. 처음 기준(제목 자카드 + 제목·요약의
  고유명사 2개·낱말 자카드 0.12)은 64% 였고, 첫 실수집에서 정치 칸에 같은 선거가 두 번 실려 「제목끼리
  고유명사 2개 공유」를 더했다. 넓은 표본에는 나라 이름 둘(Russia·Ukraine)을 나눠 가진 다른 기사가 묶이는
  오탐이 있다 — 비용은 그 갈래에서 기사 한 건을 건너뛰는 것. 놓친 중복은 작성자가 거른다.
- **CNBC 1건은 목표지 한도가 아니다.** 본문이 열리는 매체가 2곳뿐이면 CNBC 2건, 시간이 다 되거나 다른 매체가
  전부 막히면 CNBC 3건.
- **다른 매체로 쏠릴 수 있다.** 11/12 모의에서 경제 칸은 36시간 안의 후보가 Fox Business 와 NPR 뿐이었다.
- 과거 날짜를 `--refresh` 하면 실행 시점의 기사가 들어온다 — 피드는 과거를 주지 않는다. 기존 동작이다.
- `--refresh` 는 선정을 바꿀 수 있다 — 기존 동작이고, 그래서 요약된 날은 동결한다.
- 새 매체가 기사 URL 을 바꾸면 그 기사는 새 기사로 보인다(요약이 이월되지 않는다).
- `scripts/us/CLAUDE.md` 에는 이 문서의 안내 줄이 없다 — us 체인의 바이트 여유가 29 B 다. 안내는
  `us/news.py`·`fetch_news.py` 의 주석에 있다.
