#!/usr/bin/env python3
"""US 발행 게이트 — 섹터 기간 수익률 표가 그날 섹터 등락률과 같은 회차인가.

  python3 scripts/check_sector_perf.py --html morning_brief_DATE.html --datadir <workspace>

Exit 0 = 발행 가능, 1 = 위반(한 줄에 하나), 2 = 입력을 읽지 못함(통과로 치지 않는다).
정정기는 원본에서 실패한 게이트를 면제하지만 이 게이트는 면제하지 않는다(NEVER_TOLERATE).
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from us.sector_perf_gate import check  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--html', required=True)
    ap.add_argument('--datadir', default='data')
    args = ap.parse_args()
    try:
        with open(args.html, encoding='utf-8') as fh:
            doc = fh.read()
        with open(os.path.join(args.datadir, 'market_data.json'), encoding='utf-8') as fh:
            market = json.load(fh)
    except (OSError, ValueError) as e:
        print(f'FATAL: 입력을 읽지 못했다: {e}', file=sys.stderr)
        sys.exit(2)
    if not isinstance(market, dict):
        print('FATAL: market_data.json 이 객체가 아니다', file=sys.stderr)
        sys.exit(2)
    if not isinstance(market.get('report_date'), str):
        print('FATAL: market_data.json 에 report_date 가 없다', file=sys.stderr)
        sys.exit(2)
    v = check(doc, market)
    if v:
        print('\n'.join(v))
        sys.exit(1)
    print('sector performance gate: OK')


if __name__ == '__main__':
    main()
