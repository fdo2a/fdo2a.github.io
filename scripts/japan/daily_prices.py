"""일본 일간 — 종가·전일 분모·분할 검증·엔 16:30 컷 (2026-10-27).

실측(10/27 00:04 KST): yfinance `^N225` 일봉은 마감 8.5시간 뒤에도 당일 행이 없고 개별주
일봉은 Close 가 NaN 이다. `fast_info.lastPrice` 는 일경 공식과 맞지만 **관측 시각이 없고**
(`regularMarketTime` 키가 없다) 오늘 봉이 없으면 전날 값을 돌려준다 — 그래서 닛케이는 공식
CSV 의 세션 행, ETF·개별주는 5분봉 마지막 봉의 날짜로 세션을 확인한다(codex 설계 검토 #1).
`previousClose` 는 틀린다 — 분모는 정확히 직전 세션 날짜의 값만 쓴다(#2).

Pure — 네트워크 없음.
"""
import csv
import io
import math
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

TOKYO = ZoneInfo('Asia/Tokyo')
TOL_PCT = 0.01
JUMP_PCT = 15.0
FX_BASIS = 'bar_end_1630_jst'


def _finite(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def nikkei_official(csv_text, session):
    """일경 공식 CSV(`nikkei_stock_average_daily_en.csv`)의 세션 행 종가. 파일은 커밋하지 않는다."""
    if isinstance(csv_text, bytes):
        csv_text = csv_text.decode('cp932', 'replace')
    want = session.replace('-', '/')
    for rec in csv.reader(io.StringIO(csv_text)):
        if len(rec) >= 2 and rec[0].strip() == want:
            try:
                v = float(rec[1])
            except ValueError:
                return None
            return v if _finite(v) and v > 0 else None
    return None


def nikkei_close(official, fast_last, tol_pct=TOL_PCT):
    if not _finite(official):
        return {'value': None, 'ok': False, 'why': '일경 공식 CSV 에 세션 행 없음'}
    if not _finite(fast_last):
        return {'value': official, 'ok': False, 'why': 'yfinance 가격 없음 — 대조 불가'}
    gap = abs(fast_last - official) / official * 100
    if gap > tol_pct:
        return {'value': official, 'ok': False,
                'why': f'공식 {official} vs yfinance {fast_last} ({gap:.3f}%)'}
    return {'value': official, 'ok': True, 'why': None}


def same_session_price(fast_last, last_bar_date, session):
    if last_bar_date != session or not _finite(fast_last) or fast_last <= 0:
        return None
    return float(fast_last)


def denominator(history, prev_session):
    """[[날짜, 종가]] 에서 정확히 `prev_session` 행만. 「마지막 유효 행」 으로 물러서지 않는다."""
    for d, v in history or []:
        if d == prev_session and _finite(v) and v > 0:
            return {'date': d, 'value': float(v), 'source': 'history'}
    return None


def change(today, denom):
    if not denom or not _finite(today) or not _finite(denom.get('value')) or denom['value'] <= 0:
        return None
    return round((today / denom['value'] - 1) * 100, 2)


def verify_jump(today, denom, splits, session, jump_pct=JUMP_PCT):
    """±15% 는 재검증 트리거다(#14). 분할을 반영하고, 10의 거듭제곱 차이만 단위 오류로 본다."""
    base = denom['value']
    for d, ratio in splits or []:
        if denom['date'] < d <= session and _finite(ratio) and ratio > 0:
            base = base / ratio
    chg = (today / base - 1) * 100
    if abs(chg) <= jump_pct:
        return {'ok': True, 'adjusted_denom': round(base, 6), 'why': None}
    k = round(math.log10(today / base))
    if k != 0 and abs(today / base / 10 ** k - 1) < 0.05:
        return {'ok': False, 'adjusted_denom': round(base, 6),
                'why': f'가격이 분모의 10^{k} 배 — 단위·분할 기준 불일치'}
    return {'ok': True, 'adjusted_denom': round(base, 6), 'why': f'실제 큰 움직임 {chg:+.2f}%'}


def _to_tokyo(iso):
    ts = datetime.fromisoformat(iso)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=TOKYO)
    return ts.astimezone(TOKYO)


def fx_cut(bars, session, cut='16:30', bar_minutes=5):
    """[(봉 시작 ISO, 종가)] 에서 세션 날 `cut` JST 에 끝난 봉. 없으면 None — 다른 봉으로 물러서지 않는다(#3)."""
    hh, mm = map(int, cut.split(':'))
    end = datetime.combine(date.fromisoformat(session), datetime.min.time()).replace(
        hour=hh, minute=mm, tzinfo=TOKYO)
    start = end - timedelta(minutes=bar_minutes)
    for iso, v in bars or []:
        if _to_tokyo(iso) == start and _finite(v) and v > 0:
            return {'value': round(float(v), 4), 'bar_start': start.isoformat(),
                    'bar_end': end.isoformat(), 'tz': 'Asia/Tokyo', 'basis': FX_BASIS}
    return None


