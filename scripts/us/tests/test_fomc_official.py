"""연준 공표 일정 파서 — 이 값이 「연준 공표 일정·확정」으로 인쇄된다."""

import datetime as dt

from us import fomc_official as F

# 원문 구조를 그대로 줄인 표본(2026·2027 패널).
HTML = """
<div class="panel-heading"><h4 class="panel-title"><a href="#a2026">2026</a></h4></div>
<div class="fomc-meeting__month col-md-2"><strong>January</strong></div>
<div class="fomc-meeting__date col-lg-1">27-28</div>
<div class="fomc-meeting__month col-md-2"><strong>March</strong></div>
<div class="fomc-meeting__date col-lg-1">17-18*</div>
<div class="fomc-meeting__month col-md-2"><strong>October</strong></div>
<div class="fomc-meeting__date col-lg-1">27-28</div>
<div class="fomc-meeting__month col-md-2"><strong>December</strong></div>
<div class="fomc-meeting__date col-lg-1">8-9*</div>
<div class="panel-heading"><h4 class="panel-title"><a href="#a2027">2027</a></h4></div>
<div class="fomc-meeting__month col-md-2"><strong>January</strong></div>
<div class="fomc-meeting__date col-lg-1">26-27</div>
<div class="fomc-meeting__month col-md-2"><strong>August</strong></div>
<div class="fomc-meeting__date col-lg-1">22 (notation vote)</div>
<p>* Meeting associated with a Summary of Economic Projections.</p>
"""


def test_the_statement_day_is_the_last_day_of_the_meeting():
    rows = F.parse_calendar(HTML)
    assert rows[0]['date'] == dt.date(2026, 1, 28)
    assert rows[1]['date'] == dt.date(2026, 3, 18)


def test_the_year_comes_from_the_panel_not_the_row():
    """행에는 연도가 없다. 패널을 잘못 가르면 1월 회의가 엉뚱한 해로 간다."""
    days = [r['date'] for r in F.parse_calendar(HTML)]
    assert dt.date(2027, 1, 27) in days
    assert dt.date(2026, 1, 28) in days


def test_sep_is_read_from_the_asterisk_not_guessed_from_the_month():
    """`calendar.py` 는 3·6·9·12 월로 추정한다. 원문 표시가 있으면 그쪽이 맞다."""
    by_date = {r['date']: r for r in F.parse_calendar(HTML)}
    assert by_date[dt.date(2026, 3, 18)]['sep'] is True
    assert by_date[dt.date(2026, 1, 28)]['sep'] is False
    assert by_date[dt.date(2026, 12, 9)]['sep'] is True


def test_a_notation_vote_is_not_a_regular_meeting():
    """성명·기자회견이 없어 블랙아웃·SEP 계산의 전제와 다르다."""
    b = F.book(HTML, verified_at='2026-09-22')
    assert '2027-08-22' not in b['meetings']
    assert b['notation_votes'] == ['2027-08-22']


def test_book_keeps_the_verification_time_separate():
    b = F.book(HTML, verified_at='2026-09-22')
    assert b['verified_at'] == '2026-09-22'
    assert b['source'].startswith('https://www.federalreserve.gov/')
    assert b['sep_meetings'] == ['2026-03-18', '2026-12-09']


def test_meetings_are_sorted_and_cover_past_and_future():
    """직전 회의를 버리지 않는다 — 블랙아웃은 회의 다음 목요일까지다."""
    b = F.book(HTML, verified_at='2026-09-22')
    assert b['meetings'] == sorted(b['meetings'])
    assert b['meetings'][0] == '2026-01-28'


def test_unparsable_html_yields_nothing_rather_than_half_a_meeting():
    assert F.parse_calendar('<html>no panels here</html>') == []
    assert F.book('', verified_at='2026-09-22')['meetings'] == []
