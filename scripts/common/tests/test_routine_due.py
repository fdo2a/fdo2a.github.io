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


# KR 뉴스 글(2026-11-06 부터) — 실을 기사가 있는 날만 둘째 글을 기다린다
NOV6 = utc(2026, 11, 6, 12, 0)       # 21:00 KST 금요일 → 세션 11/06


def test_kr_news_post_is_awaited_after_the_split_when_there_is_news():
    got = rd.decide_kr(NOV6, {'kr/posts/2026-11-06.html'}, None, KR_HOL, lambda d: True)
    assert got[0] == 'DUE' and 'kr/news/2026-11-06.html' in got[1]
    assert rd.decide_kr(NOV6, {'kr/posts/2026-11-06.html', 'kr/news/2026-11-06.html'}, None, KR_HOL,
                        lambda d: True)[0] == 'DONE'


def test_kr_news_post_is_not_awaited_without_news_or_before_the_split():
    assert rd.decide_kr(NOV6, {'kr/posts/2026-11-06.html'}, None, KR_HOL, lambda d: False)[0] == 'DONE'
    assert rd.decide_kr(utc(2026, 11, 5, 12, 0), {'kr/posts/2026-11-05.html'}, None, KR_HOL,
                        lambda d: True)[0] == 'DONE'


def test_kr_news_expected_reads_the_collected_file():
    assert rd.kr_news_expected({'items': [{'category': 'politics', 'summary_ko': '요약'}]})
    assert not rd.kr_news_expected({'items': [{'category': 'market', 'summary_ko': '요약'}]})
    assert not rd.kr_news_expected({'items': [{'category': 'macro'}]})
    assert not rd.kr_news_expected(None) and not rd.kr_news_expected([])


# ── 주간 ──────────────────────────────────────────────────────────────────────

def test_week_key_comes_from_the_calendar_not_the_data():
    """금요일 수집이 실패해 데이터가 지난주에 머물러도 키는 이번 주다(codex #4)."""
    assert rd.week_of(utc(2026, 9, 26, 9, 0), US_HOL) == '2026-W39'


def test_week_key_when_friday_is_a_holiday():
    assert rd.week_of(utc(2026, 4, 4, 9, 0), US_HOL) == '2026-W14'   # 4/3 성금요일


SAT = utc(2026, 9, 26, 9, 0)             # 토 18:00 KST — W39 두 시장 마지막 거래일이 다 닫힌 뒤
W39_END = {'us': '2026-09-25', 'kr': '2026-09-23'}      # KR 은 9/24·25 추석


def cal_of(us=US_HOL, kr=KR_HOL, us_through=None, kr_through=None):
    return {'us': (us, us_through or CAL['us']['valid_through']),
            'kr': (kr, kr_through or CAL['kr']['valid_through'])}


def agg(end, complete=True):
    return {'complete': complete, 'end_date': end}


def weekly(files, us_agg=True, kr_agg=True, lock_age=None, now=SAT, key='2026-W39', end=W39_END, cal=None):
    def one(m, v):
        return None if v is None else agg(end[m], v)
    return rd.decide_weekly(key, {'us': one('us', us_agg), 'kr': one('kr', kr_agg)},
                            set(files), lock_age, now, cal or cal_of())[0]


def test_weekly_both_published_is_done():
    assert weekly({'weekly/2026-W39.html', 'kr/weekly/2026-W39.html'}) == 'DONE'


def test_weekly_one_missing_is_due():
    assert weekly({'weekly/2026-W39.html'}) == 'DUE'


def test_weekly_saturday_after_the_close_is_due():
    assert weekly(set()) == 'DUE'


def test_weekly_incomplete_aggregate_waits():
    """주간 루틴은 집계를 다시 만들지 않는다 — 돌려도 같은 자리에서 멈춘다(codex #2)."""
    assert weekly(set(), us_agg=False) == 'WAIT'
    assert weekly(set(), kr_agg=None) == 'WAIT'


def test_weekly_published_side_needs_no_aggregate():
    """이미 나간 쪽 집계가 없다고 남은 쪽을 막지 않는다(codex #6)."""
    assert weekly({'weekly/2026-W39.html'}, us_agg=None) == 'DUE'


def test_weekly_busy():
    assert weekly(set(), lock_age=5) == 'BUSY'


# ── 주 중간에는 DUE 를 내지 않는다 (2026-11-19) ────────────────────────────────

class _Clock(datetime):
    at = None

    @classmethod
    def now(cls, tz=None):
        return cls.at


W47_DONE = {'data/weekly/2026-W47.json': agg('2026-11-20'), 'kr/data/weekly/2026-W47.json': agg('2026-11-20')}
W47 = {'data/weekly/2026-W47.json': agg('2026-11-18'),            # 11/19 10:44 UTC 의 실제 집계
       'kr/data/weekly/2026-W47.json': agg('2026-11-19')}


def stub_main(monkeypatch, now, tree, published=(), fetch_ok=True, local=None):
    """main() 을 git 없이 돌린다. tree = origin/main 의 JSON, local = 작업 트리의 JSON(없으면 tree)."""
    import types
    _Clock.at = now
    monkeypatch.setattr(rd, 'datetime', _Clock)
    remote = dict(tree, **{'data/market_holidays.json': CAL})

    def git(*a):
        if a[0] == 'fetch':
            return types.SimpleNamespace(returncode=0 if fetch_ok else 1, stdout='', stderr='')
        if a[0] == 'ls-tree':
            return types.SimpleNamespace(returncode=0, stdout='\n'.join(published), stderr='')
        return types.SimpleNamespace(returncode=0, stdout='', stderr='')
    monkeypatch.setattr(rd, '_git', git)
    monkeypatch.setattr(rd, '_show_json', lambda path, ref='origin/main': remote.get(path))
    if hasattr(rd, '_tree_json'):
        monkeypatch.setattr(rd, '_tree_json', lambda path: (tree if local is None else local).get(path))


def run_main(capsys, *argv):
    code = rd.main(list(argv))
    return code, capsys.readouterr().out.strip()


def test_weekly_thursday_is_not_due_with_the_real_w47_aggregates(monkeypatch, capsys):
    """11/19(목) 10:44 UTC 강제 발화 — 집계는 둘 다 complete 인데 주가 끝나지 않았다. DUE 가 나오면
    루틴이 월-수(US)·월-목(KR) 집계로 주간을 발행한다."""
    stub_main(monkeypatch, utc(2026, 11, 19, 10, 44), W47)
    _, out = run_main(capsys, 'weekly')
    assert out.startswith('WAIT 2026-W47'), out
    assert '2026-11-20' in out                       # 기대한 마지막 거래일을 적는다


def test_weekly_waits_until_the_last_session_closes():
    """2027-W12 — 3/26 성금요일. 마지막 거래일은 목요일이고, 그 세션은 NY 17:00(21:00 UTC)에 닫힌다."""
    end = {'us': '2027-03-25', 'kr': '2027-03-26'}
    files = {'kr/weekly/2027-W12.html'}
    assert weekly(files, now=utc(2027, 3, 25, 20, 59), key='2027-W12', end=end) == 'WAIT'
    assert weekly(files, now=utc(2027, 3, 25, 21, 0), key='2027-W12', end=end) == 'DUE'


def test_weekly_end_date_must_be_the_last_trading_day():
    """금요일 수집이 실패하면 집계가 목요일에서 끝난다 — 토요일에도 발행하지 않는다."""
    verdict, why = rd.decide_weekly('2026-W47', {'us': agg('2026-11-19'), 'kr': agg('2026-11-20')},
                                    set(), None, utc(2026, 11, 21, 9, 0), cal_of())
    assert verdict == 'WAIT' and '2026-11-19' in why and '2026-11-20' in why and 'us' in why
    assert rd.decide_weekly('2026-W47', {'us': {'complete': True}, 'kr': agg('2026-11-20')},
                            set(), None, utc(2026, 11, 21, 9, 0), cal_of())[0] == 'WAIT'


def test_weekly_split_week_judges_only_the_unpublished_market():
    """W39 — KR 은 수요일(9/23), US 는 금요일(9/25)이 마지막 거래일이다."""
    thu = utc(2026, 9, 24, 9, 0)                     # 목 18:00 KST — KR 주는 끝났고 US 는 아니다
    assert weekly(set(), now=thu) == 'WAIT'
    assert weekly({'weekly/2026-W39.html'}, now=thu) == 'DUE'          # KR 만 남았다
    assert weekly({'kr/weekly/2026-W39.html'}, now=thu) == 'WAIT'      # US 만 남았다
    # 나간 쪽 집계가 엉뚱해도 남은 쪽 판정을 건드리지 않는다
    assert rd.decide_weekly('2026-W39', {'us': agg('2026-09-21', False), 'kr': agg('2026-09-23')},
                            {'weekly/2026-W39.html'}, None, thu, cal_of())[0] == 'DUE'


def test_weekly_lists_every_reason():
    verdict, why = rd.decide_weekly('2026-W47', {'us': agg('2026-11-18'), 'kr': None},
                                    set(), None, utc(2026, 11, 19, 10, 44), cal_of())
    assert verdict == 'WAIT' and 'us' in why and 'kr' in why and '집계' in why


def test_weekly_past_the_calendar_end_waits_loudly():
    """달력이 그 주 금요일을 덮지 못하면 추측하지 않는다 — 조용한 DUE 도, 이유 없는 WAIT 도 아니다."""
    cal = cal_of(kr=tuple(d for d in KR_HOL if d < '2027'), kr_through='2026-12-31')
    aggs = {'us': agg('2026-12-31'), 'kr': agg('2026-12-30')}
    verdict, why = rd.decide_weekly('2026-W53', aggs, set(), None, utc(2027, 1, 2, 9, 0), cal)
    assert verdict == 'WAIT' and '달력' in why and '2026-12-31' in why and 'kr' in why
    # US 달력은 덮는다 — KR 이 이미 나갔으면 US 는 그대로 판정한다
    assert rd.decide_weekly('2026-W53', aggs, {'kr/weekly/2026-W53.html'}, None,
                            utc(2027, 1, 2, 9, 0), cal)[0] == 'DUE'
    for through in (None, '', 20271231):
        assert rd.decide_weekly('2026-W53', aggs, set(), None, utc(2027, 1, 2, 9, 0),
                                cal_of(kr_through='x') | {'kr': (KR_HOL, through)})[0] == 'WAIT'


def test_weekly_year_end_week_with_the_real_calendar():
    """2026-W53 — 금요일이 2027-01-01. KR 은 12/31 연말 휴장까지 겹쳐 12/30 이 마지막 거래일이다."""
    aggs = {'us': agg('2026-12-31'), 'kr': agg('2026-12-30')}
    assert rd.decide_weekly('2026-W53', aggs, set(), None, utc(2027, 1, 2, 9, 0), cal_of())[0] == 'DUE'
    assert rd.decide_weekly('2026-W53', aggs, set(), None, utc(2026, 12, 31, 9, 0), cal_of())[0] == 'WAIT'


def test_kr_calendar_covers_2027():
    assert CAL['kr']['valid_through'] == '2027-12-31'
    assert '2027-01-01' in KR_HOL and '2027-12-31' in KR_HOL


def test_calendar_reader_returns_dates_and_a_normalised_end(monkeypatch):
    """날짜와 끝을 함께 돌려준다. 끝이 날짜가 아니면 None, 날짜면 YYYY-MM-DD 로 — `2027-W01-1` 은 날짜로
    읽히지만 글자로 비교하면 11월보다 「뒤」가 된다(codex 설계 4회차)."""
    def cal(kr):
        monkeypatch.setattr(rd, '_show_json', lambda path, ref='origin/main': {'kr': kr})
        return rd._calendar('kr')
    assert cal({'dates': ['2027-01-01'], 'valid_through': '2027-12-31'}) == (('2027-01-01',), '2027-12-31')
    assert cal({'dates': [], 'valid_through': '2027-W01-1'}) == ((), '2027-01-04')
    for bad in (None, '', 'x', 20271231):
        assert cal({'dates': [], 'valid_through': bad})[1] is None
    assert cal({'valid_through': '2027-12-31'}) == ((), None)          # dates 가 없으면 달력이 아니다
    assert cal('x') == ((), None) and cal(None) == ((), None)
    monkeypatch.setattr(rd, '_show_json', lambda path, ref='origin/main': None)
    monkeypatch.setattr(rd, '_tree_json', lambda path: None)
    assert rd._calendar('kr') == ((), None) and rd._holidays('kr') == ()


def test_weekly_with_an_expired_calendar_never_reads_as_ready(monkeypatch, capsys):
    """2028-01-08 — KR 달력이 2027-12-31 에서 끝난다. 집계가 멀쩡해도 DUE·READY 가 나오면 안 된다."""
    tree = {'data/weekly/2028-W01.json': agg('2028-01-07'), 'kr/data/weekly/2028-W01.json': agg('2028-01-07')}
    us28 = dict(CAL['us'], valid_through='2028-12-31')
    for argv in (['weekly'], ['weekly-ready', '2028-W01']):
        stub_main(monkeypatch, utc(2028, 1, 8, 9, 0), tree)
        monkeypatch.setattr(rd, '_show_json', lambda path, ref='origin/main':
                            dict(CAL, us=us28) if path.endswith('market_holidays.json') else tree.get(path))
        out = run_main(capsys, *argv)[1]
        assert out.startswith('WAIT 2028-W01') and 'kr 달력이 2027-12-31 에서 끝난다' in out, out
        assert 'us' not in out.replace('us·', '')


def test_weekly_fetch_failure_applies_the_same_rule_to_the_stale_ref(monkeypatch, capsys):
    """fetch 가 실패해도 무조건 DUE 가 아니다 — 가진 origin/main 으로 같은 규칙을 본다(codex 구현 1회차 B1-B3)."""
    stub_main(monkeypatch, utc(2026, 11, 19, 10, 44), W47, fetch_ok=False)
    out = run_main(capsys, 'weekly')[1]
    assert out.startswith('WAIT 2026-W47') and 'fetch 실패' in out
    stub_main(monkeypatch, utc(2026, 11, 21, 9, 0), W47_DONE, fetch_ok=False)
    assert run_main(capsys, 'weekly')[1].startswith('DUE 2026-W47 미발행')
    # 토요일이어도 집계가 없거나 주 끝까지 못 왔으면 DUE 가 아니다
    for tree in ({}, W47):
        stub_main(monkeypatch, utc(2026, 11, 21, 9, 0), tree, fetch_ok=False)
        assert run_main(capsys, 'weekly')[1].startswith('WAIT 2026-W47')
    # 가진 판에 두 글이 다 있으면 DONE 이다 — 주 중간이든 아니든 DUE 로 세션을 띄우지 않는다
    done = ['weekly/2026-W47.html', 'kr/weekly/2026-W47.html']
    stub_main(monkeypatch, utc(2026, 11, 19, 10, 44), W47, published=done, fetch_ok=False)
    assert run_main(capsys, 'weekly')[1].startswith('DONE 2026-W47')
    # 다른 종류는 그대로다
    stub_main(monkeypatch, utc(2026, 11, 19, 10, 44), W47, fetch_ok=False)
    assert run_main(capsys, 'us')[1].startswith('DUE fetch 실패')


# ── weekly-ready — 오케스트레이터 STEP 1 (잠금을 보지 않는다) ──────────────────

def test_weekly_ready_says_which_markets_remain(monkeypatch, capsys):
    stub_main(monkeypatch, utc(2026, 11, 21, 9, 0), W47_DONE)
    assert run_main(capsys, 'weekly-ready', '2026-W47') == (0, 'READY 2026-W47 us,kr')
    stub_main(monkeypatch, utc(2026, 11, 21, 9, 0), W47_DONE, published=['weekly/2026-W47.html'])
    assert run_main(capsys, 'weekly-ready', '2026-W47') == (0, 'READY 2026-W47 kr')
    stub_main(monkeypatch, utc(2026, 11, 21, 9, 0), W47_DONE,
              published=['weekly/2026-W47.html', 'kr/weekly/2026-W47.html'])
    assert run_main(capsys, 'weekly-ready', '2026-W47') == (0, 'DONE 2026-W47')


def test_weekly_ready_blocks_a_midweek_aggregate(monkeypatch, capsys):
    stub_main(monkeypatch, utc(2026, 11, 19, 10, 44), W47)
    code, out = run_main(capsys, 'weekly-ready', '2026-W47')
    assert code == 1 and out.startswith('WAIT 2026-W47')
    # 금요일 수집 실패 — 토요일인데 집계는 목요일까지
    stub_main(monkeypatch, utc(2026, 11, 21, 9, 0), W47)
    code, out = run_main(capsys, 'weekly-ready', '2026-W47')
    assert code == 1 and out.startswith('WAIT 2026-W47') and '2026-11-18' in out


def test_weekly_ready_reads_the_working_tree_aggregate(monkeypatch, capsys):
    """작성자가 읽는 것은 작업 트리의 집계다 — 원격이 완성본이어도 로컬이 옛 판이면 막는다."""
    stub_main(monkeypatch, utc(2026, 11, 21, 9, 0), W47_DONE, local=W47)
    assert run_main(capsys, 'weekly-ready', '2026-W47')[0] == 1
    stub_main(monkeypatch, utc(2026, 11, 21, 9, 0), W47, local=W47_DONE)
    assert run_main(capsys, 'weekly-ready', '2026-W47') == (0, 'READY 2026-W47 us,kr')


def test_weekly_ready_ignores_its_own_lock_and_takes_a_past_key(monkeypatch, capsys):
    """잠금을 쥔 런이 부른다. 키는 받은 그대로 — 주 키가 넘어간 뒤의 수동 복구가 이 길로 확인한다."""
    stub_main(monkeypatch, utc(2026, 11, 26, 9, 0), W47_DONE)          # 다음 주 목요일
    monkeypatch.setattr(rd, '_lock_age', lambda *a: 1)
    assert run_main(capsys, 'weekly-ready', '2026-W47') == (0, 'READY 2026-W47 us,kr')


def test_weekly_ready_fails_closed(monkeypatch, capsys):
    stub_main(monkeypatch, utc(2026, 11, 21, 9, 0), W47_DONE, fetch_ok=False)
    code, out = run_main(capsys, 'weekly-ready', '2026-W47')
    assert code == 1 and out.startswith('ERROR')
    stub_main(monkeypatch, utc(2026, 11, 21, 9, 0), {})                # 집계 파일이 없다
    assert run_main(capsys, 'weekly-ready', '2026-W47')[0] == 1
    stub_main(monkeypatch, utc(2026, 11, 21, 9, 0), W47_DONE)
    for bad in (['weekly-ready'], ['weekly-ready', '2026-11-20'], ['weekly-ready', '2026-W54'],
                ['weekly-ready', '2026-W47', 'x']):
        assert rd.main(bad) == 2
        capsys.readouterr()


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


def test_brief_news_input_reads_the_brief_publish_commit(tmp_path, monkeypatch):
    """발행 뒤 재수집이 뉴스 파일을 바꿔도 판정·입력은 브리프 발행 커밋의 판이다(codex 구현 검토 2026-11-06 #2·#3)."""
    import json as _j
    import subprocess as sp
    g = lambda *a: sp.run(['git', *a], cwd=tmp_path, check=True, capture_output=True)
    g('init', '-q'); g('config', 'user.email', 't@t'); g('config', 'user.name', 't')
    (tmp_path / 'kr/data/news').mkdir(parents=True); (tmp_path / 'kr/posts').mkdir(parents=True)
    f = tmp_path / 'kr/data/news/2026-11-06.json'
    f.write_text(_j.dumps({'items': [{'category': 'policy', 'summary_ko': '요약'}]}), encoding='utf-8')
    (tmp_path / 'kr/posts/2026-11-06.html').write_text('x', encoding='utf-8')
    g('add', '-A'); g('commit', '-qm', 'brief')
    f.write_text(_j.dumps({'items': []}), encoding='utf-8')
    g('add', '-A'); g('commit', '-qm', 're-collect')
    monkeypatch.chdir(tmp_path)
    assert rd.kr_news_expected(rd.brief_news_input('2026-11-06', ref='HEAD'))
    assert rd.brief_news_input('2026-11-07', ref='HEAD') is None
    # git 조회 실패는 「뉴스 없음」이 아니다 — 판정은 기다리는 쪽(codex 재확인 #2)
    import pytest as _p
    with _p.raises(rd.GitLookupError):
        rd.brief_news_input('2026-11-06', ref='no-such-ref')
    monkeypatch.setattr(rd, 'brief_news_input', lambda d: (_ for _ in ()).throw(rd.GitLookupError('x')))
    assert rd._kr_news_expected_at('2026-11-06') is True
