"""scripts/fetch_telegram_jp.py — the Japan daily's Telegram file: one save, one `usable` switch (2026-11-15).
Synthetic sentences only. Design: docs/superpowers/specs/2026-11-15-telegram-japan-daily.md"""
import json
from datetime import datetime, timedelta, timezone

import pytest

import fetch_telegram as F
import fetch_telegram_jp as FJ
from common import tg_jp as J
from common.tests.test_telegram import fake_channel, nosleep
from common.tests.test_tg_jp import FILL, P, S, post

JST = timezone(timedelta(hours=9))
AFTER = datetime(2026, 11, 13, 18, 0, tzinfo=JST)          # the run starts after the 16:30 cut
BEFORE = datetime(2026, 11, 13, 15, 0, tzinfo=JST)
SUMMARY = '어드반테스트의 검사 장비 수요가 늘어 내년 실적 전망이 올랐다는 분석이 전해졌다. 메모리 투자도 이어진다는 시각이다.'
OK = {'status': 'ok', 'pages': 3, 'truncated': False, 'reached': True}
POSTS = [post(1, 'JP모건) 어드반테스트 목표가 상향' + FILL, '11-13 09:00'),
         post(2, '엔비디아 실적 요약' + FILL, '11-13 09:10'),
         post(3, '닛케이) 키옥시아 증설' + FILL, '11-13 10:00'),
         post(4, '혼다 실적' + FILL, '11-13 17:00')]            # after the cut: the next session's


def reader(posts=POSTS, st=OK):
    def read(ch, cursor, floor, fetch, sleep, max_pages=None, track_reached=False):
        assert ch == J.JP_CHANNEL and cursor is None and track_reached
        assert floor == J.cut(P) - timedelta(hours=J.READ_MARGIN_H)
        return list(posts), dict(st)
    return read


def summ(items, bodies):
    n = 0
    for it in items:
        if not it.get('summary_ko'):
            it['summary_ko'] = SUMMARY
            n += 1
    return n, 0


def run(tmp_path, now=AFTER, read=None, summarize=summ, **kw):
    return FJ.run(S, P, str(tmp_path / 'data'), str(tmp_path / 'bodies'), now=now, read=read or reader(),
                  summarize=summarize, sleep=nosleep, **kw)


def saved(tmp_path):
    p = tmp_path / 'data' / 'telegram' / f'{S}.json'
    return json.loads(p.read_text(encoding='utf-8')) if p.exists() else None


def test_a_complete_run_is_usable(tmp_path):
    assert run(tmp_path) == 0
    d = saved(tmp_path)
    assert d['usable'] is True and d['report_date'] == S and d['market'] == 'jp'
    assert d['window'] == {'floor': J.cut(P).isoformat(), 'ceiling': J.cut(S).isoformat()}
    assert [it['id'] for it in d['items']] == [f'{J.JP_CHANNEL}/1', f'{J.JP_CHANNEL}/3']
    a, b = d['items']
    assert a['relay_firm'] == 'JP모건' and a['news_use'] is True and a['summary_ko'] == SUMMARY
    assert b['source']['name'] == '니혼게이자이'
    assert d['stats']['outside'] == 1 and d['stats']['not_japan'] == 1 and d['stats']['news_use'] == 2
    # the post text stays out of the committed file
    assert 'text' not in a and FILL.strip() not in json.dumps(d, ensure_ascii=False)
    assert (tmp_path / 'bodies' / f'{J.JP_CHANNEL}_1.txt').read_text(encoding='utf-8').startswith('JP모건)')


def test_a_run_before_the_cut_is_never_usable(tmp_path):
    assert run(tmp_path, now=BEFORE) == 1
    assert saved(tmp_path)['usable'] is False


@pytest.mark.parametrize('st', [
    dict(OK, status='partial'), dict(OK, status='failed'), dict(OK, reached=False),
    dict(OK, truncated=True, reached=False), {'status': 'ok', 'pages': 1, 'truncated': False},
])
def test_an_incomplete_read_is_not_usable(tmp_path, st):
    assert run(tmp_path, read=reader(st=st)) == 1
    assert saved(tmp_path)['usable'] is False


def test_a_stopped_summariser_is_not_usable(tmp_path):
    def stopped(items, bodies):
        for it in items:
            it['summary_note'] = '인증 실패 AuthenticationError'
        return 0, len(items)
    assert run(tmp_path, summarize=stopped) == 1
    d = saved(tmp_path)
    assert d['usable'] is False and all(it['news_use'] is False and it['news_skip'] == 'no_summary' for it in d['items'])

    def no_client(items, bodies):
        for it in items:
            it['summary_note'] = '요약 클라이언트 없음 RuntimeError'
        return 0, len(items)
    (tmp_path / 'data' / 'telegram' / f'{S}.json').unlink()
    assert run(tmp_path, summarize=no_client) == 1 and saved(tmp_path)['usable'] is False


def test_one_failed_item_does_not_spoil_the_file(tmp_path):
    def one(items, bodies):
        items[0]['summary_ko'] = SUMMARY
        items[1]['summary_note'] = '분량 벗어남 500자'
        return 1, 1
    assert run(tmp_path, summarize=one) == 0
    d = saved(tmp_path)
    assert d['usable'] is True and [it['news_use'] for it in d['items']] == [True, False]


def test_a_day_with_nothing_is_usable(tmp_path):
    def never(items, bodies):
        assert items == [], 'nothing to summarise'
        return 0, 0
    assert run(tmp_path, read=reader(posts=[POSTS[1]]), summarize=never) == 0
    d = saved(tmp_path)
    assert d['usable'] is True and d['items'] == []


def test_a_usable_file_is_never_rewritten(tmp_path):
    run(tmp_path)
    p = tmp_path / 'data' / 'telegram' / f'{S}.json'
    before = p.read_bytes()

    def boom(*a, **k):
        raise AssertionError('must not read again')
    assert run(tmp_path, read=boom) == 0 and p.read_bytes() == before


def test_a_published_session_is_refused(tmp_path):
    pub = tmp_path / 'data' / 'daily'
    pub.mkdir(parents=True)
    (pub / f'{S}.json').write_text('{}', encoding='utf-8')

    def boom(*a, **k):
        raise AssertionError('must not read')
    assert run(tmp_path, read=boom) == 0 and saved(tmp_path) is None


def test_nothing_is_saved_until_the_end(tmp_path):
    """A run killed while summarising leaves the earlier file exactly as it was."""
    run(tmp_path, now=BEFORE)
    p = tmp_path / 'data' / 'telegram' / f'{S}.json'
    before = p.read_bytes()

    def killed(items, bodies):
        raise KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):
        run(tmp_path, summarize=killed)
    assert p.read_bytes() == before and not (tmp_path / 'data' / 'telegram' / f'{S}.json.tmp').exists()


def test_summaries_carry_only_from_this_sessions_earlier_file(tmp_path):
    run(tmp_path, now=BEFORE)                                   # not usable, summaries written
    other = tmp_path / 'data' / 'telegram' / f'{P}.json'        # another session's file is never read
    other.write_text(json.dumps({'report_date': P, 'usable': True, 'items': [
        {'id': f'{J.JP_CHANNEL}/3', 'kind': 'opinion', 'source': None, 'summary_ko': '다른 날의 요약이다.'}]}), encoding='utf-8')
    asked = []

    def again(items, bodies):
        asked.extend(it['id'] for it in items if not it.get('summary_ko'))
        return 0, 0
    assert run(tmp_path, summarize=again) == 0
    assert asked == [] and all(it['summary_ko'] == SUMMARY for it in saved(tmp_path)['items'])


def test_original_article_makes_a_report_and_a_dead_one_falls_back(tmp_path):
    u = 'https://www.reuters.com/markets/asia/toyota-plant-2026-11-13/'
    posts = [post(1, '로이터) 도요타가 미국 공장을 늘린다' + FILL, '11-13 09:00', [u]),
             post(2, '닛케이) 소니 이미지센서 증설' + FILL, '11-13 09:30', ['https://www.cnbc.com/2026/11/13/sony.html'])]

    def origin(item):
        if 'reuters' in item['source']['url']:
            return '도요타가 미국 공장을 늘린다. ' * 40, '로이터', '2026-11-13T00:00:00+00:00'
        raise IOError('HTTP 403')
    run(tmp_path, read=reader(posts=posts), origin=origin)
    a, b = saved(tmp_path)['items']
    assert a['kind'] == 'report' and a['source']['name'] == '로이터' and a['source']['url'] == u
    assert b['kind'] == 'opinion' and b['source'] == {'name': '니혼게이자이', 'url': None, 'basis': 'credit'}
    assert (tmp_path / 'bodies' / f'{J.JP_CHANNEL}_1.txt').read_text(encoding='utf-8').startswith('도요타가 미국 공장을')


def test_an_old_article_is_dropped(tmp_path):
    posts = [post(1, '도요타 증설' + FILL, '11-13 09:00', ['https://www.cnbc.com/2026/10/20/toyota.html'])]
    run(tmp_path, read=reader(posts=posts), origin=lambda it: ('본문 ' * 200, 'CNBC', None))
    d = saved(tmp_path)
    assert d['items'] == [] and d['stats']['stale_dropped'] == 1


def test_report_already_in_the_daily_news_is_marked(tmp_path):
    u = 'https://www.reuters.com/markets/asia/toyota-plant-2026-11-13/'
    news = tmp_path / 'data' / 'news' / 'daily'
    news.mkdir(parents=True)
    (news / f'{S}.json').write_text(json.dumps({'items': [{'guid': u, 'url': u}]}), encoding='utf-8')
    posts = [post(1, '도요타가 미국 공장을 늘린다' + FILL, '11-13 09:00', [u])]
    run(tmp_path, read=reader(posts=posts), origin=lambda it: ('도요타가 미국 공장을 늘린다. ' * 40, '로이터', None))
    it = saved(tmp_path)['items'][0]
    assert it['news_use'] is False and it['news_skip'] == 'dup_url'


def test_valve_is_counted(tmp_path, monkeypatch):
    monkeypatch.setattr(J, 'JP_VALVE', 2)
    posts = [post(i, f'도요타 실적 {i}' + FILL, '11-13 09:00') for i in range(1, 6)]
    run(tmp_path, read=reader(posts=posts))
    d = saved(tmp_path)
    assert len(d['items']) == 2 and d['stats']['valve_dropped'] == 3


# ── the reader's `reached` bit ───────────────────────────────────────────

NOW = datetime(2026, 11, 9, 0, 0, tzinfo=timezone.utc)


def test_reached_when_the_floor_is_seen():
    _, st = F.read_channel('c', None, NOW - timedelta(hours=1), fake_channel('c', 100, NOW), nosleep, track_reached=True)
    assert st['reached'] is True and st['status'] == 'ok'


def test_a_page_without_a_before_link_is_not_the_floor():
    """The channel's first post and a `before` link the parser no longer recognises look the same
    (no link). Neither is 「read down to the floor」 — only a post below the floor is."""
    _, st = F.read_channel('c', None, NOW - timedelta(days=30), fake_channel('c', 30, NOW), nosleep, track_reached=True)
    assert st['reached'] is False and st['status'] == 'ok'
    pages = fake_channel('c', 500, NOW)
    requoted = pages('https://t.me/s/c').replace('href="/s/c?before=', "href='/s/c?before=")
    assert 'before=' in requoted
    posts, st = F.read_channel('c', None, NOW - timedelta(days=30), lambda url: requoted, nosleep, track_reached=True)
    assert posts and st['reached'] is False and st['status'] == 'ok'


def test_not_reached_at_the_page_cap():
    _, st = F.read_channel('c', None, NOW - timedelta(days=30), fake_channel('c', 500, NOW), nosleep, max_pages=2,
                           track_reached=True)
    assert st['reached'] is False and st['truncated']


def test_not_reached_when_a_page_fails():
    pages = fake_channel('c', 500, NOW)
    calls = []

    def flaky(url):
        calls.append(url)
        if 'before=' in url:
            raise IOError('HTTP 429')
        return pages(url)
    _, st = F.read_channel('c', None, NOW - timedelta(days=30), flaky, nosleep, track_reached=True)
    assert st['reached'] is False and st['status'] == 'partial'


def test_not_reached_when_the_before_link_does_not_move():
    pages = fake_channel('c', 500, NOW)
    first = pages('https://t.me/s/c')
    _, st = F.read_channel('c', None, NOW - timedelta(days=30), lambda url: first, nosleep, track_reached=True)
    assert st['reached'] is False and st['status'] == 'ok'


def test_us_kr_status_has_no_new_key():
    _, st = F.read_channel('c', None, NOW - timedelta(hours=1), fake_channel('c', 100, NOW), nosleep)
    assert set(st) == {'status', 'pages', 'truncated'}


# ── the workflow step ────────────────────────────────────────────────────

def _steps():
    import os
    import re
    here = os.path.dirname(os.path.abspath(__file__))
    text = open(os.path.join(here, '..', '..', '..', '.github', 'workflows', 'collect-japan-daily.yml'), encoding='utf-8').read()
    parts = re.split(r'\n      - (?=name: |uses: )', text)
    return text, {re.match(r'name: (.+)', p).group(1): p for p in parts if p.startswith('name: ')}


def test_workflow_step_cannot_hold_the_core_collection_back():
    text, steps = _steps()
    names = list(steps)
    assert names.index('Collect') < names.index('Fetch Telegram notes') < names.index('Commit data')
    step = steps['Fetch Telegram notes']
    assert 'continue-on-error: true' in step and 'timeout-minutes: 6' in step
    assert 'fetch_telegram_jp.py --session "$S" --prev "$P" --datadir japan/data --bodydir _workspace/telegram_jp' in step
    assert 'ANTHROPIC_FEDERATION_RULE_ID' in step and 'TYPESAFE_API_KEY' not in step
    assert 'if: always()' in steps['Commit data']
    # serialised runs: two collectors never write the same session file at once
    assert "group: collect-japan-daily" in text and 'cancel-in-progress: false' in text


def test_workflow_stages_only_the_collectors_json():
    _, steps = _steps()
    lines = [ln.strip() for ln in steps['Commit data'].splitlines()]
    assert 'git add japan/data/telegram/*.json 2>/dev/null || true' in lines        # its own line
    assert not any('telegram' in ln and 'japan/data/daily' in ln for ln in lines)
    assert not any('published' in ln and ln.startswith('git add') for ln in lines)
