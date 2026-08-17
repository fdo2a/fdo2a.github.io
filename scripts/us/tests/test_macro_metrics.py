import pytest

from us import macro_metrics as mm


def dated(values, start_year=2021):
    """(date, value) pairs, oldest first — months don't matter except for ref_period."""
    out = []
    y, m = start_year, 1
    for v in values:
        out.append((f'{y:04d}-{m:02d}-01', float(v)))
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def jump(direction, n=60, w=3, base=100.0):
    """A quiet series that lurches in `direction` over its last `w` observations."""
    quiet = [base + (i % 2) for i in range(n)]
    return quiet + [base + direction * 50.0] * w


def ind(name, axis, fred_id, actual=1.0, previous=0.0, ref='2026-07-01', tf='level'):
    return {'axis': axis, 'name': name, 'fred_id': fred_id, 'transform': tf,
            'actual': actual, 'previous': previous, 'ref_period': ref}


# ------------------------------------------------------------- transforms

def test_transform_level_passes_values_through():
    assert mm.transform_series(dated([1, 2, 3]), 'level') == [1.0, 2.0, 3.0]


def test_transform_mom_pct_is_percent_change_on_the_prior_observation():
    assert mm.transform_series(dated([100, 110]), 'mom_pct') == pytest.approx([10.0])


def test_transform_mom_diff_is_the_level_difference():
    assert mm.transform_series(dated([100, 123]), 'mom_diff') == [23.0]


def test_transform_yoy_pct_needs_twelve_months_of_lag():
    vals = dated([100] * 12 + [105])
    assert mm.transform_series(vals, 'yoy_pct') == pytest.approx([5.0])


def test_transform_returns_empty_when_history_is_too_short():
    assert mm.transform_series(dated([100]), 'yoy_pct') == []


# -------------------------------------------------------------- momentum

def test_momentum_is_the_recent_block_minus_the_prior_block():
    assert mm.momentum([1, 1, 1, 4, 4, 4], 3) == 3.0


def test_momentum_needs_two_full_blocks():
    assert mm.momentum([1, 2, 3, 4, 5], 3) is None


def test_momentum_z_scales_against_the_series_own_history():
    assert mm.momentum_z(jump(1), 3) > 3


def test_momentum_z_keeps_the_sign_of_the_move():
    assert mm.momentum_z(jump(-1), 3) < -3


def test_momentum_z_is_none_when_the_series_never_moves():
    assert mm.momentum_z([5.0] * 40, 3) is None


# ---------------------------------------------------------- new releases

def test_new_release_detected_when_the_reference_period_advances():
    econ = [ind('CPI YoY', 'Inflation', 'CPIAUCSL', ref='2026-07-01')]
    series = {'CPIAUCSL': dated(jump(1))}
    out = mm.compute(series, econ, last_seen={'CPI YoY': ['2026-06-01', 1.0]})
    assert out['new_releases'] == ['CPI YoY']


def test_no_new_release_when_the_reading_is_unchanged():
    econ = [ind('CPI YoY', 'Inflation', 'CPIAUCSL', actual=3.5, ref='2026-07-01')]
    series = {'CPIAUCSL': dated(jump(1))}
    out = mm.compute(series, econ, last_seen={'CPI YoY': ['2026-07-01', 3.5]})
    assert out['new_releases'] == []


def test_every_indicator_is_new_on_the_first_run():
    econ = [ind('CPI YoY', 'Inflation', 'CPIAUCSL')]
    out = mm.compute({'CPIAUCSL': dated(jump(1))}, econ, last_seen=None)
    assert out['new_releases'] == ['CPI YoY']


def test_last_seen_is_emitted_for_tomorrow():
    econ = [ind('CPI YoY', 'Inflation', 'CPIAUCSL', actual=3.5, ref='2026-07-01')]
    out = mm.compute({'CPIAUCSL': dated(jump(1))}, econ)
    assert out['last_seen'] == {'CPI YoY': ['2026-07-01', 3.5]}


# ------------------------------------------------------------- polarity

def test_rising_jobless_claims_push_the_growth_score_down():
    econ = [ind('Initial Jobless Claims', 'Labor', 'ICSA')]
    out = mm.compute({'ICSA': dated(jump(1))}, econ)
    assert out['growth_score'] < 0


def test_rising_payrolls_push_the_growth_score_up():
    econ = [ind('Nonfarm Payrolls (chg)', 'Labor', 'PAYEMS')]
    out = mm.compute({'PAYEMS': dated(jump(1))}, econ)
    assert out['growth_score'] > 0


def test_rising_cpi_pushes_the_inflation_score_up_and_leaves_growth_empty():
    econ = [ind('CPI YoY', 'Inflation', 'CPIAUCSL')]
    out = mm.compute({'CPIAUCSL': dated(jump(1))}, econ)
    assert out['inflation_score'] > 0
    assert out['growth_score'] is None


# -------------------------------------------------------------- weighting

def test_growth_axis_weights_the_three_sub_axes_equally():
    """Seven falling Labor prints must not outvote two rising Consumption prints."""
    econ = ([ind(f'L{i}', 'Labor', f'L{i}') for i in range(7)]
            + [ind(f'C{i}', 'Consumption', f'C{i}') for i in range(2)])
    series = {f'L{i}': dated(jump(-1)) for i in range(7)}
    series.update({f'C{i}': dated(jump(1)) for i in range(2)})
    out = mm.compute(series, econ)
    # Indicator-equal weighting would drag the axis most of the way to Labor's own
    # score; axis-equal weighting leaves the two sub-axes very nearly cancelling.
    assert abs(out['growth_score']) < abs(out['axis_scores']['Labor']) / 10


def test_diffusion_is_the_share_of_indicators_improving():
    econ = ([ind(f'L{i}', 'Labor', f'L{i}') for i in range(4)])
    series = {f'L{i}': dated(jump(1 if i < 3 else -1)) for i in range(4)}
    out = mm.compute(series, econ)
    assert out['growth_diffusion'] == 0.75


# ------------------------------------------------------------ robustness

def test_indicator_without_history_is_skipped_not_fatal():
    econ = [ind('CPI YoY', 'Inflation', 'CPIAUCSL'),
            ind('Core CPI YoY', 'Inflation', 'CPILFESL')]
    out = mm.compute({'CPIAUCSL': dated(jump(1))}, econ)
    assert out['inflation_score'] > 0
    assert [r['name'] for r in out['indicators'] if r['momentum_z'] is None] == ['Core CPI YoY']


def test_scores_are_none_when_nothing_can_be_computed():
    out = mm.compute({}, [ind('CPI YoY', 'Inflation', 'CPIAUCSL')])
    assert out['inflation_score'] is None
    assert out['growth_score'] is None


def test_unknown_indicator_name_falls_back_to_positive_polarity():
    econ = [ind('Some New Print', 'Activity', 'XYZ')]
    out = mm.compute({'XYZ': dated(jump(1))}, econ)
    assert out['growth_score'] > 0
