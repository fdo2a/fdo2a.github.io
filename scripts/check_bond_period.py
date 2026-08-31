#!/usr/bin/env python3
"""글로벌 채권 주간·월간 발행 게이트.

  python scripts/check_bond_period.py --html bond/weekly/2026-W35.html

집계 파일은 HTML 경로에서 유추한다(`bond/<span>/<키>.html` -> `period_<span>_<키>.json`).
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bond.period_gate import check  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--html', required=True)
    ap.add_argument('--datadir', default='bond/data')
    ap.add_argument('--agg', default=None)
    a = ap.parse_args()

    key = os.path.basename(a.html)[:-5]
    span = os.path.basename(os.path.dirname(os.path.abspath(a.html)))
    agg_path = a.agg or os.path.join(a.datadir, f'period_{span}_{key}.json')
    if not os.path.exists(agg_path):
        print(f'✗ 집계 파일이 없다: {agg_path}')
        sys.exit(1)

    errs = check(open(a.html).read(), json.load(open(agg_path)))
    if errs:
        print(f'✗ {len(errs)}건')
        for e in errs:
            print('  -', e)
        sys.exit(1)
    print('✓ 발행 가능')


if __name__ == '__main__':
    main()
