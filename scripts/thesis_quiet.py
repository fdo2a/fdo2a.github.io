#!/usr/bin/env python3
"""Thesis routine STEP 0.5 — can today be proven quiet from committed files?

    python3 scripts/thesis_quiet.py [--data thesis/data] [--today YYYY-MM-DD]

Prints `THESIS_QUIET` and exits 0 when every signal is empty; prints `THESIS_CHECK`
with the reasons and exits 10 otherwise. Any other exit (a crash) means "not proven
quiet" too — the routine then runs its normal research.

Logic: scripts/thesis/quiet.py.
"""
import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from thesis import history as H           # noqa: E402
from thesis import quiet as Q             # noqa: E402
from thesis import triggers as T          # noqa: E402


def _load(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def numeric_triggers(watch, rows):
    """Exactly STEP 1 of THESIS_ORCHESTRATOR.md — keep the two in step."""
    deep = H.has_depth(rows, T.MIN_HISTORY_ROWS)
    back = H.days_ago(watch['as_of'], T.LOOKBACK_DAYS)
    out = {}
    for sym, row in watch['tickers'].items():
        past = {k: H.value_on(rows, back, sym, k)
                for k in ('eps_fy1', 'eps_fy1_low', 'eps_fy1_high', 'price')}
        past = past if any(v is not None for v in past.values()) else None
        prev = H.previous(rows, watch['as_of'], sym)
        prior = T.prior_metrics(rows, sym, before=watch['as_of'])
        out[sym] = T.evaluate(row, past, row.get('fair_value'), has_depth=deep,
                              prev=prev, prior=prior)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', default='thesis/data')
    ap.add_argument('--today', default=None)
    args = ap.parse_args(argv)
    data = Path(args.data)
    today = (date.fromisoformat(args.today) if args.today
             else datetime.now(Q.KST).date())
    watch = _load(data / 'watch.json')
    triggers = (numeric_triggers(watch, H.load(data / 'history.jsonl'))
                if isinstance(watch, dict) and watch.get('tickers') else {})
    quiet, reasons = Q.decide(today, watch, triggers, _load(data / 'disclosures.json'),
                              _load(data / 'events.json'))
    if quiet:
        print(f'THESIS_QUIET {today} — 수치 트리거·확정 공시·뉴스룸 신규 항목·실적 창 모두 비었다')
        return 0
    print(f'THESIS_CHECK {today}')
    for reason in reasons:
        print(f'  - {reason}')
    return 10


if __name__ == '__main__':
    sys.exit(main())
