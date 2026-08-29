#!/usr/bin/env python3
"""Judge yesterday's stance triggers against today's metrics -> data/stance_eval.json.

Runs in the GitHub Actions collector job, right after collect_market_data.py, so the
cloud routine reads a decided answer instead of re-deriving positioning from that
session's price action.

  python scripts/eval_stance_triggers.py --datadir data
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from us.stance import evaluate  # noqa: E402


def load(path):
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except FileNotFoundError:
        return None
    except Exception as e:
        print(f'WARN: could not read {path}: {e}', file=sys.stderr)
        return None


def fresh_metrics(metrics_file, report_date):
    """The metrics, but only if they can prove they describe today's session.

    Metrics keyed to another session — or built from a price history that stopped
    short of it — would silently judge today's triggers against stale prices. So
    would metrics that cannot say when their history ended at all: a failed download
    leaves `as_of` null, and treating unproven as fresh is how partial prices get to
    move a grade. Everything doubtful is dropped, and every trigger then falls
    through to UNKNOWN, which freezes the grade rather than inventing a move.
    """
    metrics = (metrics_file or {}).get('metrics') or {}
    if not metrics:
        return {}
    for field in ('report_date', 'as_of'):
        got = (metrics_file or {}).get(field)
        if got != report_date:
            print(f'WARN: stance_metrics.json {field}={got}, not {report_date} — ignoring',
                  file=sys.stderr)
            return {}
    return metrics


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--datadir', default='data')
    args = ap.parse_args()

    market = load(os.path.join(args.datadir, 'market_data.json'))
    if not market or not market.get('report_date'):
        print('FATAL: market_data.json missing or has no report_date', file=sys.stderr)
        sys.exit(1)
    report_date = market['report_date']

    stance = load(os.path.join(args.datadir, 'stance.json'))
    metrics_file = load(os.path.join(args.datadir, 'stance_metrics.json')) or {}
    metrics = fresh_metrics(metrics_file, report_date)

    try:
        ev = evaluate(stance, metrics, report_date)
    except ValueError as e:
        print(f'FATAL: stance.json is invalid: {e}', file=sys.stderr)
        sys.exit(1)

    out = os.path.join(args.datadir, 'stance_eval.json')
    with open(out, 'w', encoding='utf-8') as fh:
        json.dump(ev, fh, indent=2, ensure_ascii=False)

    if ev['bootstrap']:
        print('no prior stance — bootstrap mode, writer sets the opening book')
        return
    print(f"stance from {ev['stance_date']}" + (' (STALE)' if ev['stale'] else ''))
    for key, a in ev['assets'].items():
        moves = '/'.join(str(g) for g in a['allowed_grades'])
        block = f" blocked:{a['increase_block']}" if a['increase_block'] else ''
        print(f"  {key:9s} {a['grade']:+d} {a['label']} · {a['days_held']}bd "
              f"· allowed {moves}{block}")
        for t in a['increase'] + a['decrease']:
            if t['status'] in ('MET', 'MANUAL'):
                print(f"      {t['status']}: {t.get('desc') or t.get('metric')}"
                      + (f" (actual {t['actual']})" if t.get('actual') is not None else ''))


if __name__ == '__main__':
    main()
