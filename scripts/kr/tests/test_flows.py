from kr.flows import build_market_flows, flows_freshness, parse_flows_row


def _payload(bizdate, personal, foreign, inst):
    return {"bizdate": bizdate, "personalValue": personal,
            "foreignValue": foreign, "institutionalValue": inst}


def test_parse_flows_row_reads_signed_thousands():
    r = parse_flows_row(_payload("20260916", "-12,061", "-16,726", "+12,251"))
    assert r == {"date": "2026-09-16", "individual": -12061,
                 "foreign": -16726, "institution": 12251}


def test_parse_flows_row_drops_non_trading_day():
    # 휴장일도 200 을 주되 세 주체가 전부 0 이다 — 거래일로 세면 안 된다.
    assert parse_flows_row(_payload("20260920", "0", "0", "0")) is None


def test_parse_flows_row_drops_malformed_bizdate():
    assert parse_flows_row(_payload("", "-1", "2", "3")) is None
    assert parse_flows_row({}) is None
    assert parse_flows_row(None) is None


def test_build_market_flows_sorts_latest_first():
    d = build_market_flows([
        _p2("2026-09-16", -12061, -16726, 12251),
        _p2("2026-09-18", -36359, 4486, 15322),
        _p2("2026-09-17", 3020, -22546, 2480),
    ])
    assert d["latest_date"] == "2026-09-18"
    assert [r["date"] for r in d["rows"]] == ["2026-09-18", "2026-09-17", "2026-09-16"]
    assert d["rows"][0]["foreign"] == 4486


def test_build_market_flows_empty():
    d = build_market_flows([])
    assert d == {"rows": [], "latest_date": None}


def _p2(date, individual, foreign, institution):
    return {"date": date, "individual": individual,
            "foreign": foreign, "institution": institution}


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
