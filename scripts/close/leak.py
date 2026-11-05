"""공개 레포 누출 검사 — STEP 2.6 전후 작업 트리·인덱스 **내용** 비교와 커밋 직전 staged 지문 검사.

비적대적 위협 모델(사고 방지)이다. 서브에이전트가 일부러 나눠·인코딩해 섞는 것은 막는다고 하지 않는다.

스냅샷 = 인덱스 항목(`git ls-files -s`, blob 해시) + 작업 트리에서 인덱스와 다른 추적 파일 각각의
**작업 트리 바이트 sha256** + 미추적 파일 각각의 sha256. `git diff` 출력의 해시는 쓰지 않는다 — 이미
수정된 바이너리를 다시 바꾸면 「Binary files differ」 줄이 그대로라 놓친다(v4.6 최종 검토 minor).
"""

import hashlib
import json
import os
import subprocess

FINGER_KEYS = ('"pair_hash"', '"verdict"', '"outcome"', '"proposed_sha256"', '"bundles"')
MIN_WHY = 10


def _git(repo, *args):
    r = subprocess.run(['git', '-C', repo, *args], capture_output=True)
    if r.returncode:
        raise RuntimeError('git %s 실패: %s' % (' '.join(args), r.stderr.decode('utf-8', 'replace')[:200]))
    return r.stdout


def _zlist(raw):
    return [p for p in raw.decode('utf-8', 'surrogateescape').split('\0') if p]


def _file_sha(repo, path):
    full = os.path.join(repo, path)
    try:
        if os.path.islink(full):
            return 'link:' + os.readlink(full)
        h = hashlib.sha256()
        with open(full, 'rb') as fh:
            for chunk in iter(lambda: fh.read(1 << 16), b''):
                h.update(chunk)
        return h.hexdigest()
    except FileNotFoundError:
        return 'missing'
    except IsADirectoryError:
        return 'dir'


def snapshot(repo):
    """→ dict(경로 키 → 값). 같으면 STEP 2.6 이 레포에 아무것도 남기지 않은 것이다."""
    out = {}
    for line in _zlist(_git(repo, 'ls-files', '-s', '-z')):
        meta, path = line.split('\t', 1)
        out['index:' + path] = meta
    for path in _zlist(_git(repo, 'diff', '--name-only', '-z')):
        out['work:' + path] = _file_sha(repo, path)
    for path in _zlist(_git(repo, 'ls-files', '-o', '--exclude-standard', '-z')):
        out['untracked:' + path] = _file_sha(repo, path)
    return out


def compare(before, after):
    """→ 달라진 경로 목록(내용은 찍지 않는다)."""
    keys = sorted(set(before) | set(after))
    return [k for k in keys if before.get(k) != after.get(k)]


def fingerprints(audit):
    """감사 기록 → 공개 diff 에 나오면 안 되는 문자열들."""
    out = set(FINGER_KEYS)
    for k in ('uuid', 'proposed_sha256', 'source_sha256'):
        v = audit.get(k)
        if isinstance(v, str) and len(v) >= 8:
            out.add(v)
    for r in audit.get('rounds', []):
        if isinstance(r, dict):
            for k in ('proposed_sha256',):
                if isinstance(r.get(k), str):
                    out.add(r[k])
            for b in r.get('bundles', []):
                if isinstance(b, dict) and isinstance(b.get('hash'), str):
                    out.add(b['hash'])
            for v in (r.get('verdicts') or {}).values():
                why = v.get('why') if isinstance(v, dict) else None
                if isinstance(why, str) and len(why.strip()) >= MIN_WHY:
                    out.add(why.strip())
    return out


def staged_hits(repo, audit):
    """staged 변경의 **더해진 줄**에 감사 지문이 있는 경로 목록."""
    finger = fingerprints(audit)
    hits = []
    for path in _zlist(_git(repo, 'diff', '--cached', '--name-only', '-z')):
        diff = _git(repo, 'diff', '--cached', '-a', '--no-color', '--', path).decode('utf-8', 'replace')
        added = '\n'.join(l[1:] for l in diff.splitlines() if l.startswith('+') and not l.startswith('+++'))
        if any(f in added for f in finger):
            hits.append(path)
    return hits


def dump(snap):
    return json.dumps(snap, ensure_ascii=False, sort_keys=True, indent=0)
