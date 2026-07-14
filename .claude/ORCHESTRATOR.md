# US Morning Brief — Orchestrator Runbook

You are the orchestrator for the daily US morning market brief. Follow this runbook start to finish.

**Report trading date**: the most recent completed US trading day. The US session closes around 05:00–06:00 KST the same morning this routine runs, so the report date is the previous US weekday relative to the KST run day (Tuesday KST → Monday US session, Wednesday KST → Tuesday, … Saturday KST → Friday). If that weekday was a US market holiday, use the trading day before it.

The repository fdo2a/fdo2a.github.io is cloned into your workspace as a source (locate with ls / find; if missing, clone https://github.com/fdo2a/fdo2a.github.io). Its .claude/agents/ directory contains the two subagent definitions used in STEP 1 and STEP 2.

## STEP 1 — 데이터 수집·검증 (subagent: brief-data-collector)

Launch the Agent tool with subagent_type "brief-data-collector", run synchronously (run_in_background: false). Prompt: the report trading date [YYYY-MM-DD] and the instruction to produce, in the workspace root: market_data.json, intraday.json, yield_curve.png (may be skipped if week-ago yields are missing), research_notes.md.

Fallbacks: if the subagent type is not available, Read .claude/agents/brief-data-collector.md in the repo and launch a general-purpose agent with that file's body (below the frontmatter) plus the report date as the prompt. If the Agent tool itself is unavailable, execute that file's instructions yourself, in full, before continuing.

Gate before proceeding: market_data.json parses as JSON with non-null indices/sectors/yields; intraday.json parses; research_notes.md exists and contains the 4-axis macro indicator table. If the gate fails, relaunch the subagent once with the specific error details; if it fails again, fix the gaps yourself using the agent file's instructions.

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
- **발행본에 [확인필요] 금지 (STEP 2 게이트).** 미확인 항목은 끝까지 확인하거나 삭제·재구성.
- Web findings attributed to sources. Professional buy-side tone.
- Final message: delivery status of both channels (GitHub Pages / Notion), which subagents ran (or which fallback was used), and any failures.
