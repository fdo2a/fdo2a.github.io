"""US 다섯 갈래의 매체 돌려 뽑기 — 식별·같은 이야기·고르면서 본문 확인 (2026-11-12).

설계와 codex 설계 검토 네 회차의 재현 입력: docs/superpowers/specs/2026-11-12-us-news-source-spread.md
"""
import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from us import news as N

NOW = datetime(2026, 11, 12, 10, 0, tzinfo=timezone.utc)
FIX = os.path.join(os.path.dirname(__file__), 'fixtures', 'same_story_pairs.json')


def row(guid, source, title=None, hours=1, cat='politics', url=None, **extra):
    """title 을 안 주면 guid 로 낱말이 하나도 안 겹치는 제목을 만든다(같은 이야기로 접히지 않게)."""
    when = (NOW - timedelta(hours=hours)).isoformat() if hours is not None else None
    return dict({'guid': guid, 'url': f'https://{source.lower()}.example/{guid}' if url is None else url,
                 'title': title or ' '.join(f'{guid}{w}' for w in ('alpha', 'bravo', 'carol', 'delta')),
                 'summary': None, 'published': when, 'category': cat, 'source': source}, **extra)


def ok(_row):
    return True


# ── 새 피드 행의 식별: guid = 프래그먼트만 뗀 원 URL ─────────────────────────
def test_extra_rows_take_their_url_as_guid_and_are_marked():
    [r] = N.identify([row('raw-123', 'CBS', url='https://www.cbsnews.com/news/a/#top')])
    assert r['guid'] == 'https://www.cbsnews.com/news/a/'
    assert r['_extra'] is True


def test_two_outlets_sharing_a_raw_guid_stay_two_articles():
    """1회차 #3 — 매체가 다른데 원 guid 가 같다."""
    a, b = N.identify([row('123', 'CBS', url='https://www.cbsnews.com/a'),
                       row('123', 'ABC', url='https://abcnews.com/b')])
    assert a['guid'] != b['guid']
    assert len(N.dedupe([a, b])) == 2


def test_urls_that_differ_only_by_a_tracking_parameter_keep_distinct_guids():
    """4회차 4-1 — `_norm_url` 은 ref·utm 을 걷어낸다. 식별에는 쓰지 않는다."""
    a, b = N.identify([row('x', 'Fortune', url='https://fortune.com/story?ref=1'),
                       row('y', 'Fortune', url='https://fortune.com/story?ref=2')])
    assert a['guid'] == 'https://fortune.com/story?ref=1'
    assert b['guid'] == 'https://fortune.com/story?ref=2'


@pytest.mark.parametrize('bad', ['https://x.example/a|b', 'https://x.example/a>b',
                                 'https://x.example/a"b', 'https://x.example/a b', '',
                                 'https://fortune.com/?p=1&show=2', "https://x.example/it's",
                                 'https://x.example/a<b'])
def test_a_url_the_page_cannot_carry_verbatim_is_dropped(bad):
    """구현 검토 1회차 #1 — `&` 가 든 guid 는 `&amp;` 로 실리고 게이트가 원문과 못 맞춘다."""
    assert N.identify([row('g', 'CBS', url=bad)]) == []


def test_every_identified_guid_reads_the_same_in_html():
    import html
    [r] = N.identify([row('g', 'CBS', url='https://www.cbsnews.com/news/a-b_c/?x=1#top')])
    assert html.escape(r['guid']) == r['guid']


def test_two_articles_that_differ_by_a_tracking_parameter_both_reach_selection():
    """구현 검토 1회차 #2 — 식별은 둘로 해 놓고 dedupe 가 하나로 합쳤다."""
    rows = N.identify([row('x', 'Fortune', url='https://fortune.com/story?ref=1'),
                       row('y', 'Fortune', url='https://fortune.com/story?ref=2')])
    kept, dropped = N.reconcile(rows, {})
    assert dropped == [] and [r['guid'] for r in N.dedupe(kept)] == [
        'https://fortune.com/story?ref=1', 'https://fortune.com/story?ref=2']


def test_a_query_that_ends_in_a_slash_is_not_the_same_url():
    """구현 검토 2회차 #2 — dedupe 가 끝의 `/` 를 떼어 `?ref=1` 과 `?ref=1/` 을 합쳤다."""
    rows = N.identify([row('x', 'Fortune', url='https://fortune.com/a?ref=1'),
                       row('y', 'Fortune', url='https://fortune.com/a?ref=1/')])
    assert len(N.dedupe(rows)) == 2


def test_a_path_with_and_without_its_trailing_slash_is_one_article():
    old = row('old-id', 'CBS', url='https://www.cbsnews.com/news/a', cat='global')
    [new] = N.identify([row('raw', 'CBS', url='https://www.cbsnews.com/news/a/', cat='industry')])
    assert len(N.dedupe([old, new])) == 1


@pytest.mark.parametrize('new_first', [False, True])
def test_an_article_the_established_feeds_also_carry_stays_usable_by_the_old_way(new_first):
    """구현 검토 2회차 #3 — 병합이 기존 피드 행에 `_extra` 를 채워 옛 길이 그 행을 못 썼다."""
    url = 'https://www.cnbc.com/2026/11/12/a.html'
    old = row('108', 'CNBC', url=url, cat='politics')
    [new] = N.identify([row('raw', 'CNBC', url=url, cat='politics')])
    [merged] = N.dedupe([new, old] if new_first else [old, new])
    assert '_extra' not in merged
    out, _ = N.legacy_fill([merged], [], ok, 3)
    assert len(out) == 1


def test_two_new_feed_copies_merge_into_a_new_feed_row():
    a, b = N.identify([row('1', 'CBS', url='https://www.cbsnews.com/news/a/', cat='politics'),
                       row('2', 'CBS', url='https://www.cbsnews.com/news/a/', cat='industry')])
    [merged] = N.dedupe([a, b])
    assert merged['_extra'] is True


def test_a_new_feed_copy_of_an_established_feed_article_is_still_one_article():
    """가디언은 기존 global 묶음과 새 묶음에 다 있다 — 같은 기사가 둘로 남으면 안 된다."""
    url = 'https://www.theguardian.com/business/2026/nov/12/story'
    old = row(url, 'The Guardian', url=url + '?utm_source=rss', cat='global')
    [new] = N.identify([row('raw', 'The Guardian', url=url, cat='industry')])
    assert len(N.dedupe([old, new])) == 1


def test_the_same_new_feed_article_from_two_feeds_is_one_article():
    a, b = N.identify([row('1', 'CBS', url='https://www.cbsnews.com/news/a/', cat='politics'),
                       row('2', 'CBS', url='https://www.cbsnews.com/news/a/', cat='industry')])
    assert len(N.dedupe([a, b])) == 1


def test_identify_does_not_touch_the_row_it_was_given():
    src = row('raw', 'CBS', url='https://www.cbsnews.com/a')
    N.identify([src])
    assert src['guid'] == 'raw' and '_extra' not in src


# ── reconcile: 그날 파일의 guid 와 후보를 직접 대조 ──────────────────────────
def test_a_saved_guid_is_not_inherited_by_another_outlets_article():
    """3회차 3-2 — 그날 파일에만 있는 guid 를 다른 기사가 물려받는다."""
    existing = {'G': ('CNBC', 'https://www.cnbc.com/a')}
    kept, dropped = N.reconcile([row('G', 'CBS', url='https://www.cbsnews.com/b')], existing)
    assert kept == []
    assert [d['guid'] for d in dropped] == ['G']


def test_the_same_outlet_changing_its_slug_is_the_same_article():
    """CNBC 가 제목을 고치면 guid 는 같고 URL 슬러그만 바뀐다 — 요약 이월이 끊기면 안 된다."""
    existing = {'G': ('CNBC', 'https://www.cnbc.com/2026/11/11/old.html')}
    kept, dropped = N.reconcile([row('G', 'CNBC', url='https://www.cnbc.com/2026/11/11/new.html')],
                                existing)
    assert len(kept) == 1 and dropped == []


def test_the_saved_article_itself_passes():
    existing = {'G': ('CNBC', 'https://www.cnbc.com/a')}
    kept, dropped = N.reconcile([row('G', 'CNBC', url='https://www.cnbc.com/a?utm_source=rss')],
                                existing)
    assert len(kept) == 1 and dropped == []


def test_candidates_colliding_across_outlets_keep_the_established_feed():
    """2회차 2-2 — 후보끼리 같은 guid·다른 매체·다른 URL. 기존 피드 행이 새 피드 행을 이긴다."""
    new = dict(row('G', 'BoE', url='https://boe.example/x'), _extra=True)
    old = row('G', 'CNBC', url='https://www.cnbc.com/a')
    kept, dropped = N.reconcile([new, old], {})
    assert [r['source'] for r in kept] == ['CNBC']
    assert [d['source'] for d in dropped] == ['BoE']


def test_the_row_already_in_todays_file_wins_a_collision():
    existing = {'G': ('BoE', 'https://boe.example/x')}
    kept, _ = N.reconcile([row('G', 'CNBC', url='https://www.cnbc.com/a'),
                           row('G', 'BoE', url='https://boe.example/x')], existing)
    assert [r['source'] for r in kept] == ['BoE']


def test_the_same_guid_twice_from_one_outlet_is_left_for_dedupe():
    rows = [row('G', 'CNBC', url='https://www.cnbc.com/a', cat='politics'),
            row('G', 'CNBC', url='https://www.cnbc.com/a', cat='economy')]
    kept, dropped = N.reconcile(rows, {})
    assert len(kept) == 2 and dropped == []


# ── 같은 이야기 ───────────────────────────────────────────────────────────
def test_same_story_meets_the_bar_on_real_headlines():
    """합격 기준(2회차 2-6): 같다고 본 쌍의 정밀 >= 0.9, 같은 이야기 쌍의 재현 >= 0.5."""
    with open(FIX, encoding='utf-8') as fh:
        pairs = json.load(fh)['pairs']
    assert sum(p['same'] for p in pairs) >= 15 and sum(not p['same'] for p in pairs) >= 15
    tp = sum(1 for p in pairs if p['same'] and N.same_story(p['a'], p['b']))
    fp = sum(1 for p in pairs if not p['same'] and N.same_story(p['a'], p['b']))
    fn = sum(1 for p in pairs if p['same'] and not N.same_story(p['a'], p['b']))
    assert tp / (tp + fp) >= 0.9
    assert tp / (tp + fn) >= 0.5
    assert (tp, fp, fn) == (21, 0, 4)        # 기준을 고치면 이 숫자가 움직인다 — 어느 쪽인지 보고 고친다


def test_three_outlets_on_one_election_are_one_story():
    a = {'title': 'Scott Colom wins Senate election in Mississippi'}
    b = {'title': 'Democrat Scott Colom unseats Cindy Hyde-Smith in stunning Mississippi Senate win'}
    assert N.same_story(a, b)


def test_two_angles_on_one_story_with_no_words_in_common_are_one_story():
    """11/12 실수집 — 정치 칸에 같은 선거가 두 번 실렸다."""
    a = {'title': 'Promises and pride: Scott Colom rejoices with young and old on historic night in Mississippi'}
    b = {'title': 'Democrat Scott Colom wins Mississippi Senate race in upset'}
    c = {'title': "Nvidia's board preparing to oust CEO Jensen Huang, sources say"}
    d = {'title': "Jensen Huang's looming ouster triggers an AI earthquake"}
    assert N.same_story(a, b) and N.same_story(c, d)


def test_a_shared_title_and_a_shared_country_are_not_a_shared_story():
    a = {'title': 'Nissan cuts sales forecast again on China woes as CEO outlines turnaround'}
    b = {'title': 'Nvidia board meets over CEO’s future as chip giant reels from China spy report'}
    assert not N.same_story(a, b)


def test_a_later_story_about_the_same_person_is_not_the_same_story():
    a = {'title': "Biden says he wouldn't have run for a second term in 2024 if he knew he had cancer"}
    b = {'title': 'Pro-Palestinian protesters pelt Joe Biden with objects outside Irish university'}
    assert not N.same_story(a, b)


def test_a_capitalised_first_word_is_not_a_shared_name():
    a = {'title': 'Democrats push to rein in Trump on immigration after voter backlash'}
    b = {'title': 'Democrats weigh Trump tariff refunds for small importers'}
    assert not N.same_story(a, b)


def test_rows_without_titles_are_never_the_same_story():
    assert not N.same_story({'title': None}, {'title': None})


# ── 후보 ──────────────────────────────────────────────────────────────────
def test_candidates_cover_only_the_rotating_categories_inside_the_window():
    rows = [row('fresh', 'CNBC'), row('stale', 'CNBC', hours=40), row('undated', 'CBS', hours=None),
            row('m', 'Yahoo Finance', cat='mlcc'), row('g', 'BBC', cat='global')]
    got = N.candidates(rows, NOW)
    assert set(got) == set(N.ROTATE)
    assert [r['guid'] for r in got['politics']] == ['fresh', 'undated']


# ── 줄(매체) ──────────────────────────────────────────────────────────────
def test_lanes_are_per_outlet_newest_first_and_ordered_by_their_freshest_story():
    rows = [row('a2', 'A', hours=5), row('b1', 'B', hours=2), row('a1', 'A', hours=1),
            row('c0', 'C', hours=None), row('c1', 'C', hours=3)]
    got = [[r['guid'] for r in lane] for lane in N.lanes(rows)]
    assert got == [['a1', 'a2'], ['b1'], ['c1', 'c0']]


# ── 고르면서 본문 확인 ────────────────────────────────────────────────────
def picked(rows, try_body=ok, cap=3):
    chosen, log, stopped = N.confirm(rows, try_body, cap, NOW)
    return [r['guid'] for r in chosen]


def test_three_live_outlets_get_one_slot_each():
    rows = ([row(f'a{i}', 'A', hours=i + 1) for i in range(5)] + [row('b1', 'B', hours=6)]
            + [row('c1', 'C', hours=7)])
    assert picked(rows) == ['a0', 'b1', 'c1']


def test_two_outlets_alternate():
    rows = [row(f'a{i}', 'A', hours=i + 1) for i in range(3)] + [row('b1', 'B', hours=9)]
    assert picked(rows) == ['a0', 'b1', 'a1']


def test_one_outlet_alone_gives_its_newest_three_as_before():
    rows = [row(f'a{i}', 'CNBC', hours=i + 1) for i in range(5)]
    assert picked(rows) == ['a0', 'a1', 'a2']


def test_four_live_outlets_still_stop_at_the_cap():
    """3회차 3-1 — 한 바퀴 도중 상한을 넘긴다."""
    rows = [row(f'{s}1', s, hours=h) for h, s in enumerate('ABCD', 1)]
    assert picked(rows) == ['A1', 'B1', 'C1']


def test_an_outlet_whose_first_story_repeats_a_confirmed_one_offers_its_next():
    """2회차 2-1 — A1,B1,C1,A2,B2 에서 B1 이 A1 과 같은 이야기면 A 가 두 자리를 가져갔다."""
    same = 'Scott Colom wins Mississippi Senate election over Hyde-Smith'
    rows = [row('A1', 'A', title=same, hours=1), row('A2', 'A', hours=5),
            row('B1', 'B', title='Scott Colom wins Senate election in Mississippi', hours=2),
            row('B2', 'B', hours=6), row('C1', 'C', hours=3)]
    assert picked(rows) == ['A1', 'B2', 'C1']


def test_a_body_that_will_not_open_passes_the_slot_to_the_same_outlets_next_story():
    rows = [row('a1', 'A', hours=1), row('b1', 'B', hours=2), row('b2', 'B', hours=3),
            row('c1', 'C', hours=4)]
    assert picked(rows, try_body=lambda r: r['guid'] != 'b1') == ['a1', 'b2', 'c1']


def test_six_blocked_outlets_fall_through_to_cnbc():
    """1회차 #1 — 후보 6건이 전부 403 이면 CNBC 가 후보에 없었다."""
    rows = [row(f'{s}1', s, hours=h) for h, s in enumerate('ABCDEF', 1)]
    rows += [row(f'n{i}', 'CNBC', hours=10 + i) for i in range(4)]
    assert picked(rows, try_body=lambda r: r['source'] == 'CNBC') == ['n0', 'n1', 'n2']


def test_some_blocked_outlets_leave_the_rest_spread():
    rows = [row(f'{s}1', s, hours=h) for h, s in enumerate('ABCD', 1)]
    rows += [row(f'n{i}', 'CNBC', hours=10 + i) for i in range(3)]
    got = picked(rows, try_body=lambda r: r['source'] in ('B', 'D', 'CNBC'))
    assert got == ['B1', 'D1', 'n0']


def test_the_alternate_of_a_failed_story_is_still_taken():
    """1회차 #2 — 본문 전에 같은 사건을 접으면 대체본이 사라졌다."""
    rows = [row('A1', 'A', title='Scott Colom wins Mississippi Senate election over Hyde-Smith', hours=1),
            row('B1', 'B', title='Scott Colom wins Senate election in Mississippi', hours=2)]
    assert picked(rows, try_body=lambda r: r['guid'] != 'A1') == ['B1']


def test_a_story_with_no_time_even_after_its_page_is_read_is_not_confirmed():
    rows = [row('u', 'A', hours=None), row('b1', 'B', hours=2)]
    chosen, log, _ = N.confirm(rows, ok, 3, NOW)
    assert [r['guid'] for r in chosen] == ['b1']
    assert ('u', 'undated') in [(r['guid'], why) for r, why in log]


def test_a_page_date_outside_the_window_is_stale():
    def reads_an_old_date(r):
        if r['guid'] == 'u':
            r['published'] = (NOW - timedelta(hours=90)).isoformat()
        return True
    chosen, log, _ = N.confirm([row('u', 'A', hours=None), row('b1', 'B', hours=2)],
                               reads_an_old_date, 3, NOW)
    assert [r['guid'] for r in chosen] == ['b1']
    assert ('u', 'stale') in [(r['guid'], why) for r, why in log]


def test_a_page_date_inside_the_window_confirms_an_undated_feed_row():
    def reads_a_date(r):
        r['published'] = (NOW - timedelta(hours=3)).isoformat()
        return True
    assert picked([row('u', 'A', hours=None)], try_body=reads_a_date) == ['u']


def test_stop_returns_what_was_confirmed_so_far():
    seen = []

    def runs_out(r):
        if len(seen) == 1:
            raise N.Stop()
        seen.append(r['guid'])
        return True
    chosen, log, stopped = N.confirm([row('a1', 'A', hours=1), row('b1', 'B', hours=2)], runs_out, 3, NOW)
    assert [r['guid'] for r in chosen] == ['a1'] and stopped is True


def test_confirm_reports_every_outcome():
    rows = [row('A1', 'A', title='Scott Colom wins Mississippi Senate election over Hyde-Smith', hours=1),
            row('B1', 'B', title='Scott Colom wins Senate election in Mississippi', hours=2),
            row('c1', 'C', hours=3)]
    _, log, stopped = N.confirm(rows, lambda r: r['guid'] != 'c1', 3, NOW)
    assert [(r['guid'], why) for r, why in log] == [('A1', 'chosen'), ('B1', 'same_story'),
                                                    ('c1', 'no_body')]
    assert stopped is False


# ── select 의 defer ───────────────────────────────────────────────────────
def test_select_without_defer_is_what_it_always_was():
    rows = [row(f'p{i}', 'CNBC', hours=i + 1) for i in range(5)]
    assert [r['guid'] for r in N.select(rows, per_category=3)] == ['p0', 'p1', 'p2']


def test_deferred_categories_are_left_out_of_select():
    rows = [row('p', 'CNBC'), row('m', 'Yahoo Finance', cat='mlcc')]
    assert [r['guid'] for r in N.select(rows, per_category=3, now=NOW, defer=N.ROTATE)] == ['m']


# ── 옛 길(시간 상한 때만) ─────────────────────────────────────────────────
def test_legacy_fill_tops_up_from_the_established_feeds_newest_first():
    rows = [row('old', 'CNBC', hours=50), row('new', 'CNBC', hours=1),
            dict(row('x', 'CBS', hours=0.5), _extra=True)]
    out, log = N.legacy_fill(rows, [], ok, 3)
    assert [r['guid'] for r in out] == ['new', 'old']        # 창 없음, 새 피드 행은 쓰지 않는다


def test_legacy_fill_keeps_what_was_confirmed_and_skips_repeats():
    have = [row('A1', 'CBS', title='Scott Colom wins Mississippi Senate election over Hyde-Smith')]
    rows = [row('n1', 'CNBC', title='Scott Colom wins Senate election in Mississippi', hours=1),
            row('n2', 'CNBC', hours=2), row('A1', 'CNBC', hours=3)]
    out, _ = N.legacy_fill(rows, have, ok, 3)
    assert [r['guid'] for r in out] == ['A1', 'n2']


def test_legacy_fill_does_not_ask_again_for_a_body_that_already_failed():
    asked = []

    def body(r):
        asked.append(r['guid'])
        return True
    rows = [dict(row('f', 'CNBC', hours=1), body_chars=0, body_note='HTTP 403'), row('n', 'CNBC', hours=2)]
    out, _ = N.legacy_fill(rows, [], body, 3)
    assert asked == ['n'] and [r['guid'] for r in out] == ['n']


def test_legacy_fill_stops_at_the_cap_and_on_stop():
    def stop(_r):
        raise N.Stop()
    rows = [row(f'n{i}', 'CNBC', hours=i + 1) for i in range(5)]
    assert len(N.legacy_fill(rows, [], ok, 3)[0]) == 3
    assert N.legacy_fill(rows, [], stop, 3)[0] == []


# ── 새 피드: 목록·분류·건너뛰기 ───────────────────────────────────────────
def feed_row(hint, title, url='https://www.cbsnews.com/news/a/', summary=None):
    return {'guid': url, 'url': url, 'title': title, 'summary': summary, 'category': hint,
            'published': NOW.isoformat(), 'source': N.source_name(url)}


def test_every_new_outlet_has_a_name_for_the_caption():
    for urls in N.EXTRA_FEEDS.values():
        for url in urls:
            host = url.split('/')[2]
            article = {'feeds.nbcnews.com': 'www.nbcnews.com', 'feeds.npr.org': 'www.npr.org',
                       'moxie.foxbusiness.com': 'www.foxbusiness.com', 'api.axios.com': 'www.axios.com',
                       'feeds.arstechnica.com': 'arstechnica.com',
                       'abcnews.go.com': 'abcnews.com'}.get(host, host)
            assert article in N.SOURCES, article


def test_new_outlets_do_not_leak_into_the_feeds_contested_walks():
    """`collect_contested.py` 는 FEEDS 의 이 묶음을 그대로 돈다 — 새 매체는 거기 없다."""
    for group in ('politics', 'economy', 'industry', 'tech'):
        assert all('cnbc.com' in u for u in N.FEEDS[group])
    assert not set(N.EXTRA_FEEDS) & set(N.FEEDS)


def test_the_dead_yahoo_index_feed_is_gone():
    assert not any('rssindex' in u for urls in N.FEEDS.values() for u in urls)


def test_politics_and_economy_hints_pass_through():
    assert N.classify(feed_row('x_politics', 'Hegseth impeachment effort torpedoed in House')) == 'politics'
    assert N.classify(feed_row('x_economy', 'Why is gasoline suddenly under $4 a gallon?')) == 'economy'


@pytest.mark.parametrize('title', [
    'Tesla extends Cybertruck production to clear backlog, Musk says',
    'Tesla beats on earnings and sales even as auto revenue declines',
    'Meta head of infrastructure will leave after layoffs',
    'Honda recalls 400,000 SUVs over fuel pump defect',
    'Target CEO steps down as holiday sales slump',
])
def test_a_business_feed_story_with_an_industry_word_reaches_industry(title):
    assert N.classify(feed_row('x_business', title)) == 'industry'


@pytest.mark.parametrize('title', [
    'A Romanov sapphire bracelet sells for $4.9 million at a Geneva auction',
    'Prada’s new Milan exhibition turns a century of fashion into fantasy',
    "Enrolling in Medicare? Here's what to consider before Dec. 7.",
    'What stores are open and closed for Veterans Day 2026?',
    'SNAP proposal would increase food insecurity, critics say',
    'Trump administration to pursue public land sales and a decrease in federal ownership',
    'Stanley Zabar, co-owner of iconic NYC food shop, dies at 94',
    'How to Save on Pet Expenses: Vet Visits, Medicines, Food, More',
])
def test_a_business_feed_story_without_one_is_dropped(title):
    assert N.classify(feed_row('x_business', title)) is None


def test_a_new_feed_story_on_foreign_policy_goes_nowhere():
    """구현 검토 3회차 — 글로벌 칸은 시간 상한이 없는 예전 길로 본문을 받는다. 새 매체는 거기 못 간다.
    미국 갈래로 돌리지도 않는다(11/12 실수집: 정치 칸에 우크라이나 기사) — 기존 피드에서 이 규칙은
    미국 칸에 해외 정책 기사를 들이지 않는 그물이었다."""
    title = 'China tariffs talks stall as Beijing weighs export controls'
    assert N.classify(feed_row('politics', title, url='https://www.cnbc.com/2026/11/12/a.html')) == 'global'
    for hint in N.EXTRA_FEEDS:
        assert N.classify(feed_row(hint, title)) is None
    assert N.classify(feed_row('x_politics', 'Ukraine faces new Starshield disruptions as Trump envoys '
                               'meet Putin for talks')) is None
    assert N.categorize([feed_row(h, title) for h in N.EXTRA_FEEDS]) == []


def test_a_foreign_company_story_without_policy_words_stays_in_industry():
    """해외 기업 기사는 산업·AI 에 남긴다(2026-10-28 사용자 결정) — 지역어만으로는 빼지 않는다."""
    assert N.classify(feed_row('x_business', 'Nissan recalls 400,000 cars sold in Japan')) == 'industry'


def test_a_pool_feed_story_survives_only_on_ai_or_macro_words():
    assert N.classify(feed_row('x_pool', 'OpenAI’s quarterly revenue reportedly crosses $10B')) == 'ai'
    assert N.classify(feed_row('x_pool', 'Treasury yields edge higher ahead of inflation data')) == 'macro'
    assert N.classify(feed_row('x_pool', 'The best mechanical keyboards we tested this year')) is None


@pytest.mark.parametrize('title,url', [
    ('The Guardian view on Maga after the midterms: doubling down', 'https://www.theguardian.com/us-news/x'),
    ('AI is eating the Fed’s lunch', 'https://www.theguardian.com/commentisfree/2026/nov/11/ai-fed'),
    ('WATCH: Powell speaks on inflation', 'https://www.pbs.org/newshour/politics/powell'),
    ('Nvidia chips and the Fed', 'https://www.cbsnews.com/video/nvidia-chips/'),
    ('Fed live updates', 'https://www.nbcnews.com/business/live/fed-blog'),
    ('11/11: CBS Evening News', 'https://www.cbsnews.com/news/111126-cbs-evening-news/'),
    ('Opinion: Why tariffs work', 'https://www.foxbusiness.com/economy/tariffs'),
])
def test_opinion_video_and_live_rows_are_skipped_before_the_keyword_check(title, url):
    """1회차 #10 — 제외 검사가 AI·매크로 판정 뒤면 낱말이 든 칼럼이 빠져나간다."""
    for hint in N.EXTRA_FEEDS:
        assert N.classify(feed_row(hint, title, url=url)) is None


def test_the_skip_rules_do_not_apply_to_the_established_feeds():
    r = feed_row('politics', 'Opinion: Why tariffs work', url='https://www.cnbc.com/2026/11/11/a.html')
    assert N.classify(r) == 'macro'


# ── 본문: 매체별 안내문 ───────────────────────────────────────────────────
def page(*paras):
    return '<html><body>' + ''.join(f'<p>{p}</p>' for p in paras) + '</body></html>'


REAL = 'This sentence stands in for a real paragraph of reporting about the economy. ' * 4
FOX = 'Quotes displayed in real-time or delayed by at least 15 minutes. Market data provided by Factset.'
NPR_MENU = ("Wait Wait...Don't Tell Me! Fresh Air Wild Card with Rachel Martin It's Been a Minute "
            'Machine Gods Get NPR+ More Podcasts & Shows Search Newsletters NPR Shop ' * 3)
NPR_NOTE = ('NPR does not offer or accept money for coverage or interviews. Anyone who makes such an '
            'offer or request is not an NPR employee and should be reported. ' * 3)


def test_a_host_notice_is_dropped_only_when_the_host_is_named():
    html = page(FOX, REAL, REAL, FOX)
    assert FOX in N.extract_body(html)
    with_host = N.extract_body(html, host='www.foxbusiness.com')
    assert FOX not in with_host and REAL.strip() in with_host


def test_without_a_host_the_body_is_byte_identical_to_before():
    html = page(FOX, REAL, NPR_NOTE, REAL)
    assert N.extract_body(html) == N.extract_body(html, host=None) == N.extract_body(html, host='unknown.example')


def test_an_npr_audio_stub_is_no_body_at_all():
    """음성 꼭지는 메뉴 글자와 고지문뿐인데 400자 하한을 넘겼다(11/12 실측 942자)."""
    html = page(NPR_MENU, NPR_NOTE)
    assert len(N.extract_body(html)) >= N.MIN_BODY
    assert N.extract_body(html, host='www.npr.org') == ''
