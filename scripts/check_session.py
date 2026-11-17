#!/usr/bin/env python3
"""「오늘의 장」 발행 게이트.

  python3 scripts/check_session.py --html morning_brief_2026-08-29.html --datadir . --market us
  python3 scripts/check_session.py --html kr_brief_2026-08-29.html --datadir kr/data --market kr

Exit 0 = 발행 가능. Exit 1 = 위반이 한 줄씩 찍힌다 — 그대로 writer에게 돌려주고
다시 돌린다. Exit 2 = 미완료(2026-11-17): 자료 파일이 없거나 읽히지 않거나 session 블록이 비었다 — 재수집.
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
    except Exception as e:
        # 없는 것도 깨진 것도 미완료다(2026-11-17) — 검사를 면제해 주면 게이트가 조용히 꺼진다.
        print(f'FATAL: {path} is missing or unreadable: {e}', file=sys.stderr)
        sys.exit(2)

    pc = blob.get('price_context') if args.market == 'us' else None
    session = blob.get(key) if key else blob
    if not session:
        # 2026-11-17: 블록이 없으면 수집 단계가 실패한 것이다 — 「볼 것이 없어 통과」로 두지 않는다
        print(f'FATAL: session block absent in {fname} — 미완료(수집 단계 실패)', file=sys.stderr)
        sys.exit(2)
    violations = check(html, session, market=args.market, price_context=pc)
    if violations:
        for line in violations:
            print(line)
        sys.exit(1)
    print('session gate: OK')


if __name__ == '__main__':
    main()
