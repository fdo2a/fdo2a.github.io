import pytest

from kr.period import finalize, session_from, upsert_session

MARKET = {"report_date": "2026-08-21",
          "indices": {"KOSPI": {"close": 6912.95, "change_pct": 0.88},
                      "KOSDAQ": {"close": 801.94, "change_pct": -4.63}}}

FLOWS = {"KOSPI": {"rows": [{"date": "2026-08-21", "foreign": -1760,
                             "institution": 2481, "individual": -11652},
                            {"date": "2026-08-20", "foreign": 17068,
                             "institution": -4895, "individual": -22712}],
                   "flows_provisional": False},
         "KOSDAQ": {"rows": [{"date": "2026-08-21", "foreign": 100,
                              "institution": -50, "individual": -50}],
                    "flows_provisional": False}}

INDUSTRY = [{"name": "생명보험", "change_pct": 8.88, "breadth": 0.25, "leading": True},
            {"name": "손해보험", "change_pct": 4.8, "breadth": 0.5, "leading": False}]

TOPVAL = [{"label": "삼성전자", "kind": "stock", "value": 7682302},
          {"label": "SK하이닉스", "kind": "stock", "value": 7384023}]


def _agg():
    return {"span": "weekly", "key": "2026-W34", "sessions": {}}


def test_session_from_collects_one_days_contribution():
    s = session_from(MARKET, FLOWS, INDUSTRY, TOPVAL)
    assert s["date"] == "2026-08-21"
    assert s["flows"]["KOSPI"]["foreign"] == -1760
    assert s["top_value"]["삼성전자"] == 7682302
    assert s["leading_industries"] == ["생명보험"]


def test_session_from_drops_provisional_flows():
    f = {"KOSPI": {"rows": [{"date": "2026-08-21", "foreign": 1, "institution": 2,
                             "individual": 3}], "flows_provisional": True},
         "KOSDAQ": {"rows": [], "flows_provisional": True}}
    s = session_from(MARKET, f, INDUSTRY, TOPVAL)
    assert s["flows"] == {}          # 잠정치는 담지 않는다
    assert s["flows_note"] == "잠정치 제외"


def test_session_from_backfills_older_confirmed_flow_rows():
    # kr_flows.json 은 10일치를 들고 있다 — 지난 날짜도 같이 회수해 월간을 자가치유시킨다
    s = session_from(MARKET, FLOWS, INDUSTRY, TOPVAL)
    assert "2026-08-20" in s["extra_flow_dates"]
    assert s["extra_flows"]["2026-08-20"]["KOSPI"]["foreign"] == 17068


def test_upsert_replaces_same_date_instead_of_double_counting():
    a = _agg()
    a = upsert_session(a, {"date": "2026-08-21", "flows": {"KOSPI": {"foreign": 100}}})
    a = upsert_session(a, {"date": "2026-08-21", "flows": {"KOSPI": {"foreign": 200}}})
    assert len(a["sessions"]) == 1
    assert a["sessions"]["2026-08-21"]["flows"]["KOSPI"]["foreign"] == 200


def test_finalize_sums_flows_over_confirmed_sessions_only():
    a = _agg()
    a = upsert_session(a, {"date": "2026-08-20",
                           "flows": {"KOSPI": {"foreign": 10, "institution": 1,
                                               "individual": -11}}})
    a = upsert_session(a, {"date": "2026-08-21",
                           "flows": {"KOSPI": {"foreign": -4, "institution": 2,
                                               "individual": 2}}})
    a = upsert_session(a, {"date": "2026-08-19", "flows": {}})   # 잠정치라 비었던 날
    r = finalize(a, {})
    assert r["flows"]["KOSPI"]["foreign"] == 6
    assert r["flows_sessions"] == 2       # 3일이 아니라 2일 — 확정치만 센다
    assert r["sessions"] == 3


def test_finalize_computes_index_returns_from_dated_closes():
    a = _agg()
    a = upsert_session(a, {"date": "2026-08-21", "flows": {}})
    closes = {"KOSPI": [("2026-08-14", 6000.0), ("2026-08-21", 6900.0)]}
    r = finalize(a, closes)
    assert r["indices"]["KOSPI"]["pct"] == pytest.approx(15.0)


def test_finalize_ranks_industries_by_mean_change():
    a = _agg()
    a = upsert_session(a, {"date": "2026-08-20", "flows": {},
                           "industry": {"생명보험": 2.0, "손해보험": 6.0}})
    a = upsert_session(a, {"date": "2026-08-21", "flows": {},
                           "industry": {"생명보험": 8.0, "손해보험": 0.0}})
    r = finalize(a, {})
    assert r["industry"]["생명보험"]["pct"] == pytest.approx(5.0)
    assert r["industry"]["생명보험"]["rank"] == 1


def test_finalize_sums_top_value_across_sessions():
    a = _agg()
    a = upsert_session(a, {"date": "2026-08-20", "flows": {}, "top_value": {"삼성전자": 100}})
    a = upsert_session(a, {"date": "2026-08-21", "flows": {},
                           "top_value": {"삼성전자": 50, "SK하이닉스": 300}})
    r = finalize(a, {})
    assert r["top_value"][0] == {"name": "SK하이닉스", "value": 300}
    assert r["top_value"][1] == {"name": "삼성전자", "value": 150}


def test_finalize_sets_boundaries_from_session_dates():
    a = _agg()
    for d in ("2026-08-21", "2026-08-17", "2026-08-19"):
        a = upsert_session(a, {"date": d, "flows": {}})
    r = finalize(a, {})
    assert r["start_date"] == "2026-08-17"
    assert r["end_date"] == "2026-08-21"


def test_leading_industries_are_capped_and_ranked():
    """leading 은 그날 절반에 붙는 플래그라 상위만 남긴다 — 실측 60행 중 30행이 true."""
    rows = [{"name": f"업종{i}", "change_pct": float(i), "leading": True}
            for i in range(10)]
    rows += [{"name": "안주도", "change_pct": 99.0, "leading": False}]
    s = session_from(MARKET, FLOWS, rows, TOPVAL)
    assert s["leading_industries"] == ["업종9", "업종8", "업종7", "업종6", "업종5"]
    assert "안주도" not in s["leading_industries"]
