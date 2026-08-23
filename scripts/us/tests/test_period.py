import pytest

from us.period import BENCHMARK, build, month_key, pct_change, slice_series, week_key, TENORS


def test_week_key_is_iso_and_zero_padded():
    assert week_key("2026-08-21") == "2026-W34"
    assert week_key("2026-01-02") == "2026-W01"


def test_week_key_uses_iso_year_not_calendar_year():
    # 2027-01-01 은 금요일 → ISO 로는 2026년 53주차
    assert week_key("2027-01-01") == "2026-W53"


def test_month_key():
    assert month_key("2026-08-21") == "2026-08"


SPX = [("2026-08-14", 100.0), ("2026-08-17", 101.0), ("2026-08-18", 102.0),
       ("2026-08-19", 103.0), ("2026-08-20", 104.0), ("2026-08-21", 110.0)]


def test_slice_series_is_inclusive_both_ends():
    got = slice_series(SPX, "2026-08-17", "2026-08-19")
    assert [d for d, _ in got] == ["2026-08-17", "2026-08-18", "2026-08-19"]


def test_pct_change_measures_from_the_close_before_the_window():
    # 주간 수익률은 직전 주 마지막 종가 대비다 — 창 안 첫 종가 대비가 아니다
    assert pct_change(SPX, "2026-08-17", "2026-08-21") == pytest.approx(10.0)


def test_pct_change_returns_none_without_a_prior_close():
    assert pct_change(SPX, "2026-08-14", "2026-08-21") is None


def test_pct_change_returns_none_when_window_is_empty():
    assert pct_change(SPX, "2026-09-01", "2026-09-05") is None


def _closes():
    def s(v0, v1):
        return [("2026-08-14", v0), ("2026-08-17", v0), ("2026-08-21", v1)]
    return {
        "indices": {"S&P 500": s(100.0, 110.0), "Nasdaq": s(100.0, 105.0)},
        "sectors": {"Technology": s(100.0, 120.0), "Energy": s(100.0, 90.0)},
        "fx": {"DXY": s(100.0, 99.0)},
        "commodities": {"WTI": s(100.0, 101.0)},
        "memory": {"Micron": s(100.0, 130.0), "Nvidia": s(100.0, 110.0)},
        "ai_infra": {"Marvell": s(100.0, 105.0)},
    }


YIELDS = {"10Y": [("2026-08-14", 4.20), ("2026-08-17", 4.25), ("2026-08-21", 4.35)],
          "2Y": [("2026-08-14", 4.10), ("2026-08-21", 4.15)]}

HEADLINES = [{"date": "2026-08-21", "headline": "재무부 바이백 확대"}]


def test_build_sets_span_key_and_boundaries():
    r = build("weekly", "2026-W34", _closes(), YIELDS, HEADLINES)
    assert r["span"] == "weekly"
    assert r["key"] == "2026-W34"
    assert r["start_date"] == "2026-08-17"
    assert r["end_date"] == "2026-08-21"
    assert r["sessions"] == 2


def test_build_ranks_sectors_best_first():
    r = build("weekly", "2026-W34", _closes(), YIELDS, HEADLINES)
    assert r["sectors"]["Technology"]["rank"] == 1
    assert r["sectors"]["Technology"]["pct"] == pytest.approx(20.0)
    assert r["sectors"]["Energy"]["rank"] == 2


def test_build_computes_basket_excess_over_spx():
    r = build("weekly", "2026-W34", _closes(), YIELDS, HEADLINES)
    # 메모리 바스켓 = (30 + 10) / 2 = 20%, S&P 500 = 10% → 초과 10%p
    assert r["memory"]["basket_pct"] == pytest.approx(20.0)
    assert r["memory"]["basket_excess_pct"] == pytest.approx(10.0)
    assert r["ai_infra"]["basket_excess_pct"] == pytest.approx(-5.0)


def test_build_reports_yield_change_in_bp():
    r = build("weekly", "2026-W34", _closes(), YIELDS, HEADLINES)
    assert r["yields"]["10Y"]["chg_bp"] == pytest.approx(15.0)


def test_build_computes_curve_spread_change():
    r = build("weekly", "2026-W34", _closes(), YIELDS, HEADLINES)
    # 2s10s: 시작 (4.20-4.10)=10bp, 끝 (4.35-4.15)=20bp
    assert r["curve"]["spread_2s10s_bp"]["chg"] == pytest.approx(10.0)


def test_build_flags_incomplete_when_a_series_is_missing():
    c = _closes()
    c["indices"]["Dow"] = []
    r = build("weekly", "2026-W34", c, YIELDS, HEADLINES)
    assert r["complete"] is False
    assert "indices.Dow" in r["missing"]


def test_build_carries_daily_headlines_ascending():
    r = build("weekly", "2026-W34", _closes(), YIELDS,
              [{"date": "2026-08-21", "headline": "b"}, {"date": "2026-08-17", "headline": "a"}])
    assert [x["date"] for x in r["daily"]] == ["2026-08-17", "2026-08-21"]


def _complete_yields():
    """모든 TENORS 를 포함한 완전한 yield 데이터."""
    return {
        '2Y': [("2026-08-14", 4.10), ("2026-08-17", 4.10), ("2026-08-21", 4.15)],
        '5Y': [("2026-08-14", 4.15), ("2026-08-17", 4.15), ("2026-08-21", 4.20)],
        '10Y': [("2026-08-14", 4.20), ("2026-08-17", 4.25), ("2026-08-21", 4.35)],
        '30Y': [("2026-08-14", 4.50), ("2026-08-17", 4.50), ("2026-08-21", 4.55)],
    }


def test_build_complete_with_all_groups_and_tenors():
    """모든 그룹과 tenor 가 있을 때 complete=True 와 missing=[]."""
    r = build("weekly", "2026-W34", _closes(), _complete_yields(), HEADLINES)
    assert r["complete"] is True
    assert r["missing"] == []


def test_build_flags_group_entirely_absent():
    """그룹이 closes 에서 통째로 빠지면 missing 에 기록."""
    c = _closes()
    del c["memory"]
    r = build("weekly", "2026-W34", c, _complete_yields(), HEADLINES)
    assert r["complete"] is False
    assert "memory: group absent" in r["missing"]


def test_build_flags_tenor_absent():
    """tenor 가 yields_hist 에서 빠지면 missing 에 기록."""
    y = _complete_yields()
    del y["5Y"]
    r = build("weekly", "2026-W34", _closes(), y, HEADLINES)
    assert r["complete"] is False
    assert "yields.5Y" in r["missing"]


def test_build_flags_tenor_without_prior_close():
    """tenor 의 시리즈가 start 전 종가를 갖지 못하면 missing 에 기록."""
    y = _complete_yields()
    y["5Y"] = [("2026-08-17", 4.15), ("2026-08-21", 4.20)]  # start 전 데이터 없음
    r = build("weekly", "2026-W34", _closes(), y, HEADLINES)
    assert r["complete"] is False
    assert "yields.5Y" in r["missing"]
    # 5Y 가 missing 이므로 5Y 를 사용하는 spread_5s30s_bp 는 curve 에 없어야 한다
    assert "spread_5s30s_bp" not in r["curve"]
    # 하지만 2s10s 는 2Y 와 10Y 가 완전하면 있어야 한다
    assert "spread_2s10s_bp" in r["curve"]


def test_build_daily_row_gets_correct_spx_pct():
    """daily 행이 정확한 spx_pct 를 받는다."""
    headlines = [{"date": "2026-08-21", "headline": "test"}]
    r = build("weekly", "2026-W34", _closes(), _complete_yields(), headlines)
    # 2026-08-17(이전 종가 100) → 2026-08-21(종가 110): (110/100-1)*100 = 10%
    row = r["daily"][0]
    assert row["date"] == "2026-08-21"
    assert row["spx_pct"] == pytest.approx(10.0)


def test_build_first_daily_date_uses_prewindow_close():
    """window 첫 날은 그 이전의 마지막 종가 대비다 — 창 시작 자신이 아니라."""
    # 이 테스트는 "직전 종가" 관례를 검증하는 유일한 것이다.
    # pre-window close 와 window start close 가 확연히 다를 때만 차별한다.
    # 차용한 benchmark: 14=100 (pre-window), 17=125 (window start), 21=130 (end)
    c = _closes()
    c["indices"]["S&P 500"] = [("2026-08-14", 100.0), ("2026-08-17", 125.0), ("2026-08-21", 130.0)]
    headlines = [{"date": "2026-08-17", "headline": "test"}]
    r = build("weekly", "2026-W34", c, _complete_yields(), headlines)
    row = r["daily"][0]
    # 정확한 구현 (직전 종가 사용): (125/100-1)*100 = 25.0
    # 잘못된 구현 (자신의 종가 사용): (125/125-1)*100 = 0.0
    assert row["spx_pct"] == pytest.approx(25.0), \
        "should measure from pre-window close (100), not window start itself (125)"


def test_build_daily_with_missing_benchmark():
    """benchmark(S&P 500) 자체가 없으면 창을 정할 달력이 없다 — 하드 실패다.

    _bounds 가 이제 벤치마크 하나만 보므로, indices 그룹이 통째로 없으면
    start/end 를 못 정하고 (구 union 코드처럼 다른 그룹 날짜로 창을 만드는 대신)
    'no sessions' 조기 반환과 같은 경로로 빠져 daily/groups 계산 자체를 건너뛴다.
    """
    c = _closes()
    del c["indices"]
    headlines = [{"date": "2026-08-21", "headline": "test"}]
    r = build("weekly", "2026-W34", c, _complete_yields(), headlines)
    assert r["complete"] is False
    assert f"indices.{BENCHMARK}" in r["missing"]
    assert r["start_date"] is None
    assert r["end_date"] is None
    assert r["sessions"] == 0
    # 창을 못 정했으므로 daily/그룹 계산 자체가 없다
    assert "daily" not in r


def test_bounds_ignores_stray_dates_outside_benchmark_calendar():
    """FX 등 비-벤치마크 계열의 벤치마크 이후 튄 날짜는 창에 영향을 주면 안 된다.

    실사고: KRW=X(원/달러)가 주말 바를 물어 와 주간 집계 end_date 가
    토/일로 밀리고 sessions 가 부풀었던 버그의 회귀 테스트. 벤치마크(S&P 500)
    에 없는 날짜가 창을 늘리면 안 된다 — union 기반 구코드에서는 이 assert 가
    실패한다(end_date 가 2026-08-23, sessions 가 3 이 됨).
    """
    c = _closes()
    # 벤치마크(S&P 500)의 마지막 날짜(08-21, 금) 이후 주말 바 하나를 FX 에만 추가
    c["fx"]["KRW=X"] = [("2026-08-14", 1300.0), ("2026-08-17", 1300.0),
                         ("2026-08-21", 1310.0), ("2026-08-23", 1312.0)]
    r = build("weekly", "2026-W34", c, YIELDS, HEADLINES)
    assert r["end_date"] == "2026-08-21"
    assert r["sessions"] == 2


def test_build_daily_with_no_matching_bar():
    """headline 날짜가 benchmark 바를 갖지 못하면 spx_pct 는 None."""
    headlines = [{"date": "2026-08-20", "headline": "test"}]
    r = build("weekly", "2026-W34", _closes(), _complete_yields(), headlines)
    # 2026-08-20 은 _closes() SPX 에 없다 (2026-08-14/17/21만 있음)
    row = r["daily"][0]
    assert row["date"] == "2026-08-20"
    assert row["spx_pct"] is None
    # 하지만 row 는 여전히 있다 (삭제되지 않음)
    assert len(r["daily"]) == 1
