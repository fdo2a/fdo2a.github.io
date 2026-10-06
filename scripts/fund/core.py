"""Assemble data/fund_board.json — the one contract the renderer and the gate read.

Always returns a dict, even when nothing could be computed: the collector writes it
with status 'unavailable' so a stale file from yesterday can never stand in for
today. 'partial' means the board renders but a block is missing (listed in
`missing`); the section is still owed.
"""

import hashlib
import json
import math

from fund import board, calendar, liquidity, regime
from fund.universe import BENCHMARK

SCHEMA_VERSION = 1
CALCULATION_VERSION = '2026-10-06'
UNIVERSE_VERSION = '2026-10-06'
VAR_META = {'lookback_sessions': 60, 'holding_sessions': 1,
            'method': 'historical', 'quantile': 'linear'}


def _finite(obj):
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: _finite(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_finite(v) for v in obj]
    return obj


def digest(data):
    """sha256[:12] of the canonical JSON — the board block carries it."""
    raw = json.dumps(data, sort_keys=True, ensure_ascii=False, allow_nan=False,
                     separators=(',', ':'))
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:12]


def _clean_series(closes, dates):
    """Drop non-finite closes with their dates, so every reading sees real sessions."""
    out_c, out_d = {}, {}
    for t, c in (closes or {}).items():
        d = (dates or {}).get(t)
        if not c or not d or len(c) != len(d):
            continue
        pairs = [(x, y) for x, y in zip(c, d)
                 if x is not None and isinstance(x, (int, float)) and math.isfinite(x) and x > 0]
        if pairs:
            out_c[t] = [x for x, _ in pairs]
            out_d[t] = [y for _, y in pairs]
    return out_c, out_d


def build(closes, dates, market, fred, report_date, generated_at, holidays=None):
    missing = []
    # date contract on the RAW input, before NaN rows are dropped — a duplicate date
    # carrying a NaN would otherwise vanish with it
    bad = sorted(t for t, d in (dates or {}).items()
                 if d and (not board.valid_dates(d) or len(d) != len((closes or {}).get(t) or [])))
    closes = {t: c for t, c in (closes or {}).items() if t not in bad}
    dates = {t: d for t, d in (dates or {}).items() if t not in bad}
    for t in bad:
        missing.append(f'prices: {t} dates not strictly increasing or length mismatch')
    closes, dates = _clean_series(closes, dates)
    head = {'schema_version': SCHEMA_VERSION, 'calculation_version': CALCULATION_VERSION,
            'universe_version': UNIVERSE_VERSION, 'report_date': report_date,
            'generated_at': generated_at, 'var_meta': VAR_META}

    spy_d = dates.get(BENCHMARK)
    spy_as_of = spy_d[-1] if spy_d else None
    fatal = []
    if not spy_d:
        fatal.append('prices: SPY history missing')
    elif spy_as_of != report_date:
        fatal.append(f'prices: SPY last session {spy_as_of} != report_date {report_date}')
    if fatal:
        missing += fatal
        return _finite({**head, 'status': 'unavailable', 'missing': missing,
                        'source_dates': {'prices': spy_as_of}, 'market_regime': None,
                        'liquidity': None, 'risk': None, 'units': [], 'rank_basis': None})

    good = {t: d for t, d in dates.items() if board.valid_dates(d)}
    if BENCHMARK not in good:
        missing.append('prices: SPY dates not strictly increasing')
        return _finite({**head, 'status': 'unavailable', 'missing': missing,
                        'source_dates': {'prices': spy_as_of}, 'market_regime': None,
                        'liquidity': None, 'risk': None, 'units': [], 'rank_basis': None})
    cal = calendar.us_sessions(dates[BENCHMARK][0], spy_as_of, holidays)
    cal_basis = 'NYSE 휴장일 달력' if cal else '펀드 유니버스 과반'
    if cal is None:
        # weaker: a session every series lost cannot be seen — say so, the day is partial
        missing.append('calendar: holiday file missing or out of range — fund-universe majority '
                       'used; a session all series lack would go unseen')
        cal = board.sessions(good)
    if not cal or cal[-1] != spy_as_of:
        missing.append(f'prices: session calendar ends {cal[-1] if cal else None}, SPY {spy_as_of}')
        return _finite({**head, 'status': 'unavailable', 'missing': missing,
                        'source_dates': {'prices': spy_as_of}, 'market_regime': None,
                        'liquidity': None, 'risk': None, 'units': [], 'rank_basis': None})
    units, basis = board.build_units(closes, dates, cal)
    basis['calendar'] = cal_basis
    if not basis['n']:
        missing.append('units: no row measurable today and five sessions ago')
        return _finite({**head, 'status': 'unavailable', 'missing': missing,
                        'source_dates': {'prices': spy_as_of}, 'market_regime': None,
                        'liquidity': None, 'risk': None, 'units': units, 'rank_basis': basis})

    for u in units:
        if u['status'] != 'ok':
            missing.append(f"units: {u['ticker']} {u['status']}")
    mr = regime.compute(closes[BENCHMARK], dates[BENCHMARK], cal)
    if mr is None:
        missing.append('market_regime: not enough SPY history')
    elif mr['missing_sessions']:
        missing.append(f"market_regime: SPY lacks sessions {', '.join(mr['missing_sessions'])}")
    liq = liquidity.build(fred)
    if not liq or liq['net'] is None or liq['nfci'] is None:
        missing.append('liquidity: series missing')
    risk = board.risk_strip(market)
    for k, v in risk.items():
        if v is None:
            missing.append(f'risk: {k} missing')

    source_dates = {'prices': spy_as_of,
                    'net_liquidity': ((liq or {}).get('net') or {}).get('date'),
                    'nfci': ((liq or {}).get('nfci') or {}).get('date'),
                    'hy_spread': (risk.get('hy_spread') or {}).get('date'),
                    'real_10y': (risk.get('real_10y') or {}).get('date')}
    return _finite({**head, 'status': 'partial' if missing else 'ok', 'missing': missing,
                    'source_dates': source_dates, 'market_regime': mr, 'liquidity': liq,
                    'risk': risk, 'units': units, 'rank_basis': basis})
