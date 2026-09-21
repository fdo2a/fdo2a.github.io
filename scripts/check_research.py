#!/usr/bin/env python3
"""Render/check ledger-derived research output or compare two unpublished drafts."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common.research_gate import check_daily, checked_summary_body, compare_drafts, render_summary
from common.research_ledger import read_records, summarize


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    commands = ap.add_subparsers(dest='command', required=True)
    for name in ('render', 'check'):
        p = commands.add_parser(name)
        p.add_argument('--root', type=Path, default=Path('research'))
        p.add_argument('--market', choices=('us', 'kr'), required=True)
        p.add_argument('--start')
        p.add_argument('--end')
        p.add_argument('--as-of')
        if name == 'render':
            p.add_argument('--out', type=Path, required=True)
        else:
            p.add_argument('--span', choices=('daily', 'weekly', 'monthly'), required=True)
            p.add_argument('--html', type=Path, required=True)
            p.add_argument('--date')
            p.add_argument('--cycle')
    p = commands.add_parser('compare')
    p.add_argument('--before', type=Path, required=True)
    p.add_argument('--after', type=Path, required=True)
    p.add_argument('--out', type=Path)
    args = ap.parse_args(argv)
    try:
        if args.command == 'compare':
            result = compare_drafts(args.before.read_text(), args.after.read_text())
            text = json.dumps(result, ensure_ascii=False, indent=2)
            if args.out:
                args.out.write_text(text + '\n')
            print(text)
            return 0
        if args.command == 'check' and args.span == 'daily':
            if not args.date or not args.cycle:
                ap.error('daily check requires --date and --cycle')
            errors = check_daily(args.html.read_text(), read_records(args.root),
                                 args.cycle, args.market, args.date)
            if errors:
                print('\n'.join(errors))
                return 1
        else:
            if not (args.start and args.end and args.as_of):
                ap.error('period render/check requires --start, --end and --as-of')
            summary = summarize(args.root, args.market, args.start, args.end, args.as_of)
            if args.command == 'render':
                args.out.write_text(render_summary(summary) + '\n')
            else:
                checked_summary_body(args.html.read_text(), summary)
        print('RESEARCH_OK')
        return 0
    except (OSError, ValueError, KeyError, TypeError) as e:
        print(f'RESEARCH_ERROR: {e}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
