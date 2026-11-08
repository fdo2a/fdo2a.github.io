import datetime as dt

import pytest

from us import census_calendar as C
from us import upcoming as U
from us.fred import FredClient, FredError
from us.macro_metrics import RELEASES


# --- A. 경제지표 일정 ---------------------------------------------------------

def _row(day, rid, name):
    return (dt.date.fromisoformat(day), rid, name)


# 실행 때 시리즈로 푼 결과의 모양 — {slug: (release_id, release_name)}.
RES = {'cpi': (10, 'Consumer Price Index'), 'employment': (50, 'Employment Situation'),
       'gdp': (53, 'Gross Domestic Product'), 'existing-home-sales': (291, 'Existing Home Sales')}


def test_a_release_is_matched_by_its_resolved_id():
    rows = [_row('2026-09-16', 10, 'Consumer Price Index'),
            _row('2026-09-17', 50, 'Employment Situation')]
    events, unresolved = U.release_events(rows, RELEASES, RES)
    assert unresolved == {}
    assert {e['name_ko'] for e in events} == {'소비자물가(CPI)', '고용상황(Employment Situation)'}


@pytest.mark.parametrize('rid,real,lookalike,slug', [
    # 2026-10-13~17 Actions 로그에 찍힌 실제 이름 쌍 — 이름 매칭 시절 슬러그째 버려졌다.
    (10, 'Consumer Price Index', 'Research Consumer Price Index', 'cpi'),
    (180, 'Unemployment Insurance Weekly Claims Report',
     'State Unemployment Insurance Weekly Claims Report', 'claims'),
    # 2026-11-04~05.
    (10, 'Consumer Price Index', 'Consumer Price Index Excluding Energy Commodities', 'cpi'),
    # 2026-10-19~28, 15일 중 7일 GDP 가 일정표에서 빠졌다.
    (53, 'Gross Domestic Product', 'Debt to Gross Domestic Product Ratios', 'gdp'),
])
def test_a_lookalike_release_neither_knocks_out_nor_stands_in_for_the_real_one(
        rid, real, lookalike, slug):
    res = {slug: (rid, real)}
    events, unresolved = U.release_events(
        [_row('2026-10-14', rid, real), _row('2026-10-15', 999, lookalike)], RELEASES, res)
    assert unresolved == {}
    assert [(e['key'], e['date']) for e in events] == [(f'release-{slug}-20261014', '2026-10-14')]
    # 진짜가 창 밖이고 유사 이름만 남은 날 — 이름 매칭은 이것을 진짜로 인쇄했다(codex 11/07 #1).
    alone, _ = U.release_events([_row('2026-10-15', 999, lookalike)], RELEASES, res)
    assert alone == []


def test_an_unresolved_slug_is_never_printed_from_its_name():
    """id 를 못 얻은 지표는 비운다 — 이름으로 짐작해 인쇄하지 않는다."""
    rows = [_row('2026-10-28', 999, 'Debt to Gross Domestic Product Ratios'),
            _row('2026-10-29', 53, 'Gross Domestic Product')]
    events, unresolved = U.release_events(rows, RELEASES, {})
    assert events == [] and unresolved == {}


def test_two_slugs_resolved_to_one_id_are_both_held_back():
    res = {'cpi': (10, 'Consumer Price Index'), 'ppi': (10, 'Consumer Price Index')}
    events, unresolved = U.release_events(
        [_row('2026-09-16', 10, 'Consumer Price Index')], RELEASES, res)
    assert events == []
    assert set(unresolved) == {'cpi', 'ppi'}


def test_a_row_naming_another_release_holds_the_slug_back():
    """벌크 행과 시리즈 조회가 같은 id 에 다른 이름을 대면 어느 쪽도 믿지 않는다."""
    events, unresolved = U.release_events(
        [_row('2026-09-16', 10, 'Producer Price Index')], RELEASES,
        {'cpi': (10, 'Consumer Price Index')})
    assert events == [] and 'cpi' in unresolved


def test_the_name_check_ignores_case_and_spacing():
    events, unresolved = U.release_events(
        [_row('2026-09-16', 10, ' consumer  price INDEX ')], RELEASES,
        {'cpi': (10, 'Consumer Price Index')})
    assert unresolved == {} and len(events) == 1


def test_a_row_without_an_id_is_not_ours():
    events, unresolved = U.release_events(
        [_row('2026-09-16', None, 'Consumer Price Index')], RELEASES, RES)
    assert events == [] and unresolved == {}


def test_an_unknown_release_is_simply_not_ours():
    assert U.release_events([_row('2026-09-16', 123, 'Beige Book')], RELEASES, RES) == ([], {})


def test_a_release_carries_both_clocks_when_the_time_is_known():
    events, _ = U.release_events([_row('2026-09-16', 10, 'Consumer Price Index')],
                                 RELEASES, RES)
    assert events[0]['time_et'] == '08:30'
    assert events[0]['time_kst'] == '2026-09-16 21:30'      # EDT
    winter, _ = U.release_events([_row('2026-01-13', 10, 'Consumer Price Index')],
                                 RELEASES, RES)
    assert winter[0]['time_kst'] == '2026-01-13 22:30'      # EST


def test_a_release_with_no_known_time_prints_the_date_alone():
    """모르는 시각을 지어내지 않는다."""
    assert 'existing-home-sales' in U.RELEASE_SERIES
    saved = U.RELEASE_TIME_ET.pop('existing-home-sales')
    try:
        events, _ = U.release_events(
            [_row('2026-09-22', 291, 'Existing Home Sales')], RELEASES, RES)
        assert events[0]['time_et'] is None
        assert events[0]['time_kst'] is None
    finally:
        U.RELEASE_TIME_ET['existing-home-sales'] = saved


# --- A-1. 시리즈 → release_id 풀기 --------------------------------------------

def _names():
    """각 슬러그 시리즈가 제 이름의 릴리스로 풀리는 표(가짜)."""
    return {sid: (100 + i, U.RELEASE_NAMES[slug][0])
            for i, (slug, sid) in enumerate(U.ALL_SERIES.items())}


def _lookup(table, calls=None):
    def f(sid):
        if calls is not None:
            calls.append(sid)
        v = table[sid]
        if isinstance(v, Exception):
            raise v
        return v
    return f


def test_the_fred_names_match_what_the_series_pages_said_on_2026_11_08():
    """FRED 시리즈 페이지의 「Release:」 이름(2026-11-08). 바꾸려면 다시 확인하고 날짜를 바꾼다."""
    seen = {'CPIAUCSL': 'Consumer Price Index', 'PAYEMS': 'Employment Situation',
            'PCEPI': 'Personal Income and Outlays',
            'RSAFS': 'Advance Monthly Sales for Retail and Food Services',
            'A191RL1Q225SBEA': 'Gross Domestic Product', 'PPIFIS': 'Producer Price Index',
            'ICSA': 'Unemployment Insurance Weekly Claims Report',
            'JTSJOL': 'Job Openings and Labor Turnover Survey',
            'INDPRO': 'G.17 Industrial Production and Capacity Utilization',
            'HSN1F': 'New Residential Sales', 'EXHOSLUSM495S': 'Existing Home Sales',
            'UMCSENT': 'Surveys of Consumers'}
    for slug, sid in U.RELEASE_SERIES.items():
        assert U.name_fits(slug, seen[sid]), (slug, sid)


def test_every_slug_has_a_series_the_dashboard_already_fetches():
    import collect_market_data as cmd
    from us.macro_metrics import INDICATOR_RELEASE
    owned = {}
    for _axis, label, sid, _tf, _u, *_ in cmd.ECON:
        owned.setdefault(sid, set()).add(INDICATOR_RELEASE[label])
    assert set(U.ALL_SERIES) == set(U.RELEASE_NAMES)
    # Census 경로로 간 지표만 FRED 일정 경로에서 빠진다(2026-11-08).
    assert set(RELEASES) - set(U.RELEASE_SERIES) - U.NOT_CALENDARED == set(C.CENSUS_NAMES)
    for slug, sid in U.RELEASE_SERIES.items():
        assert owned.get(sid) == {slug}, (slug, sid)


def test_resolve_keeps_a_release_whose_name_matches_the_slug():
    resolved, unresolved = U.resolve_releases(_lookup(_names()))
    assert unresolved == {}
    assert set(resolved) == set(U.ALL_SERIES)


@pytest.mark.parametrize('slug,name', [
    # 시리즈 id 오타·이동 — 다른 지표의 릴리스로 풀린다.
    ('cpi', 'Producer Price Index'),
    # 다른 지표의 실제 릴리스 이름(2026-11-08 FRED 페이지) — 시리즈 id 가 엇갈린 경우.
    ('ppi', 'Consumer Price Index'),
    # 유사 릴리스는 진짜 이름을 품고 있어도 받지 않는다(정확 일치).
    ('gdp', 'Debt to Gross Domestic Product Ratios'),
    ('gdp', 'Gross Domestic Product by Industry'),
    ('cpi', 'Research Consumer Price Index'),
])
def test_resolve_refuses_a_release_that_is_not_the_slug(slug, name):
    table = _names()
    table[U.RELEASE_SERIES[slug]] = (777, name)
    resolved, unresolved = U.resolve_releases(_lookup(table))
    assert slug not in resolved and slug in unresolved


def test_resolve_stops_at_a_rejected_key():
    table = {sid: FredError('HTTP 400: api_key', status=400, auth=True)
             for sid in U.ALL_SERIES.values()}
    calls = []
    resolved, unresolved = U.resolve_releases(_lookup(table, calls))
    assert resolved == {} and set(unresolved) == set(U.ALL_SERIES)
    assert len(calls) == 1


def test_resolve_stops_after_two_failures_and_keeps_what_it_had():
    """13번 연속 타임아웃이면 25초 × 13 — 두 번째 실패에서 멈춘다."""
    table = _names()
    sids = list(U.ALL_SERIES.values())
    table[sids[1]] = FredError('timeout', transient=True)
    table[sids[2]] = FredError('timeout', transient=True)
    calls = []
    resolved, unresolved = U.resolve_releases(_lookup(table, calls))
    first = next(iter(U.ALL_SERIES))
    assert list(resolved) == [first]
    assert set(unresolved) == set(U.ALL_SERIES) - {first}
    assert len(calls) == 3


def test_series_release_parses_one_release(monkeypatch):
    client = FredClient(key='k', transport='api')
    seen = {}

    def get(url):
        seen['url'] = url
        return b'{"releases": [{"id": 10, "name": "Consumer Price Index", "press_release": true}]}'

    monkeypatch.setattr(client, '_get', get)
    assert client.series_release('CPIAUCSL') == (10, 'Consumer Price Index')
    assert seen['url'].startswith('https://api.stlouisfed.org/fred/series/release?')
    assert 'series_id=CPIAUCSL' in seen['url'] and 'file_type=json' in seen['url']


@pytest.mark.parametrize('body', [
    b'{"releases": []}',
    b'{"releases": [{"id": 10, "name": "A"}, {"id": 11, "name": "B"}]}',
    b'{"releases": [{"id": "10", "name": "A"}]}',
    b'{"releases": [{"id": true, "name": "A"}]}',
    b'{"releases": [{"id": 10, "name": ""}]}',
    b'{}',
])
def test_series_release_refuses_anything_but_one_clean_release(monkeypatch, body):
    client = FredClient(key='k', transport='api')
    monkeypatch.setattr(client, '_get', lambda url: body)
    with pytest.raises(FredError):
        client.series_release('CPIAUCSL')


@pytest.mark.parametrize('body', [
    b'{"releases": [{"id": "SECRETKEY123", "name": "A"}]}',
    b'{"releases": [{"id": 10, "name": ""}], "x": "SECRETKEY123"}',
    b'<html>oops api_key=SECRETKEY123</html>',
])
def test_a_key_echoed_in_the_response_never_reaches_the_error(monkeypatch, body):
    client = FredClient(key='SECRETKEY123', transport='api')
    monkeypatch.setattr(client, '_get', lambda url: body)
    with pytest.raises(FredError) as e:
        client.series_release('CPIAUCSL')
    assert 'SECRETKEY123' not in str(e.value)
    assert e.value.__context__ is None       # 원문이 예외 사슬에 매달리지 않는다


def test_series_release_needs_the_official_api():
    with pytest.raises(FredError):
        FredClient(key=None).series_release('CPIAUCSL')


def test_the_keyless_transport_cannot_serve_the_calendar():
    """graph CSV 에는 릴리스 일정표가 없다 — 조용히 빈 목록을 주면 안 된다."""
    client = FredClient(key=None)
    assert client.transport == 'csv'
    with pytest.raises(FredError):
        client.release_dates(dt.date(2026, 9, 15), dt.date(2026, 9, 25))


def test_release_dates_parses_and_sorts(monkeypatch):
    payload = (b'{"count": 2, "release_dates": ['
               b'{"date": "2026-09-18", "release_id": 50, "release_name": "B"},'
               b'{"date": "2026-09-16", "release_id": 10, "release_name": "A"},'
               b'{"date": "bogus", "release_id": 1, "release_name": "C"}]}')
    client = FredClient(key='k', transport='api')
    monkeypatch.setattr(client, '_get', lambda url: payload)
    got = client.release_dates(dt.date(2026, 9, 15), dt.date(2026, 9, 25))
    assert [r[0].isoformat() for r in got] == ['2026-09-16', '2026-09-18']


def test_release_dates_refuses_a_truncated_response(monkeypatch):
    client = FredClient(key='k', transport='api')
    monkeypatch.setattr(client, '_get',
                        lambda url: b'{"count": 99999, "release_dates": []}')
    with pytest.raises(FredError):
        client.release_dates(dt.date(2026, 9, 15), dt.date(2026, 9, 25))


def test_the_key_never_reaches_the_calendar_url_in_an_error(monkeypatch):
    client = FredClient(key='SECRET', transport='api')

    def boom(url):
        raise FredError('HTTP 400: bad')

    monkeypatch.setattr(client, '_get', boom)
    with pytest.raises(FredError) as e:
        client.release_dates(dt.date(2026, 9, 15), dt.date(2026, 9, 25))
    assert 'SECRET' not in str(e.value)


# --- B. 국채 입찰 -------------------------------------------------------------

def _auction(day, **kw):
    row = {'auction_date': day, 'security_type': 'Note', 'security_term': '9-Year 10-Month',
           'original_security_term': '10-Year', 'offering_amt': '19000000000',
           'closing_time_comp': '01:00 PM', 'bid_to_cover_ratio': 'null',
           'high_yield': 'null', 'total_accepted': 'null',
           'indirect_bidder_accepted': 'null', 'primary_dealer_accepted': 'null'}
    row.update(kw)
    return row


def test_a_bill_keeps_its_own_term_and_a_coupon_takes_the_original():
    """`original_security_term` 한 줄로 쓰면 6주 재정증권이 「52-Week」가 된다."""
    bill = _auction('2026-09-15', security_type='Bill', security_term='6-Week',
                    original_security_term='52-Week')
    assert U.term_label(bill) == '6-Week'
    assert U.term_label(_auction('2026-09-17')) == '10-Year'


def test_the_closing_time_comes_from_the_row_not_from_a_table():
    assert U.closing_time_et(_auction('2026-09-17')) == '13:00'
    assert U.closing_time_et(_auction('2026-09-15',
                                      closing_time_comp='11:30 AM')) == '11:30'
    assert U.closing_time_et(_auction('2026-09-15', closing_time_comp='')) is None
    assert U.closing_time_et(_auction('2026-09-15', closing_time_comp='정오')) is None


def test_an_auction_event_carries_the_size_in_eok_not_rounded_billions():
    """75억 달러를 십억으로 세고 0 을 붙이면 「80억」이 된다."""
    rows = [_auction('2026-09-15', offering_amt='7500000000')]
    ev = U.auction_events(rows, dt.date(2026, 9, 15), dt.date(2026, 9, 25))[0]
    assert '75억 달러' in ev['name_ko']
    assert ev['time_kst'] == '2026-09-16 02:00'


def test_auction_events_are_clipped_to_the_window():
    rows = [_auction('2026-09-14'), _auction('2026-09-17'), _auction('2026-09-30')]
    got = U.auction_events(rows, dt.date(2026, 9, 15), dt.date(2026, 9, 25))
    assert [e['date'] for e in got] == ['2026-09-17']


def test_results_not_posted_yet_are_not_reported_as_no_demand():
    """당일 입찰은 결과가 늦게 붙는다 — 「응찰 없음」과 다른 말이다."""
    rows = [_auction('2026-09-14')]        # bid_to_cover_ratio: 'null'
    assert U.auction_results(rows, dt.date(2026, 9, 14)) == []


def test_the_demand_ratios_come_from_fields_the_api_gives():
    row = _auction('2026-09-10', security_type='Bond', original_security_term='30-Year',
                   bid_to_cover_ratio='2.610000', high_yield='5.3080',
                   total_accepted='22000024000', indirect_bidder_accepted='17452770500',
                   primary_dealer_accepted='484800000', offering_amt='22000000000')
    got = U.auction_results([row], dt.date(2026, 9, 14))[0]
    assert got['term'] == '30-Year'
    assert got['bid_to_cover'] == 2.61
    assert got['indirect_pct'] == 79.3
    assert got['dealer_pct'] == 2.2
    assert got['high_yield'] == 5.308


def test_results_are_newest_first_and_bounded_by_the_lookback():
    rows = [_auction('2026-09-10', bid_to_cover_ratio='2.6', total_accepted='100'),
            _auction('2026-09-12', bid_to_cover_ratio='2.8', total_accepted='100'),
            _auction('2026-08-20', bid_to_cover_ratio='2.4', total_accepted='100')]
    got = U.auction_results(rows, dt.date(2026, 9, 14))
    assert [r['date'] for r in got] == ['2026-09-12', '2026-09-10']


def test_a_null_string_is_not_a_number():
    """FiscalData 는 없는 값을 문자열 'null' 로 준다 — float('null') 은 터진다."""
    assert U._num('null') is None and U._num('') is None and U._num(None) is None
    assert U._num('2.610000') == 2.61


def test_the_query_keeps_its_brackets():
    """`page[size]` 를 인코딩해 버리면 FiscalData 가 못 읽는다."""
    url = U.auctions_url(dt.date(2026, 9, 15), dt.date(2026, 9, 25))
    assert 'page[size]=' in url
    assert 'auction_date:gte:2026-09-15' in url


# --- C. 수집 묶음(build_calendar._collect) -------------------------------------

@pytest.fixture(autouse=True)
def _no_census_network(monkeypatch):
    """수집 묶음 테스트가 census.gov 에 나가지 않게 — 기본은 받기 실패."""
    import build_calendar as BC
    from us.census_calendar import CensusError

    def offline(url):
        raise CensusError('offline test')

    monkeypatch.setattr(BC, '_census_get', offline)


def _fake_client(rows, table):
    class Fake:
        transport = 'api'
        key = None

        def __init__(self, *a, **k):
            pass

        def preflight(self):
            pass

        def series_release(self, sid):
            return _lookup(table)(sid)

        def release_dates(self, start, end):
            return rows
    return Fake


def test_collect_prints_what_resolved_and_names_what_did_not(monkeypatch):
    import build_calendar as BC
    table = _names()
    table[U.RELEASE_SERIES['gdp']] = FredError('timeout', transient=True)
    cpi_id = table[U.RELEASE_SERIES['cpi']][0]
    rows = [_row('2026-11-10', cpi_id, table[U.RELEASE_SERIES['cpi']][1]),
            _row('2026-11-12', 999, 'Debt to Gross Domestic Product Ratios')]
    monkeypatch.setattr(BC, 'FredClient', _fake_client(rows, table))
    monkeypatch.setattr(BC, '_auction_rows', lambda *a: [])
    rd = dt.date(2026, 11, 7)
    events, _auctions, missing, info = BC._collect(rd, rd + dt.timedelta(days=1),
                                                   rd + dt.timedelta(days=10))
    assert [e['key'] for e in events if e['kind'] == 'release'] == ['release-cpi-20261110']
    assert 'releases' not in missing
    assert 'gdp' in info['unresolved']
    assert info['release_ids']['cpi'] == cpi_id and 'gdp' not in info['release_ids']


def test_collect_with_nothing_resolved_is_a_missing_calendar(monkeypatch):
    import build_calendar as BC
    table = {sid: FredError('HTTP 400: api_key', status=400, auth=True)
             for sid in U.ALL_SERIES.values()}
    monkeypatch.setattr(BC, 'FredClient', _fake_client(
        [_row('2026-11-10', 10, 'Consumer Price Index')], table))
    monkeypatch.setattr(BC, '_auction_rows', lambda *a: [])
    rd = dt.date(2026, 11, 7)
    events, _a, missing, info = BC._collect(rd, rd, rd + dt.timedelta(days=10))
    assert 'releases' in missing
    assert set(U.ALL_SERIES) <= set(info['unresolved'])


def test_collect_scrubs_the_reason_it_prints(monkeypatch, capsys):
    import build_calendar as BC
    table = _names()
    cpi_sid = U.RELEASE_SERIES['cpi']
    table[cpi_sid] = (10, 'Consumer Price Index')
    rows = [_row('2026-11-10', 10, 'Consumer Price Index SECRETKEY123')]
    fake = _fake_client(rows, table)
    fake.key = 'SECRETKEY123'
    monkeypatch.setattr(BC, 'FredClient', fake)
    monkeypatch.setattr(BC, '_auction_rows', lambda *a: [])
    rd = dt.date(2026, 11, 7)
    _e, _a, _m, info = BC._collect(rd, rd, rd + dt.timedelta(days=10))
    assert 'cpi' in info['unresolved']
    assert 'SECRETKEY123' not in capsys.readouterr().err


def test_a_newline_in_a_release_name_cannot_start_a_workflow_command(monkeypatch, capsys):
    import build_calendar as BC
    table = _names()
    table[U.RELEASE_SERIES['gdp']] = (53, 'GDP\n::warning::injected')
    monkeypatch.setattr(BC, 'FredClient', _fake_client([], table))
    monkeypatch.setattr(BC, '_auction_rows', lambda *a: [])
    rd = dt.date(2026, 11, 7)
    BC._collect(rd, rd, rd + dt.timedelta(days=10))
    err = capsys.readouterr().err
    assert not any(line.startswith('::') for line in err.splitlines())


def test_the_reason_survives_when_the_dates_call_dies(monkeypatch, capsys):
    import build_calendar as BC
    table = _names()
    table[U.RELEASE_SERIES['jolts']] = (192, 'Unexpected Release Name')
    fake = _fake_client([], table)

    def boom(self, start, end):
        raise FredError('dates timeout', transient=True)

    fake.release_dates = boom
    monkeypatch.setattr(BC, 'FredClient', fake)
    monkeypatch.setattr(BC, '_auction_rows', lambda *a: [])
    rd = dt.date(2026, 11, 7)
    _e, _a, missing, _i = BC._collect(rd, rd, rd + dt.timedelta(days=10))
    assert 'releases' in missing
    assert 'Unexpected Release Name' in capsys.readouterr().err
