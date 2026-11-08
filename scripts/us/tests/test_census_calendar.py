"""인구조사국(Census) 경제지표 일정표 — 파싱, 연도 판 고르기, FRED 와의 교차 확인.

픽스처는 2026-11-08 census.gov 목록 페이지에서 표만 잘라 둔 것이다(tests/fixtures/census).
"""
import datetime as dt
import re as _re
from pathlib import Path

import pytest

from us import census_calendar as C
from us import upcoming as U
from us.macro_metrics import RELEASES

FIX = Path(__file__).parent / 'fixtures' / 'census'
P2026 = (FIX / 'listview-2026.html').read_text(encoding='utf-8')
PLATEST = (FIX / 'listview-latest-2027.html').read_text(encoding='utf-8')
PNOTABLE = (FIX / 'listview-2027-notable.html').read_text(encoding='utf-8')
D = dt.date.fromisoformat


def _get(pages):
    """url -> 본문. 없는 url 은 받기 실패."""
    def get(url):
        if url not in pages:
            raise C.CensusError(f'HTTP 404 {url}')
        v = pages[url]
        if isinstance(v, Exception):
            raise v
        return v
    return get


def _slot(v):
    return v['dates'], v['why']


GOOD = {C.YEAR_URL.format(year=2026): P2026,
        C.YEAR_URL.format(year=2027): PNOTABLE,
        C.LIST_URL: PLATEST}


# --- 파싱 ---------------------------------------------------------------------

def test_the_visible_date_wins_over_the_hidden_code():
    """4월 내구재 행: 보이는 날짜 「April 7, 2026」, 숨은 코드 A202604270830. FRED 는 4/7."""
    rows = C.page_rows(P2026, 2026)
    durable = rows['durable-goods']
    assert (D('2026-04-07'), '08:30') in durable['rows']
    assert all(d != D('2026-04-27') for d, _t in durable['rows'])
    assert len(durable['rows']) == 13 and durable['bad'] == []


def test_a_name_broken_across_lines_still_matches_exactly():
    rows = C.page_rows(P2026, 2026)
    assert (D('2026-11-03'), '10:00') in rows['factory-orders']['rows']


@pytest.mark.parametrize('text,want', [('8:30 AM', '08:30'), ('10:00 AM', '10:00'),
                                       ('12:00 PM', '12:00'), ('1:15 PM', '13:15'),
                                       ('12:30 AM', '00:30'), ('8.30 AM', None), ('', None)])
def test_times_become_eastern_wall_clock(text, want):
    assert C.to_time(text) == want


@pytest.mark.parametrize('text,want', [('November 25, 2026', D('2026-11-25')),
                                       ('April 7, 2026', D('2026-04-07')),
                                       ('Nov. 25, 2026', None), ('TBD', None)])
def test_dates_are_read_from_the_visible_text(text, want):
    assert C.to_date(text) == want


def test_a_page_without_the_schedule_table_is_a_failure():
    with pytest.raises(C.CensusError):
        C.page_rows(PNOTABLE, 2027)


def test_a_header_that_moved_is_a_failure():
    with pytest.raises(C.CensusError):
        C.page_rows(P2026.replace('Release Date', 'Date'), 2026)


def test_a_target_row_with_an_unreadable_date_is_reported_not_skipped():
    broken = P2026.replace('>November 25, 2026<', '>Nov. 25, 2026<')
    rows = C.page_rows(broken, 2026)
    assert rows['durable-goods']['bad']           # 속보·신규주택 둘 다 11/25 — 둘 다 걸린다
    assert rows['new-home-sales']['bad']
    assert rows['retail-sales']['bad'] == []


def test_rows_of_another_year_are_dropped():
    rows = C.page_rows(P2026, 2027)
    assert all(not v['rows'] for v in rows.values())


# --- 창 모으기 ----------------------------------------------------------------

def test_collect_returns_census_dates_and_times_in_the_window():
    got = C.collect(_get(GOOD), D('2026-11-09'), D('2026-11-18'))
    assert _slot(got['retail-sales']) == ({D('2026-11-17'): '08:30'}, None)
    assert _slot(got['housing-starts']) == ({D('2026-11-18'): '08:30'}, None)
    assert _slot(got['durable-goods']) == ({}, None)


def test_a_window_across_new_year_reads_both_pages():
    got = C.collect(_get(GOOD), D('2026-12-22'), D('2027-01-05'))
    assert got['durable-goods']['dates'] == {D('2026-12-23'): '08:30'}
    assert got['construction-spending']['why'] is None
    # 2027 판은 연도 접미사 주소에 표가 없어 무판(최신 연도) 주소에서 왔다.
    assert any(d.year == 2027 for v in got.values() for d in v['dates'])


def test_a_year_that_could_not_be_read_leaves_every_slug_unconfirmed():
    pages = {C.YEAR_URL.format(year=2026): P2026}
    got = C.collect(_get(pages), D('2026-12-22'), D('2027-01-05'))
    assert all(v['why'] and v['dates'] == {} for v in got.values())


def test_the_latest_page_is_not_taken_for_a_year_it_is_not():
    """2026 판이 없을 때 무판 주소(지금 2027)를 2026 으로 쓰면 안 된다."""
    pages = {C.YEAR_URL.format(year=2026): PNOTABLE, C.LIST_URL: PLATEST}
    got = C.collect(_get(pages), D('2026-11-09'), D('2026-11-18'))
    assert all(v['why'] for v in got.values())


def test_an_unreadable_target_row_unconfirms_only_that_slug():
    broken = P2026.replace('>November 17, 2026<', '>Nov. 17, 2026<')
    got = C.collect(_get({**GOOD, C.YEAR_URL.format(year=2026): broken}),
                    D('2026-11-09'), D('2026-11-18'))
    assert got['retail-sales']['why'] and got['retail-sales']['dates'] == {}
    assert got['housing-starts']['why'] is None


def test_a_same_day_with_two_times_is_unconfirmed():
    row = ('<tr><td><a>New Residential Construction (Building Permits, Housing Starts, and '
           'Housing Completions)</a></td><td>November 18, 2026</td><td>10:00 AM</td>'
           '<td>October 2026</td></tr></table>')
    twice = P2026.replace('</table>', row, 1)
    got = C.collect(_get({**GOOD, C.YEAR_URL.format(year=2026): twice}),
                    D('2026-11-09'), D('2026-11-18'))
    assert got['housing-starts']['why'] and got['housing-starts']['dates'] == {}


def test_an_exact_duplicate_row_is_one_date():
    """2026 표에는 같은 지표·날짜·시각 행이 겹쳐 있다(신규주택 15행 vs FRED 12일)."""
    rows = C.page_rows(P2026, 2026)
    assert len(rows['new-home-sales']['rows']) > len(set(rows['new-home-sales']['rows']))
    got = C.collect(_get(GOOD), D('2026-11-20'), D('2026-11-30'))
    assert got['new-home-sales']['dates'] == {D('2026-11-25'): '10:00'}


def test_a_thin_year_does_not_prove_the_schedule_is_there():
    """한 해 판에 그 지표 행이 몇 개뿐이면 창을 덮는다고 볼 수 없다."""
    keep = P2026
    # 소매판매 행을 두 개만 남긴다.
    import re
    rows = re.findall(r'<tr[^>]*>\s*<td[^>]*><a[^>]*>Advance Monthly Sales for Retail and Food '
                      r'Services</a></td>.*?</tr>', keep, re.S)
    for r in rows[2:]:
        keep = keep.replace(r, '')
    got = C.collect(_get({**GOOD, C.YEAR_URL.format(year=2026): keep}),
                    D('2026-11-09'), D('2026-11-18'))
    assert got['retail-sales']['why']


# --- FRED 교차 확인 → 일정 ----------------------------------------------------

def _resolved():
    return {'retail-sales': (9, 'Advance Monthly Sales for Retail and Food Services'),
            'new-home-sales': (97, 'New Residential Sales'),
            'durable-goods': (95, "Manufacturer's Shipments, Inventories, and Orders (M3) Survey"),
            'factory-orders': (95, "Manufacturer's Shipments, Inventories, and Orders (M3) Survey"),
            'housing-starts': (27, 'New Residential Construction'),
            'trade-balance': (51, 'U.S. International Trade in Goods and Services'),
            'construction-spending': (229, 'Construction Spending')}


def _fred(*pairs):
    names = {rid: n for rid, n in _resolved().values()}
    return [(D(d), rid, names[rid]) for d, rid in pairs]


def _census(**dates):
    out = {slug: {'dates': {}, 'why': None} for slug in C.CENSUS_NAMES}
    for slug, v in dates.items():
        out[slug] = v if 'why' in v else {'dates': v, 'why': None}
    return out


def test_a_census_date_that_fred_also_has_is_printed_with_the_census_time():
    census = _census(**{'durable-goods': {D('2026-11-25'): '08:30'},
                        'factory-orders': {D('2026-12-03'): '10:00'}})
    rows = _fred(('2026-11-25', 95), ('2026-12-03', 95))
    events, unresolved, *_n = U.census_events(census, rows, _resolved(), RELEASES)
    assert unresolved == {}
    got = {(e['key'], e['time_et']) for e in events}
    assert got == {('release-durable-goods-20261125', '08:30'),
                   ('release-factory-orders-20261203', '10:00')}


def test_fred_extra_days_are_never_printed_from_fred_alone():
    """rid 27 의 신규주택 판매일은 알려진 동시 갱신 — 주택착공은 제 날만 싣는다."""
    rows = _fred(('2026-11-25', 27), ('2026-11-18', 27), ('2026-11-25', 97))
    census = _census(**{'housing-starts': {D('2026-11-18'): '08:30'},
                        'new-home-sales': {D('2026-11-25'): '10:00'}})
    events, unresolved, *_n = U.census_events(census, rows, _resolved(), RELEASES)
    assert sorted(e['key'] for e in events) == ['release-housing-starts-20261118',
                                                 'release-new-home-sales-20261125']
    assert unresolved == {}


def test_an_unexplained_fred_day_unconfirms_the_slug():
    """rid 9 의 2026-09-28 — Census 표에 없다. 소매판매로 인쇄하지 않고, 그 창의 소매판매는 비운다."""
    census = _census(**{'retail-sales': {D('2026-09-16'): '08:30'}})
    events, unresolved, *_n = U.census_events(census, _fred(('2026-09-16', 9), ('2026-09-28', 9)),
                                         _resolved(), RELEASES)
    assert events == [] and 'retail-sales' in unresolved


def test_a_dropped_second_release_of_the_month_is_caught():
    """2026-04 소매판매는 4/1·4/21 두 번 — 4/21 행이 Census 표에서 빠져도 FRED 가 그날을 갖고 있다."""
    cut = _re.sub(r'<tr[^>]*>\s*<td[^>]*><a[^>]*>Advance Monthly Sales for Retail and Food Services'
                  r'</a></td>\s*<td[^>]*>April 21, 2026</td>.*?</tr>', '', P2026, count=1, flags=_re.S)
    assert cut != P2026
    census = C.collect(_get({**GOOD, C.YEAR_URL.format(year=2026): cut}),
                       D('2026-04-15'), D('2026-04-24'))
    assert _slot(census['retail-sales']) == ({}, None)       # Census 만으론 못 안다
    events, unresolved, *_n = U.census_events(census, _fred(('2026-04-21', 9)), _resolved(), RELEASES)
    assert events == [] and 'retail-sales' in unresolved


def test_a_census_date_fred_does_not_have_is_unconfirmed():
    census = _census(**{'trade-balance': {D('2026-12-08'): '08:30'}})
    events, unresolved, *_n = U.census_events(census, [], _resolved(), RELEASES)
    assert events == [] and 'trade-balance' in unresolved


def test_an_unconfirmed_census_slug_prints_nothing():
    census = _census(**{'retail-sales': {'dates': {}, 'why': 'Census 2026 판 실패'}})
    events, unresolved, *_n = U.census_events(census, _fred(('2026-11-17', 9)), _resolved(), RELEASES)
    assert events == [] and 'retail-sales' in unresolved


def test_a_census_slug_without_a_resolved_id_prints_nothing():
    res = _resolved()
    del res['construction-spending']
    census = _census(**{'construction-spending': {D('2026-12-01'): '10:00'}})
    events, unresolved, *_n = U.census_events(census, _fred(('2026-12-01', 229)), res, RELEASES)
    assert events == [] and 'construction-spending' in unresolved


def test_only_durable_and_factory_may_share_a_release():
    res = _resolved()
    res['housing-starts'] = (97, 'New Residential Sales')       # 신규주택과 같은 id 로 풀렸다
    census = _census(**{'housing-starts': {D('2026-11-25'): '08:30'},
                        'new-home-sales': {D('2026-11-25'): '10:00'}})
    events, unresolved, *_n = U.census_events(census, _fred(('2026-11-25', 97)), res, RELEASES)
    assert events == [] and {'housing-starts', 'new-home-sales'} <= set(unresolved)


def test_a_fred_row_naming_another_release_unconfirms_the_slug():
    census = _census(**{'retail-sales': {D('2026-11-17'): '08:30'}})
    rows = [(D('2026-11-17'), 9, 'Selected Real Retail Sales Series')]
    events, unresolved, *_n = U.census_events(census, rows, _resolved(), RELEASES)
    assert events == [] and 'retail-sales' in unresolved


def test_new_census_slugs_are_calendar_only():
    """일정에만 나온다 — 헤드라인 해부·4축 표의 대상이 아니다(설계 검토 #8)."""
    new = set(C.CENSUS_NAMES) - set(RELEASES)
    assert new == {'housing-starts', 'trade-balance', 'construction-spending', 'factory-orders'}
    assert new <= set(U.CALENDAR_ONLY)
    assert not (set(U.CALENDAR_ONLY) & set(RELEASES))


def test_census_and_fred_paths_cover_every_release_once():
    assert not (set(C.CENSUS_NAMES) & set(U.RELEASE_SERIES))
    assert set(RELEASES) <= set(C.CENSUS_NAMES) | set(U.RELEASE_SERIES)


def test_every_census_series_resolves_to_the_fred_names_seen_on_2026_11_08():
    seen = {'RSAFS': 'Advance Monthly Sales for Retail and Food Services',
            'HSN1F': 'New Residential Sales',
            'DGORDER': "Manufacturer's Shipments, Inventories, and Orders (M3) Survey",
            'AMTMNO': "Manufacturer's Shipments, Inventories, and Orders (M3) Survey",
            'HOUST': 'New Residential Construction',
            'BOPGSTB': 'U.S. International Trade in Goods and Services',
            'TTLCONS': 'Construction Spending'}
    for slug, sid in C.CENSUS_SERIES.items():
        assert U.name_fits(slug, seen[sid]), (slug, sid)


# --- 수집 묶음 ----------------------------------------------------------------

class _Client:
    transport = 'api'
    key = None
    rows = []

    def __init__(self, *a, **k):
        pass

    def preflight(self):
        pass

    def series_release(self, sid):
        by_sid = {'RSAFS': 'retail-sales', 'HSN1F': 'new-home-sales', 'DGORDER': 'durable-goods',
                  'AMTMNO': 'factory-orders', 'HOUST': 'housing-starts', 'BOPGSTB': 'trade-balance',
                  'TTLCONS': 'construction-spending'}
        if sid in by_sid:
            return _resolved()[by_sid[sid]]
        slug = next(k for k, v in U.RELEASE_SERIES.items() if v == sid)
        return 500 + list(U.RELEASE_SERIES).index(slug), U.RELEASE_NAMES[slug][0]

    def release_dates(self, start, end):
        return type(self).rows


def _bc(monkeypatch, rows, pages):
    import build_calendar as BC
    client = type('C', (_Client,), {'rows': rows})
    monkeypatch.setattr(BC, 'FredClient', client)
    monkeypatch.setattr(BC, '_auction_rows', lambda *a: [])
    monkeypatch.setattr(BC, '_census_get', _get(pages))
    return BC


def test_collect_prints_census_dates_confirmed_by_fred(monkeypatch):
    BC = _bc(monkeypatch, _fred(('2026-11-17', 9), ('2026-11-18', 27)), GOOD)
    events, _a, missing, info = BC._collect(D('2026-11-08'), D('2026-11-09'), D('2026-11-18'))
    keys = {(e['key'], e['time_et']) for e in events}
    assert keys == {('release-retail-sales-20261117', '08:30'),
                    ('release-housing-starts-20261118', '08:30')}
    assert missing == [] and info['unresolved'] == {}
    assert info['release_ids']['housing-starts'] == 27


def test_collect_without_census_blanks_only_census_slugs(monkeypatch, capsys):
    BC = _bc(monkeypatch, _fred(('2026-11-17', 9)) + [(D('2026-11-10'), 500, 'Consumer Price Index')], {})
    events, _a, missing, info = BC._collect(D('2026-11-08'), D('2026-11-09'), D('2026-11-18'))
    assert [e['key'] for e in events] == ['release-cpi-20261110']
    assert 'census' in missing and 'releases' not in missing
    assert set(C.CENSUS_NAMES) <= set(info['unresolved'])
    assert 'retail-sales' not in info['release_ids']


def test_collect_without_fred_blanks_census_slugs_too(monkeypatch):
    import build_calendar as BC
    BC = _bc(monkeypatch, [], GOOD)

    class Dead(_Client):
        def preflight(self):
            raise RuntimeError('no key')

    monkeypatch.setattr(BC, 'FredClient', Dead)
    events, _a, missing, info = BC._collect(D('2026-11-08'), D('2026-11-09'), D('2026-11-18'))
    assert events == [] and 'releases' in missing
    assert set(C.CENSUS_NAMES) <= set(info['unresolved'])


# --- codex 2026-11-08 구현 검토 재현 ------------------------------------------


_RETAIL_ROW = (r'<tr[^>]*>\s*<td[^>]*><a[^>]*>Advance Monthly Sales for Retail and Food Services'
               r'</a></td>\s*<td[^>]*>November 17, 2026</td>.*?</tr>')


def test_1_a_missing_row_inside_the_window_is_not_no_release():
    """연간 12행이 남아도 창 안의 11/17 행이 빠지면 「발표 없음」이 아니라 「확인 못 함」."""
    cut = _re.sub(_RETAIL_ROW, '', P2026, count=1, flags=_re.S)
    assert cut != P2026
    got = C.collect(_get({**GOOD, C.YEAR_URL.format(year=2026): cut}),
                    D('2026-11-09'), D('2026-11-18'))
    assert got['retail-sales']['why'] and got['retail-sales']['dates'] == {}


def test_1_a_renamed_row_inside_the_window_is_not_no_release():
    renamed = _re.sub(r'(<a[^>]*>)Advance Monthly Sales for Retail and Food Services(</a></td>\s*'
                      r'<td[^>]*>November 17, 2026)', r'\1Advance Monthly Retail Sales\2', P2026,
                      count=1, flags=_re.S)
    assert renamed != P2026
    got = C.collect(_get({**GOOD, C.YEAR_URL.format(year=2026): renamed}),
                    D('2026-11-09'), D('2026-11-18'))
    assert got['retail-sales']['why']


@pytest.mark.parametrize('wrap', [
    '<tr class="hidden">{}</tr>', '<tr hidden>{}</tr>', '<tr style="display: none">{}</tr>',
    '<tbody style="display:none"><tr>{}</tr></tbody>'])
def test_2_a_hidden_row_is_not_a_schedule(wrap):
    cells = ('<td><a>Advance Monthly Sales for Retail and Food Services</a></td>'
             '<td>November 12, 2026</td><td>10:00 AM</td><td>October 2026</td>')
    page = P2026.replace('</table>', wrap.format(cells) + '</table>', 1)
    got = C.collect(_get({**GOOD, C.YEAR_URL.format(year=2026): page}),
                    D('2026-11-09'), D('2026-11-18'))
    assert _slot(got['retail-sales']) == ({D('2026-11-17'): '08:30'}, None)
    events, unresolved, *_n = U.census_events(got, _fred(('2026-11-12', 9), ('2026-11-17', 9)),
                                         _resolved(), RELEASES)
    # 숨긴 행의 11/12 는 일정이 아니다 — FRED 만 그날을 가지면 설명이 안 돼 소매판매를 비운다.
    assert not any('20261112' in e['key'] for e in events)
    assert 'retail-sales' in unresolved


def test_2_an_unclosed_tag_before_the_table_does_not_hide_rows():
    page = '<div hidden><p>note</div><p>unclosed' + P2026
    assert C.page_rows(page, 2026)['retail-sales']['rows']


def test_3_a_target_row_missing_cells_is_bad():
    row = ('<tr><td><a>New Residential Construction (Building Permits, Housing Starts, and '
           'Housing Completions)</a></td><td>November 18, 2026</td></tr></table>')
    page = P2026.replace('</table>', row, 1)
    rows = C.page_rows(page, 2026)
    assert rows['housing-starts']['bad']
    got = C.collect(_get({**GOOD, C.YEAR_URL.format(year=2026): page}),
                    D('2026-11-09'), D('2026-11-18'))
    assert got['housing-starts']['why']


def test_4_two_names_for_one_id_on_one_day_unconfirm_the_slug():
    census = _census(**{'retail-sales': {D('2026-11-17'): '08:30'}})
    rows = _fred(('2026-11-17', 9)) + [(D('2026-11-17'), 9, 'WRONG')]
    events, unresolved, *_n = U.census_events(census, rows, _resolved(), RELEASES)
    assert events == [] and 'retail-sales' in unresolved


def test_5_both_reasons_survive(monkeypatch):
    class Odd(_Client):
        def series_release(self, sid):
            if sid == 'RSAFS':
                return 9, 'Selected Real Retail Sales Series'
            return super().series_release(sid)

    BC = _bc(monkeypatch, [], {})
    monkeypatch.setattr(BC, 'FredClient', type('O', (Odd,), {'rows': []}))
    _e, _a, _m, info = BC._collect(D('2026-11-08'), D('2026-11-09'), D('2026-11-18'))
    why = info['unresolved']['retail-sales']
    assert 'Selected Real Retail Sales Series' in why and 'Census' in why


def test_5_census_reason_survives_a_dead_dates_call(monkeypatch):
    class DeadDates(_Client):
        def release_dates(self, start, end):
            raise RuntimeError('dates timeout')

    BC = _bc(monkeypatch, [], {})
    monkeypatch.setattr(BC, 'FredClient', DeadDates)
    _e, _a, missing, info = BC._collect(D('2026-11-08'), D('2026-11-09'), D('2026-11-18'))
    why = info['unresolved']['housing-starts']
    assert 'Census 2026년 일정표' in why and 'dates timeout' in why
    assert {'releases', 'census'} <= set(missing)


def test_6_the_total_failure_line_is_scrubbed_and_one_line(monkeypatch, capsys):
    monkeypatch.setenv('FRED_API_KEY', 'SECRETKEY123')

    class Boom(_Client):
        def release_dates(self, start, end):
            raise RuntimeError('bad api_key=SECRETKEY123\n::warning::injected')

    BC = _bc(monkeypatch, [], GOOD)
    monkeypatch.setattr(BC, 'FredClient', Boom)
    BC._collect(D('2026-11-08'), D('2026-11-09'), D('2026-11-18'))
    err = capsys.readouterr().err
    assert 'SECRETKEY123' not in err
    assert not any(line.startswith('::') for line in err.splitlines())


def test_5_census_reason_is_logged_when_fred_dates_also_die(monkeypatch, capsys):
    class DeadDates(_Client):
        def release_dates(self, start, end):
            raise RuntimeError('dates timeout')

    BC = _bc(monkeypatch, [], {})
    monkeypatch.setattr(BC, 'FredClient', DeadDates)
    BC._collect(D('2026-11-08'), D('2026-11-09'), D('2026-11-18'))
    assert 'Census 2026년 일정표' in capsys.readouterr().err


# FRED 2026 릴리스 달력(2026-11-08 fred.stlouisfed.org/releases/calendar 에서 읽음).
_FRED_2026 = {
    9: '01-14 02-10 03-06 04-01 04-21 05-14 06-17 07-16 08-14 09-16 09-28 10-15 11-17 12-16',
    27: ('01-09 01-27 02-18 03-12 03-19 04-29 05-05 05-21 05-28 06-16 06-24 07-17 07-24 08-18 '
         '08-25 09-17 09-24 10-20 10-27 11-18 11-25 12-17 12-23'),
    51: '01-08 01-29 02-19 03-12 04-02 05-05 06-09 07-07 08-04 09-03 10-06 11-04 12-08',
    95: ('01-07 01-26 01-29 02-18 02-23 03-13 03-18 04-07 04-10 04-29 05-04 05-28 06-03 06-25 '
         '07-02 07-27 08-04 08-26 09-02 09-25 10-02 10-27 11-03 11-25 12-03 12-23'),
    97: '01-13 02-20 03-19 05-05 05-28 06-24 07-24 08-25 09-24 10-27 11-25 12-23',
    229: '01-21 02-27 03-23 05-07 06-01 07-01 08-03 09-01 10-01 11-02 12-01',
}


def test_the_real_2026_calendars_leave_only_the_known_unexplained_day():
    """실제 2026 FRED 달력 전체를 Census 표로 설명해 본다 — 설명 못 하는 날은 소매 9/28 과
    주택착공 1/27(Census 표에 그날 아무 지표도 없다) 둘뿐."""
    census = C.collect(_get(GOOD), D('2026-01-01'), D('2026-12-31'))
    rows = _fred(*[(f'2026-{md}', rid) for rid, mds in _FRED_2026.items() for md in mds.split()])
    events, unresolved, *_n = U.census_events(census, rows, _resolved(), RELEASES)
    # 4월(신규주택·건설지출 발표 없음)은 월별 확인에서 걸린다 — 한 해 창이라 그 둘은 빈다.
    assert set(unresolved) == {'retail-sales', 'new-home-sales', 'construction-spending',
                               'housing-starts'}
    assert '2026-09-28' in unresolved['retail-sales']
    assert '2026-01-27' in unresolved['housing-starts']
    assert {e['key'].rsplit('-', 1)[0] for e in events} == {
        'release-durable-goods', 'release-factory-orders', 'release-trade-balance'}
    # 1/27 이 없는 창에서는 신규주택이 비어도 그 날짜(10개)가 주택착공 쪽을 설명한다.
    late = C.collect(_get(GOOD), D('2026-11-16'), D('2026-11-27'))
    rows = _fred(('2026-11-18', 27), ('2026-11-25', 27), ('2026-11-25', 97), ('2026-11-17', 9),
                 ('2026-11-25', 95))
    late['new-home-sales'] = {**late['new-home-sales'], 'dates': {}, 'why': '시험용으로 비움'}
    events, unresolved, *_n = U.census_events(late, rows, _resolved(), RELEASES)
    assert 'housing-starts' not in unresolved
    assert 'release-housing-starts-20261118' in {e['key'] for e in events}



def test_3rd_a_shifted_row_on_a_shared_release_cannot_hide_a_missing_one():
    """codex 11/08 구현 3회: 내구재 4/7 행을 지우고 공장주문 4/10 행을 4/7 로 복제하면, FRED 95 의
    4/7 이 공장주문으로 「설명」돼 내구재 누락이 가려졌다. 공장주문이 4/7·4/10 — 3일 간격."""
    cut = _re.sub(r'<tr[^>]*>\s*<td[^>]*><a[^>]*>Advance Report on Durable Goods--Manufacturers\' '
                  r'Shipments, Inventories, and Orders</a></td>\s*<td[^>]*>April 7, 2026</td>.*?</tr>',
                  '', P2026, count=1, flags=_re.S)
    assert cut != P2026
    dup = ("<tr><td><a>Full Report - Manufacturers' Shipments, Inventories and Orders</a></td>"
           '<td>April 7, 2026</td><td>10:00 AM</td><td>February 2026</td></tr></table>')
    page = cut.replace('</table>', dup, 1)
    census = C.collect(_get({**GOOD, C.YEAR_URL.format(year=2026): page}),
                       D('2026-04-07'), D('2026-04-10'))
    events, unresolved, *_n = U.census_events(census, _fred(('2026-04-07', 95), ('2026-04-10', 95)),
                                         _resolved(), RELEASES)
    assert 'factory-orders' in unresolved and 'durable-goods' in unresolved
    assert events == []


def test_releases_closer_than_two_weeks_across_new_year_are_caught():
    early = ('<tr><td><a>Construction Spending (Construction Put in Place)</a></td>'
             '<td>January 6, 2027</td><td>10:00 AM</td><td>November 2026</td></tr></table>')
    latest = PLATEST.replace('</table>', early, 1)
    got = C.collect(_get({**GOOD, C.LIST_URL: latest}), D('2026-12-28'), D('2027-01-08'))
    assert got['construction-spending']['why']



def test_4th_a_durable_date_written_on_a_factory_day_is_caught():
    """codex 11/08 구현 4회 #1: 내구재 4/7 을 4/10 으로 잘못 적으면 공장주문의 FRED 행이 근거가 됐다."""
    moved = P2026.replace('>April 7, 2026</td>\n               <td>8:30 AM</td>\n               <td>February 2026',
                          '>April 10, 2026</td>\n               <td>8:30 AM</td>\n               <td>February 2026')
    assert moved != P2026
    census = C.collect(_get({**GOOD, C.YEAR_URL.format(year=2026): moved}),
                       D('2026-04-08'), D('2026-04-12'))
    events, unresolved, _n = U.census_events(census, _fred(('2026-04-10', 95)), _resolved(), RELEASES)
    assert events == [] and {'durable-goods', 'factory-orders'} <= set(unresolved)


def test_4th_an_unusual_time_prints_the_date_without_a_time():
    """codex 11/08 구현 4회 #2: FRED 는 시각을 확인해 주지 못한다 — 평소 시각과 다르면 시각을 비운다."""
    census = _census(**{'retail-sales': {D('2026-11-17'): '10:00'}})
    events, unresolved, notes = U.census_events(census, _fred(('2026-11-17', 9)), _resolved(),
                                                RELEASES)
    assert unresolved == {} and 'retail-sales' in notes
    assert [(e['key'], e['time_et'], e['time_kst']) for e in events] == [
        ('release-retail-sales-20261117', None, None)]


def test_the_usual_times_match_every_row_of_both_tables():
    for page, year in ((P2026, 2026), (PLATEST, 2027)):
        for slug, v in C.page_rows(page, year).items():
            assert {t for _d, t in v['rows']} == {C.CENSUS_TIME_ET[slug]}, (year, slug)
