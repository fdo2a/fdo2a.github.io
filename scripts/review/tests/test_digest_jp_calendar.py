"""매일 검증 알림이 일본 일정표가 바닥나기 전에 알린다(2026-11-13).

일본 일정표는 원출처에서 확인한 날짜를 손으로 넣는다. 일간 일정표가 11/12 에서 끝난 뒤 지표 표와
결정일 표시가 조용히 멈췄다 — 그 사실이 사람에게 닿아야 다시 채운다.
spec: docs/superpowers/specs/2026-11-08-daily-verify-digest.md
"""
from datetime import date

from review import digest as D


def _cov():
    from japan import daily_calendar as C
    return [{'id': cid, 'name_ko': n, 'cadence': 'irregular', 'source': 'https://x', 'from': '2026-01-01',
             'through': '2027-12-31', 'checked_at': '2026-11-13'} for cid, n in C.REQUIRED]


def _cal(*days):
    # 일간 일정표의 확인 창(v2)은 전부 덮인 것으로 둔다 — 이 파일의 앞쪽 시험은 「마지막 일정」 알림만 본다
    return {'events': [{'date': d} for d in days], 'coverage': _cov()}


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
    notes = D.jp_calendar_notes({'일간': {'events': [{'date': None}, {'date': '2027-01-29'}, {}], 'coverage': _cov()}},
                                date(2026, 11, 13))
    # 바닥 알림은 없다(죽지도 않는다). 날짜를 못 읽는 행은 v2 확인 창 판정에서 「계열을 확인할 수 없는 일정 행」이다
    # (codex 구현 1회 #6 — 그런 행이 있는 날은 부재 캡션을 찍지 않는다)
    from japan import daily_calendar as C
    assert notes == [D.JP_COV_PREFIX + C.UNLINKED + D.JP_COV_SUFFIX] and D.safe_notes(notes) == notes


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


# ── 일본 일간 v2: 계열별 확인 창(2026-11-19, R14) ─────────────────────────────

def test_coverage_gap_names_series_and_passes_whitelist():
    from japan import daily_calendar as C
    cov = [c for c in _cov() if c['id'] not in ('trade', 'gdp')]
    cov.append(dict(_cov()[0], id='gdp', through='2026-11-20'))          # 3주를 못 덮는다
    notes = D.jp_calendar_notes({'일간': {'events': [{'date': '2027-01-29', 'cov': 'boj_policy'}], 'coverage': cov}},
                                date(2026, 11, 13))
    assert notes == [D.JP_COV_PREFIX + 'GDP·무역통계' + D.JP_COV_SUFFIX]
    assert D.safe_notes(notes) == notes and [c for _n, c in D._classified_notes(notes)] == ['must']
    assert C.REQUIRED_NAMES['trade'] == '무역통계'


def test_monthly_meeting_rows_only_named_in_alert():
    cov = _cov()
    for c in cov:
        if c['id'] == 'boj_policy':
            c.update(cadence='monthly', **{'from': '2026-12-01', 'through': '2026-12-31'})
    cal = {'events': [{'date': '2026-12-17', 'kind': 'meeting', 'cov': 'boj_policy'}, {'date': '2027-01-29'}],
           'coverage': cov}
    notes = D.jp_calendar_notes({'일간': cal}, date(2026, 12, 1))
    assert notes and 'BOJ 금융정책' in notes[0]


def test_repo_daily_calendar_covers_every_required_series():
    """2026-11-19 원출처로 6개 계열 창을 채웠다 — 오늘 기준 미확인 계열이 없어야 한다."""
    import json
    import os
    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..')
    with open(os.path.join(root, 'japan', 'data', 'calendar_daily.json'), encoding='utf-8') as fh:
        cal = json.load(fh)
    notes = D.jp_calendar_notes({'일간': cal}, date(2026, 11, 19))
    assert not any(n.startswith(D.JP_COV_PREFIX) for n in notes), notes
