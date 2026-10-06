import pytest

from fund import board, universe


def series(n, daily, start=100.0):
    return [start * (1 + daily) ** i for i in range(n)]


def make(n=300):
    dates = [f'2025-{i:04d}' for i in range(n)]
    closes = {t: series(n, 0.0005) for t in universe.tickers()}
    closes['SMH'] = series(n, 0.002)     # strongest
    closes['XLU'] = series(n, -0.001)    # weakest
    return closes, {t: list(dates) for t in closes}


def rows_of(closes, dates):
    rows, basis = board.build_units(closes, dates)
    return {u['id']: u for u in rows}, basis


def test_units_carry_metrics_and_rank_by_3m():
    rows, basis = rows_of(*make())
    assert rows['semis']['rank'] == 1
    ranked = [u for u in rows.values() if u['rank'] is not None]
    assert rows['utilities']['rank'] == len(ranked) == basis['n']
    assert rows['spy']['rank'] is None            # benchmarks are shown, never ranked
    for key in ('ret_1m', 'ret_3m', 'ret_6m', 'ret_12m', 'rel_3m', 'mom_12_1', 'vol_60',
                'var_1d_90', 'var_1d_95', 'beta_60', 'above_50', 'above_200',
                'drawdown_52w', 'as_of', 'observations', 'status'):
        assert key in rows['semis']
    assert rows['spy']['rel_3m'] == pytest.approx(0.0, abs=1e-9)
    assert rows['semis']['status'] == 'ok'
    assert basis['date'] == '2025-0299' and basis['date_5d'] == '2025-0294'


def test_rank_and_excess_change_against_five_sessions_ago():
    n = 300
    closes, dates = make(n)
    closes['IGV'] = series(n - 5, 0.0005) + [closes['IGV'][n - 6] * 1.05 ** i for i in range(1, 6)]
    rows, _ = rows_of(closes, dates)
    sw = rows['software']
    assert sw['rank'] < sw['rank_5d']
    assert sw['rank_chg'] == sw['rank_5d'] - sw['rank']
    assert sw['rel_3m_chg_pp'] == pytest.approx(sw['rel_3m'] - sw['rel_3m_5d'], abs=0.02)
    assert sw['rel_3m_chg_pp'] > 0


def test_missing_ticker_is_listed_not_dropped_and_not_ranked():
    closes, dates = make()
    closes.pop('GRID')
    rows, basis = rows_of(closes, dates)
    assert rows['grid']['status'] == 'missing'
    assert rows['grid']['ret_3m'] is None and rows['grid']['rank'] is None
    assert basis['n'] == len([u for u in universe.UNITS if u[3] != 'benchmark']) - 1


def test_stale_series_blanks_every_metric():
    closes, dates = make()
    closes['XME'] = closes['XME'][:-1]
    dates['XME'] = dates['XME'][:-1]
    rows, _ = rows_of(closes, dates)
    assert rows['metals']['status'] == 'stale'
    assert rows['metals']['as_of'] == '2025-0298'
    assert all(rows['metals'][k] is None for k in ('ret_1m', 'vol_60', 'var_1d_95', 'rank'))


def test_risk_window_needs_the_same_sixty_one_sessions_as_spy():
    closes, dates = make()
    # drop one session inside the last 61 (but keep the last date aligned)
    i = len(dates['ITA']) - 10
    del closes['ITA'][i]
    del dates['ITA'][i]
    rows, _ = rows_of(closes, dates)
    d = rows['defense']
    assert d['status'] == 'ok'
    assert d['ret_1m'] is not None
    assert d['vol_60'] is None and d['var_1d_95'] is None and d['beta_60'] is None
    assert 'risk_window' in d['missing_reason']


def test_ties_break_on_id():
    closes, dates = make()
    for t in universe.tickers():
        closes[t] = series(300, 0.0005)
    rows, _ = rows_of(closes, dates)
    ranked = sorted((u for u in rows.values() if u['rank']), key=lambda u: u['rank'])
    assert [u['id'] for u in ranked] == sorted(u['id'] for u in ranked)


def test_risk_strip_reads_existing_fields_only():
    market = {
        'price_context': {'levels': {'VIX': {'value': 16.4, 'percentile': 35.7, 'sessions': 504}}},
        'yield_drivers': {'rows': {
            'hy_spread': {'level': 3.12, 'date': '2026-09-30', 'chg_5d_bp': 39.0},
            'real_10y': {'level': 2.93, 'date': '2026-09-30', 'chg_5d_bp': 17.0}}},
    }
    s = board.risk_strip(market)
    assert s['vix'] == {'level': 16.4, 'percentile_2y': 35.7, 'sessions': 504}
    assert s['hy_spread'] == {'level': 3.12, 'date': '2026-09-30', 'chg_5d_bp': 39.0}
    assert s['real_10y']['chg_5d_bp'] == 17.0
    assert board.risk_strip({}) == {'vix': None, 'hy_spread': None, 'real_10y': None}


# --- codex 구현 검토 1차 재현: 세션 달력 앵커 ---

def test_sessions_are_dates_held_by_most_series():
    closes, dates = make(10)
    dates['XME'] = dates['XME'][:-1] + ['2099-01-01']
    closes['XME'] = closes['XME'][:-1] + [1.0]
    s = board.sessions(dates)
    assert '2099-01-01' not in s and s == make(10)[1]['SPY']


def test_rank_follows_displayed_excess_when_one_etf_misses_a_day():
    n = 300
    closes, dates = make(n)
    spy = series(n, 0.0005)
    closes['SPY'] = spy
    closes['SMH'] = series(n, 0.0010)
    closes['IGV'] = series(n, 0.00101)
    # SMH misses one session inside the 3-month window
    i = n - 20
    del closes['SMH'][i]
    del dates['SMH'][i]
    rows, _ = rows_of(closes, dates)
    smh, igv = rows['semis'], rows['software']
    assert smh['rel_3m'] < igv['rel_3m']
    assert smh['rank'] > igv['rank']
    # both returns span the same calendar anchors
    assert smh['ret_3m'] is not None


def test_missing_anchor_price_blanks_the_return():
    closes, dates = make()
    i = len(dates['IGV']) - 64          # exactly the 3-month anchor session
    del closes['IGV'][i]
    del dates['IGV'][i]
    rows, _ = rows_of(closes, dates)
    assert rows['software']['ret_3m'] is None and rows['software']['rank'] is None


def test_unsorted_or_duplicate_dates_reject_the_series():
    closes, dates = make()
    dates['SMH'][-2], dates['SMH'][-3] = dates['SMH'][-3], dates['SMH'][-2]
    rows, _ = rows_of(closes, dates)
    assert rows['semis']['status'] == 'missing' and 'dates' in rows['semis']['missing_reason'][0]
    closes, dates = make()
    dates['IGV'][-1] = dates['IGV'][-2]
    rows, _ = rows_of(closes, dates)
    assert rows['software']['status'] == 'missing'


def test_drawdown_needs_a_full_year():
    closes, dates = make(200)
    rows, _ = rows_of(closes, dates)
    assert rows['semis']['drawdown_52w'] is None
