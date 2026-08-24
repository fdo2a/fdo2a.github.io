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
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from review.queue import is_watched, mark as mark_entry  # noqa: E402
from review.queue import pending, seed, union_pending  # noqa: E402

LEDGER = 'reviews/index.json'
FETCH_TIMEOUT_SEC = 10


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


def hash_object(root, path):
    out = git(root, 'hash-object', '--', path)
    return out.stdout.strip() if out.returncode == 0 else None


def working_tree(root, base, ref):
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
        sha = hash_object(root, path)
        if sha:
            tree[path] = sha
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
    """(발행된 판, 작업 폴더 판, 기준 설명, 낡았는지). 한 번만 훑는다."""
    fetched = try_fetch(root) if want_fetch else None
    published = tree_at(root, 'origin/main')
    ref = 'origin/main'
    if published is None:
        ref, published = 'HEAD', (tree_at(root, 'HEAD') or {})
    work = working_tree(root, published, ref)

    stale = ref == 'origin/main' and fetched is False
    if ref == 'HEAD':
        basis, stale = 'HEAD + 작업 폴더 (origin을 모른다)', True
    elif fetched:
        basis = 'origin/main + 작업 폴더'
    else:
        basis = ('origin/main 캐시(fetch 실패) + 작업 폴더' if stale
                 else 'origin/main 캐시(조회 안 함) + 작업 폴더')

    return published, work, basis, stale


def survey(root, want_fetch):
    """(미검토 목록, 기준 설명, 낡았는지) — 발행된 판과 작업 폴더를 둘 다 본다."""
    published, work, basis, stale = trees(root, want_fetch)
    ledger = load_ledger(root)
    todo = union_pending(pending(ledger, published), pending(ledger, work))
    return todo, basis, stale


STALE_NOTE = '지금 본 판이 최신이 아닐 수 있다'


def cmd_pending(args):
    try:
        root = repo_root()
        todo, basis, stale = survey(root, want_fetch=not args.no_fetch)
    except Exception as exc:  # noqa: BLE001 — 훅에서 조용히 죽는 것이 최악이다
        msg = f'[검토 게이트] 확인 실패 — {type(exc).__name__}: {exc}'
        print(msg)
        return 0 if args.hook else 1

    if args.json:
        print(json.dumps({'basis': basis, 'stale': stale,
                          'pending': [p.__dict__ for p in todo]}, ensure_ascii=False))
        return 0 if (args.hook or not todo) else 1

    if args.hook:
        if todo:
            items = ', '.join(f'{p.path}({p.reason})' for p in todo[:5])
            more = f' 외 {len(todo) - 5}건' if len(todo) > 5 else ''
            print(f'[검토 게이트] codex 미검토 발행본 {len(todo)}건 — {items}{more}. '
                  f'기준 {basis}. 절차는 .claude/REVIEW_GATE.md.')
        elif stale:
            print(f'[검토 게이트] 미검토 없음 — 단 {STALE_NOTE} (기준 {basis}).')
        return 0

    if not todo:
        print(f'미검토 없음 (기준 {basis})' + (f' — {STALE_NOTE}' if stale else ''))
        return 0
    print(f'미검토 {len(todo)}건 (기준 {basis})' + (f' — {STALE_NOTE}' if stale else ''))
    for p in todo:
        print(f'  - [{p.section}] {p.path} — {p.reason}')
    return 1


def cmd_mark(args):
    root = repo_root()
    path = rel_path(root, args.path)
    if not os.path.exists(os.path.join(root, path)):
        sys.exit(f'그런 파일이 없다: {path}')
    sha = hash_object(root, path)
    if not sha:
        sys.exit(f'sha를 못 구했다: {path}')
    try:
        ledger = mark_entry(load_ledger(root), path, sha, at=now(),
                            findings=args.findings)
        if args.baseline:
            ledger['reviewed'][path]['baseline'] = True
    except ValueError as exc:
        sys.exit(str(exc))
    save_ledger(root, ledger)
    kind = '범위 편입(읽지 않음)' if args.baseline else f'지적 {args.findings}건'
    print(f'검토 기록 — {path} @ {sha[:12]} ({kind})')
    return 0


def cmd_seed(args):
    root = repo_root()
    published, work, basis, _ = trees(root, want_fetch=False)
    # 발행된 판과 작업 폴더 판을 모두 기준선에 넣는다. 원격에만 있는 파일이 빠지면 그
    # 파일은 도입 첫날부터 미검토로 뜬다.
    tree = {**published, **work}

    ledger = load_ledger(root)
    if ledger.get('reviewed') and not args.force:
        sys.exit(f'원장이 이미 있다 ({len(ledger["reviewed"])}건). 덮어쓰려면 --force.')
    if args.force and ledger.get('reviewed'):
        print('  (--force — 실제로 읽지 않은 글도 「본 것」으로 남는다)')
    fresh = seed(tree, at=now())
    save_ledger(root, fresh)
    print(f'기준선 {len(fresh["reviewed"])}건 기록 (기준 {basis}) — '
          f'이후 발행·수정분부터 큐에 들어온다.')
    return 0


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

    args = ap.parse_args()
    return args.fn(args)


if __name__ == '__main__':
    sys.exit(main())
