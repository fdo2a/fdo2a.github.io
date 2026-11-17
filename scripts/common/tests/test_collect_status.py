"""수집 상태 칸 도우미 — 「성공」과 「대상 없음 확인」을 따로 적는 규칙이 코드로 강제되는가."""
import json

import pytest

from scripts.common import collect_status as C


def test_ok_confirmed_none_is_kept():
    c = C.build('ok', '2026-11-16', 'x', empty='confirmed_none', checked=60)
    assert c['status'] == 'ok' and c['empty'] == 'confirmed_none' and c['required_ok'] is True
    assert c['response'] == 'ok' and c['checked'] == 60 and c['missing'] == []
    assert set(c) >= {'status', 'as_of', 'collected_at', 'source', 'response', 'required_ok', 'missing', 'empty'}


@pytest.mark.parametrize('status', ['failed', 'partial'])
def test_confirmed_none_needs_a_complete_query(status):
    c = C.build(status, '2026-11-16', 'x', empty='confirmed_none')
    assert c['empty'] == 'unknown'


def test_failed_forces_required_not_ok_and_unknown():
    c = C.build('failed', '2026-11-16', 'x', empty='has_data', required_ok=True)
    assert c['required_ok'] is False and c['empty'] == 'unknown'
    assert c['response'] == 'failed'


def test_default_empty_is_unknown_not_guessed():
    assert C.build('ok', '2026-11-16', 'x')['empty'] == 'unknown'


def test_bad_values_raise():
    for kw in ({'status': 'done'}, {'empty': 'none'}):
        with pytest.raises(ValueError):
            C.build(kw.get('status', 'ok'), '2026-11-16', 'x', empty=kw.get('empty'))
    with pytest.raises(ValueError):
        C.build('ok', '2026/11/16', 'x')


def test_response_scrubs_queries_and_secrets(monkeypatch):
    monkeypatch.setenv('FRED_API_KEY', 'abcd1234secretkey')
    msg = ('HTTP 400 for https://api.stlouisfed.org/fred/series/observations?series_id=DGS10'
           '&api_key=abcd1234secretkey and key abcd1234secretkey, '
           'https://ecos.bok.or.kr/api/StatisticSearch/ZZZKEY0123/json/kr/1/10 ' + 'x' * 300)
    r = C.failed('2026-11-16', 'FRED', msg)['response']
    assert 'abcd1234secretkey' not in r and 'series_id' not in r and 'ZZZKEY0123' not in r
    assert len(r) <= C.RESPONSE_MAX and '\n' not in r


def test_by_counts():
    assert C.by_counts('2026-11-16', 'x', [], 3)['status'] == 'ok'
    p = C.by_counts('2026-11-16', 'x', ['a'], 3)
    assert p['status'] == 'partial' and p['required_ok'] is False and p['missing'] == ['a']
    assert C.by_counts('2026-11-16', 'x', ['a', 'b', 'c'], 3)['status'] == 'failed'


def test_sidecar_record_merges_and_keeps_hashes(tmp_path):
    (tmp_path / C.STATUS_FILE).write_text(json.dumps(
        {'format': C.FORMAT, 'files': {'a.json': {'sha256': 'h', 'bytes': 3, 'status': 'ok'},
                                       'b.json': {'sha256': 'z', 'bytes': 1}}}))
    C.record_sidecar(str(tmp_path), 'a.json', C.failed('2026-11-16', 'x', 'boom'))
    book = json.loads((tmp_path / C.STATUS_FILE).read_text())
    assert book['files']['a.json']['status'] == 'failed'
    assert book['files']['a.json']['sha256'] == 'h'
    assert book['files']['a.json']['collect_in'] == 'sidecar'
    assert book['files']['b.json'] == {'sha256': 'z', 'bytes': 1}


def test_sidecar_on_missing_or_corrupt_book(tmp_path):
    (tmp_path / C.STATUS_FILE).write_text('{not json')
    C.record_sidecar(str(tmp_path), 'kr_top_value.json', C.build('ok', '2026-11-16', 'x', empty='has_data'))
    book = json.loads((tmp_path / C.STATUS_FILE).read_text())
    assert book['format'] == C.FORMAT and book['files']['kr_top_value.json']['status'] == 'ok'
