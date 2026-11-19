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
          'pass_with_warnings': '통과(경고 있음)', 'pass_with_gaps': '통과(검증 빈칸 있음)',
          # 2판(prepub-record/2, 2026-11-17) — 검사 상태 na·incomplete, 글 판정 넷
          'na': '해당 없음', 'incomplete': '미완료',
          'verified': '검증됨', 'conditional': '조건부', 'failed': '실패'}
V2 = 'prepub-record/2'

OK, NO_RECORD, AMBIGUOUS = 'ok', 'no_record', 'ambiguous'

MAC, GITHUB = 'mac', 'github'                 # 짝을 다시 확인한 주체
_WHO = {MAC: {'subj': '맥이', 'name': '맥'},
        GITHUB: {'subj': 'GitHub 이', 'name': 'GitHub'}}


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
    조판으로 받지 않는다. merge·삭제·재추가는 순서가 모호하니 판정 불가로 센다.
    base 판에 글이 아직 없으면(기록이 글보다 먼저 들어간 경우) 글이 처음 생긴 판은 수정이 아니다 — 그 뒤부터 센다
    (codex 구현 3회 #6). 표시용 집계라 판정·지문과 무관하다."""
    from review import prose
    rows = _git(root, 'log', '--reverse', '--format=%H %P', f'{base}..{ref}', '--', path).decode().splitlines()
    out = {'typeset': 0, 'other': 0, 'unknown': 0}
    prev = _blob(root, base, path)
    born = prev is not None
    for row in rows:
        parts = row.split()
        if not born:                          # 글의 첫 등장 — 고친 것이 아니라 생긴 것
            prev = _blob(root, parts[0], path)
            born = prev is not None
            continue
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
    v2 = rec.get('format') == V2
    stuck = ('indeterminate', 'incomplete') if v2 else ('indeterminate',)
    numbers = next((g.get('numbers') for g in by if g.get('name') == 'check_numbers'
                    and isinstance(g.get('numbers'), dict)), None)
    # 숫자 결과가 없을 때 왜 없는지 — 검사기 항목이 없다(도입 전) / 실행 안 함 / 판정 불가 / 돌았는데 결과가 빠졌다(손상)
    ngate = next((g for g in by if g.get('name') == 'check_numbers'), None)
    return {
        'readable': True, 'status': s['status'], 'publish_ok': s['publish_ok'],   # status 는 원래 값 — 지문이 쓴다(표시는 STATUS 밖이면 「모르는 판정」, 재검토 10회)
        'verified': s['verified'], 'blocking': [_as_str(x) for x in s.get('blocking') or []],
        'not_run': [g['name'] for g in by if g.get('status') == 'not_run'],
        'partial': [g['name'] for g in by if g.get('status') == 'partial'],
        'indeterminate': [g['name'] for g in by if g.get('status') in stuck],
        'required_indeterminate': [g['name'] for g in by if g.get('status') in stuck and g.get('required', True)],
        'v2': v2, 'na': [g['name'] for g in by if g.get('status') == 'na'] if v2 else [],
        'inputs': _inputs_view(s.get('inputs')) if v2 else None,
        'required_failed': [g['name'] for g in by if g.get('status') == 'fail' and g.get('required', True)],
        'ref_failed': [g['name'] for g in by if g.get('status') == 'fail' and not g.get('required', True)],
        'note_numbers': [_as_str(x) for x in s.get('note_numbers') or []],
        'note_format': [_as_str(x) for x in s.get('note_format') or []],
        'warned': [_as_str(x) for x in s.get('warned') or []],
        'integrity': [x if isinstance(x, str) else '형식이 다른 무결성 항목' for x in s.get('integrity') or []],
        'allowed': allowed,
        'required': sum(1 for g in by if g.get('required', True)),
        'required_pass': sum(1 for g in by if g.get('required', True) and g.get('status') in ('pass', 'warn')),
        # 2판: 정상 「해당 없음」은 통과도 실패도 아니다 — 따로 센다(1a 구현 검토 #11)
        'required_na': sum(1 for g in by if g.get('required', True) and g.get('status') == 'na') if v2 else 0,
        'numbers': numbers, 'numbers_gate': None if ngate is None else ngate.get('status'), 'python': _str(_dict(rec.get('code')).get('python')),
        'created': _str(_dict(rec.get('created_at')).get('kst')),
        'reasons': {g['name']: gate_reasons(g) for g in by if g.get('status') not in ('pass',)},
    }


def _inputs_view(inp):
    """2판 기록의 자료 상태 — 「무엇이·왜」 문장(기록이 정책 이름 + 상태 한국어로 만든 것)과 분류 안 된 파일."""
    if not isinstance(inp, dict):
        return {'blocking': [], 'unclassified': [], 'warnings': 0, 'unconfirmed_empty': [], 'recollect_failed': [],
                'accepted_missing': [], 'readable': inp is None}
    lst = lambda k: [x for x in inp.get(k) or [] if isinstance(x, str)] if isinstance(inp.get(k), list) else []
    return {'blocking': lst('blocking'), 'unclassified': lst('unclassified'),
            'warnings': len(lst('warnings')), 'unconfirmed_empty': lst('unconfirmed_empty'),
            'recollect_failed': lst('recollect_failed'), 'accepted_missing': lst('accepted_missing'),
            'readable': True}


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
_COUNT_HEAD = re.compile(r'^\s*(경고|위반|고칠 것|warn|WARN)\s*\d+\s*건')
# 실패의 이유로 고를 줄 — 검사기가 위반이라고 표시한 줄(check_readability 의 `FAIL …`, check_style 의 `- …`, `위반: …`)
_VIOL_LINE = re.compile(r'^\s*(FAIL\s|FATAL\b|위반|-\s)')
_VIOL_MARK = re.compile(r'^\s*(FAIL\s+|-\s+)')
# 이유가 아닌 줄 — 파일 머리(`== <html>`)·통계·참고(note/info)·수리 안내·기준 설명(check_readability.LEGEND)
_NOISE_LINE = re.compile(r'^\s*(==\s|문장 \d+ · 중앙|산문 문단 없음|note\b|info\b|repair\b|기준 — 세는 대상|수치: 숫자 토큰'
                         r'|FAIL 은 조판이|말투 이상 없음)')
_HINT_LINE = re.compile(r'^\s*[·•]\s')
_BULLET = re.compile(r'^\s*[·•\-]\s*')
_INFO_LINE = re.compile(r'^\s*(분량:|OK\b)')
REASON_LEN, REASON_ITEMS = 400, 2       # 기록에서 읽는 원문 상한 — 알림에 실을 때는 문장 단위로 다시 줄인다(_show)


def gate_reasons(g):
    """검사기 하나가 통과가 아닌 이유 — 공개 레포 기록(verification/*.json)에 이미 있는 마스킹된 문장만 쓴다.
    `reason` 이 있으면 그것, 없으면 `items` 중 상태에 맞는 줄. 없으면 빈 목록(→ 「이유가 기록에 없어요」)."""
    if isinstance(g.get('reason'), str) and g['reason'].strip():
        return [_cut(g['reason'])]
    raw = g.get('items')
    items = [x for x in raw if isinstance(x, str) and x.strip()] if isinstance(raw, list) else []   # 손상 형식은 이유 없음
    items = [x for x in items if not _COUNT_HEAD.match(x)]      # 「경고 1건(…) — <html>」 머리줄은 이유가 아니다
    if g.get('status') == 'warn':
        items = ([x for x in items if _WARN_LINE.match(x)] or [x for x in items if _BULLET.match(x)]
                 or [x for x in items if not _NOISE_LINE.match(x)])
        items = [_BULLET.sub('', _WARN_LINE.sub('', x)).lstrip(' :：') for x in items]
    elif g.get('status') == 'fail':
        # 실패의 이유는 위반 줄이다(codex 구현 1회 #3·2회 #1). 두 줄 상한(REASON_ITEMS)을 적용하기 전에 고른다:
        # ① 검사기가 위반이라고 표시한 줄 ② 머리·통계·참고·경고가 아닌 줄 ③ 경고·힌트 줄(--strict 는 warn 으로도 실패한다).
        # 머리·통계만 남으면 이유로 싣지 않는다(→ 「이유가 기록에 없어요」) — 「외 N건」은 위반 줄만 센다.
        real = [x for x in items if not _NOISE_LINE.match(x)]
        soft = [x for x in real if _WARN_LINE.match(x) or _INFO_LINE.match(x) or _HINT_LINE.match(x)]
        hard = [x for x in real if x not in soft]
        marked = [x for x in hard if _VIOL_LINE.match(x)]
        items = [_VIOL_MARK.sub('', x) for x in (marked or hard or
                                                 [x for x in soft if not _INFO_LINE.match(x)])]
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
            out.append(('필수 검사 미완료(' if rec.get('v2') else '필수 검사 판정 불가(')
                       + ', '.join(rec['required_indeterminate'][:4]) + ')')   # 참고 검사는 이상 아님(#2)
        inp = rec.get('inputs') or {}
        if inp.get('blocking') or inp.get('unclassified'):
            out.append('자료 미완료')
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
        elif a.startswith('필수 검사 미완료('):
            a = '필수 검사 미완료(' + ', '.join(_disp(x, rec) for x in rec['required_indeterminate'][:4]) + ')'
        elif a == '자료 미완료':
            inp = rec.get('inputs') or {}
            a += f'({len(inp.get("blocking") or [])}개 · 분류 안 된 파일 {len(inp.get("unclassified") or [])}개)'
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
    """검증 완료 — 경고·빈칸 없는 pass 이고 미검증 숫자가 0 으로 확인됐다(모르면 완료 아님). KR 은 표만 대조하고
    문장 숫자는 대조하지 않으므로 완료가 아니다(2026-11-13 — 미검증 0 이 찍혀도)."""
    rec = v.get('recorded') or {}
    return bool(v.get('market') != 'kr' and rec.get('readable') and rec.get('verified')
                and rec.get('status') == ('verified' if rec.get('v2') else 'pass')
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


WS_FILES = 8
# us/number_audit.UNVERIFIED_KINDS 와 같다(시험이 강제) — 맥 요약에 실어도 되는 고정 분류 이름
UNVERIFIED_KINDS = frozenset({
    '보도·인용 문장', '사전 밖 자산', '자산과 수치 사이가 멀다', '자산 후보 둘 이상', '자산 없음', '시점·구간 단서', '어림수',
    '단위로 필드를 못 정함', '데이터에 없는 자산', '매크로 칸(수치 둘 이상·형식 불일치)', '매크로 표(예상치·표식 없는 행)',
    '연구 원장', '지표 해부', '기타 분류',
    'KR 문장', 'KR 표(지도 밖)', 'KR 업종 멀티기간', 'KR 펀드 블록(위임 안 됨)'})
# 알림에 보이는 이름(2026-11-19) — 판정·기록은 원래 분류 그대로, 표시만 바꾼다. 내부 낱말(원장·지도·KR 접두)을 뺀다
UNVERIFIED_SHOWN = {k: k for k in UNVERIFIED_KINDS}
UNVERIFIED_SHOWN.update({
    '단위로 필드를 못 정함': '단위로 항목을 못 정함', '연구 원장': '리서치 기록', '지표 해부': '지표 세부',
    'KR 문장': '문장', 'KR 표(지도 밖)': '기타 표', 'KR 업종 멀티기간': '업종 기간별', 'KR 펀드 블록(위임 안 됨)': '펀드 블록'})


def _input_name(path):
    """`<datadir>/macro.json` → `macro.json`, `<tg>/telegram.json` → `텔레그램 입력 telegram.json`."""
    root, _, rel = str(path).partition('>/')
    root = root.lstrip('<')
    if not rel:
        return _cut(str(path), 60)
    # 모르는 뿌리 이름도 길이를 재기 전에 줄인다 — 긴 이름 하나가 알림 예산을 다 써서 실패 이유를 밀어내지 않게(3회 #1)
    pre = {'datadir': '', 'tg': '텔레그램 입력 ', 'stance_next': '판단 원장 입력 '}.get(root, f'{_cut(root, 20)} 입력 ')
    return pre + _cut(rel, 60)


# KR 기록에 숫자 결과가 없는 이유(codex 설계 검토 #10) — (건별 알림 문장, 매일 요약 꼬리)
KR_NO_NUMBERS = {
    'before': ('이 기록에는 표 숫자 검사가 없어요(검사 도입 전 기록)', '도입 전'),
    'na': ('표 숫자 검사가 해당 없음(적용일 전 글)', '해당 없음'),
    'incomplete': ('표 숫자 검사가 미완료로 끝났어요(자료 누락·실행 오류)', '미완료'),
    'not_run': ('표 숫자 검사를 실행 안 함(적용일 전 글이거나 건너뜀)', '실행 안 함'),
    'indeterminate': ('표 숫자 검사가 판정 불가로 끝났어요', '판정 불가'),
    'corrupt': ('표 숫자 검사는 돌았는데 결과가 기록에서 빠졌어요(기록 손상)', '기록 손상'),
}


def _kr_no_numbers(rec):
    st = rec.get('numbers_gate')
    if st is None:
        return 'before'
    # 「해당 없음」·「미완료」는 2판의 상태다 — 1판 기록에 그 값이 있으면 전처럼 기록 손상으로 읽는다
    return st if st in ('not_run', 'indeterminate') + (('na', 'incomplete') if rec.get('v2') else ()) else 'corrupt'


def _kr_scope(n):
    tc, u = _count(n.get('table_cells')), _count(n.get('unverified'))
    return (f'표 {tc}칸 대조' if tc is not None else '표 대조 칸 수 모름') + (f', 미검증 {u}개' if u is not None else ', 미검증 수 모름')


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
            k = UNVERIFIED_SHOWN[k] if k in UNVERIFIED_KINDS else '분류 밖 이유'
            agg[k] = agg.get(k, 0) + v
    items = [f'{k} {v}' for k, v in sorted(agg.items(), key=lambda kv: -kv[1])]
    if not items:
        return ' — 이 기록에는 이유별 내역이 없어요'
    return ' — ' + ' · '.join(items[:top]) + (f' (외 {len(items) - top}종)' if len(items) > top else '')


# ── 발행 건별 알림 배치(2026-11-19 사용자 결정) ───────────────────────────────
# 세 덩어리: 발행 상태(막혔나) / 볼 것(오늘 사람이 볼 것) / 검증 범위(프로그램이 확인한 것과 못 한 것 — 매일 같은 자리).
# 정상인 칸은 한 줄로 접고, 어긋난 칸만 이유와 함께 펼친다. 검사기 내부 이름은 싣지 않고(모르는 이름은 기록 값 그대로),
# 판정·지문은 건드리지 않는다 — 문구만.

GATE_LABEL = {
    'unconfirmed': '「확인필요」 표시', 'check_macro': '매크로 표', 'check_price_context': '가격 맥락',
    'check_sector_perf': '업종 성과', 'check_session': '세션', 'check_fed': '연준', 'check_auction': '국채 입찰',
    'check_liquidity': '유동성', 'check_calendar': '일정', 'check_sources': '출처', 'check_telegram': '텔레그램 인용',
    'check_weight': '분량', 'check_movers': '움직인 종목', 'check_fund': '펀드', 'check_numbers': '숫자 대조',
    'check_research': '리서치', 'check_style': '문체', 'check_readability': '가독성', 'apply_colors_check': '등락 색',
    'check_kr_stance': 'KR 판단',
}
# 다시 읽어 보라는 힌트만 내는 검사기(AGENTS.md 규칙 5 — 막지 않는다) → 「참고」
_GATE_SLOT = re.compile(r'^((?:(?! — ).)* — )(' + '|'.join(sorted(GATE_LABEL, key=len, reverse=True)) + r')(?=\(|$)')
HINT_GATES = frozenset({'check_style', 'check_readability'})
CHECK, REVIEW, NOTE = '확인 필요', '검토 권고', '참고'
_TAGS = ((CHECK, '확인'), (REVIEW, '검토'), (NOTE, '참고'))
_NORMAL = frozenset({'pass', 'pass_with_warnings', 'pass_with_gaps'})
_V2_VERDICTS = frozenset({'verified', 'conditional', 'incomplete', 'failed', 'na'})


def _verdict_ko(rec):
    """기록 판정의 한국어 — 2판의 판정 이름은 2판 기록에서만 읽는다. 1판 기록에 그 값이 있으면 1a 전처럼 「모르는 판정」
    (codex 구현 검토 2회차 C4 — 공용 표에 2판 값이 들어와 손상된 1판 기록이 「검증됨」으로 보였다)."""
    st = rec.get('status')
    if st in _V2_VERDICTS and not rec.get('v2'):
        return '모르는 판정'
    return STATUS.get(st, '모르는 판정')
SHOW_LEN = 160            # 알림 한 이유의 상한 — 넘으면 문장 끝에서 끊는다(중간 자르기 없음)
LOOK_ITEMS = 8


def _gate_label(nm):
    return GATE_LABEL.get(nm, _cut(nm, 60))


MORE, OMIT = ' (이하 기록 파일)', '(긴 항목 생략 — 기록 파일에 있어요)'


def _clip(x, n):
    """x 의 앞부분을 n 자 안에서 낱말 경계로 — 문장 끝 → 쉼표·줄표 → 낱말 사이 순. 한 낱말도 못 넣으면 빈 문자열."""
    if len(x) <= n:
        return x
    if n <= 0:
        return ''
    head = x[:n + 1]                           # n 번째 글자 바로 뒤가 빈칸이면 거기도 낱말 경계다
    end = max(head.rfind('. ', 0, n), head.rfind('; ', 0, n))
    if end > 0:
        return head[:end + 1]
    end = max(head.rfind(' — '), head.rfind(', '))
    if end <= 0:
        end = head.rfind(' ')
    return head[:end].rstrip(' —,') if end > 0 else ''


def _show(x, n=SHOW_LEN):
    """긴 이유를 줄인다 — 낱말 중간에서 자르지 않고, 「상태 — 원인」의 원인이 통째로 사라지지 않게 한다
    (codex 구현 2회 #5·3회 #2). 첫 ` — ` 가 있으면 앞(상태)과 뒤(원인)를 따로 줄인다: 원인에 적어도 절반을 주고,
    앞이 길면 앞을 「(중략)」으로 접는다 — 줄표가 상한 밖에 있어도 원인은 남는다. 상한보다 긴 한 덩어리는
    통째로 빼고 뺐다고 적는다."""
    x = ' '.join(x.split())
    if len(x) <= n:
        return x
    sep = x.find(' — ')
    if sep <= 0:
        body = _clip(x, n)
        return body + MORE if body else OMIT
    status, cause = x[:sep], x[sep + 3:]
    c = _clip(cause, max(n // 2, n - len(status) - 3))
    st = _clip(status, max(n - 3 - len(c or OMIT), n // 4))
    left = status if st == status else (st + ' (중략)' if st else '(앞부분 생략)')
    right = cause if c == cause else (c + MORE if c else OMIT)
    return f'{left} — {right}'


_W_BODY = re.compile(r'서술형 본문이 (\d+)자다\(평상시 ([\d,]+)~([\d,]+)자(?:, 뉴스 요약 (\d+)자 별도)?\)')
_W_MACRO = re.compile(r'매크로가 (\d+)자로 평소 상한 ([\d,]+)자를 넘는다')
_W_RATIO = re.compile(r'시황군 (\d+)자 < 판단군 (\d+)자')
_S_DAYS = re.compile(r'날수를 고유어로 썼다 — ((?:「[^」]+」(?:, )?)+)')


def _weight(reasons):
    """분량 경고(us/weight.warnings) — 숫자와 방향은 남기고, 작성 지시문은 독자용 한 문장으로.
    길다 + 시황 < 판단이면 「덜기」와 「빠진 설명 확인」을 함께 쓴다 — 긴 글에 더 쓰라는 말로 읽히지 않게(사용자 11/19)."""
    facts, kinds, rest = [], set(), []
    for r in reasons:
        if m := _W_BODY.match(r):
            news = f', 뉴스 요약 {int(m[4]):,}자 별도' if m[4] else ''
            facts.append(f'본문 {int(m[1]):,}자(평소 {m[2]}~{m[3]}자{news})')
            kinds.add('long')
        elif m := _W_MACRO.match(r):
            facts.append(f'매크로 {int(m[1]):,}자(평소 상한 {m[2]}자)')
            kinds.add('macro')
        elif m := _W_RATIO.match(r):
            facts.append(f'시황 {int(m[1]):,}자 < 판단 {int(m[2]):,}자')
            kinds.add('ratio')
        else:
            rest.append(r)
    if not facts:
        return [], rest
    if 'ratio' in kinds and kinds - {'ratio'}:
        advice = '반복된 해석부터 덜고, 주요 시장 움직임·원인 설명이 빠졌는지 확인'
    elif 'ratio' in kinds:
        advice = '주요 시장 움직임·원인 설명이 빠졌는지 확인(비율을 맞추려고 시황을 덧붙이지 않기)'
    elif 'long' in kinds:
        advice = '반복 해석·장중 시각·변화 없는 판단부터 덜기(중요한 분석은 유지)'
    else:
        advice = '발표가 몰린 날이 아니면 반복 해석부터 덜기'
    return [', '.join(facts) + '. ' + advice], rest


def _style(reasons):
    """날수 고유어 경고 — 낱말별 횟수. 검사기는 앞 4개까지만 적으므로 넷이면 「이상일 수 있음」."""
    out, rest = [], []
    for r in reasons:
        m = _S_DAYS.match(r)
        if not m:
            rest.append(r)
            continue
        words = re.findall(r'「([^」]+)」', m[1])
        cnt = {}
        for w in words:
            cnt[w] = cnt.get(w, 0) + 1
        s = ' · '.join(f'「{w}」 {n}회' for w, n in cnt.items())
        if len(words) >= 4:
            s += f'({len(words)}회 이상일 수 있음)'
        out.append(s + '. 자연스러우면 수정 불필요')
    return out, rest


_NAME_LISTS = ('blocking', 'required_failed', 'required_indeterminate', 'indeterminate', 'note_numbers', 'note_format',
               'ref_failed', 'warned', 'not_run', 'partial')


def _names(rec):
    """(이름 → 표시용 열쇠 함수, 그 열쇠로 다시 묶은 이유 사전) — 이유 조회·표시명·중복 제거·힌트 분류·검증 범위가
    모두 이 한 쌍을 쓴다(codex 구현 2회 #7·3회 #5). 기록이 「check_weight (설명)」처럼 꼬리를 붙였을 때, 꼬리를 뗀
    이름이 설정에 있는 검사기이거나 기록에 따로 나오는 이름이면 같은 검사기로 본다 — 이유 사전의 열쇠도 같은 규칙으로
    합친다(꼬리 붙은 이름이 사전에 있어도 그대로 두지 않는다). 표시 전용: 판정이 읽는 원래 이름은 건드리지 않는다."""
    reasons = rec.get('reasons') if isinstance(rec.get('reasons'), dict) else {}
    cfg = set(rec.get('allowed') or ()) | set(GATE_LABEL)
    present = {k for k in reasons if isinstance(k, str)}
    for lst in _NAME_LISTS:
        present.update(x for x in rec.get(lst) or [] if isinstance(x, str))

    def key(nm):
        if not isinstance(nm, str):
            return '형식이 다른 항목'
        if nm in cfg:
            return nm
        base = nm.split('(')[0].strip()
        return base if base and base != nm and (base in cfg or base in present) else nm
    merged = {}
    for k, rs in reasons.items():
        got = merged.setdefault(key(k), [])
        got += [r for r in rs or [] if r not in got]
    return key, merged


def _key(nm, rec):
    return _names(rec)[0](nm)


def _gate_text(key, state, reasons):
    """볼 것 한 줄의 본문. state 가 None 이면 경고(검사기 이름 대신 내용부터), 아니면 「이름 상태 — 이유」.
    key = `_key()` 로 정규화한 이름."""
    rs = reasons.get(key) or []
    label = _gate_label(key)
    if state is not None:
        return f'{label} {state} — ' + (_more([_show(r) for r in rs], REASON_ITEMS) if rs else '이유가 기록에 없어요')
    human, rest = (_weight(rs) if key == 'check_weight' else _style(rs) if key == 'check_style' else ([], rs))
    parts = human[:REASON_ITEMS] + ([f'(같은 종류 외 {len(human) - REASON_ITEMS}건)'] if len(human) > REASON_ITEMS else [])
    if rest:
        parts.append(f'{label}: ' + _more([_show(r) for r in rest], REASON_ITEMS))
    return '; '.join(parts) if parts else f'{label}: 이유가 기록에 없어요'


def look_items(v):
    """[(꼬리표, 본문)] — 확인 필요 → 검토 권고 → 참고 순. 한 검사기는 한 줄(가장 무거운 갈래에서)."""
    rec = v.get('recorded') or {}
    if not rec.get('readable'):
        return []
    key, reasons = _names(rec)
    out, seen = [], set()

    def add(tag, names, state):
        for nm in names:
            nm = key(nm)
            if nm in seen:
                continue
            seen.add(nm)
            out.append((tag, _gate_text(nm, state, reasons)))
    # 구체적인 갈래부터 — 노트로 허용된 실패·판정 불가가 일반 「실패」에 가려지지 않게(codex 구현 1회 #1)
    for x in rec['integrity']:
        out.append((CHECK, '무결성 경보: ' + _show(x)))
    seen.add('integrity')                     # 기록이 blocking 에 넣는 무결성 표식 — 위 경보가 대표한다(#2)
    if 'integrity' in rec['blocking'] and not rec['integrity']:
        out.append((CHECK, '무결성 경보: 이유가 기록에 없어요'))
    if rec.get('inputs'):
        seen.add('inputs')                    # 2판 기록의 자료 상태 표식 — 발행 상태의 「자료 미완료」 줄이 대표한다
    add(CHECK, rec['required_indeterminate'], '미완료' if rec.get('v2') else '판정 불가')
    add(REVIEW, rec['note_numbers'], '실패(노트로 숫자 실패 허용)')
    add(NOTE, rec['note_format'], '실패(노트로 형식 실패 허용)')
    add(CHECK, rec['blocking'] + rec['required_failed'], '실패')
    add(REVIEW, rec['ref_failed'], '실패(참고 검사)')
    add(REVIEW, [x for x in rec['warned'] if key(x) not in HINT_GATES], None)
    add(NOTE, [x for x in rec['warned'] if key(x) in HINT_GATES], None)
    order = {t: i for i, (t, _) in enumerate(_TAGS)}
    return sorted(out, key=lambda x: order[x[0]])


def _workspace_case(chk):
    """작업 공간 전용 입력이 「원본을 보관하지 않아서」 대조 불가인 평상시 모양 — 검증 범위로 보낸다."""
    cw = chk.get('cat_why') or {}
    return ((chk.get('cats') or {}).get('workspace_inputs') == C.UNKNOWN and chk.get('workspace_files') is not None
            and not cw.get('workspace_inputs'))


def _pair_phrase(chk, who):
    w = _WHO[who]['name']
    o, cats = chk['overall'], chk.get('cats') or {}
    off = [k for k, s in cats.items() if s in (C.UNKNOWN, C.MISMATCH)]
    if o == C.MATCH or (off == ['workspace_inputs'] and _workspace_case(chk)):
        return f'발행본과 검사 기록 일치({w} 대조' + (', 작업 공간 입력 제외)' if off else ')')
    if o == C.UNKNOWN:
        return f'발행 전 기록을 읽지 못했어요({w} 대조) — 확인 필요'
    if any(s == C.MISMATCH for s in cats.values()):
        return f'발행본과 검사 기록 불일치({w} 대조)'
    return f'발행본과 검사 기록 일부 대조 불가({w} 대조)'


GATE_LINES = 6            # 자료 상태 한 갈래에 적는 줄 수


def _inputs_lines(rec):
    """2판 기록(1a 를 켠 뒤)의 자료 상태 — 「무엇이·왜」(사용자 11/11). 1판 기록에는 이 칸이 없어 줄도 없다."""
    inp = rec.get('inputs') if rec.get('readable') else None
    if not inp:
        return []
    out = []
    # 자료가 없거나 비었거나 낡았거나 수집 실패
    for x in inp['blocking'][:GATE_LINES]:
        out.append(f' · 자료 미완료: {_cut(x, 120)}')
    if len(inp['blocking']) > GATE_LINES:
        out.append(f' · 자료 미완료: 외 {len(inp["blocking"]) - GATE_LINES}개')
    for x in inp['unclassified'][:GATE_LINES]:
        out.append(f' · 자료 미완료: 분류되지 않은 파일 {_cut(_input_name(x), 80)}')
    if inp['warnings']:
        out.append(f' · 수집 상태 표시 없는 자료 {inp["warnings"]}개(적용일 전이라 막지 않았어요)')
    # 빈 대상 목록이 정상 0건인지 수집 실패인지 모른다 — 적용일 전이라 막지 않았다(1a 구현 검토 #2)
    for x in inp['unconfirmed_empty'][:GATE_LINES]:
        out.append(f' · 대상 없음 미확인: {_cut(x, 120)}')
    if len(inp['unconfirmed_empty']) > GATE_LINES:
        out.append(f' · 대상 없음 미확인: 외 {len(inp["unconfirmed_empty"]) - GATE_LINES}개')
    # 이번 수집은 그 파일을 못 썼고 같은 날 옛 판으로 검사했다 — 적용일 전이라 막지 않았다(1a 구현 검토 2회차 F3)
    for x in inp.get('recollect_failed', [])[:GATE_LINES]:
        out.append(f' · 재수집 실패: {_cut(x, 120)}')
    if len(inp.get('recollect_failed', [])) > GATE_LINES:
        out.append(f' · 재수집 실패: 외 {len(inp["recollect_failed"]) - GATE_LINES}개')
    # 사람이 승인한 기한부 결측 — 공식 기관이 발표하지 않은 지표를 검증 대상에서 조건부로 뺐다(수집 실패 허용이 아니다).
    # 예외 ID·제외 지표·승인일·만료일·영향 범위가 한 줄에 다 들어가야 한다(2026-11-17 사용자 조건 5)
    for x in inp.get('accepted_missing', [])[:GATE_LINES]:
        out.append(f' · 승인된 결측(원천 미발표): {_cut(x, 600)}')
    if len(inp.get('accepted_missing', [])) > GATE_LINES:
        out.append(f' · 승인된 결측(원천 미발표): 외 {len(inp["accepted_missing"]) - GATE_LINES}개')
    return out


def status_lines(v, who=MAC):
    out = ['■ 발행 상태']
    if v['kind'] == AMBIGUOUS:
        return out + ['판정 불가 — ' + '; '.join(v['why'])] + correction_line(v)
    if v['kind'] == NO_RECORD:
        return out + ['발행 전 기록 없음(있어야 하는데 없어요)'] + correction_line(v)
    rec, chk = v.get('recorded') or {}, v.get('check') or {}
    bits = []
    if rec.get('readable'):
        bits.append(f'필수 검사 {rec["required"]}개 중 통과 {rec["required_pass"]} · 해당 없음 {rec["required_na"]}'
                    if rec.get('v2') else f'필수 검사 {rec["required_pass"]}/{rec["required"]} 기록상 통과')
        if not rec['publish_ok']:
            bits.append('기록상 발행 불가')
        if rec['status'] not in _NORMAL and not _ref_only(rec):
            bits.append(f'기록 판정 {_verdict_ko(rec)}')
    elif v.get('recorded') is not None:
        out.append(f'기록의 요약을 읽지 못했어요 — {rec.get("unreadable_why") or "이유를 몰라요"}. 「통과」로 보지 않아요')
    if v.get('recorded') is None:
        out.append('기록 요약이 없어요 — 「통과」로 보지 않아요')
    if chk:
        bits.append(_pair_phrase(chk, who))
    else:
        bits.append(f'발행본과 검사 기록을 대조하지 못했어요({_WHO[who]["name"]} 대조 결과 없음)')
    if bits:
        out.append(' · '.join(bits))
    out += _inputs_lines(rec)
    cw = chk.get('cat_why') or {}
    for k, label in C.CATEGORY_LABEL.items():
        st = (chk.get('cats') or {}).get(k)
        if st not in (C.UNKNOWN, C.MISMATCH) or (k == 'workspace_inputs' and _workspace_case(chk)):
            continue
        rs = [_show(x, 120) for x in _cat_reasons(chk, k, st)]
        out.append(f' · {label}: {st} — ' + (_more(rs, 1) if rs else '이유가 기록되지 않았어요'))
    # 확인하는 것은 두 커밋이 같은가뿐이다 — 앞뒤 순서는 말하지 않는다(codex 구현 2회 #8)
    if v.get('same_commit') is False:
        out.append(' · 글을 추가한 커밋과 기록을 담은 커밋이 달라요(다른 커밋 — 기록 커밋 기준으로 대조)')
    elif v.get('same_commit') is None:
        out.append(' · 글과 기록이 같은 커밋에 들어갔는지 확인 불가')
    return out + correction_line(v)


def _cat_reasons(chk, k, st):
    """대조 칸 하나의 이유 문장들 — 불일치 칸이면 실제 불일치 이유를 앞에(codex 구현 2회 #2). 이유별 상태는
    `repo_check` 가 함께 준 `cat_detail` 에서 읽는다(문장 속 낱말로 짐작하지 않는다). 검사기 표시명은 이름 자리에만
    쓴다 — 경로 속 파일명은 그대로(#6). `cat_detail` 이 없거나 `cat_why` 와 어긋나면 기록 순서 그대로."""
    cw = [x for x in (chk.get('cat_why') or {}).get(k) or [] if isinstance(x, str)]
    det = (chk.get('cat_detail') or {}).get(k)
    if (isinstance(det, list) and len(det) == len(cw)
            and all(isinstance(d, dict) and d.get('text') == x for d, x in zip(det, cw))):
        rows, detailed = [(d.get('state'), x, d.get('gate')) for d, x in zip(det, cw)], True
    else:
        rows, detailed = [(None, x, None) for x in cw], False
    if st == C.MISMATCH:
        rows.sort(key=lambda r: r[0] != C.MISMATCH)          # 안정 정렬 — 같은 상태끼리는 기록 순서
    # 표시명은 검사 코드 칸에서만, 그리고 이유별 내역이 있으면 그 이유의 검사기 이름이 확인된 때만(3회 #4) —
    # 다른 칸의 값(입력 참조 등)이 우연히 검사기 이름과 같아도 바꾸지 않는다
    return [_name_slot(x, gate) if k == 'scripts' and (gate is not None or not detailed) else x
            for _s, x, gate in rows]


def _name_slot(text, gate=None):
    """「… — 검사기이름」「… — 검사기이름(경로)」의 이름 자리만 표시명으로. 그 밖의 글자는 건드리지 않는다."""
    m = _GATE_SLOT.match(text)
    if not m or (gate is not None and m[2] != gate):
        return text
    return m[1] + GATE_LABEL[m[2]] + text[m.end():]


def _ref_only(rec):
    """기록 판정이 실패·판정 불가인데 그 까닭이 참고 검사뿐인가 — 필수 검사는 모두 통과했고 기록도 발행 가능이라고 한다.
    이때 「기록 판정 판정 불가」를 발행 상태에 쓰면 글 전체의 판정처럼 읽혀 첫 줄 「발행 통과」와 어긋난다(3회 #3).
    검증 범위에서 참고 검사 때문이라고 밝힌다. 표시 전용."""
    return bool(rec.get('readable') and rec['status'] in ('fail', 'indeterminate') and rec['publish_ok']
                and not (rec['blocking'] or rec['required_failed'] or rec['required_indeterminate'] or rec['integrity'])
                and (rec['ref_failed'] or [x for x in rec['indeterminate'] if x not in rec['required_indeterminate']]))


def _numbers_line(v, rec):
    n = rec.get('numbers')
    if not n:
        if v.get('market') == 'kr':
            return '숫자: ' + KR_NO_NUMBERS[_kr_no_numbers(rec)][0] + ' — 이 결과에 숫자 검증은 들어 있지 않아요'
        return '숫자: 기록에 숫자 대조 결과가 없어요'
    pj = n.get('prose_judged')
    tc = _count(n.get('table_cells'))           # 손상된 기록의 자유 문장을 싣지 않는다(codex 구현 1회 #4)
    done = (f'표 {tc}칸' if tc is not None else '표 대조 칸 수 모름') + (f'·문장 {pj}개' if _count(pj) else '') + ' 자동 대조'
    u = n.get('unverified')
    if _count(u) is None:
        return done + ' · 범위 밖 숫자 수 모름'
    if u == 0:
        return done + ' · 범위 밖 숫자 없음'
    why = _unverified_why(n, top=4)
    why = why[3:] if why.startswith(' — ') and '이유별 내역이 없어요' not in why else '이유별 내역 없는 기록'
    return done + f' · 숫자 {u}개 범위 밖({why}). 오류 {u}건이라는 뜻은 아님'


def _count(x):
    return x if isinstance(x, int) and not isinstance(x, bool) and x >= 0 else None


def _gaps(rec):
    """검사 빈칸 — 돌지 않았거나 일부만 본 검사기. [(갈래, 이름)]. 판정과 무관한 표시용 묶음."""
    if not rec.get('readable'):
        return []
    key = _names(rec)[0]
    ref_indet = [x for x in rec['indeterminate'] if x not in rec['required_indeterminate']]
    out, seen = [], set()
    for label, nm in ([('실행 안 함', x) for x in rec['not_run']] + [('일부만 검사', x) for x in rec['partial']]
                      + [('판정 불가(참고 검사)', x) for x in ref_indet]):
        nm = key(nm)                            # 볼 것과 같은 열쇠 — 같은 검사기를 두 번 세지 않는다
        if nm not in seen:
            seen.add(nm)
            out.append((label, nm))
    return out


def gap_count(rec):
    """첫 줄의 「검사 빈칸 N건」 — 빈칸 목록이 없는데 기록이 「설정된 검사 완료 아님」이라고 하면 1건으로 센다
    (실패·판정 불가·노트로 허용된 숫자 실패처럼 볼 것이 이유를 말하는 경우는 빼고). 휴대폰 미리보기는 첫 줄만 보이므로 여기서 드러나야 한다."""
    if not rec.get('readable'):
        return 0
    n = len(_gaps(rec))
    explained = (rec['note_numbers'] or rec['blocking'] or rec['required_failed'] or rec['required_indeterminate']
                 or rec['integrity'] or rec['ref_failed'])                     # 볼 것이 이미 「왜 완료가 아닌지」를 말한다
    return n or int(not rec['verified'] and not explained)


FULL, BRIEF, NAMES, COUNT = 0, 1, 2, 3     # 검증 범위 빈칸을 줄이는 사다리 — render_publish 가 넘칠 때 한 칸씩 내려간다
GAP_NAMES, GAP_NAMES_LEN = 10, 300


def scope_lines(v, brief=FULL):
    """검증 범위 — 오늘의 문제가 아니라 프로그램이 확인한 것과 못 한 것. 매일 같은 자리에 보인다.
    brief = 길이가 넘칠 때 빈칸을 줄이는 정도: BRIEF 이유를 빼고 이름만 / NAMES 한 줄에 갈래별 건수와 이름 앞 몇 개 /
    COUNT 건수만. 볼 것의 실패 이유·숫자 범위 줄·맺음말보다 먼저 줄인다(codex 구현 2회 #3)."""
    rec, chk = v.get('recorded') or {}, v.get('check') or {}
    out = []
    if rec.get('readable'):
        out.append(_numbers_line(v, rec))
        reasons = _names(rec)[1]
        gaps = _gaps(rec)
        if gaps and brief >= NAMES:
            kinds = {}
            for label, _nm in gaps:
                kinds[label] = kinds.get(label, 0) + 1
            line = f' · 검사 빈칸 {len(gaps)}건(' + ' · '.join(f'{k} {n}건' for k, n in kinds.items()) + ')'
            if brief == NAMES:
                names, room = [], GAP_NAMES_LEN
                for _l, nm in gaps[:GAP_NAMES]:               # 이름 앞 몇 개 — 한 줄이 길어지지 않을 만큼만
                    room -= len(_gate_label(nm)) + 2
                    if room < 0 and names:
                        break
                    names.append(_gate_label(nm))
                line += ': ' + ', '.join(names) + (f' (외 {len(gaps) - len(names)}건)' if len(gaps) > len(names) else '')
            out.append(line)
        for label, key in ([] if brief >= NAMES else gaps):   # 길이를 재기 전에 자르지 않는다 — 넘치면 render 가 줄인다(#2)
            rs = reasons.get(key) or []
            why = '' if brief else ' — ' + (_more([_show(r) for r in rs], REASON_ITEMS) if rs else '이유가 기록에 없어요')
            out.append(f' · {label}: {_gate_label(key)}{why}')
        if gap_count(rec) and not gaps:
            out.append(' · 설정된 검사 완료 아님(이유가 기록에 없어요)')
        if _ref_only(rec):
            # 필수 검사가 다 통과했을 때만 그렇다고 쓴다 — 실행 안 함·일부만인 필수 검사가 있으면 과장이다(codex 구현 4회)
            done = rec.get('required') and rec.get('required_pass') == rec.get('required')
            out.append(f' · 기록 판정은 「{STATUS[rec["status"]]}」 — 참고 검사 때문이에요'
                       + ('(필수 검사는 모두 기록상 통과)' if done else ''))
    if chk and _workspace_case(chk):
        files = [_input_name(x) for x in chk.get('workspace_files') or []]
        out.append(f' · 작업 공간 전용 입력 {chk.get("workspace_only")}개는 원본을 보관하지 않아 대조 못 함(지문만 남음)'
                   + (': ' + _more(files, WS_FILES, '개').replace('; ', ', ') if files else ''))
    return ['■ 검증 범위'] + out if out else []


def correction_line(v):
    c = v.get('corrections')
    if not c or not any(c.values()):
        return []
    n = c['typeset'] + c['other'] + c['unknown']
    # 기준은 「기록을 처음 담은 판」이다 — 발행 시점이라고 단정하지 않는다(codex 구현 2회 #8). 기록이 없으면 기준을 말하지 않는다
    base = '위 검사는 기록을 처음 담은 판 기준, ' if v.get('kind') == OK else ''
    return [f' · 발행 뒤 수정 {n}회(조판 {c["typeset"]}회 · 조판 외 {c["other"]}회 · 판별 못 함 {c["unknown"]}회) — '
            f'{base}수정된 판은 발행 뒤 검토가 따로 봐요(숫자 재검사는 US 일간만)']


def footer(who=MAC):
    # 「설정된 검사」의 실행 기록일 뿐 — 보고서 전체의 사실 정확성까지 말하지 않는다(사용자 11/11)
    return f'※ {_WHO[who]["name"]}은 기록 일치만 확인. 검사 재실행이나 전체 내용의 사실 검증은 아님'


FOOTER = footer(MAC)


TEXT_LIMIT = 3800          # outbox 한 건 3,900자(publish_watch.MAX_TEXT)보다 조금 아래 — 넘으면 그 사건은 전송되지 않는다


def needs_check(v):
    """첫 줄의 「확인 필요」 — 표시 전용(판정·지문은 `anomalies`·`fingerprint` 그대로). 이상이 있거나, 기록 판정이
    모르는 값이거나(구현 1회 #8), 대조 결과 자체가 없으면(2회 #4) 「발행 통과」라고 쓰지 않는다."""
    rec = v.get('recorded') or {}
    # 발행 상태에 「기록 판정 …」이 찍히는 경우 전부 — 모르는 값, 또는 참고 검사로 설명되지 않는 실패·판정 불가(3회 #3)
    odd = rec.get('readable') and rec.get('status') not in _NORMAL and not _ref_only(rec)
    return bool(anomalies(v) or odd or (v.get('kind') == OK and not v.get('check')))


def render_publish(v, head='[발행]', who=MAC):
    d = v['date']
    items = look_items(v)
    rec = v.get('recorded') or {}
    state = '확인 필요' if needs_check(v) else '발행 통과'
    counts = [f'{short} {n}건' for tag, short in _TAGS if (n := sum(1 for t, _ in items if t == tag))]
    if (g := gap_count(v.get('recorded') or {})):
        counts.append(f'검사 빈칸 {g}건')
    top = [' · '.join([f'{head} {LABEL[v["market"]]} {int(d[5:7])}/{d[8:]}', state] + counts), ''] + status_lines(v, who)
    foot = footer(who)
    # 넘치면 덜어 내는 순서(_fit 은 마지막 안전망) — 남기는 우선순위는 「확인 필요」 항목과 그 이유 > 빈칸 이름 > 검토·참고 항목:
    # ① 빈칸의 이유 ② 검토·참고 항목(뒤에서부터) ③ 빈칸 이름을 건수와 앞 몇 개로 ④ 건수만 ⑤ 확인 필요 항목(뒤에서부터).
    # 숫자 범위 줄과 맺음말은 끝까지 남는다(codex 구현 2회 #3 — 빈칸 목록이 길어도 실패 이유가 먼저 지워지지 않게).
    n, nc = len(items), sum(1 for t, _ in items if t == CHECK)
    tries = ([(FULL, n), (BRIEF, n)] + [(BRIEF, k) for k in range(n - 1, nc - 1, -1)] + [(NAMES, nc), (COUNT, nc)]
             + [(COUNT, k) for k in range(nc - 1, -1, -1)])
    for brief, k in tries:
        scope = scope_lines(v, brief)
        lines = list(top)
        if items:
            lines += ['', '■ 볼 것'] + [f'{i}. [{t}] {x}' for i, (t, x) in enumerate(items[:k], 1)]
            if len(items) > k:
                lines.append(f' · 외 {len(items) - k}건 — 길이 제한으로 줄였어요, 전체는 기록 파일에')
        lines += [''] + scope if scope else []
        if brief and _gaps(rec):
            lines.append(' · 검사 빈칸의 이유는 길이 제한으로 뺐어요 — 기록 파일에 있어요' if brief == BRIEF else
                         ' · 검사 빈칸의 이름·이유는 길이 제한으로 줄였어요 — 전체는 기록 파일에 있어요')
        lines.append('')
        if _size('\n'.join(lines + [foot])) <= TEXT_LIMIT:
            break
    return _fit(lines, foot, TEXT_LIMIT)


def _size(text):
    """전송 길이 — 코드포인트(outbox 3,900)와 UTF-16 단위(텔레그램 4,096) 중 큰 쪽(codex 구현 1회 #9)."""
    return max(len(text), len(text.encode('utf-16-le')) // 2)


def _fit(lines, foot, limit=TEXT_LIMIT):
    """전체 길이 상한 — 넘으면 뒤에서부터 줄을 빼고 몇 줄을 뺐는지 적는다(머리·맺음말은 남긴다)."""
    lines = [x if len(x) <= 600 else _show(x, 600) for x in lines]
    text = '\n'.join(lines + [foot])
    cut = 0
    while _size(text) > limit and len(lines) > 1:
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
        bits = [f'판정 {_verdict_ko(rec)}', f'설정된 검사 {"완료" if rec["verified"] else "완료 아님"}']
        if rec.get('not_run') or rec.get('partial'):
            bits.append('실행 안 함·일부만 ' + ', '.join(_disp(x, rec) for x in (rec['not_run'] + rec['partial'])[:4]))
        if rec.get('na'):
            bits.append('해당 없음 ' + ', '.join(_disp(x, rec) for x in rec['na'][:4]))
        inp = rec.get('inputs') or {}
        if inp.get('blocking') or inp.get('unclassified'):
            bits.append(f'자료 미완료 {len(inp["blocking"]) + len(inp["unclassified"])}개')
        if inp.get('unconfirmed_empty'):
            bits.append(f'대상 없음 미확인 {len(inp["unconfirmed_empty"])}개')
        if inp.get('recollect_failed'):
            bits.append(f'재수집 실패 {len(inp["recollect_failed"])}개')
        if inp.get('accepted_missing'):
            bits.append(f'승인된 결측(원천 미발표)이 있는 자료 {len(inp["accepted_missing"])}개')
        u = unverified_numbers(v)
        if rec.get('numbers') and v.get('market') == 'kr':
            bits.append(_kr_scope(rec['numbers']).split(',')[0])         # 「표 54칸 대조」 — 미검증 수는 바로 뒤
        if not rec.get('numbers'):
            bits.append(f'표 숫자 대조 없음({KR_NO_NUMBERS[_kr_no_numbers(rec)][1]})' if v.get('market') == 'kr'
                        else '숫자 자동 대조 없음(기록에 숫자 대조 결과가 없어요)')
        elif u is None:
            bits.append('자동 대조하지 못한 수치 수 모름')                            # codex 6회 #3
        elif u:
            bits.append(f'자동 대조하지 못한 수치 {u}개{_unverified_why(rec["numbers"], top=3)}')   # codex 5회 #3
        out.append('   - ' + ' · '.join(bits))
    out += [x.replace(' · 발행 뒤', '   - 발행 뒤', 1) for x in correction_line(v)]
    return out
