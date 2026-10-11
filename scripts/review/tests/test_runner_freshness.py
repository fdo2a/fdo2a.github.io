"""러너 코드 신선도 — origin/main 과 같은 코드로만 공개판을 읽고 고친다 (2026-10-10).

10/03 의 staged 미완성 작업 때문에 site/ 가 81커밋 뒤에 묶였고, 러너는 그 코드로 일주일 동안
공개판을 고쳐 푸시했다(check_fund 없는 문체 단계). 경보는 없었다. 여기서 잡는 것: 다르면
멈추고 알린다, 자동으로 pull 하지 않는다, 맞으면 경보가 풀린다, 큐를 못 읽어도 경보는 보인다.
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


def test_behind_origin_is_stale_and_says_by_how_much(repo, tmp_path):
    push_from_elsewhere(repo, tmp_path, {'scripts/x.py': 'x = 1\n'}, 'gate')
    why = freshness.check(fetched(repo))
    assert '1커밋 뒤' in why


def test_an_unpushed_local_commit_is_stale(repo):
    write(repo, 'notes/a.md', 'x')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'local')
    assert '1커밋 앞' in freshness.check(fetched(repo))


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


def test_a_stale_checkout_stops_the_tick_and_raises_the_alarm(repo, tmp_path):
    push_from_elsewhere(repo, tmp_path, {'scripts/x.py': 'x = 1\n'}, 'gate')
    head = git(repo, 'rev-parse', 'HEAD').stdout
    out = run(repo, 'run', codex=fake_codex(tmp_path))
    assert out.returncode == 1
    assert drafts(repo) == []                                  # codex 를 부르지 않았다
    alarm = _code_alarm(repo)
    assert alarm['kind'] == '사람검토' and '1커밋 뒤' in alarm['detail']
    assert 'last_ok' not in state_of(repo)
    assert git(repo, 'rev-parse', 'HEAD').stdout == head      # 자동으로 pull 하지 않는다


def test_the_alarm_clears_only_once_the_checkout_matches(repo, tmp_path):
    push_from_elsewhere(repo, tmp_path, {'scripts/x.py': 'x = 1\n'}, 'gate')
    run(repo, 'run', codex=fake_codex(tmp_path))
    assert _code_alarm(repo)
    git(repo, 'pull', '-q')
    out = run(repo, 'run', codex=fake_codex(tmp_path))
    assert out.returncode == 0, out.stdout + out.stderr
    assert _code_alarm(repo) is None and len(drafts(repo)) == 2


def test_a_failed_fetch_keeps_the_alarm(repo, tmp_path):
    # fetch 실패로 지우면 해결을 확인하지 않은 채 경보가 사라진다(codex #8).
    push_from_elsewhere(repo, tmp_path, {'scripts/x.py': 'x = 1\n'}, 'gate')
    run(repo, 'run', codex=fake_codex(tmp_path))
    git(repo, 'remote', 'set-url', 'origin', str(tmp_path / 'gone.git'))
    run(repo, 'run', codex=fake_codex(tmp_path))
    assert _code_alarm(repo) and '러너' in state_of(repo)['errors']


def test_the_hook_shows_the_alarm(repo, tmp_path):
    push_from_elsewhere(repo, tmp_path, {'scripts/x.py': 'x = 1\n'}, 'gate')
    run(repo, 'run', codex=fake_codex(tmp_path))
    out = run(repo, 'pending', '--hook', '--no-fetch')
    assert '러너-코드' in out.stdout and '1커밋 뒤' in out.stdout


def test_the_hook_shows_the_alarm_even_when_the_queue_cannot_be_read(repo, tmp_path):
    push_from_elsewhere(repo, tmp_path, {'scripts/x.py': 'x = 1\n'}, 'gate')
    run(repo, 'run', codex=fake_codex(tmp_path))
    write(repo, 'reviews/index.json', '{망가진')
    out = run(repo, 'pending', '--hook', '--no-fetch')
    assert out.returncode == 0
    assert '확인 실패' in out.stdout and '러너-코드' in out.stdout


def test_a_broken_import_leaves_an_alarm_for_the_tick_and_a_line_for_the_hook(repo, tmp_path):
    # 레포 모듈이 깨지면 신선도 검사에 닿기 전에 죽는다(codex #6). 깨진 사본을 따로 만들어 돌린다.
    import shutil
    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    broken = tmp_path / 'broken_scripts'
    shutil.copytree(here, broken, ignore=shutil.ignore_patterns('__pycache__', 'tests'))
    (broken / 'review' / 'kinds.py').write_text('def oops(:\n')
    gate = str(broken / 'review_gate.py')
    env = dict(os.environ)
    hook = subprocess.run(['python3', gate, 'pending', '--hook'], cwd=repo, capture_output=True,
                          text=True, env=env)
    assert hook.returncode == 0 and 'import 하지 못했다' in hook.stdout
    tick = subprocess.run(['python3', gate, 'run'], cwd=repo, capture_output=True, text=True,
                          env=env)
    assert tick.returncode == 1
    with open(os.path.join(repo, 'reviews/runner.json'), encoding='utf-8') as fh:
        assert 'import 하지 못했다' in json.load(fh)['errors'][freshness.KEY]['detail']
