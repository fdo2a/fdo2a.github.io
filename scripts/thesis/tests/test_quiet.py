"""조용한 날 판정 — 모델을 부르기 전에 산술로 「오늘은 볼 게 없다」를 증명한다.

설계: docs/superpowers/specs/2026-09-24-thesis-quiet-prefilter.md
"""
from datetime import date, datetime, timezone

from thesis import newsroom as N
from thesis import quiet as Q

TODAY = date(2026, 9, 23)          # 수요일


def watch(**over):
    base = {'as_of': '2026-09-23', 'complete': True, 'missing': [],
            'tickers': {'005930.KS': {'next_earnings_date': '2026-10-28'},
                        '000660.KS': {'next_earnings_date': '2026-10-27'},
                        'MU': {'next_earnings_date': '2026-12-17'}}}
    base.update(over)
    return base


def disclosures(confirmed=0, **over):
    base = {'as_of': '2026-09-23', 'missing': [],
            'tickers': {'005930.KS': {'confirmed_count': confirmed, 'events': []}}}
    base.update(over)
    return base


def events(items=(), **over):
    base = {'collected_at': '2026-09-23T08:45:00+00:00', 'missing': [],
            'items': list(items)}
    base.update(over)
    return base


def decide(**kw):
    args = dict(today=TODAY, watch=watch(), triggers={'005930.KS': [], 'MU': []},
                disclosures=disclosures(), events=events())
    args.update(kw)
    return Q.decide(**args)


def test_a_day_with_nothing_is_quiet():
    quiet, reasons = decide()
    assert quiet and reasons == []


def test_each_signal_breaks_the_quiet():
    cases = {
        'triggers': dict(triggers={'MU': [{'kind': 'consensus_swing'}]}),
        'disclosure': dict(disclosures=disclosures(confirmed=1)),
        'newsroom': dict(events=events([{'ticker': '005930.KS', 'title': 'HBM4 shipment',
                                         'url': 'u', 'published': '2026-09-23T01:00:00+00:00'}])),
        'earnings': dict(watch=watch(tickers={'MU': {'next_earnings_date': '2026-09-24'}})),
    }
    for name, kw in cases.items():
        quiet, reasons = decide(**kw)
        assert not quiet, name
        assert reasons, name


def test_what_cannot_be_proven_quiet_is_not_quiet():
    """입력이 낡았거나 빠졌으면 「조용하다」를 증명할 수 없다 — 리서치로 넘긴다."""
    for kw in (dict(watch=watch(as_of='2026-09-22')),
               dict(watch=watch(complete=False)),
               dict(disclosures=disclosures(missing=['timeout'])),
               dict(disclosures=disclosures(pending=True)),
               dict(disclosures=None),
               dict(events=None),
               dict(events=events(missing=['SK hynix · IR: HTTP 503'])),
               dict(events=events(collected_at='2026-09-22T08:45:00+00:00'))):
        quiet, reasons = decide(**kw)
        assert not quiet and reasons, kw


def test_earnings_window_covers_the_days_after():
    for day, expect_quiet in ((date(2026, 9, 29), False), (date(2026, 10, 2), False),
                              (date(2026, 10, 3), True), (date(2026, 9, 27), True)):
        w = watch(as_of=day.isoformat(),
                  tickers={'MU': {'next_earnings_date': '2026-09-30'}})
        d = disclosures(as_of=day.isoformat())
        e = events(collected_at=f'{day.isoformat()}T08:45:00+00:00')
        quiet, _ = decide(today=day, watch=w, disclosures=d, events=e)
        assert quiet is expect_quiet, day


def test_friday_is_the_full_sweep():
    """고객사 발표와 Micron 은 피드로 기계화하지 못했다 — 주 1회는 사람처럼 다 본다."""
    day = date(2026, 9, 25)
    quiet, reasons = decide(today=day, watch=watch(as_of='2026-09-25'),
                            disclosures=disclosures(as_of='2026-09-25'),
                            events=events(collected_at='2026-09-25T08:45:00+00:00'))
    assert not quiet and any('금요일' in r for r in reasons)


# ── 뉴스룸 피드 ──

RSS = '''<?xml version="1.0"?><rss version="2.0"><channel><title>x</title>
<item><title>SK hynix Announces 3Q26 Financial Results</title>
<link>https://news.skhynix.com/a/</link><pubDate>Thu, 24 Sep 2026 06:00:00 +0000</pubDate></item>
<item><title>Old &amp; known</title>
<link>https://news.skhynix.com/b/</link><pubDate>Mon, 21 Sep 2026 06:00:00 +0000</pubDate></item>
<item><title>No date</title><link>https://news.skhynix.com/c/</link></item>
</channel></rss>'''


def test_parse_reads_title_link_and_utc_time():
    items = N.parse(RSS)
    assert items[0] == {'title': 'SK hynix Announces 3Q26 Financial Results',
                        'url': 'https://news.skhynix.com/a/',
                        'published': '2026-09-24T06:00:00+00:00'}
    assert items[1]['title'] == 'Old & known'
    assert len(items) == 2        # 날짜 없는 항목은 창에 넣을 수 없다


def test_collect_keeps_only_items_since_the_last_collection():
    now = datetime(2026, 9, 24, 8, 45, tzinfo=timezone.utc)
    prev = {'collected_at': '2026-09-23T08:45:00+00:00'}
    feeds = (('000660.KS', 'SK hynix · Press', 'p'), ('000660.KS', 'SK hynix · IR', 'i'))
    out = N.collect(prev, now, feeds=feeds, fetch=lambda url: RSS)
    assert [i['url'] for i in out['items']] == ['https://news.skhynix.com/a/']   # 중복 제거
    assert out['items'][0]['ticker'] == '000660.KS'
    assert out['since'] == '2026-09-23T08:45:00+00:00'
    assert out['collected_at'] == now.isoformat()
    assert out['missing'] == []


def test_a_failed_feed_is_recorded_not_raised():
    def fetch(url):
        raise OSError('HTTP 503')
    now = datetime(2026, 9, 24, 8, 45, tzinfo=timezone.utc)
    out = N.collect(None, now, feeds=(('MU', 'x', 'u'),), fetch=fetch)
    assert out['items'] == [] and out['missing'] and 'HTTP 503' in out['missing'][0]
    # 첫 수집(직전 기록 없음)은 36 시간을 되돌아본다.
    assert out['since'] == '2026-09-22T20:45:00+00:00'
