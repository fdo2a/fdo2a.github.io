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


# ------------------------------------------------------ headline releases

def test_only_newly_released_indicators_become_headline_releases():
    econ = [ind('CPI YoY', 'Inflation', 'CPIAUCSL', actual=3.5, ref='2026-07-01'),
            ind('Retail Sales MoM', 'Consumption', 'RSAFS', actual=0.4, ref='2026-07-01')]
    series = {'CPIAUCSL': dated(jump(1)), 'RSAFS': dated(jump(1))}
    out = mm.compute(series, econ, last_seen={'CPI YoY': ['2026-07-01', 3.5]})
    assert [r['key'] for r in out['headline_releases']] == ['retail-sales']


def test_indicators_from_one_press_release_collapse_into_one_block():
    """CPI YoY and CPI MoM are the same BLS release — dissecting it twice is waste."""
    econ = [ind('CPI YoY', 'Inflation', 'CPIAUCSL', actual=3.54),
            ind('CPI MoM', 'Inflation', 'CPIAUCSL', actual=0.07),
            ind('Core CPI YoY', 'Inflation', 'CPILFESL', actual=2.79)]
    series = {'CPIAUCSL': dated(jump(1)), 'CPILFESL': dated(jump(1))}
    out = mm.compute(series, econ)
    assert len(out['headline_releases']) == 1
    rel = out['headline_releases'][0]
    assert rel['key'] == 'cpi'
    assert [i['name'] for i in rel['indicators']] == ['CPI YoY', 'CPI MoM', 'Core CPI YoY']


def test_release_carries_the_primary_source():
    econ = [ind('Nonfarm Payrolls (chg)', 'Labor', 'PAYEMS', actual=-23.0)]
    out = mm.compute({'PAYEMS': dated(jump(1))}, econ)
    rel = out['headline_releases'][0]
    assert rel['key'] == 'employment'
    assert rel['agency'] == 'BLS'
    assert rel['url'].startswith('https://')
    assert rel['indicators'][0]['actual'] == -23.0


def test_the_primary_indicator_is_the_biggest_mover_in_the_release():
    econ = [ind('Unemployment Rate', 'Labor', 'UNRATE', actual=4.1),
            ind('Nonfarm Payrolls (chg)', 'Labor', 'PAYEMS', actual=-23.0)]
    series = {'UNRATE': dated(jump(1)),
              'PAYEMS': dated(jump(1)[:-3] + [400.0] * 3)}
    out = mm.compute(series, econ)
    assert out['headline_releases'][0]['primary'] == 'Nonfarm Payrolls (chg)'


def test_market_moving_releases_outrank_secondary_ones():
    econ = [ind('New Home Sales', 'Activity', 'HSN1F'),
            ind('CPI YoY', 'Inflation', 'CPIAUCSL')]
    series = {'HSN1F': dated(jump(1)), 'CPIAUCSL': dated(jump(1))}
    out = mm.compute(series, econ)
    assert [r['key'] for r in out['headline_releases']][0] == 'cpi'


def test_every_market_moving_release_is_promoted():
    """A tier-1 print never gets crowded out — those are the ones the brief exists for."""
    econ = [ind('CPI YoY', 'Inflation', 'CPIAUCSL'),
            ind('Nonfarm Payrolls (chg)', 'Labor', 'PAYEMS'),
            ind('Retail Sales MoM', 'Consumption', 'RSAFS'),
            ind('Core PCE YoY', 'Inflation', 'PCEPILFE'),
            ind('Real GDP Growth QoQ (ann.)', 'Activity', 'A191RL1Q225SBEA')]
    series = {i['fred_id']: dated(jump(1)) for i in econ}
    out = mm.compute(series, econ)
    assert {r['key'] for r in out['headline_releases']} == {
        'cpi', 'employment', 'retail-sales', 'pce', 'gdp'}


def test_secondary_releases_are_capped():
    econ = [ind(f'X{i}', 'Activity', f'X{i}') for i in range(6)]
    series = {f'X{i}': dated(jump(1)) for i in range(6)}
    out = mm.compute(series, econ)
    assert len(out['headline_releases']) == mm.MAX_SECONDARY_RELEASES
    assert len(out['new_releases']) == 6


def test_secondary_cap_does_not_eat_into_tier_one():
    econ = ([ind('CPI YoY', 'Inflation', 'CPIAUCSL')]
            + [ind(f'X{i}', 'Activity', f'X{i}') for i in range(6)])
    series = {i['fred_id']: dated(jump(1)) for i in econ}
    out = mm.compute(series, econ)
    keys = [r['key'] for r in out['headline_releases']]
    assert 'cpi' in keys
    assert len(keys) == 1 + mm.MAX_SECONDARY_RELEASES


def test_indicator_without_a_known_source_stands_alone_without_a_url():
    econ = [ind('Some New Print', 'Activity', 'XYZ')]
    out = mm.compute({'XYZ': dated(jump(1))}, econ)
    rel = out['headline_releases'][0]
    assert rel['key'] == 'some-new-print'
    assert rel['url'] is None and rel['agency'] is None


# --------------------------------------------------- release components

def promoted(key='cpi'):
    return [{'key': key, 'label': 'L', 'tier': 1, 'agency': 'BLS', 'url': 'u',
             'primary': 'CPI YoY', 'max_abs_z': 1.0, 'indicators': []}]


def test_component_specs_only_cover_promoted_releases():
    specs = mm.component_specs(promoted('cpi'))
    assert specs
    assert {s['release'] for s in specs} == {'cpi'}
    assert all(s['fred_id'] for s in specs)


def test_component_specs_are_empty_for_a_release_without_a_breakdown():
    assert mm.component_specs(promoted('michigan')) == []


def test_attach_components_fills_values_from_history():
    rels = promoted('cpi')
    specs = mm.component_specs(rels)
    series = {s['fred_id']: dated([100, 110]) for s in specs}
    mm.attach_components(rels, series)
    comps = rels[0]['components']
    assert comps and all(c['actual'] is not None for c in comps)
    assert comps[0]['ref_period'] == dated([100, 110])[-1][0]


def test_payroll_components_are_level_differences_in_thousands():
    rels = promoted('employment')
    specs = mm.component_specs(rels)
    series = {s['fred_id']: dated([1000.0, 1023.0]) for s in specs}
    mm.attach_components(rels, series)
    mfg = [c for c in rels[0]['components'] if c['transform'] == 'mom_diff']
    assert mfg and mfg[0]['actual'] == pytest.approx(23.0)


def test_a_component_whose_series_is_missing_is_dropped_not_fatal():
    rels = promoted('cpi')
    specs = mm.component_specs(rels)
    series = {specs[0]['fred_id']: dated([100, 110])}
    mm.attach_components(rels, series)
    assert len(rels[0]['components']) == 1


def test_attach_components_is_a_no_op_without_promoted_releases():
    rels = []
    mm.attach_components(rels, {})
    assert rels == []


# ------------------------------------------------- reader-facing framing

def test_indicators_carry_a_korean_label():
    econ = [ind('Initial Jobless Claims', 'Labor', 'ICSA')]
    out = mm.compute({'ICSA': dated(jump(1))}, econ)
    assert out['indicators'][0]['label_ko'] == '신규 실업수당 청구'


def test_falling_claims_read_as_improvement_not_as_a_negative_number():
    """The published 08-17 brief called rising-z claims '나쁜 방향' — sign inverted.
    Direction is polarity-adjusted so the writer never has to reason about the sign."""
    econ = [ind('Initial Jobless Claims', 'Labor', 'ICSA')]
    falling = dated(jump(-1))
    out = mm.compute({'ICSA': falling}, econ)
    assert out['indicators'][0]['direction'] == '개선'


def test_rising_claims_read_as_deterioration():
    econ = [ind('Initial Jobless Claims', 'Labor', 'ICSA')]
    out = mm.compute({'ICSA': dated(jump(1))}, econ)
    assert out['indicators'][0]['direction'] == '악화'


def test_inflation_axis_speaks_of_reacceleration_not_improvement():
    """Positive on the inflation axis means hotter, never better — a separate vocabulary
    so nobody has to remember which way 'good' points."""
    econ = [ind('CPI YoY', 'Inflation', 'CPIAUCSL')]
    out = mm.compute({'CPIAUCSL': dated(jump(1))}, econ)
    assert out['indicators'][0]['direction'] == '재가속'
    assert out['axis_summary']['Inflation']['direction'] == '재가속'


def test_cooling_prices_read_as_slowing():
    econ = [ind('CPI YoY', 'Inflation', 'CPIAUCSL')]
    out = mm.compute({'CPIAUCSL': dated(jump(-1))}, econ)
    assert out['indicators'][0]['direction'] == '둔화'


def test_axis_summary_states_breadth_in_words():
    econ = [ind(f'L{i}', 'Labor', f'L{i}') for i in range(7)]
    series = {f'L{i}': dated(jump(1 if i < 5 else -1)) for i in range(7)}
    out = mm.compute(series, econ)
    assert out['axis_summary']['Labor']['breadth_ko'] == '일곱 중 다섯이 개선'


def rows(axis, *scores):
    return [{'axis': axis, 'signed_z': z} for z in scores]


def test_breadth_is_counted_against_the_axis_verdict():
    """Breadth and magnitude can diverge; the phrase must not contradict the badge
    beside it. Narrow support is said with 「만」."""
    # one heavy cooler outweighs three mild hotter prints
    got = mm.breadth_phrase(rows('Inflation', -4.0, 0.4, 0.4, 0.4), 'Inflation')
    assert got == '넷 중 하나만 둔화'


def test_broad_support_uses_the_plain_particle():
    assert mm.breadth_phrase(rows('Labor', 1.0, 1.0, 1.0, -1.0), 'Labor') == '넷 중 셋이 개선'


def test_a_flat_axis_says_so_rather_than_picking_a_side():
    got = mm.breadth_phrase(rows('Labor', 1.0, -1.0), 'Labor')
    assert '나머지는 반대' in got


def test_strength_is_banded_not_a_raw_score():
    econ = [ind('CPI YoY', 'Inflation', 'CPIAUCSL')]
    out = mm.compute({'CPIAUCSL': dated(jump(1))}, econ)
    assert out['indicators'][0]['strength'] in ('뚜렷', '완만', '미미')


def test_axis_summary_counts_how_many_point_which_way():
    econ = [ind(f'L{i}', 'Labor', f'L{i}') for i in range(4)]
    series = {f'L{i}': dated(jump(1 if i < 3 else -1)) for i in range(4)}
    out = mm.compute(series, econ)
    labor = out['axis_summary']['Labor']
    assert labor['improving'] == 3
    assert labor['total'] == 4
    assert labor['direction'] == '개선'


def test_axis_summary_lists_the_movers_that_mattered():
    econ = [ind(f'L{i}', 'Labor', f'L{i}') for i in range(5)]
    series = {f'L{i}': dated(jump(1)) for i in range(5)}
    out = mm.compute(series, econ)
    leaders = out['axis_summary']['Labor']['leaders']
    assert 1 <= len(leaders) <= 3
    assert all({'label_ko', 'direction', 'actual'} <= set(x) for x in leaders)


def test_axis_summary_covers_an_axis_with_nothing_computable():
    out = mm.compute({}, [ind('CPI YoY', 'Inflation', 'CPIAUCSL')])
    assert out['axis_summary']['Inflation']['direction'] is None
