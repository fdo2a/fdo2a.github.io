"""런처 사본 뜨기 — git archive 를 임시 파일 없이 흘려서 푼다(2026-11-20).

예전에는 archive 출력(약 84MB)을 임시 파일에 받았다가 메모리로 읽어 풀었다 — tick 마다 디스크 쓰기가
한 번 더였다. 이제 파이프에서 바로 풀되, 제한 시간·취소·실패·잘린 출력·경로 탈출은 예전과 같게 막는다.
가짜 git 은 PATH 앞에 둔 스크립트다(진짜 프로세스라 죽였는지·거뒀는지를 pid 로 본다).
"""
import io
import json
import os
import signal
import subprocess
import sys
import tarfile
import threading
import time

import pytest

import runner_launch

FAKE_GIT = '''#!{py}
import os, sys, time
args = sys.argv[1:]
if args[:2] == ['-C', args[1]] and len(args) > 2:
    args = args[2:]
if args[:2] == ['rev-parse', '--show-toplevel']:
    print(os.getcwd()); sys.exit(0)
if args[:1] == ['fetch']:
    sys.exit(0)
if args[:1] == ['rev-parse']:
    print('a' * 40); sys.exit(0)
assert args[:1] == ['archive'], args
open(os.environ['FAKE_PID'], 'w').write(str(os.getpid()))
data = open(os.environ['FAKE_TAR'], 'rb').read() if os.environ.get('FAKE_TAR') else b''
cut = int(os.environ.get('FAKE_CUT', len(data)))
out = sys.stdout.buffer
out.write(data[:cut]); out.flush()
if os.environ.get('FAKE_ERR'):
    sys.stderr.write(os.environ['FAKE_ERR']); sys.stderr.flush()
if os.environ.get('FAKE_SLEEP'):
    time.sleep(float(os.environ['FAKE_SLEEP']))
sys.exit(int(os.environ.get('FAKE_CODE', '0')))
'''


def _tar(members):
    """[(name, bytes | ('sym', target))] → tar 바이트."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w', format=tarfile.PAX_FORMAT) as tar:
        for name, body in members:
            info = tarfile.TarInfo(name)
            if isinstance(body, tuple):
                info.type, info.linkname = tarfile.SYMTYPE, body[1]
                tar.addfile(info)
            else:
                info.size, info.mode = len(body), 0o644
                tar.addfile(info, io.BytesIO(body))
    return buf.getvalue()


GOOD = [('scripts/review_gate.py', b'print(1)\n'), ('data/big.bin', os.urandom(300_000)),
        ('data/small.txt', b'x\n')]


@pytest.fixture
def fake(tmp_path, monkeypatch):
    """가짜 git 을 PATH 앞에 둔다 → (설정 함수, pid 파일, 풀 곳)."""
    bindir = tmp_path / 'bin'
    bindir.mkdir()
    git = bindir / 'git'
    git.write_text(FAKE_GIT.format(py=sys.executable))
    git.chmod(0o755)
    monkeypatch.setenv('PATH', f'{bindir}{os.pathsep}{os.environ["PATH"]}')
    pid = tmp_path / 'pid'
    monkeypatch.setenv('FAKE_PID', str(pid))
    monkeypatch.setattr(runner_launch, 'SIGNALS', None)
    dest = tmp_path / 'dest'
    dest.mkdir()

    def setup(data=b'', **env):
        path = tmp_path / 'archive.tar'
        path.write_bytes(data)
        monkeypatch.setenv('FAKE_TAR', str(path))
        for key, value in env.items():
            monkeypatch.setenv('FAKE_' + key.upper(), str(value))
    return setup, pid, dest


def _gone(pid_file):
    """가짜 git 이 끝났고 거둬졌다 — 좀비로도 남지 않았다."""
    pid = int(pid_file.read_text())
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    return False


def _member_boundary(data, name):
    """`name` 멤버의 헤더가 시작하는 자리 — 그 앞에서 자르면 tarfile 은 깔끔한 끝으로 본다."""
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        for info in tar:
            if info.name == name:
                return info.offset
    raise AssertionError(name)


# --- 정상 경로 ------------------------------------------------------------------

def _real_repo(tmp_path):
    repo = tmp_path / 'repo'
    os.makedirs(repo / 'scripts')
    (repo / 'scripts' / 'review_gate.py').write_text('print(1)\n')
    (repo / 'scripts' / 'run.sh').write_text('#!/bin/sh\n')
    (repo / 'scripts' / 'run.sh').chmod(0o755)
    (repo / 'big.bin').write_bytes(os.urandom(400_000))
    os.symlink('scripts/run.sh', repo / 'link')
    env = dict(os.environ, GIT_AUTHOR_NAME='t', GIT_AUTHOR_EMAIL='t@t', GIT_COMMITTER_NAME='t',
               GIT_COMMITTER_EMAIL='t@t')
    for cmd in (['init', '-q'], ['add', '-A'], ['commit', '-q', '-m', 'x']):
        subprocess.run(['git', '-C', str(repo), *cmd], check=True, env=env)
    oid = subprocess.run(['git', '-C', str(repo), 'rev-parse', 'HEAD'], check=True,
                         capture_output=True, text=True).stdout.strip()
    return str(repo), oid


def test_the_archive_is_never_written_to_a_temp_file(tmp_path, monkeypatch):
    # 84MB 를 tick 마다 임시 파일에 한 번 더 쓰던 것(2026-11-20). 임시 파일은 stderr 몫만 남는다.
    repo, oid = _real_repo(tmp_path)
    spy = tmp_path / 'spy'
    spy.mkdir()
    real_tf = runner_launch.tempfile.TemporaryFile
    monkeypatch.setattr(runner_launch.tempfile, 'TemporaryFile',
                        lambda *a, **kw: runner_launch.tempfile.NamedTemporaryFile(
                            delete=False, dir=str(spy)))
    seen = []
    real_popen = subprocess.Popen

    def popen(argv, *a, **kw):
        seen.append((list(argv), kw.get('stdout')))
        return real_popen(argv, *a, **kw)
    monkeypatch.setattr(runner_launch.subprocess, 'Popen', popen)
    dest = tmp_path / 'dest'
    dest.mkdir()
    entry = runner_launch.snapshot(repo, oid, str(dest))
    monkeypatch.setattr(runner_launch.tempfile, 'TemporaryFile', real_tf)
    assert entry == os.path.join(str(dest), 'scripts', 'review_gate.py')
    assert (dest / 'big.bin').read_bytes() == (tmp_path / 'repo' / 'big.bin').read_bytes()
    assert os.readlink(dest / 'link') == 'scripts/run.sh'
    assert os.stat(dest / 'scripts' / 'run.sh').st_mode & 0o111
    archive = [out for argv, out in seen if 'archive' in argv]
    assert archive == [subprocess.PIPE]                     # 파이프로 받는다
    sizes = [os.path.getsize(spy / f) for f in os.listdir(spy)]
    assert all(size < 4096 for size in sizes), sizes        # 임시 파일엔 stderr 만


# --- 제한 시간·취소 ----------------------------------------------------------------

@pytest.mark.parametrize('cut', [0, 1500], ids=['before-any-output', 'mid-stream'])
def test_a_hung_archive_is_killed_at_the_deadline(fake, monkeypatch, cut):
    setup, pid, dest = fake
    setup(_tar(GOOD), cut=cut, sleep=60)
    monkeypatch.setattr(runner_launch, 'ARCHIVE_TIMEOUT', 1)
    start = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        runner_launch.snapshot('/r', 'a' * 40, str(dest))
    assert time.monotonic() - start < 10
    assert _gone(pid)


class _Sig:
    got = None


@pytest.mark.parametrize('cut', [0, 1500], ids=['before-any-output', 'mid-stream'])
def test_a_cancel_during_the_archive_kills_git(fake, monkeypatch, cut):
    setup, pid, dest = fake
    setup(_tar(GOOD), cut=cut, sleep=60)
    sig = _Sig()
    monkeypatch.setattr(runner_launch, 'SIGNALS', sig)
    threading.Timer(0.5, lambda: setattr(sig, 'got', 15)).start()
    start = time.monotonic()
    with pytest.raises(runner_launch._Cancelled):
        runner_launch.snapshot('/r', 'a' * 40, str(dest))
    assert time.monotonic() - start < 10
    assert _gone(pid)


def test_an_already_recorded_cancel_does_not_extract(fake, monkeypatch):
    setup, pid, dest = fake
    setup(_tar(GOOD))
    sig = _Sig()
    sig.got = 15
    monkeypatch.setattr(runner_launch, 'SIGNALS', sig)
    with pytest.raises(runner_launch._Cancelled):
        runner_launch.snapshot('/r', 'a' * 40, str(dest))
    for _ in range(100):                     # 기동 직후라 pid 파일이 늦을 수 있다
        if pid.exists():
            break
        time.sleep(0.05)
    assert not pid.exists() or _gone(pid)
    assert not (dest / 'scripts').exists()


def _in_main(tmp_path, monkeypatch):
    work = tmp_path / 'tmp'
    work.mkdir()
    monkeypatch.setenv('TMPDIR', str(work))
    monkeypatch.setattr(runner_launch.tempfile, 'tempdir', None)
    site = tmp_path / 'site'
    site.mkdir()
    monkeypatch.chdir(site)
    return work, site


def test_a_sigterm_during_the_stream_is_a_clean_cancel_without_an_alarm(fake, tmp_path,
                                                                         monkeypatch):
    # 취소가 tar 오류로 둔갑하면 취소된 tick 이 경보를 남긴다 — 새 실패 경로다.
    setup, pid, _ = fake
    setup(_tar(GOOD), cut=1500, sleep=60)
    work, site = _in_main(tmp_path, monkeypatch)
    threading.Timer(0.8, lambda: os.kill(os.getpid(), signal.SIGTERM)).start()
    assert runner_launch.main(['run']) == 128 + signal.SIGTERM
    assert not (site / 'reviews' / 'runner.json').exists()
    assert os.listdir(work) == []
    assert _gone(pid)


def test_a_timeout_in_main_leaves_the_same_alarm(fake, tmp_path, monkeypatch):
    setup, pid, _ = fake
    setup(_tar(GOOD), cut=1500, sleep=60)
    work, site = _in_main(tmp_path, monkeypatch)
    monkeypatch.setattr(runner_launch, 'ARCHIVE_TIMEOUT', 1)
    assert runner_launch.main(['run']) == 1
    state = json.loads((site / 'reviews' / 'runner.json').read_text())
    assert 'TimeoutExpired' in state['errors'][runner_launch.ALARM_KEY]['detail']
    assert os.listdir(work) == []
    assert _gone(pid)


# --- 실패·잘린 출력·경로 탈출 -------------------------------------------------------

def test_a_failing_archive_raises_todays_error(fake):
    setup, pid, dest = fake
    setup(b'', code=128, err='fatal: not a valid object name\n')
    with pytest.raises(RuntimeError, match=r'git archive aaaaaaa 실패 — fatal: not a valid object'):
        runner_launch.snapshot('/r', 'a' * 40, str(dest))
    assert _gone(pid)


def test_a_full_archive_with_a_non_zero_exit_is_not_a_success(fake):
    # 다 풀었어도 git 이 실패했으면 실패다 — 부분 성공 경로가 없다.
    setup, pid, dest = fake
    setup(_tar(GOOD), code=1, err='fatal: late\n')
    with pytest.raises(RuntimeError, match='git archive aaaaaaa 실패 — fatal: late'):
        runner_launch.snapshot('/r', 'a' * 40, str(dest))
    assert _gone(pid)


def test_a_stream_cut_mid_file_raises_a_tar_error(fake):
    setup, pid, dest = fake
    data = _tar(GOOD)
    setup(data, cut=_member_boundary(data, 'data/big.bin') + 512 * 4 + 100_000)
    with pytest.raises(tarfile.TarError):
        runner_launch.snapshot('/r', 'a' * 40, str(dest))
    assert _gone(pid)


def test_a_stream_cut_at_a_member_boundary_with_a_failure_raises_todays_error(fake):
    # tarfile 은 멤버 경계에서 끊긴 흐름을 깔끔한 끝으로 본다 — git 의 종료 코드가 막는다.
    setup, pid, dest = fake
    data = _tar(GOOD)
    setup(data, cut=_member_boundary(data, 'data/small.txt'), code=128, err='fatal: cut\n')
    with pytest.raises(RuntimeError, match='fatal: cut'):
        runner_launch.snapshot('/r', 'a' * 40, str(dest))
    assert _gone(pid)


def test_a_stream_cut_mid_file_with_a_failure_raises_todays_error(fake):
    setup, pid, dest = fake
    data = _tar(GOOD)
    setup(data, cut=_member_boundary(data, 'data/big.bin') + 512 * 4 + 100_000, code=128,
          err='fatal: mid\n')
    with pytest.raises(RuntimeError, match='fatal: mid') as got:
        runner_launch.snapshot('/r', 'a' * 40, str(dest))
    assert isinstance(got.value.__cause__, tarfile.TarError)
    assert _gone(pid)


@pytest.mark.parametrize('members', [
    [('scripts/review_gate.py', b'x'), ('../evil', b'pwned')],
    [('scripts/review_gate.py', b'x'), ('esc', ('sym', '../../evil')), ('esc/evil', b'pwned')],
], ids=['dotdot', 'symlink'])
def test_a_member_escaping_the_copy_is_refused(fake, tmp_path, members):
    setup, pid, dest = fake
    setup(_tar(members))
    with pytest.raises(tarfile.TarError):
        runner_launch.snapshot('/r', 'a' * 40, str(dest))
    assert not (tmp_path / 'evil').exists()
    assert _gone(pid)


def test_a_refused_member_still_wins_over_a_long_archive(fake):
    # 거부한 뒤에도 git 이 남은 출력을 쓰는 중이면, 다 받아 내고 git 이 스스로 끝나게 한다.
    setup, pid, dest = fake
    setup(_tar([('../evil', b'pwned')] + GOOD * 3))
    with pytest.raises(tarfile.TarError):
        runner_launch.snapshot('/r', 'a' * 40, str(dest))
    assert _gone(pid)


def test_a_pipe_numbered_above_fd_setsize_still_streams(fake, monkeypatch):
    # select() 는 1024 이상 번호의 fd 를 못 본다 — 예전 임시 파일 경로엔 없던 실패다(codex 구현 1차).
    import resource
    setup, pid, dest = fake
    setup(_tar(GOOD))
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    want = 1200 if hard == resource.RLIM_INFINITY else min(1200, hard)
    if want < 1100:
        pytest.skip('fd 한도가 낮다')
    resource.setrlimit(resource.RLIMIT_NOFILE, (max(soft, want), hard))
    held = []
    try:
        base = os.open(os.devnull, os.O_RDONLY)
        held.append(base)
        while held[-1] < 1030:
            held.append(os.dup(base))
        entry = runner_launch.snapshot('/r', 'a' * 40, str(dest))
    finally:
        for fd in held:
            os.close(fd)
        resource.setrlimit(resource.RLIMIT_NOFILE, (soft, hard))
    assert os.path.isfile(entry)
    assert _gone(pid)
