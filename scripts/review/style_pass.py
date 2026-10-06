"""발행 뒤 codex 문체 수정 — 루틴 STEP 2.5(Claude 윤문)를 대신한다 (2026-09-27 사용자 지시).

클라우드 루틴에는 codex 가 없어서, 문체 수정은 발행 **뒤에** 로컬 러너가 한다. 경계는 이렇다.

- codex 는 발행 커밋 스냅샷 안의 `prose_in.txt` **만** 고친다. HTML 을 만지지 않으므로 표·캡션·
  에디터 노트·연준 인용은 애초에 넘어가지 않는다 — STEP 2.5 의 `extract()` 를 그대로 쓴다.
- 되꽂기(`prose_swap.reinsert_partial` — 문단마다 숫자와 그 순서·영문 이름·판단 어휘·방향어·
  부정어·아는 한글 이름·링크·닮은 정도, 기대값은 공개판에서 새로 뽑는다)와
  게이트, 커밋·푸시는 Python 이 새 clone 에서 한다. codex 는 최신 데이터를 보지 않는다.
  **걸린 문단만 원문으로 두고 나머지는 반영한다** — 한 문단(닮은 정도 0.79)이 전체를 버리게
  하던 조건은 사용자 지시로 없앴다(2026-09-27).
- 원본에서 이미 실패하던 게이트는 **출력이 같을 때만** 봐준다. 이름만 맞대면 다른 이유의 새
  실패가 그 이름 밑으로 숨는다.
- 원장 표시는 하지 않는다. 「지적 없음」도 Claude 정정 단계가 확인한 뒤 기록한다
  (`.claude/REVIEW_GATE.md`, 2026-09-10 사용자 지시). 푸시가 끝나면 초안이 새 판 이름을 받는다.
- 문체 커밋은 트레일러를 단다. `publish_commit()` 은 트레일러 + 태그 구조·수치 불변인 커밋을
  건너뛰어, 뒤따르는 사실 정정이 원래 발행 커밋의 데이터를 근거로 쓰게 한다.

설계: docs/superpowers/specs/2026-09-27-post-publish-codex-style-pass.md
"""

import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from review import kinds  # noqa: E402
from us.post_check import markup_diff, token_diff  # noqa: E402
from us.prose_swap import ProseSwapError, extract, reinsert_partial  # noqa: E402

TRAILER = 'Style-Pass: codex'
_DEFS = 'scripts/review/style_pass.py'   # 게이트 목록의 정의
PAYLOAD = 'prose_in.txt'
UNCHANGED = '고칠 문장이 없었다'
_CYCLE = re.compile(r'data-research-cycle="([^"]+)"')
_DATE = re.compile(r'(\d{4}-\d{2}-\d{2})\.html$')
_TRAILER_RE = re.compile(r'^Style-Pass: codex ([0-9a-f]{7,40})$')
# 근거 데이터에서 이름으로 읽을 키 — 종목·ETF·지수 이름뿐. label·theme 같은 키는 「지수」「보합」
# 같은 일반어를 섞어 정상 윤문을 거부했다(2026-09-30 재검토).
_NAME_KEYS = {'name', 'members', 'item_name', 'stock'}
_NAME_RE = re.compile(r'[가-힣A-Za-z0-9&·. ]{2,24}')
# 데이터 행의 첫 칸만 — `<th>` 제목 칸(지수·섹터·만기)은 이름이 아니다.
_ROW_HEAD = re.compile(r'<tr\b[^>]*>\s*<td\b[^>]*>(.*?)</td>', re.S)
_TAG = re.compile(r'<[^>]+>')


@dataclass
class Result:
    sha: str = None        # 푸시된 새 blob — None 이면 아무것도 안 나갔다
    reason: str = None     # 안 나간 이유
    skipped: tuple = ()    # 검사에 걸려 원문으로 둔 문단 [(이름, 이유)]


def prepare(workdir, html):
    """codex 에 넘길 문단을 스냅샷에 둔다 → 원래 텍스트(무편집 판별용).

    사이드카는 두지 않는다 — codex 가 쓸 수 있는 자리의 기대값은 믿을 수 없다. 되꽂을 때
    공개판에서 새로 뽑는다.
    """
    text, _ = extract(html)
    Path(workdir, PAYLOAD).write_text(text, encoding='utf-8')
    return text


def is_style_commit(message, parent_blob=None):
    """메시지의 **마지막 줄**이 트레일러이고, `parent_blob` 을 주면 트레일러가 그 blob 을 가리킨다.

    본문 어딘가에 같은 문구로 시작하는 줄만 있어도 인정하던 것을 좁혔다(2026-09-30 검토).
    """
    lines = [line.strip() for line in (message or '').splitlines() if line.strip()]
    m = _TRAILER_RE.match(lines[-1]) if lines else None
    if not m:
        return False
    return parent_blob is None or parent_blob.startswith(m.group(1))


def known_names(html, datadir):
    """문단에서 바뀌면 안 되는 이름 — 근거 데이터의 이름 필드와 글의 표 행 머리.

    한글 이름(삼성전자·반도체)은 영문 이름 검사에 안 걸린다. 여기 없는 이름은 여전히
    닮은 정도 검사에만 기댄다.
    """
    out = set()

    def walk(node, key=None):
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, k)
        elif isinstance(node, list):
            for v in node:
                walk(v, key)
        elif isinstance(node, str) and key in _NAME_KEYS:
            add(node)

    def add(text):
        text = ' '.join(text.split())
        # 한 글자(금)는 「금리」「지금」 안에서도 세어진다.
        if _NAME_RE.fullmatch(text) and len(text.replace(' ', '')) >= 2 \
                and re.search(r'[가-힣A-Za-z]', text):
            out.add(text)

    if datadir and os.path.isdir(datadir):
        for name in sorted(os.listdir(datadir)):
            if not name.endswith('.json'):
                continue
            try:
                with open(os.path.join(datadir, name), encoding='utf-8') as fh:
                    walk(json.load(fh))
            except (OSError, ValueError):
                continue
    for cell in _ROW_HEAD.findall(html):
        add(_TAG.sub('', cell).replace('&amp;', '&'))
    return tuple(sorted(out))


def same_skeleton(before, after):
    """태그 구조·게이트 표식·수치·티커가 그대로인가 — 트레일러를 믿어도 되는지 본다."""
    diff = token_diff(before, after)
    return not markup_diff(before, after) and not diff['added'] and not diff['removed']


def gate_commands(section, post, datadir, original, date, cycle, research_root=None):
    """STEP 2.5 finalize 의 게이트 목록 그대로 (.claude/ORCHESTRATOR.md·KR_ORCHESTRATOR.md).

    `datadir`·`research_root` 는 발행 커밋에서 꺼낸 근거다. 연구 원장 게이트는 글에 cycle 이
    박혀 있고 그 커밋에 원장이 있을 때만 — 연구 워크플로 이전 글에는 없다. 매크로 게이트의
    `--next` 는 정정기와 같이 근거의 `macro.json` 이다(루틴 작업 폴더의 macro_next.json 은
    레포에 없다).
    """
    py = sys.executable
    s = 'scripts/'
    if section in kinds.PERIOD:
        return _period_gates(section, post, datadir, original, date)
    head = [[py, s + 'check_style.py', post],
            [py, s + 'check_readability.py', '--strict', '--no-inline-images', post]]
    if section == 'us':
        cmds = head + [
            [py, s + 'verify_post.py', post, '--before', original, '--skip-layout'],
            [py, s + 'check_macro.py', '--html', post, '--datadir', datadir,
             '--next', os.path.join(datadir, 'macro.json')],
            [py, s + 'check_price_context.py', '--html', post, '--datadir', datadir],
            [py, s + 'check_session.py', '--html', post, '--datadir', datadir, '--market', 'us'],
            [py, s + 'check_weight.py', '--html', post, '--datadir', datadir, '--market', 'us'],
            [py, s + 'check_fed.py', '--html', post, '--datadir', datadir],
            [py, s + 'check_sources.py', '--html', post, '--datadir', datadir],
            [py, s + 'check_calendar.py', '--html', post, '--datadir', datadir],
            [py, s + 'check_movers.py', '--html', post, '--datadir', datadir],
            [py, s + 'check_fund.py', '--html', post, '--datadir', datadir, '--market', 'us',
             '--date', date],
        ]
        market = 'us'
    else:
        cmds = head + [
            [py, s + 'check_session.py', '--html', post, '--datadir', datadir, '--market', 'kr'],
            [py, s + 'check_weight.py', '--html', post, '--datadir', datadir, '--market', 'kr'],
            [py, s + 'check_kr_stance.py', '--html', post, '--datadir', datadir,
             '--next', os.path.join(datadir, 'kr_stance.json')],   # STEP 2.9 가 옮겨 둔 자리
            [py, s + 'check_news.py', '--html', post, '--datadir', datadir, '--market', 'kr',
             '--date', date],
            [py, s + 'check_movers.py', '--html', post, '--datadir', datadir, '--market', 'kr'],
            [py, s + 'check_fund.py', '--html', post, '--datadir', datadir, '--market', 'kr',
             '--date', date],
            [py, s + 'verify_post.py', post, '--before', original, '--skip-layout'],
        ]
        market = 'kr'
    if cycle and research_root:
        cmds.append([py, s + 'check_research.py', 'check', '--span', 'daily', '--html', post,
                     '--root', research_root, '--market', market, '--date', date,
                     '--cycle', cycle])
    return cmds


def _period_gates(section, post, root, original, key):
    """주간·월간·일본 — 루틴 STEP 4-b·일본 STEP 3 의 게이트 그대로, 근거는 `root`(발행 커밋에서
    꺼낸 것). 연구 요약은 as-of 를 되살릴 수 없어 다시 렌더하지 않고 원본과 바이트 대조한다
    (`check_period --research-frozen`). 일본 게이트는 근거 폴더를 인자로 받는다."""
    py = sys.executable
    s = 'scripts/'
    market, span = kinds.PERIOD[section]
    ev = kinds.evidence(section, key)
    cmds = [[py, s + 'check_style.py', post],
            [py, s + 'check_readability.py', '--strict', post],
            [py, s + 'verify_post.py', post, '--before', original, '--skip-layout']]
    if market == 'jp':
        cmds.append([py, s + 'check_japan.py', '--html', post, '--key', key,
                     '--datadir', os.path.join(root, 'japan/data')])
        return cmds
    cmd = [py, s + 'check_period.py', '--html', post, '--agg', os.path.join(root, ev[0]),
           '--recap', os.path.join(root, f'recap_{market}.json'),
           '--scorecard', os.path.join(root, 'data/period_scorecard.json'),
           '--span', span, '--market', market, '--research-frozen', original]
    if section == 'weekly':
        cmd += ['--insight', os.path.join(root, ev[1])]
    cmds.append(cmd)
    return cmds


def _name(cmd):
    return cmd[1].rsplit('/', 1)[-1] if len(cmd) > 1 else cmd[0]


def run_gates(cwd, cmds, timeout):
    """{게이트 이름: (종료 코드, 출력)}. 같은 경로로 두 번 돌려 출력을 맞댈 수 있게 한다."""
    out = {}
    for cmd in cmds:
        try:
            p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
            out[_name(cmd)] = (p.returncode, (p.stdout + p.stderr).strip())
        except subprocess.TimeoutExpired:
            out[_name(cmd)] = (124, f'{timeout}초 초과')
    return out


# 원본도 실패했다는 이유로 넘기지 않는 게이트 — corrector.NEVER_TOLERATE 와 같은 뜻.
NEVER_TOLERATE = frozenset(['check_fund.py'])


def judge(baseline, after):
    """거부 이유 목록 — 비면 통과."""
    bad = []
    for name, (code, text) in after.items():
        if code == 0:
            continue
        was = baseline.get(name)
        if was and was[0] != 0 and was == (code, text) and name not in NEVER_TOLERATE:
            continue   # 원본에서도 똑같이 실패한다 — 윤문이 만든 실패가 아니다
        bad.append(f'{name} 실패 (종료 {code}): {text[-300:]}')
    return bad


def _git(cwd, *args, check=True):
    p = subprocess.run(['git', *args], cwd=cwd, capture_output=True, text=True, timeout=120)
    if check and p.returncode:
        raise RuntimeError(f'git {args[0]} 실패: {(p.stderr or p.stdout).strip()[-300:]}')
    return p


def _push(clone, path, sha, recheck=None):
    """한 번 밀고, 거절되면 한 번만 rebase 해서 다시 민다.

    그 사이 **이 글이** 바뀌었으면 rebase 하지 않는다. 충돌 없이 합쳐지는 경우가 가장
    위험하다 — 검사받지 않은 두 편집의 혼합이 나간다. 글은 그대로여도 게이트 코드가 바뀌었을
    수 있으므로 rebase 뒤에는 `recheck()` 로 게이트를 다시 비교한다(2026-09-30 검토).
    """
    if _git(clone, 'push', '-q', 'origin', 'HEAD:main', check=False).returncode == 0:
        return None
    _git(clone, 'fetch', '-q', 'origin', 'main')
    upstream = _git(clone, 'rev-parse', f'origin/main:{path}', check=False).stdout.strip()
    if upstream != sha:
        return f'공개판이 바뀌었다 ({sha[:7]} → {upstream[:7]}) — 이번 윤문은 버린다'
    if _git(clone, 'rebase', '-q', 'origin/main', check=False).returncode:
        _git(clone, 'rebase', '--abort', check=False)
        return 'rebase 충돌 — 그 사이 같은 파일이 바뀌었다'
    why = recheck() if recheck else None
    if why:
        return why
    if _git(clone, 'push', '-q', 'origin', 'HEAD:main', check=False).returncode:
        return 'push 거절 (재시도 1회 뒤)'
    return None


def apply(root, item, payload, workdir, evidence_datadir, research_root=None, timeout=180):
    """codex 가 고친 문단을 공개판에 반영한다 → Result. 호출자의 checkout 은 건드리지 않는다.

    `evidence_datadir` 는 일간이면 근거 데이터 폴더, 주간·월간·일본이면 발행 커밋에서 근거 파일을
    레포 경로 그대로 꺼내 둔 뿌리다(`kinds.evidence`).
    """
    period = item.section in kinds.PERIOD
    key = kinds.key_of(item.path)
    names_dir = (os.path.dirname(os.path.join(evidence_datadir, kinds.evidence(item.section, key)[0]))
                 if period else evidence_datadir)
    try:
        with tempfile.TemporaryDirectory(prefix='style-pass-') as temp:
            clone = os.path.join(temp, 'repo')
            remote = _git(root, 'remote', 'get-url', 'origin').stdout.strip()
            _git(temp, 'clone', '-q', '--no-local', '--single-branch', '--branch', 'main',
                 remote, clone)
            now = _git(clone, 'rev-parse', f'HEAD:{item.path}', check=False).stdout.strip()
            if now != item.sha:
                return Result(reason=f'공개판이 바뀌었다 ({item.sha[:7]} → {now[:7]})')
            post = os.path.join(clone, item.path)
            html = Path(post).read_text(encoding='utf-8')
            _, sidecar = extract(html)
            names = known_names(html, names_dir)
            try:
                new, skipped = reinsert_partial(html, payload, sidecar, names=names)
            except ProseSwapError as exc:
                return Result(reason=f'되꽂기 거부 — {exc}')
            skipped = tuple(skipped)
            if new == html:
                return Result(reason=UNCHANGED + (f' (원문으로 둔 문단 {len(skipped)}개 — '
                                                  + '; '.join(f'{p}: {w}' for p, w in skipped)[:400]
                                                  + ')' if skipped else ''),
                              skipped=skipped)
            original = os.path.join(temp, 'original.html')
            Path(original).write_text(html, encoding='utf-8')
            m = _DATE.search(item.path)
            cycle = _CYCLE.search(html)
            cmds = gate_commands(item.section, post, evidence_datadir, original,
                                 key if period else (m.group(1) if m else ''),
                                 cycle.group(1) if cycle else None, research_root)
            baseline = run_gates(clone, cmds, timeout)
            Path(post).write_text(new, encoding='utf-8')
            bad = judge(baseline, run_gates(clone, cmds, timeout))
            if bad:
                return Result(reason='게이트 거부 — ' + ' / '.join(bad), skipped=skipped)
            dirty = _git(clone, 'status', '--porcelain', '--untracked-files=no').stdout.split('\n')
            touched = {line[3:] for line in dirty if line.strip()}
            if touched != {item.path}:
                return Result(reason=f'게이트가 다른 파일을 바꿨다: {sorted(touched)}')
            sha = _git(clone, 'hash-object', item.path).stdout.strip()
            _git(clone, 'add', item.path)
            _git(clone, 'commit', '-q', '-m',
                 f'문체: codex 윤문 — {item.path}\n\n'
                 f'루틴 STEP 2.5 를 대신하는 발행 뒤 문체 수정. 숫자·판단 어휘·링크는 문단마다 '
                 f'원문과 같고 STEP 2.5 게이트를 통과했다.'
                 + (f'\n검사에 걸려 원문으로 둔 문단 {len(skipped)}개: '
                    + ', '.join(p for p, _ in skipped) if skipped else '')
                 + f'\n\n{TRAILER} {item.sha[:7]}')
            defs = _git(clone, 'rev-parse', f'HEAD:{_DEFS}', check=False).stdout.strip()

            def recheck():
                """rebase 된 코드로 원본·수정본 게이트를 다시 맞댄다. 목록 정의가 바뀌었으면
                이 러너가 가진 옛 목록으로는 판정할 수 없다 — 다음 tick 에 맡긴다."""
                if _git(clone, 'rev-parse', f'HEAD:{_DEFS}', check=False).stdout.strip() != defs:
                    return f'rebase 사이 게이트 목록({_DEFS})이 바뀌었다 — 이번 윤문은 버린다'
                Path(post).write_text(html, encoding='utf-8')
                base = run_gates(clone, cmds, timeout)
                Path(post).write_text(new, encoding='utf-8')
                bad = judge(base, run_gates(clone, cmds, timeout))
                if _git(clone, 'status', '--porcelain', '--untracked-files=no').stdout.strip():
                    return '게이트 재실행이 작업 폴더를 바꿨다 — 푸시하지 않는다'
                return ('rebase 뒤 게이트 거부 — ' + ' / '.join(bad)) if bad else None

            why = _push(clone, item.path, item.sha, recheck=recheck)
            if why:
                return Result(reason=why)
            return Result(sha=sha, skipped=skipped)
    except (OSError, RuntimeError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        return Result(reason=f'{type(exc).__name__}: {exc}')
