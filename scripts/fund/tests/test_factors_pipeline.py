"""FF3 trial file data/fund_factors.json — written beside the board, never into it."""

import json
import os

import pytest

from fund import core, factors, factors_check, factors_pipeline, pipeline
from fund.tests import ff3_world as W
from fund.tests.test_pipeline import FRED, MARKET, files

HEAD = ('factors_schema_version', 'factors_calculation_version', 'model', 'report_date',
        'generated_at', 'status', 'missing')


def daily_world():
    w = W.make(end='2026-11-04', n=320, seed=21, scale=1.0, dgs1mo=4.0)
    # the board needs more than 252 sessions of SPY for its regime; give it 320
    return w


def board_and_trial(tmp, w, trial=True):
    rd = w['days'][-1]
    pipeline.run(w['closes'], w['dates'], MARKET, FRED, rd, 't', str(tmp), W.HOLIDAYS)
    if trial:
        factors_pipeline.run_trial(w['closes'], w['dates'], w['rf_obs'], rd, 't', str(tmp),
                                   W.HOLIDAYS)


def read(tmp):
    with open(os.path.join(tmp, factors_pipeline.OUT), encoding='utf-8') as fh:
        return json.load(fh)


def test_run_trial_writes_header_and_rows(tmp_path):
    w = daily_world()
    board_and_trial(tmp_path, w)
    d = read(tmp_path)
    for k in HEAD:
        assert k in d
    assert d['factors_schema_version'] == 1 and d['model'] == 'ff3_proxy_v1'
    assert d['status'] == 'ok' and len(d['rows']) == 28
    assert d['reproducible_offline'] is False
    assert d['official'] is None and d['official_meta']['reason'] == 'missing_file'
    assert d['rf']['series'] == 'DGS1MO' and d['rf']['n_month'] == 20
    assert d['window'] == {'start': w['days'][-252], 'end': '2026-11-04', 'n': 252}


def test_run_trial_carries_official_when_monthly_check_is_fresh(tmp_path):
    m = W.make()
    from fund.tests.test_factors_check import run as monthly
    assert monthly(tmp_path, m)[0] == 0
    board_and_trial(tmp_path, daily_world())
    d = read(tmp_path)
    assert d['official_meta']['reason'] == 'none'
    assert d['official']['french_through'] == '2026-09-30'
    assert len(d['official']['rows']) == 28


def test_trial_run_leaves_board_digest_and_html_bytes_unchanged(tmp_path):
    w = daily_world()
    a, b = tmp_path / 'a', tmp_path / 'b'
    board_and_trial(a, w, trial=False)
    board_and_trial(b, w, trial=True)
    assert files(a) == files(b) and 'fund_board.html' in files(a)
    assert (b / factors_pipeline.OUT).exists() and not (a / factors_pipeline.OUT).exists()
    board = json.loads(files(a)['fund_board.json'])
    assert 'factors' not in board and board['schema_version'] == 1


def test_trial_exception_leaves_fund_board_files_byte_identical(tmp_path, monkeypatch):
    w = daily_world()
    board_and_trial(tmp_path, w, trial=False)
    before = files(tmp_path)

    def boom(*a, **k):
        raise RuntimeError('factor boom')
    monkeypatch.setattr(factors, 'compute_daily', boom)
    factors_pipeline.run_trial(w['closes'], w['dates'], w['rf_obs'], w['days'][-1], 't',
                               str(tmp_path), W.HOLIDAYS)
    assert files(tmp_path) == before
    d = read(tmp_path)
    assert d['status'] == 'unavailable'
    assert any('factor boom' in m for m in d['missing'])


def test_bad_factor_only_history_is_reported_by_the_trial_only(tmp_path):
    w = daily_world()
    a = tmp_path / 'a'
    clean = {k: v for k, v in w['closes'].items() if k not in factors.FACTOR_ONLY}
    pipeline.run(clean, {k: w['dates'][k] for k in clean}, MARKET, FRED, w['days'][-1], 't',
                 str(a), W.HOLIDAYS)
    w['dates']['VTI'] = list(w['dates']['VTI'])
    w['dates']['VTI'][-2] = w['dates']['VTI'][-3]
    b = tmp_path / 'b'
    board_and_trial(b, w)
    assert files(a) == files(b)
    d = read(b)
    assert d['status'] == 'unavailable'
    assert any(m.startswith('factors: VTI dates') for m in d['missing'])


def test_trial_json_is_finite_and_strict(tmp_path):
    board_and_trial(tmp_path, daily_world())
    raw = (tmp_path / factors_pipeline.OUT).read_text(encoding='utf-8')
    json.loads(raw, parse_constant=lambda c: pytest.fail(f'non-finite {c}'))


def test_collector_runs_the_trial_after_the_board_in_its_own_try():
    here = os.path.dirname(__file__)
    src = open(os.path.join(here, '..', '..', 'collect_market_data.py'), encoding='utf-8').read()
    board = src.index('fund_pipeline.run(')
    trial = src.index('factors_pipeline.run_trial(')
    assert board < trial
    between = src[board:trial]
    assert 'try:' in between


# --- codex impl review 1 #4: official_meta survives every failure ----------------------------

META_KEYS = {'french_through', 'checked_at', 'window', 'slice_sha256', 'reason'}


def test_codex_sign_mismatch_dict_keeps_daily_rows_and_meta(tmp_path):
    from fund.tests.test_factors_check import run as monthly
    assert monthly(tmp_path, W.make())[0] == 0
    path = tmp_path / factors_check.CHECK
    c = json.loads(path.read_text(encoding='utf-8'))
    c['rows'][0]['sign_mismatch'] = [{}]
    path.write_text(json.dumps(c), encoding='utf-8')
    board_and_trial(tmp_path, daily_world())
    d = read(tmp_path)
    assert d['status'] == 'ok' and len(d['rows']) == 28
    assert d['official'] is None
    assert set(d['official_meta']) == META_KEYS and d['official_meta']['reason'] == 'invalid_types'


def test_compute_daily_exception_keeps_official_meta(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError('factor boom')
    monkeypatch.setattr(factors, 'compute_daily', boom)
    w = daily_world()
    factors_pipeline.run_trial(w['closes'], w['dates'], w['rf_obs'], w['days'][-1], 't',
                               str(tmp_path), W.HOLIDAYS)
    d = read(tmp_path)
    assert d['status'] == 'unavailable'
    assert set(d['official_meta']) == META_KEYS and d['official_meta']['reason'] == 'missing_file'


def test_validation_exception_keeps_official_meta_and_daily_rows(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise TypeError('validator boom')
    monkeypatch.setattr(factors_check, 'validate_file', boom)
    board_and_trial(tmp_path, daily_world())
    d = read(tmp_path)
    assert d['status'] == 'ok' and len(d['rows']) == 28
    assert d['official'] is None
    assert set(d['official_meta']) == META_KEYS and d['official_meta']['reason'] == 'invalid_types'
    assert any('validator boom' in m for m in d['missing'])
