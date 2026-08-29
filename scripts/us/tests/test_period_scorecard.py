import pytest

from us.period_scorecard import realized, regime_check, rollup, score, segments, trigger_hygiene

AGG = {
    "start_date": "2026-08-17", "end_date": "2026-08-21",
    "indices": {"S&P 500": {"pct": 2.0}},
    "yields": {"10Y": {"chg_bp": -12.0}},
    "fx": {"DXY": {"pct": -1.5}},
    "commodities": {"WTI": {"pct": 3.0}, "Gold": {"pct": 0.2}},
    "memory": {"basket_excess_pct": 4.0},
    "ai_infra": {"basket_excess_pct": -0.3},
}


def test_realized_maps_each_asset_to_its_series():
    r = realized(AGG)
    assert r["equities"] == pytest.approx(2.0)
    assert r["fx"] == pytest.approx(-1.5)
    assert r["energy"] == pytest.approx(3.0)
    assert r["metals"] == pytest.approx(0.2)
    assert r["memory"] == pytest.approx(4.0)
    assert r["ai_infra"] == pytest.approx(-0.3)


def test_realized_flips_the_sign_for_bonds():
    # 롱 듀레이션(+등급) = 금리 하락 베팅. 10Y −12bp 는 채권에게 플러스다.
    assert realized(AGG)["bonds"] == pytest.approx(12.0)


def _rows(*pairs):
    return [{"report_date": d, "assets": {k: {"grade": g} for k, g in grades.items()}}
            for d, grades in pairs]


def test_segments_uses_the_grade_in_force_at_period_start():
    rows = _rows(("2026-08-14", {"equities": 1}), ("2026-08-21", {"equities": 2}))
    segs = segments(rows, "2026-08-17", "2026-08-21")
    assert segs["equities"][0]["grade"] == 1


def test_segments_splits_when_the_grade_changes_mid_period():
    rows = _rows(("2026-08-14", {"equities": 1}),
                 ("2026-08-19", {"equities": -1}),
                 ("2026-08-21", {"equities": -1}))
    segs = segments(rows, "2026-08-17", "2026-08-21")
    assert [s["grade"] for s in segs["equities"]] == [1, -1]


def test_score_counts_a_matching_sign_as_a_hit():
    rows = _rows(("2026-08-14", {"equities": 2}))
    r = score(rows, AGG)
    assert r["assets"]["equities"]["verdict"] == "적중"
    assert r["weighted"] == pytest.approx(1.0)


def test_score_penalises_conviction_more_than_a_light_tilt():
    strong = score(_rows(("2026-08-14", {"equities": 2, "fx": 1})), AGG)
    # equities +2 적중(+2), fx +1 이지만 DXY −1.5 → 미스(−1) → (2−1)/3
    # 점수는 JSON 산출물이라 4자리로 반올림된다 — 허용오차를 그에 맞춘다
    assert strong["weighted"] == pytest.approx(1 / 3, abs=5e-5)


def test_score_treats_small_moves_as_unjudged():
    rows = _rows(("2026-08-14", {"ai_infra": 1}))     # 실현 −0.3%p, 임계 0.5 미만
    r = score(rows, AGG)
    assert r["assets"]["ai_infra"]["verdict"] == "무판정"
    assert r["judged"] == 0


def test_score_uses_a_bp_threshold_for_bonds():
    agg = {**AGG, "yields": {"10Y": {"chg_bp": -2.0}}}   # 2bp < 3bp 임계
    r = score(_rows(("2026-08-14", {"bonds": 1})), agg)
    assert r["assets"]["bonds"]["verdict"] == "무판정"


def test_score_excludes_neutral_from_the_denominator_but_reports_it():
    rows = _rows(("2026-08-14", {"equities": 2, "bonds": 0, "fx": 0}))
    r = score(rows, AGG)
    assert r["weighted"] == pytest.approx(1.0)      # 중립 둘은 분모 밖
    assert r["neutral"] == 2
    assert r["neutral_share"] == pytest.approx(2 / 3, abs=5e-5)


def test_score_is_none_when_nothing_was_judged():
    r = score(_rows(("2026-08-14", {"bonds": 0})), AGG)
    assert r["weighted"] is None
    assert r["note"] == "판정 가능한 포지션 없음"


def test_regime_check_agrees_when_most_new_prints_match():
    macro = [{"report_date": "2026-08-21", "regime": {"growth": -1, "inflation": 0}}]
    metrics = {"indicators": [
        {"key": "PAYEMS", "axis": "labor", "direction": "악화", "released": "2026-08-19"},
        {"key": "ICSA", "axis": "labor", "direction": "악화", "released": "2026-08-20"},
        {"key": "RSAFS", "axis": "consumption", "direction": "개선", "released": "2026-08-20"}]}
    r = regime_check(macro, metrics, "2026-08-17", "2026-08-21")
    assert r["verdict"] == "정합"
    assert r["prints"] == 3


def test_regime_check_is_undecidable_without_new_prints():
    macro = [{"report_date": "2026-08-21", "regime": {"growth": 0, "inflation": 0}}]
    r = regime_check(macro, {"indicators": []}, "2026-08-17", "2026-08-21")
    assert r["verdict"] == "판정불가"


def test_trigger_hygiene_flags_long_dormant_conditions():
    rows = [{"report_date": f"2026-07-{d:02d}",
             "assets": {"equities": {"grade": 0, "triggers": {
                 "increase": [{"metric": "spx_vs_50dma_pct", "op": ">", "value": 4.0}],
                 "decrease": []}}}}
            for d in range(1, 29)]
    r = trigger_hygiene(rows, "2026-07-28", stale_days=20)
    assert any(t["metric"] == "spx_vs_50dma_pct" for t in r["dormant"])


def test_rollup_averages_recent_periods():
    hist = [{"key": f"2026-W{w}", "weighted": w / 10, "judged": 2} for w in (30, 31, 32, 33, 34)]
    r = rollup(hist, spans=(4,))
    assert r["last_4"]["periods"] == 4
    assert r["last_4"]["weighted"] == pytest.approx((3.1 + 3.2 + 3.3 + 3.4) / 4)
    assert r["all"]["periods"] == 5


def test_rollup_marks_thin_samples():
    r = rollup([{"key": "2026-W34", "weighted": 0.5, "judged": 2}], spans=(4, 12))
    assert r["last_4"]["insufficient"] is True
    assert r["last_12"]["insufficient"] is True
