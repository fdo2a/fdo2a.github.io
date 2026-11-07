"""묶음을 `review-drafts` 브랜치에 올리고, 비공개 검토 워크플로를 띄우고, 결과를 기다린다.

- 올리기: 임시 인덱스(GIT_INDEX_FILE)로 커밋을 지어 push — 루틴의 작업 폴더·인덱스를 건드리지 않는다.
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

BRANCH = 'review-drafts'
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


def push_bundle(root, bundle_dir, rid, run=subprocess.run, tries=3):
    """→ review-drafts 에 올린 커밋 SHA."""
    for attempt in range(tries):
        code, _, _ = _run(['git', '-C', root, 'fetch', '-q', 'origin', BRANCH], run)
        parent = None
        if code == 0:
            code, parent, err = _run(['git', '-C', root, 'rev-parse', 'FETCH_HEAD'], run)
            if code:
                raise SubmitError(f'FETCH_HEAD: {err[-200:]}')
        fd, index = tempfile.mkstemp(prefix='prepub-index-')
        os.close(fd)
        os.unlink(index)
        env = dict(os.environ, GIT_INDEX_FILE=index)
        try:
            if parent:
                _check(_run(['git', '-C', root, 'read-tree', parent], run, env), 'read-tree')
            for name in sorted(os.listdir(bundle_dir)):
                path = os.path.join(bundle_dir, name)
                blob = _check(_run(['git', '-C', root, 'hash-object', '-w', path], run), 'hash-object')
                _check(_run(['git', '-C', root, 'update-index', '--add', '--cacheinfo',
                             f'100644,{blob},drafts/{rid}/{name}'], run, env), 'update-index')
            tree = _check(_run(['git', '-C', root, 'write-tree'], run, env), 'write-tree')
        finally:
            if os.path.exists(index):
                os.unlink(index)
        cmd = ['git', '-C', root, 'commit-tree', tree, '-m', f'draft {rid} (unreviewed)']
        if parent:
            cmd[4:4] = ['-p', parent]
        commit = _check(_run(cmd, run, env=dict(os.environ, GIT_AUTHOR_NAME='prepub', GIT_AUTHOR_EMAIL='prepub@users.noreply.github.com',
                                                GIT_COMMITTER_NAME='prepub', GIT_COMMITTER_EMAIL='prepub@users.noreply.github.com')),
                        'commit-tree')
        code, _, err = _run(['git', '-C', root, 'push', '-q', 'origin', f'{commit}:refs/heads/{BRANCH}'], run)
        if code == 0:
            return commit
        if attempt == tries - 1:
            raise SubmitError(f'push 실패: {err[-200:]}')
        time.sleep(2 * (attempt + 1))
    raise SubmitError('push 실패')


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
