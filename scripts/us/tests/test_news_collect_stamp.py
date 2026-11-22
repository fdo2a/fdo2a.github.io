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


@pytest.mark.parametrize('collect,unfinished', [(None, False), ({'status': 'ok'}, False),
                                                ({'status': 'failed'}, True), ({'status': 'partial'}, True)])
def test_a_file_whose_stamp_is_not_ok_is_not_frozen(tmp_path, collect, unfinished):
    """요약 단계에서 죽은 판(첫 저장의 failed)에 이월 요약이 있어도 다음 실행이 동결하지 않는다(검토 1회차 #4)."""
    p = tmp_path / 'n.json'
    body = _payload([{'guid': 'a', 'summary_ko': '요약', 'body_chars': 100}])
    if collect is not None:
        body['collect'] = collect
    p.write_text(json.dumps(body, ensure_ascii=False), encoding='utf-8')
    assert F.stamp_unfinished(str(p)) is unfinished


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
