"""맥이 직접 하는 짝 확인 — 기록을 처음 담은 커밋에 남은 것만 대조한다(2단계, 2026-11-08).

루틴의 `record.verify` 와 **다른 함수**다. 루틴 경로는 한 줄도 바꾸지 않는다 — 그쪽은 작업 공간 입력까지
대조하고 못 하면 커밋·push 를 막는다. 여기서는 작업 공간에만 있던 입력을 「대조 불가」로 센다.

- 검사기 목록은 **그 커밋의 설정**과 비교한다. 지금 사본의 설정과 비교하면 검사기가 늘 때마다 과거의 정상
  기록이 모두 불일치가 된다(codex 설계 검토 #2).
- 읽지 못한 것은 불일치가 아니라 대조 불가다. 대조 불가가 하나라도 있으면 전체를 「일치」라고 하지 않는다.
- 이 함수는 짝만 본다. 검사가 실제로 돌았다는 것은 루틴이 스스로 남긴 기록에 기댄다.
"""
import json
import re

from verification import record as R

MATCH, MISMATCH, UNKNOWN, NONE = '일치', '불일치', '대조 불가', '없음'
PARTIAL = '일부 확인'
CATEGORY_LABEL = {
    'record': '기록 파일', 'post': '글 지문', 'gates': '검사기 목록', 'scripts': '검사 코드', 'repo_digest': '레포 안 코드·원장',
    'repo_inputs': '레포에 보존된 입력', 'workspace_inputs': '작업 공간 전용 입력',
}


class ReadError(RuntimeError):
    """git 을 읽지 못했다 — 「그 커밋에 없다」와 다르다. 일시 오류를 대조 불가로 굳히지 않게 올린다(codex 구현 검토 #4)."""


def _show(repo, rev, path):
    """그 커밋의 파일 내용. 없으면 None, git 을 못 읽으면 ReadError."""
    if (not isinstance(path, str) or not path or '\0' in path or path.startswith(('/', ':'))
            or any(seg in ('', '.', '..') for seg in path.split('/'))):
        return None                           # 손상된 기록의 경로 — git 인자로 넘기지 않고 「없음」(재검토 9회 #3, Fable #1)
    ls = R._git(repo, 'ls-tree', '-z', rev, '--', path)
    if ls is None or ls.returncode != 0:
        raise ReadError(f'ls-tree {rev[:7]} {path}')
    if not ls.stdout:
        return None
    out = R._git(repo, 'show', f'{rev}:{path}')
    if out is None or out.returncode != 0:
        raise ReadError(f'show {rev[:7]}:{path}')
    return out.stdout


def _combine(states):
    if not states:
        return NONE
    if MISMATCH in states:
        return MISMATCH
    if UNKNOWN in states:
        return UNKNOWN
    return MATCH


def _config_at(repo, rev, market):
    raw = _show(repo, rev, 'config/prepub_gates.json')
    if raw is None:
        return None
    try:
        cfg = json.loads(raw.decode('utf-8'))
        if not isinstance(cfg, dict) or cfg.get('format') != R.CONFIG_FORMAT:
            return None
        R.gates_of(cfg, market)
        R.post_path(cfg, market, '2000-01-01')
        return cfg
    except (ValueError, UnicodeDecodeError, R.ConfigError, KeyError, TypeError, AttributeError):
        return None


def overall(cats):
    vals = list(cats.values())
    if MISMATCH in vals:
        return MISMATCH
    if UNKNOWN in vals:
        return PARTIAL
    return MATCH


def check(repo, market, date, rev):
    """rev = 그 날짜 기록 파일을 처음 담은 커밋. → {cats, overall, why, unknown, rec}."""
    why = []
    raw = _show(repo, rev, R.record_path(market, date))
    rec = None
    if raw is not None:
        try:
            rec = json.loads(raw.decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            rec = None
    if isinstance(rec, dict):
        try:                                  # 짝 없는 서러게이트(유효한 JSON)는 뒤에서 encode·subprocess 가 죽는다(Fable #2)
            json.dumps(rec, ensure_ascii=False).encode('utf-8')
        except (UnicodeEncodeError, ValueError, TypeError):
            rec = None
    if not isinstance(rec, dict):
        res = _result({'record': UNKNOWN}, ['기록을 읽지 못했다'], None)
        res['overall'] = UNKNOWN          # 기록 자체를 못 읽었다 — 「일부 확인」이 아니다
        return res
    if rec.get('format') != R.FORMAT or rec.get('market') != market or rec.get('date') != date:
        return _result({'record': MISMATCH}, ['다른 형식이거나 다른 글의 기록이다'], rec)

    cats, cw = {}, {}

    def note(cat, msg):
        """칸마다 이유 — 알림이 「대조 불가」만 말하지 않게(사용자 11/11). 기존 why 에도 같은 문장."""
        why.append(msg)
        cw.setdefault(cat, []).append(msg)

    cfg = _config_at(repo, rev, market)
    if cfg is None:
        why.append('그 커밋의 검사기 설정을 읽지 못했다')
    post = rec.get('post') if isinstance(rec.get('post'), dict) else {}
    pp = R.post_path(cfg, market, date) if cfg else None

    # 글 지문
    body = _show(repo, rev, pp) if pp else None
    if pp is None:
        cats['post'] = UNKNOWN
        note('post', '그 커밋의 검사기 설정을 읽지 못해 글 경로를 정하지 못했다')
    elif body is None:
        cats['post'] = UNKNOWN
        note('post', f'그 커밋에 글 파일이 없다 — {pp}')
    elif not post.get('sha256'):
        cats['post'] = UNKNOWN
        note('post', '기록에 글 해시가 없다')
    elif post.get('path') != pp or post['sha256'] != R.sha256_bytes(body):
        cats['post'] = MISMATCH
        note('post', '기록의 글 해시가 그 커밋의 글과 다르다')
    else:
        cats['post'] = MATCH

    # 검사기 목록 — 그 커밋의 설정 기준
    gates = rec.get('gates') if isinstance(rec.get('gates'), list) else None
    if cfg is None:
        cats['gates'] = UNKNOWN
        note('gates', '그 커밋의 검사기 설정을 읽지 못했다')
    elif gates is None:
        cats['gates'] = UNKNOWN
        note('gates', '기록에 검사기 목록이 없다')
    elif [g.get('name') if isinstance(g.get('name'), str) else None for g in gates if isinstance(g, dict)] \
            != [g['name'] for g in R.gates_of(cfg, market)]:
        cats['gates'] = MISMATCH
        note('gates', '기록의 검사기 목록이 그 커밋의 설정과 다르다')
    else:
        cats['gates'] = MATCH

    # 검사 코드
    states = []
    builtin = {g['name'] for g in R.gates_of(cfg, market) if g.get('builtin')} if cfg else set()
    for g in gates or []:
        if not isinstance(g, dict):
            states.append(UNKNOWN)
            note('scripts', '기록의 검사기 항목 형식이 다르다')
            continue
        name = g.get('name') if isinstance(g.get('name'), str) else '이름 없는 검사기'
        argv = g.get('argv') or []
        if not isinstance(argv, list):            # 손상된 기록 — 예외 없이 대조 불가로(codex 재검토 8회 #2)
            states.append(UNKNOWN)
            note('scripts', f'기록의 실행 정보 형식이 다르다 — {name}')
            continue
        if name in builtin and not argv:
            continue                      # 설정이 내장 검사라고 한 것(`unconfirmed`)만 — 대조할 파일이 없다
        if not argv or not isinstance(argv[0], str):
            states.append(UNKNOWN)        # 파일 검사인데 실행 정보가 없다(codex 재검토 #7)
            note('scripts', f'기록에 실행 정보가 없다 — {name}')
            continue
        if not isinstance(g.get('script_sha256'), str) or not g['script_sha256']:
            states.append(UNKNOWN)        # 파일 검사인데 해시가 없다 — 건너뛰면 「일치」로 보인다(#7)
            note('scripts', f'기록에 검사 코드 해시가 없다 — {name}')
            continue
        cur = _show(repo, rev, argv[0])
        if cur is None:
            states.append(UNKNOWN)
            note('scripts', f'그 커밋에 검사 코드 파일이 없다 — {name}({argv[0]})')
        elif R.sha256_bytes(cur) != g['script_sha256']:
            states.append(MISMATCH)
            note('scripts', f'검사 코드가 기록과 다르다 — {name}')
        else:
            states.append(MATCH)
    cats['scripts'] = UNKNOWN if gates is None else _combine(states)
    if gates is None:
        note('scripts', '기록에 검사기 목록이 없다')

    # 레포 안 코드·설정·원장
    ri = rec.get('repo_inputs') if isinstance(rec.get('repo_inputs'), dict) else {}
    digest, _n = R.repo_digest(repo, market, pp, rev) if pp else (None, 0)
    if pp and digest is None:
        raise ReadError(f'repo_digest {rev[:7]}')          # rev 판 다이제스트는 git 실패일 때만 None
    if not digest:
        cats['repo_digest'] = UNKNOWN
        note('repo_digest', '글 경로를 정하지 못해 그 커밋의 다이제스트를 만들지 못했다')
    elif not ri.get('digest'):
        cats['repo_digest'] = UNKNOWN
        note('repo_digest', '기록에 레포 다이제스트가 없다')
    elif digest != ri['digest']:
        cats['repo_digest'] = MISMATCH
        note('repo_digest', '레포 안 코드·설정·원장이 기록과 다르다')
    else:
        cats['repo_digest'] = MATCH

    # 입력 — repo: 참조는 그 커밋의 blob 과, git: 참조는 조상 커밋의 blob 과, workspace-only 는 대조 불가
    files = ((rec.get('inputs') or {}).get('files') if isinstance(rec.get('inputs'), dict) else None)
    repo_states, workspace, ws_files = [], 0, []
    if not isinstance(files, list):
        cats['repo_inputs'] = UNKNOWN
        cats['workspace_inputs'] = UNKNOWN
        note('repo_inputs', '기록에 입력 목록이 없다')
        cw['workspace_inputs'] = ['기록에 입력 목록이 없다']
    else:
        for f in files:
            ref = f.get('ref') if isinstance(f, dict) else None
            if isinstance(ref, str) and ref.startswith('repo:'):
                blob = _show(repo, rev, ref[len('repo:'):])
                if blob is None:
                    repo_states.append(UNKNOWN)
                    note('repo_inputs', f'그 커밋에 보존 입력 파일이 없다 — {ref}')
                elif R.sha256_bytes(blob) != f.get('sha256'):
                    repo_states.append(MISMATCH)
                    note('repo_inputs', f'보존 입력이 기록과 다르다 — {ref}')
                else:
                    repo_states.append(MATCH)
            elif isinstance(ref, str) and ref.startswith('git:'):
                sub = []
                repo_states.append(_history_state(repo, rev, ref, f.get('sha256'), sub))
                for m in sub:
                    note('repo_inputs', m)
            elif ref == 'workspace-only':
                workspace += 1
                if isinstance(f.get('path'), str):
                    ws_files.append(f['path'])
            else:
                repo_states.append(UNKNOWN)
                note('repo_inputs', f'입력 참조 종류를 모른다 — {str(ref)[:60]}')
        cats['repo_inputs'] = _combine(repo_states)
        cats['workspace_inputs'] = UNKNOWN if workspace else NONE
    res = _result(cats, why, rec)
    res['cat_why'] = cw
    res['workspace_only'] = workspace
    res['workspace_files'] = ws_files
    res['repo_input_count'] = len(repo_states)
    return res


_SHA40 = re.compile(r'[0-9a-f]{40}')


def _history_state(repo, rev, ref, want, why):
    """`git:<커밋>:<경로>` — 그 커밋이 rev 의 조상이고 그 커밋의 파일 바이트가 기록과 같으면 일치.
    객체가 이 클론에 없거나 조상이 아니면 대조 불가(이유를 붙인다), git 을 못 읽으면 ReadError(codex 설계 검토 #3)."""
    c, _, path = ref[len('git:'):].partition(':')
    if not _SHA40.fullmatch(c) or not path:
        why.append(f'이력 참조 형식이 아니다 — {ref[:80]}')
        return UNKNOWN
    have = R._git(repo, 'rev-parse', '--verify', '--quiet', f'{c}^{{commit}}')
    if have is None or have.returncode not in (0, 1):
        raise ReadError(f'rev-parse {c[:7]}')
    if have.returncode == 1:
        why.append(f'이력 참조의 커밋이 이 클론에 없다 — {c[:7]}')
        return UNKNOWN
    anc = R._git(repo, 'merge-base', '--is-ancestor', c, rev)
    if anc is None or anc.returncode not in (0, 1):
        raise ReadError(f'merge-base {c[:7]} {rev[:7]}')
    if anc.returncode == 1:
        shallow = R._git(repo, 'rev-parse', '--is-shallow-repository')
        if shallow is None or shallow.returncode != 0:
            raise ReadError('rev-parse --is-shallow-repository')
        if shallow.stdout.decode().strip() == 'true':      # 얕은 경계에서는 「조상 아님」을 증명할 수 없다(구현 검토 #2)
            why.append(f'이력 참조의 커밋이 기록 커밋의 조상인지 확인하지 못했다(얕은 이력) — {c[:7]}')
        else:
            why.append(f'이력 참조의 커밋이 기록 커밋의 조상이 아니다 — {c[:7]}')
        return UNKNOWN
    blob = _show(repo, c, path)
    if blob is None:
        why.append(f'이력 참조의 커밋에 그 파일이 없다 — {ref[:80]}')
        return UNKNOWN
    if R.sha256_bytes(blob) != want:
        why.append(f'보존 입력이 기록과 다르다 — {ref}')
        return MISMATCH
    return MATCH


def _result(cats, why, rec):
    unknown = [k for k, v in cats.items() if v == UNKNOWN]
    return {'cats': cats, 'overall': overall(cats), 'why': why, 'unknown': unknown, 'rec': rec,
            'cat_why': {k: list(why) for k in cats if cats[k] in (UNKNOWN, MISMATCH)},
            'workspace_only': 0, 'workspace_files': [], 'repo_input_count': 0}
