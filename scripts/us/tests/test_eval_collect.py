"""macro_eval.json 의 collect 칸(2026-11-17)."""
import json
import sys

import eval_macro_regime as E

RD = '2026-11-16'


def run(tmp_path, monkeypatch, metrics=None, macro=None):
    (tmp_path / 'market_data.json').write_text(json.dumps({'report_date': RD}))
    if metrics is not None:
        (tmp_path / 'macro_metrics.json').write_text(json.dumps(metrics))
    if macro is not None:
        (tmp_path / 'macro.json').write_text(macro if isinstance(macro, str) else json.dumps(macro))
    monkeypatch.setattr(sys, 'argv', ['x', '--datadir', str(tmp_path)])
    E.main()
    return json.loads((tmp_path / 'macro_eval.json').read_text())['collect']


def test_fresh_metrics_is_ok(tmp_path, monkeypatch):
    c = run(tmp_path, monkeypatch, metrics={'report_date': RD, 'collect': {'status': 'ok'}})
    assert c['status'] == 'ok' and c['as_of'] == RD and c['empty'] == 'has_data'
    assert 'bootstrap' in c['detail']


def test_stale_or_absent_metrics_is_partial(tmp_path, monkeypatch):
    c = run(tmp_path, monkeypatch, metrics={'report_date': '2026-11-13'})
    assert c['status'] == 'partial' and c['missing'] == ['macro_metrics:stale']
    (tmp_path / 'macro_metrics.json').unlink()
    c = run(tmp_path, monkeypatch)
    assert c['missing'] == ['macro_metrics:absent']


def test_degraded_metrics_is_partial(tmp_path, monkeypatch):
    c = run(tmp_path, monkeypatch, metrics={'report_date': RD, 'collect': {'status': 'partial'}})
    assert c['status'] == 'partial' and c['missing'] == ['macro_metrics:partial']


def test_unreadable_book_is_failed_not_bootstrap(tmp_path, monkeypatch):
    c = run(tmp_path, monkeypatch, metrics={'report_date': RD}, macro='{ broken')
    assert c['status'] == 'failed' and c['missing'] == ['macro.json']
