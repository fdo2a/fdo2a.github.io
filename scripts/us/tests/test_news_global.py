"""「글로벌」·「리포트·칼럼」 갈래 (2026-09-26) — scripts/us/news.py.

사용자 지시: 미국·한국 밖(일본·중국·유럽·중동)의 정책·경제 뉴스, 그리고 공신력 있는 기관의
리포트·칼럼. 헤드라인은 2026-09-25 실제 피드에서 본뜬 모양이다.
"""
from datetime import datetime, timezone

import pytest

from us import news as N

NOW = datetime(2026, 9, 25, 22, 0, tzinfo=timezone.utc)


def rec(guid, cat, title='T', published='2026-09-25T12:00:00+00:00', region=None, **kw):
    row = {'guid': guid, 'url': f'https://www.cnbc.com/{guid}.html', 'title': title,
           'category': cat, 'published': published, 'source': 'CNBC'}
    if region:
        row['region'] = region
    row.update(kw)
    return row


# ── 등록부 ───────────────────────────────────────────────────────────────
def test_the_digest_adds_global_and_insight_at_the_end():
    assert N.DIGEST_CATEGORIES[-2:] == ('global', 'insight')
    assert N.LABELS['global'] == '글로벌'
    assert N.LABELS['insight'] == '리포트·칼럼'


def test_global_and_insight_have_their_own_feed_bundles():
    assert N.FEEDS['global'] and N.FEEDS['insight']
    hosts = {u.split('/')[2] for u in N.FEEDS['global'] + N.FEEDS['insight']}
    # 로이터 기사는 Investing.com 이 전재한 것으로 받는다 — reuters.com 은 401 이다
    assert 'www.reuters.com' not in hosts
    assert {'www.investing.com', 'www.ecb.europa.eu', 'think.ing.com'} <= hosts


# ── 출처 이름 ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize('url,name', [
    ('https://www.cnbc.com/2026/09/25/a.html', 'CNBC'),
    ('https://finance.yahoo.com/news/a.html', 'Yahoo Finance'),
    ('https://www.investing.com/news/economy-news/a', 'Investing.com'),
    ('https://www.ecb.europa.eu/press/pr/date/2026/html/a.en.html', 'ECB'),
    ('https://www.bankofengland.co.uk/news/2026/a', 'Bank of England'),
    ('https://www.bis.org/speeches/20260924-a', 'BIS'),
    ('https://think.ing.com/articles/a/', 'ING THINK'),
    ('https://www.theguardian.com/business/2026/a', 'The Guardian'),
    ('https://www.aljazeera.com/economy/2026/a', 'Al Jazeera'),
    ('https://www.bbc.com/news/articles/a', 'BBC'),
])
def test_source_name_follows_the_host(url, name):
    assert N.source_name(url) == name


def test_parse_feed_names_the_source_by_host():
    xml = ('<rss><channel><item><link>https://think.ing.com/snaps/a/</link>'
           '<title>A</title><dc:date>2026-09-25T12:01:00+00:00</dc:date></item></channel></rss>')
    [it] = N.parse_feed(xml, 'insight')
    assert it['source'] == 'ING THINK'
    assert it['published'] == '2026-09-25T12:01:00+00:00'      # dc:date 폴백


def test_rdf_items_container_is_not_read_as_an_item():
    # BIS 는 RDF 다 — <items><rdf:Seq> 를 첫 item 으로 읽으면 안 된다
    xml = ('<rdf:RDF><channel><items><rdf:Seq><rdf:li resource="x"/></rdf:Seq></items></channel>'
           '<item rdf:about="https://www.bis.org/speeches/a"><link>https://www.bis.org/speeches/a</link>'
           '<title>Speech A</title><dc:date>2026-09-24T09:00:00Z</dc:date></item></rdf:RDF>')
    rows = N.parse_feed(xml, 'insight')
    assert [r['title'] for r in rows] == ['Speech A']
    assert rows[0]['published'] == '2026-09-24T09:00:00+00:00'


# ── 지역 ─────────────────────────────────────────────────────────────────
@pytest.mark.parametrize('title,want', [
    ('Switzerland is keeping rates at 0% — for now', 'europe'),
    ('France can’t count on ECB to fix debt woes, central bank chief says', 'europe'),
    ('Zelenskyy says Ukraine ready for energy ceasefire', 'europe'),
    ('China confirms first AI talks with U.S., hints at trade truce extension', 'china'),
    ('BOJ keeps rates steady, signals hike in December', 'japan'),
    ('Saudi Arabia crude oil exports hit highest level since Iran war began', 'mideast'),
    ('Oil prices drop as US, Iran explore path out of war', 'mideast'),
    ('Hurricane shuts Gulf of Mexico oil output', None),         # 멕시코만은 중동이 아니다
    ('Warsh’s regime change at the Fed pushes ahead', None),
    ('India’s viral Cockroach Party calls election panel head a threat', None),
])
def test_region_is_read_from_the_title(title, want):
    assert N.region(title) == want


def test_the_first_region_named_wins():
    assert N.region('Iran tensions weigh on China’s oil imports') == 'mideast'


# ── 갈래 분류 ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize('title,hint,want', [
    # 지역 + 정책·경제 → 글로벌. 출처 피드는 상관없다
    ('Switzerland is keeping rates at 0% — for now', 'global', 'global'),
    ('U.S.-China trade truce extended for two months, Bessent says', 'politics', 'global'),
    ('ECB raises rates for the first time since 2023', 'pool', 'global'),
    ('Saudi Arabia crude oil exports hit highest level since Iran war began', 'global', 'global'),
    # 지역은 있는데 정책·경제가 아니면 글로벌 피드에서 버린다
    ('Here’s who attended the Trump-Xi state dinner', 'global', None),
    ('Atlanta is getting pandas: China’s Xi revives a longtime diplomatic strategy', 'global', None),
    ('Oracle Japan shares surge 7% after record fiscal first quarter', 'global', None),
    ('Russia could attack a NATO country within months, Danish intelligence warns', 'global', None),
    # 지역이 없으면 글로벌이 아니다
    ('Bentley takes on Ferrari with its first EV priced at $230,000', 'global', None),
    ('Warsh’s regime change at the Fed pushes ahead', 'global', None),
    # 글로벌이 아닌 기사는 예전 규칙 그대로
    ('The Fed holds rates steady', 'pool', 'macro'),
    ('OpenAI raises funding', 'tech', 'ai'),
])
def test_global_needs_a_region_and_a_policy_or_economy_word(title, hint, want):
    assert N.classify({'title': title, 'category': hint}) == want


def test_official_feeds_supply_the_region_themselves():
    it = {'title': 'Monetary policy decisions', 'category': 'global',
          'url': 'https://www.ecb.europa.eu/press/pr/date/2026/html/a.en.html'}
    assert N.classify(it) == 'global'
    assert N.region_of(it) == 'europe'


def test_an_official_notice_without_policy_content_is_dropped():
    it = {'title': 'Minutes of the Market Participants Group meeting', 'category': 'global',
          'url': 'https://www.bankofengland.co.uk/minutes/2026/a'}
    assert N.classify(it) is None


def test_categorize_records_the_region_for_global_rows():
    [it] = N.categorize([{'title': 'BOJ keeps rates steady', 'category': 'global',
                          'url': 'https://www.cnbc.com/a.html'}])
    assert (it['category'], it['region']) == ('global', 'japan')


@pytest.mark.parametrize('title,want', [
    ('USD/JPY: The Yen Tide Is Turning, but the Beach Is Already Crowded', 'insight'),
    ('RBA Preview: A Decisive Hike to Keep Inflation in Check', 'insight'),
    ('Treasury Yields: The Market Is Pricing Stronger Growth, Not Higher Inflation', 'insight'),
    ('Is Palantir Worth $250 or $1? Bulls and Burry Arrive at Opposite Conclusions', 'insight'),
    # 종목 나열형·셋업 글은 인사이트가 아니다
    ('9 Stocks Still Flying Under the Radar With Up to 166% Upside', None),
    ('2 Pre-Market Setups to Watch Before Sunday', None),
    ('Treasury Yields Hit a 19-Year High—These 2 Bond ETFs Offer Monthly Income', None),
    ('Top 5 Dividend Stocks for October', None),
])
def test_insight_feeds_keep_analysis_and_drop_listicles(title, want):
    assert N.classify({'title': title, 'category': 'insight'}) == want


def test_insight_feed_rows_stay_insight_even_with_region_words():
    # 칼럼은 칼럼 칸에 — ING 의 헝가리 노동시장 분석이 글로벌 기사로 가지 않는다
    it = {'title': 'CNB Minutes: Inflationary risks in Czech economy', 'category': 'insight'}
    assert N.classify(it) == 'insight'


# ── 선정: 후보 → 확정 ─────────────────────────────────────────────────────
def test_global_candidates_rotate_regions_before_taking_a_second_from_one():
    china = ['China cuts rates', 'Beijing tariff retaliation', 'China exports slump',
             'Chinese property rescue', 'Hong Kong budget deficit']
    rows = [rec(f'c{i}', 'global', t, region='china') for i, t in enumerate(china)]
    rows += [rec('e1', 'global', 'ECB rate path', region='europe'),
             rec('m1', 'global', 'OPEC oil decision', region='mideast')]
    got = [r['guid'] for r in N.select(rows, now=NOW) if r['category'] == 'global']
    assert set(got[:3]) == {'c0', 'e1', 'm1'}
    assert len(got) == min(7, N.PRESELECT['global'])


def test_the_same_event_from_two_outlets_is_one_candidate():
    rows = [rec('a', 'global', 'US and China extend trade truce for two months', region='china'),
            rec('b', 'global', 'US, China extend trade truce by two months', region='china',
                published='2026-09-25T11:00:00+00:00')]
    got = [r['guid'] for r in N.select(rows, now=NOW)]
    assert got == ['a']


def test_stale_global_rows_are_not_candidates():
    rows = [rec('old', 'global', 'ECB rate path', region='europe',
                published='2026-09-22T12:00:00+00:00'),
            rec('new', 'global', 'BOJ rate path', region='japan')]
    assert [r['guid'] for r in N.select(rows, now=NOW)] == ['new']


def test_undated_global_rows_stay_candidates_until_the_page_gives_a_date():
    rows = [rec('nodate', 'global', 'France debt woes', region='europe', published=None)]
    assert [r['guid'] for r in N.select(rows, now=NOW)] == ['nodate']


def test_more_policy_words_rank_higher_among_candidates():
    rows = [rec('weak', 'global', 'China summit ends', region='china',
                published='2026-09-25T20:00:00+00:00'),
            rec('strong', 'global', 'China cuts rates and expands stimulus as exports slump',
                region='china', published='2026-09-25T10:00:00+00:00')]
    got = [r['guid'] for r in N.select(rows, now=NOW)]
    assert got[0] == 'strong'


def test_existing_categories_keep_their_plain_cap():
    rows = [rec(f'p{i}', 'politics', f'Senate bill {i}') for i in range(5)]
    assert len(N.select(rows, now=NOW)) == 3


def test_trim_keeps_only_bodied_fresh_rows_and_applies_the_final_cap():
    titles = ['China cuts rates', 'ECB holds rates', 'OPEC oil decision', 'BOJ yen policy',
              'Beijing tariff retaliation']
    rows = [rec(f'g{i}', 'global', t, region=r, body_chars=900)
            for i, (t, r) in enumerate(zip(titles, ['china', 'europe', 'mideast', 'japan', 'china']))]
    rows.append(rec('nobody', 'global', 'ECB', region='europe', body_chars=0))
    rows.append(rec('undated', 'global', 'BoE', region='europe', body_chars=900, published=None))
    rows.append(rec('p1', 'politics', 'Senate bill'))                 # 다른 갈래는 손대지 않는다
    got = N.trim(rows, now=NOW)
    g = [r['guid'] for r in got if r['category'] == 'global']
    assert len(g) == N.FINAL['global'] == 4
    assert 'nobody' not in g and 'undated' not in g
    assert {r['region'] for r in got if r['category'] == 'global'} == \
        {'china', 'europe', 'mideast', 'japan'}
    assert 'p1' in [r['guid'] for r in got]


def test_trim_drops_a_row_whose_page_date_turned_out_stale():
    rows = [rec('late', 'insight', 'Yen view', body_chars=900,
                published='2026-09-20T12:00:00+00:00')]
    assert N.trim(rows, now=NOW) == []


# ── 기사면에서 읽는 것 ────────────────────────────────────────────────────
def test_page_published_reads_json_ld():
    html = '<script type="application/ld+json">{"datePublished":"2026-09-25T18:02:44.000+00:00"}</script>'
    assert N.page_published(html) == '2026-09-25T18:02:44+00:00'


def test_page_published_reads_the_open_graph_meta():
    html = '<meta property="article:published_time" content="2026-09-25T10:00:00Z">'
    assert N.page_published(html) == '2026-09-25T10:00:00+00:00'


def test_page_published_is_none_rather_than_a_guess():
    assert N.page_published('<html><body>no date</body></html>') is None


def test_wire_detects_reuters_copy():
    assert N.wire_of('PARIS, Sept 25 (Reuters) - France must do everything possible') == 'Reuters'
    # 본문 중간의 인용(「…, Reuters reported」 류)은 전재 표기가 아니다
    assert N.wire_of('x' * 400 + ' (Reuters) - France must') is None
    assert N.wire_of('Plain Investing.com analysis') is None


def test_investing_article_body_ignores_the_widgets_above_the_article():
    widget = '<p>' + 'U.S. stocks rise, head for weekly gains as oil falls ' * 3 + '</p>'
    para = '<p>' + 'PARIS, Sept 25 (Reuters) - France must avoid a sovereign debt crisis. ' * 4 + '</p>'
    html = f'<html><body>{widget}<div id="article" class="article_WYSIWYG">{para * 3}</div></body></html>'
    body = N.extract_body(html)
    assert body.startswith('PARIS, Sept 25 (Reuters)')
    assert 'weekly gains' not in body


# ── 수집 잡 (fetch_news) ──────────────────────────────────────────────────
import fetch_news as FN  # noqa: E402
from us import news_summary as S  # noqa: E402

_PAGE = ('<script type="application/ld+json">{"datePublished":"2026-09-25T18:02:44Z"}</script>'
         '<div id="article">' + '<p>' + 'PARIS, Sept 25 (Reuters) - France must avoid a debt '
         'crisis, the central bank governor said on Friday in a long interview. ' * 3 + '</p>' * 1
         + '<p>' + 'Borrowing costs have climbed to the highest since 2008 on fiscal worries. ' * 3
         + '</p></div>')


def test_fetch_bodies_takes_the_date_from_the_page_only_when_the_feed_had_none(tmp_path):
    rows = [{'url': 'https://www.investing.com/news/a', 'title': 'France debt', 'category': 'global',
             'published': None},
            {'url': 'https://www.investing.com/news/b', 'title': 'ECB', 'category': 'global',
             'published': '2026-09-25T09:00:00+00:00'}]
    FN.fetch_bodies(rows, str(tmp_path), None, fetch=lambda u, ctx: _PAGE)
    assert rows[0]['published'] == '2026-09-25T18:02:44+00:00'
    assert rows[0]['published_from'] == 'page'
    assert rows[1]['published'] == '2026-09-25T09:00:00+00:00'       # 피드 날짜를 덮지 않는다
    assert rows[0]['wire'] == 'Reuters'


def test_insight_rows_are_summarised_with_the_column_prompt(tmp_path):
    calls = []

    def fake(items, bodydir, system=None):
        calls.append(([i['guid'] for i in items], system))
        return len(items)

    rows = [{'guid': 'n', 'category': 'global'}, {'guid': 'c', 'category': 'insight'},
            {'guid': 'p', 'category': 'politics'}]
    assert FN.summarize_chosen(rows, str(tmp_path), summarize=fake) == 3
    assert (['n', 'p'], None) in calls
    assert (['c'], S.SYSTEM_ANALYSIS) in calls


def test_the_column_prompt_attributes_views_to_their_author():
    assert '견해' in S.SYSTEM_ANALYSIS
    assert '~다' in S.SYSTEM_ANALYSIS or '-다' in S.SYSTEM_ANALYSIS


def test_a_naive_timestamp_does_not_crash_the_freshness_window():
    # RFC 2822 「-0000」 은 parsedate_to_datetime 이 시간대 없는 값으로 준다 — aware 와 비교하면 TypeError
    xml = ('<rss><channel><item><link>https://www.cnbc.com/a.html</link><title>ECB rate path</title>'
           '<pubDate>Fri, 25 Sep 2026 12:00:00 -0000</pubDate></item></channel></rss>')
    rows = N.categorize(N.parse_feed(xml, 'global'))
    assert N.select(rows, now=NOW) is not None
    assert N.trim([dict(r, body_chars=900) for r in rows], now=NOW) == []   # 날짜를 못 믿으면 탈락
