# US Morning Brief — Orchestrator Runbook

**적용 시점:** 2026-09-21 KST 이후 새로 작성하는 보고서는 `.claude/DESK_REPORT.md`와 `.claude/RESEARCH_WORKFLOW.md`를 적용한다. 이미 발행된 파일은 이 전환을 이유로 다시 쓰지 않는다.

You are the orchestrator for the daily US morning market brief. Follow this runbook start to finish.

**Report trading date**: the most recent completed US trading day. **Authoritative source is the committed data file** (STEP 0 below) — trust `report_date` in `data/market_data.json`, which is the S&P 500's actual last-close date. Do NOT compute it from the KST run day; the old weekday-arithmetic rule caused a duplicate-report bug (2026-07-15). Only if no data file exists, fall back to arithmetic: previous US weekday relative to the KST run day (Tuesday KST → Monday US session, … Saturday KST → Friday), stepping back over US market holidays.

The repository fdo2a/fdo2a.github.io is cloned into your workspace as a source (locate with ls / find; if missing, clone https://github.com/fdo2a/fdo2a.github.io). Its .claude/agents/ directory contains the two subagent definitions used in STEP 1 and STEP 2.

## STEP 0 — 커밋된 데이터 파일 확인 (먼저)

A GitHub Actions workflow (.github/workflows/collect-market-data.yml) collects canonical yfinance/FRED data in a network-open runner and commits `data/market_data.json`, `data/intraday.json`, `data/econ_indicators.json`, `data/sector_performance.html`, `data/yield_curve.png` before this routine fires. **This is the primary data path** — the routine's own environment blocks finance hosts (Yahoo/FRED/exchanges all 403), so do NOT try to fetch them here.

0. **선점 잠금 — 가장 먼저, 다른 파일을 읽기 전에.** 이 루틴은 푸시 웹훅과 예약 크론으로 하루에 여러 번 뜬다. 2026-09-26 에는 새벽에 10번 떴고 넷이 동시에 작성하다 5시간 한도를 함께 태워 그날 글이 나가지 못했다. 아래 가드는 중복 **발행**만 막고 병렬 **작성**은 못 막는다. 레포 클론으로 들어가자마자:

   ```bash
   bash scripts/ci/run_lock.sh key us > /tmp/us-lock-key && cat /tmp/us-lock-key
   bash scripts/ci/run_lock.sh acquire "$(cat /tmp/us-lock-key)" 120
   ```

   키는 뉴욕 기준 세션 날짜라 KST 자정을 넘겨도 같은 세션은 같은 이름이다. **이후 모든 잠금 명령은 `/tmp/us-lock-key` 의 이름을 쓴다** — 다시 계산하지 않는다. **exit 3 이면 다른 런이 작성 중이다 — 아무것도 읽거나 쓰지 말고, PushNotification 도 보내지 말고 「locked by another run」만 보고하고 끝낸다.** exit 4(원격 확인 실패)도 진행하지 않고 그 사실을 보고한다. exit 0 이면 아래로 진행한다.

   **살아 있다는 표시**: STEP 2 작성 시작 전과 STEP 3 발행 커밋 직전에 `bash scripts/ci/run_lock.sh renew "$(cat /tmp/us-lock-key)"` 를 한다. **renew 가 exit 3 이면 잠금을 잃은 것이다 — 다른 런이 넘겨받았으니 커밋·푸시하지 말고 끝낸다.** 갱신 없이 120분이 지나면 다음 런이 넘겨받는다(한도로 죽은 런의 잠금).

   **쓰지 않고 끝나는 모든 경로에서는 끝내기 전에 잠금을 푼다** — 멱등 가드로 중단(already published), 수집 뒤에도 데이터가 기대 세션보다 이르거나 불완전해 중단하는 경우 전부: `bash scripts/ci/run_lock.sh release "$(cat /tmp/us-lock-key)"`. 해제는 자기가 잡은 잠금만 지운다. 작성·발행까지 간 런은 풀지 않는다. **사람이 띄운 복구 런**은 `acquire <키> 0` 으로 즉시 넘겨받는다.

0-1. **멱등 가드 — 이미 나간 글은 절대 다시 만들지 않는다.** `git -C <repo> pull` 후 `data/market_data.json` 의 `report_date` 를 읽는다. 그 값이 **오늘 기대하는 미국 세션과 같고** `posts/<report_date>.html` **과 `news/<report_date>.html` 이 둘 다** 커밋돼 있으면 즉시 중단한다: 파일을 고치지도, 커밋하지도, PushNotification 을 보내지도 말고 「already published」만 보고하고 끝낸다.

   **브리프만 있고 뉴스·산업 브리프가 없으면 이어 쓴다**(2026-09-27 — 9/25 런이 브리프 발행 1분 뒤 5시간 한도로 죽어, 재실행이 이 가드에서 멈췄다). STEP 1~3 을 건너뛰고 **STEP 3.5 만** 한다. 입력은 브리프 **발행 커밋**에서 복원한다 — 그 뒤 수집이 데이터를 덮어썼을 수 있다:

   ```bash
   C=$(git log -1 --diff-filter=A --format=%H -- posts/<report_date>.html)
   git show "$C:data/market_data.json" > <workspace>/market_data.json
   mkdir -p <workspace>/news && git show "$C:data/news/<report_date>.json" > <workspace>/news/<report_date>.json
   ```

   `research_notes.md` 는 없다(죽은 런의 워크스페이스와 함께 사라졌다) — 작성자에게 ③·④ 업계 뉴스 층을 비우라고 넘긴다. 뉴스 파일이 그 커밋에 없으면 없다고 넘긴다. 잠금은 위에서 잡은 그대로다.

   **「기대 세션과 같고」가 조건의 핵심이다.** 커밋된 데이터가 아직 어제 것이면(수집이 밀린 날 — 2026-08-27 이래 정상이다) 그 어제 글이 있는 건 당연하므로, 여기서 멈추면 오늘 글이 영영 안 나온다. 데이터가 낡았으면 가드를 통과시켜 아래 3번의 워크플로 재실행으로 내려보내고, **새 데이터를 받은 뒤 이 검사를 다시 한다**.

   이 루틴은 하루에 여러 번 뜰 수 있다 — 수집 커밋에 걸린 웹훅(레포의 **모든** push 에 반응하고, 현재 두 벌이 걸려 있다)과 예약 크론이 함께 있고, GitHub 예약 실행이 2~5시간씩 밀리므로 순서도 보장되지 않는다. 가드가 없으면 그 여분의 회차가 같은 날 글을 다시 쓴다.

   **발행 커밋 직전에 이 검사를 한 번 더 한다.** 웹훅이 여러 벌이라 두 회차가 거의 동시에 시작할 수 있고, STEP 0 의 검사만으로는 둘 다 통과해 둘 다 쓰게 된다. 커밋 직전에 `git pull` 하고 `posts/<report_date>.html` 이 그 사이 생겼으면 **아무것도 커밋하지 말고 중단한다**. push 가 거절되면(이 레포는 KR·thesis 수집이 함께 쓰므로 **우리와 무관한 커밋 때문에도 거절된다**) 강제로 밀지 말고 `git pull --rebase` 후 `posts/<report_date>.html` 이 원격에 생겼는지 확인한다 — 생겼으면 다른 회차가 발행한 것이니 중단하고, 아니면 그대로 다시 push 한다.

1. `git -C <repo> pull` (or re-clone) to get the latest committed data, then Read `data/market_data.json`.
2. If it exists, `report_date` matches today's expected US session (most recent US weekday; if it looks stale by >1 trading day, note it), and `"complete": true` — **copy the five data files to the workspace root** (`market_data.json`, `intraday.json`, `econ_indicators.json`, `sector_performance.html`, `yield_curve.png`) and skip STEP 1's market-data collection entirely. Proceed to STEP 1 for research_notes.md only (the web-research half).
   Also copy the two inherited books if present — they are **non-core**: their absence never blocks publication, and never fails the completeness gate.
   - §9 매크로: `data/macro.json` (yesterday's regime / policy path / transmission), `data/macro_eval.json` (today's verdict — what may move), `data/macro_metrics.json` (axis scores and the new-release list), and **`data/releases/`** — the primary press releases behind today's promoted indicators, already fetched and committed (`index.json` says which succeeded). Copy the whole `releases/` directory. Missing → the writer opens the book in bootstrap mode.
   - 연준 이벤트: **`data/fed/`** 디렉터리 전체 — `events.json`(오늘 다룰 이벤트와 각 원문의 수집 결과)과 `<key>.txt`(성명·기자회견 전문·연설 원문). **대부분의 날에는 `fresh` 이벤트가 없고, 그런 날은 이 섹션을 아예 열지 않는다.** Missing → the writer omits the section entirely. 원문 텍스트 파일이 인용 대조의 정본이므로 디렉터리째 복사한다.
   - 움직인 종목: `data/movers.json` 이 있으면 `<workspace>/movers.json` 으로 복사한다(S&P 500 달러 거래대금 상위 60 에서 고른 최대 5묶음 — collector 가 묶음마다 원인을 찾고 writer 가 §12 에 쓴다). 없으면 게이트가 강제하지 않는다.
   - 뉴스: `data/news/[DATE].json`이 있으면 `<workspace>/news/[DATE].json`으로 복사한다. DATE는 `report_date`다. **뉴스·산업 브리프(STEP 3.5)의 입력이다** — 시황 브리프 작성자에게는 넘기지 않는다. 기사마다 `summary_ko`(수집 잡이 만든 한국어 요약)가 들어 있다. 없으면 다른 날짜 파일로 대체하지 않는다.
3. If `data/market_data.json` is missing, stale, or `"complete": false`, **first re-run the collection workflow**. 이게 1순위다: 2026-08-27 이래 GitHub 예약 실행이 2~5시간씩 밀려 **수집이 이 루틴보다 늦게 도착하는 날이 정상이 됐다**(실측: 예약분이 4~5시간 밀린 날이 여러 번). 수동 dispatch 는 밀리지 않고 즉시 뜬다.

   ```
   gh workflow run collect-market-data.yml -f force=true
   sleep 15
   RUN=$(gh run list --workflow=collect-market-data.yml --event=workflow_dispatch \
           --limit 1 --json databaseId --jq '.[0].databaseId')
   timeout 900 gh run watch "$RUN" --exit-status
   git pull
   ```

   **`gh` 가 없으면**(클라우드 샌드박스, 실측 exit 127) `mcp__github__actions_run_trigger`(`method: run_workflow`)로 걸고 `mcp__github__actions_list`(`method: list_workflow_runs`)로 run id 를 받은 뒤 **`bash scripts/ci/wait_run.sh "$RUN"` 한 번으로** 기다린다(Bash 도구 timeout 을 600000 으로 올린다 — 도구가 먼저 끊으면 같은 명령을 다시 부른다). exit 0 만 성공이다. **Monitor·ScheduleWakeup·짧은 폴링 반복으로 기다리지 않는다** — 깨어날 때마다 전체 컨텍스트가 다시 실린다(2026-09-21 China 실행이 「아직 진행 중」을 확인하느라 수십 턴을 썼다).

   실행 ID 를 집고 `--exit-status` 를 붙인다 — 맨 `gh run watch` 는 엉뚱한 예약 실행을 기다리고, `--exit-status` 가 없으면 실패한 수집도 성공으로 읽혀 낡은 데이터가 그대로 발행된다. If that path is unavailable or still leaves gaps, note exactly which fields `missing` lists and run the full STEP 1 collector to fill the whole set (or just the gaps). The Actions run may have partially failed; treat its output as a starting point, not gospel.

   **폴백이 끝나면 `report_date`와 `complete`를 다시 본다** — 날짜가 여전히 기대 세션보다 이르면 발행하지 않고 중단한다. 뒤의 completeness 게이트는 필드 존재만 보고 날짜는 보지 않으므로, 여기서 막지 않으면 전 세션 자료가 오늘 날짜로 나간다.

**토큰 규율**: 이 데이터 파일들이 있으면 그 안의 수치를 웹서치로 재확인하지 않는다. 웹 리서치(STEP 1의 리서치 절반)는 뉴스·해석·컨센서스처럼 파일에 없는 것에만 쓴다. 경제지표 Actual/Previous는 econ_indicators.json이 이미 확정했다.

## STEP 1 — 데이터 수집·검증 (subagent: brief-data-collector)

**운용자 대상 시황·리서치:** STEP 1 시작 전에 `.claude/DESK_REPORT.md`를 읽고 그 문서의 Handoff를 수행한다. 기존 시황·수급·뉴스 자료를 유지하면서 `research_notes.md`에 `운용 판단 브리핑`을 추가한다. 작성자에게 이 절과 해당 문서 경로를 반드시 넘긴다. STEP 2 초안 뒤에 그 문서의 Editorial acceptance를 수행한다. 실제 보유·운용제약이 주어지지 않았으면 자산별 조건부 판단으로 쓰며, 새 거래 아이디어가 없는 날도 정상 발행한다.

**리서치 인계:** `.claude/TRADER_LEARNING.md`를 반드시 읽고 Research handoff를 수행한다. 수집·작성 담당에게 해당 문서 경로, 직전 발행본 경로(없으면 bootstrap), `research_notes.md`의 `학습·복기` 절을 전달한다. STEP 2 초안 뒤에 그 문서의 Editorial check를 수행하고, 위반 문단을 수정한 뒤 기존 발행 게이트를 통과시킨다.

**앞으로 작성하는 보고서:** `.claude/RESEARCH_WORKFLOW.md`를 읽고 증거 → 가설·복기 기록 → 당일 cycle 순서로 진행한다. 원장은 `research/us`, 원장·증거 파일을 새 발행본과 함께 커밋한다. 기존 발행본은 이 변경의 대상이 아니다. 작성자에게 cycle ID와 모든 미해결 가설을 전달하고, 초안이 아래 검사를 통과해야 한다. 새 자료가 추가되면 cycle도 다시 기록한다.

```bash
python3 scripts/check_research.py check --span daily --html <새 초안> --root research/us --market us --date <DATE> --cycle <CYCLE_ID>
```

발행 뒤 codex 문체 수정도 글에 박힌 cycle 로 이 검사를 다시 돌린다(`scripts/review/style_pass.py`).

If STEP 0 already produced a complete market_data.json/intraday.json/yield_curve.png, you still need **research_notes.md** — launch the collector subagent (or fallback) for the web-research portion only (STEP 2 of the agent file: 시황 동인·채권 맥락·메모리·AI 인프라·경제지표 4축). Otherwise run it in full.

Launch the Agent tool with subagent_type "brief-data-collector", run synchronously (run_in_background: false). Prompt: the report trading date [YYYY-MM-DD], whether market data is already present (and its path), and the instruction to produce any missing artifacts in the workspace root: market_data.json, intraday.json, yield_curve.png (may be skipped if week-ago yields are missing), research_notes.md.

**위임한 것은 다시 읽지 않는다.** 서브에이전트는 **동기**(`run_in_background: false`)로 부르고, 기다리는 동안 아무것도 열지 않는다. 에이전트 정의 파일(`.claude/agents/*.md`), 그 에이전트가 읽을 데이터 파일, 직전 발행본은 오케스트레이터가 읽지 않는다 — **경로만 넘기고**, 돌아온 산출물과 게이트 출력만 본다. 폴백으로 general-purpose 에이전트를 쓸 때도 정의 파일 본문을 붙여 넣지 말고 「이 파일을 먼저 Read 하라」고 경로를 준다. (2026-09-22 KR 실행이 에이전트를 백그라운드로 띄워 두고 지시문 35 KB·데이터 12개·직전 발행본을 다시 읽다가 5시간 한도로 죽었다.)

Fallbacks: if the subagent type is not available, launch a general-purpose agent whose prompt tells it to Read .claude/agents/brief-data-collector.md first and follow it (do not paste the file body), plus the report date. If the Agent tool itself is unavailable, execute that file's instructions yourself, in full, before continuing.

Gate before proceeding: market_data.json parses as JSON with non-null indices/sectors/yields; intraday.json parses; research_notes.md exists and contains the 4-axis macro indicator table. If `data/macro_metrics.json` lists `headline_releases`, research_notes.md must also carry section ⑧ (신규 발표 해부) with an entry per release — or an explicit note that the primary release could not be reached. If the gate fails, relaunch the subagent once with the specific error details; if it fails again, fix the gaps yourself using the agent file's instructions.

**Completeness gate (사용자 지시 2026-07-14 — 완성본만 발행)**: the canonical dataset must be COMPLETE before STEP 2 — indices 6종(3대 지수+러셀+Growth/Value), sectors 11종 전부(XLRE 포함) + sector_performance 5기간, yields 2Y/5Y/10Y/30Y + curve chart, FX 4종, commodities 4종, memory 6종, AI infra 5종. "미확인이라 표에서 제외" 처리는 발행 사유가 아니라 발행 중단 사유다. Yields are Naver Treasury closes (17:05 ET SIFMA cash close) for all four tenors, which puts them on **one as-of date** (2026-09-04). Yahoo spot (^FVX/^TNX/^TYX) → FRED is the fallback chain when Naver is unavailable, and only then do tenors carry different as-of dates — that fallback is degraded but publishable, not a gate failure. The gate requires a non-null level + week_ago per tenor, and additionally fails closed on `yields/naver_close_not_posted`: a run that fired **before** the 17:05 ET Treasury close must not be committed as complete, or the later run gets skipped by the idempotency guard and the day's curve stays stuck on the prior session. If primary sources (yfinance/FRED) are blocked, retry via alternative canonical routes (FRED DGS5/DGS10/DGS30 as the yield fallback, FRED CSV via curl, exchange sites) until complete. If the dataset still cannot be completed, DO NOT publish a partial report to any channel — send a PushNotification listing exactly which fields are missing and why, and stop.

## STEP 2 — 리포트 작성 (subagent: brief-report-writer)

**시황 브리프에는 오늘의 뉴스·메모리/DRAM·AI 인프라·MLCC 가 없다**(2026-09-26 사용자 지시) — 네 섹션은 STEP 3.5 의 둘째 글 「뉴스·산업 브리프」로 옮겨 갔다. 작성자에게 그 섹션을 쓰라고 하지 않는다.

Launch the Agent tool with subagent_type "brief-report-writer", run synchronously. Prompt: the report trading date, the list of input files from STEP 1 (**including macro.json / macro_eval.json / macro_metrics.json if present**), and the required outputs in the workspace root — morning_brief_[YYYY-MM-DD].html (the writer authors only `.body.html` + `.meta.json` and assembles them with `scripts/render_post.py`; head, CSS, top bar and nav come from the shell) **plus macro_next.json** (the updated macro book; the input macro.json must be left untouched). Same fallbacks as STEP 1 (agent file: .claude/agents/brief-report-writer.md).

**발행 게이트** — 아래를 레포 클론에서 돌린다. 하나라도 실패하면 **출력에 찍힌 위반을 그대로** writer 에게 넘겨 다시 돌린다(게이트가 무엇을 막는지는 출력이 말한다 — 게이트 소스를 읽지 않는다). 표식을 지우거나 게이트를 우회하지 않는다.

(a) `grep -c '확인필요' <html>` = 0. (b) 수치 5개 이상을 `grep -o '4\.62' <html>` 식으로 `market_data.json`·`intraday.json`·`econ_indicators.json` 원본과 대조 — HTML 전체(~34K 토큰)를 읽지 않는다. 수치 창작 금지, 미확인은 삭제·재구성.

```bash
python  scripts/check_macro.py         --html morning_brief_[DATE].html --datadir <workspace>
python  scripts/check_price_context.py --html morning_brief_[DATE].html --datadir <workspace>
python3 scripts/check_session.py       --html morning_brief_[DATE].html --datadir <workspace> --market us
python3 scripts/check_fed.py           --html morning_brief_[DATE].html --datadir <workspace>
python3 scripts/check_calendar.py      --html morning_brief_[DATE].html --datadir <workspace>
python3 scripts/check_sources.py       --html morning_brief_[DATE].html --datadir <workspace>
python3 scripts/check_weight.py        --html morning_brief_[DATE].html --datadir <workspace> --market us
python3 scripts/check_movers.py        --html morning_brief_[DATE].html --datadir <workspace>
```

- `check_fed.py` — **침묵이 기본값이다.** 신선한 tier-1 연준 이벤트가 없는 날 섹션을 열면 막힌다.
- 비-코어 입력(`price_context`·`session`·`calendar.json`·뉴스 수집분)이 없는 날도 표식 대조는 그대로 돈다 — 수집이 실패한 날이 창작이 실릴 확률이 가장 높다.

**가독성·문체 = 초안 수리 루프 (실패로 루틴을 끝내지 않는다)**

1. `python3 scripts/apply_readability.py <html>` → `python3 scripts/apply_colors.py <html>`(방향색; `--check` 는 미적용이면 exit 1) → `python3 scripts/check_readability.py --strict --no-inline-images <html>` 과 `python3 scripts/check_style.py <html>` 의 전체 출력을 저장한다. 문체 검사는 항상 돈다.
2. 실패하면 writer 를 **전체 보고서를 유지한 채 위반 문단만 수정하라**는 지시와 검사 원문으로 다시 돌리고, 데이터 정본·표를 재대조한 뒤 apply → check 를 반복한다.
3. 같은 위반이 두 번 연속 남으면 오케스트레이터가 그 문단을 직접 고친다(긴 문장 분리 → 중복 수치 삭제 → 산문 반올림). **통과할 때까지 계속한다.**

가독성 실패는 초안 반려일 뿐 미발행 사유가 아니다 — 중단 알림을 보내지 않는다. 중단은 데이터 정본이 끝내 완성되지 않을 때(completeness gate)뿐이다.

각 게이트가 막는 조건의 상세와 이력: `docs/superpowers/specs/2026-09-24-instruction-history-archive.md` 「STEP 2」.

## STEP 2.5 — 윤문은 루틴에서 하지 않는다 (2026-09-27)

**루틴은 STEP 2 게이트를 통과하면 바로 STEP 3 으로 간다.** `humanize-korean` 윤문을 부르지 않는다 — Claude 주간 한도를 아끼려고 사용자가 뺐다.

말투 손질은 **발행 뒤** 로컬 러너(`scripts/review_gate.py run --correct`, 매시)가 codex 로 한다. codex 는 발행 커밋 스냅샷에서 `prose_in.txt`(이 단계가 쓰던 `humanize_prose.py extract` 산출물)만 고치고, Python 이 `prose_swap.reinsert`(문단마다 숫자·영문 이름·판단 어휘·링크·닮은 정도)와 이 단계가 쓰던 게이트 목록 전체를 발행 커밋의 데이터로 다시 돌린 뒤에만 공개판을 교체한다. 거부되면 원본이 그대로 공개돼 있을 뿐이다. 모듈 `scripts/review/style_pass.py`, 설계 `docs/superpowers/specs/2026-09-27-post-publish-codex-style-pass.md`.

**그래서 초고가 곧 발행본이다.** writer 지시문의 「말하듯이 쓴다」와 STEP 2 의 `check_style` 이 첫 판의 문체를 책임진다.

## STEP 3 — Publish to the blog (GitHub Pages 루트 사이트)

Site base URL: https://fdo2a.github.io/

1. Copy the report HTML into the repo as posts/[YYYY-MM-DD].html. **Inject nothing** — the navigation block and the SEO meta (description, canonical, og:*) are already in it, rendered once by `scripts/render_post.py`. Injecting them again is how the 2026-09-23 post ended up with every head tag twice. If `grep -c 'post-shell-v1'` on the file is 0, the writer skipped the shell: send it back to render rather than patching the head by hand.
2. Copy yield_curve.png into the repo as assets/yield_curve_[YYYY-MM-DD].png (**the post references this file** via `../assets/yield_curve_[DATE].png` — it is not embedded, so this copy is required for the chart to render), then promote the writer's macro book:
   - `macro_next.json` → `data/macro.json`
   Tomorrow's Actions run judges today's regime and triggers against this file. Publishing without promoting it leaves the macro book frozen — and because macro.json also carries `last_seen`, a missed promotion makes every indicator read as newly released tomorrow, which would hand the writer a free regime change.
3. **에디터 노트 (있는 날만)** — if `notes/[YYYY-MM-DD].md` exists in the repo clone, run `python3 scripts/apply_note.py posts/[YYYY-MM-DD].html` from the repo root. That file is the publisher's own view, written by hand before the run; the script drops it in verbatim after §2 전략 코멘트. **Never write, edit, polish, or fact-check that text, and never author the section yourself** — a note the publisher did not write is worse than no note. The script is a no-op (exit 1, page untouched) when the file is missing, empty, or still the unedited template, so it is safe to run unconditionally. Most days there is no note and no section.
4. Update posts.json and merge sitemap.xml in one command — **merge, never regenerate** (regenerating from posts.json wiped the weekly·KR·thesis·news URLs every morning):
   `python3 scripts/update_archives.py --root . --kind daily --key [YYYY-MM-DD] --title "[TITLE]" --headline "[HEADLINE]"` — same-date entry is replaced, never duplicated.
5. Commit and push to main — **뉴스·산업 브리프를 쓰기 전에** 이 커밋부터 올린다:
   git add -A && git commit -m "Add [YYYY-MM-DD] brief" && git push
   If the push fails, continue with remaining steps and report the failure clearly in your final message and PushNotification.

## STEP 3.5 — 뉴스·산업 브리프 (subagent: news-industry-writer) — 브리프를 발행한 **뒤에**

2026-09-26 사용자 지시 「오늘의 뉴스, 메모리/DRAM, AI 인프라, MLCC…를 시황 레포트에서 제외시킨 뒤, 새로운 글을 하나 더 만드는 방향으로」. **같은 날, 같은 입력으로 쓰는 둘째 글이다** — 새로 수집하거나 웹서치하지 않는다.

**시황 브리프가 먼저다 — 순서로 지킨다.** 이 단계는 STEP 3 에서 브리프를 **커밋·푸시한 다음에** 시작한다. 2026-09-26 에는 9/25 브리프가 게이트를 다 통과하고도, 발행이 이 단계 뒤에 있었던 탓에 뉴스 글을 고치다 5시간 한도에 걸려 함께 사라졌다. 이 글이 게이트를 끝내 못 넘으면 이 글만 빼고 최종 보고·알림에 사유를 적는다.

0. **멱등 가드** — `news/[DATE].html` 이 이미 커밋돼 있으면 이 단계를 건너뛴다.
1. Agent 도구로 subagent_type `news-industry-writer` 를 동기 실행한다(없으면 `.claude/agents/news-industry-writer.md` 를 읽고 직접). 프롬프트: 기준일, 워크스페이스 경로, 입력 네 가지 — `market_data.json`(`memory`·`ai_infra`·`mlcc`·`price_context`), `news/[DATE].json`(없으면 없다고), `research_notes.md` ③·④ 절. 산출물: `news_industry_[DATE].html`(`.body.html`+`.meta.json` 을 `render_post.py --market news` 로 합친 것).
2. **게이트** — 작성자가 돌린 것을 레포 클론에서 다시 돌린다. 실패하면 출력을 그대로 넘겨 위반 문단만 고치게 한다(두 번 연속 같은 위반이면 오케스트레이터가 직접).
   ```bash
   python3 scripts/apply_readability.py news_industry_[DATE].html
   python3 scripts/apply_colors.py news_industry_[DATE].html
   python3 scripts/check_news.py --html news_industry_[DATE].html --datadir <workspace> --date [DATE]
   python3 scripts/check_readability.py --strict --no-inline-images news_industry_[DATE].html
   python3 scripts/check_style.py news_industry_[DATE].html
   grep -c '확인필요' news_industry_[DATE].html     # 0
   ```
   `check_news.py` 에는 **`--date [DATE]` 를 반드시 준다** — 없으면 최신 파일을 집어 어제 수집분이 오늘의 근거가 된다. `summary_ko` 가 있는 갈래 기사가 하나라도 있으면 「오늘의 뉴스」는 의무다. 하나도 없으면 섹션 없이 발행하되 **최종 보고에 사유(`summary_note`)를 적는다.** **루틴에서 기사 본문을 다시 받지 않는다**(클라우드는 CNBC·Yahoo 에 403).
3. **윤문은 이 글에 하지 않는다** — 뉴스 블록은 `summary_ko` 에 묶여 있어(유사도 게이트) 윤문이 걸리고, 산업 세 섹션은 짧다. 발행 뒤 codex 문체 수정도 `posts/` 일간만 본다. 문체 검사(`check_style`)는 위에서 돈다.
4. **발행 (이 글만의 커밋)** — `news_industry_[DATE].html` 을 `news/[YYYY-MM-DD].html` 로 복사하고(주입 없음, `post-shell-v1` 확인은 STEP 3-1 과 같다) `python3 scripts/update_archives.py --root . --kind news --key [YYYY-MM-DD] --title "[meta.json 의 title 에서 「 | DATE」 를 뗀 것]" --headline "[그 글의 h1]"`. 그리고 `git add news/ news.json sitemap.xml && git commit -m "Add [YYYY-MM-DD] news-industry brief" && git push` — 거절되면 `git pull --rebase` 후 다시 push 한다.

## STEP 4 — Notify

Send a PushNotification with the headline and the blog post URL, plus the 뉴스·산업 브리프 URL (`https://fdo2a.github.io/news/[DATE].html`) or why it was not published (mention any failures).

**발행 채널은 블로그 하나뿐이다 (2026-08-18 사용자 지시로 Notion 발행 중지).** Do NOT publish to Notion, do NOT generate a PDF, do NOT use SendUserFile, and do NOT send email. If a Notion connector is available in the session, leave it alone — its presence is not an instruction to use it.

## STEP 5 — 발행 후 자동 검토·정정

최초 push 성공 뒤 로컬 러너가 Codex 검토와 Claude 정정·재게시를 이어받는다.
절차는 `.claude/REVIEW_GATE.md`의 「US·KR 무인 정정」을 따른다.
클라우드 루틴은 Codex 검토를 완료했다고 보고하지 말고 최초 발행과 사후 검토 대기를 구분한다.
이미 발행된 글의 재작성 금지 가드는 그대로 유지한다. 정정은 로컬 러너가 맡는다.

## RULES
- All prices/% changes in the published report MUST come from market_data.json / intraday.json; macro indicator values from research_notes.md. 수치 창작 절대 금지.
- **완성본만 발행 (2026-07-14 사용자 지시)**: 핵심 표(지수·섹터·채권·FX·원자재; 뉴스·산업 브리프는 메모리·AI 인프라)에 누락 항목이 있는 채로 발행 금지 — 메모리·AI 인프라가 비면 뉴스·산업 브리프만 싣지 않고 시황 브리프는 발행한다. 완성 불가 시 발행하지 말고 PushNotification으로 누락 내역을 보고할 것. 웹 리서치로 대체 수집한 시세는 발행 전 반드시 복수 출처 교차 확인 — 단일 검색 결과 수치는 신뢰하지 않는다 (7/13호에서 FX 방향·유가 등락률 오류 발생 전례).
- **발행본에 [확인필요] 금지 (STEP 2 게이트).** 미확인 항목은 끝까지 확인하거나 삭제·재구성.
- Web findings attributed to sources. Clear, natural report prose (근거와 판단이 분명한 자연스러운 보고서 문체).
- **「buy-side」 금지 (2026-08-22 사용자 지시)** — 발행본 어디에도 쓰지 않는다. §2 헤더는 「전략 코멘트」, 해석 박스는 「전략 해석」. `scripts/check_macro.py` 게이트가 차단한다.
- Final message: blog (GitHub Pages) delivery status, which subagents ran (or which fallback was used), and any failures.
