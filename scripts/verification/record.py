"""발행 전 검증 기록 — 실제로 올릴 글에 실행 목록의 검사기를 돌리고 결과를 프로그램이 기록한다 (2026-11-08).

면접 지적 「수치 검증 절차를 눈으로 확인할 수 있어야 한다」 → 사용자 결정: 검사를 새로 만들지 않고, 발행 당시
실제로 돈 검사의 결과를 보고서별로 보존해 커밋된 글과 짝짓는다. CLI `scripts/run_gates.py`.

지키는 것(plan.md 2026-11-08 「발행 전 검증 기록」 표):
- **기록 상태 ≠ 발행 여부.** 필수 검사가 실패하거나 판정 불가면 현재 판은 올리지 않는다(`publish_ok` False).
  참고 검사는 상태에만 남는다. 적용 대상이 아니라 건너뛴 검사는 `not_run`, 필수 입력이 없어 못 돈 검사는
  `indeterminate` — 어느 쪽도 「통과」로 세지 않는다.
- AI 가 결과를 요약해 적지 않는다. 종료 코드·시각·출력 해시·입력 해시를 이 프로그램이 모은다.
- 공개 레포라 원시 출력은 저장하지 않는다(해시만). 위반·경고 줄은 경로를 가리고 길이를 줄여 남긴다.
- 편집자 노트(사람이 쓴 글)는 고치지 않는다 — 그러나 노트 때문에 난 실패를 무시하지도 않는다. 전체 글에서 실패한
  검사는 노트를 뺀 사본으로 같은 조건에서 다시 돌린다. 사본에서도 실패하면 본문 오류. 사본에서 사라지면 노트
  때문이고, 검사기의 종류(`kind`)로 처리한다: `format`(문단 길이·말투) = 기록하고 허용, `numbers`(수치 대조) =
  「노트 수치 불일치」로 검증 완료가 아님을 표시, `structure`(HTML 구조·필수 표식, 모르는 종류 포함) = 발행 보류.
  실패 항목 비교는 정규화한 출력 줄 단위다 — 검사기 대부분이 구조화된 출력을 내지 않아 위치·종류를 줄에서만
  읽는다. 그래서 차단 여부는 항목 비교가 아니라 사본의 결과와 검사기 종류가 정하고, 항목 비교는 참고로 남긴다.
  전체 글의 첫 결과는 그대로 둔다.
- 기록 기능 자체의 실패(저장 실패·기록 도구 오류)와 검사 실패를 가른다. 앞의 것은 처음 2주 동안 경고, 뒤의 것은
  기존 차단 규칙 그대로.
- 검사기 목록은 `config/prepub_gates.json` 하나 — 루틴의 반복 고리(`check`)와 기록(`record`)이 같은 목록을 쓴다.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone

FORMAT = 'prepub-record/1'
CONFIG_FORMAT = 'prepub-gates/1'
KST = timezone(timedelta(hours=9))
GATE_TIMEOUT = 300
TOTAL_TIMEOUT = 900
MAX_ITEMS = 40
MAX_ITEM_LEN = 200
MAX_INPUTS = 3000
NOTE_MARKER = 'data-editor-note'
_NOTE_RE = re.compile(r'\s*<section\b[^>]*\b' + NOTE_MARKER + r'\s*=\s*"[^"]*"[^>]*>.*?</section>\n?', re.S)
_WARN = re.compile(r'^\s*(경고|warn\b|WARN\b)')
_FATAL = re.compile(r'^\s*(FATAL|RESEARCH_ERROR)\b')     # 입력·실행 오류를 알리는 줄 — 위반이 아니다
_PLACE = re.compile(r'\{([a-z_]+)\}')
_ABS = re.compile(r'(?<![\w<])/(?:Users|private|tmp|var|home|root|opt|mnt|workspace)[^\s:"\'),]*')
KINDS = ('format', 'numbers', 'structure')
MAX_UNVERIFIED_KINDS = 12
HERE = os.path.dirname(os.path.abspath(__file__))


class ConfigError(Exception):
    pass


def load_config(path):
    try:
        with open(path, encoding='utf-8') as fh:
            cfg = json.load(fh)
    except (OSError, ValueError) as exc:
        raise ConfigError(f'검사기 목록을 읽지 못했다: {exc}') from exc
    if not isinstance(cfg, dict) or cfg.get('format') != CONFIG_FORMAT or not isinstance(cfg.get('markets'), dict):
        raise ConfigError('검사기 목록 형식이 다르다')
    return cfg


def gates_of(cfg, market):
    m = cfg['markets'].get(market)
    if not isinstance(m, dict) or not isinstance(m.get('gates'), list):
        raise ConfigError(f'{market} 실행 목록이 없다')
    return m['gates']


def now():
    return datetime.now(timezone.utc)


def _iso(t):
    return t.astimezone(KST).isoformat(timespec='seconds')


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


# ── 출력 정리 ─────────────────────────────────────────────────────────────

def _mask(line, ctx):
    for k in ('html', 'work_html', 'orig_html'):
        if ctx.get(k):
            line = line.replace(ctx[k], '<html>')
    for k in ('datadir', 'repo', 'tg', 'stance_next', 'tmp'):
        if ctx.get(k):
            line = line.replace(ctx[k], f'<{k}>')
    return _ABS.sub('<path>', line)


def items_of(text, ctx):
    out = []
    for raw in (text or '').splitlines():
        line = _mask(raw.strip(), ctx)
        if line:
            out.append(line[:MAX_ITEM_LEN])
    return out


# ── 검사기 하나 ───────────────────────────────────────────────────────────

def _argv(spec, ctx):
    """(argv, 빠진 자리표시자). 자리표시자는 ctx 에서 채운다."""
    missing, out = [], []
    for a in spec.get('argv') or []:
        def sub(m):
            v = ctx.get(m.group(1))
            if v in (None, ''):
                missing.append(m.group(1))
                return m.group(0)
            return str(v)
        out.append(_PLACE.sub(sub, a))
    if spec.get('json'):
        out.append('--json')
    return out, missing


def _base(spec):
    return {'name': spec['name'], 'required': bool(spec.get('required', True)),
            'kind': spec.get('kind') if spec.get('kind') in KINDS else 'structure',
            'argv': list(spec.get('argv') or []), 'status': 'indeterminate', 'exit': None,
            'script_sha256': None,
            'timed_out': False, 'reason': '', 'warn_count': 0, 'items': [], 'output_sha256': None,
            'note': None}


def _classify(spec, code, out, err, ctx, res):
    """종료 코드와 출력 → 상태. 모르는 것은 판정 불가."""
    lines = (out or '') + '\n' + (err or '')
    res['output_sha256'] = sha256_bytes(lines.encode('utf-8', 'replace'))
    items = items_of(lines, ctx)
    if spec.get('json'):
        try:
            obj = json.loads([x for x in (out or '').splitlines() if x.strip()][-1])
        except (IndexError, ValueError):
            obj = None
        if code == 2 or obj is None or not isinstance(obj, dict):
            res['reason'] = (items[-1] if items else '결과를 읽지 못했다') if code == 2 else '결과를 읽지 못했다'
            return 'indeterminate'
        if obj.get('skipped') is True:
            res['reason'] = '적용일 전 글이라 검사하지 않았다'
            return 'not_run' if code == 0 else 'indeterminate'
        warns, viols = obj.get('warnings'), obj.get('violations')
        counts = obj.get('counts')
        if not isinstance(warns, list) or not isinstance(viols, list) or not isinstance(counts, dict):
            res['reason'] = '결과 형식이 약속과 다르다'
            return 'indeterminate'
        res['numbers'] = {k: counts.get(k) for k in ('tokens_seen', 'table_cells', 'prose_judged',
                                                      'unverified', 'delegated', 'excluded')}
        by = obj.get('unverified_by')
        if isinstance(by, dict):        # 이유별 개수 — 검사기의 고정 분류 이름, 정수만(없으면 칸을 두지 않는다)
            res['numbers']['unverified_by'] = dict(sorted(
                ((_mask(str(k), ctx)[:60], v) for k, v in by.items()
                 if isinstance(v, int) and not isinstance(v, bool) and v > 0),
                key=lambda kv: -kv[1])[:MAX_UNVERIFIED_KINDS])
        res['items'] = [_mask(str(x), ctx)[:MAX_ITEM_LEN] for x in viols + warns][:MAX_ITEMS]
        res['warn_count'] = len(warns)
        if (code == 1) != bool(viols) or code not in (0, 1):
            res['reason'] = '종료 코드와 결과가 어긋난다'
            return 'indeterminate'
        return 'fail' if viols else ('warn' if warns else 'pass')
    res['items'] = items[:MAX_ITEMS]
    res['warn_count'] = sum(1 for x in lines.splitlines() if _WARN.match(x))
    if code == 0:
        # exit 0 이어도 검사하지 않은 경우가 있다 — 검사기별 출력 계약(codex 재검토 #8). 필수 입력이 없어
        # 못 본 것은 판정 불가, 적용 대상이 아니라 건너뛴 것은 실행 안 함.
        for pat in spec.get('partial_patterns') or []:
            hit = next((x for x in lines.splitlines() if re.search(pat, x)), None)
            if hit:
                # 일부만 검사했다 — 발행은 막지 않되(기존 규칙) 검증 완료로 세지 않는다
                res['reason'] = '일부 검사를 건너뛰었다 — ' + _mask(hit.strip(), ctx)[:MAX_ITEM_LEN]
                res['partial'] = True
        for pat in spec.get('indeterminate_patterns') or []:
            hit = next((x for x in lines.splitlines() if re.search(pat, x)), None)
            if hit:
                res['reason'] = '필수 입력이 없어 검사하지 못했다 — ' + _mask(hit.strip(), ctx)[:MAX_ITEM_LEN]
                return 'indeterminate'
        for pat in list(spec.get('not_run_patterns') or []) + [r'nothing to check', r'검사하지 않는다']:
            hit = next((x for x in lines.splitlines() if re.search(pat, x)), None)
            if hit:
                res['reason'] = '검사기가 검사하지 않았다 — ' + _mask(hit.strip(), ctx)[:MAX_ITEM_LEN]
                return 'not_run'
        if res.get('partial'):
            return 'partial'
        return 'warn' if res['warn_count'] else 'pass'
    if code == 1:
        if 'Traceback (most recent call last)' in (err or '') or any(_FATAL.match(x) for x in lines.splitlines()):
            res['reason'] = '검사기가 위반이 아니라 실행 오류로 끝났다'
            return 'indeterminate'
        return 'fail'
    res['reason'] = '입력을 읽지 못했다' if code == 2 else f'알 수 없는 종료 코드 {code}'
    return 'indeterminate'


def _effective(spec):
    """검사기의 적용일(모듈 상수). 없으면 None, 읽지 못하면 False — exit 0 이어도 그 전 글은 검사하지 않는다."""
    e = spec.get('effective')
    if not e:
        return None
    try:
        import importlib
        return str(getattr(importlib.import_module(e['module']), e['attr']))
    except Exception:  # noqa: BLE001
        return False


def _exec(spec, ctx, html, timeout):
    res = _base(spec)
    t0 = now()
    res['started'] = _iso(t0)
    try:
        if spec.get('builtin') == 'unconfirmed':
            with open(html, encoding='utf-8') as fh:
                n = fh.read().count('확인필요')
            res['exit'] = 0 if n == 0 else 1
            res['items'] = [] if n == 0 else [f'「확인필요」 {n}곳']
            res['status'] = 'pass' if n == 0 else 'fail'
            return res
        if spec.get('builtin'):
            res['reason'] = f'모르는 내장 검사 {spec["builtin"]}'
            return res
        eff = _effective(spec)
        if eff is False:
            res['reason'] = '적용일을 읽지 못했다'
            return res
        if eff and ctx.get('date') and ctx['date'] < eff:
            res['status'] = 'not_run'
            res['reason'] = f'적용일({eff}) 전 글이라 검사기가 검사하지 않는다'
            return res
        c = dict(ctx, html=html)
        argv, missing = _argv(spec, c)
        if missing:
            res['reason'] = '필수 입력 누락: ' + ', '.join(missing)
            return res
        script = os.path.join(ctx['repo'], argv[0])
        if not os.path.isfile(script):
            res['reason'] = '검사 프로그램이 없다'
            return res
        res['script_sha256'] = sha256_file(script)
        try:
            p = subprocess.run([sys.executable, script, *argv[1:]], capture_output=True, text=True,
                               cwd=ctx['repo'], timeout=timeout)
        except subprocess.TimeoutExpired:
            res['timed_out'] = True
            res['reason'] = f'{timeout}초 안에 끝나지 않았다'
            return res
        res['exit'] = p.returncode
        res['status'] = _classify(spec, p.returncode, p.stdout, p.stderr, dict(c, work_html=html), res)
        res['_out'] = p.stdout + ('\n' + p.stderr if p.stderr else '')
        return res
    except OSError as exc:
        res['reason'] = f'실행하지 못했다 — {type(exc).__name__}'
        return res
    finally:
        t1 = now()
        res['ended'] = _iso(t1)
        res['seconds'] = round((t1 - t0).total_seconds(), 2)


def _note_split(spec, ctx, html, res, timeout):
    """노트를 뺀 사본(같은 파일 이름·같은 입력)으로 다시 돌려 실패 항목을 가른다."""
    with open(html, encoding='utf-8') as fh:
        doc = fh.read()                       # html 은 불변 사본이다
    if NOTE_MARKER not in doc:
        return
    tmp = tempfile.mkdtemp(prefix='prepub-note-')
    try:
        copy = os.path.join(tmp, os.path.basename(html))
        with open(copy, 'w', encoding='utf-8') as fh:
            fh.write(_NOTE_RE.sub('\n', doc, count=1))
        again = _exec(spec, dict(ctx, tmp=tmp), copy, timeout)
        full = set(res['items'])
        stripped = set(_mask(x, dict(ctx, work_html=copy)) for x in again['items'])
        res['note'] = {'stripped_status': again['status'], 'stripped_exit': again['exit'],
                       'note_items': sorted(full - stripped), 'body_items': sorted(full & stripped)}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def run_gates(cfg, market, ctx, timeout=GATE_TIMEOUT, total=TOTAL_TIMEOUT):
    """실행 목록을 돌린다 → {'gates', 'summary', 'post_sha256', 'post_bytes'}. 글은 고치지 않는다.

    글 바이트를 **한 번** 읽어 불변 사본(같은 파일 이름)에 두고 그 사본만 검사한다 — 마지막 확인과 기록 사이에
    원본이 바뀌어도 기록의 해시는 검사한 바이트의 것이다(codex 구현 검토 #2). 원본이 검사 중에 바뀌었거나
    입력 파일이 검사 전후로 다르면 결과를 쓰지 않는다(#1·#7) — 발행 차단.
    """
    orig = ctx['html']
    with open(orig, 'rb') as fh:
        raw = fh.read()
    post_sha = sha256_bytes(raw)
    if not ctx.get('cycle'):
        # 연구 원장 cycle 은 글에 박혀 있다(`data-research-cycle`) — 인자로 안 줬으면 글에서 읽는다
        m = re.search(r'data-research-cycle="([^"]+)"', raw.decode('utf-8', 'replace'))
        ctx = dict(ctx, cycle=m.group(1) if m else None)
    inputs_before = _inputs(ctx)
    post_rel = _rel_post(orig, ctx['repo'])
    repo_before = repo_digest(ctx['repo'], market, post_rel, 'worktree')
    work = tempfile.mkdtemp(prefix='prepub-run-')
    try:
        html = os.path.join(work, os.path.basename(orig))
        with open(html, 'wb') as fh:
            fh.write(raw)
        c = dict(ctx, html=html, work_html=html, orig_html=orig)
        started = time.monotonic()
        results = []
        for spec in gates_of(cfg, market):
            left = total - (time.monotonic() - started)
            if left <= 0:
                r = _base(spec)
                r['reason'] = f'전체 {total}초 예산을 넘겨 돌리지 못했다'
                r['timed_out'] = True
                results.append(r)
                continue
            r = _exec(spec, c, html, min(timeout, max(1, int(left))))
            if r['status'] == 'fail':
                _note_split(spec, c, html, r, min(timeout, max(1, int(left))))
            results.append(r)
        integrity = []
        with open(html, 'rb') as fh:
            if sha256_bytes(fh.read()) != post_sha:
                integrity.append('검사기가 검사 사본을 바꿨다')
        try:
            with open(orig, 'rb') as fh:
                if sha256_bytes(fh.read()) != post_sha:
                    integrity.append('검사 중에 원본 글이 바뀌었다 — 다시 기록해야 한다')
        except OSError:
            integrity.append('검사 뒤 원본 글을 읽지 못했다')
        inputs_after = _inputs(ctx)
        if _digest_files(inputs_before) != _digest_files(inputs_after):
            integrity.append('검사 중에 입력 파일이 바뀌었다 — 다시 기록해야 한다')
        repo_after = repo_digest(ctx['repo'], market, post_rel, 'worktree')
        if repo_before[0] is None or repo_after[0] is None:
            integrity.append('레포 안 코드·원장의 다이제스트를 읽지 못했다')
        elif repo_before != repo_after:
            integrity.append('검사 중에 레포 안 코드·설정·원장이 바뀌었다 — 다시 기록해야 한다')
    finally:
        shutil.rmtree(work, ignore_errors=True)
    summary = summarize(results)
    if integrity:
        summary['integrity'] = integrity
        summary['publish_ok'] = False
        summary['verified'] = False
        summary['blocking'] = summary['blocking'] + ['integrity']
    return {'gates': results, 'summary': summary, 'post_sha256': post_sha, 'post_bytes': raw,
            'inputs': inputs_after, 'repo_digest': repo_after}


def _digest_files(inp):
    return sha256_bytes(json.dumps([(f['path'], f['sha256']) for f in inp['files']]).encode())


def summarize(results):
    """기록 상태와 발행 여부를 따로 낸다. 필수 검사의 실패·판정 불가는 막고, 참고 검사는 상태에만."""
    blocking, not_run, note_format, note_numbers, warned = [], [], [], [], []
    for r in results:
        st = r['status']
        if st in ('not_run', 'partial'):
            not_run.append(r['name'])
        if st == 'warn':
            warned.append(r['name'])
        if not r['required']:
            continue
        if st == 'indeterminate':
            blocking.append(r['name'])                 # 실행하지 못한 필수 검사는 통과가 아니다
        elif st == 'fail':
            n = r.get('note')
            note_only = bool(n) and n.get('stripped_status') in ('pass', 'warn')
            if not note_only:
                blocking.append(r['name'])             # 노트를 빼도 남는 실패 = 본문 오류
            elif r['kind'] == 'format':
                note_format.append(r['name'])          # 노트의 표현·형식 — 기록하고 허용
            elif r['kind'] == 'numbers':
                note_numbers.append(r['name'])         # 노트의 수치가 원자료와 다름 — 검증 완료 아님
            else:
                blocking.append(r['name'])             # 노트가 구조·필수 표식을 망가뜨림 — 보류
    statuses = {r['status'] for r in results}
    if 'fail' in statuses:
        status = 'fail'
    elif 'indeterminate' in statuses:
        status = 'indeterminate'
    elif not_run:
        status = 'pass_with_gaps'
    elif warned:
        status = 'pass_with_warnings'
    else:
        status = 'pass'
    return {'status': status, 'publish_ok': not blocking,
            'verified': status in ('pass', 'pass_with_warnings') and not note_numbers,
            'blocking': blocking, 'not_run': not_run, 'note_format': note_format,
            'note_numbers': note_numbers, 'warned': warned, 'integrity': []}


# ── 기록 ─────────────────────────────────────────────────────────────────

def _git(repo, *args):
    try:
        return subprocess.run(['git', '-C', repo, *args], capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None


def _code(repo):
    head = _git(repo, 'rev-parse', 'HEAD')
    status = _git(repo, 'status', '--porcelain', '--', 'scripts', 'config')
    diff = _git(repo, 'diff', 'HEAD', '--', 'scripts', 'config')
    dirty = bool(status and status.returncode == 0 and status.stdout.strip())
    return {'head': head.stdout.decode().strip() if head and head.returncode == 0 else None,
            'dirty': dirty,
            'dirty_sha256': sha256_bytes((diff.stdout if diff else b'') + (status.stdout if status else b''))
            if dirty else None,
            'python': sys.version.split()[0]}


REPO_PATHS = ('scripts', 'config')


def repo_paths(market):
    """판정에 쓰이는 레포 안 코드·원장. US 는 유동성 원장이 이전 글을 읽어 `posts/` 도."""
    return list(REPO_PATHS) + [f'research/{market}'] + (['posts'] if market == 'us' else [])


def repo_digest(repo, market, post_rel, source):
    """(다이제스트, 파일 수) — source: 'worktree' | 'index' | <rev>. 이 글과 기록 파일은 뺀다.
    진입 스크립트만 비교하면 판정 모듈·설정·원장이 바뀌어도 기록이 유효해 보인다(codex 구현 검토 #6)."""
    paths = repo_paths(market)
    rows = []
    if source == 'worktree':
        # git 과 똑같이 보려고 임시 index 에 `add -A` 해서 읽는다 — 직접 해시하면 심볼릭 링크(scripts/<p>/AGENTS.md)
        # 를 대상 내용으로 해시해 git 이 저장한 링크 blob 과 달라진다(모의 발행에서 나온 결함). 진짜 index 는 건드리지 않는다.
        ip = _git(repo, 'rev-parse', '--git-path', 'index')
        if ip is None or ip.returncode:
            return None, 0
        real = ip.stdout.decode().strip()
        real = real if os.path.isabs(real) else os.path.join(repo, real)
        tmpdir = tempfile.mkdtemp(prefix='prepub-index-')
        try:
            tmp = os.path.join(tmpdir, 'index')
            if os.path.isfile(real):
                shutil.copyfile(real, tmp)
            env = dict(os.environ, GIT_INDEX_FILE=tmp)
            # 없는 경로를 pathspec 으로 주면 add 가 통째로 실패한다 — 디스크에 있거나 index 에 있던 것만
            live = [p for p in paths if os.path.exists(os.path.join(repo, p)) or
                    subprocess.run(['git', '-C', repo, 'ls-files', '--', p], env=env, capture_output=True,
                                   text=True, timeout=60).stdout.strip()]
            add = subprocess.run(['git', '-C', repo, 'add', '-A', '--', *live], env=env, capture_output=True,
                                 timeout=120) if live else subprocess.CompletedProcess([], 0)
            out = subprocess.run(['git', '-C', repo, 'ls-files', '-s', '-z', '--', *paths], env=env,
                                 capture_output=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            return None, 0
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
        if add.returncode or out.returncode:
            return None, 0
        for ent in out.stdout.decode().split('\0'):
            if ent:
                meta, path = ent.split('\t', 1)
                rows.append((path, meta.split()[1]))
    else:
        cmd = ['ls-files', '-s', '-z', '--', *paths] if source == 'index' else ['ls-tree', '-r', '-z', source, '--', *paths]
        out = _git(repo, *cmd)
        if out is None or out.returncode:
            return None, 0
        for ent in out.stdout.decode().split('\0'):
            if not ent:
                continue
            meta, path = ent.split('\t', 1)
            parts = meta.split()
            rows.append((path, parts[1] if source == 'index' else parts[2]))
    rows = sorted((p, b) for p, b in rows if p != post_rel and not p.startswith('verification/'))
    return sha256_bytes(''.join(f'{p} {b}\n' for p, b in rows).encode()), len(rows)


def _inputs(ctx):
    files, capped, unreadable = [], False, 0
    roots = [('datadir', ctx.get('datadir'))]
    for key in ('tg', 'stance_next'):
        if ctx.get(key):
            roots.append((key, ctx[key]))
    for key, root in roots:
        if not root:
            continue
        paths = []
        if os.path.isdir(root):
            for d, dirs, names in os.walk(root):
                dirs[:] = sorted(x for x in dirs if not x.startswith('.'))
                paths += [os.path.join(d, n) for n in sorted(names) if not n.startswith('.')]
        elif os.path.isfile(root):
            paths = [root]
        for p in paths:
            if len(files) >= MAX_INPUTS:
                capped = True
                break
            rel = os.path.relpath(p, root) if os.path.isdir(root) else os.path.basename(p)
            try:
                files.append({'path': f'<{key}>/{rel}', 'sha256': sha256_file(p)})
            except OSError:
                unreadable += 1
    return {'count': len(files), 'capped': capped, 'unreadable': unreadable,
            'incomplete': capped or unreadable > 0, 'files': files}


def _generator(config_path):
    out = {}
    for p in (os.path.join(HERE, 'record.py'), os.path.join(os.path.dirname(HERE), 'run_gates.py'), config_path):
        try:
            out[os.path.basename(p)] = sha256_file(p)
        except OSError:
            out[os.path.basename(p)] = None
    return out


def _rel_post(html, repo):
    rel = os.path.relpath(html, repo)
    # 레포 밖 파일(초안)이면 경로를 남기지 않는다 — 공개 기록에 작업 공간 경로가 새지 않게. verify 는 실패한다.
    return '<레포 밖>/' + os.path.basename(html) if rel.startswith('..') else rel


_SPECIAL_REF = {'macro_next.json': 'data/macro.json', 'kr_stance_next.json': 'kr/data/kr_stance.json'}


def _ref_candidates(path, ctx):
    """입력 파일과 같은 바이트가 있을 레포 경로 후보 — 같으면 원본을 따로 보관하지 않아도 커밋에서 복원된다."""
    key, _, rel = path[1:].partition('>/')
    repo, date = ctx['repo'], ctx.get('date') or ''
    out = []
    root = ctx.get(key)
    if key == 'datadir' and root:
        inside = os.path.relpath(os.path.join(root, rel), repo)
        if not inside.startswith('..'):
            out.append(inside)
        else:
            out.append(os.path.join('data', rel))
            if os.path.basename(rel) in _SPECIAL_REF:
                out.append(_SPECIAL_REF[os.path.basename(rel)])
        if os.path.basename(rel) == 'telegram.json':     # US 루틴이 data/telegram/<D>.json 을 작업 공간에 복사한 판
            out += [f'data/telegram/{date}.json', f'kr/data/telegram/{date}.json']
    elif key == 'tg':
        out += [f'data/telegram/{date}.json', f'kr/data/telegram/{date}.json']
    elif key == 'stance_next':
        out.append('kr/data/kr_stance.json')
    return out


# 작업 공간 사본이 기록 전에 레포에서 덮이는 입력 → 이력에서 찾을 레포 경로. 승격된 책(macro_next → data/macro.json)
# 때문에 기록 시점의 워크트리와는 어긋나지만, 루틴이 복사해 온 판은 origin 에 이미 있다(11/10 US 실측).
# 입력 전부를 이력에서 찾지 않는다 — 수천 개 × git 호출로 기록이 멈춘다(codex 설계 검토 #2).
_HISTORY_REF = {'<datadir>/macro.json': 'data/macro.json'}
_HISTORY_DEPTH = 5
_HISTORY_BASE = 'refs/remotes/origin/main'


def _history_ref(path, want, ctx):
    """`git:<커밋>:<경로>` — 그 커밋의 파일 바이트가 입력과 같을 때만. 커밋은 HEAD 와 로컬 origin/main 추적 이력의
    조상이어야 한다(미푸시 커밋은 rebase 로 sha 가 바뀐다). 바이트 일치는 복원 가능성의 증거이지 그 파일을 원본으로
    썼다는 증거는 아니다. git 이 실패하면 None — 기록을 막지 않고 workspace-only 로 둔다."""
    rel = _HISTORY_REF.get(path)
    repo = ctx['repo']
    if not rel:
        return None
    base = _git(repo, 'rev-parse', '--verify', '--quiet', _HISTORY_BASE)
    if base is None or base.returncode != 0:
        return None
    revs = _git(repo, 'rev-list', f'--max-count={_HISTORY_DEPTH}', 'HEAD', '--', rel)
    if revs is None or revs.returncode != 0:
        return None
    for c in revs.stdout.decode().split():
        got = _git(repo, 'show', f'{c}:{rel}')
        if got is None or got.returncode != 0 or sha256_bytes(got.stdout) != want:
            continue                                   # C 에서 바뀐 뒤의 바이트만 C 의 파일이다(codex 설계 검토 #1)
        anc = _git(repo, 'merge-base', '--is-ancestor', c, _HISTORY_BASE)
        if anc is not None and anc.returncode == 0:
            return f'git:{c}:{rel}'
        # 미푸시 커밋이 같은 바이트를 담았으면 건너뛰고 더 앞 커밋을 본다(codex 구현 검토 #1)
    return None


def _preservation(inputs, ctx):
    lost = []
    for f in inputs['files']:
        ref = None
        for cand in _ref_candidates(f['path'], ctx):
            full = os.path.join(ctx['repo'], cand)
            try:
                if os.path.isfile(full) and sha256_file(full) == f['sha256']:
                    ref = 'repo:' + cand
                    break
            except OSError:
                pass
        ref = ref or _history_ref(f['path'], f['sha256'], ctx)
        f['ref'] = ref or 'workspace-only'
        if not ref:
            lost.append(f['path'])
    return {'workspace_only': len(lost), 'workspace_only_files': lost[:200],
            'note': '같은 바이트가 이 커밋의 레포 경로에 있으면 repo:<경로>, 로컬 origin/main 추적 이력의 앞 커밋에 있으면 '
                    'git:<커밋>:<경로> 로 참조한다(복원 가능성 — 그 파일을 원본으로 썼다는 증거는 아니다). '
                    'workspace-only 는 해시만 남는다 — 원본은 보관하지 않았다'}


def _rel_post(html, repo):
    rel = os.path.relpath(html, repo)
    # 레포 밖 파일(초안)이면 경로를 남기지 않는다 — 공개 기록에 작업 공간 경로가 새지 않게. verify 는 실패한다.
    return '<레포 밖>/' + os.path.basename(html) if rel.startswith('..') else rel


def build_record(cfg, config_path, market, ctx, res):
    """기록 — 글 해시는 검사한 바이트(res['post_bytes'])의 것이다. 원본을 다시 읽지 않는다."""
    html, repo = ctx['html'], ctx['repo']
    raw = res['post_bytes']
    rel = _rel_post(html, repo)
    blob = subprocess.run(['git', '-C', repo, 'hash-object', '--stdin'], input=raw, capture_output=True, timeout=60)
    digest, nfiles = res.get('repo_digest') or repo_digest(repo, market, rel, 'worktree')   # 검사 전후 같은 값
    t = now()
    gates = [{k: v for k, v in r.items() if k != '_out'} for r in res['gates']]
    inputs = res['inputs']
    preservation = _preservation(inputs, ctx)
    return {
        'format': FORMAT, 'market': market, 'date': ctx['date'],
        'post': {'path': rel, 'sha256': res['post_sha256'],
                 'blob': blob.stdout.decode().strip() if blob.returncode == 0 else None},
        'created_at': {'utc': t.isoformat(timespec='seconds'), 'kst': _iso(t)},
        'generator': _generator(config_path), 'code': _code(repo),
        'repo_inputs': {'paths': repo_paths(market), 'digest': digest, 'files': nfiles},
        'inputs': inputs, 'preservation': preservation,
        'gates': gates, 'disabled': (cfg.get('disabled') or {}).get(market, []),
        'manual': '수기 대조(문장 수치 표본 등)는 자동 기록 대상이 아니다 — 이 기록에 들어 있지 않다',
        'summary': res['summary'],
    }


def _atomic_write(path, data):
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix='.prepub-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            fh.write(data)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def fallback_path(market, date):
    return os.path.join(tempfile.gettempdir(), f'prepub-record-{market}-{date}.json')


def save_record(rec, path, fallback=None):
    """0 = 저장 / 4 = 레포 안 저장 실패, 레포 밖 대체 기록(fallback)에 같은 기록을 남겼다 /
    5 = 둘 다 실패(검사 증거가 없다 — 발행 보류). 그 날짜의 낡은 기록은 지운다 — 다른 판의 기록이 커밋되지 않게.

    저장 실패 경로에서 글 해시만 남기면 rebase 로 코드·원장·입력이 바뀌어도 재검사 없이 push 된다(codex 재검토
    #10). 그래서 같은 기록을 레포 밖에 두고 `verify --record-file` 이 전부 대조하게 한다."""
    try:
        data = json.dumps(rec, ensure_ascii=False, indent=1, sort_keys=True) + '\n'
    except (TypeError, ValueError):
        return 5
    try:
        _atomic_write(path, data)
        return 0
    except (OSError, TypeError, ValueError):
        try:
            os.unlink(path)
        except OSError:
            pass
    if fallback:
        try:
            _atomic_write(fallback, data)
            return 4
        except (OSError, TypeError, ValueError):
            pass
    return 5


# ── 짝 확인 ──────────────────────────────────────────────────────────────

def record_path(market, date):
    return f'verification/{market}/{date}.json'


def post_path(cfg, market, date):
    return cfg['markets'][market]['post'].format(date=date)


def _exists(repo, rev, path):
    """(있나, git 을 읽었나) — 「경로 없음」과 git 객체·인덱스 오류를 가른다(codex 재검토 #3)."""
    out = _git(repo, 'ls-files', '--stage', '--', path) if rev is None else _git(repo, 'ls-tree', rev, '--', path)
    if out is None or out.returncode != 0:
        return False, False
    return bool(out.stdout.strip()), True


def verify(cfg, market, date, repo, rev=None, datadir=None, extra=None, record_file=None):
    """(exit, 이유들). rev=None 이면 index(커밋 직전), 아니면 그 커밋(push 직전 = HEAD).

    exit 0 짝 맞음 / 1 어긋남(다시 record) / 2 git 을 읽지 못함(차단 — 「기록 없음」이 아니다) / 4 기록 없음.
    글 해시만 보지 않는다 — 그 판의 검사 프로그램, 레포 안 코드·설정·원장(`repo_inputs`), 그리고 `datadir`·`extra`
    로 주는 지금 입력까지 기록과 같아야 한다. 기록에 있는 입력 뿌리(--tg·--stance-next)를 안 주면 실패한다 —
    record 와 다른 인자로 대조하면 정상 발행이 기록·대조를 맴돈다(codex 구현 검토 #4).
    `record_file` 은 기록 저장이 실패한 경우(record exit 4)에만 — 레포 밖 대체 기록을 git 대신 읽고 나머지는 똑같이
    대조한다(글 해시만 보면 rebase 뒤 바뀐 코드·원장을 놓친다).
    """
    spec = ':{}' if rev is None else f'{rev}:{{}}'
    where = 'index' if rev is None else rev
    rp, pp = record_path(market, date), post_path(cfg, market, date)
    probe = _git(repo, 'rev-parse', '--git-dir') if rev is None else _git(repo, 'rev-parse', '--verify', rev)
    if probe is None or probe.returncode != 0:
        return 2, [f'git 을 읽지 못했다 — {where}']
    has_post, ok = _exists(repo, rev, pp)
    if not ok:
        return 2, [f'git 을 읽지 못했다 — {where}']
    if not has_post:
        return 1, [f'글 없음 — {pp} 이 {where} 에 없다']
    post_raw = _git(repo, 'show', spec.format(pp))
    if post_raw is None or post_raw.returncode != 0:
        return 2, [f'글 blob 을 읽지 못했다 — {where}']
    if record_file:
        try:
            with open(record_file, encoding='utf-8') as fh:
                rec_text = fh.read()
        except OSError:
            return 2, ['대체 기록을 읽지 못했다']
        has_rec, _ = _exists(repo, rev, rp)
        if has_rec:
            return 1, ['레포 안 기록이 있는데 대체 기록으로 대조하려 한다 — 레포 안 기록으로 verify']
    else:
        has_rec, ok = _exists(repo, rev, rp)
        if not ok:
            return 2, ['git 을 읽지 못했다']
        if not has_rec:
            return 4, [f'기록 없음 — {rp} 이 {where} 에 없다']
        rec_raw = _git(repo, 'show', spec.format(rp))
        if rec_raw is None or rec_raw.returncode != 0:
            return 2, [f'기록 blob 을 읽지 못했다 — {where}(경로는 있다)']
        rec_text = rec_raw.stdout.decode('utf-8', 'replace')
    try:
        rec = json.loads(rec_text)
    except ValueError:
        return 1, ['기록을 읽지 못했다']
    why = []
    if not isinstance(rec, dict) or rec.get('format') != FORMAT:
        return 1, ['기록 형식이 다르다']
    if rec.get('market') != market or rec.get('date') != date:
        why.append(f'다른 글의 기록이다 — {rec.get("market")}/{rec.get("date")}')
    post = rec.get('post') or {}
    if post.get('path') != pp:
        why.append(f'기록의 글 경로 {post.get("path")} ≠ {pp}')
    if post.get('sha256') != sha256_bytes(post_raw.stdout):
        why.append('글 해시가 다르다 — 기록한 뒤 글이 바뀌었다(다시 기록해야 한다)')
    want = [g['name'] for g in gates_of(cfg, market)]
    got = [g.get('name') for g in rec.get('gates') or []]
    if got != want:
        why.append(f'검사기 목록이 실행 목록과 다르다 — 기록 {got} / 목록 {want}')
    summ = rec.get('summary') or {}
    if not summ.get('publish_ok'):
        why.append('기록이 발행 불가를 말한다 — ' + ', '.join(summ.get('blocking') or []))
    for g in rec.get('gates') or []:
        argv = g.get('argv') or []
        if not argv or not g.get('script_sha256'):
            continue
        cur = _git(repo, 'show', spec.format(argv[0]))
        if cur is None or cur.returncode != 0 or sha256_bytes(cur.stdout) != g['script_sha256']:
            why.append(f'검사 코드가 바뀌었다 — {g.get("name")}({argv[0]})')
    ri = rec.get('repo_inputs') or {}
    now_digest, _ = repo_digest(repo, market, pp, 'index' if rev is None else rev)
    if not ri.get('digest') or now_digest != ri['digest']:
        why.append('레포 안 코드·설정·원장이 기록 때와 다르다(' + ', '.join(ri.get('paths') or []) + ') — 다시 기록해야 한다')
    roots = {f['path'][1:].split('>/', 1)[0] for f in (rec.get('inputs') or {}).get('files') or []}
    given = {'datadir': datadir, **(extra or {})}
    missing = sorted(r for r in roots if not given.get(r))
    if missing:
        why.append('입력 인자 누락 — 기록에 있는 입력을 대조하려면 ' + ', '.join('--' + m.replace('_', '-') for m in missing))
    if datadir:
        now_in = _inputs(dict(datadir=datadir, **(extra or {})))
        old = {f['path']: f['sha256'] for f in (rec.get('inputs') or {}).get('files') or []}
        new = {f['path']: f['sha256'] for f in now_in['files']}
        changed = sorted(k for k in set(old) | set(new) if old.get(k) != new.get(k))
        if changed:
            why.append(f'입력 데이터가 바뀌었다 — {len(changed)}개(' + ', '.join(changed[:5]) + ')')
    return (1, why) if why else (0, ['짝 맞음 — 기록의 글·검사 코드·레포 원장·입력 = 지금 판'])
