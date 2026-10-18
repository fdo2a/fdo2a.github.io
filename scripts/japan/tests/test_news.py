"""일본 주간 전용 뉴스 — Yahoo!ファイナンス 목록·기사면·선별(2026-10-18).

기사 본문은 상업 저작물이라 픽스처는 실제 페이지의 **구조만** 흉내 낸 합성 HTML 이다.
"""
import json

import pytest

from japan import news as N

ID1, ID2, ID3 = 'a' * 40, 'b' * 40, 'c' * 40


def _list_page(articles):
    state = {'mainNewsCategory': {'news': {'articles': articles,
                                           'paging': {'totalSize': 1000, 'page': 1}}}}
    return f'<html><script>window.__PRELOADED_STATE__ = {json.dumps(state, ensure_ascii=False)}</script></html>'


def _art(id_, title, media='ロイター', created='19:30', paid=False):
    return {'headline': title, 'link': f'https://finance.yahoo.co.jp/news/detail/{id_}',
            'mediaName': media, 'summary': None, 'createTime': created, 'isPaidArticle': paid}


BODY = '日銀の植田和男総裁は１６日、基調的な物価上昇率について議論すると述べた。' * 12


def _detail(body=BODY, paid=False, caption=True, template='bodyText'):
    cap = ('<div class="x__ArticleBody__caption">写真は日銀本店。REUTERS/Issei Kato</div>'
           if caption else '')
    if template == 'bodyText':
        inner = f'<div class="x__ArticleBody__text"><p class="x__ArticleBody__bodyText">{body}</p></div>'
    else:
        inner = f'<div class="x__ArticleBody__paragraph"><p>{body}</p></div>'
    vip = '<aside class="_VipPurchase_1"><p>続きをお読みいただくには</p></aside>' if paid else ''
    return ('<html><head><script type="application/ld+json">{"datePublished":"2026-10-16T18:42:12+09:00"}'
            '</script></head><body><nav><p>' + 'ポートフォリオ' * 40 + '</p></nav><article>'
            f'<div class="x__ArticleDetail__body">{cap}{inner}</div>{vip}'
            '<p class="x__ArticleDetail__media">ロイター</p></article>'
            '<aside><p>' + '関連記事の見出しが並ぶ。' * 40 + '</p></aside></body></html>')


# ── 목록 ──────────────────────────────────────────────────────────────
def test_parse_list_reads_the_preloaded_state():
    rows = N.parse_list(_list_page([_art(ID1, '日銀、利上げ継続'), {'headline': 'x', 'link': '/no'}]), 'bus_all')
    assert rows == [{'guid': ID1, 'url': f'https://finance.yahoo.co.jp/news/detail/{ID1}',
                     'title': '日銀、利上げ継続', 'source': 'ロイター', 'created': '19:30',
                     'paid': False, 'feed': 'bus_all'}]


@pytest.mark.parametrize('html', ['<html>no state</html>',
                                  '<script>window.__PRELOADED_STATE__ = {"other": 1}</script>'])
def test_parse_list_refuses_a_changed_shape(html):
    with pytest.raises(ValueError):
        N.parse_list(html, 'bus_all')


@pytest.mark.parametrize('created,today,want', [
    ('19:30', '2026-10-17', '2026-10-17'),
    ('10/16', '2026-10-17', '2026-10-16'),
    ('12/30', '2027-01-02', '2026-12-30'),       # 연도 경계
    ('昨日', '2026-10-17', None),
    ('2/30', '2026-10-17', None),
])
def test_list_day(created, today, want):
    assert N.list_day(created, today) == want


def test_reached_stops_paging_once_an_older_day_shows_up():
    assert not N.reached([{'created': '10/16'}], '2026-10-16', '2026-10-17')
    assert N.reached([{'created': '10/15'}], '2026-10-16', '2026-10-17')


# ── 갈래 ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize('title,want', [
    ('日銀の植田総裁、基調物価２％に「かなり近づいている」', 'macro'),
    ('秩序ある為替市場の維持に取り組んでいきたい＝片山財務相', 'macro'),
    ('日本政府、中国産の二酸化チタン顔料などの反ダンピング調査開始', 'policy'),
    ('東証大引け　日経平均は続落', 'market'),
    ('トヨタ、30年までに全車種をＳＤＶに', 'industry'),
    ('米国の消費者物価、９月は前年比３．２％上昇', 'global'),
    ('米9月輸入物価、前年比8.1％上昇', 'global'),
    ('インフレ期待悪化なら積極的な利上げ必要も＝クリーブランド連銀総裁', 'global'),
    ('中国人民銀総裁、金融市場開放加速と人民元国際化推進表明', 'global'),
    ('日経平均、NY株安受け反落', 'market'),
    # 버리는 것 — 해외 증시 마감·시세 단신·일정표·종목 나열
    ('NY株反落、175ドル安＝原油高やAI投資不安', None),
    ('〔NY石油〕WTI6日続伸、97．97ドル', None),
    ('アジア株式市場サマリー：引け（16日）', None),
    ('円相場、158円00～01銭＝16日午後5時現在', None),
    ('日経平均は反発で寄り付く', None),
    ('今週の決算発表予定 ブロンコＢ、ディスコ', None),
    ('発表迫る、好業績＆低PBRの27年3月期【上方修正】期待リスト', None),
    ('「のぞみ」指定席値上げ＝最大880円', None),
])
def test_classify(title, want):
    assert N.classify(title) == want


def test_rice_is_not_america():
    assert N.classify('米価高騰、農水省が備蓄米放出へ') != 'global'


def test_screen_drops_paid_and_unlisted_media():
    rows = [dict(guid='1', title='日銀、利上げ継続', source='ロイター', paid=True),
            dict(guid='2', title='日銀、利上げ継続', source='LIMO', paid=False),
            dict(guid='3', title='日銀、利上げ継続', source='時事通信', paid=False)]
    kept, dropped = N.screen(rows)
    assert [r['guid'] for r in kept] == ['3'] and kept[0]['category'] == 'macro'
    assert dropped == {'유료': 1, '매체 LIMO': 1}


# ── 같은 사건 ─────────────────────────────────────────────────────────
def test_different_figures_are_different_events():
    assert not N.same_event('米国の消費者物価、９月は前年比３．２％上昇', '英国の消費者物価、９月は前年比２．８％上昇')


def test_a_rewrite_of_the_same_story_is_the_same_event():
    assert N.same_event('〔NY石油〕WTI6日続伸、97．97ドル＝3週間ぶり高値水準（15日）',
                        '〔NY石油〕WTI6日続伸、97．97ドル＝3週間ぶり高値水準（15日、続き）')


def _row(guid, cat, title, body=500, day='2026-10-16', source='ロイター'):
    return {'guid': guid, 'category': cat, 'title': title, 'source': source,
            'body_chars': body, 'published': f'{day}T10:00:00+09:00'}


def test_finalize_caps_each_category_and_falls_back_to_the_next_candidate():
    rows = [_row('1', 'macro', '日銀、利上げ継続', body=0),          # 본문 실패 → 다음 후보
            _row('2', 'macro', '日銀総裁、物価に言及'),
            _row('3', 'macro', '日銀総裁、物価に言及す'),              # 2 의 재탕
            _row('4', 'macro', '財務相、為替介入に言及'),
            _row('5', 'macro', '長期金利が上昇'),
            _row('6', 'macro', '国債入札が不調'),
            _row('7', 'macro', '物価見通しを上方修正', day='2026-10-15')]   # 다른 날
    got = [r['guid'] for r in N.finalize(rows, '2026-10-16')]
    assert got == ['2', '4', '5']


def test_preselect_puts_official_sources_and_wires_first():
    rows = [_row('k', 'insight', 'x', source='株探ニュース'),
            dict(_row('b', 'insight', 'y', source='Bank of Japan'), official=True)]
    assert [r['guid'] for r in N.preselect(rows)] == ['b', 'k']


# ── 기사면 ────────────────────────────────────────────────────────────
@pytest.mark.parametrize('template', ['bodyText', 'paragraph'])
def test_extract_body_reads_only_the_article_region(template):
    body = N.extract_body(_detail(template=template))
    assert body.startswith('日銀の植田和男総裁') and 'REUTERS' not in body
    assert 'ポートフォリオ' not in body and '関連記事' not in body


def test_paid_page_has_no_body():
    html = _detail(paid=True)
    assert N.extract_body(html) == '' and N.body_note(html) == '유료'


def test_short_or_missing_region_has_no_body():
    assert N.extract_body(_detail(body='短い。')) == ''
    assert N.body_note('<html><p>' + 'x' * 900 + '</p></html>') == '본문 영역 없음'
    assert N.extract_body('<html><p>' + 'x' * 900 + '</p></html>') == ''


def test_zero_width_characters_are_removed():
    assert '‌' not in N.extract_body(_detail(body=('金融政‌策を議論した。' * 40)))


def test_page_published_is_jst():
    assert N.page_published(_detail()) == '2026-10-16T18:42:12+09:00'
    assert N.page_published('<time dateTime="2026-10-16T09:00:00Z">') == '2026-10-16T18:00:00+09:00'
    assert N.page_published('<p>no date</p>') is None


def test_nli_page_without_its_summary_marker_has_no_body():
    from us.news import _nli_body
    assert _nli_body('<html><p>' + '研究所の紹介文が続く。' * 80 + '</p></html>') == ''


def test_decimal_figures_keep_events_apart():
    assert not N.same_event('日本のGDP、前年比１．２％増', '日本のGDP、前年比１２％増')
    assert not N.same_event('【3.2%】米CPI上昇', '【2.8%】米CPI上昇')


def test_body_stops_where_the_body_element_closes():
    html = ('<article><div class="x__ArticleDetail__body"><div class="x__ArticleBody__text">'
            '<p>短い本文。</p></div></div><div class="related"><p>' + '推薦記事の文句。' * 60 +
            '</p></div><p class="x__ArticleDetail__media">ロイター</p></article>')
    assert N.extract_body(html) == ''
    nested = ('<div class="x__ArticleDetail__body"><div><div><p>' + BODY + '</p></div></div>'
              '<figure><p>図の説明。</p></figure></div><p>' + '外の文。' * 50 + '</p>')
    got = N.extract_body(nested)
    assert got.startswith('日銀の植田') and '外の文' not in got and '図の説明' not in got


def test_thousands_separators_do_not_split_figures():
    assert N.same_event('日銀、国債買入額を1,200億円に縮小', '日銀、国債買入額を1200億円に縮小')
