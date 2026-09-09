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

import argparse
import errno
import fcntl
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from review import prose as prose_mod  # noqa: E402
from review.queue import accept as accept_entry  # noqa: E402
from review.queue import baselines, classify, is_watched  # noqa: E402
from review.queue import mark as mark_entry  # noqa: E402
from review.queue import seed, union_pending  # noqa: E402
from review.runner import (DAILY_CAP, accept_draft,  # noqa: E402
                           draft_name, eligible, reserve, today_kst)

LEDGER = 'reviews/index.json'
LOCK = 'reviews/.index.lock'
DRAFTS = 'reviews/pending'
STATE = 'reviews/runner.json'
RUNNER_LOCK = 'reviews/.runner.lock'

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
        errs = state.get('errors')
        if isinstance(errs, dict) and errs:
            detail = '; '.join(f'{k} {str(v)[:120]}' for k, v in sorted(errs.items()))
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

MARKET_NAME = {'us': '미국', 'kr': '한국'}


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
    found = None
    for commit in out.stdout.split():
        if rev_parse(root, f'{commit}:{path}') == sha:
            found = commit
        elif found:
            break
    return found


def _wanted(name):
    return name.endswith(SNAPSHOT_SUFFIXES)


def snapshot(root, oid, paths, dest):
    """고정한 커밋에서 글과 근거 데이터를 꺼낸다.

    **한 커밋에서 둘을 함께 꺼내는 것이 요점이다.** 근거 데이터 파일은 날짜별이 아니라 한
    자리를 덮어쓰므로(2026-09-10 실측), 작업 폴더의 데이터로 밀린 글을 대조하면 거짓 지적이
    난다. 같은 커밋에서 나온 짝이면 「이 데이터가 이 글이 쓰인 데이터다」가 정의상 참이다.
    """
    out = git_bytes(root, 'archive', '--format=tar', oid, '--', *paths)
    if out.returncode:
        return False
    with tarfile.open(fileobj=io.BytesIO(out.stdout)) as tf:
        keep = [m for m in tf.getmembers() if m.isfile() and _wanted(m.name)]
        tf.extractall(dest, members=keep, filter='data')
    return True


def review_one(root, commit, item, timeout):
    """codex 를 읽기 전용으로 한 편 돌린다 — (초안 본문, 실패 이유)."""
    # 스냅샷 디렉터리는 git 레포가 아니다. `--skip-git-repo-check` 없이 부르면 codex 가
    # 「Not inside a trusted directory」로 거부한다 — 레포 안에서 손으로 돌릴 때는 안
    # 드러나고 launchd 첫 실행에서야 나왔다(2026-09-10).
    work = tempfile.mkdtemp(prefix='review-')
    try:
        data_dir = SNAPSHOT[item.section]
        if not snapshot(root, commit, (item.path, data_dir), work):
            return None, f'{commit[:7]} 에서 스냅샷을 못 꺼냈다'
        prompt = PROMPT.format(post=item.path,
                               market=MARKET_NAME.get(item.section, item.section),
                               datadir=data_dir)
        try:
            out = subprocess.run(
                [CODEX, 'exec', '--sandbox', 'read-only',
                 '--skip-git-repo-check', '-C', work, '-'],
                input=prompt, capture_output=True, text=True, timeout=timeout)
        except FileNotFoundError:
            return None, f'codex 가 없다 ({CODEX})'
        except subprocess.TimeoutExpired:
            return None, f'codex 가 {timeout}초 안에 안 끝났다'
        # 읽는 사이 그 글이 재발행되지 않았는지 **지금 공개된 판**에 다시 물어본다. 고정한
        # 커밋에 물으면 불변이라 늘 통과해서, 검사하는 시늉만 하게 된다.
        try_fetch(root)
        now_sha = rev_parse(root, f'origin/main:{item.path}')
        ok, why = accept_draft(out.returncode, out.stdout, now_sha or '', item.sha)
        if not ok:
            tail = (out.stdout or out.stderr or '').strip().splitlines()[-1:]
            return None, why + (f' — {tail[0][:200]}' if tail else '')
        return out.stdout, None
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _save(root, state, errs):
    """상태를 원자적으로 남긴다.

    오류는 **섹션별로** 들고 간다. 하나로 뭉치면 kr 성공이 앞선 us 실패를 덮어 지우고,
    한도는 이미 쓴 채 초안은 없는데 훅에는 「방금 성공」으로 보인다 — 조용한 실패다.
    각 섹션의 오류는 **그 섹션이 초안을 낼 때만** 풀린다.
    """
    state['errors'] = errs
    if not errs:
        state['last_ok'] = now()
    save_state(root, state)
    for where, why in sorted(errs.items()):
        print(f'[러너] {where}: {why}')
    return 1 if errs else 0


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
        errs['러너'] = '정정 전 fetch 실패'
        return state
    oid = rev_parse(root, 'origin/main')
    if not oid:
        raise ValueError('정정할 origin/main 이 없다')
    queue, published = _published_queue(root, oid)
    have = _drafts_on_disk(root)
    ready = [item for item in queue if draft_name(item) in have]
    day = today_kst()
    quota = {'calls': state.get('correction_calls', {})}
    for item in eligible(ready, published, quota, day):
        key = f'정정-{item.section}'
        commit = publish_commit(root, item.path, item.sha)
        if not commit:
            errs[key] = f'{item.path}: 발행 커밋을 찾지 못했다'
            break
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
        if why:
            errs[key] = f'{item.path}: {why}'
            break
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
            errs['러너'] = 'fetch 실패 — 공개판을 확인 못 했다'
            return _save(root, state, errs)
        oid = rev_parse(root, 'origin/main')
        if not oid:
            errs['러너'] = 'origin/main 을 못 찾았다'
            return _save(root, state, errs)

        todo, _typo, unavailable, _basis, _stale, _pub, _work = survey(
            root, want_fetch=False)
        # 큐 판정은 두 트리를 보지만 **자동으로 읽을 대상은 고정한 판만**이다. 가변
        # `origin/main` 을 다시 읽으면 tick 도중 재발행된 판을 고정판인 양 집는다.
        published = tree_at(root, oid) or {}
        if getattr(args, 'correct', False):
            todo, published = _published_queue(root, oid)
            unavailable = []
        day = today_kst()
        picks = eligible(todo + unavailable, published, state, day,
                         have=_drafts_on_disk(root))
        if not picks and not getattr(args, 'correct', False):
            # 남아 있는 섹션 오류는 그대로 둔다. 고를 것이 없다는 이유로 지우면, 한도만
            # 태우고 초안은 없는 상태가 「방금 성공」으로 보인다.
            return _save(root, state, errs)

        os.makedirs(os.path.join(root, DRAFTS), exist_ok=True)
        for item in picks:
            # 호출 **전에** 예약한다. 성공만 세면 한도를 태우고 실패한 호출이 매시
            # 되풀이되면서 사람 몫의 한도까지 먹는다.
            state = reserve(state, day, item.section)
            state['last_tick'] = now()
            save_state(root, state)

            text, why = review_one(root,
                                   publish_commit(root, item.path, item.sha) or oid,
                                   item, args.timeout)
            if why:
                # 한 편이 실패하면 그 tick 을 끝낸다. 한도 초과였다면 다음 섹션 호출은
                # 어차피 같은 이유로 죽고, 그 사이 사람 몫의 한도만 더 먹는다.
                errs[item.section] = f'{item.path}: {why}'
                return _save(root, state, errs)
            # 최종 이름은 성공한 뒤에만 붙는다 — 먼저 만들면 잘린 파일이 남고, 다음 tick 은
            # 「파일이 있다」는 이유로 그 글을 건너뛴다.
            fd, tmp = tempfile.mkstemp(dir=os.path.join(root, DRAFTS))
            with os.fdopen(fd, 'w', encoding='utf-8') as fh:
                fh.write(text)
            os.replace(tmp, os.path.join(root, DRAFTS, draft_name(item)))
            os.chmod(os.path.join(root, DRAFTS, draft_name(item)), 0o644)
            errs.pop(item.section, None)   # 이 섹션은 풀렸다
            print(f'초안 — [{item.section}] {item.path} @ {item.sha[:7]}')

        if getattr(args, 'correct', False):
            state = _correct_ready(root, args, state, errs)
        return _save(root, state, errs)
    except Exception as exc:  # noqa: BLE001
        # 예약은 이미 저장됐다. 여기서 조용히 빠져나가면 오늘 재시도도 막힌 채로 러너가
        # 꺼진 것처럼 굴고, 훅에는 아무 흔적이 없다.
        try:
            errs['러너'] = f'{type(exc).__name__}: {exc}'
            _save(root, state, errs)
        except Exception:  # noqa: BLE001
            print(f'[러너] 상태도 못 남겼다 — {type(exc).__name__}: {exc}')
        return 1
    finally:
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
    p.add_argument('--timeout', type=int, default=900,
                   help='codex 한 편의 제한 시간(초)')
    p.add_argument('--correct', action='store_true',
                   help='준비된 us/kr 초안을 Claude가 검증·정정하고 재게시')
    p.add_argument('--correction-timeout', type=int, default=1800,
                   help='Claude 한 편의 제한 시간(초)')
    p.set_defaults(fn=cmd_run)


    args = ap.parse_args()
    return args.fn(args)


if __name__ == '__main__':
    sys.exit(main())
