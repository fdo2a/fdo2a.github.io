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
    (page(section('<p>' + P_VIEW[3:-4] + P_REP[3:-4] + '</p>')), '모양'),              # two spans in one p
    (page(section(P_VIEW.replace('찾았다.', '찾았다. <a href="https://example.com">원문</a>'))), '모양'),
    (page(section(P_VIEW.replace('</span>', '<img src="x.png"></span>'))), '모양'),
    (page(section(P_VIEW.replace('</span></p>', '</span> 덧붙인 말이다.</p>'))), '모양'),
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


def test_paragraph_longer_than_300_chars_fails():
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
    assert '다시 읽기 3건' in r.stdout and 'hedgecat0301/10' in r.stdout and S_VIEW in r.stdout
    r = _cli(tmp_path, page(section()), data(), '--layout', 'news')
    assert r.returncode == 2 and '--news' in r.stderr
    r = _cli(tmp_path, page(section()), data(), '--layout', 'news', '--news', str(tmp_path / 'missing.json'))
    assert r.returncode == 0 and '뉴스 수집분 없음' in r.stdout


def test_cli_brief_layout_is_the_default_and_prints_no_pairs(tmp_path):
    d = data()
    r = _cli(tmp_path, page('<p>' + P_VIEW[3:-4] + '</p>'), d)
    assert r.returncode == 0 and '다시 읽기' not in r.stdout
