from kr.expectations import build, spread_series, standing_of, step_lookup


def _daily(n, start=3.0, step=0.01):
    """오름차순 일별 계열 n개. 날짜는 대조용이라 단조 증가하면 된다."""
    return [(f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}", round(start + i * step, 3))
            for i in range(n)]


def test_step_lookup_takes_last_observation_at_or_before():
    monthly = [("2025-10", 2.5), ("2026-01", 2.75), ("2026-09", 3.0)]
    assert step_lookup(monthly, "2026-09-21") == 3.0
    assert step_lookup(monthly, "2026-05-02") == 2.75
    assert step_lookup(monthly, "2025-10-31") == 2.5
    assert step_lookup(monthly, "2025-09-30") is None


def test_spread_series_converts_percent_to_bp():
    numer = [("2026-09-18", 4.035), ("2026-09-21", 4.056)]
    denom = [("2026-09", 3.0)]
    assert spread_series(numer, denom) == [("2026-09-18", 103.5), ("2026-09-21", 105.6)]


def test_spread_series_drops_days_without_base():
    numer = [("2025-01-02", 3.0), ("2026-09-21", 4.0)]
    denom = [("2026-09", 3.0)]
    assert spread_series(numer, denom) == [("2026-09-21", 100.0)]


def test_standing_of_reports_change_and_position():
    series = [(f"2026-01-{d:02d}", float(d)) for d in range(1, 29)]
    out = standing_of(series)
    assert out["bp"] == 28.0 and out["change_bp"] == 1.0
    assert out["sessions"] == 28
    # 28 표본은 standing 하한(30) 미만 — 위치는 말하지 않는다
    assert "standing" not in out


def test_standing_of_speaks_position_once_sample_is_long_enough():
    series = _daily(60)                       # 단조 증가 → 마지막이 최댓값
    out = standing_of(series)
    assert out["sessions"] == 60
    st = out["standing"]
    assert st["side"] == "high" and st["days"] == 0
    assert "넓은" in st["text"]                # kind='spread' 어휘


def test_standing_of_empty_series():
    assert standing_of([]) == {}


def test_build_makes_three_spreads():
    hist = {"국고채 3년": _daily(60, 3.5), "국고채 10년": _daily(60, 4.0),
            "회사채 AA- 3년": _daily(60, 3.8),
            "한국은행 기준금리": [("2026-01", 2.5)]}
    out = build(hist)
    assert set(out) == {"policy", "growth", "credit"}
    assert out["policy"]["label"] == "정책 기대"
    assert out["growth"]["bp"] == 50.0        # 10년 − 3년 = 0.5%p 고정
    assert out["credit"]["bp"] == 30.0


def test_build_skips_spread_when_leg_missing():
    hist = {"국고채 3년": _daily(60, 3.5), "한국은행 기준금리": [("2026-01", 2.5)]}
    out = build(hist)
    assert set(out) == {"policy"}             # 10년·회사채 없으면 그 줄은 없다


def test_build_empty_history():
    assert build({}) == {}
