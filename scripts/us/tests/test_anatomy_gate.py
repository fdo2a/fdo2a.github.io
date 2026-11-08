"""The anatomy block's boundary and what counts as evidence for a component (2026-11-08)."""
import os

import pytest

from us import anatomy_gate as G, release_blocks as B
from us.macro_gate import _cited_distinct, _figures, check, section_macro, structured_figures
from us.tests.test_macro_gate import build_html, eval_file, macro_file, next_file

POSTS = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'posts')


# ------------------------------------------------------------------ boundary

def _card(inner):
    return f'<section><h2>매크로</h2><div class="card"><h3>물가</h3>{inner}</div></section>'


def test_a_block_is_its_div_and_nothing_after_it():
    html = _card('<div data-release="cpi"><p>주거비 0.4%</p></div>'
                 '<div class="tbl-scroll"><table><tr><td>1 2 3 4 5</td></tr></table></div>')
    blocks, problems = B.parse(html)
    assert problems == [] and blocks['cpi']['text'] == '주거비 0.4%'


def test_the_10_27_block_no_longer_swallows_the_next_axis_table():
    path = os.path.join(POSTS, '2026-10-27.html')
    if not os.path.exists(path):
        pytest.skip('post not in this checkout')
    blocks, problems = B.parse(section_macro(open(path, encoding='utf-8').read()))
    assert problems == []
    assert len(_figures(blocks['new-home-sales']['text'])) < 15


@pytest.mark.parametrize('inner,word', [
    ('<div data-release="cpi"><p>a</p><div data-release="ppi">b</div></div>', '안에 다른 표식'),
    ('<div data-release="cpi"><div data-macro-group="rates">b</div></div>', '안에 다른 표식'),
    ('<div data-release="cpi">a</div><div data-release="cpi">b</div>', '두 번'),
    ('<p data-release="cpi">a</p>', 'div 에만'),
    ('<div data-release="cpi"><p>a', '짝이 맞지 않는다'),
])
def test_malformed_blocks_are_violations(inner, word):
    _, problems = B.parse(_card(inner))
    assert any(word in p for p in problems), problems


def test_a_block_outside_any_card_is_a_violation():
    _, problems = B.parse('<section><h2>매크로</h2><div data-release="cpi">a</div></section>')
    assert any('카드' in p for p in problems)


def test_without_blocks_cuts_exactly_the_blocks():
    html = _card('<p>keep</p><div data-release="cpi"><p>drop</p></div><p>keep2</p>')
    out = B.without_blocks(html)
    assert 'drop' not in out and 'keep' in out and 'keep2' in out


# ------------------------------------------------------------------ evidence

COMPS = [
    {'label': '주거비', 'aliases': ['주거비', '주거'], 'actual': 0.4, 'cite_values': [0.4],
     'unit': '%'},
    {'label': '에너지', 'aliases': ['에너지'], 'actual': 5.2, 'cite_values': [5.2], 'unit': '%'},
    {'label': '헬스케어', 'aliases': ['헬스케어'], 'actual': 42000,
     'cite_values': [42000, 42, 4.2], 'unit': '명'},
]
REL = {'key': 'cpi', 'label': '소비자물가(CPI)', 'components': COMPS,
       'indicators': [{'name': 'CPI MoM', 'actual': 0.6, 'previous': 0.4}]}


@pytest.mark.parametrize('text,want', [
    ('주거비는 0.4% 올랐고, 에너지는 5.2% 뛰었다.', ['주거비', '에너지']),
    ('주거비는 전월 0.3%에서 0.4%로 올랐다.', ['주거비']),
    ('주거비는 0.3%에서 0.5%로 올랐다.', []),                      # 0.4 is not there
    ('주거비가 0.4%p 올랐다.', []),                                # a change in size
    ('전월 주거비는 0.4%였다.', []),                               # last month's item
    ('주거비는 0.4% 오를 것으로 예상됐다.', []),                    # forecast
    ('에너지는 5.2%로, 다음 달에도 비슷할 전망이다.', []),            # forecast in the sentence
    ('주거비와 에너지가 0.4%, 5.2% 올랐다.', []),                   # two names, one clause
    ('주거비 0.4', []),                                           # a percent with no %
    ('헬스케어는 4.2만 명 늘었다.', ['헬스케어']),
    ('헬스케어가 42,000명 늘었다.', ['헬스케어']),
])
def test_what_counts_as_evidence(text, want):
    assert G.evidenced(text, REL) == want


def test_a_component_figure_equal_to_a_headline_figure_needs_its_own_clause():
    # 주거비 0.4 equals the headline's previous 0.4.
    assert G.evidenced('주거비는 0.4%로 소비자물가 둔화를 거슬렀다.', REL) == []
    assert G.evidenced('소비자물가는 0.6%였다. 주거비는 0.4% 올랐다.', REL) == ['주거비']


def test_a_component_named_as_part_of_a_longer_name_is_the_longer_one():
    comps = [{'label': '주거용', 'aliases': ['주거용'], 'actual': -5.5, 'cite_values': [-5.5],
              'unit': '%'},
             {'label': '비주거용', 'aliases': ['비주거용'], 'actual': 1.1, 'cite_values': [1.1],
              'unit': '%'}]
    rel = {'components': comps, 'indicators': []}
    assert G.evidenced('비주거용은 1.1% 늘었다.', rel) == ['비주거용']


def test_a_component_named_with_a_forecast_word_is_not_a_forecast():
    comps = [{'label': '6개월 뒤 전망', 'aliases': ['6개월 뒤'], 'actual': 33.0,
              'cite_values': [33.0], 'unit': ''}]
    rel = {'components': comps, 'indicators': []}
    assert G.evidenced('6개월 뒤 전망 지수는 33.0으로 내려왔다.', rel) == ['6개월 뒤 전망']


# --------------------------------------------------------------- by status

def _block(status, text, comps=COMPS):
    rel = dict(REL, anatomy_status=status, components=comps if status in ('complete', 'partial')
               else [])
    primary = rel['indicators'][0]
    return G.check_block('cpi', 'CPI', text, rel, len(_figures(text)),
                         structured_figures(rel, primary), _cited_distinct)


def test_complete_needs_two_evidenced_components():
    assert _block('complete', '주거비는 0.4% 올랐고, 에너지는 5.2% 뛰었다.') == []
    v = _block('complete', '주거비는 0.4% 올랐다. 에너지 5.2 3 4')
    assert v and '1개만' in v[0] and '한 구절' in v[0]


def test_partial_needs_its_one_component_and_three_figures():
    one = COMPS[:1]
    assert _block('partial', '주거비는 0.4% 올랐다. 0.6 1.2', one) == []
    assert _block('partial', '주거비는 0.4% 올랐다.', one)
    assert _block('partial', '물가는 0.6%, 1.2, 3.3', one)


def test_text_needs_three_figures_and_none_the_canonical_ones():
    assert _block('text', '0.6, 1.2, 3.3') == []
    assert _block('text', '0.6')
    assert _block('none', 'CPI 0.6%, 전월 0.4%.') == []
    assert _block('none', 'CPI 0.6%.')


# ------------------------------------------------------ through check()

def _rel_eval(status, components):
    ev = eval_file()
    ev['headline_releases'] = [{
        'key': 'cpi', 'label': '소비자물가(CPI)', 'tier': 1, 'agency': 'BLS', 'role': 'scored',
        'primary': 'CPI MoM', 'anatomy_status': status, 'components': components,
        'indicators': [{'name': 'CPI MoM', 'actual': 0.6, 'previous': 0.4,
                        'ref_period': '2026-09-01'}]}]
    return ev


def _merged(block):
    return build_html(extra=f'<div class="card"><h3>물가</h3>{block}</div>').replace(
        '<section><h2>13. 경제지표 대시보드</h2><table><tr><td>CPI YoY</td></tr></table></section>',
        '')


def test_check_passes_a_block_that_names_two_components():
    block = ('<div data-release="cpi"><p>BLS 9월 CPI는 0.6% 올랐다. 주거비는 0.4% 올랐고, '
             '에너지는 5.2% 뛰었다.</p></div>')
    assert check(_merged(block), macro_file(), _rel_eval('complete', COMPS[:2]), next_file()) == []


def test_check_blocks_values_without_their_items():
    block = ('<div data-release="cpi"><p>BLS 9월 CPI는 0.6% 올랐다. 0.4%와 5.2%가 '
             '움직였다.</p></div>')
    out = check(_merged(block), macro_file(), _rel_eval('complete', COMPS[:2]), next_file())
    assert any('근거' in x for x in out)
