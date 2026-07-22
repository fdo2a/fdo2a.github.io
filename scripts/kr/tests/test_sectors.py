import pandas as pd
from kr.sectors import multi_horizon_returns


def test_multi_horizon_returns_basic():
    prices = pd.Series(range(100, 350 + 1), dtype=float)
    idx = pd.date_range("2024-01-01", periods=len(prices), freq="B")
    df = pd.Series(prices.values, index=idx)
    r = multi_horizon_returns(df)
    assert set(r.keys()) == {"1D", "1W", "1M", "6M", "1Y"}
    assert round(r["1D"], 3) == round((350 / 349 - 1) * 100, 3)
    assert round(r["1W"], 3) == round((350 / 345 - 1) * 100, 3)


def test_multi_horizon_handles_short_series():
    idx = pd.date_range("2024-01-01", periods=3, freq="B")
    df = pd.Series([100.0, 101.0, 102.0], index=idx)
    r = multi_horizon_returns(df)
    assert r["1D"] is not None
    assert r["1Y"] is None
