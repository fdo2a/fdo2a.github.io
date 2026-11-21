"""검사기 자체의 「자료 없음 → 미완료(exit 2)」 — 실행기의 사전 확인과 겹치는 둘째 겹 (2026-11-17 1a).

실행기(run_gates)는 입력이 정상이 아니면 검사기를 돌리지 않으므로, 변이 시험만으로는 검사기가 고쳐졌는지 알 수
없다. 여기서 검사기를 직접 돌린다. 전에는 이 경우들이 「nothing to check」·「섹션 없이 발행」·경고로 exit 0 이었다.
"""
import json
import os
import subprocess
import sys

import pytest

SCRIPTS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
D = '2026-11-16'
PAGE = '<html><body><main><h2>주식</h2><p>본문</p></main></body></html>'


def run(script, tmp_path, *args, html=PAGE, name=f'{D}.html'):
    h = tmp_path / name
    h.write_text(html, encoding='utf-8')
    return subprocess.run([sys.executable, os.path.join(SCRIPTS, script), '--html', str(h), *args],
                          capture_output=True, text=True, cwd=os.path.dirname(SCRIPTS))


def put(d, rel, obj):
    p = d / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False), encoding='utf-8')


@pytest.fixture
def d(tmp_path):
    x = tmp_path / 'data'
    x.mkdir()
    put(x, 'market_data.json', {'report_date': D})
    return x


def test_movers(tmp_path, d):
    assert run('check_movers.py', tmp_path, '--datadir', str(d)).returncode == 2           # 자료 없음
    put(d, 'movers.json', {'report_date': '2026-11-13', 'groups': [{'id': 'g1'}]})
    assert run('check_movers.py', tmp_path, '--datadir', str(d)).returncode == 2           # 다른 날
    put(d, 'movers.json', '{')
    assert run('check_movers.py', tmp_path, '--datadir', str(d)).returncode == 2           # 깨짐
    put(d, 'movers.json', {'report_date': D, 'groups': []})
    r = run('check_movers.py', tmp_path, '--datadir', str(d))
    assert r.returncode == 0 and 'nothing to check' in r.stdout                           # 실행기가 na 를 따진다
    r = run('check_movers.py', tmp_path, '--datadir', str(d), html='<p data-mover="g1">현대건설 -7.77%</p>')
    assert r.returncode == 1                                                              # 없는 날 문단 = 위반


def test_auction(tmp_path, d):
    assert run('check_auction.py', tmp_path, '--datadir', str(d)).returncode == 2
    base = {'report_date': D, 'ok': True, 'error': None, 'pending': [], 'today': [], 'recent': [], 'next': []}
    for bad in (dict(base, ok=False), dict(base, error='HTTP 500'), dict(base, report_date='2026-11-13'),
                dict(base, pending=[{'label_ko': '10년물'}])):
        put(d, 'auctions.json', bad)
        r = run('check_auction.py', tmp_path, '--datadir', str(d))
        assert r.returncode == 2 and '미완료' in r.stderr, bad
    put(d, 'auctions.json', base)
    assert run('check_auction.py', tmp_path, '--datadir', str(d)).returncode == 0


def test_liquidity(tmp_path, d):
    args = ('--datadir', str(d), '--repo', str(tmp_path))
    assert run('check_liquidity.py', tmp_path, *args).returncode == 2
    for bad in ({'report_date': D, 'status': 'partial'}, {'report_date': '2026-11-13', 'status': 'complete'}):
        put(d, 'liquidity/liquidity.json', bad)
        assert run('check_liquidity.py', tmp_path, *args).returncode == 2, bad


def test_macro_without_books(tmp_path, d):
    r = run('check_macro.py', tmp_path, '--datadir', str(d))
    assert r.returncode == 2 and '미완료' in r.stderr


def test_price_context(tmp_path, d):
    r = run('check_price_context.py', tmp_path, '--datadir', str(d))       # price_context 블록 없음
    assert r.returncode == 2
    assert run('check_price_context.py', tmp_path, '--datadir', str(tmp_path / 'none')).returncode == 2


def test_session(tmp_path, d):
    assert run('check_session.py', tmp_path, '--datadir', str(d), '--market', 'us').returncode == 2
    assert run('check_session.py', tmp_path, '--datadir', str(d), '--market', 'kr').returncode == 2


def test_calendar(tmp_path, d):
    assert run('check_calendar.py', tmp_path, '--datadir', str(d)).returncode == 2
    for bad in ({'report_date': '2026-11-13', 'events': [], 'complete': True, 'missing': []},
                {'report_date': D, 'events': [], 'complete': False, 'missing': ['cpi']}, '{'):
        put(d, 'calendar.json', bad)
        assert run('check_calendar.py', tmp_path, '--datadir', str(d)).returncode == 2, bad


def test_fed(tmp_path, d):
    assert run('check_fed.py', tmp_path, '--datadir', str(d)).returncode == 2
    put(d, 'intraday.json', {})
    put(d, 'econ_indicators.json', {'indicators': []})
    put(d, 'fed/events.json', {'report_date': '2026-11-13', 'events': []})
    assert run('check_fed.py', tmp_path, '--datadir', str(d)).returncode == 2
    put(d, 'fed/events.json', {'report_date': D, 'events': [{'key': 'chair-1', 'fresh': True, 'tier': 1,
                                                            'sources': [{'ok': True}]}]})
    r = run('check_fed.py', tmp_path, '--datadir', str(d))
    assert r.returncode == 2 and 'chair-1' in r.stderr                    # 원문 파일이 없다
    put(d, 'fed/events.json', {'report_date': D, 'events': []})
    assert run('check_fed.py', tmp_path, '--datadir', str(d)).returncode == 0


def test_sources(tmp_path, d):
    assert run('check_sources.py', tmp_path, '--datadir', str(d)).returncode == 2
    assert run('check_sources.py', tmp_path, '--datadir', str(d), '--legacy-releases').returncode == 0


def test_telegram_brief_and_news(tmp_path):
    tg = tmp_path / 'telegram.json'
    r = run('check_telegram.py', tmp_path, '--tg', str(tg), '--date', D)
    assert r.returncode == 2
    tg.write_text(json.dumps({'report_date': '2026-11-13', 'items': []}))
    assert run('check_telegram.py', tmp_path, '--tg', str(tg), '--date', D).returncode == 2
    tg.write_text(json.dumps({'report_date': D, 'items': []}))
    assert run('check_telegram.py', tmp_path, '--tg', str(tg), '--date', D).returncode == 0
    # 뉴스 글은 일부러 없는 경로를 받는다(KR_ORCHESTRATOR 0-2) — 그대로 통과
    news = tmp_path / 'news.json'
    news.write_text(json.dumps({'report_date': D, 'items': []}))
    r = run('check_telegram.py', tmp_path, '--tg', str(tmp_path / 'x.none'), '--date', D, '--layout', 'news',
            '--news', str(news))
    assert r.returncode == 0


def test_weight(tmp_path, d):
    assert run('check_weight.py', tmp_path, '--datadir', str(d), '--market', 'us').returncode == 2   # macro_eval 없음
    assert run('check_weight.py', tmp_path, '--datadir', str(d), '--market', 'kr').returncode == 2   # kr 시장 없음


def test_fund(tmp_path, d):
    assert run('check_fund.py', tmp_path, '--datadir', str(d), '--market', 'us').returncode == 2
    for bad in ({'report_date': D, 'status': 'partial'}, {'report_date': '2026-11-13', 'status': 'ok'},
                {'report_date': D, 'status': 'unavailable'}):
        put(d, 'fund_board.json', bad)
        r = run('check_fund.py', tmp_path, '--datadir', str(d), '--market', 'us')
        assert r.returncode == 2 and '미완료' in r.stderr, bad
    # 적용일 전 글은 자료 없이도 검사하지 않는다(그대로)
    assert run('check_fund.py', tmp_path, '--datadir', str(tmp_path / 'none'), '--market', 'us',
               name='2026-09-01.html').returncode == 0


def test_kr_stance(tmp_path, d):
    nxt = tmp_path / 'next.json'
    nxt.write_text('{}')
    r = run('check_kr_stance.py', tmp_path, '--datadir', str(d), '--next', str(nxt))
    assert r.returncode == 2 and 'kr_stance_eval.json' in r.stderr


def test_numbers_kr_optional_inputs(tmp_path):
    k = tmp_path / 'kr'
    k.mkdir()
    put(k, 'kr_market_data.json', {'report_date': D})
    put(k, 'kr_flows.json', {})
    put(k, 'kr_top_value.json', [])
    r = run('check_numbers.py', tmp_path, '--datadir', str(k), '--market', 'kr', '--date', D)
    assert r.returncode == 2 and 'kr_intraday.json' in r.stderr


def test_numbers_config_unreadable(monkeypatch):
    sys.path.insert(0, SCRIPTS)
    import check_numbers as CN
    monkeypatch.setattr(CN, 'CONFIG', '/nonexistent/number_audit.json')
    with pytest.raises(CN.ConfigMissing):
        CN._mode(None)
    assert CN._mode('block') == 'block'


def test_recheck_keeps_the_old_rule_for_past_posts(tmp_path, d):
    # 정정기·윤문기·매일 알림이 지난 글을 그 커밋 자료로 다시 볼 때 — 그때 없던 자료로 원본부터 2 가 되면 정정이 막힌다
    put(d, 'fund_board.json', {'report_date': D, 'status': 'partial'})
    assert run('check_fund.py', tmp_path, '--datadir', str(d), '--market', 'us').returncode == 2
    put(d, 'fund_board.json', {'report_date': D, 'status': 'unavailable'})
    assert run('check_fund.py', tmp_path, '--datadir', str(d), '--market', 'us', '--recheck').returncode == 0
    k = tmp_path / 'kr'
    k.mkdir()
    put(k, 'kr_market_data.json', {'report_date': D})
    put(k, 'kr_flows.json', {})
    put(k, 'kr_top_value.json', [])
    r = run('check_numbers.py', tmp_path, '--datadir', str(k), '--market', 'kr', '--date', D, '--recheck')
    assert 'kr_intraday.json' not in r.stderr, r.stderr          # 옛 판정 — 선택 자료가 없어도 그 이유로 2 가 아니다


def test_publish_config_never_passes_recheck():
    cfg = json.load(open(os.path.join(os.path.dirname(SCRIPTS), 'config', 'prepub_gates.json'), encoding='utf-8'))
    for m in cfg['markets'].values():
        for g in m['gates']:
            assert '--recheck' not in (g.get('argv') or []), g['name']
