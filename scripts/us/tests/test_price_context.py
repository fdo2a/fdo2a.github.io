from us.price_context import (
    change_kind,
    changes,
    move_band,
    move_multiple,
)


def ramp(start, step, n):
    return [start + step * i for i in range(n)]


def test_changes_are_percent_returns_for_a_price_series():
    got = changes({'X': [100.0, 110.0, 121.0]}, 'X')
    assert got == [10.0, 10.0]


def test_changes_are_level_differences_for_a_yield_series():
    got = changes({'^TNX': [4.00, 4.05, 4.02]}, '^TNX')
    assert got == [round(0.05, 10), round(-0.03, 10)]


def test_change_kind_defaults_to_returns():
    assert change_kind('^GSPC') == 'r'


def test_change_kind_is_difference_for_yields():
    assert change_kind('^TNX') == 'd'


def test_move_multiple_is_one_when_today_matches_the_typical_day():
    # 60 alternating +1%/-1% days, then one more +1% day: today is exactly typical.
    closes = [100.0]
    for i in range(61):
        closes.append(closes[-1] * (1.01 if i % 2 == 0 else 1 / 1.01))
    assert abs(move_multiple({'X': closes}, 'X', w=60) - 1.0) < 0.05


def test_move_multiple_is_signed():
    closes = [100.0]
    for i in range(60):
        closes.append(closes[-1] * (1.01 if i % 2 == 0 else 1 / 1.01))
    closes.append(closes[-1] * 0.95)
    assert move_multiple({'X': closes}, 'X', w=60) < 0


def test_move_multiple_excludes_today_from_the_typical_day():
    # A dead-flat history then one big jump: today must not inflate its own yardstick.
    closes = [100.0] * 61 + [110.0]
    assert move_multiple({'X': closes}, 'X', w=60) is None  # typical day is 0 -> undefined


def test_move_multiple_needs_a_full_window():
    assert move_multiple({'X': ramp(100.0, 1.0, 10)}, 'X', w=60) is None


def test_move_multiple_on_a_missing_ticker_is_none():
    assert move_multiple({}, 'NOPE', w=60) is None


def test_move_band_labels_a_quiet_day():
    assert move_band(0.3) == '미미'


def test_move_band_labels_an_ordinary_day():
    assert move_band(-1.2) == '보통'


def test_move_band_labels_a_big_day():
    assert move_band(1.9) == '큼'


def test_move_band_labels_an_extreme_day():
    assert move_band(-3.4) == '매우 큼'


def test_move_band_of_none_is_none():
    assert move_band(None) is None


from us.price_context import (  # noqa: E402
    correlation,
    level_percentile,
    percentile_band,
)


def test_level_percentile_is_100_at_the_top_of_its_history():
    assert level_percentile({'X': ramp(1.0, 1.0, 100)}, 'X', w=100) == 100.0


def test_level_percentile_is_low_at_the_bottom_of_its_history():
    assert level_percentile({'X': ramp(100.0, -1.0, 100)}, 'X', w=100) == 0.0


def test_level_percentile_is_midway_for_a_middling_level():
    closes = ramp(1.0, 1.0, 100) + [50.0]
    assert 45.0 <= level_percentile({'X': closes}, 'X', w=101) <= 55.0


def test_level_percentile_uses_only_the_requested_window():
    # A long-ago spike outside the window must not drag the reading down.
    closes = [1000.0] * 50 + ramp(1.0, 1.0, 101)
    assert level_percentile({'X': closes}, 'X', w=100) == 100.0


def test_level_percentile_needs_some_history():
    assert level_percentile({'X': [1.0, 2.0]}, 'X', w=100) is None


def test_percentile_band_labels_an_extreme_low():
    assert percentile_band(5.0) == '매우 낮음'


def test_percentile_band_labels_the_middle():
    assert percentile_band(50.0) == '중간'


def test_percentile_band_labels_an_extreme_high():
    assert percentile_band(95.0) == '매우 높음'


def test_correlation_of_a_series_with_itself_is_one():
    closes = {'A': ramp(100.0, 1.0, 80), 'B': ramp(100.0, 1.0, 80)}
    assert correlation(closes, dates_for(closes), 'A', 'B', w=60) == 1.0


def test_correlation_of_mirrored_series_is_minus_one():
    up = [100.0]
    down = [100.0]
    for i in range(80):
        step = 1.0 if i % 3 else -2.0
        up.append(up[-1] + step)
        down.append(down[-1] - step)
    assert correlation({'A': up, 'B': down}, dates_for({'A': up, 'B': down}), 'A', 'B', w=60) == -1.0


def test_correlation_pairs_returns_with_yield_differences():
    # ^TNX is differenced, the equity leg is returned; a rising-yield/rising-stock
    # window must still come back positive rather than NaN.
    eq, ty = [100.0], [4.0]
    for i in range(80):
        step = 1.0 if i % 4 else -2.0
        eq.append(eq[-1] + step)
        ty.append(ty[-1] + step * 0.01)
    assert correlation({'^GSPC': eq, '^TNX': ty}, dates_for({'^GSPC': eq, '^TNX': ty}), '^GSPC', '^TNX', w=60) > 0.9


def test_correlation_needs_a_full_window():
    assert correlation({'A': ramp(1.0, 1.0, 10), 'B': ramp(1.0, 1.0, 10)}, None, 'A', 'B', w=60) is None


def test_correlation_on_a_missing_ticker_is_none():
    assert correlation({'A': ramp(1.0, 1.0, 80)}, dates_for({'A': ramp(1.0, 1.0, 80)}), 'A', 'NOPE', w=60) is None


from us.price_context import forward_5y5y  # noqa: E402


def _rows(n5=4.00, n10=4.50, r5=1.80, r10=2.10, be=2.40, d='2026-08-25', d_be='2026-08-25',
          c5=-2.0, c10=1.0):
    return {
        'nominal_5y': {'level': n5, 'date': d, 'chg_1d_bp': c5},
        'nominal_10y': {'level': n10, 'date': d, 'chg_1d_bp': c10},
        'real_5y': {'level': r5, 'date': d, 'chg_1d_bp': 0.0},
        'real_10y': {'level': r10, 'date': d, 'chg_1d_bp': 0.0},
        'breakeven_5y5y': {'level': be, 'date': d_be, 'chg_1d_bp': 0.0},
    }


def test_forward_5y5y_nominal_is_twice_the_ten_year_minus_the_five():
    assert forward_5y5y(_rows())['nominal'] == 5.0


def test_forward_5y5y_real_uses_the_real_legs():
    assert forward_5y5y(_rows())['real'] == 2.4


def test_forward_5y5y_reports_the_basis_date_it_used():
    assert forward_5y5y(_rows())['date'] == '2026-08-25'


def test_forward_5y5y_refuses_legs_from_different_dates():
    rows = _rows()
    rows['nominal_10y']['date'] = '2026-08-26'
    assert forward_5y5y(rows) is None


def test_forward_5y5y_daily_change_compounds_the_leg_changes():
    # 2 x 10y change - 5y change = 2(1.0) - (-2.0) = 4.0bp
    assert forward_5y5y(_rows())['chg_1d_bp'] == 4.0


def test_forward_5y5y_checks_the_decomposition_against_fred():
    # nominal 5.0 - real 2.4 = 2.6 implied, vs FRED's 2.40 -> 20bp gap
    assert forward_5y5y(_rows())['breakeven_gap_bp'] == 20.0


def test_forward_5y5y_skips_the_fred_check_when_the_dates_disagree():
    got = forward_5y5y(_rows(d_be='2026-08-20'))
    assert got['breakeven_gap_bp'] is None


def test_forward_5y5y_without_nominal_legs_is_none():
    assert forward_5y5y({}) is None


def test_forward_5y5y_survives_missing_real_legs():
    rows = _rows()
    del rows['real_5y']
    got = forward_5y5y(rows)
    assert got['nominal'] == 5.0 and got['real'] is None


import random  # noqa: E402

from us.price_context import (  # noqa: E402
    aligned_changes as _aligned_changes,
    cohesion,
    estimate_weights,
    sector_contributions,
)


def dates_for(closes, start='2022-01-01'):
    """Matching session dates for every series, so cross-series calls can align."""
    import datetime as dt
    d0 = dt.date.fromisoformat(start)
    return {t: [(d0 + dt.timedelta(days=i)).isoformat() for i in range(len(s))]
            for t, s in closes.items()}


def _walk(steps, start=100.0):
    out = [start]
    for s in steps:
        out.append(out[-1] * (1 + s / 100))
    return out


def test_cohesion_is_total_when_every_asset_moves_together():
    rng = random.Random(0)
    steps = [rng.uniform(-2, 2) for _ in range(80)]
    closes = {k: _walk(steps) for k in ('A', 'B', 'C', 'D')}
    assert cohesion(closes, dates_for(closes), ['A', 'B', 'C', 'D'], w=60)['top1_pct'] == 100.0


def test_cohesion_is_low_when_assets_move_independently():
    rng = random.Random(7)
    closes = {k: _walk([rng.uniform(-2, 2) for _ in range(80)]) for k in ('A', 'B', 'C', 'D')}
    assert cohesion(closes, dates_for(closes), ['A', 'B', 'C', 'D'], w=60)['top1_pct'] < 60.0


def test_cohesion_top3_covers_at_least_as_much_as_top1():
    rng = random.Random(3)
    closes = {k: _walk([rng.uniform(-2, 2) for _ in range(80)]) for k in ('A', 'B', 'C', 'D')}
    got = cohesion(closes, dates_for(closes), ['A', 'B', 'C', 'D'], w=60)
    assert got['top3_pct'] >= got['top1_pct']


def test_cohesion_needs_at_least_three_usable_series():
    rng = random.Random(1)
    closes = {k: _walk([rng.uniform(-2, 2) for _ in range(80)]) for k in ('A', 'B')}
    assert cohesion(closes, dates_for(closes), ['A', 'B'], w=60) is None


def test_cohesion_needs_a_full_window():
    closes = {k: ramp(100.0, 1.0, 20) for k in ('A', 'B', 'C')}
    assert cohesion(closes, dates_for(closes), ['A', 'B', 'C'], w=60) is None


SECTOR_MIX = (('A', 0.5), ('B', 0.3), ('C', 0.2))


def _mixed_index(sector_steps):
    idx_steps = [sum(w * sector_steps[t][i] for t, w in SECTOR_MIX)
                 for i in range(len(sector_steps['A']))]
    return _walk(idx_steps)


def _sector_closes(seed=11, n=140):
    rng = random.Random(seed)
    steps = {t: [rng.uniform(-3, 3) for _ in range(n)] for t, _ in SECTOR_MIX}
    closes = {t: _walk(steps[t]) for t, _ in SECTOR_MIX}
    closes['IDX'] = _mixed_index(steps)
    return closes


def test_estimate_weights_recovers_an_exact_mixture():
    closes = _sector_closes()
    cols = _aligned_changes(closes, dates_for(closes), ['A', 'B', 'C', 'IDX'], 120)
    weights, r2, _ = estimate_weights(cols[:-1], cols[-1])
    assert abs(weights[0] - 0.5) < 0.01 and abs(weights[2] - 0.2) < 0.01
    assert r2 > 0.999


def test_estimate_weights_never_returns_a_negative_weight():
    # D is pure noise the index does not contain; an unconstrained fit would happily
    # give it a negative coefficient, which is not a portfolio weight.
    rng = random.Random(23)
    closes = _sector_closes()
    closes['D'] = _walk([rng.uniform(-3, 3) for _ in range(140)])
    cols = _aligned_changes(closes, dates_for(closes), ['A', 'B', 'C', 'D', 'IDX'], 120)
    weights, _r2, _ok = estimate_weights(cols[:-1], cols[-1])
    assert all(w >= 0 for w in weights)


def test_sector_contributions_do_not_publish_an_estimated_weight():
    # A weight of "0.00%" for a sector the regression cannot identify would be a wrong
    # fact about the index. Contributions are estimates; weights would read as facts.
    got = sector_contributions(_sector_closes(), dates_for(_sector_closes()),
                               [('Alpha', 'A'), ('Beta', 'B'), ('Gamma', 'C')], 'IDX', w=120)
    assert all('weight' not in r for r in got['rows'])


def test_sector_contributions_publish_the_part_they_cannot_explain():
    got = sector_contributions(_sector_closes(), dates_for(_sector_closes()),
                               [('Alpha', 'A'), ('Beta', 'B'), ('Gamma', 'C')], 'IDX', w=120)
    assert abs(got['residual'] - (got['index_change'] - sum(r['contribution']
                                                            for r in got['rows']))) < 0.005


def test_sector_contributions_leave_almost_no_residual_when_sectors_span_the_index():
    got = sector_contributions(_sector_closes(), dates_for(_sector_closes()),
                               [('Alpha', 'A'), ('Beta', 'B'), ('Gamma', 'C')], 'IDX', w=120)
    assert abs(got['residual']) < 0.02


def test_sector_contributions_are_marked_as_estimates():
    got = sector_contributions(_sector_closes(), dates_for(_sector_closes()),
                               [('Alpha', 'A'), ('Beta', 'B'), ('Gamma', 'C')], 'IDX', w=120)
    assert got['estimated'] is True


def test_sector_contributions_reports_how_well_the_weights_fit():
    got = sector_contributions(_sector_closes(), dates_for(_sector_closes()),
                               [('Alpha', 'A'), ('Beta', 'B'), ('Gamma', 'C')], 'IDX', w=120)
    assert got['fit_r2'] > 0.99


def test_sector_contributions_add_up_to_the_index_move():
    got = sector_contributions(_sector_closes(), dates_for(_sector_closes()),
                               [('Alpha', 'A'), ('Beta', 'B'), ('Gamma', 'C')], 'IDX', w=120)
    total = sum(r['contribution'] for r in got['rows'])
    assert abs(total - got['index_change']) < 0.02


def test_sector_contributions_are_ranked_by_size_of_contribution():
    got = sector_contributions(_sector_closes(), dates_for(_sector_closes()),
                               [('Alpha', 'A'), ('Beta', 'B'), ('Gamma', 'C')], 'IDX', w=120)
    sizes = [abs(r['contribution']) for r in got['rows']]
    assert sizes == sorted(sizes, reverse=True)


def test_sector_contributions_needs_a_full_window():
    closes = {t: ramp(100.0, 1.0, 20) for t in ('A', 'B', 'C', 'IDX')}
    assert sector_contributions(closes, dates_for(closes), [('Alpha', 'A')], 'IDX', w=120) is None


from us.price_context import COHESION_SET, CORR_PAIRS, TRACKED, compute  # noqa: E402


def test_correlation_can_look_at_an_earlier_window():
    # Rising together for 60 sessions, then mirrored for 60: the recent window is
    # negative and the offset window positive.
    a, b = [100.0], [100.0]
    for i in range(60):
        step = 1.0 if i % 3 else -2.0
        a.append(a[-1] + step)
        b.append(b[-1] + step)
    for i in range(60):
        step = 1.0 if i % 3 else -2.0
        a.append(a[-1] + step)
        b.append(b[-1] - step)
    closes = {'A': a, 'B': b}
    assert correlation(closes, dates_for(closes), 'A', 'B', w=60) < 0
    assert correlation(closes, dates_for(closes), 'A', 'B', w=60, offset=60) > 0


def _full_closes(seed=5, n=300):
    rng = random.Random(seed)
    out = {}
    for _, t in TRACKED:
        out[t] = _walk([rng.uniform(-1.5, 1.5) for _ in range(n)])
    for t in COHESION_SET + ['MU', '^GSPC', '^IXIC']:
        out.setdefault(t, _walk([rng.uniform(-1.5, 1.5) for _ in range(n)]))
    for _, t in SECTORS_FOR_TEST:
        out[t] = _walk([rng.uniform(-2, 2) for _ in range(n)])
    return out


SECTORS_FOR_TEST = [('Technology', 'XLK'), ('Energy', 'XLE'), ('Financials', 'XLF')]


def test_compute_returns_a_move_reading_for_every_tracked_name():
    got = compute(_full_closes(), {}, sectors=SECTORS_FOR_TEST, dates=dates_for(_full_closes()))
    assert set(got['moves']) == {name for name, _ in TRACKED}


def test_compute_gives_each_move_a_band_word():
    got = compute(_full_closes(), {}, sectors=SECTORS_FOR_TEST, dates=dates_for(_full_closes()))
    assert got['moves']['S&P 500']['band'] in {'미미', '보통', '큼', '매우 큼'}


def test_compute_reports_a_level_percentile_for_every_tracked_name():
    got = compute(_full_closes(), {}, sectors=SECTORS_FOR_TEST, dates=dates_for(_full_closes()))
    assert 0.0 <= got['levels']['VIX']['percentile'] <= 100.0


def test_compute_returns_one_row_per_correlation_pair():
    got = compute(_full_closes(), {}, sectors=SECTORS_FOR_TEST, dates=dates_for(_full_closes()))
    assert [r['key'] for r in got['correlations']] == [k for k, _, _, _ in CORR_PAIRS]


def test_compute_flags_a_correlation_that_changed_sign():
    closes = _full_closes()
    a, b = [100.0], [100.0]
    for i in range(180):          # older window: moving together
        step = 1.0 if i % 3 else -2.0
        a.append(a[-1] + step)
        b.append(b[-1] + step)
    for i in range(60):           # recent window: mirrored
        step = 1.0 if i % 3 else -2.0
        a.append(a[-1] + step)
        b.append(b[-1] - step)
    closes['^GSPC'], closes['^TNX'] = a, b
    row = next(r for r in compute(closes, {}, sectors=SECTORS_FOR_TEST, dates=dates_for(closes))['correlations']
               if r['key'] == 'equity_rates')
    assert row['flipped'] is True


def test_compute_does_not_call_noise_a_sign_change():
    got = compute(_full_closes(), {}, sectors=SECTORS_FOR_TEST, dates=dates_for(_full_closes()))
    # Independent random walks hover near zero; none of them genuinely flipped.
    assert all(r['flipped'] is False for r in got['correlations'])


def test_compute_includes_the_forward_rate_when_yield_drivers_are_present():
    md = {'yield_drivers': {'rows': _rows()}}
    assert compute(_full_closes(), md, sectors=SECTORS_FOR_TEST, dates=dates_for(_full_closes()))['forward_5y5y']['nominal'] == 5.0


def test_compute_survives_market_data_without_yield_drivers():
    assert compute(_full_closes(), {}, sectors=SECTORS_FOR_TEST, dates=dates_for(_full_closes()))['forward_5y5y'] is None


def test_compute_on_empty_input_returns_empty_readings_rather_than_raising():
    got = compute({}, {}, sectors=SECTORS_FOR_TEST)
    assert got['moves']['S&P 500'] is None
    assert got['cohesion'] is None
    assert got['sector_contribution'] is None


def test_compute_records_the_windows_it_used():
    got = compute(_full_closes(), {}, sectors=SECTORS_FOR_TEST, dates=dates_for(_full_closes()))
    assert got['windows'] == {'move': 60, 'percentile': 504, 'correlation': 60, 'weights': 252}


from us.price_context import HISTORY_TICKERS  # noqa: E402


def test_history_tickers_cover_every_series_compute_reads():
    needed = {t for _, t in TRACKED} | set(COHESION_SET)
    for _, _, a, b in CORR_PAIRS:
        needed |= {a, b}
    assert needed <= set(HISTORY_TICKERS)


def test_level_percentile_reading_says_how_much_history_backed_it():
    got = compute(_full_closes(n=300), {}, sectors=SECTORS_FOR_TEST, dates=dates_for(_full_closes(n=300)))
    assert got['levels']['VIX']['sessions'] == 300


def test_level_percentile_reading_is_capped_at_the_window():
    got = compute(_full_closes(n=900), {}, sectors=SECTORS_FOR_TEST, dates=dates_for(_full_closes(n=900)))
    assert got['levels']['VIX']['sessions'] == 504


from us.price_context import aligned_changes  # noqa: E402


def _dts(n, start=1):
    """n consecutive session dates as ISO strings (calendar days are fine for tests)."""
    import datetime as dt
    d0 = dt.date(2025, 1, 1)
    return [(d0 + dt.timedelta(days=start + i)).isoformat() for i in range(n)]


def test_aligned_changes_uses_only_sessions_both_series_have():
    closes = {'A': [10.0, 11.0, 12.0, 13.0], 'B': [20.0, 24.0, 26.0]}
    dates = {'A': _dts(4), 'B': [_dts(4)[0], _dts(4)[2], _dts(4)[3]]}
    cols = aligned_changes(closes, dates, ['A', 'B'], w=2)
    # Common sessions are day1, day3, day4 -> two changes for each leg.
    assert cols[0] == [round((12 / 10 - 1) * 100, 10), round((13 / 12 - 1) * 100, 10)]
    assert cols[1] == [round((24 / 20 - 1) * 100, 10), round((26 / 24 - 1) * 100, 10)]


def test_aligned_changes_refuses_when_the_overlap_is_too_short():
    closes = {'A': [1.0, 2.0, 3.0], 'B': [1.0, 2.0, 3.0]}
    dates = {'A': _dts(3), 'B': _dts(3)}
    assert aligned_changes(closes, dates, ['A', 'B'], w=60) is None


def test_aligned_changes_without_dates_is_none():
    # No provenance means no honest cross-series comparison — never fall back to
    # lining series up by position.
    closes = {'A': [1.0] * 80, 'B': [2.0] * 80}
    assert aligned_changes(closes, None, ['A', 'B'], w=60) is None


def test_correlation_ignores_a_session_only_one_leg_traded():
    # A and B move together on shared sessions; B has an extra session A never saw.
    # Lining them up by position would drag the correlation off 1.0.
    import datetime as dt
    base = [dt.date(2025, 1, 1) + dt.timedelta(days=i) for i in range(120)]
    a_dates = [d.isoformat() for d in base]
    a, b = [100.0], [100.0]
    for i in range(119):
        step = 1.0 if i % 3 else -2.0
        a.append(a[-1] + step)
        b.append(b[-1] + step)
    b_dates = list(a_dates)
    b.insert(5, 999.0)
    b_dates.insert(5, (base[4] + dt.timedelta(hours=12)).isoformat() + 'x')
    got = correlation({'A': a, 'B': b}, {'A': a_dates, 'B': b_dates}, 'A', 'B', w=60)
    assert got == 1.0


def test_an_unknown_correlation_is_not_reported_as_not_flipped():
    # No dates -> no honest cross-series read. False would claim we checked.
    got = compute(_full_closes(), {}, sectors=SECTORS_FOR_TEST, dates=None)
    assert all(r['flipped'] is None for r in got['correlations'])


def test_a_nan_close_is_not_read_as_an_extreme_move():
    # A flat history has zero variance and would return None anyway; the yardstick
    # has to be live for the NaN to reach the band at all.
    rng = random.Random(41)
    closes = {'^GSPC': _walk([rng.uniform(-1.5, 1.5) for _ in range(80)]) + [float('nan')]}
    assert move_band(move_multiple(closes, '^GSPC')) != '매우 큼'


def test_sector_weights_are_not_fitted_on_the_day_they_explain():
    # Today only: a sector that never mattered suddenly carries the whole index.
    # An in-sample fit would hand it weight; a prior-only fit cannot.
    closes = _sector_closes()
    for t in ('A', 'B'):
        closes[t] = closes[t] + [closes[t][-1]]          # A and B flat today
    closes['C'] = closes['C'] + [closes['C'][-1] * 1.10]  # C +10% today
    closes['IDX'] = closes['IDX'] + [closes['IDX'][-1] * 1.10]
    got = sector_contributions(closes, dates_for(closes),
                               [('Alpha', 'A'), ('Beta', 'B'), ('Gamma', 'C')], 'IDX', w=120)
    # C's true weight is 0.2, so it can only account for ~2%p of a 10% index day.
    gamma = next(r for r in got['rows'] if r['name'] == 'Gamma')
    assert gamma['contribution'] < 3.0
    assert got['residual'] > 5.0


def test_forward_5y5y_refuses_real_legs_from_another_day():
    rows = _rows()
    rows['real_5y']['date'] = rows['real_10y']['date'] = '2026-08-20'
    assert forward_5y5y(rows)['real'] is None


def test_aligned_flag_reflects_whether_the_cross_series_reads_worked():
    # Dates present but too short to align anything: the flag must not claim they did.
    closes = {t: ramp(100.0, 1.0, 40) for t in ('^GSPC', '^TNX', 'XLK')}
    got = compute(closes, {}, sectors=[('Technology', 'XLK')], dates=dates_for(closes))
    assert got['cohesion'] is None
    assert got['aligned'] is False


def _four_sector_closes(seed=31, n=200):
    """Three sectors the index is actually made of, plus one it barely contains."""
    rng = random.Random(seed)
    mix = (('A', 0.5), ('B', 0.3), ('C', 0.2))
    steps = {t: [rng.uniform(-3, 3) for _ in range(n)] for t, _ in mix}
    steps['D'] = [rng.uniform(-3, 3) for _ in range(n)]   # in the table, not in the index
    closes = {t: _walk(steps[t]) for t in steps}
    closes['IDX'] = _walk([sum(w * steps[t][i] for t, w in mix) for i in range(n)])
    return closes


FOUR = [('Alpha', 'A'), ('Beta', 'B'), ('Gamma', 'C'), ('Delta', 'D')]


def test_a_sector_the_fit_cannot_identify_is_not_given_a_row():
    # "Delta -0.60%, 기여 -0.000%p" is not a finding, it is a broken-looking row.
    got = sector_contributions(_four_sector_closes(), dates_for(_four_sector_closes()),
                               FOUR, 'IDX', w=150)
    # Rows are ranked by contribution size, so compare membership, not order.
    assert sorted(r['name'] for r in got['rows']) == ['Alpha', 'Beta', 'Gamma']


def test_dropped_sectors_are_named_so_the_gap_can_be_explained():
    got = sector_contributions(_four_sector_closes(), dates_for(_four_sector_closes()),
                               FOUR, 'IDX', w=150)
    assert got['unidentified'] == ['Delta']


def test_dropping_a_sector_leaves_its_effect_in_the_unexplained_part():
    got = sector_contributions(_four_sector_closes(), dates_for(_four_sector_closes()),
                               FOUR, 'IDX', w=150)
    assert abs(got['residual'] - (got['index_change'] - sum(r['contribution']
                                                            for r in got['rows']))) < 0.005


def test_sectors_the_fit_can_identify_all_keep_their_rows():
    got = sector_contributions(_sector_closes(), dates_for(_sector_closes()),
                               [('Alpha', 'A'), ('Beta', 'B'), ('Gamma', 'C')], 'IDX', w=120)
    assert got['unidentified'] == []


def test_an_attribution_with_nothing_left_to_attribute_is_dropped(monkeypatch):
    """If every sector falls below the identifiability floor there is no split to
    publish, and an empty rows list would sail past the gate as though there were.

    Driven by raising the floor rather than by contriving prices: with real weights
    summing to one, some sector always clears 0.5%, so the branch is only reachable
    at the boundary — which is exactly where a guard has to hold.
    """
    import us.price_context as P
    monkeypatch.setattr(P, 'MIN_IDENTIFIABLE_WEIGHT', 0.99)
    closes = _sector_closes()
    got = P.sector_contributions(closes, dates_for(closes),
                                 [('Alpha', 'A'), ('Beta', 'B'), ('Gamma', 'C')],
                                 'IDX', w=120)
    assert got is None


# ── 팩터 분해 (2026-08-28 사용자 지시) ──────────────────────────────────────

from us.price_context import FACTORS, factor_decomposition  # noqa: E402


def _factor_world(seed=13, n=200, style_beta=0.0, own=None):
    """A market, a growth/value pair, a small-cap leg, and a basket built from them."""
    rng = random.Random(seed)
    mkt = [rng.uniform(-1.2, 1.2) for _ in range(n)]
    ivw = [m + rng.uniform(-0.4, 0.4) for m in mkt]
    ive = [m - (ivw[i] - m) for i, m in enumerate(mkt)]      # style = ivw - ive
    rut = [m + rng.uniform(-0.5, 0.5) for m in mkt]
    style = [ivw[i] - ive[i] for i in range(n)]
    idio = own if own is not None else [0.0] * n
    basket = [mkt[i] + style_beta * style[i] + idio[i] for i in range(n)]
    closes = {'^GSPC': _walk(mkt), 'IVW': _walk(ivw), 'IVE': _walk(ive),
              '^RUT': _walk(rut), 'BSK': _walk(basket)}
    return closes


def test_a_basket_that_is_the_market_has_no_excess_to_explain():
    closes = _factor_world()
    got = factor_decomposition(closes, dates_for(closes), ('BSK',), w=120, horizon=20)
    assert abs(got['excess_pct']) < 0.5


def test_a_style_driven_basket_is_explained_by_style_not_by_itself():
    closes = _factor_world(style_beta=1.5)
    got = factor_decomposition(closes, dates_for(closes), ('BSK',), w=120, horizon=20)
    assert abs(got['factors']['style']['contribution']) > abs(got['specific_pct'])


def test_an_idiosyncratic_basket_lands_in_the_specific_part():
    rng = random.Random(5)
    own = [rng.uniform(-2, 2) for _ in range(200)]
    closes = _factor_world(style_beta=0.0, own=own)
    got = factor_decomposition(closes, dates_for(closes), ('BSK',), w=120, horizon=20)
    assert abs(got['specific_pct']) > abs(got['factors']['style']['contribution'])


def test_the_parts_add_up_to_the_excess():
    closes = _factor_world(seed=21, style_beta=0.8)
    got = factor_decomposition(closes, dates_for(closes), ('BSK',), w=120, horizon=20)
    parts = sum(f['contribution'] for f in got['factors'].values()) + got['specific_pct']
    assert abs(parts - got['excess_pct']) < 0.01


def test_every_declared_factor_gets_a_reading():
    closes = _factor_world()
    got = factor_decomposition(closes, dates_for(closes), ('BSK',), w=120, horizon=20)
    assert set(got['factors']) == {key for key, _, _, _ in FACTORS}


def test_factor_decomposition_reports_how_well_the_factors_fit():
    closes = _factor_world(style_beta=1.5)
    got = factor_decomposition(closes, dates_for(closes), ('BSK',), w=120, horizon=20)
    assert 0.0 <= got['fit_r2'] <= 1.0


def test_factor_decomposition_needs_a_full_window():
    closes = {t: ramp(100.0, 1.0, 30) for t in ('^GSPC', 'IVW', 'IVE', '^RUT', 'BSK')}
    assert factor_decomposition(closes, dates_for(closes), ('BSK',), w=120, horizon=20) is None


def test_factor_decomposition_averages_a_multi_name_basket():
    closes = _factor_world()
    closes['BSK2'] = closes['BSK']
    one = factor_decomposition(closes, dates_for(closes), ('BSK',), w=120, horizon=20)
    two = factor_decomposition(closes, dates_for(closes), ('BSK', 'BSK2'), w=120, horizon=20)
    assert abs(one['excess_pct'] - two['excess_pct']) < 0.01


# ── 주도 요인 이름 (2026-08-28 사용자 지시) ────────────────────────────────

from us.price_context import DRIVER_GROUPS, market_drivers  # noqa: E402


def _driver_world(lead='equity', seed=9, n=200):
    """One asset group carries a strong shared move; everything else is noise."""
    rng = random.Random(seed)
    shared = [rng.uniform(-3, 3) for _ in range(n)]
    groups = {'equity': ('^GSPC', '^IXIC', '^RUT'), 'rates': ('^TNX', '^TYX'),
              'dollar': ('DX-Y.NYB', 'JPY=X'), 'commodity': ('CL=F', 'GC=F'),
              'vol': ('^VIX',)}
    closes = {}
    for name, tickers in groups.items():
        for t in tickers:
            if name == lead:
                steps = [s + rng.uniform(-0.2, 0.2) for s in shared]
            else:
                steps = [rng.uniform(-0.8, 0.8) for _ in range(n)]
            closes[t] = _walk(steps) if t not in ('^TNX', '^TYX') else \
                [4.0 + sum(steps[:i]) * 0.01 for i in range(n + 1)]
    return closes


def test_the_dominant_group_is_named():
    closes = _driver_world(lead='equity')
    got = market_drivers(closes, dates_for(closes), COHESION_SET, w=120)
    assert got['first']['group_ko'] == '주식'


def test_a_different_dominant_group_gets_its_own_name():
    closes = _driver_world(lead='commodity')
    got = market_drivers(closes, dates_for(closes), COHESION_SET, w=120)
    assert got['first']['group_ko'] == '원자재'


def test_the_name_comes_from_a_closed_vocabulary():
    closes = _driver_world()
    got = market_drivers(closes, dates_for(closes), COHESION_SET, w=120)
    names = {ko for ko, _ in DRIVER_GROUPS}
    assert got['first']['group_ko'] in names and got['second']['group_ko'] in names


def test_the_second_force_is_not_the_first_one_again():
    closes = _driver_world()
    got = market_drivers(closes, dates_for(closes), COHESION_SET, w=120)
    assert got['second']['group_ko'] != got['first']['group_ko']


def test_the_first_force_explains_more_than_the_second():
    closes = _driver_world()
    got = market_drivers(closes, dates_for(closes), COHESION_SET, w=120)
    assert got['first']['share_pct'] >= got['second']['share_pct']


def test_market_drivers_needs_a_full_window():
    closes = {t: ramp(100.0, 1.0, 20) for t in COHESION_SET}
    assert market_drivers(closes, dates_for(closes), COHESION_SET, w=120) is None


def test_compute_flags_a_change_of_leading_force():
    # Equities lead the older window, commodities the recent one.
    old = _driver_world(lead='equity', seed=4, n=260)
    new = _driver_world(lead='commodity', seed=8, n=80)
    closes = {t: old[t] + [old[t][-1] * (v / new[t][0]) for v in new[t][1:]] for t in old}
    got = compute(closes, {}, sectors=SECTORS_FOR_TEST, dates=dates_for(closes))
    assert got['drivers']['changed'] is True


# ── codex 검토(2026-08-28)가 잡은 것들 ──────────────────────────────────────

def test_a_high_beta_basket_is_flagged_by_its_reported_market_beta():
    """시장 민감도가 1이 아니면 초과수익의 일부는 그냥 베타 탓이다.

    그 몫을 회귀로 갈라내려 했더니 시장 다리와 성장−가치 다리가 실측 0.75로
    붙어 있어(2026-08-28) 시장 베타가 창 길이에 따라 -0.94~+1.17로 흔들렸다.
    갈라낼 수 없는 것을 갈라낸 척하는 대신, **단변량 시장 베타를 따로 실어**
    독자가 남은 몫을 그만큼 할인해 읽게 한다.
    """
    rng = random.Random(17)
    n = 200
    mkt = [rng.uniform(-1.0, 1.4) for _ in range(n)]          # 상승 편향
    ivw = [m + rng.uniform(-0.3, 0.3) for m in mkt]
    ive = [m - (ivw[i] - m) for i, m in enumerate(mkt)]
    rut = [m + rng.uniform(-0.4, 0.4) for m in mkt]
    closes = {'^GSPC': _walk(mkt), 'IVW': _walk(ivw), 'IVE': _walk(ive),
              '^RUT': _walk(rut), 'BSK': _walk([1.6 * m for m in mkt])}
    got = factor_decomposition(closes, dates_for(closes), ('BSK',), w=120, horizon=20)
    assert abs(got['market_beta'] - 1.6) < 0.15, got


def test_the_market_beta_is_reported_but_not_split_into_a_factor_leg():
    """갈라낼 수 없는 것은 다리로 세우지 않는다 — 값만 옆에 붙인다."""
    closes = _factor_world(style_beta=0.5)
    got = factor_decomposition(closes, dates_for(closes), ('BSK',), w=120, horizon=20)
    assert 'market' not in got['factors']
    assert isinstance(got['market_beta'], float)


def test_the_parts_still_add_up_without_a_market_leg():
    closes = _factor_world(seed=21, style_beta=0.8)
    got = factor_decomposition(closes, dates_for(closes), ('BSK',), w=120, horizon=20)
    parts = sum(f['contribution'] for f in got['factors'].values()) + got['specific_pct']
    assert abs(parts - got['excess_pct']) < 0.01


def test_pure_noise_has_no_leading_force_to_name():
    """서로 무관한 자산 열 개에서는 1등 자산군이 매번 바뀐다 — 그것은 국면
    전환이 아니라 잡음이고, 이름을 붙이면 없는 사건을 만들어 낸다."""
    rng = random.Random(2)
    closes = {t: _walk([rng.uniform(-1, 1) for _ in range(200)]) for t in COHESION_SET}
    assert market_drivers(closes, dates_for(closes), COHESION_SET, w=120) is None


def test_a_genuinely_shared_move_still_gets_named():
    closes = _driver_world(lead='equity')
    assert market_drivers(closes, dates_for(closes), COHESION_SET, w=120) is not None


def test_the_prior_window_records_both_places_not_just_the_first():
    """발행본이 「순서가 같다」고 쓰려면 직전 2등도 알고 있어야 한다."""
    closes = _driver_world(lead='equity')
    got = compute(closes, {}, sectors=SECTORS_FOR_TEST, dates=dates_for(closes))
    assert set(got['drivers']['prior']) == {'first', 'second'}


def test_the_market_beta_survives_a_market_heavy_style_spread():
    """실측에서 성장−가치 스프레드는 시장과 0.75 상관이었다(2026-08-28)."""
    rng = random.Random(88)
    n = 300
    mkt = [rng.uniform(-1.2, 1.2) for _ in range(n)]
    ivw = [1.5 * m + rng.uniform(-0.2, 0.2) for m in mkt]     # 시장 성분이 큰 성장주
    ive = [0.7 * m + rng.uniform(-0.2, 0.2) for m in mkt]
    rut = [m + rng.uniform(-0.4, 0.4) for m in mkt]
    style = [ivw[i] - ive[i] for i in range(n)]
    # 시장 베타 2.0에 진짜 스타일 기울기까지 있는 바스켓 — 스타일 기울기가 0이면
    # 직교화 여부로 답이 갈리지 않아 검사가 아무것도 가려내지 못한다.
    bsk = [2.0 * mkt[i] + 0.8 * style[i] + rng.uniform(-0.3, 0.3) for i in range(n)]
    closes = {'^GSPC': _walk(mkt), 'IVW': _walk(ivw), 'IVE': _walk(ive),
              '^RUT': _walk(rut), 'BSK': _walk(bsk)}
    got = factor_decomposition(closes, dates_for(closes), ('BSK',), w=250, horizon=20)
    # 이 바스켓의 실제 시장 민감도는 2.0이 아니라 2.64다: 스타일 스프레드 자체가
    # 1.5m - 0.7m = 0.8m이라, 2.0m + 0.8x(0.8m) = 2.64m으로 움직인다. 단변량 베타는
    # 스타일을 타고 들어온 시장 노출까지 합쳐 재는 값이고, 그게 우리가 싣고 싶은 값이다.
    assert abs(got['market_beta'] - 2.64) < 0.2, got
