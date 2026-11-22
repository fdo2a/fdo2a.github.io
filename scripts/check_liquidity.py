#!/usr/bin/env python3
"""발행 게이트 — 「유동성·수급」 섹션.

  python3 scripts/check_liquidity.py --html morning_brief_2026-11-12.html --datadir <workspace> --repo <repo>

Exit 0 = 발행 가능. Exit 1 = 위반을 한 줄씩. 첫 줄이 `ledger_changed:` 로 시작하면 수집 뒤 다른 글이 같은 회차를
실은 것이다 — `build_liquidity.py --datadir <workspace> --repo <repo> --recompute` 뒤 섹션만 다시 쓰고 게이트를
다시 돌린다(최대 2회). Exit 2 = 미완료: 책이 없거나 읽히지 않거나 `status` 가 complete 가 아니거나 다른 날 것 —
섹션을 빼고 발행하지 않는다(2026-11-17, 재수집 뒤에도 그러면 보류). 원장 = `<repo>/posts/*.html`(이 글 날짜만 뺀다).
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from verification.inputs import enforcing  # noqa: E402 — 1a 를 켰는가(꺼져 있으면 1a 전 판정 그대로)
from us import liquidity as L  # noqa: E402
from us.liquidity_gate import check  # noqa: E402


from common.jsonfile import load_json_missing_none as load  # noqa: E402 — 공용 JSON 읽기(2026-11-22)


def _main_1a():
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
        market = load(os.path.join(args.datadir, 'market_data.json')) or {}
    except Exception as e:
        print(f'FATAL: 입력을 읽을 수 없다: {e}', file=sys.stderr)
        sys.exit(2)
    today = market.get('report_date') if isinstance(market, dict) else None
    why = ('liquidity.json 없음' if book is None else
           '기준일(market_data.json report_date) 없음' if not today else
           f'유동성 책 상태 {book.get("status")}' if book.get('status') != 'complete' else
           f'유동성 책이 {book.get("report_date")} 것이다(오늘 {today})' if book.get('report_date') != today else None)
    if why:
        print(f'FATAL: {why} — 미완료, 수집을 다시 돌린다(섹션을 빼고 발행하지 않는다)', file=sys.stderr)
        sys.exit(2)
    ledger = L.ledger_from_posts(args.repo, today)
    errs = check(html, book, today, ledger)
    if errs:
        for e in errs:
            print(e)
        sys.exit(1)
    for w in ((book or {}).get('h41') or {}).get('pending') or []:
        print(f'경고: H.4.1 {w} 주 회차 미확인 — 다음 글이 싣는다', file=sys.stderr)
    print('liquidity gate: OK')

def _main_pre1a():
    """1a 를 켜기 전의 판정 — 1a 전 `main()` 그대로."""
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



def main():
    return _main_1a() if enforcing() else _main_pre1a()


if __name__ == '__main__':
    main()
