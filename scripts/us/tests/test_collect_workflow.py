"""collect-market-data.yml: the two diagnostic inputs never run the collector.

The four dispatch combinations cannot be run in a unit test, so the job `if`s are read
from the YAML and evaluated with GitHub's rules for this grammar: a missing input
(schedule) is '', string comparison ignores case. Only
`github.event.inputs.X (==|!=) 'v'` joined by `&&` is accepted — anything else (an
`inputs.X` context, `||`, a function) fails the test rather than being guessed at.
"""
import os
import re

import pytest
import yaml

WF = os.path.join(os.path.dirname(__file__), '..', '..', '..', '.github', 'workflows',
                  'collect-market-data.yml')
ATOM = re.compile(r"^github\.event\.inputs\.([a-z_]+)\s*(==|!=)\s*'([^']*)'$")


def load():
    with open(WF, encoding='utf-8') as fh:
        return yaml.safe_load(fh)


def evaluate(expr, inputs):
    out = True
    for atom in (a.strip() for a in expr.split('&&')):
        if 'inputs.' in atom and 'github.event.inputs.' not in atom:
            raise AssertionError(f'bare inputs. context in job if: {atom}')
        m = ATOM.match(atom)
        if not m:
            raise AssertionError(f'unsupported expression in job if: {atom}')
        name, op, val = m.groups()
        got = str(inputs.get(name, '')).lower() == val.lower()
        out = out and (got if op == '==' else not got)
    return out


def jobs_on(inputs):
    jobs = load()['jobs']
    return {n for n, j in jobs.items() if 'if' not in j or evaluate(j['if'], inputs)}


@pytest.mark.parametrize('inputs, expected', [
    ({}, {'collect'}),                                                # schedule
    ({'fred_check': 'false', 'ff_probe': 'false'}, {'collect'}),
    ({'fred_check': 'true', 'ff_probe': 'false'}, {'fred_check'}),
    ({'fred_check': 'false', 'ff_probe': 'true'}, {'ff_probe'}),
    ({'fred_check': 'true', 'ff_probe': 'true'}, {'fred_check'}),
])
def test_workflow_job_matrix(inputs, expected):
    assert jobs_on(inputs) == expected


def test_evaluator_refuses_bare_inputs_context():
    with pytest.raises(AssertionError):
        evaluate("inputs.ff_probe != 'true'", {})


def test_diagnostic_jobs_have_no_write_steps():
    jobs = load()['jobs']
    for name in ('fred_check', 'ff_probe'):
        job = jobs[name]
        assert job['permissions'] == {'contents': 'read'}
        text = yaml.safe_dump(job['steps'])
        for bad in ('git commit', 'git push', 'push_with_retry', 'git add'):
            assert bad not in text


def test_collect_step_has_a_timeout_and_commits_the_trial_file():
    steps = load()['jobs']['collect']['steps']
    collect = next(s for s in steps if s.get('id') == 'collect')
    assert 0 < collect['timeout-minutes'] <= 60
    commit = next(s for s in steps if s.get('name') == 'Commit data')
    assert 'git add data/fund_factors.json' in commit['run']
    assert 'fund_factors_check.json' not in commit['run']     # the monthly workflow owns it


def test_monthly_workflow_commits_its_three_files_with_retry():
    path = os.path.join(os.path.dirname(WF), 'check-fund-factors.yml')
    with open(path, encoding='utf-8') as fh:
        wf = yaml.safe_load(fh)
    on = wf.get('on', wf.get(True))
    assert 'schedule' in on and 'workflow_dispatch' in on
    run = '\n'.join(s.get('run', '') for s in wf['jobs']['check']['steps'])
    for f in ('fund_factors_french.csv', 'fund_factors_inputs.json', 'fund_factors_check.json'):
        assert f'data/{f}' in run
    assert 'bash scripts/ci/push_with_retry.sh' in run
    assert 'collect_fund_factors.py --outdir data' in run


# ── 수집 상태 찍기(2026-11-17): 모든 쓰기 뒤·커밋 앞, 커밋에 담긴다 ─────────────────────────

def _steps(wf_path, job='collect'):
    with open(wf_path, encoding='utf-8') as fh:
        return [s.get('name') or s.get('uses') for s in yaml.safe_load(fh)['jobs'][job]['steps']], \
            yaml.safe_load(open(wf_path, encoding='utf-8'))['jobs'][job]['steps']


def test_us_stamp_runs_after_every_writer_and_before_both_commits():
    names, steps = _steps(WF)
    i = names.index('Stamp collection status')
    for writer in ('Collect', 'Fetch primary releases', 'Sanitize primary releases', 'Evaluate macro regime',
                   'Fetch Telegram channels', 'Fetch Fed events', 'Build the next-ten-days calendar',
                   'Treasury coupon auction results', 'Fed H.4.1 and Treasury refunding (liquidity)',
                   'Sanitize liquidity'):
        assert names.index(writer) < i, writer
    for commit in ('Commit liquidity (market data already complete)', 'Commit data'):
        assert i < names.index(commit)
        assert 'data/_collect_status.json' in steps[names.index(commit)]['run']
    assert steps[i]['if'] == 'always()' and '--datadir data' in steps[i]['run']


def test_kr_stamp_runs_right_before_the_versions_commit():
    kr = os.path.join(os.path.dirname(WF), 'collect-kr-data.yml')
    names, steps = _steps(kr)
    i = names.index('Stamp collection status')
    assert names.index('Fetch Telegram channels (non-core)') < i < names.index('Commit data')
    assert 'versions.py commit' in steps[names.index('Commit data')]['run']
    assert '--datadir kr/data' in steps[i]['run']
    from kr import versions_kr
    assert 'git add kr/data/*.json' in versions_kr.STAGE_SH          # _collect_status.json 이 커밋 O 에 든다
    assert versions_kr.is_dateless('kr/data/_collect_status.json')  # 발행된 날 동결 대상(원격 판 유지)


# ── 수익률만 고치는 재실행(2026-11-19) ───────────────────────────────────────

def _step(name):
    return next(s for s in load()['jobs']['collect']['steps'] if s.get('name') == name)


def test_full_input_forces_a_rebuild_and_force_alone_keeps_the_patch():
    wf = load()
    on = wf.get('on', wf.get(True))
    assert on['workflow_dispatch']['inputs']['full']['default'] is False
    run = _step('Collect')['run']
    assert "inputs.full) && '--no-patch'" in run
    assert "(inputs.force || inputs.full)) && '--force'" in run


def step_runs(step, outputs, collect_ok=True):
    """이 스텝이 도는가 — 스텝의 `if` 를 GitHub 규칙대로 평가한다.

    상태 함수(always·!cancelled)가 없으면 앞 스텝이 실패했을 때 돌지 않는다. 없는 출력은 ''.
    지원하는 문법 밖이면 추측하지 않고 실패한다.
    """
    expr = str(step.get('if', '')).strip()
    if expr.startswith('${{'):
        expr = expr[3:-2].strip()
    has_status = 'always()' in expr or '!cancelled()' in expr
    if not expr:
        return collect_ok

    def out(m):
        return repr(outputs.get(m.group(1), ''))
    py = re.sub(r'steps\.collect\.outputs\.([a-z_]+)', out, expr)
    py = py.replace("steps.collect.outcome", repr('success' if collect_ok else 'failure'))
    # 1a 수집 장부 단계(2026-11-17) — 정상 실행에서는 성공한다(실패 경로는 test_stamp_workflow.py 가 본다)
    py = re.sub(r'steps\.stamp(?:_begin)?\.outcome', repr('success'), py)
    py = py.replace('!cancelled()', 'True').replace('always()', 'True')
    py = py.replace('&&', ' and ').replace('||', ' or ')
    assert re.fullmatch(r"[\w\s'=!()]*", py), f'unsupported step if: {expr}'
    ok = bool(eval(py, {'__builtins__': {}}, {'True': True}))
    return ok and (has_status or collect_ok)


def ran(outputs, collect_ok=True):
    return [s['name'] for s in load()['jobs']['collect']['steps']
            if s.get('name') and s.get('id') not in ('collect', 'stamp_begin') and step_runs(s, outputs, collect_ok)]


SETUP = ['Install CJK font (for chart labels)', 'Install Python deps']
LEDGER = 'Record new releases (weekly regime ledger)'
RELEASE_CHAIN = ['Fetch primary releases', 'Sanitize primary releases',
                 'Cross-check release components', 'Evaluate macro regime']
NON_CORE = ['Fetch market news', 'Fetch Telegram channels', 'Fetch Fed events',
            'Refresh FOMC schedule', 'Build the next-ten-days calendar',
            'Treasury coupon auction results']
LIQ = ['Fed H.4.1 and Treasury refunding (liquidity)', 'Sanitize liquidity']
COMMIT_LIQ = 'Commit liquidity (market data already complete)'
# 1a: 모든 쓰기 뒤·커밋 앞, 늘 돈다(기다림 실행에서도 — 장부만 쓰고 커밋은 하지 않는다). 시작 기록(stamp_begin)은 Collect 앞.
STAMP = 'Stamp collection status'


def test_step_matrix_full_collection_is_unchanged():
    assert ran({}) == SETUP + [LEDGER] + RELEASE_CHAIN + NON_CORE + LIQ + [STAMP,
        'Report status', 'Commit data', 'FRED key health']


def test_step_matrix_skipped_run_is_unchanged():
    # 이미 완전한 판: 원장·유동성만 돌고 유동성 커밋으로 끝난다(오늘과 같다).
    assert ran({'skipped': 'true'}) == SETUP + [LEDGER] + LIQ + [STAMP, COMMIT_LIQ, 'Report status']


def test_step_matrix_patch_run_commits_and_leaves_the_frozen_chain_alone():
    assert ran({'patched': 'true'}) == SETUP + NON_CORE + LIQ + [STAMP, 'Report status', 'Commit data']


def test_step_matrix_waiting_run_touches_and_commits_nothing():
    assert ran({'skipped': 'true', 'waiting': 'true'}) == SETUP + [STAMP, 'Report status']
    report = _step('Report status')['run']
    assert 'git ' not in report and "open('data/market_data.json')" in report   # 읽기만 한다


def test_step_matrix_failed_collect_commits_nothing():
    # 되돌리기·설치 실패로 수집기가 exit 1 — 커밋 스텝은 하나도 돌지 않는다.
    names = ran({}, collect_ok=False)
    assert 'Commit data' not in names and COMMIT_LIQ not in names
    assert not [n for n in names if 'Commit' in n]


def test_always_steps_keep_always():
    for name in ('Record new releases (weekly regime ledger)', 'Sanitize primary releases',
                 'Sanitize liquidity', 'Commit liquidity (market data already complete)'):
        assert 'always()' in _step(name)['if']


def test_patch_commit_stages_its_four_outputs_strictly():
    run = _step('Commit data')['run']
    strict = next(line.strip() for line in run.splitlines()
                  if 'data/yield_curve.png' in line and 'data/history/market.jsonl' in line)
    assert strict == ('git add data/market_data.json data/yield_curve.png '
                      'data/history/market.jsonl data/weekly')
    assert '|| true' not in strict
    assert "steps.collect.outputs.patched }}\" = \"true\"" in run
    assert '(yields patch)' in run
