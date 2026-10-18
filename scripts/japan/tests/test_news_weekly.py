"""일본 뉴스 — 수집기(가짜 네트워크), 주간 후보, 「이번 주 뉴스」 게이트(2026-10-18)."""
import json
from pathlib import Path

import build_japan_weekly as B
import fetch_japan_news as F
from japan import gate as G
from japan import render as R
from japan.tests.test_gate import BOX, _diag
from japan.tests.test_news import ID1, ID2, ID3, _art, _detail, _list_page
from us.news_expand import caption, expand

ROOT = Path(__file__).resolve().parents[3]


# ── 수집기 ────────────────────────────────────────────────────────────
def _fake_fetch(pages, details=None):
    calls = []

    def fetch(url, ctx):
        calls.append(url)
        if url in (details or {}):
            return details[url]
        return pages.get(url, _list_page([]))
    fetch.calls = calls
    return fetch


def test_harvest_stops_at_the_oldest_day_and_marks_failures():
    url = lambda feed, p: F.N.LIST_URL.format(feed=feed, page=p)  # noqa: E731
    pages = {url('bus_all', 1): _list_page([_art(ID1, '日銀、利上げ継続', created='10/16')]),
             url('bus_all', 2): _list_page([_art(ID2, '長期金利が上昇', created='10/15')]),
             url('bus_all', 3): _list_page([_art(ID3, 'never read', created='10/14')])}
    fetch = _fake_fetch(pages)
    rows, notes, reach = F.harvest('2026-10-16', '2026-10-17', None, fetch=fetch, gap=0)
    assert [r['guid'] for r in rows] == [ID1, ID2] and F.complete_for('2026-10-16', reach)
    assert url('bus_all', 3) not in fetch.calls

    def broken(u, ctx):
        raise OSError('down')
    _, notes, reach = F.harvest('2026-10-16', '2026-10-17', None, fetch=broken, gap=0)
    assert not F.complete_for('2026-10-16', reach) and notes


def test_pending_dates_skips_frozen_complete_days(tmp_path):
    (tmp_path / 'news').mkdir()
    def write(day, complete):
        (tmp_path / 'news' / f'{day}.json').write_text(json.dumps(
            {'complete': complete, 'items': [{'summary_ko': '요약', 'body_chars': 500}]}))
    write('2026-10-16', True)
    write('2026-10-15', False)          # 목록 하나가 죽은 날 — 다시 받는다
    assert F.pending_dates(str(tmp_path), '2026-10-17') == \
        ['2026-10-12', '2026-10-13', '2026-10-14', '2026-10-15']
    assert '2026-10-16' in F.pending_dates(str(tmp_path), '2026-10-17', refresh=True)


def test_collect_day_end_to_end(tmp_path):
    rows = [dict(r, created='10/16') for r in F.N.parse_list(_list_page([
        _art(ID1, '日銀の植田総裁、利上げ継続を表明'),
        _art(ID2, '日銀の植田総裁、利上げ継続を表明', media='LIMO'),        # 허용 밖 매체
        _art(ID3, '日銀、物価見通し', paid=True)]), 'bus_all')]
    fetch = _fake_fetch({}, {f'https://finance.yahoo.co.jp/news/detail/{ID1}': _detail()})
    seen = {}

    def summarize(items, bodydir, system=None):
        for it in items:
            it['summary_ko'] = '요약이다.'
        seen['system'] = system
        return len(items)
    p = F.collect_day('2026-10-16', rows, [], '2026-10-17', str(tmp_path / 'b'), None, True, [],
                      fetch=fetch, summarize=summarize, datadir=str(tmp_path))
    assert [it['guid'] for it in p['items']] == [ID1]
    it = p['items'][0]
    assert it['category'] == 'macro' and it['published'].startswith('2026-10-16')
    assert it['summary_ko'] and seen['system'] == F.SYSTEM
    assert p['dropped'] == {'매체 LIMO': 1, '유료': 1} and p['complete']
    saved = json.loads((tmp_path / 'news' / '2026-10-16.json').read_text())
    assert saved['items'][0]['summary_ko'] == '요약이다.'
    assert F.done(str(tmp_path / 'news' / '2026-10-16.json'))


# ── 주간 후보 ─────────────────────────────────────────────────────────
def _write_day(base, day, items):
    base.mkdir(parents=True, exist_ok=True)
    (base / f'{day}.json').write_text(json.dumps({'report_date': day, 'items': items}, ensure_ascii=False))


def test_digest_rows_use_the_article_time_and_need_a_summary(tmp_path):
    base = tmp_path / 'jn'
    _write_day(base, '2026-10-16', [
        {'guid': ID1, 'title': '日銀', 'source': 'ロイター', 'category': 'macro',
         'published': '2026-10-16T23:00:00+09:00', 'summary_ko': '요약'},
        {'guid': ID2, 'title': 'x', 'source': 'ロイター', 'category': 'macro',
         'published': '2026-10-16T23:00:00+09:00'},                          # 요약 없음
        {'guid': ID3, 'title': 'y', 'source': 'ロイター', 'category': 'macro',
         'published': '2026-10-09T23:00:00+09:00', 'summary_ko': '요약'}])   # 지난주 기사
    got = B.digest_rows('2026-W42', str(base))
    assert [r['guid'] for r in got] == [ID1] and got[0]['digest'] is True


def test_us_kr_japan_rows_stay_evidence_only(tmp_path):
    us = tmp_path / 'us'
    _write_day(us, '2026-10-13', [{'guid': 'u1', 'region': 'japan', 'title': 't', 'category': 'global',
                                    'summary_ko': '요약'}])
    got = B.week_news('2026-W42', dirs=(str(us),), japan_dir=str(tmp_path / 'none'))
    assert got and 'digest' not in got[0] and 'category' not in got[0]


# ── 게이트 ────────────────────────────────────────────────────────────
SUMMARY = ('일본은행 총재가 16일 기조 물가 상승률이 2% 목표에 상당히 가까워졌다고 말했다. 그는 29일 시작하는 '
           '금융정책결정회의에서 목표 도달 여부를 정책위원들과 충분히 논의해 결론을 내겠다고 밝혔다. 시장은 '
           '이 발언을 추가 인상 쪽으로 읽었고 단기 금리 선물에 반영된 인상 확률도 높아졌다. 다만 총재는 경제가 '
           '전망대로 움직이고 있다고만 말했을 뿐 인상 시점을 직접 언급하지는 않았다. 엔화는 발언 뒤 소폭 강세를 '
           '보였고 은행주가 올랐다. 총재는 임금 인상이 서비스 물가로 번지는 흐름을 확인하고 있다고 덧붙였고, '
           '해외 경제의 하방 위험도 회의에서 함께 점검하겠다고 말했다.')


def _digest(n=1, cat='macro', summary=SUMMARY, titles=None):
    out = []
    for i in range(n):
        g = f'{i:040x}'
        out.append({'date': '2026-10-16', 'guid': g, 'title': (titles or [f'日銀総裁発言{i}号'] * n)[i],
                    'source': 'ロイター', 'url': f'https://finance.yahoo.co.jp/news/detail/{g}',
                    'published': '2026-10-16T21:50:32+09:00', 'category': cat,
                    'summary_ko': summary, 'digest': True})
    return out


def _html(news=None, extra_outside=''):
    base = {s: '해설이다.' for s in R.SECTIONS}
    base['scenario'] = '인상 지속 신호가 둘, 인상 중단 신호가 하나다.'
    base['next'] = '단칸이 가를 것이다.' + extra_outside
    base['yen'] = '2026-09-15 기준 엔 선물 포지션은 엔 매수 쪽이다.'
    secs = ''.join(f'<section data-section="{s}"><h2>{s}</h2><p>{base[s]}</p>'
                   f'{BOX if s in G.COMMENTARY_SECTIONS else ""}</section>' for s in R.SECTIONS)
    if news is not None:
        secs += f'<section data-section="news"><h2>{R.NEWS_TITLE}</h2>{news}</section>'
    return f'<body data-register="da"><section class="card headline-card"><h1>제목</h1></section>{secs}</body>'


def _blocks(rows):
    body = ''.join(f'<!--NEWS:{r["guid"]}|일본은행 총재 발언-->' for r in rows)
    out, errs = expand(body, {'items': rows})
    assert not errs
    return out


def _check(html, digest):
    texts = [r['summary_ko'] for r in digest] + [G.title_source(r['title']) for r in digest]
    return G.check(html, _diag(), texts, digest)


def test_expanded_news_section_passes():
    d = _digest()
    assert _check(_html(_blocks(d)), d) == []


def test_news_section_is_required_when_the_week_has_candidates():
    out = _check(_html(), _digest())
    assert any('news' in v for v in out)


def test_old_weeks_without_candidates_are_exempt():
    assert _check(_html(), []) == []


def test_published_w40_w41_still_pass_with_their_committed_data():
    for key in ('2026-W40', '2026-W41'):
        html = (ROOT / f'japan/posts/{key}.html').read_text(encoding='utf-8')
        diag = json.loads((ROOT / f'japan/data/{key}.json').read_text(encoding='utf-8'))
        news = json.loads((ROOT / f'japan/data/{key}.news.json').read_text(encoding='utf-8'))
        texts = [n.get('summary_ko') or '' for n in news]
        assert G.check(html, diag, texts, [n for n in news if n.get('digest')]) == [], key


def test_a_news_block_outside_the_news_section_is_blocked():
    d = _digest()
    out = _check(_html(_blocks(d), extra_outside=_blocks(d)), d)
    assert any('절 밖' in v for v in out)


def test_wrong_title_or_misplaced_section_is_blocked():
    d = _digest()
    html = _html(_blocks(d)).replace(f'<h2>{R.NEWS_TITLE}</h2>', '<h2>뉴스</h2>')
    assert any('제목' in v for v in _check(html, d))
    moved = _html(_blocks(d))
    sec = moved[moved.index('<section data-section="news"'):moved.index('</body>')]
    moved = moved.replace(sec, '').replace('<section data-section="core"', sec + '<section data-section="core"', 1)
    assert any('순서' in v for v in _check(moved, d))


def test_more_than_three_per_category_is_blocked():
    d = _digest(4, titles=['日銀総裁発言', '財務相の為替発言', '長期金利の上昇', '国債入札の結果'])
    assert any('갈래당' in v for v in _check(_html(_blocks(d)), d))


def test_same_event_twice_is_blocked():
    d = _digest(2, titles=['日銀総裁、利上げ継続を表明', '日銀総裁、利上げ継続を表明す'])
    assert any('같은 사건' in v for v in _check(_html(_blocks(d)), d))


def test_evidence_rows_cannot_be_published_in_the_news_section():
    d = _digest()
    evidence = [dict(d[0], digest=False)]
    html = _html(_blocks(d))
    out = G.check(html, _diag(), [SUMMARY], [])
    assert any('그날 수집분에 없다' in v or '절 밖' in v or '없다' in v for v in out) and evidence


def test_news_summary_flow_words_are_not_checked_against_the_weekly_flows():
    s = SUMMARY + ' 재무성 집계로 거주자는 지난주 해외채권을 순매수했다.'
    d = _digest(summary=s)
    assert not any('해외채권' in v for v in _check(_html(_blocks(d)), d))


def test_jo_amounts_in_a_summary_are_allowed():
    s = SUMMARY + ' 정부는 경제 대책 규모를 2조 엔으로 잡았다.'
    d = _digest(summary=s)
    assert not any('수치' in v for v in _check(_html(_blocks(d)), d))


def test_caption_uses_korean_media_names():
    assert caption({'source': 'ロイター', 'published': '2026-10-16T21:50:32+09:00', 'url': 'x'}) == '로이터 · 10월 16일'
    assert caption({'source': '時事通信', 'published': '2026-10-16T21:50:32+09:00', 'url': 'x'}) == '지지통신 · 10월 16일'


def test_validate_body_accepts_the_optional_news_section_once():
    body = _html('<!--NEWS:x|제목-->').split('<body data-register="da">')[1].replace('</body>', '')
    body = body.replace('<p>해설이다.</p>', '<p>해설이다.</p>')
    for ph in ('core', 'curve', 'yen', 'flows', 'equity', 'signals', 'next'):
        sec = {'signals': 'scenario'}.get(ph, ph)
        body = body.replace(f'<section data-section="{sec}"><h2>{sec}</h2>',
                            f'<section data-section="{sec}"><h2>{sec}</h2><!--T:{ph}-->', 1)
    assert R.validate_body(body) == []
    twice = body + '<section data-section="news"><h2>이번 주 뉴스</h2></section>'
    assert any('2번' in e for e in R.validate_body(twice))


def test_page_cap_and_official_failures_leave_the_day_incomplete():
    url = lambda feed, p: F.N.LIST_URL.format(feed=feed, page=p)  # noqa: E731
    pages = {url(f, 1): _list_page([_art(ID1, '日銀、利上げ継続', created='10/16')]) for f in F.N.FEEDS}
    _, notes, reach = F.harvest('2026-10-12', '2026-10-17', None, fetch=_fake_fetch(pages),
                                gap=0, max_pages=1)
    assert not F.complete_for('2026-10-12', reach) and any('닿지 못했다' in n for n in notes)

    def down(u, ctx):
        raise OSError('503')
    rows, notes, ok = F.harvest_official(None, 2026, fetch=down)
    assert rows == [] and not ok and notes


def test_today_or_later_is_refused(capsys):
    assert F.main(['--date', '2026-10-17', '--today', '2026-10-17', '--datadir', '/nonexistent']) == 2


def test_a_missing_boj_year_page_is_not_a_failure():
    import urllib.error

    def fetch(u, ctx):
        if 'boj.or.jp' in u:
            raise urllib.error.HTTPError(u, 404, 'nf', {}, None)
        return '<?xml version="1.0"?><rss><channel><item><title>金利の見通し</title>' \
               '<link>https://www.nli-research.co.jp/report/detail/id=1</link>' \
               '<pubDate>Fri, 16 Oct 2026 01:00:00 GMT</pubDate></item></channel></rss>'
    rows, notes, ok = F.harvest_official(None, 2027, fetch=fetch, month=1)
    assert ok and [r['category'] for r in rows] == ['insight']
    assert rows[0]['published'] == '2026-10-16T10:00:00+09:00'


def test_attribute_spelling_does_not_dodge_the_counts():
    d = _digest(4, titles=['日銀総裁発言', '財務相の為替発言', '長期金利の上昇', '国債入札の結果'])
    html = _html(_blocks(d))
    for g in [r['guid'] for r in d]:
        html = html.replace(f'data-news="{g}"', f"data-news='{g}'")
    assert any('갈래당' in v for v in _check(html, d))


def test_odd_spelling_outside_the_section_is_still_outside():
    d = _digest()
    stray = _blocks(d).replace('class="news-item" data-news=', 'class="item" DATA-NEWS=')
    assert any('절 밖' in v for v in _check(_html(_blocks(d), extra_outside=stray), d))


def test_hidden_news_title_does_not_count():
    d = _digest()
    html = _html(_blocks(d)).replace(f'<h2>{R.NEWS_TITLE}</h2>', f'<h2 hidden>{R.NEWS_TITLE}</h2>')
    assert any('제목' in v for v in _check(html, d))


def test_dates_in_japanese_titles_are_not_allowed_figures():
    d = _digest(titles=['日銀総裁、１０月２７日に講演'])
    html = _html(_blocks(d)).replace('단칸이 가를 것이다.', '단칸이 가를 것이다. 정책금리는 27%다.')
    assert any('27' in v for v in _check(html, d))


def test_a_block_cannot_claim_the_news_section_on_itself():
    d = _digest()
    stray = _blocks(d).replace('class="news-item"', 'class="news-item" data-section="news"')
    assert any('절 밖' in v for v in _check(_html(_blocks(d), extra_outside=stray), d))


def test_a_second_news_section_in_other_quotes_is_blocked():
    d = _digest()
    html = _html(_blocks(d)).replace('</body>', "<section data-section='news'><h2>이번 주 뉴스</h2></section></body>")
    assert any('news' in v for v in _check(html, d))


def test_title_hidden_in_a_child_does_not_count():
    d = _digest()
    html = _html(_blocks(d)).replace(f'<h2>{R.NEWS_TITLE}</h2>', f'<h2><span hidden>{R.NEWS_TITLE}</span></h2>')
    assert any('제목' in v for v in _check(html, d))


def test_date_ranges_in_japanese_titles_are_masked():
    assert '27' not in G.title_source('日銀会合、１０月２７～２８日に開催')
    assert '28' not in G.title_source('日銀会合、10月27〜28日に開催')


def test_boj_404_is_tolerated_only_in_january():
    import urllib.error

    def fetch(u, ctx):
        if 'boj.or.jp' in u:
            raise urllib.error.HTTPError(u, 404, 'nf', {}, None)
        return '<?xml version="1.0"?><rss><channel></channel></rss>'
    assert F.harvest_official(None, 2027, fetch=fetch, month=1)[2]
    assert not F.harvest_official(None, 2026, fetch=fetch, month=10)[2]


def test_completeness_is_judged_per_day():
    url = lambda feed, p: F.N.LIST_URL.format(feed=feed, page=p)  # noqa: E731
    pages = {url(f, 1): _list_page([_art(ID1, '日銀、利上げ継続', created='10/14'),
                                    _art(ID2, '長期金利が上昇', created='10/13')]) for f in F.N.FEEDS}
    pages[url('market', 1)] = _list_page([_art(ID3, '日経平均が続落', created='10/15'),
                                          _art(ID1, '日銀、利上げ継続', created='10/14')])  # 10/14 앞에 못 닿음
    rows, notes, reach = F.harvest('2026-10-12', '2026-10-17', None, fetch=_fake_fetch(pages),
                                   gap=0, max_pages=1)
    assert F.complete_for('2026-10-15', reach) and not F.complete_for('2026-10-14', reach)
    assert not F.complete_for('2026-10-12', reach)


def test_a_feed_that_ran_out_of_pages_counts_as_read_to_the_end():
    url = lambda feed, p: F.N.LIST_URL.format(feed=feed, page=p)  # noqa: E731
    pages = {url(f, 1): _list_page([_art(ID1, '日銀、利上げ継続', created='10/14')]) for f in F.N.FEEDS}
    _, _, reach = F.harvest('2026-10-12', '2026-10-17', None, fetch=_fake_fetch(pages), gap=0, max_pages=5)
    assert F.complete_for('2026-10-12', reach)          # 2쪽이 0건 = 목록 끝


def test_a_failed_feed_leaves_every_day_incomplete():
    def broken(u, ctx):
        raise OSError('down')
    _, _, reach = F.harvest('2026-10-12', '2026-10-17', None, fetch=broken, gap=0)
    assert not F.complete_for('2026-10-16', reach)


def test_digest_rows_skip_non_korean_summaries(tmp_path):
    base = tmp_path / 'jn'
    _write_day(base, '2026-10-16', [
        {'guid': ID1, 'title': '日銀', 'source': 'ロイター', 'category': 'macro',
         'published': '2026-10-16T23:00:00+09:00', 'summary_ko': '日銀の総裁は述べた。' * 20}])
    assert B.digest_rows('2026-W42', str(base)) == []


def test_undated_rows_leave_the_feed_unread():
    url = lambda feed, p: F.N.LIST_URL.format(feed=feed, page=p)  # noqa: E731
    pages = {url(f, 1): _list_page([_art(ID1, '日銀', created='10/14')]) for f in F.N.FEEDS}
    pages[url('bus_all', 1)] = _list_page([_art(ID2, '日銀', created='昨日'), _art(ID1, '日銀', created='10/14')])
    _, notes, reach = F.harvest('2026-10-15', '2026-10-17', None, fetch=_fake_fetch(pages), gap=0)
    assert not F.complete_for('2026-10-16', reach) and any('날짜' in n for n in notes)
