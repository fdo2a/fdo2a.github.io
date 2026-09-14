#!/usr/bin/env python3
"""「다음 발표 일정」 카드의 발행 게이트.

  python3 scripts/check_calendar.py --html morning_brief_2026-09-11.html --datadir .

종료 0 = 발행 가능. 1 = 위반을 한 줄씩 출력.

낡은 장부는 없는 장부와 같이 다룬다 — 어제 받은 일정으로 오늘의 표식을 인가하면
그 카드는 하루 밀린 시각을 인쇄한다.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from us.calendar_gate import check  # noqa: E402


def _load(path):
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except FileNotFoundError:
        return None
    except Exception as e:
        print(f'WARN: could not read {path}: {e} — treating it as empty', file=sys.stderr)
        return None


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
    path = os.path.join(args.datadir, 'calendar.json')
    book, why = _load(path), None
    if book is None:
        why = f'{path} 을 읽지 못했다'
    elif market.get('report_date') and book.get('report_date') != market['report_date']:
        why = (f"{path} 은 {book.get('report_date')} 것이고 오늘은 "
               f"{market['report_date']} 다 — 낡은 장부는 쓰지 않는다")
        book = None

    violations = check(html, book or {})
    if violations:
        # 왜 인가하는 일정이 하나도 없는지 말해 주지 않으면, 되돌려받은 작성자는
        # 표식을 고치려 든다 — 고칠 것은 수집이다.
        if why:
            print(f'수집한 일정이 없다: {why}')
        for x in violations:
            print(x)
        sys.exit(1)
    print('calendar gate: OK')


if __name__ == '__main__':
    main()
