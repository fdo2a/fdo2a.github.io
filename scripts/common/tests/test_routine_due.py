"""재시도 루틴의 첫 단계 — 모델 없이 「지금 돌 일이 있는가」를 판정한다 (2026-09-27).

9/25 US 런이 브리프를 발행한 1분 뒤 5시간 한도로 죽었고, 뉴스·산업 브리프를 다시 띄울 장치가
없었다. 재시도 루틴이 3시간마다 뜨되, 할 일이 없으면 오케스트레이터를 읽기도 전에 끝나야 한다.
판정이 틀리는 방향은 둘이다 — 할 일이 있는데 DONE(글이 영영 안 나온다), 할 일이 없는데
DUE(토큰을 태운다). 앞쪽이 훨씬 비싸다.
"""
from datetime import date, datetime, timezone
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
    for m in ('us', 'kr', 'jp'):
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


# ── 월간 (2026-10-27 codex 설계 검토) ────────────────────────────────────────

def monthly(files=(), today=date(2026, 11, 3), us_rd='2026-11-02', kr_rd='2026-11-02',
            us_end='2026-10-30', kr_end='2026-10-30', us_ok=True, kr_ok=True,
            us_n=22, kr_n=20):
    # 2026-10: 평일 22일, US 휴장 없음 · KR 10/05 대체공휴일·10/09 한글날
    def agg(end, ok, n):
        return None if end is None else {'end_date': end, 'complete': ok, 'sessions': n}
    return rd.decide_monthly(today, {'us': us_rd, 'kr': kr_rd},
                             {'us': agg(us_end, us_ok, us_n), 'kr': agg(kr_end, kr_ok, kr_n)},
                             set(files), {'us': US_HOL, 'kr': KR_HOL})


def test_monthly_key_is_the_closed_month_not_the_report_date_month():
    """report_date 가 11/02 라도 KEY 는 10월이다 — month_key(report_date) 는 2026-11 을 냈다."""
    assert monthly() == ('DUE', '2026-10', 'us,kr')


def test_monthly_resumes_the_market_that_did_not_publish():
    """US 만 나간 달에 KR 을 이어받는다 — 예전 STEP 0 은 US 글만 보고 영구히 끝냈다."""
    assert monthly({'monthly/2026-10.html'}) == ('DUE', '2026-10', 'kr')
    assert monthly({'kr/monthly/2026-10.html'}) == ('DUE', '2026-10', 'us')


def test_monthly_both_published_is_done():
    assert monthly({'monthly/2026-10.html', 'kr/monthly/2026-10.html'})[0] == 'DONE'


def test_monthly_waits_until_that_market_data_crosses_the_month():
    """11/02 09:30 KST 의 US 데이터는 10/30 — 9월로 소급하지 않고 기다린다."""
    v = monthly(today=date(2026, 11, 2), us_rd='2026-10-30', kr_rd='2026-10-30')
    assert v[:2] == ('WAIT', '2026-10')
    # KR 만 남았으면 US 데이터가 밀린 것은 상관없다
    assert monthly({'monthly/2026-10.html'}, us_rd='2026-10-30')[:3] == ('DUE', '2026-10', 'kr')


def test_monthly_blocks_when_the_aggregate_stopped_before_month_end():
    """월말 수집이 실패하고 새 달 수집만 성공하면 집계가 10/26 에 멈춘 채 complete 다(codex #1)."""
    v = monthly(us_end='2026-10-26')
    assert v[0] == 'BLOCKED' and 'us' in v[2]


def test_monthly_blocks_on_missing_or_incomplete_aggregate():
    assert monthly(kr_end=None)[0] == 'BLOCKED'
    assert monthly(kr_ok=False)[0] == 'BLOCKED'


def test_monthly_blocks_when_sessions_are_missing_inside_the_month():
    """10/30 하루만 본 집계도 end_date 는 맞고 complete 다 — 거래일 수로 잡는다(codex 구현 검토 #1)."""
    v = monthly(kr_n=1)
    assert v[0] == 'BLOCKED' and 'kr' in v[2]


def test_monthly_published_kr_side_needs_no_aggregate():
    assert monthly({'kr/monthly/2026-10.html'}, kr_end=None, kr_rd=None)[:3] == ('DUE', '2026-10', 'us')


def test_monthly_kr_resume_still_needs_the_us_aggregate_for_the_scorecard():
    """STEP 3 스코어카드는 US 집계로 만든다 — KR 만 남아도 US 집계가 없으면 STEP 3 이 죽는다(구현 검토 #2)."""
    assert monthly({'monthly/2026-10.html'}, us_end=None, us_rd=None)[0] == 'BLOCKED'
    # US report_date 가 밀린 것은 KR 재개를 막지 않는다
    assert monthly({'monthly/2026-10.html'}, us_rd='2026-10-30')[:3] == ('DUE', '2026-10', 'kr')


def test_monthly_last_trading_day_follows_the_holiday_calendar():
    """KR 12/31 은 휴장 — 12월 집계는 12/30 에 끝나야 맞다."""
    v = monthly(today=date(2027, 1, 5), us_rd='2027-01-04', kr_rd='2027-01-04',
                us_end='2026-12-31', kr_end='2026-12-30', us_n=22, kr_n=21)
    assert v == ('DUE', '2026-12', 'us,kr')


def test_monthly_session_count_matches_the_real_september_aggregates():
    """실제 9월 집계(US 21·KR 20 — 노동절, 추석 9/24·25)가 달력 거래일 수와 맞는다."""
    aggs = {m: json.load(open(os.path.join(ROOT, p), encoding='utf-8'))
            for m, p in (('us', 'data/monthly/2026-09.json'), ('kr', 'kr/data/monthly/2026-09.json'))}
    assert rd.decide_monthly(date(2026, 10, 27), {'us': '2026-10-26', 'kr': '2026-10-27'}, aggs,
                             set(), {'us': US_HOL, 'kr': KR_HOL}) == ('DUE', '2026-09', 'us,kr')


def test_monthly_orchestrator_uses_the_step0_key_to_the_end():
    """STEP 0-b 가 report_date 로 KEY 를 다시 만들면 결함 1 이 돌아온다."""
    doc = open(os.path.join(ROOT, '.claude', 'MONTHLY_ORCHESTRATOR.md'), encoding='utf-8').read()
    assert 'routine_due.py monthly' in doc
    assert 'month_key(' not in doc
    assert 'kr/monthly/<KEY>.html' in doc      # 시장별 완료 판정


def test_monthly_cli_turns_git_errors_into_blocked(monkeypatch, capsys):
    """git 시간 초과가 판정 한 줄 없이 터지면 BLOCKED 알림 경로를 건너뛴다(구현 검토 #4)."""
    import subprocess

    def boom(*a, **k):
        raise subprocess.TimeoutExpired('git', 60)
    monkeypatch.setattr(rd, '_git', boom)
    assert rd.main(['monthly']) == 0
    assert capsys.readouterr().out.startswith('BLOCKED ')


def test_monthly_cli_reads_the_pulled_head_not_a_fresh_fetch(monkeypatch):
    """판정과 작성이 같은 커밋을 읽어야 한다 — fetch 한 origin/main 은 작업 트리와 다를 수 있다(구현 검토 #3)."""
    calls = []

    def fake(*a, **k):
        calls.append(a)
        return subprocess_result()
    monkeypatch.setattr(rd, '_git', fake)
    rd.main(['monthly'])
    assert not any(c[0] == 'fetch' for c in calls)
    assert not any('origin/main' in ' '.join(c) for c in calls)


def subprocess_result(code=1, out=''):
    class R:
        returncode, stdout = code, out
    return R()


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


# ── 일본 주간 ─────────────────────────────────────────────────────────────────

def test_japan_key_is_the_week_of_the_last_friday_before_today():
    """발행일은 MOF 가 금요일 커브를 올리는 다음 도쿄 영업일(보통 월, 휴일이면 그 뒤)이다."""
    assert rd.japan_key(utc(2026, 10, 4, 1, 0)) == '2026-W40'     # 일 10:00 KST
    assert rd.japan_key(utc(2026, 10, 5, 4, 0)) == '2026-W40'     # 월 13:00 KST
    assert rd.japan_key(utc(2026, 10, 13, 13, 0)) == '2026-W41'   # 화 22:00 KST (월 체육의 날)
    assert rd.japan_key(utc(2026, 10, 9, 4, 0)) == '2026-W40'     # 금 13:00 KST — 그 주 금요일은 아직이다
    assert rd.japan_key(utc(2026, 10, 10, 4, 0)) == '2026-W41'    # 토


def test_japan_post_day_is_the_tokyo_business_day_after_friday():
    assert rd.japan_post_day('2026-W40', ()).isoformat() == '2026-10-05'
    assert rd.japan_post_day('2026-W41', ('2026-10-12',)).isoformat() == '2026-10-13'
    # 금요일이 휴장이면 그 주 마지막 거래일(목)의 다음 영업일 — 같은 월요일
    assert rd.japan_post_day('2026-W40', ('2026-10-02',)).isoformat() == '2026-10-05'


def test_japan_waits_until_the_post_day():
    hol = ('2026-10-12',)
    assert rd.decide_japan('2026-W41', set(), None, date(2026, 10, 12), hol)[0] == 'WAIT'
    assert rd.decide_japan('2026-W41', set(), None, date(2026, 10, 13), hol)[0] == 'DUE'
    assert rd.decide_japan('2026-W40', set(), None, date(2026, 10, 4), ())[0] == 'WAIT'
    assert rd.decide_japan('2026-W40', {'japan/posts/2026-W40.html'}, None, date(2026, 10, 4), ())[0] == 'DONE'


def test_japan_done_busy_due():
    today = date(2026, 10, 5)
    assert rd.decide_japan('2026-W40', {'japan/posts/2026-W40.html'}, None, today, ())[0] == 'DONE'
    assert rd.decide_japan('2026-W40', set(), 30, today, ())[0] == 'BUSY'
    assert rd.decide_japan('2026-W40', set(), 300, today, ())[0] == 'DUE'
    assert rd.lock_name('japan', None, key='2026-W40') == 'japan-2026-W40'
