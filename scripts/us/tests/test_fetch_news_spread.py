"""fetch_news 의 매체 넓히기 배선 — 시간 마감·본문 번호·막힌 매체·기록 (2026-11-12).

설계와 codex 검토의 재현 입력: docs/superpowers/specs/2026-11-12-us-news-source-spread.md
"""
import json
import os
import sys
import threading
import urllib.error
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import fetch_news as F  # noqa: E402
from us import news as N  # noqa: E402
from us import news_expand, news_gate  # noqa: E402

NOW = datetime(2026, 11, 12, 10, 0, tzinfo=timezone.utc)
PARA = 'This sentence stands in for a real paragraph of reporting, long enough to count. '


def article(tag):
    """본문 문단에 tag 를 넣어 어느 기사의 본문인지 파일에서 알아볼 수 있게 한다."""
    return '<html><body>' + ''.join(f'<p>{tag} {PARA * 2}</p>' for _ in range(4)) + '</body></html>'


def row(guid, source, cat='politics', hours=1, extra=True, title=None, url=None):
    when = (NOW - timedelta(hours=hours)).isoformat() if hours is not None else None
    r = {'guid': guid, 'url': url or f'https://{source.lower()}.example/{guid}',
         'title': title or ' '.join(f'{guid}{w}' for w in ('alpha', 'bravo', 'carol', 'delta')),
         'summary': None, 'published': when, 'category': cat, 'source': source}
    if extra:
        r['_extra'] = True
    return r


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def refuse(code=403):
    def fetch(url, ctx):
        raise urllib.error.HTTPError(url, code, 'no', {}, None)
    return fetch


# ── Budget · bounded ──────────────────────────────────────────────────────
def test_bounded_returns_the_value_and_passes_errors_through():
    b = F.Budget(5)
    assert F.bounded(lambda: 'ok', b) == 'ok'
    with pytest.raises(KeyError):
        F.bounded(lambda: {}['x'], b)


def test_a_request_that_outlives_the_wait_is_late_and_its_result_is_dropped():
    """2회차 2-3 — 마감 직전에 시작한 요청은 마감 뒤에도 돌았다."""
    release, seen = threading.Event(), []

    def slow():
        release.wait(5)
        seen.append('finished')
        return 'too late'
    with pytest.raises(F.Late):
        F.bounded(slow, F.Budget(5), per=0.05)
    assert seen == []                    # 기다림은 끊겼고 값은 아무 데도 가지 않았다
    release.set()


def test_nothing_is_started_once_the_budget_is_spent():
    clock, started = Clock(), []
    budget = F.Budget(10, clock)
    clock.t = 10
    with pytest.raises(F.Late):
        F.bounded(lambda: started.append(1), budget)
    assert started == [] and budget.over()


def test_the_wait_is_the_smaller_of_the_request_cap_and_the_time_left():
    clock = Clock()
    budget = F.Budget(100, clock)
    clock.t = 99.95                       # 남은 0.05초 — per=10 이어도 0.05초만 기다린다
    release = threading.Event()
    with pytest.raises(F.Late):
        F.bounded(lambda: release.wait(5), budget, per=10)
    release.set()


def test_a_403_chain_of_fingerprint_retries_is_cut_by_the_same_wait(monkeypatch):
    """3회차 3-3 — 403 은 브라우저 지문으로 두 번 더 묻는다. 그 시간도 같은 기다림 안이다."""
    release = threading.Event()

    def refused(req, timeout=None, context=None):
        raise urllib.error.HTTPError(req.full_url, 403, 'no', {}, None)

    def slow_fingerprint(url):
        release.wait(5)
        return '<rss/>'
    monkeypatch.setattr(F.urllib.request, 'urlopen', refused)
    with pytest.raises(F.Late):
        F.bounded(lambda: F.get('https://x.example/feed', None, retries=0,
                                impersonated=slow_fingerprint), F.Budget(5), per=0.05)
    release.set()


def test_get_hands_its_timeout_to_the_socket(monkeypatch):
    seen = {}

    class R:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'x'

    def urlopen(req, timeout=None, context=None):
        seen['timeout'] = timeout
        return R()
    monkeypatch.setattr(F.urllib.request, 'urlopen', urlopen)
    F.get('https://x.example/a', None, timeout=7)
    assert seen['timeout'] == 7


# ── 본문 수집: 번호·매체별 안내문·늦은 결과 ───────────────────────────────
def test_start_numbers_the_body_file(tmp_path):
    r = row('a', 'CBS')
    F.fetch_bodies([r], str(tmp_path), None, fetch=lambda u, c: article('AAA'), start=7)
    assert r['body_file'] == '07-politics.txt'
    assert 'AAA' in (tmp_path / '07-politics.txt').read_text(encoding='utf-8')


def test_a_late_request_changes_neither_the_row_nor_the_folder(tmp_path):
    """3회차 3-4 — 늦은 결과가 행과 파일을 바꾸면 안 된다."""
    release, returned = threading.Event(), threading.Event()

    def slow(url, ctx):
        release.wait(5)
        try:
            return article('LATE')
        finally:
            returned.set()
    r = row('a', 'CBS')
    F.fetch_bodies([r], str(tmp_path), None,
                   fetch=lambda u, c: F.bounded(lambda: slow(u, c), F.Budget(5), per=0.05))
    before = dict(r)
    release.set()
    assert returned.wait(5)                  # 늦은 요청이 값을 돌려준 **뒤에도** 그대로여야 한다
    threading.Event().wait(0.05)
    assert r == before
    assert r['body_chars'] == 0 and r['body_note'] == 'Late' and 'body_file' not in r
    assert list(tmp_path.iterdir()) == []


def test_a_pdf_request_is_bounded_too(tmp_path):
    """4회차 4-2 — PDF 는 fetch 가 아니라 fetch_bytes 로 간다. 마감을 우회했다."""
    release = threading.Event()
    r = row('a', 'CNBC', extra=False, url='https://cnbc.example/report.pdf')
    picked, funnel, _ = F.spread_stage(
        [r], str(tmp_path), None, 3, NOW, start=1,
        fetch=lambda u, c: article('X'), fetch_bytes=lambda u, c: release.wait(5),
        spread_seconds=0.05, stage_seconds=0.1)
    release.set()
    assert picked == [] and r['body_note'] == 'Late'
    assert list(tmp_path.iterdir()) == []


def test_the_host_notice_is_stripped_for_spread_rows_only(tmp_path):
    notice = '<p>Quotes displayed in real-time or delayed by at least 15 minutes. Market data provided by Factset.</p>'
    html = article('FOX').replace('<body>', '<body>' + notice)
    a = row('a', 'Fox Business', url='https://www.foxbusiness.com/economy/a')
    b = dict(a)
    F.fetch_bodies([a], str(tmp_path / 'x'), None, fetch=lambda u, c: html, hosted=True)
    F.fetch_bodies([b], str(tmp_path / 'y'), None, fetch=lambda u, c: html)
    assert b['body_chars'] > a['body_chars'] > 0


# ── 돌려 뽑기 단계 ────────────────────────────────────────────────────────
def serve(pages):
    asked = []

    def fetch(url, ctx):
        asked.append(url)
        got = pages[url]
        if isinstance(got, Exception):
            raise got
        return got
    return fetch, asked


def test_each_confirmed_row_points_at_its_own_body(tmp_path):
    """2회차 2-5 — 단건 호출이 같은 번호를 쓰면 앞 파일을 덮어쓴다. 실패한 시도도 번호를 쓴다."""
    rows = [row('a1', 'A', hours=1), row('b1', 'B', hours=2), row('b2', 'B', hours=3),
            row('c1', 'C', hours=4)]
    pages = {r['url']: article(r['guid'].upper()) for r in rows}
    pages[rows[1]['url']] = urllib.error.HTTPError(rows[1]['url'], 403, 'no', {}, None)
    fetch, _ = serve(pages)
    picked, funnel, nxt = F.spread_stage(rows, str(tmp_path), None, 3, NOW, start=5, fetch=fetch)
    assert [r['guid'] for r in picked] == ['a1', 'b2', 'c1']
    assert nxt == 9                                           # 5,6(실패),7,8
    names = [r['body_file'] for r in picked]
    assert len(set(names)) == 3
    for r in picked:
        text = (tmp_path / r['body_file']).read_text(encoding='utf-8')
        assert r['guid'].upper() in text and r['url'] in text


def test_an_outlet_that_fails_twice_is_not_asked_again_this_run(tmp_path):
    rows = ([row(f'x{i}', 'X', cat='politics', hours=i + 1) for i in range(2)]
            + [row(f'y{i}', 'X', cat='industry', hours=i + 1) for i in range(2)]
            + [row('n1', 'CNBC', cat='industry', hours=5, extra=False)])
    pages = {r['url']: urllib.error.HTTPError(r['url'], 403, 'no', {}, None) for r in rows}
    pages[rows[-1]['url']] = article('N1')
    fetch, asked = serve(pages)
    picked, funnel, _ = F.spread_stage(rows, str(tmp_path), None, 3, NOW, start=1, fetch=fetch)
    assert [r['guid'] for r in picked] == ['n1']
    assert sum('x.example' in u for u in asked) == 2          # 정치에서 두 번 실패한 뒤 산업에서는 안 묻는다
    assert funnel['blocked'] == ['X']
    assert funnel['categories']['industry']['X']['fail'] == {'blocked': 2}
    assert funnel['categories']['politics']['X']['fail'] == {'HTTP 403': 2}


def test_an_empty_shell_does_not_block_the_outlet(tmp_path):
    rows = [row(f'x{i}', 'NPR', hours=i + 1) for i in range(4)]
    pages = {r['url']: '<html><body><p>menu</p></body></html>' for r in rows[:3]}
    pages[rows[3]['url']] = article('X3')
    fetch, asked = serve(pages)
    picked, funnel, _ = F.spread_stage(rows, str(tmp_path), None, 3, NOW, start=1, fetch=fetch)
    assert [r['guid'] for r in picked] == ['x3'] and len(asked) == 4
    assert funnel['blocked'] == []
    assert funnel['categories']['politics']['NPR'] == {
        'candidates': 4, 'tried': 4, 'with_body': 1, 'chosen': 1, 'fail': {'추출 실패': 3}}


def test_when_the_spread_time_runs_out_the_old_way_fills_every_category(tmp_path):
    """2회차 2-4 — 시간 상한의 부분 결과가 빈 갈래째 굳는다."""
    clock = Clock()
    rows = []
    for cat in N.ROTATE:
        rows += [row(f'{cat}-new{i}', f'New{i}', cat=cat, hours=1) for i in range(3)]
        rows += [row(f'{cat}-cnbc{i}', 'CNBC', cat=cat, hours=50 + i, extra=False) for i in range(4)]

    def slow(url, ctx):
        clock.t += 40                                  # 요청 한 건이 40초 — 넷째 요청 전에 150초가 끝난다
        return article('B')
    picked, funnel, _ = F.spread_stage(rows, str(tmp_path), None, 3, NOW, start=1, fetch=slow,
                                       clock=clock, spread_seconds=150, stage_seconds=10_000)
    by = {}
    for r in picked:
        by.setdefault(r['category'], []).append(r['source'])
    assert set(by) == set(N.ROTATE) and all(len(v) == 3 for v in by.values())
    assert by[N.ROTATE[-1]] == ['CNBC'] * 3            # 뒤 갈래는 통째로 옛 길(창 밖 50시간 기사도 쓴다)
    assert funnel['stopped'] == ['spread_time_cap']
    assert funnel['legacy_filled'] >= 3


def test_when_the_whole_stage_runs_out_it_saves_fewer(tmp_path):
    """3회차 3-3 — 옛 길도 같은 마감 안이다. 마감에 걸리면 덜 찬 채로 끝난다."""
    clock = Clock()
    rows = []
    for cat in N.ROTATE:
        rows += [row(f'{cat}-cnbc{i}', 'CNBC', cat=cat, hours=1 + i, extra=False) for i in range(4)]

    def slow(url, ctx):
        clock.t += 40
        return article('B')
    picked, funnel, _ = F.spread_stage(rows, str(tmp_path), None, 3, NOW, start=1, fetch=slow,
                                       clock=clock, spread_seconds=100, stage_seconds=240)
    assert 0 < len(picked) < 15
    assert funnel['stopped'] == ['spread_time_cap', 'stage_time_cap']


def test_time_running_out_on_the_last_candidate_still_opens_the_old_way(tmp_path):
    """구현 검토 2회차 #1 — 36시간 안 후보가 하나뿐이고 그 요청이 마감에 걸리면 Stop 없이 끝났다."""
    clock = Clock()
    cat = N.ROTATE[0]
    rows = [row('only', 'CBS', cat=cat, hours=1),
            row('old1', 'CNBC', cat=cat, hours=60, extra=False),
            row('old2', 'CNBC', cat=cat, hours=61, extra=False)]

    def fetch(url, ctx):
        if 'cbs.example' in url:
            clock.t += 200                             # 이 요청 중에 돌려 뽑기 150초가 끝난다
            raise urllib.error.HTTPError(url, 403, 'no', {}, None)
        return article('OLD')
    picked, funnel, _ = F.spread_stage(rows, str(tmp_path), None, 3, NOW, start=1, fetch=fetch,
                                       clock=clock, spread_seconds=150, stage_seconds=10_000)
    assert [r['guid'] for r in picked] == ['old1', 'old2']
    assert funnel['stopped'] == ['spread_time_cap'] and funnel['legacy_filled'] == 2


def test_the_old_way_does_not_ask_a_blocked_outlet_again(tmp_path):
    """구현 검토 1회차 #3 — CNBC 가 두 번 실패해 막힌 뒤 시간이 끝나면 옛 길이 CNBC 에 다시 물었다."""
    clock = Clock()
    rows = [row(f'n{i}', 'CNBC', cat=N.ROTATE[0], hours=1 + i, extra=False) for i in range(6)]
    asked = []

    def refused_and_slow(url, ctx):
        asked.append(url)
        clock.t += 80                                  # 두 번 실패하면 160초 — 돌려 뽑기 150초가 끝난다
        raise urllib.error.HTTPError(url, 403, 'no', {}, None)
    picked, funnel, _ = F.spread_stage(rows, str(tmp_path), None, 3, NOW, start=1, fetch=refused_and_slow,
                                       clock=clock, spread_seconds=150, stage_seconds=10_000)
    assert picked == [] and len(asked) == 2
    assert funnel['stopped'] == ['spread_time_cap'] and funnel['blocked'] == ['CNBC']


def test_the_old_way_counts_its_own_failures_toward_the_block(tmp_path):
    clock = Clock()
    rows = [row(f'n{i}', 'CNBC', cat=N.ROTATE[0], hours=1 + i, extra=False) for i in range(6)]
    asked = []

    def refused(url, ctx):
        asked.append(url)
        raise urllib.error.HTTPError(url, 403, 'no', {}, None)
    picked, funnel, _ = F.spread_stage(rows, str(tmp_path), None, 3, NOW, start=1, fetch=refused,
                                       clock=clock, spread_seconds=0, stage_seconds=10_000)
    assert picked == [] and len(asked) == 2 and funnel['blocked'] == ['CNBC']


def test_the_stage_cap_is_recorded_even_when_it_ends_on_the_last_request(tmp_path):
    """구현 검토 4회차 — 옛 길의 마지막 후보를 묻는 동안 마감이 끝나면 기록이 빠졌다."""
    clock = Clock()
    rows = [row('n0', 'CNBC', cat=N.ROTATE[-1], hours=1, extra=False)]

    def slow(url, ctx):
        clock.t += 500
        return article('B')
    picked, funnel, _ = F.spread_stage(rows, str(tmp_path), None, 3, NOW, start=1, fetch=slow,
                                       clock=clock, spread_seconds=0, stage_seconds=240)
    assert funnel['stopped'] == ['spread_time_cap', 'stage_time_cap']


def test_a_quiet_category_is_not_topped_up_when_time_was_not_the_problem(tmp_path):
    rows = [row('only', 'CBS', hours=1), row('old', 'CNBC', hours=60, extra=False)]
    fetch, _ = serve({r['url']: article('B') for r in rows})
    picked, funnel, _ = F.spread_stage(rows, str(tmp_path), None, 3, NOW, start=1, fetch=fetch)
    assert [r['guid'] for r in picked] == ['only']       # 36시간 밖 CNBC 로 채우지 않는다
    assert funnel['stopped'] == [] and funnel['legacy_filled'] == 0


# ── 새 매체 피드 ──────────────────────────────────────────────────────────
def rss(*links):
    items = ''.join(f'<item><link>{u}</link><guid isPermaLink="false">123</guid><title>T {i}</title>'
                    f'<pubDate>Thu, 12 Nov 2026 09:00:00 GMT</pubDate></item>' for i, u in enumerate(links))
    return f'<?xml version="1.0"?><rss version="2.0"><channel>{items}</channel></rss>'


def test_new_feeds_come_back_identified_by_url_and_failures_are_noted():
    feeds = {'x_politics': ('https://a.example/feed', 'https://b.example/feed'),
             'x_pool': ('https://c.example/feed',)}
    pages = {'https://a.example/feed': rss('https://a.example/1#frag', 'https://a.example/2'),
             'https://b.example/feed': urllib.error.HTTPError('u', 403, 'no', {}, None),
             'https://c.example/feed': '<html>blocked</html>'}
    fetch, _ = serve(pages)
    notes = []
    rows = F.harvest_extra(None, F.Budget(60), notes, fetch=fetch, feeds=feeds)
    assert [r['guid'] for r in rows] == ['https://a.example/1', 'https://a.example/2']
    assert all(r['_extra'] and r['category'] == 'x_politics' for r in rows)
    assert any('b.example' in n and 'HTTP 403' in n for n in notes)
    assert any('c.example' in n for n in notes)


def test_new_feeds_stop_when_their_time_is_up():
    clock = Clock()

    def slow(url, ctx):
        clock.t += 40
        return rss(url + '/1')
    notes = []
    feeds = {'x_pool': tuple(f'https://h{i}.example/feed' for i in range(5))}
    rows = F.harvest_extra(None, F.Budget(60, clock), notes, fetch=slow, feeds=feeds)
    assert len(rows) == 2 and any(n.startswith('extra_time_cap') for n in notes)


# ── 그날 파일과의 대조 ────────────────────────────────────────────────────
def save(tmp_path, items, **extra):
    path = tmp_path / 'news' / '2026-11-12.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict({'items': items}, **extra), ensure_ascii=False), encoding='utf-8')
    return str(path)


SUMMARY = ('미시시피 상원 선거에서 민주당 후보가 현직 공화당 의원을 꺾었다. ' * 8).strip()


def test_another_outlets_article_never_inherits_a_saved_summary(tmp_path):
    """3회차 3-2 통합 — 그날 파일 (G, CNBC, A) 뒤에 (G, 다른 매체, B) 만 들어온다."""
    path = save(tmp_path, [{'guid': 'G', 'source': 'CNBC', 'url': 'https://www.cnbc.com/a',
                            'summary_ko': SUMMARY}])
    newcomer = {'guid': 'G', 'source': 'CBS News', 'url': 'https://www.cbsnews.com/b', 'title': 'B'}
    kept, dropped = N.reconcile([newcomer], F.existing_index(path))
    assert kept == [] and len(dropped) == 1
    assert F.carry_summaries(path, kept) == 0


def test_a_new_outlets_article_gets_its_summary_back_on_refresh(tmp_path):
    """새 매체 기사는 다시 받아도 같은 guid(URL)라 요약이 이월된다."""
    feeds = {'x_politics': ('https://a.example/feed',)}
    fetch, _ = serve({'https://a.example/feed': rss('https://a.example/story?ref=1')})
    [first] = F.harvest_extra(None, F.Budget(60), [], fetch=fetch, feeds=feeds)
    path = save(tmp_path, [dict(first, summary_ko=SUMMARY)])
    [again] = F.harvest_extra(None, F.Budget(60), [], fetch=fetch, feeds=feeds)
    kept, dropped = N.reconcile([again], F.existing_index(path))
    assert dropped == [] and F.carry_summaries(path, kept) == 1
    assert kept[0]['summary_ko'] == SUMMARY


def test_two_new_outlets_with_one_raw_guid_expand_and_gate_separately(tmp_path):
    """1회차 #3 통합 — 원 guid 가 같은 두 매체 기사가 확장기·게이트에서 섞이지 않는다."""
    feeds = {'x_politics': ('https://a.example/feed', 'https://b.example/feed')}
    fetch, _ = serve({'https://a.example/feed': rss('https://a.example/one'),
                      'https://b.example/feed': rss('https://b.example/two')})
    a, b = F.harvest_extra(None, F.Budget(60), [], fetch=fetch, feeds=feeds)
    assert a['guid'] != b['guid']
    assert len(N.dedupe([a, b])) == 2
    items = [dict(a, summary_ko='가 기사의 요약이다. ' * 30, body_chars=900),
             dict(b, summary_ko='나 기사의 요약이다. ' * 30, body_chars=900)]
    html = f"<!--NEWS:{a['guid']}|가 제목-->\n<!--NEWS:{b['guid']}|나 제목-->"
    out, errors = news_expand.expand(html, {'items': items})
    assert errors == []
    assert out.index('가 기사의 요약') < out.index('나 기사의 요약')
    assert f'data-news="{a["guid"]}"' in out and f'data-news="{b["guid"]}"' in out
    assert not [m for m in news_gate.check(out, {'items': items}) if '그날 수집분에 없다' in m]


def test_a_new_feed_article_expands_and_passes_the_summary_check(tmp_path):
    """구현 검토 1회차 #1 — 「수집분에 있다」만 보던 시험은 `data-summary` 대조 실패를 놓쳤다.
    확장한 블록에 대해 요약 원문 대조까지 통과해야 한다."""
    feeds = {'x_business': ('https://fortune.example/feed',)}
    fetch, _ = serve({'https://fortune.example/feed': rss('https://fortune.example/2026/11/12/a-b_c/?x=1')})
    [it] = F.harvest_extra(None, F.Budget(60), [], fetch=fetch, feeds=feeds)
    items = [dict(it, summary_ko='포천 기사의 요약이다. ' * 30, body_chars=900)]
    out, errors = news_expand.expand(f"<!--NEWS:{it['guid']}|제목-->", {'items': items})
    assert errors == [] and '포천 기사의 요약' in out
    assert news_expand.summary_violations(out, {'items': items}) == []
    assert not [m for m in news_gate.check(out, {'items': items}) if 'data-news' in m or 'data-summary' in m]


def test_a_feed_url_with_an_ampersand_never_becomes_an_article():
    feeds = {'x_business': ('https://fortune.example/feed',)}
    fetch, _ = serve({'https://fortune.example/feed': rss('https://fortune.example/?p=1&show=2',
                                                         'https://fortune.example/ok')})
    rows = F.harvest_extra(None, F.Budget(60), [], fetch=fetch, feeds=feeds)
    assert [r['guid'] for r in rows] == ['https://fortune.example/ok']


# ── 저장되는 모양 ─────────────────────────────────────────────────────────
def test_the_gate_reads_a_file_that_carries_a_funnel(tmp_path):
    """1회차 #12 — 가산 필드가 읽는 쪽을 깨지 않는다."""
    rows = [row('a1', 'CBS News', hours=1)]
    fetch, _ = serve({rows[0]['url']: article('A1')})
    picked, funnel, _ = F.spread_stage(rows, str(tmp_path), None, 3, NOW, start=1, fetch=fetch)
    payload = {'report_date': '2026-11-12', 'items': picked, 'funnel': funnel, 'notes': []}
    text = json.dumps(payload, ensure_ascii=False)          # Counter 같은 것이 섞이면 여기서 죽는다
    back = json.loads(text)
    assert back['funnel']['categories']['politics']['CBS News']['chosen'] == 1
    assert news_gate.check('<html><body></body></html>', back) is not None


# ── main 통째로 (네트워크 없이) ───────────────────────────────────────────
def feed_xml(host, n, word, hours=2):
    when = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime('%a, %d %b %Y %H:%M:%S GMT')
    items = ''.join(
        f'<item><link>https://{host}/{word}-{i}</link><guid isPermaLink="false">{i}</guid>'
        f'<title>{host} {word}{i}alpha {word}{i}bravo {word}{i}carol</title><pubDate>{when}</pubDate></item>'
        for i in range(n))
    return f'<?xml version="1.0"?><rss version="2.0"><channel>{items}</channel></rss>'


@pytest.fixture
def offline(monkeypatch, tmp_path):
    """피드 셋(CNBC 정치, 새 매체 둘)과 기사면을 메모리에서 준다. 요약은 가짜."""
    feeds = {'https://www.cnbc.com/politics.rss': feed_xml('www.cnbc.com', 5, 'cnbc'),
             'https://www.pbs.org/politics.rss': feed_xml('www.pbs.org', 3, 'pbs', hours=3),
             'https://www.cbsnews.com/politics.rss': feed_xml('www.cbsnews.com', 3, 'cbs', hours=4)}
    asked, summarised, calls = [], [], []

    def get(url, ctx, retries=2, impersonated=None, timeout=None):
        asked.append(url)
        calls.append((url, retries, timeout))
        if url in feeds:
            return feeds[url]
        if 'cbsnews.com' in url and offline.cbs_down:
            raise urllib.error.HTTPError(url, 403, 'no', {}, None)
        return article(url)

    def summarise(chosen, bodydir):
        todo = [it for it in chosen if it.get('body_chars') and not it.get('summary_ko')]
        for it in todo:
            it['summary_ko'] = SUMMARY
        summarised.append(len(todo))
        return len(todo)
    monkeypatch.setattr(F, 'FEEDS', {'politics': ('https://www.cnbc.com/politics.rss',)})
    monkeypatch.setattr(F, 'EXTRA_FEEDS', {'x_politics': ('https://www.pbs.org/politics.rss',
                                                         'https://www.cbsnews.com/politics.rss')})
    monkeypatch.setattr(F, 'pages', lambda year: {})
    monkeypatch.setattr(F, 'get', get)
    monkeypatch.setattr(F, '_context', lambda: None)
    monkeypatch.setattr(F, 'apply_region_filter', lambda rows, exempt=(), post=None: (rows, {'mode': 'off'}))
    monkeypatch.setattr(F, 'summarize_chosen', summarise)
    monkeypatch.setattr(F.time, 'sleep', lambda s: None)
    offline.cbs_down = False
    offline.asked, offline.summarised, offline.calls, offline.feeds = asked, summarised, calls, feeds
    offline.datadir, offline.bodydir = str(tmp_path / 'data'), str(tmp_path / 'bodies')
    return offline


def run_main(monkeypatch, env, *flags):
    monkeypatch.setattr(sys, 'argv', ['fetch_news.py', '--datadir', env.datadir, '--bodydir', env.bodydir,
                                      '--date', '2026-11-12', *flags])
    F.main()
    with open(os.path.join(env.datadir, 'news', '2026-11-12.json'), encoding='utf-8') as fh:
        return json.load(fh)


def test_main_spreads_a_category_across_outlets_and_records_the_funnel(monkeypatch, offline):
    got = run_main(monkeypatch, offline)
    politics = [it for it in got['items'] if it['category'] == 'politics']
    assert sorted(it['source'] for it in politics) == ['CBS News', 'CNBC', 'PBS NewsHour']
    assert all(it['summary_ko'] and it['body_chars'] for it in politics)
    assert not any('_extra' in it for it in got['items'])
    assert got['items'][0]['guid'] != got['items'][1]['guid']
    cell = got['funnel']['categories']['politics']
    assert {s: c['chosen'] for s, c in cell.items()} == {'CNBC': 1, 'PBS NewsHour': 1, 'CBS News': 1}
    assert cell['CNBC']['candidates'] == 5
    assert set(got['funnel']['seconds']) == {'extra_feeds', 'confirm'}
    assert got['funnel']['stopped'] == [] and got['notes'] == []
    for it in politics:                                   # 요약기가 읽을 본문이 그 기사의 것이다
        with open(os.path.join(offline.bodydir, it['body_file']), encoding='utf-8') as fh:
            assert it['url'] in fh.read()


def test_every_request_to_a_new_outlet_is_the_short_bounded_kind(monkeypatch, offline):
    """구현 검토 3회차 — 새 매체 기사가 글로벌 칸으로 가면 재시도·20초 timeout 의 예전 길로 받았다."""
    foreign = ('<item><link>https://www.pbs.org/china-tariffs</link><guid>g</guid>'
               '<title>China tariffs talks stall as Beijing weighs export controls</title>'
               f'<pubDate>{(datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%a, %d %b %Y %H:%M:%S GMT")}'
               '</pubDate></item>')
    url = 'https://www.pbs.org/politics.rss'
    offline.feeds[url] = offline.feeds[url].replace('<channel>', '<channel>' + foreign)
    got = run_main(monkeypatch, offline)
    assert not [it for it in got['items'] if it['category'] == 'global']
    assert not [it for it in got['items'] if 'china-tariffs' in it['url']]     # 미국 갈래로도 안 간다
    new = [c for c in offline.calls if 'pbs.org' in c[0] or 'cbsnews.com' in c[0]]
    assert new and all(retries == 0 and timeout == F.EXTRA_TIMEOUT for _, retries, timeout in new)


def test_main_falls_back_to_the_outlets_that_open(monkeypatch, offline):
    offline.cbs_down = True
    got = run_main(monkeypatch, offline)
    politics = [it for it in got['items'] if it['category'] == 'politics']
    assert sorted(it['source'] for it in politics) == ['CNBC', 'CNBC', 'PBS NewsHour']
    # 두 번 실패한 뒤 셋째 기사는 묻지 않는다
    assert got['funnel']['categories']['politics']['CBS News']['fail'] == {'HTTP 403': 2, 'blocked': 1}
    assert got['funnel']['blocked'] == ['CBS News']
    assert sum('cbsnews.com/cbs-' in u for u in offline.asked) == 2


def test_a_frozen_day_is_not_fetched_again_and_refresh_keeps_the_summaries(monkeypatch, offline):
    first = run_main(monkeypatch, offline)
    n = len(offline.asked)
    again = run_main(monkeypatch, offline)                # 동결 — 아무것도 다시 받지 않는다
    assert len(offline.asked) == n and again == first
    third = run_main(monkeypatch, offline, '--refresh')   # 다시 받아도 같은 기사는 같은 guid·같은 요약
    assert [it['guid'] for it in third['items']] == [it['guid'] for it in first['items']]
    assert offline.summarised == [3, 0]
