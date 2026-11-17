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


class _Duplicate(ValueError):
    pass


def _no_duplicates(pairs):
    keys = [k for k, _ in pairs]
    if len(keys) != len(set(keys)):
        raise _Duplicate()
    return dict(pairs)


POST_PATH = {'us': 'posts/%s.html', 'kr': 'kr/posts/%s.html'}


def _staged(repo, path):
    """인덱스에 올라간 그 경로의 바이트 — 작업 파일이 아니다. 일반 파일이 아니거나 없으면 None."""
    r = subprocess.run(['git', '-C', repo, 'ls-files', '-s', '-z', '--', path], capture_output=True)
    entries = _zlist(r.stdout) if not r.returncode else []
    if len(entries) != 1:
        return None
    meta, _, name = entries[0].partition('\t')
    if name != path or not meta.startswith('100'):      # 심볼릭 링크(120000)·서브모듈(160000)은 받지 않는다
        return None
    r = subprocess.run(['git', '-C', repo, 'show', ':' + path], capture_output=True)
    return None if r.returncode else r.stdout


def _post_hashes(raw):
    """staged 글의 sha256, 그리고 에디터 노트 한 블록이 붙어 있으면 그것을 붙이기 전 판의 sha256.

    둘 다 **공개될 바이트만으로** 누구나 계산할 수 있는 값이다. 붙이기 전 판은 `apply_note` 를 거꾸로 돌려 얻는다 —
    `apply_note(앞, 노트) == 앞[:자리] + '\n' + 노트 + 앞[자리:]` 이므로 staged 글에서 「줄바꿈 + 노트」만 도려낸다.
    다시 붙였을 때 staged 글과 바이트가 같을 때만 받는다(`guard.same_published` 와 같은 관계).

    한계: 승인판에 **이미 다른 노트가 있었고** 그것을 새 노트로 갈아 끼운 글이면, 갈기 전 노트는 공개 바이트에
    없어 승인판을 되돌릴 수 없다 — 그 해시는 허용되지 않고 FOUND 로 멈춘다(안전한 쪽). 루틴의 작업 파일에는 노트가
    없으므로(노트는 STEP 3 에서 레포의 글에만 붙는다) 정상 흐름에서는 생기지 않는다.
    """
    out = {hashlib.sha256(raw).hexdigest()}
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError:
        return out
    try:
        from us.editor_note import MARKER, _SECTION_RE, apply_note
    except ImportError:
        return out
    m = _SECTION_RE.search(text) if MARKER in text else None
    if not m:
        return out
    block = m.group(0).strip()
    at = text.find(block, m.start())
    for note in (block, block + '\n'):
        cut = '\n' + note
        if at < 1 or text[at - 1:at - 1 + len(cut)] != cut:
            continue
        bare = text[:at - 1] + text[at - 1 + len(cut):]
        if apply_note(bare, note) == text:
            out.add(hashlib.sha256(bare.encode('utf-8')).hexdigest())
    return out


def public_post_hashes(repo, audit):
    """→ (검증 기록 경로, 그 기록에서 지문으로 치지 않을 해시들). 허용할 것이 없으면 (None, set()).

    발행 전 검증 기록 `verification/<market>/<date>.json` 은 글의 sha256 을 담아야 한다(`post.sha256`, 그리고
    게이트가 읽은 작업 파일 html 의 `inputs.files[].sha256`). 감사 지문에도 같은 값이 들어 있어 — 편집 0 이면
    `source_sha256`, 편집이 실리면 `rounds[].proposed_sha256` — 문체 마감 길이 돈 날마다 FOUND 가 났다
    (2026-11-09·11-16, `docs/superpowers/specs/2026-11-17-staged-scan-public-hash.md`).

    허용은 감사 기록의 필드를 믿지 않고 **인덱스의 실제 바이트**에 묶는다:
    - 경로는 감사 기록의 시장·날짜 검증 기록 하나뿐이고, staged blob 이 중복 키 없는 JSON 이어야 한다.
    - 그 기록의 `post.path` 는 그 시장·날짜의 발행 경로(`POST_PATH`)여야 하고, 인덱스의 일반 파일이어야 한다.
    - 값은 그 **staged 글**의 해시(또는 노트를 붙이기 전 판의 해시)여야 한다.
    - 자리는 `post.sha256` 과, `.html` 입력 항목 가운데 `ref` 가 `workspace-only` 이거나 `repo:<post.path>` 인
      것의 `sha256` 뿐이다. 그 자리를 비운 나머지 기록(풀어 읽은 값 기준)에 같은 해시가 남아 있거나, 원문에
      적힌 횟수가 자리 수와 다르면 허용하지 않는다. 다른 파일은 언제나 그대로 검사한다.
    """
    market, date = audit.get('market'), audit.get('date')
    if not (isinstance(market, str) and isinstance(date, str) and market in POST_PATH and date):
        return None, set()
    path = 'verification/%s/%s.json' % (market, date)
    raw = _staged(repo, path)
    if raw is None:
        return None, set()
    try:
        text = raw.decode('utf-8')
        doc = json.loads(text, object_pairs_hook=_no_duplicates)
    except (UnicodeDecodeError, ValueError):
        return None, set()
    post = doc.get('post') if isinstance(doc, dict) else None
    if not isinstance(post, dict) or post.get('path') != POST_PATH[market] % date:
        return None, set()
    body = _staged(repo, post['path'])
    if body is None:
        return None, set()
    public = _post_hashes(body)
    slots = [post]
    files = (doc.get('inputs') or {}).get('files') if isinstance(doc.get('inputs'), dict) else None
    for item in files if isinstance(files, list) else []:
        if (isinstance(item, dict) and isinstance(item.get('path'), str) and item['path'].endswith('.html')
                and item.get('ref') in ('workspace-only', 'repo:' + post['path'])):
            slots.append(item)
    held = {}
    for slot in slots:
        if isinstance(slot.get('sha256'), str) and slot['sha256'] in public:
            held[slot['sha256']] = held.get(slot['sha256'], 0) + 1
            slot['sha256'] = ''
    rest = json.dumps(doc, ensure_ascii=False)       # 허용 자리를 비운 나머지 — 이스케이프를 풀어 읽은 값
    allowed = {h for h, n in held.items() if h not in rest and text.count(h) == n}
    return path, allowed


def staged_hits(repo, audit):
    """staged 변경의 **더해진 줄**에 감사 지문이 있는 경로 목록."""
    finger = fingerprints(audit)
    record, public = public_post_hashes(repo, audit)
    hits = []
    for path in _zlist(_git(repo, 'diff', '--cached', '--name-only', '-z')):
        diff = _git(repo, 'diff', '--cached', '-a', '--no-color', '--', path).decode('utf-8', 'replace')
        added = '\n'.join(l[1:] for l in diff.splitlines() if l.startswith('+') and not l.startswith('+++'))
        marks = finger - public if path == record else finger
        if any(f in added for f in marks):
            hits.append(path)
    return hits


def dump(snap):
    return json.dumps(snap, ensure_ascii=False, sort_keys=True, indent=0)
