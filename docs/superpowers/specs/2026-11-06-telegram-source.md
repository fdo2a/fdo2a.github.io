# 텔레그램 채널을 일간 브리프의 출처로 (2026-11-06)

> 설계 초안 그대로 아래에 두고, 맨 위에 **실제 구현과 다른 점**과 codex 설계 검토 판정을 적는다. 판정 표 전문은 로컬 `report/plan.md` 2026-11-06 「텔레그램을 일간 브리프의 출처로」.

## 구현에서 바뀐 것 (codex 설계 검토 14건 반영)

- **종류 셋**: view(증권사 머리말) / **report**(원문 링크 → 원문 기사 본문을 받아 요약, 「매체에 따르면」) / opinion(그 밖, 「…라는 의견도 나왔다」, 본문이 밝힌 매체 이름). 원문을 못 받거나 매체를 모르면 report 는 opinion 으로 내려간다.
- **링크를 달지 않는다** — US 「report does not link out」(`source_gate` 무변경). 출처는 문장 안 이름.
- **id = `채널/번호`**(채널 간 충돌 방지).
- **채널별 커서**(`channels.<ch>.last_id/last_dt`): 실패 채널은 전진하지 않는다. 60쪽 상한은 전진하되 `hole` 을 남긴다(의견 출처라 몇 건 누락을 감수 — 복구 루프는 넣지 않았다). 직전 커서가 72시간보다 오래면 72시간만.
- **동결**: 그날 파일에 요약이 1건이라도 있으면 다시 받지 않는다(`--refresh` 만). 재수집은 그날 **이전** 파일의 커서로 같은 창을 다시 만든다.
- **요약**: 자체 요약기 `common/tg_summary.py`(짧은 글은 지시문 목표 60~260자, 받는 폭은 60~400자 — 2026-11-11, 11/06·11/09 짧은 글 44건 중 6건이 261~390자로 버려졌고 그중 2건이 키움 견해였다, 원문 8자 이상 일치가 요약의 80% 넘으면 「원문 복제」로 버림). report 는 뉴스 수집과 같은 `summarize_one`·띠. 로그에 본문 없음. 요약 실패는 `summary_note`·`stats` 에 남고 루틴 최종 보고로 간다.
- **스냅샷**: 두 오케스트레이터 모두 `git show HEAD:<path>` 로 워크스페이스에 복사, `report_date` 검증, 작성자와 게이트가 같은 파일.
- **게이트** `common/telegram_gate.py`: 표식 안 — 이름·틀·수치(`measure_numbers` ⊆ 그 요약)·요약 겹침 ≥0.3, 표식 밖 — 애널리스트 이름·「증권사 + 연구원/…봤다」·요약과 0.7 이상 겹치는 25자+ 문장, 어디든 — 「텔레그램」·t.me·채널 이름. 에디터 노트는 제외. 「키움증권」 단독은 상장 종목 이름이라 허용.
- **기계로 못 막는 것**: 요약과 같은 낱말·수치로 반대 뜻을 쓴 문장 — 발행 후 검토 몫(review_gate 입력에 텔레그램 파일을 넣는 것은 빚).
- 픽스처는 실제 페이지에서 본문·미리보기·전달 작성자를 지운 구조용 한 장뿐이다(공개 레포에 원문을 두지 않는다).

---

# 텔레그램 채널을 일간 브리프의 출처로 (연결 설계, 2026-11-06)

사용자 지시(순서대로): 「텔레그램 글을 하나의 source 로 활용」 → 「증권사만 인용, 나머지 재료」 → 「재료(사실 근거 아님)이라고 하지 말고 "이런 의견도 있었다" 라는 식으로 얘기해. 그리고 원문 출처가 있으면 그걸 출처로 달고」. 약관(텔레그램 자동 수집·AI 활용 금지)은 사용자가 알고 감수 — 재지적 불필요. 섀도 측정 단계는 사용자 의도가 아니었다(측정 결과를 기다리지 않는다).

**범위(1차):** US 아침 브리프(`brief-report-writer`)와 KR 마감 브리프(`kr-report-writer`). 뉴스 글 두 개는 2차. 첫 적용 KR 11/09(월) 18:00, US 11/10 07:30 KST 판(뉴욕 11/09). 증권사 아침 글(07:3x-08:00 KST)은 US 수집(07:30 KST, 겨울) 뒤라 US 에는 하루 늦게, KR 에는 같은 날 들어간다 — 실측.

## 채널과 글의 종류

| 채널 | 묶음 | 기본 시장 | 증권사 견해로 인정하는 글(코드 규칙) | 인용 이름 |
|---|---|---|---|---|
| hedgecat0301 | firm | both | 본문에 「키움 한지영」 머리말 `[..., 키움 한지영]` | 키움증권 한지영 |
| kwusa | firm | us | 본문이 `[키움` 으로 시작(예 `[키움 미국전략/주식 김승혁]`, `[키움증권/김진구]`) — 머리말의 이름을 뽑는다 | 키움증권 <이름> |
| lim_econ | firm | both | `<오늘 개장전 꼭 알아야 할 5가지` 류(Bloomberg 요약)·전달 글 제외, 나머지 본인 글 | 한화투자증권 임혜윤 |
| d_ticker, aethersemiconductor | individual | both | — | — |
| FastStockNews | relay | kr | — | — |
| FastStockNewsUSA, insidertracking | relay | us | — | — |

- **view**: 위 규칙을 만족하는 firm 글. 발행본에서 「키움증권 한지영 연구원은 ~로 봤다」처럼 **증권사·사람 이름으로 인용**한다.
- **opinion**: 그 밖의 모든 글(firm 의 비견해 글 포함 — kwusa 의 `*연합인포맥스*` 전재, lim_econ 의 Bloomberg 요약). 발행본에서 **「~라는 의견도 나왔다/있었다」** 꼴로 쓴다. 원출처가 있으면 그것을 출처로 단다:
  - 원문 링크(뉴스·공시·리서치 도메인) → 매체명 + URL
  - 본문의 출처 표기(`*연합인포맥스*`, `- 블룸버그`, `Bloomberg>`, `진시데이터`, `로이터` 등 사전) → 매체명(URL 없음)
  - 둘 다 없음 → 출처 없이 「시장 일각에서는 ~라는 의견도 있었다」
- 채널 이름·「텔레그램」·`t.me` 는 발행본 어디에도 쓰지 않는다.

## 수집 (`scripts/fetch_telegram.py`, 공개 레포 Actions)

- 섀도에서 검증한 파서·링크 분류·시장 규칙을 `scripts/common/telegram.py` 로 옮긴다(섀도 레포 코드를 복사, 테스트 포함).
- `--market us|kr --datadir <data|kr/data> --bodydir _workspace/telegram --date <report_date>`.
- 창: `[직전 수집 파일의 collected_utc, 지금)`. 직전 파일은 같은 시장 `telegram/` 에서 report_date 이전 최신(7일 안). 없으면 `지금-24h` 이고 `window_note` 에 적는다. 주말·휴장 뒤 월요일은 금요일 수집부터 이어진다.
- 채널마다 `t.me/s/<ch>` → `?before=` 로 창 시작에 닿을 때까지, 채널당 최대 30쪽, 요청 간격 1.5초. 상한에 걸리면 그 채널 `truncated: true`. 파싱 필수 필드 0개 = 채널 실패(빈 성공 아님).
- 고르기(코드): 시장 판정(firm·individual 의 both 는 글 단위 규칙, unknown 은 버림) → 잡담 제외(본문 40자 미만이면서 링크 없음) → 같은 원문 링크 키를 공유하는 글은 하나로(먼저 올라온 것, 출처 있는 것 우선). 상한 views ≤ 6, opinions ≤ 12. opinion 순위 = 출처 있음(+2) · 2채널 이상이 같은 원문(+2) · 시장 낱말 수 · 최근.
- 요약: 고른 글의 본문을 `_workspace/telegram/<id>.txt`(gitignore 된 `/_workspace/`) 에 쓰고 기존 `us.news_summary.summarize_items(…, system=SYSTEM_TG)` 로 `summary_ko`. `SYSTEM_TG` 는 새 상수: 「필자의 견해·전망은 필자의 것으로 남긴다(단정 금지)」「본문에 없는 수치를 만들지 않는다」. 요약 실패·한국어 검사 실패 건은 파일에 남기되 `summary_ko` 없음 → 작성자가 쓰지 않는다.
- 커밋 파일 `data/telegram/<D>.json`, `kr/data/telegram/<D>.json`: `{report_date, collected_utc, window:[from,to], window_note, channels:{ch:{status,pages,truncated,error}}, items:[{id, kind(view|opinion), channel, group, dt_utc, url(t.me — 출처 추적용, 발행 금지), firm, analyst, source:{name,url}|null, summary_ko, summary_note}]}`. **원문은 커밋하지 않는다** — `_workspace/` 만, 요약만 커밋.
- 워크플로: `collect-market-data.yml` 의 뉴스 단계 뒤, `collect-kr-data.yml` 의 뉴스 단계 뒤에 `continue-on-error: true` 단계. 커밋 목록에 `git add data/telegram` / `git add kr/data/telegram` 를 **명시**한다(KR 의 `kr/data/*.json` 은 하위 폴더를 못 잡는다). 요약 인증은 뉴스 단계와 같은 WIF env.

## 작성자

- US: `ORCHESTRATOR.md` 가 `data/telegram/[DATE].json` 을 `<workspace>/telegram.json` 으로 복사(없으면 복사하지 않음, 다른 날짜로 대체 금지). KR: `kr/data/telegram/[DATE].json` 을 직접 읽는다.
- `brief-report-writer.md`·`kr-report-writer.md` 에 같은 규칙 절:
  - `summary_ko` 있는 item 만. view 는 브리프당 최대 3, opinion 최대 3. 그날 글의 판단과 맞닿을 때만 쓴다(채우려고 쓰지 않는다). 자리: US 전략 코멘트·주목 섹터·종목, KR §2 전략 코멘트·§9 특징주·§11 촉매.
  - 인용 문장을 `<span data-tg="<id>">…</span>` 로 감싼다.
  - view: 「<firm> <analyst> 연구원은 …로 봤다/평가했다/전망했다」. 견해를 사실처럼 단정하지 않는다.
  - opinion: 「…라는 의견도 나왔다/있었다」·「…라는 시각도 있었다」. `source` 가 있으면 그 매체를 문장(「블룸버그에 따르면」) 또는 섹션 끝 출처 줄에 단다(URL 이 있으면 링크). 없으면 「시장 일각에서는」.
  - 수치는 그 item 의 `summary_ko` 에 있는 것만, 시세 수치는 파일 값이 정본(다르면 파일 값).
  - 「텔레그램」·채널명·`t.me` 금지.

## 게이트 (`scripts/check_telegram.py --html X --tg <file> [--market]`)

FAIL:
1. 발행본 텍스트·href 어디든 `t.me/`·`telegram.me`·「텔레그램」·채널 이름 목록.
2. `data-tg` id 가 파일에 없거나 `summary_ko` 없음.
3. view span 안에 그 item 의 firm 과 analyst 이름이 없음 / opinion span 에 의견 틀 낱말(의견·시각·관측·해석·전망·평가·주장·지적·우려 등)이 없음.
4. span 안의 수치 토큰(%, 배수, 금액, 지수 레벨 등)이 그 item `summary_ko` 의 수치 집합에 없음(시세 파일 대조는 기존 게이트 몫).
5. view > 3 또는 opinion > 3.
6. opinion item 에 `source.url` 이 있는데 발행본에 그 URL 링크도, 매체명도 없음.
WARN: firm 이름(키움증권·한화투자증권)이 `data-tg` 밖에 나오면 경고(다른 출처로 쓰였을 수 있다).
파일 없음 + `data-tg` 없음 = 통과. 파일 없음 + `data-tg` 있음 = FAIL.
US·KR 오케스트레이터 게이트 목록에 넣는다. `check_style`·`check_readability` 순서는 그대로.

## 문서

- 계약은 `scripts/kr/CLAUDE.md`(여유 10KB+)에 짧게, us 체인은 1KB 남아 `docs/superpowers/specs/2026-11-06-telegram-source.md` 로 보내고 us 잎에는 한 줄 조건부 지시만.

## 열린 것·위험

- 증권사 견해 판정 규칙이 채널 형식 변화에 약하다 — 머리말이 바뀌면 view 가 opinion 으로 떨어진다(인용이 줄 뿐 잘못 귀속하지는 않는 방향).
- lim_econ 본인 글은 최근 3일 0건 — 사실상 view 공급은 키움 두 채널.
- 공개 레포에 텔레그램 유래 요약이 커밋된다(사용자 감수).
- 섀도 레포 수집은 이 연결이 돌면 중복이다 — 첫 주 뒤 끈다.
