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


# ── 일본 일정표 바닥(2026-11-13) ─────────────────────────────────────────
# 일본 일정표 두 개는 원출처에서 확인한 날짜를 사람이 손으로 넣는다(추측 금지). 갱신하는 장치가 없어
# 일간 일정표가 11/12 에서 끝난 뒤 조용히 비었다 — 일간은 일정표에 「오늘 발표」 줄이 있어야 지표를 싣고
# 결정일을 올리므로(collect_japan_daily), 표 하나가 아니라 매크로 절이 통째로 멈춘다. 마지막 일정이 2주 안으로
# 들어오면 매일 아침 알린다. 날짜를 채우는 것은 사람 몫이다 — 이 코드는 알리기만 한다.
JP_CALENDARS = (('일간', 'japan/data/calendar_daily.json', '지표 표·결정일 표시·다음 일정 표가 멈춰요'),
                ('주간', 'japan/data/calendar.json', '다음 일정 표가 비어요'))
JP_CAL_RUNWAY = 14
_ISO_DAY = re.compile(r'\d{4}-\d{2}-\d{2}')
JP_CAL_UNREAD = '일본 일정표를 읽지 못했어요'


def jp_calendar_notes(cals, today, runway=JP_CAL_RUNWAY):
    """{이름: 일정표 dict 또는 None} → 마지막 일정이 today+runway 이하(또는 일정 없음)인 일정표마다 한 줄."""
    notes = []
    limit = today + timedelta(days=runway)
    for name, _path, effect in JP_CALENDARS:
        if name not in (cals or {}):
            continue
        cal = cals[name]
        if not isinstance(cal, dict) or not isinstance(cal.get('events'), list):
            notes.append(JP_CAL_UNREAD)
            continue
        days = []
        for e in cal['events']:
            # 소비 코드(daily_calendar·core.next_events)는 'YYYY-MM-DD' 문자열로 비교한다 — 그 꼴이 아닌 날짜는 거기서도
            # 안 잡히므로 바닥 계산에서도 뺀다(20270129 를 유효로 읽으면 알림이 늦는다)
            d = e.get('date') if isinstance(e, dict) else None
            if isinstance(d, str) and _ISO_DAY.fullmatch(d):
                try:
                    days.append(date.fromisoformat(d))
                except ValueError:
                    continue
        last = max(days) if days else None
        if last is not None and last > limit:
            continue
        where = f'마지막 일정이 {_md(last.isoformat())}예요' if last else '일정이 하나도 없어요'
        notes.append(f'일본 {name} 일정표 {where} — 원출처에서 확인한 일정을 더하지 않으면 {effect}')
    return list(dict.fromkeys(notes))


def jp_calendars(root, rev='origin/main'):
    """원격 판의 일본 일정표 둘 — 파일이 없거나 JSON 이 아니면 None(알림에 「읽지 못했어요」)."""
    out = {}
    for name, path, _effect in JP_CALENDARS:
        b = _git_bytes(root, 'show', f'{rev}:{path}')
        try:
            out[name] = json.loads(b.stdout) if b.returncode == 0 else None
        except ValueError:
            out[name] = None
    return out


def _git_bytes(root, *args):
    return subprocess.run(['git', '-C', root, *args], capture_output=True, timeout=60)


# ── KR 수집 검사 기록(2026-11-12) ─────────────────────────────────────────
# 실행 manifest 의 `checks` 만 읽는다(같은 날 뒤 재수집이 고정 경로를 덮어도 남는다). 줄은 아래 고정 문구만 —
# 원문·긴 값은 싣지 않고, 사전 밖의 값은 「알 수 없는 상태」. 차단 사유의 당일 전달은 미발행 감시가 맡는다.
# spec: docs/superpowers/specs/2026-11-12-kr-missing-vs-zero.md

KR_CHECK_UNREAD = 'KR 수집 검사 기록을 읽지 못했어요'
KR_CHECK_DAYS = 3
KR_CHECK_KEEP_DAYS = 14
KR_IDX = {'KOSPI': '코스피', 'KOSDAQ': '코스닥'}
KR_SIDES = {'individual': '개인', 'foreign': '외국인', 'institution': '기관'}
KR_PCT_WHY = {'ratio_missing': '등락률을 못 읽음', 'unverified': '등락률을 검증할 전일 종가를 못 읽음',
              'flat_unverified': '보합(0.00%)을 확인하지 못함', 'flat_contradicted': '보합(0.00%)인데 전일 종가와 어긋남',
              'fetch_error': '지수를 못 읽음'}
KR_CFG_WHY = {'missing_default': '설정 파일이 없음 — 경고만(warn)으로 읽음',
              'invalid_block': '설정을 읽지 못함 — 차단(block)으로 읽음'}
_KR_STOP = '발행 멈춤'
_MD = r'\d{1,2}/\d{2}'
_PCT = r'[+-]\d+\.\d{2}%'
_KR_CHECK_NOTE = re.compile('|'.join([
    rf'KR {_MD} (?:코스피|코스닥) 등락률: 네이버 {_PCT} vs 종가로 계산 {_PCT} — 같은 응답 안에서 어긋남'
    r'\((?:기록만, 차단 꺼짐|차단 켜짐 — 발행 멈춤)\)',
    rf'KR {_MD} (?:코스피|코스닥) 등락률: (?:' + '|'.join(re.escape(x) for x in KR_PCT_WHY.values())
    + r') — 등락률 결측으로 발행 멈춤',
    rf'KR {_MD} (?:코스피|코스닥) 등락률: 알 수 없는 상태 — 맥에서 확인',
    rf'KR {_MD} (?:코스피|코스닥) 등락률: 전일 종가가 두 응답에서 어긋남\(같은 응답 안 계산은 일치\) — 기록만',
    rf'KR {_MD} 등락률 검증 설정: (?:' + '|'.join(re.escape(x) for x in KR_CFG_WHY.values()) + ')',
    rf'KR {_MD} (?:코스피|코스닥) 수급: (?:개인|외국인|기관)(?:·(?:개인|외국인|기관))* 값을 못 읽음\((?:당일|{_MD})\)'
    r' — 수급 결측으로 발행 멈춤',
    rf'KR {_MD} (?:코스피|코스닥) 수급: 요청 실패 — 수급 결측으로 발행 멈춤',
    rf'KR {_MD} (?:코스피|코스닥) 수급: 알 수 없는 상태 — 맥에서 확인',
    rf'KR {_MD} (?:코스피|코스닥) 수급: {_MD} (?:개인|외국인|기관)(?:·(?:개인|외국인|기관))* 값을 못 읽음'
    r' — 그 날만 주간 집계에서 빠짐\(기록만\)',
    rf'KR {_MD} 거래대금: (?:수집 실패|상위 표의 양수 행이 10개 미만) — 거래대금 결측으로 발행 멈춤',
    rf'KR {_MD} 거래대금: 빈 값\(-\) 비율 \d{{1,3}}% — 부분 장애일 수 있음\(기록만\)',
    rf'KR {_MD} 판 기록 없이 올라간 수집 \d{{1,4}}건',
]))


def _md(d):
    return f'{int(d[5:7])}/{d[8:10]}'


def _fnum(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and x == x and abs(x) != float('inf')


def _sides(fields):
    names = [KR_SIDES[f] for f in (fields or []) if f in KR_SIDES]
    return '·'.join(names) if names else None


def kr_check_items(date, checks):
    """한 실행의 checks → [(항목, status, 줄)]. 정상(ok·ok_flat, cross_note 없음)은 줄을 내지 않는다."""
    out, md = [], _md(date)
    if not isinstance(checks, dict):
        return out
    ip = checks.get('index_pct') if isinstance(checks.get('index_pct'), dict) else {}
    mode = ip.get('mode')
    cfg = ip.get('config_status')
    if cfg in KR_CFG_WHY:
        out.append(('index_pct.config', cfg, f'KR {md} 등락률 검증 설정: {KR_CFG_WHY[cfg]}'))
    for name, label in KR_IDX.items():
        e = ip.get(name)
        if not isinstance(e, dict):
            continue
        st = e.get('status')
        head = f'KR {md} {label} 등락률: '
        if st == 'mismatch':
            r, d = e.get('naver_pct'), e.get('derived_pct')
            tail = '차단 켜짐 — 발행 멈춤' if mode == 'block' else '기록만, 차단 꺼짐'
            if _fnum(r) and _fnum(d):
                out.append((f'index_pct.{name}', st,
                            f'{head}네이버 {r:+.2f}% vs 종가로 계산 {d:+.2f}% — 같은 응답 안에서 어긋남({tail})'))
            else:
                out.append((f'index_pct.{name}', st, f'{head}알 수 없는 상태 — 맥에서 확인'))
        elif st in KR_PCT_WHY:
            out.append((f'index_pct.{name}', st, f'{head}{KR_PCT_WHY[st]} — 등락률 결측으로 {_KR_STOP}'))
        elif st not in ('ok', 'ok_flat'):
            out.append((f'index_pct.{name}', 'unknown', f'{head}알 수 없는 상태 — 맥에서 확인'))
        if e.get('cross_note') is True:
            out.append((f'index_pct.{name}', 'cross_note',
                        f'{head}전일 종가가 두 응답에서 어긋남(같은 응답 안 계산은 일치) — 기록만'))
    fl = checks.get('flows') if isinstance(checks.get('flows'), dict) else {}
    for name, label in KR_IDX.items():
        e = fl.get(name)
        if not isinstance(e, dict):
            continue
        st, faults = e.get('state'), [f for f in e.get('faults') or [] if isinstance(f, dict)]
        head = f'KR {md} {label} 수급: '
        if st == 'error':
            out.append((f'flows.{name}', 'error', f'{head}요청 실패 — 수급 결측으로 {_KR_STOP}'))
        elif st == 'blocked':
            f0 = faults[0] if faults else {}
            who, fd = _sides(f0.get('fields')), f0.get('date')
            when = '당일' if fd == date else (_md(fd) if isinstance(fd, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', fd)
                                             else None)
            if who and when:
                out.append((f'flows.{name}', f'blocked@{fd}', f'{head}{who} 값을 못 읽음({when}) — 수급 결측으로 {_KR_STOP}'))
            else:
                out.append((f'flows.{name}', 'blocked', f'{head}알 수 없는 상태 — 맥에서 확인'))
        elif st != 'ok':
            out.append((f'flows.{name}', 'unknown', f'{head}알 수 없는 상태 — 맥에서 확인'))
        if st == 'ok':
            for f in faults:
                who, fd = _sides(f.get('fields')), f.get('date')
                if who and isinstance(fd, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', fd):
                    out.append((f'flows.{name}', f'{f.get("status")}@{fd}',
                                f'{head}{_md(fd)} {who} 값을 못 읽음 — 그 날만 주간 집계에서 빠짐(기록만)'))
    tv = checks.get('top_value')
    if isinstance(tv, dict):
        if 'error' in tv:
            out.append(('top_value', 'error', f'KR {md} 거래대금: 수집 실패 — 거래대금 결측으로 {_KR_STOP}'))
        else:
            pos, rows, dash = tv.get('positive_rows'), tv.get('rows'), tv.get('dash')
            if isinstance(pos, int) and pos < 10:
                out.append(('top_value', 'positive_lt_10',
                            f'KR {md} 거래대금: 상위 표의 양수 행이 10개 미만 — 거래대금 결측으로 {_KR_STOP}'))
            if isinstance(rows, int) and rows > 0 and isinstance(dash, int) and dash > rows * 0.15:
                out.append(('top_value', 'dash_gt_15',
                            f'KR {md} 거래대금: 빈 값(-) 비율 {round(dash * 100 / rows)}% — 부분 장애일 수 있음(기록만)'))
    return out


_KR_RUN = re.compile(r'^versions/kr/(\d{4}-\d{2}-\d{2})/(runs|fallback)/([^/]+?)(/manifest\.json|\.json)$')


def _show_json(root, rev, path):
    """`git show rev:path` 의 JSON(dict) 또는 None — 비정상 종료·깨진 JSON·호출 예외(시간 초과·OSError) 모두 None.
    한 파일을 못 읽은 일이 앞서 읽은 줄을 버리게 두지 않는다(codex 구현 검토 2회 #4)."""
    try:
        b = _git_bytes(root, 'show', f'{rev}:{path}')
        obj = json.loads(b.stdout) if b.returncode == 0 else None
    except (subprocess.SubprocessError, OSError, ValueError):
        return None
    return obj if isinstance(obj, dict) else None


def kr_check_notes(root, rev='origin/main', seen=None):
    """원격 판 `versions/kr/` 최근 3개 거래일 폴더의 실행 manifest `checks` → (줄 목록, [(키, 줄)]).

    키 = 「거래일|항목|status」. `seen`(알림 상태 파일의 kr_checks_seen)에 있는 키는 다시 내지 않는다 — 기록은
    접수가 확인된 뒤 `mark_accepted` 가 한다. 폴백만 있는 날은 「판 기록 없이 올라간 수집 N건」과
    `kr/data/kr_market_data.json` 의 checks(그 거래일일 때만)로 보완한다. 읽기 실패는 한 줄(KR_CHECK_UNREAD).
    """
    seen = seen if isinstance(seen, dict) else {}
    try:
        r = _git_bytes(root, 'ls-tree', '-r', '--name-only', rev, 'versions/kr/')
        if r.returncode != 0:
            return [KR_CHECK_UNREAD], []
        runs, falls = {}, {}
        for path in r.stdout.decode().split('\n'):
            m = _KR_RUN.match(path.strip())
            if not m:
                continue
            d, kind, rid, tail = m.groups()
            if kind == 'runs' and tail == '/manifest.json':
                runs.setdefault(d, []).append((rid, path.strip()))
            elif kind == 'fallback' and tail == '.json':
                falls.setdefault(d, []).append(rid)
        days = sorted(set(runs) | set(falls))[-KR_CHECK_DAYS:]
        items, md_cache, unread = [], None, False
        for d in days:
            for rid, path in sorted(runs.get(d, [])):
                # 한 실행을 못 읽어도 나머지 실행의 줄은 낸다 — 못 읽은 사실은 한 줄로(KR_CHECK_UNREAD)
                man = _show_json(root, rev, path)
                if man is None:
                    unread = True
                    continue
                ck = man.get('checks')
                if isinstance(ck, dict) and 'error' in ck:       # 수집 실행이 검사 기록을 못 남겼다
                    unread = True
                elif isinstance(ck, dict):                       # 이 변경 전 manifest 에는 없다 — 건너뛴다
                    items += [(d, *x) for x in kr_check_items(d, ck)]
            orphan = [f for f in falls.get(d, []) if f not in {rid for rid, _ in runs.get(d, [])}]
            if orphan:
                items.append((d, 'fallback', str(len(orphan)), f'KR {_md(d)} 판 기록 없이 올라간 수집 {len(orphan)}건'))
                if md_cache is None:
                    # 보완 자료를 못 읽으면(없음·깨짐) 그 사실을 한 줄로 — 다른 실행의 줄은 그대로(구현 검토 1회 #4)
                    md_cache = _show_json(root, rev, 'kr/data/kr_market_data.json')
                    if md_cache is None:
                        unread, md_cache = True, {}
                if md_cache.get('report_date') == d:
                    items += [(d, *x) for x in kr_check_items(d, md_cache.get('checks'))]
    except (subprocess.SubprocessError, OSError, ValueError, UnicodeDecodeError):
        return [KR_CHECK_UNREAD], []
    lines, keys, done = ([KR_CHECK_UNREAD] if unread else []), [], set()
    for d, item, status, line in items:
        key = f'{d}|{item}|{status}'
        if key in done or key in seen:
            continue
        done.add(key)
        lines.append(line)
        keys.append((key, line))
    return lines, keys


def surviving_kr_keys(keys, text):
    """요약에 실제로 실린 줄의 키만 — 줄어서 빠진 줄은 다음 요약에 다시 낸다."""
    return [k for k, line in keys if f'⚠ {line}' in text]


def remember_kr_checks(state, p, now):
    """접수가 확인된 제출본의 KR 검사 키를 기억한다(14일 지난 키는 지운다)."""
    seen = state.get('kr_checks_seen') if isinstance(state.get('kr_checks_seen'), dict) else {}
    for k in p.get('kr_checks') or []:
        if isinstance(k, str):
            seen[k] = p['date']
    cutoff = (now.date() - timedelta(days=KR_CHECK_KEEP_DAYS)).isoformat()
    seen = {k: v for k, v in seen.items() if isinstance(v, str) and v >= cutoff}
    if seen or 'kr_checks_seen' in state:
        state['kr_checks_seen'] = seen


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


PREPUB_UNREAD = ' · [발행 전 기록] 읽지 못했어요'
PREPUB_WHY = {'module': '기록을 읽는 모듈을 불러오지 못했어요', 'read': 'git 이나 기록 파일을 읽지 못했어요',
              'render': '기록을 문장으로 옮기지 못했어요'}


def _prepub_unread(code=None):
    """고정 줄 — 예외 문장은 싣지 않는다. 모르는 코드·옛 꼴 문자열·str 아닌 값은 이유 없이."""
    why = PREPUB_WHY.get(code) if isinstance(code, str) else None
    return PREPUB_UNREAD + (f'({why})' if why else '')


def _prepub_lines(p):
    """발행 전 기록 대상(US·KR 일간, 2026-11-09~)만 — 다른 글의 문장은 그대로 둔다(바꾸면 90일치가 「바뀜」으로 다시 온다).
    예외를 올리지 않는다. 숫자 재검사 줄은 어느 경우에도 그대로 붙는다(#11)."""
    pv = p.get('prepub')
    if isinstance(pv, dict) and pv.get('error'):         # import 보다 먼저 본다 — 모듈이 없어도 이 줄은 나간다
        lines = [_prepub_unread(pv['error'])]
    else:
        try:
            from review import prepub_view as V
        except Exception:  # noqa: BLE001
            V = None
        if V is None:
            lines = [_prepub_unread('module')]
        else:
            try:
                lines = V.digest_lines(pv)
            except Exception:  # noqa: BLE001
                lines = [_prepub_unread('render')]
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
    # 집계는 그대로 두고 찍을 때만 상한을 건다 — 정상 입력의 문장은 한 글자도 다르지 않다(3a §A 6)
    n, v, w, f, bad, todo = (shown(x, TOTAL_CAP) or '?' for x in (len(posts), v, w, f, bad, todo))
    return (f'최근 {WINDOW_DAYS}일: 글 {n}편 · 숫자 위반 {v}·경고 {w}(US 일간 자동 검사 범위 안) · '
            f'codex 지적 {f}건(사실 오류로 확인된 수 아님) · 숫자 판정 불가 {bad} · 검토 미완료 {todo}')


def _header(now):
    return f'[검증 알림] {now.month}월 {now.day}일({WEEKDAY[now.weekday()]}) {now:%H:%M}'


# ── 꼭 싣는 줄의 정수·실패 종류와 이유(3a, 2026-11-12) ───────────────────────────────────

TOTAL_CAP = 99999            # render 가 만드는 줄·합계
HEALTH_CAP = 9999            # 전송기 줄
TRY_CAP = 999                # 접수 결과 줄의 시도 횟수


def shown(n, cap, unit=''):
    """꼭 싣는 줄의 정수는 전부 이 함수로 찍는다 — 줄 길이에 상한이 생긴다. 정수가 아니거나 음수·bool 이면 None."""
    if type(n) is not int or n < 0:
        return None
    return f'{n}{unit}' if n <= cap else f'{cap}{unit} 넘음'


ERRORS = ('접수 오류', '연결 오류', '제출 키 없음', '제출 키 오류', '전송 오류', '전송 보류', '충돌', '요약 만들기 오류',
          '크기 초과', '잠금 오류', '확인 불가', '기타 오류')
# (종류, 이유 코드) → 문장. 그 분기에서 맥이 아는 사실만 적는다 — 표에 없는 쌍은 이유 없이 종류만.
ERROR_WHY = {
    ('접수 오류', 'rejected'): 'Worker 가 제출을 거절했어요',
    ('연결 오류', 'server'): '약속에 없는 응답을 받았어요',
    ('연결 오류', 'noresp'): '응답을 받지 못했어요',
    ('충돌', 'conflict'): '409 응답을 받았어요 — 같은 id 에 다른 본문이 먼저 접수돼 있다는 뜻이에요',
    ('전송 오류', 'failed_permanent'): 'Worker 가 이 요약을 영구 실패로 처리했어요 — 이유는 Worker 가 보내는 경보에서 확인해 주세요',
    ('전송 보류', 'held'): 'Worker 가 접수만 하고 보내지 않았어요(보류 — Worker 는 하루 두 판까지만 보내요)',
    ('확인 불가', 'nohash_mac'): '맥의 접수 기록에 본문 대조 값이 없어 대조하지 못했어요',
    ('확인 불가', 'nohash_worker'): 'Worker 응답에서 본문 대조 값을 확인하지 못했어요',
    ('확인 불가', 'nohash'): '본문 대조 값을 확인하지 못했어요',
    ('확인 불가', 'absent'): f'Worker 상태 목록(최근 {STATUS_DAYS}일)에 그 사건이 없어 전송을 확인하지 못했어요',
    ('제출 키 없음', 'cfg_read'): '키체인을 읽는 명령을 끝내지 못했어요',
    ('제출 키 없음', 'cfg_url'): '키체인에서 읽은 Worker 주소가 비었거나 https 주소 모양이 아니에요',
    ('제출 키 없음', 'cfg_key'): '키체인에서 읽은 제출 키가 비었거나 모양이 달라요',
    ('제출 키 없음', 'cfg'): '키체인의 제출 키나 Worker 주소를 확인해 주세요',
    ('요약 만들기 오류', 'max_versions'): '오늘 낼 수 있는 판 번호(v9)를 다 썼어요',
    ('요약 만들기 오류', 'exception'): '요약을 만드는 중 오류가 났어요(자세한 내용은 맥 로그)',
    ('크기 초과', 'size'): '요약이 길이·요청 크기 한도 안에 들어가지 않았어요',
    ('잠금 오류', 'lock_set'): '기록 파일 잠금을 설정하지 못했어요',
    ('잠금 오류', 'lock_open'): '잠금 파일을 열지 못했어요',
}
ERROR_NOTE = '지난 알림 실패 — '


def error_kind(value):
    """실패 사유는 종류만 남긴다 — 예외 문장에는 맥 경로가 섞일 수 있다(설계 v4·v7 #6)."""
    return value if isinstance(value, str) and value in ERRORS else '기타 오류'


def set_error(state, kind, why=None):
    """실패 종류와 이유 코드를 **함께** 쓴다 — `last_error` 를 쓰는 자리는 이 함수와 clear_error 뿐이다(시험이 소스를 본다)."""
    state['last_error'] = kind
    if isinstance(why, str):
        state['last_error_why'] = {'kind': kind, 'why': why}
    else:
        state.pop('last_error_why', None)


def clear_error(state):
    state['last_error'] = None
    state.pop('last_error_why', None)


def error_reason(state):
    """이유 문장 | None. 이유 칸의 종류가 지금 종류와 같고 (종류, 코드)가 표에 있을 때만 — 그 밖은 예외 없이 None.
    옛 코드가 종류만 바꿔도 낡은 이유가 다른 종류에 붙지 않는다."""
    w = state.get('last_error_why')
    if not isinstance(w, dict):
        return None
    kind, why = w.get('kind'), w.get('why')
    if not (isinstance(kind, str) and isinstance(why, str)) or kind != error_kind(state.get('last_error')):
        return None
    return ERROR_WHY.get((kind, why))


def error_text(state):
    """`종류` 또는 `종류 — 이유 문장` — 요약 머리와 세션 훅이 함께 쓴다."""
    reason = error_reason(state)
    return error_kind(state.get('last_error')) + (f' — {reason}' if reason else '')


# ── 기밀: 구조로 먼저, 정규식은 보조 검사(설계 v6 #4·v7 #6) ─────────────────────

class Must(str):
    """꼭 싣는 줄 — 길이·개수에 상한이 있는 고정 문구. 예산이 빠듯해도 빼지 않는다(만드는 쪽이 붙인다)."""
    __slots__ = ()


class Soft(str):
    """줄일 수 있는 줄 — 이름·개수에 상한이 없다. 표시 없는 꼬리 입력도 이쪽으로 다룬다."""
    __slots__ = ()


_NAMES = '|'.join(sorted(re.escape(v) for v in LABEL.values()))
_NAME_LIST = rf'(?:{_NAMES}) \d{{1,2}}/\d{{2}}(?:, (?:{_NAMES}) \d{{1,2}}/\d{{2}})*'
TRIM_SUFFIX = '(이름은 맥 로그에서 확인)'
# 이름 목록 뒤: 통째 / 이름 경계에서 줄인 꼴(`A, B 외 n건(…)`) / 이름 0개 꼴(`…n건(…)`). n 은 실제 이름 수라 상한이 없다.
_NAME_TAIL = rf'(?:: {_NAME_LIST}(?: 외 \d+건{re.escape(TRIM_SUFFIX)})?|{re.escape(TRIM_SUFFIX)})'
NOTE_FIRST = f'첫 알림이라 최근 {WINDOW_DAYS}일 글과 끝나지 않은 옛 글을 담았어요'
NOTE_STALE = '최신 판을 못 받았어요 — 마지막으로 받아 둔 판 기준이에요'
NOTE_CORRUPT = '기록 파일이 손상돼 새로 시작했어요 — 지난 상태와 비교하지 못했어요'
AUTH_NOTE = '요약 제출 키 오류가 있었어요 — Worker 가 제출을 거부했어요(키체인 digest_key 와 Worker Secret 확인)'
# 머리 안내는 이 목록의 문구만 나간다. 그 밖은 「기타 안내 n건」 — 내용은 맥에서 본다.
# 어느 묶음에 맞았는지가 분류다(§A 1): _MUST_NOTES = 꼭 싣는 줄, 이름 목록·KR 지수 누락 = 줄일 수 있는 줄.
_MUST_NOTES = tuple(re.compile(re.escape(x)) for x in (
    [NOTE_FIRST, NOTE_STALE, NOTE_CORRUPT, AUTH_NOTE, KR_CHECK_UNREAD, JP_CAL_UNREAD]
    + [ERROR_NOTE + k for k in ERRORS]
    + [f'{ERROR_NOTE}{k} — {sentence}' for (k, _why), sentence in ERROR_WHY.items()]))
_NAME_NOTES = tuple(re.compile(x + _NAME_TAIL) for x in (
    r'공개판에서 사라진 글 \d+건',
    r'\d+일이 지나 추적을 멈춘 글 \d+건\(안 끝났거나 못 보낸 글\)',
    r'\d+일보다 오래된 날짜의 글이 새로 올라왔어요\(검사 안 함\) \d+건'))
_KR_NOTE = re.compile(
    r'KR 주간 \d{4}-W\d{2} 지수 누락: [A-Z0-9]+ \d{4}-\d{2}-\d{2}(?:, [A-Z0-9]+ \d{4}-\d{2}-\d{2})* — '
    r'새벽 재수집으로 자동 보완하지 않아요\. 원자료를 확인해 글을 정정한 뒤 수동 승격\(versions\.py promote\)해야 '
    r'주간이 나가요')
_JP_CAL_NOTE = re.compile(
    rf'일본 (?:일간|주간) 일정표 (?:마지막 일정이 {_MD}예요|일정이 하나도 없어요) — 원출처에서 확인한 일정을 더하지 않으면 '
    r'(?:지표 표·결정일 표시·다음 일정 표가 멈춰요|다음 일정 표가 비어요)')
_MUST_NOTES = _MUST_NOTES + (_JP_CAL_NOTE,)      # 짧은 고정 문구 둘뿐 — 줄이지 않는다
NOTE_PATTERNS = _MUST_NOTES + _NAME_NOTES + (_KR_NOTE, _KR_CHECK_NOTE)


def _classified_notes(notes):
    """[(문장, 'must' | 'names' | 'kr')] — 정해진 문구만. 나머지는 개수만 센 꼭 싣는 줄 하나로."""
    out, other = [], 0
    for n in notes:
        if not isinstance(n, str):
            other += 1
        elif any(p.fullmatch(n) for p in _NAME_NOTES):
            out.append((n, 'names'))
        elif _KR_NOTE.fullmatch(n) or _KR_CHECK_NOTE.fullmatch(n):
            out.append((n, 'kr'))
        elif any(p.fullmatch(n) for p in _MUST_NOTES):
            out.append((n, 'must'))
        else:
            other += 1
    if other:
        count = shown(other, TOTAL_CAP, '건') or '?건'
        out.append((f'기타 안내 {count} — 맥에서 확인', 'must'))
    return out


def safe_notes(notes):
    """정해진 문구만 통과시킨다. 나머지는 개수만 — 예외 문장·경로가 안내 줄로 새지 않게."""
    return [n for n, _cls in _classified_notes(notes)]


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


class _NameNote:
    """이름 목록 안내 하나 — 이름 경계에서 뒤부터 던다. 길이는 조립하지 않고 센다(이름이 십만 개여도 걸음마다 O(1))."""

    def __init__(self, note):
        self.full = note
        self.raw = note.endswith(TRIM_SUFFIX)            # 이미 줄여 들어온 문장 — 더 덜 이름이 없다(통째로만 뺀다)
        self.prefix, _, rest = note.partition(': ')
        self.names = [] if self.raw else rest.split(', ')
        self.keep = len(self.names)
        self._cum = [0]
        for x in self.names:
            self._cum.append(self._cum[-1] + len(x))

    @property
    def cut(self):
        return not self.raw and self.keep < len(self.names)

    def text(self):
        if self.raw or not self.cut:
            return self.full
        if not self.keep:
            return self.prefix + TRIM_SUFFIX
        return f'{self.prefix}: {", ".join(self.names[:self.keep])} 외 {len(self.names) - self.keep}건{TRIM_SUFFIX}'

    def __len__(self):
        if self.raw or not self.cut:
            return len(self.full)
        if not self.keep:
            return len(self.prefix) + len(TRIM_SUFFIX)
        return (len(self.prefix) + 2 + self._cum[self.keep] + 2 * (self.keep - 1)
                + len(f' 외 {len(self.names) - self.keep}건') + len(TRIM_SUFFIX))


def _dropped_line(n):
    count = shown(n, TOTAL_CAP, '줄') or '?줄'
    return f'길어서 줄인 안내 {count} — 맥 로그에서 확인'


class _Budget:
    """머리·꼬리의 줄을 「꼭 싣는 줄」과 「줄일 수 있는 줄」로 들고, 자르기 전에 예산을 맞춘다(3a §A).

    길이는 `'\n\n'.join(머리 + 본문 줄 + 꼬리 + 맺음) + 120` — 3a 전 코드의 `fixed` 와 같은 식이다(머리 줄 사이를
    두 칸으로 세어 실제보다 조금 넉넉하다). 식을 그대로 둬야 줄이지 않는 입력의 전송본이 예전과 글자 하나 다르지 않다.
    """
    SLACK = 120                                           # 「…외 n건은 다음 알림에」·「n줄 생략」 자리

    def __init__(self, head, body_line, tail, closing):
        # head·tail 항목: {'text': 실을 문장, 'cls': must|names|kr|soft, 'orig': 줄이기 전 문장, 'k': 보조 검사에 걸린 줄 수}
        self.head, self.body_line, self.tail, self.closing = head, body_line, tail, closing
        for x in head + tail:
            x['on'] = True
        self.dropped = 0

    def _items(self):
        return [x for x in self.head + self.tail if x['on']]

    @staticmethod
    def _len(x):
        return len(x['note']) + 2 if x['cls'] == 'names' else len(x['text'])     # 2 = '⚠ '

    def measure(self):
        sizes = [self._len(x) for x in self._items()] + [len(self.body_line)] + [len(x) for x in self.closing]
        if self.dropped:
            sizes.append(len(_dropped_line(self.dropped)))
        return sum(sizes) + 2 * (len(sizes) - 1) + self.SLACK

    def end_measure(self):
        """줄일 수 있는 줄을 0줄까지 뺀 끝 상태의 길이 — 뺀 줄이 있으면 「길어서 줄인 안내」 줄이 들어 있다."""
        must = [x for x in self._items() if x['cls'] == 'must']
        soft = self.dropped + len(self._items()) - len(must)
        sizes = [self._len(x) for x in must] + [len(self.body_line)] + [len(x) for x in self.closing]
        if soft:
            sizes.append(len(_dropped_line(soft)))
        return sum(sizes) + 2 * (len(sizes) - 1) + self.SLACK

    def steps(self):
        """한 걸음씩 줄인다(걸음마다 yield). ① 이름을 경계에서 — 그때 가장 긴 안내부터 ② 줄일 수 있는 꼬리 줄을 뒤에서부터
        ③ KR 지수 누락 안내를 뒤에서부터 ④ 이름 0개까지 줄인 안내를 뒤에서부터."""
        names = [x for x in self.head if x['cls'] == 'names']
        while True:
            left = [x for x in names if x['note'].keep > 0]
            if not left:
                break
            max(left, key=lambda x: len(x['note']))['note'].keep -= 1
            yield
        for group in ([x for x in self.tail if x['cls'] == 'soft'], [x for x in self.head if x['cls'] == 'kr'], names):
            for x in reversed(group):
                x['on'] = False
                self.dropped += 1
                yield

    def fit(self, limit, first=None):
        """줄이는 조건은 둘뿐이다. (가) 고정 부분만으로 넘칠 때 — 들어가는 첫 상태까지. (나) 첫 글 블록을 위해 —
        **다 줄인 끝 상태에서 블록이 들어갈 때만**, 블록이 들어가는 첫 상태까지. 끝 상태에서도 안 들어가면 한 걸음도 더
        줄이지 않는다(안내를 빼고도 글을 못 싣는 일이 없게 — codex 설계 12·13회)."""
        walk = self.steps()
        if self.measure() > limit:
            for _ in walk:
                if self.measure() <= limit:
                    break
        if first is not None and self.measure() + first + 2 > limit and self.end_measure() + first + 2 <= limit:
            for _ in walk:
                if self.measure() + first + 2 <= limit:
                    break

    def lines(self, trimmed=None):
        """(머리 줄, 꼬리 줄, 보조 검사에 걸린 줄 수). 줄이거나 뺀 줄의 줄이기 전 문장은 `trimmed` 에 덧붙인다."""
        head, tail, hidden = [], [], 0
        for group, out in ((self.head, head), (self.tail, tail)):
            for x in group:
                if x['cls'] == 'names' and x['on']:
                    x['text'], x['k'] = scrub('⚠ ' + x['note'].text())
                if x['on']:
                    out.append(x['text'])
                    hidden += x['k']
                if trimmed is not None and (not x['on'] or (x['cls'] == 'names' and x['note'].cut)):
                    trimmed.append(x['orig'])
        if self.dropped:
            tail.append(_dropped_line(self.dropped))
        return head, tail, hidden


def render(posts, prev_lines, now, notes=(), extra_tail=(), limit=LIMIT, trimmed=None):
    """(보낼 글, 기록할 문장표). 바뀐 글만 자세히, 끝나지 않은 글은 꼬리에 이름만.

    줄 중간에서 자르지 않는다(3a). 넘치면 줄일 수 있는 줄(이름 목록·KR 지수 누락 안내·`Must` 표시 없는 꼬리 줄)을
    줄이고, 그래도 넘치면 글을 다음 알림으로 미룬다. `limit` 은 줄일 수 있는 줄과 글 블록의 예산이다 — 꼭 싣는 줄은
    limit 이 낮아도 빼지 않고, 그 줄들만으로 LIMIT 을 넘으면 SizeError(자르지 않는다).
    `trimmed`(목록)를 주면 줄이거나 뺀 줄의 줄이기 전 문장을 덧붙인다 — 맥 로그용, 다시 읽지 않는다.
    보조 검사에 걸린 글은 그 줄을 바꿔 싣되 문장표에 적지 않는다 — 다음 요약에서 다시 확인하게.
    """
    posts = sorted(posts, key=lambda p: (post_day(p['path']) or date.min, p['path']))
    head = [{'text': _header(now), 'cls': 'must', 'k': 0}]
    for n, cls in _classified_notes(notes):
        if cls == 'names':
            head.append({'note': _NameNote(n), 'cls': cls, 'orig': n, 'k': 0})
        else:
            line, k = scrub(f'⚠ {n}')
            head.append({'text': line, 'cls': cls, 'orig': n, 'k': k})
    open_ = sorted((p for p in posts if not resolved(p)),       # 최신부터 — 이름이 10개에서 잘린다
                   key=lambda p: -(post_day(p['path']) or date.min).toordinal())
    tail = []
    if open_:
        names = [_day_label(p['path']) for p in open_]
        more = f' 외 {shown(len(names) - 10, TOTAL_CAP, "건")}' if len(names) > 10 else ''
        tail.append({'text': f'아직 안 끝난 글 {shown(len(open_), TOTAL_CAP, "건")}: ' + ', '.join(names[:10]) + more,
                     'cls': 'must', 'k': 0})
    unread = sum(1 for p in posts if p['state'] == '읽지 않음')
    if unread:
        tail.append({'text': f'읽지 않고 범위에 넣은 글 {shown(unread, TOTAL_CAP, "편")}'
                             f'(90일 안, 게이트 도입 전 글, 검토 대상 아님)', 'cls': 'must', 'k': 0})
    for x in extra_tail:              # 어제 요약 접수 결과·발행 건별 알림 상태·전송기 상태(읽기만)
        cls = 'must' if isinstance(x, Must) else 'soft'          # 분류는 만든 쪽의 표시로만 — 길이로 바꾸지 않는다
        line, k = scrub(str(x))
        tail.append({'text': line, 'cls': cls, 'orig': str(x), 'k': k})
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
    body = [f'새로 나온 글·바뀐 상태 {shown(len(changed), TOTAL_CAP, "건")}'] if changed \
        else ['새로 나온 글이나 바뀐 상태가 없어요.']
    budget = _Budget(head, body[0], tail, closing)
    budget.fit(limit, len(scrub(changed[0][1])[0]) if changed else None)
    head, tail, hidden = budget.lines(trimmed)
    if changed:
        fixed = len('\n\n'.join(head + body + tail + closing)) + _Budget.SLACK
        used = 0
        for i, (p, text) in enumerate(changed):
            text, k = scrub(text)
            if fixed + used + len(text) + 2 > limit:
                body.append(f'…외 {shown(len(changed) - i, TOTAL_CAP, "건")}은 다음 알림에 이어서 보낼게요.')
                break
            body.append(text)
            used += len(text) + 2
            hidden += k
            if not k:
                lines[p['path']] = {'sha': p.get('sha'), 'text': block(p)}
    if hidden:
        count = shown(hidden, TOTAL_CAP, '줄') or '?줄'
        tail.append(f'{count} 생략 — 맥에서 확인')
    text = '\n\n'.join(['\n'.join(head)] + body + tail + closing)
    if len(text) > LIMIT:             # 꼭 싣는 줄만으로 넘친다 — 줄 중간에서 자르지 않고 실패로 올린다
        raise SizeError('꼭 싣는 줄만으로 글 길이 한도를 넘는다')
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
        return f'[검증 알림] 마지막 시도 실패 — {error_text(st)}'
    late = 0
    for u in unconfirmed(st):
        try:
            late += _hours(now, u.get('accepted_at')) >= UNCONFIRMED_HOURS
        except (TypeError, ValueError, OverflowError):
            late += 1
    if late:
        return f'[검증 알림] 접수된 요약 {late}건이 {UNCONFIRMED_HOURS}시간 넘게 전송 확인이 안 돼요'
    sent = st.get('last_sent')
    if not sent:
        return '' if unconfirmed(st) else '[검증 알림] 아직 한 번도 안 보냈어요'
    try:
        hours = _hours(now, sent)
    except (TypeError, ValueError, OverflowError):
        return '[검증 알림] 마지막 전송 시각을 못 읽었어요'
    return f'[검증 알림] 마지막 전송 {hours}시간 전' if hours > STALE_HOURS else ''


# ── Worker 에 제출(2.5단계) — 맥은 텔레그램 토큰을 읽지 않는다 ──────────────────────

STATES = ('accepted', 'queued', 'sending', 'sent', 'failed_permanent', 'held')
RESULTS = ('accepted', 'dup', 'conflict', 'rejected', 'server', 'noresp')
_KEY = re.compile(r'[A-Za-z0-9._~+/=-]{32,128}')
_URL = re.compile(r'https://[A-Za-z0-9.-]+(?::\d{1,5})?')
_ID = re.compile(r'(\d{4}-\d{2}-\d{2}):morning-digest:v([1-9])')


class ConfigError(Exception):
    """열쇠고리에 제출 키·Worker 주소가 없거나 모양이 이상하다. `why` = 이유 코드(cfg_read·cfg_url·cfg_key)."""

    def __init__(self, message='', why=None):
        super().__init__(message)
        self.why = why


def config_why(exc):
    """ConfigError → `ERROR_WHY` 의 코드. 메시지 문자열을 다시 읽어 분류하지 않는다 — 모르면 cfg."""
    why = getattr(exc, 'why', None)
    return why if isinstance(why, str) and ('제출 키 없음', why) in ERROR_WHY else 'cfg'


class TransportError(Exception):
    """응답을 못 받았거나 약속과 다른 응답 — 「없음」으로 읽지 않는다. `why` = `HEALTH_WHY` 의 코드, `status` = HTTP 코드."""

    def __init__(self, message='', why=None, status=None):
        super().__init__(message)
        self.why, self.status = why, status


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
        raise ConfigError('열쇠고리를 못 읽었어요', why='cfg_read') from None
    if not _URL.fullmatch(url):
        raise ConfigError('열쇠고리의 Worker 주소가 없거나 https 주소가 아니에요', why='cfg_url')
    if not _KEY.fullmatch(key):
        raise ConfigError('열쇠고리의 제출 키가 없거나 모양이 이상해요', why='cfg_key')
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
        raise AuthError('HTTP 401', why='auth', status=401)
    if code != 200:
        raise TransportError(f'HTTP {code}' if code else '응답 없음', why='http' if code else 'noresp', status=code)
    try:
        obj = json.loads(text)
    except ValueError:
        raise TransportError('JSON', why='json') from None
    if not isinstance(obj, dict) or obj.get('format') != 'digest-status/1' \
            or not isinstance(obj.get('events'), list):
        raise TransportError('형식', why='format')
    events = {}
    for e in obj['events']:
        if not (isinstance(e, dict) and isinstance(e.get('id'), str) and e.get('state') in STATES):
            raise TransportError('사건', why='event')
        events[e['id']] = e
    return {'events': events, 'health': obj['health'] if isinstance(obj.get('health'), dict) else None}


# ── 제출 상태(계약 §4): pending → unconfirmed → 기준(base) 적용 ───────────────────────

def migrate(state):
    """옛 상태(직접 전송 시절)를 새 이름으로. `last_sent`(옛 전송 시각)·`lines` 등은 그대로 기준으로 쓴다."""
    if 'last_sent_day' in state:
        old = state.pop('last_sent_day')
        state.setdefault('last_submitted_day', old)
    if state.get('last_error') and error_kind(state['last_error']) != state['last_error']:
        set_error(state, '기타 오류')
    if not state.get('last_error'):
        state.pop('last_error_why', None)                # 종류 없이 남은 이유 칸
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
    remember_kr_checks(state, p, now)              # KR 검사 줄은 접수가 확인된 뒤에만 기억한다(2026-11-12)
    state['last_submitted'] = now.isoformat()
    clear_error(state)


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
    except ConfigError as exc:          # 열쇠고리에서 막혔다 — 요청이 나가지 않았으니 시도로 세지 않는다
        p['tries'].pop()
        set_error(state, '제출 키 없음', config_why(exc))
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
        set_error(state, {'rejected': '접수 오류', 'conflict': '충돌'}.get(result, '연결 오류'), result)
    save(state)
    return result


def text_hash(text):
    """Worker `/status` 의 `hash` 와 대조하는 값 — 접수한 본문(text)의 sha256(계약 §3)."""
    import hashlib
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _event_hash(ev):
    h = ev.get('hash') if isinstance(ev, dict) else None
    return h.lower() if isinstance(h, str) and re.fullmatch(r'[0-9a-fA-F]{64}', h) else None


def _carry(state, day, kind, **more):
    """다음 요약 꼬리에 한 번 실을 접수 결과. `more` = 그 분기에서 아는 사실(why·tries·lookup) — 판정에는 안 쓴다."""
    state['carry'] = [c for c in state.get('carry') or [] if isinstance(c, dict)] \
        + [dict({'date': day, 'kind': kind}, **more)]


TRY_WORDS = (('rejected', '거절'), ('server', '약속에 없는 응답'), ('noresp', '응답 못 받음'), ('conflict', '409'),
             ('other', '기타'))


def _try_counts(tries):
    """시도 기록 → {결과: 횟수}(0 은 뺀다). 결과가 넷 밖이거나 str 이 아니거나 항목이 dict 가 아니면 other."""
    known = {k for k, _ in TRY_WORDS[:4]}
    out = {}
    for t in tries:
        r = t.get('result') if isinstance(t, dict) else None
        k = r if isinstance(r, str) and r in known else 'other'
        out[k] = out.get(k, 0) + 1
    return out


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
            # 어느 쪽 값이 없는지까지만 안다(§B) — 「Worker 가 주지 않았다」고 단정하지 않는다
            why = 'nohash_mac' if theirs else 'nohash_worker' if mine else 'nohash'
            _carry(state, u['date'], 'unverified', why=why)
            set_error(state, '확인 불가', why)
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
            clear_error(state)
        elif st in ('failed_permanent', 'held'):
            set_error(state, '전송 오류' if st == 'failed_permanent' else '전송 보류', st)
        elif st is None and _too_old(u, now):
            set_error(state, '확인 불가', 'absent')            # Worker 가 14일 지난 사건은 안 돌려준다(날짜를 못 읽은 것도 여기)
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
    # 판정용 집합 — str 이 아닌 결과(손상)는 'other' 로. 예전에는 배열·객체가 들어 있으면 TypeError 로 끝나
    # 기한 정리가 영영 안 됐다. 정상 기록(str 결과만)에서는 집합이 예전과 같다.
    results = {t['result'] if isinstance(t.get('result'), str) else 'other' for t in p['tries'] if isinstance(t, dict)}
    unread = False
    try:
        ev = lookup(p['id'])
    except (TransportError, ConfigError):
        ev, unread = None, True
    theirs = _event_hash(ev)
    if ev is not None and theirs == text_hash(p['text']):
        mark_accepted(state, now)
        return 'accepted'
    if ev is not None and (theirs or 'conflict' in results):
        _mark_day(state, p)
        clear_error(state)
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
    more = {}
    if outcome in ('failed', 'unknown'):                 # 문구용 — 범위를 밝힌 사실만(§G)
        more['tries'] = _try_counts(p['tries'])
    if outcome == 'unknown':
        more['lookup'] = 'nohash' if ev is not None else 'unread' if unread else 'absent'
    _carry(state, p['date'], outcome, **more)
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
         'unverified': '요약 전송 확인 불가'}
CARRY_MAX = 6                                             # 접수 결과 줄 — 넘으면 최근 6줄 + 「외 n건」
NO_TRY = '제출을 한 번도 내보내지 못했어요'
LOOKUP_WORDS = {'nohash': 'Worker 응답에서 본문 대조 값을 확인하지 못했어요',
                'unread': '마지막 확인 때 Worker 상태를 읽지 못했어요',
                'absent': 'Worker 상태 목록에 그 사건이 없었어요'}
UNVERIFIED_WHY = ('nohash_mac', 'nohash_worker', 'nohash')
AUTH_HOOK = '[검증 알림] 요약 제출 키 오류 — Worker 가 제출을 거부해요(키체인 digest_key 와 Worker Secret 확인)'


def auth_failed(state, now):
    """`/digest`·`/status` 가 401 — 맥의 키와 Worker Secret 이 다르다. 세션 훅과 다음 요약 머리에 보인다."""
    state.setdefault('auth_error', now.isoformat())
    set_error(state, '제출 키 오류')
    if not any(isinstance(c, dict) and c.get('kind') == 'auth' for c in state.get('carry') or []):
        _carry(state, now.date().isoformat(), 'auth')


def auth_ok(state):
    state.pop('auth_error', None)


def carry_notes(state):
    """머리 안내로 가는 것 — 제출 키 오류(그 사이 고쳐졌어도 한 번은 알린다)."""
    return [AUTH_NOTE] if any(isinstance(c, dict) and c.get('kind') == 'auth'
                              for c in state.get('carry') or []) else []


def _tries_phrase(tries):
    """carry 의 시도 칸 → 문구 | None(칸이 없거나 쓸 수 있는 항이 없다). 모양이 맞는 항만 쓴다 — 예외를 내지 않는다."""
    if not isinstance(tries, dict):
        return None
    terms = [(w, tries[k]) for k, w in TRY_WORDS if k in tries and type(tries[k]) is int and tries[k] >= 0]
    total = sum(n for _, n in terms)
    if not total:
        # 「한 번도 못 냈다」는 빠진 항이 하나도 없을 때만 참이다(빈 dict 로 **기록된** 경우 — 판정은 「접수 실패」여도
        # 거절을 암시하지 않는다). 모르는 열쇠·모양이 다른 값이 섞였으면 그 항이 몇 번인지 모르므로 횟수 문구를 뺀다.
        return NO_TRY if len(terms) == len(tries) else None
    terms = sorted((t for t in terms if t[1]), key=lambda t: -t[1])        # 많은 것부터(같으면 표 순서)
    return f'제출 시도 {shown(total, TRY_CAP, "번")}: ' + ' · '.join(f'{w} {shown(n, TRY_CAP)}' for w, n in terms)


def _carry_line(c, who):
    kind = c['kind']
    if kind == 'unverified':
        why = c.get('why')
        why = why if isinstance(why, str) and why in UNVERIFIED_WHY else 'nohash'     # why 없는 옛 기록 포함
        return f'{who} {CARRY[kind]} — {ERROR_WHY[("확인 불가", why)]}'
    line = f'{who} {CARRY[kind]}'
    if kind in ('failed', 'unknown'):
        look = c.get('lookup')
        bits = [_tries_phrase(c.get('tries')),
                LOOKUP_WORDS.get(look) if kind == 'unknown' and isinstance(look, str) else None]
        bits = [x for x in bits if x]
        if bits:
            line += '(' + ' · '.join(bits) + ')'
    return line


def carry_lines(state, today, trimmed=None):
    """지난 요약의 접수 결과 — 다음 요약 꼬리에 한 번 싣는다(고정 문구). 6줄을 넘으면 최근 6줄 + 「외 n건」 한 줄,
    넘친 줄의 문장은 `trimmed`(맥 로그용 목록)에 덧붙인다."""
    out = []
    for c in state.get('carry') or []:
        if not isinstance(c, dict) or not isinstance(c.get('kind'), str) or c['kind'] not in CARRY:
            continue                                     # 'auth' 는 머리로(carry_notes)
        try:
            d = date.fromisoformat(c.get('date'))
        except (TypeError, ValueError):
            continue
        who = '어제' if (today - d).days == 1 else '오늘' if d == today else f'{d.month}/{d.day:02d}'
        out.append(_carry_line(c, who))
    if len(out) > CARRY_MAX:
        over, out = out[:-CARRY_MAX], out[-CARRY_MAX:]
        out.append(f'지난 요약 접수 결과 외 {shown(len(over), TOTAL_CAP, "건")} — 맥 로그에서 확인')
        if trimmed is not None:
            trimmed.extend(over)
    return out


def compose(posts, prev_lines, now, notes, tail, numbers, tracked, published, v=1, trimmed=None):
    """제출본(`pending`)을 만든다 — 글 3,900자·요청 16 KB 안. 넘으면 글을 더 미룬다(자르지 않는다).
    `trimmed`(목록)에는 채택한 판에서 줄이거나 뺀 줄의 원문만 담는다. render 의 SizeError 는 그대로 올린다."""
    day = now.date().isoformat()
    for limit in range(LIMIT, 900, -500):
        cut = []
        text, lines = render(posts, prev_lines, now, notes, tail, limit=limit, trimmed=cut)
        base = {'lines': lines, 'numbers': numbers, 'tracked': tracked,
                'open': sorted(p['path'] for p in posts if not resolved(p)),
                'all': sorted(p for p in published if post_day(p))}
        p = {'id': f'{day}:morning-digest:v{v}', 'date': day, 'v': v, 'text': text, 'base': base, 'tries': []}
        if 1 <= len(text) <= LIMIT and len(request_body(p).encode('utf-8')) <= MAX_BODY:
            if trimmed is not None:
                trimmed.extend(cut)
            return p
    raise SizeError('요약이 요청 크기 안에 들어가지 않는다')


# ── 꼬리: 발행 알림(GitHub 계산 기록)·전송기 상태 ─────────────────────────────────

STATE_BRANCH = 'alerts-state'
TAIL_UNREAD = '발행 알림: 상태를 못 읽었어요 — 미발행·전송 여부를 몰라요'
TAIL_MISSING = '발행 알림: GitHub 계산 기록이 아직 없어요'
TAIL_NO_COPY = '발행 알림: 받아 둔 사본이 없어요(원격 확인 안 함)'
TAIL_COPY = '발행 알림: 최신 상태를 받지 못해 받아 둔 사본으로 읽었어요'
HEALTH_STALE_HOURS = 9
HEALTH_UNREAD = '전송기: 상태를 못 읽었어요 — 전송 여부를 몰라요'
HEALTH_WHY = {'auth': 'Worker 가 제출 키를 받지 않았어요(401)', 'noresp': '응답을 받지 못했어요',
              'json': '응답이 JSON 이 아니었어요', 'format': '응답 형식이 약속과 달랐어요',
              'event': '사건 목록에 약속과 다른 항목이 있었어요', 'health': '응답에 전송기 상태가 없거나 형식이 달랐어요'}
CONFIG_ERROR = '설정 오류 — 텔레그램으로 못 보내는 중(Cloudflare 상태 확인)'
# Worker 가 붙인 분류 이름 → 고정 낱말. 맥이 토큰·대화 번호를 읽는 코드가 아니다(그런 문자열 리터럴을 두지 않는 시험이 있어 dict() 로 쓴다)
CONFIG_KINDS = dict(token='봇 토큰', chat='대화 번호', forbidden='봇이 대화에서 차단·강퇴됨')
HEALTH_TIMEOUT = 5
HEALTH_FAILS = 3


def tail_unread(*reasons):
    """「상태를 못 읽었어요(이유 · 이유) — …」. 이유는 이 파일의 고정 낱말만 넘긴다 — 반환 코드·예외 이름은 stderr 에만."""
    if not reasons:
        return TAIL_UNREAD
    head, _, rest = TAIL_UNREAD.partition(' — ')
    return f'{head}({" · ".join(reasons)}) — {rest}'


def publish_tail(root, now, fetch=True, run=subprocess.run):
    """`origin/alerts-state:verify_publish.json`(GitHub 이 계산한 공개 상태)을 읽어 꼬리 줄로. 읽기만 한다.

    돌려주는 줄마다 분류를 붙인다(3a §A 1·§E 8): 이 함수가 만든 고정 한 줄은 `Must`, summary_lines_from 이 돌려준
    줄만 `Soft`. 어떤 실패도 예외로 올리지 않는다 — 발행 알림 상태가 이상해도 매일 요약은 나가야 한다.
    """
    remote = f'refs/remotes/origin/{STATE_BRANCH}'

    def step(*args):
        """git 한 번 — 실행 예외(시간 초과 포함)는 None(「실패」), 반환 코드는 그대로."""
        try:
            return run(['git', '-C', root, *args], capture_output=True, timeout=60)
        except (OSError, subprocess.SubprocessError) as exc:
            print(f'발행 알림 꼬리: git {args[0]} 실행 실패 — {type(exc).__name__}', file=sys.stderr)
            return None

    remote_fail = None
    if fetch:
        ls = step('ls-remote', '--exit-code', 'origin', f'refs/heads/{STATE_BRANCH}')
        if ls is not None and ls.returncode == 2:        # 원격에 그 브랜치가 없다(네트워크 실패와 구분) — 옛 사본도 읽지 않는다
            return [Must(TAIL_MISSING)]
        if ls is not None and ls.returncode == 0:        # 러너 사본이 main 만 받는 설정이어도 받게 refspec 을 적는다
            got = step('fetch', '--quiet', 'origin', f'+refs/heads/{STATE_BRANCH}:{remote}')
            if got is None or got.returncode:
                remote_fail = 'git fetch 실패'
        else:
            remote_fail = '원격 확인 실패'

    def unread(reason):
        return [Must(tail_unread(*([remote_fail] if remote_fail else []), reason))]

    ref = step('rev-parse', '--verify', '--quiet', remote)
    if ref is None:
        return unread('받아 둔 사본을 확인하지 못함')
    if ref.returncode:
        if remote_fail:
            return unread('받아 둔 사본 없음')
        return [Must(TAIL_MISSING if fetch else TAIL_NO_COPY)]       # 원격을 안 봤으면 「아직 없다」고 단정하지 않는다
    show = step('show', f'{remote}:verify_publish.json')
    if show is None or show.returncode:
        return unread('받아 둔 사본에서 파일을 못 읽음')
    try:
        from review import publish_watch as W
    except Exception as exc:  # noqa: BLE001
        print(f'발행 알림 꼬리: 모듈을 못 불러왔다 — {type(exc).__name__}', file=sys.stderr)
        return unread('요약 꼬리 계산 오류')
    try:
        st = W.loads_state(show.stdout)                  # 형식·내용 검사까지 — 이상하면 StateError
    except W.StateError:
        return unread('상태 파일 내용 검증 실패')
    except Exception as exc:  # noqa: BLE001
        print(f'발행 알림 꼬리: 상태를 못 읽었다 — {type(exc).__name__}', file=sys.stderr)
        return unread('요약 꼬리 계산 오류')
    try:
        # GitHub 계산은 3시간 심장 박동이라 맥 시절의 2시간 기준을 쓰면 매일 「n시간 전」이 뜬다
        lines = [Soft(str(x)) for x in W.summary_lines_from(st, now, stale=W.GITHUB_STALE)]
    except Exception as exc:  # noqa: BLE001
        print(f'발행 알림 꼬리: 문장을 못 만들었다 — {type(exc).__name__}', file=sys.stderr)
        return unread('요약 꼬리 계산 오류')
    if remote_fail:                                      # 읽기는 됐지만 최신인지 모른다
        lines.insert(0, Must(f'{TAIL_COPY}({remote_fail})'))
    return lines


def _config_error_bit(ce):
    """`/status.health.config_error` → 문구. Worker 가 준 글자는 옮기지 않는다 — 분류는 고정 낱말로, 시각은 KST 로."""
    if not isinstance(ce, dict):
        return CONFIG_ERROR
    kind = ce.get('kind')
    bits = [f'Worker 분류: {CONFIG_KINDS[kind]}'] if isinstance(kind, str) and kind in CONFIG_KINDS else []
    try:                                                 # 읽기·KST 변환·문자열 만들기를 한데 — 넘치는 시각도 여기서 걸린다
        t = parse_iso(ce.get('since')).astimezone(KST)
        bits.append(f'{t.month}/{t.day:02d} {t:%H:%M} 부터')
    except (TypeError, ValueError, OverflowError):
        pass
    if not bits:
        return CONFIG_ERROR
    return f'설정 오류 — 텔레그램으로 못 보내는 중({", ".join(bits)} · Cloudflare 설정 확인)'


def health_lines(health, now, why=None, status=None):
    """Worker `/status.health` — 이상할 때만 한 줄. `health=None` 은 조회 실패다(정상으로 읽지 않는다).
    `why`(`HEALTH_WHY` 의 코드)·`status`(HTTP 코드)를 주면 못 읽은 이유를 괄호로 붙인다. 어떤 값으로도 예외를 올리지 않는다."""
    if not isinstance(health, dict):
        reason = None
        if isinstance(why, str):
            if why == 'http':
                reason = f'HTTP {status} 응답을 받았어요' if type(status) is int and 100 <= status <= 599 \
                    else HEALTH_WHY['format']
            else:
                reason = HEALTH_WHY.get(why)
        return [HEALTH_UNREAD + (f'({reason})' if reason else '')]
    bits = []
    if health.get('config_error') is not None:          # null | {code, kind, since} — code 는 싣지 않는다
        bits.append(_config_error_bit(health['config_error']))
    for key, label in (('backlog', '밀린 알림'), ('failed', '영구 실패')):
        n = health.get(key)
        count = shown(n, HEALTH_CAP, '건')
        if count is None:
            bits.append(f'{label} 수를 못 읽었어요')
        elif n:
            bits.append(f'{label} {count}')
    ok = health.get('last_outbox_ok')
    if ok is None:
        bits.append('GitHub 계산 기록을 아직 정상으로 읽은 적이 없어요')
    else:
        try:
            hours = _hours(now, ok)
            if hours > HEALTH_CAP:
                bits.append(f'GitHub 계산 기록 마지막 정상 {shown(hours, HEALTH_CAP, "시간")}')
            elif hours >= HEALTH_STALE_HOURS:
                bits.append(f'GitHub 계산 기록 마지막 정상 {hours}시간 전')
        except (TypeError, ValueError, OverflowError):
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
