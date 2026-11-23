#!/usr/bin/env python3
"""Thesis routine STEP 0.5 — can today be proven quiet from committed files?

    python3 scripts/thesis_quiet.py [--data thesis/data] [--today YYYY-MM-DD]

Prints `THESIS_QUIET` and exits 0 when every signal is empty; prints `THESIS_CHECK`
with the reasons and exits 10 otherwise. Any other exit (a crash) means "not proven
quiet" too — the routine then runs its normal research.

Logic: scripts/thesis/quiet.py; numeric triggers: scripts/thesis/evidence.py.
"""
import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from thesis import evidence as E          # noqa: E402
from thesis import quiet as Q             # noqa: E402


def _load(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', default='thesis/data')
    ap.add_argument('--today', default=None)
    args = ap.parse_args(argv)
    data = Path(args.data)
    today = (date.fromisoformat(args.today) if args.today
             else datetime.now(Q.KST).date())
    watch = _load(data / 'watch.json')
    path = data / 'history.jsonl'
    rows, bad = E.parse_history(path.read_text(encoding='utf-8') if path.exists() else None)
    # Same function as the gate and STEP 1. Deferred (stale watch, a number that cannot be
    # read) lists no numeric trigger and is never quiet: "could not judge" is not "nothing
    # fired", and THESIS_QUIET ends the run before STEP 1 would say so.
    hits, deferred = (None, f'{bad} — 수치 판정 보류') if bad else \
        E.today_triggers(watch, rows, today.isoformat())
    quiet, reasons = Q.decide(today, watch, hits or {}, _load(data / 'disclosures.json'),
                              _load(data / 'events.json'))
    if deferred:
        quiet = False
        if deferred not in reasons:
            reasons.append(deferred)
    if quiet:
        print(f'THESIS_QUIET {today} — 수치 트리거·확정 공시·뉴스룸 신규 항목·실적 창 모두 비었다')
        return 0
    print(f'THESIS_CHECK {today}')
    for reason in reasons:
        print(f'  - {reason}')
    return 10


if __name__ == '__main__':
    sys.exit(main())
