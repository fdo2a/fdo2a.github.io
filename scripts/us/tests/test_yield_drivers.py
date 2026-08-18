from us import yield_drivers as yd


def series(*values, start='2026-08-01'):
    """(date, value) pairs, oldest first — one business-ish day apart."""
    import datetime as dt
    d = dt.date.fromisoformat(start)
    out = []
    for v in values:
        out.append((d.isoformat(), float(v)))
        d += dt.timedelta(days=1)
    return out


BASE = {
    'DGS10': series(4.20, 4.22, 4.30),
    'DFII10': series(2.00, 2.02, 2.09),
    'T10YIE': series(2.20, 2.20, 2.21),
}


def test_levels_and_changes_are_reported_in_basis_points():
    out = yd.build(BASE)
    real = out['rows']['real_10y']
    assert real['level'] == 2.09
    assert real['chg_1d_bp'] == 7.0
    assert real['chg_5d_bp'] == 9.0


def test_a_missing_series_is_absent_not_fatal():
    out = yd.build({'DGS10': BASE['DGS10']})
    assert 'real_10y' not in out['rows']
    assert out['rows']['nominal_10y']['level'] == 4.30


def test_decomposition_splits_the_nominal_move():
    d = yd.build(BASE)['decomposition']['10Y']
    assert d['nominal_chg_1d_bp'] == 8.0
    assert d['real_chg_1d_bp'] == 7.0
    assert d['breakeven_chg_1d_bp'] == 1.0


def test_a_real_rate_driven_move_is_labelled_as_such():
    d = yd.build(BASE)['decomposition']['10Y']
    assert d['driver'] == 'real'
    assert d['driver_ko'] == '실질금리'


def test_an_inflation_driven_move_is_labelled_as_such():
    s = dict(BASE, DFII10=series(2.00, 2.02, 2.03), T10YIE=series(2.20, 2.20, 2.27))
    d = yd.build(s)['decomposition']['10Y']
    assert d['driver'] == 'breakeven'
    assert d['driver_ko'] == '기대인플레'


def test_a_split_move_is_not_forced_into_one_cause():
    s = dict(BASE, DFII10=series(2.00, 2.02, 2.06), T10YIE=series(2.20, 2.20, 2.24))
    assert yd.build(s)['decomposition']['10Y']['driver'] == 'mixed'


def test_a_move_too_small_to_attribute_says_so():
    s = {'DGS10': series(4.20, 4.20, 4.201),
         'DFII10': series(2.00, 2.00, 2.0005),
         'T10YIE': series(2.20, 2.20, 2.2005)}
    assert yd.build(s)['decomposition']['10Y']['driver'] == 'flat'


def test_decomposition_needs_both_legs():
    out = yd.build({'DGS10': BASE['DGS10'], 'DFII10': BASE['DFII10']})
    assert out['decomposition'] == {}


def test_credit_spreads_ride_along_when_present():
    out = yd.build(dict(BASE, BAMLH0A0HYM2=series(2.60, 2.63, 2.67)))
    assert out['rows']['hy_spread']['chg_1d_bp'] == 4.0


def test_every_row_carries_its_own_as_of_date():
    out = yd.build(BASE)
    assert out['rows']['nominal_10y']['date'] == '2026-08-03'


def test_decomposition_aligns_the_legs_to_shared_dates():
    """FRED publishes the legs on different lags; unaligned, 명목 ≠ 실질 + 기대 and the
    identity the whole section rests on stops holding."""
    s = {
        'DGS10': series(4.20, 4.22, 4.30, 4.35),      # one extra session
        'DFII10': series(2.00, 2.02, 2.09),
        'T10YIE': series(2.20, 2.20, 2.21),
    }
    d = yd.build(s)['decomposition']['10Y']
    assert d['nominal_chg_1d_bp'] == 8.0              # 4.30 vs 4.22, not 4.35
    assert d['real_chg_1d_bp'] + d['breakeven_chg_1d_bp'] == d['nominal_chg_1d_bp']
    assert d['as_of'] == '2026-08-03'


def test_decomposition_is_skipped_without_a_shared_date():
    s = {
        'DGS10': series(4.20, 4.30, start='2026-08-01'),
        'DFII10': series(2.00, 2.09, start='2026-09-01'),
        'T10YIE': series(2.20, 2.21, start='2026-09-01'),
    }
    assert yd.build(s)['decomposition'] == {}


def test_row_levels_still_use_each_series_own_latest_print():
    s = {
        'DGS10': series(4.20, 4.22, 4.30, 4.35),
        'DFII10': series(2.00, 2.02, 2.09),
        'T10YIE': series(2.20, 2.20, 2.21),
    }
    out = yd.build(s)
    assert out['rows']['nominal_10y']['level'] == 4.35
