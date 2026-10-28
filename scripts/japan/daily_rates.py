"""일본 일간 — JGB(네이버증권 당일 → MOF T+1 폴백)·BOJ 시계열 API 해석 (2026-10-27, 네이버 10-29).

**JGB 1순위는 네이버증권(2026-10-29 사용자 지시).** 지표물(`JP{n}YT=RR`) 일별 행은 도쿄 마감
(15:14~15:30 JST)에서 고정되므로 저녁 발행에 **당일** 값을 싣는다. 해석은 US 와 같은
`us.naver_yields`(전 만기 한 날짜, 닫히면서 실패). MOF 는 상수만기 커브라 정의가 다르다 —
수준 차가 30년 최대 7.5bp(59일 실측)라 **두 원천 사이의 bp 는 만들지 않는다**(전부 네이버 아니면 전부 MOF).
설계 docs/superpowers/specs/2026-10-29-japan-daily-naver-jgb.md.

MOF 커브는 다음 도쿄 영업일에 올라온다 — 저녁 발행의 JGB 는 **직전 세션** 값이고, 그보다
오래되면 결측이다. bp 는 그 관측일과 CSV 의 바로 앞 행(직전 채권 영업일)의 차이다.
BOJ API 는 키가 없다(이용 고지: 크레디트 필수, 과도한 호출 금지). `SURVEY_DATES` 가 관측 기간이고
`LAST_UPDATE` 는 메타데이터 수정에도 바뀌므로 신선도 판정에 쓰지 않는다(codex 설계 검토 #4).
시리즈 코드는 하드코딩하지 않고 `/getMetadata` 의 이름에서 찾는다.

Pure — 네트워크 없음.
"""
import math
import re
from datetime import date, datetime, timedelta, timezone

from us import naver_yields as NY

TENORS = ('2Y', '5Y', '10Y', '30Y')
NAVER_CODES = {'2Y': 'JP2YT=RR', '5Y': 'JP5YT=RR', '10Y': 'JP10YT=RR', '30Y': 'JP30YT=RR'}
NAVER_CLOSE_FROM = '15:10'   # JST. 행 스탬프가 이보다 이르면 장중 행이다(실측 마감 240건 15:14~15:30)
NAVER_CHAIN_TOL = 0.0005     # %. 세션 종가 − 네이버 등락 = 직전 행 종가(4자리 반올림 폭)
NAVER_READY = '17:45'        # JST. 2시간 지연 + 15:30 마감 + 여유 — 이 전 수집은 채택하지 않는다
NAVER_MOF_MAX_BP = 15.0      # 직전 세션 수준 차 상한 — 넘으면 코드 매핑을 의심한다(정상 차 ≤7.5bp)
CALL_MAX_LAG = 3          # 거래일. 2026-10-27 실측: 10/26 세션에 10/22 까지(2거래일)


def _finite(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def prev_business(day, holidays=()):
    """도쿄 영업일 기준 바로 앞 날 — 주말·`holidays` 를 건너뛴다."""
    d = date.fromisoformat(day) - timedelta(days=1)
    while d.weekday() >= 5 or d.isoformat() in set(holidays or ()):
        d -= timedelta(days=1)
    return d.isoformat()


def jgb_block(rows, prev_session, tenors=TENORS, holidays=None):
    """MOF 폴백. `holidays` 를 주면 비교 행이 정확히 그 앞 영업일일 때만 bp 를 낸다 —
    CSV 에 한 날이 빠지면 2세션 변화가 「전일」로 찍힌다(codex 설계 검토 #4)."""
    usable = [r for r in rows or [] if r.get('date', '') <= prev_session]
    if not usable or usable[-1]['date'] != prev_session:
        latest = usable[-1]['date'] if usable else None
        return {**{t: None for t in tenors}, 'why': f'MOF 커브 최신 {latest} — 직전 세션 {prev_session} 미게시'}
    last, before = usable[-1], (usable[-2] if len(usable) > 1 else None)
    if before and holidays is not None and before['date'] != prev_business(prev_session, holidays):
        before = None
    out = {}
    for t in tenors:
        v = last.get(t)
        if not _finite(v):
            out[t] = None
            continue
        p = before.get(t) if before else None
        out[t] = {'value': v, 'period': last['date'], 'prev_period': before['date'] if before else None,
                  'chg_bp': round((v - p) * 100, 1) if _finite(p) else None, 'unit': '%', 'source': 'mof'}
    return out


_JST = timezone(timedelta(hours=9))


def _jst_rows(payload):
    """원 행 -> [(JST 날짜, JST 시:분, 종가, 네이버 등락)]. 스탬프는 실제로 파싱해 JST 로 옮긴다 — 문자열 앞 10자를
    날짜로 읽으면 다른 오프셋의 행이 엉뚱한 날로 간다(구현 검토 #5). 못 읽는 스탬프는 버리고,
    못 읽는 종가는 None 으로 남겨 호출부의 유한값 검사가 막게 한다."""
    out = []
    for r in (payload or {}).get('result') or []:
        try:
            t = datetime.fromisoformat(str(r.get('localTradedAt') or ''))
        except ValueError:
            continue
        if t.tzinfo is None:
            continue
        t = t.astimezone(_JST)
        out.append((t.date().isoformat(), t.strftime('%H:%M'), _num(r.get('closePrice')), _num(r.get('fluctuations'))))
    return out


def _num(raw):
    try:
        return float(str(raw).replace(',', ''))
    except ValueError:
        return None


def _rows_on(payload, day):
    """그 JST 날짜의 원 행들 — (시:분, 종가, 네이버 등락). 중복·비유한 판정은 호출부가 한다."""
    return [(hm, v, f) for d, hm, v, f in _jst_rows(payload) if d == day]


def naver_ready(session, fetched_jst):
    """수집 시각이 마감 확정 뒤인가. `fetched_jst` = (YYYY-MM-DD, HH:MM) JST.

    시세가 2시간 지연이라 15:30 마감 호가는 17:30 쯤 보인다 — 16:30 예약 실행은 장중 행
    (15:00~15:2x)을 받을 수 있고 행 스탬프만으로는 그걸 가를 수 없다(codex 설계 검토 #2).
    """
    day, hm = fetched_jst
    return day > session or (day == session and hm >= NAVER_READY)


def mof_check(series, mof_rows, prev_session, tenors=TENORS):
    """네이버 직전 세션 수준을 MOF 같은 날 행과 대조 -> 'ok' / 'mismatch: …' / 'skip: …'.

    정의가 달라 정상 차가 ≤7.5bp 다 — 15bp 는 만기 매핑이 틀린 경우만 잡는다.
    """
    if mof_rows is None:
        return 'skip: MOF 수집 실패'
    row = next((r for r in mof_rows if r.get('date') == prev_session), None)
    if not row:
        return f'skip: MOF {prev_session} 행 없음'
    # 값이 있는 만기는 먼저 전부 대조한다 — 한 만기 결측이 다른 만기의 큰 차이를 덮지 않게(재검토 7차 #2)
    missing = [t for t in tenors if not _finite(row.get(t))]
    for t in tenors:
        n = dict(series[t])[prev_session]
        if t not in missing and abs(n - row[t]) * 100 > NAVER_MOF_MAX_BP:
            return f'mismatch: {t} 네이버 {n} vs MOF {row[t]}'
    return f'skip: MOF {prev_session} {",".join(missing)} 결측' if missing else 'ok'


def jgb_naver(payloads, session, prev_session, fetched_jst, mof_rows=None, tenors=TENORS):
    """네이버 `marketIndex/prices` 응답(만기별) -> (블록, 사유, MOF 대조).

    전부-아니면-전무다. 블록이 None 이면 사유가 있고 호출부가 MOF 로 내려간다:
    수집이 마감 확정 전 · 세션/직전 세션 행이 만기마다 정확히 하나의 유한값이 아님 ·
    세션 행이 도쿄 마감 전 스탬프 · 직전 공통일이 달력의 직전 세션이 아님(한 날이 통째로
    빠지면 2세션 변화가 「전일」로 찍힌다 — `build_curve` 의 공백 검사는 그걸 못 본다) ·
    MOF 대조 불일치.
    """
    if not naver_ready(session, fetched_jst):
        return None, f'수집 {fetched_jst[1]} JST — 네이버 마감 확정({NAVER_READY}) 전', None
    for t in tenors:
        for day in (session, prev_session):
            got = _rows_on((payloads or {}).get(t), day)
            if len(got) != 1 or not _finite(got[0][1]):
                return None, f'네이버 {t} {day} 행 {len(got)}개(유한값 하나여야 한다)', None
        # 직전 세션 행도 마감 행이어야 한다 — 장중 값이 분모면 bp 가 틀린다(재검토 6차 #1)
        for day in (session, prev_session):
            hm = _rows_on(payloads[t], day)[0][0]
            if hm < NAVER_CLOSE_FROM:
                return None, f'네이버 {t} {day} 행 {hm} — 도쿄 마감 전', None
        # 사슬: 네이버가 직전 행을 기준 종가로 쓰고 있는가. 끊기면 지표물 교체일(새 종목 오늘 − 옛 종목 어제는
        # 가짜 움직임)이거나 직전 행이 마감값이 아니다 — 60일 실측 236쌍 중 6쌍(재검토 7차 #1)
        _, now_v, fluct = _rows_on(payloads[t], session)[0]
        prev_v = _rows_on(payloads[t], prev_session)[0][1]
        if not _finite(fluct) or abs(now_v - fluct - prev_v) > NAVER_CHAIN_TOL:
            return None, f'네이버 {t} 등락 사슬 불일치({now_v} − {fluct} ≠ {prev_v}) — 지표물 교체 의심', None
    # 날짜는 JST 로 옮긴 같은 행에서 — `parse_prices` 의 문자열 날짜와 섞지 않는다
    series = {t: sorted((d, v) for d, _, v, _ in _jst_rows(payloads[t]) if _finite(v)) for t in tenors}
    shared = NY.shared_dates(series)
    if not shared or shared[-1] != session:
        return None, f'네이버 공통 최신일 {shared[-1] if shared else None} — 세션 {session} 아님', None
    before = shared[-2] if len(shared) > 1 else None
    if before != prev_session:
        return None, f'네이버 직전 공통일 {before} ≠ 직전 세션 {prev_session}', None
    check = mof_check(series, mof_rows, prev_session, tenors)
    if check.startswith('mismatch'):
        return None, f'MOF 대조 {check}', check
    out = {}
    for t in tenors:
        v, p = dict(series[t])[session], dict(series[t])[prev_session]
        out[t] = {'value': round(v, 3), 'period': session, 'prev_period': prev_session,
                  'chg_bp': round((v - p) * 100, 1), 'unit': '%', 'source': 'naver'}
    return out, None, check


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
