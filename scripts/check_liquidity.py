#!/usr/bin/env python3
"""발행 게이트 — 「유동성·수급」 섹션.

  python3 scripts/check_liquidity.py --html morning_brief_2026-11-12.html --datadir <workspace> --repo <repo>

Exit 0 = 발행 가능. Exit 1 = 위반을 한 줄씩. 첫 줄이 `ledger_changed:` 로 시작하면 수집 뒤 다른 글이 같은 회차를
실은 것이다 — `build_liquidity.py --datadir <workspace> --repo <repo> --recompute` 뒤 섹션만 다시 쓰고 게이트를
다시 돌린다(최대 2회). 비-코어: 책이 없거나 꺼져 있거나 다른 날 것이면 섹션 없이 통과(경고)하고, 그 상태에서
섹션을 실으면 막는다. 원장 = `<repo>/posts/*.html`(이 글 날짜만 뺀다).
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from us import liquidity as L  # noqa: E402
from us.liquidity_gate import check  # noqa: E402


def load(path):
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except FileNotFoundError:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--html', required=True)
    ap.add_argument('--datadir', default='.')
    ap.add_argument('--repo', default='.')
    args = ap.parse_args()
    try:
        with open(args.html, encoding='utf-8') as fh:
            html = fh.read()
    except OSError as e:
        print(f'FATAL: cannot read {args.html}: {e}', file=sys.stderr)
        sys.exit(2)
    try:
        book = load(os.path.join(args.datadir, 'liquidity', 'liquidity.json'))
    except Exception as e:
        print(f'liquidity.json 을 읽을 수 없다: {e}')
        sys.exit(1)
    market = load(os.path.join(args.datadir, 'market_data.json')) or {}
    today = market.get('report_date')
    ledger = L.ledger_from_posts(args.repo, today)
    errs = check(html, book, today, ledger)
    if errs:
        for e in errs:
            print(e)
        sys.exit(1)
    if book is None:
        print('경고: liquidity.json 없음 — 「유동성·수급」 섹션 없이 발행한다 (비-코어)', file=sys.stderr)
    elif book.get('status') != 'complete':
        print(f'경고: 유동성 책 상태 {book.get("status")} — 섹션 없이 발행한다', file=sys.stderr)
    for w in ((book or {}).get('h41') or {}).get('pending') or []:
        print(f'경고: H.4.1 {w} 주 회차 미확인 — 다음 글이 싣는다', file=sys.stderr)
    print('liquidity gate: OK')


if __name__ == '__main__':
    main()
