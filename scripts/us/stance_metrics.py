"""Metrics the stance triggers are judged against.

`compute()` is pure: it takes close-price histories (plain lists, oldest first) plus
the already-built market_data dict and returns a flat {name: number|None} map. The
network side lives in collect_market_data.py, so this stays testable offline.

A metric that cannot be computed comes back as None rather than being omitted — the
trigger evaluator turns that into UNKNOWN, which can never justify adding risk.
"""

# Extra history tickers beyond what market_data already covers.
HISTORY_TICKERS = [
    '^GSPC', '^IXIC', '^RUT', '^VIX', 'IVW', 'IVE',
    'DX-Y.NYB', 'KRW=X', 'JPY=X', 'EURUSD=X',
    'CL=F', 'BZ=F', 'GC=F',
    'MU', 'WDC', 'STX',
    'MRVL', 'COHR', 'LITE', 'GEV', 'VRT',
]

MEMORY_BASKET = ('MU', 'WDC', 'STX')       # US-listed only — KRW names trade a session apart
AI_INFRA_BASKET = ('MRVL', 'COHR', 'LITE', 'GEV', 'VRT')

_R2 = 2


def _series(closes, ticker):
    s = (closes or {}).get(ticker)
    if not s:
        return None
    s = [float(x) for x in s if x is not None]
    return s or None


def pct_change(closes, ticker, n):
    """Percent change over n sessions."""
    s = _series(closes, ticker)
    if s is None or len(s) < n + 1 or s[-(n + 1)] == 0:
        return None
    return round((s[-1] / s[-(n + 1)] - 1) * 100, _R2)


def vs_dma_pct(closes, ticker, n):
    """Distance of the last close from its n-session moving average, in percent."""
    s = _series(closes, ticker)
    if s is None or len(s) < n:
        return None
    dma = sum(s[-n:]) / n
    if dma == 0:
        return None
    return round((s[-1] / dma - 1) * 100, _R2)


def last(closes, ticker):
    s = _series(closes, ticker)
    return round(s[-1], _R2) if s else None


def abs_change(closes, ticker, n):
    """Level change over n sessions, in the series' own units (VIX points, etc.)."""
    s = _series(closes, ticker)
    if s is None or len(s) < n + 1:
        return None
    return round(s[-1] - s[-(n + 1)], _R2)


def basket_rel(closes, tickers, bench, n):
    """Equal-weight basket return minus benchmark return over n sessions, in %p."""
    legs = [pct_change(closes, t, n) for t in tickers]
    legs = [x for x in legs if x is not None]
    b = pct_change(closes, bench, n)
    if not legs or b is None:
        return None
    return round(sum(legs) / len(legs) - b, _R2)


def _spread(a, b):
    return None if a is None or b is None else round(a - b, _R2)


def _yield_metrics(market_data):
    out = {}
    yields = (market_data or {}).get('yields') or {}
    for tenor in ('2Y', '5Y', '10Y', '30Y'):
        row = yields.get(tenor) or {}
        level = row.get('level')
        week = row.get('week_ago')
        key = f'ust{tenor.lower()}'
        out[key] = round(level, 3) if level is not None else None
        out[f'{key}_chg_5d_bp'] = (round((level - week) * 100, 1)
                                   if level is not None and week is not None else None)
    for name in ('spread_2s10s_bp', 'spread_5s30s_bp'):
        v = (market_data or {}).get(name)
        out[name] = round(v, 1) if v is not None else None
    # 5s30s is the one curve measure whose legs share a quote date (both Yahoo spot),
    # so it is the only spread whose 5-day change is a clean like-for-like.
    y5, y30 = yields.get('5Y') or {}, yields.get('30Y') or {}
    if all(x is not None for x in (y5.get('week_ago'), y30.get('week_ago'))):
        prior = (y30['week_ago'] - y5['week_ago']) * 100
        out['spread_5s30s_chg_5d_bp'] = (round(out['spread_5s30s_bp'] - prior, 1)
                                         if out.get('spread_5s30s_bp') is not None else None)
    else:
        out['spread_5s30s_chg_5d_bp'] = None
    return out


def _breadth(market_data):
    sectors = (market_data or {}).get('sectors') or {}
    up_1d = [1 for r in sectors.values() if r and r.get('pct') is not None and r['pct'] > 0]
    perf = (market_data or {}).get('sector_performance') or {}
    up_1m = [1 for r in perf.values() if r and r.get('1M') is not None and r['1M'] > 0]
    return {
        'sectors_up_1d': len(up_1d) if sectors else None,
        'sectors_up_1m': len(up_1m) if perf else None,
    }


def compute(closes, market_data):
    m = {}

    for key, ticker in (('spx', '^GSPC'), ('ndx', '^IXIC'), ('rut', '^RUT')):
        m[f'{key}_vs_20dma_pct'] = vs_dma_pct(closes, ticker, 20)
        m[f'{key}_vs_50dma_pct'] = vs_dma_pct(closes, ticker, 50)
    m['spx_pct_5d'] = pct_change(closes, '^GSPC', 5)
    m['spx_pct_20d'] = pct_change(closes, '^GSPC', 20)
    m['vix_close'] = last(closes, '^VIX')
    m['vix_chg_5d'] = abs_change(closes, '^VIX', 5)
    m['growth_value_spread_5d'] = _spread(pct_change(closes, 'IVW', 5),
                                          pct_change(closes, 'IVE', 5))

    m.update(_breadth(market_data))
    m.update(_yield_metrics(market_data))

    for key, ticker in (('dxy', 'DX-Y.NYB'), ('usdjpy', 'JPY=X'),
                        ('usdkrw', 'KRW=X'), ('eurusd', 'EURUSD=X')):
        m[f'{key}_close'] = last(closes, ticker)
        m[f'{key}_pct_5d'] = pct_change(closes, ticker, 5)
    m['dxy_pct_20d'] = pct_change(closes, 'DX-Y.NYB', 20)

    for key, ticker in (('wti', 'CL=F'), ('brent', 'BZ=F'), ('gold', 'GC=F')):
        m[f'{key}_close'] = last(closes, ticker)
        m[f'{key}_pct_5d'] = pct_change(closes, ticker, 5)
    m['wti_pct_20d'] = pct_change(closes, 'CL=F', 20)
    m['gold_pct_20d'] = pct_change(closes, 'GC=F', 20)

    for key, basket in (('memory', MEMORY_BASKET), ('ai_infra', AI_INFRA_BASKET)):
        m[f'{key}_rel_5d'] = basket_rel(closes, basket, '^GSPC', 5)
        m[f'{key}_rel_20d'] = basket_rel(closes, basket, '^GSPC', 20)

    return m
