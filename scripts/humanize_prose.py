#!/usr/bin/env python3
"""산문만 꺼내 주고, 윤문된 것을 제자리에 돌려놓는다 (STEP 2.5).

  python3 scripts/humanize_prose.py extract  X.humanizing.html
  #  → prose_in.txt (스킬에 넘길 것) + prose_map.json (사이드카)

  python3 scripts/humanize_prose.py reinsert X.humanizing.html --payload _workspace/{run_id}/final.md
  #  → 전부 맞을 때만 X.humanizing.html 을 덮어쓴다. 어긋나면 아무것도 안 쓰고 exit 1.

되꽂기는 문단을 세지 않고 **이름으로** 맞춘다. 이름이 빠지거나·겹치거나·모르는 이름이
오거나, 인라인 태그가 사라지거나, 그 문단의 숫자가 하나라도 달라지면 통째로 거부한다.
거부되면 사본을 버리고 윤문을 포기하면 된다 — 원본은 애초에 손대지 않았다.
"""

import argparse
import json
import os
import shlex
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from us.prose_swap import ProseSwapError, extract, reinsert  # noqa: E402


def _read(path):
    with open(path, encoding='utf-8') as fh:
        return fh.read()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('mode', choices=['extract', 'reinsert', 'finalize'])
    ap.add_argument('html', help='작업 사본 (원본이 아니라 *.humanizing.html)')
    ap.add_argument('--out', default='prose_in.txt', help='extract: 스킬에 넘길 텍스트')
    ap.add_argument('--sidecar', default='prose_map.json')
    ap.add_argument('--payload', help='reinsert/finalize: 고친 prose_in.txt 또는 스킬의 final.md')
    ap.add_argument('--original', help='finalize: 교체 대상 원본')
    ap.add_argument('--gate', action='append', default=[],
                    help='finalize: 통과해야 할 검사. {f}가 사본 경로로 치환된다. 여러 번 쓸 수 있다')
    args = ap.parse_args(argv)

    if args.mode == 'finalize':
        # 아무것도 건드리기 전에 본다 — 잘못된 호출이 사본을 먼저 고쳐 놓는 일이 없게.
        if not args.original:
            ap.error('finalize 에는 --original 이 필요하다')
        if os.path.abspath(args.original) == os.path.abspath(args.html):
            ap.error('사본과 원본이 같은 파일이다 — 검사가 실패하면 원본을 지우게 된다')
        if not args.gate:
            ap.error('finalize 에는 --gate 가 최소 하나 필요하다 — '
                     '게이트 없이 원본을 교체하는 경로를 두지 않는다')

    html = _read(args.html)

    if args.mode == 'extract':
        text, sidecar = extract(html)
        with open(args.out, 'w', encoding='utf-8') as fh:
            fh.write(text)
        with open(args.sidecar, 'w', encoding='utf-8') as fh:
            json.dump(sidecar, fh, ensure_ascii=False, indent=1)
        print('산문 %d문단 → %s (사이드카 %s)' % (len(sidecar['items']), args.out, args.sidecar))
        return 0

    if not args.payload:
        ap.error('%s 에는 --payload 가 필요하다' % args.mode)
    try:
        out = reinsert(html, _read(args.payload), json.loads(_read(args.sidecar)))
    except ProseSwapError as exc:
        return _give_up('되꽂기 거부 — %s' % exc, args)
    _write_atomic(args.html, out)
    print('되꽂기 완료 — %s' % args.html)

    if args.mode == 'reinsert':
        return 0

    # finalize — 검사를 전부 통과했을 때만 원본을 교체한다. 맨손 mv를 남기지 않는 것이
    # 이 모드의 존재 이유다: 사람이든 에이전트든 검사를 건너뛰고 교체할 자리가 없어야 한다.
    _diff(_read(args.original), out)
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for raw in args.gate:
        argv = [w.replace('{f}', os.path.abspath(args.html)) for w in shlex.split(raw)]
        print('· %s' % ' '.join(argv))
        if subprocess.call(argv, cwd=root) != 0:
            return _give_up('검사 실패 — %s' % ' '.join(argv), args)
    os.replace(args.html, args.original)
    print('통과. 원본을 교체했다 — %s' % args.original)
    return 0


def _write_atomic(path, text):
    d = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=d, suffix='.part')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _give_up(reason, args):
    print(reason, file=sys.stderr)
    if args.mode == 'finalize' and os.path.exists(args.html):
        os.unlink(args.html)
        print('사본을 버렸다. 원본은 처음부터 수정되지 않았다.', file=sys.stderr)
    else:
        print('사본을 버리고 윤문을 포기한다. 원본은 그대로다.', file=sys.stderr)
    return 1


def _diff(before, after):
    """바뀐 문단만 나란히 찍는다.

    숫자·태그·자리표는 기계가 본다. 기관 이름이 바뀌거나 출처가 지워지거나 판단의
    방향이 뒤집힌 것은 사람만 볼 수 있고, 그건 이 출력을 읽는 순간에만 잡힌다.
    """
    from us.prose_swap import _plain, extract as _ex
    a = {k: _plain(v['inner']) for k, v in _ex(before)[1]['items'].items()}
    b = {k: _plain(v['inner']) for k, v in _ex(after)[1]['items'].items()}
    import difflib
    changed = [k for k in a if a.get(k) != b.get(k)]
    print('\n── 바뀐 문단 %d/%d — 고유명사·출처·판단 방향이 그대로인지 눈으로 본다 ──'
          % (len(changed), len(a)))
    for k in changed:
        old = [x + '.' for x in a[k].split('. ')]
        new = [x + '.' for x in b.get(k, '').split('. ')]
        print('  [%s]' % k)
        for line in difflib.unified_diff(old, new, lineterm='', n=0):
            if line.startswith(('---', '+++', '@@')):
                continue
            if line.startswith(('+', '-')):
                print('    %s %s' % (line[0], line[1:].strip()))  # 자르지 않는다 — 바뀐 데가 뒤에 있을 수 있다
        print('')
    print('──\n')


if __name__ == '__main__':
    sys.exit(main())
