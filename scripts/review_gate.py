#!/usr/bin/env python3
"""발행된 글 중 아직 codex 검토를 안 받은 것을 세고, 검토했다고 기록한다.

  python3 scripts/review_gate.py pending          # 미검토 목록
  python3 scripts/review_gate.py mark posts/2026-08-22.html --findings 3
  python3 scripts/review_gate.py seed             # 도입 시 1회 — 현재 발행분을 기준선으로

클라우드 루틴은 codex가 없는 환경에서 매일 발행하므로 검토는 발행 뒤에 온다. 「어제 것
검토해야지」를 기억에 맡기면 바쁜 날 건너뛰므로 원장(`reviews/index.json`)에 남긴다.

레포를 **두 눈으로** 본다. `origin/main`이 발행한 판과 작업 폴더에 있는 판 어느 쪽이든
원장이 모르는 내용을 담고 있을 수 있어서다. 며칠 뒤처진 노트북은 루틴이 이미 다시 올린
글의 «검토 완료된 옛 판»을 들고 있고, 한쪽을 다른 쪽에 덮어씌우면 하필 그 새 판이 시야에서
사라진다. 반대로 방금 손으로 고쳐 아직 push하지 않은 글은 작업 폴더에만 있다.

종료 코드: pending은 미검토가 있으면 1, 없으면 0 (--hook일 때는 항상 0).

설계: docs/superpowers/specs/2026-08-24-post-publish-review-gate-design.md
"""

import sys

# 스크립트로 실행되면 파이썬이 scripts/ 를 sys.path 맨 앞에 둔다. 그러면 거기 놓인 미추적
# json.py 가 아래 표준 모듈 import 를 가려 경보 없이 죽는다(codex 구현 검토 #5). 표준 모듈을
# 먼저 읽고, 레포 모듈 경로는 아래에서 다시 올린다.
# safe_path 는 3.11+ — 정정 에이전트는 launchd PATH 의 시스템 Python 3.9 로 이 파일을 부른다.
if __name__ == '__main__' and not getattr(sys.flags, 'safe_path', False) and sys.path:
    sys.path.pop(0)

import argparse  # noqa: E402
import dataclasses  # noqa: E402
import errno  # noqa: E402
import fcntl  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402
import signal  # noqa: E402
import subprocess  # noqa: E402
import tarfile  # noqa: E402
import tempfile  # noqa: E402
from datetime import datetime  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _import_failed(exc):
    """레포 모듈 import 가 깨졌다 — 러너도 훅도 아무 말 없이 죽던 자리(codex 설계 검토 #6).

    사람의 미완성 scripts 변경에 문법 오류가 있으면 신선도 검사에 닿기 전에 죽는다. stdlib 만으로
    훅에는 한 줄을 찍고, 러너 tick 은 상태 파일에 경보를 남긴 뒤 아무것도 하지 않고 끝낸다.
    """
    # repo_root() 와 같은 판정(작업 폴더 기준) — launchd 는 site/ 에서 돈다.
    out = subprocess.run(['git', 'rev-parse', '--show-toplevel'], capture_output=True, text=True)
    root = out.stdout.strip() if out.returncode == 0 else os.getcwd()
    why = f'러너 코드를 import 하지 못했다 — {type(exc).__name__}: {exc}'[:400]
    argv = sys.argv[1:]
    if argv[:1] == ['pending']:
        print(f'[검토 게이트] {why}. site/scripts 를 확인할 것.')
        sys.exit(0 if '--hook' in argv else 1)
    if argv[:1] == ['run']:
        try:
            from review import freshness as _fresh   # stdlib 만 쓴다 — 이것까지 깨졌으면 출력만
            _fresh.note_alarm(root, why)
        except Exception as exc2:  # noqa: BLE001
            print(f'[러너] 경보도 못 남겼다 — {type(exc2).__name__}: {exc2}', file=sys.stderr)
    print(why, file=sys.stderr)
    sys.exit(1)


try:
    from review import freshness  # noqa: E402 — stdlib 만 쓴다
    if sys.argv[1:2] == ['run'] and not os.environ.get('REVIEW_RUNNER_CODE'):
        # 런처 없이 site/ 에서 바로 돌 때만 — 다른 레포 모듈을 읽기 **전에** 지금 HEAD 의 코드를
        # 적어 둔다(codex 구현 검토 #1). 런처의 사본은 바뀌지 않는다.
        freshness.boot(os.getcwd())
    from review import kinds  # noqa: E402
    from review import prose as prose_mod  # noqa: E402
    from common import contested as contested_mod  # noqa: E402
    from review.queue import accept as accept_entry  # noqa: E402
    from review.queue import baselines, classify, is_watched  # noqa: E402
    from review.queue import mark as mark_entry  # noqa: E402
    from review.queue import seed, union_pending  # noqa: E402
    from review.runner import (CLAUDE_BLOCK_HORIZON_HOURS,  # noqa: E402
                               DAILY_CAP, HUMAN, KST, LIMIT, RESHIPPED,
                               ROUND_CAP, TIMEOUT, UNKNOWN, accept_draft,
                               blocked_until, claude_retry_at, clear_rounds,
                               draft_name, eligible, is_claude_limit,
                               err, err_line, is_limit_error, may_release,
                               note_limit, note_round, release, reserve, retry_at,
                               stalled, today_kst)
except Exception as _exc:  # noqa: BLE001 — SyntaxError·ImportError 모두
    _import_failed(_exc)

LEDGER = 'reviews/index.json'
LOCK = 'reviews/.index.lock'
DRAFTS = 'reviews/pending'
STATE = 'reviews/runner.json'
RUNNER_LOCK = 'reviews/.runner.lock'
ENV_CODE = 'REVIEW_RUNNER_CODE'   # runner_launch.ENV_CODE — 사본의 커밋
CORRECTION_BLOCK = 'correction_blocked_until'

# 러너가 codex 에 넘길 근거 — REVIEW_GATE 2단계가 손으로 가리키던 것과 같은 자리를,
# 고정한 커밋에서 꺼낸다. 산문 검토에 안 쓰는 이미지는 빼서 스냅샷을 가볍게 둔다.
SNAPSHOT = {'us': 'data', 'kr': 'kr/data'}
# `.jsonl` 은 `data/history/` 의 이력이다 — 전일 대비 방향을 역산해 볼 수 있는 자리라
# 정합 검토의 근거가 된다. 빠지는 것은 차트 이미지뿐이고, 산문 검토에 쓸 일이 없다.
SNAPSHOT_SUFFIXES = ('.html', '.json', '.jsonl', '.txt')
CODEX = os.environ.get('CODEX_BIN') or os.path.expanduser('~/.local/bin/codex')
FETCH_TIMEOUT_SEC = 10
BATCH_TIMEOUT_SEC = 30


def repo_root():
    out = subprocess.run(['git', 'rev-parse', '--show-toplevel'],
                         capture_output=True, text=True)
    if out.returncode:
        sys.exit('git 레포 안에서 실행해야 한다.')
    return out.stdout.strip()


def git(root, *args, **kw):
    """`-z` 출력을 쓰므로 경로 인코딩은 건드리지 않지만, quotepath는 확실히 끈다."""
    return subprocess.run(['git', '-C', root, '-c', 'core.quotepath=false', *args],
                          capture_output=True, text=True, **kw)


def git_bytes(root, *args, **kw):
    return subprocess.run(['git', '-C', root, '-c', 'core.quotepath=false', *args],
                          capture_output=True, **kw)


def _nul_fields(text):
    return [f for f in text.split('\0') if f]


def try_fetch(root):
    """origin을 조용히 당겨온다. 네트워크가 없으면 포기하고 False."""
    try:
        out = git(root, 'fetch', '--quiet', 'origin', 'main', timeout=FETCH_TIMEOUT_SEC)
    except subprocess.TimeoutExpired:
        return False
    return out.returncode == 0


def tree_at(root, ref):
    """{경로: blob sha} — 그 ref 시점의 파일 목록. ref가 없으면 None.

    `-z`로 받는다. 기본 출력은 공백·따옴표·한글이 든 경로를 C 문자열로 따옴표 처리해서
    내보내므로, 그대로 쪼개면 실제 경로와 다른 키가 만들어진다.
    """
    out = git(root, 'ls-tree', '-r', '-z', ref)
    if out.returncode:
        return None
    tree = {}
    for entry in _nul_fields(out.stdout):
        meta, _, path = entry.partition('\t')
        parts = meta.split()
        if len(parts) >= 3 and parts[1] == 'blob':
            tree[path] = parts[2]
    return tree


def changed_paths(root, ref):
    """ref와 작업 폴더가 다른 파일 + 추적되지 않는 파일."""
    paths = set()
    diff = git(root, 'diff', '--name-only', '-z', ref, '--')
    if diff.returncode == 0:
        paths.update(_nul_fields(diff.stdout))
    untracked = git(root, 'ls-files', '-o', '--exclude-standard', '-z')
    if untracked.returncode == 0:
        paths.update(_nul_fields(untracked.stdout))
    return paths


def hash_object(root, path, data=None):
    """blob SHA. `data`를 주면 **그 바이트의** SHA다.

    작업 폴더 파일은 SHA와 산문 지문이 반드시 같은 바이트에서 나와야 한다. 파일을 두 번
    읽으면 그 사이의 수정으로 둘이 서로 다른 내용을 가리킬 수 있다.
    """
    if data is None:
        out = git(root, 'hash-object', '--', path)
        return out.stdout.strip() if out.returncode == 0 else None
    out = git_bytes(root, 'hash-object', f'--path={path}', '--stdin', input=data)
    return out.stdout.decode().strip() if out.returncode == 0 else None


_SHA = re.compile(r'^[0-9a-f]{40}$')


class Blobs:
    """blob SHA → 내용. 없으면 None.

    커밋된 blob은 `cat-file --batch` **한 프로세스**로 미리 받는다. 항목마다 프로세스를
    띄우면 origin 판과 작업 폴더 판이 같은 객체를 두 번씩 읽어 최초 1회가 수백 번이 된다.
    작업 폴더 파일의 blob은 object DB에 없으므로(`hash-object`를 `-w` 없이 부른다 — 훅은
    읽기 전용이어야 한다) `working_tree`가 읽어 둔 바이트를 여기에 맡겨 둔다.

    **응답을 통째로 검증하고서야 캐시에 반영한다.** 헤더를 느슨하게 읽던 판은 요청에 섞인
    쓰레기 한 줄에 스트림이 어긋나, 어떤 blob의 내용을 **다른 sha 아래** 캐시했다
    (2026-09-04 codex 검토가 재현). 잘못된 내용을 조용히 통과시키느니 batch 전체를 버린다.
    """

    def __init__(self, root):
        self.root = root
        self._blobs = {}

    def remember(self, sha, data):
        self._blobs[sha] = data

    def prefetch(self, shas):
        want = sorted({s for s in shas if isinstance(s, str) and _SHA.match(s)
                       and s not in self._blobs})
        if not want:
            return
        try:
            out = git_bytes(self.root, 'cat-file', '--batch',
                            input=('\n'.join(want) + '\n').encode(),
                            timeout=BATCH_TIMEOUT_SEC)
        except (subprocess.TimeoutExpired, OSError):
            return
        if out.returncode:
            return
        got = self._parse(out.stdout, want)
        if got is not None:
            self._blobs.update(got)

    @staticmethod
    def _parse(buf, want):
        """요청 순서대로 `<sha> blob <size>` 또는 `<sha> missing` 만 받는다.

        하나라도 어긋나면 None — 그 batch 전체를 버린다. 어긋난 스트림에서 이어 읽으면 그
        다음 blob 의 내용이 엉뚱한 sha 아래로 들어간다.
        """
        out, at = {}, 0
        for sha in want:
            nl = buf.find(b'\n', at)
            if nl < 0:
                return None
            head = buf[at:nl].decode('utf-8', 'replace').split()
            at = nl + 1
            if not head or head[0] != sha:
                return None
            if len(head) == 2 and head[1] == 'missing':
                continue
            if len(head) != 3 or head[1] != 'blob':
                return None
            try:
                size = int(head[2])
            except ValueError:
                return None
            if size < 0 or at + size + 1 > len(buf) or buf[at + size] != 0x0A:
                return None
            out[sha] = buf[at:at + size]
            at += size + 1
        return out if at == len(buf) else None

    def text(self, sha):
        data = self._blobs.get(sha)
        if data is None:
            return None
        try:
            return data.decode('utf-8')
        except UnicodeDecodeError:
            return None

    def equivalent(self, path, old_sha, new_sha):
        """queue.classify 에 넘길 동등 판정."""
        return prose_mod.typography(path, self.text(old_sha), self.text(new_sha),
                                    root=self.root)


def working_tree(root, base, ref, blobs=None):
    """작업 폴더에 실제로 있는 내용으로 본 트리.

    손으로 고친 발행본은 push 전까지 origin에 없다. 손편집이야말로 이 게이트가 잡아야 할
    것(과거 FX 방향·유가 등락률 오류가 전부 손편집에서 나왔다)이라 로컬에서 달라진 파일은
    즉시 미검토로 센다. 달라진 파일만 해싱하므로 세션 시작에 붙여도 부담이 없다.
    """
    tree = dict(base)
    for path in changed_paths(root, ref):
        if not is_watched(path):
            continue
        if not os.path.exists(os.path.join(root, path)):
            tree.pop(path, None)  # 로컬에서 지운 파일 — 이 눈에는 안 보인다
            continue
        try:
            with open(os.path.join(root, path), 'rb') as fh:
                data = fh.read()
        except OSError:
            continue
        sha = hash_object(root, path, data)
        if sha:
            tree[path] = sha
            if blobs is not None:
                blobs.remember(sha, data)
    return tree


def load_ledger(root):
    """원장을 읽는다. 없으면 빈 원장, 모양이 아니면 분명한 오류.

    조용히 빈 원장으로 되돌리지 않는다 — 그러면 기록을 통째로 잃은 채 「전부 미검토」로
    보이고, 다음 `mark`가 그 상태를 디스크에 굳혀 버린다.
    """
    full = os.path.join(root, LEDGER)
    if not os.path.exists(full):
        return {'reviewed': {}}
    with open(full, encoding='utf-8') as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f'원장 모양이 아니다 ({LEDGER}): 최상위가 객체여야 한다')
    return data


def save_ledger(root, ledger):
    """중간에 죽어도 반쯤 쓰인 원장이 남지 않게 임시 파일에 쓰고 갈아끼운다.

    깨진 원장은 「전부 미검토」로 읽히므로 안전한 방향으로 실패하긴 하지만, 검토 기록을
    통째로 잃는 것은 그것대로 손해다.
    """
    full = os.path.join(root, LEDGER)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    ordered = {'reviewed': dict(sorted(ledger.get('reviewed', {}).items()))}
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(full), suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            json.dump(ordered, fh, ensure_ascii=False, indent=2)
            fh.write('\n')
        os.replace(tmp, full)
    except BaseException:
        os.path.exists(tmp) and os.unlink(tmp)
        raise


class Ledger:
    """원장을 잠그고 읽어, 로드 시점과 달라지지 않았을 때만 쓴다.

    `os.replace()`는 반쪽 JSON만 막고 lost update는 막지 않는다. `mark` 한 건과 bulk
    `refresh`가 겹치면 나중에 저장하는 쪽이 앞선 변경을 통째로 지운다.
    """

    def __init__(self, root):
        self.root = root
        self.lock = os.path.join(root, LOCK)
        self.fd = None
        self.before = None

    def __enter__(self):
        os.makedirs(os.path.dirname(self.lock), exist_ok=True)
        self.fd = os.open(self.lock, os.O_CREAT | os.O_WRONLY, 0o644)
        try:
            # `O_EXCL` 파일은 프로세스가 강제 종료되거나 lock 을 잡은 뒤 원장 읽기가
            # 실패하면 그대로 남아 이후 모든 writer 를 막는다. flock 은 커널이 푼다.
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(self.fd)
            self.fd = None
            sys.exit(f'원장이 잠겨 있다 ({LOCK}). 다른 검토 작업이 돌고 있다.')
        try:
            self.before = load_ledger(self.root)
        except BaseException:
            self.__exit__(None, None, None)
            raise
        self.data = self.before
        return self

    def save(self, ledger):
        if load_ledger(self.root) != self.before:
            sys.exit('쓰는 동안 원장이 바뀌었다. 다시 실행해라.')
        save_ledger(self.root, ledger)

    def __exit__(self, *exc):
        if self.fd is not None:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
            os.close(self.fd)
            self.fd = None
        return False


def now():
    return datetime.now().astimezone().isoformat(timespec='seconds')


def rel_path(root, path):
    """`./posts/x.html`이나 절대 경로로 불러도 원장의 키와 같은 모양으로 맞춘다.

    레포 밖은 거절한다. `../어디딴데.html`도 `.html`이라 감시 대상 판정을 통과하고
    해시도 구해지지만, 그런 경로는 발행본 트리에 영영 나타나지 않아 원장에 죽은 줄만
    남는다.
    """
    full = os.path.abspath(os.path.join(root, path))
    rel = os.path.relpath(full, root)
    if rel.startswith('..'):
        sys.exit(f'레포 밖의 경로다: {path}')
    return rel


def trees(root, want_fetch):
    """(발행된 판, 작업 폴더 판, 기준 설명, 낡았는지, 지문). 한 번만 훑는다."""
    fetched = try_fetch(root) if want_fetch else None
    published = tree_at(root, 'origin/main')
    ref = 'origin/main'
    if published is None:
        ref, published = 'HEAD', (tree_at(root, 'HEAD') or {})
    blobs = Blobs(root)
    work = working_tree(root, published, ref, blobs)

    stale = ref == 'origin/main' and fetched is False
    if ref == 'HEAD':
        basis, stale = 'HEAD + 작업 폴더 (origin을 모른다)', True
    elif fetched:
        basis = 'origin/main + 작업 폴더'
    else:
        basis = ('origin/main 캐시(fetch 실패) + 작업 폴더' if stale
                 else 'origin/main 캐시(조회 안 함) + 작업 폴더')

    return published, work, basis, stale, blobs


def _needed_shas(ledger, trees_):
    """내용이 필요한 blob — 원장과 SHA가 어긋난 항목의 새 판과 **모든 기준판**.

    기준판을 승인분까지 넣는 이유: 최초 검토 blob은 force-push 뒤 gc나 얕은 클론에서 사라질
    수 있고, 그때도 최근 승인분이 남아 있으면 판정이 된다.
    """
    reviewed = ledger.get('reviewed', {}) if isinstance(ledger, dict) else {}
    want = set()
    for tree in trees_:
        for path, sha in tree.items():
            if not is_watched(path):
                continue
            entry = reviewed.get(path)
            if not isinstance(entry, dict):
                continue
            bases = baselines(entry)
            if sha in bases:
                continue
            want.add(sha)
            want.update(bases)
    return want


def _merge(left, right):
    """두 뷰의 분류를 합친다. 한쪽에서라도 사람이 읽어야 하면 조판에서 뺀다."""
    todo = union_pending(left.todo, right.todo)
    unavailable = union_pending(left.unavailable, right.unavailable)
    hot = {p.path for p in todo} | {p.path for p in unavailable}
    typo = [p for p in union_pending(left.typography, right.typography)
            if p.path not in hot]
    return todo, typo, unavailable


def survey(root, want_fetch, ledger=None):
    """(미검토, 조판, 판정불가, 기준 설명, 낡았는지) — 발행된 판과 작업 폴더를 둘 다 본다."""
    published, work, basis, stale, blobs = trees(root, want_fetch)
    if ledger is None:
        ledger = load_ledger(root)
    blobs.prefetch(_needed_shas(ledger, (published, work)))
    todo, typo, unavailable = _merge(classify(ledger, published, blobs.equivalent),
                                     classify(ledger, work, blobs.equivalent))
    return todo, typo, unavailable, basis, stale, published, work


STALE_NOTE = '지금 본 판이 최신이 아닐 수 있다'


TYPO_NOTE = '조판만 바뀐 %d건은 세지 않았다 (`review_gate.py refresh`로 원장 정리)'


def _ago(stamp):
    """`last_ok` 를 사람이 읽는 말로. 못 읽으면 그 사실을 말한다 — 훅에서 예외가 나면
    게이트 한 줄이 통째로 사라진다."""
    if not isinstance(stamp, str) or not stamp:
        return '아직 한 번도 성공하지 않았다'
    try:
        was = datetime.fromisoformat(stamp)
        if was.tzinfo is None:
            was = was.astimezone()
        hours = (datetime.now().astimezone() - was).total_seconds() / 3600
    except (TypeError, ValueError):
        return '상태 파일이 이상하다'
    if hours < 1:
        return '마지막 성공 방금'
    return f'마지막 성공 {int(hours)}시간 전'


def runner_note(root, queue):
    """훅 한 줄에 붙일 러너 상태 — 준비된 초안 수, 마지막 성공, 오류.

    **세 수가 늘 함께 나와야** 「큐만 길어지고 초안은 안 늘어난다」 = 러너가 죽었다가
    보인다. 하나라도 조건부로 빠지면 그 자리가 「괜찮다」로 읽힌다. launchd 가 job 을
    아예 못 띄우는 경우는 러너 자신이 못 잡으므로 여기가 유일한 신호다.
    """
    try:
        state = load_state(root)
        bits = [f'codex 초안 준비됨 {drafts_ready(root, queue)}건 (검토 완료가 아니다)',
                '러너 ' + ('한 번도 안 돌았다' if not state
                          else _ago(state.get('last_ok')))]
        # 한도 소진은 훅에 보여야 한다. 두 칸을 성공으로 다 쓴 뒤에는 빈 tick 이
        # `last_ok` 를 계속 갱신해서, 그날 글이 대기 중인데도 「마지막 성공 방금」만
        # 보인다 — 러너는 멀쩡한데 오늘 몫이 없다는 사실이 안 드러난다.
        spent = [f'{k} {v}' for k, v in
                 sorted((state.get('calls') or {}).get(today_kst(), {}).items())
                 if isinstance(v, int) and v >= DAILY_CAP]
        if spent:
            bits.append('오늘 한도 소진 — ' + ', '.join(spent))
        wait = blocked_until(state)
        if wait:
            bits.append('codex 대기 — ' + wait.strftime('%H:%M') + ' 이후 재시도')
        wait = blocked_until(state, key=CORRECTION_BLOCK,
                             horizon_hours=CLAUDE_BLOCK_HORIZON_HOURS)
        if wait:
            bits.append('Claude 정정 대기 — '
                        + wait.astimezone().strftime('%m/%d %H:%M') + ' 이후 재시도')
        errs = state.get('errors')
        if isinstance(errs, dict) and errs:
            detail = '; '.join(err_line(k, v)[:140] for k, v in sorted(errs.items()))
            bits.append(f'러너 오류 — {detail}')
        return ' ' + ' / '.join(bits) + '.'
    except Exception as exc:  # noqa: BLE001 — 훅에서 조용히 죽는 것이 최악이다
        return f' 러너 상태 확인 실패 — {type(exc).__name__}.'


def cmd_pending(args):
    try:
        root = repo_root()
        todo, typo, unavailable, basis, stale, _, _ = survey(
            root, want_fetch=not args.no_fetch)
    except Exception as exc:  # noqa: BLE001 — 훅에서 조용히 죽는 것이 최악이다
        msg = f'[검토 게이트] 확인 실패 — {type(exc).__name__}: {exc}'
        # 큐를 못 읽어도 러너 경보(코드 불일치 등)는 따로 보여야 한다(codex 설계 검토 #7).
        try:
            msg += runner_note(repo_root(), [])
        except Exception:  # noqa: BLE001
            pass
        print(msg)
        return 0 if args.hook else 1

    queue = todo + unavailable

    if args.json:
        print(json.dumps({'basis': basis, 'stale': stale,
                          'pending': [p.__dict__ for p in queue],
                          'typography': [p.__dict__ for p in typo],
                          'unavailable': [p.__dict__ for p in unavailable]},
                         ensure_ascii=False))
        return 0 if (args.hook or not queue) else 1

    if args.hook:
        note = runner_note(root, queue)
        if queue:
            items = ', '.join(f'{p.path}({p.reason})' for p in queue[:5])
            more = f' 외 {len(queue) - 5}건' if len(queue) > 5 else ''
            print(f'[검토 게이트] codex 미검토 발행본 {len(queue)}건 — {items}{more}. '
                  f'기준 {basis}. 절차는 .claude/REVIEW_GATE.md.{note}')
        elif stale:
            print(f'[검토 게이트] 미검토 없음 — 단 {STALE_NOTE} (기준 {basis}).{note}')
        else:
            print(f'[검토 게이트] 미검토 없음.{note}')
        return 0

    if not queue:
        print(f'미검토 없음 (기준 {basis})' + (f' — {STALE_NOTE}' if stale else ''))
    else:
        print(f'미검토 {len(queue)}건 (기준 {basis})'
              + (f' — {STALE_NOTE}' if stale else ''))
        for p in queue:
            print(f'  - [{p.section}] {p.path} @ {p.sha[:7]} — {p.reason}')
    # 조용히 사라지지 않게 꼬리에 남긴다.
    if typo:
        print('  ' + TYPO_NOTE % len(typo))
    return 1 if queue else 0


def cmd_mark(args):
    root = repo_root()
    path = rel_path(root, args.path)
    if not os.path.exists(os.path.join(root, path)):
        sys.exit(f'그런 파일이 없다: {path}')
    with open(os.path.join(root, path), 'rb') as fh:
        data = fh.read()
    sha = hash_object(root, path, data)
    if not sha:
        sys.exit(f'sha를 못 구했다: {path}')
    with Ledger(root) as book:
        try:
            ledger = mark_entry(book.data, path, sha, at=now(),
                                findings=args.findings)
            if args.baseline:
                ledger['reviewed'][path]['baseline'] = True
        except ValueError as exc:
            sys.exit(str(exc))
        book.save(ledger)
    kind = '범위 편입(읽지 않음)' if args.baseline else f'지적 {args.findings}건'
    print(f'검토 기록 — {path} @ {sha[:12]} ({kind})')
    return 0


def cmd_seed(args):
    root = repo_root()
    published, work, basis, _, _ = trees(root, want_fetch=False)
    # 발행된 판과 작업 폴더 판을 모두 기준선에 넣는다. 원격에만 있는 파일이 빠지면 그
    # 파일은 도입 첫날부터 미검토로 뜬다.
    tree = {**published, **work}

    with Ledger(root) as book:
        if book.data.get('reviewed') and not args.force:
            sys.exit(f'원장이 이미 있다 ({len(book.data["reviewed"])}건). 덮어쓰려면 --force.')
        if args.force and book.data.get('reviewed'):
            print('  (--force — 실제로 읽지 않은 글도 「본 것」으로 남는다)')
        fresh = seed(tree, at=now())
        book.save(fresh)
    print(f'기준선 {len(fresh["reviewed"])}건 기록 (기준 {basis}) — '
          f'이후 발행·수정분부터 큐에 들어온다.')
    return 0


def cmd_refresh(args):
    """조판만 바뀐 판을 «검토된 산문과 동등»으로 승인한다.

    이 명령은 «읽었다»고 기록하지 않는다. `sha`·`at`·`findings`·`baseline`은 사람이 실제로
    읽은 판을 가리킨 채로 두고 `accepted`만 붙인다. 기본이 dry-run 인 이유는, 동등 판정이
    한 번 틀리면 아무도 안 읽은 판이 조용히 큐에서 사라지기 때문이다 — 적용은 손으로.
    """
    root = repo_root()
    with Ledger(root) as book:
        todo, typo, unavailable, basis, stale, published, work = survey(
            root, want_fetch=not args.no_fetch, ledger=book.data)
        if stale and not args.no_fetch:
            sys.exit(f'{STALE_NOTE} (기준 {basis}). origin을 당긴 뒤 다시 해라.')
        if not typo:
            print(f'조판 변경 없음 (기준 {basis}).')
            return 0

        # 한 경로에 동등한 판이 둘이면 **둘 다** 승인한다. 승인을 하나만 담던 판은 origin
        # 판과 작업 폴더 판이 매 실행 서로를 밀어내며 원장을 흔들었다(2026-09-04 codex #5).
        picked = typo
        for item in picked:
            print(f'  [{item.section}] {item.path} → {item.sha[:12]}')
        print(f'조판 {len(picked)}건 승인 대상 (기준 {basis})')
        if not args.apply:
            print('  (dry-run — 실제로 쓰려면 --apply)')
            return 0

        ledger = book.data
        stamp = now()
        for item in picked:
            ledger = accept_entry(ledger, item.path, item.sha, at=stamp)
        book.save(ledger)
        done = len(picked)
    print(f'{done}건 승인 — 읽었다고 기록하지 않았다.')
    return 0


PROMPT = """읽기 전용으로 검토만 해 줘. 파일을 고치지 말고 지적만 목록으로 돌려줘.

대상: `{post}` (한국어 {market} 증시 모닝브리프 발행본)
근거 데이터: 같은 디렉터리의 `{datadir}/` — **이 글이 발행된 커밋에서 그대로 꺼낸 것**이라
본문이 인용한 값의 정본이다.

세 가지만 본다.
1. **데이터 ↔ 본문 정합** — 본문의 수치·방향·날짜가 근거 데이터와 어긋나는 곳.
   특히 지표의 증감을 좋다/나쁘다로 옮길 때 부호가 뒤집힌 곳(실업수당 청구 감소는
   개선이다).
2. **논리 비약** — 근거가 지지하지 않는 단정, 앞뒤 절이 모순되는 곳.
3. **문장** — 한 문단에 주제가 둘 이상인 곳, 피동 종결 반복, 기계적 나열.

레이아웃·HTML·CSS는 보지 마. 별도 스크립트가 검사한다.
지적마다 «위치(§번호나 첫 문장) / 무엇이 틀렸나 / 무엇이 맞나(근거 파일과 값)»으로.
지적이 없으면 「지적 없음」이라고만 답해라.
"""

MARKET_NAME = {'us': '미국', 'kr': '한국', 'jp': '일본'}

# 주간·월간·일본(2026-10-01). 근거는 데이터 폴더가 아니라 그 글의 파일들이다(`review.kinds.evidence`).
PERIOD_PROMPT = """읽기 전용으로 검토만 해 줘. 파일을 고치지 말고 지적만 목록으로 돌려줘.

대상: `{post}` (한국어 {market} {span} 리포트 발행본)
근거 파일: {evidence} — **이 글이 발행된 커밋에서 그대로 꺼낸 것**이라 본문이 인용한 값의 정본이다.

세 가지만 본다.
1. **데이터 ↔ 본문 정합** — 본문의 수치·방향·기간이 근거 파일과 어긋나는 곳.
2. **논리 비약** — 근거가 지지하지 않는 단정, 앞뒤 절이 모순되는 곳.
3. **문장** — 한 문단에 주제가 둘 이상인 곳, 피동 종결 반복, 기계적 나열.

레이아웃·HTML·CSS는 보지 마. 별도 스크립트가 검사한다.
지적마다 «위치(섹션 제목이나 첫 문장) / 무엇이 틀렸나 / 무엇이 맞나(근거 파일과 값)»으로.
지적이 없으면 「지적 없음」이라고만 답해라.
"""
SPAN_NAME = {'weekly': '주간', 'monthly': '월간'}

# 문체 수정 단계(루틴 STEP 2.5 대체, 2026-09-27). codex 가 참고할 문체 기준 — 발행 커밋에서
# 글과 함께 꺼낸다. humanize 규칙은 공개 레포에 복사하지 않고 로컬 플러그인 경로를 읽힌다.
STYLE_REFS = ('.claude/agents/STYLE_EXEMPLARS.md',)
HUMANIZE_RULES = os.environ.get('HUMANIZE_RULES') or os.path.expanduser(
    '~/.claude/plugins/marketplaces/im-not-ai/skills/humanize-korean/references/quick-rules.md')

STYLE_PROMPT = """
이번에는 위 검토에 앞서 **문체 수정**도 한다. 이 작업 폴더에서 고쳐도 되는 파일은
`prose_in.txt` **하나뿐**이다. 글 HTML·데이터·다른 파일은 절대 수정하지 마라.

`prose_in.txt` 는 발행본의 산문 문단만 글 순서대로 뽑은 것이다. `[[P001]]` 같은 이름표 줄과
`⟦0⟧` 같은 자리표는 그대로 두고 그 아래 문장만 고친다. 고칠 것이 없으면 파일을 그대로 둔다.

**목표 — 하나의 글로 읽히게 (2026-10-10 사용자 지시).** 지금 발행본은 사실을 한 문장씩 끊어
놓아서, 문장 사이의 관계를 독자가 메워야 한다. 이번 수정의 첫째 일은 그 관계를 글에 드러내는
것이다. 아래 대상 HTML 을 먼저 처음부터 끝까지 읽어 섹션·표의 경계와 논지의 흐름을 잡은 뒤
`prose_in.txt` 를 고친다(이름표가 이어져 있어도 사이에 제목이나 표가 있을 수 있다).
- 문장 사이: 짧은 단문이 이어지면 이을 자리를 찾는다. **먼저 연결어미**(-고·-지만·-는데·-면서)로
  두 문장을 한 문장으로 잇는다. 원문 낱말은 그대로 두고 어미를 바꾸는 것이 방법이다. 문장 앞에
  접속어를 붙이는 것은 그다음이다.
- 문단 사이: 같은 섹션 안에서는 문단 첫 문장이 앞 문단을 어떻게 받는지(앞 결론을 이어 가는지,
  반대 사례인지, 다음 단계인지) 보이게 한다. 지시어(이·그·이런)는 가리키는 말이 바로 앞 문장에
  있을 때만 쓴다. 섹션이 바뀌는 자리는 억지로 잇지 않는다.
- 이을 관계가 없는 문장은 그대로 둔다. 접속어를 뿌리는 것도 끊긴 글만큼 나쁘다. 그래서
  **같은 접속어(반면·다만·하지만·그런데·게다가 등)는 글 전체에서 두 번까지**, 문단 첫머리에
  붙이는 접속어는 글 전체 문단의 다섯에 하나까지다. 한 문장에 관계는 둘까지다.
- 「실제로」는 접속어가 아니다 — 근거를 받는 척하는 군말이라 새로 넣지 않는다.
  「따라서·그러므로·결론적으로·즉」 같은 결산어도 쓰지 않는다.

**잇는 말은 원문이 말한 관계만 드러낸다.** 접속어 하나가 새 주장이 된다.
- 인과·선후(그래서·때문에·-아서·-니·-자·그러자·결국)는 원문이 그 인과나 선후를 말할 때만 쓴다.
  「유가가 올랐다. 금리가 내렸다.」를 「유가가 오르자 금리가 내렸다」로 바꾸면 원문에 없는 인과다.
- 대조·양보(하지만·반면·-지만·-는데도)는 두 사실이 실제로 엇갈릴 때만 쓴다.
- 확실성과 주체는 그대로: 「~라고 본다」는 이은 뒤에도 해석이고, 「~라고 전했다」의 말한 사람도
  그대로다. 관계가 불분명하면 잇지 말고 두 문장으로 둔다.
- 서로 다른 자산·종목을 다룬 두 문장은 한 문장으로 합치지 않는다 — 앞 문장에 붙여 쓰면 뒤
  자산의 수치가 앞 자산에 붙어 읽힌다. 문장 앞에 접속어만 붙인다.

기준: 이 글은 PM 이 읽는 데스크 문서다. 어미는 `-다` 로 고정(-습니다·~죠 금지), 수사 의문 금지,
작업 어휘(원장·회차·판정불가·파일명·코드) 금지. 한 문단에 한 주제.
연구 체계의 문장(반도체 후보의 가격 근거·새로 연 질문·다음 시험·기준선 고정)과 그 자리에서 지어낸
비유(하루를 정했다·이름표·시계를 늘린다)는 문장 표본 §10 의 예시처럼 **문장 단위로 최소한** 고친다 —
문맥을 보고 고르며 강제 치환하지 않는다(관측 시각·정책금리 경로·일목 기준선은 정상 용어). 사실·수치·
인과·판단의 방향과 강도·확인 기준은 그대로, 「확인되지 않았다」를 「없었다」로 바꾸지 않는다. 핵심
판단의 방향, 비교 관계(「A보다 B」), 인과(「~때문」)를 뒤집거나 지우지 않는다. 문장을 지우거나 한계
문장을 합치는 수정, 새 판단 어휘(악화·개선 등)는 하지 않는다 — 문단 검사가 일부를 버리지만 전부는
못 잡으므로 지시로 지킨다. 그런 문장은 원문 그대로 둔다.
판단이 바뀌는 자리를 「맞는다·선다·갈린다·고쳐 본다·쪽으로 무게를 옮긴다」로 돌려 막은 문장, 「무너졌다·
거울·걸러 냈다」 같은 비유, 범위를 넘는 전칭(「어디에도」)은 문장 표본 §10-8~10 처럼 무엇이 무엇을 뒷받침·
약화·보류하는지 그 이름으로 고친다 — 판단의 세기(뒷받침·수정·철회·보류)와 조건은 원문 그대로 둔다.
주체가 모호할 때만 밝히고, 피동 종결·기계적 나열·번역투를 걷어낸다.
문장 표본: `.claude/agents/STYLE_EXEMPLARS.md`.{rules}
문장 표본이나 추가 규칙이 이 지시와 부딪치면 이 지시를 따른다 — 표본의 「판정 문장은 짧게
끊는다」는 판정 문장을 길게 늘이지 말라는 뜻이지, 앞 근거와 잇지 말라는 뜻이 아니다.

**문단 검사** — 아래는 문단마다 원문과 같아야 하고, 하나라도 어기면 **그 문단** 수정이 버려진다.
- 숫자(부호 포함)·날짜·영문 이름·티커, 인용문
- 판단 어휘: 개선·악화·보합·둔화·가속·재가속·뚜렷·완만·미미·확대·축소·중립과 레짐 이름
- 문장의 순서. 이름과 방향어(오르다·내리다·늘다·줄다 계열)가 나오는 순서가 바뀌면 버려진다.
- 부정어(않·아니·못·없·띄어 쓴 「안」)의 개수와 그것이 부정하는 대상. 「~뿐 아니라」「~없이」
  같은 이음말을 새로 넣거나 원문에서 빼지 않는다. 조건(「~하면」)이 걸린 대상도 그대로.
- 자리표의 개수와 순서, 자리표 쌍이 감싼 말(링크 문구)
- 문단 길이는 0.5~2배. 원문과 많이 닮아야 한다(절을 다른 말로 갈아끼우면 버려진다). 짧은
  문단은 잇는 말 몇 글자로도 이 한도를 넘으므로 어미만 바꾸거나 그대로 둔다.
- 추정을 단정으로, 조건을 인과로 바꾸지 않는다. 마크다운·HTML 을 넣지 않는다.

**글 전체 검사** — 하나라도 어기면 **글 전체** 수정이 버려진다. 원문에서 이미 실패하던 검사도
출력이 조금만 달라지면 새 실패로 친다. 이을 때 특히 조심한다.
- 한 문장의 숫자는 여섯 개까지. 날짜·시각·연도, 「10년물·20일선·30분봉」 같은 기간 표기,
  단위·부호 없는 한 자리 정수만 빼고 센다 — 「1bp」「3%」「-2」는 센다. 두 문장을 합칠 때 센다.
- 한 문단에서 끝 두 글자가 같은 문장(했다·했다…)이 네 개 이어지면 안 된다 — 잇거나 동사를 바꿔 푼다.
- 같은 낱말로 시작하는 문단은 글 전체에서 네 번까지(「하지만」「10월」도 센다).
- 「~에 따른」「~를 통한」「~에 의한」은 합계 세 번까지.
- 검사가 찾는 고정 문구는 낱말 그대로 둔다: 「표본 부족」, 판정을 밝히는 말(유효·유지·무효·
  폐기·수정·판정할 수 없), 「확인하지 못했다」류의 한계 문장. 합치면서 흐리거나 지우지 않는다.
- 문단을 줄이지 않는다. 잇는 수정은 길이가 같거나 조금 늘 뿐이다.

**출력 계약** — 마지막 답의 첫 줄은 정확히 `검토 판본: 윤문 후` 이다. 둘째 줄부터 위 세 가지
검토를 **고친 뒤의 문장 기준으로** 한 지적 목록, 없으면 「지적 없음」만 쓴다.
"""


class RunnerLock:
    """tick 겹침 방지. **advisory lock 이어야 한다** — `mkdir` 락은 강제 종료나 전원
    차단 뒤 남아서, 이후 모든 tick 이 「이미 실행 중」으로 조용히 끝난다. 그러면 러너가
    영구히 꺼진 채 켜져 보인다. flock 은 프로세스가 죽으면 커널이 푼다.
    """

    def __init__(self, root):
        self.path = os.path.join(root, RUNNER_LOCK)
        self.fd = None

    def __enter__(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.fd = os.open(self.path, os.O_CREAT | os.O_WRONLY, 0o644)
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            os.close(self.fd)
            self.fd = None
            # 경합만 조용히 비킨다. 파일시스템·플랫폼 오류까지 「다른 tick 이 돈다」로
            # 삼키면 영구적인 정상 스킵이 되어 러너가 꺼진 채 켜져 보인다.
            if exc.errno in (errno.EAGAIN, errno.EWOULDBLOCK, errno.EACCES):
                return None
            raise
        return self

    def __exit__(self, *exc):
        if self.fd is not None:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
            os.close(self.fd)
            self.fd = None
        return False


def load_state(root):
    try:
        with open(os.path.join(root, STATE), encoding='utf-8') as fh:
            got = json.load(fh)
        return got if isinstance(got, dict) else {}
    except (OSError, ValueError):
        # 망가진 상태 파일에 러너가 멈추면 안 된다. 원장과 같은 실패 방향이다.
        return {}


def save_state(root, state):
    full = os.path.join(root, STATE)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(full))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            json.dump(state, fh, ensure_ascii=False, indent=2, sort_keys=True)
            fh.write('\n')
        os.replace(tmp, full)
    except BaseException:
        os.path.exists(tmp) and os.unlink(tmp)
        raise


def drafts_ready(root, queue):
    """큐 항목 중 **그 판의** 초안이 이미 놓인 것. 파일명이 SHA 를 들고 있으므로, 글이
    바뀌면 초안은 자동으로 세어지지 않는다."""
    try:
        have = set(os.listdir(os.path.join(root, DRAFTS)))
    except OSError:
        return 0
    return sum(1 for p in queue if draft_name(p) in have)


def rev_parse(root, spec):
    out = git(root, 'rev-parse', '--verify', '--quiet', spec)
    got = out.stdout.strip()
    return got if out.returncode == 0 and _SHA.match(got) else None


def publish_commit(root, path, sha):
    """이 blob 을 넣은 커밋. 없으면 None.

    **`origin/main` HEAD 를 쓰면 안 된다.** 근거 데이터 파일은 날짜별이 아니라 한 자리를
    덮어쓰므로, 최신 커밋에서 꺼내면 이틀 전 글에 오늘 데이터가 딸려온다 — 2026-09-10
    실측: `posts/2026-09-08.html` 의 발행 커밋은 `4e1f3bf` 인데 그때의 `origin/main` HEAD
    는 13 커밋 뒤인 `6633a08` 이었다. 발행 커밋에서 글과 데이터를 함께 꺼내야 「이 데이터가
    이 글이 쓰인 데이터다」가 참이 된다.
    """
    out = git(root, 'log', '--format=%H', '-n', '40', 'origin/main', '--', path)
    if out.returncode:
        return None
    # 최신 → 과거 순. 이 blob 을 담은 커밋 중 **가장 오래된** 것이 그 판을 넣은 커밋이다.
    # 최신 쪽을 잡으면 정정 재발행 뒤 데이터가 한 번 더 덮어써진 자리를 꺼내게 된다.
    #
    # **조판만 바꾼 커밋은 발행 커밋이 아니다.** 직전 판이 조판 변환으로 이 판이 되면
    # (`prose.typography` 가 True) 한 판 더 거슬러 올라간다. 2026-09-26 실측: 방문 통계
    # 소급(8458e9a)이 미검토 11편의 발행 커밋을 9/25 로 바꿔, 9/17 글을 9/25 데이터와
    # 맞댈 뻔했다. 문장을 고친 판(False)과 판정 불가(None)에서는 멈춘다.
    commits = out.stdout.split()
    found, at = None, None
    for i, commit in enumerate(commits):
        if rev_parse(root, f'{commit}:{path}') == sha:
            found, at = commit, i
        elif found:
            break
    while found and at + 1 < len(commits):
        prev = rev_parse(root, f'{commits[at + 1]}:{path}')
        if not prev or not (_style_step(root, found, path, prev, sha)
                            or _contested_step(root, found, path, prev, sha)
                            or prose_mod.typography(path, _blob_text(root, prev),
                                                    _blob_text(root, sha), root=root) is True):
            break
        sha, at, found = prev, at + 1, commits[at + 1]
        while at + 1 < len(commits) and rev_parse(root, f'{commits[at + 1]}:{path}') == sha:
            at += 1
            found = commits[at]
    return found


def _contested_step(root, commit, path, prev, sha):
    """쟁점 자리만 바뀐 판인가 — 로컬 쟁점 러너가 발행 뒤 자리표시를 채우거나 지운 커밋.

    그 판을 발행 커밋으로 치면 다음 날 덧붙인 KR 글이 다음 날 kr/data 와 맞대져 자동 검토에서 빠진다
    (KR 설계 검토 K05). 조판 판정으로 넘기지 않는다 — 판은 검토 대상으로 남고, 근거만 원래 발행 커밋이다.
    쟁점 섹션 자체의 근거는 결과 JSON 이고, 검토자에게는 섹션을 빼고 준다(`_drop_contested`).
    """
    m = re.fullmatch(r'(kr/posts|news)/(\d{4}-\d{2}-\d{2})\.html', path)
    if not m:
        return False                          # 쟁점 섹션은 KR 마감 브리프·US 뉴스·산업 브리프에만 있다
    kind = contested_mod.slot_only_change(_blob_text(root, prev), _blob_text(root, sha))
    if kind == 'filled':
        return True
    if kind != 'removed':
        return False
    # 자리가 사라진 판은 그 커밋의 결과가 확정된 non-ok 일 때만 — 러너가 자리표시를 지운 경우다.
    # 사람이 섹션을 통째로 지운 판까지 넘기지 않는다(구현 검토 #4).
    market = 'kr' if m.group(1) == 'kr/posts' else 'us'
    raw = git(root, 'show', f'{commit}:data/contested/{market}/{m.group(2)}.json')
    try:
        payload = json.loads(raw.stdout) if raw.returncode == 0 else None
    except ValueError:
        payload = None
    if not isinstance(payload, dict):
        return False                          # 배열·문자열 JSON 이 큐 순회를 멈추지 않게(구현 검토 2차 N4)
    return payload.get('status') != 'ok' and contested_mod.settled(payload, market, m.group(2))


def _drop_contested(path):
    """검토 스냅샷의 글에서 쟁점 섹션을 뺀다 — 별도 수집·검증을 거친 생성물이라 kr/data 로 대조할 것이
    아니고, 검토자가 그 문장을 「근거 없음」으로 지적하면 정정자가 HTML 을 손대게 된다(K06)."""
    try:
        with open(path, encoding='utf-8') as fh:
            text = fh.read()
    except OSError:
        return
    out = contested_mod.strip_slot(text, keep='')
    if out != text:
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write(out)


def _style_step(root, commit, path, prev, sha):
    """발행 뒤 codex 문체 커밋인가 — 트레일러 **와** 태그 구조·수치 불변이 둘 다 참일 때만.

    트레일러만 믿으면 손으로 쓴 커밋 메시지 하나로 근거 데이터를 옛 날짜에 묶을 수 있다.
    """
    from review import style_pass
    msg = git(root, 'log', '-1', '--format=%B', commit)
    if msg.returncode or not style_pass.is_style_commit(msg.stdout, prev):
        return False
    before, after = _blob_text(root, prev), _blob_text(root, sha)
    return bool(before and after) and style_pass.same_skeleton(before, after)


EVIDENCE_DATE = {'us': 'data/market_data.json', 'kr': 'kr/data/kr_market_data.json'}
_POST_DATE = re.compile(r'(?:kr/)?posts/(\d{4}-\d{2}-\d{2})\.html$')


def evidence_mismatch(root, item):
    """발행 커밋의 근거 데이터가 이 글의 날짜가 아니면 그 이유, 맞으면 None.

    무인 검토·정정의 근거는 발행 커밋 스냅샷뿐이다. 소급 발행(9/17 글이 9/19 에 9/18
    데이터로)이나 문장을 고친 재발행(9/02 글의 9/14 문단 분리)은 그 커밋의 데이터가
    다른 날 것이라, 맞대면 정상 문장이 오류로 정정된다. 그런 글은 자동으로 읽지 않는다.
    """
    m = _POST_DATE.fullmatch(item.path)
    if item.section not in EVIDENCE_DATE or not m:
        return None   # 날짜가 박힌 us·kr 일간 글만 판정한다
    commit = publish_commit(root, item.path, item.sha)
    if not commit:
        return None   # 기존 경로가 「발행 커밋을 찾지 못했다」로 따로 알린다
    raw = git(root, 'show', f'{commit}:{EVIDENCE_DATE[item.section]}')
    try:
        got = json.loads(raw.stdout).get('report_date') if raw.returncode == 0 else None
    except (ValueError, AttributeError):
        got = None
    if got == m.group(1):
        return None
    return f'{item.path}: 근거 기준일 {got} ≠ 글 날짜 {m.group(1)} ({commit[:7]})'


def _drop_misdated(root, items, errs):
    keep, why = [], []
    for item in items:
        reason = evidence_mismatch(root, item)
        (why.append(reason) if reason else keep.append(item))
    if why:
        errs['근거'] = err(HUMAN, f'{len(why)}건 자동 검토 제외 — ' + '; '.join(why))
    else:
        errs.pop('근거', None)
    return keep


def _blob_text(root, sha):
    out = git_bytes(root, 'cat-file', 'blob', sha)
    if out.returncode:
        return None
    try:
        return out.stdout.decode('utf-8')
    except UnicodeDecodeError:
        return None


def _wanted(name):
    return name.endswith(SNAPSHOT_SUFFIXES) or name in STYLE_REFS


def snapshot(root, oid, paths, dest, everything=False):
    """고정한 커밋에서 글과 근거 데이터를 꺼낸다.

    **한 커밋에서 둘을 함께 꺼내는 것이 요점이다.** 근거 데이터 파일은 날짜별이 아니라 한
    자리를 덮어쓰므로(2026-09-10 실측), 작업 폴더의 데이터로 밀린 글을 대조하면 거짓 지적이
    난다. 같은 커밋에서 나온 짝이면 「이 데이터가 이 글이 쓰인 데이터다」가 정의상 참이다.
    """
    out = git_bytes(root, 'archive', '--format=tar', oid, '--', *paths)
    if out.returncode:
        return False
    with tarfile.open(fileobj=io.BytesIO(out.stdout)) as tf:
        keep = [m for m in tf.getmembers() if m.isfile() and (everything or _wanted(m.name))]
        tf.extractall(dest, members=keep, filter='data')
    return True


def review_one(root, commit, item, timeout, style=False):
    """codex 를 읽기 전용으로 한 편 돌린다 — (초안, 실패 이유, 실패 종류, 원문).

    **종류는 발생한 분기에서 붙인다.** 타임아웃은 예외이고 재발행은 SHA 비교라,
    종료 코드와 출력만 보고 넷을 가를 수 없다.

    네 번째 값은 **자르지 않은** 실행 결과다. 훅에 남기는 이유는 200 자로 자르므로
    그걸로 한도를 판별하면 긴 메시지에서 문구를 놓친다.
    """
    # 스냅샷 디렉터리는 git 레포가 아니다. `--skip-git-repo-check` 없이 부르면 codex 가
    # 「Not inside a trusted directory」로 거부한다 — 레포 안에서 손으로 돌릴 때는 안
    # 드러나고 launchd 첫 실행에서야 나왔다(2026-09-10).
    work = tempfile.mkdtemp(prefix='review-')
    try:
        if item.section in kinds.PERIOD:
            market, span = kinds.PERIOD[item.section]
            have = _period_evidence(root, commit, item)
            if not snapshot(root, commit, (item.path, *have), work):
                return None, f'{commit[:7]} 에서 스냅샷을 못 꺼냈다', UNKNOWN, ''
            prompt = PERIOD_PROMPT.format(post=item.path, market=MARKET_NAME[market],
                                          span=SPAN_NAME[span],
                                          evidence=', '.join(f'`{p}`' for p in have) or '없음')
        else:
            data_dir = SNAPSHOT[item.section]
            if not snapshot(root, commit, (item.path, data_dir), work):
                return None, f'{commit[:7]} 에서 스냅샷을 못 꺼냈다', UNKNOWN, ''
            prompt = PROMPT.format(post=item.path,
                                   market=MARKET_NAME.get(item.section, item.section),
                                   datadir=data_dir)
            _drop_contested(os.path.join(work, item.path))
        # 문체 기준은 발행 당시 것이 아니라 **지금** 것이다. 없어도 문체 수정은 돈다.
        if style and not snapshot(root, 'origin/main', STYLE_REFS, work):
            print(f'[러너] 문체 기준을 못 꺼냈다 — {", ".join(STYLE_REFS)}')
        if style:
            from review import style_pass
            # 고치는 판은 **지금 공개된 판**이다. 발행 커밋의 판과는 조판만 다를 수 있다.
            current = _blob_text(root, item.sha)
            if current is None:
                return None, f'{item.sha[:7]} 을 못 읽었다', UNKNOWN, ''
            # 검토자가 읽는 글에서는 쟁점 섹션을 빼고(K06), 문단 추출은 공개판 그대로 — 되꽂기는 공개판의
            # 문단 순서와 맞아야 한다
            with open(os.path.join(work, item.path), 'w', encoding='utf-8') as fh:
                fh.write(contested_mod.strip_slot(current, keep=''))
            style_pass.prepare(work, current)
            rules = (f'\n추가 규칙(읽기만): `{HUMANIZE_RULES}`'
                     if os.path.isfile(HUMANIZE_RULES) else '')
            prompt = STYLE_PROMPT.format(rules=rules) + '\n' + prompt.replace(
                '읽기 전용으로 검토만 해 줘. 파일을 고치지 말고 지적만 목록으로 돌려줘.',
                '검토 부분은 지적만 목록으로 돌려줘.')
        try:
            out = subprocess.run(
                [CODEX, 'exec', '--sandbox', 'workspace-write' if style else 'read-only',
                 '--skip-git-repo-check', '-C', work, '-'],
                input=prompt, capture_output=True, text=True, timeout=timeout)
        except FileNotFoundError:
            return None, f'codex 가 없다 ({CODEX})', UNKNOWN, ''
        except subprocess.TimeoutExpired:
            return None, f'codex 가 {timeout}초 안에 안 끝났다', TIMEOUT, ''
        # 읽는 사이 그 글이 재발행되지 않았는지 **지금 공개된 판**에 다시 물어본다. 고정한
        # 커밋에 물으면 불변이라 늘 통과해서, 검사하는 시늉만 하게 된다.
        try_fetch(root)
        now_sha = rev_parse(root, f'origin/main:{item.path}')
        ok, why = accept_draft(out.returncode, out.stdout, now_sha or '', item.sha)
        if not ok:
            raw = ((out.stdout or '') + '\n' + (out.stderr or '')).strip()
            tail = (out.stdout or out.stderr or '').strip().splitlines()[-1:]
            if out.returncode != 0:
                kind = (LIMIT if is_limit_error(out.returncode, out.stdout, out.stderr)
                        else UNKNOWN)
            elif now_sha != item.sha:
                kind = RESHIPPED
            else:
                kind = UNKNOWN
            return None, why + (f' — {tail[0][:200]}' if tail else ''), kind, raw
        if style:
            return out.stdout, None, None, _apply_style(root, commit, item, work)
        return out.stdout, None, None, ''
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _apply_style(root, commit, item, work):
    """codex 가 고친 문단을 공개판에 반영 → style_pass.Result.

    게이트 근거는 **새로** 꺼낸다. codex 는 스냅샷 안에서 쓰기 권한이 있었으므로 그 데이터를
    근거로 믿지 않는다.
    """
    from review import style_pass
    evidence = tempfile.mkdtemp(prefix='style-evidence-')
    try:
        if item.section in kinds.PERIOD:
            return _apply_period_style(root, commit, item, work, evidence)
        data_dir = SNAPSHOT[item.section]
        if not snapshot(root, commit, (data_dir,), evidence):
            return style_pass.Result(reason=f'{commit[:7]} 에서 근거를 다시 못 꺼냈다')
        # 연구 원장도 **발행 당시** 것이라야 한다. 지금 원장에는 다음 날 cycle 이 쌓여 있어
        # 원본부터 「stale」로 실패하고, 그러면 유보 표현이 사라져도 못 잡는다. 증거 파일은
        # 확장자가 없어 필터 없이 꺼낸다. 연구 워크플로 이전 커밋에는 없다.
        research = f'research/{item.section}'
        has_research = snapshot(root, commit, (research,), evidence, everything=True)
        with open(os.path.join(work, style_pass.PAYLOAD), encoding='utf-8') as fh:
            payload = fh.read()
        return style_pass.apply(root, item, payload, work, os.path.join(evidence, data_dir),
                                research_root=(os.path.join(evidence, research)
                                               if has_research else None))
    except OSError as exc:
        return style_pass.Result(reason=f'{type(exc).__name__}: {exc}')
    finally:
        shutil.rmtree(evidence, ignore_errors=True)


def _period_ready(root, oid, items, errs):
    """주간·월간·일본 → (남길 항목, {경로: 실제 발행일}).

    근거가 빠진 글은 **codex 를 부르기 전에** 뺀다. 부른 뒤 거르면 근거 없이 쓴 「지적 없음」
    초안이 남고 하루 한도도 쓴다(2026-10-01 codex 구현 검토). 발행일은 그 판을 낸 커밋의 KST 날짜다.
    """
    keep, dated, why = [], {}, []
    for item in items:
        if item.section not in kinds.PERIOD:
            keep.append(item)
            continue
        commit = publish_commit(root, item.path, item.sha) or oid
        want = kinds.evidence(item.section, kinds.key_of(item.path))
        missing = [p for p in want if p not in _period_evidence(root, commit, item)]
        if missing:
            why.append(f'{item.path}: 근거 없음 {", ".join(missing)}')
            continue
        out = git(root, 'log', '-1', '--format=%cI', commit)
        try:
            dated[item.path] = datetime.fromisoformat(out.stdout.strip()).astimezone(KST).date()
        except ValueError:
            pass
        keep.append(item)
    if why:
        errs['근거-기간'] = err(HUMAN, f'{len(why)}건 자동 검토 제외 — ' + '; '.join(why))
    else:
        errs.pop('근거-기간', None)
    return keep, dated


def _period_evidence(root, commit, item):
    """발행 커밋에 있는 근거 파일만 — 없는 경로를 넘기면 git archive 가 통째로 실패한다."""
    return tuple(p for p in kinds.evidence(item.section, kinds.key_of(item.path))
                 if rev_parse(root, f'{commit}:{p}'))


def _apply_period_style(root, commit, item, work, evidence):
    """주간·월간·일본. 근거가 하나라도 없으면 반영하지 않는다 — 게이트가 원본·수정본 모두 같은
    FATAL 로 죽으면 「원본에서도 같은 실패」로 봐줘서 게이트가 꺼진 채 통과한다."""
    from review import style_pass
    want = kinds.evidence(item.section, kinds.key_of(item.path))
    have = _period_evidence(root, commit, item)
    missing = [p for p in want if p not in have]
    if missing:
        return style_pass.Result(reason=f'{commit[:7]} 에 근거가 없다: {", ".join(missing)}')
    if not snapshot(root, commit, have, evidence, everything=True):
        return style_pass.Result(reason=f'{commit[:7]} 에서 근거를 다시 못 꺼냈다')
    with open(os.path.join(work, style_pass.PAYLOAD), encoding='utf-8') as fh:
        payload = fh.read()
    return style_pass.apply(root, item, payload, work, evidence)


def _save(root, state, errs, progressed=True):
    """상태를 원자적으로 남긴다.

    `progressed=False` 는 **이번 tick 이 아무 판정도 하지 않았다**는 뜻이다(codex 대기).
    그때 `last_ok` 를 갱신하면 훅에 「마지막 성공 방금」만 보이고, 러너가 한도에 막혀
    아무것도 안 하고 있다는 사실이 사라진다.

    오류는 **섹션별로** 들고 간다. 하나로 뭉치면 kr 성공이 앞선 us 실패를 덮어 지우고,
    한도는 이미 쓴 채 초안은 없는데 훅에는 「방금 성공」으로 보인다 — 조용한 실패다.
    각 섹션의 오류는 **그 섹션이 초안을 낼 때만** 풀린다.
    """
    state['errors'] = errs
    if not errs and progressed:
        state['last_ok'] = now()
    save_state(root, state)
    for where, why in sorted(errs.items()):
        print('[러너] ' + err_line(where, why))
    return 1 if errs else 0


STYLE_LOG_KEEP = 20
STYLE_NOTE_HEAD = '[문체 반영 상태]'


def _style_note(result):
    """초안 앞에 붙일 반영 상태 — 지적은 codex 가 고친 문장 기준이다(`검토 판본: 윤문 후`).

    전부 공개됐으면 빈 문자열. 일부·전부가 공개되지 않았으면 정정 단계가 「인용이 공개판에
    없다」는 이유로 실제 오류를 기각하지 않게 알린다(2026-09-30 codex 구현 검토).
    """
    kept = [pid for pid, _ in getattr(result, 'skipped', ())]
    if result.sha and not kept:
        return ''
    if result.sha:
        where = f'문단 {", ".join(kept)} 은 윤문이 공개되지 않고 원문 그대로다.'
    else:
        where = f'윤문은 공개되지 않았다 — 공개판은 원문 그대로다({(result.reason or "")[:200]}).'
    return (f'{STYLE_NOTE_HEAD} {where} 아래 지적이 인용한 문장은 공개판과 다를 수 있다. '
            '인용이 다르다는 이유만으로 기각하지 말고, 공개판의 같은 자리 문장에서 사실 여부를 '
            '확인하라.\n\n')


def _note_style(state, item, result):
    """문체 단계의 결과를 남긴다. 거부는 러너 오류가 아니다 — 원본이 그대로 공개돼 있을 뿐이다."""
    log = [x for x in state.get('style_log', []) if isinstance(x, dict)]
    log.append({'at': now(), 'path': item.path, 'from': item.sha[:7],
                'to': (result.sha or '')[:7], 'reason': (result.reason or '')[:300],
                'kept': [pid for pid, _ in getattr(result, 'skipped', ())],
                'proposed': list(getattr(result, 'accepted', ()) or ()),
                'proposal': getattr(result, 'proposal', None)})
    state['style_log'] = log[-STYLE_LOG_KEEP:]
    kept = len(getattr(result, 'skipped', ()))
    tag = (f'반영 {item.sha[:7]} → {result.sha[:7]}' + (f' (원문 유지 {kept}문단)' if kept else '')
           if result.sha else f'미반영 — {result.reason}')
    print(f'문체 — [{item.section}] {item.path}: {tag}')
    return state


def _drafts_on_disk(root):
    try:
        return set(os.listdir(os.path.join(root, DRAFTS)))
    except OSError:
        return set()


def _published_queue(root, oid):
    """Automation uses the published ledger; the user's checkout may be days behind."""
    published = tree_at(root, oid) or {}
    if rev_parse(root, f'{oid}:{LEDGER}'):
        ledger = json.loads(git(root, 'show', f'{oid}:{LEDGER}').stdout)
        if not isinstance(ledger, dict) or not isinstance(ledger.get('reviewed'), dict):
            raise ValueError('공개 원장이 손상됐다')
    else:
        ledger = {'reviewed': {}}
    blobs = Blobs(root)
    blobs.prefetch(_needed_shas(ledger, (published,)))
    return classify(ledger, published, blobs.equivalent).pending, published


def _correct_ready(root, args, state, errs):
    from review.corrector import correct_one

    if not try_fetch(root):
        errs['러너'] = err(UNKNOWN, '정정 전 fetch 실패')
        return state
    oid = rev_parse(root, 'origin/main')
    if not oid:
        raise ValueError('정정할 origin/main 이 없다')
    if blocked_until(state, key=CORRECTION_BLOCK,
                     horizon_hours=CLAUDE_BLOCK_HORIZON_HOURS):
        return state   # Claude 계정 한도 — 초기화 전에는 부르지 않는다
    state.pop(CORRECTION_BLOCK, None)
    queue, published = _published_queue(root, oid)
    have = _drafts_on_disk(root)
    # Claude 자동 정정은 일간만이다. 주간·월간·일본의 초안은 수동 review-gate 로 간다.
    ready = [item for item in queue if item.section in kinds.DAILY and draft_name(item) in have]
    day = today_kst()
    quota = {'calls': state.get('correction_calls', {})}
    for item in eligible(ready, published, quota, day, max_age_days=None):
        key = f'정정-{item.section}'
        if stalled(state, item.path):
            # 같은 글에서 세 번 실패했다. 더 고치는 대신 사람에게 넘긴다 — 세 번이면
            # 대개 고칠 대상이 본문이 아니라 게이트나 계약이다. **날짜가 바뀌어도
            # 풀리지 않는다**: 하루 상한과 달리 이 회차는 누적이라야 의미가 있다.
            errs[key] = err(HUMAN,
                            f'{item.path}: 자동 정정 {ROUND_CAP}회 실패 — 사람이 읽어야 한다')
            continue
        commit = publish_commit(root, item.path, item.sha)
        if not commit:
            errs[key] = err(UNKNOWN, f'{item.path}: 발행 커밋을 찾지 못했다')
            break
        misdated = evidence_mismatch(root, item)
        if misdated:
            errs[key] = err(HUMAN, misdated)
            continue
        quota = reserve(quota, day, item.section)
        state['correction_calls'] = quota['calls']
        save_state(root, state)
        draft = os.path.join(root, DRAFTS, draft_name(item))
        with open(draft, encoding='utf-8') as fh:
            text, why = correct_one(root, item, fh.read(), commit,
                                    args.correction_timeout)
        # Keep the complete Claude report private, beside its Codex input.
        with open(draft + '.claude.txt', 'w', encoding='utf-8') as fh:
            fh.write(text or '')
            if why:
                fh.write('\nERROR: ' + why + '\n')
        if why and is_claude_limit(why):
            # 계정 한도 거부는 글의 결함이 아니고 토큰도 안 썼다 — 회차로 세지 않고
            # 예약을 되돌린 뒤, 초기화 시각까지 정정을 쉰다.
            quota = release(quota, day, item.section)
            state['correction_calls'] = quota['calls']
            when = claude_retry_at(why)
            if when:
                state[CORRECTION_BLOCK] = when
            save_state(root, state)
            errs[key] = err(LIMIT, f'{item.path}: {why[-160:]}')
            break
        if why and freshness.DRIFT in why:
            # Claude 를 부르기 전에 막혔다 — 글의 결함이 아니고 토큰도 안 썼다. 회차로 세지
            # 않고 예약을 되돌린다(codex 구현 검토 #3: 회차 3 이면 그 글의 자동 정정이 영영 선다).
            quota = release(quota, day, item.section)
            state['correction_calls'] = quota['calls']
            save_state(root, state)
            errs[key] = err(UNKNOWN, f'{item.path}: {why}')
            break
        if why:
            # 재시도성 실패(그 사이 main 이 움직였다)는 회차로 세지 않는다 — 고칠 수
            # 없다는 신호가 아니라 다음 tick 에 다시 하라는 신호다.
            if 'remote main changed' not in why:
                state = note_round(state, item.path)
                save_state(root, state)
            errs[key] = err(UNKNOWN, f'{item.path}: {why}')
            break
        state = clear_rounds(state, item.path)
        errs.pop(key, None)
        print(f'정정·푸시 완료 — [{item.section}] {item.path}')
    return state


def cmd_run(args):
    """매시 tick — 공개판을 고정하고, 한도 안에서 codex 초안을 만들어 둔다.

    기본은 읽기 전용 초안. --correct 는 Claude 검증·정정·정상 push까지 잇는다.
    사용자의 checkout은 fetch 외에는 움직이지 않는다.
    """
    root = repo_root()
    lock = RunnerLock(root)
    if lock.__enter__() is None:
        return 0  # 앞 tick 이 아직 돈다. 조용히 비킨다.
    state = load_state(root)
    state['last_tick'] = now()
    got = state.get('errors')
    errs = dict(got) if isinstance(got, dict) else {}
    errs.pop('러너', None)          # 이번 tick 이 다시 판정한다
    try:
        # pull 하지 않는다. 무인 pull 은 읽기가 아니라 사용자의 작업 폴더를 움직인다.
        if not try_fetch(root):
            errs['러너'] = err(UNKNOWN, 'fetch 실패 — 공개판을 확인 못 했다')
            return _save(root, state, errs)
        oid = rev_parse(root, 'origin/main')
        if not oid:
            errs['러너'] = err(UNKNOWN, 'origin/main 을 못 찾았다')
            return _save(root, state, errs)
        # 이 프로세스가 import 한 코드가 origin/main 과 같을 때만 공개판을 읽고 고친다. 다르면
        # codex·정정 모두 멈춘다 — 정정도 로컬 게이트 스크립트를 돈다. 경보는 맞았음을 확인했을
        # 때만 지운다(fetch 실패로 지우면 해결을 확인하지 않은 채 사라진다).
        code_oid = os.environ.get(ENV_CODE)
        if code_oid:
            # 런처(scripts/runner_launch.py)가 origin/main 을 떠 둔 사본에서 돌고 있다 — 사람의
            # 폴더와 무관하다. 그 커밋이 비교 기준이다.
            stale = freshness.pin_code(root, code_oid)
        else:
            # 런처 없이 site/ 에서 바로 돌았다(손으로 부를 때). 그 폴더가 origin/main 과 같고,
            # import 한 뒤 바뀌지 않았을 때만 돈다.
            stale = freshness.check(root) or freshness.pin(root)
        if stale:
            errs[freshness.KEY] = err(HUMAN, f'러너 코드가 origin/main 과 다르다 — {stale}. '
                                             '맞출 때까지 자동 검토·문체 수정·정정을 멈춘다')
            return _save(root, state, errs, progressed=False)
        errs.pop(freshness.KEY, None)

        if getattr(args, 'correct', False) or code_oid:
            # 자동 tick 은 공개판 원장만 본다 — 사람의 작업 폴더(편집 중인 원장 등)를 먼저 조사하면
            # 미완성 로컬 파일 하나가 자동 검토·정정을 전부 막는다(codex 구현 3차 #5).
            todo, published = _published_queue(root, oid)
            unavailable = []
        else:
            todo, _typo, unavailable, _basis, _stale, _pub, _work = survey(
                root, want_fetch=False)
            # 큐 판정은 두 트리를 보지만 **자동으로 읽을 대상은 고정한 판만**이다. 가변
            # `origin/main` 을 다시 읽으면 tick 도중 재발행된 판을 고정판인 양 집는다.
            published = tree_at(root, oid) or {}
        day = today_kst()
        # 차단 대상은 **codex 신규 검토 호출만**이다. 준비된 초안의 정정(Claude)은 계속
        # 돈다 — 공급자 한도는 codex 쪽 사정이고, 정정까지 멈추면 이미 읽어 둔 지적이
        # 발행본에 반영되지 않은 채 남는다.
        wait = blocked_until(state)
        if wait:
            picks = []
        else:
            state.pop('blocked_until', None)   # 만료됐으면 필드를 지운다
            # 한도를 예약하기 **전에** 거른다. 뒤에서 거르면 하루 상한만 태우고 매일 같은 글에서 헛돈다.
            ready, dated = _period_ready(root, oid, _drop_misdated(root, todo + unavailable, errs),
                                         errs)
            picks = eligible(ready, published, state, day, have=_drafts_on_disk(root),
                             dated=dated)
        if not picks and not getattr(args, 'correct', False):
            # 남아 있는 섹션 오류는 그대로 둔다. 고를 것이 없다는 이유로 지우면, 한도만
            # 태우고 초안은 없는 상태가 「방금 성공」으로 보인다.
            return _save(root, state, errs, progressed=not wait)

        os.makedirs(os.path.join(root, DRAFTS), exist_ok=True)
        for item in picks:
            # 호출 **전에** 예약한다. 성공만 세면 한도를 태우고 실패한 호출이 매시
            # 되풀이되면서 사람 몫의 한도까지 먹는다.
            state = reserve(state, day, item.section)
            state['last_tick'] = now()
            save_state(root, state)

            style = getattr(args, 'correct', False)
            text, why, kind, raw = review_one(
                root, publish_commit(root, item.path, item.sha) or oid,
                item, args.timeout, style=style)
            if why:
                if kind == LIMIT:
                    # 공급자 한도는 **우리 예산을 쓴 게 아니다.** 되돌리지 않으면 초안
                    # 0 건인 채로 그날 자동 검토가 끝난다(2026-09-19 실측).
                    # 다만 무조건 되돌리면 하루 상한이 사라지므로 되돌린 횟수를 따로
                    # 세서 바닥을 둔다.
                    if may_release(state, day):
                        state = release(state, day, item.section)
                    state = note_limit(state, day)
                    when = retry_at(raw or why)
                    if when:
                        state['blocked_until'] = when
                    # 정정(Claude)이 시작되기 **전에** 디스크에 남긴다. 마지막 _save 까지
                    # 미루면 정정 중 강제 종료가 반납을 통째로 날린다.
                    save_state(root, state)
                # 한 편이 실패하면 그 tick 을 끝낸다. 한도 초과였다면 다음 섹션 호출은
                # 어차피 같은 이유로 죽고, 그 사이 사람 몫의 한도만 더 먹는다.
                errs[item.section] = err(kind, f'{item.path}: {why}')
                break
            # 문체 수정이 **푸시까지 끝났을 때만** 초안이 새 판의 이름을 받는다. 그 전에
            # 새 이름을 붙이면 푸시가 실패한 날 공개판(옛 SHA)과 초안이 어긋나 정정이 못 집는다.
            target = item
            if style and raw is not None and hasattr(raw, 'sha'):
                state = _note_style(state, item, raw)
                text = _style_note(raw) + text
                if raw.sha:
                    target = dataclasses.replace(item, sha=raw.sha)
            # 최종 이름은 성공한 뒤에만 붙는다 — 먼저 만들면 잘린 파일이 남고, 다음 tick 은
            # 「파일이 있다」는 이유로 그 글을 건너뛴다.
            fd, tmp = tempfile.mkstemp(dir=os.path.join(root, DRAFTS))
            with os.fdopen(fd, 'w', encoding='utf-8') as fh:
                fh.write(text)
            os.replace(tmp, os.path.join(root, DRAFTS, draft_name(target)))
            os.chmod(os.path.join(root, DRAFTS, draft_name(target)), 0o644)
            errs.pop(item.section, None)   # 이 섹션은 풀렸다
            print(f'초안 — [{item.section}] {item.path} @ {target.sha[:7]}')

        if getattr(args, 'correct', False):
            state = _correct_ready(root, args, state, errs)
        return _save(root, state, errs)
    except Exception as exc:  # noqa: BLE001
        # 예약은 이미 저장됐다. 여기서 조용히 빠져나가면 오늘 재시도도 막힌 채로 러너가
        # 꺼진 것처럼 굴고, 훅에는 아무 흔적이 없다.
        try:
            errs['러너'] = err(UNKNOWN, f'{type(exc).__name__}: {exc}')
            _save(root, state, errs)
        except Exception:  # noqa: BLE001
            print(f'[러너] 상태도 못 남겼다 — {type(exc).__name__}: {exc}')
        return 1
    finally:
        freshness.PINNED = None   # 고정은 이 tick 동안만 — 같은 프로세스의 다음 호출로 새지 않게
        lock.__exit__(None, None, None)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = ap.add_subparsers(dest='cmd', required=True)

    p = sub.add_parser('pending', help='미검토 발행본 목록')
    p.add_argument('--hook', action='store_true',
                   help='세션 시작 훅용 — 한 줄로, 볼 것이 없으면 침묵, 항상 exit 0')
    p.add_argument('--json', action='store_true')
    p.add_argument('--no-fetch', action='store_true', help='origin을 당기지 않는다')
    p.set_defaults(fn=cmd_pending)

    p = sub.add_parser('mark', help='검토 완료 기록')
    p.add_argument('path', help='예: posts/2026-08-22.html')
    p.add_argument('--findings', type=int, default=0, help='반영한 지적 건수')
    p.add_argument('--baseline', action='store_true',
                   help='읽지 않고 감시 범위에만 넣는다 (기존 파일을 편입할 때)')
    p.set_defaults(fn=cmd_mark)

    p = sub.add_parser('seed', help='도입 시 1회 — 현재 발행분을 기준선으로')
    p.add_argument('--force', action='store_true')
    p.set_defaults(fn=cmd_seed)

    p = sub.add_parser('refresh', help='조판만 바뀐 판을 동등으로 승인 (읽었다고 기록하지 않는다)')
    p.add_argument('--apply', action='store_true', help='실제로 원장에 쓴다')
    p.add_argument('--no-fetch', action='store_true')
    p.set_defaults(fn=cmd_refresh)

    p = sub.add_parser('run', help='launchd 러너 — codex 초안을 미리 만들어 둔다 (읽기만)')
    # 2026-10-11 문체 지시문(HTML 을 끝까지 읽고 잇기)부터 900초 타임아웃이 잇달았다 — 10/12 KR 4회,
    # 매번 하루 호출 한도를 한 칸씩 썼다.
    p.add_argument('--timeout', type=int, default=1800,
                   help='codex 한 편의 제한 시간(초)')
    p.add_argument('--correct', action='store_true',
                   help='준비된 us/kr 초안을 Claude가 검증·정정하고 재게시')
    p.add_argument('--correction-timeout', type=int, default=1800,
                   help='Claude 한 편의 제한 시간(초)')
    p.set_defaults(fn=cmd_run)


    args = ap.parse_args()
    if args.fn is cmd_run:
        # launchd·런처의 SIGTERM 을 SystemExit 로 바꾼다 — 기본 동작은 finally 없이 죽어서 잠금·
        # 고정 해제와 정정기 하위 프로세스 정리(corrector._status)가 건너뛰어진다(codex 구현 4차 #1).
        signal.signal(signal.SIGTERM, _terminate)
    return args.fn(args)


def _terminate(signum, _frame):
    # 두 번째 신호(런처가 넘긴 것과 launchd 가 그룹에 보낸 것)가 정리 도중 다시 끊지 않게 한다.
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    sys.exit(128 + signum)


if __name__ == '__main__':
    sys.exit(main())
