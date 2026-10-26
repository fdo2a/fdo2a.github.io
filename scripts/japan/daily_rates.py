"""일본 일간 — JGB(MOF, T+1)·BOJ 시계열 API 해석 (2026-10-27).

MOF 커브는 다음 도쿄 영업일에 올라온다 — 저녁 발행의 JGB 는 **직전 세션** 값이고, 그보다
오래되면 결측이다. bp 는 그 관측일과 CSV 의 바로 앞 행(직전 채권 영업일)의 차이다.
BOJ API 는 키가 없다(이용 고지: 크레디트 필수, 과도한 호출 금지). `SURVEY_DATES` 가 관측 기간이고
`LAST_UPDATE` 는 메타데이터 수정에도 바뀌므로 신선도 판정에 쓰지 않는다(codex 설계 검토 #4).
시리즈 코드는 하드코딩하지 않고 `/getMetadata` 의 이름에서 찾는다.

Pure — 네트워크 없음.
"""
import math
import re
from datetime import date, timedelta

TENORS = ('2Y', '5Y', '10Y', '30Y')
CALL_MAX_LAG = 3          # 거래일. 2026-10-27 실측: 10/26 세션에 10/22 까지(2거래일)


def _finite(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def jgb_block(rows, prev_session, tenors=TENORS):
    usable = [r for r in rows or [] if r.get('date', '') <= prev_session]
    if not usable or usable[-1]['date'] != prev_session:
        latest = usable[-1]['date'] if usable else None
        return {**{t: None for t in tenors}, 'why': f'MOF 커브 최신 {latest} — 직전 세션 {prev_session} 미게시'}
    last, before = usable[-1], (usable[-2] if len(usable) > 1 else None)
    out = {}
    for t in tenors:
        v = last.get(t)
        if not _finite(v):
            out[t] = None
            continue
        p = before.get(t) if before else None
        out[t] = {'value': v, 'period': last['date'], 'prev_period': before['date'] if before else None,
                  'chg_bp': round((v - p) * 100, 1) if _finite(p) else None, 'unit': '%'}
    return out


def period(freq, raw):
    s = str(raw)
    f = (freq or '').upper()
    if f == 'DAILY' and len(s) == 8:
        return f'{s[:4]}-{s[4:6]}-{s[6:]}'
    if f.startswith('QUARTERLY') and len(s) == 6:
        return f'{s[:4]}Q{int(s[4:])}'
    if f.startswith('MONTHLY') and len(s) == 6:
        return f'{s[:4]}-{s[4:]}'
    return s


def boj_values(resp):
    out = []
    for r in (resp or {}).get('RESULTSET') or []:
        vals = r.get('VALUES') or {}
        pts = [[period(r.get('FREQUENCY'), d), v]
               for d, v in zip(vals.get('SURVEY_DATES') or [], vals.get('VALUES') or []) if _finite(v)]
        out.append({'code': r.get('SERIES_CODE'), 'name': r.get('NAME_OF_TIME_SERIES'),
                    'unit': r.get('UNIT'), 'freq': r.get('FREQUENCY'), 'points': pts})
    return out


def _trading_days_between(a, b, holidays=()):
    """a < b 일 때 (a, b] 의 평일·비휴장일 수."""
    hol, n, d = set(holidays), 0, date.fromisoformat(a)
    end = date.fromisoformat(b)
    while d < end:
        d += timedelta(days=1)
        if d.weekday() < 5 and d.isoformat() not in hol:
            n += 1
    return n


def call_rate(resp, session, max_lag=CALL_MAX_LAG, holidays=()):
    for s in boj_values(resp):
        if not s['points']:
            continue
        d, v = s['points'][-1]
        if _trading_days_between(d, session, holidays) > max_lag:
            return None
        return {'value': v, 'period': d, 'unit': '%', 'code': s['code']}
    return None


def resolve_series(meta_resp, name_pattern):
    pat = re.compile(name_pattern)
    hits = [r['SERIES_CODE'] for r in (meta_resp or {}).get('RESULTSET') or []
            if pat.search(r.get('NAME_OF_TIME_SERIES') or '')]
    if len(hits) > 1:
        raise ValueError(f'{name_pattern!r} 가 시리즈 {len(hits)}개에 맞는다: {hits[:5]}')
    return hits[0] if hits else None
