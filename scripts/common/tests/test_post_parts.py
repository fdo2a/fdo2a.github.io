"""Reading layers — headers the shell puts before each layer of the US/KR daily brief.

Design: docs/superpowers/specs/2026-10-31-reading-layers.md
"""
import re
from pathlib import Path

import pytest

from scripts.common import post_parts as P
from scripts.common import post_shell as S
from scripts.us import readability as R

ROOT = Path(__file__).resolve().parents[3]


def _body(path):
    html = (ROOT / path).read_text(encoding='utf-8')
    start = html.index('<div class="doc">') + len('<div class="doc">')
    end = html.rindex('</div>', 0, html.rindex('</body>'))
    return html[start:end]


def _sec(title, body='<p>본문이다.</p>'):
    return f'<section class="card"><h2>{title}</h2>{body}</section>\n'


HEADLINE = '<section><div class="card headline-card"><h1>제목</h1><p>요약이다.</p></div></section>\n'


@pytest.mark.parametrize('market,path,want', [
    ('us', 'posts/2026-10-30.html', ['part-2', 'part-3', 'part-4']),
    ('kr', 'kr/posts/2026-10-30.html', ['part-2', 'part-3', 'part-4', 'part-5']),
])
def test_published_layout_gets_every_layer_in_order(market, path, want):
    body = _body(path)
    out = P.mark(body, market)
    assert [i for i, _ in P.parts(out)] == want
    # Headers are the only change, and they sit between sections, never inside one.
    assert re.sub(r'<div class="part-head"[^>]*>[^<]*</div>\n', '', out) == body
    assert not R.section_div_breaks(out)
    assert not re.search(r'\d', ''.join(label for _, label in P.parts(out)))


def test_layer_one_has_no_header_and_judgment_stays_on_top():
    body = HEADLINE + _sec('전략 코멘트') + _sec('오늘의 장') + _sec('매크로')
    out = P.mark(body, 'us')
    assert out.index('전략 코멘트') < out.index('id="part-2"') < out.index('오늘의 장')
    assert 'part-1' not in out


def test_out_of_order_section_joins_the_open_layer():
    body = (HEADLINE + _sec('전략 코멘트') + _sec('오늘의 장') + _sec('매크로')
            + _sec('트렌드 유닛 점검') + _sec('주목 섹터·종목') + _sec('시장 판단과 복기'))
    out = P.mark(body, 'us')
    assert [i for i, _ in P.parts(out)] == ['part-2', 'part-3', 'part-4']
    assert out.count('class="part-head"') == 3


def test_prefix_titles_and_entities_match():
    assert P.layer_of('us', '연준 이벤트 — 발언록과 해석') == 3
    body = HEADLINE + _sec('전략 코멘트') + _sec('지수 &amp; 장중')
    assert 'id="part-2"' in P.mark(body, 'kr')


def test_mark_is_idempotent_and_ignores_other_markets():
    body = HEADLINE + _sec('전략 코멘트') + _sec('오늘의 장')
    once = P.mark(body, 'us')
    assert P.mark(once, 'us') == once
    assert P.mark(body, 'news') == body


def test_shell_adds_layers_only_from_the_switch_date():
    body = HEADLINE + _sec('전략 코멘트') + _sec('오늘의 장') + _sec('매크로')
    meta = {'title': '미국 증시 마감 시황 — 핵심 | 2026-11-02', 'summary': '요약.'}
    before = S.render('us', '2026-10-30', meta, body)
    after = S.render('us', P.PARTS_FROM, meta, body)
    assert 'part-head' not in before.split('</head>', 1)[1]
    assert 'id="part-2"' in after and 'id="part-3"' in after


def test_reading_map_links_to_layers_when_present():
    body = (HEADLINE + _sec('전략 코멘트') + _sec('오늘의 장') + _sec('주식') + _sec('매크로')
            + _sec('트렌드 유닛 점검') + _sec('시장 판단과 복기'))
    doc = '<div class="doc">' + P.mark(body, 'us') + '</div>'
    nav = R.inject_reading_map(doc)
    nav = nav[nav.index('<nav'):nav.index('</nav>')]
    hrefs = re.findall(r'href="#([^"]+)"', nav)
    assert hrefs[1:] == ['part-2', 'part-3', 'part-4']
    assert '요약·판단' in nav and '오늘 확인된 것' in nav


def test_reading_map_without_layers_is_unchanged():
    body = HEADLINE + _sec('전략 코멘트') + _sec('주식') + _sec('채권') + _sec('매크로')
    nav = R.inject_reading_map('<div class="doc">' + body + '</div>')
    assert 'part-' not in nav and '시장 흐름' in nav


def test_sections_inside_comments_and_scripts_are_not_sections():
    # codex 구현 검토 2026-10-31 #1
    body = (HEADLINE + _sec('전략 코멘트') + '<!-- <section><h2>매크로</h2></section> -->\n'
            + '<script>var s = "<section><h2>매크로</h2></section>";</script>\n'
            + _sec('오늘의 장') + _sec('매크로'))
    out = P.mark(body, 'us')
    assert out.index('id="part-2"') < out.index('<h2>오늘의 장') < out.index('id="part-3"')
    assert out.count('class="part-head"') == 2
    assert '<!-- <section><h2>매크로</h2></section> -->' in out


def test_nested_section_belongs_to_its_parent_and_untitled_sections_stay_put():
    inner = '<section><h2>내부 블록</h2><p>x</p></section>'
    body = (HEADLINE + _sec('전략 코멘트') + f'<section class="card"><h2>오늘의 장</h2>{inner}</section>\n'
            + '<section><p>제목 없는 섹션</p></section>\n' + _sec('매크로'))
    out = P.mark(body, 'us')
    assert [i for i, _ in P.parts(out)] == ['part-2', 'part-3']
    assert inner in out


def test_numeric_entity_titles_match():
    body = HEADLINE + _sec('전략 코멘트') + _sec('지수 &#38; 장중')
    assert 'id="part-2"' in P.mark(body, 'kr')


def test_switch_takes_calendar_dates_only():
    assert P.applies('us', P.PARTS_FROM) and not P.applies('us', '2026-10-30')
    assert not P.applies('us', '20261101') and not P.applies('news', P.PARTS_FROM)


def test_commented_header_does_not_count_as_marked():
    body = HEADLINE + _sec('전략 코멘트') + '<!-- <div class="part-head" id="part-2" data-part="2">x</div> -->' + _sec('오늘의 장')
    out = P.mark(body, 'us')
    assert [i for i, _ in P.parts(out)] == ['part-2']


def test_untitled_parent_does_not_take_a_childs_title():
    # codex 재검토 2026-10-31 #1
    body = (HEADLINE + _sec('전략 코멘트') + '<section><div><section><h2>매크로</h2></section></div></section>\n'
            + _sec('오늘의 장') + _sec('매크로'))
    out = P.mark(body, 'us')
    assert [i for i, _ in P.parts(out)] == ['part-2', 'part-3']
    assert out.index('id="part-2"') < out.index('<h2>오늘의 장')


def test_reading_map_ignores_a_commented_strategy_section():
    # codex 재검토 2026-10-31 #2
    body = ('<!-- <section><h2>전략 코멘트</h2></section> -->' + HEADLINE + _sec('전략 코멘트')
            + _sec('오늘의 장') + _sec('매크로'))
    out = R.inject_reading_map('<div class="doc">' + P.mark(body, 'us') + '</div>')
    first = re.search(r'<nav class="reading-map".*?href="#([^"]+)"', out, re.S).group(1)
    live = R._blank_inert(out)
    assert f'id="{first}"' in live and '전략 코멘트' in live[live.index(f'id="{first}"'):][:200]


def test_publish_order_keeps_the_editor_note_in_layer_one():
    # 셸 → apply_readability → apply_note(ORCHESTRATOR STEP 3.3) 순서 그대로
    from scripts.us import editor_note as N
    body = (HEADLINE + _sec('전략 코멘트') + _sec('오늘의 장') + _sec('매크로')
            + _sec('트렌드 유닛 점검') + _sec('시장 판단과 복기'))
    meta = {'title': '미국 증시 마감 시황 — 핵심 | 2026-11-02', 'summary': '요약.'}
    page = R.enhance_html(S.render('us', P.PARTS_FROM, meta, body))
    page = N.apply_note(page, N.render_note('# 노트\n\n발행자의 의견이다.', P.PARTS_FROM))
    assert page.index('전략 코멘트') < page.index('editor-note') < page.index('id="part-2"')
    assert R.enhance_html(page).count('class="part-head"') == 3          # 재조판해도 머리는 그대로
    assert R.enhance_html(page).count('reading-map-v1') == 1


def test_commented_strategy_with_a_reused_id_is_ignored():
    # codex 3차 확인 2026-10-31 — 주석 속 사본이 실제 섹션의 id 를 쓰면 그 섹션으로 끌려갔다
    body = ('<!-- <section id="read-3"><h2>전략 코멘트</h2></section> -->' + HEADLINE
            + '<section class="card" id="real"><h2>전략 코멘트</h2><p>판단이다.</p></section>\n'
            + _sec('오늘의 장') + _sec('매크로'))
    out = R.inject_reading_map('<div class="doc">' + P.mark(body, 'us') + '</div>')
    assert re.search(r'<nav class="reading-map".*?href="#([^"]+)"', out, re.S).group(1) == 'real'
