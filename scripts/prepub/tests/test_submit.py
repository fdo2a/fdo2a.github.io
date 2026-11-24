import json
import subprocess

import pytest

from prepub import submit


def git(repo, *args):
    return subprocess.run(['git', '-C', str(repo), *args], check=True, capture_output=True,
                          text=True).stdout.strip()


@pytest.fixture
def b(tmp_path):
    d = tmp_path / 'bundle'
    d.mkdir()
    (d / 'manifest.json').write_text('{}')
    (d / 'post.html').write_text('<p>초안</p>', encoding='utf-8')
    return d


@pytest.fixture
def runner(tmp_path, monkeypatch):
    """비공개 review-runner 흉내 — 맨 레포(원격) + 루틴이 받아 둔 사본."""
    remote = tmp_path / 'remote.git'
    subprocess.run(['git', 'init', '-q', '--bare', str(remote)], check=True)
    clone = tmp_path / 'review-runner'
    subprocess.run(['git', 'clone', '-q', str(remote), str(clone)], check=True, capture_output=True)
    monkeypatch.setenv('PREPUB_RUNNER_CLONE', str(clone))
    return remote, clone


def files_at(remote, commit):
    names = git(remote, 'ls-tree', '-r', '--name-only', commit).splitlines()
    return {n: git(remote, 'show', f'{commit}:{n}') for n in names}


def test_the_bundle_lands_on_the_private_drafts_branch_by_git_push(b, tmp_path, runner):
    remote, clone = runner
    sha = submit.push_bundle(str(tmp_path), str(b), 'us-2026-11-07-0123456789ab')
    assert git(remote, 'rev-parse', 'refs/heads/drafts') == sha
    assert files_at(remote, sha)['drafts/us-2026-11-07-0123456789ab/post.html'] == '<p>초안</p>'
    # 사본의 작업 폴더·HEAD 는 그대로다
    assert git(clone, 'status', '--porcelain') == ''


def test_no_git_data_api_write_is_used(b, tmp_path, runner):
    """2026-11-24 클라우드 프록시가 `POST git/blobs` 를 403 으로 막았다 — gh api 로 쓰지 않는다."""
    calls = []

    def spy(cmd, **kw):
        calls.append(cmd)
        return subprocess.run(cmd, **kw)
    submit.push_bundle(str(tmp_path), str(b), 'us-2026-11-07-0123456789ab', run=spy)
    assert calls and all(c[0] == 'git' for c in calls)


def test_a_second_bundle_keeps_the_first(b, tmp_path, runner):
    remote, _ = runner
    first = submit.push_bundle(str(tmp_path), str(b), 'us-2026-11-07-000000000001')
    sha = submit.push_bundle(str(tmp_path), str(b), 'kr-2026-11-07-000000000002')
    names = files_at(remote, sha)
    assert 'drafts/us-2026-11-07-000000000001/post.html' in names
    assert 'drafts/kr-2026-11-07-000000000002/post.html' in names
    assert git(remote, 'rev-parse', f'{sha}^') == first       # 앞 커밋 위에 쌓인다(강제 아님)


def test_a_moved_branch_is_retried_on_top_not_forced(b, tmp_path, runner, monkeypatch):
    monkeypatch.setattr(submit.time, 'sleep', lambda s: None)
    remote, _ = runner
    submit.push_bundle(str(tmp_path), str(b), 'us-2026-11-07-000000000001')
    pushes = []

    def racing(cmd, **kw):
        if 'push' in cmd and not pushes:          # 첫 push 직전에 다른 런이 먼저 민다
            pushes.append(1)
            other = tmp_path / 'other'
            subprocess.run(['git', 'clone', '-q', '-b', 'drafts', str(remote), str(other)], check=True,
                           capture_output=True)
            (other / 'x.txt').write_text('x')
            git(other, 'add', 'x.txt')
            git(other, '-c', 'user.name=o', '-c', 'user.email=o@o', 'commit', '-qm', 'other')
            git(other, 'push', '-q', 'origin', 'drafts')
        return subprocess.run(cmd, **kw)
    sha = submit.push_bundle(str(tmp_path), str(b), 'us-2026-11-07-000000000002', run=racing)
    names = files_at(remote, sha)
    assert git(remote, 'rev-parse', 'refs/heads/drafts') == sha
    assert 'x.txt' in names and 'drafts/us-2026-11-07-000000000001/post.html' in names


def test_an_unreachable_private_repo_is_a_submit_error(b, tmp_path, monkeypatch):
    monkeypatch.setenv('PREPUB_RUNNER_CLONE', str(tmp_path / 'nowhere'))
    (tmp_path / 'nowhere').mkdir()
    subprocess.run(['git', 'init', '-q', str(tmp_path / 'nowhere')], check=True)
    git(tmp_path / 'nowhere', 'remote', 'add', 'origin', str(tmp_path / 'missing.git'))
    with pytest.raises(submit.SubmitError):
        submit.push_bundle(str(tmp_path), str(b), 'us-2026-11-07-000000000001')


def test_the_routine_clone_is_found_next_to_the_site_repo(tmp_path, monkeypatch):
    monkeypatch.delenv('PREPUB_RUNNER_CLONE', raising=False)
    site = tmp_path / 'fdo2a.github.io'
    site.mkdir()
    rr = tmp_path / 'review-runner'
    subprocess.run(['git', 'init', '-q', str(rr)], check=True)
    git(rr, 'remote', 'add', 'origin', 'http://local_proxy@127.0.0.1:1/git/fdo2a/review-runner')
    assert submit.runner_clone(str(site)) == str(rr)


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
