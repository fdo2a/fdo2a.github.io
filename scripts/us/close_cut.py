"""원자재·환율 행을 **뉴욕 16:00 ET 가격**으로, 오늘과 전일 모두 같은 기준으로 만든다.

야후 일봉은 24시간 시장에서 두 가지로 틀린다(2026-10-14 실측).

1. 원자재 선물: 오늘 봉의 Close 는 확정 전까지 **수집 시각의 시간외 거래가**이고, 전일
   봉은 결제가로 확정돼 있다. 그래서 `last` 와 `chg` 의 기준이 갈렸다 — 10/12 발행 Brent
   105.70 은 20:34 ET 시세였고 결제가는 106.65 였다. 다음 날 표의 등락률은 전날 발행
   종가로 이어지지 않았다.
2. 통화쌍: 일봉 자체가 날짜와 어긋난다. USD/KRW 일봉 10/12 1,340.84·10/13 1,334.13 은
   ECB 기준환율 역산(1,333.1·1,341.4)과 뒤바뀐 듯 맞지 않았고, 30분봉은 맞았다.

그래서 두 그룹은 30분봉에서 **16:00 ET 에 끝나는 마지막 봉의 종가**를 그날 값으로
쓴다(2026-10-14 사용자 선택). 주식 마감과 같은 시각이라 같은 표 안의 자산이 같은
순간을 가리키고, 수집 시각이 몇 시든 같은 값이 나온다. 결제가와는 다르다 — 결제가는
수집 시각에 확정 형태로 받을 수 없었다(시세의 previousClose 는 다음 세션이 열려야
바뀌어 금요일 결제가는 일요일까지 못 받는다, CME 공식 자료는 자동 수집 금지).

선물은 연속 티커(CL=F) 대신 그 시점의 **월물 티커**(CLX26.NYM)로 양쪽을 잰다. 롤 주간에
연속 티커의 전일 봉이 다른 월물이면 등락률이 월물 간 가격 차를 떠안는다(codex 설계
검토 A5).
"""
import math
from datetime import datetime, timedelta, timezone

BASIS = 'close_1600_et'
CUT_GROUPS = ('fx', 'commodities')
CUT_MINUTES = 16 * 60
BAR_MINUTES = 30


def _ny(ts):
    """ISO 시각 → 뉴욕 현지 시각. 서머타임은 zoneinfo 가 맡는다."""
    from zoneinfo import ZoneInfo
    t = datetime.fromisoformat(ts)
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return t.astimezone(ZoneInfo('America/New_York'))


def _bar_end(ts, bar_minutes):
    """봉 시작 ISO → (뉴욕 날짜, 그날 0시부터 센 끝 분). 날짜를 넘는 봉은 None."""
    t = _ny(ts)
    end = t + timedelta(minutes=bar_minutes)
    if end.date() != t.date() and not (end.hour == 0 and end.minute == 0):
        return None
    minutes = 24 * 60 if end.date() != t.date() else end.hour * 60 + end.minute
    return t.date().isoformat(), minutes


def _finite(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def bar_ends(bars, bar_minutes=BAR_MINUTES):
    """[(봉 시작 ISO, 종가)] → {뉴욕 날짜: {끝 분: 종가}}."""
    out = {}
    for ts, close in bars or []:
        v = _finite(close)
        key = _bar_end(ts, bar_minutes)
        if v is None or key is None:
            continue
        out.setdefault(key[0], {})[key[1]] = v
    return out


EARLY_CLOSE_MINUTES = 13 * 60
CLOSE_TOLERANCE_PCT = 0.1     # 30분봉 마지막 종가 vs 일봉 종가, 60일 실측 최대 0.058%(2026-10-14)


def session_ends(equity_bars, equity_daily, bar_minutes=BAR_MINUTES,
                 tol_pct=CLOSE_TOLERANCE_PCT):
    """믿을 수 있는 주식 세션 → {날짜: 마감 끝 분}. 세 조건을 모두 볼 때만 세션이다.

    1. 그날 S&P 500 **일봉**이 있다 — 세션 달력은 일봉이 정한다(30분봉과 따로 받은 근거).
    2. 30분봉이 16:00 이나 표준 단축장 13:00 에 끝난다.
    3. 그 마지막 30분봉 종가가 일봉 종가와 `tol_pct` 안이다.

    내려받은 30분봉의 마지막 봉을 그대로 마감으로 믿으면, 10:00 에서 끊긴 다운로드가 「10:00
    마감 세션」으로 통과해 자기 가정을 자기가 검증한다(codex 재검토 P1). 16:00 에 붙는
    길이 0 짜리 봉은 16:00 으로 본다.
    """
    daily = equity_daily or {}
    last = {}
    for ts, close in equity_bars or []:
        v = _finite(close)
        key = _bar_end(ts, bar_minutes)
        if v is None or key is None:
            continue
        day, m = key
        m = min(m, CUT_MINUTES)
        if day not in last or m >= last[day][0]:
            last[day] = (m, v)
    out = {}
    for day, (m, v) in last.items():
        ref = _finite(daily.get(day))
        if not ref or m not in (CUT_MINUTES, EARLY_CLOSE_MINUTES):
            continue
        if abs(v / ref - 1) * 100 <= tol_pct:
            out[day] = m
    return out


def cut_closes(bars, cut_minutes=CUT_MINUTES, bar_minutes=BAR_MINUTES):
    """[(봉 시작 ISO, 종가)] → {뉴욕 날짜: 끝 시각이 cut 이하인 마지막 봉의 종가}.

    주간 진단 이력처럼 세션 달력 없이 긴 구간을 자를 때 쓴다. 18:00 ET 에 다시 열리는
    다음 세션 봉은 같은 달력 날짜여도 16:00 뒤라 빠진다. 표의 행은 `cut_row` 가 세션
    마감 시각에 **정확히** 끝나는 봉만 받는다.
    """
    out = {}
    for day, by_end in bar_ends(bars, bar_minutes).items():
        ok = [m for m in by_end if m <= cut_minutes]
        if ok:
            out[day] = by_end[max(ok)]
    return out


def cut_row(ends, sessions, anchor, calendar=None, contract=None):
    """표의 한 행 — 오늘(anchor)과 **직전 주식 세션**의 마감 시각 봉 종가를 비교한다.

    `ends` 는 `bar_ends()`, `sessions` 는 `session_ends()` 결과(믿을 수 있는 세션만),
    `calendar` 는 S&P 500 일봉 날짜 — 직전 세션은 이 달력에서 고른다. 직전 세션이
    `sessions` 에 없거나(30분봉이 빠지거나 잘림), 두 날 중 하나라도 마감 시각에 정확히
    끝나는 봉이 없으면 None — 장중 값을 종가로, 사흘 치 변화를 하루로 싣지 않는다
    (codex 구현 검토·재검토 P1). 비교를 지어내느니 행을 비우고 발행을 멈춘다.
    """
    sessions = sessions or {}
    if anchor not in sessions:
        return None
    days = sorted(calendar) if calendar is not None else sorted(sessions)
    earlier = [d for d in days if d < anchor]
    if not earlier or earlier[-1] not in sessions:
        return None
    prev_date = earlier[-1]
    last = (ends or {}).get(anchor, {}).get(sessions[anchor])
    prev = (ends or {}).get(prev_date, {}).get(sessions[prev_date])
    if last is None or not prev:
        return None

    def hhmm(m):
        return f'{m // 60:02d}:{m % 60:02d}'
    return {'last': last, 'chg': last - prev, 'pct': (last / prev - 1) * 100,
            'date': anchor, 'prev': prev, 'prev_date': prev_date,
            'basis': BASIS, 'contract': contract,
            'cut_et': hhmm(sessions[anchor]), 'prev_cut_et': hhmm(sessions[prev_date])}


def override_history(closes, dates, row):
    """일봉 이력의 오늘·전일 값을 표의 두 값으로 바꾼 사본을 돌려준다.

    가격 위치(백분위)·하루 움직임 크기·스코어카드가 표와 다른 수를 보면 같은 글 안에서
    「1.03% 올랐다」와 「평소 크기」가 서로 다른 가격을 말한다. 오늘 봉이 아직 없으면
    끝에 붙인다. 더 오래된 날은 일봉 그대로다 — 2년 분포에서 하루 이틀의 기준 차이는
    백분위를 거의 바꾸지 않는다.
    """
    if not row or closes is None or dates is None:
        return closes, dates
    c, d = list(closes), list(dates)
    for day, value in ((row.get('prev_date'), row.get('prev')), (row.get('date'), row.get('last'))):
        if day is None or value is None:
            continue
        if day in d:
            c[d.index(day)] = value
        elif not d or day > d[-1]:
            d.append(day)
            c.append(value)
    return c, d


def row_problem(row, report_date):
    """완결성 검사용: 이 행을 오늘 표에 실어도 되는가. 문제가 없으면 None."""
    if row.get('basis') != BASIS:
        return 'basis'
    if report_date and row.get('date') != report_date:
        return f"stale:{row.get('date')}"
    for k in ('last', 'prev', 'pct'):
        v = row.get(k)
        if not isinstance(v, (int, float)) or not math.isfinite(v):
            return 'value'
    if not row.get('prev_date') or not row.get('date') or row['prev_date'] >= row['date']:
        return 'prev_date'
    return None
