"""US 움직인 종목 모집단 — S&P 500 중 달러 거래대금 상위 60 (2026-09-24)."""
from us import movers_data as D

TABLE = '''<table id="constituents"><thead><tr><th>Symbol</th><th>Security</th><th>GICS Sector</th>
<th>GICS Sub-Industry</th></tr></thead><tbody>
<tr><td>MU</td><td>Micron Technology</td><td>Information Technology</td><td>Semiconductors</td></tr>
<tr><td>BRK.B</td><td>Berkshire Hathaway</td><td>Financials</td><td>Multi-Sector Holdings</td></tr>
</tbody></table>'''


def test_constituents_parse_and_translate_symbols_for_yahoo():
    rows = D.parse_constituents(TABLE)
    assert rows == [
        {"symbol": "MU", "yf": "MU", "name": "Micron Technology", "sub_industry": "Semiconductors"},
        {"symbol": "BRK.B", "yf": "BRK-B", "name": "Berkshire Hathaway",
         "sub_industry": "Multi-Sector Holdings"}]


def test_universe_keeps_top_dollar_volume_on_the_report_date():
    series = {
        "MU": [("2026-09-22", 100.0, 10), ("2026-09-23", 97.78, 50)],
        "NVDA": [("2026-09-22", 200.0, 100), ("2026-09-23", 201.0, 100)],
        "OLD": [("2026-09-21", 10.0, 1), ("2026-09-22", 11.0, 1)],     # 오늘 봉 없음
        "ONE": [("2026-09-23", 5.0, 1)],                                 # 전일 종가 없음
    }
    names = {"MU": "Micron Technology (MU)", "NVDA": "NVIDIA (NVDA)",
             "OLD": "Old (OLD)", "ONE": "One (ONE)"}
    out = D.universe(series, names, "2026-09-23", top_n=1)
    assert out == [{"name": "NVIDIA (NVDA)", "yf": "NVDA", "change_pct": 0.5,
                    "close": 201.0, "value": 20100.0}]
    two = D.universe(series, names, "2026-09-23", top_n=5)
    assert [r["yf"] for r in two] == ["NVDA", "MU"]
    assert two[1]["change_pct"] == -2.22


def test_universe_uses_the_report_date_bar_even_when_a_later_bar_exists():
    """수집이 늦게 돌거나 재실행되면 다음 날 장중 봉이 끝에 붙는다(9/24 실측)."""
    series = {"MU": [("2026-09-22", 100.0, 10), ("2026-09-23", 97.78, 50),
                     ("2026-09-24", 96.0, 5)]}
    out = D.universe(series, {"MU": "Micron Technology (MU)"}, "2026-09-23")
    assert out[0]["change_pct"] == -2.22 and out[0]["close"] == 97.78

