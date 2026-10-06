import json

from fund import kr_view, core

SESSION = {
    'report_date': '2026-10-02',
    'us_futures_during_kr': {'ES': {'pct': 0.16, 'bars': 14, 'first_t': '09:00', 'last_t': '15:30'},
                             'NQ': {'pct': 0.11, 'bars': 14, 'first_t': '09:00', 'last_t': '15:30'}},
    'asia_peers': {'rows': {'대만가권': 0.25, '닛케이': -0.94},
                   'dates': {'대만가권': '2026-10-02', '닛케이': '2026-10-02'}},
    'usdkrw_intraday': {'high': 1366.08, 'high_t': '09:30', 'low': 1349.28, 'low_t': '15:30',
                        'close': 1350.78, 'last_t': '15:30', 'bars': 14},
}
ECON = {'series': {
    '국고채 3년': {'value': 3.937, 'date': '2026-10-02', 'bp': -7.3},
    'CD 91일': {'value': 3.21, 'date': '2026-10-02', 'bp': 0.0},
    '한국은행 기준금리': {'value': 2.5, 'date': '2026-09', 'bp': None},
}}
INDUSTRY = [
    {'name': '반도체와반도체장비', 'change_pct': 0.3, 'breadth': 0.5, 'leading': False},
    {'name': '우주항공과국방', 'change_pct': 3.1, 'breadth': 0.9, 'leading': True},
]
MOVES = [{'name': 'SK하이닉스', 'change_pct': 0.44}, {'name': '삼성전자', 'change_pct': 0.0}]


def build(**over):
    kw = dict(report_date='2026-10-02', session=SESSION, econ=ECON, industry=INDUSTRY,
              moves=MOVES, generated_at='2026-10-02 16:40 KST')
    kw.update(over)
    return kr_view.build(**kw)


def test_contract_and_ok():
    d = build()
    for k in ('schema_version', 'calculation_version', 'report_date', 'generated_at', 'status',
              'missing', 'source_dates', 'fx', 'cash_rates', 'us_futures', 'observations'):
        assert k in d
    assert d['status'] == 'ok'
    json.dumps(d, allow_nan=False)


def test_fx_is_last_observation_in_kr_hours_without_a_daily_change():
    fx = build()['fx']
    assert fx['last'] == 1350.78 and fx['last_t'] == '15:30'
    assert fx['high'] == 1366.08 and fx['low'] == 1349.28
    assert 'chg' not in fx and 'pct' not in fx
    assert '한국장 시간대 마지막 관측' in fx['source']


def test_cash_rates_are_reference_rates_with_their_own_dates():
    rates = {r['name']: r for r in build()['cash_rates']}
    assert rates['CD 91일']['date'] == '2026-10-02'
    assert rates['한국은행 기준금리']['date'] == '2026-09'
    assert '국고채 10년' not in rates


def test_observations_only_what_exists_one_row_each():
    obs = build()['observations']
    names = [(o['unit_id'], o['kind'], o['name']) for o in obs]
    assert ('semis', 'industry', '반도체와반도체장비') in names
    assert ('semis', 'stock', 'SK하이닉스') in names
    assert ('semis', 'index', '대만가권') in names
    assert ('defense', 'industry', '우주항공과국방') in names
    # nothing synthetic: no row for a unit with no observation
    assert not any(o['unit_id'] == 'grid' for o in obs)
    taiex = next(o for o in obs if o['name'] == '대만가권')
    assert taiex['date'] == '2026-10-02'
    ind = next(o for o in obs if o['name'] == '우주항공과국방')
    assert ind['breadth'] == 0.9 and ind['leading'] is True


def test_partial_and_unavailable():
    d = build(session=None)
    assert d['status'] == 'partial'
    assert d['fx'] is None and d['us_futures'] is None
    d2 = build(session=None, econ=None, industry=[], moves=[])
    assert d2['status'] == 'unavailable'


def test_session_date_mismatch_is_dropped():
    s = dict(SESSION, report_date='2026-10-01')
    d = build(session=s)
    assert d['fx'] is None
    assert any('session' in m for m in d['missing'])


def test_render_deterministic_with_hash():
    d = build()
    a = kr_view.html(d)
    assert a == kr_view.html(json.loads(json.dumps(d)))
    assert f'data-fund-kr="{core.digest(d)}"' in a
    assert '미국 개장 전 관련 업종 관측' in a
    assert '상위 60개' in a
    assert kr_view.html(build(session=None, econ=None, industry=[], moves=[])) is None


def test_kr_block_has_no_paragraphs():
    assert '<p' not in kr_view.html(build())


def test_zero_bp_reads_as_no_change():
    a = kr_view.html(build())
    assert 'CD 91일 3.210%(10/2) · 변화 없음' in a
    assert '+0.0bp' not in a


def test_nan_fx_drops_only_the_fx_part():
    s = json.loads(json.dumps(SESSION))
    s['usdkrw_intraday']['close'] = float('nan')
    d = build(session=s)
    assert d['fx'] is None and any('fx' in m for m in d['missing'])
    assert d['status'] == 'partial' and d['observations']
    assert kr_view.html(d) is not None


def test_nan_rate_and_observation_are_skipped():
    e = json.loads(json.dumps(ECON))
    e['series']['CD 91일']['value'] = float('nan')
    ind = [dict(INDUSTRY[0], change_pct=float('nan')), INDUSTRY[1]]
    d = build(econ=e, industry=ind)
    assert 'CD 91일' not in [r['name'] for r in d['cash_rates']]
    assert '반도체와반도체장비' not in [o['name'] for o in d['observations']]
    json.dumps(d, allow_nan=False)


def test_missing_fx_high_low_still_renders():
    s = json.loads(json.dumps(SESSION))
    s['usdkrw_intraday']['high'] = None
    a = kr_view.html(build(session=s))
    assert '원/달러 1,350.78원' in a
