"""일본 일간 매크로 — 발표일이어도 API 에 새 기간이 없으면 pending (codex 설계 검토 #4)."""
import re

from japan import daily_macro as M
from japan import daily_rates as R

EV = [{'date': '2026-10-27', 'name_ko': '기업 서비스가격지수(9월)', 'kind': 'release', 'tier': 'minor',
       'series': 'sppi', 'period': '2026-09', 'source': 'https://www.boj.or.jp/en/about/calendar/index.htm'}]


def _series(points):
    return {'code': 'PRCS20_5200000000', 'name': '[Basic grouping index] All items',
            'unit': 'CY2020 average=100', 'freq': 'MONTHLY', 'points': points}


PTS = [['2025-09', 108.0], ['2026-07', 110.0], ['2026-08', 110.4], ['2026-09', 111.24]]


def test_release_reflected_is_released():
    got = M.macro_items(EV, {'sppi': _series(PTS)}, '2026-10-27', {'sppi': '2026-08'})
    (it,) = got
    assert it['status'] == 'released' and it['period'] == '2026-09' and it['value'] == 111.24
    assert it['prev_period'] == '2026-08' and it['prev_value'] == 110.4
    assert it['released'] == '2026-10-27'


def test_release_not_reflected_is_pending():
    got = M.macro_items(EV, {'sppi': _series(PTS[:-1])}, '2026-10-27', {'sppi': '2026-08'})
    assert got[0]['status'] == 'pending' and got[0]['value'] is None and got[0]['released'] is None


def test_stale_previous_period_does_not_fake_a_release():
    # codex 구현 검토 #9 — 직전 기록 7월, API 최신 8월: 오늘 예정된 9월이 아니면 pending
    got = M.macro_items(EV, {'sppi': _series(PTS[:-1])}, '2026-10-27', {'sppi': '2026-07'})
    assert got[0]['status'] == 'pending'


def test_event_without_expected_period_is_pending():
    ev = [dict(EV[0], period=None)]
    assert M.macro_items(ev, {'sppi': _series(PTS)}, '2026-10-27', {})[0]['status'] == 'pending'


def test_released_without_previous_snapshot():
    assert M.macro_items(EV, {'sppi': _series(PTS)}, '2026-10-27', {})[0]['status'] == 'released'


def test_no_event_no_items():
    assert M.macro_items([], {'sppi': _series(PTS)}, '2026-10-27', {}) == []


def test_event_without_series_listed_as_schedule_only():
    ev = [{'date': '2026-10-30', 'name_ko': 'BOJ 금융정책 결정문', 'kind': 'release', 'tier': 'major',
           'series': None, 'source': 'https://x'}]
    (it,) = M.macro_items(ev, {}, '2026-10-30', {})
    assert it['status'] == 'event' and it['value'] is None


def test_yoy_from_same_period_last_year_only():
    it = M.macro_items(EV, {'sppi': _series(PTS)}, '2026-10-27', {'sppi': '2026-08'})[0]
    assert it['yoy'] == 3.0
    it = M.macro_items(EV, {'sppi': _series(PTS[1:])}, '2026-10-27', {'sppi': '2026-08'})[0]
    assert it['yoy'] is None


def test_latest_periods():
    assert M.latest_periods({'sppi': _series(PTS)}) == {'sppi': '2026-09'}


def test_resolve_latest_base_picks_newest_base_year():
    meta = {'RESULTSET': [
        {'SERIES_CODE': 'PRCG20_2200000000', 'NAME_OF_TIME_SERIES': '[Producer Price Index] All commodities', 'UNIT': 'CY2020 average=100'},
        {'SERIES_CODE': 'PRCG15_2200000000', 'NAME_OF_TIME_SERIES': '[Producer Price Index] All commodities', 'UNIT': 'CY2015 average=100'},
        {'SERIES_CODE': 'PRCG20_2200000000%', 'NAME_OF_TIME_SERIES': '[Producer Price Index] All commodities (Year-on-year change)', 'UNIT': '%'}]}
    assert M.resolve_latest_base(meta, M.SERIES['cgpi']['pattern']) == 'PRCG20_2200000000'


def test_series_table_covers_calendar_series():
    from japan import daily_calendar as C
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    cal = C.load(os.path.join(here, '..', '..', '..', 'japan', 'data', 'calendar_daily.json'))
    for e in cal['events']:
        assert e['series'] is None or e['series'] in M.SERIES
        if e['series']:
            assert re.fullmatch(r'\d{4}-\d{2}|\d{4}Q\d', e.get('period') or '')
    assert R  # 같은 패키지 — boj_values 의 모양을 쓴다
