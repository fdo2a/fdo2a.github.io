import pandas as pd
import pytest

from kr.technical import compute_technical


def _linear_df(n=200):
    idx = pd.bdate_range("2020-01-01", periods=n)
    close = pd.Series([100.0 + i for i in range(n)], index=idx)
    return pd.DataFrame({"Close": close, "High": close + 1, "Low": close - 1})


def _flat_df(n=200, v=100.0):
    idx = pd.bdate_range("2020-01-01", periods=n)
    s = pd.Series([v] * n, index=idx)
    return pd.DataFrame({"Close": s, "High": s, "Low": s})


def test_moving_averages_and_alignment():
    t = compute_technical(_linear_df())
    assert t["close"] == 299.0
    assert t["ma"]["ma20"] == 289.5
    assert t["ma"]["ma60"] == 269.5
    assert t["ma"]["ma120"] == 239.5
    assert t["ma_alignment"] == "정배열"
    assert t["disparity"]["vs_ma20"] == 3.28


def test_bollinger_on_linear_series():
    b = compute_technical(_linear_df())["bollinger"]
    assert b["mid"] == 289.5
    assert b["upper"] == 301.03
    assert b["lower"] == 277.97
    assert b["pct_b"] == 0.912
    assert b["bandwidth"] == 0.0797


def test_ichimoku_lines_on_linear_series():
    ic = compute_technical(_linear_df())["ichimoku"]
    assert ic["tenkan"] == 295.0
    assert ic["kijun"] == 286.5
    assert ic["price_vs_cloud"] == "above"  # 상승추세: 가격이 26봉 지연 구름 위


def test_swing_and_chikou_on_linear_series():
    t = compute_technical(_linear_df())
    assert t["swing"]["high_20"] == 300.0
    assert t["swing"]["low_20"] == 279.0
    assert t["swing"]["high_60"] == 300.0
    assert t["swing"]["low_60"] == 239.0
    assert t["chikou_above_price_26ago"] is True


def test_flat_series_collapses_bands_and_inside_cloud():
    t = compute_technical(_flat_df())
    assert t["ma_alignment"] == "혼조"
    b = t["bollinger"]
    assert b["upper"] == b["lower"] == b["mid"] == 100.0
    assert b["bandwidth"] == 0.0
    assert b["pct_b"] == 0.5
    assert t["ichimoku"]["price_vs_cloud"] == "inside"
    assert t["chikou_above_price_26ago"] is False


def test_as_of_reflects_last_bar():
    t = compute_technical(_linear_df(n=30))
    # 30 영업일: bdate_range 2020-01-01 부터 30번째 영업일
    assert t["as_of"] == "2020-02-11"
