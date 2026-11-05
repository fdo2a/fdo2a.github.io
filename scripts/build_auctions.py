#!/usr/bin/env python3
"""그날의 미 재무부 이표채 입찰 결과를 `data/auctions.json`·`data/auction_table.html` 로.

  python3 scripts/build_auctions.py --datadir data
  python3 scripts/build_auctions.py --datadir data --date 2026-10-27

비-코어다. 실패해도 `auctions.json` 은 `ok: false` 로 **늘 쓴다** — 파일이 안 바뀌면 어제
결과가 오늘 것처럼 남는다. 표 HTML 은 오늘 입찰이 없거나 실패하면 지운다(워크플로가
`git add -A` 로 삭제까지 담는다). 실패하면 exit 1 — 워크플로 단계가 노랗게 남는다.
"""

import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from us import auctions as A  # noqa: E402


def _report_date(datadir, override):
    if override:
        return dt.date.fromisoformat(override)
    with open(os.path.join(datadir, 'market_data.json'), encoding='utf-8') as fh:
        return dt.date.fromisoformat(json.load(fh)['report_date'])


def _yields(datadir):
    try:
        with open(os.path.join(datadir, 'market_data.json'), encoding='utf-8') as fh:
            return json.load(fh).get('yields') or {}
    except Exception:
        return {}


def collect(report_date, opener=None):
    """-> (results, announced). 이력이 긴 이표채는 유형별로, 재정증권은 신선도 검사용 2주."""
    days = (dt.date.today() - report_date).days
    results = []
    for kind in A.COUPON_TYPES:
        results += A.fetch_results(A.HISTORY_DAYS + max(days, 0), kind, opener)
    results += A.fetch_results(A.RECENT_DAYS * 2 + max(days, 0), 'Bill', opener)
    return results, A.fetch_announced(14 + max(days, 0), opener)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--datadir', default='data')
    ap.add_argument('--date')
    args = ap.parse_args()

    rd = _report_date(args.datadir, args.date)
    stamp = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).strftime('%Y-%m-%d %H:%M KST')
    code = 0
    try:
        results, announced = collect(rd)
        book = A.build(rd, results, announced, _yields(args.datadir), generated=stamp)
    except Exception as e:
        print(f'국채 입찰 결과 실패: {e}', file=sys.stderr)
        book, code = A.failed(rd, e, generated=stamp), 1

    out = os.path.join(args.datadir, 'auctions.json')
    with open(out, 'w', encoding='utf-8') as fh:
        json.dump(book, fh, indent=2, ensure_ascii=False)
    table = os.path.join(args.datadir, 'auction_table.html')
    html = A.render_table(book)
    if html:
        with open(table, 'w', encoding='utf-8') as fh:
            fh.write(html)
    elif os.path.exists(table):
        os.remove(table)

    print(f"{out} — {rd} 이표채 {len(book['today'])}건"
          + (f" · 결과 미도착 {[p['label_ko'] for p in book['pending']]}" if book['pending'] else '')
          + (f" · 실패 {book['error']}" if not book['ok'] else ''))
    for t in book['today']:
        print(f"  {t['label_ko']}: {A.fmt_rate(t)} 응찰 {t['bid_to_cover']} "
              f"(평균 {(t['avg6'] or {}).get('bid_to_cover')}, n={t['n_hist']}) → {t['demand_ko']}")
    sys.exit(code)


if __name__ == '__main__':
    main()
