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


# --- 읽는 쪽의 신선도 (2026-10-01 moomoo 제거 때 옮김) ------------------------
# 낡음 검사는 파일을 쓸 때가 아니라 읽을 때 해야 한다 — 갱신이 멈춰도 파일은 남는다.

def _write_book(tmp_path, **kw):
    import json
    book = {'source': F.URL, 'verified_at': '2026-09-22', 'checked_at': '2026-09-22',
            'meetings': ['2026-09-16', '2026-10-28', '2026-12-09']}
    book.update(kw)
    p = tmp_path / 'fomc_dates.json'
    p.write_text(json.dumps(book), encoding='utf-8')
    return str(p)


def test_load_keeps_the_meeting_that_just_ended(tmp_path):
    """직전 회의가 빠지면 그 주 목요일 블랙아웃 판정 근거가 사라진다.
    codex 재현: [09-16, 10-28] 이면 09-17 에 blackout active, [10-28] 만이면 아니다."""
    meetings, _ = F.load(_write_book(tmp_path), as_of=dt.date(2026, 9, 24))
    assert dt.date(2026, 9, 16) in meetings


def test_an_expired_official_check_stops_authorising_the_table(tmp_path):
    """공식 확인에 유효기간을 둔다 — 미래 날짜가 하나 남았다는 사실을
    최신 확인의 대용물로 쓰지 않는다."""
    path = _write_book(tmp_path, verified_at='2026-01-01', checked_at='2026-01-01',
                       meetings=['2027-06-09'])
    meetings, note = F.load(path, as_of=dt.date(2026, 9, 22))
    assert meetings == []
    assert '낡' in note


def test_a_book_without_a_verification_date_authorises_nothing(tmp_path):
    path = _write_book(tmp_path, verified_at=None, checked_at=None)
    assert F.load(path, as_of=dt.date(2026, 9, 22))[0] == []


def test_a_missing_or_malformed_book_yields_nothing(tmp_path):
    assert F.load(str(tmp_path / 'nope.json'), as_of=dt.date(2026, 9, 22))[0] == []
    bad = _write_book(tmp_path, meetings=['2026-13-40'])
    assert F.load(bad, as_of=dt.date(2026, 9, 22))[0] == []


# --- 2026-10-01 codex 구현 검토 ---------------------------------------------

def test_abbreviated_month_spans_are_read():
    """원문은 달을 걸친 회의를 'Jan/Feb'·'Oct/Nov' 로 줄여 적는다. 전체 이름만
    알아보면 그 회의가 행째로 사라졌다(2023 은 8회 중 6회만 잡혔다)."""
    html = ('<div class="panel-heading"><h4 class="panel-title"><a>2023</a></h4></div>'
            '<div class="fomc-meeting__month col-md-2"><strong>Jan/Feb</strong></div>'
            '<div class="fomc-meeting__date col-lg-1">31-1</div>'
            '<div class="fomc-meeting__month col-md-2"><strong>Oct/Nov</strong></div>'
            '<div class="fomc-meeting__date col-lg-1">31-1</div>')
    assert [r['date'] for r in F.parse_calendar(html)] == [
        dt.date(2023, 2, 1), dt.date(2023, 11, 1)]


def _years(*spec):
    out = []
    for year, n in spec:
        out += [f'{year}-{m:02d}-15' for m in range(1, n + 1)]
    return out


TODAY = dt.date(2026, 10, 1)


def test_a_complete_schedule_has_no_problems():
    assert F.problems({'meetings': _years((2026, 8), (2027, 8))}, today=TODAY) == []


def test_boundary_years_may_be_partial():
    """연준은 다음 해 일정을 단계적으로 올리고, 가장 오래된 패널은 잘려 있을 수 있다."""
    book = {'meetings': _years((2021, 1), (2026, 8), (2027, 8), (2028, 1))}
    assert F.problems(book, today=TODAY) == []


def test_a_short_interior_year_is_a_partial_parse():
    book = {'meetings': _years((2025, 8), (2026, 5), (2027, 8))}
    assert any('2026' in x for x in F.problems(book, today=TODAY))


def test_duplicate_dates_are_refused():
    m = _years((2026, 8))
    assert F.problems({'meetings': m[:7] + [m[0]]}, today=TODAY)


def test_an_empty_parse_is_refused():
    assert F.problems({'meetings': []}, today=TODAY)


def test_a_future_meeting_must_not_vanish():
    """한 해 패널이 통째로 빠지면 개수 검사로는 안 보인다 — 어제 표의 앞으로의
    회의가 오늘 표에서 사라지면 거부한다. 지난 회의는 빠져도 된다."""
    prev = {'meetings': _years((2026, 8), (2027, 8))}
    dropped = {'meetings': _years((2026, 8))}
    assert any('2027' in x for x in F.problems(dropped, previous=prev, today=TODAY))
    past_trimmed = {'meetings': _years((2026, 8), (2027, 8))[1:]}
    assert F.problems(past_trimmed, previous=prev, today=TODAY) == []


def test_a_future_verification_date_authorises_nothing(tmp_path):
    path = _write_book(tmp_path, verified_at='2099-01-01')
    assert F.load(path, as_of=dt.date(2026, 10, 1))[0] == []


def test_checked_at_alone_is_not_an_official_check(tmp_path):
    """`checked_at` 은 옛 형식의 수집 시각이지 연준 원문 확인이 아니다."""
    path = _write_book(tmp_path, verified_at=None, checked_at='2026-10-01')
    assert F.load(path, as_of=dt.date(2026, 10, 1))[0] == []


def test_a_non_object_book_yields_nothing(tmp_path):
    p = tmp_path / 'fomc_dates.json'
    p.write_text('[]', encoding='utf-8')
    assert F.load(str(p), as_of=dt.date(2026, 10, 1))[0] == []


def test_without_a_previous_table_the_caller_must_bootstrap_explicitly():
    """어제 표가 없으면 ③ 대조가 꺼진다 — 한 건만 읽힌 원문도 통과한다.
    그래서 자동 갱신은 어제 표를 요구하고, 없을 때는 사람이 `--bootstrap` 한다."""
    one = {'meetings': ['2027-01-27']}
    assert F.problems(one, previous=None, today=TODAY) == []   # 함수 자체는 판단 못 한다
    assert F.problems(one, previous=None, today=TODAY, require_previous=True)


def test_allowed_removals_are_named_dates_only():
    """확인한 날짜만 빠져도 되고, 나머지 앞으로의 회의 누락 검사는 그대로다."""
    prev = {'meetings': _years((2026, 8), (2027, 8))}
    moved = {'meetings': [d for d in prev['meetings'] if d != '2027-03-15']}
    assert F.problems(moved, previous=prev, today=TODAY,
                      allowed_removals={'2027-03-15'}) == []
    dropped = {'meetings': _years((2026, 8))}
    assert F.problems(dropped, previous=prev, today=TODAY,
                      allowed_removals={'2027-03-15'})
