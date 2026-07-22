import os
from kr.flows import parse_market_flows, flows_freshness

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "flows_kospi.html")


def _html():
    with open(FIX, encoding="utf-8") as f:
        return f.read()


def test_parse_market_flows_reads_rows_and_latest():
    d = parse_market_flows(_html())
    assert d["latest_date"] == "2024-06-07"
    top = d["rows"][0]
    assert top["individual"] == -4715
    assert top["foreign"] == 2873
    assert top["institution"] == 1582
    assert len(d["rows"]) == 3


def test_freshness_same_day_confirmed():
    r = flows_freshness("2024-06-07", "2024-06-07", provisional=False)
    assert r["label"] == "당일 확정" and r["stale"] is False


def test_freshness_same_day_provisional():
    r = flows_freshness("2024-06-07", "2024-06-07", provisional=True)
    assert r["label"] == "당일 잠정치" and r["flows_provisional"] is True


def test_freshness_stale_uses_prior_day_label():
    r = flows_freshness("2024-06-05", "2024-06-07")
    assert r["stale"] is True
    assert r["label"] == "전 거래일 기준(2024-06-05)"


def test_freshness_missing():
    r = flows_freshness(None, "2024-06-07")
    assert r["stale"] is True and r["flows_date"] is None
