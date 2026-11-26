"""고친 코드 push 뒤 세운 US 글을 자동으로 푼다 (2026-11-27) — 임시 bare 레포로 실제 push 를 돌린다.

11/23 은 사람이 unhold·손 발화를 했고, 11/24 는 고친 코드(0432ee0c)가 올라온 뒤에도 잠금이 `held` 로 남았다.
세션당 3번, push 하나당 한 번만 푼다 — 같은 이유로 되풀이해 멈추면 한도를 태우지 않고 사람에게 간다.
"""
from datetime import datetime, timedelta, timezone
import importlib.util
import os
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
CI = HERE.parents[1] / 'ci'
spec = importlib.util.spec_from_file_location('resume_on_fix', CI / 'resume_on_fix.py')
rf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rf)

T0 = datetime(2026, 11, 27, 0, 0, tzinfo=timezone.utc)


def held(at=T0 - timedelta(days=1)):
    return (at, 'held us-x 2026-11-25T00:00:00Z pid 1 abc reason=style_abort')


# ── 판정(순수) ────────────────────────────────────────────────────────────────

def test_a_hold_before_the_push_is_resumed_once_per_push_and_three_times_per_session():
    assert rf.plan(['d'], {'d': held()}, {}, 'aaaaaaaaaaaa', T0) == [('d', 'resume', '자동 해제 1번째')]
    assert rf.plan(['d'], {'d': held()}, {'d': {'aaaaaaaaaaaa'}}, 'aaaaaaaaaaaa', T0)[0][1] == 'skip'
    three = {'d': {'a' * 12, 'b' * 12, 'c' * 12}}
    assert rf.plan(['d'], {'d': held()}, three, 'd' * 12, T0)[0][:2] == ('d', 'skip')
    assert rf.plan(['d'], {'d': held()}, {'d': {'a' * 12, 'b' * 12}}, 'd' * 12, T0)[0][1] == 'resume'


def test_a_hold_after_the_push_is_not_this_pushs_fix():
    assert rf.plan(['d'], {'d': held(T0 + timedelta(minutes=1))}, {}, 'a' * 12, T0)[0][1] == 'skip'


def test_only_held_locks_are_touched():
    tips = {'a': None, 'b': (T0 - timedelta(days=1), 'released us-b …'),
            'c': (T0 - timedelta(days=1), 'lock us-c … state=judging')}
    assert rf.plan(['a', 'b', 'c'], tips, {}, 'a' * 12, T0) == []


def test_push_time_reads_epoch_and_iso():
    assert rf.parse_time('1764201600') == datetime(2025, 11, 27, 0, 0, tzinfo=timezone.utc)
    assert rf.parse_time('2026-11-27T00:00:00Z') == T0


def test_the_window_is_the_current_session_and_the_late_window():
    hol = ('2026-11-26',)
    assert rf.sessions(T0, hol) == ['2026-11-18', '2026-11-19', '2026-11-20', '2026-11-23', '2026-11-24',
                                    '2026-11-25']


# ── 실제 push (bare 레포) ───────────────────────────────────────────────────────

def _git(cwd, *args):
    return subprocess.run(['git', *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def _setup(tmp_path):
    remote = tmp_path / 'remote.git'
    subprocess.run(['git', 'init', '-q', '--bare', '-b', 'main', str(remote)], check=True)
    seed = tmp_path / 'seed'
    subprocess.run(['git', 'clone', '-q', str(remote), str(seed)], check=True, capture_output=True)
    (seed / 'posts').mkdir()
    (seed / 'posts' / 'README').write_text('x')
    _git(seed, 'add', '-A')
    _git(seed, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'seed')
    _git(seed, 'push', '-q', 'origin', 'HEAD:main')
    run = tmp_path / 'run'
    subprocess.run(['git', 'clone', '-q', str(remote), str(run)], check=True, capture_output=True)
    return seed, run


def _lock(cwd, *args):
    return subprocess.run(['bash', str(CI / 'run_lock.sh'), *args], cwd=cwd, capture_output=True, text=True)


def _resume(cwd, sha, pushed_at):
    return subprocess.run(['python3', str(CI / 'resume_on_fix.py'), '--sha', sha,
                           '--pushed-at', str(int(pushed_at.timestamp()))],
                          cwd=cwd, capture_output=True, text=True)


def _subject(cwd, name):
    _git(cwd, 'fetch', '-q', 'origin', f'refs/heads/locks/{name}')
    return _git(cwd, 'log', '-1', '--format=%s', 'FETCH_HEAD')


def _resume_refs(cwd, day):
    return sorted(line.split('/')[-1] for line in
                  _git(cwd, 'ls-remote', 'origin', f'refs/heads/resume/us-{day}/*').split('\n') if line)


def test_a_fix_push_unholds_the_session_and_counts_it(tmp_path):
    seed, run = _setup(tmp_path)
    rd = rf.rd
    later = datetime.now(timezone.utc) + timedelta(minutes=5)          # push 는 세움 뒤에 왔다
    day = rd.us_late_sessions(later, rd._holidays('us'))[-1]
    name = f'us-{day}'
    assert _lock(seed, 'acquire', name, '120').returncode == 0
    assert _lock(seed, 'hold', name, 'style_abort').returncode == 0

    r = _resume(run, 'a' * 40, later)
    assert r.returncode == 0, r.stdout + r.stderr
    assert f'us-{day}: 풀었다' in r.stdout
    assert _subject(run, name).startswith('released ')
    assert _resume_refs(run, day) == ['a' * 12]

    # 같은 push 가 다시 와도(재실행) 세움이 없으니 아무것도 하지 않는다
    assert _resume(run, 'a' * 40, later).returncode == 0

    # 다시 서면 push 마다 한 번씩, 세 번까지
    for sha in ('b', 'c'):
        assert _lock(seed, 'acquire', name, '0').returncode == 0
        assert _lock(seed, 'hold', name, 'style_abort').returncode == 0
        assert 'us-' + day + ': 풀었다' in _resume(run, sha * 40, later).stdout
    assert _lock(seed, 'acquire', name, '0').returncode == 0
    assert _lock(seed, 'hold', name, 'style_abort').returncode == 0
    r = _resume(run, 'd' * 40, later)
    assert r.returncode == 0 and '3번 다 썼다' in r.stdout
    assert _subject(run, name).startswith('held ')
    assert _resume_refs(run, day) == ['a' * 12, 'b' * 12, 'c' * 12]


def test_a_hold_newer_than_the_push_stays(tmp_path):
    seed, run = _setup(tmp_path)
    rd = rf.rd
    earlier = datetime.now(timezone.utc) - timedelta(minutes=5)
    day = rd.us_late_sessions(earlier, rd._holidays('us'))[-1]
    assert _lock(seed, 'acquire', f'us-{day}', '120').returncode == 0
    assert _lock(seed, 'hold', f'us-{day}', 'style_abort').returncode == 0
    r = _resume(run, 'a' * 40, earlier)
    assert r.returncode == 0 and '이 push 뒤에 생겼다' in r.stdout
    assert _subject(run, f'us-{day}').startswith('held ')
    assert _resume_refs(run, day) == []


def test_unreadable_push_time_unholds_nothing(tmp_path):
    _, run = _setup(tmp_path)
    r = subprocess.run(['python3', str(CI / 'resume_on_fix.py'), '--sha', 'a' * 40, '--pushed-at', ''],
                       cwd=run, capture_output=True, text=True)
    assert r.returncode == 1 and '::error::' in r.stdout
