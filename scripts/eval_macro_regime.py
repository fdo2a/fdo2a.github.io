#!/usr/bin/env python3
"""Judge yesterday's macro book against today's axis scores -> data/macro_eval.json.

Runs in the GitHub Actions collector job, right after collect_market_data.py, so the
cloud routine reads a decided regime instead of re-deriving the cycle from whichever
numbers happen to be on the table that morning.

  python scripts/eval_macro_regime.py --datadir data
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from us.macro import evaluate  # noqa: E402


def load(path):
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except FileNotFoundError:
        return None
    except Exception as e:
        print(f'WARN: could not read {path}: {e}', file=sys.stderr)
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--datadir', default='data')
    args = ap.parse_args()

    market = load(os.path.join(args.datadir, 'market_data.json'))
    if not market or not market.get('report_date'):
        print('FATAL: market_data.json missing or has no report_date', file=sys.stderr)
        sys.exit(1)
    report_date = market['report_date']

    macro = load(os.path.join(args.datadir, 'macro.json'))
    metrics = load(os.path.join(args.datadir, 'macro_metrics.json')) or {}
    # Scores keyed to another session would judge today's regime against yesterday's
    # economy. Drop them: with no scores nothing is implied, so the book freezes.
    got = metrics.get('report_date')
    if metrics and got is not None and got != report_date:
        print(f'WARN: macro_metrics.json report_date={got}, not {report_date} — ignoring',
              file=sys.stderr)
        metrics = {}

    try:
        ev = evaluate(macro, metrics, report_date)
    except ValueError as e:
        print(f'FATAL: macro.json is invalid: {e}', file=sys.stderr)
        sys.exit(1)

    with open(os.path.join(args.datadir, 'macro_eval.json'), 'w', encoding='utf-8') as fh:
        json.dump(ev, fh, indent=2, ensure_ascii=False)

    if ev['bootstrap']:
        print('no prior macro book — bootstrap mode, writer sets the opening regime')
        return

    r = ev['regime']
    print(f"regime {r['name']} (성장 {r['growth_label']} / 인플레 {r['inflation_label']}) "
          f"· {r['days_held']}bd" + (' (STALE)' if ev['stale'] else ''))
    s = ev['scores']
    print(f"  scores: growth {s.get('growth_score')} / inflation {s.get('inflation_score')}"
          f" -> implied {ev['implied'].get('name')}")
    if ev['new_releases']:
        print(f"  new releases ({len(ev['new_releases'])}): "
              + ', '.join(ev['new_releases']))
    else:
        print('  no new releases — regime and policy path are frozen')
    allowed = ' / '.join(f"[{g},{i}]" for g, i in ev['allowed_regimes'])
    block = f" blocked:{ev['regime_block']}" if ev['regime_block'] else ''
    print(f'  allowed regimes: {allowed}{block}')
    for key, row in ev['transmission'].items():
        print(f"    {key:9s} {row['label']} · {row['days_held']}bd "
              f"· allowed {row['allowed_directions']}")


if __name__ == '__main__':
    main()
