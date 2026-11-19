"""일본 일간 달력 overlay — `japan/data/calendar_daily.json` (2026-10-27).

주간 달력(`calendar.json`)의 행 의미는 건드리지 않는다. 일간은 회의 기간(`kind: meeting`)과
결과 공표(`kind: release`)를 따로 적어, 회의 시작일에 매크로 절이 위로 오지 않게 한다
(codex 설계 검토 #5). 행마다 원출처 `source`·확인일 `checked_at` — 확인 못 한 날짜는 넣지 않는다.
스냅샷이 당일 행·14일 일정·`version()` 을 고정하고, 재검사는 스냅샷만 본다.

Pure — 네트워크 없음.
"""
import hashlib
import json
import re
from datetime import date, timedelta

PATH = 'japan/data/calendar_daily.json'


def load(path=PATH):
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


def version(cal):
    canon = json.dumps(cal, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(canon.encode('utf-8')).hexdigest()[:12]


_ISO_DAY = re.compile(r'\d{4}-\d{2}-\d{2}')


def valid_day(s):
    """엄격한 'YYYY-MM-DD' 만 날짜다 — `date.fromisoformat` 은 '2026-W47-4'(ISO 주 날짜)도 받는다(codex 구현 1회 #6).
    창 검증·당일·향후 조회가 모두 이 함수를 쓴다."""
    if not isinstance(s, str) or not _ISO_DAY.fullmatch(s):
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def today_events(cal, session):
    return [e for e in (cal or {}).get('events', []) if isinstance(e, dict) and valid_day(e.get('date'))
            and e.get('date') == session]


def event_day(cal, session):
    """매크로 절을 위로 올리는 날 — 그날 나온 major 결과 공표뿐이다."""
    return [e for e in today_events(cal, session)
            if e.get('kind') == 'release' and e.get('tier') == 'major']


def upcoming(cal, session, days=14):
    end = (date.fromisoformat(session) + timedelta(days=days)).isoformat()
    rows = [e for e in (cal or {}).get('events', []) if isinstance(e, dict) and valid_day(e.get('date'))
            and session < e['date'] <= end]
    return sorted(rows, key=lambda e: (e['date'], e.get('time_jst') or ''))


# ── 확인 창(coverage, v2 2026-11-19) ───────────────────────────────────
# 「오늘 일본 지표가 없다」는 일정표가 그날을 **빠짐없이** 덮을 때만 참이다. 계열마다 사람이 원출처에서 확인한 창
# `coverage: [{id, name_ko, cadence, source, from, through, checked_at}]` 과 행의 `cov` 로 그 범위를 적는다
# (`series` 는 BOJ 조회 열쇠라 건드리지 않는다). 확인 못 한 계열은 항목을 만들지 않는다 — 그 계열은 「미확인」이고
# 부재 캡션이 찍히지 않는다. 수집기(스냅샷 고정)와 매일 검증 알림(review/digest.py)이 같은 판정 함수를 쓴다(R14).
REQUIRED = (
    ('boj_policy', 'BOJ 금융정책'), ('cpi_national', '전국 CPI'), ('cpi_tokyo', '도쿄 CPI'), ('gdp', 'GDP'),
    ('cgpi', '기업물가'), ('sppi', '기업 서비스가격'), ('money_stock', '통화량'), ('monetary_base', '본원통화'),
    ('wages', '매월근로통계'), ('tankan', '단칸'), ('trade', '무역통계'), ('industrial_production', '광공업생산'),
    ('labour_force', '노동력조사'), ('household', '가계조사'), ('commercial', '상업동태통계'),
    ('machinery_orders', '기계수주'),
)
REQUIRED_NAMES = dict(REQUIRED)
UPCOMING_DAYS = 14
ALERT_DAYS = 21


UNLINKED = '계열을 확인할 수 없는 일정 행'


def _iso(s):
    return valid_day(s)


def malformed(cal):
    """날짜를 읽을 수 없는 행 — 어느 날의 일정인지 모르므로 모든 날의 부재 단정을 막는다."""
    return [e for e in (cal or {}).get('events') or [] if not isinstance(e, dict) or not valid_day(e.get('date'))]


def _unlinked(cal, lo, hi):
    """[lo, hi] 안에 있으면서 확인 창 계열(coverage id)에 연결되지 않는 행이 있는가(cov 없음·없는 cov)."""
    ids = {c.get('id') for c in (cal or {}).get('coverage') or [] if isinstance(c, dict)}
    for e in (cal or {}).get('events') or []:
        d = valid_day(e.get('date')) if isinstance(e, dict) else None
        if d and lo <= d <= hi and e.get('cov') not in ids:
            return True
    return False


def _months_inside(lo, hi):
    """[lo, hi] 에 1일부터 말일까지 완전히 드는 달들 (YYYY, MM)."""
    out = []
    y, m = lo.year, lo.month
    while (y, m) <= (hi.year, hi.month):
        first = date(y, m, 1)
        nxt = date(y + (m == 12), m % 12 + 1, 1)
        if first >= lo and nxt - timedelta(days=1) <= hi:
            out.append((y, m))
        y, m = y + (m == 12), m % 12 + 1
    return out


def windows(cal):
    """{계열 id: (from, through) | None} — 검증(R6·R10)을 통과한 필수 계열의 창만. None = 미확인."""
    cal = cal or {}
    events = [e for e in cal.get('events') or [] if isinstance(e, dict)]
    out = {cid: None for cid, _ in REQUIRED}
    entries = {}
    for c in cal.get('coverage') or []:
        if isinstance(c, dict) and c.get('id') in out:
            entries.setdefault(c['id'], []).append(c)
    for cid, got in entries.items():
        if len(got) != 1:
            continue                       # 같은 계열의 창이 둘이면 어느 쪽인지 모른다
        c = got[0]
        lo, hi = _iso(c.get('from')), _iso(c.get('through'))
        if not lo or not hi or lo > hi or not c.get('source') or not _iso(c.get('checked_at')):
            continue
        rows = [e for e in events if e.get('cov') == cid]
        days = [_iso(e.get('date')) for e in rows]
        if any(d is None or not lo <= d <= hi for d in days):
            continue                       # 창 밖 날짜의 행 — 창이 틀렸다
        if c.get('cadence') == 'monthly':
            have = {(d.year, d.month) for d, e in zip(days, rows) if e.get('kind') == 'release'}
            if any(ym not in have for ym in _months_inside(lo, hi)):
                continue                   # 창 안의 온전한 달에 발표 행이 없다 — 회의 행은 세지 않는다
        out[cid] = (lo, hi)
    # 필수 계열 id 를 달았지만 coverage 에 없는 행은 그 계열을 미확인으로 둔다(이미 None)
    return out


def missing(cal, start, end):
    """[start, end] 를 창이 덮지 못하는 필수 계열의 한국어 이름(REQUIRED 순서)."""
    lo, hi = date.fromisoformat(start), date.fromisoformat(end)
    w = windows(cal)
    out = [REQUIRED_NAMES[cid] for cid, _ in REQUIRED if not w[cid] or not (w[cid][0] <= lo and hi <= w[cid][1])]
    # 연결할 수 없는 행이 있으면 그 범위의 부재를 단정하지 않는다 — 날짜를 못 읽는 행은 어느 범위에나 걸린다
    if malformed(cal) or _unlinked(cal, lo, hi):
        out.append(UNLINKED)
    return out


def coverage(cal, session, days=UPCOMING_DAYS):
    """스냅샷에 고정할 {today_missing, upcoming_missing}. upcoming 은 대상일부터 대상일+14일 **전체 구간**(R10)."""
    end = (date.fromisoformat(session) + timedelta(days=days)).isoformat()
    return {'today_missing': missing(cal, session, session), 'upcoming_missing': missing(cal, session, end)}


def alert_missing(cal, today, days=ALERT_DAYS):
    """매일 검증 알림 — [오늘, 오늘+21일] 을 덮지 못하는 필수 계열 이름."""
    t = today if isinstance(today, str) else today.isoformat()
    return missing(cal, t, (date.fromisoformat(t) + timedelta(days=days)).isoformat())
