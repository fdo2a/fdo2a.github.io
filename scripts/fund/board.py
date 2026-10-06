"""Reference-ETF price board: one row of price readings per reference index.

Every reading is anchored on a **session calendar** (NYSE weekdays minus holidays,
fund.calendar; a fund-universe majority vote only outside the holiday file's coverage)
— never on a series' own list positions. A 3-month return is the close on
the last session over the close 63 sessions earlier on that calendar; if an ETF has
no price on either anchor the return is blank. So a missing day inside one ETF's
history cannot stretch its window, every row and SPY measure the same span, and the
rank (3-month return) always agrees with the excess over SPY shown beside it.

Rank is computed on the set measurable both today and five sessions ago, ties by id.
Rank alone does not say a row got stronger — a row can climb while its own excess
falls — so each row also carries the change in its excess return.

The 60-session risk readings, the 50/200-day averages and the 52-week drawdown need a
price on every session of their window; one gap blanks them rather than reading a
two-day move as one day.
"""

from fund import metrics as m
from fund.universe import BENCHMARK, UNITS

LAG = 5
RISK_N = 60

FIELDS = ('ret_1m', 'ret_3m', 'ret_6m', 'ret_12m', 'rel_3m', 'mom_12_1', 'vol_60',
          'var_1d_90', 'var_1d_95', 'beta_60', 'above_50', 'above_200', 'drawdown_52w')


def valid_dates(d):
    """Strictly increasing, no duplicates."""
    return all(a < b for a, b in zip(d, d[1:]))


def sessions(dates):
    """Fallback calendar when the holiday file does not cover the span: dates held by a
    strict majority of the fund universe's series (other pipelines' tickers do not vote).
    The primary calendar is fund.calendar.us_sessions."""
    fund = {t for _, _, t, _ in UNITS}
    series = [d for t, d in (dates or {}).items() if d and t in fund]
    if not series:
        return []
    count = {}
    for d in series:
        for x in set(d):
            count[x] = count.get(x, 0) + 1
    need = len(series) // 2 + 1
    return sorted(x for x, c in count.items() if c >= need)


def _window(pmap, cal, n):
    """Prices on the last n sessions of `cal`, or None if any is missing."""
    if len(cal) < n:
        return None
    out = [pmap.get(d) for d in cal[-n:]]
    return out if all(x is not None for x in out) else None


def _anchored(pmap, cal, h):
    if len(cal) < h + 1:
        return None
    a, b = pmap.get(cal[-1 - h]), pmap.get(cal[-1])
    if a is None or b is None:
        return None
    return (b / a - 1) * 100


def _mom(pmap, cal):
    if len(cal) < m.YEAR + 1:
        return None
    a, b = pmap.get(cal[-1 - m.YEAR]), pmap.get(cal[-1 - m.MONTH])
    if a is None or b is None:
        return None
    return (b / a - 1) * 100


def _readings(pmap, spy, cal):
    r3 = _anchored(pmap, cal, 63)
    s3 = _anchored(spy, cal, 63)
    w51 = _window(pmap, cal, RISK_N + 1)
    sw = _window(spy, cal, RISK_N + 1)
    w200, w50, wyr = _window(pmap, cal, 200), _window(pmap, cal, 50), _window(pmap, cal, m.YEAR)
    last = pmap.get(cal[-1])
    out = {
        'ret_1m': _anchored(pmap, cal, 21),
        'ret_3m': r3,
        'ret_6m': _anchored(pmap, cal, 126),
        'ret_12m': _anchored(pmap, cal, 252),
        'rel_3m': (r3 - s3) if r3 is not None and s3 is not None else None,
        'mom_12_1': _mom(pmap, cal),
        'vol_60': m.vol(w51, RISK_N) if w51 else None,
        'var_1d_90': m.hist_var(w51, RISK_N, 0.90) if w51 else None,
        'var_1d_95': m.hist_var(w51, RISK_N, 0.95) if w51 else None,
        'beta_60': (m.beta(w51, cal[-(RISK_N + 1):], sw, cal[-(RISK_N + 1):], RISK_N)
                    if w51 and sw else None),
        'above_50': (last > sum(w50) / 50) if w50 else None,
        'above_200': (last > sum(w200) / 200) if w200 else None,
        'drawdown_52w': (last / max(wyr) - 1) * 100 if wyr else None,
    }
    why = [] if w51 else ['risk_window']
    return out, why


def _round(v):
    if isinstance(v, float):
        return round(v, 2)
    return v


def _rank(values):
    keyed = sorted(values.items(), key=lambda kv: (-kv[1], kv[0]))
    return {uid: i + 1 for i, (uid, _) in enumerate(keyed)}


def build_units(closes, dates, cal=None):
    """-> (rows, rank_basis). `cal` defaults to sessions(dates)."""
    closes, dates = closes or {}, dates or {}
    good = {t: d for t, d in dates.items() if d and valid_dates(d)
            and closes.get(t) and len(closes[t]) == len(d)}
    cal = cal if cal is not None else sessions(good)
    spy = dict(zip(good[BENCHMARK], closes[BENCHMARK])) if BENCHMARK in good else {}
    as_of = cal[-1] if cal else None
    cal5 = cal[:-LAG] if len(cal) > LAG else []
    date_5d = cal5[-1] if cal5 else None
    rows, now, then, rel_then = {}, {}, {}, {}

    for uid, name, t, kind in UNITS:
        c, d = closes.get(t), dates.get(t)
        row = {'id': uid, 'name': name, 'ticker': t, 'kind': kind,
               **{k: None for k in FIELDS},
               'as_of': d[-1] if d else None, 'observations': len(c) if c else 0,
               'missing_reason': []}
        if not c or not d or not as_of:
            row['status'], row['missing_reason'] = 'missing', ['no_history']
        elif t not in good:
            row['status'], row['missing_reason'] = 'missing', ['dates_not_strictly_increasing']
        elif d[-1] != as_of:
            row['status'] = 'stale'
            row['missing_reason'] = [f'last_session_{d[-1]}_not_{as_of}']
        else:
            row['status'] = 'ok'
            pmap = dict(zip(d, c))
            vals, why = _readings(pmap, spy, cal)
            row.update(vals)
            row['missing_reason'] = why
            if kind != 'benchmark' and vals['ret_3m'] is not None and cal5:
                r5 = _anchored(pmap, cal5, 63)
                if r5 is not None:
                    now[uid], then[uid] = vals['ret_3m'], r5
                    s5 = _anchored(spy, cal5, 63)
                    rel_then[uid] = (r5 - s5) if s5 is not None else None
        rows[uid] = row

    common = set(now) & set(then)
    rank_now = _rank({u: now[u] for u in common})
    rank_then = _rank({u: then[u] for u in common})

    out = []
    for uid, *_ in UNITS:
        row = rows[uid]
        rank, rank5 = rank_now.get(uid), rank_then.get(uid)
        rel5 = rel_then.get(uid) if uid in common else None
        row['rel_3m_5d'] = rel5
        row['rel_3m_chg_pp'] = (row['rel_3m'] - rel5
                                if row['rel_3m'] is not None and rel5 is not None else None)
        row['rank'], row['rank_5d'] = rank, rank5
        row['rank_chg'] = (rank5 - rank) if rank is not None and rank5 is not None else None
        out.append({k: _round(v) for k, v in row.items()})
    basis = {'key': 'ret_3m', 'date': as_of, 'date_5d': date_5d, 'n': len(common),
             'ties': 'id 오름차순'}
    return out, basis


def risk_strip(market):
    market = market or {}
    vix = ((market.get('price_context') or {}).get('levels') or {}).get('VIX')
    rows = (market.get('yield_drivers') or {}).get('rows') or {}

    def yd(key):
        r = rows.get(key)
        if not r:
            return None
        return {'level': r.get('level'), 'date': r.get('date'), 'chg_5d_bp': r.get('chg_5d_bp')}

    return {
        'vix': ({'level': vix.get('value'), 'percentile_2y': vix.get('percentile'),
                 'sessions': vix.get('sessions')} if vix else None),
        'hy_spread': yd('hy_spread'),
        'real_10y': yd('real_10y'),
    }
