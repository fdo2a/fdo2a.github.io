"""Step two of the anatomy in the collector job: reset, then cross-check this run's texts."""
import json

import pytest

import xcheck_components as X
from scripts.us import anatomy as A, macro
from scripts.us.tests.test_anatomy import FRED_CPI, HEADLINE, RD, _cpi_rel, _fetch, _text

SESSION = '2026-10-14'


def _setup(tmp_path, *, index_status='complete', index_date=SESSION, metrics_date=SESSION,
           full=True, row=None):
    d = tmp_path / 'data'
    (d / 'releases').mkdir(parents=True)
    rel = A.produce(_cpi_rel(), _fetch(FRED_CPI), RD, HEADLINE)
    (d / 'market_data.json').write_text(json.dumps({'report_date': SESSION}))
    (d / 'macro_metrics.json').write_text(json.dumps(
        {'report_date': metrics_date, 'headline_releases': [rel]}))
    row = row or {'key': 'cpi', 'ok': True, 'verified': True, 'published': True,
                  'checks': {'value': True, 'primary_checked': True}, 'path': 'releases/cpi.txt'}
    (d / 'releases' / 'index.json').write_text(json.dumps(
        {'report_date': index_date, 'run_id': 'r1', 'status': index_status, 'releases': [row]}))
    (d / 'releases' / 'cpi.txt').write_text('# header\n\nshort committed copy')
    if full:
        w = tmp_path / '_workspace' / 'releases'
        w.mkdir(parents=True)
        (w / 'cpi.txt').write_text(_text('cpi'))
    return d


@pytest.fixture(autouse=True)
def _no_run_id(monkeypatch):
    monkeypatch.delenv('GITHUB_RUN_ID', raising=False)


def _rel(d):
    return json.loads((d / 'macro_metrics.json').read_text())['headline_releases'][0]


def test_this_runs_texts_confirm_the_components(tmp_path):
    d = _setup(tmp_path)
    X.run(str(d))
    rel = _rel(d)
    assert rel['anatomy_status'] == 'complete' and len(rel['components']) == 6
    assert json.loads((d / 'macro_metrics.json').read_text())['anatomy_gaps'] == []


def test_the_committed_copy_is_the_fallback_text(tmp_path):
    d = _setup(tmp_path, full=False)
    (d / 'releases' / 'cpi.txt').write_text(_text('cpi'))
    X.run(str(d))
    assert _rel(d)['anatomy_status'] == 'complete'


@pytest.mark.parametrize('kw', [
    {'index_status': 'aborted'},
    {'index_status': 'running'},
    {'index_date': '2026-10-13'},
    {'metrics_date': '2026-10-13'},
])
def test_anything_but_this_sessions_complete_texts_leaves_no_components(tmp_path, kw):
    d = _setup(tmp_path, **kw)
    X.run(str(d))
    rel = _rel(d)
    assert rel['components'] == [] and rel['anatomy_status'] == 'none'
    gaps = json.loads((d / 'macro_metrics.json').read_text())['anatomy_gaps']
    assert gaps and gaps[0]['reason'] == 'not_cross_checked'


def test_another_runs_index_is_refused_on_actions(tmp_path, monkeypatch):
    d = _setup(tmp_path)
    monkeypatch.setenv('GITHUB_RUN_ID', '99')
    X.run(str(d))
    assert _rel(d)['components'] == []


def test_a_headline_whose_value_was_not_checked_gives_no_components(tmp_path):
    row = {'key': 'cpi', 'ok': True, 'verified': True,
           'checks': {'value': None, 'primary_checked': False}}
    d = _setup(tmp_path, row=row)
    X.run(str(d))
    assert _rel(d)['anatomy_status'] == 'none'


def test_the_evaluation_hands_the_result_and_the_gaps_to_the_writer(tmp_path):
    d = _setup(tmp_path)
    X.run(str(d))
    metrics = json.loads((d / 'macro_metrics.json').read_text())
    metrics['headline_releases'].append({'key': 'michigan', 'anatomy_status': 'none',
                                         'anatomy_reason': 'no_verified_text', 'components': []})
    ev = macro.evaluate(None, metrics, SESSION)
    assert ev['headline_releases'][0]['components'][0]['label'] == '에너지'
    assert ev['anatomy_gaps'] == [{'key': 'michigan', 'status': 'none',
                                   'reason': 'no_verified_text', 'components': 0}]
