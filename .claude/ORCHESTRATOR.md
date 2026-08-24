# US Morning Brief — Orchestrator Runbook

You are the orchestrator for the daily US morning market brief. Follow this runbook start to finish.

**Report trading date**: the most recent completed US trading day. **Authoritative source is the committed data file** (STEP 0 below) — trust `report_date` in `data/market_data.json`, which is the S&P 500's actual last-close date. Do NOT compute it from the KST run day; the old weekday-arithmetic rule caused a duplicate-report bug (2026-07-15). Only if no data file exists, fall back to arithmetic: previous US weekday relative to the KST run day (Tuesday KST → Monday US session, … Saturday KST → Friday), stepping back over US market holidays.

The repository fdo2a/fdo2a.github.io is cloned into your workspace as a source (locate with ls / find; if missing, clone https://github.com/fdo2a/fdo2a.github.io). Its .claude/agents/ directory contains the two subagent definitions used in STEP 1 and STEP 2.

## STEP 0 — 커밋된 데이터 파일 확인 (먼저)

A GitHub Actions workflow (.github/workflows/collect-market-data.yml) collects canonical yfinance/FRED data in a network-open runner and commits `data/market_data.json`, `data/intraday.json`, `data/econ_indicators.json`, `data/sector_performance.html`, `data/yield_curve.png` before this routine fires. **This is the primary data path** — the routine's own environment blocks finance hosts (Yahoo/FRED/exchanges all 403), so do NOT try to fetch them here.

1. `git -C <repo> pull` (or re-clone) to get the latest committed data, then Read `data/market_data.json`.
2. If it exists, `report_date` matches today's expected US session (most recent US weekday; if it looks stale by >1 trading day, note it), and `"complete": true` — **copy the five data files to the workspace root** (`market_data.json`, `intraday.json`, `econ_indicators.json`, `sector_performance.html`, `yield_curve.png`) and skip STEP 1's market-data collection entirely. Proceed to STEP 1 for research_notes.md only (the web-research half).
   Also copy the two inherited books if present — they are **non-core**: their absence never blocks publication, and never fails the completeness gate.
   - §8 매크로 논리: `data/macro.json` (yesterday's regime / policy path / transmission), `data/macro_eval.json` (today's verdict — what may move), `data/macro_metrics.json` (axis scores and the new-release list), and **`data/releases/`** — the primary press releases behind today's promoted indicators, already fetched and committed (`index.json` says which succeeded). Copy the whole `releases/` directory. Missing → the writer opens the book in bootstrap mode.
   - §9 멀티에셋 스탠스: `data/stance.json`, `data/stance_eval.json`, `data/stance_metrics.json`. Missing → the writer freezes every grade, or bootstraps.
3. If `data/market_data.json` is missing, stale, or `"complete": false`, note exactly which fields `missing` lists and run the full STEP 1 collector to fill the whole set (or just the gaps). The Actions run may have partially failed; treat its output as a starting point, not gospel.

**토큰 규율**: 이 데이터 파일들이 있으면 그 안의 수치를 웹서치로 재확인하지 않는다. 웹 리서치(STEP 1의 리서치 절반)는 뉴스·해석·컨센서스처럼 파일에 없는 것에만 쓴다. 경제지표 Actual/Previous는 econ_indicators.json이 이미 확정했다.

## STEP 1 — 데이터 수집·검증 (subagent: brief-data-collector)

If STEP 0 already produced a complete market_data.json/intraday.json/yield_curve.png, you still need **research_notes.md** — launch the collector subagent (or fallback) for the web-research portion only (STEP 2 of the agent file: 시황 동인·채권 맥락·메모리·AI 인프라·경제지표 4축). Otherwise run it in full.

Launch the Agent tool with subagent_type "brief-data-collector", run synchronously (run_in_background: false). Prompt: the report trading date [YYYY-MM-DD], whether market data is already present (and its path), and the instruction to produce any missing artifacts in the workspace root: market_data.json, intraday.json, yield_curve.png (may be skipped if week-ago yields are missing), research_notes.md.

Fallbacks: if the subagent type is not available, Read .claude/agents/brief-data-collector.md in the repo and launch a general-purpose agent with that file's body (below the frontmatter) plus the report date as the prompt. If the Agent tool itself is unavailable, execute that file's instructions yourself, in full, before continuing.

Gate before proceeding: market_data.json parses as JSON with non-null indices/sectors/yields; intraday.json parses; research_notes.md exists and contains the 4-axis macro indicator table. If `data/macro_metrics.json` lists `headline_releases`, research_notes.md must also carry section ⑧ (신규 발표 해부) with an entry per release — or an explicit note that the primary release could not be reached. If the gate fails, relaunch the subagent once with the specific error details; if it fails again, fix the gaps yourself using the agent file's instructions.

**Completeness gate (사용자 지시 2026-07-14 — 완성본만 발행)**: the canonical dataset must be COMPLETE before STEP 2 — indices 6종(3대 지수+러셀+Growth/Value), sectors 11종 전부(XLRE 포함) + sector_performance 5기간, yields 2Y/5Y/10Y/30Y + curve chart, FX 4종, commodities 4종, memory 6종, AI infra 5종. "미확인이라 표에서 제외" 처리는 발행 사유가 아니라 발행 중단 사유다. Yields are Yahoo spot (^FVX/^TNX/^TYX) for 5Y/10Y/30Y and FRED DGS2 for 2Y (2026-07-28 사용자 지시) — **tenors carrying different as-of dates is expected, not a gate failure**; the gate only requires a non-null level + week_ago per tenor. If primary sources (yfinance/FRED) are blocked, retry via alternative canonical routes (FRED DGS5/DGS10/DGS30 as the yield fallback, FRED CSV via curl, exchange sites) until complete. If the dataset still cannot be completed, DO NOT publish a partial report to any channel — send a PushNotification listing exactly which fields are missing and why, and stop.

## STEP 2 — 리포트 작성 (subagent: brief-report-writer)

Launch the Agent tool with subagent_type "brief-report-writer", run synchronously. Prompt: the report trading date, the list of input files from STEP 1 (**including macro.json / macro_eval.json / macro_metrics.json and stance.json / stance_eval.json / stance_metrics.json if present**), and the required outputs in the workspace root — morning_brief_[YYYY-MM-DD].html **plus macro_next.json and stance_next.json** (the updated books; the input macro.json / stance.json must be left untouched). Same fallbacks as STEP 1 (agent file: .claude/agents/brief-report-writer.md).

Gate before proceeding (발행 게이트): (a) `grep -c '확인필요' <html>` — must be 0; (b) spot-check 5+ numbers by grepping the HTML for specific values from market_data.json / intraday.json / econ_indicators.json (e.g. `grep -o '4\.62' <html>`), NOT by reading the whole ~34K-token HTML into context. If either check fails, relaunch the writer subagent with the specific violations; repeat until clean. 수치 창작 절대 금지 — 미확인 항목은 삭제·재구성이 원칙.

**매크로 게이트 (§8)** — run `python scripts/check_macro.py --html morning_brief_[DATE].html --datadir <workspace>` from the repo clone. It fails the run when: the regime label is outside the 3×3 controlled vocabulary; the regime sits outside `allowed_regimes` (the writer moved it on a day with no new release, inside the 5-business-day lock, or against what the axis scores imply); the axis scores or the FedWatch probability are not quoted in the section; a newly released indicator listed in `headline_releases` has no `data-release` anatomy block, or that block stops at the headline number (no primary source named, fewer than three figures); a transmission direction is outside its `allowed_directions`; the policy path was re-timed without either a new release or a 15%p probability move; a transmission direction conflicts with the §9 stance grade and no `data-reconcile` paragraph explains it; or macro_next.json is missing / not dated today / disagrees with the §8 markers. Relaunch the writer with the exact violations.

**스탠스 게이트 (§9)** — run `python scripts/check_stance.py --html morning_brief_[DATE].html --datadir <workspace>` from the repo clone. It fails the run when: a §9 grade label is outside the controlled vocabulary; a grade sits outside that asset's `allowed_grades` from stance_eval.json; a moved row lacks the MET trigger's actual value (or, for an event trigger, a research_notes.md attribution) in the surrounding text; a row is missing its 유지 일수 or 다음 분기점; or the writer's new stance.json is not dated today / omits a history entry for a moved row. Relaunch the writer with the exact violations. This gate is what keeps §9 a position rather than a restatement of the day's tape — do not waive it. Neither gate is waivable: between them they are the only thing standing between «승계되는 판단» and a daily rewrite wearing the same headings.

**가독성 게이트 = 초안 수리 루프 (실패로 루틴 종료 금지)**

1. `python3 scripts/apply_readability.py <morning_brief 절대경로>`로 v3 조판·빠른 이동·긴 문단 분리를 적용하고, `python3 scripts/check_readability.py --strict <morning_brief 절대경로>`와 **`python3 scripts/check_style.py <morning_brief 절대경로>`**의 전체 출력을 저장한다. 문체 검사는 「말하듯이 쓴다」 기준에서 셀 수 있는 부분(비인칭 피동·번역투 연결·서술어 없는 명사형 머리말·「~한 상태다」 종결·같은 문단 머리말 반복·「~다」 연속)을 본다. **STEP 2.5의 윤문과 별개로 여기서 항상 돈다** — 윤문은 건너뛸 수 있어도 문체 기준은 건너뛰지 않는다.
2. 실패하면 출력에 찍힌 위반을 원인별로 고친다. 문체 위반은 「말하듯이 쓴다」 절의 해당 항목대로 문장을 다시 쓴다: 헤드라인은 방향·촉매·행동만 남기고, 120자 초과는 시간·주제가 바뀌는 곳에서 문장을 나누며, 수치 5개 이상은 정확한 값은 표에 두고 산문에는 관계만 남긴다. 과잉 정밀도는 산문만 반올림하고 정확한 값은 표에서 보존한다. 반복 수치는 첫 설명과 정본 표 한 곳만 남긴다.
3. writer를 **전체 보고서를 유지한 채 위반 문단만 수정하라**는 지시와 검사 원문으로 다시 실행한다. 수정 뒤 데이터 정본과 표를 재대조하고 apply → strict check를 반복한다.
4. writer 재실행이 두 번 연속 같은 위반을 남기면 오케스트레이터가 해당 문단을 직접 국소 수정한다. 긴 문장 분리 → 중복 수치 삭제 → 산문 반올림 순서로 고치고 다시 검사한다. **통과할 때까지 이 수리 루프를 계속한다.**

가독성 실패는 현재 초안을 반려할 뿐, “오늘 레포트 미발행” 사유가 아니다. 가독성 때문에 중단 알림을 보내지 않는다. 데이터 정본이 끝내 완성되지 않는 경우만 기존 completeness gate에 따라 중단할 수 있다.

## STEP 2.5 — AI 티 제거 (발행 전 마지막 손질)

2026-08-25 사용자 지시. 리포트를 **말하듯이** 쓰라는 문체 기준(`.claude/agents/brief-report-writer.md`의 「말하듯이 쓴다」 절)을 writer가 지켰더라도, 매일 같은 틀로 생성된 글에는 사람이 안 쓰는 리듬이 남는다. 발행 직전에 한 번 걸러낸다.

**1. 원본을 남긴다.**

```bash
cp morning_brief_[DATE].html morning_brief_[DATE].pre-humanize.html
```

이 파일이 없으면 3번을 못 하므로 건너뛰지 않는다.

**2. 말투를 고친다.**

**클라우드 루틴에는 플러그인이 붙어 있지 않다** (2026-08-25 확인 — 트리거의 `enabled_plugins`가 비어 있고, API로 채워지지 않았다). 그러니 `humanize-korean` 스킬은 **없다고 보고 시작한다.** Skill 도구 목록에 그 이름이 실제로 보이면 쓰고(본문 `<p>` 산문만 대상, 표·숫자·티커·제목·`data-*` 표식·에디터 노트는 손대지 말라고 프롬프트에 명시), 없으면 아래를 직접 한다. **어느 쪽이든 건너뛰지 않는다.**

`python3 scripts/check_style.py <html>`의 출력이 작업 목록이다. 검사가 짚은 항목부터 고치고, 검사가 못 보는 아래 셋도 함께 훑는다.

- **주어를 되살린다.** 앞 문장에서 이어받아 생략한 주어를 다시 넣는다. 「이후 반등해…」 → 「코스피는 이후 반등해…」.
- **한 문장에 한 관계만 남긴다.** 「A했다가 B했고 이후 C해서 D로 마감했다」는 문장이 아니라 표다. 시각이 셋 이상이면 나눈다.
- **판단을 능동으로 쓴다.** 「~로 읽힌다/판정된다」를 「~라고 볼 수 있습니다」나 「A가 B를 끌어내렸습니다」로 바꾼다.

고칠 때 **문장만 만지고 숫자·표식·표는 건드리지 않는다.** 3번이 그것을 강제한다.

**3. 수치와 구조가 그대로인지 대조한다. 이게 이 단계의 안전장치다.**

```bash
python3 scripts/verify_post.py morning_brief_[DATE].html \
  --before morning_brief_[DATE].pre-humanize.html --skip-layout
```

숫자·티커 멀티셋, 태그 구조, 그리고 게이트가 읽는 `data-*` 표식을 함께 본다. 윤문은 말투를 바꾸는 일이지 수치를 만지는 일이 아니다. 과거 손편집에서 FX 방향과 유가 등락률이 뒤집힌 전례가 있다.

**한 건이라도 나오면 파일 전체를 원본으로 되돌린다.** 검사는 어느 문단에서 틀어졌는지
알려주지 않으므로 「그 문단만 되돌리기」는 할 수 없다. 되돌린 뒤 한 번만 다시 시도하고,
또 걸리면 윤문을 포기한다.

**4. 게이트를 다시 돌린다. 이게 이 단계에서 제일 중요하다.**

STEP 2의 게이트들은 **윤문 전 원고를 보고 통과시킨 것이다.** 문장을 다시 쓴 뒤에도 그
판정이 유효하다고 가정하면 안 된다. 윤문은 문장을 합치거나 나누므로 문장 길이·수치
밀도가 깨질 수 있고, 통제 어휘나 `data-*` 표식을 건드리면 §8·§9가 검사받지 않은 채로
나간다.

```bash
python3 scripts/check_style.py morning_brief_[DATE].html
python3 scripts/check_readability.py --strict morning_brief_[DATE].html
python scripts/check_macro.py --html morning_brief_[DATE].html --datadir <workspace>
python scripts/check_stance.py --html morning_brief_[DATE].html --datadir <workspace>
```

넷 중 하나라도 실패하면 원본(`.pre-humanize.html`)으로 되돌리고 STEP 3으로 간다.
**말투 때문에 발행을 거르지 않는다** — 윤문은 있으면 좋은 것이고, 게이트는 필수다.

**5. 통과하면 `.pre-humanize.html`을 지우고 STEP 3으로 간다.**

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
2. Copy yield_curve.png into the repo as assets/yield_curve_[YYYY-MM-DD].png, then promote **both** of the writer's books:
   - `macro_next.json` → `data/macro.json`
   - `stance_next.json` → `data/stance.json`
   Tomorrow's Actions run judges today's regime and triggers against these files. Publishing without promoting them leaves both books frozen — and because macro.json also carries `last_seen`, a missed promotion makes every indicator read as newly released tomorrow, which would hand the writer a free regime change.
3. **에디터 노트 (있는 날만)** — if `notes/[YYYY-MM-DD].md` exists in the repo clone, run `python3 scripts/apply_note.py posts/[YYYY-MM-DD].html` from the repo root. That file is the publisher's own view, written by hand before the run; the script drops it in verbatim after §2 전략 코멘트. **Never write, edit, polish, or fact-check that text, and never author the section yourself** — a note the publisher did not write is worse than no note. The script is a no-op (exit 1, page untouched) when the file is missing, empty, or still the unedited template, so it is safe to run unconditionally. Most days there is no note and no section.
4. Update posts.json in the repo root: add {"date", "title", "headline"}. Same-date entry → REPLACE, never duplicate. Keep valid JSON.
5. Regenerate sitemap.xml from posts.json: one <url> for https://fdo2a.github.io/ (lastmod=today, changefreq daily) plus one <url> per post (https://fdo2a.github.io/posts/DATE.html, lastmod). Keep valid XML.
6. Commit and push to main:
   git add -A && git commit -m "Add [YYYY-MM-DD] brief" && git push
   If the push fails, continue with remaining steps and report the failure clearly in your final message and PushNotification.

## STEP 4 — Notify

Send a PushNotification with the headline and the blog post URL (mention any failures).

**발행 채널은 블로그 하나뿐이다 (2026-08-18 사용자 지시로 Notion 발행 중지).** Do NOT publish to Notion, do NOT generate a PDF, do NOT use SendUserFile, and do NOT send email. If a Notion connector is available in the session, leave it alone — its presence is not an instruction to use it.

## RULES
- All prices/% changes in the published report MUST come from market_data.json / intraday.json; macro indicator values from research_notes.md. 수치 창작 절대 금지.
- **완성본만 발행 (2026-07-14 사용자 지시)**: 핵심 표(지수·섹터·채권·FX·원자재·메모리·AI 인프라)에 누락 항목이 있는 채로 발행 금지. 완성 불가 시 발행하지 말고 PushNotification으로 누락 내역을 보고할 것. 웹 리서치로 대체 수집한 시세는 발행 전 반드시 복수 출처 교차 확인 — 단일 검색 결과 수치는 신뢰하지 않는다 (7/13호에서 FX 방향·유가 등락률 오류 발생 전례).
- **발행본에 [확인필요] 금지 (STEP 2 게이트).** 미확인 항목은 끝까지 확인하거나 삭제·재구성.
- Web findings attributed to sources. Professional strategy-desk tone (기관 전략 리포트 톤).
- **「buy-side」 금지 (2026-08-22 사용자 지시)** — 발행본 어디에도 쓰지 않는다. §2 헤더는 「전략 코멘트」, 해석 박스는 「전략 해석」. `scripts/check_macro.py` 게이트가 차단한다.
- Final message: blog (GitHub Pages) delivery status, which subagents ran (or which fallback was used), and any failures.
