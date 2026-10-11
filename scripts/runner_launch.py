#!/usr/bin/env python3
"""러너 런처 — 그 tick 의 origin/main 사본으로 `review_gate.py` 를 돌린다 (2026-10-10).

launchd 는 이 파일을 site/ 에서 부른다. 이 파일은 코드를 고르기만 하고, 실제 러너는 **그
tick 만 쓰는 임시 폴더에 origin/main 커밋을 통째로 떠 둔 사본**에서 돈다. 끝나면 사본을
지운다. 그래서 site/ 가 뒤처져 있든 누가 작업 중이든 러너는 origin/main 코드로 돌고, 사람의
폴더는 읽지도 움직이지도 않는다.

왜: 러너가 site/ 의 코드를 import 하던 동안 10/03 의 staged 작업 때문에 site/ 가 81커밋 뒤에
묶였고, 러너는 그 코드로 일주일 동안 공개판을 고쳐 푸시했다. 공유 폴더를 아무리 검사해도
「읽는 순간」과 「검사하는 순간」 사이의 변경은 막을 수 없었다(codex 구현 재검토 #1·#2).
사본을 여러 tick 이 나눠 쓰는 캐시로 두지 않는 것은 변조·반쯤 만든 사본·쓰는 중 삭제를
한꺼번에 없애려는 것이다(codex 구현 3차 #1·#2·#3). 35MB 남짓이라 매번 떠도 1~2초다.

  python3 scripts/runner_launch.py run --correct      # launchd ProgramArguments

**stdlib 만 쓴다** — 사람 폴더의 레포 모듈을 import 하면 그 폴더의 편집 중인 파일 하나에 런처가
경보 없이 죽는다(codex 구현 3차 #4). 경보 기록도 여기서 직접 한다.

설계: docs/superpowers/specs/2026-10-10-runner-code-freshness.md
"""
import sys

# 스크립트 옆 동명 모듈(예: scripts/json.py)이 아래 표준 모듈을 가리지 않게 한다.
if __name__ == '__main__' and not sys.flags.safe_path and sys.path:
    sys.path.pop(0)

import fcntl  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402
import signal  # noqa: E402
import subprocess  # noqa: E402
import tarfile  # noqa: E402
import tempfile  # noqa: E402

ENV_CODE = 'REVIEW_RUNNER_CODE'      # 사본의 커밋 — review_gate 가 비교 기준으로 쓴다
ALARM_KEY = '러너-코드'              # review.freshness.KEY
FETCH_TIMEOUT = 30
GRACE = 20                           # 신호를 넘긴 뒤 자식 정리를 기다리는 초 — plist ExitTimeOut(30) 안


def _git(root, *args, timeout=60):
    p = subprocess.run(['git', '-C', root, *args], capture_output=True, timeout=timeout)
    return p.returncode, p.stdout, p.stderr.decode('utf-8', 'replace').strip()


def snapshot(root, oid, dest):
    """`oid` 의 트리 전체를 dest 에 푼다. dest 는 이 tick 만 쓰는 빈 폴더다."""
    code, tree, err = _git(root, 'archive', oid, timeout=300)
    if code:
        raise RuntimeError(f'git archive {oid[:7]} 실패 — {err[-200:]}')
    with tarfile.open(fileobj=io.BytesIO(tree)) as tar:
        tar.extractall(dest, filter='data')
    entry = os.path.join(dest, 'scripts', 'review_gate.py')
    if not os.path.isfile(entry):
        raise RuntimeError(f'{oid[:7]} 사본에 scripts/review_gate.py 가 없다')
    return entry


def note_alarm(root, why):
    """review.freshness.note_alarm 과 같은 일 — 러너 잠금을 잡고 경보만 더한다. 경합하면 비킨다."""
    reviews = os.path.join(root, 'reviews')
    os.makedirs(reviews, exist_ok=True)
    fd = os.open(os.path.join(reviews, '.runner.lock'), os.O_CREAT | os.O_WRONLY, 0o644)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print('[러너] 다른 tick 이 돌고 있어 경보를 남기지 않았다', file=sys.stderr)
            return
        path = os.path.join(reviews, 'runner.json')
        try:
            with open(path, encoding='utf-8') as fh:
                state = json.load(fh)
        except (OSError, ValueError):
            state = {}
        state = state if isinstance(state, dict) else {}
        errs = state.get('errors') if isinstance(state.get('errors'), dict) else {}
        errs[ALARM_KEY] = {'kind': '사람검토', 'detail': why}
        state['errors'] = errs
        tmp_fd, tmp = tempfile.mkstemp(dir=reviews)
        try:
            with os.fdopen(tmp_fd, 'w', encoding='utf-8') as fh:
                json.dump(state, fh, ensure_ascii=False, indent=2, sort_keys=True)
                fh.write('\n')
            os.replace(tmp, path)
        except BaseException:
            os.path.exists(tmp) and os.unlink(tmp)
            raise
    finally:
        os.close(fd)


class _Stop(Exception):
    def __init__(self, signum):
        super().__init__(signum)
        self.signum = signum


class _Signals:
    """런처 전체(임시 폴더를 만들기 전부터)에 거는 SIGTERM·SIGINT 처리.

    첫 신호만 예외로 흐름을 끊는다. 반복 신호는 기록만 한다 — 두 번째 신호가 자식 정리 대기를
    다시 끊으면 러너가 정리하는 중에 사본을 지운다(codex 구현 5차 #1). 사본을 뜨는 중(fetch·
    archive)에 온 신호도 이 처리기가 받아 사본을 지우고 끝낸다(5차 #2).
    """

    def __init__(self):
        self.got = None
        self.hold = False       # 자식을 띄우는 중·정리 중 — 신호를 기록만 하고 흐름을 끊지 않는다
        self._old = {}

    def __enter__(self):
        for sig in (signal.SIGTERM, signal.SIGINT):
            self._old[sig] = signal.signal(sig, self._handle)
        return self

    def _handle(self, signum, _frame):
        if self.got is not None:
            return                      # 반복 신호 — 진행 중인 정리를 끊지 않는다
        self.got = signum
        if not self.hold:
            raise _Stop(signum)

    def release(self):
        """미뤄 둔 신호가 있으면 지금 흐름을 끊는다."""
        self.hold = False
        if self.got is not None:
            raise _Stop(self.got)

    def __exit__(self, *exc):
        for sig, handler in self._old.items():
            signal.signal(sig, handler)
        return False


def _exit_code(returncode):
    """자식이 신호로 죽었으면(-N) 셸 관례대로 128+N — 그대로 넘기면 241 같은 엉뚱한 수가 된다."""
    return 128 - returncode if returncode < 0 else returncode


def _run_child(argv_child, cwd, env, signals):
    """자식을 돌리고 기다린다. 신호를 받으면 자식에게 넘기고 GRACE 초까지 정리를 기다린 뒤에야
    돌아온다 — 런처가 먼저 끝나면 사본도, 자식이 띄운 별도 세션의 Claude·게이트도 남는다(codex
    구현 4차 #1). 자식(review_gate run)은 SIGTERM 을 SystemExit 로 받아 정리한다."""
    child = None
    try:
        # 띄우는 도중 끊기면 자식이 아무도 기다리지 않는 고아로 남는다 — 신호를 미뤘다가 직후에 받는다.
        signals.hold = True
        try:
            child = subprocess.Popen(argv_child, cwd=cwd, env=env)
        finally:
            signals.release()
        return _exit_code(child.wait())
    except _Stop as got:
        if child is not None and child.poll() is None:
            child.send_signal(got.signum)
            try:
                child.wait(timeout=GRACE)       # 반복 신호는 _Signals 가 삼킨다 — 대기가 끊기지 않는다
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        print(f'[런처] 신호 {got.signum} — 러너를 정리하고 끝낸다', file=sys.stderr)
        return 128 + got.signum


def main(argv):
    out = subprocess.run(['git', 'rev-parse', '--show-toplevel'], capture_output=True, text=True)
    if out.returncode:
        print('git 레포 안에서 실행해야 한다.', file=sys.stderr)
        return 2
    root = out.stdout.strip()
    work = None
    with _Signals() as signals:
        try:
            try:
                work = tempfile.mkdtemp(prefix='review-runner-')   # 0700 — 이 tick 만 쓴다
                # fetch 가 실패하면 마지막으로 받아 둔 origin/main 을 쓴다. 러너 안에서 다시
                # fetch 하고, 실패하면 공개판 작업 전에 멈춘다.
                _git(root, 'fetch', '--quiet', 'origin', 'main', timeout=FETCH_TIMEOUT)
                code, oid, err = _git(root, 'rev-parse', '--verify', '--quiet', 'origin/main')
                oid = oid.decode().strip()
                if code or not oid:
                    raise RuntimeError(f'origin/main 을 못 읽었다 {err[-200:]}')
                entry = snapshot(root, oid, work)
                sys.stdout.flush()
                sys.stderr.flush()
                # exec 하지 않고 기다린다 — 끝난 뒤 사본을 지워야 한다.
                return _run_child([sys.executable, entry, *argv], root,
                                  dict(os.environ, **{ENV_CODE: oid}), signals)
            except _Stop as got:
                print(f'[런처] 신호 {got.signum} — 사본을 뜨는 중이라 그대로 끝낸다', file=sys.stderr)
                return 128 + got.signum
            except (OSError, RuntimeError, subprocess.SubprocessError, tarfile.TarError) as exc:
                why = f'러너 코드 사본을 못 떴거나 못 돌렸다 — {type(exc).__name__}: {exc}'[:400]
                print(why, file=sys.stderr)
                if argv[:1] == ['run']:
                    try:
                        note_alarm(root, why)
                    except OSError as exc2:
                        print(f'[런처] 경보도 못 남겼다 — {type(exc2).__name__}: {exc2}',
                              file=sys.stderr)
                return 1
        finally:
            signals.hold = True             # 정리 도중의 신호가 삭제를 끊지 않게 한다
            if work:
                shutil.rmtree(work, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
