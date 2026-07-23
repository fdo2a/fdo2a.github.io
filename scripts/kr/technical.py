"""기술적 지표 결정론적 계산 — 이평(20/60/120)·볼린저(20±2σ)·일목균형표(9/26/52).

입력은 yfinance OHLC DataFrame(High/Low/Close 컬럼, 날짜 인덱스). 출력은 순수 계산값
dict로, writer는 이 레벨 위에서만 시나리오를 서술한다(수치 창작 금지). 볼린저 표준편차는
차트 관례대로 모표준편차(ddof=0). 일목 선행스팬은 26봉 시프트해 '오늘 시점 구름'을 잡는다.
"""
import math

import pandas as pd


def _r(x, n: int = 2):
    if x is None:
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    if math.isnan(f):
        return None
    return round(f, n)


def _alignment(m20, m60, m120) -> str:
    if None in (m20, m60, m120):
        return "혼조"
    if m20 > m60 > m120:
        return "정배열"
    if m20 < m60 < m120:
        return "역배열"
    return "혼조"


def compute_technical(df: pd.DataFrame) -> dict:
    """OHLC DataFrame → 기술적 지표 스냅샷(마지막 봉 기준)."""
    close = df["Close"].astype(float)
    high = df["High"].astype(float)
    low = df["Low"].astype(float)
    px = float(close.iloc[-1])

    # 이동평균
    ma = {f"ma{w}": _r(close.rolling(w).mean().iloc[-1]) for w in (20, 60, 120)}
    disparity = {
        f"vs_ma{w}": (_r((px / ma[f"ma{w}"] - 1) * 100, 2) if ma[f"ma{w}"] else None)
        for w in (20, 60, 120)
    }

    # 볼린저 20±2σ (모표준편차)
    mid = close.rolling(20).mean().iloc[-1]
    std = close.rolling(20).std(ddof=0).iloc[-1]
    upper = mid + 2 * std
    lower = mid - 2 * std
    denom = upper - lower
    pct_b = ((px - lower) / denom) if denom else 0.5
    bandwidth = (denom / mid) if mid else 0.0
    bollinger = {"upper": _r(upper), "mid": _r(mid), "lower": _r(lower),
                 "pct_b": _r(pct_b, 3), "bandwidth": _r(bandwidth, 4)}

    # 일목균형표
    tenkan = (high.rolling(9).max() + low.rolling(9).min()) / 2
    kijun = (high.rolling(26).max() + low.rolling(26).min()) / 2
    span_a = ((tenkan + kijun) / 2).shift(26)          # 선행스팬1 → 오늘 시점 값
    span_b = ((high.rolling(52).max() + low.rolling(52).min()) / 2).shift(26)
    sa = span_a.iloc[-1]
    sb = span_b.iloc[-1]
    cloud_top = max(sa, sb) if not (math.isnan(sa) or math.isnan(sb)) else float("nan")
    cloud_bottom = min(sa, sb) if not (math.isnan(sa) or math.isnan(sb)) else float("nan")
    if math.isnan(cloud_top):
        price_vs_cloud = None
    elif px > cloud_top:
        price_vs_cloud = "above"
    elif px < cloud_bottom:
        price_vs_cloud = "below"
    else:
        price_vs_cloud = "inside"
    ichimoku = {
        "tenkan": _r(tenkan.iloc[-1]), "kijun": _r(kijun.iloc[-1]),
        "senkou_a": _r(sa), "senkou_b": _r(sb),
        "cloud_top": _r(cloud_top), "cloud_bottom": _r(cloud_bottom),
        "price_vs_cloud": price_vs_cloud,
    }

    # 후행스팬: 오늘 종가 vs 26봉 전 종가
    chikou_above = None
    if len(close) > 26:
        chikou_above = bool(px > float(close.iloc[-27]))

    # 스윙 고·저 (목표/손절 레퍼런스)
    swing = {
        "high_20": _r(high.tail(20).max()), "low_20": _r(low.tail(20).min()),
        "high_60": _r(high.tail(60).max()), "low_60": _r(low.tail(60).min()),
    }

    return {
        "as_of": str(df.index[-1].date()) if hasattr(df.index[-1], "date") else None,
        "close": _r(px),
        "ma": ma, "ma_alignment": _alignment(ma["ma20"], ma["ma60"], ma["ma120"]),
        "disparity": disparity,
        "bollinger": bollinger,
        "ichimoku": ichimoku,
        "chikou_above_price_26ago": chikou_above,
        "swing": swing,
    }
