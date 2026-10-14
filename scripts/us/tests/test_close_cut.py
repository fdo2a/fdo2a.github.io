"""원자재·환율 = 뉴욕 16:00 ET 가격, 오늘과 전일 모두 같은 기준.

2026-10-13 발행본 실측: 원자재 `last` 는 수집 시각의 시간외 거래가(18:13 ET)였고
`chg` 는 전일 결제가 대비였다 — 10/12 발행 Brent 105.70 은 결제가(106.65)가 아니라
20:34 ET 시세라, 다음 날 표의 등락률이 전날 발행 종가로 이어지지 않았다. 환율은 더
나빴다: 야후 **일봉** USD/KRW 가 ECB 기준환율과 날짜가 뒤바뀐 듯 어긋났고(10/12 1,340.84
vs ECB 역산 1,333.1), 장중 봉(1,334.57)은 ECB 와 맞았다.
"""
import math

import pytest

from scripts.us import close_cut as cc


def bars(day, closes, start='13:30'):
    """30분봉 (ET 시작 시각 ISO, 종가) 목록 — start 부터 30분 간격."""
    h, m = map(int, start.split(':'))
    out = []
    for c in closes:
        out.append((f'{day}T{h:02d}:{m:02d}:00-04:00', c))
        m += 30
        h, m = h + m // 60, m % 60
    return out


def test_cut_takes_the_bar_that_ends_at_four():
    # 13:30·14:00·…·15:30 봉, 그리고 16:00·16:30 봉(정산 뒤·마감 뒤).
    b = bars('2026-10-13', [94.1, 94.2, 94.4, 94.7, 94.88, 94.79], start='13:30')
    # 15:30 봉의 종가 = 16:00 직전 마지막 체결. 16:00 봉 이후는 보지 않는다.
    assert cc.cut_closes(b) == {'2026-10-13': 94.88}


def test_cut_ignores_evening_session_bars():
    # 10/12 발행 사고의 재현: 20:00 ET 봉(다음 세션)이 그날 값으로 섞이면 안 된다.
    b = bars('2026-10-12', [106.02, 105.92], start='15:30') + \
        [('2026-10-12T20:00:00-04:00', 105.66), ('2026-10-12T20:30:00-04:00', 105.94)]
    assert cc.cut_closes(b) == {'2026-10-12': 106.02}


def test_cut_converts_other_timezones_to_new_york():
    # 통화쌍은 런던 시각으로 온다. 20:30 런던 = 15:30 ET 봉.
    b = [('2026-10-13T20:30:00+01:00', 1340.05), ('2026-10-13T21:00:00+01:00', 1340.8)]
    assert cc.cut_closes(b) == {'2026-10-13': 1340.05}


def test_cut_skips_a_day_with_no_bar_before_four():
    b = [('2026-10-13T18:00:00-04:00', 94.66)]
    assert cc.cut_closes(b) == {}


def test_cut_drops_non_finite_prices():
    b = bars('2026-10-13', [94.7, float('nan')], start='15:00')
    assert cc.cut_closes(b) == {'2026-10-13': 94.7}


SESSIONS = {'2026-10-09': 960, '2026-10-12': 960, '2026-10-13': 960}


def ends(*pairs):
    """(날짜, 끝 분, 값) → {날짜: {끝 분: 값}}"""
    out = {}
    for d, m, v in pairs:
        out.setdefault(d, {})[m] = v
    return out


def test_row_compares_today_with_the_previous_session_close():
    e = ends(('2026-10-12', 960, 93.36), ('2026-10-13', 960, 94.70), ('2026-10-13', 930, 94.6))
    row = cc.cut_row(e, SESSIONS, '2026-10-13', contract='CLX26.NYM')
    assert row['last'] == 94.70
    assert row['prev'] == 93.36 and row['prev_date'] == '2026-10-12'
    assert row['pct'] == pytest.approx((94.70 / 93.36 - 1) * 100)
    assert row['chg'] == pytest.approx(94.70 - 93.36)
    assert row['date'] == '2026-10-13'
    assert row['basis'] == cc.BASIS
    assert row['contract'] == 'CLX26.NYM'
    assert row['cut_et'] == '16:00'


def test_partial_session_is_not_a_close():
    # codex 구현 검토 P1: 오늘 봉이 10:00 까지만 있으면 16:00 컷이 아니다.
    e = ends(('2026-10-12', 960, 100.0), ('2026-10-13', 630, 105.0))
    assert cc.cut_row(e, SESSIONS, '2026-10-13') is None


def test_missing_previous_session_is_not_a_daily_change():
    # codex 구현 검토 P1: 10/12 봉을 못 받았는데 10/09 대비 +5% 를 「하루」로 싣지 않는다.
    e = ends(('2026-10-09', 960, 100.0), ('2026-10-13', 960, 105.0))
    assert cc.cut_row(e, SESSIONS, '2026-10-13') is None


def test_previous_session_skips_weekends_by_the_equity_calendar():
    e = ends(('2026-10-09', 960, 91.58), ('2026-10-12', 960, 93.36))
    assert cc.cut_row(e, SESSIONS, '2026-10-12')['prev_date'] == '2026-10-09'


def test_early_close_day_cuts_at_the_equity_close():
    # 단축장(13:00 ET)은 그 시각 봉으로 자른다 — 주식 마감과 같은 순간.
    sessions = {'2026-11-25': 960, '2026-11-27': 780}
    e = ends(('2026-11-25', 960, 1.0), ('2026-11-27', 780, 1.1), ('2026-11-27', 960, 1.2))
    row = cc.cut_row(e, sessions, '2026-11-27')
    assert row['last'] == 1.1 and row['cut_et'] == '13:00'


def test_row_is_none_when_the_anchor_is_not_a_session():
    e = ends(('2026-10-12', 960, 1.0), ('2026-10-13', 960, 1.0))
    assert cc.cut_row(e, {'2026-10-12': 960}, '2026-10-13') is None


def test_row_is_none_without_a_previous_session():
    assert cc.cut_row(ends(('2026-10-13', 960, 1.0)), {'2026-10-13': 960}, '2026-10-13') is None


def test_row_is_none_for_a_zero_previous_value():
    e = ends(('2026-10-12', 960, 0.0), ('2026-10-13', 960, 1.0))
    assert cc.cut_row(e, SESSIONS, '2026-10-13') is None


def test_session_ends_come_from_the_equity_bars_and_cap_at_four():
    spx = bars('2026-10-13', [1, 2], start='15:00') + [('2026-10-13T16:00:00-04:00', 2)] + \
        [('2026-11-27T12:30:00-05:00', 5)]     # 추수감사절 다음 날 단축장, 서머타임 해제 뒤
    daily = {'2026-10-13': 2, '2026-11-27': 5}
    assert cc.session_ends(spx, daily) == {'2026-10-13': 960, '2026-11-27': 780}


def test_truncated_equity_download_is_not_a_session():
    # codex 재검토 P1: 30분봉이 10:00 에서 끊긴 날을 「10:00 마감」으로 믿지 않는다.
    spx = [('2026-10-13T09:30:00-04:00', 100.0)]
    assert cc.session_ends(spx, {'2026-10-13': 100.0}) == {}


def test_equity_close_must_match_the_daily_bar():
    spx = bars('2026-10-13', [100.0], start='15:30')
    assert cc.session_ends(spx, {'2026-10-13': 100.05}) == {'2026-10-13': 960}
    assert cc.session_ends(spx, {'2026-10-13': 100.5}) == {}
    assert cc.session_ends(spx, {}) == {}


def test_missing_equity_session_in_the_intraday_download_fails_closed():
    # codex 재검토 P1: 30분봉에서 10/12 가 빠져도 일봉 달력에는 있으니 10/09 와 비교하지 않는다.
    e = ends(('2026-10-09', 960, 100.0), ('2026-10-12', 960, 90.0), ('2026-10-13', 960, 105.0))
    sessions = {'2026-10-09': 960, '2026-10-13': 960}
    calendar = ['2026-10-09', '2026-10-12', '2026-10-13']
    assert cc.cut_row(e, sessions, '2026-10-13', calendar=calendar) is None


def test_row_states_both_cut_times():
    sessions = {'2026-11-25': 960, '2026-11-27': 780}
    e = ends(('2026-11-25', 960, 1.0), ('2026-11-27', 780, 1.1))
    row = cc.cut_row(e, sessions, '2026-11-27', calendar=['2026-11-25', '2026-11-27'])
    assert (row['cut_et'], row['prev_cut_et']) == ('13:00', '16:00')


def test_bar_ends_index_bars_by_their_end_minute():
    b = bars('2026-10-13', [94.4, 94.7], start='15:00')
    assert cc.bar_ends(b) == {'2026-10-13': {930: 94.4, 960: 94.7}}


def test_override_rewrites_both_legs_in_the_history():
    # 표와 가격 위치·움직임 크기가 같은 두 값을 봐야 한다(codex 설계 검토 A11).
    closes = [91.85, 93.74, 94.77]
    dates = ['2026-10-09', '2026-10-12', '2026-10-13']
    row = {'last': 94.70, 'prev': 93.36, 'date': '2026-10-13', 'prev_date': '2026-10-12'}
    c, d = cc.override_history(closes, dates, row)
    assert d == dates
    assert c == [91.85, 93.36, 94.70]
    assert closes == [91.85, 93.74, 94.77]          # 원본은 건드리지 않는다


def test_override_appends_today_when_the_daily_bar_is_missing():
    c, d = cc.override_history([91.85, 93.74], ['2026-10-09', '2026-10-12'],
                               {'last': 94.70, 'prev': 93.36,
                                'date': '2026-10-13', 'prev_date': '2026-10-12'})
    assert d == ['2026-10-09', '2026-10-12', '2026-10-13']
    assert c == [91.85, 93.36, 94.70]


def test_override_leaves_history_alone_without_a_row():
    assert cc.override_history([1.0], ['2026-10-13'], None) == ([1.0], ['2026-10-13'])


def test_valid_row_requires_basis_and_anchor_date():
    good = {'last': 1.0, 'prev': 1.0, 'pct': 0.0, 'date': '2026-10-13',
            'prev_date': '2026-10-12', 'basis': cc.BASIS}
    assert cc.row_problem(good, '2026-10-13') is None
    assert cc.row_problem(dict(good, basis='daily'), '2026-10-13') == 'basis'
    assert cc.row_problem(dict(good, date='2026-10-12'), '2026-10-13') == 'stale:2026-10-12'
    assert cc.row_problem(dict(good, last=math.nan), '2026-10-13') == 'value'
    assert cc.row_problem(dict(good, prev_date='2026-10-13'), '2026-10-13') == 'prev_date'
