import pytest

from bond.stance import AXES, bootstrap, evaluate, label_for, validate_transition


def _book(grade=0, since='2026-08-20', triggers=None, key='duration'):
    b = bootstrap('2026-08-27')
    b['assets'][key].update({'grade': grade, 'since': since,
                             'triggers': triggers or {'increase': [], 'decrease': []}})
    return b


MET = {'increase': [{'kind': 'level', 'metric': 'us10y_level', 'op': '>=',
                     'value': 4.5, 'toward': '+', 'desc': 'x'}], 'decrease': []}


class TestVocabulary:
    def test_three_axes(self):
        assert set(AXES) == {'duration', 'curve', 'credit'}

    def test_labels_are_closed(self):
        assert label_for('curve', 2) == '스티프너'
        assert label_for('credit', -2) == '크레딧 UW'
        with pytest.raises(ValueError):
            label_for('duration', 3)


class TestDiscipline:
    def test_bootstrap_starts_neutral(self):
        b = bootstrap('2026-08-27')
        assert all(a['grade'] == 0 for a in b['assets'].values())

    def test_no_trigger_no_move(self):
        ev = evaluate(_book(), {'us10y_level': 4.67}, '2026-08-27')
        assert ev['assets']['duration']['allowed_grades'] == [0]
        assert ev['assets']['duration']['increase_block'] == 'no_trigger_met'

    def test_met_trigger_opens_one_step(self):
        ev = evaluate(_book(triggers=MET), {'us10y_level': 4.67}, '2026-08-27')
        assert ev['assets']['duration']['allowed_grades'] == [0, 1]

    def test_lock_blocks_increase_for_three_business_days(self):
        ev = evaluate(_book(grade=1, since='2026-08-26', triggers=MET),
                      {'us10y_level': 4.67}, '2026-08-27')
        assert ev['assets']['duration']['increase_block'] == 'lock_3bd'
        assert 2 not in ev['assets']['duration']['allowed_grades']

    def test_decrease_always_allowed(self):
        ev = evaluate(_book(grade=2, since='2026-08-26'), {}, '2026-08-27')
        assert 1 in ev['assets']['duration']['allowed_grades']

    def test_unknown_metric_cannot_add_risk(self):
        ev = evaluate(_book(triggers=MET), {}, '2026-08-27')
        assert ev['assets']['duration']['increase'][0]['status'] == 'UNKNOWN'
        assert ev['assets']['duration']['can_increase'] is False

    def test_sign_flip_takes_two_days(self):
        ev = evaluate(_book(grade=-1, since='2026-08-20'), {}, '2026-08-27')
        ok, why = validate_transition('duration', -1, 1,
                                      ev['assets']['duration'])
        assert not ok and why == 'two_step'

    def test_curve_and_credit_share_the_same_rules(self):
        for key in ('curve', 'credit'):
            ev = evaluate(_book(key=key), {}, '2026-08-27')
            assert ev['assets'][key]['allowed_grades'] == [0]
