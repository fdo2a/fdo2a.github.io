import os
from kr.sources import parse_top_value, downsample_30min

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "top_value.html")


def test_downsample_30min_keeps_anchors_and_close():
    bars = [
        {"localDateTime": "20260722090000", "currentPrice": 7064.27},
        {"localDateTime": "20260722091500", "currentPrice": 7100.0},   # dropped (:15)
        {"localDateTime": "20260722093000", "currentPrice": 7135.77},
        {"localDateTime": "20260722151800", "currentPrice": 6793.11},  # last (close guaranteed)
    ]
    pts = downsample_30min(bars)
    times = [p["t"] for p in pts]
    assert "09:00" in times and "09:30" in times
    assert "09:15" not in times
    assert pts[-1] == {"t": "15:18", "close": 6793.11}  # 종가 보장


def test_parse_top_value():
    with open(FIX, encoding="utf-8") as f:
        rows = parse_top_value(f.read())
    assert rows[0]["name"] == "KODEX 200선물인버스2X"
    assert rows[0]["value"] == 900
    assert rows[0]["volume"] == 100000
    assert rows[1]["name"] == "모나리자"
    assert len(rows) == 2
