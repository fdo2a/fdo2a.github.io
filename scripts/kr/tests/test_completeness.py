from collect_kr_data import completeness

# 2026-11-12: indices 는 코스피·코스닥 둘 다 종가·등락률이 수이고 검증 status 가 차단이 아니어야 통과한다
IDX = {"KOSPI": {"close": 2700, "change_pct": 1.0}, "KOSDAQ": {"close": 800, "change_pct": -0.5}}
OK_CHECKS = {"KOSPI": {"status": "ok"}, "KOSDAQ": {"status": "ok_flat"}}


def _bundle(**kw):
    b = {"indices": IDX, "index_checks": OK_CHECKS, "index_mode": "warn",
         "flows": {"latest_date": "2024-06-07"}, "top_value": [{"label": "모나리자"}],
         "sectors": [{"name": "반도체"}], "themes": [{"name": "로봇"}]}
    b.update(kw)
    return b


def test_completeness_flags_missing():
    ok, missing = completeness({"indices": {}, "flows": None, "top_value": [],
                                "sectors": [], "themes": []})
    assert ok is False
    assert "flows" in missing and "indices" in missing


def test_completeness_passes_when_core_present():
    ok, missing = completeness(_bundle())
    assert ok is True and missing == []


def test_completeness_ignores_missing_themes():
    """테마 섹션 폐지(2026-07-29 사용자 지시) 후 themes 결측은 발행을 막지 않는다."""
    ok, missing = completeness(_bundle(themes=[]))
    assert ok is True and missing == []


def test_one_index_is_not_enough():
    ok, missing = completeness(_bundle(indices={"KOSPI": IDX["KOSPI"]}))
    assert ok is False and missing == ["indices"]


def test_unverified_or_unread_ratio_blocks_with_the_existing_token():
    for checks in ({"KOSPI": {"status": "ok"}, "KOSDAQ": {"status": "flat_unverified"}},
                   {"KOSPI": {"status": "ok"}},                                   # 검증 기록 없음
                   {"KOSPI": {"status": "ok"}, "KOSDAQ": {"status": "ratio_missing"}}):
        assert completeness(_bundle(index_checks=checks))[1] == ["indices"]
    idx = {"KOSPI": IDX["KOSPI"], "KOSDAQ": {"close": 800, "change_pct": None}}
    assert completeness(_bundle(indices=idx))[1] == ["indices"]


def test_mismatch_blocks_only_in_block_mode():
    checks = {"KOSPI": {"status": "ok"}, "KOSDAQ": {"status": "mismatch"}}
    assert completeness(_bundle(index_checks=checks))[0] is True
    assert completeness(_bundle(index_checks=checks, index_mode="block"))[1] == ["indices"]
