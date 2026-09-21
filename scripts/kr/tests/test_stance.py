from kr.stance import evaluate, validate

GOOD = {"date": "2026-09-21", "exposure": "유지", "horizon": "다음 세션",
        "thesis": "기관 순매수가 지수를 밀어올렸고 외국인은 아직 관망이다.",
        "gap": "3년물이 기준금리보다 넓은 자리인데 주식은 그 부담을 값매기지 않았다.",
        "alternative": "기관 순매수가 방향성 매수가 아니라 자체 헤지일 수 있다.",
        "distinguisher": "장중 수급의 금융투자와 연기금등이 갈리는지 본다.",
        "wait_for": "외국인이 순매수로 돌아서는 첫 세션을 기다린다.",
        "expression": {"instrument": "KODEX 200", "value": 2120429},
        "invalidation": {"metric": "KOSPI", "level": 6904, "side": "below",
                         "note": "60일 이동평균"}}
IDX = {"KOSPI": {"close": 7007.72}, "KOSDAQ": {"close": 836.27}}


def test_validate_accepts_complete_stance():
    assert validate(GOOD) == []


def test_validate_rejects_free_form_exposure():
    bad = {**GOOD, "exposure": "약간 확대"}
    assert any("exposure" in x for x in validate(bad))


def test_validate_requires_numeric_invalidation_level():
    bad = {**GOOD, "invalidation": {"metric": "KOSPI", "side": "below",
                                    "level": "60일선 부근"}}
    assert any("level" in x for x in validate(bad))


def test_validate_requires_thesis_and_gap_substance():
    bad = {**GOOD, "gap": "차이 있음"}
    v = validate(bad)
    assert any("gap" in x for x in v) and not any("thesis" in x for x in v)


def test_validate_reports_missing_invalidation_once():
    bad = {k: v for k, v in GOOD.items() if k != "invalidation"}
    v = validate(bad)
    assert [x for x in v if "invalidation" in x] == [
        "invalidation 이 없다 — 틀렸다고 볼 조건을 숫자로 남긴다"]


def test_validate_rejects_non_dict():
    assert validate(None) == ["판단 원장이 객체가 아니다"]


def test_evaluate_holds_when_level_not_broken():
    out = evaluate(GOOD, IDX)
    assert out["verdict"] == "유효" and out["observed"] == 7007.72
    assert out["prior_exposure"] == "유지"
    assert "6,904.00" in out["note"]


def test_evaluate_breaks_when_close_falls_through():
    out = evaluate(GOOD, {"KOSPI": {"close": 6800.0}})
    assert out["verdict"] == "무효화"
    assert "발동" in out["note"]


def test_evaluate_above_side():
    up = {**GOOD, "invalidation": {"metric": "KOSDAQ", "level": 830, "side": "above"}}
    assert evaluate(up, IDX)["verdict"] == "무효화"        # 836.27 > 830
    assert evaluate(up, {"KOSDAQ": {"close": 820.0}})["verdict"] == "유효"


def test_evaluate_bootstraps_without_prior():
    out = evaluate(None, IDX)
    assert out["verdict"] == "판정불가" and "첫 기록" in out["note"]


def test_evaluate_undecidable_when_index_missing():
    out = evaluate(GOOD, {})
    assert out["verdict"] == "판정불가" and out["metric"] == "KOSPI"


def test_evaluate_undecidable_when_level_not_numeric():
    out = evaluate({**GOOD, "invalidation": {"metric": "KOSPI", "side": "below"}}, IDX)
    assert out["verdict"] == "판정불가"


def test_validate_allows_watch_only_day_without_instrument():
    """아이디어를 매일 억지로 만들지 않는다 — 상품을 안 대는 날도 통과한다."""
    watch = {k: v for k, v in GOOD.items() if k != "expression"}
    assert validate(watch) == []


def test_validate_requires_liquidity_number_with_instrument():
    bad = {**GOOD, "expression": {"instrument": "KODEX 200"}}
    assert any("expression.value" in x for x in validate(bad))


def test_validate_requires_wait_for_even_when_watching():
    bad = {k: v for k, v in GOOD.items() if k not in ("expression", "wait_for")}
    assert any("wait_for" in x for x in validate(bad))


def test_validate_requires_alternative_and_distinguisher():
    bad = {**GOOD, "alternative": "몰라", "distinguisher": ""}
    v = validate(bad)
    assert any("alternative" in x for x in v) and any("distinguisher" in x for x in v)


def test_validate_rejects_instrument_without_name():
    bad = {**GOOD, "expression": {"value": 100}}
    assert any("instrument" in x for x in validate(bad))
