"""러너는 origin/main 과 같은 코드로만 공개판을 읽고 고친다 (2026-10-10).

러너(launchd)는 사람이 쓰는 site/ 작업 폴더의 코드를 그대로 import 한다. 10/03 에 그 폴더에
staged 로 남은 미완성 작업 때문에 아무도 pull 을 못 했고, 러너는 10/10 까지 81커밋 뒤의
코드로 공개판을 고쳐 푸시했다 — check_fund 게이트가 없는 문체 단계였고, 경보는 없었다.

- 뒤처지기만 했고 작업 폴더의 추적 파일이 하나도 안 바뀌었으면 **따라잡고 그 tick 은 쉰다.**
  이미 import 한 코드는 옛 판이므로 새 코드로 도는 것은 다음 tick 이다(재실행은 하지 않는다).
- 그 밖에 다르면(다른 브랜치, 앞선 커밋, 코드 변경, 미추적 모듈) **멈추고 알린다.** 사람의
  작업을 움직이지 않는다는 원칙을 지킨다(codex 설계 검토 #2).

stdlib 만 쓴다 — 레포 모듈 import 가 깨진 상태에서도 돌아야 한다.

설계: docs/superpowers/specs/2026-10-10-runner-code-freshness.md
"""
import subprocess

KEY = '러너-코드'
DRIFT = 'tick 도중 origin 의 코드가 바뀌었다'   # 재시도성 실패의 표지 — 정정 회차로 세지 않는다
# 러너가 실행하거나 프롬프트로 읽는 레포 안 코드·규칙(정정 프롬프트가 REVIEW_GATE.md 를 읽는다 —
# symlink 와 대상 둘 다, codex #3). STYLE_EXEMPLARS 는 origin/main 에서 직접 꺼내 읽으므로
# 빠진다. HUMANIZE_RULES 는 레포 밖이라 대상이 아니다.
CODE_PATHS = ('scripts', '.claude/skills/review-gate', '.claude/REVIEW_GATE.md')

OK, BEHIND, STALE = 'ok', 'behind', 'stale'


def _git(root, *args, raw=False):
    p = subprocess.run(['git', '-C', root, *args], capture_output=True, text=True, timeout=60)
    # porcelain 은 첫 칸이 공백일 수 있다(` M 파일`) — 앞을 자르면 경로가 깨진다.
    return p.returncode, (p.stdout.rstrip('\n') if raw else p.stdout.strip())


def trees(root, ref):
    """{경로: tree sha 또는 None} — 비교의 단위. 없는 경로는 None 으로 같이 센다."""
    out = {}
    for path in CODE_PATHS:
        code, sha = _git(root, 'rev-parse', '--verify', '--quiet', f'{ref}:{path}')
        out[path] = sha if code == 0 and sha else None
    return out


def _dirty(root, *paths, untracked='all'):
    code, out = _git(root, 'status', '--porcelain', f'--untracked-files={untracked}',
                     '--', *paths, raw=True)
    if code:
        return None
    return [line[3:] for line in out.splitlines() if line.strip()]


def _listed(paths):
    more = f' 외 {len(paths) - 3}개' if len(paths) > 3 else ''
    return ', '.join(paths[:3]) + more


def status(root, upstream='origin/main'):
    """→ (OK | BEHIND | STALE, 이유). fetch 는 호출자가 먼저 한다."""
    code, branch = _git(root, 'symbolic-ref', '--quiet', '--short', 'HEAD')
    if code:
        return STALE, 'site/ 가 분리된 HEAD 다 — main 을 체크아웃해야 한다'
    if branch != 'main':
        return STALE, f'site/ 가 main 이 아니라 {branch} 브랜치다'
    code, head = _git(root, 'rev-parse', 'HEAD')
    code2, up = _git(root, 'rev-parse', '--verify', '--quiet', upstream)
    if code or code2 or not up:
        return STALE, f'HEAD 나 {upstream} 을 못 읽었다'
    # 코드 변경이 먼저다 — 뒤처졌어도 고치는 중인 코드가 있으면 따라잡지 않는다.
    # 미추적 scripts/json.py 는 표준 json 을 가린다(codex #4). 무시 목록은 git 이 이미 뺀다.
    dirty = _dirty(root, *CODE_PATHS)
    if dirty is None:
        return STALE, 'git status 를 못 읽었다'
    if dirty:
        return STALE, '커밋 안 된 코드 변경 — ' + _listed(dirty)
    if head == up:
        return OK, ''
    _, behind = _git(root, 'rev-list', '--count', f'HEAD..{upstream}')
    _, ahead = _git(root, 'rev-list', '--count', f'{upstream}..HEAD')
    where = f'site/ main 이 {upstream} 보다 {behind}커밋 뒤, {ahead}커밋 앞이다'
    if ahead != '0':
        return STALE, where + ' — origin 에 없는 커밋은 사람이 푸시하거나 정리해야 한다'
    return BEHIND, where


def check(root, upstream='origin/main'):
    """맞지 않는 이유(str) 또는 None — 뒤처짐도 이유다. 따라잡기는 `catch_up`."""
    kind, why = status(root, upstream)
    return None if kind == OK else why


def catch_up(root, upstream='origin/main'):
    """뒤처지기만 했을 때 fast-forward → 못 한 이유(str) 또는 None(따라잡았다).

    추적 파일이 **하나라도** 바뀌어 있으면 하지 않는다 — 사람이 손대는 중인 폴더다. 훅·
    autoStash·무시 파일 덮어쓰기를 끄고(codex #5), 직전에 브랜치를 한 번 더 확인한다.
    실패해도 아무것도 되돌리지 않는다 — ff 가 거부되면 작업 폴더는 그대로다.
    """
    dirty = _dirty(root, '.', untracked='no')
    if dirty is None:
        return 'git status 를 못 읽었다'
    if dirty:
        return '뒤처졌는데 작업 폴더에 커밋 안 된 변경이 있어 따라잡지 않았다 — ' + _listed(dirty)
    code, branch = _git(root, 'symbolic-ref', '--quiet', '--short', 'HEAD')
    if code or branch != 'main':
        return '따라잡기 직전에 브랜치가 바뀌었다'
    p = subprocess.run(['git', '-C', root, '-c', 'core.hooksPath=/dev/null',
                        'merge', '--ff-only', '--no-autostash', '--no-overwrite-ignore',
                        '--quiet', upstream], capture_output=True, text=True, timeout=120)
    if p.returncode:
        return 'ff 실패 — ' + (p.stderr or p.stdout).strip()[-300:]
    _, head = _git(root, 'rev-parse', 'HEAD')
    _, up = _git(root, 'rev-parse', upstream)
    return None if head == up else 'ff 뒤에도 HEAD 가 origin/main 과 다르다'


# 이 프로세스가 import 한 코드. `boot()` 은 레포 모듈을 import 하기 **전에** 부른다 — import 와
# 첫 검사 사이에 사람이 pull 하면, 검사 때의 HEAD 는 import 한 코드가 아니다(codex 구현 검토 #1).
BOOT = None
# tick 동안의 비교 기준. tick 이 시작될 때 BOOT 와 같음을 확인하고 넣는다.
PINNED = None


def boot(root):
    global BOOT
    BOOT = trees(root, 'HEAD')
    return BOOT


def pin(root):
    """tick 시작 — 지금 HEAD 가 import 한 코드(BOOT)와 같으면 고정하고 None, 아니면 이유."""
    global PINNED
    now = trees(root, 'HEAD')
    if BOOT is not None and now != BOOT:
        return '러너가 코드를 읽은 뒤 site/ 가 바뀌었다 — 다음 tick 에 새 코드로 다시 한다'
    PINNED = now
    return None


def moved(root, other, ref='HEAD'):
    """`other` 레포의 `ref` 코드가 이 프로세스가 돌리는 코드와 다르면 그 이유.

    tick 을 시작할 때 맞았어도 codex 가 도는 사이 origin 에 게이트를 바꾼 커밋이 올라올 수
    있다. 그 판을 clone 해 옛 게이트로 검사하고 밀면 안 된다(codex #1). 글·데이터만 바뀐
    커밋은 통과한다.
    """
    mine, theirs = PINNED or BOOT or trees(root, 'HEAD'), trees(other, ref)
    diff = [p for p in CODE_PATHS if mine[p] != theirs[p]]
    if diff:
        return f'{DRIFT}({", ".join(diff)}) — 다음 tick 에 새 코드로 다시 한다'
    return None
