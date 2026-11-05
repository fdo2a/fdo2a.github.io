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
