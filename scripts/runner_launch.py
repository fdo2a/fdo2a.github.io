#!/usr/bin/env python3
"""러너 런처 — origin/main 의 코드 사본으로 `review_gate.py` 를 돌린다 (2026-10-10).

launchd 는 이 파일을 site/ 에서 부른다. 이 파일은 코드를 고르기만 하고, 실제 러너는 **그
tick 의 origin/main 커밋을 통째로 떠 둔 사본**에서 실행된다. 그래서 site/ 가 뒤처져 있든
누가 작업 중이든 러너는 origin/main 코드로 돈다. 사람의 폴더는 읽지도 움직이지도 않는다.

왜: 러너가 site/ 의 코드를 import 하던 동안 10/03 의 staged 작업 때문에 site/ 가 81커밋 뒤에
묶였고, 러너는 그 코드로 일주일 동안 공개판을 고쳐 푸시했다. 공유 폴더를 아무리 검사해도
「읽는 순간」과 「검사하는 순간」 사이의 변경은 막을 수 없었다(codex 구현 재검토 #1·#2).

  python3 scripts/runner_launch.py run --correct      # launchd ProgramArguments

stdlib 만 쓴다. 상태 파일·초안·원장은 그대로 site/ 아래다(cwd). 사본은 커밋마다 한 번 뜨고
`REVIEW_RUNNER_CACHE`(기본 ~/Library/Caches/fdo2a-review-runner) 에 둔다.

설계: docs/superpowers/specs/2026-10-10-runner-code-freshness.md
"""
import io
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time

ENV_CODE = 'REVIEW_RUNNER_CODE'      # 사본의 커밋 — review_gate 가 비교 기준으로 쓴다
KEEP_DAYS = 2                        # 이보다 오래된 사본만 지운다 — 긴 tick 이 쓰는 중일 수 있다
FETCH_TIMEOUT = 30


def cache_dir():
    return os.environ.get('REVIEW_RUNNER_CACHE') or os.path.expanduser(
        '~/Library/Caches/fdo2a-review-runner')


def _git(root, *args, timeout=60):
    p = subprocess.run(['git', '-C', root, *args], capture_output=True, timeout=timeout)
    return p.returncode, p.stdout, p.stderr.decode('utf-8', 'replace').strip()


def snapshot(root, oid, cache):
    """`oid` 의 트리 전체를 cache/<oid> 에 둔다(이미 있으면 그대로) → 경로."""
    final = os.path.join(cache, oid)
    if os.path.isfile(os.path.join(final, 'scripts', 'review_gate.py')):
        return final
    os.makedirs(cache, exist_ok=True)
    code, tree, err = _git(root, 'archive', oid, timeout=300)
    if code:
        raise RuntimeError(f'git archive {oid[:7]} 실패 — {err[-200:]}')
    tmp = tempfile.mkdtemp(prefix=f'.{oid[:7]}-', dir=cache)
    try:
        with tarfile.open(fileobj=io.BytesIO(tree)) as tar:
            tar.extractall(tmp, filter='data')
        try:
            os.rename(tmp, final)          # 원자적 — 겹친 런처가 반쯤 푼 사본을 집지 않는다
        except OSError:
            if not os.path.isdir(final):   # 다른 런처가 먼저 놓았으면 그것을 쓴다
                raise
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return final


def prune(cache, keep):
    """KEEP_DAYS 넘은 사본과 남은 임시 폴더를 지운다. 지금 쓸 사본은 남긴다."""
    cutoff = time.time() - KEEP_DAYS * 86400
    try:
        names = os.listdir(cache)
    except OSError:
        return
    for name in names:
        path = os.path.join(cache, name)
        if name == keep or not os.path.isdir(path):
            continue
        try:
            if os.path.getmtime(path) < cutoff:
                shutil.rmtree(path, ignore_errors=True)
        except OSError:
            pass


def main(argv):
    out = subprocess.run(['git', 'rev-parse', '--show-toplevel'], capture_output=True, text=True)
    if out.returncode:
        print('git 레포 안에서 실행해야 한다.', file=sys.stderr)
        return 2
    root = out.stdout.strip()
    from review import freshness   # stdlib 만 쓰는 모듈 — 경보를 남길 때만 쓴다

    try:
        # fetch 가 실패하면 마지막으로 받아 둔 origin/main 을 쓴다. 러너 안에서 다시 fetch 하고
        # 공개판·코드가 움직였는지는 거기서 본다.
        _git(root, 'fetch', '--quiet', 'origin', 'main', timeout=FETCH_TIMEOUT)
        code, oid, err = _git(root, 'rev-parse', '--verify', '--quiet', 'origin/main')
        oid = oid.decode().strip()
        if code or not oid:
            raise RuntimeError(f'origin/main 을 못 읽었다 {err[-200:]}')
        cache = cache_dir()
        snap = snapshot(root, oid, cache)
        prune(cache, keep=oid)
    except (OSError, RuntimeError, subprocess.SubprocessError, tarfile.TarError) as exc:
        why = f'러너 코드 사본을 못 떴다 — {type(exc).__name__}: {exc}'[:400]
        print(why, file=sys.stderr)
        if argv[:1] == ['run']:
            freshness.note_alarm(root, why)
        return 1
    env = dict(os.environ, **{ENV_CODE: oid})
    sys.stdout.flush()
    sys.stderr.flush()
    os.chdir(root)
    os.execve(sys.executable, [sys.executable, os.path.join(snap, 'scripts', 'review_gate.py'),
                               *argv], env)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
