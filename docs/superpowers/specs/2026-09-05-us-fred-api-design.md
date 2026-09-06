# US brief — FRED access via the official API (2026-09-05)

> Moved verbatim out of `scripts/us/CLAUDE.md` on 2026-09-05 so the leaf keeps only the
> active contract. Nothing here was rewritten; the leaf now carries a summary plus a
> "When changing this" pointer back to this file.

## Why

User instruction: 「fred api를 발급받았는데 이걸 활용하도록 설정해」.

Until then the collector used a single `fredgraph.csv?id=` endpoint — the output of a
graphing service, not a documented API. This repo had already been burned twice by hosts
that quietly turned to 403: Yahoo (2026-07-15) and BLS/DOL (2026-08-18). Both times the
fix was the same shape — move to a supported interface before it breaks, not after.

## The design, as written in the leaf

**FRED access = official API** (2026-09-05, user: "I got a FRED API key, set it up to use that"): it used to be a single `fredgraph.csv?id=` — **output of a graphing service**, not a documented API, and this repo has already been burned twice by hosts quietly turning to 403 (Yahoo 2026-07-15, BLS/DOL 2026-08-18). `FredClient` in `scripts/us/fred.py` now picks the transport. **Only the pipe changed**: the `fred_series()` contract is unchanged (oldest→newest `(date, float)`, missing values dropped, **full history**), and the keyless CSV path is empirically identical to the old implementation (DGS10 16,153 rows, CPIAUCSL 954, PAYEMS 1,052, T5YIFR 5,923 — all match). History is not truncated because `macro_metrics` computes 60-point momentum and 12-point YoY from it. Four disciplines: ① **the transport is decided once by a pre-flight probe before any production call** (`DGS10&limit=1`) — naming one run when the first half used the API and the second used CSV makes the telemetry lie; ② **do not read every 400 as "bad key"** — a wrong `series_id` also returns 400, so downgrade only when the error body's `error_message` names `api_key`; 429 and 5xx do not switch the transport and **rescue just that series via CSV** (losing a whole series silently changes the macro axis composition — when `retry()` returns `None`, `collect_econ()` simply drops it); ③ **`HTTPError.url` carries the key verbatim** (measured; `str(e)` does not). `raise … from None` is not enough — raising *inside* the except block hangs the original on `__context__`, so build the exception and raise it *outside* the block. `scrub()` wipes the query pattern, the constructor key, and the env var (the ECOS precedent); ④ **never rely on defaults** — send `sort_order`, `observation_start`/`end`, `units`, `output_type`, and `limit` explicitly, and reject truncation (`count > limit`) or non-ascending order. The key is repo secret `FRED_API_KEY` (**step-level** env in the workflow, never job-wide). With no key or a rejected key it falls back to CSV so **publishing never stops**; the `fred` field in `market_data.json` plus a "FRED key health" step *after* the commit flag a dead key. If you touch the transport, run `python3 scripts/collect_market_data.py --fred-check` — it pulls all 35 production series down both paths and compares the **entire date→value map** (the last 30 points cannot validate 60-point momentum). Logic: `scripts/us/fred.py` (TDD 31 tests); the design and the 12 codex findings are in the root `plan.md`.

## Related files

- Transport: `scripts/us/fred.py` (`FredClient`), TDD 31 tests
- Caller: `scripts/collect_market_data.py` (`collect_econ()`, `--fred-check`)
- Secret: repo secret `FRED_API_KEY`, injected as **step-level** env in
  `.github/workflows/collect-market-data.yml`
- The 12 codex review findings and how each was resolved: root `plan.md`


## 왜 2Y 만 FRED 인가 (2026-07-28 실측, 2026-09-06 잎사귀에서 이관)

5Y·10Y·30Y 는 Yahoo 현물 지수(`^FVX`·`^TNX`·`^TYX`)라 **주식 종가와 같은 날**이지만
2년물만 T-1 인 FRED `DGS2` 를 쓴다. 대안을 둘 다 확인하고 버렸다.

- `^UST2Y` 는 **존재하지 않는다.**
- `2YY=F` 는 선물이라 **하루 늦게 들어오고**, `DGS2` 와 **20bp 넘게 벌어진다.**

그래서 만기별로 as-of 날짜가 다르고, 그 사실을 숨기지 않는 것이 계약이다 — 표의 행마다
`source` 와 `date`, 커브 차트의 `2Y*` 와 각주, 캡션까지. 2s10s 는 두 다리의 날짜가 달라
`spread_2s10s_bp`(발행값)와 `spread_2s10s_fred_bp`(같은 날 FRED)를 **둘 다** 인쇄하고,
한 날짜로 커브를 논할 때는 `spread_5s30s_bp`(같은 날 Yahoo)를 쓴다.
