"""close_guard.py 명령 — 오케스트레이터가 부르는 그대로."""

import json
import os
import subprocess
import sys

import pytest

from close import flow, leak

SCRIPTS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GUARD = os.path.join(SCRIPTS, 'close_guard.py')
P1 = '유가가 2% 올랐다. 금리가 내렸다. 달러는 보합권에서 움직이며 장을 마쳤다는 점이 눈에 띄었다.'
P3 = '이 문단은 길게 써서 후보가 되지 않게 한 문장으로 끝까지 이어 쓰며 문맥을 주는 역할만 하도록 둔다.'
EDIT = '유가가 2% 올랐고 금리가 내렸다. 달러는 보합권에서 움직이며 장을 마쳤다는 점이 눈에 띄었다.'


def g(*args, cwd=None):
    r = subprocess.run([sys.executable, GUARD, *args], capture_output=True, text=True, cwd=cwd)
    return r.returncode, r.stdout


@pytest.fixture
def cd(tmp_path, monkeypatch):
    d = tmp_path / 'close'
    d.mkdir()
    monkeypatch.setenv('CLOSE_DIR', str(d))
    html = '<html><body><h2>시장</h2><div class="card"><p>%s</p><p>%s</p></div></body></html>' % (P1, P3)
    (d / 'pre.html').write_text(html, encoding='utf-8')
    (d / 'candidates.json').write_text(json.dumps(flow.scan(html), ensure_ascii=False), encoding='utf-8')
    (d / 'edits.json').write_text(json.dumps({'C01': EDIT}, ensure_ascii=False), encoding='utf-8')
    return d


def _check(d, *extra):
    return g('check', str(d / 'pre.html'), str(d / 'candidates.json'), str(d / 'edits.json'),
             '--out', str(d / 'pairs.json'), '--no-write', *extra)


def _apply(d, *extra):
    return g('apply', str(d / 'pre.html'), str(d / 'candidates.json'), str(d / 'edits.json'),
             str(d / 'pairs.json'), str(d / 'verdicts.json'), '--out', str(d / 'approved.html'),
             '--audit', str(d / 'audit.json'), '--no-write', *extra)


def _verdict(d, v='same'):
    pairs = json.loads((d / 'pairs.json').read_text())
    (d / 'verdicts.json').write_text(json.dumps({'proposed_sha256': pairs['proposed_sha256'], 'verdicts': {
        b['id']: {'verdict': v, 'why': '관계·세기·주체가 그대로다'} for b in pairs['bundles']}}, ensure_ascii=False))


def test_check_apply_roundtrip(cd):
    code, out = _check(cd)
    assert code == 0 and 'passed 1' in out, out
    assert (cd / 'proposed.html').exists() and (cd / 'checker_input.txt').exists()
    _verdict(cd)
    code, out = _apply(cd)
    assert code == 0 and out.strip().endswith('close: applied 1'), out
    assert '올랐고' in (cd / 'approved.html').read_text()
    audit = json.loads((cd / 'audit.json').read_text())
    assert audit['outcome'] == 'applied' and audit['applied_edits'] == ['C01'] and audit['uuid']


def test_pairs_tampered_after_approval(cd):
    _check(cd)
    _verdict(cd)
    pairs = json.loads((cd / 'pairs.json').read_text())
    pairs['bundles'][0]['after'] = ['완전히 다른 글']
    (cd / 'pairs.json').write_text(json.dumps(pairs, ensure_ascii=False))
    # pairs 의 묶음 텍스트는 믿지 않는다 — 다시 만든 판 해시가 같으면 반영, 승인 대상은 다시 만든 판
    code, out = _apply(cd)
    assert code == 0 and 'applied 1' in out
    # edits 를 승인 뒤 바꾸면 다시 만든 판이 달라 편집 0
    (cd / 'edits.json').write_text(json.dumps({'C01': EDIT.replace('올랐고', '오르고')}, ensure_ascii=False))
    code, out = _apply(cd)
    assert 'zero' in out
    assert (cd / 'approved.html').read_bytes() == (cd / 'pre.html').read_bytes()


def test_changed_verdict_writes_pre(cd):
    _check(cd)
    _verdict(cd, 'changed')
    code, out = _apply(cd)
    assert code == 0 and 'zero' in out
    assert (cd / 'approved.html').read_bytes() == (cd / 'pre.html').read_bytes()
    assert json.loads((cd / 'audit.json').read_text())['outcome'] == 'checker_rejected'


def test_missing_verdicts_file_zero(cd):
    _check(cd)
    code, out = _apply(cd)
    assert code == 0 and 'zero' in out


def test_expect_pre_mismatch_exit_3(cd):
    _check(cd)
    _verdict(cd)
    code, out = _apply(cd, '--expect-pre', '0' * 64)
    assert code == 3


def test_expect_cand_mismatch_exit_2(cd):
    code, _ = _check(cd, '--expect-cand', '0' * 64)
    assert code == 2


def test_output_inside_repo_exit_2(cd):
    code, _ = g('check', str(cd / 'pre.html'), str(cd / 'candidates.json'), str(cd / 'edits.json'),
                '--out', os.path.join(os.path.dirname(SCRIPTS), 'pairs_leak.json'), '--no-write')
    assert code == 2
    assert not os.path.exists(os.path.join(os.path.dirname(SCRIPTS), 'pairs_leak.json'))


def test_bad_edits_json_exit_2(cd):
    (cd / 'edits.json').write_text('{not json')
    assert _check(cd)[0] == 2


def test_missing_pre_exit_3(cd):
    os.remove(cd / 'pre.html')
    assert _check(cd)[0] == 3


def test_zero_command(cd):
    code, out = g('zero', str(cd / 'pre.html'), '--out', str(cd / 'approved.html'),
                  '--audit', str(cd / 'audit.json'), '--outcome', 'no_candidates')
    assert code == 0
    assert (cd / 'approved.html').read_bytes() == (cd / 'pre.html').read_bytes()
    assert json.loads((cd / 'audit.json').read_text())['outcome'] == 'zero:no_candidates'


def test_verify_file(cd):
    (cd / 'target.html').write_bytes((cd / 'pre.html').read_bytes())
    assert g('verify', str(cd / 'pre.html'), str(cd / 'target.html'))[0] == 0
    (cd / 'target.html').write_text((cd / 'pre.html').read_text().replace('유가', '원유'))
    assert g('verify', str(cd / 'pre.html'), str(cd / 'target.html'))[0] == 1


# ---------------------------------------------------------------- 누출 검사

def _git(repo, *a):
    subprocess.run(['git', '-C', str(repo), *a], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / 'repo'
    r.mkdir()
    _git(r, 'init', '-q')
    _git(r, 'config', 'user.email', 't@t')
    _git(r, 'config', 'user.name', 't')
    (r / 'posts.json').write_text('[]\n')
    (r / 'chart.png').write_bytes(b'\x89PNG\x00\x01')
    _git(r, 'add', '-A')
    _git(r, 'commit', '-qm', 'init')
    return r


def test_snapshot_detects_new_untracked_and_modified(repo):
    a = leak.snapshot(str(repo))
    (repo / 'notes.txt').write_text('감사 기록 사본')
    b = leak.snapshot(str(repo))
    assert leak.compare(a, b) == ['untracked:notes.txt']
    (repo / 'posts.json').write_text('[1]\n')
    c = leak.snapshot(str(repo))
    assert 'work:posts.json' in leak.compare(b, c)


def test_snapshot_detects_already_modified_binary_modified_again(repo):
    (repo / 'chart.png').write_bytes(b'\x89PNG\x00\x02')          # STEP 2.6 전에 이미 수정됨
    before = leak.snapshot(str(repo))
    (repo / 'chart.png').write_bytes(b'\x89PNG\x00\x03 hidden')   # STEP 2.6 중 다시 바뀜
    after = leak.snapshot(str(repo))
    assert leak.compare(before, after) == ['work:chart.png']
    # git diff 의 텍스트는 두 번 모두 「Binary files differ」 — 그걸 해시했으면 놓쳤다
    d1 = subprocess.run(['git', '-C', str(repo), 'diff', '--stat'], capture_output=True, text=True).stdout
    assert 'Bin' in d1


def test_snapshot_detects_staged_change(repo):
    a = leak.snapshot(str(repo))
    (repo / 'posts.json').write_text('[2]\n')
    _git(repo, 'add', 'posts.json')
    b = leak.snapshot(str(repo))
    assert 'index:posts.json' in leak.compare(a, b)


def test_snapshot_unchanged_is_clean(repo):
    assert leak.compare(leak.snapshot(str(repo)), leak.snapshot(str(repo))) == []


def test_leak_compare_cli(repo, tmp_path, monkeypatch):
    monkeypatch.delenv('CLOSE_DIR', raising=False)
    d = tmp_path / 'cd'
    d.mkdir()
    assert g('snapshot', '--repo', str(repo), '--out', str(d / 'a.json'))[0] == 0
    (repo / 'x.json').write_text('{}')
    assert g('snapshot', '--repo', str(repo), '--out', str(d / 'b.json'))[0] == 0
    code, out = g('leak-compare', str(d / 'a.json'), str(d / 'b.json'))
    assert code == 1 and 'untracked:x.json' in out and '{}' not in out


AUDIT = {'uuid': 'a1b2c3d4e5f6a7b8c9d0', 'proposed_sha256': 'e' * 64, 'rounds': [
    {'bundles': [{'hash': 'd' * 64}], 'verdicts': {'B01': {'verdict': 'same', 'why': '주체와 관계가 그대로 유지된다'}}}]}


def test_staged_scan_finds_audit_in_existing_file(repo, tmp_path):
    (tmp_path / 'audit.json').write_text(json.dumps(AUDIT, ensure_ascii=False))
    (repo / 'posts.json').write_text('[{"date": "2026-11-06", "note": "주체와 관계가 그대로 유지된다"}]\n')
    _git(repo, 'add', '-A')
    code, out = g('staged-scan', '--repo', str(repo), '--audit', str(tmp_path / 'audit.json'))
    assert code == 1 and 'posts.json' in out


@pytest.mark.parametrize('text', ['{"outcome": "applied"}', 'id a1b2c3d4e5f6a7b8c9d0', 'eeee' * 16])
def test_staged_scan_fingerprints(repo, tmp_path, text):
    (tmp_path / 'audit.json').write_text(json.dumps(AUDIT, ensure_ascii=False))
    (repo / 'new.txt').write_text(text)
    _git(repo, 'add', '-A')
    assert g('staged-scan', '--repo', str(repo), '--audit', str(tmp_path / 'audit.json'))[0] == 1


def test_staged_scan_clean(repo, tmp_path):
    (tmp_path / 'audit.json').write_text(json.dumps(AUDIT, ensure_ascii=False))
    (repo / 'posts.json').write_text('[{"date": "2026-11-06"}]\n')
    _git(repo, 'add', '-A')
    assert g('staged-scan', '--repo', str(repo), '--audit', str(tmp_path / 'audit.json'))[0] == 0


def test_verify_git_blob(repo, tmp_path):
    (tmp_path / 'ok.html').write_text('[]\n')
    assert g('verify', str(tmp_path / 'ok.html'), '--git', 'HEAD:posts.json', '--repo', str(repo))[0] == 0
    (tmp_path / 'ok.html').write_text('[9]\n')
    assert g('verify', str(tmp_path / 'ok.html'), '--git', 'HEAD:posts.json', '--repo', str(repo))[0] == 1


def test_kill_switch_default_off():
    from close import paths
    assert paths.enabled() is False
    with open(paths.CONFIG, encoding='utf-8') as fh:
        assert json.load(fh) == {'enabled': False}


def test_kill_switch_broken_is_off(tmp_path):
    from close import paths
    p = tmp_path / 'c.json'
    p.write_text('{"enabled": "true"}')
    assert paths.enabled(str(p)) is False
    p.write_text('nope')
    assert paths.enabled(str(p)) is False
    p.write_text('{"enabled": true}')
    assert paths.enabled(str(p)) is True


def test_writer_prompt_has_rules_and_candidates(cd):
    code, out = g('writer-prompt', str(cd / 'candidates.json'), '--out', str(cd / 'w.txt'))
    assert code == 0, out
    text = (cd / 'w.txt').read_text()
    assert '## 13.' in text and '[C01] ' + P1 in text
    assert str(cd) not in text          # 파일 경로를 주지 않는다
    assert '## 12.' not in text         # §13 만


def test_enabled_command_off_by_default():
    code, out = g('enabled')
    assert code == 1 and out.strip() == 'close: off'
