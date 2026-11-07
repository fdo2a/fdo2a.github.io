import json
import subprocess

import pytest

from prepub import submit


def git(repo, *args):
    return subprocess.run(['git', '-C', str(repo), *args], check=True, capture_output=True,
                          text=True).stdout.strip()


@pytest.fixture
def pair(tmp_path):
    origin = tmp_path / 'origin.git'
    git(tmp_path, 'init', '-q', '--bare', str(origin))
    work = tmp_path / 'work'
    git(tmp_path, 'clone', '-q', str(origin), str(work))
    (work / 'a.txt').write_text('main')
    git(work, 'add', '-A')
    git(work, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', 'main')
    git(work, 'push', '-q', 'origin', 'HEAD:main')
    b = tmp_path / 'bundle'
    b.mkdir()
    (b / 'manifest.json').write_text('{}')
    (b / 'post.html').write_text('<p>x</p>')
    return origin, work, b


def test_the_bundle_lands_on_the_drafts_branch_without_touching_the_work_tree(pair):
    origin, work, b = pair
    head, status = git(work, 'rev-parse', 'HEAD'), git(work, 'status', '--porcelain')
    sha = submit.push_bundle(str(work), str(b), 'us-2026-11-07-0123456789ab')
    assert git(origin, 'rev-parse', submit.BRANCH) == sha
    assert git(origin, 'show', f'{sha}:drafts/us-2026-11-07-0123456789ab/post.html') == '<p>x</p>'
    assert git(work, 'rev-parse', 'HEAD') == head and git(work, 'status', '--porcelain') == status


def test_a_second_bundle_keeps_the_first(pair):
    origin, work, b = pair
    submit.push_bundle(str(work), str(b), 'us-2026-11-07-000000000001')
    sha = submit.push_bundle(str(work), str(b), 'kr-2026-11-07-000000000002')
    names = git(origin, 'ls-tree', '-r', '--name-only', sha)
    assert 'drafts/us-2026-11-07-000000000001/post.html' in names
    assert 'drafts/kr-2026-11-07-000000000002/post.html' in names


class FakeGh:
    def __init__(self, results):
        self.results, self.calls = list(results), []

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        body = self.results.pop(0) if self.results else None
        code = 0 if body is not None else 1
        return subprocess.CompletedProcess(cmd, code, json.dumps(body) if body else '', '')


def test_wait_returns_the_matching_result():
    gh = FakeGh([None, {'request_id': 'r', 'draft_sha': 's', 'status': 'reviewed', 'review': 'ok'}])
    t = [0]
    state, res = submit.wait('r', 's', 600, run=gh, sleep=lambda s: t.__setitem__(0, t[0] + s),
                             clock=lambda: t[0])
    assert state == 'reviewed' and res['review'] == 'ok'


def test_a_result_for_another_draft_is_not_applied():
    gh = FakeGh([{'request_id': 'r', 'draft_sha': 'OTHER', 'status': 'reviewed'}])
    assert submit.wait('r', 's', 600, run=gh, sleep=lambda s: None, clock=lambda: 0)[0] == 'mismatch'


def test_the_deadline_gives_up_and_ignores_a_late_result():
    t = [0]
    gh = FakeGh([None] * 100)
    state, _ = submit.wait('r', 's', 60, run=gh, sleep=lambda s: t.__setitem__(0, t[0] + s),
                           clock=lambda: t[0], every=20)
    assert state == 'timeout'


def test_dispatch_uses_rest_not_graphql():
    gh = FakeGh([{}])
    submit.dispatch('us-2026-11-07-0123456789ab', 'a' * 40, run=gh)
    cmd = gh.calls[0]
    assert cmd[:4] == ['gh', 'api', '-X', 'POST'] and 'workflow' not in cmd[1]
    assert 'inputs[draft_sha]=' + 'a' * 40 in cmd
