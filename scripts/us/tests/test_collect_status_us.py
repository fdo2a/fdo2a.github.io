"""US 수집기의 collect 칸 — 시세·장중·경제지표·매크로 점수(2026-11-17, 공통 계약 A). 네트워크 없음."""
import inspect
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import collect_market_data as cmd  # noqa: E402

RD = '2026-11-16'


FULL = {'report_date': RD, 'complete': True, 'missing': [], 'indices': {'S&P 500': {}},
        'yield_drivers': {'rows': {'real_10y': {}}, 'decomposition': {}}, 'price_context': {}, 'session': {}}


def test_market_complete_is_ok():
    c = cmd.market_collect(FULL)
    assert c['status'] == 'ok' and c['required_ok'] and c['as_of'] == RD and c['empty'] == 'has_data'


def test_market_incomplete_is_partial_with_the_missing_rows():
    c = cmd.market_collect(dict(FULL, complete=False, missing=['yields/2Y']))
    assert c['status'] == 'partial' and c['required_ok'] is False and c['missing'] == ['yields/2Y']


def test_market_without_indices_is_failed():
    c = cmd.market_collect({'report_date': RD, 'complete': False, 'missing': [], 'indices': {}})
    assert c['status'] == 'failed' and c['empty'] == 'unknown'


def test_intraday_all_partial_none():
    names = [n for n, _ in cmd.INTRADAY_KEY]
    full = {n: {'close': 1} for n in names}
    assert cmd.intraday_collect(full, RD)['status'] == 'ok'
    part = dict(full, WTI=None)
    c = cmd.intraday_collect(part, RD)
    assert c['status'] == 'partial' and c['missing'] == ['WTI'] and c['as_of'] == RD
    assert cmd.intraday_collect({n: None for n in names}, RD)['status'] == 'failed'


def test_econ_fetch_failure_is_missing_but_a_missing_month_is_not():
    rows = [{'name': 'x'}]
    c = cmd.econ_collect(rows, {'CPI YoY': 'no_value', 'Core CPI YoY': 'no_value'}, RD)
    assert c['status'] == 'ok' and c['missing'] == [] and 'CPI YoY' in c['detail']
    c = cmd.econ_collect(rows, {'JOLTS Job Openings': 'fetch_failed', 'CPI YoY': 'no_value'}, RD)
    assert c['status'] == 'partial' and c['missing'] == ['JOLTS Job Openings']
    assert cmd.econ_collect([], {}, RD)['status'] == 'failed'


def test_collect_econ_records_why_each_row_is_absent(monkeypatch):
    monkeypatch.setattr(cmd.time, 'sleep', lambda s: None)
    monkeypatch.setattr(cmd, 'retry', lambda fn, **k: fn())
    first = cmd.ECON[0]
    monkeypatch.setattr(cmd, 'fred_series', lambda sid: [] if sid == first[2] else [('2026-01-01', 1.0)])
    monkeypatch.setattr(cmd, '_econ_pair', lambda vals, tf: None)
    reasons = {}
    out, _ = cmd.collect_econ(reasons)
    assert out == []
    assert reasons[first[1]] == 'fetch_failed'
    assert set(reasons.values()) == {'fetch_failed', 'no_value'}


def test_macro_metrics_partial_when_inputs_degraded():
    ok = {'status': 'ok'}
    assert cmd.macro_metrics_collect({'book_state': 'ok'}, ok, RD)['status'] == 'ok'
    c = cmd.macro_metrics_collect({'book_state': 'corrupt'}, {'status': 'partial'}, RD)
    assert c['status'] == 'partial' and c['missing'] == ['econ_indicators', 'macro.json:corrupt']


def test_every_us_collector_file_is_stamped_in_main():
    src = inspect.getsource(cmd.main)
    for marker in ("data['collect'] = market_collect(data)", "'collect': intraday_collect(",
                   "'collect': econ_status", "'collect': macro_metrics_collect("):
        assert marker in src
    assert src.index("data['collect'] = market_collect(data)") < src.index('json.dump(data, open(md_path')


import pytest  # noqa: E402


@pytest.mark.parametrize('broken,token', [
    ({'yield_drivers': {'rows': {}, 'decomposition': {}}}, 'block:yield_drivers'),   # 금리 동인 블록 실패의 기본값
    ({'price_context': None}, 'block:price_context'),                               # 가격 맥락 블록 실패 = 키 없음
    ({'session': None}, 'block:session'),
])
def test_failed_derived_block_is_partial_even_when_complete(broken, token):
    data = dict(FULL)
    for k, v in broken.items():
        if v is None:
            data.pop(k)
        else:
            data[k] = v
    c = cmd.market_collect(data)
    assert c['status'] == 'partial' and c['required_ok'] is False and token in c['missing']
