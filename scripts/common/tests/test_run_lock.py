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


def _setup(tmp_path, deny_deletes=False):
    remote = tmp_path / 'remote.git'
    subprocess.run(['git', 'init', '-q', '--bare', str(remote)], check=True)
    if deny_deletes:
        # 클라우드 루틴의 git 경로는 ref 삭제 push 를 거부한다(2026-10-19 US 런). 갱신 push 는 통과한다.
        _git(remote, 'config', 'receive.denyDeletes', 'true')
    return _clone(tmp_path, 'a', remote), _clone(tmp_path, 'b', remote)


def _own(clone, name='k'):
    return Path(clone) / _git(clone, 'rev-parse', '--git-dir').stdout.strip() / f'run_lock_{name}'


def _tip_subject(clone, name):
    _git(clone, 'fetch', '-q', 'origin', f'refs/heads/locks/{name}')
    return _git(clone, 'log', '-1', '--format=%s', 'FETCH_HEAD').stdout.strip()


def _refuse_all_pushes(remote):
    hook = Path(remote) / 'hooks' / 'pre-receive'
    hook.write_text('#!/bin/sh\necho "proxy: push refused" >&2\nexit 1\n')
    hook.chmod(0o755)


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


def test_release_does_not_delete_a_lock_someone_else_took_over(tmp_path):
    # codex #2: A 가 만료된 뒤 B 가 넘겨받았는데 A 가 release 하면 B 의 잠금이 지워지던 길.
    a, b = _setup(tmp_path)
    assert _run(a, 'acquire', 'k').returncode == 0
    assert 'took over' in _run(b, 'acquire', 'k', '0').stdout
    assert 'left it alone' in _run(a, 'release', 'k').stdout
    c = _clone(tmp_path, 'c', tmp_path / 'remote.git')
    assert _run(c, 'acquire', 'k').returncode == 3          # B 의 잠금이 살아 있다


def test_renew_keeps_a_live_holder_from_being_taken_over(tmp_path):
    # codex #1: 오래 걸리는 런이 갱신하면 stale 기준이 다시 시작된다.
    a, b = _setup(tmp_path)
    assert _run(a, 'acquire', 'k').returncode == 0
    assert _run(a, 'renew', 'k').returncode == 0
    assert _run(b, 'acquire', 'k', '60').returncode == 3


def test_renew_fails_once_the_lock_is_lost(tmp_path):
    a, b = _setup(tmp_path)
    assert _run(a, 'acquire', 'k').returncode == 0
    assert _run(b, 'acquire', 'k', '0').returncode == 0
    assert _run(a, 'renew', 'k').returncode == 3


def test_key_is_a_session_date():
    import re
    r = subprocess.run(['bash', str(SCRIPT), 'key', 'us'], capture_output=True, text=True)
    assert r.returncode == 0 and re.fullmatch(r'us-\d{4}-\d{2}-\d{2}\n', r.stdout)


# ── 클라우드에서 ref 삭제가 거부될 때 (2026-10-20) ──────────────────────────────
# 10/19 US 런은 쓰지 않고 끝나며 release 했지만 삭제 push 가 거부됐고, 「taken over」로 잘못 보고했다.
# 잠금은 원격에 그대로 남아 재시도 루틴이 120분 동안 BUSY 로 막힐 수 있었다.

def test_release_works_where_ref_deletes_are_refused(tmp_path):
    a, b = _setup(tmp_path, deny_deletes=True)
    assert _run(a, 'acquire', 'us-2026-10-19', '120').returncode == 0
    r = _run(a, 'release', 'us-2026-10-19')
    assert r.returncode == 0 and 'released us-2026-10-19' in r.stdout
    assert _tip_subject(a, 'us-2026-10-19').startswith('released ')
    # 120분 stale 기준 그대로 — 기다리지 않고 바로 잡는다.
    r = _run(b, 'acquire', 'us-2026-10-19', '120')
    assert r.returncode == 0 and 'acquired' in r.stdout
    assert _tip_subject(b, 'us-2026-10-19').startswith('lock ')


def _routine_due():
    import importlib.util
    spec = importlib.util.spec_from_file_location('routine_due', SCRIPT.parent / 'routine_due.py')
    rd = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rd)
    return rd


def test_retry_check_does_not_see_a_released_lock_as_busy(tmp_path, monkeypatch):
    from datetime import datetime, timezone
    rd = _routine_due()
    now = datetime(2026, 10, 20, 0, 30, tzinfo=timezone.utc)      # 09:30 KST 첫 재시도 슬롯
    for kind, decide in (('us', rd.decide_us), ('kr', rd.decide_kr)):
        name = rd.lock_name(kind, now)
        a, b = _setup(tmp_path / kind, deny_deletes=True)
        assert _run(a, 'acquire', name, '120').returncode == 0
        monkeypatch.chdir(b)
        seen = datetime.now(timezone.utc)                          # acquire 뒤에 잰다
        age = rd._lock_age(name, seen)
        assert age is not None and 0 <= age < rd.STALE_MIN[kind]   # 살아 있는 잠금은 그대로 보인다
        assert decide(now, set(), age)[0] == 'BUSY'
        assert _run(a, 'release', name).returncode == 0
        age = rd._lock_age(name, seen)
        assert age is None                                         # 풀린 잠금 = 잠금 없음
        assert decide(now, set(), age)[0] == 'DUE'


def test_two_runs_racing_for_a_released_lock_only_one_wins(tmp_path):
    a, b = _setup(tmp_path, deny_deletes=True)
    assert _run(a, 'acquire', 'k').returncode == 0
    assert _run(a, 'release', 'k').returncode == 0
    c = _clone(tmp_path, 'c', tmp_path / 'remote.git')
    # 둘 다 같은 released 표시를 보고 넘겨받으려 한다 — b 가 먼저 이기면 c 는 b 의 젊은 잠금을 본다.
    assert _run(b, 'acquire', 'k').returncode == 0
    r = _run(c, 'acquire', 'k')
    assert r.returncode == 3 and 'held by another run' in r.stdout


def test_release_after_a_takeover_leaves_the_new_holder_alone_under_deny_deletes(tmp_path):
    a, b = _setup(tmp_path, deny_deletes=True)
    assert _run(a, 'acquire', 'k').returncode == 0
    assert 'took over' in _run(b, 'acquire', 'k', '0').stdout
    r = _run(a, 'release', 'k')
    assert r.returncode == 0 and 'taken over' in r.stdout
    assert _tip_subject(b, 'k').startswith('lock ')            # b 의 잠금은 released 로 덮이지 않았다
    assert _run(b, 'renew', 'k').returncode == 0


def test_release_says_refused_not_taken_over_when_the_push_is_rejected(tmp_path):
    a, _ = _setup(tmp_path)
    assert _run(a, 'acquire', 'k').returncode == 0
    _refuse_all_pushes(tmp_path / 'remote.git')
    r = _run(a, 'release', 'k')
    assert r.returncode == 5
    assert 'taken over' not in r.stdout + r.stderr
    assert 'NOT released' in r.stderr and 'proxy: push refused' in r.stderr


def test_release_of_a_lock_that_is_already_gone(tmp_path):
    a, b = _setup(tmp_path)
    assert _run(a, 'acquire', 'k').returncode == 0
    _git(b, 'push', '-q', 'origin', ':refs/heads/locks/k')
    r = _run(a, 'release', 'k')
    assert r.returncode == 0 and 'already gone' in r.stdout


def _barrier(remote, lock, expected_old, barrier_dir):
    """lease push 두 개가 같은 옛 SHA 를 들고 도착할 때까지 붙잡는다 — 순차 실행이 아니라 진짜 경합."""
    barrier_dir.mkdir()
    hook = Path(remote) / 'hooks' / 'pre-receive'
    hook.write_text(f"""#!/bin/sh
while read old new ref; do
  [ "$ref" = "refs/heads/locks/{lock}" ] && [ "$old" = "{expected_old}" ] || continue
  touch "{barrier_dir}/$$"
  i=0
  while [ "$(ls "{barrier_dir}" | wc -l)" -lt 2 ] && [ $i -lt 150 ]; do sleep 0.1; i=$((i+1)); done
done
exit 0
""")
    hook.chmod(0o755)


def _spawn(cwd, *args):
    return subprocess.Popen(['bash', str(SCRIPT), *args], cwd=cwd,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def _remote_tip(clone, name):
    out = _git(clone, 'ls-remote', 'origin', f'refs/heads/locks/{name}').stdout.split()
    return out[0] if out else ''


def test_concurrent_acquires_of_a_released_lock_have_exactly_one_winner(tmp_path):
    a, b = _setup(tmp_path, deny_deletes=True)
    c = _clone(tmp_path, 'c', tmp_path / 'remote.git')
    assert _run(a, 'acquire', 'k').returncode == 0
    assert _run(a, 'release', 'k').returncode == 0
    marker = _remote_tip(a, 'k')
    _barrier(tmp_path / 'remote.git', 'k', marker, tmp_path / 'barrier')
    pb, pc = _spawn(b, 'acquire', 'k', '120'), _spawn(c, 'acquire', 'k', '120')
    rb, rc = pb.wait(timeout=60), pc.wait(timeout=60)
    assert len(list((tmp_path / 'barrier').iterdir())) == 2       # 둘 다 lease push 까지 갔다
    assert sorted([rb, rc]) == [0, 3]
    winner = b if rb == 0 else c
    loser = c if rb == 0 else b
    tip = _remote_tip(a, 'k')
    assert (_own(winner)).read_text().strip() == tip
    assert not (_own(loser)).exists()
    assert _tip_subject(a, 'k').startswith('lock ')


def _ordered_barrier(remote, lock, expected_old, barrier_dir, first):
    """같은 옛 SHA 를 든 lease push 둘이 모두 도착한 뒤, 제목이 `first` 로 시작하는 쪽을 먼저 반영시킨다.

    pre-receive 는 ref 를 잠그기 전에 돈다 — 둘째는 첫째의 post-receive(갱신 완료) 표시를 기다린다.
    """
    _barrier(remote, lock, expected_old, barrier_dir)
    hooks = Path(remote) / 'hooks'
    pre = (hooks / 'pre-receive').read_text().replace('done\nexit 0\n', f"""  case "$(git log -1 --format=%s "$new")" in
  "{first} "*) ;;
  *) i=0; while [ ! -e "{barrier_dir}.first" ] && [ $i -lt 150 ]; do sleep 0.1; i=$((i+1)); done ;;
  esac
done
exit 0
""")
    (hooks / 'pre-receive').write_text(pre)
    post = hooks / 'post-receive'
    post.write_text(f"""#!/bin/sh
while read old new ref; do
  case "$(git log -1 --format=%s "$new" 2>/dev/null)" in "{first} "*) touch "{barrier_dir}.first" ;; esac
done
exit 0
""")
    post.chmod(0o755)


import pytest  # noqa: E402


@pytest.mark.parametrize('first', ['lock', 'released'])
def test_release_racing_a_stale_takeover_ends_with_the_taker_holding_it(tmp_path, first):
    # 테이커가 먼저면 release 는 손대지 않고, release 가 먼저면 테이커가 그 표시를 넘겨받는다.
    a, b = _setup(tmp_path, deny_deletes=True)
    assert _run(a, 'acquire', 'k').returncode == 0
    held = _remote_tip(a, 'k')
    _ordered_barrier(tmp_path / 'remote.git', 'k', held, tmp_path / 'barrier', first)
    pa, pb = _spawn(a, 'release', 'k'), _spawn(b, 'acquire', 'k', '0')
    ra, rb = pa.wait(timeout=60), pb.wait(timeout=60)
    out_a, out_b = pa.stdout.read(), pb.stdout.read()
    assert len(list((tmp_path / 'barrier').iterdir())) == 2        # 둘 다 같은 SHA 로 lease push 까지 갔다
    assert ra == 0 and rb == 0, (out_a, out_b)
    if first == 'lock':
        assert 'taken over' in out_a and 'took over k' in out_b
    else:
        assert 'released k' in out_a and 'previous run released it' in out_b
    assert _tip_subject(a, 'k').startswith('lock ')
    assert _own(b).read_text().strip() == _remote_tip(a, 'k')
    assert not _own(a).exists()


def test_acquire_says_refused_not_held_when_the_takeover_push_is_rejected(tmp_path):
    a, b = _setup(tmp_path, deny_deletes=True)
    assert _run(a, 'acquire', 'k').returncode == 0
    assert _run(a, 'release', 'k').returncode == 0
    _refuse_all_pushes(tmp_path / 'remote.git')
    r = _run(b, 'acquire', 'k')
    assert r.returncode == 4
    assert 'held by another run' not in r.stdout
    assert 'refused' in r.stderr and 'proxy: push refused' in r.stderr


def test_release_keeps_ownership_when_non_fast_forward_updates_are_refused(tmp_path):
    a, _ = _setup(tmp_path)
    assert _run(a, 'acquire', 'k').returncode == 0
    _git(tmp_path / 'remote.git', 'config', 'receive.denyNonFastForwards', 'true')
    r = _run(a, 'release', 'k')
    assert r.returncode == 5 and 'NOT released' in r.stderr
    assert _own(a).exists()                                        # 다시 시도할 수 있게 남긴다


def test_release_that_cannot_read_the_remote_is_exit_4_and_keeps_ownership(tmp_path):
    a, _ = _setup(tmp_path)
    assert _run(a, 'acquire', 'k').returncode == 0
    env = dict(os.environ, RUN_LOCK_REMOTE='nowhere')
    r = subprocess.run(['bash', str(SCRIPT), 'release', 'k'], cwd=a, env=env, capture_output=True, text=True)
    assert r.returncode == 4 and 'NOT released' in r.stderr
    assert _own(a).exists()


def test_successful_release_drops_ownership_and_renew_then_fails(tmp_path):
    a, _ = _setup(tmp_path, deny_deletes=True)
    assert _run(a, 'acquire', 'k').returncode == 0
    assert _run(a, 'release', 'k').returncode == 0
    assert not _own(a).exists()
    assert _run(a, 'renew', 'k').returncode == 3


def test_lock_commits_are_unique_even_at_the_same_second(tmp_path):
    # codex 설계 검토 #4: 시각을 고정해도 nonce 로 SHA 가 갈린다. 제목 끝은 16자리 16진수.
    import re
    a, _ = _setup(tmp_path)
    shim = tmp_path / 'bin'
    shim.mkdir()
    (shim / 'date').write_text('#!/bin/sh\ncase "$1" in +%s) echo 1792454400 ;; *) echo 2026-10-20T00:00:00Z ;; esac\n')
    (shim / 'date').chmod(0o755)
    env = dict(os.environ, PATH=f"{shim}:{os.environ['PATH']}")
    subjects, shas = set(), set()
    for _ in range(3):
        r = subprocess.run(['bash', str(SCRIPT), 'acquire', 'u', '1000000'], cwd=a, env=env,
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr
        shas.add(_own(a, 'u').read_text().strip())
        subjects.add(_tip_subject(a, 'u'))
        assert subprocess.run(['bash', str(SCRIPT), 'release', 'u'], cwd=a, env=env).returncode == 0
        assert re.fullmatch(r'released u 2026-10-20T00:00:00Z pid \d+ [0-9a-f]{16}', _tip_subject(a, 'u'))
    assert len(shas) == 3
    # pid 가 매번 달라 SHA 차이만으로는 nonce 를 증명하지 못한다 — 끝 토큰이 서로 달라야 한다.
    assert len({x.split()[-1] for x in subjects}) == 3
    assert all(re.fullmatch(r'lock u 2026-10-20T00:00:00Z pid \d+ [0-9a-f]{16}', x) for x in subjects)


@pytest.mark.parametrize('content', ['', 'not-a-sha\n'])
def test_a_broken_ownership_file_is_never_reported_as_taken_over(tmp_path, content):
    # codex 구현 검토 2차 #1: 소유 파일을 못 읽으면 mine 이 비어 「taken over」로 지우고 0 을 내던 길.
    a, _ = _setup(tmp_path, deny_deletes=True)
    assert _run(a, 'acquire', 'k').returncode == 0
    held = _remote_tip(a, 'k')
    _own(a).write_text(content)
    r = _run(a, 'release', 'k')
    assert r.returncode == 4 and 'taken over' not in r.stdout and 'NOT released' in r.stderr
    assert _own(a).exists() and _remote_tip(a, 'k') == held
    assert _run(a, 'renew', 'k').returncode == 3
