#!/usr/bin/env python3
"""승계된 등급 이력으로 모의 포트폴리오를 처음부터 굴려 원장을 만든다 (1회성).

`data/history/stance.jsonl` 은 2026-08-14 부트스트랩부터 남아 있다. 그 책을 그대로
따라가면 오늘 시작하는 것보다 정직한 출발점이 나온다 — 비중이 그날그날 **실제로
발행됐던** 등급에서 나오기 때문이다. 창작이 아니라 재생이다.

가격은 여기서만 직접 받는다(일일 실행은 수집 워크플로가 넘긴 종가만 쓴다).

  python scripts/backfill_portfolio.py --datadir data [--period 6mo]
"""

import argparse
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from us import portfolio_io as IO  # noqa: E402
from us.history import append_jsonl, read_jsonl  # noqa: E402,F401
from us.portfolio import BASE_NAV, HISTORY_TICKERS  # noqa: E402


def download(period):
    import yfinance as yf
    df = yf.download(list(HISTORY_TICKERS), period=period, interval='1d',
                     group_by='ticker', auto_adjust=True, progress=False,
                     threads=False)
    if df is None or not len(df):
        raise RuntimeError('yfinance returned nothing')
    by_date, closes, dates = {}, {}, {}
    for t in HISTORY_TICKERS:
        series = df[t]['Close'].dropna()
        closes[t] = [float(x) for x in series]
        dates[t] = [str(d.date()) for d in series.index]
        for stamp, value in series.items():
            by_date.setdefault(str(stamp.date()), {})[t] = float(value)
    return by_date, closes, dates


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--datadir', default='data')
    # 수집이 매일 쓰는 창과 같아야 한다 — 여기서 6개월로 재면 발행본이
    # 「3년을 쟀다」고 쓰면서 6개월 값을 인쇄한다(2026-09-02 codex 검토).
    ap.add_argument('--period', default='3y')
    ap.add_argument('--start', help='설정일 (기본: 스탠스 이력의 첫 날)')
    args = ap.parse_args()
    d = args.datadir

    stance_rows = read_jsonl(os.path.join(d, 'history', 'stance.jsonl'))
    current = IO.load(os.path.join(d, 'stance.json'))
    if current and current.get('report_date'):
        if not any(r.get('report_date') == current['report_date'] for r in stance_rows):
            stance_rows.append(current)
    if not stance_rows:
        print('FATAL: 스탠스 이력이 없다 — 굴릴 책이 없다', file=sys.stderr)
        sys.exit(1)
    start = args.start or min(r['report_date'] for r in stance_rows
                              if r.get('report_date'))

    market = IO.load(os.path.join(d, 'market_data.json')) or {}
    report_date = market.get('report_date')

    prices_by_date, closes, hist_dates = download(args.period)
    sessions = [x for x in sorted(prices_by_date) if x >= start
                and (not report_date or x <= report_date)]
    if not sessions:
        print('FATAL: 굴릴 세션이 없다', file=sys.stderr)
        sys.exit(1)

    book_for = IO.book_lookup(stance_rows)
    state, rows, gaps = IO.replay(sessions, prices_by_date,
                                  lambda d: IO.grades_of(book_for(d)),
                                  base_nav=BASE_NAV)
    ledger_path = os.path.join(d, 'history', 'portfolio.jsonl')
    for row in rows:
        append_jsonl(ledger_path, row)
    rows = IO.read_ledger(ledger_path)

    generated = dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    # 오늘 비중을 만든 책이 어느 날 것인지 — 하루 시차 때문에 stance.json 의 날짜와
    # 다르다. 발행본이 그 사실을 밝히므로 정확한 날짜를 넘긴다.
    applied = book_for(state['active']['date']) or {}
    IO.write(os.path.join(d, 'portfolio_state.json'),
             IO.state_blob(state, applied.get('report_date')))
    from us.portfolio_risk import compute as compute_rationale
    book = IO.publishable(state, rows, report_date or state['active']['date'],
                          gaps, applied.get('report_date'), generated,
                          rationale=compute_rationale(closes, hist_dates))
    IO.write(os.path.join(d, 'portfolio.json'), book)

    perf = book['performance']
    print(f"설정 {perf['inception']} · {perf['sessions']}거래일 · "
          f"기준가 {perf['nav']:.2f} · 벤치마크 {perf['bench_nav']:.2f}")
    if gaps:
        print(f'  종가 결측으로 건너뛴 세션: {", ".join(gaps)}')
    for r in perf['rebalances']:
        print(f"  리밸런싱 {r['report_date']}: {r['changed']}")


if __name__ == '__main__':
    main()
