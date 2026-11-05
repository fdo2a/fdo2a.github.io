"""FF3 proxy-factor regression (trial). Spec v2 §3, v3 §2·§10, v3.1 A-3."""

import datetime
import math
import os

import numpy as np
import pytest

from fund import calendar, factors, universe

HOLIDAYS = {'valid_from': '2020-01-01', 'valid_through': '2030-12-31', 'dates': []}


# --- OLS ---------------------------------------------------------------------

def design(m, s, h):
    return np.column_stack([np.ones(len(m)), m, s, h])


def codex3_input():
    t = np.arange(252)
    m, s, h = .01 * np.sin(.11 * t), .01 * np.cos(.17 * t), .01 * np.sin(.23 * t)
    y = .002 + 1.8 * m + .3 * s - .25 * h + .001 * np.sin(.33 * t)
    return design(m, s, h), y


def reference_se(X, y):
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    s2 = resid @ resid / (len(y) - X.shape[1])
    return beta, np.sqrt(s2 * np.diag(np.linalg.pinv(X.T @ X)))


def test_ols_matches_hand_computed_three_regressors():
    rng = np.random.default_rng(1)
    m, s, h = rng.normal(0, .01, (3, 20))
    y = .001 + 1.2 * m - .4 * s + .7 * h + rng.normal(0, .002, 20)
    X = design(m, s, h)
    hand = np.linalg.solve(X.T @ X, X.T @ y)
    out = factors.ols(X, y)
    assert out['status'] == 'ok' and out['n'] == 20
    assert np.allclose(out['beta'], hand, rtol=0, atol=1e-8)


def test_se_r2_dof_248():
    rng = np.random.default_rng(2)
    m, s, h = rng.normal(0, .01, (3, 252))
    y = .0005 + .9 * m + .2 * s - .1 * h + rng.normal(0, .003, 252)
    X = design(m, s, h)
    out = factors.ols(X, y)
    beta, _ = reference_se(X, y)
    resid = y - X @ beta
    rss = resid @ resid
    s2 = rss / 248                       # n − 4
    se = np.sqrt(s2 * np.diag(np.linalg.inv(X.T @ X)))
    assert np.allclose(out['se'], se, rtol=1e-9, atol=0)
    assert out['r2'] == pytest.approx(1 - rss / ((y - y.mean()) ** 2).sum(), abs=1e-12)


def test_se_matches_statsmodels_style_reference_on_well_conditioned_input():
    X, y = codex3_input()
    out = factors.ols(X, y)
    assert out['status'] == 'ok'
    assert out['kappa'] == pytest.approx(1.1869828, rel=1e-6)
    _, ref = reference_se(X, y)
    assert np.max(np.abs(np.array(out['se']) - ref) / ref) <= 1e-9
    assert out['se'][1] == pytest.approx(0.006343528638054, rel=1e-9)


def test_perfect_fit_r2_one_se_zero():
    rng = np.random.default_rng(3)
    m, s, h = rng.normal(0, .01, (3, 252))
    y = .001 + 1.5 * m + .3 * s - .2 * h
    out = factors.ols(design(m, s, h), y)
    assert out['status'] == 'ok'
    assert out['r2'] == pytest.approx(1.0, abs=1e-12)
    assert max(out['se']) < 1e-10


def test_constant_y_unavailable():
    rng = np.random.default_rng(4)
    m, s, h = rng.normal(0, .01, (3, 252))
    out = factors.ols(design(m, s, h), np.full(252, .001))
    assert (out['status'], out['reason']) == ('unavailable', 'constant_y')


@pytest.mark.parametrize('bad', [float('nan'), float('inf'), -float('inf')])
def test_nan_inf_unavailable(bad):
    X, y = codex3_input()
    y = y.copy()
    y[100] = bad
    assert factors.ols(X, y)['reason'] == 'non_finite'
    X2 = X.copy()
    X2[7, 2] = bad
    assert factors.ols(X2, codex3_input()[1])['reason'] == 'non_finite'


def test_hml_equals_smb_is_rank_deficient_not_ill_conditioned():
    X, y = codex3_input()
    X = X.copy()
    X[:, 3] = X[:, 2]
    out = factors.ols(X, y)
    assert (out['status'], out['reason']) == ('unavailable', 'rank_deficient')


def test_codex_near_collinear_matrix_is_ill_conditioned_not_negative_se():
    t = np.arange(252)
    m, s = .01 * np.sin(.11 * t), .01 * np.cos(.17 * t)
    h = s + 5e-11 * np.sin(.23 * t)
    y = .002 + 1.8 * m + .3 * s + .001 * np.sin(.33 * t)
    out = factors.ols(design(m, s, h), y)
    assert (out['status'], out['reason']) == ('unavailable', 'ill_conditioned')
    assert out['beta'] is None and out['se'] is None


def test_threshold_passes_realistic_correlation_0_9():
    rng = np.random.default_rng(5)
    m = rng.normal(0, .01, 252)
    s = .9 * m + math.sqrt(1 - .81) * rng.normal(0, .01, 252)
    h = rng.normal(0, .01, 252)
    y = 1.1 * m + rng.normal(0, .003, 252)
    out = factors.ols(design(m, s, h), y)
    assert out['status'] == 'ok' and out['kappa'] < 100


def test_zero_column_before_normalisation():
    X, y = codex3_input()
    X = X.copy()
    X[:, 3] = 0.0
    with np.errstate(all='raise'):          # nothing may divide by the zero norm first
        out = factors.ols(X, y)
    assert out['reason'] == 'zero_column'


def test_check_order_is_finite_norm_rank_kappa():
    X, y = codex3_input()
    # each input trips exactly one stage; a later stage would also trip on some of them
    a = X.copy(); a[:, 3] = 0.0; a[0, 1] = float('nan')          # non-finite AND zero col
    b = X.copy(); b[:, 3] = 0.0                                   # zero col (rank 3 too)
    c = X.copy(); c[:, 3] = c[:, 2]                               # rank (κ infinite too)
    t = np.arange(252)
    d = X.copy(); d[:, 3] = d[:, 2] + 5e-11 * np.sin(.23 * t)     # κ only
    assert [factors.ols(v, y)['reason'] for v in (a, b, c, d)] == [
        'non_finite', 'zero_column', 'rank_deficient', 'ill_conditioned']


def test_all_outputs_finite_or_unavailable():
    rng = np.random.default_rng(6)
    for i in range(200):
        n = 252
        scale = 10.0 ** rng.uniform(-8, 2)
        X = design(*rng.normal(0, scale, (3, n)))
        if i % 3 == 0:
            X[:, 3] = X[:, 2] * (1 + 10.0 ** rng.uniform(-14, -2) * rng.normal(size=n))
        y = rng.normal(0, scale, n)
        out = factors.ols(X, y)
        if out['status'] == 'ok':
            vals = out['beta'] + out['se'] + [out['r2'], out['kappa']]
            assert all(math.isfinite(v) for v in vals)
            assert all(v >= 0 for v in out['se'])
        else:
            assert out['reason']


# --- RF ------------------------------------------------------------------------

def test_rf_conversion_rhs_is_y_over_100_over_12():
    rf = factors.rf_rate(4.05, 21)
    assert (1 + rf) ** 21 - 1 == pytest.approx(4.05 / 100 / 12, rel=1e-12)
    assert 4.05 / 100 / 12 == pytest.approx(0.003375)


def test_rf_age_7_ok_8_missing():
    ms = {'2026-09': 21}
    obs = [('2026-09-01', 4.0)]
    got = factors.rf_by_date(obs, ['2026-09-08', '2026-09-09'], ms)
    assert got['2026-09-08'] == factors.rf_rate(4.0, 21)       # 7 days old
    assert got['2026-09-09'] is None                           # 8 days old


def test_rf_n_is_full_calendar_month_not_sessions_to_date():
    here = os.path.dirname(__file__)
    hol = calendar.load(os.path.join(here, '..', '..', '..', 'data', 'market_holidays.json'))
    ms = factors.month_sessions(['2026-11-02', '2026-11-03', '2026-11-04'], hol)
    closed = set(hol['dates'])
    d, n = datetime.date(2026, 11, 1), 0
    while d.month == 11:
        n += d.weekday() < 5 and d.isoformat() not in closed
        d += datetime.timedelta(days=1)
    assert ms == {'2026-11': n}
    assert n > 3 and n == 20                      # Thanksgiving 11/26 is closed


def test_month_sessions_cover_every_window_month():
    days = weekdays(253, datetime.date(2026, 9, 30))
    ms = factors.month_sessions(days, HOLIDAYS)
    assert sorted(ms) == sorted({d[:7] for d in days})
    assert factors.month_sessions(days, None) is None


# --- returns-first windows on synthetic histories ------------------------------

def weekdays(n, end=datetime.date(2026, 11, 4)):
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d -= datetime.timedelta(days=1)
    return out[::-1]


ETFS = [t for _, _, t, _ in universe.UNITS]


def synthetic(n=300, seed=7):
    """Histories where every series exists on every weekday; RF observed daily."""
    rng = np.random.default_rng(seed)
    days = weekdays(n)
    mkt, smb, hml = rng.normal(0, .01, (3, n))
    r = {'VTI': mkt, 'IWB': rng.normal(0, .008, n)}
    r['IWM'] = r['IWB'] + smb
    r['IWF'], r['IWO'] = rng.normal(0, .008, (2, n))
    r['IWD'] = r['IWF'] + hml + rng.normal(0, .001, n)
    r['IWN'] = r['IWO'] + hml - (r['IWD'] - r['IWF'] - hml)
    for i, t in enumerate(ETFS):
        if t in r:
            continue
        b = rng.uniform(.3, 1.6, 3)
        r[t] = b[0] * mkt + b[1] * .3 * smb + (b[2] - 1) * hml + rng.normal(0, .004, n)
    closes = {t: list(100 * np.cumprod(1 + v)) for t, v in r.items()}
    dates = {t: list(days) for t in closes}
    rf = [(d, 4.0 + .01 * (i % 5)) for i, d in enumerate(days)]
    return closes, dates, rf, days


def daily(closes, dates, rf, report_date, holidays=HOLIDAYS):
    return factors.compute_daily(closes, dates, rf, report_date, holidays)


def row(out, ticker):
    uid = next(u for u, _, t, _ in universe.UNITS if t == ticker)
    return next(r for r in out['rows'] if r['id'] == uid)


def drop(closes, dates, t, day):
    k = dates[t].index(day)
    closes[t] = closes[t][:k] + closes[t][k + 1:]
    dates[t] = dates[t][:k] + dates[t][k + 1:]


def test_clean_synthetic_day_is_ok_with_28_rows():
    c, d, rf, days = synthetic()
    out = daily(c, d, rf, days[-1])
    assert out['status'] == 'ok' and out['missing'] == []
    assert len(out['rows']) == 28 and all(r['status'] == 'ok' for r in out['rows'])
    assert out['window'] == {'start': days[-252], 'end': days[-1], 'n': 252}
    assert all(r['n'] == 252 for r in out['rows'])
    # the factor legs explain themselves: IWM's SMB loading is large and positive
    assert row(out, 'IWM')['b_smb'] > .5


def test_returns_first_then_join_two_day_gap_is_none():
    cal = ['d1', 'd2', 'd3', 'd4']
    prices = [100.0, None, 110.0, 121.0]
    assert factors.session_returns(prices) == [None, None, pytest.approx(.1)]
    assert factors.align_prices(['d1', 'd3', 'd4'], [100.0, 110.0, 121.0], cal) == prices


def test_252_prices_yield_251_returns_row_unavailable():
    c, d, rf, days = synthetic()
    first_anchor = days[-253]
    drop(c, d, 'SMH', first_anchor)
    out = daily(c, d, rf, days[-1])
    assert row(out, 'SMH')['status'] == 'unavailable'
    assert row(out, 'SMH')['reason'] == 'price_gap'
    assert out['status'] == 'partial'


def test_missing_middle_session_in_one_etf_blanks_only_that_row():
    c, d, rf, days = synthetic()
    drop(c, d, 'XLE', days[-100])
    out = daily(c, d, rf, days[-1])
    assert row(out, 'XLE')['status'] == 'unavailable'
    assert sum(r['status'] == 'ok' for r in out['rows']) == 27
    assert out['status'] == 'partial'
    assert any('XLE' in m for m in out['missing'])


def test_missing_middle_session_in_iwn_blanks_every_row():
    c, d, rf, days = synthetic()
    drop(c, d, 'IWN', days[-100])
    out = daily(c, d, rf, days[-1])
    assert out['status'] == 'unavailable'
    assert all(r['status'] == 'unavailable' and r['reason'] == 'factor_missing'
               for r in out['rows'])
    assert any(m.startswith('factors: IWN') and days[-100] in m for m in out['missing'])


def test_iwn_missing_one_session_unavailable_no_fallback():
    """IWD−IWF alone is still computable that day — it is not used as a fallback HML."""
    c, d, rf, days = synthetic()
    drop(c, d, 'IWN', days[-5])
    out = daily(c, d, rf, days[-1])
    assert row(out, 'SPY')['status'] == 'unavailable'
    assert row(out, 'SPY')['b_hml'] is None


def test_session_absent_in_all_series_is_a_gap_not_a_join():
    c, d, rf, days = synthetic()
    for t in list(c):
        drop(c, d, t, days[-50])
    out = daily(c, d, rf, days[-1])
    assert out['status'] == 'unavailable'
    assert out['window']['n'] == 252 and out['window']['start'] == days[-252]


def test_rf_missing_mid_window_unavailable():
    c, d, rf, days = synthetic()
    gap = set(days[-140:-128])                  # 12 weekdays: > 7 days with no observation
    rf = [(x, y) for x, y in rf if x not in gap]
    out = daily(c, d, rf, days[-1])
    assert out['status'] == 'unavailable'
    assert all(r['reason'] == 'rf_missing' for r in out['rows'])
    assert any(m.startswith('factors: RF') for m in out['missing'])


def test_time_varying_rf_changes_beta():
    """codex 1차 4: a varying RF moves both sides — the excess regression recovers 1.8,
    the same data read with a constant RF does not."""
    t = np.arange(252)
    m = .01 * np.sin(.11 * t)
    s, h = .01 * np.cos(.17 * t), .01 * np.sin(.29 * t)
    rf = .00015 + .00004 * np.sin(.11 * t)
    etf = rf + 1.8 * (m - rf) + .3 * s - .2 * h + .001 * np.sin(.37 * t)
    right = factors.fit(etf, m, s, h, rf)
    wrong = factors.fit(etf, m, s, h, np.full(252, rf.mean()))
    assert right['status'] == wrong['status'] == 'ok'
    assert abs(right['beta'][1] - 1.8) < 1e-3
    assert abs(wrong['beta'][1] - right['beta'][1]) > 1e-3


def test_unsorted_factor_leg_is_rejected_and_listed():
    c, d, rf, days = synthetic()
    d['VTI'] = list(d['VTI'])
    d['VTI'][-2] = d['VTI'][-3]
    out = daily(c, d, rf, days[-1])
    assert out['status'] == 'unavailable'
    assert any(m.startswith('factors: VTI dates') for m in out['missing'])


def test_calendar_outside_holiday_file_is_unavailable():
    c, d, rf, days = synthetic()
    out = daily(c, d, rf, days[-1], holidays=None)
    assert out['status'] == 'unavailable'
    assert any(m.startswith('factors: calendar') for m in out['missing'])


def test_factor_tickers_not_in_rank_universe():
    assert len(universe.UNITS) == 28
    assert not set(factors.FACTOR_ONLY) & set(universe.tickers())
    assert set(factors.FACTOR_TICKERS) - set(factors.FACTOR_ONLY) <= set(universe.tickers())


def test_reconstitution_in_window_listed():
    c, d, rf, days = synthetic()
    out = daily(c, d, rf, days[-1])
    assert out['reconstitution_in_window'] == ['2026-06-26']


def test_inputs_hashes_cover_every_series():
    c, d, rf, days = synthetic()
    out = daily(c, d, rf, days[-1])
    h = out['inputs_sha256']
    assert set(h['prices']) == set(ETFS) | set(factors.FACTOR_TICKERS)
    assert h['rf'] and h['calendar']
    c2 = {t: list(v) for t, v in c.items()}
    c2['SMH'][-1] *= 1.0000001
    assert daily(c2, d, rf, days[-1])['inputs_sha256']['prices']['SMH'] != h['prices']['SMH']
