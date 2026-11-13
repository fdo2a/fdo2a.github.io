"""발행 전 기록을 읽어 알림 문장으로 — 발행 건별 알림과 매일 요약이 함께 쓰는 계산(2단계, 2026-11-08).

두 사실을 따로 낸다(codex 설계 검토 #3): ① 직접 확인한 짝(`verification.repo_check`) ② 루틴이 남긴 검사 결과.
짝이 맞아도 기록 안에 실행 안 함·일부만 검사·노트 수치가 있을 수 있다.
짝을 누가 다시 봤는지는 `who` 로 받는다(2.5단계) — 발행 건별 알림은 GitHub Actions 가 계산하므로 `GITHUB`,
맥의 미리보기·매일 요약은 `MAC`(기본값). 판단(`fingerprint`·`anomalies`)은 `who` 와 무관하다.

기준 커밋은 「그 날짜 기록 파일을 **처음 담은** 커밋」이다. 「처음 공개된 판」이라고 부르지 않는다 — git 그래프만으로는
공개 시점을 증명하지 못한다(설계 검토 #1). 그 뒤 판은 짝 경보를 만들지 않고 「조판 외 변경 n회」로만 센다.
설계: docs/superpowers/specs/2026-11-08-telegram-prepub-records.md
"""
import json
import re
import subprocess

from verification import record as R
from verification import repo_check as C

EFFECTIVE = '2026-11-09'                      # 발행 전 기록이 루틴에 들어간 첫 발행일
TARGETS = {'us': 'posts/{date}.html', 'kr': 'kr/posts/{date}.html'}
LABEL = {'us': 'US 일간', 'kr': 'KR 일간'}
_PATH = {'us': re.compile(r'^posts/(\d{4}-\d{2}-\d{2})\.html$'),
         'kr': re.compile(r'^kr/posts/(\d{4}-\d{2}-\d{2})\.html$')}
STATUS = {'pass': '통과', 'warn': '경고', 'fail': '실패', 'indeterminate': '판정 불가',
          'not_run': '실행 안 함', 'partial': '일부만 검사',
          'pass_with_warnings': '통과(경고 있음)', 'pass_with_gaps': '통과(검증 빈칸 있음)'}

OK, NO_RECORD, AMBIGUOUS = 'ok', 'no_record', 'ambiguous'

MAC, GITHUB = 'mac', 'github'                 # 짝을 다시 확인한 주체
_WHO = {MAC: {'subj': '맥이', 'pair': '[맥이 직접 확인]',
              'foot': '맥이 직접 확인한 범위는 따로 적었어요 — 검사가 실제로 돌았다는 것까지 맥이 증명하지는 못해요.'},
        GITHUB: {'subj': 'GitHub 이', 'pair': '[GitHub이 직접 대조]',
                 'foot': 'GitHub 이 짝만 다시 확인했어요(범위는 따로 적었어요) — 검사가 실제로 돌았다는 것까지 '
                         '증명하지는 못해요.'}}


def subject(who=MAC):
    """문장 주어 — 「맥이」 / 「GitHub 이」. 모르는 주체는 KeyError(조용히 맥이라고 쓰지 않는다)."""
    return _WHO[who]['subj']


class GitError(RuntimeError):
    """git 을 읽지 못했다 — 「없음」과 다르다."""


def _git(root, *args):
    try:
        out = subprocess.run(['git', '-C', root, '-c', 'core.quotepath=off', *args],
                             capture_output=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GitError(str(exc)) from exc
    if out.returncode:
        raise GitError(out.stderr.decode('utf-8', 'replace')[-200:])
    return out.stdout


def target_of(path):
    """(market, date) — 발행 전 기록 대상(US·KR 일간, 적용일 이후)일 때만."""
    for market, rx in _PATH.items():
        m = rx.match(path)
        if m and m.group(1) >= EFFECTIVE:
            return market, m.group(1)
    return None


def post_path(market, date):
    return TARGETS[market].format(date=date)


def _adding(root, ref, path):
    out = _git(root, 'log', '--format=%H', '--diff-filter=A', ref, '--', path).decode().split()
    return out


def _blob(root, rev, path):
    """없으면(삭제) None, 못 읽으면 GitError."""
    if not _git(root, 'ls-tree', '-z', rev, '--', path):
        return None
    return _git(root, 'show', f'{rev}:{path}')


def corrections(root, ref, path, base):
    """base 판 뒤로 그 글을 바꾼 판들을 이웃끼리 가른다 → {typeset, other, unknown}.

    `typography` 의 False 는 「조판으로 증명되지 않음」이라 「조판 외 변경」으로 센다(본문 정정이라 단정하지 않는다 —
    설계 검토 #8). root 를 주지 않는다: 자산 외부화 판정은 지금 파일을 읽어 과거 판을 재현하지 못하므로, 그런 변경은
    조판으로 받지 않는다. merge·삭제·재추가는 순서가 모호하니 판정 불가로 센다."""
    from review import prose
    rows = _git(root, 'log', '--reverse', '--format=%H %P', f'{base}..{ref}', '--', path).decode().splitlines()
    out = {'typeset': 0, 'other': 0, 'unknown': 0}
    prev = _blob(root, base, path)
    for row in rows:
        parts = row.split()
        if len(parts) > 2:                    # merge
            out['unknown'] += 1
            prev = _blob(root, parts[0], path)
            continue
        cur = _blob(root, parts[0], path)
        if cur is None or prev is None:
            out['unknown'] += 1
        else:
            v = prose.typography(path, prev.decode('utf-8', 'replace'), cur.decode('utf-8', 'replace'))
            out['typeset' if v is True else 'other' if v is False else 'unknown'] += 1
        prev = cur
    return out


def recorded(rec, allowed=None):
    """루틴이 남긴 검사 결과 — 기록 그대로. 필수 필드가 없으면 「읽지 못함」.
    allowed = 그 커밋 설정의 검사기 이름 — **표시할 때만** 밖의 이름을 고정 문구로 바꾼다(맥 요약 계약, codex 재검토 4회 #1).
    판정용 값(이름·상태)은 기록 그대로 둔다 — 표시 정규화가 fully_verified·anomalies 를 바꾸면 안 된다(재검토 11회)."""
    allowed = frozenset(x for x in (allowed or ()) if isinstance(x, str))     # 설정 이름이 목록·사전이어도(Fable #3)
    s = rec.get('summary') if isinstance(rec, dict) else None
    gates = rec.get('gates') if isinstance(rec, dict) else None
    lists = ('blocking', 'note_numbers', 'note_format', 'warned', 'integrity', 'not_run')
    if (not isinstance(s, dict) or not isinstance(gates, list) or not gates
            or not isinstance(s.get('publish_ok'), bool) or not isinstance(s.get('verified'), bool)
            or not isinstance(s.get('status'), str)
            or any(not isinstance(s.get(k), list) for k in lists)          # 빠진 칸을 빈 목록으로 읽지 않는다
            or any(not isinstance(g, dict) or not isinstance(g.get('name'), str)
                   or not isinstance(g.get('status'), str) for g in gates)):
        # 문자열 "false" 를 참으로 읽지 않는다(codex 구현 검토 #7). 무엇이 빠졌는지는 적는다(사용자 11/11)
        return {'readable': False, 'unreadable_why': _unreadable_why(s, gates, lists)}
    by = [g for g in gates if isinstance(g, dict)]
    numbers = next((g.get('numbers') for g in by if g.get('name') == 'check_numbers'
                    and isinstance(g.get('numbers'), dict)), None)
    return {
        'readable': True, 'status': s['status'], 'publish_ok': s['publish_ok'],   # status 는 원래 값 — 지문이 쓴다(표시는 STATUS 밖이면 「모르는 판정」, 재검토 10회)
        'verified': s['verified'], 'blocking': [_as_str(x) for x in s.get('blocking') or []],
        'not_run': [g['name'] for g in by if g.get('status') == 'not_run'],
        'partial': [g['name'] for g in by if g.get('status') == 'partial'],
        'indeterminate': [g['name'] for g in by if g.get('status') == 'indeterminate'],
        'required_indeterminate': [g['name'] for g in by if g.get('status') == 'indeterminate' and g.get('required', True)],
        'required_failed': [g['name'] for g in by if g.get('status') == 'fail' and g.get('required', True)],
        'ref_failed': [g['name'] for g in by if g.get('status') == 'fail' and not g.get('required', True)],
        'note_numbers': [_as_str(x) for x in s.get('note_numbers') or []],
        'note_format': [_as_str(x) for x in s.get('note_format') or []],
        'warned': [_as_str(x) for x in s.get('warned') or []],
        'integrity': [x if isinstance(x, str) else '형식이 다른 무결성 항목' for x in s.get('integrity') or []],
        'allowed': allowed,
        'required': sum(1 for g in by if g.get('required', True)),
        'required_pass': sum(1 for g in by if g.get('required', True) and g.get('status') in ('pass', 'warn')),
        'numbers': numbers, 'python': _str(_dict(rec.get('code')).get('python')),
        'created': _str(_dict(rec.get('created_at')).get('kst')),
        'reasons': {g['name']: gate_reasons(g) for g in by if g.get('status') not in ('pass',)},
    }


def _as_str(x):
    return x if isinstance(x, str) else '형식이 다른 항목'      # join 에서 멈추지 않게 — 판정 의미는 그대로


def _disp(x, rec):
    """표시용 검사기 이름."""
    return _safe_name(x, rec.get('allowed') or frozenset())


def _safe_name(x, allowed):
    """요약 목록의 항목 — 그 커밋 설정에 있는 검사기 이름이나 `integrity`(기록이 쓰는 고정 낱말)만."""
    return x if isinstance(x, str) and (x in allowed or x == 'integrity') else '이름 모를 검사기'


def _dict(x):
    return x if isinstance(x, dict) else {}


def _str(x):
    return x[:40] if isinstance(x, str) else None


def _unreadable_why(s, gates, lists):
    if not isinstance(s, dict):
        return '요약 칸(summary)이 없어요'
    if not isinstance(gates, list) or not gates:
        return '검사기 목록(gates)이 없어요'
    bad = [k for k in ('publish_ok', 'verified') if not isinstance(s.get(k), bool)]
    bad += ['status'] if not isinstance(s.get('status'), str) else []
    bad += [k for k in lists if not isinstance(s.get(k), list)]
    if bad:
        return '요약에 빠졌거나 형식이 다른 칸: ' + ', '.join(bad)
    return '검사기 항목 중 이름·상태가 없는 것이 있어요'


_WARN_LINE = re.compile(r'^\s*(경고|warn|WARN)')
_COUNT_HEAD = re.compile(r'^\s*(경고|위반|warn|WARN)\s*\d+\s*건')
_BULLET = re.compile(r'^\s*[·•\-]\s*')
REASON_LEN, REASON_ITEMS = 100, 2


def gate_reasons(g):
    """검사기 하나가 통과가 아닌 이유 — 공개 레포 기록(verification/*.json)에 이미 있는 마스킹된 문장만 쓴다.
    `reason` 이 있으면 그것, 없으면 `items` 중 상태에 맞는 줄. 없으면 빈 목록(→ 「이유가 기록에 없어요」)."""
    if isinstance(g.get('reason'), str) and g['reason'].strip():
        return [_cut(g['reason'])]
    raw = g.get('items')
    items = [x for x in raw if isinstance(x, str) and x.strip()] if isinstance(raw, list) else []   # 손상 형식은 이유 없음
    items = [x for x in items if not _COUNT_HEAD.match(x)]      # 「경고 1건(…) — <html>」 머리줄은 이유가 아니다
    if g.get('status') == 'warn':
        items = ([x for x in items if _WARN_LINE.match(x)] or [x for x in items if _BULLET.match(x)] or items)
        items = [_BULLET.sub('', _WARN_LINE.sub('', x)).lstrip(' :：') for x in items]
    return [_cut(x) for x in items]


def _cut(x, n=REASON_LEN):
    x = ' '.join(x.split())
    return x if len(x) <= n else x[:n - 1] + '…'


def _more(items, n, unit='건'):
    """앞 n 개 + 「외 N건」."""
    head = '; '.join(items[:n])
    return head + (f' (외 {len(items) - n}{unit})' if len(items) > n else '')


def view(root, ref, market, date):
    """한 글의 상태. GitError 는 그대로 올린다(조회 실패를 「기록 없음」으로 바꾸지 않는다)."""
    path = post_path(market, date)
    rp = R.record_path(market, date)
    adds = _adding(root, ref, path)
    recs = _adding(root, ref, rp)
    v = {'market': market, 'date': date, 'path': path, 'post_adds': adds, 'record_commit': None,
         'same_commit': None, 'check': None, 'recorded': None, 'corrections': None, 'kind': None, 'why': []}
    if len(adds) != 1:
        v['kind'] = AMBIGUOUS
        v['why'].append(f'글을 추가한 커밋이 {len(adds)}개 — 기준 판을 하나로 정하지 못했다')
    if len(recs) > 1:
        v['kind'] = AMBIGUOUS
        v['why'].append(f'기록을 추가한 커밋이 {len(recs)}개 — 기준 판을 하나로 정하지 못했다')
    if v['kind'] is None and not recs:
        v['kind'] = NO_RECORD
    base = None
    if v['kind'] is None:
        rc = recs[0]
        v['kind'], v['record_commit'], v['same_commit'] = OK, rc, rc == adds[0]
        try:
            v['check'] = C.check(root, market, date, rc)
        except C.ReadError as exc:
            raise GitError(str(exc)) from exc
        try:
            cfg = C._config_at(root, rc, market)
        except C.ReadError as exc:
            raise GitError(str(exc)) from exc
        v['recorded'] = recorded(v['check'].get('rec'), [g['name'] for g in R.gates_of(cfg, market)] if cfg else None)
        base = rc
    elif v['kind'] == NO_RECORD:
        base = adds[0]
    if base:
        v['corrections'] = corrections(root, ref, path, base)
    v['check_light'] = None if v['check'] is None else {k: v['check'][k] for k in ('cats', 'overall', 'why')}
    return v


def anomalies(v):
    """즉시 확인이 필요한 이상 — 「검증 완료 아님」(미실행·일부만·경고·미검증 숫자)과 다르다(사용자 11/08).

    이상: 기록 없음, 기준 판을 못 정함, 짝 불일치, 맥이 레포 안 것을 대조하지 못함(작업 공간 입력 말고),
    글과 기록이 다른 커밋, 기록 요약을 읽지 못함, 기록이 발행 불가라고 함(필수 검사 실패·판정 불가 — 그런데 올라왔다),
    필수 검사의 판정 불가, 무결성 경보."""
    out = []
    if v.get('kind') == NO_RECORD:
        return ['발행 전 기록 없음']
    if v.get('kind') != OK:
        return ['기준 판을 정하지 못함']
    chk, rec = v.get('check') or {}, v.get('recorded') or {}
    if chk.get('overall') == C.MISMATCH:
        out.append('짝 불일치')
    if set(chk.get('unknown') or []) - {'workspace_inputs'} or chk.get('overall') == C.UNKNOWN:
        out.append('레포 안 대조 불가')
    if v.get('same_commit') is not True:
        out.append('글과 기록이 다른 커밋')
    if not rec.get('readable'):
        out.append('기록 요약을 읽지 못함')
    else:
        if not rec.get('publish_ok'):
            out.append('기록이 발행 불가라고 함')
        if rec.get('required_failed'):
            # 노트 때문에 허용된 필수 실패도 publish_ok 는 참이다 — 그래도 필수 검사가 실패한 글이다(codex 5회 #1)
            out.append('필수 검사 실패(' + ', '.join(rec['required_failed'][:4]) + ')')
        if rec.get('required_indeterminate'):
            out.append('필수 검사 판정 불가(' + ', '.join(rec['required_indeterminate'][:4]) + ')')   # 참고 검사는 이상 아님(#2)
        if rec.get('integrity'):
            out.append('무결성 경보')
    return out


INTEGRITY_KINDS = {
    '검사기가 검사 사본을 바꿨다': '검사기가 검사 사본을 바꿈',
    '검사 중에 원본 글이 바뀌었다': '검사 중 원본 글이 바뀜',
    '검사 뒤 원본 글을 읽지 못했다': '검사 뒤 원본 글을 못 읽음',
    '검사 중에 입력 파일이 바뀌었다': '검사 중 입력 파일이 바뀜',
    '레포 안 코드·원장의 다이제스트를 읽지 못했다': '레포 다이제스트를 못 읽음',
    '검사 중에 레포 안 코드·설정·원장이 바뀌었다': '검사 중 레포 안 코드가 바뀜',
}


def anomaly_labels(v):
    """표시용 — `anomalies()` 의 이름 뒤에 어느 칸·어느 검사기인지(고정 이름만: 맥 요약은 검사기 원문을 싣지 않는다).
    판정(`clean`)은 `anomalies()` 그대로 — 표시를 바꿔도 기준선이 흔들리지 않게(codex 설계 검토 #9)."""
    out = []
    chk, rec = v.get('check') or {}, v.get('recorded') or {}
    cats = chk.get('cats') or {}
    for a in anomalies(v):
        if a == '짝 불일치':
            a += '(' + ', '.join(C.CATEGORY_LABEL.get(k, k) for k, s in cats.items() if s == C.MISMATCH) + ')'
        elif a == '레포 안 대조 불가':
            ks = [k for k in (chk.get('unknown') or []) if k != 'workspace_inputs']
            a += '(' + (', '.join(C.CATEGORY_LABEL.get(k, k) for k in ks) or '기록 전체') + ')'
        elif a == '무결성 경보':
            # 기록이 쓰는 고정 문장만(verification/record.py) — 나머지는 묶는다(codex 재검토 #3)
            ks = [INTEGRITY_KINDS.get(str(x).split(' — ')[0], '기타 무결성 경보') for x in rec.get('integrity') or []]
            a += '(' + ', '.join(dict.fromkeys(ks)) + ')'
        elif a == '기록 요약을 읽지 못함' and rec.get('unreadable_why'):
            a += f'({rec["unreadable_why"]})'
        elif a.startswith('필수 검사 실패('):
            a = '필수 검사 실패(' + ', '.join(_disp(x, rec) for x in rec['required_failed'][:4]) + ')'
        elif a.startswith('필수 검사 판정 불가('):
            a = '필수 검사 판정 불가(' + ', '.join(_disp(x, rec) for x in rec['required_indeterminate'][:4]) + ')'
        elif a == '기준 판을 정하지 못함' and v.get('why'):
            a += f'({v["why"][0]})'
        out.append(a)
    return out


def clean(v):
    """기준선(첫 실행)에서 조용히 넘겨도 되는가 — 이상이 없으면. 「검증 완료 아님」만으로는 이상이 아니다
    (미검증 숫자가 있다고 지난 글을 전부 이상으로 보내면 첫 실행이 알림으로 넘친다 — 사용자 11/08). 숨기지는 않는다:
    그런 글 수는 기준선 안내에 따로 센다."""
    return not anomalies(v)


def unverified_numbers(v):
    """미검증 숫자 수 — 값이 없거나 정수가 아니면 None(모른다). 0 으로 바꾸지 않는다(codex 6회 #3)."""
    n = (v.get('recorded') or {}).get('numbers') or {}
    u = n.get('unverified')
    return u if isinstance(u, int) and not isinstance(u, bool) and u >= 0 else None


def fully_verified(v):
    """검증 완료 — 경고·빈칸 없는 pass 이고 미검증 숫자가 0 으로 확인됐다(모르면 완료 아님, KR 은 숫자 대조가 없어 완료 아님)."""
    rec = v.get('recorded') or {}
    return bool(rec.get('readable') and rec.get('verified') and rec.get('status') == 'pass'
                and rec.get('numbers') and unverified_numbers(v) == 0)


def fingerprint(v):
    """같은 사건인지 — 정정(조판 외 변경)은 넣지 않는다: 정정은 발행 건별 알림을 만들지 않는다."""
    rec = v.get('recorded') or {}
    key = [v['kind'], v.get('record_commit'), (v.get('check') or {}).get('overall'),
           sorted(((v.get('check') or {}).get('cats') or {}).items()),
           rec.get('status'), rec.get('publish_ok'), rec.get('verified'), rec.get('readable')]
    return json.dumps(key, ensure_ascii=False)


# ── 문장 ─────────────────────────────────────────────────────────────────

def headline(v, who=MAC):
    if v['kind'] == AMBIGUOUS:
        return '판정 불가 — ' + '; '.join(v['why'])
    if v['kind'] == NO_RECORD:
        return '발행 전 기록 없음(있어야 하는데 없어요)'
    o = v['check']['overall']
    if o == C.MATCH:
        return '발행본과 검사 기록 일치'
    if o == C.PARTIAL:
        unk = v['check']['unknown']
        return (f'발행본과 검사 기록 — {subject(who)} 확인한 범위는 일치, 대조 불가 {len(unk)}칸'
                f'({", ".join(C.CATEGORY_LABEL.get(k, k) for k in unk)})')
    if o == C.UNKNOWN:
        return '발행 전 기록을 읽지 못했어요 — 확인 필요'
    return '기록 불일치, 확인 필요'


def pair_lines(v, who=MAC):
    chk = v.get('check')
    if not chk:
        return []
    cats = chk['cats']
    out = [_WHO[who]['pair']]
    cw = chk.get('cat_why') or {}
    for k, label in C.CATEGORY_LABEL.items():
        if k not in cats or cats[k] == C.NONE:
            continue
        if k == 'workspace_inputs' and cats[k] == C.UNKNOWN and chk.get('workspace_files') is not None \
                and not cw.get(k):
            files = [_input_name(x) for x in chk.get('workspace_files') or []]
            out.append(f' · {label}: {cats[k]} {chk.get("workspace_only")}개 — 루틴 작업 공간에만 있던 파일이라 '
                       '원본을 보관하지 않았어요(지문만 남아 내용을 다시 볼 수 없어요)')
            if files:
                out.append('   - ' + _more(files, WS_FILES, '개').replace('; ', ', '))
            continue
        line = f' · {label}: {cats[k]}'
        if cats[k] in (C.UNKNOWN, C.MISMATCH):
            rs = [_cut(x, 120) for x in cw.get(k) or []]
            line += ' — ' + (_more(rs, 1) if rs else '이유가 기록되지 않았어요')
        out.append(line)
    if not v.get('same_commit'):
        out.append(' · 기록이 글을 추가한 커밋이 아닌 뒤 커밋에 들어 있어요(기록 커밋 기준으로 대조)')
    return out


WS_FILES = 8
# us/number_audit.UNVERIFIED_KINDS 와 같다(시험이 강제) — 맥 요약에 실어도 되는 고정 분류 이름
UNVERIFIED_KINDS = frozenset({
    '보도·인용 문장', '사전 밖 자산', '자산과 수치 사이가 멀다', '자산 후보 둘 이상', '자산 없음', '시점·구간 단서', '어림수',
    '단위로 필드를 못 정함', '데이터에 없는 자산', '매크로 칸(수치 둘 이상·형식 불일치)', '매크로 표(예상치·표식 없는 행)',
    '연구 원장', '지표 해부', '기타 분류',
    'KR 문장', 'KR 표(지도 밖)', 'KR 업종 멀티기간', 'KR 펀드 블록(위임 안 됨)'})


def _input_name(path):
    """`<datadir>/macro.json` → `macro.json`, `<tg>/telegram.json` → `텔레그램 입력 telegram.json`."""
    root, _, rel = str(path).partition('>/')
    root = root.lstrip('<')
    if not rel:
        return _cut(str(path), 60)
    pre = {'datadir': '', 'tg': '텔레그램 입력 ', 'stance_next': '판단 원장 입력 '}.get(root, f'{root} 입력 ')
    return pre + _cut(rel, 60)


def recorded_lines(v):
    rec = v.get('recorded')
    if rec is None:
        return []
    if not rec.get('readable'):
        return ['[루틴이 남긴 검사 결과]',
                f' · 기록의 요약을 읽지 못했어요 — {rec.get("unreadable_why") or "이유를 몰라요"}. 「통과」로 보지 않아요']
    st = STATUS.get(rec['status'], '모르는 판정')
    out = ['[루틴이 남긴 검사 결과]',
           f' · 판정 {st} · 발행 {"가능" if rec["publish_ok"] else "불가"} · '
           f'설정된 검사 {"완료" if rec["verified"] else "완료 아님"} · 필수 검사 {rec["required_pass"]}/{rec["required"]} 통과']
    budget = [REASON_BUDGET]                 # 갈래 전체가 나눠 쓰는 이유 예산(codex 구현 검토 #1)
    for key, label in (('blocking', '막은 것'), ('indeterminate', '판정 불가'), ('not_run', '실행 안 함'),
                       ('partial', '일부만 검사'), ('note_numbers', '노트 때문인 숫자 실패(설정된 검사 완료 아님)'),
                       ('note_format', '노트 때문인 형식 실패(허용)'), ('ref_failed', '참고 검사 실패'),
                       ('warned', '경고'), ('integrity', '무결성')):
        if rec.get(key):
            out += _gate_lines(label, rec[key], rec.get('reasons') or {}, budget, rec)
    if budget[0] < 0:
        out.append(' · 이유 일부는 길이 제한으로 줄였어요 — 전체는 기록 파일(verification/…)에 있어요')
    n = rec.get('numbers')
    if n:
        out.append(f' · 숫자: 표 칸 {n.get("table_cells", "?")} 대조 · 문장 판정 {n.get("prose_judged", "?")} · '
                   f'자동 대조하지 못한 수치 {n.get("unverified", "?")}개{_unverified_why(n)}')
    elif v.get('market') == 'kr':
        out.append(' · 숫자: KR 은 표 숫자를 기계로 대조하는 검사가 없어요(발행 전·후 모두) — 이 결과에 숫자 검증은 들어 있지 않아요')
    else:
        out.append(' · 숫자: 기록에 숫자 대조 결과가 없어요')
    return out


GATE_LINES = 6            # 한 갈래(경고·막은 것…)에 이름을 적는 검사기 수
REASON_BUDGET = 1800      # 이유 문장 전체 상한(글자) — 한 사건 3,900자 안에 머리·짝 줄·꼬리를 남긴다


def _gate_lines(label, names, reasons, budget, rec):
    """` · 경고: check_weight — 이유; 이유` — 검사기마다 한 줄. 이유가 없으면 그렇다고 적는다.
    budget = [남은 글자] — 다 쓰면 이유를 빼고 이름만(맨 끝에 한 번 알린다)."""
    out = []
    for nm in names[:GATE_LINES]:
        nm = nm if isinstance(nm, str) else '형식이 다른 항목'
        key = nm if nm in reasons else nm.split('(')[0].strip()
        # 건별 알림은 공개 기록 값을 그대로 실어도 된다 — 이름을 가리면 「무엇이」가 사라진다(Fable #5).
        # 맥 요약(digest_lines·anomaly_labels)만 _disp 로 가린다.
        shown = _cut(nm, 60)
        rs = reasons.get(key)
        if rs is None:
            why = ''
        elif not rs:
            why = ' — 이유가 기록에 없어요'
        else:
            why = ' — ' + _more(rs, REASON_ITEMS)
        if rs and len(why) > budget[0]:
            why, budget[0] = '', -1
        elif budget[0] >= 0:
            budget[0] -= len(why)
        else:
            why = '' if rs else why
        out.append(f' · {label}: {shown}{why}')
    if len(names) > GATE_LINES:
        out.append(f' · {label}: 외 {len(names) - GATE_LINES}개')
    return out


def _unverified_why(n, top=4):
    """` — 자산 없음 129 · 시점·구간 단서 34 …(외 N종)`. 이유별 내역이 없는 옛 기록은 그렇다고 적는다."""
    u = n.get('unverified')
    if not isinstance(u, int) or u <= 0:
        return ''
    by = n.get('unverified_by')
    if not isinstance(by, dict) or not by:
        return ' — 이 기록에는 이유별 내역이 없어요'
    agg = {}
    for k, v in by.items():
        if isinstance(v, int) and not isinstance(v, bool) and v > 0:
            # 고정 분류만 — 바뀐 기록의 자유 문장이 맥 요약에 실리지 않게(codex 구현 검토 #4)
            k = k if k in UNVERIFIED_KINDS else '분류 밖 이유'
            agg[k] = agg.get(k, 0) + v
    items = [f'{k} {v}' for k, v in sorted(agg.items(), key=lambda kv: -kv[1])]
    if not items:
        return ' — 이 기록에는 이유별 내역이 없어요'
    return ' — ' + ' · '.join(items[:top]) + (f' (외 {len(items) - top}종)' if len(items) > top else '')


def correction_line(v):
    c = v.get('corrections')
    if not c or not any(c.values()):
        return []
    return [f' · 그 뒤 조판 외 변경 {c["other"]}회(조판 {c["typeset"]}회·조판인지 가리지 못한 변경 {c["unknown"]}회) — '
            '발행 전 기록은 이전 판 기준, 지금 판은 발행 뒤 재검사 몫(숫자는 US 일간만)']


def footer(who=MAC):
    # 「설정된 검사」의 실행 기록일 뿐 — 보고서 전체의 사실 정확성까지 말하지 않는다(사용자 11/11)
    return ('※ 검사 결과는 클라우드 루틴이 남긴 기록 기준이에요. ' + _WHO[who]['foot']
            + ' 보고서 전체가 사실로 맞다는 뜻은 아니에요.')


FOOTER = footer(MAC)


TEXT_LIMIT = 3800          # outbox 한 건 3,900자(publish_watch.MAX_TEXT)보다 조금 아래 — 넘으면 그 사건은 전송되지 않는다


def render_publish(v, head='[발행]', who=MAC):
    d = v['date']
    lines = [f'{head} {LABEL[v["market"]]} {int(d[5:7])}/{d[8:]} — {headline(v, who)}']
    lines += pair_lines(v, who) + recorded_lines(v) + correction_line(v)
    rec = v.get('recorded') or {}
    if rec.get('python'):
        lines.append(f' · 루틴 파이썬 {rec["python"]}')
    return _fit(lines, footer(who))


def _fit(lines, foot, limit=TEXT_LIMIT):
    """전체 길이 상한 — 넘으면 뒤에서부터 줄을 빼고 몇 줄을 뺐는지 적는다(머리·맺음말은 남긴다)."""
    lines = [x if len(x) <= 600 else x[:599] + '…' for x in lines]
    text = '\n'.join(lines + [foot])
    cut = 0
    while len(text) > limit and len(lines) > 1:
        lines.pop()
        cut += 1
        text = '\n'.join(lines + [f' · 길이 제한으로 줄 {cut}개를 뺐어요 — 전체는 기록 파일에 있어요', foot])
    return text


def digest_lines(v, who=MAC):
    """매일 요약의 [발행 전 기록] 줄 — 짧게."""
    rec = v.get('recorded') or {}
    out = [f' · [발행 전 기록] {headline(v, who)}']
    bad = anomaly_labels(v) if v.get('kind') else []
    if bad:
        out.append('   - 즉시 확인: ' + ', '.join(bad))
    if rec.get('readable'):
        bits = [f'판정 {STATUS.get(rec["status"], "모르는 판정")}', f'설정된 검사 {"완료" if rec["verified"] else "완료 아님"}']
        if rec.get('not_run') or rec.get('partial'):
            bits.append('실행 안 함·일부만 ' + ', '.join(_disp(x, rec) for x in (rec['not_run'] + rec['partial'])[:4]))
        u = unverified_numbers(v)
        if not rec.get('numbers'):
            bits.append('숫자 자동 대조 없음(KR 은 표 숫자 검사가 없어요)' if v.get('market') == 'kr'
                        else '숫자 자동 대조 없음(기록에 숫자 대조 결과가 없어요)')
        elif u is None:
            bits.append('자동 대조하지 못한 수치 수 모름')                            # codex 6회 #3
        elif u:
            bits.append(f'자동 대조하지 못한 수치 {u}개{_unverified_why(rec["numbers"], top=3)}')   # codex 5회 #3
        out.append('   - ' + ' · '.join(bits))
    out += [x.replace(' · 그 뒤', '   - 그 뒤', 1) for x in correction_line(v)]
    return out
