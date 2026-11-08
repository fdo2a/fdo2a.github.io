"""Components both FRED (as of the release date) and the agency's text confirm.

Fixtures under fixtures/anatomy/ are the first 12,000 characters of real US-government
releases (public domain) as `fetch_releases` flattened them. The Philadelphia Fed's
pages are not public domain, so its cases below are paraphrased sentences in the same
shape, not the bank's text.
"""
import json
import os

import pytest

from scripts.us import anatomy as A
from scripts.us import fred
from scripts.us.release_text import TRUNCATED
from scripts.us.tests.test_fred import FakeOpener, _client

FX = os.path.join(os.path.dirname(__file__), 'fixtures', 'anatomy')

# key -> (headline reference period, {component label: value the agency printed}).
REAL = {
    'cpi': ('2026-09-01', {'에너지': 5.2, '식품': 0.0, '주거비': 0.4, '중고차': 0.7,
                           '의료': 0.1, '휘발유': 9.1}),
    'ppi': ('2026-09-01', {'식품·에너지·무역서비스 제외': 0.5}),
    'employment': ('2026-10-01', {'헬스케어': 42000, '전문·사업서비스': 70000,
                                  '운수·창고': 25000, '제조업': 19000,
                                  '경제활동참가율': 61.9, '주당 노동시간': 34.4}),
    'claims': ('2026-10-31', {'계절조정 전 청구': 176698, '보험 실업률': 1.1}),
    'jolts': ('2026-09-01', {'채용': 5.4e6, '자발적 이직': 3.4e6, '해고': 1.6e6, '이직률': 2.1}),
    'industrial-production': ('2026-08-01', {'제조업 생산': -0.3, '광업': 0.1, '유틸리티': 1.8,
                                             '설비가동률': 76.3}),
    'durable-goods': ('2026-09-01', {'운송 제외': 0.5, '국방 제외': 2.2}),
    'new-home-sales': ('2026-09-01', {'재고 개월 수': 8.4, '판매가격 중위값': 400400,
                                      '판매 대기 재고': 476000}),
    'housing-starts': ('2026-09-01', {'단독주택 착공': 859000, '완공': 1192000}),
    'trade-balance': ('2026-09-01', {'수출': 321.5e9, '수입': 426.6e9, '상품수지': -135.9e9}),
    'construction-spending': ('2026-09-01', {'민간 건설': -2.4, '주거용(민간)': -5.5,
                                             '비주거용(민간)': 1.1, '공공 건설': -0.1}),
    'factory-orders': ('2026-09-01', {'출하': 1.3, '재고': 0.4, '미충족 주문': 0.9,
                                      '내구재 주문(수정)': 1.9}),
}


def _text(key):
    with open(os.path.join(FX, f'{key}.txt'), encoding='utf-8') as fh:
        return fh.read()


def _comp(key, label):
    return next(c for c in A.COMPONENTS[key] if c['label'] == label)


@pytest.mark.parametrize('key', sorted(REAL))
def test_every_registered_component_is_found_in_the_real_release(key):
    ref, want = REAL[key]
    text = _text(key)
    assert {c['label'] for c in A.COMPONENTS[key]} == set(want)
    for label, value in want.items():
        got, _, why = A.text_value(_comp(key, label), text, ref)
        assert why == 'ok', (key, label, why)
        assert got == pytest.approx(value), (key, label)


def test_another_month_finds_nothing():
    """「in September」 binds the month. 「over the month」 does not — it is the document's
    own month, which release_verify has already checked against the reference period."""
    text = 'The shelter index rose 0.4 percent in September after rising 0.3 percent in August.'
    got, _, why = A.text_value(_comp('cpi', '주거비'), text, '2026-10-01')
    assert got is None and why == 'not_in_text'


def test_an_average_in_the_same_sentence_is_not_the_value():
    text = ('Health care added 42,000 jobs in October, higher than the average monthly gain '
            'of 31,000 over the prior 12 months.')
    got, _, _ = A.text_value(_comp('employment', '헬스케어'), text, '2026-10-01')
    assert got == 42000


def test_a_component_named_only_in_a_list_is_not_found():
    text = ('Employment showed little change over the month in other major industries, '
            'including health care and manufacturing.')
    for label in ('헬스케어', '제조업'):
        assert A.text_value(_comp('employment', label), text, '2026-10-01')[2] == 'not_in_text'


def test_two_different_values_for_one_component_are_ambiguous():
    text = ('The shelter index rose 0.4 percent in September. '
            'The index for shelter increased 0.3 percent in September.')
    got, _, why = A.text_value(_comp('cpi', '주거비'), text, '2026-09-01')
    assert got is None and why == 'ambiguous_in_text'


def test_the_same_value_said_twice_is_fine():
    text = ('The shelter index rose 0.4 percent in September. '
            'The shelter index increased 0.4 percent over the month.')
    assert A.text_value(_comp('cpi', '주거비'), text, '2026-09-01')[0] == 0.4


def test_nothing_after_the_truncation_marker_counts():
    text = 'Something else.\n' + TRUNCATED + '\nThe shelter index rose 0.4 percent in September.'
    assert A.text_value(_comp('cpi', '주거비'), text, '2026-09-01')[2] == 'not_in_text'


def test_a_twelve_month_figure_is_not_a_monthly_one():
    text = 'The shelter index increased 3.2 percent over the last year.'
    assert A.text_value(_comp('cpi', '주거비'), text, '2026-09-01')[2] == 'not_in_text'


@pytest.mark.parametrize('sentence,value', [
    ('The energy index decreased 1.1 percent in September.', -1.1),
    ('The index for energy fell 1.1 percent in September.', -1.1),
    ('The energy index edged down 0.1 percent over the month.', -0.1),
    ('The energy index was unchanged in September.', 0.0),
])
def test_the_sign_comes_from_the_verb(sentence, value):
    assert A.text_value(_comp('cpi', '에너지'), sentence, '2026-09-01')[0] == value


def test_an_explicit_sign_in_brackets_is_read():
    text = 'Manufacturing employment continued to trend down in October (−19,000).'
    assert A.text_value(_comp('employment', '제조업'), text, '2026-10-01')[0] == -19000


def test_a_deficit_is_negative_and_a_surplus_does_not_fit():
    text = 'a decrease in the goods deficit of $0.7 billion to $135.9 billion and'
    assert A.text_value(_comp('trade-balance', '상품수지'), text, '2026-09-01')[0] == -135.9e9
    text = 'a decrease in the goods surplus of $0.7 billion to $135.9 billion and'
    assert A.text_value(_comp('trade-balance', '상품수지'), text, '2026-09-01')[2] == 'not_in_text'


def test_a_change_with_no_direction_word_is_not_guessed():
    comp = dict(_comp('cpi', '에너지'),
                patterns=(r'The energy index moved ' + A.V + r' percent in {M}',))
    assert A.text_value(comp, 'The energy index moved 1.1 percent in September.',
                        '2026-09-01')[2] == 'sign_unclear'


# Philadelphia Fed — paraphrased, not the bank's text.
PHILLY = ('The diffusion index for current general activity slipped to -3.4 in March. '
          'The new orders index fell 12 points to -8.0 this month, and the current shipments '
          'index edged down 2 points to 5.5. The employment index stayed positive but moved '
          'down 4 points to 6.1 in March. The prices paid index rose 3 points to 40.2, and '
          'the current prices received index climbed 6 points to 22.7. The diffusion index '
          'for future general activity dropped 9 points to 18.0. The future new orders index '
          'rose 4 points to 30.0.')


def test_philly_levels_keep_their_own_sign_and_skip_the_change_in_points():
    want = {'신규주문': -8.0, '출하': 5.5, '고용': 6.1, '지불가격': 40.2, '수취가격': 22.7,
            '6개월 뒤 전망': 18.0}
    for label, value in want.items():
        got, _, why = A.text_value(_comp('philly-fed', label), PHILLY, '2026-03-01')
        assert (got, why) == (value, 'ok'), label


# ------------------------------------------------------------- agreement

@pytest.mark.parametrize('fred_base,text,prec,step,ok', [
    (0.391, 0.4, 0.1, None, True),
    (0.349, 0.4, 0.1, None, False),
    (41600, 42000, 1000, 1000, True),
    (41400, 42000, 1000, 1000, False),
    (24800, 25000, 1000, 1000, True),
    (0.04, 0.0, None, None, True),        # 「was unchanged」
    (0.06, 0.0, None, None, False),
    (-0.254, -0.3, 0.1, None, True),
    (0.254, -0.3, 0.1, None, False),      # the sign is part of the figure
    (1398000, 1400000, 1000, None, False),
])
def test_agreement_is_rounding_to_the_texts_precision(fred_base, text, prec, step, ok):
    assert A.agrees(fred_base, text, prec, step) is ok


def test_cite_values_offer_the_agency_figure_and_the_korean_units():
    assert A.cite_values(41600, 1000, '명') == (42000, [42000, 42, 4.2])
    assert A.cite_values(5402000, 1e5, '건') == (5400000, [5400000, 5400, 540, 5.4])
    assert A.cite_values(321511e6, 1e8, '$B') == (321.5, [321.5, 3215])
    assert A.cite_values(0.391, 0.1, '%') == (0.4, [0.4])


# ------------------------------------------------------------ FRED round

def _row(date, start, end, value):
    return {'date': date, 'realtime_start': start, 'realtime_end': end, 'value': value}


D = '2026-10-15'
ROWS = [
    _row('2026-08-01', '2026-09-06', '2026-10-14', 100.0),
    _row('2026-08-01', '2026-10-15', '2026-10-15', 101.0),   # revised on D
    _row('2026-09-01', '2026-10-15', '2026-10-15', 102.01),  # first print on D
]


def test_round_value_reads_both_periods_as_of_the_release_date():
    value, why, detail = A.round_value(ROWS, '2026-09-01', D, 'mom_pct')
    assert why == 'ok'
    assert value == pytest.approx(1.0)
    assert detail['changed'] == ['current', 'previous']


def test_the_previous_period_need_not_change_on_the_release_date():
    rows = [_row('2026-08-01', '2026-09-06', '2026-10-15', 100.0), ROWS[2]]
    value, why, detail = A.round_value(rows, '2026-09-01', D, 'mom_diff')
    assert why == 'ok' and value == pytest.approx(2.01) and detail['changed'] == ['current']


def test_a_current_value_that_did_not_start_on_the_release_date_is_out():
    rows = [ROWS[0], _row('2026-09-01', '2026-10-14', '2026-10-15', 102.0)]
    value, why, _ = A.round_value(rows, '2026-09-01', D, 'level')
    assert value is None and why == 'not_published_on_release_date'


def test_a_missing_observation_or_previous_is_out():
    assert A.round_value([], '2026-09-01', D, 'level')[1] == 'no_value_on_release_date'
    assert A.round_value([ROWS[2]], '2026-09-01', D, 'mom_pct')[1] == \
        'no_previous_on_release_date'
    assert A.round_value(ROWS, '2026-09-01', None, 'level')[1] == 'no_period'


def test_a_dot_value_is_no_value():
    rows = [_row('2026-09-01', D, D, None)]
    assert A.round_value(rows, '2026-09-01', D, 'level')[1] == 'no_value_on_release_date'


def test_minus_7d_reads_the_week_before_the_headline_week():
    rows = [_row('2026-10-24', '2026-11-05', '2026-11-05', 1.1)]
    value, why, _ = A.round_value(rows, '2026-10-31', '2026-11-05', 'level', 'minus_7d')
    assert (value, why) == (1.1, 'ok')


def test_period_words_for_months_and_weeks():
    assert A.fill('in {M} {Y}', '2026-09-01') == 'in September 2026'
    assert A.fill('{WE} / {WE7}', '2026-10-31') == 'October 31 / October 24'
    assert A.period_dates('2026-01-01', 'mom_pct') == ('2026-01-01', '2025-12-01')


# -------------------------------------------------------------- pipeline

def _cpi_rel():
    return {'key': 'cpi', 'primary': 'CPI MoM',
            'indicators': [{'name': 'CPI MoM', 'ref_period': '2026-09-01', 'actual': 0.6}]}


FRED_CPI = {  # FRED value on D for each CPI component, as a month-on-month % change
    'CPIENGSL': 5.1957, 'CPIUFDSL': 0.048, 'CUSR0000SAH1': 0.3907, 'CUSR0000SETA02': 0.669,
    'CPIMEDSL': 0.1235, 'CUSR0000SETB01': 9.0938,
}
RD = '2026-10-14'


def _fetch(values, start=RD):
    def fetch(sid, obs_start, obs_end):
        if sid not in values:
            raise fred.FredError('boom')
        rows = [_row(obs_end, start, RD, 100.0 + values[sid])]
        if obs_start != obs_end:
            rows.insert(0, _row(obs_start, '2026-09-10', RD, 100.0))
        return rows
    return fetch


HEADLINE = [_row('2026-09-01', RD, RD, 330.0)]
OK_ROW = {'key': 'cpi', 'ok': True, 'verified': True,
          'checks': {'value': True, 'primary_checked': True}}


def test_produce_then_cross_check_keeps_what_both_sources_agree_on():
    rel = A.produce(_cpi_rel(), _fetch(FRED_CPI), RD, HEADLINE)
    assert rel['components'] == []
    assert all(c['round_ok'] for c in rel['anatomy']['candidates'])
    A.cross_check(rel, _text('cpi'), OK_ROW)
    assert rel['anatomy_status'] == 'complete'
    shown = {c['label']: c['actual'] for c in rel['components']}
    assert shown == {'에너지': 5.2, '식품': 0.0, '주거비': 0.4, '중고차': 0.7, '의료': 0.1,
                     '휘발유': 9.1}


def test_a_component_fred_and_the_text_disagree_on_is_dropped():
    vals = dict(FRED_CPI, CUSR0000SAH1=0.3)
    rel = A.cross_check(A.produce(_cpi_rel(), _fetch(vals), RD, HEADLINE), _text('cpi'), OK_ROW)
    assert '주거비' not in {c['label'] for c in rel['components']}
    cand = next(c for c in rel['anatomy']['candidates'] if c['fred_id'] == 'CUSR0000SAH1')
    assert cand['reason'] == 'fred_text_disagree'


def test_a_fetch_failure_drops_only_that_component():
    vals = {k: v for k, v in FRED_CPI.items() if k != 'CPIMEDSL'}
    rel = A.cross_check(A.produce(_cpi_rel(), _fetch(vals), RD, HEADLINE), _text('cpi'), OK_ROW)
    assert len(rel['components']) == 5
    cand = next(c for c in rel['anatomy']['candidates'] if c['fred_id'] == 'CPIMEDSL')
    assert cand['reason'].startswith('fetch_failed')


def test_a_headline_fred_did_not_publish_on_the_release_date_drops_everything():
    stale = [_row('2026-09-01', '2026-10-10', RD, 330.0)]
    rel = A.cross_check(A.produce(_cpi_rel(), _fetch(FRED_CPI), RD, stale), _text('cpi'), OK_ROW)
    assert rel['components'] == []
    assert rel['anatomy']['round'] == 'headline_not_published_on_release_date'
    assert rel['anatomy_status'] == 'text'          # the verified text is still there


def test_no_release_date_drops_every_component():
    rel = A.cross_check(A.produce(_cpi_rel(), _fetch(FRED_CPI), None, HEADLINE),
                        _text('cpi'), OK_ROW)
    assert rel['components'] == [] and rel['anatomy']['round'] == 'no_release_date'


@pytest.mark.parametrize('row', [
    None,
    {'ok': False},
    {'ok': True, 'verified': True, 'checks': {'value': None, 'primary_checked': False}},
])
def test_without_a_text_whose_headline_was_checked_nothing_is_usable(row):
    rel = A.cross_check(A.produce(_cpi_rel(), _fetch(FRED_CPI), RD, HEADLINE), _text('cpi'), row)
    assert rel['components'] == [] and rel['anatomy_status'] == 'none'
    assert rel['anatomy_reason'] == 'no_verified_text'


def test_one_usable_component_is_partial_and_a_release_without_a_registry_is_text():
    vals = {'CPIENGSL': FRED_CPI['CPIENGSL']}
    rel = A.cross_check(A.produce(_cpi_rel(), _fetch(vals), RD, HEADLINE), _text('cpi'), OK_ROW)
    assert rel['anatomy_status'] == 'partial'
    mich = {'key': 'michigan', 'primary': 'M', 'indicators': [{'name': 'M',
                                                               'ref_period': '2026-10-01'}]}
    rel = A.cross_check(A.produce(mich, _fetch({}), RD, None), 'text', dict(OK_ROW, key='michigan'))
    assert rel['anatomy_status'] == 'text' and rel['anatomy']['round'] == 'no_registry'


def test_a_private_text_never_makes_a_text_only_block():
    rel = {'key': 'philly-fed', 'primary': 'P',
           'indicators': [{'name': 'P', 'ref_period': '2026-03-01'}]}
    rel = A.cross_check(A.produce(rel, _fetch({}), RD, HEADLINE), PHILLY, OK_ROW)
    assert rel['components'] == [] and rel['anatomy_status'] == 'none'


def test_reset_and_gaps():
    rel = A.cross_check(A.produce(_cpi_rel(), _fetch(FRED_CPI), RD, HEADLINE), _text('cpi'), OK_ROW)
    A.reset(rel)
    assert rel['components'] == [] and rel['anatomy_status'] == 'none'
    assert A.gaps([rel, {'key': 'x', 'anatomy_status': 'complete'}]) == [
        {'key': 'cpi', 'status': 'none', 'reason': 'not_cross_checked', 'components': 0}]


# ------------------------------------------------------------ FRED client

def _vintage_payload(*rows, count=None):
    return json.dumps({'count': count if count is not None else len(rows),
                       'observations': list(rows)}).encode()


def test_vintage_asks_for_history_rows_over_a_window_ending_on_the_day():
    op = FakeOpener(_vintage_payload(
        {'date': '2026-09-01', 'realtime_start': '2026-10-15', 'realtime_end': '2026-10-15',
         'value': '102.0'},
        {'date': '2026-09-01', 'realtime_start': '2026-09-20', 'realtime_end': '2026-10-14',
         'value': '.'}))
    c = _client(op)
    c.transport = 'api'
    rows = c.vintage('CPIAUCSL', '2026-08-01', '2026-09-01', '2026-10-15')
    assert rows[0]['value'] == 102.0 and rows[1]['value'] is None
    url = op.urls[-1]
    for part in ('output_type=1', 'realtime_start=2026-09-05', 'realtime_end=2026-10-15',
                 'observation_start=2026-08-01', 'observation_end=2026-09-01'):
        assert part in url


def test_vintage_and_release_dates_refuse_the_csv_transport():
    c = fred.FredClient(key=None, opener=FakeOpener(), min_interval=0)
    c.transport = 'csv'
    with pytest.raises(fred.FredError):
        c.vintage('X', '2026-01-01', '2026-01-01', '2026-02-01')
    with pytest.raises(fred.FredError):
        c.last_release_date(10, '2026-02-01')


def test_vintage_rejects_a_truncated_response():
    c = _client(FakeOpener(_vintage_payload(count=fred.LIMIT + 1)))
    c.transport = 'api'
    with pytest.raises(fred.FredError):
        c.vintage('X', '2026-01-01', '2026-01-01', '2026-02-01')


def test_last_release_date_bounds_the_request_and_ignores_later_rows():
    body = json.dumps({'release_dates': [{'release_id': 10, 'date': '2026-11-20'},
                                         {'release_id': 10, 'date': '2026-10-14'},
                                         {'release_id': 10, 'date': '2026-09-11'}]}).encode()
    op = FakeOpener(body)
    c = _client(op)
    c.transport = 'api'
    assert c.last_release_date(10, '2026-10-15') == '2026-10-14'
    url = op.urls[-1]
    assert 'realtime_end=2026-10-15' in url and 'sort_order=desc' in url
    assert 'include_release_dates_with_no_data=false' in url


def test_last_release_date_is_none_when_there_is_nothing():
    c = _client(FakeOpener(json.dumps({'release_dates': []}).encode()))
    c.transport = 'api'
    assert c.last_release_date(10, '2026-10-15') is None


# ------------------------------------------------ codex 구현 검토 1회 (11/08)

def test_the_last_printed_digit_is_the_precision():
    """「$280 billion」 is to the billion: FRED's 284 billion does not agree."""
    _, prec = A._number(__import__('re').match(A.V, '280 billion'))
    assert prec == 1e9
    assert not A.agrees(284e9, 280e9, prec)


def test_the_printed_figure_is_the_agencys_not_a_rerounded_fred():
    comp = _comp('employment', '헬스케어')
    rel = {'key': 'employment', 'primary': 'P',
           'indicators': [{'name': 'P', 'ref_period': '2026-10-01'}]}
    rows = {'CES6562000101': 42.5}
    rel = A.produce(rel, lambda sid, a, b: [_row(b, RD, RD, 1000 + rows.get(sid, 0)),
                                            _row(a, '2026-09-01', RD, 1000.0)],
                    RD, [_row('2026-10-01', RD, RD, 1.0)])
    A.cross_check(rel, 'Health care added 43,000 jobs in October.', OK_ROW)
    hc = next(c for c in rel['components'] if c['label'] == comp['label'])
    assert hc['actual'] == 43000 and 43 in hc['cite_values']
