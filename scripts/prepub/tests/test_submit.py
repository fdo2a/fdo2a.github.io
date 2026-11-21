import json
import subprocess

import pytest

from prepub import submit


def git(repo, *args):
    return subprocess.run(['git', '-C', str(repo), *args], check=True, capture_output=True,
                          text=True).stdout.strip()


class FakeApi:
    """비공개 review-runner 의 Git Data API 흉내 — `gh api -X M path --input -` 만 받는다."""

    def __init__(self):
        self.objs, self.refs, self.calls, self.fail_patch = {}, {}, [], 0
        self.n = 0

    @property
    def ref(self):
        return self.refs.get('drafts')

    def _id(self, kind, body):
        self.n += 1
        sha = f'{self.n:040x}'
        self.objs[sha] = (kind, body)
        return sha

    def __call__(self, cmd, input=None, **kw):
        assert cmd[:2] == ['gh', 'api'] and 'repos/fdo2a/review-runner/' in ' '.join(cmd)
        self.calls.append(cmd)
        method = cmd[cmd.index('-X') + 1] if '-X' in cmd else 'GET'
        path = [c for c in cmd if c.startswith('repos/')][0].split('repos/fdo2a/review-runner/', 1)[1]
        body = json.loads(input) if input else None

        def ok(obj):
            return subprocess.CompletedProcess(cmd, 0, json.dumps(obj), '')

        def err(code):
            return subprocess.CompletedProcess(cmd, 1, '', f'gh: error (HTTP {code})')
        if method == 'GET' and path.startswith('git/ref/heads/'):
            r = self.refs.get(path.rsplit('/', 1)[1])
            return ok({'object': {'sha': r}}) if r else err(404)
        if method == 'GET' and path.startswith('git/commits/'):
            kind, c = self.objs[path.rsplit('/', 1)[1]]
            return ok({'sha': path.rsplit('/', 1)[1], 'tree': {'sha': c['tree']}})
        if method == 'POST' and path == 'git/blobs':
            import base64
            return ok({'sha': self._id('blob', base64.b64decode(body['content']).decode())})
        if method == 'POST' and path == 'git/trees':
            files = dict(self.objs[body['base_tree']][1]) if body.get('base_tree') else {}
            files.update({e['path']: e['sha'] for e in body['tree']})
            return ok({'sha': self._id('tree', files)})
        if method == 'POST' and path == 'git/commits':
            return ok({'sha': self._id('commit', body)})
        if method == 'PATCH' and path.startswith('git/refs/heads/'):
            if self.fail_patch:
                self.fail_patch -= 1
                return err(422)
            assert body['force'] is False
            self.refs[path.rsplit('/', 1)[1]] = body['sha']
            return ok({'object': {'sha': body['sha']}})
        if method == 'POST' and path == 'git/refs':
            name = body['ref'].rsplit('/', 1)[1]
            if self.refs.get(name):
                return err(422)
            self.refs[name] = body['sha']
            return ok({'object': {'sha': body['sha']}})
        raise AssertionError(cmd)

    def files(self, commit):
        tree = self.objs[self.objs[commit][1]['tree']][1]
        return {p: self.objs[sha][1] for p, sha in tree.items()}


@pytest.fixture
def b(tmp_path):
    d = tmp_path / 'bundle'
    d.mkdir()
    (d / 'manifest.json').write_text('{}')
    (d / 'post.html').write_text('<p>초안</p>', encoding='utf-8')
    return d


def test_the_bundle_lands_on_the_private_drafts_branch(b, tmp_path):
    api = FakeApi()
    sha = submit.push_bundle(str(tmp_path), str(b), 'us-2026-11-07-0123456789ab', run=api)
    assert api.ref == sha
    assert api.files(sha)['drafts/us-2026-11-07-0123456789ab/post.html'] == '<p>초안</p>'
    # 공개 레포에는 아무것도 올리지 않는다 — 모든 호출이 비공개 레포 API 다(FakeApi 가 단언)
    assert not [c for c in api.calls if c[0] == 'git']


def test_a_second_bundle_keeps_the_first(b, tmp_path):
    api = FakeApi()
    submit.push_bundle(str(tmp_path), str(b), 'us-2026-11-07-000000000001', run=api)
    sha = submit.push_bundle(str(tmp_path), str(b), 'kr-2026-11-07-000000000002', run=api)
    names = api.files(sha)
    assert 'drafts/us-2026-11-07-000000000001/post.html' in names
    assert 'drafts/kr-2026-11-07-000000000002/post.html' in names
    assert api.objs[sha][1]['parents']                      # 앞 커밋 위에 쌓인다(강제 아님)


def test_a_moved_branch_is_retried_on_top_not_forced(b, tmp_path, monkeypatch):
    monkeypatch.setattr(submit.time, 'sleep', lambda s: None)
    api = FakeApi()
    submit.push_bundle(str(tmp_path), str(b), 'us-2026-11-07-000000000001', run=api)
    api.fail_patch = 1
    sha = submit.push_bundle(str(tmp_path), str(b), 'us-2026-11-07-000000000002', run=api)
    assert api.ref == sha and 'drafts/us-2026-11-07-000000000001/post.html' in api.files(sha)


def test_an_unreachable_private_repo_is_a_submit_error(b, tmp_path, monkeypatch):
    monkeypatch.setattr(submit.time, 'sleep', lambda s: None)

    def down(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 1, '', 'gh: error (HTTP 502)')
    with pytest.raises(submit.SubmitError):
        submit.push_bundle(str(tmp_path), str(b), 'us-2026-11-07-000000000001', run=down)


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
