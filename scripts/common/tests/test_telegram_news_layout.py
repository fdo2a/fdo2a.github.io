"""`check_telegram.py --layout news` — the 「증권사 견해·시장 의견」 section of the news posts (2026-11-12).
Design: docs/superpowers/specs/2026-11-12-telegram-news-posts.md"""
import json
import subprocess
import sys
import os

import pytest

from common.telegram_gate import NEWS_TITLE, check

SCRIPTS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

S_VIEW = '필자는 나스닥이 5.5% 급락한 배경을 금리보다 AI 투자 속도에 대한 의심에서 찾고, 실적 확인 전까지 변동성이 이어진다고 본다.'
S_REP = '로이터는 텍사스 주지사 당선인이 데이터센터 사업 중단을 요구했다고 보도했다. 전력과 용수 부담이 이유다.'
S_OP = '민주당 승리로 테슬라와 스페이스X 관련 규제가 강화될 수 있다는 시각이 전해졌다.'
S_CITED = '반도체 수요가 급증하고 공급이 빠르게 감소했다. 재고가 줄어 가격이 오를 수 있다는 의견이 제시됐다.'


def data(**over):
    items = [
        {'id': 'hedgecat0301/10', 'kind': 'view', 'firm': '키움증권', 'analyst': '한지영', 'source': None,
         'summary_ko': S_VIEW, 'news_use': True},
        {'id': 'insidertracking/7', 'kind': 'report', 'firm': None, 'analyst': None,
         'source': {'name': '로이터', 'url': 'https://www.reuters.com/x', 'basis': 'link'}, 'summary_ko': S_REP, 'news_use': True},
        {'id': 'kwusa/3', 'kind': 'opinion', 'firm': None, 'analyst': None,
         'source': {'name': '연합인포맥스', 'url': None, 'basis': 'credit'}, 'summary_ko': S_OP, 'news_use': True},
        {'id': 'd_ticker/9', 'kind': 'opinion', 'firm': None, 'analyst': None, 'source': None,
         'summary_ko': S_CITED, 'news_use': False, 'news_skip': 'cited'},
    ]
    for it in items:
        it.update(over.get(it['id'], {}))
    return {'report_date': '2026-11-11', 'items': items}


P_VIEW = '<p><span data-tg="hedgecat0301/10">키움증권 한지영 연구원은 나스닥이 5.5% 급락한 배경을 금리보다 AI 투자 속도에 대한 의심에서 찾았다.</span></p>'
P_REP = '<p><span data-tg="insidertracking/7">로이터에 따르면 텍사스 주지사 당선인은 데이터센터 사업 중단을 요구했다.</span></p>'
P_OP = '<p><span data-tg="kwusa/3">연합인포맥스를 인용해 민주당 승리로 테슬라 관련 규제가 강화될 수 있다는 시각도 나왔다.</span></p>'


def section(inner=P_VIEW + P_REP + P_OP, title=NEWS_TITLE, attrs=''):
    return f'<section data-tg-section{attrs}><h2>{title}</h2><div class="card">{inner}</div></section>'


NEWS_BLOCK = ('<section id="read-1"><h2>오늘의 뉴스</h2><div class="card"><div class="news-item" data-news="g1">'
              '<p class="news-head">알파벳, 홍콩 달러 채권 발행 검토<span class="sub">CNBC · 11월 11일</span></p>'
              '<p data-summary="g1">{summary}{link}</p></div></div></section>')
NEWS_SUMMARY = '알파벳이 홍콩 달러와 싱가포르 달러 표시 채권을 처음으로 발행하는 방안을 검토하고 있다. 조달 규모는 약 30억 달러다.'
NEWS = {'items': [{'guid': 'g1', 'summary_ko': NEWS_SUMMARY}]}


def page(*parts, news_summary=NEWS_SUMMARY, link=''):
    body = NEWS_BLOCK.format(summary=news_summary, link=link) + ''.join(parts)
    return f'<html><body data-register="da"><main><div class="doc">{body}</div></main></body></html>'


def run(html, d=None, news=NEWS, **kw):
    return check(html, data() if d is None else d, layout='news', news=news, **kw)


# ── passes ───────────────────────────────────────────────────────────────

def test_well_formed_section_passes_and_reports_pairs():
    pairs = []
    assert run(page(section()), pairs=pairs) == []
    assert [p[0] for p in pairs] == ['hedgecat0301/10', 'insidertracking/7', 'kwusa/3']
    assert pairs[0][2] == S_VIEW and pairs[0][1].startswith('키움증권 한지영')


def test_post_without_the_section_passes_with_or_without_a_file():
    assert run(page()) == []
    assert check(page(), None, layout='news', news=NEWS) == []


def test_visible_opacity_values_are_not_hidden():
    for val in ('1', '.5', '0.01', '100%'):
        assert run(page(section(P_VIEW.replace('<p>', f'<p style="opacity:{val}">')))) == [], val


def test_attributes_added_by_the_typesetter_are_fine():
    inner = P_VIEW.replace('<p>', '<p class="lead" style="margin:0 0 12px">')
    html = page(section(inner, attrs=' id="read-2" class="sec"').replace('<div class="card">', '<div class="card pad" id="x">'))
    assert run(html) == []


def test_brief_layout_is_unchanged_by_news_only_rules():
    # same markup, brief layout: news_use, the section shape and the outside-overlap FAIL do not apply
    d = data()
    for it in d['items']:
        it.pop('news_use', None)
    html = page('<p>' + P_VIEW[3:-4] + '</p>', '<p>' + S_REP + '</p>')
    warns = []
    assert check(html, d, warnings=warns) == []
    assert any('겹친다' in w for w in warns)


# ── section shape ────────────────────────────────────────────────────────

@pytest.mark.parametrize('html,needle', [
    (page(section(P_VIEW), section(P_REP)), '섹션이 2개'),
    (page(section(title='검증되지 않은 주장')), '모양'),
    (page(section().replace('</h2>', '</h2><h2>검증되지 않은 주장</h2>')), '모양'),
    (page(section(P_VIEW + '<p>표식 없는 문장이 섹션 안에 있다.</p>')), '모양'),
    (page(section(P_VIEW[3:-4])), '모양'),                                             # span without p
    (page(section(P_VIEW.replace('찾았다.', '찾았다. <a href="https://example.com">원문</a>'))), '모양'),
    (page(section(P_VIEW.replace('</span>', '<img src="x.png"></span>'))), '모양'),
    (page(section(P_VIEW + '<p>' + P_REP[3:-4] + '<b>굵게</b></p>')), '모양'),            # a tag that is not a marker
    (page(section('<p>표식보다 먼저 나오는 문단이지만 표식이 없다.</p>' + P_VIEW)), '모양'),
    (page(section(P_VIEW.replace('<span data-tg', '<span class="x"').replace('</p>', '</p>') + P_REP)), '모양'),  # a span that is not a marker
    (page(section(P_VIEW).replace('<div class="card">', '<div class="card">머리말 한 줄')), '모양'),
    (page(section(P_VIEW).replace('<div class="card">', '<div>')), '모양'),
    (page(section('')), '모양'),                                                       # empty section
    (page(section(P_VIEW), P_REP), '섹션 밖'),
    (page(P_VIEW), '섹션 밖'),
])
def test_section_shape_is_enforced(html, needle):
    v = run(html)
    assert any(needle in x for x in v), v


@pytest.mark.parametrize('html', [
    page(section(P_VIEW.replace('<span data-tg', '<span hidden data-tg'))),
    page(section(P_VIEW.replace('<p>', '<p style="display:none">'))),
    page(section(P_VIEW.replace('<span data-tg', '<span class="sr-only" data-tg'))),
    page(section(P_VIEW, attrs=' hidden')),
    page(section(P_VIEW, attrs=' style="font-size:0"')),
    page(section(P_VIEW.replace('<p>', '<p style="opacity:.0">'))),                 # codex 구현 검토 2회: 0 의 다른 표기
    page(section(P_VIEW.replace('<p>', '<p style="color:red; opacity: 0.00 !important">'))),
    page(section(P_VIEW.replace('<p>', '<p style="opacity:0%">'))),
    page(section(P_VIEW.replace('<p>', '<p style="opacity:0e0">'))),
    page('<div style="display: none">' + section(P_VIEW) + '</div>'),
    page('<details><summary>더 보기</summary>' + section(P_VIEW) + '</details>'),
    page('<template>' + section(P_VIEW) + '</template>'),
])
def test_hidden_quotes_fail(html):
    v = run(html)
    assert any('숨' in x for x in v), v


# ── eligibility, caps, length, overlap ───────────────────────────────────

def test_item_not_marked_for_news_use_fails_with_its_reason():
    cited = '<p><span data-tg="d_ticker/9">반도체 수요가 급증하고 공급이 빠르게 감소했다는 의견도 나왔다.</span></p>'
    v = run(page(section(P_VIEW + cited)))
    assert any('d_ticker/9' in x and 'cited' in x for x in v), v


def test_file_that_did_not_come_from_the_input_tool_fails():
    d = data()
    for it in d['items']:
        it.pop('news_use', None)
    v = run(page(section(P_VIEW)), d)
    assert any('tg_news.py' in x for x in v), v


def _many(n_views, n_others):
    """A file and a section with that many distinct views and opinions."""
    d = data()
    ps = []
    for i in range(n_views):
        d['items'].append({'id': f'kwusa/{100 + i}', 'kind': 'view', 'firm': '키움증권', 'analyst': '김승혁', 'source': None,
                           'summary_ko': f'필자는 {i + 2}분기 반도체 재고 조정이 끝나 간다고 보고 업황이 바닥을 지났다고 진단했다.', 'news_use': True})
        ps.append(f'<p><span data-tg="kwusa/{100 + i}">키움증권 김승혁 연구원은 {i + 2}분기 반도체 재고 조정이 끝나 가고 업황이 바닥을 지났다고 진단했다.</span></p>')
    for i in range(n_others):
        d['items'].append({'id': f'd_ticker/{200 + i}', 'kind': 'opinion', 'firm': None, 'analyst': None, 'source': None,
                           'summary_ko': f'가스터빈 수주가 {i + 40}GW 로 늘어 증설이 수요를 따라가지 못한다는 시각이 제시됐다.', 'news_use': True})
        ps.append(f'<p><span data-tg="d_ticker/{200 + i}">시장 일각에서는 가스터빈 수주가 {i + 40}GW 로 늘어 증설이 수요를 따라가지 못한다는 시각도 나왔다.</span></p>')
    return d, page(section(''.join(ps)))


def test_there_is_no_cap_on_the_number_of_paragraphs():
    """2026-11-12 사용자 지시 「뉴스 개수를 한정하지 말고 오늘 시장을 지배한 이슈나 중요도가 높다고 보여지는
    내용들은 포함할 수 있도록 하자. 분량은 좀 길어져도 괜찮아」 — 견해 3·그 밖 6 상한을 없앴다."""
    d, html = _many(7, 15)
    pairs = []
    assert run(html, d, pairs=pairs) == [] and len(pairs) == 22
    # the brief keeps its own caps
    d2, _ = _many(4, 0)
    brief = page(''.join(f'<p><span data-tg="kwusa/{100 + i}">키움증권 김승혁 연구원은 {i + 2}분기 반도체 재고 조정이 끝나 가고 '
                         f'업황이 바닥을 지났다고 진단했다.</span></p>' for i in range(4)))
    assert any('최대 3' in x for x in check(brief, d2))


def test_the_same_item_quoted_twice_fails():
    v = run(page(section(P_VIEW + P_REP + P_VIEW)))
    assert any('hedgecat0301/10' in x and '두 번' in x for x in v), v


def test_marker_longer_than_300_chars_fails():
    long_summary = S_OP + ' ' + '규제가 강화되면 발사 일정과 보조금에 영향이 갈 수 있다는 시각도 함께 전해졌다. ' * 6
    d = data(**{'kwusa/3': {'summary_ko': long_summary}})
    body = '연합인포맥스를 인용해 민주당 승리로 테슬라와 스페이스X 관련 규제가 강화될 수 있다는 시각도 나왔다. ' + \
           '규제가 강화되면 발사 일정과 보조금에 영향이 갈 수 있다는 시각도 함께 전해졌다. ' * 6
    assert len(body.strip()) > 300
    v = run(page(section(f'<p><span data-tg="kwusa/3">{body.strip()}</span></p>')), d)
    assert any('300자' in x for x in v), v
    cut = body.strip().index('전해졌다.', 200) + 5
    ok = body.strip()[:cut]
    assert 200 < len(ok) <= 300
    assert run(page(section(f'<p><span data-tg="kwusa/3">{ok}</span></p>')), d) == []


def test_overlap_floor_is_higher_than_the_brief():
    # coverage ~0.35: passes the brief floor (0.3), fails the news floor (0.45)
    weak = ('<p><span data-tg="kwusa/3">연합인포맥스를 인용해 민주당 승리 뒤 테슬라 규제 우려와 전기차 보조금 축소를 둘러싼 '
            '여러 관측이 나왔다.</span></p>')
    from common.telegram_gate import coverage, _visible
    c = coverage(_visible(weak).replace('연합인포맥스', ''), S_OP)
    assert 0.3 <= c < 0.45, c
    assert any('맞지 않는다' in x for x in run(page(section(weak))))
    d = data()
    assert check(page(weak), d) == []


# ── one piece of writing, not one paragraph per item (2026-11-14) ─────────
# 사용자 지시 「기사를 조각조각 요약한 것 밖에 안되잖아. 같은 출처를 반복해서 얘기할 필요 없고, 이 내용들이
# 하나의 완성된 글이 되어 발행되도록」 — a paragraph may weave several items and carry linking text.

S_REP2 = '로이터는 텍사스 전력망 운영사가 신규 데이터센터 접속 심사를 미루기로 했다고 보도했다.'
S_VIEW2 = '필자는 반도체 재고 조정이 끝나 가고 업황이 바닥을 지났다고 진단했다.'
S_OP2 = '가스터빈 수주가 40GW 로 늘어 증설이 수요를 따라가지 못한다는 시각이 제시됐다.'
S_OP3 = '변압기 납기가 길어져 전력 설비 업체의 가격 협상력이 커졌다는 의견이 제시됐다.'

SP_VIEW, SP_REP, SP_OP = P_VIEW[3:-4], P_REP[3:-4], P_OP[3:-4]
SP_REP2_BARE = '<span data-tg="insidertracking/8">전력망 운영사도 신규 데이터센터 접속 심사를 미루기로 했다고 전했다.</span>'
SP_REP2_BACK = '<span data-tg="insidertracking/8">같은 보도는 전력망 운영사도 신규 데이터센터 접속 심사를 미루기로 했다고 전했다.</span>'
SP_REP2_NAMED = '<span data-tg="insidertracking/8">로이터는 전력망 운영사도 신규 데이터센터 접속 심사를 미루기로 했다고 전했다.</span>'
SP_VIEW2_BARE = '<span data-tg="hedgecat0301/11">반도체 재고 조정이 끝나 가고 업황이 바닥을 지났다고도 진단했다.</span>'
SP_VIEW2_BACK = '<span data-tg="hedgecat0301/11">한 연구원은 반도체 재고 조정이 끝나 가고 업황이 바닥을 지났다고도 진단했다.</span>'
SP_OP2_BARE = '<span data-tg="d_ticker/11">가스터빈 수주가 40GW 로 늘어 증설이 수요를 따라가지 못한다는 시각도 나왔다.</span>'
SP_OP2_SUBJ = '<span data-tg="d_ticker/11">시장에서는 가스터빈 수주가 40GW 로 늘어 증설이 수요를 따라가지 못한다는 시각도 나왔다.</span>'
SP_OP3_BARE = '<span data-tg="d_ticker/12">변압기 납기가 길어져 전력 설비 업체의 가격 협상력이 커졌다는 의견도 있었다.</span>'


def data2():
    d = data()
    d['items'] += [
        {'id': 'insidertracking/8', 'kind': 'report', 'firm': None, 'analyst': None,
         'source': {'name': '로이터', 'url': 'https://www.reuters.com/y', 'basis': 'link'}, 'summary_ko': S_REP2, 'news_use': True},
        {'id': 'hedgecat0301/11', 'kind': 'view', 'firm': '키움증권', 'analyst': '한지영', 'source': None,
         'summary_ko': S_VIEW2, 'news_use': True},
        {'id': 'd_ticker/11', 'kind': 'opinion', 'firm': None, 'analyst': None, 'source': None,
         'summary_ko': S_OP2, 'news_use': True},
        {'id': 'd_ticker/12', 'kind': 'opinion', 'firm': None, 'analyst': None, 'source': None,
         'summary_ko': S_OP3, 'news_use': True},
    ]
    return d


def para(*parts):
    return '<p>' + ' '.join(parts) + '</p>'


def run2(*paragraphs, **kw):
    return run(page(section(''.join(paragraphs))), data2(), **kw)


def test_a_paragraph_can_weave_several_items_and_linking_text():
    pairs, paras = [], []
    v = run2(para('데이터센터 전력을 둘러싼 보도가 이어졌다.', SP_REP, SP_REP2_BACK), para(SP_VIEW, SP_VIEW2_BACK),
             pairs=pairs, paras=paras)
    assert v == []
    assert [p[0] for p in pairs] == ['insidertracking/7', 'insidertracking/8', 'hedgecat0301/10', 'hedgecat0301/11']
    assert len(paras) == 2
    assert paras[0][0] == ('text', '데이터센터 전력을 둘러싼 보도가 이어졌다. ')          # spaces as written
    assert [x[1] for x in paras[0] if x[0] == 'tg'] == ['insidertracking/7', 'insidertracking/8']
    assert [x for x in paras[0] if x[0] == 'text'][1] == ('text', ' ')


def _lacks(v, tid, name):
    return any(tid in x and name in x for x in v)


def test_the_speaker_is_written_in_the_marker_a_name_or_a_back_reference():
    """Never inferred from the data alone (codex 설계 검토 2회): the reader sees 「같은 보도는」."""
    assert run2(para(SP_REP, SP_REP2_NAMED)) == []
    assert run2(para(SP_REP, SP_REP2_BACK)) == []
    assert run2('<p>' + SP_REP + ' \n ' + SP_REP2_BACK + '</p>') == []
    # the same source right before is not enough without the words
    assert _lacks(run2(para(SP_REP, SP_REP2_BARE)), 'insidertracking/8', '로이터')
    # another paragraph
    assert _lacks(run2(para(SP_REP), para(SP_REP2_BACK)), 'insidertracking/8', '로이터')
    # linking words between the two markers can change who is speaking
    assert _lacks(run2(para(SP_REP, '반면 다른 쪽에서는', SP_REP2_BACK)), 'insidertracking/8', '로이터')
    assert _lacks(run2('<p>' + SP_REP + ' ― ' + SP_REP2_BACK + '</p>'), 'insidertracking/8', '로이터')
    # the marker before it is another source, or is not the one right before
    assert _lacks(run2(para(SP_OP, SP_REP2_BACK)), 'insidertracking/8', '로이터')
    assert _lacks(run2(para(SP_REP, SP_OP, SP_REP2_BACK)), 'insidertracking/8', '로이터')
    # the back-reference is at the very start
    late = SP_REP2_BACK.replace('같은 보도는 전력망 운영사도', '전력망 운영사도 같은 보도에서')
    assert _lacks(run2(para(SP_REP, late)), 'insidertracking/8', '로이터')
    # the word has to end: 「같은 보도자료에 따르면」 is a press release, not the outlet (설계 검토 3회 #1)
    for start in ('같은 보도자료에 따르면', '같은 보도국은', '이 매체들은'):
        assert _lacks(run2(para(SP_REP, SP_REP2_BACK.replace('같은 보도는', start))), 'insidertracking/8', '로이터'), start
    for start in ('이어서 같은 보도는', '또 이 매체는', '같은 기사에 따르면', '해당 통신도'):
        assert run2(para(SP_REP, SP_REP2_BACK.replace('같은 보도는', start))) == [], start
    # a chain: named → back-reference → back-reference
    d = data2()
    d['items'].append({'id': 'insidertracking/9', 'kind': 'report', 'firm': None, 'analyst': None,
                       'source': {'name': '로이터', 'url': None, 'basis': 'credit'}, 'news_use': True,
                       'summary_ko': '로이터는 주 의회가 용수 사용 상한을 두는 법안을 검토한다고 보도했다.'})
    third = '<span data-tg="insidertracking/9">이 매체는 주 의회가 용수 사용 상한을 두는 법안을 검토한다고도 보도했다.</span>'
    assert run(page(section(para(SP_REP, SP_REP2_BACK, third))), d) == []
    assert _lacks(run(page(section(para(SP_REP, SP_REP2_BARE, third))), d), 'insidertracking/9', '로이터')


def test_no_back_reference_after_a_marker_that_names_another_speaker_of_the_file():
    # 「로이터에 따르면 A다. 연합인포맥스는 B를 전했다.」「같은 보도는 C」 — whose report? (2회 #3)
    d = data2()
    for it in d['items']:
        if it['id'] == 'insidertracking/7':
            it['summary_ko'] = S_REP + ' 연합인포맥스는 이 요구가 전력주에 부담이라고 전했다.'
    first = SP_REP.replace('요구했다.', '요구했다. 연합인포맥스는 이 요구가 전력주에 부담이라고 전했다.')
    assert run(page(section(para(first, SP_REP2_NAMED))), d) == []
    assert _lacks(run(page(section(para(first, SP_REP2_BACK))), d), 'insidertracking/8', '로이터')


def test_a_view_refers_back_only_to_the_same_firm_and_analyst():
    assert run2(para(SP_VIEW, SP_VIEW2_BACK)) == []
    assert _lacks(run2(para(SP_VIEW, SP_VIEW2_BARE)), 'hedgecat0301/11', '한지영')
    assert run2(para(SP_VIEW, SP_VIEW2_BACK.replace('한 연구원은', '그 연구원은'))) == []
    assert _lacks(run2(para(SP_VIEW, SP_VIEW2_BACK.replace('한 연구원은', '한 연구원들은'))), 'hedgecat0301/11', '한지영')
    assert _lacks(run2(para(SP_VIEW, SP_VIEW2_BACK.replace('한 연구원은', '김 연구원은'))), 'hedgecat0301/11', '한지영')
    assert _lacks(run2(para(SP_REP, SP_VIEW2_BACK)), 'hedgecat0301/11', '한지영')
    d = data2()
    for it in d['items']:
        if it['id'] == 'hedgecat0301/11':
            it['analyst'] = '김승혁'
    assert _lacks(run(page(section(para(SP_VIEW, SP_VIEW2_BACK))), d), 'hedgecat0301/11', '김승혁')
    # a team view (no analyst) never lends or borrows its name
    d = data2()
    for it in d['items']:
        if it['id'].startswith('hedgecat0301/'):
            it['analyst'] = None
    v = run(page(section(para(SP_VIEW.replace(' 한지영 연구원은', '은'), SP_VIEW2_BACK))), d)
    assert _lacks(v, 'hedgecat0301/11', '키움증권')


def test_an_unsourced_item_after_a_sourced_one_needs_its_own_subject():
    # 「로이터에 따르면 A다. B라는 시각도 나왔다.」 reads as Reuters' report (codex 설계 검토 1회 #1)
    assert _lacks(run2(para(SP_REP, SP_OP2_BARE)), 'd_ticker/11', '주어')
    assert _lacks(run2(para(SP_VIEW, SP_OP2_BARE)), 'd_ticker/11', '주어')
    assert _lacks(run2(para(SP_REP, '한편', SP_OP2_BARE)), 'd_ticker/11', '주어')   # linking text does not stand in for it
    # 「시장에서」 somewhere in the sentence is not a speaker (2회 #1)
    mid = SP_OP2_BARE.replace('가스터빈 수주가', '가스터빈 수주가 시장에서는')
    assert _lacks(run2(para(SP_REP, mid)), 'd_ticker/11', '주어')
    # 「시장은행은」 is a name, not the market (설계 검토 3회 #1)
    for start in ('시장은행은', '업계지는', '시장에서의'):
        assert _lacks(run2(para(SP_REP, SP_OP2_SUBJ.replace('시장에서는', start))), 'd_ticker/11', '주어'), start
    for start in ('증권가에서는', '투자자들 사이에서는', '시장 일각에서는', '일각에서는', '반면 월가에서는'):
        assert run2(para(SP_REP, SP_OP2_SUBJ.replace('시장에서는', start))) == [], start
    assert run2(para(SP_REP, SP_OP2_SUBJ)) == []
    assert run2(para(SP_REP, SP_OP2_SUBJ.replace('시장에서는', '한편 업계 일각에서는'))) == []
    # first in its paragraph, or after another unsourced item: nothing to be mistaken for
    assert run2(para(SP_REP), para(SP_OP2_BARE)) == []
    assert run2(para(SP_REP, SP_OP2_SUBJ, SP_OP3_BARE)) == []
    assert run2(para(SP_OP2_BARE, SP_OP3_BARE)) == []


@pytest.mark.parametrize('link,needle', [
    ('나스닥이 5.5% 밀린 날이었다.', '숫자'),
    ('이날은 11월 장의 분수령이었다.', '숫자'),
    ('로이터 보도가 논의의 출발점이었다.', '이름'),
    ('한지영 연구원의 진단이 눈에 띄었다.', '이름'),
    ('키움증권 쪽 견해가 먼저 나왔다.', '이름'),
    ('연합인포맥스가 옮긴 시각도 있었다.', '이름'),
    ('하루에 세 차례 올랐다는 점이 화제였다.', '숫자'),             # a quantity in words (구현 검토 1회 #1)
    ('주가가 두 배가 됐다는 점이 논의의 바탕이었다.', '숫자'),
    ('수십억 달러가 걸린 문제라는 데 견해가 모였다.', '숫자'),
    ('거래가 절반으로 줄었다는 점이 쟁점이었다.', '숫자'),
    ('전력망을 둘러싼 보도가 ３건 이어졌다.', '숫자'),               # full-width digit
    ('서너 차례 금리를 내렸다는 점이 바탕이었다.', '숫자'),         # compound numerals (구현 검토 2회 #2)
    ('스물한 차례 상승했다는 점이 화제였다.', '숫자'),
    ('수백 건이 쟁점이었다는 데 견해가 모였다.', '숫자'),
    ('한두 번이 아니라는 지적이 이어졌다.', '숫자'),
    ('수차례 이어진 논쟁이라는 점이 바탕이었다.', '숫자'),
    ('수 주째 이어진 논쟁이라는 점이 바탕이었다.', '숫자'),
    ('데이터센터 전력을 둘러싼 보도가 이어졌고 ' + '규제와 전력망과 용수 문제가 한꺼번에 불거졌다는 점에서 ' * 2 + '눈길을 끌었다.', '80자'),
    ('텍사스 주지사 당선인이 데이터센터 사업 중단을 요구했다.', '겹친다'),
    ('전력과 용수 부담이 이유다', '겹친다'),                        # not sentence-shaped, still a copied clause
])
def test_linking_text_carries_no_number_no_name_and_no_summary(link, needle):
    v = run2(para(link, SP_REP, SP_REP2_BACK))
    assert any('잇는 말' in x and needle in x for x in v), v


@pytest.mark.parametrize('link', [
    '다양한 종목에서 같은 흐름이 보였다.',            # 「한 종목」 inside 「다양한」
    '이번 주 내내 이어진 논쟁이다.',
    '한편 전력 설비를 보는 눈은 달랐다.',
    '한 해외 매체의 보도가 논의의 출발점이었다.',     # 「한 해」 inside 「한 해외」
    '이 원칙을 둘러싼 견해가 맞섰다.',                 # 「이 원」 inside 「이 원칙」
    '시장의 일원으로서 논의를 이어갔다.',              # 「일원」 is not one won (구현 검토 2회 #3)
    '두 주요 지수를 보는 눈이 달랐다.',
    '사원 수를 둘러싼 논의는 아니었다.',
    '수주는 엇갈렸다는 데 견해가 모였다.',             # 「수주」 is orders, not several weeks (구현 검토 3회 #2)
    '인수 조건을 둘러싼 견해가 엇갈렸다.',             # measured on the published posts: 「조건」 420 times
    '서명을 앞둔 합의를 두고 시각이 갈렸다.',
    '조명이 쏠린 종목을 두고 견해가 나뉘었다.',
    '견해는 한 곳으로 모였다.',                        # what linking text is for
    '시각은 두 가지로 갈렸다.',
    '설비의 수명을 둘러싼 견해도 있었다.',
    '견해는 엇갈렸다.',
    '데이터센터 전력을 둘러싼 보도가 이어졌다.',
])
def test_linking_text_without_a_quantity_passes(link):
    assert run2(para(link, SP_REP, SP_REP2_BACK, SP_OP2_SUBJ, SP_OP3_BARE)) == []


def test_a_name_written_apart_in_linking_text_is_a_warning_for_the_reader():
    # 「로 이터가 전했다」 may be the outlet (구현 검토 1회 #2); 「매일 경제 지표가」 next to 매일경제 in the
    # file is plain words. Code cannot tell them apart, so it does not block — it tells the reader.
    for link in ('로 이터가 전한 내용이 출발점이었다.', '한 지 영 연구원의 진단이 눈에 띄었다.'):
        warns = []
        assert run2(para(link, SP_REP, SP_REP2_BACK, SP_OP2_SUBJ, SP_OP3_BARE), warnings=warns) == [], link
        assert any('띄어 쓴 이름' in w for w in warns), (link, warns)
    d = data2()
    d['items'].append({'id': 'kwusa/4', 'kind': 'opinion', 'firm': None, 'analyst': None, 'news_use': True,
                       'source': {'name': '매일경제', 'url': None, 'basis': 'credit'}, 'summary_ko': S_OP3})
    warns = []
    assert run(page(section(para('매일 경제 지표가 나오는 주였다.', SP_REP, SP_REP2_BACK))), d, warnings=warns) == []
    assert any('띄어 쓴 이름' in w and '매일경제' in w for w in warns), warns
    warns = []
    assert any('이름' in x for x in run(page(section(para('매일경제 보도가 출발점이었다.', SP_REP, SP_REP2_BACK))), d, warnings=warns))


def test_a_name_inside_the_speakers_own_name_is_not_another_speaker():
    # sources 「로이터통신」 ×2 and, elsewhere in the file, 「로이터」 (구현 검토 1회 #3)
    d = data2()
    for it in d['items']:
        if it['id'] in ('insidertracking/7', 'insidertracking/8'):
            it['source'] = dict(it['source'], name='로이터통신')
    d['items'].append({'id': 'kwusa/4', 'kind': 'opinion', 'firm': None, 'analyst': None, 'news_use': True,
                       'source': {'name': '로이터', 'url': None, 'basis': 'credit'}, 'summary_ko': S_OP3})
    first = SP_REP.replace('로이터에 따르면', '로이터통신에 따르면')
    assert run(page(section(para(first, SP_REP2_BACK))), d) == []
    # the other way round: the marker is 「로이터」's and names 「로이터통신」 too (구현 검토 2회 #1)
    d2 = data2()
    d2['items'].append({'id': 'kwusa/4', 'kind': 'opinion', 'firm': None, 'analyst': None, 'news_use': True,
                        'source': {'name': '로이터통신', 'url': None, 'basis': 'credit'}, 'summary_ko': S_OP3})
    d2['items'][1]['summary_ko'] = S_REP + ' 로이터통신은 주 의회도 같은 요구를 했다고 전했다.'
    both = SP_REP.replace('요구했다.', '요구했다. 로이터통신은 주 의회도 같은 요구를 했다고 전했다.')
    assert run(page(section(para(both, SP_REP2_NAMED))), d2) == []
    assert _lacks(run(page(section(para(both, SP_REP2_BACK))), d2), 'insidertracking/8', '로이터')
    # spaced out in the marker before
    spaced = SP_REP.replace('요구했다.', '요구했다. 연합 인포맥스는 이 요구가 부담이라고 전했다.')
    d3 = data2()
    d3['items'][1]['summary_ko'] = S_REP + ' 연합인포맥스는 이 요구가 부담이라고 전했다.'
    assert _lacks(run(page(section(para(spaced, SP_REP2_BACK))), d3), 'insidertracking/8', '로이터')
    # 「로이터」 really named next to it still blocks the back-reference
    d['items'][1]['summary_ko'] = S_REP + ' 로이터 기자는 주 의회도 같은 요구를 했다고 전했다.'
    two = first.replace('요구했다.', '요구했다. 로이터 기자는 주 의회도 같은 요구를 했다고 전했다.')
    assert _lacks(run(page(section(para(two, SP_REP2_BACK))), d), 'insidertracking/8', '로이터통신')


def test_a_longer_speakers_name_does_not_name_the_shorter_one():
    # the item is 「로이터」's, the marker says 「로이터통신은」 — another outlet of the file (구현 검토 3회 #1)
    d = data2()
    d['items'].append({'id': 'kwusa/4', 'kind': 'opinion', 'firm': None, 'analyst': None, 'news_use': True,
                       'source': {'name': '로이터통신', 'url': None, 'basis': 'credit'}, 'summary_ko': S_OP3})
    wrong = SP_REP.replace('로이터에 따르면', '로이터통신에 따르면')
    assert _lacks(run(page(section(para(wrong))), d), 'insidertracking/7', '로이터')
    assert run(page(section(para(SP_REP))), d) == []
    # the longer name spaced out is still the longer name (구현 검토 4회 #1)
    for spaced in ('로이터 통신에 따르면', '로이터  통신에 따르면', '로 이터 통 신에 따르면'):
        assert _lacks(run(page(section(para(SP_REP.replace('로이터에 따르면', spaced)))), d), 'insidertracking/7', '로이터'), spaced
    assert not _lacks(run(page(section(para(SP_REP.replace('로이터에 따르면', '로이터 통신과 로이터에 따르면')))), d),
                      'insidertracking/7', '출처')
    both = SP_REP.replace('로이터에 따르면', '로이터통신과 로이터에 따르면')
    assert not _lacks(run(page(section(para(both))), d), 'insidertracking/7', '출처')
    # and the other way round: the item is 「로이터통신」's, the marker says only 「로이터」
    for it in d['items']:
        if it['id'] == 'kwusa/4':
            it['source']['name'] = '로이터'
        if it['id'] == 'insidertracking/7':
            it['source'] = dict(it['source'], name='로이터통신')
    assert _lacks(run(page(section(para(SP_REP))), d), 'insidertracking/7', '로이터통신')
    # the brief layout names the same way
    b = data()
    for it in b['items']:
        it.pop('news_use', None)
    b['items'].append({'id': 'kwusa/4', 'kind': 'opinion', 'firm': None, 'analyst': None,
                       'source': {'name': '로이터통신', 'url': None, 'basis': 'credit'}, 'summary_ko': S_OP3})
    assert _lacks(check(page(para(wrong)), b), 'insidertracking/7', '로이터')
    assert check(page(para(SP_REP)), b) == []
    assert _lacks(check(page(para(SP_REP.replace('로이터에 따르면', '로이터 통신에 따르면'))), b), 'insidertracking/7', '로이터')
    assert check(page(para(SP_REP.replace('로이터에 따르면', '로이터 통신과 로이터에 따르면'))), b) == []


def test_the_same_name_spelled_with_and_without_a_space_is_one_name():
    # 「로이터통신」 and 「로이터 통신」 both in the file must not hide each other (구현 검토 5회 #1)
    for layout in ('news', 'brief'):
        d = data2()
        for it in d['items']:
            if it['id'] in ('insidertracking/7', 'insidertracking/8'):
                it['source'] = dict(it['source'], name='로이터통신')
            if layout == 'brief':
                it.pop('news_use', None)
        d['items'].append({'id': 'kwusa/4', 'kind': 'opinion', 'firm': None, 'analyst': None,
                           'source': {'name': '로이터 통신', 'url': None, 'basis': 'credit'}, 'summary_ko': S_OP3,
                           **({'news_use': True} if layout == 'news' else {})})
        first = SP_REP.replace('로이터에 따르면', '로이터통신에 따르면')
        if layout == 'brief':
            assert check(page(para(first)), d) == []
        else:
            assert run(page(section(para(first))), d) == []
            assert run(page(section(para(first, SP_REP2_BACK))), d) == []      # nor block the back-reference


def test_dates_are_compared_token_by_token():
    from common.telegram_gate import dates_only_in
    assert dates_only_in('1월에 발표했다', '11월에 발표했다') == ['1월']
    assert dates_only_in('3일 발표했다', '11월 13일 발표했다') == ['3일']
    assert dates_only_in('11월 13일 발표했다', '11월 13일에 발표했다') == []


def test_character_references_are_read_the_way_they_show():
    # `&#32;같은 보도는` starts with a space, and 32 is not a figure (구현 검토 1회 #4)
    assert run2(para(SP_REP, SP_REP2_BACK.replace('>같은 보도는', '>&#32;같은 보도는'))) == []
    assert run2(para(SP_REP, SP_REP2_BACK.replace('>같은 보도는', '>&nbsp;같은 보도는'))) == []
    # the brief layout reads them the same way
    d = data()
    for it in d['items']:
        it.pop('news_use', None)
    assert check(page('<p>' + P_VIEW[3:-4].replace('급락한 배경을', '급락한&#32;배경을') + '</p>'), d) == []


def test_short_linking_words_pass():
    assert run2(para(SP_REP, SP_REP2_BACK), para('반면', SP_OP2_BARE, '이어', SP_OP3_BARE)) == []


def test_linking_text_is_a_small_share_of_the_section():
    link = '데이터센터 전력을 둘러싼 보도가 하루 내내 이어졌다는 점이 이날의 줄기였다.'
    v = run2(para(link, SP_REP), para(link.replace('보도', '소식'), SP_REP2_NAMED))
    assert any('잇는 말' in x and '20%' in x for x in v), v
    assert run2(para(link, SP_REP, SP_REP2_BACK, SP_OP2_SUBJ, SP_OP3_BARE), para(SP_VIEW, SP_VIEW2_BACK)) == []


def test_cli_prints_the_paragraphs_in_order_then_the_pairs(tmp_path):
    html = page(section(para('데이터센터 전력을 둘러싼 보도가 이어졌다.', SP_REP, SP_REP2_BACK) + para(SP_VIEW)))
    r = _cli(tmp_path, html, data2(), '--layout', 'news', '--news', str(tmp_path / 'news.json'))
    assert r.returncode == 0, r.stdout + r.stderr
    out = r.stdout
    assert '다시 읽기 3건' in out and '문단 2개' in out
    assert '문단 1: 데이터센터 전력을 둘러싼 보도가 이어졌다. [insidertracking/7] 로이터에 따르면' in out
    assert out.index('문단 2: [hedgecat0301/10]') < out.index('요약: ' + S_REP)
    assert '날짜:' not in out


def test_cli_prints_the_spaces_as_written(tmp_path):
    # glued markers print glued, a line break prints as one space, &amp; as & (설계 검토 3회 #2)
    glued = '<p>전력 &amp; 용수를 둘러싼 보도다.\n   ' + SP_REP + SP_REP2_BACK + '</p>'
    r = _cli(tmp_path, page(section(glued)), data2(), '--layout', 'news', '--news', str(tmp_path / 'news.json'))
    assert r.returncode == 0, r.stdout + r.stderr
    assert '문단 1: 전력 & 용수를 둘러싼 보도다. [insidertracking/7] 로이터에 따르면' in r.stdout
    assert '요구했다.[insidertracking/8] 같은 보도는' in r.stdout


def test_cli_points_at_dates_the_summary_does_not_have(tmp_path):
    # dates are masked out of the number check, so the reader is shown them (codex 설계 검토 1회 #6)
    sp = SP_OP2_BARE.replace('가스터빈 수주가', '2028년 3분기까지 가스터빈 수주가')
    r = _cli(tmp_path, page(section(para(sp))), data2(), '--layout', 'news', '--news', str(tmp_path / 'news.json'))
    assert r.returncode == 0, r.stdout + r.stderr
    assert '날짜: 2028년, 3분기 — 요약에는 이 표기가 없다' in r.stdout


# ── text outside the section ─────────────────────────────────────────────

def test_copied_summary_outside_the_section_fails():
    v = run(page(section(P_VIEW), '<section><h2>메모리/DRAM</h2><p>' + S_REP + '</p></section>'))
    assert any('표식 밖' in x for x in v), v


def test_short_copied_sentence_fails_even_for_a_not_usable_item():
    """codex 설계 검토 2회: 21자짜리 복사 문장. 비교 대상에는 news_use 가 false 인 요약도 든다."""
    v = run(page('<p>반도체 수요가 급증하고 공급이 빠르게 감소했다.</p>'))
    assert any('표식 밖' in x for x in v), v


def test_copied_sentence_right_after_a_heading_fails():
    """codex 설계 검토 3회: 태그를 공백으로 바꾸면 제목과 한 문장으로 합쳐져 겹침이 0.525 로 떨어졌다."""
    v = run(page('<section><h2>오늘의 뉴스와 반도체 산업 및 글로벌 시장 동향</h2><p>반도체 수요가 급증하고 공급이 빠르게 감소했다.</p></section>'))
    assert any('표식 밖' in x for x in v), v


def test_link_sentence_inside_a_news_block_is_compared():
    """codex 설계 검토 2회: 뉴스 블록을 통째로 빼면 연결 문장이 검사를 피한다."""
    v = run(page(link=' 반도체 수요가 급증하고 공급이 빠르게 감소했다.'))
    assert any('표식 밖' in x for x in v), v
    assert run(page(link=' 이날 알파벳은 1.2% 올랐다.')) == []


def test_machine_filled_news_summary_is_not_compared_but_a_hand_written_one_is():
    same = S_REP                      # a news article whose stored summary equals a Telegram summary
    news = {'items': [{'guid': 'g1', 'summary_ko': same}]}
    assert run(page(news_summary=same), news=news) == []
    # the paragraph is not the stored summary (or there is no news file): compared whole
    assert any('표식 밖' in x for x in run(page(news_summary=same), news=NEWS))
    assert any('표식 밖' in x for x in run(page(news_summary=same), news=None))


def test_contested_section_is_not_compared():
    cont = f'<section id="contested" data-contested="abc"><h2>쟁점 분석</h2><p>{S_REP}</p></section>'
    assert run(page(cont)) == []


def test_short_fragments_that_are_not_sentences_pass():
    d = data(**{'kwusa/3': {'summary_ko': '11월 11일 종가 기준 미국 증시는 반도체·AI 하드웨어가 이끌었다는 시각이 전해졌다.'}})
    assert run(page('<p class="caption">11월 11일 종가 기준.</p><h3>반도체·AI 하드웨어</h3>'), d) == []


def test_editor_note_is_not_exempt_in_a_news_post():
    """codex 구현 검토 1회 #1: 뉴스 글에는 편집자 노트가 없다 — 그 표식을 단 섹션이 검사를 피하는 자리가 됐다."""
    note = '<section id="editor-note" data-editor-note="2026-11-11"><p>{}</p></section>'
    assert any('텔레그램' in x for x in run(page(note.format('텔레그램에서 본 이야기다.'))))
    assert any('표식 밖' in x for x in run(page(note.format(S_REP))))
    # the brief keeps the exemption (the note there is the publisher's own text)
    assert check(page(note.format('텔레그램에서 본 이야기다.')), data()) == []


# ── CLI ──────────────────────────────────────────────────────────────────

def _cli(tmp_path, html, d, *extra):
    h, t, n = tmp_path / 'p.html', tmp_path / 'tg.json', tmp_path / 'news.json'
    h.write_text(html, encoding='utf-8')
    if d is not None:
        t.write_text(json.dumps(d, ensure_ascii=False), encoding='utf-8')
    n.write_text(json.dumps(NEWS, ensure_ascii=False), encoding='utf-8')
    return subprocess.run([sys.executable, os.path.join(SCRIPTS, 'check_telegram.py'), '--html', str(h), '--tg', str(t),
                           '--date', '2026-11-11', *extra], capture_output=True, text=True)


def test_cli_news_layout_prints_pairs_and_needs_the_news_path(tmp_path):
    r = _cli(tmp_path, page(section()), data(), '--layout', 'news', '--news', str(tmp_path / 'news.json'))
    assert r.returncode == 0, r.stdout + r.stderr
    assert '다시 읽기 3건' in r.stdout and '문단 3개' in r.stdout and 'hedgecat0301/10' in r.stdout and S_VIEW in r.stdout
    r = _cli(tmp_path, page(section()), data(), '--layout', 'news')
    assert r.returncode == 2 and '--news' in r.stderr
    r = _cli(tmp_path, page(section()), data(), '--layout', 'news', '--news', str(tmp_path / 'missing.json'))
    assert r.returncode == 0 and '뉴스 수집분 없음' in r.stdout


def test_cli_brief_layout_is_the_default_and_prints_no_pairs(tmp_path):
    d = data()
    r = _cli(tmp_path, page('<p>' + P_VIEW[3:-4] + '</p>'), d)
    assert r.returncode == 0 and '다시 읽기' not in r.stdout
