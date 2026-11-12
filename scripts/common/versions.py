#!/usr/bin/env python3
"""수집 자료 판 관리 — 실행 원본 보관·발행된 날 동결·발행판 보관·수동 승격(1단계, 2026-11-10).

    python3 scripts/common/versions.py commit --market kr --mode shadow|enforce --message "<msg>" [--force]
    python3 scripts/common/versions.py promote --market kr --date D --field ledger.indices.KOSDAQ \
        (--value 644.27 | --from <run_id>) --reason "<사유>"
    python3 scripts/common/versions.py verify-published --market kr --date D

commit 은 워크플로의 마지막 단계다. 오늘의 Commit data 와 같은 경로로 로컬 커밋 O 를 만든 뒤
임시 작업 폴더에서 원격 최신 위에 다시 세워 한 번에 push 한다. 판정·재구성 중 무엇이든 실패하면
  shadow            → O 를 그대로 `push_with_retry.sh` 로(오늘과 같은 결과) + 폴백 기록·::warning::
                      (보호가 꺼진 실행이며 동결 성공으로 세지 않는다)
  enforce·발행됨    → 반영 보류(push 없음, ::warning::) — 무보호 덮어쓰기 금지
  enforce·미발행    → 보호 폴백: 매 시도 원격에서 발행 여부를 다시 보고 O 만 올린다. 폴백 자신이
                      실패하면 push 없이 실패로 끝낸다(무보호 경로로 내려가지 않는다)

모드: shadow(기본) = 고정 경로는 오늘과 같은 바이트, 원본·판정·발행판만 기록.
      enforce      = 원격에서 이미 발행된 거래일 D 의 값은 발행 커밋 P 트리로 둔다.
spec: docs/superpowers/specs/2026-11-10-kr-data-versions.md
"""
import argparse
import datetime as _dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

KST = _dt.timezone(_dt.timedelta(hours=9))
PIN_LOOKBACK = 10
ATTEMPTS = 5
REMOTE = 'origin'
BRANCH = 'main'


class Fallback(RuntimeError):
    """판정·재구성을 끝낼 수 없다 — 오늘 경로로 내려간다."""


# ── git ───────────────────────────────────────────────────────────────

def git(repo, *args, check=True, data=None):
    r = subprocess.run(['git', '-C', repo, *args], input=data, capture_output=True)
    if check and r.returncode != 0:
        raise Fallback(f'git {" ".join(args[:3])} 실패: {r.stderr.decode(errors="replace")[:200]}')
    return r


def out(repo, *args):
    return git(repo, *args).stdout.decode().strip()


def show(repo, rev, path):
    r = git(repo, 'show', f'{rev}:{path}', check=False)
    return r.stdout if r.returncode == 0 else None


def exists(repo, rev, path):
    return git(repo, 'cat-file', '-e', f'{rev}:{path}', check=False).returncode == 0


def publish_commit(repo, rev, path):
    """`path` 를 처음 들인 커밋(발행 커밋 P). 없으면 None."""
    r = git(repo, 'log', rev, '--diff-filter=A', '--format=%H', '--', path, check=False)
    shas = r.stdout.decode().split()
    return shas[-1] if r.returncode == 0 and shas else None


def tree_files(repo, rev, prefix):
    r = git(repo, 'ls-tree', '-r', '--name-only', rev, '--', prefix, check=False)
    return r.stdout.decode().split() if r.returncode == 0 else []


def sha256(b):
    return hashlib.sha256(b).hexdigest()


def jload(b):
    try:
        return json.loads(b) if b is not None else None
    except ValueError:
        return None


def jdump(obj):
    return (json.dumps(obj, ensure_ascii=False, indent=2) + '\n').encode()


# ── 실행 ID·필드 상태·차이 ──────────────────────────────────────────────

def run_id(now=None, env=None):
    env = os.environ if env is None else env
    now = (now or _dt.datetime.now(_dt.timezone.utc)).astimezone(_dt.timezone.utc)
    stamp = now.strftime('%Y%m%dT%H%M%SZ')
    if env.get('GITHUB_RUN_ID'):
        return f'{stamp}-gh{env["GITHUB_RUN_ID"]}.{env.get("GITHUB_RUN_ATTEMPT", "1")}'
    return f'{stamp}-local-{uuid.uuid4().hex}'


# 아시아 이웃 시장의 현지 시간대 — 현지 자정 뒤 yfinance 일봉은 마지막 완료 봉이 빠진다(17커밋 관측).
PEER_TZ = {'닛케이': 9, '항셍': 8, '상해종합': 8, '대만가권': 8}


def _after_local_midnight(date, collected_utc, offset_h):
    local = collected_utc.astimezone(_dt.timezone(_dt.timedelta(hours=offset_h))).date()
    return local > _dt.date.fromisoformat(date)


def field_status(files, date, collected_utc):
    """yfinance 유래 필드의 지정 거래일 확인 — 기록만(1단계는 고정 경로를 바꾸지 않는다)."""
    st = {}
    sess = jload(files.get('kr/data/kr_session.json')) or {}
    for name, d in (((sess.get('asia_peers') or {}).get('dates')) or {}).items():
        if d == date:
            st[f'asia_peers.{name}'] = 'ok'
        elif _after_local_midnight(date, collected_utc, PEER_TZ.get(name, 9)):
            st[f'asia_peers.{name}'] = 'unverified_target_date'
        else:
            st[f'asia_peers.{name}'] = 'stale_or_holiday'
    tech = jload(files.get('kr/data/kr_technical.json')) or {}
    after_kst = _after_local_midnight(date, collected_utc, 9)
    for name, row in tech.items():
        if not isinstance(row, dict):
            continue
        ok = row.get('as_of') == date and row.get('close') is not None
        st[f'technical.{name}'] = 'ok' if ok else ('unverified_target_date' if after_kst else 'stale_or_holiday')
    moves = jload(files.get('kr/data/kr_stock_moves.json'))
    if isinstance(moves, list):
        st['stock_moves'] = f'n={len(moves)}' + (' after_midnight' if after_kst else '')
    return st


def _keyed(rows):
    if isinstance(rows, list) and rows and all(isinstance(r, dict) for r in rows):
        for k in ('name', 'label'):
            if all(k in r for r in rows):
                return {r[k]: r for r in rows}
    return None


def diff_files(base, new):
    """{path: bytes} 두 묶음의 차이 — 파일 단위 + 이름 붙은 목록이면 바뀐 행 이름."""
    outd = {}
    for path in sorted(set(base) | set(new)):
        a, b = base.get(path), new.get(path)
        if a == b:
            continue
        if a is None:
            outd[path] = {'class': 'filled_in_revision'}
            continue
        if b is None:
            outd[path] = {'class': 'missing_in_revision'}
            continue
        ent = {'class': 'changed'}
        ja, jb = jload(a), jload(b)
        ka, kb = _keyed(ja), _keyed(jb)
        if ka is not None and kb is not None:
            ch = sorted(n for n in set(ka) | set(kb) if ka.get(n) != kb.get(n))
            ent.update(rows_changed=len(ch), rows_total=len(ka), examples=ch[:20])
        elif isinstance(ja, dict) and isinstance(jb, dict):
            ent['keys_changed'] = sorted(k for k in set(ja) | set(jb) if ja.get(k) != jb.get(k))[:40]
        outd[path] = ent
    return outd


# ── 시장 어댑터(지금은 KR 만) ─────────────────────────────────────────────

def adapter(market):
    if market == 'kr':
        from kr import versions_kr
        return versions_kr
    raise SystemExit(f'지원하지 않는 시장: {market}')


def _week_key(date):
    from us.period import week_key
    return week_key(date)


def _jsonl(b):
    rows = []
    for line in (b or b'').decode().splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    return rows


def _jsonl_dump(rows):
    return ''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows).encode()


def snapshot(repo, rev, A, date):
    """한 커밋 트리에서 그 실행·발행판의 산출 묶음 {path: bytes}."""
    files = {}
    key = _week_key(date)
    for p in tree_files(repo, rev, A.DATA) + tree_files(repo, rev, 'kr/assets'):
        if A.is_frozen(p, date, key):
            b = show(repo, rev, p)
            if b is not None:
                files[p] = b
    return files


def worktree_snapshot(repo, A, date):
    """작업 트리(디스크)의 산출 묶음 — 커밋 전 원본 보존용."""
    files, key = {}, _week_key(date)
    for top in (A.DATA, 'kr/assets'):
        for d, _dirs, names in os.walk(os.path.join(repo, top)):
            for n in names:
                rel = os.path.relpath(os.path.join(d, n), repo)
                if A.is_frozen(rel, date, key):
                    with open(os.path.join(repo, rel), 'rb') as f:
                        files[rel] = f.read()
    return files


def _session_inputs(files, A):
    return {p: jload(files.get(p)) for p in A.SESSION_INPUTS} if files else None


def promotions(repo, rev, market, dates):
    outd = {}
    for d in dates:
        base = f'versions/{market}/{d}/promotions/'
        for p in sorted(tree_files(repo, rev, base)):
            if p.endswith('.json'):
                rec = jload(show(repo, rev, p))
                if rec:
                    outd.setdefault(d, []).append(rec)
    return outd


def _week_dates(key, rows):
    return sorted({r.get('report_date') for r in rows if r.get('report_date') and _week_key(r['report_date']) == key})


def _write(repo, path, data):
    full = os.path.join(repo, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, 'wb') as f:
        f.write(data)


def _remove(repo, path):
    full = os.path.join(repo, path)
    if os.path.exists(full):
        os.remove(full)


# ── 발행판 보관 ────────────────────────────────────────────────────────

def pin_files(repo, rev, A, market, date):
    """발행 커밋 P 트리에서 발행판 묶음. P 가 없으면 None."""
    post = A.POST.format(date=date)
    P = publish_commit(repo, rev, post)
    if not P:
        return None
    files = snapshot(repo, P, A, date)
    rec_path = A.RECORD.format(date=date)
    rec = show(repo, P, rec_path)
    post_b = show(repo, P, post)
    meta = {'market': market, 'date': date, 'publish_commit': P, 'source': 'publish_commit_tree',
            'post': {'path': post, 'sha256': sha256(post_b or b'')},
            'record': {'path': rec_path, 'sha256': sha256(rec)} if rec is not None else None,
            'files': {p: sha256(b) for p, b in sorted(files.items())},
            'stance_next_sha256': sha256(show(repo, P, 'kr/data/kr_stance.json') or b''),
            'stance_prev_sha256_estimated': sha256(show(repo, f'{P}^', 'kr/data/kr_stance.json') or b''),
            'pinned_at': _dt.datetime.now(KST).isoformat(timespec='seconds')}
    base = f'versions/{market}/{date}/published/'
    outd = {base + 'files/' + p: b for p, b in files.items() if not p.endswith('.png')}   # 차트는 해시만
    outd[base + 'published.json'] = jdump(meta)
    return outd


def missing_pins(repo, rev, A, market):
    posts = sorted(p for p in tree_files(repo, rev, os.path.dirname(A.POST.format(date='x')))
                   if p.endswith('.html') and len(os.path.basename(p)) == len('2026-01-01.html'))
    dates = [os.path.basename(p)[:-5] for p in posts][-PIN_LOOKBACK:]
    return [d for d in dates if not exists(repo, rev, f'versions/{market}/{d}/published/published.json')]


# ── commit ────────────────────────────────────────────────────────────

class Worktree:
    """원격 최신을 펼친 임시 작업 폴더 — 원래 작업 트리(다른 작업의 미커밋 변경·미추적 파일)는 건드리지 않는다
    (codex 구현 검토 1회 #2). 객체 저장소는 같아서 O 를 cherry-pick 할 수 있다."""

    def __init__(self, repo, rev):
        self.repo = repo
        self.path = tempfile.mkdtemp(prefix='versions-wt-')
        try:
            git(repo, 'worktree', 'add', '-q', '--detach', self.path, rev)
        except Exception:
            self.close()                                # 생성 실패도 정리한다(구현 검토 2회 #15)
            raise

    def close(self):
        git(self.repo, 'worktree', 'remove', '--force', self.path, check=False)
        shutil.rmtree(self.path, ignore_errors=True)
        git(self.repo, 'worktree', 'prune', check=False)


def _stage(repo, A):
    """옛 Commit data 의 add 줄 그대로. 첫 줄 실패 = 오늘처럼 단계 실패."""
    r = subprocess.run(['bash', '-e', '-c', A.STAGE_SH], cwd=repo)
    if r.returncode != 0:
        raise SystemExit(r.returncode)
    return git(repo, 'diff', '--cached', '--quiet', check=False).returncode != 0


def _report_date(repo, A):
    with open(os.path.join(repo, A.MARKET_DATA), encoding='utf-8') as f:
        return json.load(f)['report_date']


def _save_run(dest, rdir, files, manifest=None):
    for p, b in files.items():
        _write(dest, rdir + 'files/' + p, b)
    if manifest is not None:
        _write(dest, rdir + 'manifest.json', jdump(manifest))


def reconcile(repo, wt, A, market, date, O, base, rid, mode, collected_utc, tmpdir=None):
    """임시 작업 폴더 wt(원격 최신) 위에 이번 실행을 다시 세운다. → manifest dict."""
    target = f'{REMOTE}/{BRANCH}'
    key = _week_key(date)
    post = A.POST.format(date=date)
    published = exists(repo, target, post)
    P = publish_commit(repo, target, post) if published else None
    if 'no_publish_commit' in os.environ.get('VERSIONS_TEST_FAIL', '').split(','):
        P = None                                       # 시험 전용 — 발행 커밋 조회 실패
    run_files = snapshot(repo, O or base, A, date)
    p_files = snapshot(repo, P, A, date) if P else None
    changes = []
    if O:
        for line in out(repo, 'diff', '--name-status', base, O).splitlines():
            st, _, path = line.partition('\t')
            changes.append((st, path))
    freeze = mode == 'enforce' and published

    if not freeze:
        if O and git(wt, 'cherry-pick', '--allow-empty', '--keep-redundant-commits', O, check=False).returncode != 0:
            git(wt, 'cherry-pick', '--abort', check=False)
            raise Fallback('원격 최신 위에 이번 수집을 올리다 충돌')
    else:
        for st, path in changes:
            if A.is_frozen(path, date, key):
                continue
            if show(repo, target, path) != show(repo, base, path):     # 원격도 바꿨다 — 덮지도 버리지도 않는다
                raise Fallback(f'원격과 같은 경로를 바꿨다: {path}')
            if st.startswith('D'):
                _remove(wt, path)
            else:
                b = show(repo, O, path)
                if b is not None:
                    _write(wt, path, b)
        if P:                                          # 동결 결과 = P 트리(없으면 없음, #5)
            dated = {p for p in set(run_files) | set(p_files) | set(snapshot(repo, target, A, date))
                     if A.is_dated(p, date)}
            for path in sorted(dated):
                if path in p_files:
                    _write(wt, path, p_files[path])
                else:
                    _remove(wt, path)
        else:                                          # 발행됐는데 P 를 못 찾음 — 덮지 않고 보류(구현 검토 3회 #18)
            raise Fallback('발행이 확인됐는데 발행 커밋을 찾지 못했다')
    if freeze or mode == 'enforce':
        _overlay_shared(repo, wt, A, market, date, run_files, p_files, freeze, target)

    manifest = {
        'market': market, 'trade_date': date, 'run_id': rid, 'mode': mode,
        'collected_at_utc': collected_utc.isoformat(timespec='seconds'),
        'collected_at_kst': collected_utc.astimezone(KST).isoformat(timespec='seconds'),
        'trigger': os.environ.get('GITHUB_EVENT_NAME', 'local'),
        'published_on_remote': published, 'publish_commit': P,
        'frozen': freeze, 'would_freeze': (mode == 'shadow' and published),
        'changes': [{'status': s_, 'path': p_} for s_, p_ in changes],
        'files': {p: sha256(b) for p, b in sorted(run_files.items())},
        'field_status': field_status(run_files, date, collected_utc),
        'diff_vs_published': diff_files(p_files, run_files) if p_files else None,
    }
    if hasattr(A, 'run_checks'):                       # 검사 기록 사본 — 기록만(고정 경로·동결 불변, 2026-11-12)
        manifest['checks'] = A.run_checks(run_files)
        manifest['field_status'].update(A.checks_field_status(manifest['checks']))
    rdir = f'versions/{market}/{date}/runs/{rid}/'
    if exists(repo, target, rdir + 'manifest.json'):
        raise Fallback(f'같은 실행 ID 의 원본이 이미 있다: {rid}')
    # 바이트 복사는 원격 판과 다른 파일만 — 같은 파일은 manifest 의 sha256 과 원격 커밋으로 복원된다
    # (PNG 도 같다 — 원격에 없거나 다르면 바이트를 남긴다, #6).
    tsha = out(repo, 'rev-parse', target)
    stored, copy = {}, {}
    for p, b in run_files.items():
        if show(repo, target, p) == b:
            stored[p] = f'remote@{tsha}'
        else:
            copy[p] = b
            stored[p] = 'copied'
    manifest['stored'] = stored
    _save_run(wt, rdir, copy, manifest)
    for d in missing_pins(repo, target, A, market):
        for p, b in (pin_files(repo, target, A, market, d) or {}).items():
            _write(wt, p, b)
    if tmpdir:
        try:
            _write(tmpdir, rdir + 'manifest.json', jdump(manifest))
        except OSError:
            pass
    return manifest


def published_dates(repo, rev, A, key):
    """그 주에 원격에 일간 글이 있는 날짜."""
    d = os.path.dirname(A.POST.format(date='x'))
    return sorted(os.path.basename(p)[:-5] for p in tree_files(repo, rev, d)
                  if p.endswith('.html') and len(os.path.basename(p)) == len('2026-01-01.html')
                  and _week_key(os.path.basename(p)[:-5]) == key)


def _overlay_shared(repo, wt, A, market, date, run_files, p_files, frozen, target):
    """원장 D 행·그 주 주간 파일. 동결이면 P 트리 기준. 승격은 enforce 에서만 맨 마지막(shadow 는 오늘과 같은 바이트, #9)."""
    key = _week_key(date)
    head = 'HEAD'
    ledger_now = _jsonl(show(wt, target if frozen else head, A.LEDGER))
    promos = promotions(repo, target, market, _week_dates(key, ledger_now) + [date])
    pub = published_dates(repo, target, A, key)
    wpath = A.WEEKLY.format(key=key)
    if not frozen and not promos:
        # enforce 미발행일: 고정 경로는 이번 실행 그대로, 단 발행된 날의 지수 빈 칸이면 주간을 보류한다
        _hold_weekly_in(wt, repo, A, date, target)
        return
    rows = A.merge_ledger(ledger_now, A.ledger_row(_session_inputs(run_files, A)),
                          A.ledger_row(_session_inputs(p_files, A)) if p_files else None,
                          date, frozen, promos)
    _write(wt, A.LEDGER, _jsonl_dump(rows))
    remote_agg = jload(show(wt, target if frozen else head, wpath))
    run_in, p_in = (_session_inputs(run_files, A), _session_inputs(p_files, A)) if frozen else (None, None)
    agg = A.merge_week(remote_agg, run_in, p_in, date, frozen, promos, rows, key, published_dates=pub)
    _write(wt, wpath, jdump(agg))


def _fallback(repo, market, date, O, rid, msg, reason):
    """오늘 방식 — 원래 작업 트리는 O 그대로라 soft reset 으로 O 의 변경을 다시 스테이징한다."""
    print(f'::warning::versions fallback — 동결 보호 비활성({reason}). 오늘 방식으로 올린다.')
    if not O:
        print('변경 없음 — 폴백도 push 하지 않는다')
        return 0
    git(repo, 'reset', '-q', '--soft', f'{O}^')
    try:                                               # 기록 실패가 오늘 경로를 막지 않는다(#4)
        if 'fallback_record' in os.environ.get('VERSIONS_TEST_FAIL', '').split(','):
            raise OSError('시험용')
        rec = {'market': market, 'trade_date': date, 'run_id': rid, 'reason': reason[:300],
               'at': _dt.datetime.now(KST).isoformat(timespec='seconds'), 'protection': 'disabled'}
        path = f'versions/{market}/{date}/fallback/{rid}.json'
        _write(repo, path, jdump(rec))
        git(repo, 'add', '--', path)
    except Exception as e:  # noqa: BLE001
        print(f'::warning::폴백 기록 실패({e}) — 기록 없이 올린다', file=sys.stderr)
    r = subprocess.run(['bash', os.path.join(repo, 'scripts/ci/push_with_retry.sh'), msg], cwd=repo)
    return r.returncode


def _hold(market, date, rid, reason, saved):
    """enforce — 발행된 날(또는 발행 여부를 확인할 수 없을 때) 무보호 덮어쓰기 대신 반영을 보류한다(사용자 정책 11/10)."""
    where = '원본은 artifact 에 있다' if saved else '원본 저장도 실패했다 — 이 실행의 값은 남지 않는다'
    print(f'::warning::versions hold — {market} {date}: {reason}. 고정 경로를 바꾸지 않고 이 실행 {rid} 의 '
          f'반영을 보류한다. {where}.')
    return 0


def _hold_weekly_in(wt, repo, A, date, target):
    """작업 폴더 wt 의 주간 파일에 발행일 지수 빈 칸 보류를 원장 기준으로 적용. 바뀌었으면 True."""
    key = _week_key(date)
    wpath = A.WEEKLY.format(key=key)
    agg = jload(show(wt, 'HEAD', wpath))
    if agg is None:
        return False
    before = json.dumps(agg, sort_keys=True)
    A.hold_published_gaps(agg, published_dates(repo, target, A, key), _jsonl(show(wt, 'HEAD', A.LEDGER)))
    if json.dumps(agg, sort_keys=True) == before:
        return False
    _write(wt, wpath, jdump(agg))
    return True


def _guarded_fallback(repo, A, market, date, O, rid, saved, reason):
    """enforce 미발행일 폴백 — 오늘처럼 O 를 원격 최신 위에 올리되, 매 시도 원격에서 발행 여부를 다시 본다.
    pull --rebase 로 새 글을 받은 뒤 그날 값을 덮는 경로를 막는다(구현 검토 2회 #11). 폴백 자신의
    내부 실패는 무보호 스크립트로 내려가지 않고 실패로 끝낸다(5회 #1).
    """
    print(f'::warning::versions fallback(enforce, 미발행일) — 판 기록 없이 오늘 방식으로 올린다({reason})')
    if not O:
        return 0
    post = A.POST.format(date=date)
    target = f'{REMOTE}/{BRANCH}'
    for attempt in range(1, ATTEMPTS + 1):
        if git(repo, 'fetch', '-q', REMOTE, BRANCH, check=False).returncode != 0:
            return _hold(market, date, rid, '원격 최신을 볼 수 없어 발행 여부를 확인하지 못했다', saved)
        if exists(repo, target, post):
            return _hold(market, date, rid, '그 사이 발행됐다', saved)
        wt = None
        try:
            if 'guarded_worktree' in os.environ.get('VERSIONS_TEST_FAIL', '').split(','):
                raise Fallback('시험용 worktree 실패')
            wt = Worktree(repo, target)
            if git(wt.path, 'cherry-pick', '--allow-empty', '--keep-redundant-commits', O, check=False).returncode != 0:
                git(wt.path, 'cherry-pick', '--abort', check=False)
                print('원격 최신 위에 이번 수집을 올리다 충돌 — 오늘 push_with_retry 와 같은 실패', file=sys.stderr)
                return 1
            if _hold_weekly_in(wt.path, repo, A, date, target):     # 폴백에서도 발행일 빈 칸 보류(#19·4회 #3)
                git(wt.path, 'add', '--', A.WEEKLY.format(key=_week_key(date)))
                git(wt.path, 'commit', '-q', '--amend', '--no-edit')
            if git(wt.path, 'push', '-q', REMOTE, f'HEAD:{BRANCH}', check=False).returncode == 0:
                return 0
        except Exception as e:  # noqa: BLE001 — 폴백 자신의 실패: enforce 는 무보호 경로로 내려가지 않는다(5회 #1·#2)
            print(f'::error::보호 폴백 내부 실패({e}) — enforce 에서는 무보호 push 를 하지 않는다. '
                  f'반영하지 않고 실패로 끝낸다(루틴은 수집 실패로 본다). 원본은 '
                  f'{"artifact 에 있다" if saved else "남지 않았다"}', file=sys.stderr)
            return 1
        finally:
            if wt:
                wt.close()
        print(f'push 거절 {attempt}/{ATTEMPTS}', file=sys.stderr)
    return 1


def cmd_commit(a):
    if os.environ.get('GITHUB_ACTIONS') != 'true' and not a.scratch_checkout:
        print('거부: commit 은 일회성 checkout(Actions) 전용이다 — 원래 브랜치에 동결을 거치지 않은 수집 커밋이 '
              '남는다. 시험·수동 실행은 버릴 clone 에서 --scratch-checkout 으로.', file=sys.stderr)
        return 2
    repo, A = a.repo, adapter(a.market)
    date = _report_date(repo, A)
    base = out(repo, 'rev-parse', 'HEAD')
    post = A.POST.format(date=date)
    published = exists(repo, base, post)               # fetch 가 한 번도 안 되면 job 시작 checkout 기준
    rid = run_id()
    collected = _dt.datetime.now(_dt.timezone.utc)
    rdir = f'versions/{a.market}/{date}/runs/{rid}/'
    saved = False
    if a.tmpdir:                                      # 어떤 실패에도 원본이 남게 — 스테이징·커밋 전에(#21)
        try:
            _save_run(a.tmpdir, rdir, worktree_snapshot(repo, A, date))
            saved = True
        except OSError as e:
            print(f'::warning::실행 원본 artifact 저장 실패: {e}', file=sys.stderr)
    O = None
    try:
        if _stage(repo, A):
            git(repo, 'commit', '-q', '-m', a.message)
            O = out(repo, 'rev-parse', 'HEAD')
    except Fallback as e:                              # 오늘도 이 커밋이 실패하면 단계가 실패한다
        print(f'::error::수집 커밋을 만들지 못했다({e}) — 오늘과 같은 실패. 원본은 '
              f'{"artifact 에 있다" if saved else "남지 않았다"}', file=sys.stderr)
        return 1
    reason = f'{ATTEMPTS}회 push 거절'
    for attempt in range(1, ATTEMPTS + 1):
        wt = None
        try:
            if f'fetch{attempt}' in os.environ.get('VERSIONS_TEST_FAIL', '').split(','):
                raise Fallback('시험용 fetch 실패')
            git(repo, 'fetch', '-q', REMOTE, BRANCH)
            fetched = True
            published = exists(repo, f'{REMOTE}/{BRANCH}', post)   # fetch 가 되면 원격 최신만 본다(#16)
            if f'reconcile{attempt}' in os.environ.get('VERSIONS_TEST_FAIL', '').split(','):
                raise Fallback('시험용 실패')
            wt = Worktree(repo, f'{REMOTE}/{BRANCH}')
            m = reconcile(repo, wt.path, A, a.market, date, O, base, rid, a.mode, collected, a.tmpdir)
            git(wt.path, 'add', '-A')
            staged = git(wt.path, 'diff', '--cached', '--quiet', check=False).returncode != 0
            at_target = out(wt.path, 'rev-parse', 'HEAD') == out(repo, 'rev-parse', f'{REMOTE}/{BRANCH}')
            if at_target:
                if not staged:
                    print('변경 없음 — push 하지 않는다')
                    return 0
                git(wt.path, 'commit', '-q', '-m', a.message)
            elif staged:                              # cherry-pick 한 O 에 판 기록을 접는다 — 커밋 하나
                git(wt.path, 'commit', '-q', '--amend', '--no-edit')
            hook = os.environ.get('VERSIONS_TEST_BEFORE_PUSH')
            if hook and attempt == 1:                 # 시험 전용 — push 직전 경합 재현
                subprocess.run(hook, shell=True, cwd=repo, check=False)
            if git(wt.path, 'push', '-q', REMOTE, f'HEAD:{BRANCH}', check=False).returncode == 0:
                print(f'versions: {a.market} {date} run {rid} mode={a.mode} published={m["published_on_remote"]} '
                      f'frozen={m["frozen"]} would_freeze={m["would_freeze"]}')
                return 0
            print(f'push 거절 {attempt}/{ATTEMPTS} — 원격에서 다시 세운다', file=sys.stderr)
        except Fallback as e:
            reason = str(e)
            break
        except Exception as e:  # noqa: BLE001 — 어떤 실패든 아래 정책으로
            reason = f'{type(e).__name__}: {e}'
            break
        finally:
            if wt:
                wt.close()
    # 실패 정책(사용자 11/10): shadow = 오늘 방식 폴백 + 경고 / enforce 발행됨 = 보류 /
    # enforce 미발행 = 매 시도 발행 여부를 다시 보는 보호 폴백 / enforce 인데 원격을 한 번도 못 봄 = 보류
    # (fetch 를 한 번도 못 했으면 checkout 기준 판정으로 — 미발행이면 보호 폴백이 다시 fetch 해 본다, #20)
    if a.mode == 'enforce':
        if published:
            return _hold(a.market, date, rid, f'발행된 날인데 동결 처리가 실패했다({reason})', saved)
        return _guarded_fallback(repo, A, a.market, date, O, rid, saved, reason)
    return _fallback(repo, a.market, date, O, rid, a.message, reason)


# ── promote ───────────────────────────────────────────────────────────

def _post_text(html_b):
    """주석·태그·속성을 걷어낸 본문 글자(#7)."""
    t = (html_b or b'').decode(errors='replace')
    t = re.sub(r'<!--.*?-->', ' ', t, flags=re.S)
    t = re.sub(r'<(script|style)\b.*?</\1>', ' ', t, flags=re.S | re.I)
    t = re.sub(r'<[^>]+>', ' ', t)
    return t


INDEX_LABELS = {'KOSPI': ('코스피', 'KOSPI'), 'KOSDAQ': ('코스닥', 'KOSDAQ')}
NEAR = 40


def _post_has_number(html_b, value, index=None):
    """본문에 그 값이 소수 둘째 자리까지 그대로 있는가 — 앞뒤가 숫자·소수점·쉼표면 다른 수다.
    index 를 주면 그 지수 이름 **바로 다음 수치**가 그 값이어야 한다(NEAR 자 안, 사이에 다른 수 없음)
    — 다른 지수·환율의 같은 수로 통과하지 않게(구현 검토 3회 #22)."""
    text = _post_text(html_b)
    v = float(value)
    forms = {f'{v:,.2f}', f'{v:.2f}'}
    num = re.compile(r'(?<![\d.,])\d[\d,]*(?:\.\d+)?')
    if index is None:
        return any(m.group(0) in forms for m in num.finditer(text))
    others = [l for k, labs in INDEX_LABELS.items() if k != index for l in labs]
    for lab in INDEX_LABELS.get(index, (index,)):
        for m in re.finditer(re.escape(lab), text):
            nxt = num.search(text, m.end(), m.end() + NEAR)
            if not nxt or nxt.group(0) not in forms:
                continue
            between = text[m.end():nxt.start()]
            if any(o in between for o in others):          # 「코스닥과 코스피 644.27」 — 다른 지수의 값(4회 #4)
                continue
            return True
    return False


def _value_from_run(repo, rev, market, date, run, field):
    """→ (값, 읽은 파일 {path: sha256}, manifest sha256)."""
    A = adapter(market)
    base = f'versions/{market}/{date}/runs/{run}/'
    man_b = show(repo, rev, base + 'manifest.json')
    man = jload(man_b) or {}
    files = {}
    for p in A.SESSION_INPUTS:
        st = (man.get('stored') or {}).get(p, 'copied')
        files[p] = show(repo, st.split('@', 1)[1], p) if st.startswith('remote@') else show(repo, rev, base + 'files/' + p)
    if any(v is None for v in files.values()):
        raise SystemExit(f'실행 원본 {run} 에 세션 입력이 없다')
    ins = {p: jload(b) for p, b in files.items()}
    if field.startswith('ledger.indices.'):
        v = (A.ledger_row(ins) or {}).get('indices', {}).get(field.rsplit('.', 1)[1])
    else:
        sess = A._session(ins)
        part = field[len('session.'):]
        v = sess['flows'].get(part.split('.', 1)[1]) if part.startswith('flows.') else sess.get(part)
    if v in (None, {}, []):
        raise SystemExit(f'실행 원본 {run} 에 {field} 값이 없다')
    return v, {p: sha256(b) for p, b in files.items()}, sha256(man_b or b'')


def cmd_promote(a):
    """사람이 부르는 명령 — 수집 워크플로·루틴은 부르지 않는다. Actions 안에서는 거부한다."""
    if os.environ.get('GITHUB_ACTIONS') == 'true':
        print('거부: 승격은 사람이 로컬에서 부른다 — 자동 실행 경로에서는 돌지 않는다', file=sys.stderr)
        return 4
    repo, A = a.repo, adapter(a.market)
    target = f'{REMOTE}/{BRANCH}'
    for attempt in range(1, ATTEMPTS + 1):
        git(repo, 'fetch', '-q', REMOTE, BRANCH)
        post = A.POST.format(date=a.date)
        if not exists(repo, target, post):
            raise SystemExit(f'{post} 가 원격에 없다 — 승격은 발행된 날에만')
        if a.value is not None:
            value, src_files, src_manifest = json.loads(a.value), None, None
        else:
            value, src_files, src_manifest = _value_from_run(repo, target, a.market, a.date, a.run, a.field)
        post_b = show(repo, target, post)
        if a.field.startswith('ledger.indices.') and \
                not _post_has_number(post_b, value, index=a.field.rsplit('.', 1)[1]):
            print(f'거부: {post} 본문에 {value} 이 없다 — 글 정정이 먼저다(review-gate 경로). '
                  '글과 입력 자료가 맞아야 승격한다.', file=sys.stderr)
            return 3
        wt = Worktree(repo, target)
        try:
            n = len([p for p in tree_files(repo, target, f'versions/{a.market}/{a.date}/promotions/') if p.endswith('.json')])
            ledger = _jsonl(show(repo, target, A.LEDGER))
            old = next((r for r in ledger if r.get('report_date') == a.date), None)
            rec = {'field': a.field, 'value': value, 'from': a.run or 'value', 'reason': a.reason,
                   'source_manifest_sha256': src_manifest, 'source_files_sha256': src_files,
                   'post_sha256_at_promotion': sha256(post_b or b''),
                   'previous_ledger_row_sha256': sha256(json.dumps(old, sort_keys=True).encode()) if old else None,
                   'at': _dt.datetime.now(KST).isoformat(timespec='seconds')}
            _write(wt.path, f'versions/{a.market}/{a.date}/promotions/{n + 1:03d}.json', jdump(rec))
            P = publish_commit(repo, target, post)
            p_files = snapshot(repo, P, A, a.date) if P else None
            key = _week_key(a.date)
            promos = promotions(repo, target, a.market, _week_dates(key, ledger) + [a.date])
            promos.setdefault(a.date, []).append(rec)
            rows = A.merge_ledger(ledger, None, A.ledger_row(_session_inputs(p_files, A)) if p_files else old,
                                  a.date, True, promos)
            _write(wt.path, A.LEDGER, _jsonl_dump(rows))
            wpath = A.WEEKLY.format(key=key)
            agg = A.merge_week(jload(show(repo, target, wpath)), None,
                               _session_inputs(p_files, A) if p_files else None, a.date, True, promos, rows, key,
                               published_dates=published_dates(repo, target, A, key))
            _write(wt.path, wpath, jdump(agg))
            git(wt.path, 'add', '-A')
            git(wt.path, 'commit', '-q', '-m', f'versions: {a.market} {a.date} 수동 승격 {a.field} — {a.reason[:60]}')
            if git(wt.path, 'push', '-q', REMOTE, f'HEAD:{BRANCH}', check=False).returncode == 0:
                print(f'승격 완료: {a.field}={value}, 주간 {key} complete={agg.get("complete")}')
                return 0
        finally:
            wt.close()
        print(f'push 거절 {attempt}/{ATTEMPTS}', file=sys.stderr)
    return 1


# ── verify-published ──────────────────────────────────────────────────

def verify_published(repo, rev, market, date):
    """발행판 파일·기록 입력 해시 대조. → (상태, 상세)."""
    A = adapter(market)
    meta = jload(show(repo, rev, f'versions/{market}/{date}/published/published.json'))
    if not meta:
        return 'no_pin', {}
    P = meta['publish_commit']
    detail = {'mismatch': [], 'missing_blob': [], 'unrestorable': [], 'checked': 0}
    for p, h in meta['files'].items():
        b = show(repo, P, p) if p.endswith('.png') else show(repo, rev, f'versions/{market}/{date}/published/files/{p}')
        if b is None or sha256(b) != h:
            detail['mismatch'].append(p)
    rec = jload(show(repo, P, A.RECORD.format(date=date)))
    if not rec:
        return ('mismatch' if detail['mismatch'] else 'record_none'), detail
    inputs = rec.get('inputs') or {}
    for f in inputs.get('files') or []:
        ref = f.get('ref') or ''
        if not ref.startswith('repo:'):
            detail['unrestorable'].append(f.get('path'))
            continue
        b = show(repo, P, ref[5:])
        detail['checked'] += 1
        if b is None:
            detail['missing_blob'].append(ref[5:])
        elif sha256(b) != f.get('sha256'):
            detail['mismatch'].append(ref[5:])
    if detail['mismatch'] or detail['missing_blob']:
        return 'mismatch', detail
    if detail['unrestorable'] or inputs.get('incomplete'):
        return 'partial_record', detail
    return 'ok', detail


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    c = sub.add_parser('commit')
    c.add_argument('--market', default='kr')
    c.add_argument('--mode', choices=('shadow', 'enforce'), default='shadow')
    c.add_argument('--message', required=True)
    c.add_argument('--repo', default='.')
    c.add_argument('--tmpdir', default=os.environ.get('RUNNER_TEMP'))
    c.add_argument('--force', action='store_true', help='기록만 — 발행판은 force 로도 바뀌지 않는다')
    c.add_argument('--scratch-checkout', action='store_true',
                   help='Actions 밖에서 돌릴 때 — 버릴 clone 이라는 확인(원래 브랜치에 무보호 커밋이 남는다)')
    p = sub.add_parser('promote')
    p.add_argument('--market', default='kr')
    p.add_argument('--date', required=True)
    p.add_argument('--field', required=True)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument('--value')
    g.add_argument('--from', dest='run')
    p.add_argument('--reason', required=True)
    p.add_argument('--repo', default='.')
    v = sub.add_parser('verify-published')
    v.add_argument('--market', default='kr')
    v.add_argument('--date', required=True)
    v.add_argument('--repo', default='.')
    v.add_argument('--rev', default='HEAD')
    a = ap.parse_args(argv)
    if a.cmd == 'commit':
        return cmd_commit(a)
    if a.cmd == 'promote':
        if a.value is not None:
            a.run = None
        return cmd_promote(a)
    st, detail = verify_published(a.repo, a.rev, a.market, a.date)
    print(st, json.dumps({k: (v if isinstance(v, int) else v[:20]) for k, v in detail.items()}, ensure_ascii=False))
    return 0 if st in ('ok', 'partial_record', 'record_none') else 1


if __name__ == '__main__':
    sys.exit(main())
