#!/usr/bin/env python3
"""발행 게이트 — 「국채 입찰」 섹션.

  python3 scripts/check_auction.py --html morning_brief_2026-11-09.html --datadir .

Exit 0 = 발행 가능. Exit 1 = 위반을 한 줄씩 출력 — writer 에게 그대로 돌려준다.

비-코어의 경계는 `check_fed.py` 와 같다. `auctions.json` 이 없거나 실패했거나 다른 날
것이면 **섹션 없이** 통과(경고)하고, 그 상태에서 섹션을 실으면 막는다. 파일이 오늘 것이고
결과가 있는 날 섹션이 없으면 닫히면서 실패한다.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from us.auction_gate import check  # noqa: E402


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
    args = ap.parse_args()
    try:
        with open(args.html, encoding='utf-8') as fh:
            html = fh.read()
    except OSError as e:
        print(f'FATAL: cannot read {args.html}: {e}', file=sys.stderr)
        sys.exit(2)
    try:
        book = load(os.path.join(args.datadir, 'auctions.json'))
    except Exception as e:
        # 깨진 파일을 «없음»으로 돌리면 비-코어 면제가 사고를 덮는다.
        print(f'auctions.json 을 읽을 수 없다: {e}')
        sys.exit(1)
    market = load(os.path.join(args.datadir, 'market_data.json')) or {}
    today = market.get('report_date')

    errs = check(html, book, today)
    if errs:
        for e in errs:
            print(e)
        sys.exit(1)
    if book is None:
        print('경고: auctions.json 없음 — 「국채 입찰」 섹션 없이 발행한다 (비-코어)', file=sys.stderr)
    elif not book.get('ok'):
        print(f'경고: 입찰 결과 수집 실패({book.get("error")}) — 섹션 없이 발행한다', file=sys.stderr)
    elif book.get('report_date') != today:
        print(f'경고: auctions.json 이 {book.get("report_date")} 에서 멈춰 있다 — 섹션 없이 발행한다',
              file=sys.stderr)
    elif book.get('pending'):
        print('경고: 결과가 아직 없는 입찰 — ' + ', '.join(p['label_ko'] for p in book['pending']),
              file=sys.stderr)


if __name__ == '__main__':
    main()
