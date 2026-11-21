"""1a 「자료 누락 차단」을 두 번에 나눠 올린다(2026-11-20) — 스위치(`verification.inputs.EFFECTIVE`)가 None 인 동안
막는 판정은 하나도 켜지지 않는다. 이 모듈은 꺼진 상태(= 운영)에서 돈다.

실제 글·자료로 main 판과 견준 것은 레포 밖 대조 스크립트의 몫이고(계획 파일에 표), 여기는 그 가운데 다시 깨지기 쉬운
자리를 고정한다: 스위치가 한 곳인가, 꺼진 채 검사기·실행기·기록·재검사가 1a 전 판정을 내는가.
"""
import json
import os
import re
import subprocess
import sys

import pytest

from review import corrector, digest, style_pass
from verification import inputs as I

SCRIPTS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOT = os.path.dirname(SCRIPTS)
PAGE = '<html><body data-register="da"><main><section><h2>x</h2><p>본문이다.</p></section></main></body></html>'


def run(script, tmp_path, *args, name='2026-11-18.html', html=PAGE):
    h = tmp_path / name
    h.write_text(html, encoding='utf-8')
    return subprocess.run([sys.executable, os.path.join(SCRIPTS, script), '--html', str(h), *args],
                          capture_output=True, text=True, cwd=ROOT)


def test_the_switch_is_off_and_the_copies_agree():
    assert I.EFFECTIVE is None and I.strict_from() is None and I.enforcing() is False
    assert corrector.STRICT_FROM is None and style_pass.STRICT_FROM is None
    assert corrector._enforcing() is False and style_pass._enforcing() is False


def test_only_inputs_reads_the_date():
    """스위치 판정은 `inputs.enforcing()` 한 곳 — 다른 모듈이 `inputs.EFFECTIVE` 를 직접 보지 않는다."""
    bad = []
    for root, dirs, files in os.walk(SCRIPTS):
        dirs[:] = [d for d in dirs if d not in ('tests', '__pycache__')]
        for f in files:
            path = os.path.join(root, f)
            if f.endswith('.py') and os.path.relpath(path, SCRIPTS) != os.path.join('verification', 'inputs.py'):
                src = re.sub(r'#[^\n]*', '', open(path, encoding='utf-8').read())      # 주석은 뺀다
                if re.search(r'\b(?:I|inputs)\.EFFECTIVE\b|from verification\.inputs import[^\n]*\bEFFECTIVE\b', src):
                    bad.append(os.path.relpath(path, SCRIPTS))
    assert bad == []


def test_the_test_hook_can_only_turn_it_on(monkeypatch):
    monkeypatch.setenv(I.TEST_ENV, '')
    assert I.enforcing() is False                      # 빈 값은 켜지 않는다
    monkeypatch.setenv(I.TEST_ENV, '2026-11-17')
    assert I.enforcing() is True and I.strict_from() == '2026-11-17'
    monkeypatch.setattr(I, 'EFFECTIVE', '2026-12-01')  # 실제 날짜가 있으면 그것이 이긴다 — 환경 변수로 미루거나 끌 수 없다
    monkeypatch.setenv(I.TEST_ENV, '2099-01-01')
    assert I.strict_from() == '2026-12-01'
    monkeypatch.delenv(I.TEST_ENV)
    assert I.enforcing() is True


@pytest.mark.parametrize('path', ['posts/2026-11-16.html', 'posts/2026-11-19.html', 'kr/posts/2026-12-01.html',
                                  'posts/draft.html', '', None])
def test_every_post_gets_the_old_verdict_while_off(path):
    assert I.legacy_post(path) is True
    assert corrector.legacy_post(path) is True and corrector._legacy_post_copy(path) is True
    assert style_pass.legacy_post(path) is True and style_pass._legacy_post_copy(path) is True
    assert corrector.strict_for(path) is False and style_pass.strict_for(path) is False


def test_recheck_flags_are_not_passed_while_off():
    assert corrector._recheck('fund') == [] and corrector._recheck('numbers') == []
    assert style_pass._recheck() == [] and digest._recheck() == []
    cmds = style_pass.gate_commands('us', 'p.html', 'data', 'o.html', '2026-11-18', None)
    assert not any('--recheck' in c for c in cmds)


def test_run_gates_uses_the_v1_record_while_off(monkeypatch):
    import run_gates as G
    from verification import record, record2
    assert G.R is record and record.FORMAT == 'prepub-record/1' and record2.FORMAT == 'prepub-record/2'
    called = []
    monkeypatch.setattr(G, '_main1', lambda argv=None: called.append('v1') or 0)
    monkeypatch.setattr(G, '_main2', lambda argv=None: called.append('v2') or 0)
    G.main([])
    monkeypatch.setenv(I.TEST_ENV, '2026-11-17')
    G.main([])
    assert called == ['v1', 'v2']


PRE_1A_BLOB = '65c9890c'        # 1a 를 병합하기 전 main 의 record.py(c9af9a0b)
V1_BLOB = '9b6e6aaa'            # = 위 + 숫자 출처 검사(2026-11-22 사용자 승인 「고정 풀고 붙여」)


def test_v1_record_module_is_the_pre_1a_one_plus_number_sources():
    """`record.py` 는 1a 전 파일에 숫자 출처 검사(`result: sources`·`optional_argv`·ctx `first_html`·`contested`·
    us-news 경로)만 더한 판이다(2판은 `record2.py`). 바이트 동일 대신 아래 시험이 「기존 검사의 결과는 1a 전과 같다」를
    1a 전 blob 을 직접 불러 대조한다."""
    blob = subprocess.run(['git', 'hash-object', os.path.join(SCRIPTS, 'verification', 'record.py')],
                          capture_output=True, text=True, cwd=ROOT).stdout.strip()
    assert blob.startswith(V1_BLOB), blob


def _pre_1a_record(tmp_path):
    import importlib.util
    src = subprocess.run(['git', 'cat-file', 'blob', PRE_1A_BLOB], capture_output=True, cwd=ROOT)
    if src.returncode:
        pytest.skip('1a 전 blob 을 읽지 못했다(얕은 clone)')
    f = tmp_path / 'record_pre1a.py'
    f.write_bytes(src.stdout)
    spec = importlib.util.spec_from_file_location('record_pre1a', f)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_OUTS = [(0, '{"warnings": [], "violations": [], "counts": {"tokens_seen": 3}}', ''),
         (1, '{"warnings": ["w"], "violations": ["v /tmp/x"], "counts": {}}', ''),
         (0, '{"skipped": true}', ''), (0, 'ok\n', ''), (1, 'bad 2Y 4.478%\n', 'err'), (2, '', 'boom'), (0, '', '')]


def test_v1_record_gives_the_pre_1a_result_for_every_existing_gate(tmp_path):
    """실제 설정의 us·kr 검사기 전부(숫자 출처 검사 제외) × 출력 몇 꼴 — argv·상태·기록 칸이 1a 전 모듈과 같다."""
    from verification import record as new
    old = _pre_1a_record(tmp_path)
    cfg = json.load(open(os.path.join(ROOT, 'config', 'prepub_gates.json'), encoding='utf-8'))
    d = tmp_path / 'w'
    (d / 'sub').mkdir(parents=True)
    (d / 'market_data.json').write_text('{}', encoding='utf-8')
    (d / 'sub' / 'a.txt').write_text('x', encoding='utf-8')
    tg = tmp_path / 'tg.json'
    tg.write_text('{}', encoding='utf-8')
    ctx = {'html': str(tmp_path / 'p.html'), 'datadir': str(d), 'repo': ROOT, 'date': '2026-11-23', 'tg': str(tg),
           'stance_next': None, 'cycle': 'c1', 'tmp': str(tmp_path)}
    n = 0
    for market in ('us', 'kr'):
        assert new.repo_paths(market) == old.repo_paths(market)
        for spec in cfg['markets'][market]['gates']:
            if spec.get('result') == 'sources' or spec.get('optional_argv'):
                continue
            assert new._argv(spec, ctx) == old._argv(spec, ctx), spec['name']
            for code, out, err in _OUTS:
                a, b = {}, {}
                assert new._classify(spec, code, out, err, ctx, a) == old._classify(spec, code, out, err, ctx, b), spec['name']
                assert a == b, spec['name']
                n += 1
    assert n > 100
    assert new._inputs(ctx) == old._inputs(ctx)
    assert new._mask(f'{d}/x {tg} /abs/p', ctx) == old._mask(f'{d}/x {tg} /abs/p', ctx)


# ── 검사기: 켜면 미완료(2)인 자리가 꺼진 채로는 1a 전 판정 ─────────────────────────────

def test_missing_inputs_do_not_exit_2_while_off(tmp_path):
    d = tmp_path / 'data'
    d.mkdir()
    (d / 'market_data.json').write_text(json.dumps({'report_date': '2026-11-18'}))
    # 1a 전: 자료가 없으면 비-코어로 통과(0)
    for script, extra in (('check_movers.py', []), ('check_session.py', ['--market', 'us']),
                          ('check_price_context.py', []), ('check_fed.py', []), ('check_auction.py', []),
                          ('check_fund.py', ['--market', 'us']), ('check_sources.py', []),
                          ('check_liquidity.py', ['--repo', str(tmp_path)])):
        r = run(script, tmp_path, '--datadir', str(d), *extra)
        assert r.returncode == 0, (script, r.returncode, r.stdout[-300:], r.stderr[-300:])
    # 1a 전: macro_eval 이 없으면 위반(1) — 미완료(2)가 아니다
    r = run('check_weight.py', tmp_path, '--datadir', str(d), '--market', 'us')
    assert r.returncode == 1 and 'macro_eval.json을' in r.stdout
    # 1a 전: 텔레그램 입력이 없고 글에 표식이 없으면 통과
    r = run('check_telegram.py', tmp_path, '--tg', str(d / 'telegram.json'), '--date', '2026-11-18')
    assert r.returncode == 0, r.stderr


def test_the_same_inputs_exit_2_once_on(tmp_path, monkeypatch):
    monkeypatch.setenv(I.TEST_ENV, '2026-11-17')
    d = tmp_path / 'data'
    d.mkdir()
    (d / 'market_data.json').write_text(json.dumps({'report_date': '2026-11-18'}))
    for script, extra in (('check_movers.py', []), ('check_session.py', ['--market', 'us']),
                          ('check_price_context.py', []), ('check_fed.py', []), ('check_auction.py', []),
                          ('check_fund.py', ['--market', 'us']), ('check_sources.py', []),
                          ('check_liquidity.py', ['--repo', str(tmp_path)]),
                          ('check_weight.py', ['--market', 'us'])):
        r = run(script, tmp_path, '--datadir', str(d), *extra)
        assert r.returncode == 2, (script, r.returncode, r.stdout[-300:], r.stderr[-300:])


# ── 11/18 US 글의 실제 사례: 제외 지표 칸이 없는 자료 + 임시 고지 표식 ─────────────────────

def test_coverage_marker_without_coverage_data_is_not_judged_while_off(monkeypatch):
    """2026-11-18 US 글(4952eace) 재현 — 수집기는 아직 제외 지표 칸(coverage)을 쓰지 않고 작성자는 임시 고지(a2d45e48)로
    `data-axis-coverage` 표식을 쓴다. 꺼진 채로는 산출 범위 규칙이 돌지 않는다(1a 전에는 그 규칙이 없었다)."""
    from us import macro_gate as MG
    from us.tests.test_macro_coverage import _marker, section
    sec = section(' ' + _marker())
    doc = f'<html><body><main>{sec}</main></body></html>'
    judged = lambda: [x for x in MG.check(doc, None, None, None, metrics={'report_date': '2026-11-18'})  # noqa: E731
                      if '산출 범위' in x]
    assert judged() == []
    monkeypatch.setenv(I.TEST_ENV, '2026-11-17')
    assert len(judged()) == 1 and '빠진 지표가 없는데' in judged()[0]


def test_econ_row_without_previous_is_still_dropped_while_off(monkeypatch):
    """직전 변환값을 못 만드는 지표 — 꺼진 채로는 1a 전처럼 행을 뺀다(지표 목록·표가 달라지지 않는다)."""
    import collect_market_data as cmd
    vals = [('2026-07-01', 100.0), ('2026-08-01', 101.0), ('2026-10-01', 103.0)]
    assert cmd._econ_pair(vals, 'mom_pct') is None or cmd._econ_pair(vals, 'mom_pct')[1] is not None
    full = [('2026-06-01', 99.0), ('2026-07-01', 100.0), ('2026-08-01', 102.0), ('2026-10-01', 103.0)]
    assert cmd._econ_pair(full, 'mom_pct') is None


# ── codex 구현 검토(2026-11-20) C2·C4 ────────────────────────────────────────────

def test_kr_intraday_points_equal_the_pre_1a_function_even_for_a_malformed_last_bar():
    from kr import sources
    bars = [{'localDateTime': '20261120090000', 'currentPrice': 1}, {'localDateTime': 'x', 'currentPrice': 2}]
    # 1a 전: 짧은 봉은 순회에서 건너뛰지만 「마지막 봉 보장」은 원래 마지막 봉을 쓴다 — 그 점까지 같아야 한다
    assert sources.downsample_30min(bars) == [{'t': '09:00', 'close': 1.0}, {'t': ':', 'close': 2.0}]
    assert sources.dated_30min(bars) == ('2026-11-20', sources.downsample_30min(bars))
    assert sources.dated_30min([]) == (None, [])


def test_a_v1_record_is_not_read_with_v2_meanings():
    from review import prepub_view as V
    base = {'readable': True, 'verified': True, 'numbers': {'unverified': 0}}
    v1 = {'market': 'us', 'recorded': dict(base, status='verified', v2=False)}      # 1판에 없는 값 — 완료로 읽지 않는다
    assert V.fully_verified(v1) is False
    assert V._kr_no_numbers({'numbers_gate': 'na', 'v2': False}) == 'corrupt'
    assert V._kr_no_numbers({'numbers_gate': 'na', 'v2': True}) == 'na'
    assert V._kr_no_numbers({'numbers_gate': 'not_run'}) == 'not_run'


def test_a_v1_record_with_a_v2_verdict_name_shows_as_unknown(tmp_path):
    """codex 2회차 C4 — 1판 기록의 `summary.status` 가 2판 이름이면 1a 전처럼 「모르는 판정」으로 보인다."""
    from review import prepub_view as V
    from review.tests import prepub_fixture as F
    repo = F.init(tmp_path)
    F.publish(repo, workspace=False, summ=F.summary(status='verified'))
    v = V.view(str(repo), 'HEAD', 'us', '2026-11-09')
    assert v['recorded']['v2'] is False
    text = V.render_publish(v, who=V.GITHUB)
    assert '기록 판정 모르는 판정' in text and '검증됨' not in text
    assert '판정 모르는 판정' in '\n'.join(V.digest_lines(v))


def test_a_dropped_row_says_which_month_is_missing_while_off(monkeypatch):
    """꺼진 동안 직전 값이 없어 뺀 지표 — 산출 범위 문장이 「상태 확인 불가」가 아니라 없는 달과 그 상태를 말한다
    (12/10 무렵 11월 CPI 가 나오면 생긴다: 2026-11 전년 대비는 되는데 2026-10 전년 대비를 만들 2025-10 이 미발표)."""
    import collect_market_data as cmd
    vals = [(f'{y}-{m:02d}-01', 100.0 + i) for i, (y, m) in enumerate(
        [(2025, m) for m in range(8, 13) if m != 10] + [(2026, m) for m in range(1, 12)])]
    assert cmd._econ_pair(vals, 'yoy_pct') is None                      # 1a 전처럼 행을 뺀다
    got = cmd._previous_lacking(vals, 'yoy_pct', ['2025-10-01'])
    assert got == {'2025-10': 'not_published'}
    monkeypatch.setattr(cmd, 'ECON', [('Inflation', 'CPI YoY', 'CPIAUCSL', 'yoy_pct', '%')])
    monkeypatch.setattr(cmd, 'fred_series', lambda *a, **k: vals, raising=False)
    monkeypatch.setattr(cmd, 'fred_blanks', lambda sid: ['2025-10-01'])
    monkeypatch.setattr(cmd, 'fred_unclear', lambda sid: [])
    monkeypatch.setattr(cmd.time, 'sleep', lambda s: None)
    reasons, refs = {}, {}
    cmd.collect_econ(reasons, refs)
    assert reasons == {'CPI YoY': 'no_value'}
    assert refs['CPI YoY']['lacking'] == ['2025-10'] and refs['CPI YoY']['lacking_why'] == {'2025-10': 'not_published'}


def test_coverage_fields_are_written_only_once_on():
    """`macro_metrics.json` 의 `coverage`·`coverage_ko` 는 작성자가 읽는 파일에 새로 나타나는 칸이다 — 꺼진 동안은 싣지 않는다
    (2026-11-20 사용자 결정: 꺼진 동안 작성 입력은 1a 전과 같다). 수집기 본체는 네트워크 없이 돌릴 수 없어 호출 자리를 본다."""
    src = open(os.path.join(SCRIPTS, 'collect_market_data.py'), encoding='utf-8').read()
    calls = [m.start() for m in re.finditer(r'\bwith_coverage\(', src)]
    assert len(calls) == 1
    before = src[:calls[0]].splitlines()[-2]                 # 호출 줄(`mm = with_coverage(`)의 바로 윗줄
    assert before.strip() == 'if enforcing():'
    # 작성 지시문·오케스트레이터는 수집 상태 칸을 읽으라고 하지 않는다 — 그 칸은 꺼진 동안에도 실린다
    docs = os.path.join(ROOT, '.claude')
    for dp, _dn, fs in os.walk(docs):
        for f in fs:
            if f.endswith('.md'):
                text = open(os.path.join(dp, f), encoding='utf-8').read()
                assert '_collect_status' not in text and 'collected_at' not in text and '`collect`' not in text, f
