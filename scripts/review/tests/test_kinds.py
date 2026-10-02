"""글 종류 표 — 주간·월간·일본도 발행 뒤 codex 문체 수정을 받는다 (2026-10-01 사용자 지시).

주·월 키는 파일명에 날짜가 없어서 러너의 신선도 필터가 통째로 건너뛰었다.
"""
from datetime import date

from review import kinds
from review.queue import Pending
from review.runner import draft_name, eligible


def test_publish_day_of_each_kind():
    assert kinds.publish_day('weekly/2026-W39.html') == date(2026, 9, 26)        # 토
    assert kinds.publish_day('kr/weekly/2026-W39.html') == date(2026, 9, 26)
    assert kinds.publish_day('japan/posts/2026-W39.html') == date(2026, 9, 27)   # 일
    assert kinds.publish_day('monthly/2026-09.html') == date(2026, 10, 1)
    assert kinds.publish_day('kr/monthly/2026-12.html') == date(2027, 1, 1)
    assert kinds.publish_day('posts/2026-09-30.html') == date(2026, 9, 30)
    assert kinds.publish_day('weekly/index.html') is None


def test_evidence_files_per_kind():
    assert kinds.evidence('weekly', '2026-W39') == (
        'data/weekly/2026-W39.json', 'data/weekly_ext/2026-W39.insight.json',
        'recap_us.json', 'data/period_scorecard.json')
    assert kinds.evidence('kr/monthly', '2026-09') == (
        'kr/data/monthly/2026-09.json', 'recap_kr.json', 'data/period_scorecard.json')
    assert kinds.evidence('japan/posts', '2026-W40') == (
        'japan/data/2026-W40.json', 'japan/data/2026-W40.news.json')


def item(path, section, sha='a' * 40):
    return Pending(path=path, section=section, sha=sha, reason='신규')


def test_period_items_are_picked_within_their_window():
    q = [item('weekly/2026-W39.html', 'weekly'), item('japan/posts/2026-W39.html', 'japan/posts'),
         item('monthly/2026-09.html', 'monthly')]
    pub = {i.path: i.sha for i in q}
    got = {i.path for i in eligible(q, pub, {}, '2026-09-29')}
    assert {'weekly/2026-W39.html', 'japan/posts/2026-W39.html'} <= got
    got = {i.path for i in eligible(q, pub, {}, '2026-10-07')}
    assert got == {'monthly/2026-09.html'}                                 # 주간은 3일 지남


def test_daily_window_is_unchanged():
    q = [item('posts/2026-09-28.html', 'us')]
    assert eligible(q, {q[0].path: q[0].sha}, {}, '2026-09-30') == []


def test_period_draft_names_carry_the_publish_day():
    assert draft_name(item('kr/weekly/2026-W39.html', 'kr/weekly')).startswith('2026-09-26-kr_weekly-')


def test_freshness_follows_the_actual_publish_date_when_given():
    """codex 구현 검토: US W39 는 키 날짜(9/26)보다 5일 늦은 10/01 에 발행됐다 — 키로만 재면 영영 못 집는다."""
    w39 = item('weekly/2026-W39.html', 'weekly')
    pub = {w39.path: w39.sha}
    assert eligible([w39], pub, {}, '2026-10-01') == []
    assert eligible([w39], pub, {}, '2026-10-01', dated={w39.path: date(2026, 10, 1)}) == [w39]
    assert draft_name(w39).startswith('2026-09-26-weekly-')   # 이름은 키 날짜 그대로
