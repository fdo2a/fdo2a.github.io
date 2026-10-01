"""재시도 루틴의 첫 단계 — 모델 없이 「지금 돌 일이 있는가」를 판정한다 (2026-09-27).

9/25 US 런이 브리프를 발행한 1분 뒤 5시간 한도로 죽었고, 뉴스·산업 브리프를 다시 띄울 장치가
없었다. 재시도 루틴이 3시간마다 뜨되, 할 일이 없으면 오케스트레이터를 읽기도 전에 끝나야 한다.
판정이 틀리는 방향은 둘이다 — 할 일이 있는데 DONE(글이 영영 안 나온다), 할 일이 없는데
DUE(토큰을 태운다). 앞쪽이 훨씬 비싸다.
"""
from datetime import datetime, timezone
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location(
    'routine_due', os.path.join(HERE, '..', '..', 'ci', 'routine_due.py'))
rd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rd)


def utc(*a):
    return datetime(*a, tzinfo=timezone.utc)


# ── 기대 세션 ─────────────────────────────────────────────────────────────────

def test_us_session_is_new_york_minus_17h():
    # 토 08:30 KST 본 런 = 금 19:30 ET → 금요일 세션
    assert rd.us_session(utc(2026, 9, 25, 23, 30)) == '2026-09-25'
    # 일 05:30 KST 마지막 재시도 = 토 16:30 ET → 여전히 금요일
    assert rd.us_session(utc(2026, 9, 26, 20, 30)) == '2026-09-25'


def test_us_session_on_a_weekend_falls_back_to_friday():
    assert rd.us_session(utc(2026, 9, 27, 23, 30)) == '2026-09-25'   # 일 19:30 ET


def test_kr_session_is_seoul_minus_16h():
    assert rd.kr_session(utc(2026, 9, 25, 9, 0)) == '2026-09-25'     # 금 18:00 KST
    assert rd.kr_session(utc(2026, 9, 26, 6, 0)) == '2026-09-25'     # 토 15:00 KST
    assert rd.kr_session(utc(2026, 9, 27, 6, 0)) == '2026-09-25'     # 일 → 금


# ── 휴장 달력 ─────────────────────────────────────────────────────────────────

import json  # noqa: E402

ROOT = os.path.join(HERE, '..', '..', '..')
CAL = json.load(open(os.path.join(ROOT, 'data', 'market_holidays.json'), encoding='utf-8'))
US_HOL, KR_HOL = tuple(CAL['us']['dates']), tuple(CAL['kr']['dates'])


def test_holiday_calendar_has_no_weekends_and_is_sorted():
    from datetime import date
    for m in ('us', 'kr'):
        days = CAL[m]['dates']
        assert days == sorted(set(days))
        assert all(date.fromisoformat(d).weekday() < 5 for d in days)


def test_kr_chuseok_moves_the_session_back_to_the_last_trading_day():
    """9/24·25 추석 — 금 21:00 KST 의 기대 세션은 9/23 이다."""
    assert rd.kr_session(utc(2026, 9, 25, 12, 0), KR_HOL) == '2026-09-23'


def test_us_independence_day_observed():
    assert rd.us_session(utc(2026, 7, 3, 23, 30), US_HOL) == '2026-07-02'


# ── US ────────────────────────────────────────────────────────────────────────

NOW = utc(2026, 9, 26, 17, 30)          # 일 02:30 KST — 9/25 세션 재시도 시각


def us(files, lock_age=None, now=NOW, hol=US_HOL):
    return rd.decide_us(now, set(files), lock_age, hol)[0]


def test_us_both_articles_published_is_done():
    assert us({'posts/2026-09-25.html', 'news/2026-09-25.html'}) == 'DONE'


def test_us_brief_without_news_is_due():
    """9/25 의 실제 상태다."""
    assert us({'posts/2026-09-25.html'}) == 'DUE'


def test_us_nothing_published_is_due():
    assert us(set()) == 'DUE'


def test_us_live_lock_for_that_session_is_busy():
    assert us(set(), lock_age=30) == 'BUSY'


def test_us_stale_lock_is_left_to_acquire():
    assert us(set(), lock_age=200) == 'DUE'


def test_us_yesterdays_articles_do_not_make_today_done():
    """수집이 밀리거나 시세가 늦게 붙은 거래일 — 어제 글로 DONE 이면 오늘 글이 빠진다(codex #1·#2)."""
    assert us({'posts/2026-09-24.html', 'news/2026-09-24.html'}) == 'DUE'


def test_us_unlisted_holiday_errs_toward_due():
    """달력에 없는 휴장일은 헛도는 재시도로 끝난다 — 글이 빠지는 쪽으로 틀리지 않는다."""
    assert us({'posts/2026-09-24.html', 'news/2026-09-24.html'}, hol=()) == 'DUE'


def test_us_listed_holiday_is_done_when_the_prior_session_is_published():
    labor = utc(2026, 9, 8, 2, 30)       # 9/7 노동절 다음날 11:30 KST → 기대 세션 9/4(금)
    assert us({'posts/2026-09-04.html', 'news/2026-09-04.html'}, now=labor) == 'DONE'


# ── KR ────────────────────────────────────────────────────────────────────────

def kr(files, now=utc(2026, 9, 23, 12, 0), lock_age=None):
    return rd.decide_kr(now, set(files), lock_age, KR_HOL)[0]


def test_kr_published_is_done():
    assert kr({'kr/posts/2026-09-23.html'}) == 'DONE'


def test_kr_missing_is_due():
    assert kr(set()) == 'DUE'


def test_kr_chuseok_is_done():
    assert kr({'kr/posts/2026-09-23.html'}, now=utc(2026, 9, 25, 12, 0)) == 'DONE'


def test_kr_busy():
    assert kr(set(), lock_age=10) == 'BUSY'


# ── 주간 ──────────────────────────────────────────────────────────────────────

def test_week_key_comes_from_the_calendar_not_the_data():
    """금요일 수집이 실패해 데이터가 지난주에 머물러도 키는 이번 주다(codex #4)."""
    assert rd.week_of(utc(2026, 9, 26, 9, 0), US_HOL) == '2026-W39'


def test_week_key_when_friday_is_a_holiday():
    assert rd.week_of(utc(2026, 4, 4, 9, 0), US_HOL) == '2026-W14'   # 4/3 성금요일


def weekly(files, us_agg=True, kr_agg=True, lock_age=None):
    def agg(v):
        return None if v is None else {'complete': v}
    return rd.decide_weekly('2026-W39', {'us': agg(us_agg), 'kr': agg(kr_agg)},
                            set(files), lock_age)[0]


def test_weekly_both_published_is_done():
    assert weekly({'weekly/2026-W39.html', 'kr/weekly/2026-W39.html'}) == 'DONE'


def test_weekly_one_missing_is_due():
    assert weekly({'weekly/2026-W39.html'}) == 'DUE'


def test_weekly_incomplete_aggregate_waits():
    """주간 루틴은 집계를 다시 만들지 않는다 — 돌려도 같은 자리에서 멈춘다(codex #2)."""
    assert weekly(set(), us_agg=False) == 'WAIT'
    assert weekly(set(), kr_agg=None) == 'WAIT'


def test_weekly_published_side_needs_no_aggregate():
    """이미 나간 쪽 집계가 없다고 남은 쪽을 막지 않는다(codex #6)."""
    assert weekly({'weekly/2026-W39.html'}, us_agg=None) == 'DUE'


def test_weekly_busy():
    assert weekly(set(), lock_age=5) == 'BUSY'


# ── 잠금 이름은 루틴이 잡는 이름과 같아야 한다 ────────────────────────────────

def test_lock_names_match_run_lock_rules():
    assert rd.lock_name('us', utc(2026, 9, 26, 17, 30), holidays=US_HOL) == 'us-2026-09-25'
    assert rd.lock_name('kr', utc(2026, 9, 23, 12, 0), holidays=KR_HOL) == 'kr-2026-09-23'
    assert rd.lock_name('weekly', None, key='2026-W39') == 'weekly-2026-W39'


def test_one_session_one_lock_across_a_holiday():
    """추석 사흘 동안 9/23 세션을 처리하는 런은 모두 같은 잠금을 잡는다(구현 재검토 #1)."""
    runs = [utc(2026, 9, 24, 9, 0), utc(2026, 9, 25, 6, 0), utc(2026, 9, 25, 12, 0),
            utc(2026, 9, 26, 6, 0), utc(2026, 9, 26, 12, 0)]
    assert {rd.lock_name('kr', t, holidays=KR_HOL) for t in runs} == {'kr-2026-09-23'}
