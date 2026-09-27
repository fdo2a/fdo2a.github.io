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


# ── US ────────────────────────────────────────────────────────────────────────

NOW = utc(2026, 9, 26, 17, 30)          # 일 02:30 KST — 9/25 세션 재시도 시각
FRESH = utc(2026, 9, 26, 9, 59)         # 마감(금 16:00 ET = 20:00Z) 뒤 수집


def us(files, report_date='2026-09-25', complete=True, committed=FRESH, lock_age=None, now=NOW):
    return rd.decide_us(now, {'report_date': report_date, 'complete': complete}, committed,
                        set(files), lock_age)[0]


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


def test_us_data_still_on_yesterday_is_due_not_done():
    """수집이 밀린 날: 어제 글이 있다고 DONE 이면 오늘 글이 영영 안 나온다(codex #1)."""
    got = us({'posts/2026-09-24.html', 'news/2026-09-24.html'}, report_date='2026-09-24',
             committed=utc(2026, 9, 25, 9, 0))      # 금 05:00 ET — 금요일 마감 전 수집
    assert got == 'DUE'


def test_us_holiday_is_done():
    """마감 한참 뒤에 수집했는데도 데이터가 전 세션이면 휴장이다."""
    got = us({'posts/2026-09-24.html', 'news/2026-09-24.html'}, report_date='2026-09-24')
    assert got == 'DONE'


def test_us_incomplete_data_is_due_because_step0_recollects():
    assert us(set(), complete=False) == 'DUE'


# ── KR ────────────────────────────────────────────────────────────────────────

KNOW = utc(2026, 9, 25, 12, 0)          # 금 21:00 KST


def kr(files, report_date='2026-09-25', complete=True, committed=utc(2026, 9, 25, 9, 12),
       lock_age=None):
    return rd.decide_kr(KNOW, {'report_date': report_date, 'complete': complete}, committed,
                        set(files), lock_age)[0]


def test_kr_published_is_done():
    assert kr({'kr/posts/2026-09-25.html'}) == 'DONE'


def test_kr_missing_is_due():
    assert kr(set()) == 'DUE'


def test_kr_chuseok_is_done():
    """9/25 는 추석 휴장 — 18:12 KST 수집기 커밋이 여전히 9/23 이면 할 일이 없다."""
    assert kr({'kr/posts/2026-09-23.html'}, report_date='2026-09-23',
              committed=utc(2026, 9, 25, 9, 12)) == 'DONE'


def test_kr_collection_just_after_close_is_not_yet_a_holiday():
    """마감 직후 소스 지연을 휴장으로 오판하면 그날 글이 빠진다."""
    assert kr({'kr/posts/2026-09-24.html'}, report_date='2026-09-24',
              committed=utc(2026, 9, 25, 7, 40)) == 'DUE'


def test_kr_collection_before_close_is_due():
    assert kr({'kr/posts/2026-09-24.html'}, report_date='2026-09-24',
              committed=utc(2026, 9, 25, 3, 0)) == 'DUE'


def test_kr_busy():
    assert kr(set(), lock_age=10) == 'BUSY'


# ── 주간 ──────────────────────────────────────────────────────────────────────

def weekly(files, us_agg=True, kr_agg=True, lock_age=None):
    aggs = {'us': {'complete': True} if us_agg else None,
            'kr': {'complete': True} if kr_agg else None}
    if us_agg == 'partial':
        aggs['us'] = {'complete': False}
    return rd.decide_weekly('2026-W39', aggs, set(files), lock_age)[0]


def test_weekly_both_published_is_done():
    assert weekly({'weekly/2026-W39.html', 'kr/weekly/2026-W39.html'}) == 'DONE'


def test_weekly_one_missing_is_due():
    assert weekly({'weekly/2026-W39.html'}) == 'DUE'


def test_weekly_incomplete_aggregate_waits():
    """주간 루틴은 집계를 다시 만들지 않는다 — 돌려도 같은 자리에서 멈춘다(codex #2)."""
    assert weekly(set(), us_agg='partial') == 'WAIT'
    assert weekly(set(), kr_agg=False) == 'WAIT'


def test_weekly_busy():
    assert weekly(set(), lock_age=5) == 'BUSY'


# ── 잠금 이름은 루틴이 잡는 이름과 같아야 한다 ────────────────────────────────

def test_lock_names_match_run_lock_rules():
    assert rd.lock_name('us', utc(2026, 9, 26, 17, 30)) == 'us-2026-09-25'
    assert rd.lock_name('kr', utc(2026, 9, 25, 12, 0)) == 'kr-2026-09-25'
    assert rd.lock_name('weekly', None, key='2026-W39') == 'weekly-2026-W39'
