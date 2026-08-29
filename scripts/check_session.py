#!/usr/bin/env python3
"""「오늘의 장」 발행 게이트.

  python3 scripts/check_session.py --html morning_brief_2026-08-29.html --datadir . --market us
  python3 scripts/check_session.py --html kr_brief_2026-08-29.html --datadir kr/data --market kr

Exit 0 = 발행 가능. Exit 1 = 위반이 한 줄씩 찍힌다 — 그대로 writer에게 돌려주고
다시 돌린다. 비-코어: session 블록이 없는 데이터셋이면 강제할 것이 없어 통과한다.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from us.session_gate import check  # noqa: E402

SOURCES = {'us': ('market_data.json', 'session'), 'kr': ('kr_session.json', None)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--html', required=True)
    ap.add_argument('--datadir', default='data')
    ap.add_argument('--market', choices=('us', 'kr'), default='us')
    args = ap.parse_args()

    try:
        with open(args.html, encoding='utf-8') as fh:
            html = fh.read()
    except OSError as e:
        print(f'FATAL: cannot read {args.html}: {e}', file=sys.stderr)
        sys.exit(2)

    fname, key = SOURCES[args.market]
    path = os.path.join(args.datadir, fname)
    try:
        with open(path, encoding='utf-8') as fh:
            blob = json.load(fh)
    except FileNotFoundError:
        print(f'no {path} — nothing to check')
        return
    except Exception as e:
        # 깨진 산출물은 「없는 것」과 다르다. 없으면 비-코어라 통과지만, 읽다 만
        # 파일에 검사를 면제해 주면 게이트가 조용히 꺼진다.
        print(f'FATAL: {path} is unreadable: {e}', file=sys.stderr)
        sys.exit(2)

    pc = blob.get('price_context') if args.market == 'us' else None
    violations = check(html, blob.get(key) if key else blob,
                       market=args.market, price_context=pc)
    if violations:
        for line in violations:
            print(line)
        sys.exit(1)
    print('session gate: OK')


if __name__ == '__main__':
    main()
