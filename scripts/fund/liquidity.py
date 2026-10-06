"""Liquidity axis: a simple Fed-balance-sheet proxy plus NFCI.

Net liquidity = WALCL - TGA - reverse repo, all read on WALCL's Wednesday:

  WALCL      Fed total assets, Wednesday level, millions of dollars
  WDTGAL     Treasury General Account, Wednesday level, millions of dollars
  RRPONTSYD  overnight reverse repo, daily, billions of dollars
  NFCI       Chicago Fed financial conditions, weekly (Friday); higher = tighter

Units are a static contract (FRED series pages, 2026-10-06) rather than metadata
fetched at run time — the keyless CSV fallback carries no units. WDTGAL, not the
weekly-average WTREGEN, so all three legs are Wednesday levels.

Each leg contributes a signal pointed the same way: +1 is easier. Net liquidity
rising is +1; NFCI rising is tighter, so its signal is -sign(change). Direction is
called only when both agree; disagreement is 중립 and a missing leg is None — a
gap is never read as neutral.
"""

import datetime
import math

WEEKS = 4
MILLION_TO_BILLION = 1 / 1000
RRP_STALE_DAYS = 4


def _clean(series):
    """Drop missing and non-finite values before anything is computed — a NaN that
    survives to `_sign` reads as a direction."""
    return [(d, v) for d, v in (series or [])
            if isinstance(v, (int, float)) and math.isfinite(v)]


def _date_minus_days(d, days):
    return (datetime.date.fromisoformat(d) - datetime.timedelta(days=days)).isoformat()


def _days_between(a, b):
    return (datetime.date.fromisoformat(b) - datetime.date.fromisoformat(a)).days


def _on_or_before(series, date):
    best = None
    for d, v in series:
        if d <= date:
            best = (d, v)
    return best


def _net_at(walcl, tga, rrp, date):
    w = dict(walcl).get(date)
    t = dict(tga).get(date)
    r = _on_or_before(rrp, date)
    # reverse repo is daily; a value more than RRP_STALE_DAYS old is not that Wednesday's
    if w is None or t is None or r is None or _days_between(r[0], date) > RRP_STALE_DAYS:
        return None
    level = w * MILLION_TO_BILLION - t * MILLION_TO_BILLION - r[1]
    return level, {'walcl': {'date': date, 'value_m': w},
                   'tga': {'date': date, 'value_m': t},
                   'rrp': {'date': r[0], 'value_bn': r[1]}}


def _sign(x):
    if x is None:
        return None
    if x == 0:
        return 0
    return 1 if x > 0 else -1


def build(series):
    series = series or {}
    walcl = _clean(series.get('WALCL'))
    tga = _clean(series.get('WDTGAL'))
    rrp = _clean(series.get('RRPONTSYD'))
    nf = _clean(series.get('NFCI'))
    if not (walcl or tga or rrp or nf):
        return None

    net, raw_net_chg = None, None
    if walcl:
        date = walcl[-1][0]
        now = _net_at(walcl, tga, rrp, date)
        if now:
            level, comps = now
            then_date = _date_minus_days(date, 7 * WEEKS)
            then = _net_at(walcl, tga, rrp, then_date)
            raw_net_chg = (level - then[0]) if then else None
            net = {'date': date, 'level_bn': round(level, 1),
                   'comparison_date': then_date if then else None,
                   'chg_4w_bn': round(raw_net_chg, 1) if then else None,
                   'components': comps}

    nfci, raw_nfci_chg = None, None
    if nf:
        want = _date_minus_days(nf[-1][0], 7 * WEEKS)
        prev = next(((d, v) for d, v in nf if d == want), None)
        raw_nfci_chg = (nf[-1][1] - prev[1]) if prev else None
        nfci = {'date': nf[-1][0], 'level': round(nf[-1][1], 3),
                'comparison_date': prev[0] if prev else None,
                'chg_4w': round(nf[-1][1] - prev[1], 3) if prev else None,
                'looser_than_average': nf[-1][1] < 0}

    # signals read the raw change; rounding is for display only
    sig_net = _sign(raw_net_chg) if net else None
    sig_nfci = -_sign(raw_nfci_chg) if raw_nfci_chg is not None else None
    if sig_net is None or sig_nfci is None:
        direction = None
    elif sig_net == sig_nfci == 1:
        direction = '완화'
    elif sig_net == sig_nfci == -1:
        direction = '긴축'
    else:
        direction = '중립'
    return {'net': net, 'nfci': nfci,
            'signals': {'net': sig_net, 'nfci': sig_nfci},
            'direction': direction,
            'basis': '연준 대차대조표 기반 단순 대리 지표(총자산 − TGA − 역레포, 수요일 기준)'}


SERIES = ('WALCL', 'WDTGAL', 'RRPONTSYD', 'NFCI')
