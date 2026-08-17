import pytest

from us.stance import (
    ASSETS,
    CURVE_LABELS,
    business_days_inclusive,
    evaluate,
    evaluate_trigger,
    grade_bounds,
    label_for,
    validate_transition,
)


# --- controlled vocabulary -------------------------------------------------

def test_every_asset_has_a_label_for_every_grade_in_range():
    for key in ASSETS:
        lo, hi = grade_bounds(key)
        for g in range(lo, hi + 1):
            assert isinstance(label_for(key, g), str)


def test_labels_are_unique_within_an_asset():
    for key in ASSETS:
        lo, hi = grade_bounds(key)
        labels = [label_for(key, g) for g in range(lo, hi + 1)]
        assert len(set(labels)) == len(labels)


def test_themes_are_three_step_relative_scales():
    for key in ("memory", "ai_infra"):
        assert grade_bounds(key) == (-1, 1)
    assert label_for("memory", -1) == "UW"
    assert label_for("ai_infra", 1) == "OW"


def test_core_assets_are_five_step():
    for key in ("equities", "bonds", "fx", "energy", "metals"):
        assert grade_bounds(key) == (-2, 2)


def test_grade_out_of_range_is_rejected():
    with pytest.raises(ValueError):
        label_for("memory", 2)
    with pytest.raises(ValueError):
        label_for("equities", 3)


def test_unknown_asset_is_rejected():
    with pytest.raises(ValueError):
        label_for("crypto", 0)


def test_curve_vocabulary_is_closed():
    assert "벨리 OW" in CURVE_LABELS
    assert "숏~중립 듀레이션, 장기물 신중" not in CURVE_LABELS


# --- trigger evaluation ----------------------------------------------------

METRICS = {"vix_close": 18.4, "spx_vs_20dma_pct": 1.24, "wti_pct_5d": -9.2}


def test_metric_trigger_met_and_not_met():
    met = evaluate_trigger({"kind": "metric", "metric": "wti_pct_5d", "op": "<", "value": -7},
                           METRICS)
    assert met["status"] == "MET" and met["actual"] == -9.2

    unmet = evaluate_trigger({"kind": "metric", "metric": "vix_close", "op": ">", "value": 22},
                             METRICS)
    assert unmet["status"] == "NOT_MET" and unmet["actual"] == 18.4


@pytest.mark.parametrize("op,value,expected", [
    (">", 18.0, "MET"), (">", 18.4, "NOT_MET"), (">=", 18.4, "MET"),
    ("<", 18.4, "NOT_MET"), ("<=", 18.4, "MET"), ("<", 20.0, "MET"),
])
def test_all_four_operators(op, value, expected):
    t = {"kind": "metric", "metric": "vix_close", "op": op, "value": value}
    assert evaluate_trigger(t, METRICS)["status"] == expected


def test_missing_metric_is_unknown_not_met():
    t = {"kind": "metric", "metric": "does_not_exist", "op": ">", "value": 1}
    r = evaluate_trigger(t, METRICS)
    assert r["status"] == "UNKNOWN" and r["actual"] is None


def test_null_metric_value_is_unknown():
    t = {"kind": "metric", "metric": "gold_pct_5d", "op": ">", "value": 1}
    assert evaluate_trigger(t, {"gold_pct_5d": None})["status"] == "UNKNOWN"


def test_event_trigger_is_manual():
    r = evaluate_trigger({"kind": "event", "desc": "이란 협상 결렬 공식화"}, METRICS)
    assert r["status"] == "MANUAL" and r["desc"] == "이란 협상 결렬 공식화"


def test_unsupported_operator_is_unknown_rather_than_crash():
    t = {"kind": "metric", "metric": "vix_close", "op": "~=", "value": 18}
    assert evaluate_trigger(t, METRICS)["status"] == "UNKNOWN"


# --- business days ---------------------------------------------------------

def test_business_days_inclusive_counts_both_ends():
    assert business_days_inclusive("2026-08-17", "2026-08-17") == 1
    assert business_days_inclusive("2026-08-17", "2026-08-19") == 3


def test_business_days_skips_the_weekend():
    # 2026-08-14 is a Friday, 2026-08-17 a Monday.
    assert business_days_inclusive("2026-08-14", "2026-08-17") == 2


def test_business_days_never_returns_less_than_one():
    assert business_days_inclusive("2026-08-20", "2026-08-17") == 1


# --- allowed grades / movement discipline ----------------------------------

def _stance(grade, since="2026-08-03", increase=None, decrease=None, asset="equities"):
    return {
        "report_date": "2026-08-14",
        "assets": {
            asset: {
                "grade": grade,
                "label": label_for(asset, grade),
                "since": since,
                "thesis": "t",
                "triggers": {"increase": increase or [], "decrease": decrease or []},
            }
        },
    }


UP = [{"kind": "metric", "metric": "spx_vs_20dma_pct", "op": ">", "value": 1.0}]
UP_UNREACHED = [{"kind": "metric", "metric": "spx_vs_20dma_pct", "op": ">", "value": 5.0}]


def test_hold_is_always_allowed():
    ev = evaluate(_stance(1), METRICS, "2026-08-17")
    assert 1 in ev["assets"]["equities"]["allowed_grades"]


def test_decrease_toward_neutral_needs_no_trigger():
    a = evaluate(_stance(2), METRICS, "2026-08-17")["assets"]["equities"]
    assert a["can_decrease"] is True
    assert 1 in a["allowed_grades"]


def test_increase_without_a_met_trigger_is_blocked():
    a = evaluate(_stance(1, increase=UP_UNREACHED), METRICS, "2026-08-17")["assets"]["equities"]
    assert a["can_increase"] is False
    assert a["increase_block"] == "no_trigger_met"
    assert 2 not in a["allowed_grades"]


def test_increase_with_a_met_trigger_is_allowed():
    a = evaluate(_stance(1, increase=UP), METRICS, "2026-08-17")["assets"]["equities"]
    assert a["can_increase"] is True and 2 in a["allowed_grades"]


def test_increase_is_locked_for_three_business_days_after_a_change():
    # since Friday 08-14, evaluating Monday 08-17 -> days_held 2 (< 3)
    a = evaluate(_stance(1, since="2026-08-14", increase=UP), METRICS,
                 "2026-08-17")["assets"]["equities"]
    assert a["days_held"] == 2
    assert a["can_increase"] is False and a["increase_block"] == "lock_3bd"
    # ...but de-risking is never locked
    assert a["can_decrease"] is True and 0 in a["allowed_grades"]


def test_lock_releases_on_the_third_business_day():
    a = evaluate(_stance(1, since="2026-08-13", increase=UP), METRICS,
                 "2026-08-17")["assets"]["equities"]
    assert a["days_held"] == 3 and a["can_increase"] is True


def test_grade_at_maximum_cannot_increase():
    a = evaluate(_stance(2, increase=UP), METRICS, "2026-08-17")["assets"]["equities"]
    assert a["can_increase"] is False and a["increase_block"] == "at_max"


def test_neutral_grade_needs_a_direction_on_the_increase_trigger():
    up_plus = [dict(UP[0], toward="+")]
    a = evaluate(_stance(0, increase=up_plus), METRICS, "2026-08-17")["assets"]["equities"]
    assert a["allowed_grades"] == [0, 1]


def test_neutral_grade_ignores_a_directionless_increase_trigger():
    a = evaluate(_stance(0, increase=UP), METRICS, "2026-08-17")["assets"]["equities"]
    assert a["allowed_grades"] == [0]
    assert a["increase_block"] == "no_direction"


def test_negative_grade_increases_away_from_zero():
    a = evaluate(_stance(-1, increase=UP), METRICS, "2026-08-17")["assets"]["equities"]
    assert sorted(a["allowed_grades"]) == [-2, -1, 0]


def test_unknown_trigger_never_unlocks_an_increase():
    unk = [{"kind": "metric", "metric": "not_collected", "op": ">", "value": 1}]
    a = evaluate(_stance(1, increase=unk), METRICS, "2026-08-17")["assets"]["equities"]
    assert a["can_increase"] is False


def test_event_trigger_leaves_the_increase_to_the_writer():
    ev = [{"kind": "event", "desc": "FOMC 인하 확정"}]
    a = evaluate(_stance(1, increase=ev), METRICS, "2026-08-17")["assets"]["equities"]
    assert a["can_increase"] is True and a["increase_block"] == "manual"
    assert a["manual_pending"] == ["FOMC 인하 확정"]


# --- transition validation -------------------------------------------------

def test_two_step_move_is_rejected():
    a = evaluate(_stance(0, increase=[dict(UP[0], toward="+")]), METRICS,
                 "2026-08-17")["assets"]["equities"]
    ok, reason = validate_transition("equities", 0, 2, a)
    assert ok is False and reason == "two_step"


def test_sign_flip_in_one_day_is_rejected():
    """The 7/29 -1 -> 7/30 +1 regression: a same-day sign flip must be impossible."""
    a = evaluate(_stance(-1, increase=UP), METRICS, "2026-08-17")["assets"]["equities"]
    ok, reason = validate_transition("equities", -1, 1, a)
    assert ok is False and reason == "two_step"


def test_valid_single_step_toward_neutral_passes():
    a = evaluate(_stance(-1), METRICS, "2026-08-17")["assets"]["equities"]
    assert validate_transition("equities", -1, 0, a) == (True, None)


def test_out_of_range_grade_is_rejected():
    a = evaluate(_stance(1), METRICS, "2026-08-17")["assets"]["equities"]
    ok, reason = validate_transition("memory", 1, 2, a)
    assert ok is False and reason == "out_of_range"


# --- stance file lifecycle -------------------------------------------------

def test_missing_stance_is_bootstrap_and_unconstrained():
    ev = evaluate(None, METRICS, "2026-08-17")
    assert ev["bootstrap"] is True and ev["assets"] == {}


def test_stale_stance_keeps_grades_but_releases_the_lock():
    st = _stance(1, since="2026-08-14", increase=UP)
    st["report_date"] = "2026-08-05"
    ev = evaluate(st, METRICS, "2026-08-17")
    assert ev["stale"] is True
    assert ev["assets"]["equities"]["can_increase"] is True


def test_fresh_stance_is_not_stale():
    st = _stance(1, increase=UP)
    st["report_date"] = "2026-08-14"
    ev = evaluate(st, METRICS, "2026-08-17")
    assert ev["stale"] is False


def test_a_market_holiday_gap_is_not_treated_as_a_skipped_run():
    """Fri stance -> Tue report (Monday closed) is 3 business days inclusive, still fresh."""
    st = _stance(1, since="2026-08-14", increase=UP)
    st["report_date"] = "2026-08-14"
    assert evaluate(st, METRICS, "2026-08-18")["stale"] is False


def test_eval_carries_the_labels_forward():
    a = evaluate(_stance(-2), METRICS, "2026-08-17")["assets"]["equities"]
    assert a["label"] == "비중축소" and a["grade"] == -2
