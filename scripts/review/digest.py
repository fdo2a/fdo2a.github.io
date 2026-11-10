"""매일 검증 알림 — 발행본마다 「무엇이 검증됐고 무엇이 안 됐나」를 하루 한 통으로 (2026-11-08).

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
- 2.5단계(2026-11-10): 맥은 텔레그램에 직접 보내지 않는다. 요약을 Cloudflare Worker 에 **제출**하고
  (`POST /digest`), Worker 가 보낸다. 맥에는 텔레그램 토큰을 읽는 코드가 없다 — 열쇠고리에서 읽는 것은
  제출 키(`fdo2a-alerts`/`digest_key`)와 Worker 주소(`worker_url`)뿐이다. 키·본문은 curl 설정 stdin 으로
  넘겨 프로세스 목록에 안 남긴다. urllib 이 아니라 curl 인 이유: 프레임워크 파이썬 3.13 에 인증서 묶음이 없다.
- 제출본을 먼저 고정한다(`pending`) — 응답이 없으면 그 본문 그대로 다시 낸다. 「무엇을 이미 알렸나」(`lines`)는
  Worker 가 그 요약을 `sent` 로 돌려준 뒤에만 전진한다. 접수만 된 요약의 변화는 다음 요약이 다시 담는다.
- 출처가 불확실한 문자열(예외 문장·검사기 원문·초안 유무)은 요약에 넣지 않고 고정된 종류로만 적는다.
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
SERVICE = 'fdo2a-alerts'      # 제출 키(digest_key)·Worker 주소(worker_url) — 텔레그램 토큰은 맥에 없다
MAX_BODY = 16000             # 요청 16 KB(16,384 B) 안 — 여유 384 B
STATUS_DAYS = 14             # Worker /status 가 돌려주는 기간
UNCONFIRMED_HOURS = 24
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


WHY = {'timeout': '시간 초과', 'exit': '알 수 없는 종료 코드', 'input': '검사기가 입력을 읽지 못했어요',
       'parse': '결과를 읽지 못했어요', 'contract': '결과 형식이 약속과 달라요',
       'commit': '발행 커밋을 못 찾았어요', 'blob': '글 내용을 못 꺼냈어요',
       'data': '대조할 데이터를 못 찾았어요'}
_LINE_KIND = re.compile(r'^(경고|위반)\(([가-힣A-Za-z]{1,8})\)')


def _error(reason, why='parse'):
    """`reason` 은 맥 안에서만 본다(stderr·경로가 섞일 수 있다). 요약에는 `why`(고정 문구)만 나간다."""
    return {'kind': 'error', 'reason': reason[:160], 'why': WHY[why]}


def line_kinds(violations, warnings):
    """검사기 원문 줄 → {종류: 개수}. 원문은 요약에 싣지 않는다(2.5단계 — 종류와 개수만)."""
    out = {}
    for default, rows in (('위반', violations), ('경고', warnings)):
        for x in rows:
            m = _LINE_KIND.match(x)
            k = f'{m.group(1)}({m.group(2)})' if m else default
            out[k] = out.get(k, 0) + 1
    return out


def number_result(code, stdout, stderr, timed_out):
    """`check_numbers.py --json` 의 결과 → 알림용 사전. 모르는 것은 전부 판정 불가."""
    if timed_out:
        return _error('시간 초과', 'timeout')
    if code not in (0, 1, 2):
        return _error(f'알 수 없는 종료 코드 {code}', 'exit')
    if code == 2:
        lines = [x.strip() for x in (stderr or '').splitlines() if x.strip()]
        why = lines[-1] if lines else '입력을 읽지 못했어요'
        return _error(why[len('FATAL: '):] if why.startswith('FATAL: ') else why, 'input')
    try:
        last = [x for x in (stdout or '').splitlines() if x.strip()][-1]
        obj = json.loads(last)
        if not isinstance(obj, dict):
            raise ValueError
    except (IndexError, ValueError):
        return _error('결과를 읽지 못했어요')
    if obj.get('skipped') is True:
        return {'kind': 'skipped'} if code == 0 else _error('건너뛴 결과에 실패 코드', 'contract')
    # 계약이 깨진 응답을 정상으로 읽지 않는다(codex 구현 검토 #6, 재검토 #4)
    counts = obj.get('counts')
    if obj.get('skipped') is not False or not isinstance(obj.get('warnings'), list) \
            or not isinstance(obj.get('violations'), list) or not isinstance(counts, dict) \
            or not all(isinstance(x, str) for x in obj['warnings'] + obj['violations']) \
            or not all(type(counts.get(k)) is int for k in COUNT_KEYS):
        return _error('결과 형식이 약속과 달라요', 'contract')
    warnings, violations = obj['warnings'], obj['violations']
    if (code == 1) != bool(violations):
        return _error('종료 코드와 결과가 어긋나요', 'contract')
    kind = 'violation' if violations else 'warn' if warnings else 'ok'
    return {'kind': kind, 'warnings': len(warnings), 'violations': len(violations),
            'counts': obj.get('counts') or {}, 'lines': (violations + warnings)[:3],
            'kinds': line_kinds(violations, warnings)}


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
        return _error(f'발행 커밋을 찾다 실패했어요 ({type(exc).__name__})', 'commit')
    if not commit:
        return _error('발행 커밋을 못 찾았어요', 'commit')
    work = tempfile.mkdtemp(prefix='verify-digest-')
    try:
        post = _git_bytes(root, 'cat-file', 'blob', sha)
        if post.returncode:
            return _error('글 내용을 못 꺼냈어요', 'blob')
        html = os.path.join(work, 'posts', os.path.basename(path))
        os.makedirs(os.path.dirname(html))
        with open(html, 'wb') as fh:
            fh.write(post.stdout)
        datadir = os.path.join(work, 'data')
        source, why = _data_commit(root, commit, path)
        if not source:
            return _error(why, 'data')
        for rel in DATA_FILES:
            got = _git_bytes(root, 'show', f'{source}:{rel}')
            if got.returncode:
                if rel == REQUIRED_DATA:
                    return _error(f'{rel} 이 발행 커밋에 없어요', 'data')
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
        return f' · 숫자(발행 뒤 재검사): 판정 불가 — {num.get("why") or "사유는 맥에서 확인"}'
    c = num.get('counts') or {}
    head = (f' · 숫자(발행 뒤 재검사): 표 칸 {c.get("table_cells", "?")} 대조 · '
            f'문장 판정 {c.get("prose_judged", "?")} · 미검증 {c.get("unverified", "?")} · '
            f'위반 {num.get("violations", 0)} · 경고 {num.get("warnings", 0)}')
    # 검사기 원문 줄은 싣지 않는다 — 종류와 개수만(설계 v7 #6). 원문은 맥에서 check_numbers.py 로 본다.
    kinds_ = num.get('kinds') if isinstance(num.get('kinds'), dict) else {}
    extra = ['   - 종류: ' + ' · '.join(f'{k} {kinds_[k]}' for k in sorted(kinds_))] if kinds_ else []
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
        return ' · codex 검토: 검토 진행 중'        # 초안 파일 유무·이름은 적지 않는다(설계 v4·v7 #6)
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
        lines = [' · [발행 전 기록] 읽지 못했어요']       # 예외 문장은 싣지 않는다. 숫자 재검사 줄은 그대로(#11)
    else:
        try:
            lines = V.digest_lines(pv)
        except Exception:  # noqa: BLE001
            lines = [' · [발행 전 기록] 읽지 못했어요']
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


# ── 기밀: 구조로 먼저, 정규식은 보조 검사(설계 v6 #4·v7 #6) ─────────────────────

_NAMES = '|'.join(sorted(re.escape(v) for v in LABEL.values()))
_NAME_LIST = rf'(?:{_NAMES}) \d{{1,2}}/\d{{2}}(?:, (?:{_NAMES}) \d{{1,2}}/\d{{2}})*'
NOTE_FIRST = f'첫 알림이라 최근 {WINDOW_DAYS}일 글과 끝나지 않은 옛 글을 담았어요'
NOTE_STALE = '최신 판을 못 받았어요 — 마지막으로 받아 둔 판 기준이에요'
NOTE_CORRUPT = '기록 파일이 손상돼 새로 시작했어요 — 지난 상태와 비교하지 못했어요'
# 머리 안내는 이 목록의 문구만 나간다. 그 밖은 「기타 안내 n건」 — 내용은 맥에서 본다.
NOTE_PATTERNS = tuple(re.compile(x) for x in (
    re.escape(NOTE_FIRST), re.escape(NOTE_STALE), re.escape(NOTE_CORRUPT),
    r'요약 제출 키 오류가 있었어요 — Worker 가 제출을 거부했어요\(키체인 digest_key 와 Worker Secret 확인\)',
    r'지난 알림 실패 — [가-힣 ]{2,12}',
    rf'공개판에서 사라진 글 \d+건: {_NAME_LIST}',
    rf'\d+일이 지나 추적을 멈춘 글 \d+건\(안 끝났거나 못 보낸 글\): {_NAME_LIST}',
    rf'\d+일보다 오래된 날짜의 글이 새로 올라왔어요\(검사 안 함\) \d+건: {_NAME_LIST}',
    r'KR 주간 \d{4}-W\d{2} 지수 누락: [A-Z0-9]+ \d{4}-\d{2}-\d{2}(?:, [A-Z0-9]+ \d{4}-\d{2}-\d{2})* — '
    r'새벽 재수집으로 자동 보완하지 않아요\. 원자료를 확인해 글을 정정한 뒤 수동 승격\(versions\.py promote\)해야 '
    r'주간이 나가요',
))


def safe_notes(notes):
    """정해진 문구만 통과시킨다. 나머지는 개수만 — 예외 문장·경로가 안내 줄로 새지 않게."""
    out, other = [], 0
    for n in notes:
        if isinstance(n, str) and any(p.fullmatch(n) for p in NOTE_PATTERNS):
            out.append(n)
        else:
            other += 1
    if other:
        out.append(f'기타 안내 {other}건 — 맥에서 확인')
    return out


REDACTED = '(내부 정보 — 생략)'
# `sk-` 는 영숫자 바로 뒤에 오면 보지 않는다 — 'risk-off' 같은 낱말이 걸리면 그 글이 매일 되풀이된다.
_SECRET = re.compile(
    r'/Users/|~/Library|/private/|\d{6,}:[A-Za-z0-9_-]{30,}|ghp_|(?<![A-Za-z0-9])sk-[A-Za-z0-9]'
    r'|reviews/pending|\d{4}-\d{2}-\d{2}-[a-z_]+-[0-9a-f]{7}\.md|undated-[a-z_]+-[0-9a-f]{7}\.md')


def scrub(text):
    """(정제한 글, 바꾼 줄 수). 보조 검사 — 걸린 줄을 통째로 바꾼다."""
    out, n = [], 0
    for line in text.split('\n'):
        if _SECRET.search(line):
            out.append(REDACTED)
            n += 1
        else:
            out.append(line)
    return '\n'.join(out), n


def render(posts, prev_lines, now, notes=(), extra_tail=(), limit=LIMIT):
    """(보낼 글, 기록할 문장표). 바뀐 글만 자세히, 끝나지 않은 글은 꼬리에 이름만.

    `limit` 을 낮추면 글을 더 많이 다음 알림으로 미룬다(요청 16 KB 를 넘을 때 — 줄 중간에서 자르지 않는다).
    보조 검사에 걸린 글은 그 줄을 바꿔 싣되 문장표에 적지 않는다 — 다음 요약에서 다시 확인하게.
    """
    posts = sorted(posts, key=lambda p: (post_day(p['path']) or date.min, p['path']))
    hidden = 0
    head = [_header(now)]
    for n in safe_notes(notes):
        line, k = scrub(f'⚠ {n}')
        head.append(line)
        hidden += k
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
    for x in extra_tail:              # 어제 요약 접수 결과·발행 건별 알림 상태·전송기 상태(읽기만)
        line, k = scrub(str(x))
        tail.append(line)
        hidden += k
    closing = [_totals([p for p in posts if in_window(p['path'], now.date())]), CAVEAT]

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
        fixed = len('\n\n'.join(head + body + tail + closing)) + 120      # 「외 n건」·「n줄 생략」 자리
        used = 0
        for i, (p, text) in enumerate(changed):
            text, k = scrub(text)
            if fixed + used + len(text) + 2 > limit:
                body.append(f'…외 {len(changed) - i}건은 다음 알림에 이어서 보낼게요.')
                break
            body.append(text)
            used += len(text) + 2
            hidden += k
            if not k:
                lines[p['path']] = {'sha': p.get('sha'), 'text': block(p)}
    if hidden:
        tail.append(f'{hidden}줄 생략 — 맥에서 확인')
    text = '\n\n'.join(['\n'.join(head)] + body + tail + closing)
    if len(text) > limit:                                      # 꼬리 자체가 넘치는 극단
        text = text[:limit - 1] + '…'
    return text, lines


# ── 언제 보내나, 기록 파일 ─────────────────────────────────────────────────

def due(now, state):
    """오늘 치를 아직 접수시키지 못했나 — 판정은 「보냈다」가 아니라 「접수됐다」(설계 v7 #3)."""
    return now.hour >= SEND_HOUR and state.get('last_submitted_day') != now.date().isoformat()


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


# ── 세션 시작 한 줄 ────────────────────────────────────────────────────────

ERRORS = ('접수 오류', '연결 오류', '제출 키 없음', '제출 키 오류', '전송 오류', '전송 보류', '충돌', '요약 만들기 오류',
          '크기 초과', '잠금 오류', '확인 불가', '기타 오류')


def error_kind(value):
    """실패 사유는 종류만 남긴다 — 예외 문장에는 맥 경로가 섞일 수 있다(설계 v4·v7 #6)."""
    return value if value in ERRORS else '기타 오류'


def parse_iso(value):
    """시간대가 있는 ISO 시각. Worker(JS)의 `…Z`·밀리초도 읽는다 — 3.9 의 fromisoformat 은 `Z` 를 못 읽는다."""
    if not isinstance(value, str):
        raise ValueError('문자열이 아니다')
    t = value.strip()
    if t[-1:] in ('Z', 'z'):
        t = t[:-1] + '+00:00'
    m = re.fullmatch(r'(.*T\d{2}:\d{2}:\d{2})\.(\d+)(.*)', t)
    if m:
        t = f'{m.group(1)}.{(m.group(2) + "000000")[:6]}{m.group(3)}'
    d = datetime.fromisoformat(t)
    if d.tzinfo is None:
        raise ValueError('시간대가 없다')
    return d


def _hours(now, iso):
    return int((now - parse_iso(iso)).total_seconds() // 3600)


def digest_note(path, now):
    """세션 시작 한 줄 — 알림이 조용히 멈춘 것을 사람이 보게. 할 말이 없으면 ''. 네트워크·열쇠고리를 안 쓴다."""
    try:
        st = load_state(path)
    except StateError:
        return '[검증 알림] 기록 파일이 손상됐어요 — 다음 제출 때 새로 시작해요'
    if st.get('auth_error'):
        return AUTH_HOOK
    if st.get('last_error'):
        return f'[검증 알림] 마지막 시도 실패 — {error_kind(st["last_error"])}'
    late = 0
    for u in unconfirmed(st):
        try:
            late += _hours(now, u.get('accepted_at')) >= UNCONFIRMED_HOURS
        except (TypeError, ValueError):
            late += 1
    if late:
        return f'[검증 알림] 접수된 요약 {late}건이 {UNCONFIRMED_HOURS}시간 넘게 전송 확인이 안 돼요'
    sent = st.get('last_sent')
    if not sent:
        return '' if unconfirmed(st) else '[검증 알림] 아직 한 번도 안 보냈어요'
    try:
        hours = _hours(now, sent)
    except (TypeError, ValueError):
        return '[검증 알림] 마지막 전송 시각을 못 읽었어요'
    return f'[검증 알림] 마지막 전송 {hours}시간 전' if hours > STALE_HOURS else ''


# ── Worker 에 제출(2.5단계) — 맥은 텔레그램 토큰을 읽지 않는다 ──────────────────────

STATES = ('accepted', 'queued', 'sending', 'sent', 'failed_permanent', 'held')
RESULTS = ('accepted', 'dup', 'conflict', 'rejected', 'server', 'noresp')
_KEY = re.compile(r'[A-Za-z0-9._~+/=-]{32,128}')
_URL = re.compile(r'https://[A-Za-z0-9.-]+(?::\d{1,5})?')
_ID = re.compile(r'(\d{4}-\d{2}-\d{2}):morning-digest:v([1-9])')


class ConfigError(Exception):
    """열쇠고리에 제출 키·Worker 주소가 없거나 모양이 이상하다."""


class TransportError(Exception):
    """응답을 못 받았거나 약속과 다른 응답 — 「없음」으로 읽지 않는다."""


class AuthError(TransportError):
    """Worker 가 401 — 제출 키가 Worker Secret 과 다르다(또는 Worker 에 Secret 이 없다)."""


class SizeError(Exception):
    pass


def _keychain(account, run):
    out = run(['security', 'find-generic-password', '-s', SERVICE, '-a', account, '-w'],
              capture_output=True, text=True, timeout=20)
    return out.stdout.strip() if out.returncode == 0 else ''


def _endpoint(run):
    """(Worker 주소, 제출 키). 값은 curl 설정에 끼워 넣으므로 모양부터 본다(따옴표·줄바꿈 금지, https 만)."""
    try:
        url = _keychain('worker_url', run).rstrip('/')
        key = _keychain('digest_key', run)
    except (OSError, subprocess.SubprocessError):
        raise ConfigError('열쇠고리를 못 읽었어요') from None
    if not _URL.fullmatch(url):
        raise ConfigError('열쇠고리의 Worker 주소가 없거나 https 주소가 아니에요')
    if not _KEY.fullmatch(key):
        raise ConfigError('열쇠고리의 제출 키가 없거나 모양이 이상해요')
    return url, key


def _quoted(value):
    return value.replace('\\', '\\\\').replace('"', '\\"')


def _curl(url, key, run, body=None, max_time=30):
    """(HTTP 코드 | None, 응답 본문). 키·본문은 설정 stdin 으로만 — 인자·주소·로그에 안 남긴다.
    curl 의 출력·오류 문장은 어디에도 옮겨 적지 않는다. `key=None` 은 공개 주소(/health) — 인증 헤더를 안 붙인다."""
    args = ['curl', '-q', '-sS', '--max-time', str(max_time), '--proto', '=https', '-w', '\n%{http_code}',
            '-K', '-']
    conf = [f'url = "{_quoted(url)}"'] + ([f'header = "Authorization: Bearer {key}"'] if key else [])
    if body is not None:
        conf += ['request = "POST"', 'header = "Content-Type: application/json"',
                 f'data-binary = "{_quoted(body)}"']
    try:
        out = run(args, input=('\n'.join(conf) + '\n').encode('utf-8'), capture_output=True,
                  timeout=max_time * 2)
    except (OSError, subprocess.SubprocessError):
        return None, ''
    if out.returncode:
        return None, ''
    raw = out.stdout if isinstance(out.stdout, str) else (out.stdout or b'').decode('utf-8', 'replace')
    text, _, code = raw.rpartition('\n')
    try:
        code = int(code)
    except ValueError:
        return None, ''
    return (code if 100 <= code <= 599 else None), text


def classify(code, text, sid):
    """제출 응답 → `RESULTS` 하나. 약속에 없는 응답은 「접수」도 「거절」도 아니다 — 확인 불가 쪽(server)."""
    if code is None:
        return 'noresp'
    if code in (200, 202):
        try:
            obj = json.loads(text)
        except ValueError:
            return 'server'                      # 중간 장비의 200 HTML 등
        if not isinstance(obj, dict) or obj.get('id') != sid or obj.get('state') not in STATES:
            return 'server'
        return 'accepted' if code == 202 else 'dup'
    if code == 409:
        return 'conflict'
    if code in (400, 401):
        return 'rejected'
    return 'server'


def request_body(p):
    """제출 본문 — 고정된 `pending` 에서 매번 같은 바이트가 나온다(같은 id·같은 해시)."""
    return json.dumps({'format': 'digest-submit/1', 'id': p['id'], 'date': p['date'],
                       'kind': 'morning-digest', 'text': p['text']},
                      ensure_ascii=False, separators=(',', ':'), sort_keys=True)


def post_digest(body, sid, run=subprocess.run):
    url, key = _endpoint(run)
    code, text = _curl(url + '/digest', key, run, body=body)
    return 'unauthorized' if code == 401 else classify(code, text, sid)     # 401 은 시도 기록에는 rejected 로


def fetch_status(sid=None, run=subprocess.run):
    """{'events': {id: 사건}, 'health': {...}}. 못 읽으면 TransportError."""
    url, key = _endpoint(run)
    if sid is not None and not _ID.fullmatch(sid):
        raise TransportError('id')
    code, text = _curl(url + '/status' + (f'?id={sid}' if sid else ''), key, run)
    if code == 401:
        raise AuthError('HTTP 401')
    if code != 200:
        raise TransportError(f'HTTP {code}' if code else '응답 없음')
    try:
        obj = json.loads(text)
    except ValueError:
        raise TransportError('JSON') from None
    if not isinstance(obj, dict) or obj.get('format') != 'digest-status/1' \
            or not isinstance(obj.get('events'), list):
        raise TransportError('형식')
    events = {}
    for e in obj['events']:
        if not (isinstance(e, dict) and isinstance(e.get('id'), str) and e.get('state') in STATES):
            raise TransportError('사건')
        events[e['id']] = e
    return {'events': events, 'health': obj['health'] if isinstance(obj.get('health'), dict) else None}


# ── 제출 상태(계약 §4): pending → unconfirmed → 기준(base) 적용 ───────────────────────

def migrate(state):
    """옛 상태(직접 전송 시절)를 새 이름으로. `last_sent`(옛 전송 시각)·`lines` 등은 그대로 기준으로 쓴다."""
    if 'last_sent_day' in state:
        old = state.pop('last_sent_day')
        state.setdefault('last_submitted_day', old)
    if state.get('last_error') and state['last_error'] not in ERRORS:
        state['last_error'] = '기타 오류'
    if 'pending' in state and pending_of(state) is None:
        state.pop('pending')
    return state


def pending_of(state):
    p = state.get('pending')
    ok = isinstance(p, dict) and all(isinstance(p.get(k), str) for k in ('id', 'date', 'text')) \
        and isinstance(p.get('base'), dict) and isinstance(p.get('tries'), list) \
        and type(p.get('v')) is int and _ID.fullmatch(p['id'])
    return p if ok else None


def unconfirmed(state):
    return [u for u in state.get('unconfirmed') or []
            if isinstance(u, dict) and isinstance(u.get('id'), str) and isinstance(u.get('date'), str)
            and type(u.get('v')) is int and isinstance(u.get('base'), dict)]


def _applied(state):
    a = state.get('applied')
    return (a[0], a[1]) if isinstance(a, list) and len(a) == 2 else ('', 0)


def _mark_day(state, p):
    state['last_submitted_day'] = max(state.get('last_submitted_day') or '', p['date'])
    last = state.get('submitted') if isinstance(state.get('submitted'), dict) else {}
    if (p['date'], p['v']) > (last.get('date') or '', last.get('v') or 0):
        state['submitted'] = {'date': p['date'], 'v': p['v']}


def mark_accepted(state, now):
    """접수 확인 — 본문은 버리고 기준만 들고 전송 확인을 기다린다. `lines` 는 아직 전진하지 않는다."""
    p = state.pop('pending')
    state['unconfirmed'] = unconfirmed(state) + [
        {'id': p['id'], 'date': p['date'], 'v': p['v'], 'base': p['base'], 'accepted_at': now.isoformat(),
         'hash': text_hash(p['text'])}]
    _mark_day(state, p)
    state.update(last_submitted=now.isoformat(), last_error=None)


def attempt(state, now, save, post):
    """고정해 둔 본문을 그대로 낸다. `post(body, id)` → `RESULTS` 하나.

    시도는 **보내기 전에** `noresp` 로 적어 둔다 — 보내는 중에 죽어도 「요청이 나갔을 수 있다」가 남는다
    (빈 시도 목록을 「전부 거절」로 읽지 않게, 설계 v9 #1).
    """
    p = state['pending']
    p['tries'].append({'at': now.isoformat(), 'result': 'noresp'})
    state['last_attempt'] = now.isoformat()
    save(state)
    try:
        result = post(request_body(p), p['id'])
    except ConfigError:                 # 열쇠고리에서 막혔다 — 요청이 나가지 않았으니 시도로 세지 않는다
        p['tries'].pop()
        state['last_error'] = '제출 키 없음'
        save(state)
        raise
    if result == 'unauthorized':
        result = 'rejected'
        auth_failed(state, now)
        unauthorized = True
    else:
        unauthorized = False
        if result in ('accepted', 'dup', 'conflict', 'rejected'):       # Worker 가 키를 받아들였다
            auth_ok(state)
    if result not in RESULTS:
        result = 'server'
    p['tries'][-1]['result'] = result
    if result in ('accepted', 'dup'):
        mark_accepted(state, now)
    elif not unauthorized:
        state['last_error'] = {'rejected': '접수 오류', 'conflict': '충돌'}.get(result, '연결 오류')
    save(state)
    return result


def text_hash(text):
    """Worker `/status` 의 `hash` 와 대조하는 값 — 접수한 본문(text)의 sha256(계약 §3)."""
    import hashlib
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _event_hash(ev):
    h = ev.get('hash') if isinstance(ev, dict) else None
    return h.lower() if isinstance(h, str) and re.fullmatch(r'[0-9a-fA-F]{64}', h) else None


def _carry(state, day, kind):
    state['carry'] = [c for c in state.get('carry') or [] if isinstance(c, dict)] + [{'date': day, 'kind': kind}]


def confirm(state, events, now):
    """`/status` 의 사건으로 전송을 확인한다. 기준은 **`sent` 이고 사건의 hash 가 맥이 고정한 본문의 해시와 같을 때만**,
    (날짜, 버전) 순으로, 더 클 때만 적용한다(늦게 확인된 옛 요약이 새 기준을 덮지 않게 — 설계 v8 #2·v9 #2).

    같은 id 에 다른 본문이 접수돼 있으면(hash 다름) 409 와 같게 다룬다 — 「접수됨 — 다른 본문」, 기준 미적용
    (codex 구현 1회 #4: id 가 있다는 사실만으로 자기 본문이라 믿지 않는다). hash 가 없으면 대조할 수 없으니
    적용하지 않고 「전송 확인 불가」. 바뀌었으면 True.
    """
    left, changed = [], False
    for u in sorted(unconfirmed(state), key=lambda u: (u['date'], u['v'])):
        ev = events.get(u['id'])
        st = ev.get('state') if isinstance(ev, dict) else None
        theirs, mine = _event_hash(ev), u.get('hash')
        if st is not None and theirs and mine and theirs != mine:
            _carry(state, u['date'], 'conflict')
        elif st == 'sent' and not (theirs and mine):
            _carry(state, u['date'], 'unverified')
            state['last_error'] = '확인 불가'
        elif st == 'sent':
            if (u['date'], u['v']) > _applied(state):
                state.update({k: u['base'][k] for k in BASE_KEYS if k in u['base']})
                state['applied'] = [u['date'], u['v']]
                state.pop('seen', None)
            sent_at = ev.get('sent_at')
            try:
                when = parse_iso(sent_at)
            except ValueError:
                sent_at, when = now.isoformat(), now          # 계약 위반 — 확인한 시각으로 대신한다
            try:
                newer = when >= parse_iso(state.get('last_sent'))
            except ValueError:
                newer = True
            if newer:
                state['last_sent'] = sent_at
            state['last_error'] = None
        elif st in ('failed_permanent', 'held'):
            state['last_error'] = '전송 오류' if st == 'failed_permanent' else '전송 보류'
        elif st is None and _too_old(u, now):
            state['last_error'] = '확인 불가'                  # Worker 가 14일 지난 사건은 안 돌려준다
        else:
            left.append(u)
            continue
        changed = True
    if changed or len(left) != len(state.get('unconfirmed') or []):
        state['unconfirmed'] = left
        changed = True
    return changed


BASE_KEYS = ('lines', 'open', 'tracked', 'all', 'numbers')


def _too_old(u, now):
    try:
        return (now.date() - date.fromisoformat(u['date'])).days > STATUS_DAYS
    except ValueError:
        return True


def settle(state, now, lookup, expired, archive=None):
    """pending 을 `/status?id=` 로 정리한다. `lookup(id)` → 사건 | None(없음), 못 읽으면 TransportError.

    - 사건이 있고 hash 가 내 본문과 같다: 접수로 기록(전송 확인을 기다린다).
    - 사건이 있고 hash 가 다르다(또는 hash 는 없는데 409 를 받은 적이 있다): 「접수됨 — 다른 본문」, 기준 미적용(v11).
    - 사건은 있는데 hash 가 없어 대조할 수 없다: 내 본문이라 믿지 않는다 — 기한 전이면 그대로, 지났으면 「확인 불가」.
    - 없거나 못 읽었고 기한 전: 그대로 둔다(다음 tick 에 같은 본문으로 다시).
    - 기한이 지났다: 모든 시도가 400·401 이면 「접수 실패」, 그 밖(5xx·무응답·409·조회 실패)은 「확인 불가」.
    접수되지 못하고 내려놓는 제출본은 지우지 않고 `archive(pending, 결과)` 로 넘긴다(codex 구현 1회 #2 — 내용 유실 없음).
    돌려주는 값: 'accepted' | 'conflict' | 'failed' | 'unknown' | None(그대로).
    """
    p = state['pending']
    results = {t.get('result') for t in p['tries'] if isinstance(t, dict)}
    try:
        ev = lookup(p['id'])
    except (TransportError, ConfigError):
        ev = None
    theirs = _event_hash(ev)
    if ev is not None and theirs == text_hash(p['text']):
        mark_accepted(state, now)
        return 'accepted'
    if ev is not None and (theirs or 'conflict' in results):
        _mark_day(state, p)
        state['last_error'] = None
        outcome = 'conflict'
    elif not expired:
        return None
    elif ev is not None:
        outcome = 'unknown'
    else:
        outcome = 'failed' if results <= {'rejected'} else 'unknown'
    if archive:
        archive(p, outcome)
    state.pop('pending')
    _carry(state, p['date'], outcome)
    return outcome


ARCHIVE_DAYS = 30


def archive_path(path):
    return (path[:-5] if path.endswith('.json') else path) + '.expired.jsonl'


def archive_expired(path, pending, outcome, now):
    """접수되지 못한 제출본(본문·기준·시도)을 기록 파일 옆에 남긴다 — 0600, 30일. 다시 제출하지는 않는다
    (Worker 가 받는 날짜가 지났다). 기준은 적용되지 않았으니 다음 요약이 같은 변화를 다시 담는다."""
    append_archive(path, [{'archived_at': now.isoformat(), 'outcome': outcome, 'pending': pending}], now)


def append_archive(path, entries, now):
    """보관 줄을 더한다. 기존 파일은 **없을 때만** 새로 만든다 — 읽지 못하면(권한·입출력 오류) 덮어쓰지 않고
    OSError 를 그대로 올린다(codex 구현 2회 #8). 해석 못 하는 줄도 지우지 않고 남긴다(30일 정리는 읽히는 줄만)."""
    dest = archive_path(path)
    keep = []
    try:
        with open(dest, encoding='utf-8') as fh:
            for line in fh:
                line = line.rstrip('\n')
                if not line:
                    continue
                try:
                    if (now - parse_iso(json.loads(line).get('archived_at'))).days >= ARCHIVE_DAYS:
                        continue
                except (ValueError, AttributeError, TypeError):
                    pass
                keep.append(line)
    except FileNotFoundError:
        pass
    except UnicodeDecodeError as exc:   # 깨진 바이트도 「읽지 못함」 — 덮어쓰지 않고 보관 실패로 올린다(codex 구현 3회 #1)
        raise OSError(f'보관 파일을 UTF-8 로 읽지 못함: {exc}') from exc
    keep += [json.dumps(e, ensure_ascii=False, sort_keys=True) for e in entries]
    d = os.path.dirname(dest)
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix='.digest-expired-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            fh.write('\n'.join(keep) + '\n')
        os.chmod(tmp, 0o600)
        os.replace(tmp, dest)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


CARRY = {'failed': '요약 접수 실패', 'unknown': '요약 접수 여부 확인 불가',
         'conflict': '요약 접수됨 — 다른 본문이 먼저 접수돼 있었어요',
         'unverified': '요약 전송 확인 불가 — Worker 가 본문 대조 값을 주지 않았어요'}
AUTH_NOTE = '요약 제출 키 오류가 있었어요 — Worker 가 제출을 거부했어요(키체인 digest_key 와 Worker Secret 확인)'
AUTH_HOOK = '[검증 알림] 요약 제출 키 오류 — Worker 가 제출을 거부해요(키체인 digest_key 와 Worker Secret 확인)'


def auth_failed(state, now):
    """`/digest`·`/status` 가 401 — 맥의 키와 Worker Secret 이 다르다. 세션 훅과 다음 요약 머리에 보인다."""
    state.setdefault('auth_error', now.isoformat())
    state['last_error'] = '제출 키 오류'
    if not any(isinstance(c, dict) and c.get('kind') == 'auth' for c in state.get('carry') or []):
        _carry(state, now.date().isoformat(), 'auth')


def auth_ok(state):
    state.pop('auth_error', None)


def carry_notes(state):
    """머리 안내로 가는 것 — 제출 키 오류(그 사이 고쳐졌어도 한 번은 알린다)."""
    return [AUTH_NOTE] if any(isinstance(c, dict) and c.get('kind') == 'auth'
                              for c in state.get('carry') or []) else []


def carry_lines(state, today):
    """지난 요약의 접수 결과 — 다음 요약 꼬리에 한 번 싣는다(고정 문구)."""
    out = []
    for c in state.get('carry') or []:
        if not isinstance(c, dict) or c.get('kind') not in CARRY:     # 'auth' 는 머리로(carry_notes)
            continue
        try:
            d = date.fromisoformat(c.get('date'))
        except (TypeError, ValueError):
            continue
        who = '어제' if (today - d).days == 1 else '오늘' if d == today else f'{d.month}/{d.day:02d}'
        out.append(f'{who} {CARRY[c["kind"]]}')
    return out


def compose(posts, prev_lines, now, notes, tail, numbers, tracked, published, v=1):
    """제출본(`pending`)을 만든다 — 글 3,900자·요청 16 KB 안. 넘으면 글을 더 미룬다(자르지 않는다)."""
    day = now.date().isoformat()
    for limit in range(LIMIT, 900, -500):
        text, lines = render(posts, prev_lines, now, notes, tail, limit=limit)
        base = {'lines': lines, 'numbers': numbers, 'tracked': tracked,
                'open': sorted(p['path'] for p in posts if not resolved(p)),
                'all': sorted(p for p in published if post_day(p))}
        p = {'id': f'{day}:morning-digest:v{v}', 'date': day, 'v': v, 'text': text, 'base': base, 'tries': []}
        if 1 <= len(text) <= LIMIT and len(request_body(p).encode('utf-8')) <= MAX_BODY:
            return p
    raise SizeError('요약이 요청 크기 안에 들어가지 않는다')


# ── 꼬리: 발행 알림(GitHub 계산 기록)·전송기 상태 ─────────────────────────────────

STATE_BRANCH = 'alerts-state'
TAIL_UNREAD = '발행 알림: 상태를 못 읽었어요 — 미발행·전송 여부를 몰라요'
TAIL_MISSING = '발행 알림: GitHub 계산 기록이 아직 없어요'
HEALTH_STALE_HOURS = 9
CONFIG_ERROR = '설정 오류 — 텔레그램으로 못 보내는 중(Cloudflare 상태 확인)'
HEALTH_TIMEOUT = 5
HEALTH_FAILS = 3


def publish_tail(root, now, fetch=True, run=subprocess.run):
    """`origin/alerts-state:verify_publish.json`(GitHub 이 계산한 공개 상태)을 읽어 꼬리 줄로. 읽기만 한다."""
    remote = f'refs/remotes/origin/{STATE_BRANCH}'

    def git(*args):
        return run(['git', '-C', root, *args], capture_output=True, timeout=60)
    try:
        reachable = None
        if fetch:
            ls = git('ls-remote', '--exit-code', 'origin', f'refs/heads/{STATE_BRANCH}')
            if ls.returncode == 2:                       # 원격에 그 브랜치가 없다(네트워크 실패와 구분)
                return [TAIL_MISSING]
            reachable = ls.returncode == 0
            if reachable:                                # 러너 사본이 main 만 받는 설정이어도 받게 refspec 을 적는다
                git('fetch', '--quiet', 'origin', f'+refs/heads/{STATE_BRANCH}:{remote}')
        if git('rev-parse', '--verify', '--quiet', remote).returncode:
            return [TAIL_UNREAD if reachable is False else TAIL_MISSING]
        show = git('show', f'{remote}:verify_publish.json')
        if show.returncode:
            return [TAIL_UNREAD]
        from review import publish_watch as W
        st = W.loads_state(show.stdout)                  # 형식·내용 검사까지 — 이상하면 StateError → 못 읽음
        # GitHub 계산은 3시간 심장 박동이라 맥 시절의 2시간 기준을 쓰면 매일 「n시간 전」이 뜬다
        return [str(x) for x in W.summary_lines_from(st, now, stale=W.GITHUB_STALE)]
    except Exception:  # noqa: BLE001 — 발행 알림 상태가 이상해도 매일 요약은 나가야 한다
        return [TAIL_UNREAD]


def health_lines(health, now):
    """Worker `/status.health` — 이상할 때만 한 줄. `health=None` 은 조회 실패다(정상으로 읽지 않는다)."""
    if not isinstance(health, dict):
        return ['전송기: 상태를 못 읽었어요 — 전송 여부를 몰라요']
    bits = []
    if health.get('config_error') is not None:          # null | {code, kind, since} — 내용은 옮겨 적지 않는다
        bits.append(CONFIG_ERROR)
    for key, label in (('backlog', '밀린 알림'), ('failed', '영구 실패')):
        n = health.get(key)
        if type(n) is not int or n < 0:
            bits.append(f'{label} 수를 못 읽었어요')
        elif n:
            bits.append(f'{label} {n}건')
    ok = health.get('last_outbox_ok')
    if ok is None:
        bits.append('GitHub 계산 기록을 아직 정상으로 읽은 적이 없어요')
    else:
        try:
            hours = _hours(now, ok)
            if hours >= HEALTH_STALE_HOURS:
                bits.append(f'GitHub 계산 기록 마지막 정상 {hours}시간 전')
        except (TypeError, ValueError):
            bits.append('GitHub 계산 기록 시각을 못 읽었어요')
    return ['전송기: ' + ' · '.join(bits)] if bits else []


# ── 세션 시작 훅: 전송기 설정 오류는 텔레그램 말고 여기서 보인다(2026-11-10 사용자 결정) ─────────

def _health_file(path):
    # 요약 기록 파일과 따로 둔다 — 훅은 잠금 없이 도는데, 같은 파일을 고쳐 쓰면 tick 이 막 저장한 제출본을 덮을 수 있다.
    return path + '.health'


def fetch_health(run=subprocess.run):
    """공개 `GET /health` → config_error(bool). 주소가 없으면 None(조용히 건너뜀), 못 읽으면 TransportError.
    제출 키는 읽지 않는다 — 훅이 키를 만질 이유가 없다."""
    try:
        url = _keychain('worker_url', run).rstrip('/')
    except (OSError, subprocess.SubprocessError):
        return None
    if not _URL.fullmatch(url):
        return None
    code, text = _curl(url + '/health', None, run, max_time=HEALTH_TIMEOUT)
    if code != 200:
        raise TransportError('응답')
    try:
        obj = json.loads(text)
    except ValueError:
        raise TransportError('JSON') from None
    if not isinstance(obj, dict) or obj.get('format') != 'alerts-health/1' \
            or type(obj.get('config_error')) is not bool:
        raise TransportError('형식')
    return obj['config_error']


def worker_note(path, run=subprocess.run):
    """세션 시작 한 줄(전송기) — 설정 오류면 알리고, 조회 실패는 연속 3번째부터만 말한다. 할 말이 없으면 ''."""
    counter = _health_file(path)
    try:
        bad = fetch_health(run)
    except TransportError:
        try:
            with open(counter, encoding='utf-8') as fh:
                n = int(json.load(fh).get('fail') or 0)
        except (OSError, ValueError, TypeError, AttributeError):
            n = 0
        n += 1
        try:
            save_state(counter, {'fail': n})
        except OSError:
            pass
        return '[검증 알림] 전송기 상태 확인 불가' if n >= HEALTH_FAILS else ''
    if bad is None:
        return ''
    try:
        os.unlink(counter)
    except OSError:
        pass
    return f'[검증 알림] 전송기 {CONFIG_ERROR}' if bad else ''
