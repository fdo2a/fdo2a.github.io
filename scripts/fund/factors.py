"""Three-factor exposure of the reference ETFs on ETF proxy factors (FF3 trial).

    R_ETF,d − RF_d = α + β_m (R_VTI,d − RF_d) + β_s SMB_d + β_h HML_d + ε_d

    SMB = IWM − IWB,  HML = ½[(IWD − IWF) + (IWN − IWO)]   (no fallback leg)
    RF  = DGS1MO, (1 + y/100/12)^(1/N) − 1, N = sessions in that calendar month

These are **not** Fama-French factors — an ETF exposure model whose proxies are
compared monthly with the official French file (`factors_check.py`). Internal units are
decimal daily returns; ×100 is display only. Returns are computed per series on the
session calendar first (a gap is None, never a two-day move read as one) and joined by
date; any None in the 252-return window blanks the row. Any RF gap blanks every row —
a varying RF moves both sides of the regression, so there is no "loadings only" mode.

numpy is imported inside the functions. The board never imports this module: its ticker
filter reads `factor_legs.py` (codex impl review 1 #1).
"""

import datetime
import hashlib
import json
import math

MODEL = 'ff3_proxy_v1'
FACTORS_SCHEMA_VERSION = 1
FACTORS_CALCULATION_VERSION = '2026-11-05'
WINDOW = 252
RF_MAX_AGE_DAYS = 7
KAPPA_MAX = 1e6

# RF_SERIES, FACTOR_TICKERS, FACTOR_ONLY live in factor_legs.py (no imports) so the board
# path never needs this module to import.
from fund.factor_legs import FACTOR_ONLY, FACTOR_TICKERS, RF_SERIES  # noqa: E402,F401

PROXIES = {'mkt': 'VTI−RF', 'smb': 'IWM−IWB', 'hml': '½[(IWD−IWF)+(IWN−IWO)]'}
RF_CONVENTION = '(1+y/100/12)^(1/N)−1'
# Russell US index reconstitution, effective after the close of these dates (spec v2 §2-3:
# 2026-06-26, and the first semi-annual one 2026-12-11).
RECONSTITUTIONS = ('2026-06-26', '2026-12-11')


def sha_json(obj):
    """sha256 of canonical JSON — one helper so daily and monthly hashes compare."""
    raw = json.dumps(obj, sort_keys=True, ensure_ascii=False, allow_nan=False,
                     separators=(',', ':'))
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


# --- OLS -----------------------------------------------------------------------

def _unavailable(reason, n, kappa=None):
    return {'status': 'unavailable', 'reason': reason, 'beta': None, 'se': None,
            'r2': None, 'n': n, 'kappa': kappa}


def ols(X, y):
    """OLS of y on X (column 0 = intercept) by SVD of the column-normalised design.

    Stages, in this order, each final (spec v3.1 A-3): finite inputs and Var(y) > 0 →
    zero-norm regressor (before normalising) → rank → condition number κ > 1e6 →
    β = V Σ⁻¹ Uᵀ y / c → SE = sqrt(s² Σ_k V_jk²/s_k²) / c with s² = RSS/(n−p) → every
    output finite. inv(XᵀX) is never formed.
    """
    import numpy as np
    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=float)
    n, p = X.shape
    if not (np.all(np.isfinite(X)) and np.all(np.isfinite(y))):
        return _unavailable('non_finite', n)
    if n <= p:
        return _unavailable('too_few_rows', n)
    if not y.max() > y.min():        # Var(y) > 0, exactly (float var of a constant is ≈1e-36)
        return _unavailable('constant_y', n)
    c = np.linalg.norm(X, axis=0)
    if np.any(c[1:] <= 1e-12) or not c[0] > 0:
        return _unavailable('zero_column', n)
    Xs = X / c
    U, s, Vt = np.linalg.svd(Xs, full_matrices=False)
    if np.any(s <= s[0] * 4 * np.finfo(float).eps * n):
        return _unavailable('rank_deficient', n)
    kappa = float(s[0] / s[-1])
    if kappa > KAPPA_MAX:
        return _unavailable('ill_conditioned', n, kappa)
    V = Vt.T
    beta = (V @ ((U.T @ y) / s)) / c
    resid = y - X @ beta
    rss = float(resid @ resid)
    tss = float(((y - y.mean()) ** 2).sum())
    s2 = rss / (n - p)
    se = np.sqrt(s2 * ((V ** 2) / (s ** 2)).sum(axis=1)) / c
    r2 = 1 - rss / tss
    vals = list(beta) + list(se) + [r2, kappa]
    if not all(math.isfinite(float(v)) for v in vals) or np.any(se < 0):
        return _unavailable('non_finite', n, kappa)
    return {'status': 'ok', 'reason': None, 'beta': [float(v) for v in beta],
            'se': [float(v) for v in se], 'r2': float(r2), 'n': n, 'kappa': kappa}


def fit(etf, mkt, smb, hml, rf):
    """The model on decimal daily returns: (etf − rf) on [1, mkt − rf, smb, hml]."""
    import numpy as np
    etf, mkt, smb, hml, rf = (np.asarray(v, dtype=float) for v in (etf, mkt, smb, hml, rf))
    X = np.column_stack([np.ones(len(etf)), mkt - rf, smb, hml])
    return ols(X, etf - rf)


# --- risk-free -----------------------------------------------------------------

def rf_rate(y, n):
    """Annual % yield → daily decimal: compounding over the month's N sessions gives y/100/12."""
    return (1 + y / 100 / 12) ** (1 / n) - 1


def month_sessions(days, holidays):
    """{'YYYY-MM': sessions in that whole calendar month} for every month `days` touch,
    or None when the holiday file does not cover one of them."""
    out = {}
    for ym in sorted({d[:7] for d in days}):
        y, m = int(ym[:4]), int(ym[5:7])
        first = datetime.date(y, m, 1)
        last = (datetime.date(y + (m == 12), m % 12 + 1, 1) - datetime.timedelta(days=1))
        s = _sessions(first.isoformat(), last.isoformat(), holidays)
        if not s:
            return None
        out[ym] = len(s)
    return out


def _sessions(start, end, holidays):
    from fund.calendar import us_sessions
    return us_sessions(start, end, holidays)


def _rf_obs_index(obs, d):
    """Index of the latest observation dated ≤ d and at most RF_MAX_AGE_DAYS old, or None."""
    best = None
    for i, (od, y) in enumerate(obs):
        if od > d:
            break
        best = i
    if best is None:
        return None
    age = (datetime.date.fromisoformat(d) - datetime.date.fromisoformat(obs[best][0])).days
    return best if age <= RF_MAX_AGE_DAYS else None


def clean_rf_obs(obs):
    out = []
    for row in obs or []:
        try:
            d, y = row[0], float(row[1])
        except (TypeError, ValueError, IndexError):
            continue
        if isinstance(d, str) and math.isfinite(y):
            out.append((d, y))
    out.sort(key=lambda r: r[0])
    return out


def rf_by_date(obs, ret_dates, month_n):
    """{return date: daily decimal RF or None}. Session d uses the latest observation
    dated ≤ d if it is at most 7 days old; N is that month's full session count."""
    obs = clean_rf_obs(obs)
    out = {}
    for d in ret_dates:
        i = _rf_obs_index(obs, d)
        n = (month_n or {}).get(d[:7])
        out[d] = rf_rate(obs[i][1], n) if i is not None and n else None
    return out


def rf_obs_used(obs, ret_dates):
    """Observations from the one the first return date used through the window's end —
    the leading observation is kept, so the window can be recomputed offline."""
    obs = clean_rf_obs(obs)
    if not ret_dates:
        return []
    i = _rf_obs_index(obs, ret_dates[0])
    lo = obs[i][0] if i is not None else ret_dates[0]
    return [[d, y] for d, y in obs if lo <= d <= ret_dates[-1]]


# --- returns on the session calendar ----------------------------------------------

def align_prices(series_dates, series_prices, cal):
    """Prices on each calendar session, None where the series has none."""
    pmap = dict(zip(series_dates, series_prices))
    return [pmap.get(d) for d in cal]


def session_returns(prices):
    """Return on session i = p[i]/p[i−1] − 1, None unless both anchors have a price."""
    return [b / a - 1 if a is not None and b is not None else None
            for a, b in zip(prices, prices[1:])]


def _valid_dates(d):
    return all(a < b for a, b in zip(d, d[1:]))


def _good_price(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) and x > 0


def prepare(closes, dates, rf_obs, end, holidays, tickers=None):
    """The inputs one window reads: 253 anchor sessions ending `end`, every series'
    anchor prices (floats exactly as read; None where absent), the RF observations the
    window uses and each window month's full session count.

    Returns (inputs, missing). inputs is None when the calendar cannot be built."""
    tickers = sorted(set(tickers or ([t for _, _, t, _ in _units()] + list(FACTOR_TICKERS))))
    missing = []
    end_d = datetime.date.fromisoformat(end)
    start = (end_d - datetime.timedelta(days=WINDOW * 7 // 5 + 40)).isoformat()
    cal = _sessions(start, end, holidays)
    if not cal or cal[-1] != end or len(cal) < WINDOW + 1:
        missing.append(f'factors: calendar — holiday file does not cover {start}..{end} '
                       f'or {end} is not a session')
        return None, missing
    anchors = cal[-(WINDOW + 1):]
    ms = month_sessions(anchors[1:], holidays)
    if ms is None:
        missing.append('factors: calendar — holiday file does not cover every window month')
        return None, missing
    prices = {}
    for t in tickers:
        c, d = (closes or {}).get(t), (dates or {}).get(t)
        if not c or not d:
            missing.append(f'factors: {t} history missing')
            prices[t] = None
            continue
        if len(c) != len(d) or not _valid_dates(d):
            missing.append(f'factors: {t} dates not strictly increasing or length mismatch')
            prices[t] = None
            continue
        pairs = [(x, y) for x, y in zip(d, c) if _good_price(y)]
        prices[t] = align_prices([x for x, _ in pairs], [float(y) for _, y in pairs], anchors)
    rf = {'series': RF_SERIES, 'obs': rf_obs_used(rf_obs, anchors[1:]), 'month_sessions': ms}
    return {'calendar': {'sessions': anchors}, 'prices': prices, 'rf': rf}, missing


def _units():
    from fund.universe import UNITS
    return UNITS


def _gaps(rets, ret_dates, k=3):
    gone = [d for d, r in zip(ret_dates, rets) if r is None]
    return ', '.join(gone[:k]) + (f' (+{len(gone) - k})' if len(gone) > k else '')


def proxy_factors(inputs):
    """(ret_dates, returns{t: list}, mkt, smb, hml, rf) on decimal returns, None per
    day where any leg is missing, plus the `missing` lines for the factor legs."""
    anchors = inputs['calendar']['sessions']
    ret_dates = anchors[1:]
    rets = {t: (session_returns(p) if p is not None else [None] * len(ret_dates))
            for t, p in inputs['prices'].items()}
    missing = []
    for t in FACTOR_TICKERS:
        if t in rets and inputs['prices'].get(t) is not None and None in rets[t]:
            missing.append(f'factors: {t} no return on {_gaps(rets[t], ret_dates)}')
    rf_map = rf_by_date(inputs['rf']['obs'], ret_dates, inputs['rf']['month_sessions'])
    rf = [rf_map[d] for d in ret_dates]
    if None in rf:
        missing.append(f'factors: RF {inputs["rf"]["series"]} missing or older than '
                       f'{RF_MAX_AGE_DAYS} days on {_gaps(rf, ret_dates)}')
    leg = lambda t: rets.get(t) or [None] * len(ret_dates)
    mkt, smb, hml = [], [], []
    for i in range(len(ret_dates)):
        v = {t: leg(t)[i] for t in FACTOR_TICKERS}
        ok = all(x is not None for x in v.values())
        mkt.append(v['VTI'] if ok else None)
        smb.append(v['IWM'] - v['IWB'] if ok else None)
        hml.append(((v['IWD'] - v['IWF']) + (v['IWN'] - v['IWO'])) / 2 if ok else None)
    return ret_dates, rets, mkt, smb, hml, rf, missing


def _row(uid, res, reason=None):
    keys = ('b_mkt', 'se_mkt', 'b_smb', 'se_smb', 'b_hml', 'se_hml', 'alpha_d', 'r2',
            'n', 'kappa')
    if res is None or res['status'] != 'ok':
        out = {k: None for k in keys}
        out.update(id=uid, status='unavailable',
                   reason=reason or (res or {}).get('reason'),
                   kappa=(res or {}).get('kappa'))
        return out
    b, se = res['beta'], res['se']
    return {'id': uid, 'status': 'ok', 'b_mkt': b[1], 'se_mkt': se[1], 'b_smb': b[2],
            'se_smb': se[2], 'b_hml': b[3], 'se_hml': se[3], 'alpha_d': b[0],
            'r2': res['r2'], 'n': res['n'], 'kappa': res['kappa'], 'reason': None}


def regress_rows(ret_dates, rets, mkt, smb, hml, rf, missing):
    """One row per universe ETF, in universe order. A factor or RF gap blanks every row
    (reason factor_missing / rf_missing); an ETF gap blanks only that row."""
    rows = []
    factor_gap = any(x is None for x in mkt + smb + hml)
    rf_gap = any(x is None for x in rf)
    for uid, _, t, _ in _units():
        if rf_gap:
            rows.append(_row(uid, None, 'rf_missing'))
            continue
        if factor_gap:
            rows.append(_row(uid, None, 'factor_missing'))
            continue
        r = rets.get(t)
        if r is None or None in r:
            rows.append(_row(uid, None, 'price_gap'))
            missing.append(f'factors: {t} price gap'
                           + (f' on {_gaps(r, ret_dates)}' if r is not None else ' (no usable history)'))
            continue
        res = fit(r, mkt, smb, hml, rf)
        if res['status'] != 'ok':
            missing.append(f'factors: {t} {res["reason"]}')
        rows.append(_row(uid, res))
    return rows


def window_of(inputs):
    ret_dates = inputs['calendar']['sessions'][1:]
    return {'start': ret_dates[0], 'end': ret_dates[-1], 'n': len(ret_dates)}


def inputs_hashes(inputs):
    return {'prices': {t: sha_json(p) for t, p in inputs['prices'].items()},
            'rf': sha_json(inputs['rf']['obs']),
            'calendar': sha_json({'sessions': inputs['calendar']['sessions'],
                                  'month_sessions': inputs['rf']['month_sessions']})}


def status_of(rows):
    ok = sum(r['status'] == 'ok' for r in rows)
    return 'ok' if ok == len(rows) and rows else ('partial' if ok else 'unavailable')


def compute_daily(closes, dates, rf_obs, report_date, holidays):
    """The daily trial object (body, no file header) for the window ending report_date."""
    base = {'model': MODEL, 'window_sessions': WINDOW, 'proxies': dict(PROXIES)}
    inputs, missing = prepare(closes, dates, rf_obs, report_date, holidays)
    if inputs is None:
        return {**base, 'status': 'unavailable', 'missing': missing, 'window': None,
                'rf': {'series': RF_SERIES, 'convention': RF_CONVENTION, 'last_date': None,
                       'n_month': None, 'month_sessions': None},
                'reconstitution_in_window': [], 'inputs_sha256': None,
                'reproducible_offline': False,
                'rows': [_row(uid, None, 'calendar') for uid, _, _, _ in _units()]}
    ret_dates, rets, mkt, smb, hml, rf, more = proxy_factors(inputs)
    missing += more
    rows = regress_rows(ret_dates, rets, mkt, smb, hml, rf, missing)
    w = window_of(inputs)
    obs = inputs['rf']['obs']
    ms = inputs['rf']['month_sessions']
    status = status_of(rows)
    return {**base, 'status': status, 'missing': missing, 'window': w,
            'rf': {'series': RF_SERIES, 'convention': RF_CONVENTION,
                   'last_date': obs[-1][0] if obs else None,
                   'n_month': ms.get(report_date[:7]), 'month_sessions': ms},
            'reconstitution_in_window': [d for d in RECONSTITUTIONS
                                         if inputs['calendar']['sessions'][0] <= d < w['end']],
            'inputs_sha256': inputs_hashes(inputs), 'reproducible_offline': False,
            'rows': rows}
