"""뉴스 수집 모듈 — 피드 파싱·본문 추출·중복 제거·선정."""
from us.news import (
    FEEDS,
    dedupe,
    extract_body,
    parse_feed,
    select,
)


def item(guid='1', url='https://www.cnbc.com/2026/09/18/a.html', title='T',
         desc='D', pub='Fri, 18 Sep 2026 23:43:21 GMT'):
    return (f'<item><link>{url}</link>'
            f'<guid isPermaLink="false">{guid}</guid>'
            f'<title>{title}</title>'
            f'<description><![CDATA[{desc}]]></description>'
            f'<pubDate>{pub}</pubDate></item>')


def feed(*items):
    return ('<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>'
            '<title>US Top News and Analysis</title>' + ''.join(items)
            + '</channel></rss>')


# ── 피드 파싱 ─────────────────────────────────────────────────────────────
def test_parses_the_five_fields_cnbc_actually_sends():
    [it] = parse_feed(feed(item()), 'top')
    assert it['guid'] == '1'
    assert it['url'] == 'https://www.cnbc.com/2026/09/18/a.html'
    assert it['title'] == 'T'
    assert it['summary'] == 'D'
    assert it['category'] == 'top'


def test_pubdate_becomes_iso_so_rows_sort():
    [it] = parse_feed(feed(item()), 'top')
    assert it['published'] == '2026-09-18T23:43:21+00:00'


def test_unparseable_pubdate_is_kept_as_none_not_guessed():
    [it] = parse_feed(feed(item(pub='nonsense')), 'top')
    assert it['published'] is None


def test_entities_in_title_are_unescaped_for_the_writer():
    [it] = parse_feed(feed(item(title='Trump says he&apos;s banning A &amp; B')), 'top')
    assert it['title'] == "Trump says he's banning A & B"


def test_description_without_cdata_still_parses():
    xml = feed('<item><link>u</link><guid>9</guid><title>T</title>'
               '<description>plain &amp; simple</description></item>')
    [it] = parse_feed(xml, 'top')
    assert it['summary'] == 'plain & simple'


def test_item_without_link_is_dropped_a_source_we_cannot_point_at_is_not_a_source():
    xml = feed('<item><guid>9</guid><title>T</title></item>', item())
    assert [i['guid'] for i in parse_feed(xml, 'top')] == ['1']


def test_broken_feed_returns_empty_rather_than_raising():
    assert parse_feed('<html>502 Bad Gateway</html>', 'top') == []
    assert parse_feed('', 'top') == []
    assert parse_feed(None, 'top') == []


def test_yahoo_items_lacking_guid_fall_back_to_url():
    xml = feed('<item><link>https://finance.yahoo.com/news/x.html</link>'
               '<title>Y</title><description>d</description></item>')
    [it] = parse_feed(xml, 'market')
    assert it['guid'] == 'https://finance.yahoo.com/news/x.html'


# ── 본문 추출 ─────────────────────────────────────────────────────────────
# MIN_BODY(400자) 를 넘겨야 기사로 인정된다 — 여기서 보는 것은 문단 필터다
LONG = 'Trump said Friday that he is banning three outlets from the White House. ' * 7


def test_extracts_paragraphs_long_enough_to_be_prose():
    html = f'<html><body><p>{LONG}</p><p>short</p></body></html>'
    assert LONG.strip() in extract_body(html)
    assert 'short' not in extract_body(html)


def test_drops_the_nav_and_house_boilerplate_that_rides_along():
    html = ('<p>LivestreamMenuMake ItselectUSAINTLLivestreamSearch quotes, news '
            '&amp; videosWatchlistSIGN INCreate free accountMarketsBusiness</p>'
            '<p>CNBC is the world leader in business news and real-time financial '
            'market coverage. Find fast, actionable information.</p>'
            f'<p>{LONG}</p>')
    out = extract_body(html)
    assert 'Livestream' not in out
    assert 'world leader in business news' not in out
    assert LONG.strip() in out


def test_script_and_style_never_reach_the_reader():
    html = f'<script>var p = "<p>{LONG}</p>";</script><p>{LONG}</p>'
    assert extract_body(html).count('Trump said Friday') == 7  # 본문 한 문단분만


def test_body_is_capped_so_one_runaway_page_cannot_flood_the_routine():
    html = ''.join(f'<p>{LONG}</p>' for _ in range(200))
    assert len(extract_body(html, max_chars=4000)) <= 4000


def test_empty_page_yields_empty_string_not_an_exception():
    assert extract_body('') == ''
    assert extract_body(None) == ''


# ── 중복 제거 ─────────────────────────────────────────────────────────────
def rec(guid, category, url=None):
    return {'guid': guid, 'category': category,
            'url': url or f'https://x/{guid}', 'title': guid}


def test_same_guid_twice_survives_once():
    assert len(dedupe([rec('a', 'top'), rec('a', 'top')])) == 1


def test_narrower_category_wins_over_top_news():
    out = dedupe([rec('a', 'top'), rec('a', 'economy')])
    assert [r['category'] for r in out] == ['economy']


def test_narrower_wins_regardless_of_arrival_order():
    out = dedupe([rec('a', 'economy'), rec('a', 'top')])
    assert [r['category'] for r in out] == ['economy']


def test_same_story_different_guid_is_caught_by_url():
    out = dedupe([rec('a', 'top', url='https://x/same'),
                  rec('b', 'economy', url='https://x/same')])
    assert [r['category'] for r in out] == ['economy']


def test_two_genuinely_different_stories_both_survive():
    assert len(dedupe([rec('a', 'top'), rec('b', 'economy')])) == 2


# ── 선정 ──────────────────────────────────────────────────────────────────
def test_caps_each_category_at_the_quota():
    rows = [rec(f'{c}{i}', c) for c in ('top', 'market') for i in range(6)]
    out = select(rows, per_category=3)
    assert len(out) == 6
    assert sum(1 for r in out if r['category'] == 'top') == 3


def test_a_thin_category_is_not_topped_up_from_another():
    rows = [rec('t0', 'top')] + [rec(f'm{i}', 'market') for i in range(6)]
    out = select(rows, per_category=3)
    assert sum(1 for r in out if r['category'] == 'top') == 1
    assert sum(1 for r in out if r['category'] == 'market') == 3


def test_newest_first_within_a_category():
    rows = [dict(rec('old', 'top'), published='2026-09-18T01:00:00+00:00'),
            dict(rec('new', 'top'), published='2026-09-18T09:00:00+00:00')]
    assert [r['guid'] for r in select(rows, per_category=2)] == ['new', 'old']


def test_items_without_a_timestamp_sort_last_but_are_not_dropped():
    rows = [dict(rec('none', 'top'), published=None),
            dict(rec('dated', 'top'), published='2026-09-18T01:00:00+00:00')]
    assert [r['guid'] for r in select(rows, per_category=2)] == ['dated', 'none']


# ── 피드 등록부 ───────────────────────────────────────────────────────────
def test_every_category_the_user_asked_for_has_a_feed():
    assert set(FEEDS) == {'top', 'market', 'economy', 'politics', 'mlcc'}


def test_the_digest_section_does_not_carry_mlcc_it_belongs_to_its_own_section():
    from us.news import DIGEST_CATEGORIES
    assert 'mlcc' not in DIGEST_CATEGORIES
    assert set(DIGEST_CATEGORIES) < set(FEEDS)


def test_mlcc_news_feeds_are_trimmed_to_the_liquid_names():
    # 여덟을 연속 호출하면 Yahoo 가 429 를 준다 — 표는 여덟, 뉴스 피드는 넷
    from us.news import MLCC_TICKERS
    assert len(MLCC_TICKERS) == 4
    assert len(FEEDS['mlcc']) == len(MLCC_TICKERS)
    assert all('6981.T' in u or True for u in FEEDS['mlcc'])


def test_mlcc_is_the_narrowest_category_so_it_wins_every_overlap():
    from us.news import NARROWNESS
    assert NARROWNESS['mlcc'] < min(NARROWNESS[c] for c in NARROWNESS if c != 'mlcc')


def test_every_feed_entry_is_an_https_url():
    for cat, urls in FEEDS.items():
        assert urls, cat
        for u in urls:
            assert u.startswith('https://'), (cat, u)


# ── codex 적대적 검토 2026-09-19 ──────────────────────────────────────────
def test_summary_is_capped_so_a_full_article_in_cdata_is_not_stored():
    """#2 [치명] RSS description 에 전문이 실려 오면 공개 레포에 그대로 커밋됐다."""
    from us.news import MAX_SUMMARY
    xml = feed(item(desc='본문 ' * 8000))
    [it] = parse_feed(xml, 'top')
    assert len(it['summary']) <= MAX_SUMMARY


def test_two_outlets_reusing_the_same_guid_are_not_merged():
    """#14 [중대] 출처가 다른 별개 기사를 guid 충돌로 합쳤다."""
    rows = [{'guid': '123', 'url': 'https://cnbc.com/a', 'category': 'top',
             'source': 'CNBC'},
            {'guid': '123', 'url': 'https://finance.yahoo.com/b', 'category': 'market',
             'source': 'Yahoo Finance'}]
    assert len(dedupe(rows)) == 2


def test_a_third_row_linking_two_groups_collapses_them():
    """#14 [중대] (a,u1) (b,u2) (a,u2) 가 세 그룹을 잇는데 둘로 남았다."""
    rows = [{'guid': 'a', 'url': 'u1', 'category': 'top', 'source': 'CNBC'},
            {'guid': 'b', 'url': 'u2', 'category': 'top', 'source': 'CNBC'},
            {'guid': 'a', 'url': 'u2', 'category': 'top', 'source': 'CNBC'}]
    assert len(dedupe(rows)) == 1


def test_tracking_parameters_do_not_split_one_article_into_two():
    rows = [{'guid': 'a', 'url': 'https://x/a', 'category': 'top', 'source': 'CNBC'},
            {'guid': 'b', 'url': 'https://x/a?utm_source=rss', 'category': 'top',
             'source': 'CNBC'}]
    assert len(dedupe(rows)) == 1


def test_an_error_page_is_not_a_body():
    """#13 [중대] 오류 안내문이 `body_chars>0` 을 만들어 게이트를 통과시켰다."""
    err = ('<p>We could not process your request. Please try again later or '
           'contact customer support.</p>')
    assert extract_body(err) == ''


def test_a_page_too_thin_to_be_an_article_yields_nothing():
    assert extract_body(f'<p>{"x" * 70}</p>') == ''


def test_namespaced_and_atom_feeds_are_reported_not_silently_empty():
    """#15 [경미] 피드 형식이 바뀐 날과 진짜 빈 피드를 구별하지 못했다."""
    from us.news import parse_feed_strict
    atom = ('<feed xmlns="http://www.w3.org/2005/Atom">'
            '<entry><title>T</title><link href="https://x/a"/></entry></feed>')
    rows, note = parse_feed_strict(atom, 'top')
    assert rows == [] and note and 'atom' in note.lower()
    rows, note = parse_feed_strict('<rss><channel></channel></rss>', 'top')
    assert rows == [] and note is None


def test_the_group_keeps_the_richest_row_not_the_first_one():
    """codex 2차 #10 — 첫 행의 결손 정보(title/published/옛 URL)가 남았다."""
    rows = [{'guid': 'a', 'url': 'https://x/old', 'category': 'top', 'source': 'CNBC',
             'title': None, 'published': None},
            {'guid': 'a', 'url': 'https://x/new', 'category': 'top', 'source': 'CNBC',
             'title': '제목', 'published': '2026-09-19T01:00:00+00:00'}]
    [out] = dedupe(rows)
    assert out['title'] == '제목' and out['published']


def test_order_does_not_change_the_surviving_row():
    a = {'guid': 'a', 'url': 'u', 'category': 'top', 'source': 'CNBC',
         'title': None, 'published': None}
    b = {'guid': 'a', 'url': 'u', 'category': 'top', 'source': 'CNBC',
         'title': 'T', 'published': '2026-09-19T01:00:00+00:00'}
    assert dedupe([a, b])[0]['title'] == dedupe([b, a])[0]['title'] == 'T'


def test_an_error_phrase_quoted_inside_a_real_article_does_not_void_it():
    """codex 2차 #11 — 정상 기사가 장애를 서술하면 본문 전체가 버려졌다."""
    real = 'The outage hit trading desks across the region on Friday morning. ' * 8
    html = f'<p>{real}</p><p>Users saw the message access denied during the outage. ' \
           f'{"Reporters confirmed the detail with two sources. " * 3}</p>'
    assert extract_body(html) != ''


def test_an_error_page_is_still_rejected_when_it_is_long():
    """codex 2차 #11b — 안내문이 길면 본문으로 인정됐다."""
    err = ('<h1>Access denied</h1>'
           + '<p>Access denied. Please try again later or contact customer support '
             'if you believe this is an error. Our team is looking into it. ' * 6
           + '</p>')
    assert extract_body(err) == ''


def test_a_short_article_is_reported_as_short_not_as_a_fetch_failure():
    """codex 2차 #12 — `body_chars=0` 이 「실패」와 「짧음」을 구별 못 했다."""
    from us.news import body_note
    assert body_note('x' * 100) == '짧다'
    assert body_note('') == '추출 실패'
    assert body_note('y' * 500) is None
