#!/usr/bin/env python3
"""「다음 발표 일정」 카드의 발행 게이트.

  python3 scripts/check_calendar.py --html morning_brief_2026-09-11.html --datadir .

종료 0 = 발행 가능. 1 = 위반을 한 줄씩 출력. 2 = 미완료(2026-11-17) — 장부가 없거나 읽히지 않거나
낡았거나(`report_date`) 미완(`complete` 가 참이 아님·`missing`), 또는 기준일을 모른다. 빈 장부로 검사하지 않는다.

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
        print(f'FATAL: could not read {path}: {e} — 미완료', file=sys.stderr)
        sys.exit(2)


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
    if not market.get('report_date'):
        why = 'market_data.json 의 기준일을 모른다'
    elif book is None:
        why = f'{os.path.basename(path)} 이 없다'
    elif book.get('report_date') != market['report_date']:
        why = (f"{os.path.basename(path)} 은 {book.get('report_date')} 것이고 오늘은 "
               f"{market['report_date']} 다 — 낡은 장부는 쓰지 않는다")
    elif book.get('complete') is False or book.get('missing'):
        why = f"{os.path.basename(path)} 이 미완이다(missing {book.get('missing')})"
    if why:
        # 고칠 것은 수집이다 — 빈 장부로 검사해 표식만 고치게 하지 않는다(2026-11-17)
        print(f'FATAL: 수집한 일정이 없다: {why} — 미완료, 수집을 다시 돌린다', file=sys.stderr)
        sys.exit(2)

    violations = check(html, book or {})
    if violations:
        # 왜 인가하는 일정이 하나도 없는지 말해 주지 않으면, 되돌려받은 작성자는
        # 표식을 고치려 든다 — 고칠 것은 수집이다.
        for x in violations:
            print(x)
        sys.exit(1)
    print('calendar gate: OK')


if __name__ == '__main__':
    main()
