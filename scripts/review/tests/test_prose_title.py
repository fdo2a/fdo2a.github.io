"""제목 문장 원소(readability v6 `split_title_sentences`)를 조판으로 받는 경로.

옛 판(v5)의 제목에 `<tl-s>` 를 씌운 새 판은 조판이다. 그러나 그 원소에 닿아 무엇이 보이고
안 보일지를 바꿀 수 있는 CSS 가 페이지에 있으면 판정 불가(None)다. 아래 사례는 전부 2026-11-05
codex 검토 세 차례가 재현한 것이다.
"""

import pytest

from review.prose import equivalent
from us import colorize
from us import readability as R


def _page(css='', body_css='', h1='<h1>오른다. 내린다.</h1>', head=''):
    return ('<html><head>%s<style>%s\n%s</style></head><body>%s<div class="doc"><section>'
            '<div class="card headline-card">%s<p>본문이다.</p></div></section></div></body></html>'
            % (head, css, R.V5_CSS, body_css, h1))


def _verdict(old):
    return equivalent(old, colorize.apply(R.enhance_html(old)))


def test_a_plain_title_split_is_typography():
    assert _verdict(_page()) is True


@pytest.mark.parametrize('css', [
    '* { box-sizing: border-box; }',
    '.doc span { font-size:0 }',               # span 규칙은 <tl-s> 에 닿지 않는다
    'h1 span:nth-child(2n + 1) { display:none }',
    '.stance-tbl:has(th:nth-child(6):last-child) { table-layout: fixed; }',
    ':is(.doc, .container) .pos { color:red } .card:not(.headline-card) .x { color:red }',
    '[data-axis] { color:red } :root { --a:1 } p:not([class]) { font-size:17px }',
    '* { color: inherit; } * { margin: 0; padding: 0 }',
    'p::first-letter { color:red } * { border:0 }',
])
def test_css_that_cannot_reach_the_title_element_still_folds(css):
    assert _verdict(_page(css)) is True


@pytest.mark.parametrize('css', [
    'h1 *{content-visibility:hidden}',
    'h1 :nth-child(2n + 1){opacity:.0}',
    'h1:has(> *) { display:none }',
    'h1 tl-s{display:none}',
    '.card :not(b){display:none}',
    ':is(h1, .x) > *{display:none}',
    'h1 *::before{content:"x"}',
    'h1 :is(tl-s){color:transparent}',
    'tl-s { margin-left: -99999px; }',          # 허용 속성이어도 값이 0 이 아니면 보류
    'h1::first-letter { font-size: 0; }',       # inline-block 안 글자는 첫 글자가 아니게 된다
    'h1{display:flex;flex-direction:row-reverse}',  # 문장 원소가 따로 배치되어 순서가 뒤집힌다
])
def test_css_that_reaches_the_title_element_is_undecidable(css):
    assert _verdict(_page(css)) is None


def test_a_body_style_is_checked_too():
    assert _verdict(_page(body_css='<style>h1 *{font-size:0}</style>')) is None


def test_an_attribute_with_a_bracket_does_not_change_the_visible_title():
    old = _page(h1='<h1 title="가 > 나. 다">제목. 다음</h1>')
    new = colorize.apply(R.enhance_html(old))
    assert '<h1 title="가 > 나. 다"><tl-s>제목.</tl-s> <tl-s>다음</tl-s></h1>' in new
    assert equivalent(old, new) is True


@pytest.mark.parametrize('body_css', [
    # 속성값 안의 `<style>` 흉내가 실제 style 을 문자열로 덮던 경로
    '<div data-copy="<style>"></div><style>tl-s{font-size:0} p::before{content:""}</style>',
])
def test_a_fake_style_tag_in_an_attribute_does_not_mask_real_css(body_css):
    assert _verdict(_page(body_css=body_css)) is None


def test_style_text_inside_a_textarea_is_not_css():
    assert _verdict(_page(body_css='<textarea><style>tl-s{font-size:0}</style></textarea>')) is True


@pytest.mark.parametrize('head', [
    '<link rel="stylesheet" href="data:text/css,tl-s%7Bfont-size%3A0%7D">',
    '<script>customElements.define("tl-s", class extends HTMLElement {})</script>',
    '<script src="https://example.com/x.js"></script>',
])
def test_unknown_stylesheets_and_scripts_are_undecidable(head):
    assert _verdict(_page(head=head)) is None


def test_the_known_font_link_and_ad_scripts_still_fold():
    head = ('<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/'
            'dist/web/variable/pretendardvariable-dynamic-subset.min.css">'
            '<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=x">'
            '</script><script async src="https://gc.zgo.at/count.js"></script>')
    assert _verdict(_page(head=head)) is True


@pytest.mark.parametrize('head', [
    '<script>document.addEventListener("DOMContentLoaded",()=>{const h=document.querySelector("h1");'
    'h.textContent=h.firstChild.textContent;});</script>',
    '<noscript><style>h1>*{display:none}</style></noscript>',
    '<link rel="stylesheet" rel="preload" href="data:text/css,h1%20%3E%20*%7Bdisplay%3Anone%7D">',
])
def test_scripts_noscript_and_duplicate_attributes_are_undecidable(head):
    assert _verdict(_page(head=head)) is None


def test_inline_style_flex_on_the_title_is_undecidable():
    assert _verdict(_page(h1='<h1 style="display:flex;flex-direction:row-reverse">오른다. 내린다.</h1>')) is None


def test_fake_textarea_in_attributes_does_not_mask_real_css():
    body = '<div data-copy="<textarea>"></div><style>tl-s{font-size:0}</style><div data-copy="</textarea>"></div>'
    assert _verdict(_page(body_css=body)) is None


def test_the_shell_footer_script_and_json_ld_still_fold():
    from common import post_shell
    head = '<script type="application/ld+json">{"headline":"x"}</script>' + post_shell._FOOT_JS
    assert _verdict(_page(head=head)) is True


def test_the_gate_reads_the_shell_script_without_importing_the_shell():
    """review_gate 는 `scripts/` 만 경로에 둔다. 거기서 `post_shell` 을 불러오면 `scripts.` 접두
    import 가 실패하고, 그 예외가 판정 불가로 삼켜졌다(2026-11-05 실측 21편)."""
    import os
    import subprocess
    import sys
    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    code = ('import sys; sys.path[:] = [p for p in sys.path if p not in ("", %r)]; '
            'sys.path.insert(0, %r); from review import prose; '
            'print(len(prose._known_inline_scripts()))' % (os.path.dirname(here), here))
    out = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True,
                         cwd=os.path.dirname(here))
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == '1'


@pytest.mark.parametrize('css, h1', [
    ('.hero{display:flex;flex-direction:row-reverse}', '<h1 class="hero">오른다. 내린다.</h1>'),
    ('#headline{display:grid}', '<h1 id="headline">오른다. 내린다.</h1>'),
    ('[data-title]{display:flex}', '<h1 data-title="x">오른다. 내린다.</h1>'),
])
def test_layout_on_the_titles_own_class_id_or_attribute_is_undecidable(css, h1):
    assert _verdict(_page(css, h1=h1)) is None


def test_layout_rules_for_other_elements_and_a_plain_inline_display_still_fold():
    css = '.grid-2{display:grid} nav.reading-map{display:flex} .hero{display:flex}'
    assert _verdict(_page(css)) is True
    assert _verdict(_page(h1='<h1 style="display:block">오른다. 내린다.</h1>')) is True


def test_a_nested_raw_text_lookalike_does_not_mask_real_css():
    body = ('<textarea></textarea><textarea><title></textarea>'
            '<style>h1>*{display:none}</style></title>')
    assert _verdict(_page(body_css=body)) is None
