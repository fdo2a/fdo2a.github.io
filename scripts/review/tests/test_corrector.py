"""Real Git boundary checks with a fake Claude (no model/network calls)."""
import json
from pathlib import Path
import subprocess

import pytest

from scripts.review.corrector import correct_one
from scripts.review.queue import Pending


def git(root, *args):
    return subprocess.check_output(['git', *args], cwd=root, text=True).strip()


@pytest.fixture
def setup(tmp_path, monkeypatch):
    remote, root = tmp_path / 'remote.git', tmp_path / 'local'
    git(tmp_path, 'init', '--bare', str(remote))
    git(tmp_path, 'clone', str(remote), str(root))
    git(root, 'checkout', '-b', 'main')
    for key, value in [('user.name', 'Test'), ('user.email', 'test@example.com')]:
        monkeypatch.setenv('GIT_AUTHOR_' + ('NAME' if key.endswith('name') else 'EMAIL'), value)
        monkeypatch.setenv('GIT_COMMITTER_' + ('NAME' if key.endswith('name') else 'EMAIL'), value)
    for path, content in {'posts/2026-09-10.html': '<p>old 1</p>',
                          'data/evidence.json': '{}',
                          '.claude/REVIEW_GATE.md': 'Review facts.',
                          'reviews/index.json': '{"reviewed":{}}'}.items():
        dest = root / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content)
    git(root, 'add', '.')
    git(root, 'commit', '-m', 'publish')
    git(root, 'push', '-u', 'origin', 'main')
    item = Pending('posts/2026-09-10.html', 'us', git(root, 'rev-parse', 'HEAD:posts/2026-09-10.html'), 'new')
    # Trusted local gate scripts are deliberately absent from the origin clone.
    scripts = root / 'scripts'
    scripts.mkdir()
    for name in ('macro', 'fed', 'weight', 'price_context',
                 'session', 'readability', 'style'):
        (scripts / f'check_{name}.py').write_text('''import sys
from pathlib import Path
assert all('gate-evidence' in x for x in sys.argv[1:] if x.endswith('/data'))
assert not any('repo/data' in x for x in sys.argv)
with (Path(__file__).parent / 'gate-calls.txt').open('a') as f:
    f.write(Path(__file__).name + '\\n')
print('gate passed')
''')
    (scripts / 'verify_post.py').write_text('''import sys
assert sys.argv[2] == '--before' and sys.argv[1] == sys.argv[3]
print('layout passed')
''')
    executable = tmp_path / 'claude'
    monkeypatch.setenv('CLAUDE_BIN', str(executable))
    return root, remote, item, executable


def fake(executable, extra='', mark=True):
    executable.write_text('''#!/usr/bin/env python3
import json, subprocess, sys
from pathlib import Path
prompt = sys.stdin.read()
assert 'HISTORICAL' in prompt
assert '--permission-mode' in sys.argv
Path('posts/2026-09-10.html').write_text('<p>fixed 2</p>')
''' + extra + ('''
sha = subprocess.check_output(['git','hash-object','posts/2026-09-10.html'],text=True).strip()
Path('reviews/index.json').write_text(json.dumps({'reviewed':{'posts/2026-09-10.html':{'sha':sha,'at':'now','findings':1}}}))
''' if mark else '') + '''
subprocess.run(['git','add','.'],check=True)
subprocess.run(['git','commit','-m','verified correction'],check=True)
print('corrected and checked')
''')
    executable.chmod(0o755)


def test_success_keeps_user_checkout(setup):
    root, remote, item, exe = setup
    fake(exe)
    base = git(root, 'rev-parse', 'HEAD')
    (root / item.path).write_text('user unsaved work')
    result, error = correct_one(root, item, 'wrong value', base, 10)
    assert error is None, error
    assert 'corrected' in result
    assert git(remote, 'show', 'main:' + item.path) == '<p>fixed 2</p>'
    assert (root / item.path).read_text() == 'user unsaved work'
    assert git(root, 'rev-parse', 'HEAD') == base
    # Seven gates on the original (baseline) and the same seven on the correction.
    assert len((root / 'scripts/gate-calls.txt').read_text().splitlines()) == 14


@pytest.mark.parametrize('extra,mark,reason', [
    ('', False, 'ledger'),
    ("Path('unauthorized').write_text('no')\n", True, 'unauthorized'),
])
def test_rejects_unmarked_or_unrelated(setup, extra, mark, reason):
    root, remote, item, exe = setup
    fake(exe, extra, mark)
    base = git(root, 'rev-parse', 'HEAD')
    _, error = correct_one(root, item, 'review', base, 10)
    assert reason in error
    assert git(remote, 'rev-parse', 'main') == base


def test_stale_post(setup):
    root, remote, item, exe = setup
    base = git(root, 'rev-parse', 'HEAD')
    (root / item.path).write_text('new remote version')
    git(root, 'commit', '-am', 'new publication')
    git(root, 'push')
    _, error = correct_one(root, item, 'review', base, 10)
    assert 'changed before' in error


def test_timeout(setup):
    root, remote, item, exe = setup
    fake(exe, 'import time; time.sleep(10)\n')
    base = git(root, 'rev-parse', 'HEAD')
    _, error = correct_one(root, item, 'review', base, 0.05)
    assert 'timeout' in error
    assert git(remote, 'rev-parse', 'main') == base


def test_claude_failure(setup):
    root, remote, item, exe = setup
    fake(exe, 'sys.exit(7)\n')
    base = git(root, 'rev-parse', 'HEAD')
    _, error = correct_one(root, item, 'review', base, 10)
    assert 'exited 7' in error
    assert git(remote, 'rev-parse', 'main') == base


def test_concurrent_remote_change(setup):
    root, remote, item, exe = setup
    base = git(root, 'rev-parse', 'HEAD')
    fake(exe, f'''
subprocess.run(['git','-C',{str(root)!r},'commit','--allow-empty','-m','concurrent publication'],check=True)
subprocess.run(['git','-C',{str(root)!r},'push'],check=True)
''')
    _, error = correct_one(root, item, 'review', base, 10)
    assert 'remote main changed' in error
    assert git(remote, 'show', 'main:' + item.path) == '<p>old 1</p>'


@pytest.mark.parametrize('failure', ['nonzero', 'missing', 'layout_unavailable'])
def test_independent_gate_blocks_push(setup, failure):
    root, remote, item, exe = setup
    fake(exe)
    base = git(root, 'rev-parse', 'HEAD')
    if failure == 'nonzero':
        # Passes on the original, fails only on the corrected post — a regression.
        (root / 'scripts/check_macro.py').write_text(
            "import sys\nfrom pathlib import Path\n"
            "post = sys.argv[sys.argv.index('--html') + 1]\n"
            "if 'fixed' in Path(post).read_text(): raise SystemExit('invalid HTML')\n")
    elif failure == 'missing':
        (root / 'scripts/check_macro.py').unlink()
    else:
        (root / 'scripts/verify_post.py').write_text("print('Playwright가 없어 레이아웃 검사는 건너뛴다')")
    _, error = correct_one(root, item, 'review', base, 10)
    assert error
    assert git(remote, 'rev-parse', 'main') == base


def test_every_replayed_gate_exists_in_the_real_repo():
    """픽스처는 게이트 스크립트를 가짜로 만든다 — 지워진 게이트는 여기서만 드러난다."""
    from pathlib import Path
    from scripts.review import corrector
    real = Path(__file__).resolve().parents[2]
    names = {'macro', *corrector.US_DATADIR_GATES, *corrector.KR_DATADIR_GATES}
    missing = [n for n in names if not (real / f'check_{n}.py').is_file()]
    assert missing == []


def _claude_calls(tmp):
    marker = tmp / 'claude-called'
    return marker.read_text().count('x') if marker.exists() else 0


def _counting(exe, extra=''):
    """fake() plus a marker so a test can prove Claude was (not) invoked."""
    fake(exe, f"Path({str(exe.parent / 'claude-called')!r}).open('a').write('x')\n" + extra)


def test_gate_failing_on_original_does_not_block(setup):
    """발행 뒤에 생긴 게이트는 원본부터 실패한다 — 정정을 버릴 이유가 아니다(2026-09-21 KR)."""
    root, remote, item, exe = setup
    (root / 'scripts/check_weight.py').write_text("raise SystemExit('판단군이 하한에 못 미친다')")
    _counting(exe, "assert 'check_weight.py' in prompt\n")
    base = git(root, 'rev-parse', 'HEAD')
    result, error = correct_one(root, item, 'wrong value', base, 10)
    assert error is None, error
    assert 'pre-existing' in result
    assert git(remote, 'show', 'main:' + item.path) == '<p>fixed 2</p>'


def test_untracked_leftovers_do_not_discard_correction(setup):
    root, remote, item, exe = setup
    _counting(exe, "import atexit\natexit.register(lambda: Path('scratch-notes.txt').write_text('tmp'))\n")
    base = git(root, 'rev-parse', 'HEAD')
    _, error = correct_one(root, item, 'wrong value', base, 10)
    assert error is None, error
    assert git(remote, 'show', 'main:' + item.path) == '<p>fixed 2</p>'


def test_uncommitted_tracked_change_names_the_file(setup):
    root, remote, item, exe = setup
    fake(exe, "import atexit\natexit.register(lambda: Path('data/evidence.json').write_text('{\"x\": 1}'))\n")
    base = git(root, 'rev-parse', 'HEAD')
    _, error = correct_one(root, item, 'review', base, 10)
    assert 'data/evidence.json' in error
    assert git(remote, 'rev-parse', 'main') == base


@pytest.mark.parametrize('broken', ['missing', 'layout_unavailable'])
def test_unrunnable_gate_stops_before_claude(setup, tmp_path, broken):
    """게이트를 못 돌리는 환경이면 결과를 어차피 버린다 — 모델을 부르기 전에 멈춘다."""
    root, remote, item, exe = setup
    _counting(exe)
    if broken == 'missing':
        (root / 'scripts/check_style.py').unlink()
    else:
        (root / 'scripts/verify_post.py').write_text("print('Playwright가 없어 레이아웃 검사는 건너뛴다')")
    base = git(root, 'rev-parse', 'HEAD')
    _, error = correct_one(root, item, 'review', base, 10)
    assert error
    assert _claude_calls(tmp_path) == 0
    assert git(remote, 'rev-parse', 'main') == base


def test_model_is_pinned(setup, monkeypatch):
    root, remote, item, exe = setup
    fake(exe, "i = sys.argv.index('--model'); assert sys.argv[i + 1] == 'test-model'\n")
    monkeypatch.setenv('CLAUDE_CORRECTION_MODEL', 'test-model')
    base = git(root, 'rev-parse', 'HEAD')
    _, error = correct_one(root, item, 'review', base, 10)
    assert error is None, error
