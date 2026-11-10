"""발행된 날의 동결 병합 — 순수 함수(2026-11-10).

spec: docs/superpowers/specs/2026-11-10-kr-data-versions.md 「무엇을 하나」 3.
"""
from kr import versions_kr as V

D = "2026-11-06"
PREV = "2026-11-05"
KEY = "2026-W45"


def mk_files(date, kospi=5059.69, kosdaq=644.27, industry=None, top=None, flows_rows=None, provisional=True):
    ind = industry if industry is not None else [
        {"name": "IT서비스", "change_pct": 1.15, "breadth": 0.227, "leading": True},
        {"name": "은행", "change_pct": -1.74, "breadth": 0.18, "leading": False}]
    idx = {}
    if kospi is not None:
        idx["KOSPI"] = {"close": kospi, "change_pct": -6.0}
    if kosdaq is not None:
        idx["KOSDAQ"] = {"close": kosdaq, "change_pct": -5.0}
    rows = flows_rows if flows_rows is not None else [
        {"date": date, "individual": 5532, "foreign": -27211, "institution": 17050},
        {"date": PREV, "individual": 22087, "foreign": -33733, "institution": 8819}]
    return {
        "kr/data/kr_market_data.json": {"report_date": date, "complete": True, "missing": [], "indices": idx},
        "kr/data/kr_industry.json": ind,
        "kr/data/kr_top_value.json": top if top is not None else [{"label": "SK하이닉스", "value": 8730799}],
        "kr/data/kr_flows.json": {m: {"rows": rows, "latest_date": date, "flows_provisional": provisional}
                                  for m in ("KOSPI", "KOSDAQ")},
    }


def night_files():
    return mk_files(D, industry=[{"name": "IT서비스", "change_pct": 1.11, "breadth": 0.277, "leading": True},
                                 {"name": "은행", "change_pct": -1.82, "breadth": 0.09, "leading": False}],
                    top=[{"label": "SK하이닉스", "value": 8961260}],
                    flows_rows=[{"date": D, "individual": 5207, "foreign": -26892, "institution": 17092},
                                {"date": PREV, "individual": 22000, "foreign": -33000, "institution": 8000}])


def remote_agg():
    return {"span": "weekly", "key": KEY, "_sessions": {
        PREV: {"industry": {"IT서비스": 0.5}, "top_value": {}, "leading_industries": [],
               "flows": {"KOSPI": {"foreign": -1, "institution": 1, "individual": 0}}},
        D: {"industry": {"IT서비스": 1.15, "은행": -1.74}, "top_value": {"SK하이닉스": 8730799},
            "leading_industries": ["IT서비스"], "flows": {}}}}


LEDGER = [{"report_date": "2026-10-30", "indices": {"KOSPI": 5700.0, "KOSDAQ": 700.0}},
          {"report_date": PREV, "indices": {"KOSPI": 5383.0, "KOSDAQ": 678.0}},
          {"report_date": D, "indices": {"KOSPI": 5059.69, "KOSDAQ": 644.27}}]


def test_published_day_keeps_published_industry_and_topvalue():
    agg = V.merge_week(remote_agg(), night_files(), mk_files(D), D, published=True,
                       promotions={}, ledger_rows=LEDGER, key=KEY)
    s = agg["_sessions"][D]
    assert s["industry"]["은행"] == -1.74 and s["industry"]["IT서비스"] == 1.15
    assert s["top_value"]["SK하이닉스"] == 8730799
    assert s["leading_industries"] == ["IT서비스"]
    assert agg["_provenance"][D]["industry"] == "published"


def test_published_day_still_takes_next_session_flows_for_earlier_dates():
    # 다음 거래일 관측값(extra_flows)은 동결과 별개의 선택 정책 — 이전 날짜에는 오늘처럼 반영
    agg = V.merge_week(remote_agg(), night_files(), mk_files(D), D, published=True,
                       promotions={}, ledger_rows=LEDGER, key=KEY)
    assert agg["_sessions"][PREV]["flows"]["KOSPI"]["individual"] == 22000


def test_published_day_flows_remote_first_then_published():
    r = remote_agg()
    r["_sessions"][D]["flows"] = {"KOSPI": {"foreign": 9, "institution": 9, "individual": 9}}
    p = mk_files(D, provisional=False)           # 발행판이 D 행을 확정으로 들고 있는 가상 사례
    agg = V.merge_week(r, night_files(), p, D, published=True, promotions={}, ledger_rows=LEDGER, key=KEY)
    f = agg["_sessions"][D]["flows"]
    assert f["KOSPI"]["foreign"] == 9             # 원격 기존 값이 먼저
    assert f["KOSDAQ"]["individual"] == 5532      # 원격에 없으면 발행판


def test_published_day_with_empty_published_industry_stays_empty():
    # 자동 보완 금지 — 발행판이 비었으면 비운 채로(재수집값을 넣지 않는다)
    p = mk_files(D, industry=[])
    agg = V.merge_week(remote_agg(), night_files(), p, D, published=True, promotions={}, ledger_rows=LEDGER, key=KEY)
    assert agg["_sessions"][D]["industry"] == {}


def test_unpublished_day_behaves_like_today():
    agg = V.merge_week(remote_agg(), night_files(), None, D, published=False,
                       promotions={}, ledger_rows=LEDGER, key=KEY)
    assert agg["_sessions"][D]["industry"]["은행"] == -1.82
    assert agg["_provenance"][D]["industry"] == "run"


def test_published_but_publish_commit_missing_falls_back_to_run():
    agg = V.merge_week(remote_agg(), night_files(), None, D, published=True,
                       promotions={}, ledger_rows=LEDGER, key=KEY)
    assert agg["_sessions"][D]["industry"]["은행"] == -1.82
    assert agg["_provenance"][D]["industry"] == "run_no_publish_commit"


def test_promotion_wins_last_over_next_session_flows():
    promos = {PREV: [{"field": "session.flows.KOSPI",
                      "value": {"foreign": 1, "institution": 2, "individual": 3}}]}
    agg = V.merge_week(remote_agg(), night_files(), mk_files(D), D, published=True,
                       promotions=promos, ledger_rows=LEDGER, key=KEY)
    assert agg["_sessions"][PREV]["flows"]["KOSPI"] == {"foreign": 1, "institution": 2, "individual": 3}
    assert agg["_provenance"][PREV]["flows.KOSPI"] == "promotion"


def test_finalize_output_keeps_existing_keys():
    agg = V.merge_week(remote_agg(), night_files(), mk_files(D), D, published=True,
                       promotions={}, ledger_rows=LEDGER, key=KEY)
    for k in ("industry", "top_value", "flows", "indices", "complete", "missing", "start_date", "end_date", "_sessions"):
        assert k in agg


# ── 원장 ────────────────────────────────────────────────────────────────

def test_ledger_published_row_comes_from_publish_commit():
    night_row = {"report_date": D, "indices": {"KOSPI": 1.0, "KOSDAQ": 2.0}}
    rows = V.merge_ledger(LEDGER, night_row, V.ledger_row(mk_files(D)), D, published=True, promotions={})
    row = [r for r in rows if r["report_date"] == D][0]
    assert row["indices"] == {"KOSPI": 5059.69, "KOSDAQ": 644.27}


def test_ledger_published_row_with_missing_index_stays_missing():
    # 시나리오 2: 발행본부터 지수 한쪽이 없다 → 새벽 값으로 채우지 않는다
    p = mk_files(D, kosdaq=None)
    night_row = {"report_date": D, "indices": {"KOSPI": 5059.69, "KOSDAQ": 644.27}}
    rows = V.merge_ledger(LEDGER, night_row, V.ledger_row(p), D, published=True, promotions={})
    row = [r for r in rows if r["report_date"] == D][0]
    assert "KOSDAQ" not in row["indices"]


def test_ledger_promotion_restores_index():
    p = mk_files(D, kosdaq=None)
    promos = {D: [{"field": "ledger.indices.KOSDAQ", "value": 644.27}]}
    rows = V.merge_ledger(LEDGER, None, V.ledger_row(p), D, published=True, promotions=promos)
    row = [r for r in rows if r["report_date"] == D][0]
    assert row["indices"]["KOSDAQ"] == 644.27


def test_ledger_unpublished_upserts_run_row():
    night_row = {"report_date": D, "indices": {"KOSPI": 1.0, "KOSDAQ": 2.0}}
    rows = V.merge_ledger(LEDGER, night_row, None, D, published=False, promotions={})
    assert [r for r in rows if r["report_date"] == D][0]["indices"]["KOSPI"] == 1.0
    assert len([r for r in rows if r["report_date"] == D]) == 1


# ── 시나리오 1·2 를 주간 complete 로 ────────────────────────────────────

def test_scenario1_published_has_index_night_lacks_weekly_complete():
    night = mk_files(D, kosdaq=None)
    rows = V.merge_ledger(LEDGER, V.ledger_row(night), V.ledger_row(mk_files(D)), D, published=True, promotions={})
    agg = V.merge_week(remote_agg(), night, mk_files(D), D, published=True, promotions={}, ledger_rows=rows, key=KEY)
    assert agg["complete"] is True


def test_scenario2_published_lacks_index_weekly_held_with_named_gap():
    p = mk_files(D, kosdaq=None)
    rows = V.merge_ledger([r for r in LEDGER if r["report_date"] != D], V.ledger_row(night_files()),
                          V.ledger_row(p), D, published=True, promotions={})
    agg = V.merge_week(remote_agg(), night_files(), p, D, published=True, promotions={}, ledger_rows=rows, key=KEY)
    assert agg["complete"] is False
    assert f"indices.KOSDAQ.{D}" in agg["missing"]



def test_hold_only_for_published_day_gaps():
    agg = {'complete': True, 'missing': ['indices.KOSDAQ.2026-11-05', 'indices.KOSDAQ.2026-11-06']}
    V.hold_published_gaps(agg, ['2026-11-04'])
    assert agg['complete'] is True                                  # 빈 칸이 미발행일뿐
    V.hold_published_gaps(agg, ['2026-11-05'])
    assert agg['complete'] is False and any(m.startswith('held:') for m in agg['missing'])
