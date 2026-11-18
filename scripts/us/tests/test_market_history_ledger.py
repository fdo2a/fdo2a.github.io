"""국채 원장이 깨진 회차는 시세 이력을 건드리지 않는다(codex 구현 검토 4회)."""
import importlib
import json

cmd = importlib.import_module('collect_market_data')


def _row(d, ten):
    return {'report_date': d, 'yields': {'10Y': ten}, 'basis': {'yields': 'cut_1600_et'}}


def test_corrupt_ledger_leaves_history_alone(tmp_path):
    h = tmp_path / 'history'
    h.mkdir()
    p = h / 'market.jsonl'
    p.write_text(json.dumps(_row('2026-11-06', 4.86)) + '\n')
    before = p.read_text()
    data = {'report_date': '2026-11-06', 'yields': {t: None for t in ('2Y', '5Y', '10Y', '30Y')}}
    cmd.market_history(str(h), data, ledger={}, ledger_ok=False)
    assert p.read_text() == before


def test_healthy_ledger_appends_and_backfills(tmp_path):
    h = tmp_path / 'history'
    h.mkdir()
    p = h / 'market.jsonl'
    p.write_text(json.dumps({'report_date': '2026-11-05', 'yields': {'10Y': 4.9}}) + '\n')
    cut = {t: {'level': 4.86, 'basis': 'cut_1600_et'} for t in ('2Y', '5Y', '10Y', '30Y')}
    ledger = {'2026-11-05': {'tenors': {t: {'value': 4.8} for t in ('2Y', '5Y', '10Y', '30Y')}}}
    cmd.market_history(str(h), {'report_date': '2026-11-06', 'yields': cut}, ledger, True)
    rows = [json.loads(x) for x in p.read_text().splitlines()]
    assert [r['report_date'] for r in rows] == ['2026-11-05', '2026-11-06']
    assert rows[0]['cut_1600']['yields']['10Y'] == 4.8


def test_corrupt_ledger_stops_collection_before_writing(tmp_path):
    import pytest
    p = tmp_path / 'yields_1600.json'
    p.write_text('{"2026-11-06": ')
    with pytest.raises(SystemExit) as e:
        cmd.load_ledger_or_exit(str(p))
    assert e.value.code == 3
    assert p.read_text() == '{"2026-11-06": '
    assert cmd.load_ledger_or_exit(str(tmp_path / 'none.json')) == {}     # 첫 실행은 빈 원장


def test_main_fails_on_corrupt_ledger_even_when_a_complete_dataset_exists(tmp_path, monkeypatch):
    import pytest
    (tmp_path / 'market_data.json').write_text(json.dumps({'report_date': '2026-11-06', 'complete': True}))
    (tmp_path / 'yields_1600.json').write_text('<<<<<<< HEAD\n')
    before = {p.name: p.read_text() for p in tmp_path.iterdir()}

    def boom(*a, **k):
        raise AssertionError('수집을 시작하면 안 된다')
    monkeypatch.setattr(cmd, 'collect_daily', boom)
    monkeypatch.setattr(cmd, 'fred_client', boom)            # 외부(FRED)에 닿기 전에 끝나야 한다
    monkeypatch.setattr('sys.argv', ['collect_market_data.py', '--outdir', str(tmp_path)])
    with pytest.raises(SystemExit) as e:
        cmd.main()
    assert e.value.code == 3
    assert {p.name: p.read_text() for p in tmp_path.iterdir()} == before


def test_main_fails_on_structurally_broken_ledger_before_network(tmp_path, monkeypatch):
    import pytest
    (tmp_path / 'yields_1600.json').write_text(json.dumps({'2026-11-06': 'broken'}))

    def boom(*a, **k):
        raise AssertionError('네트워크·수집에 닿으면 안 된다')
    monkeypatch.setattr(cmd, 'collect_daily', boom)
    monkeypatch.setattr(cmd, 'fred_client', boom)
    monkeypatch.setattr('sys.argv', ['collect_market_data.py', '--outdir', str(tmp_path)])
    with pytest.raises(SystemExit) as e:
        cmd.main()
    assert e.value.code == 3
