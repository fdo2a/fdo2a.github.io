#!/usr/bin/env python3
"""Publication gate for the reader's route back to the primary document.

Run from the repo clone, against the writer's output in the routine workspace:

  python3 scripts/check_sources.py --html morning_brief_2026-09-11.html --datadir .

Exit 0 = publishable. Exit 1 = violations printed, one per line; hand them back to
the writer subagent verbatim and re-run.

Exit 2 = incomplete (2026-11-17) when publishing now: market_data.json without a
report_date, an unreadable book, or a releases index / Fed book that is absent, stale or
not complete — re-collect. With --legacy-releases (re-checking a past post against its own
commit's data) an absent, stale or pre-contract book still reads as empty, as before:
it authorises nothing and never switches the gate off. The page is not *required* to link; a link it does print must point at a
document collected today, for the block it sits in. Yesterday's URL cannot
authorise today's citation, and a day when collection failed is the day an invented
link is most likely.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from verification.inputs import enforcing  # noqa: E402 — 1a 를 켰는가(꺼져 있으면 1a 전 판정 그대로)
from us.source_gate import check  # noqa: E402


def _load(path):
    """-> book | None. Absent or unreadable both come back None — neither authorises."""
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except FileNotFoundError:
        return None
    except Exception as e:
        if enforcing():
            print(f'FATAL: could not read {path}: {e} — 미완료', file=sys.stderr)
            sys.exit(2)
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


def _releases_contract(book, legacy, path):
    """-> book | None. Since 2026-11-06 `fetch_releases.py` stamps the index with the run
    that wrote it and `status`; only a finished run's index authorises a link. An index
    without `status` predates the contract — accepted only when re-checking a past
    post's own commit (`--legacy-releases`), never for a post being published now."""
    if book is None:
        return None
    status = book.get('status')
    if status is None:
        if legacy:
            return book
        print(f'WARN: {path} has no status (pre-2026-11-06 schema) — treating it as empty',
              file=sys.stderr)
        return None
    if status != 'complete':
        print(f'WARN: {path} status is {status!r}, not complete — treating it as empty',
              file=sys.stderr)
        return None
    return book


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--html', required=True)
    ap.add_argument('--datadir', default='data')
    ap.add_argument('--legacy-releases', action='store_true',
                    help="re-checking a past post against its own commit's data: accept a "
                         'releases index written before the 2026-11-06 contract')
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
    from verification.inputs import legacy_recheck
    # --legacy-releases 의 옛 판정은 1a 적용일 전 글에만 — 새 글의 미완료를 재검사에서 통과로 두지 않는다(구현 검토 #9)
    # 1a 를 켜기 전에는 --legacy-releases 를 받은 그대로 쓴다(1a 전과 같다)
    if enforcing():
        args.legacy_releases = legacy_recheck(args.legacy_releases, args.html)
    if enforcing() and not args.legacy_releases:
        rel, fed_book = _load(rel_path), _load(fed_path)
        why = ('market_data.json 기준일이 없다' if not report_date else
               'releases/index.json 이 없다' if rel is None else
               'fed/events.json 이 없다' if fed_book is None else
               f"releases/index.json 이 {rel.get('report_date')} 것이다" if rel.get('report_date') != report_date else
               f"fed/events.json 이 {fed_book.get('report_date')} 것이다"
               if fed_book.get('report_date') != report_date else
               f"releases/index.json status={rel.get('status')!r}" if rel.get('status') != 'complete' else None)
        if why:
            print(f'FATAL: {why} — 미완료, 수집을 다시 돌린다', file=sys.stderr)
            sys.exit(2)
    # Nothing readable and current -> the empty book, which authorises nothing.
    releases = _releases_contract(_fresh(_load(rel_path), report_date, rel_path),
                                  args.legacy_releases, rel_path) or {'releases': []}
    fed = _fresh(_load(fed_path), report_date, fed_path) or {'events': []}

    violations = check(html, releases, fed)
    if violations:
        for x in violations:
            print(x)
        sys.exit(1)
    print('source gate: OK')


if __name__ == '__main__':
    main()
