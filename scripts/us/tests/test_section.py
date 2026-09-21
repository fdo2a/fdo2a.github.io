"""섹션 구간 자르기 공용 헬퍼."""
from us.section import locate_section, number_forms, strip_tags

DOC = ('<section><h2>매크로</h2><p>뉴스 섹션에서 다룬다</p></section>'
       '<section><h2>오늘의 뉴스</h2><p>본문</p></section>'
       '<section><h2>AI 인프라</h2><p>끝</p></section>')


def test_slice_stops_at_the_next_section():
    seg = locate_section(DOC, '오늘의 뉴스')
    assert '<p>본문</p>' in seg and 'AI 인프라' not in seg


def test_heading_beats_an_earlier_mention_in_someone_elses_prose():
    seg = locate_section(DOC, '뉴스')
    assert '<h2>오늘의 뉴스</h2>' in seg and '<h2>매크로</h2>' not in seg


def test_exact_refuses_a_partial_title():
    assert locate_section(DOC, '뉴스', exact=True) is None
    assert locate_section(DOC, '오늘의 뉴스', exact=True) is not None


def test_missing_section_is_none_not_an_empty_string():
    assert locate_section(DOC, '없는 섹션', exact=True) is None


def test_strip_tags_collapses_markup_and_whitespace():
    assert strip_tags('<p>가\n  나</p>').strip() == '가 나'


def test_strip_tags_eats_a_tag_containing_a_bracket():
    assert '숨김' not in strip_tags('<span title="a>b">숨김</span>' .replace('숨김', ''))
    assert strip_tags('<!-- 주석 -->보임').strip() == '보임'


def test_number_forms_covers_the_spellings_a_writer_would_use():
    assert '5.4' in number_forms(5.4) and '5.40' in number_forms(5.4)
    assert '3' in number_forms(3.0)


def test_number_forms_of_none_is_empty():
    assert number_forms(None) == []


def test_the_slice_ends_at_the_closing_tag_not_the_next_opening_one():
    """codex 검토 2026-09-19 #16 — 닫힌 섹션 뒤에 붙은 블록을 안쪽으로 셌다."""
    doc = ('<section><h2>오늘의 뉴스</h2><p>안</p></section>'
           '<div data-news="x">밖</div>'
           '<section><h2>AI 인프라</h2></section>')
    seg = locate_section(doc, '오늘의 뉴스', exact=True)
    assert '안' in seg and '밖' not in seg


def test_a_nested_section_does_not_end_the_slice_early():
    doc = ('<section><h2>오늘의 뉴스</h2><section><h3>주요</h3><p>안쪽</p></section>'
           '<p>바깥쪽</p></section><section><h2>다음</h2></section>')
    seg = locate_section(doc, '오늘의 뉴스', exact=True)
    assert '안쪽' in seg and '바깥쪽' in seg and '다음' not in seg


def test_an_unclosed_section_still_stops_at_the_next_one():
    doc = ('<section><h2>오늘의 뉴스</h2><p>안</p>'
           '<section><h2>AI 인프라</h2><p>밖</p></section>')
    seg = locate_section(doc, '오늘의 뉴스', exact=True)
    assert '안' in seg


def test_the_slice_does_not_overrun_past_the_closing_tag():
    """codex 2차 #2 — `len('section>')` 를 더해 구간이 늘 7자 넘쳤다."""
    doc = '<section><h2>오늘의 뉴스</h2><p>안</p></section>ABCDEFGH'
    seg = locate_section(doc, '오늘의 뉴스', exact=True)
    assert seg.endswith('</section>')
    assert 'ABCDEFG' not in seg


def test_a_closing_tag_inside_an_attribute_does_not_end_the_slice():
    """codex 2차 #1 — 속성값의 `</section>` 을 닫는 태그로 셌다."""
    doc = ('<section><h2>오늘의 뉴스</h2><span title="</section>"></span>'
           '<p>안</p></section><section><h2>다음</h2><p>밖</p></section>')
    seg = locate_section(doc, '오늘의 뉴스', exact=True)
    assert '안' in seg and '밖' not in seg
