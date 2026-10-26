"""일본 일간 달력 overlay — 회의 시작일과 결과 공표일을 가른다(codex 설계 검토 #5)."""
import json
import os

from japan import daily_calendar as C

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, '..', '..', '..')

CAL = {'checked_at': '2026-10-27', 'events': [
    {'date': '2026-10-29', 'time_jst': None, 'name_ko': 'BOJ 금융정책결정회의(10월 29-30일)',
     'kind': 'meeting', 'tier': 'major', 'series': None, 'source': 'https://x', 'checked_at': '2026-10-27'},
    {'date': '2026-10-30', 'time_jst': None, 'name_ko': 'BOJ 정책 결정문',
     'kind': 'release', 'tier': 'major', 'series': None, 'source': 'https://x', 'checked_at': '2026-10-27'},
    {'date': '2026-11-02', 'time_jst': '14:00', 'name_ko': '전망 보고서 전문',
     'kind': 'release', 'tier': 'minor', 'series': None, 'source': 'https://x', 'checked_at': '2026-10-27'},
    {'date': '2026-11-12', 'time_jst': '08:50', 'name_ko': '기업물가지수(10월)',
     'kind': 'release', 'tier': 'minor', 'series': 'cgpi', 'source': 'https://x', 'checked_at': '2026-10-27'},
]}


def test_meeting_start_is_not_event_day():
    assert C.event_day(CAL, '2026-10-29') == []


def test_result_day_is_event_day():
    got = C.event_day(CAL, '2026-10-30')
    assert [e['name_ko'] for e in got] == ['BOJ 정책 결정문']


def test_minor_release_not_event_day():
    assert C.event_day(CAL, '2026-11-02') == []


def test_today_events_include_all_kinds():
    assert len(C.today_events(CAL, '2026-10-29')) == 1


def test_upcoming_excludes_today():
    got = C.upcoming(CAL, '2026-10-30')
    assert [e['date'] for e in got] == ['2026-11-02', '2026-11-12']
    assert C.upcoming(CAL, '2026-10-30', days=3) == [CAL['events'][2]]


def test_version_stable_under_key_order():
    shuffled = json.loads(json.dumps(CAL))
    shuffled['events'] = [dict(reversed(list(e.items()))) for e in shuffled['events']]
    assert C.version(CAL) == C.version(shuffled)
    assert len(C.version(CAL)) == 12


def test_seed_file_rows_have_source_and_kind():
    cal = C.load(os.path.join(ROOT, 'japan', 'data', 'calendar_daily.json'))
    assert cal['events']
    for e in cal['events']:
        assert e['kind'] in ('release', 'meeting') and e['tier'] in ('major', 'minor')
        assert e['source'].startswith('https://') and e['checked_at']


def test_weekly_calendar_untouched():
    with open(os.path.join(ROOT, 'japan', 'data', 'calendar.json'), encoding='utf-8') as fh:
        weekly = json.load(fh)
    for e in weekly['events']:
        assert 'kind' not in e and 'tier' not in e
