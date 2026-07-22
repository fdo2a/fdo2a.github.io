import os
from kr.sources import parse_top_value

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "top_value.html")


def test_parse_top_value():
    with open(FIX, encoding="utf-8") as f:
        rows = parse_top_value(f.read())
    assert rows[0]["name"] == "KODEX 200선물인버스2X"
    assert rows[0]["value"] == 900
    assert rows[0]["volume"] == 100000
    assert rows[1]["name"] == "모나리자"
    assert len(rows) == 2
