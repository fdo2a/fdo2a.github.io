"""맥이 직접 하는 짝 확인 — 기록을 처음 담은 커밋에 남은 것만 대조한다(2단계, 2026-11-08).

루틴의 `record.verify` 와 **다른 함수**다. 루틴 경로는 한 줄도 바꾸지 않는다 — 그쪽은 작업 공간 입력까지
대조하고 못 하면 커밋·push 를 막는다. 여기서는 작업 공간에만 있던 입력을 「대조 불가」로 센다.

- 검사기 목록은 **그 커밋의 설정**과 비교한다. 지금 사본의 설정과 비교하면 검사기가 늘 때마다 과거의 정상
  기록이 모두 불일치가 된다(codex 설계 검토 #2).
- 읽지 못한 것은 불일치가 아니라 대조 불가다. 대조 불가가 하나라도 있으면 전체를 「일치」라고 하지 않는다.
- 이 함수는 짝만 본다. 검사가 실제로 돌았다는 것은 루틴이 스스로 남긴 기록에 기댄다.
"""
import json

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
    if not isinstance(rec, dict):
        res = _result({'record': UNKNOWN}, ['기록을 읽지 못했다'], None)
        res['overall'] = UNKNOWN          # 기록 자체를 못 읽었다 — 「일부 확인」이 아니다
        return res
    if rec.get('format') != R.FORMAT or rec.get('market') != market or rec.get('date') != date:
        return _result({'record': MISMATCH}, ['다른 형식이거나 다른 글의 기록이다'], rec)

    cats = {}
    cfg = _config_at(repo, rev, market)
    if cfg is None:
        why.append('그 커밋의 검사기 설정을 읽지 못했다')
    post = rec.get('post') if isinstance(rec.get('post'), dict) else {}
    pp = R.post_path(cfg, market, date) if cfg else None

    # 글 지문
    body = _show(repo, rev, pp) if pp else None
    if pp is None or body is None or not post.get('sha256'):
        cats['post'] = UNKNOWN
        why.append('글 또는 기록의 글 해시를 읽지 못했다')
    elif post.get('path') != pp or post['sha256'] != R.sha256_bytes(body):
        cats['post'] = MISMATCH
        why.append('기록의 글 해시가 그 커밋의 글과 다르다')
    else:
        cats['post'] = MATCH

    # 검사기 목록 — 그 커밋의 설정 기준
    gates = rec.get('gates') if isinstance(rec.get('gates'), list) else None
    if cfg is None or gates is None:
        cats['gates'] = UNKNOWN
    elif [g.get('name') for g in gates if isinstance(g, dict)] != [g['name'] for g in R.gates_of(cfg, market)]:
        cats['gates'] = MISMATCH
        why.append('기록의 검사기 목록이 그 커밋의 설정과 다르다')
    else:
        cats['gates'] = MATCH

    # 검사 코드
    states = []
    for g in gates or []:
        if not isinstance(g, dict):
            states.append(UNKNOWN)
            continue
        argv = g.get('argv') or []
        if not argv:
            continue                      # 내장 검사(`unconfirmed`) — 대조할 파일이 없다
        if not isinstance(g.get('script_sha256'), str) or not g['script_sha256']:
            states.append(UNKNOWN)        # 파일 검사인데 해시가 없다 — 건너뛰면 「일치」로 보인다(#7)
            continue
        cur = _show(repo, rev, argv[0])
        if cur is None:
            states.append(UNKNOWN)
        elif R.sha256_bytes(cur) != g['script_sha256']:
            states.append(MISMATCH)
            why.append(f'검사 코드가 기록과 다르다 — {g.get("name")}')
        else:
            states.append(MATCH)
    cats['scripts'] = UNKNOWN if gates is None else _combine(states)

    # 레포 안 코드·설정·원장
    ri = rec.get('repo_inputs') if isinstance(rec.get('repo_inputs'), dict) else {}
    digest, _n = R.repo_digest(repo, market, pp, rev) if pp else (None, 0)
    if pp and digest is None:
        raise ReadError(f'repo_digest {rev[:7]}')          # rev 판 다이제스트는 git 실패일 때만 None
    if not digest or not ri.get('digest'):
        cats['repo_digest'] = UNKNOWN
    elif digest != ri['digest']:
        cats['repo_digest'] = MISMATCH
        why.append('레포 안 코드·설정·원장이 기록과 다르다')
    else:
        cats['repo_digest'] = MATCH

    # 입력 — repo: 참조는 그 커밋의 blob 과, workspace-only 는 대조 불가
    files = ((rec.get('inputs') or {}).get('files') if isinstance(rec.get('inputs'), dict) else None)
    repo_states, workspace = [], 0
    if not isinstance(files, list):
        cats['repo_inputs'] = UNKNOWN
        cats['workspace_inputs'] = UNKNOWN
    else:
        for f in files:
            ref = f.get('ref') if isinstance(f, dict) else None
            if isinstance(ref, str) and ref.startswith('repo:'):
                blob = _show(repo, rev, ref[len('repo:'):])
                if blob is None:
                    repo_states.append(UNKNOWN)
                elif R.sha256_bytes(blob) != f.get('sha256'):
                    repo_states.append(MISMATCH)
                    why.append(f'보존 입력이 기록과 다르다 — {ref}')
                else:
                    repo_states.append(MATCH)
            elif ref == 'workspace-only':
                workspace += 1
            else:
                repo_states.append(UNKNOWN)
        cats['repo_inputs'] = _combine(repo_states)
        cats['workspace_inputs'] = UNKNOWN if workspace else NONE
    res = _result(cats, why, rec)
    res['workspace_only'] = workspace
    res['repo_input_count'] = len(repo_states)
    return res


def _result(cats, why, rec):
    unknown = [k for k, v in cats.items() if v == UNKNOWN]
    return {'cats': cats, 'overall': overall(cats), 'why': why, 'unknown': unknown, 'rec': rec,
            'workspace_only': 0, 'repo_input_count': 0}
