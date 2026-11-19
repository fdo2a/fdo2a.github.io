"""One table of hidden / not-hidden elements, run through the shared judgement (common.hidden) and
through every publishing gate's real path — a gate that stops seeing one of these fails here.

2026-11-19: the gates each had their own list and a hole closed in one stayed open in the others.
Design and measurements: plans/2026-11-19-hidden-text.md (outside the repo)."""
import os
import re

import pytest

from common import hidden as H
from common import movers as M
from common.telegram_gate import check as tg_check
from fund.gate import _Doc
from japan import daily_news_gate as JDN
from kr import stance_gate as SG
from us import auction_gate as AG
from us import liquidity_gate as LG
from us import news_gate as NG
from us import price_gate as PG
from us.number_audit import _Stream, core_hidden_tokens, tokens

from common.tests import test_contested as TC
from common.tests import test_telegram_news_layout as TT

HIDDEN = [
    'hidden', 'hidden="until-found"', 'inert', 'aria-hidden="true"', 'aria-hidden="TRUE"',
    'class="sr-only"', 'class="x SR-ONLY"', 'class="visually-hidden"', 'class="screen-reader-text"',
    'class="hidden"', 'class="hiden"',
    'style="display:none"', 'style="DISPLAY : NONE"', 'style="display/**/:none"', 'style="displ\\61y:none"',
    'style="color:red; display:none !important"',
    'style="visibility:hidden"', 'style="visibility:collapse"', 'style="content-visibility:hidden"',
    'style="opacity:0"', 'style="opacity:.0"', 'style="opacity:0.0"', 'style="opacity:0%"',
    'style="opacity:0e0"', 'style="opacity:0.05"', 'style="opacity:0.09"', 'style="opacity:-1"',
    'style="opacity:0 !important"',
    'style="font-size:0"', 'style="font-size:0px"', 'style="font-size:.0em"', 'style="font-size:0.05rem"',
    'style="width:0"', 'style="width:0%"', 'style="height:0px"', 'style="max-height:0"', 'style="max-width:0"',
    'style="color:transparent"', 'style="color:rgba(0,0,0,0)"', 'style="color:rgb(0 0 0 / 0)"',
    'style="color:#0000"', 'style="color:#ffffff00"',
    'style="clip:rect(0,0,0,0)"', 'style="clip-path:inset(50%)"',
    'style="text-indent:-9999px"', 'style="transform:scale(0)"', 'style="left:-9999px"', 'style="top:-200px"',
    'style="display:none" style=""', 'style="" style="display:none"',
    # not hidden in a browser (the declaration is invalid and dropped) — hidden here on purpose: a value
    # this module cannot read with certainty blocks (see UNSURE below)
    'style="opacity:0px"', 'style="width:-1px"',
]
NOT_HIDDEN = [
    'class="caption"', 'class="hiddenish"', 'aria-hidden="false"', 'title="display:none"', 'data-hidden="1"',
    'style="opacity:.5"', 'style="opacity:0.1"', 'style="opacity:1"', 'style="opacity:100%"',
    'style="width:50%"', 'style="font-size:12px"',
    'style="font-size:0.5em"', 'style="display:flex"', 'style="display:block"', 'style="text-indent:0"',
    'style="color:#e5342b"', 'style="color:inherit"', 'style="margin-left:auto"', 'style="max-width:1120px"',
    'style="min-width:0"', 'style="line-height:0"', 'style="border-width:0"', 'style="overflow:hidden"',
    'style="clip-path:none"', 'style="background-color:transparent"', 'style="--x-display:none"',
    'style="transform:scale(1)"', 'style="left:-10px"',
]


def attrs_of(attr):
    got = H.start_tag(f'<p {attr}>')
    return got[1]


@pytest.mark.parametrize('attr', HIDDEN)
def test_core_hides(attr):
    assert H.is_hidden(attrs_of(attr))


@pytest.mark.parametrize('attr', NOT_HIDDEN)
def test_core_does_not_hide(attr):
    assert not H.is_hidden(attrs_of(attr))


def test_a_dict_is_accepted_too():
    assert H.is_hidden({'style': 'opacity:.0'}) and not H.is_hidden({'style': 'opacity:.5'})


# ── every gate's real path: the violation it adds fires on HIDDEN, not on NOT_HIDDEN ────────────────

def news(attr):
    html = (f'<h2>{NG.TITLE}</h2><div class="news-item" data-news="g1"><p>기사 요약이다.</p>'
            f'<span {attr}>가</span></div>')
    return any('숨긴 요소가 있다' in x for x in NG.check(html, {'items': []}))


def japan_daily(attr):
    html = f'<section data-section="news"><h2 {attr}>{JDN.TITLE}</h2></section>'
    return any('news 절 안' in x for x in JDN.check(html, {'items': []}, '2026-11-18'))


def telegram_news(attr):
    html = TT.page(TT.section(TT.P_VIEW.replace('<p>', f'<p {attr}>'), ))
    return any('숨겨져 있다' in x for x in TT.run(html))


def telegram_brief(attr):
    html = f'<div class="doc"><p><span data-tg="a/1" {attr}>필자는 반등을 본다.</span></p></div>'
    return any('data-tg="a/1" 인용' in x for x in tg_check(html, None))


def contested(attr):
    p = TC.payload()
    html = TC.published(p)
    sec = TC._sec(html)
    # contested keeps ancestors as dicts; a duplicated attribute is its own violation there (「중복 속성」)
    return any('보이지 않는 조상' in x or '중복 속성' in x
               for x in TC.gate(html.replace(sec, f'<div {attr}>{sec}</div>'), p))


def price(attr):
    return any('표식 블록' in x for x in PG.check(f'<p data-forward="1" {attr}>5.02%</p>', None))


def auction(attr):
    doc = f'<div {attr}><section><h2>국채 입찰</h2><p>x</p></section></div>'
    return bool(AG._hidden_ancestor(doc, doc.index('<section')))


def liquidity(attr):
    doc = f'<div {attr}><section><h2>유동성·수급</h2><p>x</p></section></div>'
    return bool(LG._hidden_ancestor(doc, doc.index('<section')))


def number_audit(attr):
    doc = _Stream(f'<html><body><p {attr}>지수는 7.77% 올랐다.</p></body></html>')
    return bool([t for d in doc.hidden_text for t in tokens(d)] + core_hidden_tokens(doc))


def fund_doc(attr):
    doc = _Doc(f'<section><p {attr}>x</p></section>', 'data-x')
    return any(n.core_hidden for n in doc.nodes)


def stance_layout(attr):
    html = f'<section><h2>{SG.LEARNING}</h2><p data-lede="review" {attr}>어제 판단은 맞았다.</p></section>'
    v, _review = SG.check_layout_v2(html)
    return any('섹션이나 그 안·바깥 요소가 숨겨져' in x for x in v)


def stance_lede(attr):
    return bool(SG.hidden_ledes(f'<h2>{SG.SECTION}</h2><p data-lede="call" {attr}>판단이다.</p><h2>다음</h2>'))


MOVERS = {"report_date": "2026-09-23", "groups": [
    {"id": "g1", "industry": "반도체", "direction": "up", "members": [{"name": "삼성전자", "change_pct": 3.25}]}]}


def movers(attr):
    html = f'<html><body><div class="doc"><p data-mover="g1">반도체(삼성전자 <span {attr}>+3.25%</span>)</p></div></body></html>'
    return any('숨겨져 있다' in x for x in M.check(html, MOVERS, '2026-09-23'))


GATES = [news, japan_daily, telegram_news, telegram_brief, contested, price, auction, liquidity,
         number_audit, fund_doc, stance_layout, stance_lede, movers]


@pytest.mark.parametrize('gate', GATES, ids=lambda g: g.__name__)
@pytest.mark.parametrize('attr', HIDDEN)
def test_every_gate_blocks_hidden(gate, attr):
    assert gate(attr), attr


# Where a gate's own frozen predicate *is* its hidden violation (telegram, contested), the regex side
# effects it always had still block there — kept so no gate blocks less (2026-11-19 decision). Measured
# with the grid in plans/2026-11-19-hidden-text.md; remove one only with a corpus diff.
FROZEN_QUIRKS = {
    'telegram_news': {'style="min-width:0"', 'style="line-height:0"', 'style="border-width:0"',
                      'style="clip-path:none"', 'style="background-color:transparent"', 'style="--x-display:none"'},
    'contested': {'style="opacity:0.1"', 'style="--x-display:none"'},
}


@pytest.mark.parametrize('gate', [g for g in GATES if g not in (auction, liquidity, number_audit)],
                         ids=lambda g: g.__name__)
@pytest.mark.parametrize('attr', NOT_HIDDEN)
def test_every_gate_lets_visible_through(gate, attr):
    assert gate(attr) == (attr in FROZEN_QUIRKS.get(gate.__name__, ())), attr


@pytest.mark.parametrize('gate', [auction, liquidity, number_audit], ids=lambda g: g.__name__)
@pytest.mark.parametrize('attr', [a for a in NOT_HIDDEN if 'display:none' not in a and a != 'data-hidden="1"'
                                  and 'hidden' not in a.split('=')[0]])
def test_raw_and_stream_gates_let_visible_through(gate, attr):
    # auction/liquidity keep their raw regex (it also reads `title="display:none"`); number_audit is fine
    assert not gate(attr), attr


# ── the ways round 1 / round 2 of the codex design review broke a widening — each still blocks ────────

def test_auction_raw_regex_still_reads_a_tag_inside_a_script_string():
    doc = '<script>let s = "<span style=\'display:none\'>";</script><section><h2>국채 입찰</h2></section>'
    assert AG._hidden_ancestor(doc, doc.index('<section'))


def test_price_marker_folded_in_closed_details_blocks():
    html = '<details><summary>근거</summary><p data-forward="1">9월 3일 기준 5.02%</p></details>'
    assert any('표식 블록' in x for x in PG.check(html, None))
    assert not any('표식 블록' in x for x in PG.check(html.replace('<details>', '<details open>'), None))
    assert not any('표식 블록' in x for x in
                   PG.check('<details><summary><b data-forward="1">5.02%</b></summary></details>', None))


def test_news_inert_link_is_both_read_and_blocked():
    html = (f'<h2>{NG.TITLE}</h2><div class="news-item" data-news="g1"><p>요약.</p>'
            '<a inert href="https://wrong.example/">가</a></div>')
    doc = NG._read(html)
    assert doc.items[0]['links'] == ['https://wrong.example/']      # read as before
    assert any('숨긴 요소가 있다' in x for x in NG.check(html, {'items': []}))


def test_number_audit_keeps_the_stream_and_counts_core_hidden_apart():
    doc = _Stream('<html><body><p><span inert>VIX</span> 5% 올랐다.</p></body></html>')
    assert 'VIX' in ''.join(d for d, *_ in (x for x in doc.stream if x))     # still read
    assert [t.raw for t in core_hidden_tokens(doc)] == [] and doc.hidden_text == []
    doc = _Stream('<html><body><p><span style="opacity:.0">7.77%</span></p></body></html>')
    assert [t.raw for t in core_hidden_tokens(doc)] and doc.hidden_text == []


def test_post_shell_parts_are_not_in_any_scope():
    # the shell's pager links (hidden until a script fills them) and breadcrumb separator sit outside every
    # gate scope; the zero-width bars of the KR sector chart are empty
    html = ('<html><body><nav><span class="crumbs-sep" aria-hidden="true">›</span>'
            '<a class="pf-next" hidden>다음 글 ›</a></nav><div class="doc">'
            f'<h2>{NG.TITLE}</h2><div class="news-item" data-news="g1"><p>요약.</p></div></div>'
            '<span class="spf-bar"><i style="width:0%;"></i></span></body></html>')
    assert not any('숨긴 요소' in x for x in NG.check(html, {'items': []}))
    assert not core_hidden_tokens(_Stream(html))


# ── a future gate must use common/hidden.py, not its own list ───────────────────────────────────────

SCRIPTS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_OWN_RULE = re.compile(r"(?:display|visibility|opacity|font-size)\\s\*:"            # a regex of its own
                       r"|'(?:display:none|visibility:hidden|opacity:0|content-visibility:hidden)' in")
# The predicates frozen on 2026-11-19 (each gate still reads with its own; see common/hidden.py), and the
# typesetting code that writes or diffs CSS rather than judging elements. Counts are exact: a new rule
# here fails the test — put it in common/hidden.py instead.
FROZEN = {   # = origin/main on 2026-11-19, unchanged by this work
    'common/contested.py': 4, 'common/movers.py': 2, 'common/telegram_gate.py': 1, 'fund/gate.py': 2,
    'review/prose.py': 7, 'us/auction_gate.py': 2, 'us/census_calendar.py': 2, 'us/liquidity_gate.py': 2,
    'us/news_gate.py': 4, 'us/number_audit.py': 2, 'us/price_gate.py': 3, 'us/readability.py': 2,
}


def test_no_gate_keeps_its_own_hidden_rule():
    found = {}
    for root, dirs, files in os.walk(SCRIPTS):
        dirs[:] = [d for d in dirs if d not in ('tests', '__pycache__')]
        for f in files:
            if f.endswith('.py'):
                path = os.path.join(root, f)
                n = len(_OWN_RULE.findall(open(path, encoding='utf-8').read()))
                if n:
                    found[os.path.relpath(path, SCRIPTS)] = n
    assert found == FROZEN


# ── full entry points with real inputs (published fixtures, the gates' own test builders) ────────────
# The table above reaches some gates through a part of their path; these run the whole check so a
# violation that is computed but never reported, or scoped wrong, fails too. A representative subset
# keeps the slower audits fast.

REAL_HIDDEN = ['inert', 'aria-hidden="true"', 'class="sr-only"', 'style="opacity:.0"', 'style="opacity:0%"',
               'style="font-size:0"', 'style="display/**/:none"', 'style="color:rgba(0,0,0,0)"',
               'style="clip-path:inset(50%)"', 'style="transform:scale(1,0)"', 'style="display:none" style=""']
REAL_VISIBLE = ['class="caption"', 'style="opacity:.5"', 'style="min-width:0"', 'style="clip-path:inset(0)"',
                'style="opacity:0; opacity:1"', 'style="width:0; width:100%"']


def auction_check(attr):
    from us.tests import test_auctions as TA
    b = TA._book()
    html = TA.post(b, blk=TA.block(b) + f'<span {attr}>가</span>')
    return any('섹션 안에 숨긴 요소' in x for x in AG.check(html, b, TA.RD))


def auction_around(attr):
    from us.tests import test_auctions as TA
    b = TA._book()
    html = TA.post(b)
    i, j = html.index('<section data-auction-day'), html.index('<section><h2>FX')
    html = html[:i] + f'<div {attr}>' + html[i:j] + '</div>' + html[j:]
    return any('섹션을 숨긴 요소가 감싸고' in x for x in AG.check(html, b, TA.RD))


def liquidity_check(attr):
    from us.tests import test_liquidity_gate as TL
    b = TL.book()
    html = TL.post(b).replace('<h2>유동성·수급</h2>', f'<h2>유동성·수급</h2><span {attr}>가</span>', 1)
    return any('섹션 안에 숨긴 요소' in x for x in LG.check(html, b, TL.RD, TL.NO_LEDGER))


def fund_check(attr):
    from fund import gate as FGATE
    from fund.tests import test_gate as TF
    board = TF.build_board()
    html = TF.us_post(board, extra=f'<p {attr}>메모다.</p>')
    return any('섹션이나 그 안·바깥 요소가 숨겨져' in x for x in TF.check_us(html, board))


def us_audit(attr):
    from us.tests import test_number_audit as TN
    html = TN.load('post.html').replace('</body>', f'<p><span {attr}>7.77%</span></p></body>', 1)
    data = {k: TN.load(f'{k}.json') for k in ('market_data', 'econ_indicators', 'macro_metrics', 'fund_board')}
    return any('숨긴 요소 안에 수치 「7.77%」' in x for x in TN.run(html, data).violations)


def kr_audit(attr):
    from kr.tests import test_number_audit as TK
    html = TK.html_of().replace('</body>', f'<p><span {attr}>7.77%</span></p></body>', 1)
    return any('숨긴 요소 안에 수치 「7.77%」' in x for x in TK.run(html, TK.data_of()).violations)


def kr_map_table(attr):
    from kr.tests import test_number_audit as TK
    html = TK.sub(TK.html_of(), '<td>코스피</td>', f'<td>코스피<b {attr}></b></td>')
    return any('지도 표나 그 안·바깥 요소가 숨겨져' in x for x in TK.run(html, TK.data_of()).violations)


def japan_weekly(attr):
    from japan import gate as JGATE
    html = f'<section data-section="news"><h2>{JGATE.NEWS_TITLE}</h2><p {attr}>메모.</p></section>'
    return any('news 절 안' in x for x in JGATE.check_news(html, {}, ['news'], []))


def news_title(attr):
    html = (f'<h2><span {attr}>{NG.TITLE}</span></h2><div class="news-item" data-news="g1"><p>요약.</p></div>')
    return any('숨긴 요소가 있다' in x for x in NG.check(html, {'items': []}))


REAL = [auction_check, auction_around, liquidity_check, fund_check, us_audit, kr_audit, kr_map_table,
        japan_weekly, news_title]


@pytest.mark.parametrize('gate', REAL, ids=lambda g: g.__name__)
@pytest.mark.parametrize('attr', REAL_HIDDEN)
def test_entry_point_blocks_hidden(gate, attr):
    assert gate(attr), attr


@pytest.mark.parametrize('gate', REAL, ids=lambda g: g.__name__)
@pytest.mark.parametrize('attr', REAL_VISIBLE)
def test_entry_point_lets_visible_through(gate, attr):
    assert not gate(attr), attr


# round-1 implementation review: later declarations, void elements, hidden void descendants
def test_a_later_valid_declaration_wins():
    assert not H.style_hides('opacity:0; opacity:1') and not H.style_hides('width:0; width:100%')
    assert H.style_hides('opacity:1; opacity:0') and H.style_hides('opacity:0 !important; opacity:1')
    assert not H.style_hides('opacity:0; opacity:1 !important') and not H.style_hides('display:none; display:revert')


def test_a_hidden_void_element_encloses_nothing():
    doc = '<img style="opacity:0"><p data-mover="g1">x</p>'
    assert H.hidden_ancestor(doc, doc.index('<p')) is None
    assert H.fragment_hidden('<p data-mover="g1">x<img style="opacity:0"></p>', 0, 44)


def test_price_sees_a_hidden_void_descendant_of_a_marker():
    assert any('표식 블록' in x for x in PG.check('<p data-forward="1">글<img style="opacity:0"></p>', None))


# ── round-2 implementation review: what cannot be read with certainty blocks (fail closed) ───────────
# Not a CSS engine. Any declaration of a judged property — winning or not — whose value is invalid, or
# valid but not evaluated here (var, calc, env, attr …), makes the element count as hidden; so does a
# style that cannot be cut into declarations with certainty. Every case below is one where "later
# declaration wins" and a browser disagree, or would need real CSS evaluation to settle.
UNSURE = [
    'width:.0; width:1banana', 'display:none; display:block flex',                       # round 2 #1
    '--x:garbage; opacity:0; opacity:var(--x)', '--x:garbage; opacity:1; opacity:var(--x, 0)',   # #2
    '--X:0; opacity:var(--x)', 'opacity:var(--undefined)', '--x:0; opacity:var(--x)',             # #3
    'opacity:1; opacity:x', 'opacity:0; opacity:1.', 'opacity:0; opacity:1 !importan',
    'opacity:0; opacity:1 !important !important', 'opacity:0; opacity:', 'opacity:0; opacity:1 1',
    'opacity:0; opacity:1\xa0', 'opacity:0; opacity:\u0661', 'opacity:0; opacity:1\x0b',
    'width:0; width:calc(100% - 2px)', 'width:0; width:env(x, 1px)', 'width:0; width:attr(w px)',
    'width:0; width:min(1px, 2px)', 'width:0; width:100', 'width:0; width:1dvh', 'height:0; height:-1px',
    'font-size:0; font-size:xxx-large', 'display:none; display:run-in', 'display:none; display:banana',
    'visibility:hidden; visibility:visble', 'content-visibility:hidden; content-visibility:shown',
    'color:transparent; color:notacolor', 'color:transparent; color:blac\u212a', 'color:transparent; color:rgb(0,,0)',
    'color:transparent; color:rgb(0, 0%, 0)', 'color:transparent; color:rgb(0 0 0 / )', 'color:transparent; color:#12345',
    'color:transparent; color:hsl(0, 0, 0)', 'color:transparent; color:oklch(50% 0.1 20)',
    'color:transparent; color:color-mix(in srgb, red, blue)', 'color:transparent; color:rgb(1%% 0 0)',
    'transform:scale(0); transform:matrix(1,0,0,1,0,0)', 'transform:scale(0); transform:scale()',
    'transform:scale(0); transform:scale(1 1)', 'transform:scale(0); transform:scale(1) banana',
    'transform:scale(0); transform:translate(calc(1px))', 'scale:0; scale:1 1 1 1', 'scale:0; scale:1px',
    'text-indent:-9999px; text-indent:5', 'left:-9999px; left:1furlong', 'top:-9999px; top:calc(0px)',
    # the cut itself: escapes, comments, strings, blocks — a browser reads these differently from a split on `;`
    'opacity:0; opacity:1\\3b', 'opacity:0; opacity:1/**/0', 'opacity:0; x:{; opacity:1; }',
    'opacity:0; x:[; opacity:1; ]', 'opacity:0; @media x; opacity:1', 'opacity:0; x:"\n; opacity:1',
    'opacity:0; x:url(a"b); opacity:1; y:"', 'opacity:0; x:url(a(b); opacity:1', 'opacity:0; x:); opacity:1',
    'opacity:0; x:"unclosed; opacity:1', 'opacity:0; x:(unclosed; opacity:1', 'opacity:0; x:url(; opacity:1',
    'color:red; b\\61 ckground:x', '--x:{a;b}',
]
CERTAIN_VISIBLE = [
    "font-family:'Courier New'; font-weight:bold", "width:616px;background-image:url('https://e.example/a;b')",
    'background:url(data:image/png;base64,AAAA); width:50%', 'background:URL( "a)b" ); opacity:1',
    'margin:var(--m); padding:calc(1px + 2px); background:var(--x)',     # not a judged property
    'opacity:1; OPACITY : 0.5 ; opacity:100%', 'opacity:0; opacity:1 ! important; opacity:0',
    'width:12.5pt; height:auto; max-width:1120px; max-height:none; font-size:0.9em; font-size:small',
    'color:#e5342b; color:RED; color:rgb(1, 2, 3); color:rgba(1, 2, 3, .5); color:rgb(1 2 3 / 50%)',
    'color:hsl(120, 50%, 50%); color:hsla(120deg 50% 50% / 1); color:#fff8; color:currentColor',
    'transform:translateY(-2px) rotate(3deg) scale(1.2, 1)', 'transform:none', 'scale:1 1', 'scale:none',
    'clip:auto', 'clip-path:inset(0 0px)', 'clip-path:inset(50%); clip-path:none', 'clip:banana; clip:auto',
    'text-indent:17.75pt', 'left:auto; top:0', 'display:table-cell', 'visibility:visible', 'content-visibility:auto',
    'opacity:1;;; ;garbage; opacity', '',
]
CERTAIN_HIDDEN = [
    'opacity:1; opacity:0', 'width:100%; width:0 !important; width:50%', 'color:rgba(0,0,0,0.05)',
    'color:#ffffff10', 'color:hsl(0 0% 0% / 0)', 'transform:translate(1px) scale(1, 0.0e0)', 'transform:scaleY(0)',
    'scale:1 0', 'clip-path:inset(50%); clip-path:inset()', 'clip-path:inset(50%); clip-path:inset(0banana)',
    'clip:auto; clip:banana',
    # a `;` inside a string or parentheses does not end a declaration — the later opacity is not one
    'opacity:0; x:"; opacity:1; "', "opacity:0; x:'; opacity:1; '", 'opacity:0; x:(; opacity:1; )', 'clip-path:none; clip-path:circle(0)', 'text-indent:-8.8pt', 'font-size:0.05rem',
]


# round-3 implementation review: a judged property that moves the element off the page, either way, in any
# unit; and text too small to read. A relative unit (em, %, vw …) is taken at its largest plausible size.
FAR_OR_TINY = [
    'transform:translateX(-9999px)', 'transform:translate(0, 9999px)', 'transform:translateY(-99vh)',
    'transform:scale(1) translate(-300%)', 'position:absolute; left:-99vw', 'left:100vw', 'left:-75pt', 'top:-9em',
    'right:9999px', 'bottom:-200px', 'right:100%', 'translate:-9999px', 'translate:0 -200vh', 'translate:0 0 0; translate:5in',
    'text-indent:9999px', 'text-indent:100%', 'font-size:1px', 'font-size:2pt', 'font-size:0.1em', 'font-size:10%',
    'font-size:.5vw',
]
NEAR_AND_READABLE = [
    'transform:translateX(-2px)', 'transform:translate(1em, -1.5em)', 'left:-10px', 'top:-0.2em', 'right:0; bottom:auto',
    'translate:none', 'translate:2px -3px', 'translate:1px 1px 9999px', 'text-indent:26.8pt', 'text-indent:2em',
    'font-size:5.33pt', 'font-size:8pt', 'font-size:12px', 'font-size:0.5em', 'font-size:70%', 'font-size:smaller',
]
CERTAIN_VISIBLE += NEAR_AND_READABLE
CERTAIN_HIDDEN += FAR_OR_TINY
UNSURE += ['right:-9999px; right:1furlong', 'bottom:0; bottom:calc(1px)', 'translate:-9999px; translate:1px 2px 3px 4px',
           'translate:-9999px; translate:var(--t)', 'translate:-9999px; translate:1px 1px 5%',
           'transform:translateX(-9999px); transform:translateX(1)', 'transform:scale(0); transform:rotateX(90deg)']


@pytest.mark.parametrize('style', UNSURE)
def test_a_style_that_cannot_be_read_with_certainty_blocks(style):
    hides, why = H.style_verdict(style)
    assert hides and why.startswith(H.UNSURE), (style, why)
    assert H.is_hidden([('style', style)])


@pytest.mark.parametrize('style', CERTAIN_VISIBLE)
def test_a_plain_visible_style_is_read(style):
    assert H.style_verdict(style) == (False, None)


@pytest.mark.parametrize('style', CERTAIN_HIDDEN)
def test_a_plain_hiding_style_is_read(style):
    hides, why = H.style_verdict(style)
    assert hides and not why.startswith(H.UNSURE), (style, why)


def test_custom_property_names_keep_their_case():
    assert H.declarations('--X: A b ;--x:0; Color : RED !IMPORTANT') == [
        ('--X', 'A b', False), ('--x', '0', False), ('color', 'red', True)]
    assert H.declarations('a:"') is None


def test_every_inline_style_published_so_far_is_read():
    # the shapes found on the 352 pages in the repo on 2026-11-19 (counted with a parser) — none may be UNSURE
    for style in ('width:12.5%', 'color:#e5342b', 'color:#1a7', 'font-size:9pt', 'width:451.3pt', 'font-size:12.5px',
                  'height:14.2pt', 'max-width:720px', 'display:flex', 'text-indent:17.75pt', 'text-indent:-8.8pt',
                  'height:auto', 'color:inherit', 'display:block', 'max-width:100%', 'text-indent:0',
                  'display:inline-block', 'width:616px', "font-family:'Times New Roman'"):
        why = H.style_verdict(style)[1]
        assert not (why or '').startswith(H.UNSURE), style
    # the smallest and largest published: font-size 5.33pt-22pt, text-indent up to 26.8pt
    for style in ('font-size:5.33pt', 'font-size:22pt', 'text-indent:26.8pt', 'font-size:12px'):
        assert H.style_verdict(style) == (False, None), style


def test_the_message_says_when_the_css_was_only_unreadable():
    html = (f'<h2>{NG.TITLE}</h2><div class="news-item" data-news="g1"><p>기사 요약이다.</p>'
            '<span style="width:calc(100% - 2px)">가</span></div>')
    got = [x for x in NG.check(html, {'items': []}) if '숨긴 요소가 있다' in x]
    assert got and H.UNSURE in got[0] and 'width:calc(100% - 2px)' in got[0]
    assert H.unsure_note('<p style="display:none">x</p>') == ''
    assert H.UNSURE in ''.join(PG.check('<p data-forward="1" style="opacity:var(--o)">5.02%</p>', None))


# round 2 #4 — an element that can have no content encloses nothing, whatever each gate's own (frozen)
# list of void tags says. `before` is put ahead of the gate's scope, never around it.
def before_news(x):
    html = f'{x}<h2>{NG.TITLE}</h2><div class="news-item" data-news="g1"><p>기사 요약이다.</p></div>'
    return any('숨긴 요소가 있다' in v for v in NG.check(html, {'items': []}))


def before_japan_daily(x):
    html = f'{x}<section data-section="news"><h2>{JDN.TITLE}</h2></section>'
    return any('news 절 안' in v for v in JDN.check(html, {'items': []}, '2026-11-18'))


def before_japan_weekly(x):
    from japan import gate as JGATE
    html = f'{x}<section data-section="news"><h2>{JGATE.NEWS_TITLE}</h2><p>메모.</p></section>'
    return any('news 절 안' in v for v in JGATE.check_news(html, {}, ['news'], []))


def before_telegram_news(x):
    return any('숨겨져 있다' in v for v in TT.run(TT.page(x + TT.section())))


def before_telegram_brief(x):
    html = f'<div class="doc">{x}<p><span data-tg="a/1">필자는 반등을 본다.</span></p></div>'
    return any('data-tg="a/1" 인용' in v for v in tg_check(html, None))


def before_contested(x):
    p = TC.payload()
    html = TC.published(p)
    sec = TC._sec(html)
    return any('보이지 않는 조상' in v for v in TC.gate(html.replace(sec, x + sec), p))


def before_price(x):
    return any('표식 블록' in v for v in PG.check(f'{x}<p data-forward="1">5.02%</p>', None))


def before_auction(x):
    doc = f'{x}<section><h2>국채 입찰</h2><p>x</p></section>'
    return bool(H.hidden_ancestor(doc, doc.index('<section')))


def before_number_audit(x):
    return bool(core_hidden_tokens(_Stream(f'<html><body>{x}<p>지수는 7.77% 올랐다.</p></body></html>')))


def before_fund(x):
    doc = _Doc(f'{x}<section><p>x</p></section>', 'data-x')
    sec = next(n for n in doc.nodes if n.tag == 'section')
    return any(n.core_hidden and any(a is n for a in sec.ancestors()) for n in doc.nodes)


def before_stance_lede(x):
    return bool(SG.hidden_ledes(f'<h2>{SG.SECTION}</h2>{x}<p data-lede="call">판단이다.</p><h2>다음</h2>'))


def before_movers(x):
    html = f'<html><body><div class="doc">{x}<p data-mover="g1">반도체(삼성전자 +3.25%)</p></div></body></html>'
    return any('숨겨져 있다' in v for v in M.check(html, MOVERS, '2026-09-23'))


BEFORE = [before_news, before_japan_daily, before_japan_weekly, before_telegram_news, before_telegram_brief,
          before_contested, before_price, before_auction, before_number_audit, before_fund, before_stance_lede,
          before_movers]


@pytest.mark.parametrize('gate', BEFORE, ids=lambda g: g.__name__)
@pytest.mark.parametrize('tag', sorted(H.VOID))
def test_a_hidden_void_element_before_the_scope_hides_nothing(gate, tag):
    assert not gate(f'<{tag} inert>'), tag
    # telegram's own frozen predicate reads opacity, and its own void list has no `param` — as on origin/main
    assert gate(f'<{tag} style="opacity:0">') == ((gate, tag) == (before_telegram_news, 'param')), tag


@pytest.mark.parametrize('gate', [g for g in BEFORE if g is not before_contested], ids=lambda g: g.__name__)
def test_an_unclosed_hidden_element_before_the_scope_still_hides_it(gate):
    assert gate('<div inert>')
