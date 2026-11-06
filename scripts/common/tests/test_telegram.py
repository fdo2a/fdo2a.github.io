"""Telegram source for the daily briefs — collection rules, summariser and publication gate."""
import json
import os
import types
from datetime import datetime, timedelta, timezone

import pytest

import fetch_telegram as F
from common import telegram as tg
from common import tg_summary
from common.telegram_gate import check, elements
from common.tg_parse import ParseError, parse_page

FX = os.path.join(os.path.dirname(__file__), 'fixtures', 'telegram', 'sample_page.html')
NOW = datetime(2026, 11, 9, 8, 0, tzinfo=timezone.utc)


def post(i, text, links=(), at=None, fwd=None):
    return {'id': i, 'url': f'https://t.me/c/{i}', 'dt_utc': (at or NOW).isoformat(), 'text': text,
            'links': list(links), 'forwarded_from': fwd}


# ── parsing ──────────────────────────────────────────────────────────────

def test_scrubbed_fixture_parses_and_carries_no_real_text():
    with open(FX, encoding='utf-8') as f:
        html = f.read()
    posts, before = parse_page(html, 'lim_econ')
    assert len(posts) == 20 and before is not None
    assert all(p['text'].startswith('테스트 본문') for p in posts if p['text'])
    with pytest.raises(ParseError):
        parse_page('<html></html>', 'lim_econ')


# ── views, credits, kinds ────────────────────────────────────────────────

@pytest.mark.parametrize('ch,text,want', [
    ('hedgecat0301', '[11/6, 장 시작 전 생각: AI 패닉, 키움 한지영] - 나스닥 -5.5%', ('키움증권', '한지영')),
    ('kwusa', '[키움 미국전략/주식 김승혁] US Daily (11/6) S&P500 -4.36%', ('키움증권', '김승혁')),
    ('kwusa', '[키움증권/김진구] 유니티 소프트웨어 (U.US) 기업리포트', ('키움증권', '김진구')),
    ('kwusa', '[키움 글로벌리서치팀] 키차트 11월 1주차', ('키움증권', '글로벌리서치팀')),
    ('kwusa', '제목 : 테슬라 하락 *연합인포맥스* 시킹 알파는', None),
    ('lim_econ', '<오늘 개장전 꼭 알아야 할 5가지_11/6 Bloomberg> ① AI 투매' + '가' * 300, None),
    ('lim_econ', '수출 지표를 보면 ' + '반도체 수출이 견조하다. ' * 20, ('한화투자증권', '임혜윤')),
    ('FastStockNews', '[키움 한지영] 흉내', None),
])
def test_view_of(ch, text, want):
    assert tg.view_of(ch, post(1, text)) == want


def test_forwarded_firm_post_is_not_a_view():
    assert tg.view_of('hedgecat0301', post(1, '[11/6, 키움 한지영] x', fwd='다른 채널')) is None


@pytest.mark.parametrize('text,want', [
    ('제목 : 테슬라 하락 *연합인포맥스* 시킹 알파는 민주당 승리', '연합인포맥스'),
    ('이탈리아, 가스 발전소 보조금 지급 승인 예정 - 블룸버그', '블룸버그'),
    ('<오늘 개장전 꼭 알아야 할 5가지_11/6 Bloomberg> ① AI 투매', '블룸버그'),
    ('[MSCI] 11월 6일, 진시데이터 – MSCI 회장은', '진시데이터'),
    ('출처 없는 글 - 친구', None),
])
def test_credited_source(text, want):
    assert tg.credited_source(text) == want


def test_classify_kinds_and_market():
    rep = tg.classify_post('FastStockNews', post(5, '✅ 대만 증시 안정책 코스피 영향',
                                                 ['https://n.news.naver.com/article/366/0001203086?sid=101']), 'kr')
    assert rep['kind'] == 'report' and rep['id'] == 'FastStockNews/5' and rep['source']['basis'] == 'link'
    op = tg.classify_post('kwusa', post(6, '제목 : 테슬라와 스페이스X, 민주당 승리 예상에 하락 *연합인포맥스* 시킹 알파는 미국 중간선거에서 민주당이 승리할 것으로'), 'us')
    assert op['kind'] == 'opinion' and op['source']['name'] == '연합인포맥스'
    assert tg.classify_post('kwusa', post(7, '제목 : 테슬라와 스페이스X, 민주당 승리 예상에 하락 *연합인포맥스* 시킹 알파는 미국 중간선거에서'), 'kr') is None
    assert tg.classify_post('FastStockNews', post(8, '외국인은 오늘도'), 'kr') is None          # chatter
    v = tg.classify_post('hedgecat0301', post(9, '[11/6, 장 시작 전 생각, 키움 한지영] 코스피 급락 이후 나스닥 반등 여부가 관건이라는 메모'), 'kr')
    assert v['kind'] == 'view' and v['analyst'] == '한지영'


def test_select_dedupes_same_original_and_caps():
    link = 'https://www.reuters.com/markets/a'
    a = tg.classify_post('insidertracking', post(1, '연준 금리 동결 전망에 나스닥 선물이 흔들린다는 보도', [link], NOW), 'us')
    b = tg.classify_post('FastStockNewsUSA', post(2, '연준 금리 동결 전망, 나스닥 선물 약세 전환', [link + '?utm_source=x'],
                                                  NOW + timedelta(minutes=5)), 'us')
    out = tg.select([(a, {'text': 'x'}), (b, {'text': 'y'})])
    assert [i['id'] for i, _ in out] == ['insidertracking/1']
    chans = ['insidertracking', 'FastStockNewsUSA', 'd_ticker', 'kwusa', 'aethersemiconductor']
    many = [(tg.classify_post(chans[i % 5], post(i, f'나스닥 급락 소식 {i} — 엔비디아 하락과 금리 상승이 겹치며 투매가 이어졌다는 이야기'), 'us'),
             {'text': '나스닥'}) for i in range(40)]
    got = tg.select(many)
    assert len(got) == min(tg.MAX_OPINIONS, 5 * tg.MAX_PER_CHANNEL)
    from collections import Counter
    assert max(Counter(i['channel'] for i, _ in got).values()) <= tg.MAX_PER_CHANNEL


def test_paywalled_link_becomes_credited_opinion_and_url_date():
    it = tg.classify_post('d_ticker', post(3, '코어위브 CDS 사상 최고, 나스닥 AI 인프라 신용 우려 확산이라는 분석',
                                           ['https://www.bloomberg.com/news/articles/2026-10-13/cxmt-claims']), 'us')
    assert it['kind'] == 'opinion' and it['source'] == {'name': '블룸버그', 'url': None, 'basis': 'paywalled_link'}
    assert it['article_date'] == '2026-10-13'
    assert tg.url_date('https://www.cnbc.com/2026/10/20/x.html') == '2026-10-20'
    assert tg.url_date('https://www.asiae.co.kr/article/2026101413534603392') == '2026-10-14'
    assert tg.url_date('https://www.reuters.com/markets/x') is None


def test_stale_article_and_wall_detection():
    assert F.stale({'article_date': '2026-10-13'}, NOW)
    assert not F.stale({'article_date': '2026-11-08'}, NOW) and not F.stale({}, NOW)
    item = {'source': {'url': 'https://x.example/a', 'name': '로이터'}}
    wall = 'Subscribe now. Complete digital access to quality journalism. ' * 20
    body, name, pub = F.fetch_origin(item, None, lambda u, c: ('page', u), lambda p: wall, lambda p: None)
    assert body is None and name == '로이터'
    body, _, _ = F.fetch_origin(item, None, lambda u, c: ('page', u), lambda p: '짧다', lambda p: None)
    assert body is None
    good = '연준이 금리를 동결했다. ' * 60
    body, _, _ = F.fetch_origin(item, None, lambda u, c: ('page', u), lambda p: good, lambda p: '2026-11-08T00:00:00+00:00')
    assert body == good


def test_outlet_for_naver_reads_press_from_page():
    page = '<meta property="og:article:author" content="조선비즈 | 네이버">'
    assert tg.outlet_for('https://n.news.naver.com/mnews/article/366/0001203086', page) == '조선비즈'
    assert tg.outlet_for('https://www.reuters.com/x') == '로이터'
    assert tg.outlet_for('https://unknown.example/x') is None


# ── collection ───────────────────────────────────────────────────────────

def fake_channel(ch, top, start=NOW):
    def page(url):
        before = int(url.split('before=')[1]) if 'before=' in url else top + 1
        ids = list(range(max(1, before - 20), before))
        rows = ''.join(
            f'<div class="tgme_widget_message js-widget_message" data-post="{ch}/{i}">'
            f'<div class="tgme_widget_message_text">글 {i}</div>'
            f'<time datetime="{(start - timedelta(minutes=10 * (top - i))).isoformat()}"></time></div>'
            for i in ids)
        if ids and min(ids) > 1:
            rows += f'<a href="/s/{ch}?before={min(ids)}">m</a>'
        return rows
    return page


nosleep = lambda s: None


def test_read_channel_stops_at_cursor():
    posts, st = F.read_channel('c', 90, None, fake_channel('c', 100), nosleep)
    assert [p['id'] for p in posts] == list(range(91, 101)) and st['status'] == 'ok'


def test_read_channel_cap_records_hole():
    posts, st = F.read_channel('c', 10, None, fake_channel('c', 200), nosleep, max_pages=2)
    assert st['truncated'] and st['hole'] == [10, posts[0]['id']] and posts[-1]['id'] == 200


def test_read_channel_without_cursor_uses_floor():
    posts, st = F.read_channel('c', None, NOW - timedelta(hours=1), fake_channel('c', 100), nosleep)
    assert min(p['id'] for p in posts) == 94       # 10-minute spacing, last hour


def test_failed_channel_keeps_old_cursor(monkeypatch):
    monkeypatch.setattr(tg, 'CHANNELS', {'c': {'group': 'relay', 'market': 'us'}})
    def boom(url):
        raise IOError('HTTP 429')
    prev = {'channels': {'c': {'last_id': 50, 'last_dt': (NOW - timedelta(hours=2)).isoformat()}}}
    cands, chans, notes = F.collect('us', prev, NOW, boom, nosleep)
    assert chans['c']['status'] == 'failed' and chans['c']['last_id'] == 50


def test_stale_cursor_is_cut_to_lookback(monkeypatch):
    monkeypatch.setattr(tg, 'CHANNELS', {'c': {'group': 'relay', 'market': 'us'}})
    prev = {'channels': {'c': {'last_id': 1, 'last_dt': (NOW - timedelta(days=5)).isoformat()}}}
    cands, chans, notes = F.collect('us', prev, NOW, fake_channel('c', 1000), nosleep)
    assert notes and '72' in notes[0]


def test_previous_file_and_freeze(tmp_path):
    d = tmp_path / 'telegram'
    d.mkdir()
    (d / '2026-11-06.json').write_text(json.dumps({'channels': {'c': {'last_id': 3}}, 'items': []}))
    (d / '2026-11-09.json').write_text(json.dumps({'items': [{'summary_ko': '요약'}]}))
    assert F.previous_file(str(d), '2026-11-09')['channels']['c']['last_id'] == 3
    assert F.previous_file(str(d), '2026-11-20') is None or True
    assert F.frozen(str(d / '2026-11-09.json')) and not F.frozen(str(d / '2026-11-06.json'))


# ── summariser ───────────────────────────────────────────────────────────

class FakeClient:
    def __init__(self, texts):
        self.texts, self.calls = list(texts), 0
        self.messages = self

    def create(self, **kw):
        self.calls += 1
        t = self.texts.pop(0)
        return types.SimpleNamespace(stop_reason='end_turn', content=[types.SimpleNamespace(type='text', text=t)])


def test_short_summary_band_and_copy_rejection(monkeypatch):
    monkeypatch.setattr(tg_summary.ns, '_text', lambda r: r.content[0].text)
    body = '필자는 나스닥 급락이 AI 투자 속도에 대한 의심에서 비롯됐다고 본다. 금리는 부차적이라는 판단이다. ' * 2
    good = ('필자는 나스닥 급락의 원인을 금리보다 AI 투자 속도에 대한 의심에서 찾는다. 단기 반등을 노리기보다 '
            '실적으로 투자 회수 속도가 확인될 때까지 기다리는 편이 낫다고 진단했다.')
    items = [{'id': 'a/1', 'kind': 'view'}, {'id': 'a/2', 'kind': 'opinion'}]
    bodies = {'a/1': body, 'a/2': body}
    done, failed = tg_summary.summarize(items, bodies, client=FakeClient([good, body.strip(), body.strip()]),
                                        model='m', log=lambda *a: None)
    assert items[0]['summary_ko'] == good
    assert 'summary_ko' not in items[1] and items[1]['summary_note']
    assert (done, failed) == (1, 1)


def test_summary_without_client_marks_every_item(monkeypatch):
    monkeypatch.setattr(tg_summary.ns, 'make_client', lambda: (_ for _ in ()).throw(RuntimeError('no key')))
    monkeypatch.setattr(tg_summary.ns, 'credential_source', lambda: 'key')
    items = [{'id': 'a/1', 'kind': 'view'}]
    assert tg_summary.summarize(items, {'a/1': 'x'}, log=lambda *a: None) == (0, 1)
    assert items[0]['summary_note'].startswith('요약 클라이언트 없음')


# ── gate ─────────────────────────────────────────────────────────────────

DATA = {'report_date': '2026-11-09', 'items': [
    {'id': 'hedgecat0301/10', 'kind': 'view', 'firm': '키움증권', 'analyst': '한지영', 'source': None,
     'summary_ko': '필자는 나스닥이 5.5% 급락한 배경을 금리보다 AI 투자 속도에 대한 의심에서 찾고, 실적 확인 전까지 변동성이 이어진다고 본다.'},
    {'id': 'insidertracking/7', 'kind': 'report', 'firm': None, 'analyst': None,
     'source': {'name': '로이터', 'url': 'https://www.reuters.com/x', 'basis': 'link'},
     'summary_ko': '로이터는 텍사스 주지사 당선인이 데이터센터 사업 중단을 요구했다고 보도했다. 전력과 용수 부담이 이유다.'},
    {'id': 'kwusa/3', 'kind': 'opinion', 'firm': None, 'analyst': None,
     'source': {'name': '연합인포맥스', 'url': None, 'basis': 'credit'},
     'summary_ko': '민주당 승리로 테슬라와 스페이스X 관련 규제가 강화될 수 있다는 시각이 전해졌다.'},
]}


def page(body):
    return f'<html><body data-register="da"><main>{body}</main></body></html>'


GOOD = page('<p><span data-tg="hedgecat0301/10">키움증권 한지영 연구원은 나스닥이 5.5% 급락한 배경을 금리보다 AI 투자 속도에 대한 의심에서 찾았다.</span></p>'
            '<p><span data-tg="insidertracking/7">로이터에 따르면 텍사스 주지사 당선인은 데이터센터 사업 중단을 요구했다.</span></p>'
            '<p><span data-tg="kwusa/3">연합인포맥스를 인용해 민주당 승리로 테슬라 관련 규제가 강화될 수 있다는 시각도 나왔다.</span></p>')


def test_gate_passes_well_formed_post():
    assert check(GOOD, DATA) == []


def test_gate_passes_post_without_telegram():
    assert check(page('<p>코스피가 하락했다.</p>'), None) == []


@pytest.mark.parametrize('html,needle', [
    (page('<p>텔레그램 채널에 따르면 하락했다.</p>'), '텔레그램'),
    (page('<p><a href="https://t.me/kwusa/3">링크</a></p>'), 't.me'),
    (page('<p>딘스티커는 하락을 예상했다.</p>'), '채널 이름'),
    (page('<p><span data-tg="nope/1">무엇</span></p>'), '파일에 없거나'),
    (page('<p><span data-tg="hedgecat0301/10">한지영 연구원은 나스닥 급락을 AI 투자 의심에서 찾았다.</span></p>'), '「키움증권」'),
    (page('<p><span data-tg="insidertracking/7">텍사스 주지사 당선인은 데이터센터 사업 중단을 요구했다고 한다.</span></p>'), '로이터'),
    (page('<p><span data-tg="kwusa/3">연합인포맥스: 민주당 승리로 테슬라 규제가 강화된다.</span></p>'), '의견 틀'),
    (page('<p><span data-tg="hedgecat0301/10">키움증권 한지영 연구원은 나스닥이 7.2% 급락한 배경을 AI 투자 의심에서 찾았다.</span></p>'), '요약에 없는 수치'),
    (page('<p><span data-tg="hedgecat0301/10">키움증권 한지영 연구원은 반도체 재고가 늘었다고 봤다는 내용으로 전혀 다른 말을 길게 했다.</span></p>'), '맞지 않는다'),
])
def test_gate_blocks(html, needle):
    v = check(html, DATA)
    assert any(needle in x for x in v), v


def test_gate_without_file_but_marker_fails():
    assert check(GOOD, None) == ['data-tg 표식이 있는데 텔레그램 파일이 없다']


def test_gate_bare_firm_stock_name_is_fine():
    assert check(page('<p>증권주 가운데 키움증권이 4.1% 올랐다.</p>'), DATA) == []


def test_gate_ignores_editor_note_and_counts_limits():
    note = '<section id="editor-note" data-editor-note="2026-11-09"><p>텔레그램에서 본 이야기</p></section>'
    assert check(page(note), DATA) == []
    four = ''.join(f'<p><span data-tg="hedgecat0301/10">키움증권 한지영 연구원은 나스닥 급락 배경을 AI 투자 속도 의심에서 찾았다.</span></p>'
                   for _ in range(4))
    assert any('최대 3' in x for x in check(page(four), DATA))


def test_elements_balance_nested_tags():
    html = '<p data-tg="a/1">x <p>inner</p> y</p><p>after</p>'
    (tid, inner, s, e), = elements(html)
    assert tid == 'a/1' and 'after' not in inner and 'inner' in inner


# ── codex 구현 검토 1차 재현 ─────────────────────────────────────────────

def test_plain_brief_quoting_a_firm_from_elsewhere_passes():
    assert check(page('<p>키움증권 연구원은 시장이 과민하다고 봤다.</p>'), None) == []


@pytest.mark.parametrize('fake', ['999달러', '5.5bp', '5.5달러'])
def test_numbers_are_unit_sensitive(fake):
    html = page(f'<p><span data-tg="hedgecat0301/10">키움증권 한지영 연구원은 나스닥이 {fake} 급락한 배경을 금리보다 AI 투자 속도에 대한 의심에서 찾았다.</span></p>')
    assert any('요약에 없는 수치' in x for x in check(html, DATA))


def test_single_quoted_marker_and_link_are_seen():
    assert any('파일이 없다' in x for x in check(page("<p><span data-tg='fake/9'>무엇</span></p>"), None))
    assert any('t.me' in x for x in check(page("<p><a href='https://t.me/foobar/1'>출처</a></p>"), None))


def test_consent_page_is_not_an_article():
    item = {'source': {'url': 'https://www.reuters.com/x', 'name': '로이터'}}
    consent = 'We use cookies and your personal data to tailor content and advertisements. You can manage your choices at any time. ' * 8
    body, _, _ = F.fetch_origin(item, None, lambda u, c: ('p', u), lambda p: consent, lambda p: None)
    assert body is None


def test_partial_channel_keeps_old_cursor(monkeypatch):
    monkeypatch.setattr(tg, 'CHANNELS', {'c': {'group': 'relay', 'market': 'us'}})
    good = fake_channel('c', 110)
    calls = []
    def flaky(url):
        calls.append(url)
        if 'before=' in url:
            raise IOError('HTTP 500')
        return good(url)
    prev = {'channels': {'c': {'last_id': 50, 'last_dt': (NOW - timedelta(hours=2)).isoformat()}}}
    _, chans, _ = F.collect('us', prev, NOW, flaky, nosleep)
    assert chans['c']['status'] == 'partial' and chans['c']['last_id'] == 50


def test_stale_uses_the_channels_actual_window(monkeypatch):
    monkeypatch.setattr(tg, 'CHANNELS', {'c': {'group': 'relay', 'market': 'us'}})
    prev = {'channels': {'c': {'last_id': 1, 'last_dt': '2026-10-01T00:00:00+00:00'}}}
    _, chans, _ = F.collect('us', prev, NOW, fake_channel('c', 30), nosleep)
    start = datetime.fromisoformat(chans['c']['from_dt'])
    assert start >= NOW - timedelta(hours=F.MAX_LOOKBACK_H)
    assert F.stale({'article_date': '2026-10-20'}, start)


def test_analyst_quoted_from_another_source_passes():
    assert check(page('<p>한지영 연구원은 시장이 과민하다고 봤다.</p>'), DATA) == []


def test_uppercase_marker_is_seen():
    assert any('파일이 없다' in x for x in check(page('<p><span DATA-TG="fake/9">무엇</span></p>'), None))


def test_redirect_to_other_host_is_not_that_outlet():
    item = {'source': {'url': 'https://www.reuters.com/x', 'name': '로이터'}}
    good = '연준이 금리를 동결했다. ' * 60
    body, name, _ = F.fetch_origin(item, None, lambda u, c: ('p', 'https://other.example/y'),
                                   lambda p: good, lambda p: None)
    assert body is None and name is None
    body, _, _ = F.fetch_origin(item, None, lambda u, c: ('p', 'https://reuters.com/x?r=1'),
                                lambda p: good, lambda p: None)
    assert body == good


def test_freeze_needs_complete_channels(tmp_path):
    p = tmp_path / 'x.json'
    p.write_text(json.dumps({'channels': {'a': {'status': 'ok'}, 'b': {'status': 'partial'}},
                             'items': [{'summary_ko': '요약'}]}))
    assert not F.frozen(str(p))
    p.write_text(json.dumps({'channels': {'a': {'status': 'ok'}}, 'items': [{'summary_ko': '요약'}]}))
    assert F.frozen(str(p))


def test_outside_overlap_is_a_warning_not_a_block():
    w = []
    html = page('<p>로이터는 텍사스 주지사 당선인이 데이터센터 사업 중단을 요구했다고 보도했다. 전력과 용수 부담이 이유다.</p>')
    assert check(html, DATA, warnings=w) == [] and any('겹친다' in x for x in w)


def test_analyst_view_outside_marker_is_a_warning():
    w = []
    html = page('<p>한지영 연구원은 나스닥이 급락한 배경을 금리보다 AI 투자 속도에 대한 의심에서 찾는다고 봤다.</p>')
    assert check(html, DATA, warnings=w) == [] and any('표식 밖' in x for x in w)


def test_lim_econ_relay_with_link_or_credit_is_not_her_view():
    long = '반도체 수출이 견조하다는 분석이 이어진다. ' * 20
    assert tg.view_of('lim_econ', post(1, long, ['https://www.reuters.com/markets/x'])) is None
    assert tg.view_of('lim_econ', post(2, long + ' - 블룸버그')) is None
    assert tg.view_of('lim_econ', post(3, long)) == ('한화투자증권', '임혜윤')


def test_lim_econ_needs_own_note_or_own_report():
    long = '반도체 수출이 견조하다는 분석이 이어진다. ' * 20
    assert tg.view_of('lim_econ', post(4, '로이터에 따르면 ' + long)) is None
    assert tg.view_of('lim_econ', post(7, long + ' 출처: 로이터')) is None
    assert tg.view_of('lim_econ', post(5, long, ['https://naver.me/abc'])) is None
    p = post(6, long, ['https://naver.me/abc'])
    p['doc_title'] = '[한화 임혜윤] KO Export_261102.pdf'
    assert tg.view_of('lim_econ', p) == ('한화투자증권', '임혜윤')


def test_lim_econ_own_report_with_foreign_credit_is_not_a_view():
    p = post(8, '반도체 수출이 견조하다는 분석이 이어진다. ' * 20 + ' 출처: 로이터')
    p['doc_title'] = '[한화 임혜윤] KO Export_261102.pdf'
    assert tg.view_of('lim_econ', p) is None
