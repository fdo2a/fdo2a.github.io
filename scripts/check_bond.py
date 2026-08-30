#!/usr/bin/env python3
"""글로벌 채권 리포트 발행 게이트.

  python scripts/check_bond.py --html bond/posts/2026-08-27.html [--datadir bond/data]

exit 0 = 발행 가능. exit 1 = 위반 목록을 한 줄씩 찍는다 — 그대로 작성자에게 돌려준다.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bond.gate import check  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--html', required=True)
    ap.add_argument('--datadir', default='bond/data')
    ap.add_argument('--econ', default='data/econ_indicators.json',
                    help='발행본이 인용하는 경제지표 파일(다른 파이프라인 소속)')
    a = ap.parse_args()

    def load(name):
        return json.load(open(os.path.join(a.datadir, name)))

    econ = json.load(open(a.econ)) if os.path.exists(a.econ) else None
    errs = check(open(a.html).read(), load('bond_market.json'),
                 load('bond_metrics.json'), load('bond_stance_eval.json'),
                 load('bond_stance.json'), econ)
    if errs:
        print(f'✗ {len(errs)}건')
        for e in errs:
            print('  -', e)
        sys.exit(1)
    print('✓ 발행 가능')


if __name__ == '__main__':
    main()
