# US Morning Brief — Orchestrator Runbook

**적용 시점:** 2026-09-21 KST 이후 새로 작성하는 보고서는 `.claude/DESK_REPORT.md`와 `.claude/RESEARCH_WORKFLOW.md`를 적용한다. 이미 발행된 파일은 이 전환을 이유로 다시 쓰지 않는다.

You are the orchestrator for the daily US morning market brief. Follow this runbook start to finish.

**Report trading date**: the most recent completed US trading day. **Authoritative source is the committed data file** (STEP 0 below) — trust `report_date` in `data/market_data.json`, which is the S&P 500's actual last-close date. Do NOT compute it from the KST run day; the old weekday-arithmetic rule caused a duplicate-report bug (2026-07-15). Only if no data file exists, fall back to arithmetic: previous US weekday relative to the KST run day (Tuesday KST → Monday US session, … Saturday KST → Friday), stepping back over US market holidays.

The repository fdo2a/fdo2a.github.io is cloned into your workspace as a source (locate with ls / find; if missing, clone https://github.com/fdo2a/fdo2a.github.io). Its .claude/agents/ directory contains the two subagent definitions used in STEP 1 and STEP 2.

## STEP 0 — 커밋된 데이터 파일 확인 (먼저)

A GitHub Actions workflow (.github/workflows/collect-market-data.yml) collects canonical yfinance/FRED data in a network-open runner and commits `data/market_data.json`, `data/intraday.json`, `data/econ_indicators.json`, `data/sector_performance.html`, `data/yield_curve.png` before this routine fires. **This is the primary data path** — the routine's own environment blocks finance hosts (Yahoo/FRED/exchanges all 403), so do NOT try to fetch them here.

0. **멱등 가드 — 이미 나간 글은 절대 다시 만들지 않는다.** `git -C <repo> pull` 후 `data/market_data.json` 의 `report_date` 를 읽는다. 그 값이 **오늘 기대하는 미국 세션과 같고** `posts/<report_date>.html` 이 이미 커밋돼 있으면 즉시 중단한다: 파일을 고치지도, 커밋하지도, PushNotification 을 보내지도 말고 「already published」만 보고하고 끝낸다.

   **「기대 세션과 같고」가 조건의 핵심이다.** 커밋된 데이터가 아직 어제 것이면(수집이 밀린 날 — 2026-08-27 이래 정상이다) 그 어제 글이 있는 건 당연하므로, 여기서 멈추면 오늘 글이 영영 안 나온다. 데이터가 낡았으면 가드를 통과시켜 아래 3번의 워크플로 재실행으로 내려보내고, **새 데이터를 받은 뒤 이 검사를 다시 한다**.

   이 루틴은 하루에 여러 번 뜰 수 있다 — 수집 커밋에 걸린 웹훅(레포의 **모든** push 에 반응하고, 현재 두 벌이 걸려 있다)과 예약 크론이 함께 있고, GitHub 예약 실행이 2~5시간씩 밀리므로 순서도 보장되지 않는다. 가드가 없으면 그 여분의 회차가 같은 날 글을 다시 쓴다.

   **발행 커밋 직전에 이 검사를 한 번 더 한다.** 웹훅이 여러 벌이라 두 회차가 거의 동시에 시작할 수 있고, STEP 0 의 검사만으로는 둘 다 통과해 둘 다 쓰게 된다. 커밋 직전에 `git pull` 하고 `posts/<report_date>.html` 이 그 사이 생겼으면 **아무것도 커밋하지 말고 중단한다**. push 가 거절되면(이 레포는 KR·thesis 수집이 함께 쓰므로 **우리와 무관한 커밋 때문에도 거절된다**) 강제로 밀지 말고 `git pull --rebase` 후 `posts/<report_date>.html` 이 원격에 생겼는지 확인한다 — 생겼으면 다른 회차가 발행한 것이니 중단하고, 아니면 그대로 다시 push 한다.

1. `git -C <repo> pull` (or re-clone) to get the latest committed data, then Read `data/market_data.json`.
2. If it exists, `report_date` matches today's expected US session (most recent US weekday; if it looks stale by >1 trading day, note it), and `"complete": true` — **copy the five data files to the workspace root** (`market_data.json`, `intraday.json`, `econ_indicators.json`, `sector_performance.html`, `yield_curve.png`) and skip STEP 1's market-data collection entirely. Proceed to STEP 1 for research_notes.md only (the web-research half).
   Also copy the two inherited books if present — they are **non-core**: their absence never blocks publication, and never fails the completeness gate.
   - §9 매크로: `data/macro.json` (yesterday's regime / policy path / transmission), `data/macro_eval.json` (today's verdict — what may move), `data/macro_metrics.json` (axis scores and the new-release list), and **`data/releases/`** — the primary press releases behind today's promoted indicators, already fetched and committed (`index.json` says which succeeded). Copy the whole `releases/` directory. Missing → the writer opens the book in bootstrap mode.
   - 연준 이벤트: **`data/fed/`** 디렉터리 전체 — `events.json`(오늘 다룰 이벤트와 각 원문의 수집 결과)과 `<key>.txt`(성명·기자회견 전문·연설 원문). **대부분의 날에는 `fresh` 이벤트가 없고, 그런 날은 이 섹션을 아예 열지 않는다.** Missing → the writer omits the section entirely. 원문 텍스트 파일이 인용 대조의 정본이므로 디렉터리째 복사한다.
   - 뉴스: `data/news/[DATE].json`이 있으면 `<workspace>/news/[DATE].json`으로 복사한다. DATE는 `report_date`다. 작성자에게 이 파일 경로를 입력으로 전달한다 — 기사마다 `summary_ko`(수집 잡이 만든 한국어 요약)가 들어 있다. 없으면 다른 날짜 파일로 대체하지 않는다.
3. If `data/market_data.json` is missing, stale, or `"complete": false`, **first re-run the collection workflow**. 이게 1순위다: 2026-08-27 이래 GitHub 예약 실행이 2~5시간씩 밀려 **수집이 이 루틴보다 늦게 도착하는 날이 정상이 됐다**(실측: 예약분이 4~5시간 밀린 날이 여러 번). 수동 dispatch 는 밀리지 않고 즉시 뜬다.

   ```
   gh workflow run collect-market-data.yml -f force=true
   sleep 15
   RUN=$(gh run list --workflow=collect-market-data.yml --event=workflow_dispatch \
           --limit 1 --json databaseId --jq '.[0].databaseId')
   timeout 900 gh run watch "$RUN" --exit-status
   git pull
   ```

   실행 ID 를 집고 `--exit-status` 를 붙인다 — 맨 `gh run watch` 는 엉뚱한 예약 실행을 기다리고, `--exit-status` 가 없으면 실패한 수집도 성공으로 읽혀 낡은 데이터가 그대로 발행된다. If that path is unavailable or still leaves gaps, note exactly which fields `missing` lists and run the full STEP 1 collector to fill the whole set (or just the gaps). The Actions run may have partially failed; treat its output as a starting point, not gospel.

   **폴백이 끝나면 `report_date`와 `complete`를 다시 본다** — 날짜가 여전히 기대 세션보다 이르면 발행하지 않고 중단한다. 뒤의 completeness 게이트는 필드 존재만 보고 날짜는 보지 않으므로, 여기서 막지 않으면 전 세션 자료가 오늘 날짜로 나간다.

**토큰 규율**: 이 데이터 파일들이 있으면 그 안의 수치를 웹서치로 재확인하지 않는다. 웹 리서치(STEP 1의 리서치 절반)는 뉴스·해석·컨센서스처럼 파일에 없는 것에만 쓴다. 경제지표 Actual/Previous는 econ_indicators.json이 이미 확정했다.

## STEP 1 — 데이터 수집·검증 (subagent: brief-data-collector)

**운용자 대상 시황·리서치:** STEP 1 시작 전에 `.claude/DESK_REPORT.md`를 읽고 그 문서의 Handoff를 수행한다. 기존 시황·수급·뉴스 자료를 유지하면서 `research_notes.md`에 `운용 판단 브리핑`을 추가한다. 작성자에게 이 절과 해당 문서 경로를 반드시 넘긴다. STEP 2 초안과 STEP 2.5 윤문 후에는 그 문서의 Editorial acceptance를 수행한다. 실제 보유·운용제약이 주어지지 않았으면 자산별 조건부 판단으로 쓰며, 새 거래 아이디어가 없는 날도 정상 발행한다.

**리서치 인계:** `.claude/TRADER_LEARNING.md`를 반드시 읽고 Research handoff를 수행한다. 수집·작성 담당에게 해당 문서 경로, 직전 발행본 경로(없으면 bootstrap), `research_notes.md`의 `학습·복기` 절을 전달한다. STEP 2 초안과 STEP 2.5 윤문 후에 그 문서의 Editorial check를 수행하고, 위반 문단을 수정한 뒤 기존 발행 게이트를 통과시킨다.

**앞으로 작성하는 보고서:** `.claude/RESEARCH_WORKFLOW.md`를 읽고 증거 → 가설·복기 기록 → 당일 cycle 순서로 진행한다. 원장은 `research/us`, 원장·증거 파일을 새 발행본과 함께 커밋한다. 기존 발행본은 이 변경의 대상이 아니다. 작성자에게 cycle ID와 모든 미해결 가설을 전달하고, 초안과 윤문 후 모두 아래 검사를 통과시킨다. 새 자료가 추가되면 cycle도 다시 기록한다.

```bash
python3 scripts/check_research.py check --span daily --html <새 초안> --root research/us --market us --date <DATE> --cycle <CYCLE_ID>
```

STEP 2.5 `finalize`에도 같은 명령을 `--gate`로 추가한다(`--html {f}`). 초안 전후 비교는 workflow의 `compare`로 기록하고, 인과관계·유보 표현의 의미 보존은 사람이 확인한다.


If STEP 0 already produced a complete market_data.json/intraday.json/yield_curve.png, you still need **research_notes.md** — launch the collector subagent (or fallback) for the web-research portion only (STEP 2 of the agent file: 시황 동인·채권 맥락·메모리·AI 인프라·경제지표 4축). Otherwise run it in full.

Launch the Agent tool with subagent_type "brief-data-collector", run synchronously (run_in_background: false). Prompt: the report trading date [YYYY-MM-DD], whether market data is already present (and its path), and the instruction to produce any missing artifacts in the workspace root: market_data.json, intraday.json, yield_curve.png (may be skipped if week-ago yields are missing), research_notes.md.

**위임한 것은 다시 읽지 않는다.** 서브에이전트는 **동기**(`run_in_background: false`)로 부르고, 기다리는 동안 아무것도 열지 않는다. 에이전트 정의 파일(`.claude/agents/*.md`), 그 에이전트가 읽을 데이터 파일, 직전 발행본은 오케스트레이터가 읽지 않는다 — **경로만 넘기고**, 돌아온 산출물과 게이트 출력만 본다. 폴백으로 general-purpose 에이전트를 쓸 때도 정의 파일 본문을 붙여 넣지 말고 「이 파일을 먼저 Read 하라」고 경로를 준다. (2026-09-22 KR 실행이 에이전트를 백그라운드로 띄워 두고 지시문 35 KB·데이터 12개·직전 발행본을 다시 읽다가 5시간 한도로 죽었다.)

Fallbacks: if the subagent type is not available, launch a general-purpose agent whose prompt tells it to Read .claude/agents/brief-data-collector.md first and follow it (do not paste the file body), plus the report date. If the Agent tool itself is unavailable, execute that file's instructions yourself, in full, before continuing.

Gate before proceeding: market_data.json parses as JSON with non-null indices/sectors/yields; intraday.json parses; research_notes.md exists and contains the 4-axis macro indicator table. If `data/macro_metrics.json` lists `headline_releases`, research_notes.md must also carry section ⑧ (신규 발표 해부) with an entry per release — or an explicit note that the primary release could not be reached. If the gate fails, relaunch the subagent once with the specific error details; if it fails again, fix the gaps yourself using the agent file's instructions.

**Completeness gate (사용자 지시 2026-07-14 — 완성본만 발행)**: the canonical dataset must be COMPLETE before STEP 2 — indices 6종(3대 지수+러셀+Growth/Value), sectors 11종 전부(XLRE 포함) + sector_performance 5기간, yields 2Y/5Y/10Y/30Y + curve chart, FX 4종, commodities 4종, memory 6종, AI infra 5종. "미확인이라 표에서 제외" 처리는 발행 사유가 아니라 발행 중단 사유다. Yields are Naver Treasury closes (17:05 ET SIFMA cash close) for all four tenors, which puts them on **one as-of date** (2026-09-04). Yahoo spot (^FVX/^TNX/^TYX) → FRED is the fallback chain when Naver is unavailable, and only then do tenors carry different as-of dates — that fallback is degraded but publishable, not a gate failure. The gate requires a non-null level + week_ago per tenor, and additionally fails closed on `yields/naver_close_not_posted`: a run that fired **before** the 17:05 ET Treasury close must not be committed as complete, or the later run gets skipped by the idempotency guard and the day's curve stays stuck on the prior session. If primary sources (yfinance/FRED) are blocked, retry via alternative canonical routes (FRED DGS5/DGS10/DGS30 as the yield fallback, FRED CSV via curl, exchange sites) until complete. If the dataset still cannot be completed, DO NOT publish a partial report to any channel — send a PushNotification listing exactly which fields are missing and why, and stop.

## STEP 2 — 리포트 작성 (subagent: brief-report-writer)

**뉴스 입력 (작성 전)** — 커밋된 `news/[DATE].json` 의 각 항목에 수집 잡이 원문을 읽고 만든 한국어 요약 `summary_ko` 가 있다(2026-09-24). **루틴에서 기사 본문을 다시 받지 않는다** — 클라우드 환경은 CNBC·Yahoo 에 403 이라 예전의 `--bodies-only` 재수집은 한 번도 성공하지 못했고, 실패한 재수집이 `body_chars` 를 0 으로 덮어써 게이트가 뉴스 섹션을 면제해 왔다(9/19~9/22 발행본에 뉴스가 없던 이유). `summary_ko` 가 있는 갈래 기사가 하나라도 있으면 「오늘의 뉴스」 섹션은 의무다. 하나도 없으면(예: 레포 Variables 에 WIF 값 미등록, 항목의 `summary_note` 참조) 섹션 없이 발행하되 **최종 보고에 그 사유를 적는다** — 조용히 빠지게 두지 않는다.

Launch the Agent tool with subagent_type "brief-report-writer", run synchronously. Prompt: the report trading date, the list of input files from STEP 1 (**including macro.json / macro_eval.json / macro_metrics.json if present**), and the required outputs in the workspace root — morning_brief_[YYYY-MM-DD].html **plus macro_next.json** (the updated macro book; the input macro.json must be left untouched). Same fallbacks as STEP 1 (agent file: .claude/agents/brief-report-writer.md).

Gate before proceeding (발행 게이트): (a) `grep -c '확인필요' <html>` — must be 0; (b) spot-check 5+ numbers by grepping the HTML for specific values from market_data.json / intraday.json / econ_indicators.json (e.g. `grep -o '4\.62' <html>`), NOT by reading the whole ~34K-token HTML into context. If either check fails, relaunch the writer subagent with the specific violations; repeat until clean. 수치 창작 절대 금지 — 미확인 항목은 삭제·재구성이 원칙.

**매크로 게이트 (§10)** — run `python scripts/check_macro.py --html morning_brief_[DATE].html --datadir <workspace>` from the repo clone. It fails the run when: the policy path의 `falsifier` 가 지면에 없을 때; the regime label is outside the 3×3 controlled vocabulary; the regime sits outside `allowed_regimes` (the writer moved it on a day with no new release, inside the 5-business-day lock, or against what the axis scores imply); the axis scores or the FedWatch probability are not quoted in the section; a newly released indicator listed in `headline_releases` has no `data-release` anatomy block, or that block stops at the headline number (no primary source named, fewer than three figures); a transmission direction is outside its `allowed_directions`; the policy path was re-timed without either a new release or a 15%p probability move; macro_next.json is missing / not dated today / disagrees with the §8 markers; or an axis-table row (`data-indicator`) is missing, or its 직전 대비 / 추세 cell, Actual or Previous differs from the computed value (추세 must be 「—」 when `macro_metrics.json` is not today's). Relaunch the writer with the exact violations.

**가격 맥락 게이트 (§4·§6·§7·§8)** — run `python scripts/check_price_context.py --html morning_brief_[DATE].html --datadir <workspace>` from the repo clone. It fails the run when: a cross-asset relationship whose sign flipped against the prior 60 sessions is not written about (needs a `data-relation="KEY"` paragraph — same discipline as §8's reconciliation, disagreement allowed, silence not); a `data-attribution` block prints the sector split without the residual it cannot explain, or prints one at all on a day the sector weights barely fit the index; or internal machinery (주성분·고유값·필드명) reached the page. Non-core: an older dataset with no `price_context` block passes untouched. Relaunch the writer with the exact violations.

**시황 게이트 (「오늘의 장」)** — run `python3 scripts/check_session.py --html morning_brief_[DATE].html --datadir <workspace> --market us` from the repo clone. It fails the run when: a `data-session` paragraph is missing or empty; a region whose average direction diverged from the S&P 500 is not written about (silence is the failure, disagreement is fine); the participation reading is narrated on a neutral day or omitted on a day it fired; a global close printed in the table disagrees with the collected value, or a close older than three sessions carries no as-of date; the reading is called 「상승 종목 비율」·「등락 종목 수」·「시장 폭」; internal field names or a 「§N」 notation reached the page. Non-core: a dataset with no `session` block passes untouched.

**연준 이벤트 게이트 (「연준 이벤트」)** — run `python3 scripts/check_fed.py --html morning_brief_[DATE].html --datadir <workspace>` from the repo clone. It fails the run when: today has no fresh Fed event but the section was published anyway (**침묵이 기본값이다** — FOMC·잭슨홀 같은 자리가 없는 날 이 섹션을 열면 이벤트 섹션이 아니라 매일 새로 쓰는 논평란이 된다); a fresh tier-1 event has no section, no `data-fed-event` intro, or fewer than two verified quotes; **a quoted sentence is not in the collected primary document, character for character**; a quote was printed for an event whose document could not be fetched; a quote has no Korean translation or no source caption; a computed statement redline has no `data-fed-change` block, or that block quotes none of the changed sentences; there are fewer than two `data-fed-idea` blocks, an idea hangs off a quote that was never printed, or an idea has no invalidation condition; or a figure in the section is in neither the data files nor the primary document. **이 게이트의 자리는 인용문이다** — 지어낸 수치는 데이터와 맞대면 걸리지만 지어낸 발언은 그럴듯할수록 안 걸린다. 인용의 문턱 값(무효화 조건 안의 수치)만 창작 검사에서 면제된다. Relaunch the writer with the exact violations.

**캘린더 게이트 (§9 「다음 발표 일정」 카드)** — run `python3 scripts/check_calendar.py --html morning_brief_[DATE].html --datadir <workspace>` from the repo clone. 금지형이다 — 카드를 채우라고 요구하지 않는다. 막는 것은 셋: `data-calendar="<key>"` 가 **수집한 적 없는 일정**을 가리키는 것, 표식이 가리키는 일정과 **다른 날짜**를 적는 것, **시각을 모르는 일정에 시각을 적는 것**. 낡은 `calendar.json` 은 없는 것과 같이 다룬다(어제 일정으로 오늘 표식을 인가하면 하루 밀린 시각이 인쇄된다). 표식이 없는 글은 그대로 통과한다. Relaunch the writer with the exact violations.

**뉴스 게이트 (오늘의 뉴스)** — run `python3 scripts/check_news.py --html morning_brief_[DATE].html --datadir <workspace> --date [DATE]` from the repo clone. 수집분 `news/<date>.json` 과 발행본을 `data-news` 표식으로 대조한다. It fails the run when: 수집되지 않은 `guid` 를 실었을 때(지어낸 기사); **수집 요약(`summary_ko`)이 없는** 기사를 실었을 때(제목만 보고 쓴 것); 블록이 그 기사의 `summary_ko` 와 글자 유사도 0.5 미만일 때(실제 guid 아래 다른 내용); 같은 기사를 두 번 실었을 때; 한 항목의 본문이 240자 미만(RSS 한 줄 요약을 옮긴 것)이거나 420자 초과일 때; `data-news` 없는 뉴스 블록이 있을 때; `display:none`·`hidden`·주석으로 **숨긴 블록**으로 항목 수를 채웠을 때(2026-09-19 실측으로 셋 다 재현 후 차단); 블록의 링크가 그 기사의 원문이 아닐 때. **수집분이 없거나 비면 섹션 의무만 면제되고 표식 대조는 그대로 돈다** — 수집이 실패한 날이 지어낸 뉴스가 실릴 확률이 가장 높다(2026-09-19 codex 검토 #1). 요약이 하나도 없는 날도 섹션 없이 발행할 수 있다. **`--date [DATE]` 를 반드시 준다** — 없으면 최신 파일을 집어 어제 수집분이 오늘의 근거가 된다(#11). 그날 뉴스를 기억에서 꺼내 쓰는 것이 이 게이트가 막는 실패다.

**출처 게이트 (§9 발표 해부·연준 이벤트)** — run `python3 scripts/check_sources.py --html morning_brief_[DATE].html --datadir <workspace>` from the repo clone. **금지형이다 — 링크를 요구하지 않는다.** 귀속은 문장의 주어로 쓴다(「BLS 는 … 밝혔습니다」). 막는 것은 «인쇄된 링크가 거짓말인 경우»뿐이다: 수집한 원문 목록에 없는 URL, 수집에 실패한 문서(`ok:false`)를 가리키는 링크, 다른 발표의 URL 이 이 블록에 붙은 것, 표식 없는 블록의 외부 링크, 글자 없는 링크, http(s) 아닌 스킴. **숨긴 링크도 검사한다** — 미디어쿼리 한 줄로 「숨김」 판정이 뚫리는 것을 확인했고, CSS 엔진 없이 렌더 결과를 맞힐 수 없다. `script`/`style`/`template` 만 빠진다. 수집 파일이 없거나 날짜가 어긋나면 **아무것도 인가되지 않은 것**으로 본다 — 게이트가 꺼지지 않는다(수집이 실패한 날이 지어낸 링크가 실릴 확률이 가장 높은 날이다). Head 의 AdSense·canonical·OG·JSON-LD 와 사이트 안 이동 링크는 대상이 아니다. Relaunch the writer with the exact violations.

**무게중심 게이트** — `python3 scripts/check_weight.py --html <새 초안> --datadir <workspace> --market us`. 필수 시황 섹션이 비어 있지 않은지, 가격 위치의 수치 근거와 큰 변동의 설명, 전략 코멘트의 논리 순서를 검사한다. 총 글자 수 하한과 시황/판단 비율은 강제하지 않는다. US 매크로 상한은 발표일 4,600자·축약일 2,400자로 유지한다.

**가독성 게이트 = 초안 수리 루프 (실패로 루틴 종료 금지)**

1. `python3 scripts/apply_readability.py <morning_brief 절대경로>` 다음 **`python3 scripts/apply_colors.py <morning_brief 절대경로>`**(수치 칸 방향색 — 오르면 초록, 채권 금리는 반전, 매크로는 같은 행 「직전 대비」 칸을 따른다. 보이는 글자는 안 바뀌므로 수치 대조에 영향이 없다. `--check`는 미적용이면 exit 1 이므로 체인에서 빠진 날을 알 수 있다)로 v5 조판(데스크톱 본문 17px·**폭 제한 없음** — 문장이 카드를 다 채운다, 라벨은 제 줄에, 캡션 특정도 교정)·빠른 이동·긴 문단 분리를 적용하고, `python3 scripts/check_readability.py --strict --no-inline-images <morning_brief 절대경로>`와 **`python3 scripts/check_style.py <morning_brief 절대경로>`**의 전체 출력을 저장한다. 문체 검사는 **쉬운 말 검사를 겸한다(2026-08-26)** — 풀어 쓸 수 있는 음차어, 풀이 없이 처음 나온 전문어, 한 문장에 겹친 낯선 말을 잡는다. 나머지 문체 항목은 「말하듯이 쓴다」 기준에서 셀 수 있는 부분(비인칭 피동·번역투 연결·서술어 없는 명사형 머리말·「~한 상태다」 종결·같은 문단 머리말 반복·「~다」 연속)을 본다. **STEP 2.5의 윤문과 별개로 여기서 항상 돈다** — 윤문은 건너뛸 수 있어도 문체 기준은 건너뛰지 않는다.
2. 실패하면 출력에 찍힌 위반을 원인별로 고친다. 문체 위반은 「말하듯이 쓴다」 절의 해당 항목대로 문장을 다시 쓴다: 헤드라인은 방향·촉매·행동만 남기고, 120자 초과는 시간·주제가 바뀌는 곳에서 문장을 나누며, 수치 5개 이상은 정확한 값은 표에 두고 산문에는 관계만 남긴다. 과잉 정밀도는 산문만 반올림하고 정확한 값은 표에서 보존한다. 반복 수치는 첫 설명과 정본 표 한 곳만 남긴다.
3. writer를 **전체 보고서를 유지한 채 위반 문단만 수정하라**는 지시와 검사 원문으로 다시 실행한다. 수정 뒤 데이터 정본과 표를 재대조하고 apply → strict check를 반복한다.
4. writer 재실행이 두 번 연속 같은 위반을 남기면 오케스트레이터가 해당 문단을 직접 국소 수정한다. 긴 문장 분리 → 중복 수치 삭제 → 산문 반올림 순서로 고치고 다시 검사한다. **통과할 때까지 이 수리 루프를 계속한다.**

가독성 실패는 현재 초안을 반려할 뿐, “오늘 레포트 미발행” 사유가 아니다. 가독성 때문에 중단 알림을 보내지 않는다. 데이터 정본이 끝내 완성되지 않는 경우만 기존 completeness gate에 따라 중단할 수 있다.

## STEP 2.5 — AI 티 제거 (발행 전 마지막 손질)

2026-08-25 사용자 지시. 리포트를 **말하듯이** 쓰라는 문체 기준(`.claude/agents/brief-report-writer.md`의 「말하듯이 쓴다」 절)을 writer가 지켰더라도, 매일 같은 틀로 생성된 글에는 사람이 안 쓰는 리듬이 남는다. 발행 직전에 한 번 걸러낸다.

**1. 원본은 건드리지 않는다. 사본에서 작업한다.**

```bash
cp morning_brief_[DATE].html morning_brief_[DATE].humanizing.html
```

윤문도 검증도 전부 이 사본에서 한다. 원본이 바뀌는 순간은 4번의 finalize 하나뿐이다. 그래서 스킬이 예외로 죽든, 시간이 초과되든, 문단을 반만 쓰고 멈추든, 사본을 지우면 그것으로 끝이다 — 원본은 애초에 한 번도 수정되지 않았다. **원본을 먼저 고치고 나중에 되돌리는 방식은 쓰지 않는다.** 되돌리기가 실패하는 분기가 남기 때문이다.

**2. 산문을 꺼낸다.**

```bash
python3 scripts/humanize_prose.py extract morning_brief_[DATE].humanizing.html
```

`prose_in.txt`(손댈 문단만, 이름표 `[[P001]]`이 붙어 있다)와 `prose_map.json`(사이드카)이 나온다. 표 안 문단·캡션·에디터 노트는 애초에 뽑히지 않는다 — **넘기지 않은 것은 훼손될 수 없다.** 인라인 태그(`<strong>` 등)는 `⟦0⟧` 자리표로 바뀌어 나가고, 되꽂을 때 하나라도 없으면 거부된다.

**3. `prose_in.txt`의 문장을 고친다. 이름표 줄(`[[P001]]`)은 건드리지 않는다.**

`humanize-korean` 스킬은 레포 `.claude/settings.json`이 마켓플레이스(`epoko77-ai/im-not-ai`)째 등록해 둔다 — 이 레포를 클론한 세션은 시작할 때 설치를 시도한다. **그래도 쓸 수 있다고 가정하지 않는다.** 트리거의 `allowed_tools`에 `Skill`이 빠져 있으면 설치돼도 부를 수 없고(스킬이 서브에이전트를 띄우므로 `Agent`도 있어야 한다), 샌드박스가 마켓플레이스를 못 받아오는 경우도 있다.

**목록에 보이는 것과 부를 수 있는 것은 다르다.** `allowed_tools`는 사전 승인 목록이라 이름이 보여도 호출이 거부될 수 있다. 그러니 판정은 호출해 보고 한다 — 거부·오류·산출물 없음 중 하나라도 나오면 **반쯤 나온 결과는 버리고** 직접 고친다. **어느 쪽이든 이 단계를 건너뛰지는 않는다.**

- **스킬로 할 때**: `prose_in.txt`를 입력으로 준다. 스킬은 텍스트를 받아 `_workspace/{run_id}/final.md`(마크다운)를 내놓는다 — **HTML을 고쳐 주지 않으므로 HTML을 통째로 넘기는 사용법은 없다.** 이름표를 그대로 두고 문장만 고치라고, **강도는 「보수」**로 명시한다 — 스킬이 절을 갈아끼우기 시작하면 4번에서 통째로 거부된다.
- **직접 할 때**: `prose_in.txt`를 그 자리에서 고치고, 그 파일을 그대로 4번의 `--payload`로 쓴다. `python3 scripts/check_style.py <html>`의 출력이 작업 목록이다. 검사가 짚은 항목부터 고치고, 검사가 못 보는 아래 셋도 함께 훑는다.
  - **주체가 모호할 때만 밝힌다.** 문맥상 분명한 주어를 문장마다 반복하지 않는다.
  - **한 문장에 한 관계만 남긴다.** 「A했다가 B했고 이후 C해서 D로 마감했다」는 문장이 아니라 표다. 시각이 셋 이상이면 나눈다.
  - **판단의 강도를 보존한다.** 피동 표현을 줄여도 추정을 단정이나 인과관계로 바꾸지 않는다.

**두 경로 모두 문장만 만진다.** 숫자·자리표·이름표는 그대로 둔다. 4번이 그것을 강제한다.

**4. 되꽂고, 검사하고, 통과했을 때만 원본을 교체한다. 한 명령으로 한다.**

```bash
python3 scripts/humanize_prose.py finalize morning_brief_[DATE].humanizing.html \
  --original morning_brief_[DATE].html --payload <고친 prose_in.txt 또는 _workspace/{run_id}/final.md> \
  --gate "python3 scripts/check_style.py {f}" \
  --gate "python3 scripts/check_readability.py --strict --no-inline-images {f}" \
  --gate "python3 scripts/verify_post.py {f} --before morning_brief_[DATE].html --skip-layout" \
  --gate "python scripts/check_macro.py --html {f} --datadir <workspace>" \
  --gate "python scripts/check_price_context.py --html {f} --datadir <workspace>" \
  --gate "python3 scripts/check_session.py --html {f} --datadir <workspace> --market us" \
  --gate "python3 scripts/check_weight.py --html {f} --datadir <workspace> --market us" \
  --gate "python3 scripts/check_research.py check --span daily --html {f} --root research/us --market us --date <DATE> --cycle <CYCLE_ID>" \
  --gate "python3 scripts/check_fed.py --html {f} --datadir <workspace>" \
  --gate "python3 scripts/check_news.py --html {f} --datadir <workspace> --date [DATE]" \
  --gate "python3 scripts/check_sources.py --html {f} --datadir <workspace>" \
  --gate "python3 scripts/check_calendar.py --html {f} --datadir <workspace>"
```

연구 원장 게이트와 연준 이벤트 게이트가 이 목록에 **반드시 있어야 한다** — 윤문은 문단을 통째로 갈아끼우므로 판단 유보나 결측 고지가 조용히 사라질 수 있다. 연준 인용문은 더 분명하다: 한 낱말만 다듬어도 원문 대조가 깨지고, 그러면 의장이 하지 않은 말이 따옴표 안에 남는다. 인용 블록 자체는 `humanize_prose.py`가 애초에 뽑지 않지만(넘기지 않은 것은 훼손될 수 없다), 검사는 그 가정을 믿지 않고 다시 한다. 초안 단계에서 한 번 통과한 것으로는 최종본을 보증하지 못한다(2026-09-01 codex 검토).

되꽂기 → 바뀐 문단 출력 → 게이트 순서로 돌고, **전부 통과했을 때만** `os.replace`로 원본을 교체한다. 하나라도 실패하면 사본을 지우고 exit 1로 끝난다 — 원본은 처음부터 수정되지 않았다. **맨손 `mv`는 쓰지 않는다.** 검사를 건너뛰고 교체할 자리를 남기지 않는 것이 이 명령의 존재 이유다.

되꽂기가 거부하는 것 — **문단마다** 이것들이 원문과 같아야 한다:

- 숫자 (**부호 포함** — `+1.2%`와 `-1.2%`는 다른 값이다)
- 영문 이름·티커 (AAPL과 TSLA를 문단끼리 맞바꾸면 각자 제 원문과는 여전히 닮아 유사도로는 안 잡힌다)
- **판단 어휘** — 개선·악화·보합, 둔화·가속·재가속, 뚜렷·완만·미미, 레짐 이름 9종, 확대·축소·중립. 「완만한 개선」을 「뚜렷한 악화」로 바꾸면 3-gram 유사도는 0.8이 넘는다. 말투는 바꿔도 이 낱말들은 그대로 둔다
- 링크가 감싼 말 (`<a>`가 「연준 보고서」에서 「노동부 자료」로 옮겨 붙으면 멀쩡한 링크가 엉뚱한 출처를 가리킨다)
- 인라인 자리표의 개수와 순서, 문단 길이(0.5~2.0배)
- 그리고 **몸통이 제 원문보다 다른 문단에 더 닮지 않을 것**

**이 단계가 허락하는 것은 문법과 말투까지다.** 종결어미를 바꾸고, 주어를 되살리고, 긴 문장을 나누는 것 — 거기까지다. 절을 갈아끼우는 재작성은 문턱(닮은 정도 0.80)에서 걸린다. 원문에 없던 인과를 넣거나 조건절을 떼어 단정으로 만드는 의미 변화는 어떤 사실 검사로도 못 잡으니, **애초에 그만큼 못 바꾸게 막는 편이 낫다.** 08-21 발행본 58문단 실측에서 말투 편집은 최저 0.95, 절을 갈아끼운 재작성은 중앙 0.62로 두 무리가 갈렸다.

닮은 정도 비교는 총체적 뒤바뀜도 함께 잡는다. 이름표는 자리만 정하지 몸통이 제 자리 것인지는 보증하지 않는다 — 숫자가 없는 문단끼리 내용을 통째로 맞바꾸면 수치 검사도 `verify_post`도 전부 통과한다(2026-08-25 codex 검토에서 실제로 뚫린 뒤 들어간 검사다).

`finalize`는 게이트가 **하나도 없으면 시작하지 않고**, 사본과 원본 경로가 같아도 시작하지 않는다(검사 실패 시 원본을 지우게 된다). 게이트는 셸을 거치지 않고 인자 배열로 실행된다.

`check_macro`·`check_price_context`가 여기 다시 들어가는 이유가 있다. STEP 2의 게이트들은 **윤문 전 원고를 보고 통과시킨 것이다.** 윤문은 문장을 합치거나 나누므로 문장 길이·수치 밀도가 깨질 수 있고, 통제 어휘나 `data-*` 표식을 건드리면 §8·§9가 검사받지 않은 채로 나간다.

**5. 명령이 찍어 준 「바뀐 문단」을 읽는다.**

허용 범위를 문법·말투로 좁혔으니 남는 것은 그 안에서의 미세한 뉘앙스뿐이다. 그래도 **사람이 한 번 읽는다** — finalize가 바뀐 문단만 전/후로 찍어 주므로 그 출력을 그 자리에서 읽는다.

**이 읽기는 교체를 막지 못한다** — finalize는 이미 원본을 바꾼 뒤다. 그래서 여기서 이상한 것을 발견하면 발행 후 검토 게이트(`.claude/REVIEW_GATE.md`)로 넘긴다. 그쪽이 발행본을 다시 읽고 정정하는 자리다. 윤문이 만든 의미 변화도 그 절차가 잡는 대상에 포함된다.

**윤문이 거부돼도 발행은 계속한다.** 말투는 있으면 좋은 것이고, 게이트는 필수다.

사본(`*.humanizing.html`)·`prose_in.txt`·`prose_map.json`과 스킬 작업 폴더(`_workspace/`)는 `.gitignore`에 걸려 있다. STEP 3의 `git add -A`가 쓸어 담지 않는다.

## STEP 3 — Publish to the blog (GitHub Pages 루트 사이트)

Site base URL: https://fdo2a.github.io/

1. Copy the report HTML into the repo as posts/[YYYY-MM-DD].html, then make two injections:
   (a) Immediately BEFORE `<div class="doc">`, this navigation block:
```html
<div style="max-width:1120px;margin:0 auto;padding:14px 18px 0;display:flex;align-items:center;gap:10px;">
  <a href="../index.html" style="text-decoration:none;background:#fff;border:1px solid #E5E8EB;border-radius:9999px;padding:6px 14px;font-size:12px;font-weight:700;color:#191F28;">‹ 전체 보고서</a>
  <a href="../index.html" style="text-decoration:none;font-size:14px;font-weight:800;color:#0064FF;letter-spacing:-0.02em;">US Market Brief</a>
</div>
```
   (b) Immediately BEFORE `<title>`, SEO meta tags:
```html
<meta name="description" content="[헤드라인 한 줄 요약]. [YYYY-MM-DD] 미국 증시 모닝브리프.">
<link rel="canonical" href="https://fdo2a.github.io/posts/[YYYY-MM-DD].html">
<meta property="og:type" content="article">
<meta property="og:title" content="미국 증시 모닝브리프 — [YYYY년 M월 D일 (요일)]">
<meta property="og:url" content="https://fdo2a.github.io/posts/[YYYY-MM-DD].html">
```
2. Copy yield_curve.png into the repo as assets/yield_curve_[YYYY-MM-DD].png (**the post references this file** via `../assets/yield_curve_[DATE].png` — it is not embedded, so this copy is required for the chart to render), then promote the writer's macro book:
   - `macro_next.json` → `data/macro.json`
   Tomorrow's Actions run judges today's regime and triggers against this file. Publishing without promoting it leaves the macro book frozen — and because macro.json also carries `last_seen`, a missed promotion makes every indicator read as newly released tomorrow, which would hand the writer a free regime change.
3. **에디터 노트 (있는 날만)** — if `notes/[YYYY-MM-DD].md` exists in the repo clone, run `python3 scripts/apply_note.py posts/[YYYY-MM-DD].html` from the repo root. That file is the publisher's own view, written by hand before the run; the script drops it in verbatim after §2 전략 코멘트. **Never write, edit, polish, or fact-check that text, and never author the section yourself** — a note the publisher did not write is worse than no note. The script is a no-op (exit 1, page untouched) when the file is missing, empty, or still the unedited template, so it is safe to run unconditionally. Most days there is no note and no section.
4. Update posts.json in the repo root: add {"date", "title", "headline"}. Same-date entry → REPLACE, never duplicate. Keep valid JSON.
5. Regenerate sitemap.xml from posts.json: one <url> for https://fdo2a.github.io/ (lastmod=today, changefreq daily) plus one <url> per post (https://fdo2a.github.io/posts/DATE.html, lastmod). Keep valid XML.
6. Commit and push to main:
   git add -A && git commit -m "Add [YYYY-MM-DD] brief" && git push
   If the push fails, continue with remaining steps and report the failure clearly in your final message and PushNotification.

## STEP 4 — Notify

Send a PushNotification with the headline and the blog post URL (mention any failures).

**발행 채널은 블로그 하나뿐이다 (2026-08-18 사용자 지시로 Notion 발행 중지).** Do NOT publish to Notion, do NOT generate a PDF, do NOT use SendUserFile, and do NOT send email. If a Notion connector is available in the session, leave it alone — its presence is not an instruction to use it.

## STEP 5 — 발행 후 자동 검토·정정

최초 push 성공 뒤 로컬 러너가 Codex 검토와 Claude 정정·재게시를 이어받는다.
절차는 `.claude/REVIEW_GATE.md`의 「US·KR 무인 정정」을 따른다.
클라우드 루틴은 Codex 검토를 완료했다고 보고하지 말고 최초 발행과 사후 검토 대기를 구분한다.
이미 발행된 글의 재작성 금지 가드는 그대로 유지한다. 정정은 로컬 러너가 맡는다.

## RULES
- All prices/% changes in the published report MUST come from market_data.json / intraday.json; macro indicator values from research_notes.md. 수치 창작 절대 금지.
- **완성본만 발행 (2026-07-14 사용자 지시)**: 핵심 표(지수·섹터·채권·FX·원자재·메모리·AI 인프라)에 누락 항목이 있는 채로 발행 금지. 완성 불가 시 발행하지 말고 PushNotification으로 누락 내역을 보고할 것. 웹 리서치로 대체 수집한 시세는 발행 전 반드시 복수 출처 교차 확인 — 단일 검색 결과 수치는 신뢰하지 않는다 (7/13호에서 FX 방향·유가 등락률 오류 발생 전례).
- **발행본에 [확인필요] 금지 (STEP 2 게이트).** 미확인 항목은 끝까지 확인하거나 삭제·재구성.
- Web findings attributed to sources. Clear, natural report prose (근거와 판단이 분명한 자연스러운 보고서 문체).
- **「buy-side」 금지 (2026-08-22 사용자 지시)** — 발행본 어디에도 쓰지 않는다. §2 헤더는 「전략 코멘트」, 해석 박스는 「전략 해석」. `scripts/check_macro.py` 게이트가 차단한다.
- Final message: blog (GitHub Pages) delivery status, which subagents ran (or which fallback was used), and any failures.
