"""일본 일간 「증권사 견해·시장 의견」 절 — 조립·게이트·발행 고정·근거 경로 (2026-11-15).
시험 문장은 전부 지어낸 것이다(원문은 레포에 넣지 않는다).
설계: docs/superpowers/specs/2026-11-15-telegram-japan-daily.md"""
import json

import pytest

import build_japan_daily as B
import tg_news
from common import telegram_gate as TG
from common import tg_jp
from japan import daily_gate as G
from japan import daily_render as R
from japan.tests import test_daily_gate as GH
from japan.tests.test_daily_render import SNAP, S

CH = tg_jp.JP_CHANNEL
SUM1 = ('후루카와전기의 상반기 실적이 광섬유 호조로 예상을 웃돌았고 연간 가이던스도 다시 올랐다는 분석이다. '
        '목표주가는 6,100엔, 투자의견은 비중확대로 제시됐다.')
SUM2 = '일본은행이 12월 회의에서 금리를 올릴 가능성이 커졌다는 시각이 제시됐다. 임금 상승세가 근거로 꼽혔다.'
SUM3 = '니혼게이자이는 키옥시아가 낸드 증설 투자를 1조 엔 규모로 검토한다고 전했다.'


def item(n, summary, **kw):
    base = {'id': f'{CH}/{n}', 'channel': CH, 'group': 'individual', 'kind': 'opinion', 'firm': None, 'analyst': None,
            'source': None, 'relay_firm': None, 'note_date': None, 'dt_utc': f'{S}T01:00:00+00:00',
            'summary_ko': summary, 'news_use': True}
    return dict(base, **kw)


def tg(*items):
    return {'report_date': S, 'market': 'jp', 'usable': True, 'items': list(items), 'stats': {}}


I1 = item(101, SUM1, relay_firm='모건스탠리')
I2 = item(102, SUM2)
I3 = item(103, SUM3, source={'name': '니혼게이자이', 'url': None, 'basis': 'credit'})
DATA = tg(I1, I2, I3)
P1 = ('모건스탠리가 후루카와전기의 상반기 실적이 광섬유 호조로 예상을 웃돌았고 연간 가이던스도 다시 올랐다고 봤다는 내용이 '
      '전해졌다. 목표주가는 6,100엔으로 제시됐다.')
P2 = '일본은행이 12월 회의에서 금리를 올릴 가능성이 커졌다는 시각이 전해졌다. 임금 상승세가 근거로 꼽혔다.'
P3 = '니혼게이자이는 키옥시아가 낸드 증설 투자를 1조 엔 규모로 검토한다고 전했다는 소식이다.'


def para(n, text):
    return f'<p><span data-tg="{CH}/{n}">{text}</span></p>'


def section(*paras, open_tag='<section class="card" data-section="views" data-tg-section>', title=TG.NEWS_TITLE):
    return f'{open_tag}<h2>{title}</h2>{"".join(paras)}</section>'


VIEWS = section(para(101, P1), para(102, P2), para(103, P3))


def body(views=VIEWS, prose=None, order=R.SECTIONS):
    b = GH.body(prose, order)
    news = f'<section class="card" data-section="news"><h2>{R.TITLES["news"]}</h2>{dict(GH.PROSE, **(prose or {}))["news"]}</section>'
    assert news in b
    return b.replace(news, news + '\n' + views) if views else b


def page(views=VIEWS, prose=None, snap=SNAP, order=R.SECTIONS):
    return R.assemble(body(views, prose, order), {'title': '일본 증시 마감', 'summary': '요약'}, snap)


def check(h, data=DATA, news=None, pairs=None):
    return G.check(h, SNAP, S, filename=f'{S}.html', news=news, tg=data, pairs=pairs)


# ── 조립 ─────────────────────────────────────────────────────────────────

def test_title_is_the_gates_title():
    assert R.TITLES['views'] == TG.NEWS_TITLE


def test_body_with_and_without_the_section_validates():
    assert R.validate_body(body(), R.SECTIONS) == []
    assert R.validate_body(body(views=None), R.SECTIONS) == []
    ev = R.order(['x'])
    assert R.validate_body(body(order=ev), ev) == []


@pytest.mark.parametrize('b', [
    body().replace(VIEWS, VIEWS + VIEWS),                                              # twice
    body().replace(' data-tg-section', ''),                                           # one marker only
    body(views=None).replace('<section class="card" data-section="next">', VIEWS + '<section class="card" data-section="next">', 1)
    .replace(f'<section class="card" data-section="news"><h2>{R.TITLES["news"]}</h2></section>\n', '', 1)
    + f'<section class="card" data-section="news"><h2>{R.TITLES["news"]}</h2></section>',   # before news
])
def test_body_rejects_a_misplaced_section(b):
    assert any('views' in e for e in R.validate_body(b, R.SECTIONS))


def test_assembled_section_gets_an_id_and_keeps_both_markers():
    h = page()
    assert 'data-section="views" data-tg-section>' in h and h.count('data-tg-section') == 1
    assert '<section id="read-8" class="card" data-section="views"' in h


# ── 게이트: 통과 ─────────────────────────────────────────────────────────

def test_clean_page_passes_and_prints_pairs():
    pairs = []
    assert check(page(), pairs=pairs) == []
    assert [p[0] for p in pairs] == [f'{CH}/101', f'{CH}/102', f'{CH}/103'] and pairs[0][2] == SUM1


def test_page_without_the_section_passes_with_and_without_a_file():
    assert check(page(views=None)) == []
    assert check(page(views=None), data=None) == []


def test_section_passes_on_an_event_day():
    snap = dict(SNAP, calendar=dict(SNAP['calendar'], event_day=[{'name_ko': 'BOJ 금융정책결정회의'}]))
    h = page(snap=snap, order=R.order(['x']))
    assert G.check(h, snap, S, filename=f'{S}.html', tg=DATA) == []


def test_the_sections_numbers_are_not_snapshot_numbers():
    """Without the exemption the note's figures are 「어느 원본에도 없는 수치」 — and with a file they pass."""
    assert check(page()) == []
    v = check(page(), data=None)
    assert any('쓸 수 있는 텔레그램 파일이 없다' in m for m in v)


# ── 게이트: 파일이 없으면 표식도 없어야 한다 ─────────────────────────────

@pytest.mark.parametrize('h', [
    page(),
    page(views=None, prose={'today': f'<p>오후 들어 낙폭을 줄였다. <span data-tg="{CH}/101">전해졌다.</span></p>'}),
    page(views='<section class="card" data-tg-section><h2>증권사 견해·시장 의견</h2></section>'),
])
def test_markers_without_a_usable_file_are_blocked(h):
    assert any('쓸 수 있는 텔레그램 파일이 없다' in m for m in check(h, data=None))


# ── 게이트: 절의 모양 ────────────────────────────────────────────────────

@pytest.mark.parametrize('views,word', [
    (section(para(101, P1), title='시장 의견'), '모양'),
    (section(para(101, P1) + '<p>덧붙이는 말이다.</p>'), '모양'),
    (section(f'<p>앞말 <span data-tg="{CH}/101">{P1}</span></p>'), '모양'),
    (section(f'<p><span data-tg="{CH}/101">{P1}</span><span data-tg="{CH}/102">{P2}</span></p>'), '모양'),
    (section(f'<p><span data-tg="{CH}/101"><b>{P1}</b></span></p>'), '모양'),
    (section(f'<div class="card">{para(101, P1)}</div>'), '모양'),
    (section(para(101, P1), open_tag='<section class="card" data-section="views" data-tg-section hidden>'), '모양'),
    (section(para(101, P1), open_tag='<section class="card" data-section="views" data-tg-section style="display:none">'), '모양'),
    (section(), '모양'),
    (section(para(101, P1)) + section(para(102, P2)), '개다'),
    (section(para(101, P1), open_tag='<section class="card" data-tg-section>'), '절 밖에 표식'),
    (section(para(101, P1), open_tag="<section class='card' data-section='views'>"), '절 밖에 표식'),
    (section(para(101, P1) + '<section data-section="x"><p>안쪽 절.</p></section>'), '모양'),
])
def test_wrong_shape_is_blocked(views, word):
    v = check(page(views=views))
    assert any(word in m for m in v), v


def test_quoting_variants_of_the_markers_are_one_section():
    views = section(para(101, P1), open_tag="<section class='card' data-section='views' data-tg-section=''>")
    h = page(views=None)
    news_close = h.index('</section>', h.index('data-section="news"')) + len('</section>')
    h = h[:news_close] + '\n' + views + h[news_close:]
    node, v = TG.views_node(h)
    assert v == [] and node['source'] == views
    # daily_gate's own section pattern reads double quotes only — the span does not match, so nothing is exempt
    assert any('제자리에 없다' in m for m in check(h))


def test_stray_marker_outside_the_section_is_blocked():
    h = page(prose={'today': f'<p>오후 들어 낙폭을 줄였다. <span data-tg="{CH}/102">{P2}</span></p>'},
             views=section(para(101, P1)))
    assert any('절 밖에 표식' in m for m in check(h))


def test_section_not_right_after_news_is_blocked():
    h = page(views=None)
    i = h.index('<section id="read-3"')
    h = h[:i] + VIEWS + '\n' + h[i:]
    assert any('제자리에 없다' in m for m in check(h))


def test_comment_inside_the_section_is_not_exempt():
    h = page().replace(f'<p><span data-tg="{CH}/102">', f'<!-- 6,100 --><p><span data-tg="{CH}/102">', 1)
    assert any('제자리에 없다' in m for m in check(h))


def test_views_node_span_is_the_source_span():
    h = page()
    node, v = TG.views_node(h)
    assert v == [] and h[node['start']:node['end']] == node['source']
    assert node['source'].startswith('<section id="read-8"') and node['source'].endswith('</section>')
    assert [tid for tid, _ in node['paras']] == [f'{CH}/101', f'{CH}/102', f'{CH}/103']


# ── 게이트: 항목 규칙 ────────────────────────────────────────────────────

def one(text, it=I1, n=101):
    return check(page(views=section(para(n, text))), data=tg(it, *(x for x in (I1, I2, I3) if x['id'] != it['id'])))


def test_direct_statement_is_not_hearsay():
    v = one('후루카와전기의 상반기 실적이 광섬유 호조로 예상을 웃돌았고 연간 가이던스도 다시 올랐다고 평가했다. '
            '목표주가는 6,100엔으로 제시됐다.')
    assert any('전해 들은 말의 틀' in m for m in v)


def test_a_broker_the_note_is_not_from_is_blocked():
    v = one(P1.replace('모건스탠리', 'JP모건'))
    assert any('증권사 이름 「JP모건」' in m for m in v)
    # a broker named in the summary itself is the summary's
    it = item(101, SUM1 + ' 골드만삭스도 같은 의견이라고 덧붙였다.', relay_firm='모건스탠리')
    assert one(P1 + ' 골드만삭스도 같은 의견이라는 내용이다.', it=it) == []


def test_unsourced_note_passes_without_a_name():
    assert one(P2, it=I2, n=102) == []


def test_yen_is_a_unit():
    assert any('요약에 없는 수치' in m for m in one(P1.replace('6,100엔', '6,100원')))
    assert any('요약에 없는 수치' in m for m in one(P1.replace('6,100엔', '6,100')))
    assert any('요약에 없는 수치' in m for m in one(P3.replace('1조 엔', '1억 엔'), it=I3, n=103))


def test_dates_must_come_from_the_note_or_its_summary():
    v = one(P2.replace('12월 회의', '1월 회의'), it=I2, n=102)
    assert any('없는 날짜' in m and '1월' in m for m in v)
    assert one('10월 26일 ' + P2, it=I2, n=102) == []                                  # the note's own day
    assert any('2025년' in m for m in one('2025년 10월 26일 ' + P2, it=I2, n=102))      # a wrong year


def test_a_note_from_before_the_session_names_its_day():
    old = item(102, SUM2, dt_utc='2026-10-24T03:00:00+00:00')                         # Saturday JST
    assert any('10월 24일' in m and '밝힌다' in m for m in one(P2, it=old, n=102))
    assert one('10월 24일 ' + P2, it=old, n=102) == []
    dated = item(102, SUM2, note_date='2026-10-25')
    assert any('10월 25일' in m for m in one(P2, it=dated, n=102))
    assert one(P2.replace('일본은행이', '10월 25일 메모는 일본은행이'), it=dated, n=102) == []


def test_item_must_be_usable_quoted_once_and_short():
    skipped = dict(I2, news_use=False, news_skip='junk')
    assert any('쓸 수 없는 항목' in m for m in one(P2, it=skipped, n=102) + check(page(), data=tg(I1, skipped, I3)))
    assert any('두 번' in m for m in check(page(views=section(para(101, P1), para(101, P1)))))
    assert any('최대 300자' in m for m in one(P2 + ' 임금 상승세가 근거로 꼽혔다.' * 20, it=I2, n=102))
    assert any('파일에 없거나' in m for m in check(page(views=section(para(999, P2)))))


def test_outlet_must_be_named():
    v = one(P3.replace('니혼게이자이는 ', ''), it=I3, n=103)
    assert any('니혼게이자이' in m and '문장 안에' in m for m in v)


# ── 게이트: 절 밖 ────────────────────────────────────────────────────────
# What excuses a sentence that overlaps a note: an article of the day's news file that says it at
# least as closely. Nothing on the page decides it (구현 검토 1회 #2, 2·3·4회 — every reading of
# 「is the article on the page」 had a counterexample).

NEWS = {'items': [{'guid': 'n1', 'summary_ko': SUM2, 'title': 't', 'source': 's'}]}
BLOCK = f'<div class="news-item" data-news="n1"><p class="news-head">제목</p><p data-summary="n1">{SUM2}</p></div>'
FIRST = SUM2.split('. ')[0] + '.'
OVERLAP = '표식 밖 문장이 텔레그램 요약과 겹친다'


def test_copy_of_a_summary_outside_the_section_fails():
    v = check(page(prose={'today': f'<p>{SUM2}</p>'}))
    assert any(OVERLAP in m for m in v)


def test_an_article_of_the_days_file_vouches_for_the_sentence():
    """A note and an article about the same release: prose written from the article is not the note's —
    whether the page shows that article (the stored summary in its block) or not."""
    assert check(page(prose={'news': BLOCK}), news=NEWS) == []
    assert check(page(prose={'news': BLOCK, 'today': f'<p>{FIRST}</p>'}), news=NEWS) == []
    assert check(page(prose={'today': f'<p>{FIRST}</p>'}), news=NEWS) == []


MARKUP = [
    '<p data-summary="n1">{}</p>',
    '<div data-news="n1"><p data-summary="n1">{}</p></div>',
    '<p data-cite="n1">{}</p>',
    '<p data-mover="g1" data-cite="n1">{}</p>',
    '<P data-mover="g1" data-cite="n1">x</P><p>{}</p>',
    '<div hidden><p data-mover="g1" data-cite="n1">x</p></div><p>{}</p>',
    '<div hidden/><p>{}</p>',
    '<p data-mover="g1" data-cite="n1"><p>{}</p></p>',
    '</section><section data-contested><p>{}</p>',
]


@pytest.mark.parametrize('wrap', MARKUP)
@pytest.mark.parametrize('news', [None, {'items': []},
                                  {'items': [{'guid': 'n1', 'summary_ko': '도요타가 북미 판매 목표를 올렸다고 밝혔다.'}]}])
def test_no_markup_excuses_a_copied_note(wrap, news):
    """No article of the day says it: the sentence is the note's, whatever it is wrapped in."""
    v = check(page(prose={'today': wrap.format(FIRST)}), news=news)
    assert any(OVERLAP in m for m in v), v


@pytest.mark.parametrize('wrap', MARKUP[:4] + MARKUP[5:6])
def test_markup_does_not_take_the_vouching_away_either(wrap):
    v = check(page(prose={'today': wrap.format(FIRST)}), news=NEWS)
    assert not any(OVERLAP in m for m in v), v


def test_a_sentence_closer_to_the_note_than_to_the_article_is_the_notes():
    other = {'items': [{'guid': 'n1', 'summary_ko': '일본은행이 12월 회의를 앞두고 있다는 보도가 나왔다. 엔화는 보합이었다.'}]}
    block = BLOCK.replace(SUM2, other['items'][0]['summary_ko'])
    v = check(page(prose={'news': block, 'today': f'<p>{FIRST}</p>'}), news=other)
    assert any(OVERLAP in m for m in v)


def test_same_event_different_detail_the_notes_detail_still_fails():
    """An article and a note on the same earnings release. The article has the result; the target
    price and the rating are only the note's — a sentence carrying them is the note's."""
    art = {'items': [{'guid': 'n1', 'summary_ko': '후루카와전기는 상반기 실적이 광섬유 호조로 예상을 웃돌았다고 발표했다. '
                                                  '연간 가이던스도 다시 올렸다.'}]}
    from_article = '<p>후루카와전기는 상반기 실적이 광섬유 호조로 예상을 웃돌았다고 발표했다.</p>'
    from_note = '<p>목표주가는 6,100엔, 투자의견은 비중확대로 제시됐다.</p>'
    assert not any(OVERLAP in m for m in check(page(prose={'today': from_article}), news=art))
    assert any(OVERLAP in m for m in check(page(prose={'today': from_note}), news=art))


def test_an_unpublishable_summary_vouches_for_nothing():
    bad = {'items': [{'guid': 'n1', 'summary_ko': ''}, {'guid': 'n2', 'summary_ko': None}, None, {'summary_ko': 123},
                     {'guid': 'n3', 'summary_ko': '日本銀行が12月会合で利上げする可能性が高まったとの見方が示された。'}]}
    assert TG._jp_articles(bad) == []
    assert TG._jp_articles(NEWS) == [SUM2] and TG._jp_articles(None) == []


@pytest.mark.parametrize('br', ['<br>', '<br/>', '<BR >', '<wbr>', '<br class="x">'])
def test_a_line_break_does_not_end_the_sentence(br):
    """구현 검토 5회 — cut at every <br>, a copied sentence was five fragments too short to compare."""
    summ = '도요타 전기차 생산 계획이 예상보다 늦어질 것이라는 분석이 전해졌다.'
    prose = f'<p>도요타 전기차{br}생산 계획이{br}예상보다{br}늦어질 것이라는{br}분석이 전해졌다.</p>'
    v = check(page(views=None, prose={'today': prose}), data=tg(item(1, summ)), news={'items': []})
    assert any(OVERLAP in m for m in v), v
    if 'wbr' not in br:
        assert TG._pieces(prose) == []                  # US/KR: the reading their posts were checked with


@pytest.mark.parametrize('pre', ['<div hidden/>', '<span style="display:none"/>', '<template/>'])
def test_a_self_closed_hidden_element_before_the_section_hides_it(pre):
    """구현 검토 4회 — HTML ignores the slash on a non-void element, so the section is inside it."""
    node, v = TG.views_node(pre + VIEWS)
    assert node is None and v


def test_channel_words_are_blocked_anywhere_and_located():
    v = check(page(prose={'today': '<p>텔레그램에서 본 내용이다.</p>'}))
    assert any('텔레그램' in m and '뉴스 절 안' not in m for m in v)
    block = BLOCK.replace('제목', '텔레그램 창업자 발언')
    v = check(page(prose={'news': block}), news=NEWS)
    assert any('뉴스 절 안' in m for m in v)
    assert any('에테르의' in m for m in check(page(prose={'today': '<p>에테르의 메모에 따르면 그렇다.</p>'})))


@pytest.mark.parametrize('tag', ['<meta name="description" content="텔레그램 채널 소식">',
                                 '<meta property="og:description" content="&#53588;&#47112;&#44536;&#47016; 소식">',
                                 '<img alt="에테르의 메모" src="x.png">', '<a title="telegram" href="/x">링크</a>'])
@pytest.mark.parametrize('data', [None, DATA])
def test_the_words_are_banned_in_attribute_values_too(tag, data):
    """구현 검토 6회 — a description meta is published text. The data-tg ids are not a hit."""
    h = page(views=VIEWS if data else None)
    assert check(h, data=data) == []
    v = check(h.replace('</head>', tag + '</head>', 1) if 'meta' in tag else h.replace('<p>요약.</p>', '<p>요약.</p>' + tag, 1), data=data)
    assert any('태그 속성' in m for m in v), v


def test_the_word_rule_runs_without_a_file_too():
    """구현 검토 1회 #6 — 「발행본에 그 단어가 없다」 is not a promise about days with a file."""
    v = check(page(views=None, prose={'today': '<p>텔레그램 창업자가 방일했다.</p>'}), data=None)
    assert any('텔레그램' in m for m in v) and not any('strip' in m for m in v)
    block = BLOCK.replace('제목', '텔레그램 창업자 발언')
    assert any('뉴스 절 안' in m for m in check(page(views=None, prose={'news': block}), data=None, news=NEWS))


# ── 움직인 종목 문단: 검사한 것만 뺀다 ──────────────────────────────────

def test_mover_paragraph_outside_a_prose_section_is_blocked():
    h = page(views=None).replace('<p>요약.</p>', '<p>요약.</p><p data-mover="g9" class="caption">가짜 수치 987,654엔이다.</p>', 1)
    v = check(h, data=None)
    assert any('data-mover' in m and '절 밖' in m for m in v)


# ── 칸 빼기 ──────────────────────────────────────────────────────────────

def test_strip_removes_the_section_from_page_and_body():
    h, n = tg_news.strip_section(page())
    assert n == 1 and 'data-tg' not in h and check(h) == [] and check(h, data=None) == []
    b, n = tg_news.strip_section(body())
    assert n == 1 and R.validate_body(b, R.SECTIONS) == []
    one_marker = body().replace(' data-tg-section', '')
    b, n = tg_news.strip_section(one_marker)
    assert n == 1 and 'data-section="views"' not in b
    assert tg_news.strip_section(page(views=None))[1] == 0


# ── 근거 경로·진단·발행 고정 ────────────────────────────────────────────

def _root(tmp_path, data=DATA, html=None, published=False):
    d = tmp_path / 'japan' / 'data'
    (d / 'daily' / 'candidate').mkdir(parents=True)
    (d / 'daily' / 'candidate' / f'{S}.json').write_text(json.dumps(SNAP, ensure_ascii=False), encoding='utf-8')
    if published:
        (d / 'daily' / f'{S}.json').write_text(json.dumps(SNAP, ensure_ascii=False), encoding='utf-8')
    if data is not None:
        (d / 'telegram').mkdir(parents=True)
        (d / 'telegram' / f'{S}.json').write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
    if html is not None:
        (tmp_path / 'japan' / 'daily').mkdir(parents=True)
        (tmp_path / 'japan' / 'daily' / f'{S}.html').write_text(html, encoding='utf-8')
    return tmp_path


def test_telegram_path_before_and_after_publication(tmp_path):
    root = _root(tmp_path)
    assert B.telegram_path(root, S) == root / 'japan' / 'data' / 'telegram' / f'{S}.json'
    assert B.load_telegram(root, S)[0]['items'][0]['id'] == f'{CH}/101'
    (root / 'japan' / 'data' / 'daily' / f'{S}.json').write_text('{}', encoding='utf-8')
    assert B.telegram_path(root, S) == root / 'japan' / 'data' / 'telegram' / 'published' / f'{S}.json'
    assert B.load_telegram(root, S) == (None, None)            # published, nothing pinned: absent


@pytest.mark.parametrize('data,why', [
    (dict(DATA, usable=False, unusable_why=['컷 전에 시작한 실행']), 'usable'),
    ({k: v for k, v in DATA.items() if k != 'usable'}, 'usable'),
    (dict(DATA, report_date='2026-10-23'), 'report_date'),
    (dict(DATA, items=None), '형식'),
    (dict(DATA, items=[None]), '형식'),
    (dict(DATA, items=[{'summary_ko': 'x'}]), '형식'),
    (dict(DATA, items=[dict(I1, id=7)]), '형식'),
    (dict(DATA, items=[dict(I1, summary_ko=3)]), '형식'),
    ([], '형식'),
])
def test_a_file_that_is_not_usable_is_absent(tmp_path, data, why):
    root = _root(tmp_path, data=data)
    got, note = B.load_telegram(root, S)
    assert got is None and why in note


def test_a_broken_file_is_absent(tmp_path):
    root = _root(tmp_path)
    (root / 'japan' / 'data' / 'telegram' / f'{S}.json').write_text('{"items": [', encoding='utf-8')
    got, note = B.load_telegram(root, S)
    assert got is None and '읽지 못했다' in note


def test_diag_reports_candidates_only_for_a_usable_file(tmp_path, capsys):
    root = _root(tmp_path, data=tg(I1, dict(I2, news_use=False, news_skip='junk')))
    B.main(['diag', '--session', S, '--root', str(root)])
    out = capsys.readouterr().out
    assert '견해·의견 후보 1건' in out and f'telegram/{S}.json' in out
    (root / 'japan' / 'data' / 'telegram' / f'{S}.json').write_text(
        json.dumps(dict(DATA, usable=False, unusable_why=['요약기 중단'])), encoding='utf-8')
    B.main(['diag', '--session', S, '--root', str(root)])
    out = capsys.readouterr().out
    assert '견해·의견: 없음' in out and '요약기 중단' in out and '후보' not in out.split('견해·의견')[1]
    (root / 'japan' / 'data' / 'telegram' / f'{S}.json').unlink()
    B.main(['diag', '--session', S, '--root', str(root)])
    assert '견해·의견: 없음(파일 없음)' in capsys.readouterr().out


def test_diag_shows_what_the_valve_dropped(tmp_path, capsys):
    root = _root(tmp_path, data=dict(DATA, stats={'valve_dropped': 3}))
    B.main(['diag', '--session', S, '--root', str(root)])
    assert '안전 한도로 3건' in capsys.readouterr().out


def test_cli_prints_pairs_and_ignores_a_non_usable_file(tmp_path, capsys):
    import check_japan_daily as CLI
    root = _root(tmp_path, html=page())
    assert CLI.main(['--session', S, '--root', str(root)]) == 0
    out = capsys.readouterr().out
    assert '견해·의견 다시 읽기 3건' in out and SUM1 in out
    (root / 'japan' / 'data' / 'telegram' / f'{S}.json').write_text(json.dumps(dict(DATA, usable=False)), encoding='utf-8')
    assert CLI.main(['--session', S, '--root', str(root)]) == 1
    cap = capsys.readouterr()
    assert '없는 것으로 본다' in cap.out and '쓸 수 있는 텔레그램 파일이 없다' in cap.err


# 발행 고정(견해 파일을 글과 함께 고정)은 실행 격리 뒤 검증 기록으로 정한다 —
# scripts/japan/tests/test_jpd_publish_run.py·test_publish_daily.py (2026-11-19).
