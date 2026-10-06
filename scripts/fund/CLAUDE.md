# Fund desk — code rules

The US and KR dailies are reference material for the PM of a tactical global-equity fund run on **trend units** (3-month themes, each a basket screened from a reference index, with target / loss-cut / time stop). This package computes the price-side inputs that PM uses; writers only interpret. Mandate and stage map: `.claude/DESK_REPORT.md` 「The fund this report serves」.

## Modules

| File | Does |
|---|---|
| `universe.py` | 28 reference ETFs: benchmark / risk_on / risk_off (「방어 스타일」) / region. A theme not listed does not show — change with a reason in the spec |
| `metrics.py` | Returns, 12-1 momentum, vol, historical 1-day VaR (`max(0, -q)`, linear quantile), beta, SMA, drawdown. Pure |
| `board.py` | Per-ETF rows; rank on the set measurable today **and** 5 sessions ago; `rel_3m_chg_pp`; continuity rules |
| `regime.py` | Price-only 4-state regime with 3-session hysteresis, no state file |
| `liquidity.py` | WALCL − WDTGAL − RRPONTSYD (Wednesday), NFCI; static unit contract; 4-week change = exactly 28 days back, else none |
| `calendar.py` | US sessions from the holiday file; an independent calendar so a day every series lost still shows as a gap |
| `core.py` | `data/fund_board.json` contract (`status` ok/partial/unavailable, `missing`, `source_dates`) |
| `render.py` / `kr_view.py` | Deterministic blocks `data-fund-board` / `data-fund-kr`; KR view built from the KR collector's in-memory objects |
| `kr_links.py` | Static map: KR industries / stocks / Asian indices → US reference index. Not a lead-lag model |
| `gate.py` | CLI `scripts/check_fund.py --market us|kr`; registered in ORCHESTRATOR, KR_ORCHESTRATOR, `review/corrector.py`, `review/style_pass.py` |

## Invariants

- **JSON always, HTML only when renderable** (`publish.write`); an unavailable day deletes yesterday's HTML. Section owed iff `status` ∈ {ok, partial} and `report_date` == post date; otherwise it must be absent.
- **The block is byte-compared with a fresh render.** Nothing downstream may rewrite it: `colorize` skips the two section titles, `prose_swap` skips the blocks, block lines are `<div>` not `<p>` (readability counts `<p>` as prose).
- **No `macro_eval` on the board** — it is written after collection, so it would be yesterday's call.
- **Session calendar** = NYSE weekdays minus `data/market_holidays.json` (`calendar.py`, only inside its `valid_from`..`valid_through`; else a strict-majority vote of the 28 fund ETFs, `board.sessions`). It anchors every reading, the regime included: returns are close-on-anchor / close-on-anchor, a missing anchor price blanks the value; risk windows, SMAs and the 52-week high need a price on every session of the window; a session SPY lacks is a `None` raw regime call (breaks the 3-run). Series with unsorted or duplicate dates are rejected. A row whose last session ≠ the calendar's is stale and blank.
- **Regime `since`** is exact only after an observed transition; the opening state of the 260-call window prints 「최소 N거래일」.
- **VaR is a 60-session sample, 1-day holding, ETF-level** — never a unit's risk, never a target / loss-cut width.
- `check_fund.py` failures are never excused because the original post also failed (`NEVER_TOLERATE`): the corrector collects them at baseline and hands them over as must-fix; the final replay blocks. Posts before `gate.EFFECTIVE` are not checked; the filename date wins over `--date`.
- Non-finite inputs are cleaned **before** availability and signals are judged (a NaN must never read as a direction); signals use raw changes, rounding is display-only.
- Gate reads the parsed DOM the way a browser would where hiding is concerned (entities decoded, comments dropped, self-closed non-void tags stay open, a block start tag closes an open `<p>`, duplicate attributes rejected in and above the section): `data-fund` only on `<p>` in the section, judged on **visible** text; hidden = `hidden`, inline display:none / visibility:hidden, `<details>` without `open`, or any raw-text / non-display container (`textarea`, `select`, `noscript`, `template` …) on any ancestor. A block mismatch is fixed only by replacing the whole block with `check_fund.py --print-block`. Signed figures must match signed values; % and %p are separate sets. **Not covered**: CSS-class or stylesheet hiding, causality, idea quality.

When changing this: read `docs/superpowers/specs/2026-10-06-fund-desk-design.md` before touching `regime.py`, `board.py` or `gate.py`.
