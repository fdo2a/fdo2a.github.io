"""입력 자료·검사 결과·발행 대상이 **같은 실행**에 속하는가(2026-11-18 사용자 추가 지시, 3회차 G4 강화).

이미 있던 것: 기록의 글 해시(`post.sha256`), 입력 파일마다의 해시(`inputs.files` — 수집 장부 `_collect_status.json` 도 자료
폴더의 파일이라 여기 들어 있다), verify 의 글·입력·검사 코드·레포 원장 대조, 장부 항목의 sha256 과 디스크 파일의 대조
(`changed_after_collect`). 비어 있던 것: 기록에 **어느 수집 실행의 장부를 읽었는지**(실행 ID·장부 해시·장부 날짜)가 따로
없었고, 장부의 날짜가 글 날짜와 다른 것을 보지 않았다. 여기서 앞선 실행의 것이 새 실행에 섞이는 경로를 하나씩 재현한다.
"""
import json
import os
import subprocess

import pytest

from verification import inputs as I
from verification import record as R
from verification.tests.test_record import (PASS, cli, commit_all, config, g, gate, record_args, repo,  # noqa: F401
                                            verify, write_post)

D = '2026-11-06'


def ledger(repo, run_id, files=None, date=D):
    import hashlib
    ws = repo / 'ws'
    ent = {}
    for name in files or ['market_data.json']:
        raw = (ws / name).read_bytes()
        ent[name] = {'present': True, 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw), 'run': 'written'}
    (ws / '_collect_status.json').write_text(json.dumps({
        'format': 'collect-status/1', 'market': 'us', 'report_date': date, 'run_id': run_id,
        'run': {'run_id': run_id, 'open': False, 'checked': True}, 'files': ent}))


def recorded(repo):
    return json.loads((repo / 'verification' / 'us' / f'{D}.json').read_text())


def setup(repo):
    gate(repo, 'ok', PASS)
    cfg = config(repo, [g('ok')])
    html = write_post(repo)
    ledger(repo, 'run-1')
    assert cli(repo, *record_args(repo, html), cfg=cfg).returncode == 0
    commit_all(repo)
    return cfg, html


def test_record_names_the_collection_run_it_read(repo):
    cfg, _ = setup(repo)
    rec = recorded(repo)
    cr = rec['collect_run']
    assert cr['run_id'] == 'run-1' and cr['report_date'] == D and cr['checked'] is True      # 재현: 전에는 칸이 없었다
    by = {f['path']: f['sha256'] for f in rec['inputs']['files']}
    assert cr['sha256'] == by['<datadir>/_collect_status.json']                              # 입력 해시 목록의 그 파일
    assert rec['post']['sha256'] and '<datadir>/market_data.json' in by
    assert verify(repo, '--rev', 'HEAD', cfg=cfg).returncode == 0


def test_verify_rejects_a_ledger_from_another_run(repo):
    # 기록은 옛 실행(run-1)의 장부를 읽었는데 디스크의 장부는 새 실행(run-2) 것
    cfg, _ = setup(repo)
    ledger(repo, 'run-2')
    p = verify(repo, '--rev', 'HEAD', cfg=cfg)
    assert p.returncode == 1 and '수집 실행이 다르다' in p.stdout and 'run-1' in p.stdout and 'run-2' in p.stdout


def test_verify_rejects_new_inputs_under_the_old_record(repo):
    # 입력만 새 실행의 것으로 바뀌었다(장부는 그대로) — 기록의 입력 해시와 다르다
    cfg, _ = setup(repo)
    (repo / 'ws' / 'market_data.json').write_text('{"report_date": "2026-11-06", "v": 2}')
    p = verify(repo, '--rev', 'HEAD', cfg=cfg)
    assert p.returncode == 1 and '입력 데이터가 바뀌었다' in p.stdout


def test_verify_rejects_a_new_post_under_the_old_record(repo):
    cfg, html = setup(repo)
    write_post(repo, open(html, encoding='utf-8').read().replace('본문', '본문 고침'))
    commit_all(repo, 'rewrite')
    p = verify(repo, '--rev', 'HEAD', cfg=cfg)
    assert p.returncode == 1 and '글 해시가 다르다' in p.stdout


def test_verify_rejects_a_removed_or_unreadable_ledger(repo):
    cfg, _ = setup(repo)
    os.unlink(repo / 'ws' / '_collect_status.json')
    p = verify(repo, '--rev', 'HEAD', cfg=cfg)
    assert p.returncode == 1 and ('수집 실행' in p.stdout or '입력 데이터가 바뀌었다' in p.stdout)
    (repo / 'ws' / '_collect_status.json').write_text('{')
    p = verify(repo, '--rev', 'HEAD', cfg=cfg)
    assert p.returncode == 1 and '수집 실행' in p.stdout


def test_record_without_a_ledger_says_so_and_still_verifies(repo):
    # 장부가 없는 날(적용일 전) — 기록은 「장부 없음」을 적는다. 나중에 장부가 생기면 다른 실행이다
    gate(repo, 'ok', PASS)
    cfg = config(repo, [g('ok')])
    html = write_post(repo)
    assert cli(repo, *record_args(repo, html), cfg=cfg).returncode == 0
    commit_all(repo)
    assert recorded(repo)['collect_run'] == {'present': False}
    assert verify(repo, '--rev', 'HEAD', cfg=cfg).returncode == 0
    ledger(repo, 'run-9')
    p = verify(repo, '--rev', 'HEAD', cfg=cfg)
    assert p.returncode == 1 and '수집 실행이 다르다' in p.stdout


# ── 장부와 입력이 서로 다른 실행의 것 ──────────────────────────────────────

META = {'path': '<datadir>/_collect_status.json', 'class': 'gate', 'name': '수집 상태 기록', 'optional': True,
        'required_when_enforced': True, 'produced_by': 'meta'}
MD = {'path': '<datadir>/market_data.json', 'class': 'gate', 'name': '시장 데이터', 'date': 'report_date'}
STAMP = {'status': 'ok', 'as_of': D, 'collected_at': '2026-11-07T08:00:00+09:00', 'source': 't', 'response': 'ok',
         'required_ok': True, 'missing': [], 'empty': 'has_data'}


def _assess(tmp_path, ledger_obj, effective, monkeypatch, body=None):
    from verification.tests.test_inputs import policy
    monkeypatch.setattr(I, 'EFFECTIVE', effective)
    (tmp_path / 'market_data.json').write_text(json.dumps(body or {'report_date': D, 'collect': STAMP}))
    (tmp_path / '_collect_status.json').write_text(json.dumps(ledger_obj))
    return I.assess(policy([META, MD]), 'us', {'datadir': str(tmp_path), 'date': D})['files']


def _sha(p):
    import hashlib
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_new_ledger_with_old_input_is_caught_by_the_hash(tmp_path, monkeypatch):
    # 장부만 새 실행의 것(다른 바이트의 해시), 입력은 옛 실행의 파일 — 적용일과 무관하게 막는다
    (tmp_path / 'market_data.json').write_text(json.dumps({'report_date': D, 'collect': STAMP}))
    book = {'report_date': D, 'run_id': 'run-2', 'files': {'market_data.json': {'sha256': 'f' * 64, 'run': 'written'}}}
    for eff in (None, D):
        f = _assess(tmp_path, book, eff, monkeypatch)['<datadir>/market_data.json']
        assert f['state'] == 'changed_after_collect' and f['blocking'], eff


def test_ledger_of_another_session_blocks_from_effective(tmp_path, monkeypatch):
    (tmp_path / 'market_data.json').write_text(json.dumps({'report_date': D, 'collect': STAMP}))
    ok = {'report_date': D, 'run_id': 'run-1',
          'files': {'market_data.json': {'sha256': _sha(tmp_path / 'market_data.json'), 'run': 'written'}}}
    assert not _assess(tmp_path, ok, D, monkeypatch)['<datadir>/_collect_status.json']['blocking']
    for bad in (dict(ok, report_date='2026-11-05'), {k: v for k, v in ok.items() if k != 'report_date'},
                {k: v for k, v in ok.items() if k != 'run_id'}, dict(ok, run_id='')):
        f = _assess(tmp_path, bad, D, monkeypatch)['<datadir>/_collect_status.json']
        assert f['blocking'] and f['state'] in ('stale', 'incomplete_fields'), bad      # 재현: 전에는 ok
        # 적용일 전에는 장부가 필수가 아니다 — 막지 않는다
        assert not _assess(tmp_path, bad, None, monkeypatch)['<datadir>/_collect_status.json']['blocking']
