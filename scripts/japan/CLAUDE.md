# Japan weekly — code rules

One post per week, on the day MOF posts Friday's JGB curve (next Tokyo business day — usually Monday; `routine_due.py japan_post_day`), answering one question: **can Japan keep normalising rates?** The chain is BOJ → JGB → yen and money flows → Japanese equities. Code computes every number; the writer only interprets (`.claude/agents/japan-report-writer.md`, routine `.claude/JAPAN_ORCHESTRATOR.md`).

## Modules

| File | Does |
|---|---|
| `scripts/common/weekly_sources.py` | Parsers + fetchers shared with the US weekly insight (MOF curve and flows, CFTC, yfinance, FRED, fed funds contracts) |
| `scripts/collect_weekly_data.py` | Snapshot `data/weekly_ext/<KEY>.json`. **No daily collection** — every source returns full history. **Runs only in Actions** (`collect-weekly-data.yml`; routines cannot reach these hosts) — routines check `scripts/ci/snapshot_ready.py` and dispatch |
| `core.py` | Core six, curve, flows, hedged proxy, positioning, equities, fixed A/B signals. Pure |
| `render.py` | Tables, body contract (`SECTIONS`, `<!--T:name-->`), assembly |
| `gate.py` | Publish gate; CLI `scripts/check_japan.py` |
| `news.py` + `scripts/fetch_japan_news.py` | 「이번 주 뉴스」: Yahoo!ファイナンス category lists (`__PRELOADED_STATE__`, paged) + BOJ + NLI → `japan/data/news/<date>.json`, summaries only. Actions `collect-japan-news.yml` |

## Invariants

- **Spreads subtract each leg's own latest value**, never the date intersection — a Japanese holiday week leaves no common date and the intersection prints a fake "0bp" (W39: 9/21-23). `leg_spread()` keeps both as-of dates.
- **US legs take the published close** from `data/weekly/<KEY>.json` when FRED lags (`with_published_close`).
- **MOF sign: net = acquisition − disposition, + is net buying.** Residents buying foreign bonds is an *outflow*; net selling is the repatriation side. The gate checks 순매수/순매도 against the weekly value, or the 4-week sum when the sentence says 4주.
- **Hedged UST is an approximation** (US 3M − JGB 1Y; no forward points or basis). `approx: True`; any paragraph mentioning 헤지 must say 근사.
- **Never `ZQ=F`** — it rolled silently from Sep to Nov on 2026-09-25. Name contract months.
- **Failed sources stay in `fetch_status`** and block publishing; a failed fetch is not a quiet week.
- **Signals are fixed in code** (`SIGNALS`) — the writer must not pick thresholds.
- Tokyo CPI dates are absent from `japan/data/calendar.json` on purpose: not confirmed from the Statistics Bureau. Add only dates checked at the source.
- **News: only `digest: true` rows of `<KEY>.news.json` may be published** (Japan collector, week range by the article's JST time). US/KR `region=japan` rows are BOJ evidence only — old weeks (W40/W41) have no digest rows and stay exempt. `<KEY>.news.json` must stay self-contained: the review runner re-checks from it alone.
- **A summary is publishable only when `us.news_summary.summary_problem()` is None** (no kana/kanji, one paragraph, no self-correction). Collector, `digest_rows`, `news_gate` and `check_news`/`number_sources` share it — never re-implement it.
- **Collect finished JST days**: each run fills every unfrozen weekday of the last 5; a day is frozen only when summarised **and** `complete` (every list read). Media allowlist `MEDIA_RANK`; paid pages (`_VipPurchase`) have no body.
- The `news` section is optional in `ORDER` but always checked for order, uniqueness and title; `data-news` blocks outside it are blocked, ≤3 per category, no `same_event` pair. Flow-direction checks skip it.

When changing this: read `docs/superpowers/specs/2026-09-26-weekly-insight-and-japan-design.md` before touching `core.py` or `gate.py`, and `docs/superpowers/specs/2026-10-18-japan-news-design.md` before touching `news.py`, `fetch_japan_news.py` or the news part of `gate.py`.

## Japan daily close brief (2026-10-27)

Every Tokyo trading day, `/japan/daily/<session>.html`, routine `.claude/JAPAN_DAILY_ORCHESTRATOR.md` (wakes 18:20 KST and starts once the KR brief is on main — `scripts/ci/wait_for_kr.sh`, ≤72 min; retry 21:00; **no backfill**), writer `.claude/agents/japan-daily-writer.md`. Separate from the weekly — never edit weekly files, `calendar.json` meanings, `news.py` classification or the weekly news freeze for it.

| File | Does |
|---|---|
| `collect_japan_daily.py` + `collect-japan-daily.yml` (`30 16 * * 1-5` Asia/Tokyo) | Candidate snapshot `japan/data/daily/candidate/<s>.json`; refuses a published session |
| `fetch_japan_news.py --daily-session` + `japan/news_daily.py` | `japan/data/news/daily/<s>.json`, economic categories only, 16:30 JST cut before the cap |
| `common/region_filter.py` (+ `region_labels.py`, `jev_client.py`) | Domestic/foreign filter on the regex-kept candidates, before the cap: **drop only** rows Jev (`jev-1.14.0`) calls `foreign` at conf ≥ 0.9; never recovers, keeps `foreign_impact`, never drops a story already in that day's file. Any failure → that row stays on the regex result; a crash rolls back to regex. Daemon thread joined at 60 s. Audit in the payload's `region_filter` (gate/review read `items` only). Japan label text is frozen — shadow fingerprints. When changing this: read `docs/superpowers/specs/2026-10-28-jev-region-filter.md` before touching `common/region_filter.py` |
| `japan/daily_{prices,rates,macro,movers,calendar}.py` | Pure logic; calendar overlay `japan/data/calendar_daily.json` (release vs meeting rows) |
| `japan/daily_render.py` + `build_japan_daily.py` | Section order from `order(event_day)`, tables, BOJ credit footer; `diag`/`assemble` |
| `japan/daily_gate.py` + `check_japan_daily.py`, `japan/daily_news_gate.py` via `check_news.py --market jp-daily` | Publish gates |
| `publish_japan_daily.py` | Candidate → published snapshot, history `japan/data/history/jp_daily.jsonl`, `japan/daily.json`, sitemap |
| `japan/region_shadow.py` + `japan_region_shadow.py` + `region-shadow.yml` | **Shadow only** (2026-10-27): regex vs Haiku vs Jev domestic/foreign labels on cut-in headlines. Input `japan/data/news/region_shadow/input/` is written only by `collect_daily` (fail-open), results `…/result/` only by the shadow workflow. Nothing in selection, gates or review reads them; `report` prints agreement, not accuracy |

- **Nikkei close = official Nikkei CSV row for the session** matched to `fast_info.lastPrice` within 0.01% (`complete`); never commit the CSV. ETFs/stocks only when the last 5-minute bar is on the session. **Never `previousClose`** — a change needs a denominator dated exactly `prev_session`.
- FX = 5-minute bar ending 16:30 JST (weekly uses 16:00 ET — values differ). JGB = Naver benchmark close for the session (`JP{2,5,10,30}YT=RR`, all-or-nothing, adopted only when fetched ≥17:45 JST, prev row must be exactly `prev_session`, cross-checked against MOF ≤15bp); else the whole block falls back to the MOF row for `prev_session`. **Never compute bp across the two sources** (definitions differ by up to 7.5bp). Per-row `source`; caption/footer follow it. Early candidates carry `jgb_recollect: true`. When changing this: read `docs/superpowers/specs/2026-10-29-japan-daily-naver-jgb.md` before touching `japan/daily_rates.py`. Call rate = BOJ API latest observation (≤3 trading days old).
- Macro `released` only when the calendar row's expected `period` is present in the BOJ series; otherwise `pending`. Holidays/weekends return `SKIP` (no backfill). No consensus anywhere.
- Core values in prose carry `<span data-ref="field.path">`; values with a period ≠ session need that date in the paragraph. No weekly signal vocabulary, no 「지수 기여」.
- BOJ API: no key, ≤10 calls per run, series codes cached 7 days (`japan/data/daily/boj_series.json`); the credit line is mandatory.
- Review runner: `japan/daily` = (`jp`, `daily`) in `review/kinds.py` — codex drafts, manual review-gate correction (not in `DAILY`).

When changing this: read `docs/superpowers/specs/2026-10-27-japan-daily-design.md` (§13 overrides) before touching `scripts/japan/daily_*.py`, `collect_japan_daily.py` or `publish_japan_daily.py`.
