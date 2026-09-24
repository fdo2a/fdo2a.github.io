import pytest

from kr import sources
from kr.sources import downsample_30min


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


def _stock(code, name, sosok, value, volume, ratio):
    return {"itemCode": code, "stockName": name, "sosok": sosok,
            "accumulatedTradingValue": value, "accumulatedTradingVolume": volume,
            "fluctuationsRatio": ratio}


def _fake_pages(monkeypatch, pages):
    """marketValue 응답을 페이지 번호로 흉내낸다. 범위를 넘으면 빈 목록."""
    def fake(url, timeout=12):
        page = int(url.split("page=")[1].split("&")[0])
        return {"stocks": pages[page - 1] if page <= len(pages) else []}
    monkeypatch.setattr(sources, "fetch_json", fake)


def test_fetch_top_value_sorts_by_value_and_filters_market(monkeypatch):
    _fake_pages(monkeypatch, [[
        _stock("1", "삼성전자", "0", "6,043,124", "22,223,579", "5.36"),
        _stock("2", "알테오젠", "1", "9,999,999", "1", "1.0"),   # 코스닥 — 제외
        _stock("3", "LG에너지솔루션", "0", "812,876", "1,000", "-2.34"),
    ]])
    rows = sources.fetch_top_value("0")
    assert [r["name"] for r in rows] == ["삼성전자", "LG에너지솔루션"]
    assert rows[0]["value"] == 6043124 and rows[0]["volume"] == 22223579
    assert rows[1]["change_pct"] == -2.34
    # 종목코드를 들고 나가야 KRX 종가(yfinance `<code>.KS`)로 등락률을 다시 잴 수 있다
    assert rows[0]["code"] == "1"


def test_fetch_top_value_pages_until_no_new_codes(monkeypatch):
    page = [_stock("1", "삼성전자", "0", "100", "1", "0.1")]
    _fake_pages(monkeypatch, [page, page, page])   # 2쪽부터 새 종목 없음
    rows = sources.fetch_top_value("0")
    assert len(rows) == 1


def test_fetch_top_value_raises_when_empty(monkeypatch):
    """SPA 껍데기가 조용히 [] 를 내던 실패 — 이제 예외로 올린다."""
    _fake_pages(monkeypatch, [[]])
    with pytest.raises(RuntimeError, match="거래대금"):
        sources.fetch_top_value("0")


def test_fetch_market_flows_walks_back_over_holidays(monkeypatch):
    seen = []

    def fake(url, timeout=12):
        bizdate = url.split("bizdate=")[1]
        seen.append(bizdate)
        if bizdate in ("20260920", "20260919"):       # 주말 — 전부 0
            return {"bizdate": bizdate, "personalValue": "0",
                    "foreignValue": "0", "institutionalValue": "0"}
        return {"bizdate": bizdate, "personalValue": "-1",
                "foreignValue": "+2", "institutionalValue": "3"}
    monkeypatch.setattr(sources, "fetch_json", fake)
    rows = sources.fetch_market_flows("KOSPI", "20260921", days=2)
    assert [r["date"] for r in rows] == ["2026-09-21", "2026-09-18"]
    assert seen == ["20260921", "20260920", "20260919", "20260918"]


def test_fetch_market_flows_raises_when_all_blank(monkeypatch):
    monkeypatch.setattr(sources, "fetch_json", lambda url, timeout=12: {
        "bizdate": "20260921", "personalValue": "0",
        "foreignValue": "0", "institutionalValue": "0"})
    with pytest.raises(RuntimeError, match="수급"):
        sources.fetch_market_flows("KOSPI", "20260921", days=1, max_back=3)


def test_retired_sources_raise_without_network():
    for call in (lambda: sources.fetch_intraday_flows("01", "20260921"),
                 lambda: sources.fetch_program_flows("01", "20260921"),
                 lambda: sources.fetch_themes()):
        with pytest.raises(RuntimeError, match="폐지"):
            call()


def test_fetch_index_raises_on_blank_close(monkeypatch):
    """지수도 빈 응답을 0 으로 통과시키지 않는다."""
    monkeypatch.setattr(sources, "fetch_json",
                        lambda url, timeout=12: {"closePrice": "0", "fluctuationsRatio": "0"})
    with pytest.raises(RuntimeError, match="지수"):
        sources.fetch_index("KOSPI")


def test_fetch_index_reads_close_and_ratio(monkeypatch):
    monkeypatch.setattr(sources, "fetch_json",
                        lambda url, timeout=12: {"closePrice": "7,007.72",
                                                 "fluctuationsRatio": "1.65"})
    assert sources.fetch_index("KOSPI") == {"close": 7007.72, "change_pct": 1.65}


def test_fetch_industry_raises_when_empty(monkeypatch):
    monkeypatch.setattr(sources, "fetch_json", lambda url, timeout=12: {"groups": []})
    with pytest.raises(RuntimeError, match="업종"):
        sources.fetch_industry()
