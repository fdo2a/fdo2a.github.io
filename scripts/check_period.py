#!/usr/bin/env python3
"""Publication gate for the weekly / monthly recaps.

  python3 scripts/check_period.py --html weekly_2026-W34.html \
      --agg data/weekly/2026-W34.json --recap recap_source.json \
      --scorecard data/scorecard.json --span weekly

Exit 0 = publishable. Exit 1 = violations printed, one per line; hand them back to the
writer subagent verbatim and re-run.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from us.period_gate import check  # noqa: E402


def load(path):
    if not path or not os.path.exists(path):
        return None
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--html', required=True)
    ap.add_argument('--agg', required=True)
    ap.add_argument('--recap', required=True)
    ap.add_argument('--scorecard', default=None)
    ap.add_argument('--span', choices=('weekly', 'monthly'), required=True)
    ap.add_argument('--research-root', help='Verified append-only research directory')
    ap.add_argument('--research-as-of', help='Timezone-aware frozen review cutoff')
    ap.add_argument('--market', choices=('us', 'kr'))
    ap.add_argument('--insight', help='US 주간 인사이트 진단 (data/weekly/<KEY>.insight.json)')
    args = ap.parse_args()

    try:
        with open(args.html, encoding='utf-8') as fh:
            html = fh.read()
        agg = load(args.agg)
        recap = load(args.recap)
    except OSError as e:
        print(f'FATAL: {e}', file=sys.stderr)
        sys.exit(2)
    if agg is None or recap is None:
        print('FATAL: 집계 파일 또는 발행본 회수 파일이 없다', file=sys.stderr)
        sys.exit(2)

    research_summary = None
    if args.research_root or args.research_as_of:
        if not (args.research_root and args.research_as_of and args.market):
            ap.error('--research-root, --research-as-of and --market are required together')
        from pathlib import Path
        from common.research_ledger import summarize
        try:
            research_summary = summarize(Path(args.research_root), args.market,
                                         agg['start_date'], agg['end_date'], args.research_as_of)
        except (OSError, ValueError, KeyError) as e:
            print(f'FATAL: research ledger: {e}', file=sys.stderr)
            return 2
    insight = load(args.insight) if args.insight else None
    if args.insight and insight is None:
        print(f'FATAL: 진단 파일이 없다: {args.insight}', file=sys.stderr)
        return 2
    violations = check(html, agg, load(args.scorecard), recap, args.span,
                       research_summary=research_summary, insight=insight)
    if not violations:
        print('기간 리포트 게이트 통과')
        return
    print(f'기간 리포트 게이트 실패 — {len(violations)}건')
    for x in violations:
        print(f'  - {x}')
    sys.exit(1)


if __name__ == '__main__':
    sys.exit(main())
