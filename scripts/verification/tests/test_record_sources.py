"""숫자 출처 검사를 발행 전 기록으로(2026-11-20) — `sources` 갈래, 합 재검산, 선택 인자, us-news 경로."""
import json
import os

from verification import record as R

SCRIPTS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOT = os.path.dirname(SCRIPTS)
D = '2026-11-18'
MD = {'report_date': D, 'complete': True, 'missing': [],
      'indices': {'S&P 500': {'last': 7323.63, 'chg': -16.9, 'pct': -0.2302, 'date': D}}}
BODY = ('<html><head><link rel="canonical" href="https://fdo2a.github.io/{url}/{d}.html"><title>t</title></head>'
        '<body><p>지수는 <span data-ref="md:indices.SP500.pct">-0.23%</span> 내렸고 0.5% 는 모른다.</p></body></html>')


def _cfg(tmp_path, market='us'):
    gate = {'name': 'check_number_sources',
            'argv': ['scripts/check_number_sources.py', '--market', market, '--date', '{date}', '--html', '{html}',
                     '--datadir', '{datadir}', '--repo', '{repo}', '--effective', '2026-01-01'],
            'optional_argv': [['--tg', '{tg}'], ['--first', '{first_html}']],
            'kind': 'numbers', 'required': False, 'json': True, 'result': 'sources'}
    cfg = {'format': 'prepub-gates/1', 'disabled': {},
           'markets': {market: {'post': ('posts' if market == 'us' else 'news') + '/{date}.html', 'gates': [gate]}}}
    p = tmp_path / 'gates.json'
    p.write_text(json.dumps(cfg), encoding='utf-8')
    return R.load_config(str(p))


def _run(tmp_path, market='us', first=False):
    ws = tmp_path / 'ws'
    ws.mkdir(exist_ok=True)
    (ws / 'market_data.json').write_text(json.dumps(MD), encoding='utf-8')
    url = 'posts' if market == 'us' else 'news'
    post = tmp_path / 'post' / f'{D}.html'
    post.parent.mkdir(exist_ok=True)
    post.write_text(BODY.format(url=url, d=D), encoding='utf-8')
    ctx = dict(html=str(post), datadir=str(ws), repo=ROOT, date=D)
    if first:
        f = ws / 'numsrc_first.html'
        f.write_text(BODY.format(url=url, d=D).replace('<span data-ref="md:indices.SP500.pct">-0.23%</span>', '-0.23%'),
                     encoding='utf-8')
        ctx['first_html'] = str(f)
    return R.run_gates(_cfg(tmp_path, market), market, ctx, timeout=120, total=300)


def test_sources_recorded_and_status_does_not_change_verdict(tmp_path):
    r = _run(tmp_path)
    g = r['gates'][0]
    assert g['status'] == 'pass', g
    s = g['sources']
    assert s['counts']['data'] == 1 and s['counts']['unknown'] == 1 and s['counts']['total'] == 2
    assert s['history'] == 'unverifiable'            # 첫 판 없이 돌렸다 — 0 으로 적지 않는다
    assert 'numbers' not in g                        # 숫자 대조(check_numbers) 칸에 섞지 않는다
    assert r['summary']['status'] == 'pass' and r['summary']['verified'] is True and r['summary']['publish_ok']


def test_first_html_gives_history(tmp_path):
    g = _run(tmp_path, first=True)['gates'][0]
    h = g['sources']['history']
    assert h['first_unknown'] == 2 and h['fixed'] == 1 and h['still'] == 1
    assert g['sources']['first_sha256']


def test_us_news_market_runs(tmp_path):
    g = _run(tmp_path, market='us-news')['gates'][0]
    assert g['status'] == 'pass', g
    assert g['sources']['counts']['total'] == 2


def _obj(**kw):
    c = {'table': 0, 'data': 1, 'article': 0, 'telegram': 0, 'web': 0, 'excluded': 0, 'unknown': 1, 'total': 2}
    src = {'counts': dict(c), 'runs': dict(c), 'history': 'unverifiable', 'unknown': [{'text': '0.5% — x', 'why': '표식 없음'}]}
    src.update(kw)
    return {'skipped': False, 'warnings': [], 'violations': [], 'sources': src}


def _classify(obj, code=0):
    res = R._base({'name': 'check_number_sources'})
    st = R._classify({'json': True, 'result': 'sources'}, code, json.dumps(obj), '', {}, res)
    return st, res


def test_recount_bad_sum_is_indeterminate():
    c = {'table': 0, 'data': 1, 'article': 0, 'telegram': 0, 'web': 0, 'excluded': 0, 'unknown': 1, 'total': 3}
    st, res = _classify(_obj(counts=c))
    assert st == 'indeterminate' and 'sources' not in res
    st, _ = _classify(_obj(runs=dict(c, total=2, unknown='1')))
    assert st == 'indeterminate'
    st, _ = _classify(_obj(history={'first_unknown': 2, 'fixed': 0, 'gone': 0, 'still': 0, 'ambiguous': 0}))
    assert st == 'indeterminate'
    st, _ = _classify(_obj(), code=1)
    assert st == 'indeterminate'
    assert _classify(_obj())[0] == 'pass'


def test_skipped_before_effective_is_not_run():
    res = R._base({'name': 'check_number_sources'})
    st = R._classify({'json': True, 'result': 'sources'}, 0, json.dumps({'skipped': True}), '', {}, res)
    assert st == 'not_run'


def test_optional_argv_dropped_when_missing():
    spec = {'argv': ['x.py', '--html', '{html}'], 'optional_argv': [['--first', '{first_html}'], ['--tg', '{tg}']]}
    argv, missing = R._argv(spec, {'html': '/h', 'tg': '/t'})
    assert argv == ['x.py', '--html', '/h', '--tg', '/t'] and missing == []


def test_us_news_repo_paths():
    assert R.repo_paths('us-news') == ['scripts', 'config', 'research/us', 'posts']
    digest, n = R.repo_digest(ROOT, 'us-news', f'news/{D}.html', 'worktree')
    assert digest is not None and n > 0                # /news/ 가 gitignore 라 넣으면 다이제스트가 통째로 실패했다
    assert R.repo_paths('us') == ['scripts', 'config', 'research/us', 'posts']
    assert R.record_path('us-news', D) == f'verification/us-news/{D}.json'


def test_real_config_has_both_markets():
    cfg = R.load_config(os.path.join(ROOT, 'config', 'prepub_gates.json'))
    us = {g['name']: g for g in R.gates_of(cfg, 'us')}
    assert us['check_number_sources']['required'] is False and us['check_number_sources']['result'] == 'sources'
    news = [g['name'] for g in R.gates_of(cfg, 'us-news')]
    assert news[-1] == 'check_number_sources' and 'check_news' in news and 'check_contested' in news
    assert R.post_path(cfg, 'us-news', D) == f'news/{D}.html'
