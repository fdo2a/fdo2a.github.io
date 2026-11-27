"""의무 판정(`due_events`)·일정표 대조(`missing_scheduled`)·발행본 장부(`covered_from_posts`)."""
import json
import os
import subprocess

import pytest

from common import cb_events as CE

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))


def _sched(start='2026-11-28'):
    return {'bank': 'bok', 'start': start, 'meetings': [
        {'meeting': '2026-11-26', 'decision': '2026-11-26', 'presser': '2026-11-26', 'minutes': '2026-12-15'},
        {'meeting': '2027-01-14', 'decision': '2027-01-14', 'presser': '2027-01-14', 'minutes': '2027-02-02'}]}


def _row(kind, meeting, date, ok=True):
    return {'key': CE.event_key(kind, meeting), 'kind': kind, 'date': date, 'meeting_date': meeting,
            'sources': [{'role': 'x', 'ok': ok}]}


def test_keys_match_the_collector_naming():
    assert CE.event_key('bok_decision', '2026-11-26') == 'bok-decision-20261126'
    assert CE.event_key('boj_presser', '2026-10-30') == 'boj-presser-20261030'


def test_before_start_nothing_is_due_even_on_the_decision_day():
    # 11/26 KR 발행본은 금통위를 「정책·정치 촉매」에서 이미 다뤘지만 표식이 없다 — start 가 없으면 켠 첫날 due 가 된다
    rows = [_row('bok_decision', '2026-11-26', '2026-11-26'), _row('bok_presser', '2026-11-26', '2026-11-26')]
    for d in ('2026-11-26', '2026-11-27', '2026-11-30'):
        assert CE.due_events(rows, _sched(), set(), d) == []
    due = CE.due_events(rows, _sched(start='2026-11-20'), set(), '2026-11-26')
    assert [e['key'] for e in due] == ['bok-decision-20261126', 'bok-presser-20261126']


def test_covered_keys_are_not_due_and_window_is_ten_days():
    rows = [_row('bok_minutes', '2026-11-26', '2026-12-15')]
    s = _sched()
    assert [e['key'] for e in CE.due_events(rows, s, set(), '2026-12-15')] == ['bok-minutes-20261126']
    assert CE.due_events(rows, s, {'bok-minutes-20261126'}, '2026-12-16') == []
    assert [e['key'] for e in CE.due_events(rows, s, set(), '2026-12-25')] == ['bok-minutes-20261126']
    assert CE.due_events(rows, s, set(), '2026-12-26') == []        # 11일째 — 창 밖
    assert CE.due_events(rows, s, set(), '2026-12-14') == []        # 공개 전


def test_schedule_only_decision_day_is_due_without_events_json():
    due = CE.due_events(None, _sched(), set(), '2027-01-14')
    assert [(e['key'], e.get('from_schedule'), e['sources']) for e in due] == [('bok-decision-20270114', True, [])]
    # 원문 행이 있어도 전부 실패면 여전히 일정표 의무(받은 행이 없다)
    failed = [_row('bok_decision', '2027-01-14', '2027-01-14', ok=False)]
    assert CE.due_events(failed, _sched(), set(), '2027-01-14')[0]['from_schedule'] is True
    # 받은 행이 있으면 그 행이 due — 일정표 행을 따로 만들지 않는다
    got = [_row('bok_decision', '2027-01-14', '2027-01-14')]
    assert [e.get('from_schedule') for e in CE.due_events(got, _sched(), set(), '2027-01-14')] == [None]
    # 기자간담회는 결정일 의무가 아니다 — 못 받았으면 칸을 요구하지 않는다(알림만)
    assert all(e['kind'] == 'bok_decision' for e in CE.due_events(None, _sched(), set(), '2027-01-14'))


def test_missing_scheduled_lists_unreceived_docs_only():
    rows = [_row('bok_decision', '2027-01-14', '2027-01-14')]
    miss = CE.missing_scheduled(_sched(), rows, '2027-01-14')
    assert [m['key'] for m in miss] == ['bok-presser-20270114']
    assert CE.missing_scheduled(_sched(), rows, '2026-11-27') == []     # start 앞


def test_bad_schedule_stops_loudly():
    with pytest.raises(CE.ScheduleError):
        CE.due_events([], {'bank': 'bok', 'meetings': []}, set(), '2026-12-01')
    with pytest.raises(CE.ScheduleError):
        CE.due_events([], {'bank': 'bok', 'start': '2026-11-28', 'meetings': [{'meeting': '2026-13-01'}]}, set(),
                      '2026-12-01')


def _git(repo, *args):
    subprocess.run(['git', '-C', repo, *args], check=True, capture_output=True)


def test_covered_reads_committed_posts_before_the_date_only(tmp_path):
    repo = str(tmp_path)
    _git(repo, 'init', '-q')
    _git(repo, 'config', 'user.email', 't@t')
    _git(repo, 'config', 'user.name', 't')
    os.makedirs(os.path.join(repo, 'kr', 'posts'))
    def put(name, body):
        with open(os.path.join(repo, 'kr', 'posts', name), 'w', encoding='utf-8') as fh:
            fh.write(body)
    put('2026-12-15.html', '<p data-cb-event="bok-minutes-20261126">어제 글</p>')
    put('2026-12-16.html', '<p data-cb-event="bok-decision-20261126">오늘 글</p>')
    put('2026-12-14.html', '<!-- <p data-cb-event="bok-x-1"> --> <p>없음</p>')
    _git(repo, 'add', '-A')
    _git(repo, 'commit', '-qm', 'x')
    # 작업 트리에만 있는 글은 장부가 아니다
    put('2026-12-10.html', '<p data-cb-event="bok-uncommitted-1">커밋 안 됨</p>')
    got = CE.covered_from_posts(repo, 'kr/posts', '2026-12-16')
    assert got == {'bok-minutes-20261126'}          # 오늘(12-16) 글은 빠지고, 주석 속 표식은 세지 않는다


def test_real_schedules_parse_and_start_is_set():
    for rel, bank in (('kr/data/bok/schedule.json', 'bok'), ('japan/data/boj/schedule.json', 'boj')):
        with open(os.path.join(ROOT, rel), encoding='utf-8') as fh:
            s = json.load(fh)
        assert s['bank'] == bank and s['start'] == '2026-11-28'
        docs = CE.schedule_docs(s)
        assert docs and all(d['date'] >= d['meeting_date'] for d in docs)
    with open(os.path.join(ROOT, 'japan/data/boj/schedule.json'), encoding='utf-8') as fh:
        boj = {m['meeting']: m for m in json.load(fh)['meetings']}
    assert boj['2026-12-18']['presser'] == '2026-12-21' and boj['2026-10-30']['minutes'] == '2026-12-23'
    assert 'minutes' not in boj['2027-12-17']           # 일정표가 「未定」 — 비워 둔다
