import pytest

from us import macro


def book(growth=0, inflation=0, since='2026-08-03', policy=None, transmission=None,
         report_date='2026-08-14'):
    return {
        'report_date': report_date,
        'horizon': '3-6개월',
        'regime': {'growth': growth, 'inflation': inflation, 'since': since,
                   'thesis': '테스트용'},
        'policy_path': policy or {'stance': 'cut', 'timing': '2026-09 FOMC',
                                  'prob_pct': 68.0, 'thesis': '테스트용',
                                  'falsifier': 'Core PCE 3.5% 재상회'},
        'transmission': transmission or {
            k: {'direction': 0, 'since': since, 'channel': '테스트용', 'confirm': '테스트용'}
            for k in macro.TRANSMISSION_ASSETS},
        'last_seen': {},
    }


def metrics(growth=0.0, inflation=0.0, new_releases=()):
    return {
        'growth_score': growth,
        'inflation_score': inflation,
        'growth_diffusion': 0.5,
        'inflation_diffusion': 0.5,
        'new_releases': list(new_releases),
        'indicators': [],
    }


# ---------------------------------------------------------------- regime grid

def test_every_grid_cell_has_a_distinct_name():
    names = [macro.regime_name(g, i) for g in (-1, 0, 1) for i in (-1, 0, 1)]
    assert len(names) == 9
    assert len(set(names)) == 9


def test_regime_name_rejects_out_of_range_axis():
    with pytest.raises(ValueError):
        macro.regime_name(2, 0)


def test_classify_uses_cut_points():
    assert macro.classify(0.9) == 1
    assert macro.classify(-0.9) == -1
    assert macro.classify(0.1) == 0
    assert macro.classify(None) is None


# ------------------------------------------------------- new releases gate

def test_regime_frozen_when_no_new_release_even_if_scores_moved():
    ev = macro.evaluate(book(), metrics(growth=-1.5, new_releases=[]), '2026-08-14')
    assert ev['regime_change_allowed'] is False
    assert ev['regime_block'] == 'no_new_release'
    assert ev['allowed_regimes'] == [[0, 0]]


def test_regime_may_move_one_axis_when_a_new_release_lands():
    ev = macro.evaluate(book(), metrics(growth=-1.5, new_releases=['Retail Sales MoM']),
                        '2026-08-14')
    assert ev['regime_change_allowed'] is True
    assert [0, 0] in ev['allowed_regimes']
    assert [-1, 0] in ev['allowed_regimes']


def test_diagonal_moves_are_never_allowed():
    ev = macro.evaluate(book(),
                        metrics(growth=-1.5, inflation=1.5, new_releases=['CPI YoY']),
                        '2026-08-14')
    assert [-1, 1] not in ev['allowed_regimes']
    assert [-1, 0] in ev['allowed_regimes']
    assert [0, 1] in ev['allowed_regimes']


def test_move_only_toward_what_the_scores_imply():
    ev = macro.evaluate(book(), metrics(growth=-1.5, new_releases=['NFP']), '2026-08-14')
    assert [1, 0] not in ev['allowed_regimes']


def test_lock_blocks_a_second_move_within_five_business_days():
    ev = macro.evaluate(book(since='2026-08-13'),
                        metrics(growth=-1.5, new_releases=['NFP']), '2026-08-14')
    assert ev['regime_change_allowed'] is False
    assert ev['regime_block'] == 'lock_5bd'


def test_stale_book_waives_the_lock():
    ev = macro.evaluate(book(since='2026-08-13', report_date='2026-08-04'),
                        metrics(growth=-1.5, new_releases=['NFP']), '2026-08-14')
    assert ev['stale'] is True
    assert ev['regime_change_allowed'] is True


def test_implied_regime_is_reported_even_when_movement_is_blocked():
    ev = macro.evaluate(book(), metrics(growth=-1.5, inflation=1.5), '2026-08-14')
    assert ev['implied'] == {'growth': -1, 'inflation': 1,
                             'name': macro.regime_name(-1, 1)}


def test_days_held_counts_business_days_inclusive():
    ev = macro.evaluate(book(since='2026-08-10'), metrics(), '2026-08-14')
    assert ev['regime']['days_held'] == 5


def test_bootstrap_when_no_prior_book():
    ev = macro.evaluate(None, metrics(), '2026-08-14')
    assert ev['bootstrap'] is True
    assert ev['regime'] is None


# ------------------------------------------------------------- policy path

def test_policy_path_carries_over_and_is_frozen_without_a_release():
    ev = macro.evaluate(book(), metrics(), '2026-08-14')
    assert ev['policy']['timing'] == '2026-09 FOMC'
    assert ev['policy']['change_allowed'] is False
    assert ev['policy']['change_block'] == 'no_new_release'


def test_policy_path_opens_on_a_new_release():
    ev = macro.evaluate(book(), metrics(new_releases=['CPI YoY']), '2026-08-14')
    assert ev['policy']['change_allowed'] is True


# ------------------------------------------------------------ transmission

def test_transmission_rows_cover_every_stance_asset():
    ev = macro.evaluate(book(), metrics(), '2026-08-14')
    assert set(ev['transmission']) == set(macro.TRANSMISSION_ASSETS)


def test_transmission_frozen_without_a_release():
    b = book(transmission={k: {'direction': 1, 'since': '2026-08-03'}
                           for k in macro.TRANSMISSION_ASSETS})
    ev = macro.evaluate(b, metrics(), '2026-08-14')
    row = ev['transmission']['equities']
    assert row['allowed_directions'] == [0, 1]  # holding, or stepping back to neutral


def test_transmission_may_step_away_from_neutral_on_a_release():
    ev = macro.evaluate(book(), metrics(new_releases=['CPI YoY']), '2026-08-14')
    assert ev['transmission']['bonds']['allowed_directions'] == [-1, 0, 1]


def test_transmission_never_flips_sign_in_one_day():
    b = book(transmission={k: {'direction': -1, 'since': '2026-08-03'}
                           for k in macro.TRANSMISSION_ASSETS})
    ev = macro.evaluate(b, metrics(new_releases=['CPI YoY']), '2026-08-14')
    assert 1 not in ev['transmission']['fx']['allowed_directions']


# -------------------------------------------------------------- transitions

def test_validate_regime_transition_rejects_a_diagonal_move():
    ev = macro.evaluate(book(), metrics(growth=-1.5, new_releases=['NFP']), '2026-08-14')
    ok, why = macro.validate_regime_transition((0, 0), (-1, 1), ev)
    assert ok is False
    assert why == 'two_step'


def test_validate_regime_transition_rejects_a_step_the_scores_do_not_imply():
    ev = macro.evaluate(book(), metrics(growth=-1.5, new_releases=['NFP']), '2026-08-14')
    ok, why = macro.validate_regime_transition((0, 0), (1, 0), ev)
    assert ok is False
    assert why == 'not_allowed'


def test_validate_regime_transition_accepts_an_allowed_move():
    ev = macro.evaluate(book(), metrics(growth=-1.5, new_releases=['NFP']), '2026-08-14')
    ok, why = macro.validate_regime_transition((0, 0), (-1, 0), ev)
    assert ok is True
    assert why is None


def test_conflicts_pairs_macro_direction_against_stance_grade():
    trans = {k: {'direction': 0, 'since': '2026-08-03'} for k in macro.TRANSMISSION_ASSETS}
    trans['bonds']['direction'] = 1
    stance = {'assets': {'bonds': {'grade': -1}, 'equities': {'grade': 0}}}
    assert macro.conflicts(trans, stance) == ['bonds']


def test_no_conflict_when_signs_agree_or_either_side_is_neutral():
    trans = {k: {'direction': 0, 'since': '2026-08-03'} for k in macro.TRANSMISSION_ASSETS}
    trans['equities']['direction'] = 1
    stance = {'assets': {'equities': {'grade': 2}, 'bonds': {'grade': -1}}}
    assert macro.conflicts(trans, stance) == []


# ------------------------------------------------------ transmission groups

def test_groups_cover_every_asset_exactly_once():
    seen = [a for _, _, assets in macro.TRANSMISSION_GROUPS for a in assets]
    assert sorted(seen) == sorted(macro.TRANSMISSION_ASSETS)


def test_group_of_maps_an_asset_to_its_channel():
    assert macro.group_of('bonds') == 'rates'
    assert macro.group_of('ai_infra') == 'ai_cycle'


def test_group_of_rejects_an_unknown_asset():
    with pytest.raises(ValueError):
        macro.group_of('crypto')


# ---------------------------------------------------- headline releases pass-through

def test_headline_releases_reach_the_writer_contract():
    m = metrics(new_releases=['CPI YoY'])
    m['headline_releases'] = [{'name': 'CPI YoY', 'key': 'cpi-yoy', 'actual': 3.54,
                               'agency': 'BLS', 'url': 'https://example.test'}]
    ev = macro.evaluate(book(), m, '2026-08-14')
    assert ev['headline_releases'][0]['key'] == 'cpi-yoy'


def test_headline_releases_default_to_empty():
    ev = macro.evaluate(book(), metrics(), '2026-08-14')
    assert ev['headline_releases'] == []


# --- 축약일 판정 (2026-08-30 사용자 지시) ---

ABBREV_BOOK = {
    'report_date': '2026-08-26',
    'regime': {'growth': -1, 'inflation': 0, 'since': '2026-08-26'},
    'policy_path': {'timing': '2026-12', 'prob_pct': 68.4},
    'transmission': {},
    'axis_directions': {'Labor': '보합', 'Activity': '악화', 'Consumption': '악화',
                        'Inflation': '둔화'},
}
ABBREV_AXES = {'Labor': {'direction': '보합'}, 'Activity': {'direction': '악화'},
               'Consumption': {'direction': '악화'}, 'Inflation': {'direction': '둔화'}}
QUIET = {
    'report_date': '2026-08-27',
    'growth_score': -0.377, 'inflation_score': -0.327,
    'new_releases': ['Initial Jobless Claims'],
    'headline_releases': [{'key': 'claims', 'tier': 2}],
    'axis_summary': ABBREV_AXES,
}


def test_quiet_day_is_abbreviated():
    ev = macro.evaluate(ABBREV_BOOK, QUIET, '2026-08-27')
    assert ev['abbreviated'] is True
    assert ev['abbreviated_reason'] is None
    assert ev['axis_directions']['Activity'] == '악화'


def test_tier1_release_is_not_abbreviated():
    m = dict(QUIET, headline_releases=[{'key': 'cpi', 'tier': 1}])
    ev = macro.evaluate(ABBREV_BOOK, m, '2026-08-27')
    assert ev['abbreviated'] is False
    assert 'tier 1' in ev['abbreviated_reason']


def test_axis_direction_change_is_not_abbreviated():
    m = dict(QUIET, axis_summary=dict(ABBREV_AXES, Labor={'direction': '악화'}))
    ev = macro.evaluate(ABBREV_BOOK, m, '2026-08-27')
    assert ev['abbreviated'] is False
    assert '고용' in ev['abbreviated_reason']


def test_policy_condition_is_gone_not_dead_code():
    """전일 값끼리 비교하던 죽은 조건을 없앴다 — 정책 경로는 macro_gate가 본다."""
    from us.macro import _abbreviated
    ok, why = _abbreviated(ABBREV_BOOK, QUIET, [(-1, 0)], ABBREV_BOOK['axis_directions'])
    assert ok is True and why is None


def test_first_day_without_stored_directions_still_abbreviates():
    book = {k: v for k, v in ABBREV_BOOK.items() if k != 'axis_directions'}
    assert macro.evaluate(book, QUIET, '2026-08-27')['abbreviated'] is True
