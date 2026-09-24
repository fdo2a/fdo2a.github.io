#!/usr/bin/env python3
"""움직인 종목 발행 게이트 — 묶음마다 `<p data-mover="gN">` 문단과 대표 종목 등락률이 있는가.

  python3 scripts/check_movers.py --html morning_brief_2026-09-24.html --datadir <workspace>
  python3 scripts/check_movers.py --html kr_brief_2026-09-24.html --datadir kr/data --market kr

movers 파일이 없거나, 묶음이 비었거나, 같은 폴더 시장 데이터와 report_date 가 다르면
강제하지 않는다(비-코어). Exit 0 = 발행 가능, 1 = 위반. Logic: scripts/common/movers.py.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.common.movers import check  # noqa: E402

FILES = {'us': ('movers.json', 'market_data.json'),
         'kr': ('kr_movers.json', 'kr_market_data.json')}


def _load(path):
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--html', required=True)
    ap.add_argument('--datadir', default='data')
    ap.add_argument('--market', choices=sorted(FILES), default='us')
    args = ap.parse_args(argv)
    with open(args.html, encoding='utf-8') as fh:
        html = fh.read()
    movers_name, market_name = FILES[args.market]
    movers = _load(os.path.join(args.datadir, movers_name))
    market = _load(os.path.join(args.datadir, market_name)) or {}
    violations = check(html, movers, market.get('report_date'))
    if not violations:
        print(f'움직인 종목 이상 없음 — {args.html}')
        return 0
    for v in violations:
        print(f'FAIL {v}')
    return 1


if __name__ == '__main__':
    sys.exit(main())
