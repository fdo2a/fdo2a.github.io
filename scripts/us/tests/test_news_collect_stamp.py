"""US 뉴스 수집 파일의 수집 상태 표시(2026-11-22) — 1a 를 켜면 US 뉴스 글의 gate 자료 `news/{date}.json` 은
collect 칸과 장부의 run(written·skipped·kept)이 있어야 막히지 않는다. 설계: 숫자 출처 spec §13·검토 기록 plans/.
"""
import json
import os
import subprocess
import sys

import pytest

import fetch_news as F
import stamp_collect as S
from verification import inputs as I

SCRIPTS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOT = os.path.dirname(SCRIPTS)
D = '2026-11-23'


def _payload(items, notes=()):
    return {'report_date': D, 'harvested': 10, 'notes': list(notes), 'items': items, 'region_filter': {}, 'funnel': {}}


def test_a_normal_day_is_ok_and_has_the_shape_the_gate_reads():
    c = F.news_collect(_payload([{'guid': 'a', 'summary_ko': '요약'}]), final=True, feeds_read=12)
    assert c['status'] == 'ok' and c['as_of'] == D and c['empty'] == 'has_data' and c['required_ok'] is True
    assert I._stamp_ok_shape(c)


def test_first_save_before_summaries_is_failed():
    c = F.news_collect(_payload([{'guid': 'a'}]), final=False)
    assert c['status'] == 'failed' and 'running' in c['response']


def test_no_rss_feed_read_is_failed_even_with_items_from_pages():
    """기관 목록(피드 없는 출처)만 읽은 날 — harvested 는 0 이 아니어도 수집이 된 것이 아니다(검토 1회차 #3)."""
    c = F.news_collect(_payload([{'guid': 'boj', 'summary_ko': '요약'}]), final=True, feeds_read=0)
    assert c['status'] == 'failed'


def test_items_without_any_summary_is_failed():
    c = F.news_collect(_payload([{'guid': 'a'}, {'guid': 'b'}]), final=True, feeds_read=5)
    assert c['status'] == 'failed' and c['missing'] == ['summary:all']


def test_feed_failures_and_partial_summaries_stay_ok_with_a_detail():
    c = F.news_collect(_payload([{'guid': 'a', 'summary_ko': '요'}, {'guid': 'b'}], notes=['x: HTTP 403']),
                       final=True, feeds_read=5)
    assert c['status'] == 'ok' and '메모 1건' in c['detail'] and '요약 1/2건' in c['detail']


def test_no_items_after_reading_feeds_is_confirmed_none():
    c = F.news_collect(_payload([]), final=True, feeds_read=5)
    assert c['status'] == 'ok' and c['empty'] == 'confirmed_none'


def _ok_stamp(items=({'guid': 'a', 'summary_ko': '요약', 'body_chars': 100},)):
    return F.news_collect(_payload(list(items)), final=True, feeds_read=3)


BAD_STAMPS = [{'status': 'failed'}, {'status': 'partial'}, 'null', 'ok', [], {}, {'status': 'ok'},
              'stale', 'both_stale', 'required_false', 'missing', 'empty_mismatch', 'running']


def _stamp_case(name):
    """이름 → collect 값. 'absent' 는 칸이 없는 옛 파일."""
    if not isinstance(name, str):
        return name
    ok = _ok_stamp()
    return {'null': None, 'ok': 'ok', 'good': ok,
            'stale': dict(ok, as_of='2026-11-20'), 'required_false': dict(ok, required_ok=False),
            'missing': dict(ok, missing=['x']), 'empty_mismatch': dict(ok, empty='confirmed_none'),
            'running': F.news_collect(_payload([]), final=False)}[name]


def _write_day(p, name):
    body = _payload([{'guid': 'a', 'summary_ko': '요약', 'body_chars': 100}])
    if name == 'both_stale':        # 파일 안의 두 날짜가 함께 옛 날 — 게이트는 발행일과 견준다(구현 검토 3회차 #4)
        body['report_date'] = '2026-11-20'
        body['collect'] = dict(_ok_stamp(), as_of='2026-11-20')
    elif name != 'absent':
        body['collect'] = _stamp_case(name)
    p.write_text(json.dumps(body, ensure_ascii=False), encoding='utf-8')


@pytest.mark.parametrize('name,unfinished', [('absent', False), ('good', False)] + [(b, True) for b in BAD_STAMPS])
def test_a_file_whose_stamp_is_not_ok_is_not_frozen(tmp_path, name, unfinished):
    """collect 칸이 있는데 게이트가 통과시킬 끝난 도장이 아니면 동결하지 않는다 — 요약 단계에서 죽은 판(검토 1회차 #4),
    null·글자·빈 객체·status 만 있는 반쪽·as_of 어긋남(구현 검토 2회차 #4). 칸이 없는 옛 파일만 그대로 동결."""
    p = tmp_path / 'n.json'
    _write_day(p, name)
    assert F.stamp_unfinished(str(p), D) is unfinished


def test_a_frozen_stamp_is_one_the_gate_passes(tmp_path, monkeypatch):
    """동결되는 도장(끝난 것)은 1a 를 켠 게이트에서도 ok 다 — 「동결됐는데 게이트는 막는」 길이 없다."""
    monkeypatch.setattr(I, 'EFFECTIVE', D)
    pol = I.load(os.path.join(ROOT, 'config', 'prepub_inputs.json'))
    ctx = _news_day(tmp_path, _ok_stamp(), 'kept')
    f = os.path.join(ctx['datadir'], 'news', f'{D}.json')
    assert F.frozen(f) and not F.stamp_unfinished(f, D)
    assert I.assess(pol, 'us-news', ctx)['files'][f'<datadir>/news/{D}.json']['state'] == 'ok'


def test_the_news_file_is_tracked_by_the_news_step_and_may_be_kept():
    assert S.STEP_OF['us']['news/{D}.json'] == 'news'
    assert 'news/{D}.json' in S.MAY_KEEP
    run = {'open': True, 'started_at': '2026-11-24T00:00:00+00:00', 'run_id': 'r1'}
    # 동결된 날 — 단계는 성공, 파일은 다시 쓰이지 않았다 → kept
    st, _ = S.run_state('us', 'news/{D}.json', f'news/{D}.json', '/nope', '2026-11-23T23:00:00+00:00', run,
                        {'news': {'outcome': 'success'}}, run_id='r1')
    assert st == 'kept'
    # 단계가 실패했고 파일이 다시 쓰이지 않았다 → failed
    st, _ = S.run_state('us', 'news/{D}.json', f'news/{D}.json', '/nope', '2026-11-23T23:00:00+00:00', run,
                        {'news': {'outcome': 'failure'}}, run_id='r1')
    assert st == 'failed'
    # 이번 실행이 썼다 → written
    st, _ = S.run_state('us', 'news/{D}.json', f'news/{D}.json', '/nope', '2026-11-24T00:05:00+00:00', run,
                        {'news': {'outcome': 'success'}}, run_id='r1')
    assert st == 'written'


@pytest.mark.parametrize('market', ['us', 'kr'])
def test_contested_is_refused_outside_us_news(tmp_path, market):
    h = tmp_path / f'{D}.html'
    h.write_text('<html></html>', encoding='utf-8')
    c = tmp_path / 'contested.json'
    c.write_text('{}', encoding='utf-8')
    p = subprocess.run([sys.executable, os.path.join(SCRIPTS, 'run_gates.py'), 'check', '--market', market,
                        '--date', D, '--html', str(h), '--datadir', str(tmp_path), '--contested', str(c)],
                       capture_output=True, text=True, cwd=ROOT)
    assert p.returncode == 2 and '--contested' in p.stderr


def _news_day(tmp_path, collect, run='written', sha_ok=True):
    import hashlib
    d = tmp_path / 'ws'
    (d / 'news').mkdir(parents=True)
    body = _payload([{'guid': 'a', 'summary_ko': '요약'}])
    if collect is not None:
        body['collect'] = collect
    f = d / 'news' / f'{D}.json'
    f.write_text(json.dumps(body, ensure_ascii=False), encoding='utf-8')
    sha = hashlib.sha256(f.read_bytes()).hexdigest() if sha_ok else '0' * 64
    (d / '_collect_status.json').write_text(json.dumps(
        {'report_date': D, 'run_id': 'r1', 'files': {f'news/{D}.json': {'present': True, 'sha256': sha, 'run': run}}}),
        encoding='utf-8')
    c = tmp_path / 'contested.json'
    c.write_text('{}', encoding='utf-8')
    return {'datadir': str(d), 'date': D, 'contested': str(c), 'tg': str(tmp_path / 'none.json')}


@pytest.mark.parametrize('collect,run,state', [
    ('ok', 'written', 'ok'), ('ok', 'kept', 'ok'), ('ok', 'untracked', 'unstamped'),
    ('failed', 'written', 'failed'), (None, 'written', 'unstamped')])
def test_us_news_input_with_1a_on(tmp_path, monkeypatch, collect, run, state):
    """1a 를 켠 날 US 뉴스 글의 뉴스 자료 판정 — 정상 수집·동결은 통과, 실행 미상·실패·표시 없음은 막는다."""
    monkeypatch.setattr(I, 'EFFECTIVE', D)
    c = None if collect is None else (F.news_collect(_payload([{'guid': 'a', 'summary_ko': '요약'}]), True, 3)
                                      if collect == 'ok' else F.news_collect(_payload([]), False))
    pol = I.load(os.path.join(ROOT, 'config', 'prepub_inputs.json'))
    h = I.assess(pol, 'us-news', _news_day(tmp_path, c, run))
    got = h['files'][f'<datadir>/news/{D}.json']['state']
    assert got == state, h['files'][f'<datadir>/news/{D}.json']


EMPTY_RSS = '<?xml version="1.0"?><rss><channel><title>x</title></channel></rss>'
HTML_503 = '<html><body>503 Service Unavailable</body></html>'
HTML_WITH_CHANNEL = '<html><body>503 Service Unavailable <channel>maintenance</channel></body></html>'   # 2회차 반례
HTML_WITH_ITEM = '<!DOCTYPE html><html><body><item><title>t</title><link>https://x.test/a</link></item></body></html>'
ITEM = '<item><title>t</title><link>https://x.test/a</link></item>'
RSS_ITEM = f'<?xml version="1.0" encoding="ISO-8859-1"?>\n<rss version="2.0"><channel>{ITEM}</channel></rss>'
RSS_BROKEN_BODY = f'\ufeff\n<rss><channel>{ITEM}<item><title>a & b &nbsp;</title></channel>'        # 본문이 깨진 진짜 피드
RDF_ITEM = f'<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"><channel/>{ITEM}</rdf:RDF>'
ATOM_ENTRY = ('<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>1</id><title>t</title>'
              '<link href="https://x.test/a"/></entry></feed>')
ATOM_EMPTY = '<feed xmlns="http://www.w3.org/2005/Atom"><title>x</title></feed>'       # 형식 경고 — 읽은 것이 아니다
NS_ITEM = '<rss><channel><x:item><link>https://x.test/a</link></x:item></channel></rss>'   # 형식 경고
TEXT_RSS = '503 Service Unavailable <rss><channel></channel></rss>'
RSS_COMMENT_503 = '<rss><!-- <channel> --><error>503 maintenance</error></rss>'          # 3회차 반례 — 채널 없는 오류 문서
RSS_CUT_NO_ITEM = '<rss><channel><title>provider'                                         # 3회차 반례 — 기사 전에 잘린 응답
# 알려진 한계(11/22): 「읽음」= 루트 + 파서(정규식)가 기사를 1건 이상 냄. 주석 속 <item> 도 파서는 기사로 낸다 — 검사를 더하지 않는다
RSS_COMMENT_ITEM = f'<rss><!-- {ITEM} --><error>503</error></rss>'
RSS_CUT_AFTER_ITEM = f'<rss><channel><title>provider</title>{ITEM}<item><title>cu'        # 잘렸지만 기사 한 건은 받았다


@pytest.mark.parametrize('raw,read', [
    (RSS_ITEM, True), (RSS_BROKEN_BODY, True), (RDF_ITEM, True), (ATOM_ENTRY, True), (RSS_CUT_AFTER_ITEM, True), (RSS_COMMENT_ITEM, True),
    (EMPTY_RSS, False), (RSS_COMMENT_503, False), (RSS_CUT_NO_ITEM, False), (HTML_503, False), (HTML_WITH_CHANNEL, False), (HTML_WITH_ITEM, False), (ATOM_EMPTY, False), (NS_ITEM, False),
    (TEXT_RSS, False), ('', False), ('   ', False), (None, False)])
def test_rss_read_counts_a_real_feed_only(raw, read):
    """루트 요소가 피드(rss·feed·RDF)이고 기사가 한 건 이상 뽑힌 것만 읽은 것(2026-11-22 사용자 결정) — 빈 RSS,
    rss 루트의 오류 문서, 기사 전에 잘린 응답은 아니다. 잘렸어도 기사가 뽑혔으면 읽은 것. html 루트는 안에
    <channel>·<item> 이 있어도 아니다(codex 구현 검토 1회차 #1·#3, 2회차 #3, 3회차 #3)."""
    from us import news as N
    items, why = N.parse_feed_strict(raw, 'economy') if raw is not None else ([], None)
    assert F.rss_read(raw, items, why) is read


def test_html_with_items_is_harvested_but_not_counted_as_a_feed():
    """항목이 뽑혔어도(html 안의 <item>) 피드 수에는 들지 않는다 — 그런 응답만 온 날은 failed."""
    from us import news as N
    items, why = N.parse_feed_strict(HTML_WITH_ITEM, 'economy')
    assert items and not F.rss_read(HTML_WITH_ITEM, items, why)
    c = F.news_collect(_payload([{'guid': 'a', 'summary_ko': '요약'}]), final=True, feeds_read=0)
    assert c['status'] == 'failed'


def test_harvest_extra_counts_feeds_through_the_counter():
    pages = {'u1': EMPTY_RSS, 'u2': HTML_503, 'u3': '', 'u4': HTML_WITH_CHANNEL, 'u5': RSS_COMMENT_503,
             'u6': RSS_CUT_NO_ITEM}
    counter, notes = {}, []
    rows = F.harvest_extra(None, F.Budget(60), notes, fetch=lambda u, ctx: pages[u], feeds={'economy': list(pages)},
                           counter=counter)
    assert rows == [] and counter == {}                 # 기사가 뽑힌 피드가 없다
    pages.update(u7=RSS_ITEM, u8=HTML_WITH_ITEM)
    counter = {}
    rows = F.harvest_extra(None, F.Budget(60), notes, fetch=lambda u, ctx: pages[u], feeds={'economy': list(pages)},
                           counter=counter)
    assert rows and counter == {'read': 1}              # html 안의 <item> 은 행으로는 들어와도 세지 않는다


class _Stop(Exception):
    pass


@pytest.mark.parametrize('name,frozen_out', [('good', True), ('absent', True)] + [(b, False) for b in BAD_STAMPS])
def test_main_freezes_only_a_finished_file(tmp_path, monkeypatch, name, frozen_out):
    """main() 의 동결 분기 — collect 칸이 있는데 끝난 도장이 아닌 판(failed·null·글자·반쪽)은 다시 받는다
    (받으러 가면 _context 가 불린다)."""
    (tmp_path / 'news').mkdir()
    _write_day(tmp_path / 'news' / f'{D}.json', name)
    monkeypatch.setattr(F, '_context', lambda: (_ for _ in ()).throw(_Stop()))
    monkeypatch.setattr(sys, 'argv', ['fetch_news.py', '--datadir', str(tmp_path), '--date', D,
                                      '--bodydir', str(tmp_path / 'b')])
    if frozen_out:
        assert F.main() == 0
    else:
        with pytest.raises(_Stop):
            F.main()


@pytest.mark.parametrize('where', ['base', 'extra'])
@pytest.mark.parametrize('raw,status,empty', [
    (HTML_WITH_ITEM, 'failed', None), (HTML_WITH_CHANNEL, 'failed', None), ('', 'failed', None),
    (EMPTY_RSS, 'failed', None), (RSS_COMMENT_503, 'failed', None), (RSS_CUT_NO_ITEM, 'failed', None),
    (RSS_ITEM, 'ok', 'confirmed_none'), (RSS_CUT_AFTER_ITEM, 'ok', 'confirmed_none')])
def test_main_final_stamp_follows_the_feeds_actually_read(tmp_path, monkeypatch, raw, status, empty, where):
    """main() 을 끝까지 돌려 **저장된** 도장을 본다 — html·빈 RSS·rss 루트의 오류 문서·기사 전에 잘린 응답만 받은
    날은 failed, 기사가 뽑힌 피드를 읽은 날은 ok(고른 기사가 없으니 없음 확인). 구현 검토 3회차 #9: feeds_read 를
    손으로 넣는 시험은 main 의 셈을 지키지 못한다. 빈 RSS 는 11/22 사용자 결정으로 ok → failed.
    `where`: 그 응답이 기본 피드로만 / 새 매체 피드로만 온 날 — 두 셈이 모두 main 의 도장에 닿는지 본다."""
    monkeypatch.setattr(F, 'FEEDS', {'economy': ['https://f.test/rss']} if where == 'base' else {})
    monkeypatch.setattr(F, 'EXTRA_FEEDS', {'economy': ['https://f.test/rss']} if where == 'extra' else {})
    monkeypatch.setattr(F, '_fast_get', lambda url, ctx, **kw: raw)
    monkeypatch.setattr(F, 'GAP', 0)
    monkeypatch.setattr(F, '_context', lambda: None)
    monkeypatch.setattr(F, 'get', lambda url, ctx, **kw: raw)
    monkeypatch.setattr(F, 'pages', lambda year: {})
    monkeypatch.setattr(F, 'apply_region_filter', lambda rows, exempt=None: (rows, {}))
    monkeypatch.setattr(F, 'select', lambda rows, **kw: [])
    monkeypatch.setattr(F, 'fetch_bodies', lambda *a, **kw: None)
    monkeypatch.setattr(F, 'spread_stage', lambda *a, **kw: ([], {'stopped': []}, None))
    monkeypatch.setattr(F, 'summarize_chosen', lambda chosen, bodydir: 0)
    monkeypatch.setattr(F, 'write_numbers', lambda *a, **kw: None)
    monkeypatch.setattr(sys, 'argv', ['fetch_news.py', '--datadir', str(tmp_path), '--date', D,
                                      '--bodydir', str(tmp_path / 'b')])
    F.main()
    c = json.loads((tmp_path / 'news' / f'{D}.json').read_text(encoding='utf-8'))['collect']
    assert c['status'] == status
    if empty:
        assert c['empty'] == empty and I._stamp_ok_shape(c)
