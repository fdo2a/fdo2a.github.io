"""Monthly FF3 check: official French daily factors vs the ETF proxy factors.

Runs in Actions (check-fund-factors.yml, Sunday + workflow_dispatch). Network I/O lives
here; everything it decides is in fund/factors_check.py. Writes
data/fund_factors_french.csv, data/fund_factors_inputs.json and
data/fund_factors_check.json — or nothing, when the result is a no-op or fails its own
structure check.

    python scripts/collect_fund_factors.py --outdir data
"""

import argparse
import datetime
import os
import sys
import urllib.request


def fetch_zip(url=None, timeout=60):
    from collect_market_data import _SSL
    from fund.factors_check import FRENCH_URL
    req = urllib.request.Request(url or FRENCH_URL, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=timeout, context=_SSL) as resp:
        body = resp.read()
        http = {'etag': resp.headers.get('ETag'),
                'last_modified': resp.headers.get('Last-Modified')}
    return body, http


def fetch_histories():
    """2-year auto-adjusted daily closes for the 28 reference ETFs and the factor legs —
    the same yfinance settings as collect_market_data.collect_histories."""
    import yfinance as yf
    from collect_market_data import retry
    from fund.factors import FACTOR_TICKERS
    from fund.universe import tickers as fund_tickers
    tickers = sorted(set(fund_tickers()) | set(FACTOR_TICKERS))

    def dl():
        df = yf.download(tickers, period='2y', interval='1d', group_by='ticker',
                         auto_adjust=True, progress=False, threads=False)
        return df if df is not None and len(df) else None

    df = retry(dl)
    closes, dates = {}, {}
    if df is None:
        return closes, dates
    for t in tickers:
        try:
            c = df[t]['Close'].dropna()
        except Exception:
            continue
        if len(c):
            closes[t] = [float(x) for x in c]
            dates[t] = [str(d.date()) for d in c.index]
    return closes, dates


def fetch_rf():
    from collect_market_data import fred_series, retry
    from fund.factors import RF_SERIES
    return retry(lambda: fred_series(RF_SERIES), attempts=2) or []


def now_kst():
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).strftime(
        '%Y-%m-%d %H:%M KST')


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--outdir', default='data')
    args = ap.parse_args(argv)
    from fund import factors_check
    from fund.calendar import load as load_holidays
    holidays = load_holidays(os.path.join(args.outdir, 'market_holidays.json'))
    if holidays is None:
        print('market_holidays.json missing or invalid — cannot build the session calendar')
        return 1
    try:
        return factors_check.run(args.outdir, holidays, fetch_zip, fetch_histories, fetch_rf,
                                 now_kst)
    except Exception as e:
        print(f'fund factor check failed: {e}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
