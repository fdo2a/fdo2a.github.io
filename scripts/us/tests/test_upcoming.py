import datetime as dt

import pytest

from us import upcoming as U
from us.fred import FredClient, FredError
from us.macro_metrics import RELEASES


# --- A. 경제지표 일정 ---------------------------------------------------------

def _row(day, rid, name):
    return (dt.date.fromisoformat(day), rid, name)


def test_a_release_is_matched_by_name_not_by_a_hardcoded_id():
    """id 를 박으면 틀렸을 때 다른 지표의 일정을 그 이름으로 인쇄한다."""
    rows = [_row('2026-09-16', 10, 'Consumer Price Index'),
            _row('2026-09-17', 50, 'Employment Situation')]
    events, dropped = U.release_events(rows, RELEASES)
    assert dropped == []
    assert {e['name_ko'] for e in events} == {'소비자물가(CPI)', '고용상황(Employment Situation)'}


def test_a_slug_matching_two_releases_is_dropped_rather_than_mislabelled():
    """어느 쪽이 그 지표인지 모르면 빈 칸이 낫다."""
    rows = [_row('2026-09-16', 10, 'Consumer Price Index'),
            _row('2026-09-18', 999, 'Consumer Price Index for Elderly')]
    events, dropped = U.release_events(rows, RELEASES)
    assert events == []
    assert dropped and dropped[0][0] == 'cpi'


def test_an_unknown_release_is_simply_not_ours():
    rows = [_row('2026-09-16', 123, 'Beige Book')]
    assert U.release_events(rows, RELEASES) == ([], [])


def test_a_release_carries_both_clocks_when_the_time_is_known():
    events, _ = U.release_events([_row('2026-09-16', 10, 'Consumer Price Index')],
                                 RELEASES)
    assert events[0]['time_et'] == '08:30'
    assert events[0]['time_kst'] == '2026-09-16 21:30'      # EDT
    winter, _ = U.release_events([_row('2026-01-13', 10, 'Consumer Price Index')],
                                 RELEASES)
    assert winter[0]['time_kst'] == '2026-01-13 22:30'      # EST


def test_a_release_with_no_known_time_prints_the_date_alone():
    """모르는 시각을 지어내지 않는다."""
    assert 'existing-home-sales' in dict(U.RELEASE_PATTERNS)
    saved = U.RELEASE_TIME_ET.pop('existing-home-sales')
    try:
        events, _ = U.release_events(
            [_row('2026-09-22', 77, 'Existing Home Sales')], RELEASES)
        assert events[0]['time_et'] is None
        assert events[0]['time_kst'] is None
    finally:
        U.RELEASE_TIME_ET['existing-home-sales'] = saved


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
