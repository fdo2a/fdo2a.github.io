from us.calendar_gate import check

BOOK = {'report_date': '2026-09-14', 'events': [
    {'key': 'fomc-20260916', 'name_ko': 'FOMC 성명', 'date': '2026-09-16',
     'time_et': '14:00', 'time_kst': '2026-09-17 03:00'},
    {'key': 'expiry-202609', 'name_ko': '쿼드러플 위칭(분기 만기)', 'date': '2026-09-18',
     'time_et': None, 'time_kst': None},
]}


def _page(body):
    return f'<html><body><main>{body}</main></body></html>'


def test_a_page_with_no_markers_passes():
    assert check(_page('<p>조용한 한 주였다.</p>'), BOOK) == []


def test_a_marked_event_that_matches_passes():
    html = _page('<li data-calendar="fomc-20260916">9월 16일 FOMC 성명 '
                 '(한국 시각 17일 03:00)</li>')
    assert check(html, BOOK) == []


def test_an_iso_date_also_counts():
    html = _page('<li data-calendar="expiry-202609">2026-09-18 쿼드러플 위칭</li>')
    assert check(html, BOOK) == []


def test_an_event_we_never_collected_is_blocked():
    """수집한 적 없는 일정에 표식을 달면 그것이 지어낸 일정이다."""
    html = _page('<li data-calendar="release-cpi-20260916">9월 16일 CPI</li>')
    v = check(html, BOOK)
    assert v and '수집한 일정에 없다' in v[0]


def test_the_wrong_day_under_a_right_key_is_blocked():
    html = _page('<li data-calendar="fomc-20260916">9월 17일 FOMC 성명</li>')
    v = check(html, BOOK)
    assert v and '날짜' in v[0]


def test_a_time_invented_for_a_timeless_event_is_blocked():
    """만기에는 시각이 없다 — 적으면 지어낸 것이다."""
    html = _page('<li data-calendar="expiry-202609">9월 18일 만기 09:30</li>')
    v = check(html, BOOK)
    assert v and '모르는 시각' in v[0]


def test_a_time_that_disagrees_with_the_collection_is_blocked():
    html = _page('<li data-calendar="fomc-20260916">9월 16일 FOMC 04:00</li>')
    v = check(html, BOOK)
    assert v and '시각이 수집값과 다르다' in v[0]


def test_either_clock_may_be_quoted():
    for stamp in ('14:00', '03:00'):
        html = _page(f'<li data-calendar="fomc-20260916">9월 16일 FOMC {stamp}</li>')
        assert check(html, BOOK) == [], stamp


def test_an_empty_book_leaves_every_marker_unauthorised():
    """수집이 실패한 날 표식을 달았다면 그것은 대조된 적 없는 일정이다."""
    html = _page('<li data-calendar="fomc-20260916">9월 16일 FOMC</li>')
    assert check(html, {})
    assert check(_page('<p>조용한 하루였다.</p>'), {}) == []


def test_the_innermost_marker_owns_the_text():
    """바깥 블록의 표식이 안쪽 일정의 날짜를 인가하면 안 된다."""
    html = _page('<div data-calendar="fomc-20260916"><p>9월 16일 FOMC</p>'
                 '<p data-calendar="expiry-202609">9월 18일 만기</p></div>')
    assert check(html, BOOK) == []


def test_entities_are_read_as_the_reader_sees_them():
    html = _page('<li data-calendar="fomc-20260916">9&#50900; 16&#51068; FOMC</li>')
    assert check(html, BOOK) == []
