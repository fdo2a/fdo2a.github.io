#!/usr/bin/env python3
"""일본 일간 시작 가드 — 루틴 사본이 `origin/main` 과 같은 커밋에서만 시작하게 한다(2026-11-19, 설계 20판 §6-3).

    python3 scripts/ci/jpd_clean_start.py --key "$KEY" --session "$S"     # 잠금을 잡은 직후
      exit 0  시작해도 된다(같은 커밋 / 뒤처지기만 해서 ff 로 맞춤 / 실패한 발행 산출물을 되돌림)
      exit 3  거부 — 아무것도 건드리지 않았다. 루틴은 쓰지 않고 끝내고 경보한다.

순서:
1. 진행 중인 rebase·merge·cherry-pick 이 있거나 `git fetch origin main` 이 실패하면 거부.
2. **가장 먼저 작업 폴더 전체를 본다** — 발행 산출물 7경로 밖에 추적 파일 변경이나 미추적 파일
   (`.gitignore` 제외)이 하나라도 있으면 HEAD 가 같든 뒤처졌든 거부.
3. 변경이 없고 앞선 커밋이 없으면: 같으면 0, 뒤처졌으면 `merge --ff-only` 뒤 0.
4. 그 밖(앞선 커밋이 있거나 7경로에 변경이 있음)은 아래가 **전부** 참일 때만 `reset --hard origin/main`
   + 7경로 중 미추적 파일 삭제. `git clean` 은 쓰지 않는다.
   ⓐ 이 사본이 이 세션의 잠금을 쥐고 있다(`.git/run_lock_<KEY>` 의 SHA == 원격 잠금 ref 끝)
   ⓑ 앞선 로컬 커밋이 전부 단일 부모이고 제목이 `Add JP daily [` 로 시작하며 7경로만 건드린다
   ⓒ 작업 폴더의 변경·미추적 파일이 전부 7경로다(2 에서 이미 확인)
   ⓓ **되돌릴 변경이 전부 이 세션의 실패한 발행 기록 하나에 묶인다**(codex 구현 1회차 #3 — 사람 폴더도 잠금은
      얻을 수 있다): `_workspace/jpd/jpd-<S>-*/publish.json` 가운데 한 기록이, `origin/main` 과 다른 7경로의 HEAD 판·
      작업 폴더 판을 모두 설명해야 한다. 설명 = 발행기가 **쓰기 전에** 적어 둔 바이트(`written` 해시 — 발행이 쓰는 도중에
      죽어도 각 경로는 origin 판이거나 이 바이트다, codex 구현 2회차)와 같거나, 공유 파일(목록·이력·sitemap)
      이면 부모 판에 그 기록의 이 세션 변경만 더한 바이트(`publish_japan_daily.expected_shared`, rebase 복구 뒤의 판)와 같다.
      파일 삭제는 설명되지 않는다. 사람이 손으로 고친 바이트는 어느 기록과도 같지 않아 거부된다.
사람이 쓰는 폴더에는 잠금 파일(ⓐ)도, 그 바이트를 쓴 발행 기록(ⓓ)도 없어 거부된다. 모든 git 호출은 `--root` 를 명시한다.
"""
import argparse
import glob
import hashlib
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PREFIX = 'Add JP daily ['


def outputs(session):
    """실패한 발행이 남길 수 있는 경로 — 이 일곱뿐이다(수집 후보·뉴스·견해 수집 파일·BOJ 캐시는 아니다)."""
    return {f'japan/daily/{session}.html', f'japan/data/daily/{session}.json',
            f'japan/data/daily/runs/{session}.json', f'japan/data/telegram/published/{session}.json',
            'japan/data/history/jp_daily.jsonl', 'japan/daily.json', 'sitemap.xml'}


class Refuse(Exception):
    pass


def _git(root, *args, check=True):
    r = subprocess.run(['git', '-C', root, *args], capture_output=True)
    if check and r.returncode:
        raise Refuse(f'git {" ".join(args[:2])} 실패: {r.stderr.decode("utf-8", "replace").strip()}')
    return r


def _out(root, *args):
    return _git(root, *args).stdout.decode('utf-8', 'surrogateescape').strip()


def dirt(root):
    """-> (변경·미추적 경로 집합, 미추적 경로 집합). 이름 바꾸기는 풀어서, 경로는 따옴표 없이."""
    raw = _git(root, 'status', '--porcelain=v1', '-z', '--untracked-files=all', '--no-renames').stdout
    paths, untracked = set(), set()
    for entry in raw.decode('utf-8', 'surrogateescape').split('\0'):
        if not entry:
            continue
        code, path = entry[:2], entry[3:]
        paths.add(path)
        if code == '??':
            untracked.add(path)
    return paths, untracked


def _in_progress(root):
    gd = _out(root, 'rev-parse', '--absolute-git-dir')
    return [n for n in ('rebase-merge', 'rebase-apply', 'MERGE_HEAD', 'CHERRY_PICK_HEAD', 'REVERT_HEAD')
            if os.path.exists(os.path.join(gd, n))]


def _holds_lock(root, key, remote):
    gd = _out(root, 'rev-parse', '--absolute-git-dir')
    try:
        with open(os.path.join(gd, f'run_lock_{key}'), encoding='utf-8') as fh:
            mine = fh.read().strip()
    except OSError:
        return False, f'잠금 파일 .git/run_lock_{key} 이 없다 — 이 사본은 이 세션의 잠금을 쥐고 있지 않다'
    if not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', mine):
        return False, f'잠금 파일 .git/run_lock_{key} 의 내용이 SHA 가 아니다'
    ref = f'refs/heads/locks/{key}'
    tip = [line.split('\t')[0] for line in _out(root, 'ls-remote', remote, ref).splitlines()
           if line.endswith('\t' + ref)]
    if tip != [mine]:
        return False, f'잠금 파일의 SHA 가 원격 잠금 {ref} 끝과 다르다 — 잠금을 잃었거나 다른 런의 것이다'
    return True, None


def _ahead_problems(root, base, allowed):
    bad = []
    for c in _out(root, 'rev-list', f'{base}..HEAD').split():
        parents = _out(root, 'rev-list', '--parents', '-n', '1', c).split()[1:]
        subject = _out(root, 'log', '-1', '--format=%s', c)
        if len(parents) != 1:
            bad.append(f'{c[:10]} 은 병합 커밋이다')
            continue
        if not subject.startswith(PREFIX):
            bad.append(f'{c[:10]} 제목 「{subject}」 이 「{PREFIX}」 로 시작하지 않는다')
        raw = _git(root, 'diff-tree', '--no-commit-id', '-r', '--name-only', '-z', '--no-renames', c).stdout
        files = {p for p in raw.decode('utf-8', 'surrogateescape').split('\0') if p}
        if files - allowed:
            bad.append(f'{c[:10]} 이 발행 산출물 밖을 건드린다: ' + ', '.join(sorted(files - allowed)))
    return bad


def _blob(root, rev, rel):
    if _git(root, 'cat-file', '-e', f'{rev}:{rel}', check=False).returncode:
        return None
    return _git(root, 'show', f'{rev}:{rel}').stdout


def _records(root, session):
    out = []
    for p in sorted(glob.glob(os.path.join(root, '_workspace', 'jpd', f'jpd-{session}-*', 'publish.json'))):
        run_id = os.path.basename(os.path.dirname(p))
        try:
            with open(p, encoding='utf-8') as fh:
                rec = json.load(fh)
        except (OSError, ValueError):
            continue
        if rec.get('run_id') == run_id and rec.get('session') == session and isinstance(rec.get('written'), dict):
            out.append(rec)
    return out


def _unexplained(root, session, base, ahead, paths, rec):
    """기록 `rec` 로 설명되지 않는 (경로, 판) 목록."""
    from publish_japan_daily import expected_shared
    bad = []
    for rel in sorted(paths):
        origin = _blob(root, base, rel)
        bases = [origin] + [_blob(root, f'{c}^', rel) for c in ahead]
        wt_path = os.path.join(root, rel)
        wt = open(wt_path, 'rb').read() if os.path.isfile(wt_path) else None
        for label, v in (('HEAD', _blob(root, 'HEAD', rel)), ('작업 폴더', wt)):
            if v == origin:
                continue
            if v is None:
                bad.append(f'{rel}({label}: 삭제)')
                continue
            if hashlib.sha256(v).hexdigest() == rec['written'].get(rel):
                continue
            try:
                ok = any(expected_shared(rel, b, session, rec.get('entry') or {}, rec.get('history_row'), v) == v
                         for b in bases)
            except (ValueError, KeyError, TypeError, AttributeError):
                ok = False
            if not ok:
                bad.append(f'{rel}({label})')
    return bad


def start(root, key, session, remote='origin'):
    """-> 사람에게 보일 한 줄. 거부는 Refuse."""
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', session):
        raise Refuse(f'세션 형식이 아니다: {session}')
    if key != f'jpd-{session}':
        raise Refuse(f'잠금 이름 {key} 이 세션 {session} 의 이름(jpd-{session})이 아니다')
    busy = _in_progress(root)
    if busy:
        raise Refuse('진행 중인 git 작업이 있다: ' + ', '.join(busy))
    _git(root, 'fetch', '-q', remote, f'+refs/heads/main:refs/remotes/{remote}/main')
    base = f'refs/remotes/{remote}/main'
    allowed = outputs(session)
    changed, untracked = dirt(root)
    outside = sorted(changed - allowed)
    if outside:
        raise Refuse('발행 산출물 밖에 변경·미추적 파일이 있다 — 사람의 작업일 수 있어 건드리지 않는다: '
                     + ', '.join(outside))
    head, origin = _out(root, 'rev-parse', 'HEAD'), _out(root, 'rev-parse', base)
    ahead = _out(root, 'rev-list', f'{base}..HEAD').split()
    if not changed and not ahead:
        if head == origin:
            return 'HEAD == origin/main — 시작'
        _git(root, 'merge', '-q', '--ff-only', base)
        return f'origin/main 으로 ff ({head[:10]} → {origin[:10]}) — 시작'
    ok, why = _holds_lock(root, key, remote)
    if not ok:
        raise Refuse(why)
    bad = _ahead_problems(root, base, allowed)
    if bad:
        raise Refuse('앞선 로컬 커밋이 실패한 발행이 아니다: ' + ' / '.join(bad))
    raw = _git(root, 'diff', '--name-only', '-z', '--no-renames', base, 'HEAD').stdout
    touched = (changed | {x for x in raw.decode('utf-8', 'surrogateescape').split('\0') if x}) & allowed
    recs = _records(root, session)
    if not recs:
        raise Refuse(f'이 세션의 실패한 발행 기록(_workspace/jpd/jpd-{session}-*/publish.json)이 없다 — '
                     '루틴이 쓴 산출물이라는 근거가 없어 건드리지 않는다: ' + ', '.join(sorted(touched)))
    why = None
    for rec in recs:
        left = _unexplained(root, session, base, ahead, touched, rec)
        if not left:
            break
        why = f'{rec["run_id"]} 기록과 다른 바이트: ' + ', '.join(left)
    else:
        raise Refuse('되돌릴 변경이 실패한 발행 기록과 맞지 않는다 — 사람의 편집일 수 있다. ' + why)
    _git(root, 'reset', '-q', '--hard', base)
    for rel in sorted(untracked & allowed):
        p = os.path.join(root, rel)
        if os.path.isfile(p):
            os.remove(p)
    left, _ = dirt(root)
    if left or _out(root, 'rev-parse', 'HEAD') != origin:
        raise Refuse('되돌린 뒤에도 깨끗하지 않다: ' + ', '.join(sorted(left)))
    return (f'실패한 발행을 되돌렸다 — 커밋 {len(ahead)}개, 경로 {len(changed)}개'
            + (f' ({", ".join(sorted(changed))})' if changed else '') + ' → origin/main')


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--key', required=True)
    ap.add_argument('--session', required=True)
    ap.add_argument('--root', default='.')
    ap.add_argument('--remote', default='origin')
    args = ap.parse_args(argv)
    try:
        print('jpd_clean_start: ' + start(os.path.abspath(args.root), args.key, args.session, args.remote))
    except Refuse as e:
        print(f'jpd_clean_start: 거부 — {e}', file=sys.stderr)
        return 3
    return 0


if __name__ == '__main__':
    sys.exit(main())
