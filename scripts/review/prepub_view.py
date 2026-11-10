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


def recorded(rec):
    """루틴이 남긴 검사 결과 — 기록 그대로. 필수 필드가 없으면 「읽지 못함」."""
    s = rec.get('summary') if isinstance(rec, dict) else None
    gates = rec.get('gates') if isinstance(rec, dict) else None
    lists = ('blocking', 'note_numbers', 'note_format', 'warned', 'integrity', 'not_run')
    if (not isinstance(s, dict) or not isinstance(gates, list) or not gates
            or not isinstance(s.get('publish_ok'), bool) or not isinstance(s.get('verified'), bool)
            or not isinstance(s.get('status'), str)
            or any(not isinstance(s.get(k), list) for k in lists)          # 빠진 칸을 빈 목록으로 읽지 않는다
            or any(not isinstance(g, dict) or not isinstance(g.get('name'), str)
                   or not isinstance(g.get('status'), str) for g in gates)):
        return {'readable': False}        # 문자열 "false" 를 참으로 읽지 않는다(codex 구현 검토 #7)
    by = [g for g in gates if isinstance(g, dict)]
    numbers = next((g.get('numbers') for g in by if g.get('name') == 'check_numbers'
                    and isinstance(g.get('numbers'), dict)), None)
    return {
        'readable': True, 'status': s['status'], 'publish_ok': s['publish_ok'],
        'verified': s['verified'], 'blocking': list(s.get('blocking') or []),
        'not_run': [g['name'] for g in by if g.get('status') == 'not_run'],
        'partial': [g['name'] for g in by if g.get('status') == 'partial'],
        'indeterminate': [g['name'] for g in by if g.get('status') == 'indeterminate'],
        'required_indeterminate': [g['name'] for g in by if g.get('status') == 'indeterminate' and g.get('required', True)],
        'required_failed': [g['name'] for g in by if g.get('status') == 'fail' and g.get('required', True)],
        'ref_failed': [g['name'] for g in by if g.get('status') == 'fail' and not g.get('required', True)],
        'note_numbers': list(s.get('note_numbers') or []), 'note_format': list(s.get('note_format') or []),
        'warned': list(s.get('warned') or []), 'integrity': list(s.get('integrity') or []),
        'required': sum(1 for g in by if g.get('required', True)),
        'required_pass': sum(1 for g in by if g.get('required', True) and g.get('status') in ('pass', 'warn')),
        'numbers': numbers, 'python': (rec.get('code') or {}).get('python'),
        'created': (rec.get('created_at') or {}).get('kst'),
    }


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
        v['recorded'] = recorded(v['check'].get('rec'))
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
        return '발행 전 기록 일치'
    if o == C.PARTIAL:
        return f'발행 전 기록 — {subject(who)} 확인한 범위는 일치, 대조 불가 {len(v["check"]["unknown"])}칸'
    if o == C.UNKNOWN:
        return '발행 전 기록을 읽지 못했어요 — 확인 필요'
    return '기록 불일치, 확인 필요'


def pair_lines(v, who=MAC):
    chk = v.get('check')
    if not chk:
        return []
    cats = chk['cats']
    out = [_WHO[who]['pair']]
    for k, label in C.CATEGORY_LABEL.items():
        if k in cats and cats[k] != C.NONE:
            extra = f' {chk.get("workspace_only")}개' if k == 'workspace_inputs' and cats[k] == C.UNKNOWN else ''
            out.append(f' · {label}: {cats[k]}{extra}')
    if not v.get('same_commit'):
        out.append(' · 기록이 글을 추가한 커밋이 아닌 뒤 커밋에 들어 있어요(기록 커밋 기준으로 대조)')
    for w in chk['why'][:3]:
        out.append(f'   - {w[:120]}')
    return out


def recorded_lines(v):
    rec = v.get('recorded')
    if rec is None:
        return []
    if not rec.get('readable'):
        return ['[루틴이 남긴 검사 결과]', ' · 기록의 요약을 읽지 못했어요 — 「통과」로 보지 않아요']
    st = STATUS.get(rec['status'], f'{rec["status"]}(모르는 판정)')
    out = ['[루틴이 남긴 검사 결과]',
           f' · 판정 {st} · 발행 {"가능" if rec["publish_ok"] else "불가"} · '
           f'검증 {"완료" if rec["verified"] else "완료 아님"} · 필수 {rec["required_pass"]}/{rec["required"]} 통과']
    for key, label in (('blocking', '막은 것'), ('indeterminate', '판정 불가'), ('not_run', '실행 안 함'),
                       ('partial', '일부만 검사'), ('note_numbers', '노트 때문인 숫자 실패(검증 완료 아님)'),
                       ('note_format', '노트 때문인 형식 실패(허용)'), ('ref_failed', '참고 검사 실패'),
                       ('warned', '경고'), ('integrity', '무결성')):
        if rec.get(key):
            out.append(f' · {label}: {", ".join(rec[key][:6])}')
    n = rec.get('numbers')
    if n:
        out.append(f' · 숫자: 표 칸 {n.get("table_cells", "?")} 대조 · 문장 판정 {n.get("prose_judged", "?")} · '
                   f'미검증 {n.get("unverified", "?")}')
    elif v.get('market') == 'kr':
        out.append(' · 숫자: KR 은 표 숫자를 기계로 대조하는 검사가 없어요(발행 전·후 모두) — 이 결과에 숫자 검증은 들어 있지 않아요')
    else:
        out.append(' · 숫자: 기록에 숫자 대조 결과가 없어요')
    return out


def correction_line(v):
    c = v.get('corrections')
    if not c or not any(c.values()):
        return []
    return [f' · 그 뒤 조판 외 변경 {c["other"]}회(조판 {c["typeset"]}회·판정 불가 {c["unknown"]}회) — '
            '발행 전 기록은 이전 판 기준, 지금 판은 발행 뒤 재검사 몫(숫자는 US 일간만)']


def footer(who=MAC):
    return '※ 검사 결과는 클라우드 루틴이 남긴 기록 기준이에요. ' + _WHO[who]['foot']


FOOTER = footer(MAC)


def render_publish(v, head='[발행]', who=MAC):
    d = v['date']
    lines = [f'{head} {LABEL[v["market"]]} {int(d[5:7])}/{d[8:]} — {headline(v, who)}']
    lines += pair_lines(v, who) + recorded_lines(v) + correction_line(v)
    rec = v.get('recorded') or {}
    if rec.get('python'):
        lines.append(f' · 루틴 파이썬 {rec["python"]}')
    return '\n'.join(lines + [footer(who)])


def digest_lines(v, who=MAC):
    """매일 요약의 [발행 전 기록] 줄 — 짧게."""
    rec = v.get('recorded') or {}
    out = [f' · [발행 전 기록] {headline(v, who)}']
    bad = anomalies(v) if v.get('kind') else []
    if bad:
        out.append('   - 즉시 확인: ' + ', '.join(bad))
    if rec.get('readable'):
        bits = [f'판정 {STATUS.get(rec["status"], rec["status"])}', f'검증 {"완료" if rec["verified"] else "완료 아님"}']
        if rec.get('not_run') or rec.get('partial'):
            bits.append('실행 안 함·일부만 ' + ', '.join((rec['not_run'] + rec['partial'])[:4]))
        u = unverified_numbers(v)
        if not rec.get('numbers'):
            bits.append('숫자 자동 대조 없음')
        elif u is None:
            bits.append('미검증 숫자 수 모름')                            # codex 6회 #3
        elif u:
            bits.append(f'미검증 숫자 {u}')                               # codex 5회 #3
        out.append('   - ' + ' · '.join(bits))
    out += [x.replace(' · 그 뒤', '   - 그 뒤', 1) for x in correction_line(v)]
    return out
