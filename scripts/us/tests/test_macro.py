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
