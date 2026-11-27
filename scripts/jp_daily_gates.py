#!/usr/bin/env python3
"""일본 일간 실행 격리 — 입력 고정과 다섯 게이트 래퍼(2026-11-19, 설계 20판 §6-2·§6-4·§6-4-1).

    D=_workspace/jpd/$RUN_ID                     # RUN_ID = jpd-<S>-<UTC 초>-<난수>
    python3 scripts/jp_daily_gates.py --pin --run-dir $D --session $S
        → HEAD 가 가리키는 커밋 SHA 를 한 번 읽고, 그 커밋의 수집 후보·뉴스·견해 파일을 `D/root/` 같은 상대 경로에 꺼내고 `D/inputs.json` 에 해시를 적는다.
          작업 폴더의 파일이 아니라 `git show HEAD:<경로>` 의 바이트다. HEAD 에 없으면 그 실행에서는 「없음」.
          D 가 이미 있으면 거부한다 — 입력은 실행마다 한 번만 고정된다.
    python3 scripts/jp_daily_gates.py --run-dir $D --session $S
        → `D/jpd_<S>.html`(조립본)에 조판 → 일간 게이트 → 뉴스 게이트 → 읽기 쉬움 → 문체, 전부 `D/root` 만 읽는다.
          **전부 통과했을 때만** `D/gates.json` 을 한 번에(임시 파일 → rename) 쓴다. 시작할 때 있던 것은 먼저 지운다.
          exit 0 통과 · 1 위반(목록을 찍고 `D/gates.log` 에 남긴다) · 2 사용 오류.
          입력 해시는 시작·조판 직후·검사 끝에 `inputs.json` 의 고정값과 직접 견준다.
    python3 scripts/jp_daily_gates.py --invalidate "<이유>" --run-dir $D --session $S
        → 통과 기록을 지우고 이유를 `D/gates.log` 에 쓴다(작성자에게 되돌릴 때). 조립(`build_japan_daily.py assemble
          --out $D/…`)도 시작할 때 같은 일을 하고, 실패하면 그 목록을 로그에 남긴다.

`telegram_sha256` 은 게이트가 실제로 채택한 견해 바이트에만 붙는다(`build_japan_daily.telegram_problem` 이 유일한
스위치) — `usable: false`·깨진 파일은 `null` 이고 발행기는 그날 고정 파일을 만들지 않는다.
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, REPO)


class GateError(Exception):
    pass


def inputs(session):
    return [f'japan/data/daily/candidate/{session}.json', f'japan/data/news/daily/{session}.json',
            f'japan/data/telegram/{session}.json']


def html_path(run_dir, session):
    # 일간 게이트는 파일 이름이 `<S>.html` 로 끝나는지 본다
    return os.path.join(run_dir, f'jpd_{session}.html')


def sha256(b):
    return hashlib.sha256(b).hexdigest()


def _read(path):
    try:
        with open(path, 'rb') as fh:
            return fh.read()
    except FileNotFoundError:
        return None


def check_run_id(run_dir, session):
    run_id = os.path.basename(os.path.normpath(run_dir))
    if not re.fullmatch(rf'jpd-{re.escape(session)}-\d+-\d+', run_id):
        raise GateError(f'실행 폴더 이름 {run_id} 이 이 세션의 run_id(jpd-{session}-<UTC 초>-<난수>)가 아니다')
    return run_id


def _commit(root):
    r = subprocess.run(['git', '-C', root, 'rev-parse', '--verify', 'HEAD^{commit}'], capture_output=True, text=True)
    if r.returncode or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', r.stdout.strip()):
        raise GateError('HEAD 를 읽지 못했다')
    return r.stdout.strip()


def _blob(root, commit, rel):
    """`<commit>:<rel>` 의 바이트 — HEAD 가 아니라 처음 읽은 SHA 에서(codex 구현 1회차 #4)."""
    r = subprocess.run(['git', '-C', root, 'cat-file', '-e', f'{commit}:{rel}'], capture_output=True)
    if r.returncode:
        return None
    r = subprocess.run(['git', '-C', root, 'show', f'{commit}:{rel}'], capture_output=True)
    if r.returncode:
        raise GateError(f'{commit[:10]}:{rel} 을 읽지 못했다: {r.stderr.decode("utf-8", "replace").strip()}')
    return r.stdout


BOJ = 'japan/data/boj'
BOJ_COVERED = f'{BOJ}/covered.json'


def boj_blobs(root, commit, session):
    """일본은행 칸 입력(2026-11-27) — 같은 커밋의 일정 파일(필수)·수집 결과·원문과, 같은 커밋의 일본 일간 발행본
    (파일 이름 날짜 < S)에서 뽑은 「이미 다룬 KEY」 장부 `covered.json`. 원문 파일 이름이 날마다 달라 `inputs()` 고정
    목록에 못 넣는다 — events.json 을 읽어 목록을 만든다."""
    from common import cb_events as CE
    out = {}
    sched = _blob(root, commit, f'{BOJ}/schedule.json')
    if sched is None:
        raise GateError(f'{commit[:10]}:{BOJ}/schedule.json 이 없다 — 일본은행 일정 파일 없이 입력을 고정하지 않는다')
    out[f'{BOJ}/schedule.json'] = sched
    for name in ('events.json', 'statements.json'):
        b = _blob(root, commit, f'{BOJ}/{name}')
        if b is not None:
            out[f'{BOJ}/{name}'] = b
    book = out.get(f'{BOJ}/events.json')
    if book is not None:
        try:
            events = json.loads(book.decode('utf-8')).get('events') or []
        except (ValueError, AttributeError) as e:
            raise GateError(f'{BOJ}/events.json 을 읽지 못했다: {e}')
        for e in events:
            key = (e or {}).get('key') if isinstance(e, dict) else None
            if key and re.fullmatch(r'[a-z0-9-]+', key):
                b = _blob(root, commit, f'{BOJ}/{key}.txt')
                if b is not None:
                    out[f'{BOJ}/{key}.txt'] = b
    try:
        keys = sorted(CE.covered_from_posts(root, 'japan/daily', session, rev=commit))
    except RuntimeError as e:
        raise GateError(f'발행본 장부를 읽지 못했다: {e}')
    out[BOJ_COVERED] = (json.dumps({'input_commit': commit, 'session': session, 'keys': keys}, ensure_ascii=False,
                                   indent=1) + '\n').encode('utf-8')
    return out


def pin(root, run_dir, session):
    """HEAD 의 입력을 D/root 에 한 번 꺼낸다 -> inputs 기록."""
    run_id = check_run_id(run_dir, session)
    if os.path.exists(run_dir):
        raise GateError(f'{run_dir} 이 이미 있다 — 실행마다 새 run_id 로 고정한다')
    commit = _commit(root)
    blobs = {rel: _blob(root, commit, rel) for rel in inputs(session)}
    blobs.update(boj_blobs(root, commit, session))
    os.makedirs(os.path.join(run_dir, 'root'))
    for rel, b in blobs.items():
        if b is None:
            continue
        p = os.path.join(run_dir, 'root', rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'wb') as fh:
            fh.write(b)
    rec = {'run_id': run_id, 'session': session, 'input_commit': commit,
           'files': {rel: (sha256(b) if b is not None else None) for rel, b in blobs.items()}}
    _write_atomic(os.path.join(run_dir, 'inputs.json'), rec)
    return rec


def _write_atomic(path, obj):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)
        fh.write('\n')
    os.replace(tmp, path)


def gate_commands(run_dir, session, html):
    """다섯 게이트 — 오케스트레이터 STEP 3 의 순서 그대로, 입력은 D/root 사본만."""
    py, root = sys.executable, os.path.join(run_dir, 'root')
    sc = lambda name: os.path.join(HERE, name)  # noqa: E731
    return [
        ('apply_readability', [py, sc('apply_readability.py'), html]),
        ('check_japan_daily', [py, sc('check_japan_daily.py'), '--session', session, '--root', root, '--html', html]),
        ('check_news', [py, sc('check_news.py'), '--html', html, '--datadir', os.path.join(root, 'japan', 'data'),
                        '--market', 'jp-daily', '--date', session]),
        ('check_readability', [py, sc('check_readability.py'), '--strict', html]),
        ('check_style', [py, sc('check_style.py'), html]),
    ]


def _input_hashes(run_dir, rels):
    return {rel: (sha256(b) if (b := _read(os.path.join(run_dir, 'root', rel))) is not None else None)
            for rel in rels}


def _moved(run_dir, session, rec):
    """D/root 의 입력 가운데 고정할 때 적은 해시(inputs.json)와 다른 것. 목록은 `inputs.json` 의 `files` 키 —
    일본은행 원문 파일은 실행마다 달라 `inputs(session)` 고정 목록으로는 못 본다(2026-11-27)."""
    rels = sorted(set(inputs(session)) | set(rec.get('files') or {}))
    now = _input_hashes(run_dir, rels)
    return [rel for rel in rels if now[rel] != (rec.get('files') or {}).get(rel)]


def invalidate(run_dir, reason, lines=()):
    """이 실행의 통과 기록을 지운다 — 작성자에게 되돌리는 순간과 새 판을 조립할 때(codex 구현 1회차 #1).
    로그는 지금 시도의 것으로 덮어쓴다(경보가 앞 판의 로그를 가리키지 않게)."""
    p = os.path.join(run_dir, 'gates.json')
    if os.path.exists(p):
        os.remove(p)
    with open(os.path.join(run_dir, 'gates.log'), 'w', encoding='utf-8') as fh:
        fh.write('\n'.join([f'검증 무효 — {reason}', *[f'  - {x}' for x in lines]]) + '\n')


def adopted_telegram(run_dir, session):
    """게이트가 채택한 견해 바이트의 해시, 채택하지 않았으면 None."""
    from build_japan_daily import telegram_problem
    b = _read(os.path.join(run_dir, 'root', 'japan', 'data', 'telegram', f'{session}.json'))
    if b is None:
        return None
    try:
        data = json.loads(b.decode('utf-8'))
    except ValueError:
        return None
    return None if telegram_problem(data, session) else sha256(b)


_TITLE = re.compile(r'<title>(.*?)</title>', re.S)
_DESC = re.compile(r'<meta name="description" content="([^"]*)">')


def title_summary(html_text):
    """조립이 넣은 `<title>`·meta description — 조립의 escape 를 정확히 되돌린다."""
    from scripts.common import post_shell as SH
    t, d = _TITLE.search(html_text), _DESC.search(html_text)
    return (SH.unescape(t.group(1)).strip() if t else ''), (SH.unescape(d.group(1)).strip() if d else '')


def run_gates(run_dir, session, commands=None):
    """-> (통과 여부, 로그 글). 통과했을 때만 gates.json."""
    out = os.path.join(run_dir, 'gates.json')
    if os.path.exists(out):
        os.remove(out)                     # 앞선 통과가 이번 실패 뒤에 남지 않게
    log = []

    def fail(msg):
        log.append(f'검증 실패 — {msg}')
        text = '\n'.join(log)
        with open(os.path.join(run_dir, 'gates.log'), 'w', encoding='utf-8') as fh:
            fh.write(text + '\n')
        return False, text

    try:
        run_id = check_run_id(run_dir, session)
        with open(os.path.join(run_dir, 'inputs.json'), encoding='utf-8') as fh:
            rec = json.load(fh)
    except (GateError, OSError, ValueError) as e:
        return fail(f'실행 폴더를 쓸 수 없다: {e}')
    if rec.get('run_id') != run_id or rec.get('session') != session:
        return fail(f'inputs.json 의 run_id·세션({rec.get("run_id")}, {rec.get("session")})이 이 실행과 다르다')
    diff = _moved(run_dir, session, rec)
    if diff:
        return fail('고정한 입력이 바뀌었다: ' + ', '.join(diff))
    pinned = {rel: rec['files'].get(rel) for rel in inputs(session)}
    html = html_path(run_dir, session)
    if not os.path.exists(html):
        return fail(f'조립본 {html} 이 없다')
    cmds = (commands or gate_commands)(run_dir, session, html)
    results, before = [], None
    for i, (name, argv) in enumerate(cmds):
        r = subprocess.run(argv, capture_output=True, text=True, cwd=REPO)
        results.append({'name': name, 'exit': r.returncode})
        text = (r.stdout + r.stderr).strip()
        log.append(f'[{name}] exit {r.returncode}' + (f'\n{text}' if text else ''))
        if i == 0:
            if r.returncode:
                return fail('조판이 실패했다')
            # 조판이 글을 고쳐 쓴 뒤의 바이트가 검사받는 바이트다. 입력은 조판 직후에도 고정값과 직접 견준다
            moved = _moved(run_dir, session, rec)
            if moved:
                return fail('조판 중 고정한 입력이 바뀌었다: ' + ', '.join(moved))
            before = sha256(_read(html))
    if any(x['exit'] for x in results):
        return fail('게이트 위반: ' + ', '.join(x['name'] for x in results if x['exit']))
    page = _read(html)
    moved = _moved(run_dir, session, rec)
    if moved or sha256(page) != before:
        return fail('게이트를 도는 사이 조립본이나 입력이 바뀌었다' + (': ' + ', '.join(moved) if moved else ''))
    title, summary = title_summary(page.decode('utf-8'))
    if not title or not summary:
        return fail('조립본에 <title> 이나 meta description 이 없다')
    rel = inputs(session)
    _write_atomic(out, {
        'run_id': run_id, 'session': session, 'input_commit': rec.get('input_commit'),
        'html_sha256': sha256(page), 'snapshot_sha256': pinned[rel[0]], 'news_sha256': pinned[rel[1]],
        'telegram_sha256': adopted_telegram(run_dir, session), 'title': title, 'summary': summary,
        'gates': results, 'verdict': 'pass',
        'finished_at': datetime.datetime.now(datetime.timezone.utc).isoformat()})
    log.append(f'다섯 게이트 통과 — {out}')
    text = '\n'.join(log)
    with open(os.path.join(run_dir, 'gates.log'), 'w', encoding='utf-8') as fh:
        fh.write(text + '\n')
    return True, text


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--run-dir', required=True)
    ap.add_argument('--session', required=True)
    ap.add_argument('--root', default='.')
    ap.add_argument('--pin', action='store_true', help='HEAD 의 입력을 실행 폴더에 고정한다(작성자를 부르기 전에 한 번)')
    ap.add_argument('--invalidate', metavar='REASON', help='통과 기록을 지운다(작성자에게 되돌릴 때)')
    args = ap.parse_args(argv)
    args.run_dir = os.path.abspath(args.run_dir)     # 게이트는 cwd=REPO 에서 돈다
    if args.invalidate is not None:
        try:
            check_run_id(args.run_dir, args.session)
        except GateError as e:
            print(e, file=sys.stderr)
            return 2
        invalidate(args.run_dir, args.invalidate)
        print(f'통과 기록 무효 — {args.invalidate}')
        return 0
    if args.pin:
        try:
            rec = pin(os.path.abspath(args.root), args.run_dir, args.session)
        except GateError as e:
            print(e, file=sys.stderr)
            return 2
        for rel, h in rec['files'].items():
            print(f'{rel}: {h[:12] if h else "없음"}')
        print(f'입력 고정 — HEAD {rec["input_commit"][:10]} → {os.path.join(args.run_dir, "root")}')
        return 0
    ok, text = run_gates(args.run_dir, args.session)
    print(text, file=sys.stdout if ok else sys.stderr)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
