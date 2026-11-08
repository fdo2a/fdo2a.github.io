"""Scored vs anatomy indicators, the book state, and indicators introduced mid-life.

2026-11-08 (A단계): an indicator can be on the page to be *dissected* without moving
the regime (`role: anatomy`, e.g. the Philadelphia Fed index), the tier-2 cap only
guards the first run, and a new row (Census 4) must not open the regime gate on the
day it first appears.
"""
from us import macro, macro_metrics as mm
from us.tests.test_macro_metrics import dated, ind, jump


def _econ(role=None, **kw):
    row = ind(**kw)
    if role:
        row['role'] = role
    return row


PHILLY = dict(name='Philly Fed Manufacturing', axis='Activity', fred_id='PHL', actual=20.9,
              previous=37.8, ref='2026-10-01')
CLAIMS = dict(name='Initial Jobless Claims', axis='Labor', fred_id='ICSA', actual=189.0,
              ref='2026-10-31')


def test_anatomy_row_reaches_the_page_but_not_the_scores():
    econ = [_econ(**CLAIMS), _econ(role='anatomy', **PHILLY)]
    series = {'ICSA': dated(jump(-1)), 'PHL': dated(jump(1))}
    out = mm.compute(series, econ, last_seen={'Initial Jobless Claims': ['2026-10-24', 190.0],
                                              'Philly Fed Manufacturing': ['2026-09-01', 37.8]})
    assert out['new_releases'] == ['Initial Jobless Claims']
    assert out['anatomy_releases'] == ['Philly Fed Manufacturing']
    keys = {r['key']: r for r in out['headline_releases']}
    assert keys['philly-fed']['role'] == 'anatomy'
    assert keys['claims']['role'] == 'scored'
    # Activity has only the anatomy row, so it has no score at all.
    assert out['axis_scores']['Activity'] is None
    assert out['axis_summary']['Activity']['total'] == 0
    row = next(r for r in out['indicators'] if r['name'] == 'Philly Fed Manufacturing')
    assert row['role'] == 'anatomy' and row['is_new'] is True


def test_an_anatomy_only_day_cannot_move_the_regime_or_the_policy():
    econ = [_econ(**CLAIMS), _econ(role='anatomy', **PHILLY)]
    series = {'ICSA': dated(jump(-1)), 'PHL': dated(jump(1))}
    out = mm.compute(series, econ, last_seen={'Initial Jobless Claims': ['2026-10-31', 189.0],
                                              'Philly Fed Manufacturing': ['2026-09-01', 37.8]})
    assert out['new_releases'] == []
    assert [r['key'] for r in out['headline_releases']] == ['philly-fed']
    book = {'report_date': '2026-11-18',
            'regime': {'growth': 0, 'inflation': 0, 'since': '2026-09-01'},
            'policy_path': {'timing': '12월'}}
    ev = macro.evaluate(book, out, '2026-11-19')
    assert ev['regime_block'] == 'no_new_release'
    assert ev['policy']['change_allowed'] is False
    assert all(r['allowed_directions'] == [r['direction']] for r in ev['transmission'].values())
    # The anatomy block still has to be written.
    assert ev['headline_releases'][0]['key'] == 'philly-fed'


def test_an_anatomy_only_day_on_a_fresh_book_still_opens_nothing_scored():
    econ = [_econ(role='anatomy', **PHILLY)]
    out = mm.compute({'PHL': dated(jump(1))}, econ, last_seen={})
    assert out['new_releases'] == []
    assert out['growth_score'] is None


def test_tier_one_check_for_the_fold_reads_scored_releases_only():
    metrics = {'headline_releases': [{'key': 'x', 'tier': 1, 'role': 'anatomy'}],
               'axis_summary': {}}
    ok, _ = macro._abbreviated({'axis_directions': {}}, metrics, [[0, 0]], {})
    assert ok is True
    metrics['headline_releases'][0]['role'] = 'scored'
    ok, why = macro._abbreviated({'axis_directions': {}}, metrics, [[0, 0]], {})
    assert ok is False and 'tier 1' in why


def _secondaries(n=6):
    econ = [ind(f'X{i}', 'Activity', f'X{i}', ref='2026-10-01') for i in range(n)]
    series = {f'X{i}': dated(jump(1)) for i in range(n)}
    seen = {f'X{i}': ['2026-09-01', 0.5] for i in range(n)}
    return econ, series, seen


def test_secondary_releases_are_not_capped_on_a_normal_day():
    econ, series, seen = _secondaries()
    out = mm.compute(series, econ, last_seen=seen)
    assert len(out['headline_releases']) == 6


def test_cap_applies_only_while_the_book_is_absent_corrupt_or_empty():
    econ, series, _ = _secondaries()
    for state, seen in (('absent', None), ('corrupt', None), ('empty', {})):
        out = mm.compute(series, econ, last_seen=seen, book_state=state)
        assert len(out['headline_releases']) == mm.MAX_SECONDARY_RELEASES, state
        assert out['book_state'] == state
    # Inferred when not passed.
    assert mm.compute(series, econ)['book_state'] == 'absent'
    assert mm.compute(series, econ, last_seen={})['book_state'] == 'empty'


NEW_ROW = dict(name='Housing Starts', axis='Activity', fred_id='HOUST', actual=1221.0,
               previous=1288.0, ref='2026-09-01')
OLD_ROW = dict(name='New Home Sales', axis='Activity', fred_id='HSN1F', actual=676.0,
               previous=680.0, ref='2026-09-01')


def _intro(introduced_new=None):
    econ = [_econ(**OLD_ROW), _econ(**NEW_ROW)]
    series = {'HSN1F': dated(jump(1)), 'HOUST': dated(jump(-1))}
    seen = {'New Home Sales': ['2026-09-01', 676.0]}
    return mm.compute(series, econ, last_seen=seen, introduced_new=introduced_new)


def test_a_row_new_to_the_book_is_seeded_not_released():
    out = _intro()
    assert out['new_releases'] == [] and out['headline_releases'] == []
    assert out['introduced'] == ['Housing Starts']
    assert out['last_seen']['Housing Starts'] == ['2026-09-01', 1221.0]


def test_a_row_new_to_the_book_is_kept_out_of_the_scores_on_that_day():
    """The first day's composition change must not move an axis by itself."""
    out = _intro()
    alone = mm.compute({'HSN1F': dated(jump(1))}, [_econ(**OLD_ROW)],
                       last_seen={'New Home Sales': ['2026-09-01', 676.0]})
    assert out['axis_scores']['Activity'] == alone['axis_scores']['Activity']
    row = next(r for r in out['indicators'] if r['name'] == 'Housing Starts')
    assert row['introduced'] is True


def test_a_row_new_to_the_book_that_released_today_is_dissected_but_not_scored():
    out = _intro(introduced_new={'Housing Starts'})
    assert out['new_releases'] == []
    rel = out['headline_releases'][0]
    assert rel['key'] == 'housing-starts' and rel['role'] == 'anatomy'


def test_the_day_after_introduction_the_row_counts():
    econ = [_econ(**OLD_ROW), _econ(**NEW_ROW)]
    series = {'HSN1F': dated(jump(1)), 'HOUST': dated(jump(-1))}
    seen = {'New Home Sales': ['2026-09-01', 676.0], 'Housing Starts': ['2026-09-01', 1221.0]}
    out = mm.compute(series, econ, last_seen=seen)
    assert out['introduced'] == []
    row = next(r for r in out['indicators'] if r['name'] == 'Housing Starts')
    assert row['introduced'] is False
    assert out['axis_summary']['Activity']['total'] == 2


def test_no_row_is_introduced_while_the_book_is_not_ok():
    econ = [_econ(**OLD_ROW), _econ(**NEW_ROW)]
    series = {'HSN1F': dated(jump(1)), 'HOUST': dated(jump(-1))}
    out = mm.compute(series, econ, last_seen=None)
    assert out['introduced'] == []
    assert set(out['new_releases']) == {'New Home Sales', 'Housing Starts'}


def test_a_row_missing_today_keeps_its_last_seen_reading():
    """A failed fetch must not make tomorrow read an unchanged print as new."""
    econ = [_econ(**OLD_ROW)]
    seen = {'New Home Sales': ['2026-09-01', 676.0], 'Housing Starts': ['2026-09-01', 1221.0]}
    out = mm.compute({'HSN1F': dated(jump(1))}, econ, last_seen=seen)
    assert out['last_seen']['Housing Starts'] == ['2026-09-01', 1221.0]


def test_factory_orders_absorb_the_durable_revision_of_the_same_month():
    econ = [ind('Durable Goods Orders MoM', 'Activity', 'DGORDER', actual=1.91, ref='2026-09-01'),
            ind('Factory Orders MoM', 'Activity', 'AMTMNO', actual=1.84, ref='2026-09-01')]
    series = {'DGORDER': dated(jump(1)[:-3] + [400.0] * 3), 'AMTMNO': dated(jump(1))}
    seen = {'Durable Goods Orders MoM': ['2026-09-01', 1.84],
            'Factory Orders MoM': ['2026-08-01', 0.3]}
    out = mm.compute(series, econ, last_seen=seen)
    assert [r['key'] for r in out['headline_releases']] == ['factory-orders']
    rel = out['headline_releases'][0]
    assert rel['primary'] == 'Factory Orders MoM'
    assert {i['name'] for i in rel['indicators']} == {'Factory Orders MoM',
                                                       'Durable Goods Orders MoM'}


def test_durable_goods_of_another_month_stay_their_own_release():
    econ = [ind('Durable Goods Orders MoM', 'Activity', 'DGORDER', actual=0.5, ref='2026-10-01'),
            ind('Factory Orders MoM', 'Activity', 'AMTMNO', actual=1.84, ref='2026-09-01')]
    series = {'DGORDER': dated(jump(1)), 'AMTMNO': dated(jump(1))}
    seen = {'Durable Goods Orders MoM': ['2026-09-01', 1.91],
            'Factory Orders MoM': ['2026-08-01', 0.3]}
    out = mm.compute(series, econ, last_seen=seen)
    assert {r['key'] for r in out['headline_releases']} == {'factory-orders', 'durable-goods'}
