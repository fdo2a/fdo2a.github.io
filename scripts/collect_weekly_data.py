#!/usr/bin/env python3
"""주간 스냅샷 — US 주간 인사이트와 일본 주간이 같이 읽는 원자료를 한 번에 받는다.

    python3 scripts/collect_weekly_data.py --key 2026-W39 --end 2026-09-25

산출 `data/weekly_ext/<KEY>.json`. 매일 돌리지 않는다 — 소스가 전부 이력을 준다.
실패한 소스는 `fetch_status` 에 이유와 함께 남고, 그 소스를 쓰는 절은 게이트에서 막힌다
(못 받은 것을 조용한 무변화로 위장하지 않는다). 종료 코드는 전부 실패일 때만 1.

소스 정의: scripts/common/weekly_sources.py
"""
import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.common import weekly_sources as W  # noqa: E402

KST = timezone(timedelta(hours=9))

US_TICKERS = {
    'S&P 500': '^GSPC', 'Nasdaq': '^IXIC', 'Dow': '^DJI', 'Russell 2000': '^RUT',
    'S&P 500 Growth': 'IVW', 'S&P 500 Value': 'IVE',
    'DXY': 'DX-Y.NYB', 'USD/KRW': 'KRW=X', 'USD/JPY': 'JPY=X', 'EUR/USD': 'EURUSD=X',
    'WTI': 'CL=F', 'Brent': 'BZ=F', 'Natural Gas': 'NG=F', 'Gold': 'GC=F',
    'Technology': 'XLK', 'Energy': 'XLE', 'Communication Services': 'XLC',
    'Consumer Discretionary': 'XLY', 'Utilities': 'XLU', 'Consumer Staples': 'XLP',
    'Health Care': 'XLV', 'Industrials': 'XLI', 'Financials': 'XLF', 'Materials': 'XLB',
    'Real Estate': 'XLRE',
}
JP_TICKERS = {
    'Nikkei 225': '^N225', 'TOPIX ETF': '1306.T', 'TOPIX Banks ETF': '1615.T',
    'J-REIT ETF': '1343.T', 'TOPIX Autos ETF': '1622.T',
}
FRED_SERIES = ('DGS2', 'DGS5', 'DGS10', 'DGS30', 'DTB3', 'EFFR')
JGB_TENORS = ('1Y', '2Y', '5Y', '10Y', '20Y', '30Y', '40Y')
JGB_KEEP = 280       # 1년 남짓 영업일
WEEKLY_KEEP = 110     # 2년 남짓 — 52주 변동성 기준선 + 여유
DAILY_KEEP = 90       # 20일 상관 두 창 + 여유


def weekly_closes(rows):
    """일별 [[date, close]] -> 주(ISO)의 마지막 거래일 종가 [[date, close]]."""
    by_week = {}
    for d, v in rows:
        y, w, _ = date.fromisoformat(d).isocalendar()
        by_week[(y, w)] = [d, v]
    return [by_week[k] for k in sorted(by_week)]


def _try(status, name, fn, attempts=3, pause=2.0):
    """일시 장애(연결 리셋 — 2026-09-26 CFTC 실측)는 몇 번 더 두드린다. 끝내 실패하면
    이유를 남긴다 — 그 소스를 쓰는 절이 게이트에서 막힌다."""
    import time
    err = None
    for i in range(attempts):
        try:
            out = fn()
        except Exception as e:  # noqa: BLE001 — 실패 이유를 남기는 것이 목적이다
            err = e
            if i + 1 < attempts:
                time.sleep(pause * (i + 1))
            continue
        status[name] = 'ok' if out else 'empty'
        return out
    status[name] = f'error: {type(err).__name__}: {str(err)[:160]}'
    return None


def collect(key, end, today=None):
    today = today or datetime.now(KST).date()
    ctx = W.ssl_context()
    status, prices = {}, {}
    for name, tk in {**US_TICKERS, **JP_TICKERS}.items():
        rows = _try(status, f'price:{tk}', lambda tk=tk: W.fetch_closes(tk, '2y'))
        if rows:
            prices[name] = {'ticker': tk, 'weekly': weekly_closes(rows)[-WEEKLY_KEEP:],
                            'daily': rows[-DAILY_KEEP:]}
    fred = {}
    for sid in FRED_SERIES:
        rows = _try(status, f'fred:{sid}', lambda sid=sid: W.fetch_fred(sid))
        if rows:
            fred[sid] = rows
    fedfunds = []
    for month, sym in W.fed_funds_contracts(today, months=7):
        raw = _try(status, f'fedfunds:{sym}', lambda sym=sym: W.fetch_closes_volume(sym, '1mo'))
        if raw:
            rows, copied = W.drop_copied_rows(raw)
            # 1주 전 = 마지막 행 날짜로부터 7일 이상 앞선 마지막 행. 행 개수로 세면 복사 행을
            # 버린 만큼 더 과거로 밀려난다.
            cut = (date.fromisoformat(rows[-1][0]) - timedelta(days=7)).isoformat()
            ago = [r for r in rows if r[0] <= cut]
            fedfunds.append({'month': month, 'symbol': sym, 'date': rows[-1][0],
                             'price': rows[-1][1], 'implied': W.implied_rate(rows[-1][1]),
                             'week_ago': ago[-1][1] if ago else None,
                             'week_ago_date': ago[-1][0] if ago else None,
                             'copied_rows_dropped': copied})
    cftc = {}
    for code, label in W.CFTC_CONTRACTS.items():
        rows = _try(status, f'cftc:{code}', lambda code=code: W.fetch_cftc(code, ctx))
        if rows:
            cftc[code] = {'label': label, 'rows': rows}
    flows = _try(status, 'mof:week', lambda: W.fetch_mof_week(ctx)) or []
    jgb = _try(status, 'mof:jgb', lambda: W.fetch_jgb(ctx)) or []
    jgb = [{k: r[k] for k in ('date',) + JGB_TENORS if k in r} for r in jgb[-JGB_KEEP:]]
    return {
        'key': key, 'end_date': end,
        'generated': datetime.now(KST).isoformat(timespec='seconds'),
        'fetch_status': status,
        'prices': prices, 'fred': fred, 'fedfunds': fedfunds, 'cftc': cftc,
        'mof_flows': flows[-160:], 'jgb': jgb,
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--key', required=True)
    ap.add_argument('--end', required=True, help='집계의 end_date (YYYY-MM-DD)')
    ap.add_argument('--out-dir', default='data/weekly_ext')
    args = ap.parse_args(argv)
    snap = collect(args.key, args.end)
    out = Path(args.out_dir) / f'{args.key}.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(snap, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    bad = {k: v for k, v in snap['fetch_status'].items() if v != 'ok'}
    print(f'{out} — 소스 {len(snap["fetch_status"])}개, 실패·빈 값 {len(bad)}개')
    for k, v in bad.items():
        print(f'  - {k}: {v}')
    return 1 if len(bad) == len(snap['fetch_status']) else 0


if __name__ == '__main__':
    sys.exit(main())
