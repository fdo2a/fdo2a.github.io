"""매일 검증 알림이 일본 일정표가 바닥나기 전에 알린다(2026-11-13).

일본 일정표는 원출처에서 확인한 날짜를 손으로 넣는다. 일간 일정표가 11/12 에서 끝난 뒤 지표 표와
결정일 표시가 조용히 멈췄다 — 그 사실이 사람에게 닿아야 다시 채운다.
spec: docs/superpowers/specs/2026-11-08-daily-verify-digest.md
"""
from datetime import date

from review import digest as D


def _cal(*days):
    return {'events': [{'date': d} for d in days]}


def test_runs_out_within_two_weeks_both_calendars():
    notes = D.jp_calendar_notes({'일간': _cal('2026-11-10', '2026-11-12'), '주간': _cal('2026-12-17')},
                                date(2026, 11, 13))
    assert notes == ['일본 일간 일정표 마지막 일정이 11/12예요 — 원출처에서 확인한 일정을 더하지 않으면 '
                     '지표 표·결정일 표시·다음 일정 표가 멈춰요']


def test_boundary_is_inclusive():
    today = date(2026, 11, 13)
    assert D.jp_calendar_notes({'주간': _cal('2026-11-27')}, today)          # 정확히 14일 뒤 — 알린다
    assert D.jp_calendar_notes({'주간': _cal('2026-11-28')}, today) == []     # 15일 뒤 — 아직 조용


def test_empty_and_unreadable():
    today = date(2026, 11, 13)
    assert D.jp_calendar_notes({'주간': {'events': []}}, today) == [
        '일본 주간 일정표 일정이 하나도 없어요 — 원출처에서 확인한 일정을 더하지 않으면 다음 일정 표가 비어요']
    assert D.jp_calendar_notes({'일간': None, '주간': {'x': 1}}, today) == [D.JP_CAL_UNREAD]


def test_bad_dates_are_skipped_not_fatal():
    notes = D.jp_calendar_notes({'일간': {'events': [{'date': None}, {'date': '2027-01-29'}, {}]}},
                                date(2026, 11, 13))
    assert notes == []


def test_notes_pass_the_whitelist_as_must_lines():
    today = date(2026, 11, 13)
    lines = (D.jp_calendar_notes({'일간': _cal('2026-11-12'), '주간': {'events': []}}, today)
             + [D.JP_CAL_UNREAD])
    assert [cls for _n, cls in D._classified_notes(lines)] == ['must', 'must', 'must']
    assert D.safe_notes(lines) == lines


def test_non_iso_dates_do_not_extend_the_runway():
    # 소비 코드가 못 읽는 꼴('20270129')을 바닥으로 세면 실제로 비어 가는 일정표를 놓친다
    notes = D.jp_calendar_notes({'주간': {'events': [{'date': '2026-11-20'}, {'date': '20270129'}, 'x']}},
                                date(2026, 11, 13))
    assert notes and '11/20' in notes[0]
