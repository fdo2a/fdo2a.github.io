from us.stance_metrics import (
    abs_change,
    basket_rel,
    compute,
    last,
    pct_change,
    vs_dma_pct,
)


def ramp(start, step, n):
    return [start + step * i for i in range(n)]


CLOSES = {
    '^GSPC': ramp(100.0, 1.0, 60),      # 100 -> 159
    '^VIX': ramp(20.0, -0.1, 60),
    'MU': ramp(100.0, 2.0, 60),
    'WDC': ramp(100.0, 2.0, 60),
    'STX': ramp(100.0, 2.0, 60),
    'CL=F': [80.0] * 59 + [72.0],
}


def test_pct_change_over_n_sessions():
    assert pct_change(CLOSES, '^GSPC', 5) == round((159 / 154 - 1) * 100, 2)


def test_pct_change_needs_enough_history():
    assert pct_change({'X': [1.0, 2.0]}, 'X', 5) is None


def test_pct_change_on_a_missing_ticker_is_none():
    assert pct_change(CLOSES, 'NOPE', 5) is None


def test_vs_dma_is_positive_for_a_rising_series():
    assert vs_dma_pct(CLOSES, '^GSPC', 20) > 0


def test_vs_dma_is_zero_for_a_flat_series():
    assert vs_dma_pct({'X': [50.0] * 30}, 'X', 20) == 0.0


def test_vs_dma_needs_a_full_window():
    assert vs_dma_pct({'X': [50.0] * 10}, 'X', 20) is None


def test_last_and_abs_change():
    assert last(CLOSES, '^VIX') == 14.1
    assert abs_change(CLOSES, '^VIX', 5) == -0.5


def test_basket_rel_is_excess_return_in_points():
    # Basket legs run +2/session off a 208 base (+4.81% over 5), SPX +1/session off
    # 154 (+3.25%) — so the basket outruns the benchmark by ~1.56%p.
    assert basket_rel(CLOSES, ('MU', 'WDC', 'STX'), '^GSPC', 5) == 1.56


def test_basket_rel_is_negative_when_the_basket_lags():
    lagging = dict(CLOSES, MU=[100.0] * 60, WDC=[100.0] * 60, STX=[100.0] * 60)
    assert basket_rel(lagging, ('MU', 'WDC', 'STX'), '^GSPC', 5) < 0


def test_basket_rel_survives_one_missing_leg():
    assert basket_rel(CLOSES, ('MU', 'GONE'), '^GSPC', 5) is not None


def test_basket_rel_is_none_without_a_benchmark():
    assert basket_rel(CLOSES, ('MU',), 'NOPE', 5) is None


MARKET_DATA = {
    'sectors': {'Technology': {'pct': 1.2}, 'Energy': {'pct': -0.4}, 'Utilities': {'pct': 0.1}},
    'sector_performance': {'Technology': {'1M': 3.0}, 'Energy': {'1M': -1.0},
                           'Utilities': {'1M': None}},
    'yields': {
        '2Y': {'level': 4.37, 'week_ago': 4.30},
        '5Y': {'level': 4.20, 'week_ago': 4.20},
        '10Y': {'level': 4.55, 'week_ago': 4.514},
        '30Y': {'level': 5.10, 'week_ago': 5.046},
    },
    'spread_2s10s_bp': 18.0,
    'spread_5s30s_bp': 90.0,
}


def test_compute_returns_yield_levels_and_five_day_bp_changes():
    m = compute(CLOSES, MARKET_DATA)
    assert m['ust10y'] == 4.55
    assert m['ust10y_chg_5d_bp'] == 3.6
    assert m['ust5y_chg_5d_bp'] == 0.0
    assert m['spread_5s30s_bp'] == 90.0
    assert m['spread_5s30s_chg_5d_bp'] == 5.4


def test_compute_counts_sector_breadth():
    m = compute(CLOSES, MARKET_DATA)
    assert m['sectors_up_1d'] == 2
    assert m['sectors_up_1m'] == 1


def test_compute_marks_uncollected_metrics_as_none_rather_than_dropping_them():
    m = compute({}, {})
    assert 'vix_close' in m and m['vix_close'] is None
    assert 'memory_rel_5d' in m and m['memory_rel_5d'] is None
    assert all(v is None for v in m.values())


def test_compute_covers_every_metric_named_in_the_spec():
    m = compute(CLOSES, MARKET_DATA)
    for name in ('spx_vs_20dma_pct', 'spx_vs_50dma_pct', 'ndx_vs_20dma_pct',
                 'rut_vs_20dma_pct', 'spx_pct_5d', 'spx_pct_20d',
                 'growth_value_spread_5d', 'vix_close', 'vix_chg_5d',
                 'sectors_up_1d', 'sectors_up_1m',
                 'ust2y', 'ust5y', 'ust10y', 'ust30y',
                 'spread_2s10s_bp', 'spread_5s30s_bp',
                 'dxy_close', 'dxy_pct_5d', 'dxy_pct_20d', 'usdjpy_close', 'usdjpy_pct_5d',
                 'usdkrw_close', 'usdkrw_pct_5d', 'eurusd_pct_5d',
                 'wti_close', 'wti_pct_5d', 'wti_pct_20d', 'brent_close',
                 'gold_close', 'gold_pct_5d', 'gold_pct_20d',
                 'memory_rel_5d', 'memory_rel_20d', 'ai_infra_rel_5d', 'ai_infra_rel_20d'):
        assert name in m, name


def test_wti_five_day_drop_is_picked_up_as_a_trigger_input():
    m = compute(CLOSES, MARKET_DATA)
    assert m['wti_pct_5d'] == -10.0
