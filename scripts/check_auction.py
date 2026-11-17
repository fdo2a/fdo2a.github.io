#!/usr/bin/env python3
"""발행 게이트 — 「국채 입찰」 섹션.

  python3 scripts/check_auction.py --html morning_brief_2026-11-09.html --datadir .

Exit 0 = 발행 가능. Exit 1 = 위반을 한 줄씩 출력 — writer 에게 그대로 돌려준다.

Exit 2 = 미완료: `auctions.json` 이 없거나 읽히지 않거나 수집 실패(`ok` 가 참이 아님·`error`)거나 다른 날 것이거나
결과 미확정(`pending`)이 남았다 — 섹션을 빼고 발행하지 않는다(2026-11-17 사용자 결정, 재수집 뒤에도 그러면 보류).
파일이 오늘 것이고 결과가 있는 날 섹션이 없으면, 결과가 없는 날 섹션을 실으면 위반(1).
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from us.auction_gate import BadBook, check  # noqa: E402


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
        market = load(os.path.join(args.datadir, 'market_data.json')) or {}
    except Exception as e:
        print(f'FATAL: 입력을 읽을 수 없다: {e}', file=sys.stderr)
        sys.exit(2)
    today = market.get('report_date') if isinstance(market, dict) else None
    why = ('auctions.json 없음' if book is None else
           'auctions.json 이 객체가 아니다' if not isinstance(book, dict) else
           # 칸이 없거나 목록이 아니면 「입찰 없는 날」이 아니다(1a 구현 검토 2회차 F1)
           'auctions.json 의 today 칸이 없거나 목록이 아니다' if not isinstance(book.get('today'), list) else
           '기준일(market_data.json report_date) 없음' if not today else
           f'입찰 결과 수집 실패({str(book.get("error"))[:120]})' if not book.get('ok') or book.get('error') else
           f'auctions.json 이 {book.get("report_date")} 에서 멈춰 있다(오늘 {today})'
           if book.get('report_date') != today else
           '결과가 아직 없는 입찰 — ' + ', '.join(str(p.get('label_ko')) for p in book['pending'])
           if book.get('pending') else None)
    if why:
        # 섹션 없이 발행하지 않는다 — 수집을 다시 돌리고, 그래도 그러면 보류(2026-11-17)
        print(f'FATAL: {why} — 미완료, 수집을 다시 돌린다', file=sys.stderr)
        sys.exit(2)

    try:
        errs = check(html, book, today)
    except BadBook as e:
        print(f'FATAL: {e} — 미완료, 수집을 다시 돌린다', file=sys.stderr)
        sys.exit(2)
    if errs:
        for e in errs:
            print(e)
        sys.exit(1)


if __name__ == '__main__':
    main()
