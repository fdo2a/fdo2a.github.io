"""러너 코드 신선도 — origin/main 과 같은 코드로만 공개판을 읽고 고친다 (2026-10-10).

10/03 의 staged 미완성 작업 때문에 site/ 가 81커밋 뒤에 묶였고, 러너는 그 코드로 일주일 동안
공개판을 고쳐 푸시했다(check_fund 없는 문체 단계). 경보는 없었다. 여기서 잡는 것: 다르면
런처는 origin/main 의 사본으로 러너를 돌린다(사람 폴더와 무관), 런처 없이 돌면 다르면 멈추고 알린다
(자동 pull 없음), 맞으면 경보가 풀린다, 큐를 못 읽어도·import 가 깨져도 경보는 보인다.
"""
import json
import os
import subprocess

from review import freshness
from review.tests.test_run_cli import (POST, drafts, fake_codex, git, repo,  # noqa: F401
                                       run, state_of, write)


def push_from_elsewhere(repo, tmp_path, files, msg):
    other = str(tmp_path / 'other')
    if not os.path.isdir(other):
        url = git(repo, 'remote', 'get-url', 'origin').stdout.strip()
        subprocess.run(['git', 'clone', '-q', url, other], check=True, capture_output=True)
        git(other, 'config', 'user.email', 't@t')
        git(other, 'config', 'user.name', 't')
    else:
        git(other, 'pull', '-q')
    for rel, text in files.items():
        write(other, rel, text)
    git(other, 'add', '-A')
    git(other, 'commit', '-qm', msg)
    git(other, 'push', '-q', 'origin', 'main')
    return other


def fetched(repo):
    git(repo, 'fetch', '-q', 'origin')
    return repo


# --- check() -------------------------------------------------------------------

def test_a_checkout_equal_to_origin_is_fresh(repo):
    assert freshness.check(fetched(repo)) is None


def test_behind_origin_is_reported_with_the_distance(repo, tmp_path):
    push_from_elsewhere(repo, tmp_path, {'scripts/x.py': 'x = 1\n'}, 'gate')
    kind, why = freshness.status(fetched(repo))
    assert kind == freshness.STALE and '1커밋 뒤' in why


def local_commit(repo):
    write(repo, 'notes/a.md', 'x')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'local')


def test_an_unpushed_local_commit_is_stale(repo):
    local_commit(repo)
    kind, why = freshness.status(fetched(repo))
    assert kind == freshness.STALE and '1커밋 앞' in why


def test_another_branch_is_stale(repo):
    git(repo, 'checkout', '-q', '-b', 'wip')
    assert 'wip 브랜치' in freshness.check(fetched(repo))


def test_a_detached_head_is_stale(repo):
    git(repo, 'checkout', '-q', '--detach')
    assert '분리된 HEAD' in freshness.check(fetched(repo))


def test_staged_or_unstaged_script_changes_are_stale(repo, tmp_path):
    push_from_elsewhere(repo, tmp_path, {'scripts/x.py': 'x = 1\n'}, 'gate')
    git(repo, 'pull', '-q')
    write(repo, 'scripts/x.py', 'x = 2\n')
    assert 'scripts/x.py' in freshness.check(fetched(repo))
    git(repo, 'add', 'scripts/x.py')
    assert 'scripts/x.py' in freshness.check(repo)


def test_an_untracked_module_under_scripts_is_stale(repo):
    # 미추적 scripts/json.py 는 표준 json 을 가린다(codex 설계 검토 #4).
    write(repo, 'scripts/json.py', '')
    assert 'scripts/json.py' in freshness.check(fetched(repo))


def test_the_correction_procedure_counts_as_code(repo, tmp_path):
    # 정정 프롬프트는 .claude/REVIEW_GATE.md 를 로컬에서 읽는다(codex #3).
    push_from_elsewhere(repo, tmp_path, {'.claude/skills/review-gate/SKILL.md': 'a\n'}, 'skill')
    git(repo, 'pull', '-q')
    write(repo, '.claude/skills/review-gate/SKILL.md', 'b\n')
    assert 'SKILL.md' in freshness.check(fetched(repo))


def test_local_post_or_data_edits_do_not_stop_the_runner(repo):
    write(repo, POST, '<html>손으로 고치는 중</html>')
    write(repo, 'reviews/runner.json', '{}')
    assert freshness.check(fetched(repo)) is None


# --- moved() -------------------------------------------------------------------

def test_a_code_commit_after_pinning_counts_as_moved(repo, tmp_path):
    freshness.pin(repo)
    try:
        other = push_from_elsewhere(repo, tmp_path, {'scripts/x.py': 'x = 1\n'}, 'gate')
        assert 'scripts' in freshness.moved(repo, other)
    finally:
        freshness.PINNED = None


def test_a_post_or_data_commit_after_pinning_is_not_moved(repo, tmp_path):
    freshness.pin(repo)
    try:
        other = push_from_elsewhere(repo, tmp_path, {'data/market_data.json': '{}'}, 'data')
        assert freshness.moved(repo, other) is None
    finally:
        freshness.PINNED = None


def test_a_pull_between_import_and_the_first_check_skips_the_tick(repo, tmp_path):
    # import 한 코드(BOOT)와 검사 때의 HEAD 가 다르면, 검사가 통과해도 돌리는 코드는 옛 판이다
    # (codex 구현 검토 #1).
    freshness.boot(repo)
    try:
        push_from_elsewhere(repo, tmp_path, {'scripts/x.py': 'x = 1\n'}, 'gate')
        git(repo, 'pull', '-q')
        assert freshness.check(fetched(repo)) is None
        assert '코드를 읽은 뒤' in freshness.pin(repo)
    finally:
        freshness.BOOT = freshness.PINNED = None


def test_pinning_survives_a_pull_in_the_checkout(repo, tmp_path):
    # 이미 import 한 코드는 그대로다. 사람이 tick 도중 pull 해도 비교 기준은 고정한 판이다.
    freshness.pin(repo)
    try:
        other = push_from_elsewhere(repo, tmp_path, {'scripts/x.py': 'x = 1\n'}, 'gate')
        git(repo, 'pull', '-q')
        assert freshness.moved(repo, other) is not None
    finally:
        freshness.PINNED = None


# --- 러너 tick ------------------------------------------------------------------

def _code_alarm(repo):
    return state_of(repo)['errors'].get(freshness.KEY)


def test_a_behind_checkout_is_not_pulled_and_stops_a_direct_run(repo, tmp_path):
    push_from_elsewhere(repo, tmp_path, {'scripts/x.py': 'x = 1\n'}, 'gate')
    head = git(repo, 'rev-parse', 'HEAD').stdout
    out = run(repo, 'run', codex=fake_codex(tmp_path))
    assert out.returncode == 1 and drafts(repo) == []
    assert git(repo, 'rev-parse', 'HEAD').stdout == head      # 자동으로 pull 하지 않는다
    assert '1커밋 뒤' in _code_alarm(repo)['detail']


def test_a_stale_checkout_stops_the_tick_and_raises_the_alarm(repo, tmp_path):
    local_commit(repo)
    head = git(repo, 'rev-parse', 'HEAD').stdout
    out = run(repo, 'run', codex=fake_codex(tmp_path))
    assert out.returncode == 1
    assert drafts(repo) == []                                  # codex 를 부르지 않았다
    alarm = _code_alarm(repo)
    assert alarm['kind'] == '사람검토' and '1커밋 앞' in alarm['detail']
    assert 'last_ok' not in state_of(repo)
    assert git(repo, 'rev-parse', 'HEAD').stdout == head


def test_the_alarm_clears_only_once_the_checkout_matches(repo, tmp_path):
    local_commit(repo)
    run(repo, 'run', codex=fake_codex(tmp_path))
    assert _code_alarm(repo)
    git(repo, 'push', '-q', 'origin', 'main')
    out = run(repo, 'run', codex=fake_codex(tmp_path))
    assert out.returncode == 0, out.stdout + out.stderr
    assert _code_alarm(repo) is None and len(drafts(repo)) == 2


def test_a_failed_fetch_keeps_the_alarm(repo, tmp_path):
    # fetch 실패로 지우면 해결을 확인하지 않은 채 경보가 사라진다(codex #8).
    local_commit(repo)
    run(repo, 'run', codex=fake_codex(tmp_path))
    git(repo, 'remote', 'set-url', 'origin', str(tmp_path / 'gone.git'))
    run(repo, 'run', codex=fake_codex(tmp_path))
    assert _code_alarm(repo) and '러너' in state_of(repo)['errors']


def test_the_hook_shows_the_alarm(repo, tmp_path):
    local_commit(repo)
    run(repo, 'run', codex=fake_codex(tmp_path))
    out = run(repo, 'pending', '--hook', '--no-fetch')
    assert '러너-코드' in out.stdout and '1커밋 앞' in out.stdout


def test_the_hook_shows_the_alarm_even_when_the_queue_cannot_be_read(repo, tmp_path):
    local_commit(repo)
    run(repo, 'run', codex=fake_codex(tmp_path))
    write(repo, 'reviews/index.json', '{망가진')
    out = run(repo, 'pending', '--hook', '--no-fetch')
    assert out.returncode == 0
    assert '확인 실패' in out.stdout and '러너-코드' in out.stdout


def _broken_copy(tmp_path, rel, text):
    import shutil
    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    broken = tmp_path / 'broken_scripts'
    shutil.copytree(here, broken, ignore=shutil.ignore_patterns('__pycache__', 'tests'))
    (broken / rel).write_text(text)
    return str(broken / 'review_gate.py')


def test_a_broken_import_leaves_an_alarm_for_the_tick_and_a_line_for_the_hook(repo, tmp_path):
    # 레포 모듈이 깨지면 신선도 검사에 닿기 전에 죽는다(codex #6). 깨진 사본을 따로 만들어 돌린다.
    gate = _broken_copy(tmp_path, 'review/kinds.py', 'def oops(:\n')
    hook = subprocess.run(['python3', gate, 'pending', '--hook'], cwd=repo, capture_output=True,
                          text=True)
    assert hook.returncode == 0 and 'import 하지 못했다' in hook.stdout
    tick = subprocess.run(['python3', gate, 'run'], cwd=repo, capture_output=True, text=True)
    assert tick.returncode == 1
    with open(os.path.join(repo, 'reviews/runner.json'), encoding='utf-8') as fh:
        assert 'import 하지 못했다' in json.load(fh)['errors'][freshness.KEY]['detail']


def test_a_shadowing_module_next_to_the_script_does_not_silence_the_hook(repo, tmp_path):
    # 스크립트 옆 json.py 가 표준 json 을 가리면 경보 처리기보다 먼저 죽었다(codex 구현 검토 #5).
    gate = _broken_copy(tmp_path, 'json.py', 'raise RuntimeError("broken")\n')
    hook = subprocess.run(['python3', gate, 'pending', '--hook', '--no-fetch'], cwd=repo,
                          capture_output=True, text=True)
    assert hook.returncode == 0, hook.stderr
    assert '[검토 게이트]' in hook.stdout


def test_an_import_failure_does_not_overwrite_a_running_tick(repo, tmp_path):
    # 정상 tick 이 잠금을 쥔 동안에는 상태 파일을 건드리지 않는다(codex 구현 검토 #4).
    import fcntl
    os.makedirs(os.path.join(repo, 'reviews'), exist_ok=True)
    write(repo, 'reviews/runner.json', json.dumps({'calls': {'d': {'us': 2}}}))
    fd = os.open(os.path.join(repo, 'reviews/.runner.lock'), os.O_CREAT | os.O_WRONLY)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        gate = _broken_copy(tmp_path, 'review/kinds.py', 'def oops(:\n')
        tick = subprocess.run(['python3', gate, 'run'], cwd=repo, capture_output=True, text=True)
        assert tick.returncode == 1 and '다른 tick' in tick.stderr
    finally:
        os.close(fd)
    assert state_of(repo) == {'calls': {'d': {'us': 2}}}


# --- 정정 경로 -------------------------------------------------------------------

def test_a_drift_during_correction_does_not_use_a_round(repo, tmp_path, monkeypatch):
    # 신선도 실패는 Claude 를 부르기 전이다 — 회차 3 이면 그 글의 자동 정정이 영영 선다(codex #3).
    from review.tests.test_run_correct import invoke
    import review_gate as gate
    run(repo, 'run', codex=fake_codex(tmp_path))
    state = state_of(repo)
    state['rounds'] = {POST: 2}
    write(repo, 'reviews/runner.json', json.dumps(state))

    def correct(root, item, draft, commit, timeout):
        return '', f'{freshness.DRIFT}(scripts) — 다음 tick 에 새 코드로 다시 한다'
    assert invoke(repo, monkeypatch, correct) == 1
    after = state_of(repo)
    assert any(freshness.DRIFT in v['detail'] for k, v in after['errors'].items()
               if k.startswith('정정'))                       # 정정 경로를 실제로 탔다
    assert after['rounds'].get(POST) == 2
    assert sum(after['correction_calls'].get(gate.today_kst(), {}).values()) == 0


# --- 런처 -----------------------------------------------------------------------

LAUNCH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                      'runner_launch.py')
FAKE_GATE = ('import json, os, sys\n'
             'print(json.dumps({"file": os.path.abspath(__file__), "cwd": os.getcwd(),\n'
             '                  "code": os.environ.get("REVIEW_RUNNER_CODE"), "argv": sys.argv[1:],\n'
             '                  "version": VERSION}))\n')


def launch(repo, tmp_path, *args):
    env = dict(os.environ, TMPDIR=str(tmp_path / 'tmp'))
    os.makedirs(tmp_path / 'tmp', exist_ok=True)
    p = subprocess.run(['python3', LAUNCH, *args], cwd=repo, capture_output=True, text=True,
                       env=env)
    return p, (json.loads(p.stdout.strip().splitlines()[-1]) if p.returncode == 0 else None)


def test_the_launcher_runs_origin_code_whatever_the_checkout_holds(repo, tmp_path):
    push_from_elsewhere(repo, tmp_path, {'scripts/review_gate.py': 'VERSION = 1\n' + FAKE_GATE},
                        'v1')
    # 사람의 폴더는 뒤처져 있고, 다른 브랜치이고, scripts 를 고치는 중이다.
    git(repo, 'checkout', '-q', '-b', 'wip')
    write(repo, 'scripts/review_gate.py', 'VERSION = 0\n' + FAKE_GATE)
    p, got = launch(repo, tmp_path, 'run', '--correct')
    assert p.returncode == 0, p.stderr
    origin = git(repo, 'rev-parse', 'origin/main').stdout.strip()
    assert got['version'] == 1 and got['code'] == origin
    assert os.path.realpath(got['file']).startswith(os.path.realpath(str(tmp_path / 'tmp')))
    assert os.listdir(tmp_path / 'tmp') == []                     # 끝나면 사본을 지운다
    assert os.path.realpath(got['cwd']) == os.path.realpath(repo)   # 상태·원장은 site/ 그대로
    assert got['argv'] == ['run', '--correct']
    assert git(repo, 'symbolic-ref', '--short', 'HEAD').stdout.strip() == 'wip'   # 안 움직였다


def test_the_launcher_follows_origin_to_the_next_commit(repo, tmp_path):
    push_from_elsewhere(repo, tmp_path, {'scripts/review_gate.py': 'VERSION = 1\n' + FAKE_GATE},
                        'v1')
    assert launch(repo, tmp_path, 'run')[1]['version'] == 1
    push_from_elsewhere(repo, tmp_path, {'scripts/review_gate.py': 'VERSION = 2\n' + FAKE_GATE},
                        'v2')
    assert launch(repo, tmp_path, 'run')[1]['version'] == 2


def test_a_launcher_failure_leaves_an_alarm(repo, tmp_path):
    git(repo, 'remote', 'set-url', 'origin', str(tmp_path / 'gone.git'))
    git(repo, 'update-ref', '-d', 'refs/remotes/origin/main')
    p, _ = launch(repo, tmp_path, 'run')
    assert p.returncode == 1
    assert '사본을 못 떴' in state_of(repo)['errors'][freshness.KEY]['detail']


def test_a_launched_tick_ignores_the_checkout_and_pins_the_snapshot_commit(repo, tmp_path,
                                                                         monkeypatch):
    # 런처가 넘긴 커밋이 기준이다 — 사람 폴더가 다른 브랜치여도 돈다.
    from review.tests.test_run_correct import invoke
    push_from_elsewhere(repo, tmp_path, {'scripts/x.py': 'x = 1\n'}, 'gate')
    git(repo, 'fetch', '-q', 'origin')
    git(repo, 'checkout', '-q', '-b', 'wip')
    monkeypatch.setenv('REVIEW_RUNNER_CODE', git(repo, 'rev-parse', 'origin/main').stdout.strip())
    seen = []

    def correct(root, item, draft, commit, timeout):
        seen.append(dict(freshness.PINNED))
        return '검증 완료', None
    out = run(repo, 'run', codex=fake_codex(tmp_path))   # 같은 환경변수 — 사본 경로로 초안을 낸다
    assert out.returncode == 0, out.stdout + out.stderr
    assert len(drafts(repo)) == 2
    assert invoke(repo, monkeypatch, correct) == 0
    assert freshness.KEY not in state_of(repo)['errors']
    assert seen and seen[0]['scripts'] == freshness.trees(repo, 'origin/main')['scripts']


def test_the_launcher_does_not_import_the_checkouts_modules(repo, tmp_path):
    # 사람 폴더의 편집 중인 모듈 하나에 런처가 경보 없이 죽던 경로(codex 구현 3차 #4).
    import shutil
    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    copy = tmp_path / 'launcher_scripts'
    shutil.copytree(here, copy, ignore=shutil.ignore_patterns('__pycache__', 'tests'))
    (copy / 'review' / 'freshness.py').write_text('def oops(:\n')
    (copy / 'json.py').write_text('raise RuntimeError("shadow")\n')
    push_from_elsewhere(repo, tmp_path, {'scripts/review_gate.py': 'VERSION = 1\n' + FAKE_GATE},
                        'v1')
    os.makedirs(tmp_path / 'tmp', exist_ok=True)
    p = subprocess.run(['python3', str(copy / 'runner_launch.py'), 'run'], cwd=repo,
                       capture_output=True, text=True, env=dict(os.environ, TMPDIR=str(tmp_path / 'tmp')))
    assert p.returncode == 0, p.stderr
    assert json.loads(p.stdout.strip().splitlines()[-1])['version'] == 1


def test_an_automated_tick_ignores_a_half_edited_local_ledger(repo, tmp_path, monkeypatch):
    # 자동 tick 은 공개판 원장만 본다(codex 구현 3차 #5). 실제 Claude 는 부르지 않는다.
    monkeypatch.setenv('CLAUDE_BIN', str(tmp_path / 'no-claude'))
    write(repo, 'reviews/index.json', '{WIP')
    out = run(repo, 'run', '--correct', codex=fake_codex(tmp_path))
    assert 'JSONDecodeError' not in out.stdout + out.stderr


# --- 종료 처리 -------------------------------------------------------------------

SLOW_GATE = ('import os, signal, sys, time\n'
             'def bye(signum, frame):\n'
             '    open(os.environ["MARK"], "w").write("cleaned")\n'
             '    sys.exit(128 + signum)\n'
             'signal.signal(signal.SIGTERM, bye)\n'
             'open(os.environ["MARK"] + ".started", "w").write(os.path.abspath(__file__))\n'
             'time.sleep(60)\n')


def test_sigterm_reaches_the_runner_and_the_copy_is_removed(repo, tmp_path):
    # launchd 가 런처를 끄면 러너가 정리할 기회를 얻고, 사본은 지워진다(codex 구현 4차 #1).
    import signal
    import time
    push_from_elsewhere(repo, tmp_path, {'scripts/review_gate.py': SLOW_GATE}, 'slow')
    os.makedirs(tmp_path / 'tmp', exist_ok=True)
    mark = str(tmp_path / 'mark')
    p = subprocess.Popen(['python3', LAUNCH, 'run'], cwd=repo,
                         env=dict(os.environ, TMPDIR=str(tmp_path / 'tmp'), MARK=mark))
    for _ in range(200):
        if os.path.exists(mark + '.started'):
            break
        time.sleep(0.05)
    assert os.path.exists(mark + '.started')
    p.send_signal(signal.SIGTERM)
    assert p.wait(timeout=30) == 128 + signal.SIGTERM
    assert open(mark).read() == 'cleaned'
    assert os.listdir(tmp_path / 'tmp') == []


def test_a_child_killed_by_a_signal_is_reported_as_128_plus_n():
    import runner_launch
    assert runner_launch._exit_code(-15) == 143
    assert runner_launch._exit_code(7) == 7


def test_a_temp_folder_failure_still_leaves_an_alarm(repo, monkeypatch):
    # 임시 폴더 생성·자식 기동 실패도 경보로 남는다(codex 구현 4차 #2).
    import runner_launch
    monkeypatch.chdir(repo)

    def no_space(*a, **k):
        raise OSError(28, 'No space left on device')
    monkeypatch.setattr(runner_launch.tempfile, 'mkdtemp', no_space)
    assert runner_launch.main(['run']) == 1
    assert 'No space' in state_of(repo)['errors'][freshness.KEY]['detail']


def test_a_child_start_failure_still_leaves_an_alarm(repo, tmp_path, monkeypatch):
    import runner_launch
    push_from_elsewhere(repo, tmp_path, {'scripts/review_gate.py': 'pass\n'}, 'gate')
    monkeypatch.chdir(repo)

    def busy(*a, **k):
        raise OSError(35, 'Resource temporarily unavailable')
    monkeypatch.setattr(runner_launch, '_run_child', busy)
    assert runner_launch.main(['run']) == 1
    assert 'temporarily' in state_of(repo)['errors'][freshness.KEY]['detail']


def test_a_cancelled_correction_kills_its_separate_session(tmp_path, monkeypatch):
    # 정정기의 하위 프로세스는 별도 세션이라 러너와 같이 죽지 않았다(codex 구현 4차 #1).
    import time
    from review import corrector
    pidfile = tmp_path / 'pid'
    real = subprocess.Popen.communicate

    def cancelled(self, *a, **k):
        for _ in range(200):
            if pidfile.exists() and pidfile.read_text():
                break
            time.sleep(0.05)
        raise SystemExit(143)
    monkeypatch.setattr(subprocess.Popen, 'communicate', cancelled)
    code = f"import os, time; open({str(pidfile)!r}, 'w').write(str(os.getpid())); time.sleep(60)"
    try:
        corrector._status(['python3', '-c', code], str(tmp_path), timeout=60)
    except SystemExit:
        pass
    monkeypatch.setattr(subprocess.Popen, 'communicate', real)
    pid = int(pidfile.read_text())
    try:
        os.kill(pid, 0)
        alive = True
    except ProcessLookupError:
        alive = False
    assert not alive
