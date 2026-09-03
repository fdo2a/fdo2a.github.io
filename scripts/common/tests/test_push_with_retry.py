"""수집 워크플로의 공용 push 스크립트 — 다른 워크플로와 겹쳐도 지지 않아야 한다.

2026-08-27부터 GitHub 스케줄러가 예약 실행을 2~5시간씩 밀어내면서, 원래 몇 시간
떨어져 있던 수집 워크플로 넷이 같은 몇 분 안에 밀려 나오기 시작했다. 그 결과가
09-01 US·09-02·09-03 KR 실패다 — 전부 `! [rejected] main -> main (fetch first)`.
"""
import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "ci" / "push_with_retry.sh"


def git(*args, cwd, **kw):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@e",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@e")
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True,
                          capture_output=True, text=True, **kw)


def run_script(cwd, message):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@e",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@e",
               PUSH_RETRY_SLEEP="0")
    return subprocess.run(["bash", str(SCRIPT), message], cwd=cwd, env=env,
                          capture_output=True, text=True)


@pytest.fixture()
def world(tmp_path):
    """bare origin 하나에 클론 둘 — 워크플로 둘이 같은 레포에 커밋하는 상황."""
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(origin)],
                   check=True, capture_output=True)
    seed = tmp_path / "seed"
    subprocess.run(["git", "clone", str(origin), str(seed)], check=True, capture_output=True)
    (seed / "README").write_text("seed\n")
    git("add", "README", cwd=seed)
    git("commit", "-m", "seed", cwd=seed)
    git("push", "-u", "origin", "main", cwd=seed)

    a, b = tmp_path / "a", tmp_path / "b"
    for c in (a, b):
        subprocess.run(["git", "clone", str(origin), str(c)], check=True, capture_output=True)
    yield origin, a, b
    shutil.rmtree(tmp_path, ignore_errors=True)


def test_pushes_staged_change(world):
    origin, a, _ = world
    (a / "kr.json").write_text("{}\n")
    git("add", "kr.json", cwd=a)
    r = run_script(a, "data: kr")
    assert r.returncode == 0, r.stderr
    assert "kr.json" in git("ls-tree", "--name-only", "main", cwd=origin).stdout


def test_recovers_when_another_workflow_pushed_first(world):
    """이것이 실제로 터진 실패다 — 우리 커밋을 만든 사이에 원격이 앞서 나갔다."""
    origin, a, b = world
    (a / "kr.json").write_text("{}\n")
    git("add", "kr.json", cwd=a)

    # 다른 워크플로(thesis)가 먼저 밀어 넣는다.
    (b / "thesis.json").write_text("{}\n")
    git("add", "thesis.json", cwd=b)
    git("commit", "-m", "thesis", cwd=b)
    git("push", cwd=b)

    r = run_script(a, "data: kr")
    assert r.returncode == 0, r.stderr + r.stdout
    tree = git("ls-tree", "--name-only", "main", cwd=origin).stdout
    assert "kr.json" in tree and "thesis.json" in tree


def test_no_staged_change_is_not_a_failure(world):
    _, a, _ = world
    r = run_script(a, "data: kr")
    assert r.returncode == 0, r.stderr
    assert "변경 없음" in r.stdout


def test_unstaged_tracked_changes_do_not_block_rebase(world):
    """수집 스크립트가 남긴 «스테이징 안 된 추적 파일»이 rebase 를 막으면 안 된다 (--autostash)."""
    origin, a, b = world
    (a / "kr.json").write_text("{}\n")
    git("add", "kr.json", cwd=a)
    (a / "README").write_text("dirty\n")          # 스테이징 안 된 수정

    (b / "thesis.json").write_text("{}\n")
    git("add", "thesis.json", cwd=b)
    git("commit", "-m", "thesis", cwd=b)
    git("push", cwd=b)

    r = run_script(a, "data: kr")
    assert r.returncode == 0, r.stderr + r.stdout
    assert "kr.json" in git("ls-tree", "--name-only", "main", cwd=origin).stdout


# --- 실제로 터진 실패는 pull 과 push 사이의 레이스다 -----------------------------
#
# 위의 «원격이 먼저 앞서 있는» 경우는 첫 pull 이 흡수해서 재시도 루프가 한 번도 돌지
# 않는다. 진짜 실패는 우리가 pull 을 마친 뒤, push 하기 전에 다른 워크플로가 끼어드는
# 것이다 — pre-push 훅으로 그 순간을 만든다.

RACE_ONCE_HOOK = """#!/bin/sh
if [ ! -f "$GIT_DIR/raced" ]; then
  touch "$GIT_DIR/raced"
  git -C "{other}" push -q
fi
exit 0
"""

RACE_ALWAYS_HOOK = """#!/bin/sh
git -C "{other}" pull --rebase -q
git -C "{other}" commit --allow-empty -q -m "race $$"
git -C "{other}" push -q
exit 0
"""


def install_pre_push(repo, script):
    hook = repo / ".git" / "hooks" / "pre-push"
    hook.write_text(script)
    hook.chmod(0o755)


def identify(repo):
    git("config", "user.name", "t", cwd=repo)
    git("config", "user.email", "t@e", cwd=repo)


def test_retries_when_the_remote_moves_between_pull_and_push(world):
    """이것이 실제 실패다 — 첫 push 는 거절당하고, 재시도가 성공해야 한다."""
    origin, a, b = world
    identify(b)
    (b / "thesis.json").write_text("{}\n")
    git("add", "thesis.json", cwd=b)
    git("commit", "-m", "thesis", cwd=b)          # 아직 push 하지 않는다
    install_pre_push(a, RACE_ONCE_HOOK.format(other=b))

    (a / "kr.json").write_text("{}\n")
    git("add", "kr.json", cwd=a)
    r = run_script(a, "data: kr")

    assert r.returncode == 0, r.stderr + r.stdout
    assert "push 거절 1/5" in r.stderr          # 루프가 실제로 돌았다
    tree = git("ls-tree", "--name-only", "main", cwd=origin).stdout
    assert "kr.json" in tree and "thesis.json" in tree


def test_gives_up_after_five_rejections(world):
    """원격이 계속 앞서 나가면 5회에서 멈추고 실패로 끝난다 — 무한 루프가 아니다."""
    _, a, b = world
    identify(b)
    install_pre_push(a, RACE_ALWAYS_HOOK.format(other=b))
    (a / "kr.json").write_text("{}\n")
    git("add", "kr.json", cwd=a)

    r = run_script(a, "data: kr")
    assert r.returncode == 1
    assert "push 거절 4/5" in r.stderr
    assert "5회 재시도" in r.stderr


def test_rebase_conflict_aborts_instead_of_retrying(world):
    """충돌은 다시 밀어도 같은 곳에서 죽는다 — 중간 상태를 남기지 말고 그 자리에서 끝낸다."""
    _, a, b = world
    identify(b)
    (b / "README").write_text("theirs\n")
    git("add", "README", cwd=b)
    git("commit", "-m", "theirs", cwd=b)
    git("push", cwd=b)

    (a / "README").write_text("ours\n")
    git("add", "README", cwd=a)
    r = run_script(a, "data: kr")

    assert r.returncode == 1
    assert "재시도하지 않는다" in r.stderr
    assert "push 거절" not in r.stderr
    # rebase 중간 상태가 남아 있으면 다음 실행까지 오염된다.
    assert not (a / ".git" / "rebase-merge").exists()
    assert not (a / ".git" / "rebase-apply").exists()
    assert git("rev-parse", "--abbrev-ref", "HEAD", cwd=a).stdout.strip() == "main"


def test_untracked_file_colliding_with_remote_fails_cleanly(world):
    """--autostash 는 추적 안 되는 파일을 치우지 않는다 — 조용히 이기지 말고 실패한다."""
    _, a, b = world
    identify(b)
    (b / "new.txt").write_text("theirs\n")
    git("add", "new.txt", cwd=b)
    git("commit", "-m", "theirs", cwd=b)
    git("push", cwd=b)

    (a / "new.txt").write_text("ours\n")           # 추적 안 됨
    (a / "kr.json").write_text("{}\n")
    git("add", "kr.json", cwd=a)
    r = run_script(a, "data: kr")

    assert r.returncode == 1
    assert "재시도하지 않는다" in r.stderr
    assert not (a / ".git" / "rebase-merge").exists()
