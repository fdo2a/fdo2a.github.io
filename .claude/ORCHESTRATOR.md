# US Morning Brief — Orchestrator Runbook

You are the orchestrator for the daily US morning market brief. Follow this runbook start to finish.

**Report trading date**: the most recent completed US trading day. **Authoritative source is the committed data file** (STEP 0 below) — trust `report_date` in `data/market_data.json`, which is the S&P 500's actual last-close date. Do NOT compute it from the KST run day; the old weekday-arithmetic rule caused a duplicate-report bug (2026-07-15). Only if no data file exists, fall back to arithmetic: previous US weekday relative to the KST run day (Tuesday KST → Monday US session, … Saturday KST → Friday), stepping back over US market holidays.

The repository fdo2a/fdo2a.github.io is cloned into your workspace as a source (locate with ls / find; if missing, clone https://github.com/fdo2a/fdo2a.github.io). Its .claude/agents/ directory contains the two subagent definitions used in STEP 1 and STEP 2.

## STEP 0 — 커밋된 데이터 파일 확인 (먼저)

A GitHub Actions workflow (.github/workflows/collect-market-data.yml) collects canonical yfinance/FRED data in a network-open runner and commits `data/market_data.json`, `data/intraday.json`, `data/yield_curve.png` before this routine fires. **This is the primary data path** — the routine's own environment blocks finance hosts (Yahoo/FRED/exchanges all 403), so do NOT try to fetch them here.

1. `git -C <repo> pull` (or re-clone) to get the latest committed data, then Read `data/market_data.json`.
2. If it exists, `report_date` matches today's expected US session (most recent US weekday; if it looks stale by >1 trading day, note it), and `"complete": true` — **copy the three data files to the workspace root** (`market_data.json`, `intraday.json`, `yield_curve.png`) and skip STEP 1's market-data collection entirely. Proceed to STEP 1 for research_notes.md only (the web-research half).
3. If `data/market_data.json` is missing, stale, or `"complete": false`, note exactly which fields `missing` lists and run the full STEP 1 collector to fill the whole set (or just the gaps). The Actions run may have partially failed; treat its output as a starting point, not gospel.

## STEP 1 — 데이터 수집·검증 (subagent: brief-data-collector)

If STEP 0 already produced a complete market_data.json/intraday.json/yield_curve.png, you still need **research_notes.md** — launch the collector subagent (or fallback) for the web-research portion only (STEP 2 of the agent file: 시황 동인·채권 맥락·메모리·AI 인프라·경제지표 4축). Otherwise run it in full.

Launch the Agent tool with subagent_type "brief-data-collector", run synchronously (run_in_background: false). Prompt: the report trading date [YYYY-MM-DD], whether market data is already present (and its path), and the instruction to produce any missing artifacts in the workspace root: market_data.json, intraday.json, yield_curve.png (may be skipped if week-ago yields are missing), research_notes.md.

Fallbacks: if the subagent type is not available, Read .claude/agents/brief-data-collector.md in the repo and launch a general-purpose agent with that file's body (below the frontmatter) plus the report date as the prompt. If the Agent tool itself is unavailable, execute that file's instructions yourself, in full, before continuing.

Gate before proceeding: market_data.json parses as JSON with non-null indices/sectors/yields; intraday.json parses; research_notes.md exists and contains the 4-axis macro indicator table. If the gate fails, relaunch the subagent once with the specific error details; if it fails again, fix the gaps yourself using the agent file's instructions.

**Completeness gate (사용자 지시 2026-07-14 — 완성본만 발행)**: the canonical dataset must be COMPLETE before STEP 2 — indices 6종(3대 지수+러셀+Growth/Value), sectors 10종 전부, yields 2Y/5Y/10Y/30Y + curve chart, FX 4종, commodities 4종, memory 6종, AI infra 5종. "미확인이라 표에서 제외" 처리는 발행 사유가 아니라 발행 중단 사유다. If primary sources (yfinance/FRED) are blocked, retry via alternative canonical routes (yfinance mirror tickers ^FVX/^TNX/^TYX, FRED CSV via curl, exchange sites) until complete. If the dataset still cannot be completed, DO NOT publish a partial report to any channel — send a PushNotification listing exactly which fields are missing and why, and stop.

## STEP 2 — 리포트 작성 (subagent: brief-report-writer)

Launch the Agent tool with subagent_type "brief-report-writer", run synchronously. Prompt: the report trading date, the list of input files from STEP 1, and the required output filename morning_brief_[YYYY-MM-DD].html in the workspace root. Same fallbacks as STEP 1 (agent file: .claude/agents/brief-report-writer.md).

Gate before proceeding (발행 게이트): (a) grep the final HTML for '확인필요' — must be 0 occurrences; (b) spot-check at least 5 numbers in the HTML tables against market_data.json / intraday.json — all must match. If either check fails, relaunch the writer subagent with the specific violations; repeat until clean. 수치 창작 절대 금지 — 미확인 항목은 삭제·재구성이 원칙.

## STEP 3 — Publish to the blog (GitHub Pages 루트 사이트)

Site base URL: https://fdo2a.github.io/

1. Copy the report HTML into the repo as posts/[YYYY-MM-DD].html, then make two injections:
   (a) Immediately BEFORE `<div class="doc">`, this navigation block:
```html
<div style="max-width:760px;margin:0 auto;padding:14px 18px 0;display:flex;align-items:center;gap:10px;">
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
2. Copy yield_curve.png into the repo as assets/yield_curve_[YYYY-MM-DD].png.
3. Update posts.json in the repo root: add {"date", "title", "headline"}. Same-date entry → REPLACE, never duplicate. Keep valid JSON.
4. Regenerate sitemap.xml from posts.json: one <url> for https://fdo2a.github.io/ (lastmod=today, changefreq daily) plus one <url> per post (https://fdo2a.github.io/posts/DATE.html, lastmod). Keep valid XML.
5. Commit and push to main:
   git add -A && git commit -m "Add [YYYY-MM-DD] brief" && git push
   If the push fails, continue with remaining steps and report the failure clearly in your final message and PushNotification.

## STEP 4 — Publish to Notion

Using the Notion MCP tools (notion-create-pages), create one page in data source e75a2eb0-425a-4f01-94a1-ca8082811026 (database "US Market Brief"):
- properties: "제목" = 보고서 제목, "date:날짜:start" = YYYY-MM-DD, "헤드라인" = 헤드라인 한 줄, "웹 링크" = https://fdo2a.github.io/posts/YYYY-MM-DD.html
- icon: 📈
- content: full report in Notion-flavored Markdown — > quote headline + styled-web link first, sections as # headings with markdown tables. 채권 섹션에 ![미 국채 수익률 커브](https://fdo2a.github.io/assets/yield_curve_[YYYY-MM-DD].png) + 주간 변화 캡션. 마지막에 면책 문구(정보 제공 목적, 투자 권유 아님).
- Do not create duplicates for the same date.

## STEP 5 — Notify

Send a PushNotification with the headline and the blog post URL (mention any channel failures). Do NOT generate a PDF, do NOT use SendUserFile, and do NOT send email — the deliverables are the blog post and the Notion page only.

## RULES
- All prices/% changes in the published report MUST come from market_data.json / intraday.json; macro indicator values from research_notes.md. 수치 창작 절대 금지.
- **완성본만 발행 (2026-07-14 사용자 지시)**: 핵심 표(지수·섹터·채권·FX·원자재·메모리·AI 인프라)에 누락 항목이 있는 채로 발행 금지. 완성 불가 시 발행하지 말고 PushNotification으로 누락 내역을 보고할 것. 웹 리서치로 대체 수집한 시세는 발행 전 반드시 복수 출처 교차 확인 — 단일 검색 결과 수치는 신뢰하지 않는다 (7/13호에서 FX 방향·유가 등락률 오류 발생 전례).
- **발행본에 [확인필요] 금지 (STEP 2 게이트).** 미확인 항목은 끝까지 확인하거나 삭제·재구성.
- Web findings attributed to sources. Professional buy-side tone.
- Final message: delivery status of both channels (GitHub Pages / Notion), which subagents ran (or which fallback was used), and any failures.
