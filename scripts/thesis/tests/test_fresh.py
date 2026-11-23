"""수집 시각과 무관한 세션 이름표·확정 관측·신선도.

실제 사고(2026-11-23 조사): 예약 수집이 7.5-10시간 늦게 돌아 MU 장중 값이 그날 종가로
59행 중 36행 기록됐고, 수집 시각의 KST 날짜가 as_of 로 찍혀 낡은 KR 종가가 「오늘 것」으로
통과했다. 늦은 예약분이 다음날 키로 더 옛 KR 값을 열기도 했다(11-16 → 11-17 행).
"""
from datetime import datetime, timedelta, timezone

import pytest

from thesis import fresh as F

KST = timezone(timedelta(hours=9))
CAL = F.calendar({
    'kr': {'valid_through': '2027-12-31', 'dates': ['2026-10-09']},
    'us': {'valid_through': '2027-12-31', 'dates': ['2026-11-26']},
})


def at(text):
    return datetime.fromisoformat(text)


# ── 기대 세션 ────────────────────────────────────────────────────────

def test_weekday_after_kr_close_pairs_with_previous_us_session():
    # 월 16:05 KST: KR 월, MU 는 금요일 미국 장(한국 장 마감 전에 끝난 마지막 장)
    assert F.sessions(at('2026-11-23T16:05:00+09:00'), CAL) == \
        {'kr': '2026-11-23', 'us': '2026-11-20'}


def test_late_scheduled_run_gets_the_same_sessions_as_an_on_time_one():
    # 11-19 예약분이 11-20 02:37 KST 에 돌았다(실제). KR 11-19, MU 11-18 — 11-19 미국 장중 아님
    assert F.sessions(at('2026-11-20T02:37:25+09:00'), CAL) == \
        {'kr': '2026-11-19', 'us': '2026-11-18'}


def test_before_kr_close_is_the_previous_kr_session():
    assert F.sessions(at('2026-11-24T15:59:00+09:00'), CAL)['kr'] == '2026-11-23'


def test_saturday_is_friday_with_thursday_us():
    # 금 예약분이 토 02:13 KST 에 돌았다(11-21 실제) — 주말 건너뛰기로 버려지던 실행
    assert F.sessions(at('2026-11-21T02:13:29+09:00'), CAL) == \
        {'kr': '2026-11-20', 'us': '2026-11-19'}
    assert F.sessions(at('2026-11-22T16:00:00+09:00'), CAL) == \
        {'kr': '2026-11-20', 'us': '2026-11-19'}


def test_holidays_step_back():
    assert F.sessions(at('2026-10-09T17:00:00+09:00'), CAL)['kr'] == '2026-10-08'
    # 미국 추수감사절(목) 다음 금요일 KR 세션의 짝은 수요일
    assert F.sessions(at('2026-11-27T16:30:00+09:00'), CAL) == \
        {'kr': '2026-11-27', 'us': '2026-11-25'}


def test_calendar_past_valid_through_refuses():
    with pytest.raises(F.CalendarGap):
        F.sessions(at('2028-01-03T16:30:00+09:00'), CAL)


# ── 봉 자르기·확정 관측 ──────────────────────────────────────────────

def test_bars_after_the_session_are_dropped():
    dates = ['2026-11-18', '2026-11-19', '2026-11-20']
    assert F.keep_upto(dates, '2026-11-19') == [True, True, False]


def test_confirmed_needs_observation_after_that_session_closed():
    mu = {'price_date': '2026-11-19', 'observed_at': '2026-11-20T02:37:25+09:00'}
    assert not F.confirmed(mu, 'us')            # 11-19 12:37 ET — 장중
    mu['observed_at'] = '2026-11-20T16:05:00+09:00'
    assert F.confirmed(mu, 'us')
    assert not F.confirmed({'price_date': '2026-11-19'}, 'us')   # 옛 꼴


# ── 종목별 단조 병합 ─────────────────────────────────────────────────

def test_merge_keeps_a_later_confirmed_price():
    # 11-16 20:04 KST 수동 수집이 KR 11-16 을 받았고, 뒤의 예약분(11-17 03:52)은 11-13 만 받았다
    old = {'price': 196800.0, 'price_date': '2026-11-16',
           'observed_at': '2026-11-16T20:04:52+09:00', 'chg_20d_pct': -1.0,
           'pct_from_52w_high': -30.0}
    new = {'price': 206000.0, 'price_date': '2026-11-13',
           'observed_at': '2026-11-17T03:52:25+09:00', 'chg_20d_pct': 2.0,
           'pct_from_52w_high': -27.0, 'eps_fy1': 1.0}
    out = F.merge_price(new, old, 'kr')
    assert (out['price'], out['price_date'], out['chg_20d_pct']) == (196800.0, '2026-11-16', -1.0)
    assert out['eps_fy1'] == 1.0                 # 컨센서스는 늘 새 관측


def test_merge_ignores_old_unconfirmed_price():
    old = {'price': 707.29, 'price_date': '2026-11-19'}           # 전환 전 장중 MU
    new = {'price': 705.27, 'price_date': '2026-11-18',
           'observed_at': '2026-11-23T16:05:00+09:00'}
    assert F.merge_price(new, old, 'us')['price'] == 705.27


def test_derive_recomputes_ratios_from_the_merged_price():
    row = {'price': 200.0, 'bvps': 100.0, 'eps_fy1': 50.0, 'pb': 9.9, 'pe_fy1': 9.9}
    F.derive(row)
    assert (row['pb'], row['pe_fy1']) == (2.0, 4.0)


# ── stale·신선도 ────────────────────────────────────────────────────

def tickers(kr_date='2026-11-23', us_date='2026-11-20',
            seen='2026-11-23T16:05:00+09:00'):
    return {'005930.KS': {'price_date': kr_date, 'observed_at': seen},
            '000660.KS': {'price_date': kr_date, 'observed_at': seen},
            'MU': {'price_date': us_date, 'observed_at': seen}}


SESS = {'kr': '2026-11-23', 'us': '2026-11-20'}


def test_stale_names_each_ticker_off_its_market_session():
    assert F.stale(tickers(), SESS) == []
    reasons = F.stale(tickers(kr_date='2026-11-20'), SESS)
    assert len(reasons) == 2 and all('2026-11-23' in r for r in reasons)
    assert len(F.stale(tickers(us_date='2026-11-19'), SESS)) == 1


def watch(**over):
    base = {'as_of': '2026-11-23', 'complete': True, 'missing': [], 'stale': [],
            'collected_at': '2026-11-23T16:05:00+09:00', 'tickers': tickers()}
    base.update(over)
    return base


NOW = at('2026-11-23T16:20:00+09:00')


def test_fresh_watch_passes():
    assert F.check(NOW, watch(), CAL) == []


def test_the_real_2026_11_20_snapshot_is_stale():
    # 11-20 02:37 KST 수집판(as_of 11-20, KR 11-18, MU 11-19 장중)을 11-20 16:00 에 읽었다
    w = watch(as_of='2026-11-20', collected_at='2026-11-20T02:37:25+09:00',
              tickers={'005930.KS': {'price_date': '2026-11-18'},
                       '000660.KS': {'price_date': '2026-11-18'},
                       'MU': {'price_date': '2026-11-19'}})
    reasons = F.check(at('2026-11-20T16:00:00+09:00'), w, CAL)
    assert any('005930.KS' in r and '2026-11-20' in r for r in reasons)
    assert any('MU' in r and '마감 전' in r for r in reasons)
    assert any('수집 시각' in r for r in reasons)


def test_old_collection_is_stale_even_with_right_sessions():
    w = watch(collected_at='2026-11-23T12:00:00+09:00')
    assert any('수집 시각' in r for r in F.check(NOW, w, CAL))


def test_incomplete_or_missing_watch_is_stale():
    assert F.check(NOW, None, CAL)
    assert F.check(NOW, watch(complete=False, missing=['MU']), CAL)


def test_calendar_gap_is_stale_not_a_crash():
    assert F.check(at('2028-01-03T16:30:00+09:00'), watch(), CAL)


def test_replay_now_is_that_day_at_publish_time():
    assert F.now_for('2026-11-20') == at('2026-11-20T16:00:00+09:00')


def test_refresh_picks_the_run_carrying_its_request_id():
    import thesis_refresh as R
    listing = [{'databaseId': 1, 'displayTitle': 'thesis collect (scheduled)'},
               {'databaseId': 2, 'displayTitle': 'thesis collect 4f2a9c01d3e7'},
               {'databaseId': 3, 'displayTitle': 'thesis collect 000000000000'}]
    assert R.pick_run(listing, '4f2a9c01d3e7') == 2
    assert R.pick_run(listing, 'ffffffffffff') is None
