"""러너 CLI — 임시 레포에서 실제로 git 을 돌리고, codex 자리에 가짜를 세운다.

순수 규칙은 test_runner 가 본다. 여기서 잡는 것은 그것이 원리적으로 못 보는 자리다 —
고정한 커밋에서 스냅샷이 실제로 나오는지, 실패한 호출이 한도를 쓴 채로 남는지, 잘린
출력이 최종 이름을 못 받는지, 겹친 tick 이 비키는지.
"""

import json
import os
import subprocess
import sys
from datetime import date

import pytest

from review.tests.blocks import CUR

HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GATE = os.path.join(HERE, 'review_gate.py')

TODAY = date.today().isoformat()
POST = f'posts/{TODAY}.html'
KR_POST = f'kr/posts/{TODAY}.html'

PAGE = f"""<html><head><style>
.stance-tbl thead {{ display: none; }}
p {{ font-size:16px; }}
{CUR}
</style></head><body><div class="card">
<p><strong class="p-label">동인.</strong> 유가가 올랐다.</p></div></body></html>
"""


def git(repo, *args):
    return subprocess.run(['git', '-C', repo, *args], capture_output=True, text=True,
                          check=True)


def write(repo, rel, text):
    full = os.path.join(repo, rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, 'w', encoding='utf-8') as fh:
        fh.write(text)


def fake_codex(tmp_path, body='지적 없음', code=0):
    """codex 자리에 세우는 가짜. 스냅샷이 실제로 놓였는지도 함께 확인한다."""
    path = tmp_path / 'codex'
    path.write_text(
        '#!/bin/sh\n'
        'cd "$(echo "$@" | tr " " "\\n" | grep -A1 -x -- -C | tail -1)" || exit 9\n'
        # us 면 posts/+data/, kr 이면 kr/posts/+kr/data/ 가 놓여야 한다.
        f'if [ -f "{POST}" ]; then\n'
        '  test -f data/market_data.json || { echo "데이터가 없다" >&2; exit 7; }\n'
        # 이력은 있어야 하고(수치 역산의 근거), 차트는 없어야 한다(산문 검토에 안 쓴다).
        '  test -f data/history/market.jsonl || { echo "이력이 없다" >&2; exit 6; }\n'
        '  test ! -f data/chart.png || { echo "이미지가 딸려왔다" >&2; exit 5; }\n'
        f'elif [ -f "{KR_POST}" ]; then\n'
        '  test -f kr/data/kr_market_data.json || { echo "kr 데이터가 없다" >&2; exit 4; }\n'
        '  test ! -f data/market_data.json || { echo "us 데이터가 섞였다" >&2; exit 3; }\n'
        'else echo "스냅샷에 글이 없다" >&2; exit 8; fi\n'
        f'printf %s "{body}"\n'
        f'exit {code}\n')
    path.chmod(0o755)
    return str(path)


def run(repo, *args, codex=None):
    env = dict(os.environ)
    if codex:
        env['CODEX_BIN'] = codex
    return subprocess.run([sys.executable, GATE, *args], cwd=repo,
                          capture_output=True, text=True, env=env)


def state_of(repo):
    with open(os.path.join(repo, 'reviews/runner.json'), encoding='utf-8') as fh:
        return json.load(fh)


def drafts(repo):
    try:
        return sorted(os.listdir(os.path.join(repo, 'reviews/pending')))
    except OSError:
        return []


@pytest.fixture()
def repo(tmp_path):
    """오늘치 글 한 편이 origin 에 발행돼 있고, 근거 데이터가 같은 커밋에 있다."""
    origin = str(tmp_path / 'origin.git')
    root = str(tmp_path / 'site')
    subprocess.run(['git', 'init', '-q', '--bare', '-b', 'main', origin], check=True)
    subprocess.run(['git', 'clone', '-q', origin, root], check=True)
    git(root, 'config', 'user.email', 't@t')
    git(root, 'config', 'user.name', 't')
    write(root, POST, PAGE)
    write(root, KR_POST, PAGE)
    write(root, 'data/market_data.json', json.dumps({'report_date': TODAY}))
    write(root, 'data/history/market.jsonl', json.dumps({'d': TODAY}) + '\n')
    write(root, 'data/chart.png', 'x' * 10)
    write(root, 'kr/data/kr_market_data.json', json.dumps({'report_date': TODAY}))
    git(root, 'add', '-A')
    git(root, 'commit', '-qm', 'publish')
    git(root, 'push', '-q', 'origin', 'main')
    return root


def test_both_sections_get_a_draft(repo, tmp_path):
    """us 만 돌리던 테스트로는 kr 스냅샷·프롬프트·한도가 전부 깨져도 초록이었다."""
    out = run(repo, 'run', codex=fake_codex(tmp_path))
    assert out.returncode == 0, out.stdout + out.stderr
    us = git(repo, 'rev-parse', f'HEAD:{POST}').stdout.strip()
    kr = git(repo, 'rev-parse', f'HEAD:{KR_POST}').stdout.strip()
    assert drafts(repo) == sorted([f'{TODAY}-us-{us[:7]}.md',
                                   f'{TODAY}-kr-{kr[:7]}.md'])
    body = open(os.path.join(repo, 'reviews/pending', drafts(repo)[0])).read()
    assert body == '지적 없음'
    assert state_of(repo)['errors'] == {} and state_of(repo)['last_ok']


def test_the_snapshot_comes_from_the_pinned_commit(repo, tmp_path):
    """가짜 codex 는 스냅샷 안에 글과 데이터가 **둘 다** 있어야 0 을 낸다. 작업 폴더를
    보는 게 아니라 커밋에서 꺼낸다는 것이 이 설계의 요점이다."""
    os.remove(os.path.join(repo, 'data/market_data.json'))
    os.remove(os.path.join(repo, POST))
    assert run(repo, 'run', codex=fake_codex(tmp_path)).returncode == 0
    assert len(drafts(repo)) == 2


def test_a_failed_call_still_uses_the_quota(repo, tmp_path):
    """실패가 한도를 안 쓰면 매시 되풀이되면서 사람 몫까지 먹는다."""
    out = run(repo, 'run', codex=fake_codex(tmp_path, code=3))
    assert out.returncode == 1 and drafts(repo) == []
    state = state_of(repo)
    assert sum(state['calls'][max(state['calls'])].values()) == 1
    assert '종료 코드 3' in ' '.join(state['errors'].values())


def test_an_empty_reply_does_not_become_a_draft(repo, tmp_path):
    """잘린 출력이 최종 이름을 받으면 다음 tick 이 「파일이 있다」고 건너뛴다."""
    assert run(repo, 'run', codex=fake_codex(tmp_path, body='  ')).returncode == 1
    assert drafts(repo) == []
    assert '비어' in ' '.join(state_of(repo)['errors'].values())


def test_the_cap_holds_on_the_next_tick(repo, tmp_path):
    run(repo, 'run', codex=fake_codex(tmp_path))
    for name in drafts(repo):
        os.remove(os.path.join(repo, 'reviews/pending', name))
    assert run(repo, 'run', codex=fake_codex(tmp_path)).returncode == 0
    assert drafts(repo) == []          # 한도를 이미 썼으므로 다시 부르지 않는다


def test_a_failure_is_not_erased_by_the_next_quiet_tick(repo, tmp_path):
    """실패로 한도를 태우면 다음 tick 은 고를 것이 없다. 그때 `last_ok` 를 새로 찍고
    `error` 를 지우면, 초안은 없는데 훅에는 「방금 성공」으로 보이는 조용한 실패가 된다."""
    run(repo, 'run', codex=fake_codex(tmp_path, code=3))
    was = dict(state_of(repo)['errors'])
    assert list(was) == ['us']
    # 다음 tick 은 kr 을 성공시킨다. 그래도 us 오류는 살아 있어야 한다.
    out = run(repo, 'run', codex=fake_codex(tmp_path))
    assert out.returncode == 1
    assert [n for n in drafts(repo) if '-us-' in n] == []
    assert state_of(repo)['errors'] == was
    assert '러너 오류 — us' in run(repo, 'pending', '--hook').stdout
    assert 'last_ok' not in state_of(repo)


def test_one_failure_stops_the_rest_of_the_tick(repo, tmp_path):
    """한도 초과였다면 다음 섹션 호출은 어차피 같은 이유로 죽고, 사람 몫만 더 먹는다."""
    run(repo, 'run', codex=fake_codex(tmp_path, code=3))
    state = state_of(repo)
    assert sum(state['calls'][max(state['calls'])].values()) == 1


def test_the_snapshot_uses_the_publishing_commit_not_the_tip(repo, tmp_path):
    """발행 뒤 데이터가 덮어써져도 초안은 발행 시점 데이터로 받아야 한다."""
    write(repo, 'data/market_data.json', json.dumps({'report_date': '9999-01-01'}))
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'recollect')
    git(repo, 'push', '-q', 'origin', 'main')
    codex = fake_codex(tmp_path, body='CHECK')
    # 가짜 codex 를 「발행 시점 값이면 통과」로 바꿔 단다.
    open(codex, 'a').close()
    with open(codex, 'w') as fh:
        fh.write('#!/bin/sh\n'
                 'D=$(echo "$@" | tr " " "\\n" | grep -A1 -x -- -C | tail -1)\n'
                 'cd "$D" || exit 9\n'
                 f'if [ -f "{POST}" ]; then\n'
                 '  grep -q 9999-01-01 data/market_data.json && '
                 '{ echo "최신 데이터가 딸려왔다" >&2; exit 2; }\n'
                 'fi\n'
                 'echo "지적 없음"\n')
    os.chmod(codex, 0o755)
    out = run(repo, 'run', codex=codex)
    assert out.returncode == 0, out.stdout + open(
        os.path.join(repo, 'reviews/runner.json')).read()


def test_an_overlapping_tick_steps_aside(repo, tmp_path):
    """flock 을 잡은 채 두 번째를 돌린다 — 조용히 0 으로 비켜야 한다."""
    import fcntl
    os.makedirs(os.path.join(repo, 'reviews'), exist_ok=True)
    fd = os.open(os.path.join(repo, 'reviews/.runner.lock'),
                 os.O_CREAT | os.O_WRONLY, 0o644)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        out = run(repo, 'run', codex=fake_codex(tmp_path))
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
    assert out.returncode == 0 and drafts(repo) == []


def test_a_work_tree_only_version_is_left_to_the_person(repo, tmp_path):
    """손편집을 하면 큐에 같은 경로의 판이 둘 생긴다(origin 판·작업 폴더 판).

    러너는 **공개판만** 읽는다 — 손편집분은 아직 독자가 보는 글이 아니다. 초안은 하나,
    이름에 박히는 SHA 는 origin 판의 것이어야 한다. 그래야 사람이 정정할 때 현재 큐
    SHA(작업 폴더 판)와 대조해서 이 초안이 다른 판의 것임을 알아본다.
    """
    published = git(repo, 'rev-parse', f'HEAD:{POST}').stdout.strip()
    write(repo, POST, PAGE.replace('올랐다', '내렸다'))
    assert run(repo, 'run', codex=fake_codex(tmp_path)).returncode == 0
    assert f'{TODAY}-us-{published[:7]}.md' in drafts(repo)


def test_the_hook_shows_a_ready_draft(repo, tmp_path):
    run(repo, 'run', codex=fake_codex(tmp_path))
    out = run(repo, 'pending', '--hook')
    assert out.returncode == 0
    assert '초안 준비됨 2건' in out.stdout and '검토 완료가 아니다' in out.stdout


def test_the_hook_says_the_runner_never_ran(repo):
    """세 필드가 늘 나와야 「큐만 길어지고 초안은 안 는다」가 보인다."""
    out = run(repo, 'pending', '--hook')
    assert '초안 준비됨 0건' in out.stdout and '한 번도 안 돌았다' in out.stdout


def test_a_damaged_state_file_does_not_take_the_hook_down(repo, tmp_path):
    """naive ISO 한 줄에 훅이 죽으면 게이트 한 줄이 통째로 사라진다."""
    os.makedirs(os.path.join(repo, 'reviews'), exist_ok=True)
    with open(os.path.join(repo, 'reviews/runner.json'), 'w') as fh:
        fh.write('{"last_ok": "2026-09-10"}')
    out = run(repo, 'pending', '--hook')
    assert out.returncode == 0 and '검토 게이트' in out.stdout


def test_the_queue_shows_the_version_so_a_draft_can_be_matched(repo, tmp_path):
    """절차가 초안 파일명의 sha7 과 대조하라는데, 볼 방법이 없으면 안전장치가 아니다."""
    sha = git(repo, 'rev-parse', f'HEAD:{POST}').stdout.strip()
    assert f'@ {sha[:7]}' in run(repo, 'pending').stdout


def test_the_hook_surfaces_a_runner_error(repo, tmp_path):
    run(repo, 'run', codex=fake_codex(tmp_path, code=3))
    assert '러너 오류' in run(repo, 'pending', '--hook').stdout


def test_the_runner_never_writes_the_ledger(repo, tmp_path):
    before = open(os.path.join(repo, 'reviews/index.json')).read() \
        if os.path.exists(os.path.join(repo, 'reviews/index.json')) else None
    run(repo, 'run', codex=fake_codex(tmp_path))
    after = open(os.path.join(repo, 'reviews/index.json')).read() \
        if os.path.exists(os.path.join(repo, 'reviews/index.json')) else None
    assert before == after
