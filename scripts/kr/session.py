"""KR 「오늘의 장」 재료.

US 쪽과 뼈대는 같고 시간 축만 한국 것이다 — 전일 미국장 → 아시아 동시간대 →
코스피 장중(미국 선물 오버레이) → 원달러.

이 파일은 자기 report_date를 갖는다. intraday.json이 기준일 없이 시각 문자열만
들고 있어 신선도를 증명하지 못하는 문제를 새 파일에서 반복하지 않는다.
"""

import datetime as _dt

PEERS = (('닛케이', '^N225'), ('항셍', '^HSI'),
         ('상해종합', '000001.SS'), ('대만가권', '^TWII'))
FUTURES = (('ES', 'ES=F'), ('NQ', 'NQ=F'))
# 휴장 달력(`data/market_holidays.json`)이 있는 아시아 지수 — 기대 날짜와 대조한다(jp 달력). 나머지는 달력이 없다.
CALENDAR_PEERS = ('닛케이',)
KR_OPEN, KR_CLOSE = (9, 0), (15, 30)
KST = _dt.timezone(_dt.timedelta(hours=9))
# 장중 창(선물·원달러)의 마지막 봉이 이 시각(KST) 이후여야 「그날 장 끝까지 본 창」이다(2026-11-17, 1a 구현 검토 2회차 F2).
# 정규장 마감 15:30 에서 30분봉 하나의 여유. 실측: origin/main 의 kr_session.json 92판(발행일 54일)에서 선물 창이 있는
# 91판·환율 92판의 마지막 봉이 전부 15:30. **조기 마감·개장 지연 달력은 없다**(`data/market_holidays.json` 은 휴장일만) —
# 그래서 다른 마감 시각을 추정하지 않는다. 선물·환율은 KRX 와 무관하게 거래되므로 KRX 가 일찍 닫는 날에도 15:30 KST 봉이
# 있을 것으로 **보지만 실측하지 못했다**(54일에 그런 날이 없다). 창 자체(09:00~15:30)가 그날 KRX 장 시간과 다른 날
# (수능일 10:00~16:30)은 여전히 구분하지 못한다.
WINDOW_END = (15, 0)


def _finite(x):
    return isinstance(x, (int, float)) and x == x


def _sessions_between(a, b):
    """주말만 뺀 거래일 간격. 정확한 휴장 달력이 없으므로 과대평가하지 않는다 —
    라벨을 붙일지 말지를 정하는 데는 이것으로 충분하다."""
    try:
        d0, d1 = _dt.date.fromisoformat(str(a)), _dt.date.fromisoformat(str(b))
    except ValueError:
        return None
    n, cur = 0, d0
    while cur < d1:
        cur += _dt.timedelta(days=1)
        if cur.weekday() < 5:
            n += 1
    return n


def expected_session(report_date, calendar, before):
    """(기대 거래일 | None, 이유). before=True 면 report_date **직전** 거래일(전일 미국장), False 면 report_date 이거나
    휴장이면 그 직전 거래일(같은 날 아시아 장). calendar = 휴장 달력 한 시장분 `{dates, valid_through}` —
    없거나 그날을 덮지 않으면 None(판정할 수 없다 — 성공으로 추정하지 않는다)."""
    try:
        day = _dt.date.fromisoformat(str(report_date))
    except ValueError:
        return None, 'report_date'
    if not isinstance(calendar, dict) or not isinstance(calendar.get('dates'), list):
        return None, 'calendar_missing'
    through = calendar.get('valid_through')
    if not isinstance(through, str) or through < day.isoformat():
        return None, 'calendar_out_of_range'
    hol = set(calendar['dates'])
    d = day - _dt.timedelta(days=1) if before else day
    while d.weekday() >= 5 or d.isoformat() in hol:
        d -= _dt.timedelta(days=1)
    return d.isoformat(), 'ok'


def us_prev(market_data, report_date):
    """전일 미국장. 같은 레포의 data/market_data.json을 읽고 재수집하지 않는다.

    미국이 쉬고 한국만 열면 며칠 묵은 값이 된다. `lag_sessions`가 2 이상이면
    writer가 「N일 미국장 기준」을 밝히고, 게이트가 그것을 강제한다.
    """
    if not market_data:
        return None
    idx = market_data.get('indices') or {}
    rows = {n: round(float(idx[n]['pct']), 2) for n in ('S&P 500', 'Nasdaq', 'Dow')
            if idx.get(n) and _finite(idx[n].get('pct'))}
    if not rows:
        return None
    as_of = str(market_data.get('report_date') or '')
    return {'as_of': as_of, 'rows': rows,
            'lag_sessions': _sessions_between(as_of, report_date) if as_of else None}


def kr_hours_window(bars, report_date):
    """한국 정규장 시간대(09:00~15:30 KST)의 선물 등락.

    이 창은 ET 달력에서 전날 밤에 걸린다. ET 날짜로 자르면 앞 절반이 사라지므로
    KST로 변환한 뒤 자른다.
    """
    try:
        day = _dt.date.fromisoformat(str(report_date))
    except ValueError:
        return None
    picked = []
    for b in bars or []:
        try:
            ts = _dt.datetime.fromisoformat(str(b.get('t'))).astimezone(KST)
        except (ValueError, TypeError):
            continue
        if ts.date() != day or not _finite(b.get('close')):
            continue
        if KR_OPEN <= (ts.hour, ts.minute) <= KR_CLOSE:
            picked.append((ts, float(b['close'])))
    if len(picked) < 2:
        return None
    picked.sort()
    first, last = picked[0][1], picked[-1][1]
    if not first:
        return None
    return {'pct': round((last / first - 1) * 100, 2), 'bars': len(picked),
            'first_t': picked[0][0].strftime('%H:%M'),
            'last_t': picked[-1][0].strftime('%H:%M')}


def window_complete(win):
    """(완결인가 | None, 사유). 창의 마지막 봉(`last_t`, HH:MM KST)이 `WINDOW_END` 이후면 완결. 마지막 봉 시각을 읽지
    못하면 None — 판정할 수 없다(완결로 추정하지 않는다)."""
    t = (win or {}).get('last_t')
    try:
        hh, mm = str(t).split(':')
        last = (int(hh), int(mm))
    except (ValueError, AttributeError):
        return None, 'last_t 를 읽지 못했다'
    if last >= WINDOW_END:
        return True, None
    return False, f'마지막 봉 {t} < {WINDOW_END[0]:02d}:{WINDOW_END[1]:02d}'


def usdkrw_window(bars, report_date):
    """원달러 정규장 구간의 고·저와 종가.

    야후가 이 시리즈를 `Europe/London`으로 준다 — KST로 변환한 뒤 자른다.
    """
    try:
        day = _dt.date.fromisoformat(str(report_date))
    except ValueError:
        return None
    picked = []
    for b in bars or []:
        try:
            ts = _dt.datetime.fromisoformat(str(b.get('t'))).astimezone(KST)
        except (ValueError, TypeError):
            continue
        if ts.date() != day:
            continue
        if not all(_finite(b.get(k)) for k in ('high', 'low', 'close')):
            continue
        if KR_OPEN <= (ts.hour, ts.minute) <= KR_CLOSE:
            picked.append((ts, b))
    if not picked:
        return None
    picked.sort()
    hi = max(picked, key=lambda p: p[1]['high'])
    lo = min(picked, key=lambda p: p[1]['low'])
    return {'high': round(float(hi[1]['high']), 2), 'high_t': hi[0].strftime('%H:%M'),
            'low': round(float(lo[1]['low']), 2), 'low_t': lo[0].strftime('%H:%M'),
            'close': round(float(picked[-1][1]['close']), 2),
            'last_t': picked[-1][0].strftime('%H:%M'), 'bars': len(picked)}


def asia_peers(pcts, kospi_pct):
    """아시아 이웃 시장과 코스피의 상대 강약.

    값은 `{이름: 등락}` 또는 `{이름: (등락, 기준일)}`을 받는다. 기준일을 함께
    주면 그대로 실어 휴장으로 묵은 값을 발행 게이트가 잡을 수 있다.
    """
    rows, dates = {}, {}
    for k, v in (pcts or {}).items():
        pct, date = v if isinstance(v, (tuple, list)) else (v, None)
        if not _finite(pct):
            continue
        rows[k] = round(pct, 2)
        if date:
            dates[k] = str(date)
    if not rows or not _finite(kospi_pct):
        return None
    avg = sum(rows.values()) / len(rows)
    return {'rows': rows, 'dates': dates, 'avg_pct': round(avg, 2),
            'relative_pp': round(kospi_pct - avg, 2)}
