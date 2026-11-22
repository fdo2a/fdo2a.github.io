# 모든 숫자 발행 전 확인 — 숫자 출처 검사 (US 루틴 1차, 2026-11-20)

대상: US 일간 `posts/D.html` + US 뉴스·산업 글 `news/D.html`. 코드: `scripts/common/numsrc.py`(문법·칸·이력), `scripts/us/facts.py`(칸 풀이기), `scripts/us/number_sources.py`(US 자리 규칙), `scripts/common/article_numbers.py`(기사·텔레그램 숫자 목록), CLI `scripts/check_number_sources.py`. 설계 검토는 codex 3회(상한) — 3회차 지적 두 갈래(「.5%」, 문단 안 재배치)는 사용자 「추천대로 해」로 받아 아래 §2.1·§7.3 에 반영했다. 계획·결정 기록: `../plans/2026-11-20-모든-숫자-발행-전-확인.md`.

## 0. 점검표(codex 설계 검토 1-3회와 같은 13개)

**막을 것**: ① 보이는 숫자가 어느 칸에도 안 들어감 ② `data-ref` 숫자가 칸 값과 다른데(값·부호·단위·배율) 「자료로 확인」 ③ 없는·못 읽은·`invalid` 칸을 가리키는데 통과 ④ 기사 표식 숫자가 **그 기사** 목록에 없는데 「기사와 일치」 ⑤ 숫자 목록이 지금 요약과 짝이 아닌데 대조에 씀 ⑥ 표식 하나가 수량 둘 이상·수량이 표식 경계를 넘음·표식 겹침 ⑦ 「제외」 선언으로 값 숫자를 뺌 ⑧ 기존 표 차단 약화 ⑨ 기사 원문이 공개 레포에 들어감 ⑩ 기록·알림의 칸 합 ≠ 숫자 수, 뉴스 글 기록이 알림까지 안 닿음, 옛 기록을 못 읽음 ⑪ 숫자·문단을 지우거나 표식만 바꿔 맞췄는데 기록에 안 남음 ⑫ 값으로 칸을 찾아 줌·자유 조합 계산 ⑬ 표식을 달 수 없는 자리의 숫자가 세는 범위에서 빠지거나 대조 없이 「자료로 확인」.

**범위 밖**: 맞는 값을 다른 주어에 붙인 문장, 방향어와 부호의 해석(11/19 원칙 — 사후 정규식 검증 금지), 기사 자체의 오류(「기사와 일치」≠「맞다」), 숫자 없는 수량어·그림 속 숫자·속성값, 쟁점 분석·편집자 노트 안 숫자의 진위(세기는 한다), KR·일본·주간과 차단 전환(2·3차, 2주 뒤 사용자 결정).

## 1. 지금 상태 — ① 재측정(11/12·13·16·17·18 다섯 편, 발행 커밋 자료)

- 새 문법의 숫자열: 편당 1,434-1,556(보이는 글 전체). 수량: 1,284-1,415. 기존 `check_numbers` 토큰은 741-800.
- 문장 수치(표·위임 밖, 기존 토크나이저 927개)의 출처: 자료 잎 그대로 874(market_data 498 · intraday 102 · macro.json 69 · fund_board 60 · macro_metrics 38 · auctions 36 · movers 33 · econ_indicators 30 · calendar 8), 계산처럼 보이는 것 37(그중 진짜 계산은 WTI−브렌트 차 6·성장−가치 등락률 차 1·이력 누적·bp 변화 5 정도, 나머지는 우연 일치), 어디에도 없음 16(보도된 FedWatch 확률, 기간 상대수익 차 = 깊이 2, 전일 2s10s).
- **결론**: 연산은 설계 그대로(`diff·sum·ratio·pctchg·rank·gap` + 이력 `ret·chgbp·streak`). 이력 파일(`data/history/market.jsonl`) 행에 상태 칸이 **없다**(확인함) → 이력 연산은 늘 U. 상태 칸 없는 파일(intraday·movers·econ_indicators)의 165개(18%)와 별칭이 없는 macro.json 69개(7%)는 처음 2주 U 다.
- 표식 없는 옛 글을 새 검사로 돌리면: 표 대조(T) 660-694 · 세지 않은 숫자 263-295 · 확인 불가 360-459(표식 없음 213-305, 코드 블록 124-156). 칸(R)·기사(A)는 표식·숫자 목록이 생긴 뒤부터.

## 2. 틀

### 2.1 숫자열과 수량
- **보는 글**: `us.number_audit._Stream`(같은 파서)의 흐름 — 엔티티를 풀고, 전각→반각, 인라인 태그는 붙여 읽고 블록 경계에서 끊는다. 숨김·SVG 는 보이지 않으므로 세지 않는다(그 숫자는 `check_numbers` 가 막는다). `<title>`·메타 설명·대체 문구는 따로.
- **숫자열** = `\d(?:[\d,]*\d)?(?:\.\d+)?` 의 최대 일치 + **앞 0 생략 소수 `.5`**(공백·괄호·부호·$·문두 뒤에서만 — `us/number_audit.py:40-43` 규칙 그대로, 「했다.5%」의 5% 는 5%). 「.5%」= 0.5%(3회차 #2).
- **수량** = `[부호][$] 숫자열 [배율] ( [빈칸] 숫자열 배율 )* [단위]`. 배율 조·억·만·천(합성 「천만」「백만」 포함, 뒤로 갈수록 작아야 이어짐), 영문 K·M·B. 「80만 3000원」처럼 배율 없는 꼬리는 앞 배율보다 작고 세 자리 이상일 때만 같은 수량. 단위는 닫힌 목록(`numsrc.UNITS`). 범위 「3~6개월」은 수량 둘이 단위를 같이 쓴다. 천 단위 구분이 아닌 쉼표(「3,4위」)는 값을 정하지 않는다.
- **X-코드**(값이 아닌 숫자): 날짜·시각·분기·회계연도·연도(코드 문법), 고정 이름(`config/number_sources.json` 의 `fixed_terms` — 만기·지수·문서 이름, 닫힌 목록), 영문자에 붙은 식별자(「CLF27」「912810UZ9」; 값 꼬리 K·M·B·x·bp·p 는 제외).
- **부호**: `_TOK` 와 같은 경계 — 부호 글자 앞이 ASCII 글자·숫자·밑줄이거나 「숫자.」「숫자,」이면 부호가 아니다(「3-6개월」은 범위). 한글 뒤는 부호다(「나스닥-0.42%」).
- **귀속**: 숫자열은 정확히 한 수량에 속한다. 불변식 두 층 — `Σ칸(수량) == 수량 수`, `Σ칸(숫자열) == 숫자열 수`, 그리고 **수량 문법과 따로 다시 센 보이는 글의 숫자열 수 == 수량에 든 숫자열 수**. 어긋나면 exit 2. 시험: 기존 `_TOK` 토큰 구간은 모두 한 수량 안(11/05 고정 글).

### 2.2 칸(배타, 수량마다 하나)
T 표 대조 · R 자료 칸(`data-ref`) · A 기사 목록 · G 텔레그램 원글 목록 · W 검색 발췌 · X 세지 않은 숫자 · U 확인 불가(나머지 전부). 판정 순서: 구역(X) → T → 표식 → X-코드 → 상속(텔레그램·요약 문단·블록 제목) → 코드 블록·그 밖 U.

**표식 문법**: `span[data-ref|data-src|data-nx]`. 한 표식 안 수량은 정확히 하나이고 부호·배율·단위까지 안에. 수량이 표식 경계에 걸치거나(`<span>7,323</span>.63`, `.<span>5%</span>`), 표식이 겹치거나, 한 표식에 수량이 둘이면 U 「표식 오류」. 수량이 없는 표식은 `marker_empty` 로 센다.

### 2.3 T 는 맞춰 본 노드만
`number_audit.audit(…, trace=)` 가 판정과 무관한 부산물로 흐름 항목마다 갈래를 돌려준다(판정·종료 코드·출력 불변 — 회귀 시험과 골든 CLI 출력). T = 시장 표 6종에서 **값을 맞춰 보고 위반이 없었던 칸**(`Result.cells_ok` — `owned` 는 틀린 칸도 담는다) + 위임 노드(섹터 기간 표 `spf-val`, 트렌드 유닛 `data-fund-board`, 유동성 표·표식 문단, 매크로 표식 행의 추세·숫자 하나 칸). 수량의 글자가 전부 T 항목 안일 때만 T. 그 밖의 코드 블록(입찰 표·일정·지표 해부·연구 원장 요약·매크로 미표식 행)은 U 「코드 블록(표식 없음)」. 제목·메타는 같은 인쇄 꼴의 본문 수량이 U·X 가 아니면 그 칸, 아니면 U. 쟁점 분석(`data-contested`)·편집자 노트(`data-editor-note`)는 구역째 X(건수 따로).

## 3. 자료 숫자 — `data-ref="별칭:경로[|abs][|lvl]"`
- 별칭(닫힌 표): `md` market_data · `id` intraday · `ei` econ_indicators · `mm` macro_metrics · `mv` movers · `fb` fund_board · `au` auctions · `lq` liquidity · `cal` calendar · `rl` 연구 원장(`rl:<기록 id>.<경로>`, 이번 cycle 과 그 candidate·reviewed 기록만) · `dv` 계산값. 키는 공백·& 를 빼고 대소문자 없이(둘 이상 맞으면 칸 없음), 목록은 `[id|key|name|label_ko|fred_id|term]`.
- **스키마 표**(`facts.SCHEMA`)가 경로 꼴마다 인쇄 단위·부호 유무·묶음/자산/필드·배율·관측일 자리를 준다. 표에 없는 경로·숫자가 아닌 잎 = U 「칸 없음」. `cal`·`lq` 는 지금 칸이 없다(일정은 날짜뿐, 유동성은 T).
- **값으로 칸을 찾아 주지 않는다**(끝자리 +1 의 65% 가 다른 칸과 맞는다). 불일치는 가리킨 칸만 본다.
- **계산값**: `dv:diff|sum|ratio|pctchg(a,b)` — 같은 묶음 두 자산의 같은 필드, 또는 한 자산의 두 날짜(last↔prev, level↔week_ago). `dv:rank(md:묶음,필드,키)`(큰 값 1위), `dv:gap(값칸,rl:문턱칸)`. 피연산자는 기본 칸만(깊이 1). 이력 연산 `ret·chgbp·streak` 은 상태 칸이 없어 U 「칸 무효」. 금리 수준 차는 %p·bp, 등락률 차는 %p, 비율은 배·%.
- **표시 규칙**: 값은 인쇄 자리로 반올림해 같아야 한다(반 자리 허용, 이중 반올림 없음). 부호를 인쇄했으면 같아야 하고, 부호 있는 **음수** 칸을 부호 없이 쓰면 `|abs` 가 있어야 한다(양수는 그대로 — 구현 해석). 단위는 칸의 허용 집합, 배율은 숫자 크기로(「160억 달러」= 1.6e10). `|lvl`: 유효숫자 2개 이하이고 차가 마지막 유효 자리 1단위 이내(「7,300선」↔7,323.63; 「7,000선」도 규칙상 통과).

### 3.1 상태(값 대조 전에)
| 별칭 | 받는 조건 |
|---|---|
| `md` | `complete is true`, `missing` 에 같은 묶음 항목 없음(꼴 「묶음/이름[/문제]」 — 보수적으로 묶음째), fx·원자재 행 `basis == close_1600_et`, `report_date ==` 글 날짜 |
| `mm` | `book_state == "ok"`, `report_date ==` 글 날짜 |
| `fb` | 파일 `status == "ok"`, `missing` 에 없음, 유닛 `status == "ok"` |
| `au` | `ok`·`complete` 둘 다 `true` |
| `cal` | `complete is true`, 행 `status == "confirmed"` |
| `lq` | `status == "complete"` |
| `rl` | 원장 읽기 성공, 이번 cycle 이 참조한 기록 |
| `ei`·`id`·`mv` | 상태 칸이 없다 — 늘 U |
| `dv` | 피연산자 상태의 나쁜 쪽, 이력 연산은 U |
어기면 invalid → U 「칸 무효」. 관측일이 글 날짜와 다르면 stale — R 로 세되 `stale_refs` 에 건수. 시험: 값·날짜가 맞는 칸에서 complete=false / missing 항목 / book_state≠ok / 상태 키 삭제 / 문자열 "true" / `ei:` / basis≠16:00 — 모두 U.

## 4. 뉴스 숫자
- 수집 잡(`fetch_news.py`·`fetch_telegram.py`)이 요약 뒤에 본문·제목의 수량을 정규화해 **`data/news/numbers/D.json`·`data/telegram/numbers/D.json`** 에 쓴다(설계의 `data/news/D.numbers.json` 과 다름 — `check_news.load_collected` 가 `news/*.json` 의 마지막 파일을 「최근 수집분」으로 고르는 길이 있어 하위 폴더로 뺐다). 워크플로의 `git add data/news`·`data/telegram` 이 그대로 담는다.
- 꼴: `{report_date, extractor:"v1", items:[{guid, summary_sha, title_numbers, body_numbers, n, summary_check:{status, missing}}]}`, 숫자 = `[값, 갈래, 통화]`(갈래 pct·pp·bp·times·money·num, 통화 닫힌 목록). **허용 목록 직렬화**(`article_numbers.serialize`) — 본문 낱말을 심어도 파일에 없다(시험). 글자 자리는 guid 와 `missing`(우리 요약의 표기, 12개·20자)뿐. 매체 약관은 코드로 확인할 수 없다.
- 일치: 갈래가 같고, 통화가 둘 다 있으면 같고, 목록 값을 **글에 인쇄된 자리**로 반올림한 값이 글의 값(절대값). 같은 guid 둘 이상 / 그 기사 항목 없음 / `summary_sha` ≠ 지금 요약 해시 → 그 기사 목록 사용 불가(U 「목록 없음」). 본문을 못 받은 기사는 제목 숫자만, 같은 요약이면 앞 판 항목을 옮긴다(`write_day`).
- 요약 ⊂ 본문: 같은 자리에서 보고 `missing` 과 수집 로그에만 남긴다(섀도, 기사·요약을 버리지 않는다).
- 상속 자리(`data-tg`·`data-news`·`data-summary`·`news-head`)는 수량의 글자 전부가 같은 조상 안일 때만 — 경계에 걸치면 「표식 오류」.
- 글에서: `p[data-summary=G]` 의 **요약 원문 앞부분**만 G 목록을 물려받는다. 연결 한 문장은 확장기가 이스케이프해 표식을 받지 않으므로 U(확인함). 블록의 한국어 제목(`p.news-head`, 캡션 `.sub` 제외)은 분류기가 G 목록과 대조한다(설계는 확장기가 `data-src=news` 를 찍는 것 — HTML 을 바꾸지 않고 같은 대조를 한다). 직접 쓴 블록은 숫자마다 `data-src="news"`(가장 가까운 바깥 `data-news`), 블록 밖은 `data-src="news:<guid>"`. 단위 없는 31 이하 정수는 `article_common`.

## 5. 텔레그램 · 웹 리서치
- `span[data-tg=ID]` 안 수량 → 그 글의 원글 숫자 목록(같은 규칙, 이유 「기사 목록에 없음」).
- `data-src="web:<source_id>"` → 그 cycle 기록의 `sources[].snapshot`(`research/us/evidence/<sha>`), sha256 이 이름과 같을 때만. 일간은 글의 `data-research-cycle`(`--cycle` 과 다르면 사용 불가), 뉴스 글은 같은 날 커밋된 `posts/D.html` 의 그 속성. cycle 기록의 `market`·`report_date` 가 다르면 사용 불가.

## 6. 제외
X-코드(§2.1) + 작성자 선언 `data-nx="enum"` 하나뿐 — 99 이하 정수, 세는 말(종·개·가지·곳·명·건·차례), %·%p·bp·금액·배·소수점·천 단위가 있으면 「선언 무효」(U). `level` 선언은 없다(어림선은 `|lvl`). 선언은 건수와 목록을 기록에 싣는다.

## 7. 확인 불가 · 참고 2주 · 수정 이력
### 7.1 U 이유(닫힌 분류)
표식 없음 / 표식 오류 / 자료와 다름 / 칸 없음 / 칸 무효 / 기사 목록에 없음 / 목록 없음 / 발췌에 없음 / 코드 블록(표식 없음) / 선언 무효. **기본값**: `config/prepub_gates.json` 에서 `required: false`, 확인 불가는 위반이 아니라 `sources` 집계다(게이트 상태 pass — 기록 판정·`verified`·`numbers` 에 손대지 않는다). 칸 합 위반·입력 오류는 exit 2 → 판정 불가 → 알림 「숫자 출처 검사 못 함」. **적용일 `numsrc.EFFECTIVE` 는 자리표시 `2099-12-31`** — 병합 뒤 첫 발행일로 바꾼다(그 전 글은 not_run, 뉴스 글 기록·알림 대상도 이 날부터).

### 7.2 기존 게이트
`check_numbers` 표 층·위임 차단·토크나이저·종료 코드는 그대로(trace 는 부산물). `config/number_audit.json` 은 바꾸지 않는다 — 문장 층의 「11/21 block 전환」은 하지 않고 warn 에 둔다.

### 7.3 수정 이력 — 문장 단위(3회차 #11 뒤 사용자 승인 판)
- 숫자별 자리 추적(removed·reref·moved)을 버렸다. **첫 판에서 U 였던 수량마다** 최종본에서 셋 중 하나: **고쳐서 확인**(이제 U 가 아닌 칸) / **문장째 사라짐** / **그대로 확인 불가**.
- 대응: (구역, **값 수량**을 `#` 로 가린 문장 글 — 날짜·이름 X-코드 글자는 그대로) + 문장 안 몇째 수량. 가린 문장이 첫 판에 둘 이상이거나 최종본에 둘 이상이면 그 수량들은 **이력 확인 불가**(「변경 없음」으로 적지 않는다).
- 첫 판은 최종 기록의 필수 입력: 루틴이 게이트를 처음 돌리기 전 초안을 `<workspace>/numsrc_first.html`(뉴스 글 `numsrc_first_news.html`)로 복사하고 `run_gates.py --first-html` 로 넘긴다. 게이트가 같은 입력으로 다시 분류한다. 없거나 canonical 의 시장·날짜가 다르면 `history: "unverifiable"` → 「수정 이력 확인 불가」.
- **기록에는 문장 글을 싣지 않는다**(지운 초안 문장은 공개된 적이 없다) — 건수와 사라진 수량의 인쇄 꼴(12개·20자)만.
- 시험: ① 「5%」 문단을 지우고 다른 문단에 같은 표식 5% → 문장째 사라짐 1 ② 「A 5%, B 5%」→「B 5%, C 5%」(긴 공통 문장) → 사라짐 2, 그대로 0 ③ 표식을 달아 고침 → 고쳐서 확인 ④ 같은 문장 둘 → 이력 확인 불가 ⑤ 첫 판 없음 ⑥ 다른 날·다른 시장 첫 판.
- 허용 수정 셋(표식 달기·칸 값으로 고치기·출처에 없으면 빼고 보고), 작성자 최대 2회. `ORCHESTRATOR.md` 「중복 수치 삭제」는 이 검사의 U 에 쓰지 않는다.

## 8. 기록 · 알림
- 게이트 `--json`: `{skipped, warnings:[], violations:[], sources:{counts, runs, detail, unknown_by, web_by, unknown(60·80자), unknown_total, declared, dv_list, history, history_why, first_sha256, cycle}}`.
- `record.py`: 설정의 `result: "sources"` 갈래가 `sources` 로 옮긴다(`numbers` 와 섞지 않는다). **합을 다시 센다** — 배타 칸 합 == total(두 층), history 꼴; 어긋나면 판정 불가. `optional_argv` = 값이 있을 때만 붙는 인자(`--tg`·`--cycle`·`--first`). `repo_paths('us-news') = scripts·config·research/us·posts` — 설계의 `news` 는 뺐다(`.gitignore` 의 `/news/` 때문에 임시 index `add -A` 가 통째로 실패한다, 구현 중 발견).
- `prepub_view.recorded()`: `sources`(검증한 사본)·`sources_bad`·`sources_gate`. 표시: sources 있음 → 「숫자 N개 = 자료로 확인 a · 어림선 l · 기사와 일치 b · 텔레그램 글과 일치 g · 검색 발췌와 일치 c · 세지 않은 숫자 x · 확인 불가 d」(0 이어도 전부, 합 확인) + 내역 줄 + 이유 + 확인 불가 앞 8개 + 「프로그램이 보지 못하는 것: 숫자의 주어·방향, 기사 자체의 오류」 / `sources_bad` → 「숫자 집계가 맞지 않아요」 / 게이트가 not_run·indeterminate → 「숫자 출처 검사 못 함」 / 게이트 항목 없음(옛 기록) → 옛 숫자 줄 그대로. 「검증 완료」를 U=0 에 묶지 않는다(`fully_verified`·`fingerprint`·`anomalies`·`clean` 은 그대로). **건별 알림에서 분량·문체 경고 줄을 뺐다**(11/20 사용자) — 판정·기록·실패 표시는 그대로.
- us-news: `config/prepub_gates.json` `markets["us-news"]`(STEP 3.5 의 손 게이트 + 새 게이트), `prepub_view.RECORD_TARGETS`(세션 감시 `TARGETS` 는 us·kr 그대로 — 뉴스 글은 미발행 감시 없음), `publish_watch.WATCH_PATHS` 에 `news`, `_target_of_any`·`verify_publish` 는 `RECORD_TARGETS`. 뉴스 글은 `numsrc.EFFECTIVE` 이후만 대상(그 전 글이 전체 재계산에서 「기록 없음」 경보가 되지 않게). `digest.py` 는 sources 가 있으면 「숫자 N개 중 확인 불가 d개」.

## 9. 사각지대(남은 것)
맞는 값·다른 주어(알림 문구로만 막는다) · 「검색 발췌와 일치」는 자기 메모 대조일 수 있다 · 영→한 숫자 대조 오탐은 섀도로 잰다 · 작성자 출력 +약 25%(표식) · 차단으로 가면 숫자를 덜 쓸 수 있다(편당 숫자 수와 문장째 사라짐을 2주 함께 본다) · 상태 칸 없는 파일(지표 원본·장중·움직인 종목)과 macro.json 은 2주 U 를 늘린다 · US 글의 `apply_readability`·`apply_colors` 는 문단 안 `data-ref` span 을 보존한다(시험 `test_markers_survive_publish_transforms` — `apply_colors` 는 표 칸 class 만 만진다). check_readability·check_style 을 지난 뒤의 생존은 일본 일간에서만 확인했다.

## 10. 확인 못 함
매체 약관 · `web_session` 스냅샷이 원 바이트인지 · `check_auction` 이 span 든 칸을 읽는지(입찰 표 렌더러 표식은 이번에 넣지 않았다 — 표가 U 「코드 블록」) · 영→한 대조의 실제 오탐률(Actions 첫 수집 뒤) · 수집 숫자 목록은 US 만 쓴다(`fetch_telegram.py --market kr` 은 쓰지 않는다 — 2차).


## 2026-11-21 — 어림선은 따로 센다

사용자: 「7,000선」 같은 어림선은 필요한 표현이다(좁히지 않는다). 그래서 `|lvl` 대조 규칙은 그대로 두고, 맞으면 `data` 가 아니라 배타 칸 `level`(알림 「어림선」)로 센다 — 그 확인은 자릿수 범위(7,000선 ⇐ 7,000~7,999)뿐이라 「자료로 확인」에 섞으면 신뢰를 부풀린다.

## 11. codex 구현 검토 1회 반영(2026-11-21)
- **표식이 표 대조보다 먼저**: 수량이 표식 안이면 개수·겹침·경계·칸 유효성을 먼저 본다. 깨진 표식·없는 칸을 가리키는 표식은 표 칸이 맞았어도 U. 맞는 표식이 표 칸에 있으면 T(표식 쪽 내역은 세지 않는다).
- **연구 원장 칸도 스키마 표로만**: `research_ledger.validate` 가 값·단위·관측 시각을 함께 검증하는 자리 — `event.expectations[n].value`·`event.actual.value`·`event.reactions[n].before|after` — 만 칸이다. 그 밖의 숫자 잎은 칸 없음, 단위가 닫힌 표 밖이거나 관측 시각이 없으면 칸 무효, 관측일이 글 날짜와 다르면 stale. 이름 없는 목록 항목은 자리 번호(`[0]`)로 가리킨다.
- **`dv:gap` 의 둘째 칸은 원장의 명시적 문턱 칸만**(`facts.RL_THRESHOLDS`). 지금 원장 꼴에는 숫자 문턱 칸이 없다(문턱은 무효화 조건 글에 있다 — 11/21 원장 196행에 숫자 잎 0개) → gap 은 늘 U(fail closed).
- **enum 선언은 배율(천·만·억·조, K·M·B)이 붙으면 무효**.
- **어림선 `|lvl` 은 부호까지 본다** — 「-7,000선」은 양수 칸에 맞지 않는다. 글 CLI 출력도 어림선 칸을 싣는다(칸 합 == 총수).

## 12. codex 구현 검토 2회 반영(2026-11-21)
- **어림선은 표 칸에서도 `level`**: 표 대조가 맞은 칸이라도 맞는 `|lvl` 표식이 있으면 `table` 이 아니라 배타 칸 `level` 로 센다(§11 첫 항목의 예외 — `|lvl` 없는 맞는 표식은 그대로 T). 내역(`lvl`·`stale_refs` 등)도 표식 쪽 것을 그대로 센다.

## 13. main 의 1a(자료 누락 차단) 위에 붙이기(2026-11-22)

병합하려니 main 이 1a 1단계를 받아 `verification/record.py` 를 1a 전 blob(65c9890c)으로 **고정**해 두었다 — 스위치(`inputs.EFFECTIVE`)가 꺼진 동안 판정이 1a 전과 같다는 근거였다. 숫자 출처의 기록 몫이 바로 그 파일에 있어서, 사용자가 셋 중 「고정 풀고 붙여」를 골랐다(나머지: 바깥 단계로 빼기 · 1a 를 켤 때 같이).

- **1판 `record.py`**: 숫자 출처 몫(`result: sources`·`optional_argv`·ctx `first_html`·`contested`·us-news 경로)만 더한 판(blob 9b6e6aaa). 바이트 고정 시험은 **같은 결과 시험**으로 바꿨다 — 1a 전 blob 을 git 에서 꺼내 불러, 실제 설정의 us·kr 검사기 전부(숫자 출처 제외) × 출력 일곱 꼴에서 `_argv`·`_classify`·기록 칸·`_inputs`·`_mask`·`repo_paths` 가 같다(`test_switch_off.py`).
- **2판 `record2.py`·`_main2`**: 같은 몫을 옮겼다. 다른 점 하나 — 집계가 어긋나면 1판은 판정 불가, 2판은 미완료. 둘 다 `required: false` 라 글 판정에 들지 않는다.
- **자료 분류표**: `us-news` 갈래를 새로 넣었다. 필수 검사가 읽는 셋(`news/{date}.json` gate · `<tg>` gate optional writer-산출 · `<contested>` gate writer-산출)과 나머지 작업 공간 `unused` 한 줄. `contested` 를 파일 뿌리(`inputs.ROOTS`·`FILE_ROOTS`)에 더했다. 숫자 출처 검사는 두 갈래 모두 `inputs: []`(참고 검사 — 없는 자료는 숫자를 「확인 불가」로 센다). US 쪽의 새 파일 `news/numbers/*`·`telegram/numbers/*` 는 기존 `news/*.json`·`telegram/*.json` unused 줄에 든다.
- ~~**1a 를 켜기 전 할 일**~~ (2026-11-22 해결, 아래): `news/{date}.json` 은 수집 도장이 없다(`stamp_collect.STEP_OF` 에 없음). 켠 날부터 US 뉴스 글이 `unstamped` 로 미완료가 되지 않게, 켜기 전에 도장을 붙이거나 생산자를 다시 정한다.
- **2026-11-22 뉴스 수집 도장**: `fetch_news.py` 가 `collect` 칸을 쓴다 — 요약 전 첫 저장은 failed(running), 끝난 저장은 RSS 피드(기본·새 매체)를 하나도 못 읽었거나 기사가 있는데 요약 0건이면 failed, 그 밖은 ok(피드 몇 곳 실패·요약 일부 실패는 detail). 「읽은 피드」는 응답의 **루트 요소**가 rss·feed·RDF 이고(expat 로 첫 시작 태그만 본다 — `feed_root`) 항목이 있거나 형식 경고가 없는 것 — html 루트의 점검 페이지는 안에 `<channel>`·`<item>` 글자가 있어도 아니다(구현 검토 2회차 #3, 글자 찾기 → 구조 판정). collect 칸이 **있는데** 게이트가 통과시킬 끝난 도장(형식·status ok·as_of=report_date=받으려는 날(3회차 #4 — 파일 안 두 날짜가 함께 옛 날이면 게이트는 stale 인데 동결되던 길)·required_ok·missing 없음·empty 가 items 와 맞음)이 아닌 판은 동결하지 않는다(`stamp_unfinished` — failed·null·반쪽 도장, 구현 검토 2회차 #4). 칸이 없는 도입 전 파일은 그대로 동결. **남은 한계(구현 검토 3회차, 같은 갈래 3번째라 검사를 더하지 않고 멈춤)**: 루트가 rss 인데 채널이 없는 오류 문서(`<rss><!-- <channel> --><error>…`)나 잘린 응답 한 곳만 읽힌 날은 ok·없음 확인이 된다 — 51개 피드가 모두 그런 응답이거나 실패해야 생긴다. **1a 를 켜는 날 할 일(3회차 #1, US 일간과 공통)**: 루틴이 작업 공간으로 자료를 복사할 때 `_collect_status.json` 을 함께 가져오지 않는다(`.claude/ORCHESTRATOR.md` 초기 복사·재개 절차) — 그대로 켜면 정상 수집분도 `unstamped`. 장부: `STEP_OF['us']['news/{D}.json'] = 'news'`(워크플로 단계 id `news`), 동결된 날은 `MAY_KEEP` → kept. `run_gates` 는 `--contested` 를 us-news 밖에서 거절한다(exit 2). KR 은 바꿀 것이 없다 — KR 기록의 뿌리(`kr/data`·`--tg`·`--stance-next`)에 쟁점 분석 파일이 놓이지 않는다(이력은 `data/contested/kr/`). codex 설계 검토 1회차에서 거절한 것: 같은 초에 시작한 재실행(1a 공통의 초 단위 시각 비교 — Actions 에서 일어날 수 없다), 도입 전 동결 파일에 칸이 없는 것(1a 를 켠 뒤 글이 읽는 파일은 새로 수집된 날의 것), 일본어판의 한 번 재조립(파일이 실제로 다시 쓰일 때만).
- **알림 정답표 12건**(`prepub_v1_golden.json`)을 다시 만들었다 — 바뀐 줄은 분량·문체 힌트(「볼 것」의 [검토 권고]·[참고])와 머리의 「검토 N건·참고 N건」뿐임을 줄 단위로 대조했다.
