<!-- This file is where shared rules live. codex walks project docs from the git repo
     root (site/) down to cwd and never above it, so report/CLAUDE.md is NOT loaded when
     working inside site/ (measured 2026-09-05 with `codex debug prompt-input`).
     This file + one leaf must fit codex's chain limit, which drops the tail with no
     marker. Byte budget and what to do when it goes red: rule 4 below.
     Gate: scripts/common/tests/test_agent_docs.py -->

## Getting started (where to work, what to run)

- **Work from `site/`.** The project root (`/Users/daeyoung/Desktop/AI/report`) is not a git repo. Every path and command below is relative to `site/`; run `git`, `gh`, and all scripts after `cd site`.
- **Tests**: `cd site && python3 -m pytest scripts` — the whole tree, no `--ignore`. **Must run from `site/`**: from the project root it fails collection (`ModuleNotFoundError: scripts`) and ends with "N collected, 6 errors", and **the count alone looks like a pass, so read the `Interrupted` line.**
- **Publish gates run in order**: `scripts/apply_readability.py` (typography override — must come before any check) → per-pipeline gates (US `check_macro.py`, `check_stance.py`, `check_fed.py`, `check_weight.py`, `check_price_context.py`, `check_portfolio.py`, `check_session.py`; thesis `check_thesis.py`; weekly/monthly `check_period.py`; China `check_china.py`) → `check_readability.py --strict` → `check_style.py`. Note `check_style.py` takes a path only — it does not accept `--html`.
- **Hand-edited posts**: `python3 scripts/verify_post.py posts/DATE.html` (compares the number multiset against git HEAD).
- **Trigger data collection manually**: `gh workflow run collect-market-data.yml -f force=true` (same for `collect-kr-data.yml`, `collect-thesis-data.yml`, `collect-china-data.yml`).
- **Check unreviewed posts**: `python3 scripts/review_gate.py pending --hook`. The SessionStart hook calls this automatically, but the hook ends in `|| true` and fails silently — run it by hand whenever the queue looks wrong. The 「조판만 바뀐 N건」 and 「판정 불가」 queues have their own handling — `.claude/REVIEW_GATE.md`. The hourly launchd runner (`review_gate.py run --correct`) reviews us/kr with Codex, then invokes Claude to verify, correct and republish from an isolated clone. Drafts in `reviews/pending/` alone never authorize `mark`; follow `.claude/REVIEW_GATE.md`.

## Adding something new — keep this shape

Before you write new guidance, **decide where it goes.** `scripts/common/tests/test_agent_docs.py` enforces the shape.

| What you are writing | Where it goes |
|---|---|
| Rules, commands, gate order that apply to every task | **this file** |
| One pipeline's module map, I/O, invariants, gate markers, operational traps | `scripts/<p>/CLAUDE.md` |
| Design rationale, history, user quotes, bypasses that were found | `docs/superpowers/specs/` |
| Report authoring spec / routine procedure | `.claude/agents/*.md` / `.claude/*_ORCHESTRATOR.md` |
| A step-by-step procedure with a clear trigger | `.claude/skills/<name>/SKILL.md` |

1. A leaf holds **only the contract you need while working** — send history to a spec and end the section with **"When changing this: read `<spec>` before touching `X.py`."** A bare pointer does not get read; it has to be a conditional instruction. Name the **spec file**, not the directory. A path that no longer exists goes in **strikethrough** (`~~scripts/gone.py~~`) — that is the only exemption the reference gate honours.
2. New pipeline → create the leaf plus the `AGENTS.md → CLAUDE.md` symlink, and add its name to `LEAVES` in the test.
3. **No copies.** `AGENTS.md` is always a symlink (`site/` alone runs the other way).
4. **Budget: this file ≤ 12,488 B, this file + one leaf ≤ 31,744 B** — 1,024 B short of codex's 32,768 B cliff, where it discards the tail **with no marker**. The reserve is not room to spend; it is the width that lets the test go red while codex can still read the whole chain. When the test fails, **do not squeeze the leaf** — move the history (dates, measurements, what went wrong) into a spec and keep every obligation, then check the destination does not already say it. Growth here eats every chain's slack at once, and **us is the chain that runs out first** (~1 KB left; kr, thesis and china have 10 KB or more), so before writing here, suspect it belongs to a single pipeline.
5. English is fine for CLAUDE.md / AGENTS.md / SKILL.md (2026-09-05). Korean costs 3 bytes per character against the byte budget, so prefer English for guidance — but keep Korean where the Korean string *is* the data (section labels, controlled vocabulary, gate markers).

## Pipeline index — which file to open when

`scripts/{us,kr,thesis,china}/CLAUDE.md` attaches **automatically** when you touch a file in that directory. Everything below must be **opened explicitly**.

| Pipeline | To change the routine | Report spec |
|---|---|---|
| US morning brief | `.claude/ORCHESTRATOR.md` | `.claude/agents/brief-report-writer.md`, `brief-data-collector.md` |
| KR close brief | `.claude/KR_ORCHESTRATOR.md` | `.claude/agents/kr-report-writer.md` |
| Ticker thesis watch | `.claude/THESIS_ORCHESTRATOR.md` | pages are never hand-written — `scripts/thesis/content.py` |
| Weekly / monthly | `.claude/WEEKLY_ORCHESTRATOR.md`, `MONTHLY_ORCHESTRATOR.md` | `.claude/agents/period-report-writer.md` |
| China econ learning | `.claude/CHINA_ORCHESTRATOR.md` | `.claude/agents/china-report-writer.md` |
| Post-publish review | skill `review-gate` (`.claude/REVIEW_GATE.md`) | ledger `reviews/index.json` |


## Rules

Rationale and history live in the documents each rule points to. Only the rule itself belongs here.

1. **Design**: Toss system (Toss Blue #0064FF, Pretendard, 14px rounded cards, flat).
2. **Pagination**: `break-inside: avoid-page` per section.
3. **Fact-check gate**: never publish `[확인필요]`. Resolve an unverified item by research or delete it. **Never invent a number — deleting beats inventing.**
4. **Banned term "buy-side"**: never use buy-side / buy side / 바이사이드 anywhere in US or KR posts. The §7 (US) and §2 (KR) headers are 「전략 코멘트」; interpretation boxes are 「전략 해석」. `BANNED_LABELS` in `scripts/us/macro_gate.py` scans the whole post.
5. **Voice — write the way you talk** (Korean prose): name the subject, use active voice, one relation per sentence, one topic per paragraph (2–4 sentences). No body indent; `word-break: keep-all`. What to filter is not loanwords but **words the reader is seeing for the first time** — ① terms that always appear in market coverage stay as they are (`COMMON`); ② only transliterations that fail that bar get spelled out (`PLAIN`); ③ jargon that not even the news uses gets glossed once on first appearance (`GLOSS`); ④ **never stack unfamiliar words in one sentence** (only ② and ③ count). **The three groups and the stacking limit live in `scripts/us/style.py`**, and `scripts/check_style.py` checks all four rules (path argument only, no `--html`). Tables, headings, and captions are exempt. Details: `.claude/agents/brief-report-writer.md`, section 「말하듯이 쓴다」.
   **STEP 2.5 "remove the AI tell"** runs `humanize-korean:humanize-korean` on new Korean prose just before publishing — style only, with facts, numbers, dates, proper nouns and quotes unchanged. Three rules: **never touch the original** (edit a `*.humanizing.html` copy), put the result **into the authored source, not the generated HTML**, and swap only with **`scripts/humanize_prose.py finalize`** (never `mv` by hand) — it replaces the original only when every gate passes. **A readability warning rejects that draft, not the day's report.** Logic `scripts/us/prose_swap.py`; procedure `.claude/ORCHESTRATOR.md` / `KR_ORCHESTRATOR.md` STEP 2.5.
6. **Center of gravity: market/price coverage > judgment/positioning.** Price sections open with `<p data-standing>`, and only assets whose `moves.band` is `큼` or `매우 큼` get a `<p data-cause>` digging into why. Do not fix the order — lead with whatever there is something to say about that day. **US only**, so the body lives in `scripts/us/CLAUDE.md`; logic `scripts/us/weight.py`; design `docs/superpowers/specs/2026-08-30-recap-weight-rebalance-design.md`.
7. **Intraday flow**: market coverage includes a 30-minute-bar intraday path plus the catalyst narrative.
8. **Local environment**: macOS. PDF renders through headless Chrome; fonts are Pretendard / Apple SD Gothic Neo. **Foreground `sleep` is blocked — use `/bin/sleep`.** Playwright is installed.
9. **Verification**:
   ⓪ **A `<div>` still open at `</section>` closes the body container there** — later sections lose the 1120px cap and the side margins, and balanced open/close counts across the document do not rule it out. `readability.section_div_breaks()`, run by `check_readability.py` before both US and KR publishing.
   ① Check responsiveness with Playwright: `scrollWidth == viewport width` at 390 and 1280. **Never eyeball a screenshot.**
   ② When editing body text, compare the **data-token multiset (numbers, %, tickers) before and after** to guarantee the figures did not move.
   ③ Body container and nav bar are 1120px; wrap tables in `.tbl-scroll`.
   ④ Base is 42em/16px; **at 1024px and above it is 17px with no width cap.** Do not remove `word-break: keep-all`. Put the body `font-size` **on bare `p` only** — putting it on `.card p` outbids `.caption` and renders 12.5px captions at body size. `scripts/apply_readability.py` (v4) applies and repairs this automatically.
10. **Scheduled runs arrive late**: since 2026-08-27 the Actions scheduler delays scheduled runs by 2–5 hours. **Moving the cron time is not a fix.**
    ① All three collectors commit and push through **`bash scripts/ci/push_with_retry.sh`** (if the exec bit lands as 100644 in the index they all die with `Permission denied`). **A staged-only change does not survive this** — `git rm --cached` without a commit is undone by the next `pull --rebase --autostash`. Commit anything you want to keep. **Retry only on a rejected push** — a conflict or an auth failure dies in the same place, and a conflict leaves `.git/rebase-merge` behind that kills the remaining attempts too.
    ② **When the routine wakes before collection**, STEP 0 runs `gh workflow run <wf> -f force=true` directly, then **captures the run ID and waits with `gh run watch "$RUN" --exit-status`** (a bare `gh run watch` waits on the wrong run, and without `--exit-status` a failed collection reads as success). Afterwards re-read `report_date` and `complete`, and **do not publish if the data is still early.** Put the idempotency guard **after** collection — guarding first makes the routine read yesterday's data and quit with "already published".

## Work routine — 7 steps per command (user instruction, 2026-09-04)

**Applies to everything**, whether it is a one-line "fix this" or a new pipeline.

1. **Design** — write the spec. **Keep it in context; do not save it.**
2. **Design review** — hand it to codex (`/codex:rescue`) before implementing. **Read-only.**
3. **Update `plan.md`** — at the project root (`../plan.md`; keeping it in `site/` mixes it into publish commits). Record each point of feedback as **accepted / rejected / partially accepted in a table** — rejected ones with the reason.
4. **Implement** — TDD is the default here.
5. **Implementation review** — back to codex. This doubles as the pre-commit/pre-publish review.
6. **Narrow fix** — within two or three files, pass the codex output through as-is and name only the items to fix.
7. **Broad fix** — when it touches gates, data contracts, or pipeline boundaries, **restructure the findings into a written fix plan** and work through it in stages.

Two review points, because a wrong design wastes the whole implementation. **This is not asking for approval again.** Cloud routine sessions have no codex CLI, so it is a local-session rule. Delegate to codex also when the same problem has failed 2–3 times.

**Routine-published posts get a post-hoc gate**: when the SessionStart hook reports pending items via `scripts/review_gate.py pending --hook`, report it and follow the `review-gate` skill (`.claude/REVIEW_GATE.md`). Ledger: `reviews/index.json`.
