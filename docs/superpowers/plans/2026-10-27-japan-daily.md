# Japan Daily Close Brief Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish a Korean PM-desk evening brief for every Tokyo trading day at `/japan/daily/<date>.html` covering stocks, JGBs, yen, macro and Japanese economic news, without changing the Japan weekly.

**Architecture:** An Actions collector writes a candidate snapshot (code computes every number); a cloud routine fixes the target Tokyo session, dispatches collection, has a writer fill prose slots, renders tables from the snapshot, runs gates, promotes the snapshot to "published" and commits. Review runner re-checks from the published snapshot alone.

**Tech Stack:** Python 3.13, pytest, yfinance 1.4.1, GitHub Actions, existing `scripts/us|common|japan` helpers.

**Spec:** `docs/superpowers/specs/2026-10-27-japan-daily-design.md` — §13 overrides earlier sections. Review table: `../plan.md` 「2026-10-27 — 일본 일간」.

## Global Constraints

- Japan weekly files, `japan/posts/`, `japan/data/<KEY>*.json`, `japan/data/calendar.json` meaning, `japan/news.py` shared classification and `fetch_japan_news.py` freeze behaviour stay unchanged (regression tests prove it).
- Session = Tokyo trading day from `data/market_holidays.json` `jp`; Tokyo cash close 15:30 JST.
- Nikkei `complete` only when the official Nikkei CSV has the `target_session` row and it matches `fast_info.lastPrice` within 0.01%. The CSV is never committed.
- Never use yfinance `previousClose`; a change needs a denominator dated exactly `prev_session`.
- FX cut = 5-minute bar ending 16:30 JST; `JPYKRW=X × 100` = 원 per 100엔.
- JGB = MOF `jgbcme.csv`, latest observation ≤ `prev_session`; bp = latest obs − previous bond business day.
- BOJ API `https://www.stat-search.boj.or.jp/api/v1/`, no key, ≤ 10 calls per run; series resolved by name via `/getMetadata`, never hardcoded.
- Footer credit verbatim: `This service uses the API provided by the "Bank of Japan Time-Series Data Search." The Bank of Japan does not guarantee the content of the service.`
- Body `<body data-register="da">`, 「전략 코멘트」 header, no buy-side, no consensus/expectation comparison anywhere, no 「지수 기여」 wording.
- News categories for the daily: `('macro', 'policy', 'industry', 'market')` in that order, ≤3 each, article JST date = session, published ≤ 16:30 JST.
- Daily cron `cron: '30 16 * * 1-5'` with `timezone: 'Asia/Tokyo'`; routine 19:00 KST, retry 21:00 KST, no backfill after 21:00 failure.
- Writer spec `.claude/agents/japan-daily-writer.md` ≤ 20,480 B. Model sonnet-5, no connectors.
- Doc budget: AGENTS.md ≤ 12,488 B and AGENTS.md + any leaf ≤ 31,744 B (`scripts/common/tests/test_agent_docs.py`).
- Tests from `site/`: `python3 -m pytest scripts` — read the `Interrupted` line.

## Review Focus

- A Japanese holiday on Monday (prev_session crosses a weekend + holiday) → changes use the real previous session, never Friday-vs-Thursday mislabelled. Test in Task 1 and Task 3.
- Run after midnight JST (delayed retry) → target_session stays the session fixed before the lock, not the new calendar day. Test in Task 1.
- yfinance returns yesterday's price as `lastPrice` (no bar today) → instrument excluded, not published as today. Test in Task 3.
- BOJ release day where the API has not yet reflected the new period → macro says pending, never states the old value as today's release. Test in Task 5.
- News article updated after 16:30 or dated the previous day → excluded before the per-category cap. Test in Task 7.

---

### Task 1: Session, lock and due decision for `jp_daily`

**Files:**
- Modify: `scripts/ci/routine_due.py` (STALE_MIN, session fn, lock_name, decide, CLI)
- Test: `scripts/ci/tests/test_routine_due.py` (add cases; create file if absent following existing ci tests)

**Interfaces:**
- Produces: `jp_session(now: datetime, holidays=()) -> str` (ISO; JST date minus 15h30m, then `_trading_back`), `jp_prev_session(session: str, holidays=()) -> str`, `decide_jp_daily(now, files, lock_age, holidays=()) -> (verdict, msg)` wanting `japan/daily/<s>.html`, `lock_name('jp_daily', now, holidays=) -> 'jpd-<session>'`, CLI `routine_due.py jp_daily` and `lock-name jp_daily`, `STALE_MIN['jp_daily'] = 120`.

- [ ] **Step 1: Failing tests** — `test_jp_session_evening` (2026-10-26 19:00 KST → `2026-10-26`), `test_jp_session_before_close` (2026-10-26 14:00 KST → `2026-10-23`), `test_jp_session_after_midnight` (2026-10-27 00:30 KST → `2026-10-26`), `test_jp_prev_session_holiday` (holidays `['2026-11-03']`, session `2026-11-04` → `2026-11-02`), `test_decide_jp_daily_done_busy_due`, `test_lock_name_cli_accepts_jp_daily`, `test_weekly_japan_lock_unchanged` (`lock_name('japan', now, 'W43') == 'japan-W43'`).
- [ ] **Step 2:** `python3 -m pytest scripts/ci -q` → new tests FAIL.
- [ ] **Step 3:** Implement; CLI usage strings list `us|kr|jp_daily`.
- [ ] **Step 4:** Tests PASS, whole `scripts/ci` green.
- [ ] **Step 5:** Commit `feat(jp-daily): 도쿄 세션·잠금·발행 판정`.

### Task 2: Daily calendar overlay and `event_day`

**Files:**
- Create: `japan/data/calendar_daily.json`, `scripts/japan/daily_calendar.py`
- Test: `scripts/japan/tests/test_daily_calendar.py`

**Interfaces:**
- Produces: overlay schema `{"checked_at": ISO, "events": [{"date", "time_jst"|null, "name_ko", "kind": "release"|"meeting", "tier": "major"|"minor", "series": str|null, "source": URL, "checked_at": ISO}]}`; `load(path) -> dict`; `version(cal) -> str` (sha256 of canonical JSON, first 12 hex); `event_day(cal, session) -> list[event]` (release + major + date == session); `upcoming(cal, session, days=14) -> list[event]` (date > session, ≤ session+14); `today_events(cal, session) -> list[event]` (all kinds).
- Seed only source-checked rows: BOJ 10/29-30 meeting (`kind: meeting`), 10/30 policy result + outlook summary (`release, major`), 11/2 full outlook report (`release, minor`), 11/10 summary of opinions (`release, minor`), 12/17-18 meeting, 12/18 result. Add CPI/Tankan/GDP/wages rows only with a ministry URL checked on the day you add them; otherwise leave them out.

- [ ] **Step 1: Failing tests** — `test_meeting_start_is_not_event_day` (10/29 → `[]`), `test_result_day_is_event_day` (10/30 → one event), `test_minor_release_not_event_day`, `test_upcoming_excludes_today`, `test_version_stable_under_key_order`, `test_weekly_calendar_untouched` (load `japan/data/calendar.json`, assert it has no `kind`/`tier` keys).
- [ ] **Step 2:** FAIL. **Step 3:** Implement + seed file. **Step 4:** PASS. **Step 5:** Commit.

### Task 3: Equity closes, changes, splits, FX cut (pure)

**Files:**
- Create: `scripts/japan/daily_prices.py`
- Test: `scripts/japan/tests/test_daily_prices.py`

**Interfaces:**
- Produces:
  - `nikkei_official(csv_text: str, session: str) -> float|None` (row dated session; tolerate the trailing copyright line and cp932).
  - `nikkei_close(official: float|None, fast_last: float|None, tol_pct=0.01) -> dict` → `{"value", "ok": bool, "why"}`.
  - `same_session_price(fast_last, last_bar_date: str|None, session) -> float|None` (None unless bar date == session).
  - `denominator(history: list[[date, close]], prev_session: str) -> dict|None` → `{"date", "value", "source"}` only when a row is dated exactly prev_session.
  - `change(today: float, denom: dict|None) -> float|None` (pct, 2 dp).
  - `verify_jump(today, denom, splits: list[[date, ratio]]) -> dict` → `{"ok", "adjusted_denom", "why"}`; |chg| > 15% triggers split adjustment (yfinance `Ticker.splits`); still > 15% after adjustment and no split → ok True (real move) unless prices differ by a power of 10 (unit error → ok False).
  - `fx_cut(bars: list[(iso_start, close)], session: str, cut="16:30", bar_minutes=5) -> dict|None` → `{"value", "bar_start", "bar_end", "tz": "Asia/Tokyo", "basis": "bar_end_1630_jst"}`; the bar whose end == 16:30 JST on session.
- Consumes: `jp_prev_session` (Task 1).

- [ ] **Step 1: Failing tests** — `test_nikkei_official_reads_session_row` (fixture: last two rows of the 10/26 CSV incl. copyright line → 62189.65), `test_nikkei_close_mismatch_not_ok` (62189.65 vs 62285.61), `test_same_session_price_rejects_stale_bar`, `test_denominator_requires_exact_prev_session` (`10/23=100, 10/26 missing, 10/27=110`, prev_session `2026-10-26` → None), `test_change_none_without_denom`, `test_verify_jump_split_adjusts` (ratio 10), `test_verify_jump_real_move_kept` (−18%, no split), `test_verify_jump_unit_error` (×100), `test_fx_cut_picks_1630_bar`, `test_fx_cut_missing_bar_none`.
- [ ] **Step 2–4:** FAIL → implement → PASS. **Step 5:** Commit.

### Task 4: JGB and BOJ API parsing (pure)

**Files:**
- Create: `scripts/japan/daily_rates.py`
- Test: `scripts/japan/tests/test_daily_rates.py`

**Interfaces:**
- Consumes: `common.weekly_sources.parse_jgb_csv`.
- Produces:
  - `jgb_block(rows, prev_session, tenors=('2Y','5Y','10Y','30Y')) -> dict` → per tenor `{"value", "period": obs_date, "prev_period", "chg_bp"}`; obs_date = latest row ≤ prev_session; `None` block with `why` when latest row < previous bond business day of prev_session (stale).
  - `boj_values(resp: dict) -> list[{"code","name","unit","freq","period","value"}]` from `RESULTSET[].VALUES.SURVEY_DATES/VALUES`, dropping nulls; `period` normalised (`20261022` → `2026-10-22`, `202609` → `2026-09`, quarterly `2026Q3`).
  - `call_rate(resp, session, max_lag_days=3) -> dict|None` → latest obs with `period`, `fetched_at` supplied by caller; None if older than session − 3 trading days.
  - `resolve_series(meta_resp: dict, name_pattern: str) -> str|None` (regex over `NAME_OF_TIME_SERIES`; error if >1 match).

- [ ] **Step 1: Failing tests** — `test_jgb_uses_prev_session_row` (fixture rows to 10/23, prev_session 10/23), `test_jgb_bp_against_previous_bond_day`, `test_jgb_stale_returns_none`, `test_boj_values_drop_null` (fixture = the FM01/STRDCLUCON JSON captured 2026-10-27, values to 10/22), `test_call_rate_lag_ok` (session 10/26 → 10/22 ok), `test_call_rate_too_old`, `test_resolve_series_ambiguous_raises`.
- [ ] **Step 2–4:** FAIL → implement → PASS. **Step 5:** Commit.

### Task 5: Macro release status

**Files:**
- Create: `scripts/japan/daily_macro.py`
- Test: `scripts/japan/tests/test_daily_macro.py`

**Interfaces:**
- Consumes: `daily_calendar.today_events`, `daily_rates.boj_values`.
- Produces: `macro_items(events_today, series_values: dict[series_key, list], session) -> list[{"name_ko","series","status": "released"|"pending","period","value","prev_period","prev_value","yoy","released": session|null,"source"}]`. `released` only when the event's `series` has a period newer than the one stored in the previous published snapshot (`prev_periods: dict` argument); else `pending`. v1 series: BOJ CGPI, SPPI, Tankan DI, money stock (name patterns as constants `SERIES` with BOJ db codes).

- [ ] **Step 1: Failing tests** — `test_release_reflected_is_released`, `test_release_not_reflected_is_pending` (API still returns last month), `test_no_event_no_items`, `test_yoy_from_same_period_last_year_only`.
- [ ] **Step 2–4.** **Step 5:** Commit.

### Task 6: Movers adapter (fixed universe, no contribution)

**Files:**
- Create: `scripts/japan/daily_movers.py`
- Test: `scripts/japan/tests/test_daily_movers.py`

**Interfaces:**
- Produces: `UNIVERSE: tuple[(code, name_ko, sector17)]` — about 40 large caps (Toyota 7203 「도요타」, Sony 6758 「소니그룹」, Tokyo Electron 8035 「도쿄일렉트론」, MUFG 8306, … ; sector names = TOPIX-17 Korean labels shared with the sector table); `build(session, rows: list[{"code","name","change_pct","close"}]) -> dict` in `common.movers.check`-compatible shape (`{"report_date","universe","threshold_pct": 5.0,"groups":[{"id": "g1", "label", "industry", "direction", "members":[{"name","change_pct","close"}]}]}`) — candidates = top 2 and bottom 2 by change_pct plus |change| ≥ 5; group by (sector17, direction), ≤ 5 groups; labels 「등락 상위」「등락 하위」「이상 등락」. Read `common/movers.py` `group_movers`/`check` for the exact keys and reuse `group_movers` if its input shape fits.
- `common/movers.py` itself is not modified.

- [ ] **Step 1: Failing tests** — `test_groups_without_market_cap`, `test_no_contribution_label`, `test_check_compatible` (render a `<p data-mover="g1">` with the member pct and assert `common.movers.check(html, built, session) == []`), `test_us_kr_movers_unchanged` (existing `scripts/common/tests` still pass).
- [ ] **Step 2–4.** **Step 5:** Commit.

### Task 7: Daily news file and gate

**Files:**
- Create: `scripts/japan/news_daily.py`, `scripts/japan/daily_news_gate.py`
- Modify: `scripts/fetch_japan_news.py` (add `--daily-session YYYY-MM-DD` mode), `scripts/check_news.py` (market `jp-daily`)
- Test: `scripts/japan/tests/test_news_daily.py`

**Interfaces:**
- Consumes: `japan.news` `screen`, `dedupe`, `preselect`, `same_event`, `PER_CATEGORY`; `fetch_japan_news.fetch_bodies`, `summarize_chosen`; `us.news_summary.summary_problem`.
- Produces:
  - `DAILY_CATEGORIES = ('macro', 'policy', 'industry', 'market')`, `CUT = '16:30'`.
  - `retag(rows) -> rows` (official BOJ speech rows `insight` → `macro`; everything else unchanged; `global`/`insight` dropped).
  - `cut_filter(rows, session, cut=CUT) -> rows` (article `published` JST date == session and time ≤ cut) — applied **before** `preselect`.
  - `finalize_daily(rows, session, per=3) -> rows` (DAILY_CATEGORIES order, same_event across all taken, body + summary_problem None).
  - File `japan/data/news/daily/<session>.json` `{"report_date","cut":"16:30","complete","notes","items":[…]}`; written by `fetch_japan_news.py --daily-session` without reading or writing `japan/data/news/<date>.json`.
  - `daily_news_gate.check(html, collected, session) -> list[str]` — wraps `us.news_gate.check(html, collected, session, categories=DAILY_CATEGORIES, title='일본 경제 뉴스')` and adds: only DAILY_CATEGORIES, ≤3 per category, no same_event pair among rendered items, all items inside the news section, each item's guid in `collected` with published date == session and ≤ cut, numbers in an item only from that item's summary.
  - `check_news.py --market jp-daily --date <session>` loads the daily file and calls it.

- [ ] **Step 1: Failing tests** — reproduce codex #6: `test_four_same_event_macro_blocked`, `test_global_item_blocked`, `test_after_cut_blocked` (20:00), `test_previous_day_blocked`, `test_cut_before_cap` (4 candidates, the in-cut one ranked last survives), `test_boj_speech_becomes_macro_daily_only` (weekly `classify`/`harvest_official` output unchanged), `test_weekly_freeze_untouched` (run daily mode in tmp dir; assert no file under `news/<date>.json`).
- [ ] **Step 2–4.** Also run `python3 -m pytest scripts/japan scripts/us/tests -q -k news` → green. **Step 5:** Commit.

### Task 8: Collector and workflow

**Files:**
- Create: `scripts/collect_japan_daily.py`, `.github/workflows/collect-japan-daily.yml`
- Test: `scripts/japan/tests/test_collect_daily.py` (fetchers injected; no network)

**Interfaces:**
- Consumes: Tasks 1-7.
- Produces: `collect(session: str, fetch: Fetchers, now: datetime) -> dict` writing `japan/data/daily/candidate/<session>.json`:
  `{"session","prev_session","scheduled_at","ran_at","cut":"16:30","complete": bool,"fetch_status":{source: "ok"|reason},"indices":{"nikkei":{…},"topix_etf":{…}},"sectors":[{code,name_ko,value,chg_pct,denom,ok,why}],"movers":{…},"jgb":{…},"call_rate":{…},"fx":{"usdjpy","eurjpy","krw_per_100jpy"},"macro":[…],"calendar":{"version","today","upcoming"},"news_file": "japan/data/news/daily/<s>.json"}`.
  Also `reconcile(prev_published: dict, daily_bars) -> list[row]` appends to `japan/data/daily/checks.jsonl` (`{"session","field","published","later","diff_pct","kind": "lag"|"rounding"|"mismatch"}`) — never edits a published snapshot; `mismatch` rows feed the review gate. Test `test_reconcile_never_touches_published`.
  Refuses to write when `japan/data/daily/<session>.json` (published) exists. Appends history `japan/data/history/jp_daily.jsonl` only from the publish step (Task 10), not here.
- Workflow: `on.schedule cron '30 16 * * 1-5' timezone 'Asia/Tokyo'` + `workflow_dispatch` input `session` and `nonce`; `concurrency: {group: collect-japan-daily, cancel-in-progress: false}`; steps: install yfinance, curl_cffi, pypdf; run `fetch_japan_news.py --daily-session`, then `collect_japan_daily.py --session`; commit via `bash scripts/ci/push_with_retry.sh`. Run name includes the nonce (copy the weekly workflow's nonce pattern).

- [ ] **Step 1: Failing tests** — `test_complete_false_when_official_missing`, `test_fetch_failure_recorded_and_blocks_core`, `test_noncore_failure_drops_block_only`, `test_refuses_to_overwrite_published`, `test_snapshot_records_basis_and_times`.
- [ ] **Step 2–4.** **Step 5:** Commit. **Step 6:** `gh workflow run collect-japan-daily.yml -f session=<today> -f nonce=<x>` on a trading day 16:30-19:00 JST, `gh run watch "$RUN" --exit-status`; record in plan.md: Nikkei official match, fast_info freshness, sectors present (1629 handled), BOJ API and Yahoo reachable from Actions.

### Task 9: Renderer and assembly

**Files:**
- Create: `scripts/japan/daily_render.py`, `scripts/build_japan_daily.py`
- Test: `scripts/japan/tests/test_daily_render.py`

**Interfaces:**
- Produces: `SECTIONS = ('comment','today','equity','bonds','yen','macro','news','next')`, `order(event_days: list) -> tuple` (macro moved to index 1 when non-empty), `render_tables(snap) -> dict[name, html]` (indices, sectors, movers members, JGB with period labels, call rate with period, FX with cut label and the note 「주간 보고서의 달러/엔은 뉴욕 16:00 기준이라 값이 다르다」, macro, next 14 days), `assemble(body, meta, snap) -> html` following `japan/render.assemble` (`<!--T:name-->` placeholders, section ids, breadcrumb, `<body data-register="da">`, BOJ credit footer, canonical `https://fdo2a.github.io/japan/daily/<s>.html`).
  CLI: `build_japan_daily.py diag --session S` (prints writer input JSON: snapshot + order + news items + previous daily path), `assemble --session S --body body.html --meta meta.json --out japan/daily/S.html`.

- [ ] **Step 1: Failing tests** — `test_order_normal_day`, `test_order_event_day_macro_second`, `test_jgb_table_shows_period_label`, `test_fx_table_shows_cut_and_weekly_note`, `test_credit_footer_verbatim`, `test_missing_noncore_block_omitted_with_note`.
- [ ] **Step 2–4.** **Step 5:** Commit.

### Task 10: Daily gate, publish step, listings

**Files:**
- Create: `scripts/japan/daily_gate.py`, `scripts/check_japan_daily.py`, `scripts/publish_japan_daily.py`
- Modify: `scripts/update_archives.py` (kind `jp-daily` → `japan/daily.json`, `japan/daily`, entry key `date`), `japan/index.html`
- Test: `scripts/japan/tests/test_daily_gate.py`, `scripts/japan/tests/test_publish_daily.py`

**Interfaces:**
- Produces:
  - `daily_gate.check(html, snap, session, news) -> list[str]` — complete; filename/snapshot/session agree; core finite > 0; `data-register="da"`; no `[확인필요]`/TODO; section order == `order(snap.calendar.today event_days)`; unique sections; `<span data-ref="path.to.field">` value/unit/period match snapshot (e.g. `jgb.10Y.value`); any paragraph citing a field whose period ≠ session carries that period's date form; remaining prose numbers ⊂ snapshot figures (reuse `japan.gate._figures`/`_jo_eok`); consensus words (예상·컨센서스·상회·하회·시장 전망치) blocked in every section; weekly signal vocabulary (A 경로·B 경로·신호 집계·임계값) blocked; 「지수 기여」 blocked; BOJ credit present; `common.movers.check`; `us.macro_gate.BANNED_LABELS`.
  - `check_japan_daily.py --session S [--html path]` exit 1 on any finding.
  - `publish_japan_daily.py --session S --title T --headline H` — copies candidate → `japan/data/daily/S.json`, appends `japan/data/history/jp_daily.jsonl` (upsert by session), updates `japan/daily.json` via `update_archives` with `commit` placeholder filled after commit, merges sitemap.
  - `japan/index.html`: daily list first (from `japan/daily.json`), weekly list second; metadata/JSON-LD/intro no longer say 「매주 일요일」 only; empty daily list renders the weekly list alone.
- [ ] **Step 1: Failing tests** — one test per codex #7/#8 repro: `test_swapped_tenor_values_blocked` (「JGB 2년 1.5%, 10년 0.75%」 with data-ref), `test_wrong_unit_blocked` (「1.5엔」), `test_unverified_marker_blocked`, `test_missing_register_blocked`, `test_consensus_in_comment_blocked`, `test_stale_value_without_date_blocked`, `test_order_mismatch_blocked`, `test_signal_vocab_blocked`, `test_credit_missing_blocked`, `test_publish_keeps_weekly_listing` (japan/posts.json untouched, sitemap keeps US/KR/weekly URLs), `test_publish_replaces_same_date`.
- [ ] **Step 2–4.** **Step 5:** Playwright check on an assembled fixture: `scrollWidth == viewport` at 390 and 1280. **Step 6:** Commit.

### Task 11: Review runner integration

**Files:**
- Modify: `scripts/review/kinds.py`, `scripts/review_gate.py` (the DAILY/section branches near lines 106, 693, 1028-1041, 1125-1145, 1272), `scripts/review/style_pass.py` (170-171, 212-225), `scripts/review/corrector.py` (104-116, 230-232, 258-280)
- Test: `scripts/review/tests/test_kinds_jp_daily.py` (+ extend existing review tests)

**Interfaces:**
- Produces: `KINDS` entry `'japan/daily': {"market": "jp", "span": "daily", "evidence": ("japan/data/daily/{key}.json", "japan/data/news/daily/{key}.json"), "gate": ["scripts/check_japan_daily.py", "--session", "{key}"], "max_age": 2}`; `section_of('japan/daily/2026-10-27.html') == 'japan/daily'`; `publish_day` → the file date; corrector accepts `japan/daily` with the same fact-correction rights as us/kr and re-runs `check_japan_daily.py` + `check_news.py --market jp-daily`.
- [ ] **Step 1: Failing tests** — `test_jp_daily_section_evidence_gate`, `test_jp_daily_publish_day`, `test_corrector_allows_jp_daily`, `test_japan_weekly_kind_unchanged` (evidence, gate `check_japan.py --key`, MAX_AGE 3, Sunday publish day).
- [ ] **Step 2–4.** Run `python3 -m pytest scripts/review -q`. **Step 5:** Commit.

### Task 12: Routine docs, writer spec, agent-doc budget

**Files:**
- Create: `.claude/JAPAN_DAILY_ORCHESTRATOR.md`, `.claude/agents/japan-daily-writer.md`
- Modify: `scripts/us/CLAUDE.md` (move history to a spec first), `AGENTS.md` pipeline table row 「Japan daily」, `scripts/japan/CLAUDE.md` (daily section: modules, invariants from Global Constraints, 「When changing this: read `docs/superpowers/specs/2026-10-27-japan-daily-design.md` before touching `scripts/japan/daily_*.py`」)
- Test: `scripts/common/tests/test_agent_docs.py` (existing)

**Interfaces:**
- Orchestrator steps: STEP 0 fix `target_session` (`routine_due.py jp_daily`), acquire `jpd-<session>` lock, dispatch collection with nonce + `gh run watch "$RUN" --exit-status`, re-read candidate `complete`, guard after collection; STEP 1 `build_japan_daily.py diag`; STEP 2 writer → body/meta, translationese self-check; STEP 2.5 assemble → `apply_readability.py` → `check_japan_daily.py` → `check_news.py --market jp-daily` → `check_readability.py --strict` → `check_style.py`; STEP 3 `publish_japan_daily.py`, fetch guard `git cat-file -e origin/main:japan/daily/S.html`, commit `Add JP daily [S]`, push with rebase recovery like KR STEP 3; STEP 4 PushNotification; all non-writing exits release the lock; 21:00 retry gives up with a final-failure notification (no backfill).
- Writer: reader = PM, `-다`, 「전략 코멘트」 2-3 paragraphs, sections fixed by `order`, prose only into slots, numbers only via snapshot with `data-ref` for core values, date labels for JGB/call rate/FX cut, no consensus, no weekly signals, news blocks only from the daily news file, pointer to `STYLE_EXEMPLARS.md` sections instead of copying them. ≤ 20,480 B.
- [ ] **Step 1:** `wc -c` the chains; move US leaf history (dates, measurements) into an existing or new spec until AGENTS.md + US leaf leaves ≥ the bytes the new row needs; keep every obligation.
- [ ] **Step 2:** Write docs. **Step 3:** `python3 -m pytest scripts/common/tests/test_agent_docs.py -q` PASS and `wc -c .claude/agents/japan-daily-writer.md` ≤ 20480. **Step 4:** Commit.

### Task 13: First draft, implementation review, routine

- [ ] **Step 1:** Whole suite `python3 -m pytest scripts` green (read `Interrupted`).
- [ ] **Step 2:** codex implementation review (read-only, full text to stdout per memory), table in `../plan.md`, fixes.
- [ ] **Step 3:** On a trading day after Task 8 Step 6, run the orchestrator locally end-to-end without committing the post; all gates pass; show the draft to the user.
- [ ] **Step 4:** After the user has seen the draft: create cloud routines (19:00 KST `0 10 * * 1-5` UTC, retry 21:00 KST), sonnet-5, no connectors; record trigger ids in `scripts/japan/CLAUDE.md`. Push.
