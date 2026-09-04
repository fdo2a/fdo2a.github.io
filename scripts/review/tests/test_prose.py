"""옛 판을 조판 변환으로 밀어 새 판이 «바이트 그대로» 나오는가.

이 모듈이 지켜야 할 성질은 하나다 — **통과하는 새 판은 단 하나여야 한다.** 옛 판과 블록으로
완전히 결정되므로 그 사이에 무엇도 끼워 넣을 수 없어야 한다. 아래 공격 목록은 전부
2026-09-04 codex 검토가 이전 판(양쪽 손실 정규화)에서 실제로 뚫었던 것들이다.
"""

import pytest

from review.prose import equivalent, find_block, typography
from review.tests.blocks import CUR, PREV

PAGE = """<html><head><style>
.stance-tbl thead { display: none; }
.stance-tbl td::before { content: attr(data-label); }
  %s
%s
</style><script type="application/ld+json">{"headline":"오늘의 장"}</script></head>
<body><div class="card"><p><strong%s>동인.</strong> 유가가 %s.</p>
<p class="caption" data-standing="equities">지금 여기.</p></div></body></html>"""

OLD = PAGE % ('.card p, p { font-size:16px; }', PREV, '', '올랐다')
NEW = PAGE % ('p { font-size:16px; }', CUR, ' class="p-label"', '올랐다')


def test_the_same_post_typeset_two_ways_is_equivalent():
    """블록 교체·선택자 강등·라벨 클래스가 한꺼번에 다르다."""
    assert equivalent(OLD, NEW) is True


def test_the_direction_matters():
    """새 판을 옛 판으로 되밀 수는 없다 — 조판은 한 방향으로만 간다."""
    assert equivalent(NEW, OLD) is not True


# ── 이전 판이 실제로 뚫렸던 공격들 ────────────────────────────────────────────

def test_css_smuggled_into_the_block_is_refused():
    """마커 뒤에 은폐 CSS를 넣던 공격. 등록된 블록이 아니므로 판정 불가다."""
    attacked = NEW.replace(CUR, CUR + '\nhtml, body { display:none !important; }')
    assert equivalent(OLD, attacked) is None


def test_generated_text_smuggled_into_the_block_is_refused():
    attacked = NEW.replace(CUR, CUR + '\nbody::before { content:"전략 전면 철회"; }')
    assert equivalent(OLD, attacked) is None


def test_an_unknown_block_is_never_typography():
    assert equivalent(OLD, PAGE % ('p { font-size:16px; }',
                                   '/* readability-v5 */\np { color: red; }',
                                   ' class="p-label"', '올랐다')) is None


def test_a_second_marker_makes_the_block_undecidable():
    assert find_block(NEW + '<style>/* readability-v5 */</style>') is None
    assert equivalent(OLD, NEW + '<!-- /* readability-v5 */ -->') is None


def test_a_marker_in_the_body_is_not_a_block():
    """CSS 문자열이나 본문에 마커 모양이 있으면 엉뚱한 구간을 자르게 된다."""
    assert find_block('<html><body><p>전략 /* readability-v5 */ 매수</p></body></html>') is None


def test_a_selector_collision_no_longer_hides_a_visibility_change():
    """`.card p, p{font-size:0}` 와 `p{font-size:0}` 는 보이는 결과가 다르다."""
    hidden = PAGE % ('p { font-size:0; }', CUR, ' class="p-label"', '올랐다')
    assert equivalent(OLD, hidden) is False


def test_a_lookalike_label_class_no_longer_collides():
    faked = NEW.replace('class="p-label"', 'class="not-p-label"')
    assert equivalent(OLD, faked) is False


def test_whitespace_after_a_label_is_not_absorbed():
    assert equivalent(OLD, NEW.replace('</strong> 유가가', '</strong>유가가')) is False


# ── 산문·가시성·의미 변경은 전부 걸린다 ──────────────────────────────────────

def test_hiding_a_paragraph_with_an_inline_style_is_caught():
    assert equivalent(OLD, NEW.replace('<p class="caption"',
                                       '<p style="display:none" class="caption"')) is False


def test_hiding_a_paragraph_with_the_hidden_attribute_is_caught():
    assert equivalent(OLD, NEW.replace('class="caption"', 'class="caption" hidden')) is False


def test_css_outside_the_block_is_caught():
    assert equivalent(OLD, NEW.replace('.stance-tbl thead { display: none; }',
                                       '.stance-tbl thead { display: block; }')) is False


def test_json_ld_is_caught():
    assert equivalent(OLD, NEW.replace('"오늘의 장"', '"반대의 장"')) is False


def test_a_semantic_class_swap_is_caught():
    assert equivalent(OLD, NEW.replace('class="caption"', 'class="fed-trans"')) is False


def test_dropping_a_gate_marker_is_caught():
    assert equivalent(OLD, NEW.replace(' data-standing="equities"', '')) is False


def test_one_changed_word_is_caught():
    assert equivalent(OLD, NEW.replace('올랐다', '내렸다')) is False


def test_a_deleted_paragraph_is_caught():
    assert equivalent(OLD, NEW.replace(
        '<p class="caption" data-standing="equities">지금 여기.</p>', '')) is False


# ── 판정 불가는 「같다」가 아니다 ────────────────────────────────────────────

def test_a_page_without_a_block_is_undecidable():
    assert equivalent('<html><body><p>글.</p></body></html>', NEW) is None


def test_missing_content_is_undecidable():
    assert equivalent(None, NEW) is None and equivalent(OLD, None) is None


def test_a_non_html_path_is_never_typography():
    """thesis_state.json 같은 원고에는 조판이라는 것이 없다."""
    assert typography('thesis/data/thesis_state.json', '{"a":1}', '{"a":2}') is False
    assert typography('posts/x.html', OLD, NEW) is True


# ── 3차 codex 검토가 지적한 구멍들 ──────────────────────────────────────────

def test_a_fake_style_tag_in_a_comment_is_not_a_block():
    """`<style` 를 문자열로 되짚으면 `<stylex>` 도 주석 안의 것도 여는 태그가 된다."""
    assert find_block(
        '<html><head><!-- <stylex>/* readability-v5 */ 가짜 --></head>'
        '<body><p>본문</p></body></html>') is None


def test_a_style_string_inside_a_script_is_not_a_block():
    assert find_block(
        '<html><head><script>var s="<style>/* readability-v5 */";</script></head>'
        '<body></body></html>') is None


def test_a_style_element_with_attributes_still_holds_its_block():
    assert find_block(NEW.replace('<style>', '<style type="text/css">')) is not None


def test_a_transform_that_edits_a_script_string_is_refused():
    """라벨 정규식은 문서 전체에 돈다 — 스크립트 문자열의 HTML 흉내까지 고친다."""
    payload = '<script>var t="<p><strong>모드:</strong> 안전</p>";</script>'
    assert equivalent(OLD.replace('<body>', '<body>' + payload),
                      NEW.replace('<body>', '<body>' + payload)) is None


def test_css_that_hides_a_label_class_makes_the_page_undecidable():
    """`p-label` 을 붙이는 것만으로 글이 사라지는 페이지는 조판이라 부를 수 없다."""
    trap = '.p-label { display:none; }\n'
    assert equivalent(OLD.replace('.stance-tbl thead', trap + '.stance-tbl thead'),
                      NEW.replace('.stance-tbl thead', trap + '.stance-tbl thead')) is None


def test_an_ordinary_label_rule_is_not_treated_as_a_trap():
    """`display:inline-block` 은 감추지 않는다 — 발행본 CSS에 흔하다(실측 19편)."""
    fine = '.box-label { display:inline-block; font-size:12.5px; }\n'
    assert equivalent(OLD.replace('.stance-tbl thead', fine + '.stance-tbl thead'),
                      NEW.replace('.stance-tbl thead', fine + '.stance-tbl thead')) is True


def test_a_demoted_rule_carrying_display_makes_the_page_undecidable():
    """선택자 강등은 같은 규칙의 `display` 특정도까지 내린다 — 더 약한 규칙이 이길 수 있다."""
    old = OLD.replace('.card p, p { font-size:16px; }',
                      '.card p, p { font-size:16px; display:block; }')
    new = NEW.replace('p { font-size:16px; }', 'p { font-size:16px; display:block; }')
    assert equivalent(old, new) is None


@pytest.mark.parametrize('rule', [
    '.p-label { display:none; }',
    '.p-label { display:none !important; }',
    '.p-label { DISPLAY : NONE; }',
    '.p-label { /* 조판 */ display:none; }',
    '.p-label{/*{*/display:none/*}*/}',
    '.p-label{content:"{";display:none}',
    '.p-label { position:absolute; left:-9999px; }',
    '.p-label { opacity:0%; }',
    '.p-label { transform:scale(0); }',
    '.p\\2d label { display:none; }',
    '.p\\-label { display:none; }',
    '.box\\-label { display:none; }',
    '.p-label { &{ display:none; } }',
    '@media print { .p-label { display:none; } }',
    '.p-label { visibility:hidden; }',
    '.p-label { opacity:0; }',
    '.p-label { font-size:0; }',
    '.p-label { height:0; overflow:hidden; }',
    '.p-label { text-indent:-9999px; }',
    '.p-label { clip-path:inset(100%); }',
    '.p-label { display:var(--maybe-none); }',
])
def test_every_way_of_hiding_a_label_makes_the_page_undecidable(rule):
    """감추는 표기는 하나로 정해져 있지 않다. 다 막을 수는 없지만 아는 것은 막는다."""
    assert equivalent(OLD.replace('.stance-tbl thead', rule + '\n.stance-tbl thead'),
                      NEW.replace('.stance-tbl thead', rule + '\n.stance-tbl thead')) is None


@pytest.mark.parametrize('rule', [
    '.box-label { display:inline-block; font-size:12.5px; }',
    '.caption { font-size:12.5px; }',
    '.p-label { margin-bottom:2px; }',
])
def test_ordinary_rules_are_not_mistaken_for_traps(rule):
    """오탐은 값이 비싸다 — 발행본 19편이 통째로 큐에 돌아왔던 자리다."""
    assert equivalent(OLD.replace('.stance-tbl thead', rule + '\n.stance-tbl thead'),
                      NEW.replace('.stance-tbl thead', rule + '\n.stance-tbl thead')) is True


def test_a_comment_split_property_is_not_treated_as_hiding():
    """`disp/**/lay:none` 은 CSS 로서 무효라 아무것도 감추지 못한다 — 오탐으로 두지 않는다."""
    rule = '.p-label { disp/**/lay:none; }'
    assert equivalent(OLD.replace('.stance-tbl thead', rule + '\n.stance-tbl thead'),
                      NEW.replace('.stance-tbl thead', rule + '\n.stance-tbl thead')) is True


def test_whitespace_added_inside_a_script_string_is_refused():
    """inert 서명이 «증거 글자»만 모으면 원래 공백이 사라져 이 변경이 통과한다."""
    old = OLD.replace('<body>', '<body><script>var t="<strong class=\'p-label\'>모드:</strong>안전";</script>')
    new = NEW.replace('<body>', '<body><script>var t="<strong class=\'p-label\'>모드:</strong> 안전";</script>')
    assert equivalent(old, new) is not True


def test_a_selector_that_only_looks_like_a_label_is_left_alone():
    """`.p2d label` 은 클래스 `p2d` 의 후손 `label` 이다 — 우리 라벨과 무관하다."""
    rule = '.p2d label { display:none; }'
    assert equivalent(OLD.replace('.stance-tbl thead', rule + '\n.stance-tbl thead'),
                      NEW.replace('.stance-tbl thead', rule + '\n.stance-tbl thead')) is True
