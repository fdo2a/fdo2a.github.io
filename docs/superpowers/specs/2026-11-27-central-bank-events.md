# 한국은행 금통위(KR 마감브리프) · 일본은행 결정회의(일본 일간) 발언록 칸 (2026-11-27)

사용자 지시(2026-11-27): 「미국 레포트의 fomc 의사록처럼 한국에는 금융통화위원회 내용 및 총재의 기자회견 발언, 일본 레포트에는
일본은행 금융정책결정회의 및 총재의 기자회견 발언등을 같은 방식으로 추가해」. 방향 = 미국 §10(연준 이벤트, 설계
`2026-09-02-us-fed-events-design.md`)을 두 일간에 이식한다. 미국 칸·주간은 건드리지 않는다. 의사록 공개일에도 칸을 연다
(사용자가 「의사록」을 명시 — 미국은 `fomc_minutes` 가 tier 2 라 칸을 열지 않는다는 점은 사용자에게 알렸다).

## 1. 무엇을 막는가

이 칸이 막는 것은 **인용 창작**이다. 총재·위원이 하지 않은 말을 그들의 말로 싣는 것이 유일하고 가장 큰 실패 방식이다.
그래서 Actions 가 원문을 통째로 받아 커밋하고(`kr/data/bok/<key>.txt`, `japan/data/boj/<key>.txt`), 발행 게이트가 칸 안의
모든 `<blockquote>` 를 그 원문과 대조한다. 원문을 못 받은 이벤트는 인용을 금지한다(삭제 > 창작).

미국에서 그대로 가져온 것: 이벤트가 있는 날만 칸(없는 날 칸이 있으면 막고, 있는데 칸이 없으면 막는다), 인용 규율 넷
(blockquote 안 태그 금지 · 생략 ≤2와 조각 하한 · 원문 순서와 간격 상한 · 표식 밖 blockquote 금지), 도입 문단
`data-cb-event=KEY`(지난 날짜면 날짜를 밝힌다), 원문 있을 때 인용 둘 이상, 투자 아이디어 4요소(근거 발언 ref · 전달 경로 ·
표현 수단 · 무효화 조건, 하한 없음), 문턱값은 무효화 블록 안에서만, 칸 수치는 데이터 + 그 이벤트 원문, 내부 용어 노출 금지.

## 2. 코드 지도

| 파일 | 하는 일 |
|---|---|
| `scripts/common/cb_quote.py` | 대조 정규화(태그 → 엔티티 → NFKC → 따옴표·줄표 → **공백 전부 제거**), `verify_quote(quote, corpus, lang)`, KR 단위 수치 `source_numbers`, 일본어 兆·億 → 조·억 |
| `scripts/common/cb_events.py` | `due_events`·`missing_scheduled`(두 시장 진단·게이트·알림이 같이 쓴다), `covered_from_posts`(커밋된 발행본의 `data-cb-event`), 일정 파일 읽기 |
| `scripts/common/cb_gate.py` | 칸 검사(미국 `fed_gate.check` 와 같은 항목) — 수치 검사만 시장별 콜백 |
| `scripts/common/cb_collect.py` | 수집기 공용(받기 · PDF 글 · 산출 파일) |
| `scripts/kr/bok_events.py` · `scripts/collect_bok_events.py` | 한은 RSS·listYear 행·자막·의사록 첨부 읽기, 결정문 □ 7문단 변경점 |
| `scripts/kr/bok_gate.py` · `scripts/check_bok.py` | KR 게이트(`--diag` = 작성 전 진단) |
| `scripts/japan/boj_events.py` · `scripts/collect_boj_events.py` | 일본은행 목록 읽기, 공표문 금리·표결 문장 변경점, 전망 기본 견해 문장 redline |
| `scripts/japan/daily_gate.py`·`daily_render.py`·`scripts/build_japan_daily.py`·`scripts/jp_daily_gates.py` | 일본 일간의 boj 절(순서·검사·진단·입력 고정) |
| `kr/data/bok/schedule.json` · `japan/data/boj/schedule.json` | 손 채움 일정 — 결정일·각 문서 공개 예정일·`start` |

## 3. 의무 판정 — 수집기가 아니라 발행본과 일정 파일

- **「다뤘는가」의 장부는 발행본이다**(US 유동성 칸 `data-h41-release` 와 같은 방식). 수집은 됐는데 그날 루틴이 한도로
  빠지면(실제로 11/20 일본 일간) 수집기의 `first_seen` 으로는 다음 발행일에 이벤트를 조용히 잃는다.
  `covered` = 발행일 D 보다 앞선 날짜 발행본의 `data-cb-event` 집합. 오늘 글은 넣지 않는다.
  - KR: `check_bok.py --repo .` 가 HEAD 에 커밋된 `kr/posts/*.html` 를 `git grep`·`git show` 로 읽는다(check·record·verify 가
    같은 집합을 본다).
  - 일본: 진단·조립·게이트는 고정한 `$D/root` 만 읽으므로 `jp_daily_gates.py --pin` 이 **같은 커밋에서** 일정 파일(필수)·
    events.json·statements.json·각 원문과 파생 파일 `japan/data/boj/covered.json`(`input_commit`·`session`·`keys`)을 꺼낸다.
    전부 `inputs.json` 의 `files` 에 해시가 남고, `_moved` 는 `files` 키 목록을 본다(원문 파일 이름이 날마다 달라서).
    켠 뒤 세션인데 `covered.json` 이 없으면 진단 exit 1·게이트 위반 — 빈 집합으로 읽지 않는다.
- **due 조건**(`due_events(events, schedule, covered, D)`): 공개일 ≤ D, D 로부터 10일 창, 일정 파일 `start` 이상, KEY 가
  `covered` 에 없음, 그리고 원문을 하나라도 받았거나(`ok:true`) **일정표의 결정일인데 그 KEY 의 받은 행이 없음**(일정표 의무 —
  `from_schedule: true`, 원문 없음). 결정일 의무는 수집기가 쓰지 않는다 — 수집 step 이 죽은 날은 기록 자체가 없다(codex 4회차).
- 결정일 외 예정 문서(기자간담회·회견·의사록·주요 의견·의사요지)를 못 받았으면 칸을 요구하지 않고 매일 검증 알림에
  「예정된 ○○ 원문을 못 받았다 — 이유」 한 줄(`missing_scheduled`, 이유는 고정 목록 넷). 다음 수집에서 받으면 10일 창 안에서 칸이 열린다.
- **한 번 실은 KEY 는 끝이다.** 원문 없이 연 결정일도 표식이 찍혀 다음 날 원문이 와도 다시 열지 않는다(침묵 원칙).
- **`start` = 2026-11-28.** 11/26 KR 발행본은 금통위를 「정책·정치 촉매」에서 이미 다뤘지만 표식이 없다 — `start` 가 없으면
  켠 첫날 그 결정문이 due 가 된다(codex 4회차). 코드 상수 `kr/bok_gate.START`·`build_japan_daily.BOJ_START` 가 같은 값이고
  시험이 묶는다. 일정 파일이 아직 없던 커밋을 재연하는 옛 날짜(발행 커밋 재연 시험)는 「해당 없음」이다.

## 4. 원천 (2026-11-27 실측)

**한국은행** — robots.txt 는 `/portal/` 만 허용한다(`/fileSrc/`·`/static/` 금지).
- 결정문: RSS `/portal/bbs/P0000559/news.rss?menuNo=200690`, 제목 「통화정책방향(YYYY.M.D)」, description = 본문 HTML(□ 7문단),
  결정일 10:30. listYear.do 의 결정문 칸은 다음 날에도 비어 있었다 — RSS 로만 감지.
- 기자간담회: `listYear.do?mtgSe=A&menuNo=200755&pYear=YYYY` 의 그날 행. 같은 칸의 첫 PDF 는 「참고자료(2611).pdf」(2.8 MB)라
  제목 「…모두발언(2611).pdf」 로 고른다. 자막 = `B0000169/view.do?…programType=multiCont` 의 `<div class="subtitle">`
  (11/26 18,580자, 당일 게시). 원문 = 모두발언 PDF + 자막을 한 corpus 로.
- 의사록: RSS `/portal/bbs/B0000245/news.rss?menuNo=200789` → view.do. view.do 의 첨부 링크는 `/fileSrc/` 라, 같은 첨부 ID·순번으로
  `/portal/cmmn/file/fileDown.do?menuNo=200789&atchFileId=…&fileSn=…` 를 만든다(302 → file-cdn.bok.or.kr, 받은 PDF 가 원본과 바이트 같음).
  같은 RSS 에 정기회의 의사록이 섞여 있어 결정회의 것만 받는다. 게시 = 「회의일로부터 2주 경과 후 첫 화요일」(listYear.do 각주) —
  `bok_events.minutes_date`, 2026-07~10 의사록 6건과 일치(9/22 화요일 회의 → 10/13: 2주째 날이 화요일이면 그다음 주).
- 결정문 변경점: □ 문단 단위. 2026-02 결정문부터 7문단(결정·세계·국내·물가·금융외환·향후 방향·표결), 그 전은 6문단 — 7이 아니면 None.
- 2027 일정: 한국은행 영문 보도자료(2026-10-29) 1/14 2/25 4/9 5/27 7/15 8/26 10/15 11/25. 의사록 예정일은 규칙으로 계산
  (`minutes_basis: rule`) — 공휴일과 겹치면 밀릴 수 있다(그때는 알림이 하루 이틀 먼저 「못 받았다」를 낸다).

**일본은행** — robots 제한 없음. 일본어 원문만(회견 기록은 영문이 없다).
- 공표문 `/mopo/mpmdeci/mpr_{Y}/k{yymmdd}{a-d}.pdf`(목록 `state_{Y}/index.htm`, 「（参考）」 부속 문서는 거른다), 회의 종료 직후.
- 전망 기본 견해 `/mopo/outlook/gor{yymm}a.pdf`. 회견 기록 `/about/press/kaiken_{Y}/kk{yymmdd}a.pdf` — 같은 목록에 심의위원·부총재
  회견이 섞여 있어 「総裁定例記者会見（M月D日）」 이름으로 고른다. 공개는 다음 영업일(10/30 → 11/02, 9/18 → 9/24).
- 주요 의견 `opinion_{Y}/opi{yymmdd}.pdf`·의사요지 `minu_{Y}/g{yymmdd}.pdf` — 파일 날짜는 회의 마지막 날, 공개일은 일정표.
- 일정(`/mopo/mpmsche_minu/index.htm`, 2026-11-27 확인): 2026-12 회의 12/17·18 → 공표문 12/18, 主な意見 12/28, 議事要旨 2027-01-27,
  10/29·30 회의 議事要旨 12/23, 2027 회의 8회 전부. 2027-12 議事要旨는 「未定」이라 비웠다. 회견 기록 공개일은 일정표 주석
  「翌営業日」을 JPX 휴장일(`data/market_holidays.json`)로 계산한 날(`presser_basis: next_business_day`) — 수집기는 목록의 실제 파일 날짜를 쓴다.
- 공표문 변경점: 제목·구성이 회의마다 달라 **정책금리 문장 + 표결 문장만** 맞댄다(공백 지운 NFKC 꼴에서 찾는다). 어느 쪽이든 못 찾으면 None.
  9/18 → 10/30: 금리 문장 같음, 표결 문장 바뀜(반대 浅田·佐藤 → 高田). 전망 기본 견해는 문장 단위 redline(7월 ↔ 10월: 128문장 중 48 같음).

## 5. 측정

- **조각 간격 상한**(공백 제거 뒤 글자 수, 「한 사람의 한 답변」 90분위에서 올려 잡음):
  - 한국어 2,500 — 11/26 기자간담회 자막의 총재 발언 9개(모두발언 포함) p50 1,150 · p90 2,401 · p95 2,508 · 최대 2,614.
  - 일본어 900 — 10/30 정례 회견 기록(11/02 공개 PDF)의 답변(（答）) 28개 p50 360 · p90 816 · p95 1,317 · 최대 2,269.
  - 설계의 1,500 은 실측 전 기본값이었다. 언어별로 쓴다(`SEGMENT_GAP_MAX`).
- 인용 하한 20자 · 조각 하한 12자(공백 제거 뒤) — 미국 40/25 의 대략 절반.
- **생략 표시 `…`·`...`·`[...]`**: 한은 결정문·모두발언·자막·의사록, 일본은행 공표문·전망·회견·주요 의견·의사요지 원문 어디에도 없다
  (`…` 0, `...` 0, `‥` 0, `・・・` 0) — 원문 자체의 말줄임과 겹치지 않는다. NFKC 가 `…` 를 `...` 로 바꾸므로 정규화 뒤 꼴로 나눈다.
- **구현에서 더한 규칙 — 생략이 지운 부분 ≥ 8자**(`ELIDED_MIN`). 한국어·일본어 부정은 짧은 꼬리(「이탈하지 않고」의 「않고」,
  「上昇しない」의 「ない」)라 앞뒤 조각을 둘 다 길게 남긴 채 부정어만 지울 수 있다 — 미국의 조각 하한으로는 안 잡힌다
  (11/26 자막 「…크게 이탈하지 […] 내년에는…」 으로 재현). 한계: 부정어를 포함해 8자 넘게 지우면 이 규칙도 지나간다.
- **KR 칸 수치 단위**(11/26 결정문·모두발언·자막·10/22 의사록에서 실제로 나온 것): % · %p · bp · 조 · 억 · 명 · 배 (+ 같은 뜻
  표기 퍼센트·포인트·베이시스포인트·원·달러). 범위 「2∼3%」의 앞 끝도 넣는다.
- **일본 일간 수치**: boj 절 안에서만 그날 원문의 숫자 토큰 전부를 허용 집합에 더한다 — 게이트와 같은 `_text_figures` 로, 공백을
  둔 판과 지운 판 둘 다(PDF 의 「１． ５％」), 兆·億 → 조·억(「8,600억 엔」·「2조 4,600억 엔」). 수집기 머리줄(원문 주소)은 뺀다.
- PDF 각주 번호가 본문에 붙어 있다(「（簿価ベース）1とすることを決定した」) — 인용은 각주 번호 앞에서 끊는다(작성 사양).

## 6. 일본 일간 게이트에서 boj 절을 빼는 자리 (codex 5회차 #6)

boj 절은 작성자 산문 검사 셋에서 빠진다: `allp` 어휘 검사(`_CONSENSUS` 「전망치」, `_SIGNALS`, 「오늘」+콜, 「오늘」+JGB, 「지수 기여」),
`_check_refs`/`_check_unbound`(data-ref 묶기 — 문턱값 「10년물 2.9%」가 핵심 값 반올림과 겹쳐 막히던 후보 경로도 함께 닫힌다),
2판 `_check_v2_prose`(TOPIX·곡선·「없다」+발표 — 번역은 「장기금리」「수익률 곡선」을 옮겨야 한다). 실제 10/30 요약 문장
「물가 전망치는 2.4%에서 2.6%로」, 「일본은행이 오늘 무담보 콜금리 유도 목표를 1.25%로」가 절 안에서는 통과하고 절 밖에서는
그대로 막힌다(`scripts/japan/tests/test_daily_boj.py`). 대신 boj 절은 공용 칸 검사 + (무효화 블록 밖) 스냅샷 ∪ 원문 숫자 검사를 받는다.
머리 카드·제목·meta 의 수치 검사는 그대로다.

## 7. 나머지 결정

- 발행 전 입력 분류(`config/prepub_inputs.json`): `kr/data/bok/{schedule,events}.json`·`*.txt` 는 **writer** 분류(`covered_by: check_bok`),
  `seen.json`·`statements.json` 은 unused. gate 분류는 날짜·수집 상태가 어긋나면 브리프 전체를 세우는데, 이 칸은 수집 실패로 발행을
  막지 않기로 했다. 그래서 `check_bok` 의 `inputs` 는 비워 두고, 일정 파일이 없거나 받았다는 원문 파일이 없으면 검사기가 exit 2.
- `check_bok` 은 `config/prepub_gates.json` kr 목록에 required(structure). KR 절 배치 검사(`kr/stance_gate.py`)는 §2 문단 순서와
  복기·일정·뉴스 위치만 본다 — 「전략 코멘트」 뒤·「오늘의 장」 앞의 새 절과 부딪치지 않는다. 읽는 층 머리(`post_parts`)는 목록에 없는
  절을 이미 열린 층(1층)에 둔다.
- 인용 카드 조판: KR `post_css/kr.css` 에 `.cb-quote`·`.cb-idea`(바꾸기 전 판은 `legacy/kr-2026-11-27.css` — 쟁점 게이트가 옛 글을
  계속 믿는다). 일본 일간은 boj 절이 있는 날만 조립이 같은 규칙을 덧붙인다(없는 날 조립본은 바이트 그대로 — 옛 판 재연 시험).
- 변경점 블록은 계산해 둔 변경이 **실제로 있을 때만** 요구한다(미국은 diff 가 None 이 아니면 요구). 일본은행 공표문은 금리·표결이
  그대로인 회의가 흔해 「바뀐 것 없음」을 150자로 쓰게 하지 않는다.
- 수집 단계는 비-코어(`continue-on-error`, 6분). KR 잡은 curl_cffi·pypdf 를 그 단계에서 설치한다. `versions_kr.STAGE_SH` 에
  `kr/data/bok`, 일본 「Commit data」에 `japan/data/boj`. `kr/data/bok/` 는 하위 폴더라 발행된 날 동결(`is_dateless`) 대상이 아니다.
- 매일 검증 알림(`review/digest.py` `cb_missing_notes`, `verify_digest.py`)이 origin/main 의 일정 파일·events.json 으로 같은 함수를
  불러 한 줄씩 — 문구는 고정 패턴(`_cb_pattern`)이라 「기타 안내 1건」으로 뭉개지지 않는다. 이유는 고정 목록
  (수집 기록 없음 · 수집 실패 · 일부 수집 실패 · 공개 목록에 아직 없음).
- 문체·가독성·번역투 검사의 번역 문단 제외 목록에 `cb-trans`(`us/readability.py`·`us/style.py`·`us/translationese.py`).

## 8. 알던 한계 · 범위 밖

- 원문 없이 나간 결정일은 원문이 나중에 와도 다시 열지 않는다. 한은 자막이 18시 이후에 올라오면 그날은 모두발언만.
- 발행 뒤 검토 러너의 일본 일간 게이트 재실행(`review/style_pass.py` `_period_gates`)은 지금 꺼져 있다(`STYLE_REWRITE = False`).
  다시 켤 때 근거 스냅샷에 boj 파일과 `covered.json`(같은 함수, 발행 커밋 기준)을 넣어야 한다. 손으로 repo 루트에서
  `check_japan_daily.py --session S` 를 돌리면(켠 뒤 세션) `covered.json` 이 없어 위반이 난다 — 입력 고정 폴더(`$D/root`)로 돌린다.
- KR 「정책·정치 촉매」와 내용이 겹칠 수 있다(작성 사양으로 나눈다 — 칸이 있는 날 촉매 절은 결정 사실을 되풀이하지 않는다).
- 첫 실제 실행: 한은 의사록 2026-12-15(예정), 일본은행 12/18 공표문·12/21 회견·12/23 의사요지(10월분)·12/28 주요 의견.
  Actions 에서 bok.or.kr·boj.or.jp 접근은 아직 확인하지 않았다(로컬 curl 은 200).
- 미국 칸 변경, 주간, 총재 연설·국회 발언, 영문판 대조, 일어난 적 없는 꼴(손 편집된 events.json, 같은 날 두 번 회의, 회의 연기)은 범위 밖.

## 9. codex 설계 검토 이력 (5회, 상한)

| 회차 | 판정 | 받은 것 |
|---|---|---|
| 1 (terra high) | NOT OK | 「다뤘는가」 장부를 발행본으로(#3), 익명 문서 귀속은 캡션만 검사(#4), 일본 숫자 게이트가 1.25% 를 막음(#6), 수집 실패 ≠ 이벤트 없음(#7), 범위 밖: 공표문 변경점 None 계약 · cb-trans 제외 목록 |
| 2 (terra high) | NOT OK | 일본 진단·게이트는 고정 입력만 본다 → 같은 커밋에서 장부를 만든다(#3), 결정일 합성 행은 그 자체로 due(#7) |
| 3 (sol high, Fable) | NOT OK | 새 폴더가 커밋 add 목록에 없음, 10/30 공표문 금액(8,600億円)이 막힘 → 원문 숫자 토큰 전부 · KR 단위에 금액 |
| 4 (sol high, Fable) | NOT OK | `start`(11/26 글에 표식 없음), 「수집기가 죽으면 기록이 없다」 갈래 네 번째 → 모양 바꿈: 일정표에서 직접 계산, 무효화 블록 수치 제외 |
| 5 (sol high, Fable) | NOT OK(상한) | 일본 산문 어휘 검사가 boj 절을 막음(#6) → 절을 그 검사들에서 뺀다, 알림 문구가 고정 목록에 없음(#7) → 고정 패턴. 사용자 「받고 구현 시작」 |

자세한 판정표: `../plans/2026-11-27-금통위-일본은행-발언록.md`(레포 밖).
