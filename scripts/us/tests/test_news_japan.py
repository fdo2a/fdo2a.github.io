"""일본 출처 (2026-09-26 사용자 지시 「일본 관련 뉴스나 레포트, 칼럼같은건 어떻게 할 수 있을지
방법을 찾아서 추가해」) — scripts/us/news.py.

Yahoo!ニュース 경제(교도·지지 등 통신 기사), 일본은행 정책 발표문(PDF)·연설, 닛세이기초연구소
리포트. 픽스처는 2026-09-26 실제 페이지의 **모양만** 본뜬 합성 문장이다.
"""
from datetime import datetime, timezone

import pytest

import fetch_news as FN
from us import news as N
from us import news_summary as S

NOW = datetime(2026, 9, 25, 22, 0, tzinfo=timezone.utc)
YAHOO = 'https://news.yahoo.co.jp/articles/12e78248debdfaf68e589865f8760bab4022a508?source=rss'


# ── 등록부 ───────────────────────────────────────────────────────────────
def test_japan_feeds_are_registered():
    assert any('news.yahoo.co.jp/rss/categories/business' in u for u in N.FEEDS['global'])
    assert any('nli-research.co.jp' in u for u in N.FEEDS['insight'])


def test_boj_pages_are_registered_by_year():
    pages = N.pages(2026)
    urls = {cat: [u for u, _ in rows] for cat, rows in pages.items()}
    assert 'https://www.boj.or.jp/en/mopo/mpmdeci/state_2026/index.htm' in urls['global']
    assert 'https://www.boj.or.jp/en/about/press/koen_2026/index.htm' in urls['insight']


@pytest.mark.parametrize('url,name', [
    (YAHOO, 'Yahoo!ニュース'),
    ('https://www.boj.or.jp/en/about/press/koen_2026/ko260910a.htm', 'Bank of Japan'),
    ('http://www.nli-research.co.jp/report/detail/id=86896?site=nli', 'ニッセイ基礎研究所'),
])
def test_japanese_hosts_have_names(url, name):
    assert N.source_name(url) == name


# ── Atom (닛세이기초연구소) ─────────────────────────────────────────────────
def test_atom_entries_are_parsed():
    xml = ('<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><title>x</title>'
           '<entry><title><![CDATA[中国：26年7～9月期の成長率予測]]></title>'
           '<link rel="alternate" href="http://www.nli-research.co.jp/report/detail/id=86896?site=nli"/>'
           '<id>tag:nli,86896</id><updated>2026-09-25T13:12:11+09:00</updated>'
           '<summary><![CDATA[要旨の一部]]></summary></entry></feed>')
    [it] = N.parse_feed(xml, 'insight')
    assert it['url'] == 'http://www.nli-research.co.jp/report/detail/id=86896?site=nli'
    assert it['title'] == '中国：26年7～9月期の成長率予測'
    assert it['published'] == '2026-09-25T13:12:11+09:00'
    assert it['source'] == 'ニッセイ基礎研究所'
    assert it['summary'] == '要旨の一部'


# ── 분류 ─────────────────────────────────────────────────────────────────
def y(title):
    return {'title': title, 'category': 'global', 'url': YAHOO}


@pytest.mark.parametrize('title,want,region', [
    ('強い円が望ましいと米財務長官(共同通信)', 'global', 'japan'),
    ('日銀、追加利上げを決定　政策金利0.75%に(時事通信)', 'global', 'japan'),
    ('中国、米国産農産物の購入拡大か(共同通信)', 'global', 'china'),
    ('ホルムズ海峡の封鎖解除で原油急落(ロイター)', 'global', 'mideast'),
    ('為替相場 26日（日本時間 3時）(共同通信)', None, None),       # 정례 시세표
    ('日経平均、終値は300円高(共同通信)', None, None),              # 시황
    ('「フェラーリ フェスティバル東京2026」開催(webCG)', None, None),
    ('姫路独協大 徳洲会に経営権譲渡へ', None, None),
])
def test_yahoo_japan_titles(title, want, region):
    it = y(title)
    assert N.classify(it) == want
    if want:
        assert N.region_of(it) == region


@pytest.mark.parametrize('title,want', [
    ('中国：26年7～9月期の成長率予測－勢いを欠く状態が続く見込み', 'insight'),
    ('「106万円の壁」撤廃で変わるパート雇用', 'insight'),
    ('日本に居ながら時差ぼけ？－ソーシャル・ジェットラグに悩む現代人', None),   # 생활 리포트
])
def test_nli_reports_need_an_economic_subject(title, want):
    it = {'title': title, 'category': 'insight',
          'url': 'http://www.nli-research.co.jp/report/detail/id=1?site=nli'}
    assert N.classify(it) == want


def test_japanese_research_rows_carry_the_japan_region():
    [it] = N.categorize([{'title': 'MASU Kazuyuki: Economic Activity, Prices, and Monetary Policy',
                          'category': 'insight',
                          'url': 'https://www.boj.or.jp/en/about/press/koen_2026/ko260910a.htm'}])
    assert (it['category'], it['region']) == ('insight', 'japan')


def test_japan_goes_first_in_the_rotation():
    rows = [dict(guid=g, title=t, category='global', region=r, published='2026-09-25T12:00:00+00:00')
            for g, t, r in [('e', 'ECB rate path', 'europe'), ('c', 'China cuts rates', 'china'),
                            ('j', '日銀 利上げ', 'japan')]]
    assert N.select(rows, now=NOW)[0]['guid'] == 'j'


def test_insight_keeps_one_japan_slot_among_western_columns():
    rows = [dict(guid=f'i{i}', title=t, category='insight', source=s,
                 published='2026-09-25T12:00:00+00:00', body_chars=900)
            for i, (t, s) in enumerate([('CNB Minutes', 'ING THINK'), ('Yen view', 'Investing.com'),
                                        ('Speeches move markets', 'ECB'), ('Transition', 'BIS'),
                                        ('Europe fiscal', 'Bruegel')])]
    rows.append(dict(guid='boj', title='Japan’s Economy and Monetary Policy', category='insight',
                     region='japan', source='Bank of Japan', published='2026-09-25T00:00:00+09:00',
                     body_chars=900))
    got = [r['guid'] for r in N.trim(rows, now=NOW)]
    assert got[0] == 'boj'
    assert len(got) == N.FINAL['insight']


# ── 일본은행 목록 ─────────────────────────────────────────────────────────
_SPEECHES = ('<table><tr><th>Date</th><th>Speaker</th><th>Title</th></tr>'
             '<tr><td>Sept.&nbsp;10,&nbsp;2026</td><td>MASU Kazuyuki, Member of the Policy Board</td>'
             '<td><a href="/en/about/press/koen_2026/ko260910a.htm">&quot;Economic Activity, Prices, and '
             'Monetary Policy in Japan&quot; (Speech at a Meeting with Local Leaders in Fukui)</a>&nbsp;</td></tr>'
             '<tr><td>Aug.&nbsp;27,&nbsp;2026</td><td>HIMINO Ryozo, Deputy Governor</td>'
             '<td><a href="/en/about/press/koen_2026/ko260827a.htm">&quot;Japan\'s Economy and Monetary '
             'Policy&quot;</a></td></tr></table>')

_STATEMENTS = ('<table><tr><th>Date</th><th>Title</th></tr>'
               '<tr><td>Sept.&nbsp;18,&nbsp;2026</td><td><a href="/en/mopo/mpmdeci/mpr_2026/k260918b.pdf">'
               '(Reference) Change in the Guideline for Money Market Operations (September 2026 MPM)'
               '&nbsp;[PDF&nbsp;197KB]</a></td></tr>'
               '<tr><td>Sept.&nbsp;18,&nbsp;2026</td><td><a href="/en/mopo/mpmdeci/mpr_2026/k260918a.pdf">'
               'Change in the Guideline for Money Market Operations&nbsp;[PDF&nbsp;204KB]</a></td></tr>'
               '<tr><td>July&nbsp;31,&nbsp;2026</td><td><a href="/en/mopo/mpmdeci/mpr_2026/k260731a.pdf">'
               'Statement on Monetary Policy&nbsp;[PDF&nbsp;160KB]</a></td></tr></table>')


def test_boj_speech_index_becomes_rows():
    rows = N.parse_boj_speeches(_SPEECHES, 'insight')
    assert [r['url'] for r in rows] == [
        'https://www.boj.or.jp/en/about/press/koen_2026/ko260910a.htm',
        'https://www.boj.or.jp/en/about/press/koen_2026/ko260827a.htm']
    first = rows[0]
    assert first['title'].startswith('MASU Kazuyuki, Member of the Policy Board: "Economic Activity')
    assert first['published'] == '2026-09-10T00:00:00+09:00'
    assert first['source'] == 'Bank of Japan'
    assert first['category'] == 'insight'
    assert rows[1]['published'] == '2026-08-27T00:00:00+09:00'


def test_boj_statement_index_skips_reference_copies():
    rows = N.parse_boj_statements(_STATEMENTS, 'global')
    assert [r['title'] for r in rows] == ['Change in the Guideline for Money Market Operations',
                                          'Statement on Monetary Policy']
    assert rows[0]['url'] == 'https://www.boj.or.jp/en/mopo/mpmdeci/mpr_2026/k260918a.pdf'
    assert rows[0]['published'] == '2026-09-18T00:00:00+09:00'


def test_boj_statements_are_global_policy_news():
    [row] = N.parse_boj_statements(_STATEMENTS, 'global')[:1]
    assert N.classify(row) == 'global'
    assert N.region_of(row) == 'japan'


def test_a_page_without_a_table_is_reported_not_silent():
    with pytest.raises(ValueError):
        N.parse_boj_speeches('<html>maintenance</html>', 'insight')


# ── 본문 ─────────────────────────────────────────────────────────────────
def test_yahoo_body_starts_at_the_article_not_the_sidebar():
    side = '<p>' + '「タイプロは失敗だったのか」と話題の芸能ニュースがランキング上位に入っている。' * 2 + '</p>'
    body = ('<p>' + '【ワシントン共同】ベセント米財務長官は25日、片山財務相との電話会談で日本の経済の'
            '基礎的条件を反映した強い円が望ましいとの認識を示した。' * 8 + '</p>')
    html = f'<html>{side}<div class="article_body highLightSearchTarget">{body}</div></html>'
    got = N.extract_body(html)
    assert got.startswith('【ワシントン共同】')
    assert 'タイプロ' not in got


def test_nli_body_runs_from_the_summary_to_the_share_buttons():
    html = ('<div class="cont_report detail">NEW 2026年09月25日 三浦 祐介 文字サイズ 小 中 大 '
            '<p>■要旨</p><p>' + '中国の2026年4～6月期の実質GDP成長率は前年同期比4.3%と減速した。' * 12
            + '</p><p>はてなブックマーク LinkedIn X Facebook</p><p>メルマガ配信中! ' + 'x' * 200 + '</p></div>')
    got = N.extract_body(html)
    assert got.startswith('中国の2026年4～6月期')
    assert 'はてな' not in got and 'メルマガ' not in got


def test_pdf_text_is_empty_rather_than_a_crash_on_garbage():
    assert N.pdf_text(b'not a pdf') == ''


def test_fetch_bodies_reads_pdfs_as_bytes(tmp_path, monkeypatch):
    monkeypatch.setattr(N, 'pdf_text', lambda data: 'The Bank will raise the policy interest rate. ' * 20)
    monkeypatch.setattr(FN, 'pdf_text', N.pdf_text)
    rows = [{'url': 'https://www.boj.or.jp/en/mopo/mpmdeci/mpr_2026/k260918a.pdf',
             'title': 'Change in the Guideline', 'category': 'global',
             'published': '2026-09-18T00:00:00+09:00'}]
    FN.fetch_bodies(rows, str(tmp_path), None,
                    fetch=lambda u, c: pytest.fail('text fetch for a PDF'),
                    fetch_bytes=lambda u, c: b'%PDF-1.7')
    assert rows[0]['body_chars'] > 400


def test_yahoo_wire_comes_from_the_title_suffix():
    assert N.title_wire('強い円が望ましいと米財務長官(共同通信)') == '共同通信'
    assert N.title_wire('Plain title') is None


# ── 요약 프롬프트 ─────────────────────────────────────────────────────────
def test_both_foreign_prompts_accept_japanese_sources():
    assert '일본어' in S.SYSTEM and '일본어' in S.SYSTEM_ANALYSIS


def test_a_western_column_about_japan_does_not_take_the_japan_research_slot():
    # 2026-09-26 실수집: Investing.com 「US-Japan Coordination Snaps Yen Slide」 가 일본 칸을 차지해
    # 닛세이기초연구소 리포트가 후보에서 밀려났다. 칼럼의 칸은 **발행 기관**이 정한다.
    rows = N.categorize([
        {'title': 'US Dollar Steadies as US-Japan Coordination Snaps Yen Slide', 'category': 'insight',
         'url': 'https://www.investing.com/analysis/a-1'},
        {'title': '中国：26年7～9月期の成長率予測', 'category': 'insight',
         'url': 'http://www.nli-research.co.jp/report/detail/id=86896?site=nli'}])
    assert [r.get('region') for r in rows] == [None, 'japan']


def test_yahoo_body_stops_before_the_related_articles():
    # 2026-09-26 실수집: 한 문단짜리 교도 속보 뒤에 추천 기사·푸터가 붙어 본문 하한을 채웠다
    body = '<p>' + '【ワシントン共同】ベセント米財務長官は25日、強い円が望ましいと述べた。' * 2 + '</p>'
    tail = ('<section><h3>【関連記事】</h3><ul><li>' + '江ノ電などクレカのタッチ決済でVポイントを付与する新サービス' * 4
            + '</li></ul></section><p>' + '「タイプロは失敗だった」と話題の芸能ニュースがランキング上位に入った。' * 6 + '</p>')
    html = f'<div class="article_body highLightSearchTarget">{body}</div>{tail}'
    assert N.extract_body(html) == ''            # 진짜 본문은 하한 미달 — 채워 넣지 않는다


@pytest.mark.parametrize('title,want', [
    ('新型EVを披露、国内販売を強化', None),          # 披露 의 露 는 러시아가 아니다
    ('独自の経済対策を検討', None),                  # 独自 의 独 은 독일이 아니다
    ('露大統領、原油輸出の制限を表明', 'europe'),
    ('独首相、財政ルール見直しを表明', 'europe'),
])
def test_one_character_country_abbreviations_need_context(title, want):
    assert N.region(title) == want
