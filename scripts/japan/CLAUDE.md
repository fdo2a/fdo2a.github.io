# Japan weekly — code rules

One post per week (Sunday), answering one question: **can Japan keep normalising rates?** The chain is BOJ → JGB → yen and money flows → Japanese equities. Code computes every number; the writer only interprets (`.claude/agents/japan-report-writer.md`, routine `.claude/JAPAN_ORCHESTRATOR.md`).

## Modules

| File | Does |
|---|---|
| `scripts/common/weekly_sources.py` | Parsers + fetchers shared with the US weekly insight (MOF curve and flows, CFTC, yfinance, FRED, fed funds contracts) |
| `scripts/collect_weekly_data.py` | Snapshot `data/weekly_ext/<KEY>.json`. **No daily collection** — every source returns full history |
| `core.py` | Core six, curve, flows, hedged proxy, positioning, equities, fixed A/B signals. Pure |
| `render.py` | Tables, body contract (`SECTIONS`, `<!--T:name-->`), assembly |
| `gate.py` | Publish gate; CLI `scripts/check_japan.py` |

## Invariants

- **Spreads subtract each leg's own latest value**, never the date intersection — a Japanese holiday week leaves no common date and the intersection prints a fake "0bp" (W39: 9/21-23). `leg_spread()` keeps both as-of dates.
- **US legs take the published close** from `data/weekly/<KEY>.json` when FRED lags (`with_published_close`).
- **MOF sign: net = acquisition − disposition, + is net buying.** Residents buying foreign bonds is an *outflow*; net selling is the repatriation side. The gate checks 순매수/순매도 against the weekly value, or the 4-week sum when the sentence says 4주.
- **Hedged UST is an approximation** (US 3M − JGB 1Y; no forward points or basis). `approx: True`; any paragraph mentioning 헤지 must say 근사.
- **Never `ZQ=F`** — it rolled silently from Sep to Nov on 2026-09-25. Name contract months.
- **Failed sources stay in `fetch_status`** and block publishing; a failed fetch is not a quiet week.
- **Signals are fixed in code** (`SIGNALS`) — the writer must not pick thresholds.
- Tokyo CPI dates are absent from `japan/data/calendar.json` on purpose: not confirmed from the Statistics Bureau. Add only dates checked at the source.

When changing this: read `docs/superpowers/specs/2026-09-26-weekly-insight-and-japan-design.md` before touching `core.py` or `gate.py`.
