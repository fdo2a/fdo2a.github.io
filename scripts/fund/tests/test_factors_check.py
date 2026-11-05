"""Monthly French-file check (FF3 trial). Spec v2 §5, v3 §3-6·§9, v3.1 A-7·5·B-6.

Fixtures are synthetic (ff3_world) — no row of the real French file is in the repo's
tests. Network is never touched: the run takes injected fetchers, and the offline
recompute test makes urlopen / yfinance raise.
"""

import copy
import json
import os
import shutil

import numpy as np
import pytest

from fund import factors, factors_check as fc, universe
from fund.tests import ff3_world as W

FIX = os.path.join(os.path.dirname(__file__), 'fixtures', 'ff3')
DATA = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'data')
IDS = [u for u, _, _, _ in universe.UNITS]


def run(outdir, world, http=None, zip_override=None):
    text = W.french_text(world['french'])
    calls = {'hist': 0, 'rf': 0}

    def fetch_zip():
        return (zip_override or W.zip_bytes(text)), (http or {'etag': None, 'last_modified': None})

    def fetch_histories():
        calls['hist'] += 1
        return world['closes'], world['dates']

    def fetch_rf():
        calls['rf'] += 1
        return world['rf_obs']

    code = fc.run(str(outdir), W.HOLIDAYS, fetch_zip, fetch_histories, fetch_rf,
                  now=lambda: '2026-11-08 10:00 KST')
    return code, calls


def files(d):
    return {n: (d / n).read_bytes() for n in (fc.CHECK, fc.SLICE, fc.INPUTS) if (d / n).exists()}


def load_check(d):
    return json.loads((d / fc.CHECK).read_text(encoding='utf-8'))


# --- parser -----------------------------------------------------------------------

def test_parse_synthetic_french_fixture():
    w = W.make()
    rows, missing, cr = fc.parse_french(W.french_text(w['french']))
    assert missing == []
    assert len(rows) == len(w['french'])
    assert rows[0][0] == w['days'][0] and len(rows[0]) == 5
    assert float(rows[-1][1]) == w['french'][-1][1]
    assert cr.startswith('Copyright 2026 Synthetic')


@pytest.mark.parametrize('how', ['reversed', 'duplicate'])
def test_reversed_or_duplicate_dates_reject_file(how):
    w = W.make()
    rows = list(w['french'])
    if how == 'reversed':
        rows[10], rows[11] = rows[11], rows[10]
    else:
        rows[11] = (rows[10][0],) + rows[11][1:]
    with pytest.raises(ValueError):
        fc.parse_french(W.french_text(rows))


def test_non_numeric_row_skipped_and_listed():
    w = W.make()
    text = W.french_text(w['french']).replace(
        w['days'][5].replace('-', '') + ',', w['days'][5].replace('-', '') + ',  -99.99x', 1)
    rows, missing, _ = fc.parse_french(text)
    assert w['days'][5] not in [r[0] for r in rows]
    assert len(rows) == len(w['french']) - 1
    assert any('non-numeric' in m and w['days'][5].replace('-', '') in m for m in missing)


def test_missing_header_rejects_file():
    with pytest.raises(ValueError):
        fc.parse_french('nothing here\r\n\r\n20260930,1,2,3,4\r\n')


def test_dates_outside_calendar_listed_not_approximated():
    w = W.make()
    fr = [list(r) for r in w['french']]
    # a weekend date inside the window (not a session) and a session the file lacks
    fr.insert(-20, ['2026-08-30', .5, .5, .5, 0.0])
    gone = w['days'][-40]
    fr = [r for r in fr if r[0] != gone]
    fr.sort(key=lambda r: r[0])
    inputs, _ = factors.prepare(w['closes'], w['dates'], w['rf_obs'], w['days'][-1], W.HOLIDAYS)
    out = fc.compute(inputs, [tuple(r) for r in fr])
    assert any('2026-08-30' in m and 'not a session' in m for m in out['missing'])
    assert any(gone in m and 'French file lacks' in m for m in out['missing'])
    assert all(r['status'] == 'unavailable' for r in out['rows'])


# --- scale, fit, sign ----------------------------------------------------------------

def test_scaled_exposure_and_fit_rmse_factor_doubled_gives_zero_error():
    """공식 F·대리 2F·ETF F → 공식 1, 대리 0.5, k 0.5, 척도 보정 1, 적합 차이 0."""
    w = W.make(etf_override={'SMH': lambda m, s, h: m + s + h})
    inputs, _ = factors.prepare(w['closes'], w['dates'], w['rf_obs'], w['days'][-1], W.HOLIDAYS)
    out = fc.compute(inputs, w['french'])
    r = next(x for x in out['rows'] if x['id'] == 'semis')
    assert r['status'] == 'ok'
    for f in ('mkt', 'smb', 'hml'):
        assert r[f'b_{f}_official'] == pytest.approx(1.0, abs=1e-9)
        assert r[f'b_{f}_proxy_m'] == pytest.approx(0.5, abs=1e-9)
        assert out['factor_level'][f]['k'] == pytest.approx(0.5, abs=1e-12)
        assert out['factor_level'][f]['scale_reason'] == 'none'
        assert r[f'scale_{f}'] == pytest.approx(1.0, abs=1e-9)
        assert r[f'scale_gap_{f}'] == pytest.approx(0.0, abs=1e-9)
    assert r['fit_rmse'] == pytest.approx(0.0, abs=1e-10)
    assert r['sign_mismatch'] == []


def test_sign_mismatch_listed_per_etf_factor():
    """대리 SMB 를 공식의 −1 배로 만들면 SMB 가 실린 ETF 는 smb 부호가 갈린다."""
    w = W.make(scale=1.0, etf_override={'XLE': lambda m, s, h: m + .8 * s - .5 * h})
    # flip the proxy SMB leg only: IWM − IWB = −SMB
    iwb = np.array(w['closes']['IWB'])
    rb = iwb[1:] / iwb[:-1] - 1
    o_smb = np.array([r[2] for r in w['french']]) / 100
    rm = rb - o_smb[1:]
    w['closes']['IWM'] = [float(x) for x in 100 * np.cumprod(np.concatenate([[1.0], 1 + rm]))]
    inputs, _ = factors.prepare(w['closes'], w['dates'], w['rf_obs'], w['days'][-1], W.HOLIDAYS)
    out = fc.compute(inputs, w['french'])
    r = next(x for x in out['rows'] if x['id'] == 'energy')
    assert r['status'] == 'ok'
    assert r['sign_mismatch'] == ['smb']
    assert out['factor_level']['smb']['scale_reason'] == 'k_negative'
    assert r['scale_smb'] is None


def test_one_etf_short_window_only_that_row_unavailable():
    w = W.make()
    w['closes']['EWJ'] = w['closes']['EWJ'][-200:]
    w['dates']['EWJ'] = w['dates']['EWJ'][-200:]
    inputs, _ = factors.prepare(w['closes'], w['dates'], w['rf_obs'], w['days'][-1], W.HOLIDAYS)
    out = fc.compute(inputs, w['french'])
    bad = [r['id'] for r in out['rows'] if r['status'] != 'ok']
    assert bad == ['japan']
    assert out['status'] == 'partial'


def kvec(official, proxy, reps=63):
    o = np.tile(np.array(official, float), reps)
    p = np.tile(np.array(proxy, float), reps)
    return fc.scale_k(o, p)


def test_k_zero_codex_vectors_scale_null_official_kept():
    k, reason = kvec([-.01, .01, -.01, .01], [-.01, -.01, .01, .01])
    assert reason == 'k_zero' and abs(k) <= 1e-12


def test_k_tiny_1e_9_is_k_small():
    p = np.tile([-.01, -.01, .01, .01], 63)
    o = 1e-9 * p + np.tile([-.01, .01, -.01, .01], 63)
    assert fc.scale_k(o, p)[1] == 'k_small'


def test_k_negative_0_8_is_k_negative():
    p = np.tile([-.01, .02, .01, -.005], 63)
    assert fc.scale_k(-.8 * p, p) == (pytest.approx(-.8), 'k_negative')


def test_k_0_77_scales():
    p = np.tile([-.01, .02, .01, -.005], 63)
    assert fc.scale_k(.77 * p, p) == (pytest.approx(.77), 'none')
    assert fc.scale_k(.77 * p, np.full(252, .01))[1] == 'proxy_constant'
    assert fc.scale_k(5.5 * p, p)[1] == 'k_large'


def test_rmse_and_official_identical_with_or_without_scale(monkeypatch):
    w = W.make()
    inputs, _ = factors.prepare(w['closes'], w['dates'], w['rf_obs'], w['days'][-1], W.HOLIDAYS)
    a = fc.compute(inputs, w['french'])
    monkeypatch.setattr(fc, 'scale_k', lambda o, p: (None, 'k_zero'))
    b = fc.compute(inputs, w['french'])
    keep = [k for k in a['rows'][0] if not k.startswith('scale')]
    assert [{k: r[k] for k in keep} for r in a['rows']] == [{k: r[k] for k in keep} for r in b['rows']]
    assert all(r['scale_mkt'] is None for r in b['rows'])


# --- run, inputs file, no-op ------------------------------------------------------------

def test_run_writes_three_files_and_normal_28_rows_pass_self_check(tmp_path):
    w = W.make()
    code, calls = run(tmp_path, w)
    assert code == 0 and calls == {'hist': 1, 'rf': 1}
    check = load_check(tmp_path)
    assert check['status'] == 'ok'
    assert [r['id'] for r in check['rows']] == IDS
    assert fc.check_structure(check, W.HOLIDAYS) == (True, 'none')
    assert check['window'] == {'start': w['days'][-252], 'end': w['days'][-1], 'n': 252}
    assert check['french_through'] == w['days'][-1] == '2026-09-30'
    assert check['source']['attribution'].startswith('Kenneth R. French Data Library')
    assert check['http'] == {'etag': None, 'last_modified': None}


def test_inputs_file_under_256kb(tmp_path):
    run(tmp_path, W.make())
    assert (tmp_path / fc.INPUTS).stat().st_size <= 256 * 1024


def test_inputs_hashes_match_contents(tmp_path):
    run(tmp_path, W.make())
    check = load_check(tmp_path)
    assert check['inputs_sha256'] == fc.sha256_bytes((tmp_path / fc.INPUTS).read_bytes())
    assert check['slice_sha256'] == fc.sha256_bytes((tmp_path / fc.SLICE).read_bytes())
    inputs = json.loads((tmp_path / fc.INPUTS).read_text(encoding='utf-8'))
    assert inputs['sha256'] == factors.inputs_hashes(inputs)


def test_month_sessions_in_inputs_cover_every_window_month(tmp_path):
    run(tmp_path, W.make())
    inputs = json.loads((tmp_path / fc.INPUTS).read_text(encoding='utf-8'))
    ret_dates = inputs['calendar']['sessions'][1:]
    assert sorted(inputs['rf']['month_sessions']) == sorted({d[:7] for d in ret_dates})
    assert len(inputs['calendar']['sessions']) == 253


def test_rf_leading_observation_kept():
    """codex 재현: 첫 수익률 2025-09-30, 앵커 9/29, 최신 RF 9/26."""
    w = W.make(n=320)
    w['rf_obs'] = [(d, 4.0) for d in w['days'] if d <= '2025-09-26' or d >= '2025-10-01']
    inputs, missing = factors.prepare(w['closes'], w['dates'], w['rf_obs'], '2026-09-30', W.HOLIDAYS)
    assert inputs['calendar']['sessions'][:2] == ['2025-09-29', '2025-09-30']
    assert inputs['rf']['obs'][0][0] == '2025-09-26'
    rf = factors.rf_by_date(inputs['rf']['obs'], inputs['calendar']['sessions'][1:],
                            inputs['rf']['month_sessions'])
    assert rf['2025-09-30'] == factors.rf_rate(4.0, 21)


def _block_network(monkeypatch):
    import urllib.request

    def no(*a, **k):
        raise AssertionError('network touched')
    monkeypatch.setattr(urllib.request, 'urlopen', no)
    try:
        import yfinance
        monkeypatch.setattr(yfinance, 'download', no)
    except ImportError:
        pass


def recompute(d):
    with open(os.path.join(d, fc.INPUTS), encoding='utf-8') as fh:
        inputs = json.load(fh)
    with open(os.path.join(d, fc.SLICE), encoding='utf-8') as fh:
        sl = fc.read_slice(fh.read())
    with open(os.path.join(d, fc.CHECK), encoding='utf-8') as fh:
        check = json.load(fh)
    return fc.compute(inputs, sl), check


def test_offline_recompute_is_bitwise_equal_synthetic_fixture(monkeypatch):
    _block_network(monkeypatch)
    out, check = recompute(FIX)
    assert out['rows'] == check['rows']
    assert out['factor_level'] == check['factor_level']


def test_offline_recompute_is_bitwise_equal_repo_files(monkeypatch):
    if not all(os.path.exists(os.path.join(DATA, n)) for n in (fc.CHECK, fc.SLICE, fc.INPUTS)):
        pytest.skip('monthly files not committed yet')
    _block_network(monkeypatch)
    out, check = recompute(DATA)
    assert out['rows'] == check['rows']


def test_noop_with_etag_none_and_identical_slice(tmp_path):
    w = W.make()
    run(tmp_path, w)
    before = files(tmp_path)
    code, calls = run(tmp_path, w)
    assert code == 0 and calls == {'hist': 0, 'rf': 0}
    assert files(tmp_path) == before


def test_same_french_through_one_slice_row_revised_recomputes(tmp_path):
    w = W.make()
    run(tmp_path, w)
    w2 = copy.deepcopy(w)
    d, a, b, c, e = w2['french'][-30]
    w2['french'][-30] = (d, a + .01, b, c, e)
    code, calls = run(tmp_path, w2)
    assert calls['hist'] == 1
    assert load_check(tmp_path)['french_through'] == w['days'][-1]


def test_previous_partial_recomputes_on_identical_slice(tmp_path):
    w = W.make()
    w['closes']['EWJ'] = w['closes']['EWJ'][-200:]
    w['dates']['EWJ'] = w['dates']['EWJ'][-200:]
    code, _ = run(tmp_path, w)
    assert code == 0 and load_check(tmp_path)['status'] == 'partial'
    code, calls = run(tmp_path, w)
    assert calls['hist'] == 1


@pytest.mark.parametrize('field', ['factors_calculation_version', 'model'])
def test_version_or_model_change_recomputes(tmp_path, field):
    w = W.make()
    run(tmp_path, w)
    check = load_check(tmp_path)
    check[field] = 'old'
    (tmp_path / fc.CHECK).write_text(json.dumps(check), encoding='utf-8')
    _, calls = run(tmp_path, w)
    assert calls['hist'] == 1
    assert load_check(tmp_path)[field] != 'old'


@pytest.mark.parametrize('gone', [fc.CHECK, fc.SLICE, fc.INPUTS])
def test_noop_requires_all_three_files_present(tmp_path, gone):
    w = W.make()
    run(tmp_path, w)
    (tmp_path / gone).unlink()
    _, calls = run(tmp_path, w)
    assert calls['hist'] == 1
    assert set(files(tmp_path)) == {fc.CHECK, fc.SLICE, fc.INPUTS}


@pytest.mark.parametrize('target', [fc.SLICE, fc.INPUTS])
def test_noop_requires_hashes_match(tmp_path, target):
    w = W.make()
    run(tmp_path, w)
    with open(tmp_path / target, 'ab') as fh:
        fh.write(b' ')
    _, calls = run(tmp_path, w)
    assert calls['hist'] == 1


def test_unparseable_french_file_writes_nothing(tmp_path):
    w = W.make()
    rows = list(w['french'])
    rows[3], rows[4] = rows[4], rows[3]
    code, calls = run(tmp_path, w, zip_override=W.zip_bytes(W.french_text(rows)))
    assert code == 1 and calls['hist'] == 0
    assert files(tmp_path) == {}


def test_bad_structure_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(fc, 'check_structure', lambda obj, hol: (False, 'window_mismatch'))
    code, _ = run(tmp_path, W.make())
    assert code == 1 and files(tmp_path) == {}


def test_partial_one_row_unavailable_is_written_and_retried(tmp_path):
    w = W.make()
    w['closes']['MCHI'] = w['closes']['MCHI'][:-1]
    w['dates']['MCHI'] = w['dates']['MCHI'][:-1]
    code, _ = run(tmp_path, w)
    check = load_check(tmp_path)
    assert code == 0 and check['status'] == 'partial'
    assert [r['id'] for r in check['rows'] if r['status'] != 'ok'] == ['china']
    assert fc.check_structure(check, W.HOLIDAYS) == (True, 'none')
    _, calls = run(tmp_path, w)
    assert calls['hist'] == 1


def test_consumer_rejects_partial_for_official_table_but_producer_keeps_it(tmp_path):
    w = W.make()
    w['closes']['MCHI'] = w['closes']['MCHI'][:-1]
    w['dates']['MCHI'] = w['dates']['MCHI'][:-1]
    run(tmp_path, w)
    check = load_check(tmp_path)
    assert fc.check_structure(check, W.HOLIDAYS)[0]
    official, meta = fc.validate(check, '2026-11-04', W.HOLIDAYS)
    assert official is None and meta['reason'] == 'status_not_ok'


# --- check_structure ---------------------------------------------------------------------

def good_check(end='2026-09-30'):
    s = W.sessions('2024-01-02', end)[-252:]
    row = {'status': 'ok', 'reason': None, 'n': 252, 'sign_mismatch': []}
    for k in fc.ROW_FLOATS:
        row[k] = 0.5
    for k in fc.ROW_OPTIONAL:
        row[k] = None
    return {'status': 'ok', 'model': factors.MODEL,
            'factors_calculation_version': factors.FACTORS_CALCULATION_VERSION,
            'french_through': end, 'window': {'start': s[0], 'end': s[-1], 'n': 252},
            'slice_sha256': 'x', 'fetched_at': '2026-10-05 10:00 KST',
            'rows': [{'id': u, **row} for u in IDS], 'factor_level': None}


def test_codex_start_equals_end_empty_rows_window_mismatch():
    c = good_check()
    c['window'] = {'start': '2026-09-30', 'end': '2026-09-30', 'n': 252}
    c['rows'] = []
    assert fc.check_structure(c, W.HOLIDAYS) == (False, 'window_mismatch')


def test_duplicate_row_id_rejected():
    c = good_check()
    c['rows'][1] = dict(c['rows'][0])
    assert fc.check_structure(c, W.HOLIDAYS) == (False, 'duplicate_row')


def test_missing_row_rejected():
    c = good_check()
    c['rows'] = c['rows'][:-1]
    assert fc.check_structure(c, W.HOLIDAYS) == (False, 'missing_row')


def test_etf_id_field_instead_of_id_rejected():
    c = good_check()
    c['rows'] = [{**{k: v for k, v in r.items() if k != 'id'}, 'etf_id': r['id']} for r in c['rows']]
    assert fc.check_structure(c, W.HOLIDAYS) == (False, 'invalid_types')


def test_ok_row_infinite_loading_rejected():
    c = good_check()
    c['rows'][3]['b_mkt_official'] = float('inf')
    assert fc.check_structure(c, W.HOLIDAYS) == (False, 'invalid_types')


def test_status_must_agree_with_rows():
    c = good_check()
    c['rows'][0] = {**c['rows'][0], 'status': 'unavailable',
                    **{k: None for k in fc.ROW_FLOATS}}
    assert fc.check_structure(c, W.HOLIDAYS) == (False, 'status_mismatch')
    c['status'] = 'partial'
    assert fc.check_structure(c, W.HOLIDAYS) == (True, 'none')


# --- validate (consumer) -------------------------------------------------------------------

def test_meta_survives_when_official_none():
    c = good_check()
    c['status'] = 'partial'
    c['rows'][0] = {**c['rows'][0], 'status': 'unavailable', **{k: None for k in fc.ROW_FLOATS}}
    official, meta = fc.validate(c, '2026-11-04', W.HOLIDAYS)
    assert official is None
    assert meta == {'french_through': '2026-09-30', 'checked_at': '2026-10-05 10:00 KST',
                    'window': c['window'], 'slice_sha256': 'x', 'reason': 'status_not_ok'}
    assert fc.validate(None, '2026-11-04', W.HOLIDAYS)[1]['reason'] == 'missing_file'


def test_validate_file_missing_and_invalid_json(tmp_path):
    assert fc.validate_file(str(tmp_path), '2026-11-04', W.HOLIDAYS)[1]['reason'] == 'missing_file'
    (tmp_path / fc.CHECK).write_text('{nope', encoding='utf-8')
    assert fc.validate_file(str(tmp_path), '2026-11-04', W.HOLIDAYS)[1]['reason'] == 'missing_file'
    (tmp_path / fc.SLICE).write_text('date,mkt_rf,smb,hml,rf\n2026-09-30,1,2,3,0\n', encoding='utf-8')
    assert fc.validate_file(str(tmp_path), '2026-11-04', W.HOLIDAYS)[1]['reason'] == 'invalid_json'


def test_validate_file_reads_a_written_check(tmp_path):
    run(tmp_path, W.make())
    official, meta = fc.validate_file(str(tmp_path), '2026-11-04', W.HOLIDAYS)
    assert meta['reason'] == 'none' and len(official['rows']) == 28
    assert fc.validate_file(str(tmp_path), '2026-09-29', W.HOLIDAYS)[1]['reason'] == 'future_date'


def test_good_check_is_official():
    official, meta = fc.validate(good_check(), '2026-11-04', W.HOLIDAYS)
    assert meta['reason'] == 'none'
    assert official['french_through'] == '2026-09-30' and len(official['rows']) == 28


def test_future_french_through_rejected():
    assert fc.validate(good_check('2026-12-31'), '2026-11-30', W.HOLIDAYS)[1]['reason'] == 'future_date'


def test_future_slice_date_rejected():
    _, meta = fc.validate(good_check(), '2026-11-04', W.HOLIDAYS, slice_dates=['2026-11-05'])
    assert meta['reason'] == 'future_date'


def test_file_ending_mid_month_is_incomplete():
    assert fc.validate(good_check('2026-09-01'), '2026-10-15', W.HOLIDAYS)[1]['reason'] == 'incomplete_month'


def test_old_calculation_version_rejected():
    c = good_check()
    c['factors_calculation_version'] = '2026-01-01'
    assert fc.validate(c, '2026-11-04', W.HOLIDAYS)[1]['reason'] == 'version_mismatch'
    c = good_check()
    c['model'] = 'ff3_proxy_v0'
    assert fc.validate(c, '2026-11-04', W.HOLIDAYS)[1]['reason'] == 'model_mismatch'


def test_string_loading_is_invalid_types():
    c = good_check()
    c['rows'][5]['b_mkt_official'] = '0.83'
    assert fc.validate(c, '2026-11-04', W.HOLIDAYS)[1]['reason'] == 'invalid_types'


def test_stale_month_boundary_weekend_and_year_end():
    assert fc.months_behind('2026-11-04', '2026-09-30') == 2
    assert fc.months_behind('2026-11-30', '2026-09-30') == 2
    assert fc.months_behind('2026-12-01', '2026-09-30') == 3
    assert fc.months_behind('2027-01-04', '2026-10-30') == 3
    assert fc.months_behind('2026-12-31', '2026-10-30') == 2
    # 2026-10-31 is a Saturday — the October file ends on Friday 10/30 and is complete
    assert fc.validate(good_check('2026-10-30'), '2026-12-31', W.HOLIDAYS)[1]['reason'] == 'none'
    assert fc.validate(good_check('2026-10-30'), '2027-01-04', W.HOLIDAYS)[1]['reason'] == 'stale'
    assert fc.validate(good_check(), '2026-11-04', W.HOLIDAYS)[1]['reason'] == 'none'
    assert fc.validate(good_check(), '2026-12-01', W.HOLIDAYS)[1]['reason'] == 'stale'


def test_attribution_text():
    assert fc.ATTRIBUTION == ('Kenneth R. French Data Library · '
                              'Copyright Eugene F. Fama and Kenneth R. French')


def make_fixture():
    """Regenerate scripts/fund/tests/fixtures/ff3 (synthetic only)."""
    os.makedirs(FIX, exist_ok=True)
    tmp = os.path.join(FIX, '_tmp')
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    import pathlib
    run(pathlib.Path(tmp), W.make())
    for n in (fc.CHECK, fc.SLICE, fc.INPUTS):
        shutil.move(os.path.join(tmp, n), os.path.join(FIX, n))
    os.rmdir(tmp)


def test_cli_wires_fetchers_and_writes_three_files(tmp_path, monkeypatch):
    import collect_fund_factors as cli
    w = W.make()
    shutil.copy(os.path.join(DATA, 'market_holidays.json'), tmp_path / 'market_holidays.json')
    monkeypatch.setattr(cli, 'fetch_zip',
                        lambda: (W.zip_bytes(W.french_text(w['french'])), {'etag': '"e"', 'last_modified': None}))
    monkeypatch.setattr(cli, 'fetch_histories', lambda: (w['closes'], w['dates']))
    monkeypatch.setattr(cli, 'fetch_rf', lambda: w['rf_obs'])
    assert cli.main(['--outdir', str(tmp_path)]) == 0
    assert set(files(tmp_path)) == {fc.CHECK, fc.SLICE, fc.INPUTS}
    assert load_check(tmp_path)['http']['etag'] == '"e"'


def test_cli_without_holiday_file_fails_and_writes_nothing(tmp_path):
    import collect_fund_factors as cli
    assert cli.main(['--outdir', str(tmp_path)]) == 1
    assert files(tmp_path) == {}
