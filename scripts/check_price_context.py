#!/usr/bin/env python3
"""Publication gate for the price-context readings (§3·§5·§6·§7 공통).

Run from the repo clone, against the writer's output in the routine workspace:

  python scripts/check_price_context.py --html morning_brief_2026-08-28.html --datadir .

Exit 0 = publishable. Exit 1 = violations printed, one per line; hand them back to
the writer subagent verbatim and re-run.

Non-core: if market_data.json carries no price_context block (an older dataset, or a
collector run where that step failed) there is nothing to enforce and the gate passes.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from us.price_gate import check  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--html', required=True)
    ap.add_argument('--datadir', default='data')
    args = ap.parse_args()

    try:
        with open(args.html, encoding='utf-8') as fh:
            html = fh.read()
    except OSError as e:
        print(f'FATAL: cannot read {args.html}: {e}', file=sys.stderr)
        sys.exit(2)

    md_path = os.path.join(args.datadir, 'market_data.json')
    try:
        with open(md_path, encoding='utf-8') as fh:
            market = json.load(fh)
        price_context = market.get('price_context')
        report_date = market.get('report_date')
    except FileNotFoundError:
        print(f'no {md_path} — nothing to check')
        return
    except Exception as e:
        print(f'WARN: could not read {md_path}: {e}', file=sys.stderr)
        return

    if not price_context:
        print('no price_context block in market_data.json — nothing to check')
        return

    scorecard = None
    sc_path = os.path.join(args.datadir, 'scorecard.json')
    if os.path.exists(sc_path):
        try:
            with open(sc_path, encoding='utf-8') as fh:
                scorecard = json.load(fh)
        except Exception as e:
            print(f'WARN: could not read {sc_path}: {e}', file=sys.stderr)
    # A scorecard left over from another session would let a stale `sufficient: true`
    # authorise today's claim. Treat it as absent, which the gate fails closed on.
    if scorecard is not None and scorecard.get('report_date') != report_date:
        print(f"WARN: scorecard.json is for {scorecard.get('report_date')}, "
              f'not {report_date} — ignoring', file=sys.stderr)
        scorecard = None

    violations = check(html, price_context, scorecard=scorecard)
    if violations:
        for x in violations:
            print(x)
        sys.exit(1)
    print('price context gate: OK')


if __name__ == '__main__':
    main()
