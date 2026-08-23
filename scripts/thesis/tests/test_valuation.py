from thesis import valuation as V


TICKER = {
    'eps_fy1': 67312.55,
    'bvps': 82300.0,
    'price': 281500,
}


def test_scenario_values_are_ordered_bear_base_bull():
    fv = V.fair_value('005930.KS', TICKER)
    assert fv['bear'] < fv['base'] < fv['bull']


def test_weighted_sits_between_bear_and_bull():
    fv = V.fair_value('005930.KS', TICKER)
    assert fv['bear'] < fv['weighted'] < fv['bull']


def test_bands_are_discounts_off_weighted():
    fv = V.fair_value('005930.KS', TICKER)
    assert fv['band1'] == round(fv['weighted'] * 0.80)
    assert fv['band2'] == round(fv['weighted'] * 0.68)
    assert fv['band2'] < fv['band1'] < fv['weighted']


def test_two_methods_are_averaged_not_just_earnings():
    """자산법이 결과에 실제로 기여해야 한다 — BPS를 바꾸면 값이 움직인다."""
    low = V.fair_value('005930.KS', dict(TICKER, bvps=10_000.0))
    high = V.fair_value('005930.KS', dict(TICKER, bvps=200_000.0))
    assert high['base'] > low['base']


def test_korea_multiples_are_lower_than_us():
    assert V.MULTIPLES['005930.KS']['base'] < V.MULTIPLES['MU']['base']
    assert V.MULTIPLES['000660.KS']['base'] < V.MULTIPLES['MU']['base']


def test_missing_eps_returns_none():
    assert V.fair_value('MU', {'eps_fy1': None, 'bvps': 100.0}) is None


def test_missing_bvps_falls_back_to_earnings_method_only():
    fv = V.fair_value('MU', {'eps_fy1': 155.03, 'bvps': None})
    assert fv is not None
    assert fv['method'] == 'earnings_only'


def test_both_inputs_present_reports_blended_method():
    fv = V.fair_value('MU', {'eps_fy1': 155.03, 'bvps': 115.0})
    assert fv['method'] == 'blended'


def test_probabilities_sum_to_one():
    assert abs(sum(w for _, w in V.SCENARIOS.values()) - 1.0) < 1e-9


def test_unknown_ticker_uses_default_multiples():
    fv = V.fair_value('AAPL', {'eps_fy1': 10.0, 'bvps': 5.0})
    assert fv is not None
