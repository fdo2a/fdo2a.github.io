"""러너는 origin/main 과 같은 코드로만 공개판을 읽고 고친다 (2026-10-10).

러너(launchd)는 사람이 쓰는 site/ 작업 폴더의 코드를 그대로 import 한다. 10/03 에 그 폴더에
staged 로 남은 미완성 작업 때문에 아무도 pull 을 못 했고, 러너는 10/10 까지 81커밋 뒤의
코드로 공개판을 고쳐 푸시했다 — check_fund 게이트가 없는 문체 단계였고, 경보는 없었다.

자동 pull 은 하지 않는다. 공유 폴더에서는 확인과 ff 사이에 사람이 브랜치를 바꾸거나 파일을
고칠 수 있어 「사람 작업을 움직이지 않는다」를 보장할 수 없다(codex 설계 검토 #2·#5).
다르면 멈추고 알린다. 맞추는 것은 사람의 일이다.

stdlib 만 쓴다 — 레포 모듈 import 가 깨진 상태에서도 돌아야 한다.

설계: docs/superpowers/specs/2026-10-10-runner-code-freshness.md
"""
import subprocess

KEY = '러너-코드'
# 러너가 실행하거나 프롬프트로 읽는 레포 안 코드·규칙(정정 프롬프트가 REVIEW_GATE.md 를 로컬에서
# 읽는다 — symlink 와 대상 둘 다, codex #3). STYLE_EXEMPLARS 는 origin/main 에서
# 직접 꺼내 읽으므로 빠진다. HUMANIZE_RULES 는 레포 밖이라 대상이 아니다.
CODE_PATHS = ('scripts', '.claude/skills/review-gate', '.claude/REVIEW_GATE.md')


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


def check(root, upstream='origin/main'):
    """→ 멈출 이유(str) 또는 None. fetch 는 호출자가 먼저 한다."""
    code, branch = _git(root, 'symbolic-ref', '--quiet', '--short', 'HEAD')
    if code:
        return 'site/ 가 분리된 HEAD 다 — main 을 체크아웃해야 한다'
    if branch != 'main':
        return f'site/ 가 main 이 아니라 {branch} 브랜치다'
    code, head = _git(root, 'rev-parse', 'HEAD')
    code2, up = _git(root, 'rev-parse', '--verify', '--quiet', upstream)
    if code or code2 or not up:
        return f'HEAD 나 {upstream} 을 못 읽었다'
    if head != up:
        _, behind = _git(root, 'rev-list', '--count', f'HEAD..{upstream}')
        _, ahead = _git(root, 'rev-list', '--count', f'{upstream}..HEAD')
        return (f'site/ main 이 {upstream} 보다 {behind}커밋 뒤, {ahead}커밋 앞이다 '
                f'— pull(또는 푸시)로 맞춰야 한다')
    # 추적 파일의 staged·unstaged 변경, 그리고 scripts/ 아래 미추적 파일(미추적 json.py 가
    # 표준 모듈을 가린다 — codex #4). 무시 목록(__pycache__)은 git 이 이미 뺀다.
    code, dirty = _git(root, 'status', '--porcelain', '--untracked-files=all', '--', *CODE_PATHS, raw=True)
    if code:
        return 'git status 를 못 읽었다'
    if dirty:
        first = dirty.splitlines()
        more = f' 외 {len(first) - 3}개' if len(first) > 3 else ''
        return ('커밋 안 된 코드 변경 — ' + ', '.join(line[3:] for line in first[:3]) + more)
    return None


# tick 을 시작할 때 고정한 코드 — 프로세스가 import 한 판. tick 도중 사람이 site/ 를 pull 해도
# 이미 import 한 코드는 그대로이므로, 비교 기준은 그때의 HEAD 가 아니라 이것이다.
PINNED = None


def pin(root):
    global PINNED
    PINNED = trees(root, 'HEAD')
    return PINNED


def moved(root, other, ref='HEAD'):
    """`other` 레포의 `ref` 코드가 이 프로세스가 돌리는 코드와 다르면 그 이유.

    tick 을 시작할 때 맞았어도 codex 가 도는 사이 origin 에 게이트를 바꾼 커밋이 올라올 수
    있다. 그 판을 clone 해 옛 게이트로 검사하고 밀면 안 된다(codex #1). 글·데이터만 바뀐
    커밋은 통과한다.
    """
    mine, theirs = PINNED or trees(root, 'HEAD'), trees(other, ref)
    diff = [p for p in CODE_PATHS if mine[p] != theirs[p]]
    if diff:
        return f'tick 도중 origin 의 코드가 바뀌었다({", ".join(diff)}) — 다음 tick 에 새 코드로 다시 한다'
    return None
