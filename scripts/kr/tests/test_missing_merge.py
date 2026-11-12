"""재수집이 있던 값을 지우지 않는다 — 원장 지수·주간 세션(2026-11-12).

발행된 날의 동결(versions enforce)은 그대로다: 빈 지수는 빈 채, 재수집 값으로 채우지 않는다.
spec: docs/superpowers/specs/2026-11-12-kr-missing-vs-zero.md
"""
from kr import versions_kr as V
from kr.etf_normalize import dropped_products, normalize_top_value
from kr.history import merge_index_record
from kr.period import merge_session, session_from, upsert_session

D = "2026-11-06"
KEY = "2026-W45"


# ── 원장 ────────────────────────────────────────────────────────────────

def test_merge_index_record_keeps_existing_when_new_lacks_index():
    ex = {"report_date": D, "indices": {"KOSPI": 5000.0, "KOSDAQ": 640.0}}
    new = {"report_date": D, "indices": {"KOSPI": 5010.0}}
    assert merge_index_record(ex, new) == {"report_date": D, "indices": {"KOSPI": 5010.0, "KOSDAQ": 640.0}}


def test_merge_index_record_new_value_wins():
    ex = {"report_date": D, "indices": {"KOSPI": 5000.0, "KOSDAQ": 640.0}}
    new = {"report_date": D, "indices": {"KOSPI": 5010.0, "KOSDAQ": 641.0}}
    assert merge_index_record(ex, new)["indices"] == {"KOSPI": 5010.0, "KOSDAQ": 641.0}


def test_merge_index_record_ignores_nan_and_zero():
    ex = {"report_date": D, "indices": {"KOSPI": 5000.0, "KOSDAQ": 640.0}}
    new = {"report_date": D, "indices": {"KOSPI": float("nan"), "KOSDAQ": 0.0}}
    assert merge_index_record(ex, new)["indices"] == {"KOSPI": 5000.0, "KOSDAQ": 640.0}


def test_merge_index_record_without_existing_is_new():
    new = {"report_date": D, "indices": {"KOSPI": 5010.0}}
    assert merge_index_record(None, new) == new
    assert merge_index_record(None, None) is None
    ex = {"report_date": D, "indices": {"KOSPI": 1.0}}
    assert merge_index_record(ex, None) == ex


def test_merge_ledger_unpublished_with_promotion_keeps_other_index_and_promotion_last():
    led = [{"report_date": D, "indices": {"KOSPI": 5000.0, "KOSDAQ": 640.0}}]
    run_row = {"report_date": D, "indices": {"KOSPI": 5010.0}}
    promos = {D: [{"field": "ledger.indices.KOSPI", "value": 4999.0}]}
    rows = V.merge_ledger(led, run_row, None, D, published=False, promotions=promos)
    assert rows == [{"report_date": D, "indices": {"KOSPI": 4999.0, "KOSDAQ": 640.0}}]


def test_merge_ledger_published_without_commit_also_keeps_existing():
    led = [{"report_date": D, "indices": {"KOSPI": 5000.0, "KOSDAQ": 640.0}}]
    rows = V.merge_ledger(led, {"report_date": D, "indices": {"KOSPI": 5010.0}}, None, D,
                          published=True, promotions={})
    assert rows[0]["indices"] == {"KOSPI": 5010.0, "KOSDAQ": 640.0}


def test_merge_ledger_published_stays_publish_commit_value_even_if_run_has_index():
    led = [{"report_date": D, "indices": {"KOSPI": 5000.0}}]
    p_row = {"report_date": D, "indices": {"KOSPI": 5000.0}}
    run_row = {"report_date": D, "indices": {"KOSPI": 5000.0, "KOSDAQ": 640.0}}
    rows = V.merge_ledger(led, run_row, p_row, D, published=True, promotions={})
    assert rows[0]["indices"] == {"KOSPI": 5000.0}          # 빈 지수는 빈 채


# ── 주간 세션 ────────────────────────────────────────────────────────────

def sess(**kw):
    base = {"flows": {}, "industry": {}, "top_value": {}, "leading_industries": [],
            "extra_flows": {}, "extra_flow_dates": []}
    base.update(kw)
    return base


F1 = {"foreign": 1, "institution": 2, "individual": 3}
F2 = {"foreign": 9, "institution": 9, "individual": 9}


def test_merge_session_keeps_market_flows_missing_from_new():
    ex = sess(flows={"KOSPI": F1, "KOSDAQ": F1})
    new = sess(flows={"KOSPI": F2})
    out = merge_session(ex, new)
    assert out["flows"] == {"KOSPI": F2, "KOSDAQ": F1}
    assert "flows_note" not in out


def test_merge_session_new_without_flows_keeps_existing_and_drops_note():
    ex = sess(flows={"KOSPI": F1})
    new = sess(flows_note="잠정치 제외")
    out = merge_session(ex, new)
    assert out["flows"] == {"KOSPI": F1} and "flows_note" not in out


def test_merge_session_empty_everywhere_keeps_note():
    out = merge_session(sess(), sess(flows_note="잠정치 제외"))
    assert out["flows"] == {} and out["flows_note"] == "잠정치 제외"


def test_merge_session_industry_bundle_new_industry_replaces_both_even_empty_leading():
    # 4회차 #1 재현 — 주도 업종이 없는 날은 정상이다
    ex = sess(industry={"반도체": 1.0}, leading_industries=["반도체"])
    new = sess(industry={"반도체": -1.0}, leading_industries=[])
    out = merge_session(ex, new)
    assert out["industry"] == {"반도체": -1.0} and out["leading_industries"] == []


def test_merge_session_industry_bundle_empty_new_industry_keeps_both():
    ex = sess(industry={"반도체": 1.0}, leading_industries=["반도체"])
    for lead in ([], ["엉뚱"]):
        out = merge_session(ex, sess(industry={}, leading_industries=lead))
        assert out["industry"] == {"반도체": 1.0} and out["leading_industries"] == ["반도체"]
    out = merge_session(ex, sess(industry=None))
    assert out["industry"] == {"반도체": 1.0}


def test_merge_session_top_value_bundle():
    ex = sess(top_value={"A": 10, "B": 5})
    assert merge_session(ex, sess(top_value={}))["top_value"] == {"A": 10, "B": 5}
    assert merge_session(ex, sess(top_value={"C": 1}))["top_value"] == {"C": 1}     # 통째 교체


def test_merge_session_snapshot_failure_does_not_erase():
    ex = sess(top_value={"A": 10}, industry={"반도체": 1.0}, leading_industries=["반도체"])
    out = merge_session(ex, sess(top_value={}, industry={}))
    assert out["top_value"] == {"A": 10} and out["leading_industries"] == ["반도체"]


def test_merge_session_without_existing_is_new():
    new = sess(top_value={"A": 1})
    assert merge_session(None, new) == new


def test_upsert_session_uses_merge_with_session_from_provisional_input():
    # 기존 세션에 확정 수급 → 같은 날 재수집(당일 잠정 행만)이 session_from 을 거쳐 와도 유지
    agg = {"sessions": {D: sess(flows={"KOSPI": F1, "KOSDAQ": F1}, top_value={"A": 1},
                                industry={"반도체": 1.0}, leading_industries=["반도체"])}}
    market = {"report_date": D}
    kr_flows = {m: {"rows": [{"date": D, "individual": 7, "foreign": 7, "institution": 7}],
                    "latest_date": D, "flows_provisional": True} for m in ("KOSPI", "KOSDAQ")}
    s = session_from(market, kr_flows, [], [])
    agg = upsert_session(agg, s)
    got = agg["sessions"][D]
    assert got["flows"] == {"KOSPI": F1, "KOSDAQ": F1}
    assert got["top_value"] == {"A": 1} and got["industry"] == {"반도체": 1.0}
    assert "date" not in got


def test_merge_week_unpublished_branch_uses_merge_session():
    remote = {"_sessions": {D: sess(top_value={"A": 10}, industry={"반도체": 1.0},
                                    leading_industries=["반도체"], flows={"KOSPI": F1})}}
    run = {"kr/data/kr_market_data.json": {"report_date": D, "indices": {}},
           "kr/data/kr_flows.json": {}, "kr/data/kr_industry.json": [], "kr/data/kr_top_value.json": []}
    agg = V.merge_week(remote, run, None, D, published=False, promotions={}, ledger_rows=[], key=KEY)
    s = agg["_sessions"][D]
    assert s["top_value"] == {"A": 10} and s["industry"] == {"반도체": 1.0}
    assert s["flows"] == {"KOSPI": F1}


# ── 정규화의 결측 거래량 ─────────────────────────────────────────────────

def test_group_volume_is_none_when_any_member_is_none():
    rows = [{"name": "KODEX 반도체", "value": 10, "volume": 5},
            {"name": "TIGER 반도체", "value": 20, "volume": None},
            {"name": "삼성전자", "value": 30, "volume": None},
            {"name": "SK하이닉스", "value": 25, "volume": 7}]
    out = {g["label"]: g for g in normalize_top_value(rows)}
    assert out["삼성전자"]["volume"] is None
    assert out["SK하이닉스"]["volume"] == 7
    themed = [g for g in out.values() if len(g["members"]) == 2]
    assert themed and themed[0]["volume"] is None and themed[0]["value"] == 30


def test_dropped_products_pass_none_volume():
    rows = [{"name": "KODEX 200", "value": 10, "volume": None}]
    assert dropped_products(rows)[0]["volume"] is None
