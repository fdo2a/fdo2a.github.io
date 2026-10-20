#!/usr/bin/env python3
"""쟁점 분석 로컬 러너 — Mac 의 launchd 가 15분마다 부른다(`runner_launch.py contested run`).

2026-10-21 사용자: 「최대한 claude 주간한도를 사용하도록」 → 「로컬로 하자」. 판단은 Mac 에 로그인된
Claude Code(`claude -p`, 구독)가 하고, 이 러너는 수집·대조·조립·발행을 맡는다. 클라우드 루틴은
결과 JSON 을 읽어 섹션을 찍기만 한다.

한 tick 이 하는 일(대부분의 tick 은 할 일이 없어 몇 초 만에 끝난다):
1. origin/main 을 임시 폴더에 새로 clone 한다 — 사람 폴더는 읽지도 움직이지도 않는다.
2. `data/market_data.json` 이 완성된 최근 기준일을 찾는다.
3. 그 날짜 결과(`data/contested/us/<D>.json`)가 확정 전이면 수집 → 고르기·추출·검증 → 조립.
4. 뉴스·산업 브리프가 이미 발행돼 자리표시(`PENDING`)를 갖고 있으면 섹션을 채우고 게이트를 돈다
   (못 넘으면 명시적 생략 기록). 확정된 결과가 섹션이 아니면 자리표시를 지운다.
5. 결과(와 고친 발행본)를 커밋·푸시한다. 그 사이 발행본이 바뀌었으면 버린다.

    python3 scripts/contested_local.py run [--date D] [--dry-run]
"""

import argparse
import fcntl
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import contested as C  # noqa: E402

KST = timezone(timedelta(hours=9))
LOCK = os.path.expanduser('~/Library/Caches/fdo2a-contested.lock')
MAX_AGE_DAYS = 3


def _git(cwd, *args, check=True, timeout=120):
    p = subprocess.run(['git', *args], cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if check and p.returncode:
        raise RuntimeError(f'git {args[0]} 실패: {(p.stderr or p.stdout).strip()[-300:]}')
    return p.stdout.strip()


def _load(path):
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _save(path, payload):
    payload['content_hash'] = C.content_hash(payload)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix='.tmp')
    with os.fdopen(fd, 'w', encoding='utf-8') as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
        fh.write('\n')
    os.replace(tmp, path)


def page_state(html):
    """발행본의 쟁점 자리 — 'none'(글 없음)·'pending'·'section'·'omitted'·'absent'."""
    if html is None:
        return 'none'
    if C.PENDING in html:
        return 'pending'
    if 'data-contested=' in html:
        return 'section'
    if C.OMIT_RE.search(html):
        return 'omitted'
    return 'absent'


def plan(prev, page, date):
    """이번 tick 에 할 일 — 'analyze'·'fill'·'clear'·'skip'."""
    done = C.settled(prev, 'us', date)
    if page in ('section', 'omitted'):
        return 'skip'                         # 발행 증거가 묶였다 — 그 날짜 결과는 바꾸지 않는다
    if not done:
        return 'analyze'
    if page == 'pending':
        return 'fill' if prev['status'] == 'ok' else 'clear'
    return 'skip'


def gates(clone, rel, json_path, date):
    """발행 게이트(쟁점 섹션을 채운 뒤) — (통과 여부, 출력 끝)."""
    py = sys.executable
    cmds = [[py, 'scripts/apply_readability.py', rel], [py, 'scripts/apply_colors.py', rel],
            [py, 'scripts/check_contested.py', '--html', rel, '--json', json_path,
             '--market', 'us', '--date', date],
            [py, 'scripts/check_readability.py', '--strict', '--no-inline-images', rel],
            [py, 'scripts/check_style.py', rel]]
    for c in cmds:
        p = subprocess.run(c, cwd=clone, capture_output=True, text=True, timeout=300)
        if p.returncode:
            return False, f'{c[1]}: {(p.stdout + p.stderr).strip()[-400:]}'
    return True, ''


def fill(clone, date, payload):
    """발행본의 자리표시를 채운다(또는 지운다) → 바뀐 파일 목록과 메모."""
    sys.path.insert(0, os.path.join(clone, 'scripts'))
    import render_contested as R
    rel = f'news/{date}.html'
    path = os.path.join(clone, rel)
    with open(path, encoding='utf-8') as fh:
        before = fh.read()
    jpath = os.path.join(clone, 'data', 'contested', 'us', f'{date}.json')
    after = R.apply(before, payload)
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(after)
    if payload.get('status') != 'ok':
        return [rel], 'cleared'
    ok, why = gates(clone, rel, jpath, date)
    if ok:
        return [rel], 'filled'
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(R.apply(before, payload, omit='gate_failed'))
    ok2, why2 = gates(clone, rel, jpath, date)
    if not ok2:
        raise RuntimeError(f'생략 뒤에도 게이트 실패 — {why2}')
    return [rel], f'omitted({why[:120]})'


class Interrupted(BaseException):
    """launchd·런처가 보낸 SIGTERM — 일반 예외 처리에 삼켜지지 않게(3차 P2)."""


STATE = os.path.expanduser('~/Library/Caches/fdo2a-contested-state.json')
ANALYZE_MAX_HOURS = 36        # 기준일 발행 뒤 이만큼 지나면 분석하지 않고 자리표시를 지운다


def _attempts_local(date, bump=False):
    """날짜별 시도 횟수를 로컬에도 적는다 — 푸시가 계속 실패해도 3회 상한이 걸린다(3차 P2)."""
    try:
        with open(STATE, encoding='utf-8') as fh:
            st = json.load(fh)
        st = st if isinstance(st, dict) else {}
    except (OSError, ValueError):
        st = {}
    n = st.get(date) if isinstance(st.get(date), int) else 0
    if bump and os.environ.get('CONTESTED_DRY'):
        return n + 1                       # 시험 운행은 실제 시도 횟수를 쓰지 않는다
    if bump:
        st[date] = n + 1
        st = {k: v for k, v in st.items() if isinstance(v, int)}
        tmp = STATE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(dict(sorted(st.items())[-30:]), fh)
        os.replace(tmp, STATE)
        return n + 1
    return n


def _normalize(prev):
    if not isinstance(prev, dict):
        return None
    if not isinstance(prev.get('attempts'), int) or isinstance(prev.get('attempts'), bool):
        prev = dict(prev, attempts=0)
    return prev


def push(clone, files, msg, page_shas):
    _git(clone, 'add', *files)
    if not _git(clone, 'status', '--porcelain', '--untracked-files=no', check=False):
        return 'nothing'
    base = _git(clone, 'rev-parse', 'HEAD')
    _git(clone, 'commit', '-q', '-m', msg)
    if subprocess.run(['git', 'push', '-q', 'origin', 'HEAD:main'], cwd=clone).returncode == 0:
        return 'pushed'
    _git(clone, 'fetch', '-q', 'origin', 'main')
    for f, sha in page_shas.items():
        if _git(clone, 'rev-parse', f'origin/main:{f}', check=False) != sha:
            return f'abandoned: {f} 가 그 사이 바뀌었다'
    # 그 사이 게이트·러너 코드가 바뀌었으면 옛 코드로 검사한 결과를 밀지 않는다 — 다음 tick 에 새 코드로
    moved = _git(clone, 'diff', '--name-only', base, 'origin/main', '--', 'scripts', '.claude', check=False)
    if moved:
        return 'abandoned: 코드가 그 사이 바뀌었다'
    if subprocess.run(['git', 'rebase', '-q', 'origin/main'], cwd=clone).returncode:
        subprocess.run(['git', 'rebase', '--abort'], cwd=clone)
        return 'abandoned: rebase 충돌'
    if subprocess.run(['git', 'push', '-q', 'origin', 'HEAD:main'], cwd=clone).returncode:
        return 'abandoned: push 거절'
    return 'pushed'


def _market_for(clone, date, temp):
    """그 기준일의 완성된 market_data.json 을 히스토리에서 찾아 임시 폴더에 둔다 → (datadir, commit)."""
    for oid in _git(clone, 'log', '--format=%H', '-n', '40', '--', 'data/market_data.json').split():
        raw = _git(clone, 'show', f'{oid}:data/market_data.json', check=False)
        try:
            md = json.loads(raw)
        except ValueError:
            continue
        if md.get('report_date') == date and md.get('complete'):
            d = os.path.join(temp, f'data-{date}')
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, 'market_data.json'), 'w', encoding='utf-8') as fh:
                fh.write(raw)
            return d, oid
    return None, None


def _dates(clone, md):
    """볼 날짜 — 현재 기준일 + 자리표시가 남은 최근 발행본(시장 기준일이 넘어가도 놓치지 않게, 3차 P1)."""
    out = []
    if md.get('report_date'):
        out.append(md['report_date'])
    today = datetime.now(KST).date()
    for name in sorted(os.listdir(os.path.join(clone, 'news')) if os.path.isdir(os.path.join(clone, 'news')) else []):
        m = re.fullmatch(r'(\d{4}-\d{2}-\d{2})\.html', name)
        if not m or m.group(1) in out:
            continue
        if (today - datetime.fromisoformat(m.group(1)).date()).days > MAX_AGE_DAYS:
            continue
        with open(os.path.join(clone, 'news', name), encoding='utf-8') as fh:
            if C.PENDING in fh.read():
                out.append(m.group(1))
    return sorted(out)


def handle(clone, temp, date, md_current, notes):
    """한 날짜 → (바뀐 파일, 발행본 sha, 메모) 또는 None(할 일 없음)."""
    rel_json = f'data/contested/us/{date}.json'
    jpath = os.path.join(clone, rel_json)
    prev = _normalize(_load(jpath))
    page_rel = f'news/{date}.html'
    page_path = os.path.join(clone, page_rel)
    html = open(page_path, encoding='utf-8').read() if os.path.exists(page_path) else None
    shas = {page_rel: _git(clone, 'rev-parse', f'HEAD:{page_rel}', check=False)} if html else {}
    todo = plan(prev, page_state(html), date)
    if todo == 'skip':
        return None
    files = []
    if todo == 'analyze':
        age_h = (datetime.now(KST) - datetime.fromisoformat(date).replace(tzinfo=KST)).total_seconds() / 3600
        attempts = max((prev or {}).get('attempts', 0), _attempts_local(date))
        if age_h > ANALYZE_MAX_HOURS + 24 or attempts >= C.MAX_ATTEMPTS:
            reason = 'stale' if age_h > ANALYZE_MAX_HOURS + 24 else 'attempts_exhausted'
            result = _final_error(date, prev, reason)
        else:
            result = analyze_date(clone, temp, date, md_current, prev)
        _save(jpath, result)
        files.append(rel_json)
        with open(os.path.expanduser('~/Library/Caches/fdo2a-contested-last.json'), 'w') as fh:
            json.dump(result, fh, ensure_ascii=False, indent=1)
        note = f'{result["status"]}({result.get("reason") or "-"})'
        if html is not None and page_state(html) == 'pending' and C.settled(result, 'us', date):
            f, n = fill(clone, date, result)
            files += f
            note += f' · 발행본 {n}'
    else:
        result = prev
        f, n = fill(clone, date, result)
        files += f
        note = f'{result["status"]} · 발행본 {n}'
    topic = ((result or {}).get('event') or {}).get('topic_ko') or ''
    notes.append(f'{date} {note}' + (f' · {topic}' if topic else ''))
    return files, (shas if any(f.startswith('news/') for f in files) else {})


def _base(date, attempts):
    import contested_build as Bld
    now = datetime.now(timezone.utc).isoformat(timespec='seconds')
    return {'schema_version': C.SCHEMA_VERSION, 'market': 'us', 'span': 'daily', 'report_date': date,
            'status': 'error', 'reason': 'unknown', 'retryable': True, 'attempts': attempts,
            'collected_at': now, 'cutoff_at': now,
            'model': {k: Bld.MODELS[k] for k in ('pick', 'extract', 'verify')},
            'prompt_version': C.PROMPT_VERSION, 'market_snapshot': None, 'counts': {},
            'diagnostics': {'runner': 'local'}, 'event': {'topic_ko': '', 'query': '', 'trigger': []}}


def _final_error(date, prev, reason):
    b = _base(date, max((prev or {}).get('attempts', 0), _attempts_local(date)))
    return dict(b, status='error', reason=reason, retryable=False)


def analyze_date(clone, temp, date, md_current, prev):
    """수집·분석 한 번 → 결과 dict. 어떤 실패도 결과로 남긴다(3차 P2)."""
    from collect_contested import collect
    import contested_build as Bld
    attempts = max((prev or {}).get('attempts', 0), _attempts_local(date)) + 1
    _attempts_local(date, bump=True)              # 모델을 부르기 전에 적는다
    base = _base(date, attempts)
    try:
        if md_current.get('report_date') == date and md_current.get('complete'):
            datadir, oid = 'data', None
        else:
            datadir, oid = _market_for(clone, date, temp)
            if not datadir:
                return dict(base, status='error', reason='market_data_not_found', retryable=True)
        bundle = collect(date, datadir, rank=Bld.ranker(diag=base['diagnostics']))
        if oid and isinstance(bundle.get('market_snapshot'), dict):
            bundle['market_snapshot'] = dict(bundle['market_snapshot'], path='data/market_data.json',
                                             commit=oid)
        base['counts'] = {'harvest': bundle.get('harvest'),
                          'candidates': len(bundle.get('candidates') or []),
                          'articles': [len(c['articles']) for c in bundle.get('candidates') or []]}
        base['diagnostics'].update(gdelt=bundle.get('gdelt'), hosts=bundle.get('hosts'),
                                   notes=bundle.get('notes'))
        result = Bld.analyze(bundle, base)
    except Interrupted:
        raise
    except Exception as e:
        result = dict(base, status='error', reason=f'analyze_{type(e).__name__}'[:40], retryable=True)
    if result.get('status') != 'ok' and attempts >= C.MAX_ATTEMPTS:
        result['retryable'] = False                # 시도를 다 썼다 — 자리표시를 지운다
    return result


def tick(root, date=None, dry=False):
    if dry:
        os.environ['CONTESTED_DRY'] = '1'
    remote = _git(root, 'remote', 'get-url', 'origin')
    with tempfile.TemporaryDirectory(prefix='contested-') as temp:
        clone = os.path.join(temp, 'repo')
        _git(temp, 'clone', '-q', '--no-local', '--single-branch', '--branch', 'main', '--depth', '80',
             remote, clone, timeout=300)
        os.chdir(clone)                      # 스냅샷(git log)·게이트가 clone 기준으로 돈다
        md = _load(os.path.join(clone, 'data', 'market_data.json')) or {}
        dates = [C.iso_date(date)] if date else _dates(clone, md)
        files, shas, notes = [], {}, []
        analyzed = False
        for d in dates:
            prev = _normalize(_load(os.path.join(clone, f'data/contested/us/{d}.json')))
            page = os.path.join(clone, f'news/{d}.html')
            html = open(page, encoding='utf-8').read() if os.path.exists(page) else None
            if plan(prev, page_state(html), d) == 'analyze' and analyzed:
                continue                       # 한 tick 에 분석은 한 날짜만 — 한도를 몰아 쓰지 않는다
            got = handle(clone, temp, d, md, notes)
            if got:
                files += got[0]
                shas.update(got[1])
                analyzed = analyzed or any(f.startswith('data/') for f in got[0])
        if not files:
            return 'skip: 할 일 없음 ' + ' '.join(dates)
        if dry:
            return 'dry-run: ' + ' / '.join(notes)
        msg = 'data: contested analysis us — ' + ' / '.join(notes) + \
            '\n\n로컬 러너(claude -p, 구독)가 만든 쟁점 분석 결과.'
        return ' / '.join(notes) + ' · ' + push(clone, sorted(set(files)), msg, shas)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['run'])
    ap.add_argument('--date', type=C.iso_date)
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args(argv)
    root = _git(os.getcwd(), 'rev-parse', '--show-toplevel')
    os.makedirs(os.path.dirname(LOCK), exist_ok=True)
    with open(LOCK, 'w') as lk:
        try:
            fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print('[쟁점] 다른 tick 이 돌고 있다')
            return 0
        def _term(*_):
            raise Interrupted()
        signal.signal(signal.SIGTERM, _term)
        try:
            print(f'[쟁점 {datetime.now(KST):%m-%d %H:%M}] {tick(root, a.date, a.dry_run)}')
        except Interrupted:
            print('[쟁점] SIGTERM — 정리하고 끝낸다(시도 횟수는 이미 적었다)', file=sys.stderr)
            return 143
        except Exception as e:
            print(f'[쟁점] 실패 — {type(e).__name__}: {str(e)[:300]}', file=sys.stderr)
            return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
