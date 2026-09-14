#!/usr/bin/env python3
"""Publication gate for the reader's route back to the primary document.

Run from the repo clone, against the writer's output in the routine workspace:

  python3 scripts/check_sources.py --html morning_brief_2026-09-11.html --datadir .

Exit 0 = publishable. Exit 1 = violations printed, one per line; hand them back to
the writer subagent verbatim and re-run.

An absent, unreadable or stale index authorises nothing — it never switches the
gate off. The page is not *required* to link; a link it does print must point at a
document collected today, for the block it sits in. Yesterday's URL cannot
authorise today's citation, and a day when collection failed is the day an invented
link is most likely.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from us.source_gate import check  # noqa: E402


def _load(path):
    """-> book | None. Absent or unreadable both come back None — neither authorises."""
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except FileNotFoundError:
        return None
    except Exception as e:
        print(f'WARN: could not read {path}: {e} — treating it as empty',
              file=sys.stderr)
        return None


def _fresh(book, report_date, path):
    """-> book | None. A book from another session would authorise links we never
    fetched today, so it is dropped rather than trusted."""
    if book is None:
        return None
    if not report_date:
        # No trading day to compare against — we cannot tell today's collection
        # from last week's, so nothing here gets to authorise a citation.
        print(f'WARN: no report_date to date {path} against — treating it as empty',
              file=sys.stderr)
        return None
    if book.get('report_date') != report_date:
        print(f"WARN: {path} is for {book.get('report_date')}, not {report_date} — "
              f'treating it as empty', file=sys.stderr)
        return None
    return book


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

    market = _load(os.path.join(args.datadir, 'market_data.json')) or {}
    report_date = market.get('report_date')

    rel_path = os.path.join(args.datadir, 'releases', 'index.json')
    fed_path = os.path.join(args.datadir, 'fed', 'events.json')
    # Nothing readable and current -> the empty book, which authorises nothing.
    releases = _fresh(_load(rel_path), report_date, rel_path) or {'releases': []}
    fed = _fresh(_load(fed_path), report_date, fed_path) or {'events': []}

    violations = check(html, releases, fed)
    if violations:
        for x in violations:
            print(x)
        sys.exit(1)
    print('source gate: OK')


if __name__ == '__main__':
    main()
