"""stamp_collect.py — 등록 파일의 해시·크기·수집 상태를 _collect_status.json 에(2026-11-17)."""
import hashlib
import json

import stamp_collect as S
from common import collect_status as C

RD = '2026-11-16'


def w(p, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(obj if isinstance(obj, str) else json.dumps(obj), encoding='utf-8')


def test_us_files_hashes_and_collect_sources(tmp_path):
    ok = C.build('ok', RD, 'x', empty='has_data')
    w(tmp_path / 'market_data.json', {'report_date': RD, 'collect': ok})
    w(tmp_path / 'fed' / 'events.json', {'report_date': RD, 'events': [], 'collect': ok})
    w(tmp_path / 'fed' / 'fomc-statement-20261028.txt', 'text')
    w(tmp_path / 'sector_performance.html', '<div></div>')
    w(tmp_path / 'econ_indicators.json', {'indicators': []})             # 옛 형식 — 칸 없음
    w(tmp_path / 'macro.json', {'regime': 1})                            # 루틴 상태 — 등록하지 않는다
    book = S.stamp(str(tmp_path))
    f = book['files']
    assert book['market'] == 'us' and book['report_date'] == RD
    md = f['market_data.json']
    assert md['sha256'] == hashlib.sha256((tmp_path / 'market_data.json').read_bytes()).hexdigest()
    assert md['bytes'] == (tmp_path / 'market_data.json').stat().st_size
    assert md['collect_in'] == 'file' and md['status'] == 'ok' and md['as_of'] == RD
    assert f['fed/fomc-statement-20261028.txt']['collect_in'] == 'producer:fed/events.json'
    assert f['sector_performance.html']['status'] == 'ok'
    assert f['econ_indicators.json']['collect_in'] == 'none' and 'status' not in f['econ_indicators.json']
    assert f['auctions.json'] == {'present': False}
    assert f[f'telegram/{RD}.json'] == {'present': False}
    assert 'macro.json' not in f
    on_disk = json.loads((tmp_path / C.STATUS_FILE).read_text())
    assert on_disk['files'] == f and on_disk['format'] == C.FORMAT


def test_kr_sidecar_entries_survive_and_get_hashes(tmp_path):
    w(tmp_path / 'kr_market_data.json', {'report_date': RD})
    w(tmp_path / 'kr_top_value.json', [{'name': 'a'}])
    C.record_sidecar(str(tmp_path), 'kr_top_value.json', C.build('ok', RD, 'Naver', empty='has_data'))
    w(tmp_path / 'kr_stance.json', {'x': 1})
    book = S.stamp(str(tmp_path))
    e = book['files']['kr_top_value.json']
    assert book['market'] == 'kr'
    assert e['collect_in'] == 'sidecar' and e['status'] == 'ok' and e['sha256'] and e['bytes'] > 0
    assert book['files']['kr_index_etf.json'] == {'present': False}
    assert 'kr_stance.json' not in book['files']
    # 다시 찍어도(다음 실행이 목록 파일을 다시 쓰지 않았어도) 상태는 남는다
    again = S.stamp(str(tmp_path))['files']['kr_top_value.json']
    assert again['status'] == 'ok' and again['sha256'] == e['sha256']


def test_list_file_without_sidecar_is_none(tmp_path):
    w(tmp_path / 'kr_market_data.json', {'report_date': RD})
    w(tmp_path / 'kr_index_etf.json', [])
    assert S.stamp(str(tmp_path))['files']['kr_index_etf.json']['collect_in'] == 'none'


def test_cli_prints_and_warns(tmp_path, capsys):
    w(tmp_path / 'market_data.json', {'report_date': RD, 'collect': C.failed(RD, 'x', 'boom')})
    assert S.main(['--datadir', str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert '::warning::수집 상태 failed: market_data.json' in out
