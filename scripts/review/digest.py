"""매일 검증 알림 — 발행본마다 「무엇이 검증됐고 무엇이 안 됐나」를 텔레그램 한 통으로 (2026-11-08).

사용자 지시: 「AI 리포트의 내용·숫자가 맞는지 검증하는 장치가 있어야 하고 본인이 알아야 한다」 →
「보고서에 적지 말고 매일 알림으로」 → 「텔레그램으로」. 그래서 발행본과 발행 루틴은 건드리지 않는다.
AI 를 부르지 않는다(토큰 0). CLI 는 `scripts/verify_digest.py`.

알림이 거짓말을 하지 않게 지키는 것(codex 설계 검토 1회차, plan.md 2026-11-08 표):
- 숫자 재검사는 **발행 뒤 재검사**다 — 루틴 안의 발행 전 결과는 레포에 남지 않는다. 발행 커밋의 글과
  데이터를 함께 꺼내 `check_numbers.py --json` 을 다시 돌린다. 경고도 「확인 필요」다(문장 층은 경고만
  내고 exit 0). 입력 오류·시간 초과·모순된 종료 코드는 전부 「판정 불가」.
- 검토 상태는 review_gate 의 분류(미검토·조판·판정 불가)와 만료를 **공개판에** 그대로 쓴다. 원장에
  이름만 있는 것(baseline)은 「읽지 않음」이다. `findings` 는 원장에 적힌 채택 지적 수일 뿐 정정 수가
  아니다 — 그렇게 적는다.
- 시각 창이 아니라 **글마다 지난 알림의 문장과 비교**한다. 늦게 끝난 검토, 늦게 푸시된 글도 다음
  알림에 「바뀐 상태」로 나온다. 끝나지 않은 글은 7일 동안 꼬리에 남는다.
- 마크다운 해석 없이 보낸다(이스케이프 실수로 전송이 통째로 실패하지 않게). 한 통 4,000자 안 —
  나누어 보내면 일부만 간 상태를 기록할 수 없다.
- 토큰·대화 번호는 macOS 열쇠고리에만(공개 레포). curl 에는 설정 stdin 으로 넘겨 프로세스 목록에 안 남긴다.
  파이썬 urllib 이 아니라 curl 인 이유: 프레임워크 파이썬 3.13 에 인증서 묶음이 없어 SSL 검증에 실패했다.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone

from review import kinds

KST = timezone(timedelta(hours=9))
LIMIT = 3900
SEND_HOUR = 9
WINDOW_DAYS = 7          # 오늘 포함 7개 날짜
KEEP_DAYS = 90           # 미해결·미전달·내용이 바뀐 글을 따라가는 한도 — 넘으면 알리고 멈춘다
STALE_HOURS = 30
SERVICE = 'fdo2a-telegram'
STATE_ENV = 'VERIFY_DIGEST_STATE'
DEFAULT_STATE = os.path.expanduser('~/Library/Application Support/fdo2a/verify_digest.json')
UNREVIEWED = ('news', 'kr/news')          # 날짜 파일명이지만 자동 검토가 없는 글
TRACK = tuple(kinds.SECTIONS) + UNREVIEWED
LABEL = {'us': 'US 일간', 'kr': 'KR 일간', 'weekly': 'US 주간', 'kr/weekly': 'KR 주간',
         'japan/posts': '일본 주간', 'japan/daily': '일본 일간', 'news': 'US 뉴스',
         'kr/news': 'KR 뉴스'}
DATA_FILES = ('data/market_data.json', 'data/econ_indicators.json', 'data/macro_metrics.json',
              'data/fund_board.json', 'data/liquidity/liquidity.json')
REQUIRED_DATA = 'data/market_data.json'
CAVEAT = ('※ 숫자 재검사는 US 일간만 해요. 문장 속 숫자 상당수는 미검증이고, '
          '뜻·해석이 맞는지는 기계 검사 밖이에요.')
WEEKDAY = '월화수목금토일'
_DAY = re.compile(r'(\d{4}-\d{2}-\d{2})\.html$')


class StateError(Exception):
    pass


class SendError(Exception):
    pass


def now_kst():
    return datetime.now(KST)


def state_path():
    return os.environ.get(STATE_ENV) or DEFAULT_STATE


# ── 어떤 글을 따라가나 ─────────────────────────────────────────────────────

def post_day(path):
    section = kinds.section_of(path)
    if section in kinds.SECTIONS:
        return kinds.publish_day(path)
    if section in UNREVIEWED:
        m = _DAY.search(path)
        try:
            return date.fromisoformat(m.group(1)) if m else None
        except ValueError:
            return None
    return None


def tracked_posts(tree, today, extra=()):
    """공개판에서 따라갈 글 — (경로, blob, 날짜). 날짜는 파일명(주간은 주 키)에서.

    최근 7개 날짜의 글 + `extra`(지난 알림에서 미해결이던 글, 처음 보는 옛 글) 가운데 30일 안의 것.
    창만 쓰면 늦게 푸시된 옛 글과 7일 넘게 안 끝난 글이 조용히 빠진다(codex 구현 검토 #1).
    """
    extra = set(extra)
    out = []
    for path in sorted(tree):
        day = post_day(path)
        if not day or day > today:
            continue
        recent = today - timedelta(days=WINDOW_DAYS - 1) <= day
        kept = path in extra and today - timedelta(days=KEEP_DAYS) <= day
        if recent or kept:
            out.append((path, tree[path], day))
    return out


def _kept(path, today):
    d = post_day(path)
    return bool(d) and today - timedelta(days=KEEP_DAYS - 1) <= d <= today


def in_window(path, today):
    d = post_day(path)
    return bool(d) and today - timedelta(days=WINDOW_DAYS - 1) <= d <= today


def kept_posts(tree, today):
    """공개판에서 오늘 포함 90개 날짜 안의 글 전부 — 매일 전부 다시 평가한다.

    창·미해결·미전달을 따로 고르던 방식은 가장자리마다 글이 조용히 빠졌다(codex 구현 검토 1-3회차:
    밀린 글, 창 밖 수정, 창 밖 상태 변화, 첫 알림 전 미해결). 다시 평가하고 지난 전달 기록과 비교하면
    바뀐 것만 나온다. 숫자 재검사는 (blob, 코드) 캐시라 비용이 거의 없다.
    """
    return [(p, tree[p], post_day(p)) for p in sorted(tree) if _kept(p, today)]


def _names(paths):
    return ', '.join(_day_label(k) for k in paths)       # 전부 — 건수만 있고 이름이 없는 글이 없게


def reconcile(posts, state, published, today):
    """(비교할 전달 기록, 알림 머리 문장, 새 추적표 {경로: blob}). posts = 90일 안 공개판 글 전부(평가 끝),
    published = 공개판 {경로: blob}.

    - 첫 알림: 창 밖의 **끝난** 글만 기준판으로 적는다 — 끝나지 않은 옛 글은 첫 알림에 나온다.
    - 공개판에서 사라진 글(전달 기록·미해결·지난 추적표에 있던 것)은 알리고 기록에서 뺀다.
    - 90일이 지나 빠지는 글 가운데 미해결이었거나, 못 보냈거나, 마지막으로 보낸 판과 공개판이 다르면 알린다.
    - 90일보다 오래된 날짜의 글이 새로 올라오면 알린다(검사는 하지 않는다). 첫 알림의 기존 글은 제외.
    """
    lines = {k: v for k, v in (state.get('lines') or {}).items() if isinstance(v, dict)}
    open_ = set(state.get('open') or [])
    prev = state.get('tracked') if isinstance(state.get('tracked'), dict) else {}
    notes = []
    first = not state.get('last_sent')
    if first:
        for p in posts:
            if not in_window(p['path'], today) and resolved(p):
                lines[p['path']] = {'sha': p.get('sha'), 'text': block(p)}
    gone = sorted(k for k in set(lines) | open_ | set(prev) if k not in published)
    if gone:
        notes.append(f'공개판에서 사라진 글 {len(gone)}건: {_names(gone)}')
        for k in gone:
            lines.pop(k, None)
    aged = sorted(k for k, sha in prev.items()
                  if k in published and not _kept(k, today)
                  and (k in open_ or (lines.get(k) or {}).get('sha') != published[k]))
    if aged:
        notes.append(f'{KEEP_DAYS}일이 지나 추적을 멈춘 글 {len(aged)}건(안 끝났거나 못 보낸 글): {_names(aged)}')
    if not first and isinstance(state.get('all'), list):
        known = set(state['all'])
        late = sorted(k for k in published if k not in known and post_day(k)
                      and not _kept(k, today) and post_day(k) < today)
        if late:
            notes.append(f'{KEEP_DAYS}일보다 오래된 날짜의 글이 새로 올라왔어요(검사 안 함) '
                         f'{len(late)}건: {_names(late)}')
    lines = {k: v for k, v in lines.items() if _kept(k, today)}
    return lines, notes, {p['path']: p.get('sha') for p in posts}


def checker_version(paths, base):
    """숫자 재검사 캐시 키 — 결과에 영향을 주는 파일 내용의 해시(`base` 기준 상대 경로 + 내용).
    레포 전체 커밋을 쓰면 발행 커밋마다 캐시가 무너지고, 절대 경로를 쓰면 매 tick 새 임시 사본이라
    재사용이 안 된다(codex 구현 재검토 4·5회차 #4)."""
    import hashlib
    h = hashlib.sha256()
    for p in sorted(paths, key=lambda x: os.path.relpath(x, base)):
        h.update(os.path.relpath(p, base).encode())
        try:
            with open(p, 'rb') as fh:
                h.update(fh.read())
        except OSError:
            h.update(b'<missing>')
    return h.hexdigest()[:12]


def auto_reviewed(path):
    return kinds.section_of(path) in kinds.SECTIONS


# ── 검토 상태 ────────────────────────────────────────────────────────────

def review_state(path, sha, reviewed, buckets):
    """(상태, 원장 지적 수). buckets = 공개판 분류 {경로: pending|expired|unavailable|typography}."""
    bucket = buckets.get(path)
    if bucket == 'pending':
        return '대기', None
    if bucket == 'expired':
        return '만료', None
    if bucket == 'unavailable':
        return '판정 불가', None
    entry = reviewed.get(path)
    if not isinstance(entry, dict):
        return '기록 없음', None
    if entry.get('baseline'):
        return '읽지 않음', None
    try:
        findings = int(entry.get('findings') or 0)
    except (TypeError, ValueError):
        findings = None
    return '완료', findings


# ── 숫자 재검사 ──────────────────────────────────────────────────────────

def needs_replay(path):
    if kinds.section_of(path) != 'us':
        return False
    m = _DAY.search(path)
    if not m:
        return False
    from us import number_audit
    return m.group(1) >= number_audit.EFFECTIVE


COUNT_KEYS = ('tokens_seen', 'table_cells', 'prose_judged', 'unverified', 'delegated', 'excluded')


def _error(reason):
    return {'kind': 'error', 'reason': reason[:160]}


def number_result(code, stdout, stderr, timed_out):
    """`check_numbers.py --json` 의 결과 → 알림용 사전. 모르는 것은 전부 판정 불가."""
    if timed_out:
        return _error('시간 초과')
    if code not in (0, 1, 2):
        return _error(f'알 수 없는 종료 코드 {code}')
    if code == 2:
        lines = [x.strip() for x in (stderr or '').splitlines() if x.strip()]
        why = lines[-1] if lines else '입력을 읽지 못했어요'
        return _error(why[len('FATAL: '):] if why.startswith('FATAL: ') else why)
    try:
        last = [x for x in (stdout or '').splitlines() if x.strip()][-1]
        obj = json.loads(last)
        if not isinstance(obj, dict):
            raise ValueError
    except (IndexError, ValueError):
        return _error('결과를 읽지 못했어요')
    if obj.get('skipped') is True:
        return {'kind': 'skipped'} if code == 0 else _error('건너뛴 결과에 실패 코드')
    # 계약이 깨진 응답을 정상으로 읽지 않는다(codex 구현 검토 #6, 재검토 #4)
    counts = obj.get('counts')
    if obj.get('skipped') is not False or not isinstance(obj.get('warnings'), list) \
            or not isinstance(obj.get('violations'), list) or not isinstance(counts, dict) \
            or not all(isinstance(x, str) for x in obj['warnings'] + obj['violations']) \
            or not all(type(counts.get(k)) is int for k in COUNT_KEYS):
        return _error('결과 형식이 약속과 달라요')
    warnings, violations = obj['warnings'], obj['violations']
    if (code == 1) != bool(violations):
        return _error('종료 코드와 결과가 어긋나요')
    kind = 'violation' if violations else 'warn' if warnings else 'ok'
    return {'kind': kind, 'warnings': len(warnings), 'violations': len(violations),
            'counts': obj.get('counts') or {}, 'lines': (violations + warnings)[:3]}


_INDEX_GAP = re.compile(r'indices\.[A-Z]+\.\d{4}-\d{2}-\d{2}')


def kr_index_gaps(agg):
    """주간 집계 missing 에서 「세션 날짜 × 지수」 빈 칸만(kr.period.finalize 가 적는 키)."""
    return sorted(m for m in (agg or {}).get('missing') or [] if _INDEX_GAP.fullmatch(m))


def kr_index_gap_notes(aggs):
    """{주 키: 주간 집계} → 알림 머리 줄. 발행 때 빠진 지수는 자동 보완하지 않는다(2026-11-10)."""
    notes = []
    for key in sorted(aggs or {}):
        gaps = kr_index_gaps(aggs[key])
        if not gaps:
            continue
        what = ', '.join(f'{g.split(".")[1]} {g.split(".")[2]}' for g in gaps[:6])
        notes.append(f'KR 주간 {key} 지수 누락: {what} — 새벽 재수집으로 자동 보완하지 않아요. '
                     f'원자료를 확인해 글을 정정한 뒤 수동 승격(versions.py promote)해야 주간이 나가요')
    return notes


def kr_weekly_aggs(root, rev='origin/main', last=2):
    """원격 판의 최근 KR 주간 집계 두 개 — 읽지 못하면 빈 dict(알림은 계속)."""
    r = _git_bytes(root, 'ls-tree', '--name-only', rev, 'kr/data/weekly/')
    if r.returncode != 0:
        return {}
    names = sorted(n for n in r.stdout.decode().split() if re.search(r'\d{4}-W\d{2}\.json$', n))[-last:]
    out = {}
    for n in names:
        b = _git_bytes(root, 'show', f'{rev}:{n}')
        if b.returncode == 0:
            try:
                out[os.path.basename(n)[:-5]] = json.loads(b.stdout)
            except ValueError:
                continue
    return out


def _git_bytes(root, *args):
    return subprocess.run(['git', '-C', root, *args], capture_output=True, timeout=60)


def _report_date(root, commit):
    got = _git_bytes(root, 'show', f'{commit}:{REQUIRED_DATA}')
    if got.returncode:
        return None, False
    try:
        obj = json.loads(got.stdout.decode('utf-8'))
        return (obj.get('report_date') if isinstance(obj, dict) else None), True
    except ValueError:
        return None, True


def _data_commit(root, commit, path):
    """(데이터를 꺼낼 커밋, 실패 이유). 발행 커밋의 데이터가 다른 날이면 그 날 판을 거슬러 찾는다.

    글을 나중에 다시 그린 커밋(펀드 점검판 20편 다시 그림 632671bc 등)이 발행 커밋이 되면 그
    커밋의 데이터는 다음 세션이다 — 그대로 대조하면 검사기가 날짜가 다르다며 판정 불가를 낸다.
    그 날짜의 `market_data.json` 가운데 발행 커밋 이전의 가장 최근 판을 쓴다(나머지 데이터도 그 커밋에서).
    """
    m = _DAY.search(path)
    want = m.group(1) if m else None
    have, exists = _report_date(root, commit)
    if not exists:
        return None, f'{REQUIRED_DATA} 이 발행 커밋에 없어요'
    if not want or not have or have == want:
        return commit, ''
    log = _git_bytes(root, 'log', '--format=%H', '-n', '120', commit, '--', REQUIRED_DATA)
    for c in log.stdout.decode().split() if log.returncode == 0 else []:
        if _report_date(root, c)[0] == want:
            return c, ''
    return None, f'그 날({want}) 판 데이터를 못 찾았어요 — 발행 커밋 데이터는 {have}'


def replay_numbers(root, path, sha, checker, commit_of=None, timeout=180):
    """발행 커밋의 글(이 blob)과 그 커밋의 데이터로 숫자 검사를 다시 돌린다."""
    if commit_of is None:
        import review_gate
        commit_of = review_gate.publish_commit
    try:
        commit = commit_of(root, path, sha)
    except Exception as exc:  # noqa: BLE001 — 알림은 계속 간다
        return _error(f'발행 커밋을 찾다 실패했어요 ({type(exc).__name__})')
    if not commit:
        return _error('발행 커밋을 못 찾았어요')
    work = tempfile.mkdtemp(prefix='verify-digest-')
    try:
        post = _git_bytes(root, 'cat-file', 'blob', sha)
        if post.returncode:
            return _error('글 내용을 못 꺼냈어요')
        html = os.path.join(work, 'posts', os.path.basename(path))
        os.makedirs(os.path.dirname(html))
        with open(html, 'wb') as fh:
            fh.write(post.stdout)
        datadir = os.path.join(work, 'data')
        source, why = _data_commit(root, commit, path)
        if not source:
            return _error(why)
        for rel in DATA_FILES:
            got = _git_bytes(root, 'show', f'{source}:{rel}')
            if got.returncode:
                if rel == REQUIRED_DATA:
                    return _error(f'{rel} 이 발행 커밋에 없어요')
                continue
            dest = os.path.join(work, rel)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, 'wb') as fh:
                fh.write(got.stdout)
        try:
            run = subprocess.run([sys.executable, checker, '--html', html, '--datadir', datadir,
                                  '--json'], capture_output=True, text=True, cwd=work,
                                 timeout=timeout)
            res = number_result(run.returncode, run.stdout, run.stderr, False)
        except subprocess.TimeoutExpired:
            res = number_result(None, '', '', True)
        res['commit'] = commit[:8]
        res['data_commit'] = source[:8]
        return res
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ── 판단과 문장 ───────────────────────────────────────────────────────────

def verdict(p):
    num = p.get('number') or {}
    if num.get('kind') in ('warn', 'violation', 'error'):
        return '확인 필요'
    state = p['state']
    if not p['auto'] and state != '완료':
        return '사람이 읽어야 함'
    if state == '읽지 않음':
        # 원장의 baseline — 게이트 도입 때 「읽지 않고 범위에 넣은」 옛 글. 정책상 검토 대상이 아니라
        # 미해결로 쌓으면 90일 동안 같은 수십 편이 목록을 채운다. 꼬리에 따로 센다.
        return '검토 안 함(범위 편입)'
    if state in ('만료', '판정 불가', '기록 없음'):
        return '확인 필요'
    if state == '대기':
        return '검토 대기'
    return '검토 끝'


def resolved(p):
    return verdict(p) in ('검토 끝', '검토 안 함(범위 편입)')


def _day_label(path):
    d = post_day(path)
    name = LABEL.get(kinds.section_of(path), kinds.section_of(path))
    return f'{name} {d.month}/{d.day:02d}' if d else name


def _number_line(num):
    if not num:
        return ' · 숫자: 자동 검사 없음'
    kind = num.get('kind')
    if kind == 'skipped':
        return ' · 숫자: 검사 적용일 전 글'
    if kind == 'error':
        return f' · 숫자(발행 뒤 재검사): 판정 불가 — {num.get("reason", "")}'
    c = num.get('counts') or {}
    head = (f' · 숫자(발행 뒤 재검사): 표 칸 {c.get("table_cells", "?")} 대조 · '
            f'문장 판정 {c.get("prose_judged", "?")} · 미검증 {c.get("unverified", "?")} · '
            f'위반 {num.get("violations", 0)} · 경고 {num.get("warnings", 0)}')
    extra = [f'   - {x[:120]}' for x in (num.get('lines') or [])[:2]]
    if num.get('data_commit') and num.get('commit') and num['data_commit'] != num['commit']:
        # 같은 report_date 라도 발행 때 쓴 수집판이라는 보장은 없다 — 추정임을 밝힌다(codex 구현 검토 #3·재검토)
        extra.insert(0, f'   - 다시 그린 글이라 발행 때 쓴 데이터인지 확인 불가 — 같은 날짜 수집판으로 '
                        f'대조한 추정(데이터 {num["data_commit"]} · 검사기 {num.get("checker", "?")})')
    return '\n'.join([head] + extra)


def _review_line(p):
    state, n = p['state'], p.get('findings')
    if not p['auto'] and state != '완료':
        return ' · codex 검토: 자동 검토 대상 아님 — 사람이 읽어야 해요'
    if state == '대기' and p.get('draft'):
        who = 'Claude 확인·정정 대기' if kinds.section_of(p['path']) in kinds.DAILY \
            else '사람이 확인해야 해요'
        return f' · codex 검토: 초안 나옴 — {who}'
    return {
        '완료': f' · codex 검토: 끝 · 지적 {n if n is not None else "?"}건(검토 기록 기준)',
        '대기': ' · codex 검토: 대기',
        '만료': ' · codex 검토: 기한 지남 — 자동 검토가 더는 안 봐요',
        '판정 불가': ' · codex 검토: 판정 불가 — 사람이 확인해야 해요',
        '읽지 않음': ' · codex 검토: 범위에만 넣고 읽지 않음',
        '기록 없음': ' · codex 검토: 기록 없음',
    }.get(state, f' · codex 검토: {state}')


def _prepub_lines(p):
    """발행 전 기록 대상(US·KR 일간, 2026-11-09~)만 — 다른 글의 문장은 그대로 둔다(바꾸면 90일치가 「바뀜」으로 다시 온다)."""
    from review import prepub_view as V
    pv = p.get('prepub')
    if isinstance(pv, dict) and pv.get('error'):
        lines = [f' · [발행 전 기록] 읽지 못했어요 — {pv["error"][:100]}']   # 숫자 재검사 줄은 그대로 낸다(#11)
    else:
        try:
            lines = V.digest_lines(pv)
        except Exception as exc:  # noqa: BLE001
            lines = [f' · [발행 전 기록] 읽지 못했어요 — {type(exc).__name__}']
    num = _number_line(p.get('number'))
    if not p.get('number'):
        num = ' · [발행 뒤 재검사] 숫자: 자동 재검사 없음(US 일간만 해요)'
    else:
        num = num.replace(' · 숫자(발행 뒤 재검사):', ' · [발행 뒤 재검사] 숫자:', 1)
    return lines + [num]


def block(p, changed_body=False):
    mark = ' (글 내용이 바뀜)' if changed_body else ''
    head = f'■ {_day_label(p["path"])} — {verdict(p)}{mark}'
    if 'prepub' in p:
        return '\n'.join([head] + _prepub_lines(p) + [_review_line(p)])
    return '\n'.join([head, _number_line(p.get('number')), _review_line(p)])


def _totals(posts):
    nums = [p.get('number') or {} for p in posts]
    v = sum(n.get('violations', 0) for n in nums)
    w = sum(n.get('warnings', 0) for n in nums)
    f = sum(p.get('findings') or 0 for p in posts if p['state'] == '완료')
    bad = sum(1 for n in nums if n.get('kind') == 'error')
    todo = sum(1 for p in posts if p['state'] != '완료')
    # 못 본 것을 0건처럼 보이지 않게 함께 센다(codex 구현 검토 #5)
    return (f'최근 {WINDOW_DAYS}일: 글 {len(posts)}편 · 숫자 위반 {v}·경고 {w}(US 일간 자동 검사 범위 안) · '
            f'codex 지적 {f}건(사실 오류로 확인된 수 아님) · 숫자 판정 불가 {bad} · 검토 미완료 {todo}')


def _header(now):
    return f'[검증 알림] {now.month}월 {now.day}일({WEEKDAY[now.weekday()]}) {now:%H:%M}'


def render(posts, prev_lines, now, notes=(), extra_tail=()):
    """(보낼 글, 기록할 문장표). 바뀐 글만 자세히, 끝나지 않은 글은 꼬리에 이름만."""
    posts = sorted(posts, key=lambda p: (post_day(p['path']) or date.min, p['path']))
    head = [_header(now)] + [f'⚠ {n}' for n in notes]
    open_ = sorted((p for p in posts if not resolved(p)),       # 최신부터 — 이름이 10개에서 잘린다
                   key=lambda p: -(post_day(p['path']) or date.min).toordinal())
    tail = []
    if open_:
        names = [_day_label(p['path']) for p in open_]
        more = f' 외 {len(names) - 10}건' if len(names) > 10 else ''
        tail.append(f'아직 안 끝난 글 {len(open_)}건: ' + ', '.join(names[:10]) + more)
    unread = sum(1 for p in posts if p['state'] == '읽지 않음')
    if unread:
        tail.append(f'읽지 않고 범위에 넣은 글 {unread}편(90일 안, 게이트 도입 전 글, 검토 대상 아님)')
    tail += list(extra_tail)          # 발행 건별 알림의 상태(읽기만) — 미발행·관측 멈춤·미전송
    tail += [_totals([p for p in posts if in_window(p['path'], now.date())]), CAVEAT]

    # 문장과 공개판 blob 을 함께 비교한다 — 상태 문장이 같아도 내용이 바뀌면 알린다(codex 구현 검토 #2).
    # sha 없는 옛 기록(문자열)은 바뀐 것으로 본다.
    changed = []
    for p in posts:
        old = prev_lines.get(p['path'])
        old = old if isinstance(old, dict) else {}
        body = bool(old) and old.get('sha') != p.get('sha')
        if body or old.get('text') != block(p):
            changed.append((p, block(p, changed_body=body)))
    # 잘릴 때 최근 글이 먼저 살아남게 — 창 안 최신 → 창 밖 최신 순(밀린 것은 다음 알림에)
    today = now.date()
    changed.sort(key=lambda x: (not in_window(x[0]['path'], today),
                                -(post_day(x[0]['path']) or date.min).toordinal(), x[0]['path']))
    # 따라가지 않는 글의 전달 기록도 그대로 둔다 — 지우면 다음 날 「처음 보는 글」로 되살아난다
    lines = {k: v for k, v in prev_lines.items() if isinstance(v, dict)}
    if not changed:
        body = ['새로 나온 글이나 바뀐 상태가 없어요.']
    else:
        body = [f'새로 나온 글·바뀐 상태 {len(changed)}건']
        fixed = len('\n\n'.join(head + body + tail)) + 80      # 「외 n건」 자리
        used = 0
        for i, (p, text) in enumerate(changed):
            if fixed + used + len(text) + 2 > LIMIT:
                body.append(f'…외 {len(changed) - i}건은 다음 알림에 이어서 보낼게요.')
                break
            body.append(text)
            used += len(text) + 2
            lines[p['path']] = {'sha': p.get('sha'), 'text': block(p)}
    text = '\n\n'.join(['\n'.join(head)] + body + tail)
    if len(text) > LIMIT:                                      # 꼬리 자체가 넘치는 극단
        text = text[:LIMIT - 1] + '…'
    return text, lines


# ── 언제 보내나, 기록 파일 ─────────────────────────────────────────────────

def due(now, state):
    return now.hour >= SEND_HOUR and state.get('last_sent_day') != now.date().isoformat()


def load_state(path):
    try:
        with open(path, encoding='utf-8') as fh:
            obj = json.load(fh)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        raise StateError(f'{type(exc).__name__}: {exc}') from exc
    if not isinstance(obj, dict):
        raise StateError('기록 파일이 사전이 아니다')
    return obj


def save_state(path, state):
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix='.digest-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            json.dump(state, fh, ensure_ascii=False, indent=1, sort_keys=True)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def digest_note(path, now):
    """세션 시작 한 줄 — 알림이 조용히 멈춘 것을 사람이 보게. 할 말이 없으면 ''."""
    try:
        st = load_state(path)
    except StateError:
        return '[검증 알림] 기록 파일이 손상됐어요 — 다음 발송 때 새로 시작해요'
    if st.get('last_error'):
        return f'[검증 알림] 마지막 전송 실패 — {st["last_error"]}'
    sent = st.get('last_sent')
    if not sent:
        return '[검증 알림] 아직 한 번도 안 보냈어요'
    try:
        hours = int((now - datetime.fromisoformat(sent)).total_seconds() // 3600)
    except (TypeError, ValueError):
        return '[검증 알림] 마지막 발송 시각을 못 읽었어요'
    return f'[검증 알림] 마지막 발송 {hours}시간 전' if hours > STALE_HOURS else ''


# ── 텔레그램 ─────────────────────────────────────────────────────────────

def _keychain(account, run):
    out = run(['security', 'find-generic-password', '-s', SERVICE, '-a', account, '-w'],
              capture_output=True, text=True, timeout=20)
    return out.stdout.strip() if out.returncode == 0 else ''


def _curl(token, method, data, run, secret=()):
    """토큰과 `secret` 항목(대화 번호)은 curl 설정 stdin 으로 — 프로세스 목록에 안 남긴다."""
    args = ['curl', '-sS', '--max-time', '30', '-K', '-']
    conf = [f'url = "https://api.telegram.org/bot{token}/{method}"']
    for k, v in data:
        if k in secret:
            conf.append(f'data-urlencode = "{k}={v}"')
        else:
            args += ['--data-urlencode', f'{k}={v}']
    out = run(args, input='\n'.join(conf) + '\n', capture_output=True, text=True, timeout=60)
    if out.returncode:
        raise SendError(f'curl 실패(코드 {out.returncode})')
    try:
        obj = json.loads(out.stdout)
    except ValueError:
        raise SendError('텔레그램 응답을 읽지 못했어요') from None
    if not obj.get('ok'):
        why = str(obj.get('description') or obj.get('error_code') or '이유 없음').replace(token, '***')
        raise SendError(f'텔레그램이 거절했어요: {why[:120]}')
    return obj


def send_telegram(text, run=subprocess.run):
    token = _keychain('token', run)
    if not token:
        raise SendError('열쇠고리에서 텔레그램 토큰을 못 읽었어요')
    chat = _keychain('chat', run)
    if not chat:
        raise SendError('열쇠고리에서 대화 번호를 못 읽었어요 — 봇에게 메시지를 보낸 뒤 --setup-chat')
    if not re.fullmatch(r'-?\d+', chat):
        raise SendError('열쇠고리의 대화 번호 형식이 이상해요')
    _curl(token, 'sendMessage', [('chat_id', chat), ('text', text)], run, secret=('chat_id',))


def setup_chat(run=subprocess.run):
    """봇에게 온 개인 대화가 정확히 하나면 그 번호를 열쇠고리에 둔다. 번호는 출력하지 않는다."""
    token = _keychain('token', run)
    if not token:
        raise SendError('열쇠고리에서 텔레그램 토큰을 못 읽었어요')
    obj = _curl(token, 'getUpdates', [], run)
    chats = {((u.get('message') or {}).get('chat') or {}).get('id')
             for u in obj.get('result') or []
             if ((u.get('message') or {}).get('chat') or {}).get('type') == 'private'}
    chats.discard(None)
    if len(chats) != 1:
        raise SendError(f'봇에게 온 개인 대화가 {len(chats)}개예요 — 하나여야 해요'
                        ' (봇 대화창에서 메시지를 한 번 보내 주세요)')
    out = run(['security', 'add-generic-password', '-U', '-s', SERVICE, '-a', 'chat', '-w',
               str(chats.pop())], capture_output=True, text=True, timeout=20)
    if out.returncode:
        raise SendError('대화 번호를 열쇠고리에 못 넣었어요')
