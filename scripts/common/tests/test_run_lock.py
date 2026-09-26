"""루틴 선점 잠금 — 임시 bare 레포로 실제 git push 를 돌려 본다."""
import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / 'ci' / 'run_lock.sh'


def _git(cwd, *args, env=None):
    return subprocess.run(['git', *args], cwd=cwd, env=env, capture_output=True, text=True, check=True)


def _clone(tmp_path, name, remote):
    d = tmp_path / name
    subprocess.run(['git', 'clone', '-q', str(remote), str(d)], check=True, capture_output=True)
    return d


def _run(cwd, *args):
    return subprocess.run(['bash', str(SCRIPT), *args], cwd=cwd, capture_output=True, text=True)


def _setup(tmp_path):
    remote = tmp_path / 'remote.git'
    subprocess.run(['git', 'init', '-q', '--bare', str(remote)], check=True)
    return _clone(tmp_path, 'a', remote), _clone(tmp_path, 'b', remote)


def test_only_the_first_run_gets_the_lock(tmp_path):
    a, b = _setup(tmp_path)
    assert _run(a, 'acquire', 'us-2026-09-26').returncode == 0
    r = _run(b, 'acquire', 'us-2026-09-26')
    assert r.returncode == 3 and 'held by another run' in r.stdout


def test_a_different_day_is_a_different_lock(tmp_path):
    a, b = _setup(tmp_path)
    assert _run(a, 'acquire', 'us-2026-09-26').returncode == 0
    assert _run(b, 'acquire', 'us-2026-09-27').returncode == 0


def test_a_stale_lock_is_taken_over(tmp_path):
    a, b = _setup(tmp_path)
    assert _run(a, 'acquire', 'us-2026-09-26').returncode == 0
    # stale_minutes=0 이면 방금 잡힌 잠금도 오래된 것으로 본다 — 죽은 런의 잠금을 넘겨받는 경로.
    r = _run(b, 'acquire', 'us-2026-09-26', '0')
    assert r.returncode == 0 and 'took over' in r.stdout


def test_release_frees_the_lock(tmp_path):
    a, b = _setup(tmp_path)
    assert _run(a, 'acquire', 'us-2026-09-26').returncode == 0
    assert _run(a, 'release', 'us-2026-09-26').returncode == 0
    assert _run(b, 'acquire', 'us-2026-09-26').returncode == 0


def test_unreachable_remote_does_not_proceed(tmp_path):
    a, _ = _setup(tmp_path)
    env = dict(os.environ, RUN_LOCK_REMOTE='nowhere')
    r = subprocess.run(['bash', str(SCRIPT), 'acquire', 'x'], cwd=a, env=env, capture_output=True, text=True)
    assert r.returncode == 4
