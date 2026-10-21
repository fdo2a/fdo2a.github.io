"""쟁점 분석 2단계(KR) — 본문 추출·통신사 탐지·발행사 다양성·robots·레지스트리·러너 계획."""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
sys.path.insert(0, ROOT)

import collect_contested_kr as K  # noqa: E402
import json  # noqa: E402

LONG = ('정부가 내놓은 주택 공급 대책을 두고 시장의 평가가 엇갈리고 있다. ' * 12).strip()


def test_body_from_itemprop_with_br():
    html = ('<html><head><title>공급 대책 평가 엇갈려</title></head><body>'
            '<div class="ad"><p>광고 문구가 길게 들어 있는 문단이다 광고 광고 광고 광고 광고</p></div>'
            f'<div itemprop="articleBody">[서울=뉴시스] 홍길동 기자 = {LONG}<br><br>'
            '<div class="photo"><figure><img src="x"><figcaption>사진 설명</figcaption></figure></div>'
            f'두 번째 문단이다. {LONG}<br>'
            '<script>var x = "스크립트";</script>'
            '홍길동 기자 hong@newsis.com<br>ⓒ 뉴시스, 무단전재 및 재배포 금지</div>'
            '<p>관련 기사 목록이 길게 이어지는 문단이다 관련 관련 관련 관련</p></body></html>')
    body = K.extract_body(html)
    assert body.startswith('[서울=뉴시스]')
    assert '두 번째 문단이다' in body
    assert '스크립트' not in body and '사진 설명' not in body
    assert '무단전재' not in body and 'hong@newsis.com' not in body
    assert '관련 기사 목록' not in body and '광고 문구' not in body


def test_body_from_json_ld_and_nested_divs():
    import json
    ld = json.dumps({'@type': 'NewsArticle', 'articleBody': LONG}, ensure_ascii=False)
    html = f'<script type="application/ld+json">{ld}</script><p>짧다</p>'
    assert K.extract_body(html) == LONG
    other = json.dumps({'@type': 'WebPage', 'articleBody': LONG}, ensure_ascii=False)
    assert K.extract_body(f'<script type="application/ld+json">{other}</script>') == ''
    nested = (f'<div itemprop="articleBody"><div class="inner">{LONG}</div>'
              f'<div>{LONG}</div></div><div>밖의 글이 길게 들어 있는 문단이다 {LONG}</div>')
    body = K.extract_body(nested)
    assert body.count('주택 공급 대책') == 24 and '밖의 글' not in body


def test_structured_body_wins_over_longer_paragraphs():
    import json
    ld = json.dumps({'@type': 'NewsArticle', 'articleBody': LONG}, ensure_ascii=False)
    noise = ''.join(f'<p>관련 기사와 댓글이 길게 이어지는 문단이다 {i} ' + '잡음 ' * 30 + '</p>' for i in range(10))
    assert K.extract_body(f'<script type="application/ld+json">{ld}</script>{noise}') == LONG
    short = f'<div itemprop="articleBody">속보 한 줄이다.</div>{noise}'
    assert K.extract_body(short) == ''                    # 상자가 있으면 짧아도 <p> 로 넘어가지 않는다


def test_body_falls_back_to_paragraphs_and_floor_is_300():
    html = ''.join(f'<p>{LONG[:150]} {i}</p>' for i in range(4))
    assert len(K.extract_body(html)) >= 300
    assert K.extract_body('<p>' + '가' * 120 + '</p>' * 2) == ''
    assert K.BODY_MIN == 300


def test_wire_detection_korean():
    assert K.wire_of('(서울=연합뉴스) 김철수 기자 = 코스피가') == '연합뉴스'
    assert K.wire_of('[세종=뉴시스]이영희 기자 = 정부가') == '뉴시스'
    assert K.wire_of('(서울=뉴스1) 박기자 기자 = ') == '뉴스1'
    assert K.wire_of('[이데일리 김기자] 코스피가 연합뉴스 보도에') is None
    # 앞머리에만 있어야 전재다 — 본문 뒤쪽 인용은 아니다
    assert K.wire_of('코스피가 ' * 100 + '(서울=연합뉴스)') is None


def test_outlet_registry_maps_hosts_to_publishers():
    assert K.outlet_of('https://biz.chosun.com/stock/1') == ('chosun', '조선일보')
    assert K.outlet_of('https://www.chosun.com/economy/2026/10/20/X/') == ('chosun', '조선일보')
    assert K.outlet_of('https://www.yna.co.kr/view/AKR1') == ('yna', '연합뉴스')
    assert K.outlet_of('https://n.news.naver.com/mnews/article/001/1') == (None, None)
    assert K.outlet_of('https://evil.yna.co.kr.attacker.com/x') == (None, None)
    assert K.outlet_of('https://www.hani.co.kr/arti/1.html') == (None, None)   # Claude-User 금지


# ── KR 시장 관측치 레지스트리 ─────────────────────────────────────────────
from common import contested as C  # noqa: E402

KR_FILES = {
    'kr_market_data.json': {'report_date': '2026-10-20', 'complete': True, 'flows_provisional': True,
                            'indices': {'KOSPI': {'close': 5552.74, 'change_pct': -3.73},
                                        'KOSDAQ': {'close': 781.97, 'change_pct': -3.33}}},
    'kr_econ.json': {'series': {
        '국고채 3년': {'value': 3.84, 'date': '2026-10-20', 'bp': -3.7},
        '국고채 10년': {'value': 4.176, 'date': '2026-10-20', 'bp': -2.9},
        'CD 91일': {'value': 3.26, 'date': '2026-10-20', 'bp': 1.0},
        '회사채 AA- 3년': {'value': 4.534, 'date': '2026-10-20', 'bp': -2.6},
        '한국은행 기준금리': {'value': 3.0, 'date': '2026-09', 'bp': 0.0}}},
    'kr_flows.json': {'KOSPI': {'rows': [
        {'date': '2026-10-20', 'individual': 8475, 'foreign': -4884, 'institution': -9901},
        {'date': '2026-10-19', 'individual': -11767, 'foreign': 947, 'institution': 5302}]}},
    'kr_session.json': {'report_date': '2026-10-20',
                        'us_prev': {'as_of': '2026-10-19', 'rows': {'S&P 500': 0.41, 'Nasdaq': 1.11}},
                        'usdkrw_intraday': {'close': 1327.58, 'last_t': '15:30'}},
}


def test_kr_registry_fills_values_and_dates():
    reg = C.market_registry_kr(KR_FILES)
    assert reg['indices.KOSPI.pct']['value'] == -3.73 and reg['indices.KOSPI.pct']['as_of'] == '2026-10-20'
    assert reg['indices.KOSDAQ.last']['value'] == 781.97
    assert reg['rates.KTB3Y.level'] == {'indicator_ko': '국고채 3년 금리', 'entity': 'KTB3Y', 'value': 3.84,
                                        'unit': '%', 'as_of': '2026-10-20'}
    assert reg['rates.KTB10Y.bp']['unit'] == 'bp'
    assert 'rates.BOK.level' not in reg              # 월 단위 기준일은 날짜가 아니다
    assert reg['flows.KOSPI.foreign']['value'] == -4884 and reg['flows.KOSPI.foreign']['unit'] == '억원'
    assert '잠정' in reg['flows.KOSPI.foreign']['indicator_ko']          # 확정치처럼 보이면 안 된다(K03)
    assert reg['fx.USDKRW.close']['as_of'] == '2026-10-20'
    assert '15:30' in reg['fx.USDKRW.close']['indicator_ko']
    assert reg['us_prev.Nasdaq.pct']['as_of'] == '2026-10-19'
    assert all(k.isascii() for k in reg)
    for v in reg.values():
        assert set(v) == {'indicator_ko', 'entity', 'value', 'unit', 'as_of'}


def test_kr_registry_drops_stale_and_future_values():
    import copy
    f = copy.deepcopy(KR_FILES)
    f['kr_flows.json']['KOSPI']['rows'].pop(0)                    # 최신 행이 전 거래일 — 오늘 수급이 아니다
    f['kr_session.json']['report_date'] = '2026-10-19'             # 세션 수집 실패로 남은 어제 파일
    f['kr_econ.json']['series']['국고채 3년']['date'] = '2026-10-21'  # 기준일 뒤 값
    reg = C.market_registry_kr(f)
    assert not any(k.startswith('flows.') for k in reg)
    assert 'fx.USDKRW.close' not in reg and 'us_prev.Nasdaq.pct' not in reg
    assert 'rates.KTB3Y.level' not in reg and 'rates.KTB10Y.level' in reg
    f2 = copy.deepcopy(KR_FILES)
    f2['kr_market_data.json']['flows_provisional'] = False
    assert '잠정' not in C.market_registry_kr(f2)['flows.KOSPI.foreign']['indicator_ko']
    del f2['kr_session.json']['usdkrw_intraday']['last_t']
    assert 'fx.USDKRW.close' not in C.market_registry_kr(f2)


def test_kr_registry_tolerates_missing_and_broken_files():
    assert C.market_registry_kr({}) == {}
    reg = C.market_registry_kr({'kr_market_data.json': {'report_date': '2026-10-20', 'indices': None},
                                'kr_econ.json': {'series': {'국고채 3년': 'x'}},
                                'kr_flows.json': {'KOSPI': {'rows': ['x']}}})
    assert reg == {}


def test_markets_open_kr_and_config():
    assert C.MARKETS == ('us', 'kr')
    assert C.MARKET_CFG['kr']['page'].format(d='2026-10-20') == 'kr/posts/2026-10-20.html'
    assert C.MARKET_CFG['us']['page'].format(d='2026-10-20') == 'news/2026-10-20.html'
    assert C.MARKET_CFG['kr']['result'].format(d='2026-10-20') == 'data/contested/kr/2026-10-20.json'
    assert C.MARKET_CFG['kr']['shell'] == 'kr' and C.MARKET_CFG['us']['shell'] == 'news'


# ── 수집기: 검색 쪽넘김·묶음·robots·리다이렉트·본문 ─────────────────────────
from datetime import datetime, timedelta, timezone  # noqa: E402

KST = timezone(timedelta(hours=9))
CUT = K.cutoff_of('2026-10-20')


def _row(title, url, hours_before):
    return {'title': title, 'url': url, 'published': CUT - timedelta(hours=hours_before)}


def test_cutoff_is_fixed_per_date():
    assert CUT == datetime(2026, 10, 20, 20, 0, tzinfo=KST)
    assert K.cutoff_of('2026-10-20') == CUT          # 실행 시각과 무관 — 재시도해도 같다(K04)


def test_window_search_skips_after_cutoff_and_detects_truncation():
    pages = {1: ([_row('늦은 기사', 'https://www.yna.co.kr/view/A0', -2)] +
                 [_row(f'기사 {i}', f'https://www.yna.co.kr/view/A{i}', i / 10) for i in range(1, 100)], 5000),
             101: ([_row(f'기사 b{i}', f'https://www.yna.co.kr/view/B{i}', 10 + i / 10) for i in range(100)], 5000)}
    got, reached = K.window_search('q', CUT - timedelta(hours=24), CUT, 2, lambda q, s: pages[s])
    assert all(r['published'] <= CUT for r in got) and len(got) == 199
    assert reached is False                        # 쪽 상한에 먼저 닿았다 — 창을 다 못 봤다(K09)
    pages[101] = ([_row('옛 기사', 'https://www.yna.co.kr/view/C', 30)], 5000)
    got, reached = K.window_search('q', CUT - timedelta(hours=24), CUT, 2, lambda q, s: pages[s])
    assert reached is True and len(got) == 99


def test_cluster_groups_same_event_and_ranks_debate_over_market_wrap():
    rows = [_row('코스피 3.7% 급락 마감…외국인 기관 매도', 'https://www.yna.co.kr/view/1', 3),
            _row('코스피 3.7% 급락 마감 외국인 기관 동반 매도', 'https://www.mk.co.kr/news/1', 3),
            _row('외국인 기관 매도에 코스피 3.7% 급락 마감', 'https://www.sedaily.com/article/1', 3),
            _row('원·달러 환율 연저점 경신…어디까지 떨어질까', 'https://www.hankyung.com/article/1', 3),
            _row('원·달러 환율 연저점 경신 하락 전망 엇갈려', 'https://www.edaily.co.kr/News/1', 3),
            _row('원·달러 환율 연저점 경신에 수출기업 우려', 'https://www.fnnews.com/news/1', 3)]
    groups = K.cluster(rows)
    assert [len(g) for g in groups] == [3, 3]
    assert '환율' in groups[0][0]['title']         # 시황 묶음보다 논쟁 신호가 앞선다
    assert K.member('원·달러 환율 연저점 경신 1320원대', [K.toks(r['title']) for r in groups[0]])
    assert not K.member('원·달러 환율 1320원대 마감', [K.toks(r['title']) for r in groups[0]])


class _Get:
    def __init__(self, pages):
        self.pages, self.calls = pages, []

    def __call__(self, url):
        self.calls.append(url)
        v = self.pages.get(url)
        if v is None:
            return 404, None, ''
        return v


def test_robots_policy_and_redirect_rechecks():
    robots_txt = 'User-agent: *\nDisallow: /private/\n\nUser-agent: Claude-User\nDisallow: /claude-no/\n'
    get = _Get({'https://www.yna.co.kr/robots.txt': (200, None, robots_txt),
                'https://www.yna.co.kr/view/1': (301, 'https://n.news.naver.com/mnews/article/001/1', ''),
                'https://www.yna.co.kr/view/2': (302, '/private/x', ''),
                'https://www.yna.co.kr/view/3': (200, None, '<p>ok</p>'),
                'https://www.mk.co.kr/robots.txt': (503, None, '')})
    rb = K.Robots(lambda u: (lambda c, _l, t: (c, t))(*get(u)))
    import pytest
    with pytest.raises(K.Blocked):
        K.fetch_page('https://www.yna.co.kr/view/1', rb, get=get)   # 네이버로 넘어가기 전에 멈춘다
    assert not any('naver.com' in u for u in get.calls)
    with pytest.raises(K.Blocked):
        K.fetch_page('https://www.yna.co.kr/view/2', rb, get=get)   # 리다이렉트 목적지가 robots 금지
    with pytest.raises(K.Blocked):
        rb.check('https://www.yna.co.kr/claude-no/1')             # Claude-User 명시 금지도 뺀다(보수 정책)
    assert K.fetch_page('https://www.yna.co.kr/view/3', rb, get=get)[1] == '<p>ok</p>'
    with pytest.raises(K.Transient):
        rb.check('https://www.mk.co.kr/news/1')                  # robots 조회 실패 = 일시 실패
    with pytest.raises(K.Blocked):
        rb.check('https://www.hani.co.kr/arti/1.html')           # 허용 목록 밖


def _article(title, wire='', pub='2026-10-20T15:00:00+09:00'):
    body = (f'{wire}{title}에 대한 기사 본문이다. ' + '정부와 시장의 판단이 엇갈리고 있다. ' * 20)
    return (f'<html><head><title>{title} - 매체</title><meta property="og:title" content="{title}">'
            f'<meta property="article:published_time" content="{pub}"></head>'
            f'<body><div itemprop="articleBody">{body}</div></body></html>')


def test_fetch_bodies_limits_publisher_groups_wire_and_marks_transient():
    T = '원·달러 환율 연저점 경신 전망 엇갈려'
    pages = {f'https://{h}/robots.txt': (404, None, '') for h in
             ('www.yna.co.kr', 'www.hankyung.com', 'biz.chosun.com', 'www.chosun.com', 'www.mk.co.kr')}
    rows = []
    for i, (host, wire) in enumerate([('www.chosun.com', ''), ('biz.chosun.com', ''), ('www.chosun.com', ''),
                                      ('www.yna.co.kr', '(서울=연합뉴스) 김기자 기자 = '),
                                      ('www.hankyung.com', '(서울=연합뉴스) 이기자 기자 = ')]):
        url = f'https://{host}/a/{i}'
        pages[url] = (200, None, _article(T + f' {i}', wire))
        rows.append({'title': T, 'url': url, 'published': None})
    rows.append({'title': T, 'url': 'https://www.mk.co.kr/news/9', 'published': None})
    pages['https://www.mk.co.kr/news/9'] = (500, None, '')
    get = _Get(pages)
    rb = K.Robots(lambda u: (lambda c, _l, t: (c, t))(*get(u)))
    status = []
    arts = K.fetch_bodies(rows, rb, CUT, K.Run(900), get=get, status=status)
    assert [a['source'] for a in arts].count('조선일보') == 2         # 발행사 기준 한도 — 호스트가 달라도
    groups = {a['source']: a['origin_group'] for a in arts}
    assert groups['연합뉴스'] == groups['한국경제'] == 'wire:연합뉴스'   # 연합 전재는 한 출처
    assert 'fail' in status                                        # 5xx 는 일시 실패로 남는다(K08)
    assert all(a['title'].startswith(T) for a in arts)               # 제목은 언론사 면에서 읽은 것


def _files(tmp_path):
    import json as _json
    d = tmp_path / 'data'
    d.mkdir()
    for name, obj in KR_FILES.items():
        (d / name).write_text(_json.dumps(obj, ensure_ascii=False))
    return str(d)


NOW = datetime(2026, 10, 20, 21, 0, tzinfo=KST)


def _rss(items):
    body = ''.join(f'<item><title><![CDATA[{t}]]></title><link>{u}</link><pubDate>{d}</pubDate></item>'
                   for t, u, d in items)
    return f'<rss><channel>{body}</channel></rss>'


def test_collect_bundle_shape_and_empty_search(tmp_path, monkeypatch):
    monkeypatch.setattr(K, 'NAVER_STATE', str(tmp_path / 'naver.json'))
    empty = K.collect('2026-10-20', _files(tmp_path), deadline=60, now=NOW,
                      page_fn=lambda q, s: ([], 0), get=_Get({}))
    assert empty['status'] == 'none' and empty['reason'] == 'no_candidate' and empty['discovery'] == 'ok'
    assert empty['source'] == 'naver' and empty['source_switch'] == ''
    assert empty['registry']['indices.KOSPI.pct']['value'] == -3.73
    assert empty['cutoff_at'] == '2026-10-20T20:00:00+09:00'
    assert set(empty['market_snapshot']['extra']) == {'kr_econ.json', 'kr_flows.json', 'kr_session.json'}


def test_naver_block_switches_to_rss_for_the_day(tmp_path, monkeypatch):
    """키 정지·인증 실패면 그날은 언론사 RSS 로 — 사유를 남기고, 다음 tick 은 네이버를 부르지 않는다."""
    monkeypatch.setattr(K, 'NAVER_STATE', str(tmp_path / 'naver.json'))
    monkeypatch.delenv('CONTESTED_DRY', raising=False)
    calls = []

    def blocked(q, s):
        calls.append(q)
        raise K.SearchError('naver_auth')
    T = '원·달러 환율 연저점 경신 전망 엇갈려'
    hosts = ('www.yna.co.kr', 'www.hankyung.com', 'www.mk.co.kr', 'www.sedaily.com')
    pages = {f'https://{h}/robots.txt': (404, None, '') for h in hosts}
    items = []
    for i, h in enumerate(hosts):
        url = f'https://{h}/a/{i}'
        pages[url] = (200, None, _article(T + f' {i}'))
        items.append((T + f' {i}', url, 'Tue, 20 Oct 2026 15:00:00 +0900'))
    items.append(('어제 기사', 'https://www.yna.co.kr/old', 'Mon, 19 Oct 2026 08:00:00 +0900'))
    feeds = (f'https://{hosts[0]}/rss.xml', f'https://{hosts[1]}/rss.xml')
    pages[feeds[0]] = (200, None, _rss(items[:2] + items[4:]))
    pages[feeds[1]] = (200, None, _rss(items[2:4]))
    b = K.collect('2026-10-20', _files(tmp_path), deadline=900, now=NOW, page_fn=blocked, get=_Get(pages),
                  feeds=feeds)
    assert b['source'] == 'rss' and b['source_switch'] == 'naver_auth'
    assert b['status'] == 'ok' and len(b['candidates'][0]['articles']) == 4
    assert K.naver_down('2026-10-20') == 'naver_auth'
    n = len(calls)
    again = K.collect('2026-10-20', str(tmp_path / 'missing'), deadline=60, now=NOW, page_fn=blocked,
                      get=_Get(pages), feeds=feeds)
    assert again['source_switch'] == 'naver_auth'
    assert len(calls) == n                             # 그날은 네이버를 다시 부르지 않는다
    assert K.naver_down('2026-10-21') is None          # 다음 날은 다시 네이버부터


def test_transient_search_failure_does_not_switch(tmp_path, monkeypatch):
    monkeypatch.setattr(K, 'NAVER_STATE', str(tmp_path / 'naver.json'))

    def flaky(q, s):
        raise K.SearchError('search_failed')
    b = K.collect('2026-10-20', _files(tmp_path), deadline=60, now=NOW, page_fn=flaky, get=_Get({}))
    assert (b['status'], b['reason'], b['source'], b['source_switch']) == \
        ('error', 'search_failed', 'naver', '')
    assert K.naver_down('2026-10-20') is None


def test_rss_time_formats():
    want = datetime(2026, 10, 20, 17, 33, 16, tzinfo=KST)
    assert K.rss_time('Tue, 20 Oct 2026 17:33:16 +0900') == want
    assert K.rss_time('Tue,20 Oct 2026 17:33:16 +0900') == want
    assert K.rss_time('2026-10-20 17:33:16') == want
    assert K.rss_time('Tue, 20 10 2026 17:33:16 +0900') == want
    assert K.rss_time('Tue, 20 Oct 2026 08:33:16 GMT') == want
    assert K.rss_time('') is None and K.rss_time('\n   ') is None


def test_rss_window_not_covered_is_truncated(tmp_path):
    pages = {'https://www.yna.co.kr/robots.txt': (404, None, ''),
             'https://www.yna.co.kr/rss.xml': (200, None, _rss([('늦은 기사 하나', 'https://www.yna.co.kr/a/1',
                                                                 'Tue, 20 Oct 2026 19:00:00 +0900')]))}
    get = _Get(pages)
    rb = K.Robots(lambda u: (lambda c, _l, t: (c, t))(*get(u)))
    src = K.RssSource(rb, get=get, feeds=('https://www.yna.co.kr/rss.xml',))
    groups, disc, n = src.discover(CUT, K.Run(60))
    assert disc == 'truncated' and n == 1               # 피드가 발견 창 앞쪽을 덮지 못했다


def test_search_page_never_puts_keys_in_url_or_errors(monkeypatch):
    monkeypatch.setenv('NAVER_CLIENT_ID', 'IDVALUE123')
    monkeypatch.setenv('NAVER_CLIENT_SECRET', 'SECRETVALUE')
    seen = {}

    def opener(req, timeout=None, **_):
        seen['url'], seen['headers'] = req.full_url, dict(req.header_items())
        raise urllib.error.HTTPError(req.full_url, 401, 'x', {}, None)
    import urllib.error
    import pytest
    with pytest.raises(K.SearchError) as e:
        K.search_page('코스피', 1, opener=opener)
    assert 'IDVALUE123' not in seen['url'] and 'SECRETVALUE' not in str(e.value)
    assert seen['url'].startswith('https://naverapihub.apigw.ntruss.com/search/v1/news?')
    assert e.value.code == 'naver_auth'


# ── 실제 KR 발행본에서 네 상태(자리표시·ok·확정 none·생략) — KR 설계 검토 K02 ─────
import render_contested as R  # noqa: E402
import check_contested as G  # noqa: E402
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'common', 'tests'))
import test_contested as TC  # noqa: E402

KR_POST = os.path.join(ROOT, 'kr', 'posts', '2026-10-20.html')


def kr_payload(**over):
    p = TC.payload(market='kr')
    o1 = next(o for o in p['observations'] if o['obs_id'] == 'o1')
    o1.update(registry_key='indices.KOSPI.pct', indicator_ko='코스피 일간 등락률', entity='KOSPI',
              value=-3.73)
    p.update(over)
    return TC.rehash(p)


def _kr_page():
    with open(KR_POST, encoding='utf-8') as fh:
        html = fh.read()
    i = html.index('<div class="footer-note">')
    return html[:i] + C.MARKER + '\n\n' + html[i:]


_TRUST_KR = None


def kr_gate(html, p):
    global _TRUST_KR
    if _TRUST_KR is None:
        _TRUST_KR = G.trusted_styles('kr', '2026-10-20')
    return C.check(html, p, 'kr', '2026-10-20', G.transforms('kr'), _TRUST_KR)


def test_real_kr_post_passes_in_all_four_states():
    from scripts.us import readability
    page = _kr_page()
    chain = G.transforms('kr')[-1]
    pend = chain(R.apply(page, None))
    assert C.PENDING in pend and kr_gate(pend, None) == []
    p = kr_payload()
    assert C.validate(p, 'kr', '2026-10-20') == []
    filled = chain(R.apply(page, p))
    assert 'data-contested=' in filled and kr_gate(filled, p) == []
    # 발행 뒤 러너가 자리표시를 채우는 길 — 이미 가독성을 입힌 글에 다시 한 번
    late = readability.enhance_html(R.apply(pend, p))
    assert kr_gate(late, p) == []
    none = TC.rehash(dict(kr_payload(), status='none', reason='no_conflict', claims=[], pairs=[],
                          issues=[], observations=[], analysis=None, articles=[]))
    cleared = chain(R.apply(page, none))
    assert C.PENDING not in cleared and kr_gate(cleared, none) == []
    om = chain(R.apply(page, p, omit='gate_failed'))
    assert kr_gate(om, p) == []


def test_kr_gate_still_rejects_foreign_style():
    page = _kr_page()
    p = kr_payload()
    bad = G.transforms('kr')[-1](R.apply(page, p)).replace(
        '</body>', '<style>#contested{display:none}</style></body>')
    assert any('style' in e for e in kr_gate(bad, p))


def test_us_chain_unchanged():
    assert len(G.transforms('us')) == 3 and len(G.transforms('kr')) == 1


# ── 러너: 시장별 계획·시도 횟수·섹션 밖 보존·순서 ───────────────────────────
import contested_local as L  # noqa: E402


def test_runner_plan_and_attempt_keys_per_market(tmp_path, monkeypatch):
    monkeypatch.setattr(L, 'STATE', str(tmp_path / 'state.json'))
    p = kr_payload()
    assert L.plan(p, 'pending', '2026-10-20', 'kr') == 'fill'
    assert L.plan(p, 'pending', '2026-10-20', 'us') == 'analyze'      # 시장이 다른 결과는 확정이 아니다
    assert L._attempts_local('2026-10-20', bump=True, market='kr') == 1
    assert L._attempts_local('2026-10-20', market='us') == 0              # 시장마다 따로 센다
    (tmp_path / 'state.json').write_text('{"2026-10-19": 2}')
    assert L._attempts_local('2026-10-19', market='us') == 2              # 옛 US 열쇠도 읽는다
    assert L._attempts_local('2026-10-19', market='kr') == 0


def test_outside_section_is_same_for_every_slot_state():
    page = _kr_page()
    p = kr_payload()
    states = [R.apply(page, None), R.apply(page, p), R.apply(page, p, omit='gate_failed'), page]
    outs = {L.outside_section(h) for h in states}
    assert len(outs) == 1
    tampered = R.apply(page, p).replace('코스피', '코스피!', 1)
    assert L.outside_section(tampered) not in outs


def test_market_rotation(tmp_path, monkeypatch):
    monkeypatch.setattr(L, 'ROTATE', str(tmp_path / 'rot.json'))
    monkeypatch.delenv('CONTESTED_DRY', raising=False)
    assert L._order() == ['us', 'kr']
    L._remember('us')
    assert L._order() == ['kr', 'us']


# ── codex 구현 검토(KR) 회귀 — #2·#3·#5·#6·#7·#8·#9 ─────────────────────────
def test_before_cutoff_is_not_final(tmp_path, monkeypatch):
    monkeypatch.setattr(K, 'NAVER_STATE', str(tmp_path / 'naver.json'))
    early = datetime(2026, 10, 20, 19, 59, tzinfo=KST)
    b = K.collect('2026-10-20', _files(tmp_path), deadline=60, now=early, page_fn=lambda q, s: ([], 0),
                  get=_Get({}))
    assert (b['status'], b['reason']) == ('error', 'before_cutoff')
    on = datetime(2026, 10, 20, 20, 0, tzinfo=KST)
    b = K.collect('2026-10-20', str(tmp_path / 'data'), deadline=60, now=on, page_fn=lambda q, s: ([], 0),
                  get=_Get({}))
    assert b['reason'] == 'no_candidate'


def test_runner_waits_for_kr_cutoff_without_spending_attempts(tmp_path, monkeypatch):
    monkeypatch.setattr(L, 'STATE', str(tmp_path / 'state.json'))

    class Early(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 20, 18, 30, tzinfo=KST)
    monkeypatch.setattr(L, 'datetime', Early)
    clone = tmp_path / 'clone'
    (clone / 'kr' / 'posts').mkdir(parents=True)
    notes = []
    assert L.handle(str(clone), str(tmp_path), '2026-10-20', {}, notes, 'kr') is None
    assert notes == ['kr 2026-10-20 기준 시각 전']
    assert L._attempts_local('2026-10-20', market='kr') == 0


def test_rss_expand_window_is_tracked_apart_from_discovery():
    """가장 오래된 기사가 발견 창(24h)은 덮지만 확장 창(72h)은 못 덮는 피드(#5)."""
    pages = {'https://www.yna.co.kr/robots.txt': (404, None, ''),
             'https://www.yna.co.kr/rss.xml': (200, None, _rss([
                 ('원·달러 환율 연저점 경신 전망 엇갈려 1', 'https://www.yna.co.kr/a/1', 'Tue, 20 Oct 2026 15:00:00 +0900'),
                 ('원·달러 환율 연저점 경신 전망 엇갈려 2', 'https://www.yna.co.kr/a/2', 'Mon, 19 Oct 2026 18:00:00 +0900')]))}
    get = _Get(pages)
    rb = K.Robots(lambda u: (lambda c, _l, t: (c, t))(*get(u)))
    src = K.RssSource(rb, get=get, feeds=('https://www.yna.co.kr/rss.xml',))
    groups, disc, n = src.discover(CUT, K.Run(60))
    assert disc == 'ok'
    assert src.expand([{'title': '원·달러 환율 연저점 경신 전망 엇갈려', 'url': 'https://www.yna.co.kr/a/1'}],
                      CUT)[2] is False


def test_time_cap_is_recorded_as_transient():
    T = '원·달러 환율 연저점 경신 전망 엇갈려'
    rows = [{'title': T, 'url': f'https://www.yna.co.kr/a/{i}', 'published': None} for i in range(3)]
    status = []
    arts = K.fetch_bodies(rows, None, CUT, K.Run(60), get=_Get({}), status=status)
    assert arts == [] and status == ['time_cap']
    import contested_build as Bld
    assert 'time_cap' in Bld.TRANSIENT


def test_naver_state_keeps_every_day_under_lock(tmp_path, monkeypatch):
    monkeypatch.setattr(K, 'NAVER_STATE', str(tmp_path / 'naver.json'))
    monkeypatch.delenv('CONTESTED_DRY', raising=False)
    K.mark_naver_down('2026-10-20', 'naver_auth')
    K.mark_naver_down('2026-10-21', 'naver_throttled')
    assert K.naver_down('2026-10-20') == 'naver_auth' and K.naver_down('2026-10-21') == 'naver_throttled'
    assert not [p for p in os.listdir(tmp_path) if p.endswith('.tmp')]
    monkeypatch.setenv('CONTESTED_DRY', '1')
    K.mark_naver_down('2026-10-22', 'naver_auth')
    assert K.naver_down('2026-10-22') is None


def test_redirect_cannot_exceed_publisher_cap():
    T = '원·달러 환율 연저점 경신 전망 엇갈려'
    pages = {f'https://{h}/robots.txt': (404, None, '') for h in
             ('www.yna.co.kr', 'www.mk.co.kr', 'www.hankyung.com', 'www.chosun.com')}
    rows = []
    for i, h in enumerate(('www.yna.co.kr', 'www.mk.co.kr', 'www.hankyung.com')):
        src, dst = f'https://{h}/r/{i}', f'https://www.chosun.com/a/{i}'
        pages[src] = (302, dst, '')
        pages[dst] = (200, None, _article(T + f' {i}'))
        rows.append({'title': T, 'url': src, 'published': None})
    get = _Get(pages)
    rb = K.Robots(lambda u: (lambda c, _l, t: (c, t))(*get(u)))
    status = []
    arts = K.fetch_bodies(rows, rb, CUT, K.Run(900), get=get, status=status)
    assert [a['source'] for a in arts] == ['조선일보', '조선일보'] and status.count('blocked') == 1


def test_style_pass_never_extracts_contested_paragraphs():
    from us import prose_swap
    html = _kr_page().replace(C.MARKER, C.render(kr_payload()))
    text, _ = prose_swap.extract(html)
    assert '재정 긴축이 거리 시위로' not in text and '참가 인원 집계 차이' not in text


def test_incomplete_market_data_does_not_spend_attempts(tmp_path, monkeypatch):
    """10/21 실운영: US 10/20 시장 파일이 complete:false 인 동안 tick 마다 시도를 태웠다."""
    import subprocess
    monkeypatch.setattr(L, 'STATE', str(tmp_path / 'state.json'))
    clone = tmp_path / 'clone'
    (clone / 'data').mkdir(parents=True)
    (clone / 'news').mkdir()
    subprocess.run(['git', 'init', '-q', str(clone)], check=True)
    md = {'report_date': '2026-10-20', 'complete': False}
    (clone / 'data' / 'market_data.json').write_text(json.dumps(md))
    subprocess.run(['git', '-C', str(clone), 'add', '-A'], check=True)
    subprocess.run(['git', '-C', str(clone), '-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-qm', 'x'],
                   check=True)

    class Now(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 21, 7, 0, tzinfo=KST)
    monkeypatch.setattr(L, 'datetime', Now)
    notes = []
    assert L.handle(str(clone), str(tmp_path), '2026-10-20', md, notes, 'us') is None
    assert notes == ['us 2026-10-20 시장 데이터 미완'] and L._attempts_local('2026-10-20', market='us') == 0
    assert L._market_ready(str(clone), '2026-10-20', dict(md, complete=True), 'us')


def _throttled_clone(tmp_path):
    import subprocess
    clone = tmp_path / 'clone'
    (clone / 'data').mkdir(parents=True)
    (clone / 'news').mkdir()
    subprocess.run(['git', 'init', '-q', str(clone)], check=True)
    md = {'report_date': '2026-10-20', 'complete': True}
    (clone / 'data' / 'market_data.json').write_text(json.dumps(md))
    subprocess.run(['git', '-C', str(clone), 'add', '-A'], check=True)
    subprocess.run(['git', '-C', str(clone), '-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-qm', 'x'],
                   check=True)
    return clone, md


def test_throttled_discovery_refunds_the_attempt_and_cools_down(tmp_path, monkeypatch):
    """10/21 실운영: GDELT 429 가 이어지는 동안 tick 마다 시도를 태워 US 10/20 이 상한에 닿을 뻔했다."""
    import sys
    import types
    import contested_build as Bld
    monkeypatch.setattr(L, 'STATE', str(tmp_path / 'state.json'))
    monkeypatch.delenv('CONTESTED_DRY', raising=False)
    monkeypatch.setenv('HOME', str(tmp_path))              # 마지막 결과 파일(~/Library/Caches)을 실제 홈에 쓰지 않게
    (tmp_path / 'Library' / 'Caches').mkdir(parents=True, exist_ok=True)
    clone, md = _throttled_clone(tmp_path)
    clock = {'t': datetime(2026, 10, 21, 7, 39, tzinfo=KST)}

    class Now(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock['t'] if tz is None else clock['t'].astimezone(tz)
    monkeypatch.setattr(L, 'datetime', Now)
    fake = types.ModuleType('collect_contested')
    fake.collect = lambda *a, **k: {'status': 'ok', 'gdelt': 'throttled', 'discovery': 'throttled'}
    monkeypatch.setitem(sys.modules, 'collect_contested', fake)
    monkeypatch.setattr(Bld, 'ranker', lambda diag=None: None)
    monkeypatch.setattr(Bld, 'analyze', lambda bundle, base: dict(
        base, status='error', reason='fetch_incomplete', retryable=True))
    L._attempts_local('2026-10-20', bump=True, market='us')            # 앞선 시도 1회
    notes = []
    files, _ = L.handle(str(clone), str(tmp_path), '2026-10-20', md, notes, 'us')
    res = json.loads((clone / 'data' / 'contested' / 'us' / '2026-10-20.json').read_text())
    assert res['attempts'] == 1 and res['retryable'] is True
    assert res['diagnostics']['attempt_refunded'] == 'discovery_throttled'
    assert L._attempts_local('2026-10-20', market='us') == 1
    assert C.validate(res, 'us', '2026-10-20') == []
    # 쉬는 동안은 다시 묻지 않는다 — 막힌 GDELT 를 15분마다 두드리지 않게
    clock['t'] = datetime(2026, 10, 21, 8, 20, tzinfo=KST)
    notes = []
    assert L.handle(str(clone), str(tmp_path), '2026-10-20', md, notes, 'us') is None
    assert notes == ['us 2026-10-20 검색 제한 대기']
    clock['t'] = datetime(2026, 10, 21, 8, 45, tzinfo=KST)
    notes = []
    assert L.handle(str(clone), str(tmp_path), '2026-10-20', md, notes, 'us') is not None


def test_throttled_but_last_attempt_still_refunds(tmp_path, monkeypatch):
    """상한 직전 시도도 돌려준다 — 막힌 검색 탓에 그날을 최종 오류로 굳히지 않는다."""
    import sys
    import types
    import contested_build as Bld
    monkeypatch.setattr(L, 'STATE', str(tmp_path / 'state.json'))
    monkeypatch.delenv('CONTESTED_DRY', raising=False)
    monkeypatch.setenv('HOME', str(tmp_path))              # 마지막 결과 파일(~/Library/Caches)을 실제 홈에 쓰지 않게
    (tmp_path / 'Library' / 'Caches').mkdir(parents=True, exist_ok=True)
    clone, md = _throttled_clone(tmp_path)

    class Now(datetime):
        @classmethod
        def now(cls, tz=None):
            t = datetime(2026, 10, 21, 7, 54, tzinfo=KST)
            return t if tz is None else t.astimezone(tz)
    monkeypatch.setattr(L, 'datetime', Now)
    fake = types.ModuleType('collect_contested')
    fake.collect = lambda *a, **k: {'status': 'ok', 'gdelt': 'throttled', 'discovery': 'throttled'}
    monkeypatch.setitem(sys.modules, 'collect_contested', fake)
    monkeypatch.setattr(Bld, 'ranker', lambda diag=None: None)
    monkeypatch.setattr(Bld, 'analyze', lambda bundle, base: dict(
        base, status='none', reason='analysis_unverified', retryable=True))
    for _ in range(C.MAX_ATTEMPTS - 1):
        L._attempts_local('2026-10-20', bump=True, market='us')
    L.handle(str(clone), str(tmp_path), '2026-10-20', md, [], 'us')
    res = json.loads((clone / 'data' / 'contested' / 'us' / '2026-10-20.json').read_text())
    assert res['attempts'] == C.MAX_ATTEMPTS - 1 and res['retryable'] is True
    assert not C.settled(res, 'us', '2026-10-20')


def test_refund_cooldown_survives_a_failed_push_and_dry_runs_restore(tmp_path, monkeypatch):
    """구현 검토 P2 두 건: 푸시가 실패해 원격 결과가 옛것이어도 쉬고, 시험 운행은 시도 전 횟수로 돌린다."""
    monkeypatch.setattr(L, 'STATE', str(tmp_path / 'state.json'))
    monkeypatch.delenv('CONTESTED_DRY', raising=False)
    t = {'now': datetime(2026, 10, 21, 7, 39, tzinfo=KST)}

    class Now(datetime):
        @classmethod
        def now(cls, tz=None):
            return t['now'] if tz is None else t['now'].astimezone(tz)
    monkeypatch.setattr(L, 'datetime', Now)
    for _ in range(4):
        L._attempts_local('2026-10-20', bump=True, market='us')
    assert L._attempts_local('2026-10-20', bump=True, market='us') == 5
    assert L._attempts_local('2026-10-20', market='us', refund_to=4) == 4
    old_remote = {'attempts': 4, 'diagnostics': {}, 'collected_at': '2026-10-20T21:00:00+00:00'}
    t['now'] = datetime(2026, 10, 21, 8, 20, tzinfo=KST)
    assert L._cooling('2026-10-20', old_remote, 'us')                  # 원격엔 표시가 없어도 로컬로 쉰다
    t['now'] = datetime(2026, 10, 21, 8, 40, tzinfo=KST)
    assert not L._cooling('2026-10-20', old_remote, 'us')
    assert not L._cooling('2026-10-20', old_remote, 'kr')
    naive = {'diagnostics': {'attempt_refunded': 'discovery_throttled'}, 'collected_at': '2026-10-20T23:30:00'}
    assert L._cooling('2026-10-21', naive, 'us')                       # 시간대 없는 시각도 UTC 로 읽는다
    monkeypatch.setenv('CONTESTED_DRY', '1')
    assert L._attempts_local('2026-10-20', bump=True, market='us') == 5
    assert L._attempts_local('2026-10-20', market='us', refund_to=4) == 4
    assert L._attempts_local('2026-10-20', market='us') == 4


def test_push_adds_tracked_pages_under_ignored_dirs(tmp_path, monkeypatch):
    """10/21 실운영: 레포 .gitignore 의 `/news/` 때문에 추적 중인 발행본도 `git add` 가 거부돼 tick 마다 죽었다."""
    import subprocess
    g = ['-c', 'user.email=t@t', '-c', 'user.name=t']
    remote = tmp_path / 'remote.git'
    subprocess.run(['git', 'init', '-q', '--bare', '-b', 'main', str(remote)], check=True)
    clone = tmp_path / 'clone'
    subprocess.run(['git', 'clone', '-q', str(remote), str(clone)], check=True, capture_output=True)
    subprocess.run(['git', '-C', str(clone), 'checkout', '-q', '-b', 'main'], check=True)
    (clone / '.gitignore').write_text('/news/\n')
    (clone / 'news').mkdir()
    (clone / 'news' / '2026-10-20.html').write_text('<p>a</p>')
    subprocess.run(['git', '-C', str(clone), 'add', '-f', '.gitignore', 'news/2026-10-20.html'], check=True)
    subprocess.run(['git', '-C', str(clone), *g, 'commit', '-qm', 'x'], check=True)
    subprocess.run(['git', '-C', str(clone), 'push', '-q', 'origin', 'HEAD:main'], check=True)
    (clone / 'news' / '2026-10-20.html').write_text('<p>b</p>')
    for k, v in (('GIT_AUTHOR_NAME', 't'), ('GIT_AUTHOR_EMAIL', 't@t'), ('GIT_COMMITTER_NAME', 't'),
                 ('GIT_COMMITTER_EMAIL', 't@t')):
        monkeypatch.setenv(k, v)
    assert L.push(str(clone), ['news/2026-10-20.html'], 'fill', {}) == 'pushed'
    out = subprocess.run(['git', '--git-dir', str(remote), 'show', 'main:news/2026-10-20.html'],
                         capture_output=True, text=True, check=True).stdout
    assert out == '<p>b</p>'
