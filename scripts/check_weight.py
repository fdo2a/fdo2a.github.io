#!/usr/bin/env python3
"""무게중심 게이트 — 시황·가격 대 판단·포지션.

  python3 scripts/check_weight.py --html morning_brief_2026-08-30.html --datadir . --market us
  python3 scripts/check_weight.py --html kr_brief_2026-08-30.html --datadir kr/data --market kr

Exit 0 = 발행 가능. Exit 1 = 위반이 한 줄씩 찍힌다 — 그대로 writer에게 돌려주고 다시 돌린다.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from us.weight import check  # noqa: E402

MARKET_FILE = {'us': 'market_data.json', 'kr': 'kr_market_data.json'}


def _load(path):
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--html', required=True)
    ap.add_argument('--datadir', default='data')
    ap.add_argument('--market', choices=('us', 'kr'), default='us')
    args = ap.parse_args()

    try:
        with open(args.html, encoding='utf-8') as fh:
            doc = fh.read()
    except OSError as e:
        print(f'FATAL: cannot read {args.html}: {e}', file=sys.stderr)
        sys.exit(2)

    market_data = _load(os.path.join(args.datadir, MARKET_FILE[args.market]))
    macro_eval = _load(os.path.join(args.datadir, 'macro_eval.json'))

    violations = check(doc, market=args.market, market_data=market_data,
                       macro_eval=macro_eval)
    if violations:
        for x in violations:
            print(x)
        sys.exit(1)
    day = '축약일' if (macro_eval or {}).get('abbreviated') else '발표일'
    print(f'OK — 무게중심 게이트 통과 ({day})')


if __name__ == '__main__':
    main()
