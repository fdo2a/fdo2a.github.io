import pytest

from us.editor_note import apply_note, extract_note, render_note

PAGE = ('<body><section id="verdict"><h2>전략 코멘트</h2><p>…</p></section>\n'
        '<section id="macro"><h2>매크로 논리</h2><p>…</p></section>\n'
        '<section id="disclaimer"><p>면책</p></section></body>')


# --- 마크다운 렌더 ------------------------------------------------------------

def test_paragraphs_split_on_blank_lines():
    html = render_note('첫 문단이다.\n\n둘째 문단이다.', '2026-08-20')
    assert html.count('<p') == 2
    assert '첫 문단이다.' in html and '둘째 문단이다.' in html


def test_a_leading_heading_becomes_the_section_title():
    html = render_note('# 나는 지금 채권이 싸다고 본다\n\n이유는…', '2026-08-20')
    assert '<h2>나는 지금 채권이 싸다고 본다</h2>' in html
    assert '<p' in html and '나는 지금' not in html.split('</h2>')[1]


def test_without_a_heading_it_is_labelled_generically():
    assert '<h2>에디터 노트</h2>' in render_note('그냥 본문.', '2026-08-20')


def test_emphasis_lists_quotes_and_links():
    html = render_note('- 하나\n- **둘**\n\n> 인용\n\n[링크](https://x.com) *기울임*', '2026-08-20')
    assert '<li>하나</li>' in html and '<strong>둘</strong>' in html
    assert '<blockquote' in html and '인용' in html
    assert '<a href="https://x.com"' in html and '<em>기울임</em>' in html


def test_html_in_the_note_is_escaped_not_executed():
    html = render_note('<script>alert(1)</script> & 그리고', '2026-08-20')
    assert '<script>' not in html
    assert '&lt;script&gt;' in html and '&amp;' in html


def test_the_note_is_marked_as_the_authors_own_view():
    html = render_note('본문', '2026-08-20')
    assert 'data-editor-note="2026-08-20"' in html
    assert '직접' in html          # 캡션이 사람이 쓴 글임을 밝힌다


def test_an_untouched_template_never_ships():
    """노트 파일만 만들어두고 잊은 날 — 안내문이 발행본에 실리면 안 된다."""
    from us.editor_note import is_template
    tpl = '# (제목 — 이 줄을 지우면 「에디터 노트」로 나간다)\n\n여기에 그날의 생각을 쓴다.'
    assert is_template(tpl)
    assert render_note(tpl, '2026-08-20') == ''


def test_an_empty_note_renders_nothing():
    assert render_note('   \n\n', '2026-08-20') == ''


# --- 페이지에 붙이기 ----------------------------------------------------------

def test_the_note_lands_right_after_the_buyside_verdict():
    out = apply_note(PAGE, render_note('내 생각', '2026-08-20'))
    assert out.index('내 생각') > out.index('전략 코멘트')
    assert out.index('내 생각') < out.index('매크로 논리')


def test_reapplying_replaces_the_previous_note():
    once = apply_note(PAGE, render_note('처음 생각', '2026-08-20'))
    twice = apply_note(once, render_note('고쳐 쓴 생각', '2026-08-20'))
    assert '처음 생각' not in twice
    assert twice.count('data-editor-note') == 1


def test_an_empty_note_removes_the_section():
    once = apply_note(PAGE, render_note('처음 생각', '2026-08-20'))
    assert 'data-editor-note' not in apply_note(once, '')


def test_the_rest_of_the_page_is_untouched():
    out = apply_note(PAGE, render_note('내 생각', '2026-08-20'))
    for keep in ('전략 코멘트', '매크로 논리', '면책'):
        assert keep in out


def test_a_page_without_the_verdict_section_falls_back_to_before_the_disclaimer():
    page = '<body><section id="macro"><h2>매크로 논리</h2></section>\n' \
           '<section id="disclaimer"><p>면책</p></section></body>'
    out = apply_note(page, render_note('내 생각', '2026-08-20'))
    assert out.index('내 생각') < out.index('면책')


def test_a_note_can_be_read_back_out_of_a_page():
    out = apply_note(PAGE, render_note('# 제목\n\n본문이다.', '2026-08-20'))
    assert extract_note(out)['date'] == '2026-08-20'
    assert '본문이다.' in extract_note(out)['html']
    assert extract_note(PAGE) is None


def test_applying_nothing_to_a_clean_page_changes_nothing():
    assert apply_note(PAGE, '') == PAGE
