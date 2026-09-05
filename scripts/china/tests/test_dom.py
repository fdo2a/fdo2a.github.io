from china import dom as D


def test_text_ignores_script_and_style():
    t = D.visible_text('<p>보이는 글</p><script>var x=1</script><style>p{}</style>')
    assert '보이는' in t and 'var' not in t and 'p{}' not in t


def test_text_ignores_comments():
    assert '숨김' not in D.visible_text('<p>보임</p><!-- 숨김 -->')


def test_hidden_attribute_hides_subtree():
    assert '숨김' not in D.visible_text('<div hidden><p>숨김</p></div>')


def test_display_none_and_visibility_hidden_hide_subtree():
    assert '나' not in D.visible_text('<div style="display:none"><p>나</p></div>')
    assert '다' not in D.visible_text('<span style="visibility: hidden">다</span>')


def test_visible_sibling_survives_a_hidden_one():
    t = D.visible_text('<div hidden>숨김</div><div>보임</div>')
    assert t.strip() == '보임'


def test_find_marked_returns_only_visible_elements():
    html = '<section data-lesson="A01">x</section><div hidden data-lesson="A02">y</div>'
    got = D.find_marked(html, 'data-lesson')
    assert [e.attrs['data-lesson'] for e in got] == ['A01']


def test_find_marked_counts_duplicates():
    html = '<section data-lesson="A01">x</section><section data-lesson="A01">y</section>'
    assert len(D.find_marked(html, 'data-lesson')) == 2


def test_element_knows_its_own_visible_text():
    html = '<section data-lesson="A01"><p>본문</p><span hidden>숨김</span></section>'
    el = D.find_marked(html, 'data-lesson')[0]
    assert el.text().strip() == '본문'


def test_depth_distinguishes_top_level_from_nested():
    html = '<section data-lesson="A01"><div data-lesson="A02">x</div></section>'
    got = D.find_marked(html, 'data-lesson')
    assert got[0].depth < got[1].depth


def test_alt_text_is_not_counted_as_visible_prose():
    assert '설명' not in D.visible_text('<img alt="긴 설명 문장">')


def test_void_tags_do_not_break_nesting():
    html = '<section data-lesson="A01"><br><img src="x"><p>뒤</p></section>'
    el = D.find_marked(html, 'data-lesson')[0]
    assert '뒤' in el.text()


# ── codex 2차 검토 (2026-09-05) ──

def test_aria_hidden_content_still_counts_as_visible():
    """aria-hidden 은 보조기술에서만 감춘다 — 화면에는 보인다. 숨김으로 치면
    시황을 aria-hidden 으로 감싸 상한 계산에서 빼는 우회가 열린다."""
    assert '보임' in D.visible_text('<div aria-hidden="true"><p>보임</p></div>')


def test_a_hidden_paragraph_does_not_swallow_the_next_one():
    """`<p hidden>숨김<p>99%</p>` — 브라우저는 두 번째 p 를 형제로 연다."""
    assert '99%' in D.visible_text('<p hidden>숨김<p>99%</p>')


def test_implicit_close_applies_to_list_and_table_cells():
    assert '뒤' in D.visible_text('<ul><li hidden>앞<li>뒤</li></ul>')
    assert '뒤' in D.visible_text('<table><tr><td hidden>앞<td>뒤</td></tr></table>')


# ── codex 3차 (2026-09-05) ──

def test_implicit_close_reaches_through_inline_wrappers():
    """`<p hidden><span>x<p>99%</p>` — 스택 꼭대기만 보면 span 에 막혀 상속된다."""
    assert '99%' in D.visible_text('<p hidden><span>x<p>99%</p>')


def test_heading_closes_an_open_paragraph():
    assert '뒤' in D.visible_text('<p hidden>앞<h5>뒤</h5>')


def test_inline_tags_do_not_split_a_number():
    """`14.<b>4</b>%` 는 한 수치다 — 쪼개면 원문에 없는 14 가 생긴다."""
    assert '14.4' in D.visible_text('<p>14.<b>4</b>%</p>')


def test_block_tags_still_separate_numbers():
    assert '0.50.9' not in D.visible_text('<table><tr><td>0.5</td><td>0.9</td></tr></table>')
