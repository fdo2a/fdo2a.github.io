#!/usr/bin/env python3
"""Gate: Telegram-sourced sentences in a US/KR daily brief (rules: scripts/common/telegram_gate.py).

  python3 scripts/check_telegram.py --html morning_brief_2026-11-10.html --tg <workspace>/telegram.json --date 2026-11-09

No file and no data-tg in the post passes. A file whose report_date is not --date counts as
no file (a stale snapshot must not authorise anything).
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common.telegram_gate import check  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--html', required=True)
    ap.add_argument('--tg', required=True, help='telegram.json snapshot the writer was given')
    ap.add_argument('--date', required=True, help='report_date')
    a = ap.parse_args(argv)
    with open(a.html, encoding='utf-8') as f:
        html = f.read()
    data = None
    try:
        with open(a.tg, encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = None
    if data and data.get('report_date') != a.date:
        print(f'경고: {a.tg} 의 report_date {data.get("report_date")} ≠ {a.date} — 없는 것으로 본다')
        data = None
    warns = []
    v = check(html, data, warnings=warns)
    for w in warns:
        print(f'경고: {w}')
    if not v:
        print(f'텔레그램 인용 이상 없음 — {a.html}')
        return 0
    for x in v:
        print(f'FAIL {x}')
    return 1


if __name__ == '__main__':
    sys.exit(main())
