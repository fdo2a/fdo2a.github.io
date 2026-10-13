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
# safe_path 는 3.11+ — 정정 에이전트는 launchd PATH 의 시스템 Python 3.9 로 이 파일을 부른다.
if __name__ == '__main__' and not getattr(sys.flags, 'safe_path', False) and sys.path:
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
import time  # noqa: E402

ENV_CODE = 'REVIEW_RUNNER_CODE'      # 사본의 커밋 — review_gate 가 비교 기준으로 쓴다
ALARM_KEY = '러너-코드'              # review.freshness.KEY
FETCH_TIMEOUT = 30
GRACE = 20                           # 신호를 넘긴 뒤 자식 정리를 기다리는 초 — plist ExitTimeOut(30) 안


class _Cancelled(Exception):
    """신호를 받아 그만둔다 — 처리기가 아니라 런처 코드가 안전한 지점에서 던진다."""


class _Signals:
    """SIGTERM·SIGINT 를 **기록만** 하는 처리기. 런처 시작부터 끝까지 건다.

    처리기에서 예외를 던지면 어느 줄에서든 흐름이 끊긴다 — 임시 폴더를 만든 직후, 정리에 들어가는
    순간, 경보를 쓰는 도중(codex 구현 5·6차). 그래서 처리기는 첫 신호를 적고, 자식이 돌고 있으면
    넘겨 주기만 한다. 런처는 git·자식을 기다리는 동안 짧게 끊어 확인하고(`poll`) 스스로 멈춘다.
    """

    SIGS = (signal.SIGTERM, signal.SIGINT)

    def __init__(self):
        self.got = None
        self.child = None
        self.forwarded = False
        self._old = {}

    def __enter__(self):
        for sig in (signal.SIGTERM, signal.SIGINT):
            self._old[sig] = signal.signal(sig, self._handle)
        return self

    def _handle(self, signum, _frame):
        if self.got is None:
            self.got = signum
            self._send()

    def _send(self):
        """첫 신호를 자식에게 **한 번만** 넘긴다 — 처리기와 기동 직후 보정이 둘 다 보내면 두 번째
        신호가 자식의 정리를 끊는다(codex 구현 7차 #5)."""
        child = self.child
        if self.got is None or self.forwarded or child is None or child.poll() is not None:
            return
        self.forwarded = True
        child.send_signal(self.got)

    def forward(self):
        """기동 직후 보정 — 확인과 전송 사이에 처리기가 끼지 않게 신호를 잠시 막는다."""
        old = signal.pthread_sigmask(signal.SIG_BLOCK, self.SIGS)
        try:
            self._send()
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, old)

    def final(self, keep_blocked=False):
        """마지막 판정 — 신호를 막고, 막기 전에 기록된 것과 막힌 채 대기 중인 것을 거둔다.

        `keep_blocked` 는 명령줄 경로다: 막은 채로 돌아와 그대로 종료한다. 판정 뒤에 온 신호는
        막힌 채 프로세스와 함께 버려지므로, 판정과 종료 사이의 틈이 없다(codex 구현 7·8차 #6).
        호출형(테스트)은 처리기와 마스크를 되돌린다 — 그 뒤의 신호는 호출자의 몫이다.
        막힌 동안 두 신호가 함께 대기하면 도착 순서를 알 수 없으므로 SIGTERM(launchd)을 앞세운다.
        """
        old = signal.pthread_sigmask(signal.SIG_BLOCK, self.SIGS)
        restore = True
        try:
            pending = signal.sigpending()
            for sig in self.SIGS:                       # SIGTERM 먼저
                if sig in pending:
                    signal.sigwait([sig])   # 대기 중인 것만 거두므로 바로 돌아온다(macOS 엔 sigtimedwait 가 없다)
                    if self.got is None:
                        self.got = sig
            got = self.got
            for sig, handler in self._old.items():
                signal.signal(sig, handler)
            self._old = {}
            restore = not keep_blocked
        finally:
            if restore:
                signal.pthread_sigmask(signal.SIG_SETMASK, old)
        return got

    def check(self):
        if self.got is not None:
            raise _Cancelled()

    def __exit__(self, *exc):
        for sig, handler in self._old.items():      # final() 을 못 거친 경로(예외)용
            signal.signal(sig, handler)
        return False


SIGNALS = None          # main() 이 거는 _Signals — _git 이 기다리는 동안 확인한다
POLL = 0.2


def _wait(proc, timeout=None):
    """프로세스를 기다리되 POLL 마다 신호를 확인한다 → returncode. 신호면 그 프로세스를 끝내고
    _Cancelled. 시간을 넘기면 TimeoutExpired."""
    deadline = None if timeout is None else time.monotonic() + timeout
    while True:
        if SIGNALS is not None and SIGNALS.got is not None:
            raise _Cancelled()          # 이미 취소됐으면 기다리지도, 결과를 받지도 않는다(7차 #8)
        left = POLL if deadline is None else min(POLL, deadline - time.monotonic())
        if left <= 0:                   # 폴링 횟수가 아니라 실제 경과 시간으로 잰다(7차 #7)
            proc.kill()
            proc.wait()
            raise subprocess.TimeoutExpired(proc.args, timeout)
        try:
            code = proc.wait(timeout=left)
        except subprocess.TimeoutExpired:
            continue
        if SIGNALS is not None and SIGNALS.got is not None:
            raise _Cancelled()
        return code


def _git(root, *args, timeout=60):
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        proc = subprocess.Popen(['git', '-C', root, *args], stdout=out, stderr=err)
        try:
            code = _wait(proc, timeout)
        except _Cancelled:
            proc.kill()
            proc.wait()
            raise
        out.seek(0)
        err.seek(0)
        return code, out.read(), err.read().decode('utf-8', 'replace').strip()


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


def _exit_code(returncode):
    """자식이 신호로 죽었으면(-N) 셸 관례대로 128+N — 그대로 넘기면 241 같은 엉뚱한 수가 된다."""
    return 128 - returncode if returncode < 0 else returncode


def _run_child(argv_child, cwd, env, signals):
    """자식을 돌리고 기다린다. 신호가 오면(처리기가 이미 자식에게 넘겼다) GRACE 초까지 정리를
    기다린 뒤에야 돌아온다 — 런처가 먼저 끝나면 사본도, 자식이 띄운 별도 세션의 Claude·게이트도
    남는다(codex 구현 4차 #1). 자식(review_gate run)은 SIGTERM 을 SystemExit 로 받아 정리한다."""
    child = subprocess.Popen(argv_child, cwd=cwd, env=env)
    signals.child = child
    signals.forward()                       # 띄우기 직전에 온 신호 — 처리기는 아직 자식을 몰랐다
    try:
        return _exit_code(_wait(child))
    except _Cancelled:
        try:
            child.wait(timeout=GRACE)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()
        raise
    finally:
        signals.child = None


def _launch(root, argv, signals, work):
    """사본을 뜨고 자식을 돌린다 → 자식의 종료 코드. 신호면 _Cancelled, 실패면 예외."""
    signals.check()
    # fetch 가 실패하면 마지막으로 받아 둔 origin/main 을 쓴다. 러너 안에서 다시 fetch 하고,
    # 실패하면 공개판 작업 전에 멈춘다.
    _git(root, 'fetch', '--quiet', 'origin', 'main', timeout=FETCH_TIMEOUT)
    code, oid, err = _git(root, 'rev-parse', '--verify', '--quiet', 'origin/main')
    oid = oid.decode().strip()
    if code or not oid:
        raise RuntimeError(f'origin/main 을 못 읽었다 {err[-200:]}')
    entry = snapshot(root, oid, work)
    signals.check()
    sys.stdout.flush()
    sys.stderr.flush()
    # exec 하지 않고 기다린다 — 끝난 뒤 사본을 지워야 한다.
    return _run_child([sys.executable, entry, *argv], root,
                      dict(os.environ, **{ENV_CODE: oid}), signals)


def main(argv, cli=False):
    global SIGNALS
    out = subprocess.run(['git', 'rev-parse', '--show-toplevel'], capture_output=True, text=True)
    if out.returncode:
        print('git 레포 안에서 실행해야 한다.', file=sys.stderr)
        return 2
    root = out.stdout.strip()
    with _Signals() as signals:
        SIGNALS = signals
        work = None
        code = 1
        try:
            work = tempfile.mkdtemp(prefix='review-runner-')   # 0700 — 이 tick 만 쓴다
            code = _launch(root, argv, signals, work)
        except _Cancelled:
            pass
        except (OSError, RuntimeError, subprocess.SubprocessError, tarfile.TarError) as exc:
            why = f'러너 코드 사본을 못 떴거나 못 돌렸다 — {type(exc).__name__}: {exc}'[:400]
            print(why, file=sys.stderr)
            if argv[:1] == ['run']:
                try:
                    note_alarm(root, why)
                except OSError as exc2:
                    print(f'[런처] 경보도 못 남겼다 — {type(exc2).__name__}: {exc2}', file=sys.stderr)
            code = 1
        finally:
            if work:
                shutil.rmtree(work, ignore_errors=True)
            SIGNALS = None
        got = signals.final(keep_blocked=cli)
        if got is not None:
            # 언제 왔든(사본을 뜨는 중·정리 중·경보를 쓰는 중·마지막 판정 직전) 신호로 끝났다고 보고한다.
            print(f'[런처] 신호 {got} — 정리하고 끝낸다', file=sys.stderr)
            return 128 + got
        return code


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:], cli=True))
