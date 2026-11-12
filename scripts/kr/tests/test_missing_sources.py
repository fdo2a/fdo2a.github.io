"""페처가 못 읽은 값을 0 으로 채우지 않는다 — 지수·수급·거래대금(2026-11-12).

spec: docs/superpowers/specs/2026-11-12-kr-missing-vs-zero.md
"""
import pytest

from kr import sources
from kr.flows import classify_row, parse_flows_row


# ── 지수 ────────────────────────────────────────────────────────────────

def _basic(monkeypatch, **kw):
    body = {"closePrice": "5,342.73", "fluctuationsRatio": "-0.61",
            "compareToPreviousClosePrice": "-32.63", "localTradedAt": "2026-11-12T16:15:00+09:00"}
    body.update(kw)
    body = {k: v for k, v in body.items() if v is not ...}
    monkeypatch.setattr(sources, "fetch_json", lambda url, timeout=12: body)


def test_fetch_index_carries_prev_diff(monkeypatch):
    _basic(monkeypatch)
    assert sources.fetch_index("KOSPI") == {"close": 5342.73, "change_pct": -0.61,
                                            "trade_date": "2026-11-12", "prev_diff": -32.63}


@pytest.mark.parametrize("raw", [..., "-", None, "", "abc"])
def test_fetch_index_unreadable_ratio_is_none_not_zero(monkeypatch, raw):
    _basic(monkeypatch, fluctuationsRatio=raw)
    row = sources.fetch_index("KOSPI")
    assert row["change_pct"] is None
    assert row["close"] == 5342.73


def test_fetch_index_zero_ratio_is_zero(monkeypatch):
    _basic(monkeypatch, fluctuationsRatio="0.00")
    assert sources.fetch_index("KOSPI")["change_pct"] == 0.0


@pytest.mark.parametrize("raw", ["nan", "0", ..., "-", "inf", "-5"])
def test_fetch_index_bad_close_raises(monkeypatch, raw):
    _basic(monkeypatch, closePrice=raw)
    with pytest.raises(RuntimeError, match="지수"):
        sources.fetch_index("KOSPI")


def test_fetch_index_missing_prev_diff_is_none(monkeypatch):
    _basic(monkeypatch, compareToPreviousClosePrice=...)
    assert sources.fetch_index("KOSPI")["prev_diff"] is None


def test_fetch_index_ohlc_reads_flow_bizdate(monkeypatch):
    monkeypatch.setattr(sources, "fetch_json", lambda url, timeout=12: {
        "totalInfos": [{"code": "lastClosePrice", "value": "5,375.36"},
                       {"code": "highPrice", "value": "5,458.84"},
                       {"code": "lowPrice", "value": "5,293.05"},
                       {"code": "openPrice", "value": "nan"}],
        "dealTrendInfo": {"bizdate": "20261112"}})
    o = sources.fetch_index_ohlc("KOSPI")
    assert o == {"open": None, "high": 5458.84, "low": 5293.05, "prevClose": 5375.36,
                 "flow_bizdate": "20261112"}


def test_fetch_index_ohlc_without_deal_trend(monkeypatch):
    monkeypatch.setattr(sources, "fetch_json", lambda url, timeout=12: {"totalInfos": []})
    assert sources.fetch_index_ohlc("KOSPI")["flow_bizdate"] is None


# ── 수급 행 분류 ─────────────────────────────────────────────────────────

def _p(biz, ind, fr, ins):
    out = {"bizdate": biz}
    for k, v in (("personalValue", ind), ("foreignValue", fr), ("institutionalValue", ins)):
        if v is not ...:
            out[k] = v
    return out


def test_classify_one_side_missing_is_partial():
    st, row, fields = classify_row(_p("20261112", "-2,347", ..., "-6,704"))
    assert st == "partial" and row is None and fields == ["foreign"]
    st, _, fields = classify_row(_p("20261112", "-", "+3,812", ""))
    assert st == "partial" and fields == ["individual", "institution"]


def test_classify_one_side_zero_is_ok():
    st, row, fields = classify_row(_p("20261112", "-2,347", "0", "-6,704"))
    assert st == "ok" and fields == []
    assert row == {"date": "2026-11-12", "individual": -2347, "foreign": 0, "institution": -6704}


def test_classify_all_zero_is_zero():
    assert classify_row(_p("20261114", "0", "0", "0"))[0] == "zero"


def test_classify_all_unreadable():
    assert classify_row(_p("20261112", None, "-", "abc"))[0] == "unreadable"
    assert classify_row({})[0] == "unreadable"
    assert classify_row(None)[0] == "unreadable"


def test_classify_bad_or_other_bizdate_is_unreadable():
    assert classify_row(_p("2026111", "1", "2", "3"))[0] == "unreadable"
    assert classify_row(_p("", "1", "2", "3"))[0] == "unreadable"
    assert classify_row(_p("20261111", "1", "2", "3"), requested="20261112")[0] == "unreadable"
    assert classify_row(_p("20261112", "1", "2", "3"), requested="20261112")[0] == "ok"


def test_parse_flows_row_return_shape_unchanged():
    assert parse_flows_row(_p("20261112", "-2,347", "+3,812", "-6,704")) == {
        "date": "2026-11-12", "individual": -2347, "foreign": 3812, "institution": -6704}
    assert parse_flows_row(_p("20261112", "-2,347", ..., "-6,704")) is None
    assert parse_flows_row(_p("20261114", "0", "0", "0")) is None


# ── 수급 페처 ───────────────────────────────────────────────────────────

OK = ("-1", "+2", "3")
ZERO = ("0", "0", "0")
PART = ("-1", "-", "3")
UNREAD = (None, None, None)


def _walk(monkeypatch, plan, fail_on=None):
    """plan: {YYYYMMDD: 세 값}. 없는 날은 OK. fail_on 날짜는 요청 예외."""
    seen = []

    def fake(url, timeout=12):
        biz = url.split("bizdate=")[1]
        seen.append(biz)
        if biz == fail_on:
            raise RuntimeError("HTTP 502")
        vals = plan.get(biz, OK)
        return _p(biz, *vals)
    monkeypatch.setattr(sources, "fetch_json", fake)
    return seen


def test_walk_today_zero_prev_ok_keeps_prior_day_path(monkeypatch):
    _walk(monkeypatch, {"20261112": ZERO})
    w = sources.walk_market_flows("KOSPI", "20261112", days=2)
    assert w["blocked"] is None
    assert [r["date"] for r in w["rows"]] == ["2026-11-11", "2026-11-10"]
    assert w["diagnostics"] == []


def test_walk_today_ok(monkeypatch):
    _walk(monkeypatch, {})
    w = sources.walk_market_flows("KOSPI", "20261112", days=2)
    assert w["blocked"] is None and w["rows"][0]["date"] == "2026-11-12"


@pytest.mark.parametrize("today", [UNREAD, PART])
def test_walk_today_unreadable_or_partial_blocks(monkeypatch, today):
    _walk(monkeypatch, {"20261112": today})
    w = sources.walk_market_flows("KOSPI", "20261112", days=2)
    assert w["blocked"] == "unreadable_before_latest"
    assert w["diagnostics"][0]["date"] == "2026-11-12"
    assert w["diagnostics"][0]["status"] == ("unreadable" if today is UNREAD else "partial")


def test_walk_today_zero_prev_unreadable_blocks(monkeypatch):
    # 2회차 #7 재현 — 당일 0, 전일 못 읽음, 그 앞 ok → 그 ok 를 「전 거래일」이라 부를 수 없다
    _walk(monkeypatch, {"20261112": ZERO, "20261111": UNREAD})
    w = sources.walk_market_flows("KOSPI", "20261112", days=2)
    assert w["blocked"] == "unreadable_before_latest"


def test_walk_older_partial_is_dropped_and_recorded(monkeypatch):
    _walk(monkeypatch, {"20261111": PART, "20261110": PART})
    w = sources.walk_market_flows("KOSPI", "20261112", days=3)
    assert w["blocked"] is None
    assert [r["date"] for r in w["rows"]] == ["2026-11-12", "2026-11-09", "2026-11-08"]
    assert [(d["date"], d["status"], d["fields"]) for d in w["diagnostics"]] == [
        ("2026-11-11", "partial", ["foreign"]), ("2026-11-10", "partial", ["foreign"])]


def test_walk_request_failure_raises_with_diagnostics(monkeypatch):
    _walk(monkeypatch, {"20261111": PART}, fail_on="20261110")
    with pytest.raises(sources.FlowsFetchError, match="수급") as e:
        sources.walk_market_flows("KOSPI", "20261112", days=5)
    assert isinstance(e.value, RuntimeError)
    assert [d["date"] for d in e.value.diagnostics] == ["2026-11-11"]


def test_walk_no_ok_rows_raises(monkeypatch):
    monkeypatch.setattr(sources, "fetch_json", lambda url, timeout=12: _p(url.split("bizdate=")[1], *ZERO))
    with pytest.raises(sources.FlowsFetchError, match="수급"):
        sources.walk_market_flows("KOSPI", "20261112", days=1, max_back=3)


def test_walk_order_matches_old_fetcher(monkeypatch):
    seen = _walk(monkeypatch, {"20261108": ZERO, "20261107": ZERO})
    sources.walk_market_flows("KOSPI", "20261110", days=2)
    assert seen == ["20261110", "20261109"]


def test_fetch_market_flows_still_returns_list(monkeypatch):
    _walk(monkeypatch, {})
    rows = sources.fetch_market_flows("KOSPI", "20261112", days=2)
    assert isinstance(rows, list) and len(rows) == 2


# ── 거래대금 ─────────────────────────────────────────────────────────────

def _stock(i, value, sosok="0", volume="1,000", ratio="1.0", cap="100"):
    return {"itemCode": f"{i:06d}", "stockName": f"S{i}", "sosok": sosok,
            "accumulatedTradingValue": value, "accumulatedTradingVolume": volume,
            "fluctuationsRatio": ratio, "marketValueRaw": cap}


def _pages(monkeypatch, stocks):
    pages = [stocks[i:i + 100] for i in range(0, len(stocks), 100)] or [[]]

    def fake(url, timeout=12):
        page = int(url.split("page=")[1].split("&")[0])
        return {"stocks": pages[page - 1] if page <= len(pages) else []}
    monkeypatch.setattr(sources, "fetch_json", fake)


def _market(n, dash_at=(), bad_at=()):
    out = []
    for i in range(n):
        v = "-" if i in dash_at else ("x1" if i in bad_at else f"{1000 + i}")
        out.append(_stock(i, v))
    return out


def test_top_value_drops_dash_rows_without_raising(monkeypatch):
    _pages(monkeypatch, _market(300, dash_at=set(range(200, 230))))
    rows, st = sources.fetch_top_value_stats("0")
    assert len(rows) == 270
    assert st == {"rows": 300, "dash": 30, "bad": 0, "dash_top100": 0}
    assert all(isinstance(r["value"], int) for r in rows)


def test_top_value_bad_boundary(monkeypatch):
    # 300행 — 1% = 3 이라 max(5, 3) = 5. 5건 통과, 6건 예외(상위 100 밖에 둔다)
    _pages(monkeypatch, _market(300, bad_at=set(range(200, 205))))
    assert sources.fetch_top_value_stats("0")[1]["bad"] == 5
    _pages(monkeypatch, _market(300, bad_at=set(range(200, 206))))
    with pytest.raises(RuntimeError, match="거래대금"):
        sources.fetch_top_value_stats("0")


def test_top_value_bad_uses_one_percent_when_larger(monkeypatch):
    # 1,000행 — 1% = 10. 10건 통과, 11건 예외
    _pages(monkeypatch, _market(1000, bad_at=set(range(500, 510))))
    assert sources.fetch_top_value_stats("0")[1]["bad"] == 10
    _pages(monkeypatch, _market(1000, bad_at=set(range(500, 511))))
    with pytest.raises(RuntimeError):
        sources.fetch_top_value_stats("0")


def test_top_value_dash_ratio_boundary(monkeypatch):
    # 1,000행 중 dash 300(30%) 통과, 301 예외 — 상위 100 밖
    _pages(monkeypatch, _market(1000, dash_at=set(range(600, 900))))
    assert sources.fetch_top_value_stats("0")[1]["dash"] == 300
    _pages(monkeypatch, _market(1000, dash_at=set(range(599, 900))))
    with pytest.raises(RuntimeError, match="거래대금"):
        sources.fetch_top_value_stats("0")


def test_top_value_top100_watch_boundary(monkeypatch):
    _pages(monkeypatch, _market(1000, dash_at={1, 2, 3, 4, 5}))
    assert sources.fetch_top_value_stats("0")[1]["dash_top100"] == 5
    _pages(monkeypatch, _market(1000, dash_at={1, 2, 3, 4, 5, 6}))
    with pytest.raises(RuntimeError, match="거래대금"):
        sources.fetch_top_value_stats("0")


def test_top_value_top100_counts_bad_too(monkeypatch):
    _pages(monkeypatch, _market(1000, dash_at={1, 2, 3}, bad_at={7, 8, 9}))
    with pytest.raises(RuntimeError):
        sources.fetch_top_value_stats("0")


def test_top_value_top200_all_dash_raises(monkeypatch):
    # 2회차 #8 재현 — 전체 1,000행 중 20% 라 (b) 는 통과하지만 상위 감시(c)가 잡는다
    _pages(monkeypatch, _market(1000, dash_at=set(range(200))))
    with pytest.raises(RuntimeError, match="거래대금"):
        sources.fetch_top_value_stats("0")


def test_top_value_top100_is_per_market(monkeypatch):
    # 코스닥 행의 dash 는 코스피 감시에 들어가지 않는다
    kosdaq = [_stock(5000 + i, "-", sosok="1") for i in range(50)]
    _pages(monkeypatch, kosdaq + _market(400))
    rows, st = sources.fetch_top_value_stats("0")
    assert st["dash_top100"] == 0 and st["rows"] == 400


def test_top_value_volume_and_ratio_may_be_none(monkeypatch):
    _pages(monkeypatch, [_stock(1, "500", volume="-", ratio="", cap="-")])
    rows, _ = sources.fetch_top_value_stats("0")
    assert rows[0]["volume"] is None and rows[0]["change_pct"] is None and rows[0]["cap"] is None


def test_fetch_top_value_wrapper_returns_list(monkeypatch):
    _pages(monkeypatch, _market(20))
    rows = sources.fetch_top_value("0")
    assert isinstance(rows, list) and rows[0]["value"] == 1019


def test_top_value_no_market_rows_raises(monkeypatch):
    _pages(monkeypatch, [_stock(1, "5", sosok="1")])
    with pytest.raises(RuntimeError, match="거래대금"):
        sources.fetch_top_value_stats("0")
