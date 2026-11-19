"""숫자 출처 검사가 기록 JSON → 건별 알림까지 닿는가(2026-11-20, 설계 §8.4). us-news 경로·옛 기록·합 검증 포함."""
import json
import os
import subprocess
import sys
from datetime import datetime

import pytest

from common import numsrc
from review import prepub_view as V
from review import publish_watch as W
from review.tests import prepub_fixture as F
from verification import record as R
from verification import repo_check as C

SCRIPTS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOT = os.path.dirname(SCRIPTS)
D = '2026-11-18'
MD = {'report_date': D, 'complete': True, 'missing': [],
      'indices': {'S&P 500': {'last': 7323.63, 'chg': -16.9, 'pct': -0.2302, 'date': D}}}
PAGE = ('<html><head><link rel="canonical" href="https://fdo2a.github.io/{url}/{d}.html"><title>t</title></head><body>'
        '<p>지수는 <span data-ref="md:indices.SP500.pct">-0.23%</span> 내렸고 0.5% 는 출처가 없다.</p></body></html>')


def _gate(market):
    return {'name': 'check_number_sources',
            'argv': ['scripts/check_number_sources.py', '--market', market, '--date', '{date}', '--html', '{html}',
                     '--datadir', '{datadir}', '--repo', '{repo}', '--effective', '2026-01-01'],
            'optional_argv': [['--first', '{first_html}']],
            'kind': 'numbers', 'required': False, 'json': True, 'result': 'sources'}


def _record(tmp_path, market='us'):
    """실제 `run_gates.py record` 를 돌려 기록 JSON 파일을 만든다."""
    ws = tmp_path / 'ws'
    ws.mkdir(exist_ok=True)
    (ws / 'market_data.json').write_text(json.dumps(MD), encoding='utf-8')
    url = 'posts' if market == 'us' else 'news'
    post = tmp_path / f'{D}.html'
    post.write_text(PAGE.format(url=url, d=D), encoding='utf-8')
    cfg = tmp_path / 'gates.json'
    cfg.write_text(json.dumps({'format': 'prepub-gates/1', 'markets': {
        market: {'post': url + '/{date}.html', 'gates': [_gate(market)]}}}), encoding='utf-8')
    out = tmp_path / 'rec.json'
    p = subprocess.run([sys.executable, os.path.join(SCRIPTS, 'run_gates.py'), 'record', '--market', market, '--date', D,
                        '--html', str(post), '--datadir', str(ws), '--repo', ROOT, '--config', str(cfg),
                        '--out', str(out)], capture_output=True, text=True, cwd=ROOT)
    assert p.returncode == 0, p.stdout + p.stderr
    with open(out, encoding='utf-8') as fh:
        return json.load(fh)


def _view(rec, market='us'):
    return {'market': market, 'date': D, 'kind': V.OK, 'record_commit': 'c', 'same_commit': True, 'why': [],
            'check': {'overall': C.MATCH, 'cats': {}, 'unknown': []}, 'corrections': None,
            'recorded': V.recorded(rec, [g['name'] for g in rec['gates']])}


SIX = '숫자: 숫자 2개 = 자료로 확인 1 · 기사와 일치 0 · 텔레그램 글과 일치 0 · 검색 발췌와 일치 0 · 세지 않은 숫자 0 · 확인 불가 1'


def test_record_json_to_publish_alert(tmp_path):
    rec = _record(tmp_path)
    text = V.render_publish(_view(rec))
    assert SIX in text
    assert '수정 이력 확인 불가' in text and V.SOURCE_LIMITS in text
    assert '검증 완료' not in text
    line = next(x for x in text.splitlines() if x.startswith('숫자: 숫자 '))
    nums = [int(x) for x in line.split('= ')[1].replace('·', ' ').split() if x.isdigit()]
    assert sum(nums) == 2


def test_us_news_record_reaches_alert(tmp_path):
    rec = _record(tmp_path, 'us-news')
    text = V.render_publish(_view(rec, 'us-news'))
    assert text.startswith('[발행] US 뉴스·산업 11/18') and SIX in text


def test_old_record_keeps_old_line():
    with open(os.path.join(ROOT, 'verification', 'us', '2026-11-18.json'), encoding='utf-8') as fh:
        rec = json.load(fh)
    v = _view(rec)
    assert v['recorded']['sources'] is None and v['recorded']['sources_gate'] is None
    scope = '\n'.join(V.scope_lines(v))
    assert '표 69칸·문장 24개 자동 대조' in scope and '숫자 출처' not in scope and '숫자 792개' not in scope


def _with_sources(rec, **kw):
    g = next(x for x in rec['gates'] if x['name'] == 'check_number_sources')
    g['sources'].update(kw)
    return rec


def test_bad_sum_is_not_shown_as_counts(tmp_path):
    rec = _record(tmp_path)
    bad = _with_sources(json.loads(json.dumps(rec)), counts=dict(
        next(x for x in rec['gates'] if x['name'] == 'check_number_sources')['sources']['counts'], total=5))
    v = _view(bad)
    assert v['recorded']['sources'] is None and v['recorded']['sources_bad'] is True
    text = V.render_publish(v)
    assert V.SOURCE_BAD in text and '숫자 5개' not in text
    # 표시 정규화는 판정을 바꾸지 않는다
    assert V.fingerprint(v) == V.fingerprint(_view(rec)) and V.anomalies(v) == V.anomalies(_view(rec))


def test_not_run_gate_says_cannot_check(tmp_path):
    rec = _record(tmp_path)
    g = next(x for x in rec['gates'] if x['name'] == 'check_number_sources')
    g['status'] = 'not_run'
    g.pop('sources')
    text = V.render_publish(_view(rec))
    assert '숫자 출처 검사 못 함(적용일 전 글이라 실행 안 함)' in text


def test_weight_and_style_warnings_left_out_of_publish_alert(tmp_path):
    rec = _record(tmp_path)
    rec['gates'] += [{'name': 'check_weight', 'status': 'warn', 'required': True,
                      'items': ['경고: 서술형 본문이 7101자다(평상시 4,000~6,000자)']},
                     {'name': 'check_style', 'status': 'warn', 'required': True, 'items': ['경고: 날수를 고유어로 썼다 — 「이틀」']}]
    rec['summary']['warned'] = ['check_weight', 'check_style']
    text = V.render_publish(_view(rec))
    assert '분량' not in text and '이틀' not in text and '서술형 본문' not in text


# ── publish_watch 까지 ──

NEWS_CFG = {'format': R.CONFIG_FORMAT, 'markets': dict(F.CONFIG['markets'], **{
    'us-news': {'post': 'news/{date}.html', 'gates': [{'name': 'check_number_sources', 'script': 'scripts/g1.py'}]}})}


def _news_publish(repo, date, rec_sources):
    F.write(repo, 'config/prepub_gates.json', json.dumps(NEWS_CFG))
    F.commit(repo, 'config')
    pp = f'news/{date}.html'
    body = '<p>뉴스</p>'
    F.write(repo, pp, body)
    digest, n = R.repo_digest(str(repo), 'us-news', pp, 'HEAD')
    rec = {'format': R.FORMAT, 'market': 'us-news', 'date': date, 'post': {'path': pp, 'sha256': F.sha(body)},
           'created_at': {'kst': f'{date}T09:00:00+09:00'},
           'repo_inputs': {'paths': R.repo_paths('us-news'), 'digest': digest, 'files': n}, 'inputs': {'files': []},
           'gates': [{'name': 'check_number_sources', 'argv': ['scripts/g1.py'], 'required': False, 'kind': 'numbers',
                      'script_sha256': F.sha(open(os.path.join(str(repo), 'scripts/g1.py'), 'rb').read()),
                      'status': 'pass', 'exit': 0, 'sources': rec_sources}],
           'summary': F.summary(), 'code': {'python': '3.11.9'}}
    F.write(repo, R.record_path('us-news', date), json.dumps(rec, ensure_ascii=False))
    return F.commit(repo, f'Add news {date}')


def _sources():
    c = {'table': 0, 'data': 1, 'article': 2, 'telegram': 0, 'web': 0, 'excluded': 0, 'unknown': 1, 'total': 4}
    return {'counts': c, 'runs': dict(c), 'history': 'unverifiable', 'detail': {}, 'unknown': [], 'unknown_total': 1}


def test_us_news_publish_event_through_step(tmp_path, monkeypatch):
    monkeypatch.setattr(numsrc, 'EFFECTIVE', '2026-11-09')
    repo = F.init(tmp_path)
    _news_publish(repo, '2026-11-09', _sources())
    st = W.step(W.new_state('처음'), str(repo), datetime(2026, 11, 9, 20, 0, tzinfo=W.KST), True, ref='HEAD')
    ev = [e for e in st['events'] if e['kind'] == 'publish' and e['key'] == 'news/2026-11-09.html']
    assert len(ev) == 1
    assert ev[0]['text'].startswith('[발행] US 뉴스·산업 11/09') and '숫자 4개 = 자료로 확인 1 · 기사와 일치 2' in ev[0]['text']
    # 세션 감시(미발행)는 us·kr 만 — us-news 세션 열쇠가 없다
    assert not any(k.startswith('us-news:') for k in st['sessions'])


def test_news_post_before_start_is_not_a_target(tmp_path, monkeypatch):
    monkeypatch.setattr(numsrc, 'EFFECTIVE', '2026-11-10')
    repo = F.init(tmp_path)
    _news_publish(repo, '2026-11-09', _sources())
    st = W.step(W.new_state('처음'), str(repo), datetime(2026, 11, 9, 20, 0, tzinfo=W.KST), True, ref='HEAD')
    assert not [e for e in st['events'] if 'news/' in e.get('key', '')]
    assert V.target_of('news/2026-11-09.html') is None and V.target_of('news/2026-11-10.html') == ('us-news', '2026-11-10')


def test_news_targets_start_at_numsrc_effective(monkeypatch):
    # 뉴스 글 기록·알림은 숫자 출처 검사 적용일(자리표시 상수 — 병합 뒤 첫 발행일로 바꾼다)부터
    monkeypatch.setattr(numsrc, 'EFFECTIVE', '2026-11-19')
    assert V.target_of('news/2026-11-18.html') is None and V.target_of('news/2026-11-19.html') == ('us-news', '2026-11-19')
    assert V.target_of('posts/2026-11-18.html') == ('us', '2026-11-18')


def test_digest_line_uses_sources_when_present(tmp_path):
    from review import digest as DG
    v = _view(_record(tmp_path))
    lines = DG._show_prepub({'prepub': v, 'path': f'posts/{D}.html'})
    assert ' · [발행 전 기록] 숫자 2개 중 확인 불가 1개(숫자 출처 검사)' in lines
    assert not any('완료' in x and '숫자 출처' in x for x in lines)
