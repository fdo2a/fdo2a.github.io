"""묶음을 비공개 `review-runner` 의 `drafts` 가지에 올리고, 비공개 검토 워크플로를 띄우고, 결과를 기다린다.

- 올리기: 비공개 레포에 **git push**(2026-11-24). 11/22 의 Git Data API(`gh api git/blobs`)는 클라우드 프록시가 403 으로
  막아 US 11/23 편이 섰다. 가지는 앞으로만 민다.
  예전에는 공개 레포 `review-drafts` 가지에 올렸다(11/07 예외). 막기 모드에서는 세운 글(검토를 못 마친 판)이
  공개 가지에 남는다 — 그래서 옮겼다. 루틴이 받아 둔 review-runner 사본의 원격으로 민다(작업 폴더·HEAD 는 안 건드린다).
- 띄우기: REST(`gh api -X POST …/dispatches`). 루틴 세션은 GraphQL 을 막아 `gh workflow run` 이 실패한다
  (2026-11-07 실측).
- 기다리기: `results/<request_id>.json` 이 생길 때까지 REST 로 읽는다. **요청 ID·초안 커밋이 정확히 같을
  때만** 받는다 — 옛 결과·남의 결과를 새 초안에 붙이지 않는다. 마감을 넘기면 결과가 늦게 와도 버린다.
"""
import json
import os
import subprocess
import tempfile
import time

BRANCH = 'drafts'
RUNNER_REPO = 'fdo2a/review-runner'
WORKFLOW = 'review.yml'


class SubmitError(Exception):
    pass


CALL_TIMEOUT = 60   # 네트워크 호출 하나 — 멈추면 9분 대기·잠금 갱신 간격을 넘긴다(codex 구현 #8)


def _run(cmd, run=subprocess.run, env=None, input=None, timeout=CALL_TIMEOUT):
    try:
        out = run(cmd, capture_output=True, text=True, env=env, input=input, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, '', f'timeout after {timeout}s'
    return out.returncode, (out.stdout or '').strip(), (out.stderr or '').strip()


def _api(method, path, run, body=None, timeout=CALL_TIMEOUT):
    """→ (dict | None, 오류 글). 404 는 (None, '404')."""
    cmd = ['gh', 'api', '-X', method, f'repos/{RUNNER_REPO}/{path}']
    if body is not None:
        cmd += ['--input', '-']
    code, out, err = _run(cmd, run, input=json.dumps(body) if body is not None else None, timeout=timeout)
    if code:
        return None, ('404' if 'HTTP 404' in err else err[-200:] or f'exit {code}')
    try:
        return json.loads(out or '{}'), ''
    except ValueError:
        return None, 'JSON 아님'


def push_bundle(root, bundle_dir, rid, run=subprocess.run, tries=3):
    """→ 비공개 `drafts` 가지에 올린 커밋 SHA. `root` 는 옛 호출 꼴을 지키려고만 받는다(공개 레포에 쓰지 않는다)."""
    files = {f'drafts/{rid}/{name}': os.path.join(bundle_dir, name) for name in sorted(os.listdir(bundle_dir))}
    return upload(files, BRANCH, f'draft {rid} (unreviewed)', run, tries)


HOLDS_BRANCH = 'holds'
RUNNER_URL = 'https://github.com/fdo2a/review-runner.git'


def runner_clone(root=None):
    """루틴이 소스로 받아 둔 review-runner 사본 — 그 사본의 원격·자격으로 민다. 없으면 None.

    클라우드 프록시는 이 레포의 Git Data API 쓰기(`POST git/blobs`)를 403 으로 막는다(2026-11-24 US 11/23 편이
    여기서 섰다). git push 는 소스 레포라 통한다 — 11/22 전까지 공개 레포 review-drafts 를 git 으로 밀었다.
    """
    env = os.environ.get('PREPUB_RUNNER_CLONE')
    if env:
        return env
    base = os.path.dirname(os.path.abspath(root or os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))))
    for name in sorted(os.listdir(base)) if os.path.isdir(base) else []:
        d = os.path.join(base, name)
        if not os.path.isdir(os.path.join(d, '.git')):
            continue
        out = subprocess.run(['git', '-C', d, 'remote', 'get-url', 'origin'], capture_output=True, text=True)
        if out.returncode == 0 and out.stdout.strip().rstrip('/').removesuffix('.git').endswith('review-runner'):
            return d
    return None


def upload(files, branch, message, run=subprocess.run, tries=3, clone=None):
    """{레포 안 경로: 로컬 파일} 을 비공개 레포의 `branch` 에 한 커밋으로 git push — 가지는 앞으로만 민다.

    사본이 있으면 그 사본 안에서 배관 명령만 쓴다(작업 폴더·HEAD·인덱스는 건드리지 않는다). 없으면 빈 임시 레포에서
    `RUNNER_URL` 로 민다.
    """
    clone = clone or runner_clone()
    with tempfile.TemporaryDirectory() as tmp:
        if clone:
            repo, remote = clone, 'origin'
        else:
            repo, remote = tmp, RUNNER_URL
            _check(_run(['git', 'init', '-q', tmp], run), 'git init')
        env = dict(os.environ, GIT_INDEX_FILE=os.path.join(tmp, 'index'),
                   GIT_AUTHOR_NAME='prepub', GIT_AUTHOR_EMAIL='prepub@users.noreply.github.com',
                   GIT_COMMITTER_NAME='prepub', GIT_COMMITTER_EMAIL='prepub@users.noreply.github.com')

        def g(*args, timeout=CALL_TIMEOUT):
            return _run(['git', '-C', repo, *args], run, env=env, timeout=timeout)
        for attempt in range(tries):
            code, _, err = g('fetch', '-q', remote, f'+refs/heads/{branch}:refs/prepub/{branch}')
            if code and "couldn't find remote ref" not in err:
                raise SubmitError(f'가지 읽기 실패: {err[-200:]}')
            parent = None if code else _check(g('rev-parse', f'refs/prepub/{branch}'), 'rev-parse')
            if os.path.exists(env['GIT_INDEX_FILE']):
                os.remove(env['GIT_INDEX_FILE'])
            _check(g('read-tree', parent) if parent else g('read-tree', '--empty'), 'read-tree')
            for path, local in sorted(files.items()):
                sha = _check(g('hash-object', '-w', os.path.abspath(local)), 'hash-object')
                _check(g('update-index', '--add', '--cacheinfo', f'100644,{sha},{path}'), 'update-index')
            tree = _check(g('write-tree'), 'write-tree')
            commit = _check(g('commit-tree', tree, *(['-p', parent] if parent else []), '-m', message), 'commit-tree')
            code, _, err = g('push', '-q', remote, f'{commit}:refs/heads/{branch}', timeout=120)
            if not code:
                return commit
            if attempt == tries - 1 or not any(k in err for k in ('rejected', 'fetch first', 'non-fast-forward')):
                raise SubmitError(f'가지 밀기 실패: {err[-200:]}')
            time.sleep(2 * (attempt + 1))      # 다른 런이 먼저 밀었다 — 새 끝 위에 다시 짓는다
    raise SubmitError('가지 밀기 실패')


def _check(res, what):
    code, out, err = res
    if code:
        raise SubmitError(f'{what}: {err[-200:]}')
    return out


def dispatch(rid, draft_sha, run=subprocess.run):
    code, _, err = _run(['gh', 'api', '-X', 'POST',
                         f'repos/{RUNNER_REPO}/actions/workflows/{WORKFLOW}/dispatches',
                         '-f', 'ref=main', '-f', f'inputs[request_id]={rid}',
                         '-f', f'inputs[draft_sha]={draft_sha}'], run)
    if code:
        raise SubmitError(f'dispatch 실패: {err[-200:]}')


def fetch_result(rid, run=subprocess.run):
    """→ 결과 dict 또는 None(아직 없다)."""
    code, out, _ = _run(['gh', 'api', '-H', 'Accept: application/vnd.github.raw',
                         f'repos/{RUNNER_REPO}/contents/results/{rid}.json'], run)
    if code:
        return None
    try:
        return json.loads(out)
    except ValueError:
        return None


def wait(rid, draft_sha, deadline_sec, run=subprocess.run, sleep=time.sleep, clock=time.monotonic,
         every=20):
    """→ (상태, 결과 dict 또는 None). 상태: reviewed|limit|failed|…|timeout|mismatch."""
    end = clock() + deadline_sec
    while True:
        res = fetch_result(rid, run)
        if clock() > end:
            return 'timeout', None   # 마감 뒤에 온 결과는 버린다
        if res is not None:
            if res.get('request_id') != rid or res.get('draft_sha') != draft_sha:
                return 'mismatch', res
            return res.get('status') or 'failed', res
        if clock() + every > end:
            return 'timeout', None
        sleep(every)
