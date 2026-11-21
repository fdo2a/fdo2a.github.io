"""묶음을 비공개 `review-runner` 의 `drafts` 가지에 올리고, 비공개 검토 워크플로를 띄우고, 결과를 기다린다.

- 올리기(2026-11-22): **비공개 레포의 Git Data API**(`gh api`)로 blob·tree·commit 을 짓고 가지를 앞으로만 민다.
  예전에는 공개 레포 `review-drafts` 가지에 올렸다(11/07 예외). 막기 모드에서는 세운 글(검토를 못 마친 판)이
  공개 가지에 남는다 — 그래서 옮겼다. 루틴의 작업 폴더·인덱스·git 자격은 쓰지 않는다(띄우기와 같은 `gh`).
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


def upload(files, branch, message, run=subprocess.run, tries=3):
    """{레포 안 경로: 로컬 파일} 을 비공개 레포의 `branch` 에 한 커밋으로 — 가지는 앞으로만 민다."""
    import base64
    blobs = []
    for path, local in sorted(files.items()):
        with open(local, 'rb') as fh:
            data = base64.b64encode(fh.read()).decode('ascii')
        got, err = _api('POST', 'git/blobs', run, {'content': data, 'encoding': 'base64'})
        if not got or not got.get('sha'):
            raise SubmitError(f'blob 실패: {err}')
        blobs.append({'path': path, 'mode': '100644', 'type': 'blob', 'sha': got['sha']})
    for attempt in range(tries):
        ref, err = _api('GET', f'git/ref/heads/{branch}', run)
        parent = (ref or {}).get('object', {}).get('sha')
        if ref is None and err != '404':
            raise SubmitError(f'가지 읽기 실패: {err}')
        body = {'tree': blobs}
        if parent:
            got, err = _api('GET', f'git/commits/{parent}', run)
            if not got:
                raise SubmitError(f'앞 커밋 읽기 실패: {err}')
            body['base_tree'] = got['tree']['sha']
        tree, err = _api('POST', 'git/trees', run, body)
        if not tree or not tree.get('sha'):
            raise SubmitError(f'tree 실패: {err}')
        commit, err = _api('POST', 'git/commits', run, {
            'message': message, 'tree': tree['sha'], 'parents': [parent] if parent else [],
            'author': {'name': 'prepub', 'email': 'prepub@users.noreply.github.com'}})
        if not commit or not commit.get('sha'):
            raise SubmitError(f'commit 실패: {err}')
        if parent:
            got, err = _api('PATCH', f'git/refs/heads/{branch}', run, {'sha': commit['sha'], 'force': False})
        else:
            got, err = _api('POST', 'git/refs', run, {'ref': f'refs/heads/{branch}', 'sha': commit['sha']})
        if got is not None:
            return commit['sha']
        if attempt == tries - 1:
            raise SubmitError(f'가지 밀기 실패: {err}')
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
