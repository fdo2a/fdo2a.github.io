"""calendar.json 의 collect 칸 — 재료 결측·확인 못 한 지표는 「없음 확인」이 아니다(2026-11-17)."""
import json
import sys

import build_calendar as BC

RD = '2026-11-16'


def book(**kw):
    b = {'report_date': RD, 'events': [{'key': 'x'}], 'missing': [], 'unresolved': []}
    b.update(kw)
    return b


def test_complete_calendar_is_ok():
    c = BC.calendar_collect(book())
    assert c['status'] == 'ok' and c['empty'] == 'has_data' and c['required_ok'] and c['as_of'] == RD


def test_failed_material_is_partial():
    c = BC.calendar_collect(book(missing=['releases']))
    assert c['status'] == 'partial' and c['required_ok'] is False and c['missing'] == ['releases']


def test_unresolved_indicator_counts_as_missing():
    c = BC.calendar_collect(book(unresolved=['cpi']))
    assert c['status'] == 'partial' and c['missing'] == ['unresolved:cpi']


def test_no_events_with_full_material_is_confirmed_none_otherwise_unknown():
    assert BC.calendar_collect(book(events=[]))['empty'] == 'confirmed_none'
    assert BC.calendar_collect(book(events=[], missing=['auctions']))['empty'] == 'unknown'


def test_offline_run_writes_partial_collect(tmp_path, monkeypatch):
    (tmp_path / 'market_data.json').write_text(json.dumps({'report_date': RD}))
    monkeypatch.setattr(sys, 'argv', ['x', '--datadir', str(tmp_path), '--offline'])
    BC.main()
    c = json.loads((tmp_path / 'calendar.json').read_text())['collect']
    assert c['status'] == 'partial' and set(c['missing']) >= {'releases', 'auctions'}
