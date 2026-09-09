"""Automatic correction consumes ready drafts independently of Codex quota."""
import sys
from types import SimpleNamespace

import review_gate as gate
from review.tests.test_run_cli import (repo, git, write, POST, KR_POST, PAGE,
                                      state_of, fake_codex, run)


def invoke(repo, monkeypatch, correct):
    monkeypatch.setattr(gate, 'repo_root', lambda: repo)
    monkeypatch.setitem(sys.modules, 'review.corrector',
                        SimpleNamespace(correct_one=correct))
    return gate.cmd_run(SimpleNamespace(timeout=10, correct=True, correction_timeout=10))


def test_ready_drafts_run_without_new_codex_calls(repo, tmp_path, monkeypatch):
    run(repo, 'run', codex=fake_codex(tmp_path))
    calls = []
    def correct(root, item, draft, commit, timeout):
        calls.append(item.path)
        assert draft == '지적 없음' and commit
        return '검증 완료', None
    assert invoke(repo, monkeypatch, correct) == 0
    assert set(calls) == {POST, KR_POST}
    assert state_of(repo)['correction_calls']


def test_correction_failure_is_reserved_and_stops_tick(repo, tmp_path, monkeypatch):
    run(repo, 'run', codex=fake_codex(tmp_path))
    calls = []
    def correct(*args):
        calls.append(args[1].path)
        return '', 'Claude failed'
    for _ in range(2):
        assert invoke(repo, monkeypatch, correct) == 1
    assert len(calls) == 2 and calls[0] == calls[1]
    assert '정정-us' in state_of(repo)['errors']


def test_published_ledger_prevents_repeat_with_stale_local_ledger(repo, tmp_path, monkeypatch):
    import json
    run(repo, 'run', codex=fake_codex(tmp_path))
    ledger = {'reviewed': {p: {'sha': git(repo, 'rev-parse', f'HEAD:{p}').stdout.strip(),
                              'at': '2026-09-10T00:00:00+09:00', 'findings': 0}
                           for p in (POST, KR_POST)}}
    write(repo, 'reviews/index.json', json.dumps(ledger))
    git(repo, 'add', 'reviews/index.json')
    git(repo, 'commit', '-qm', 'reviewed remotely')
    git(repo, 'push', '-q', 'origin', 'main')
    write(repo, 'reviews/index.json', '{"reviewed": {}}')
    def forbidden(*args):
        raise AssertionError('already reviewed remote version was called again')
    assert invoke(repo, monkeypatch, forbidden) == 0
