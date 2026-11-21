"""KR 수집기의 collect 칸(2026-11-17, 공통 계약 A) — 네트워크 없이 main 을 통째로 돈다.

핵심은 움직인 종목: 묶음 0개가 「없음 확인」인 것은 후보를 거의 다 잰 날뿐이다. 11/09~11/16 의 늦은
실행(01~04시)은 후보 58종목 중 0~1종목만 재고 묶음 0개를 오류 표시 없이 남겼다.
"""
import json

import collect_kr_data
from common import collect_status as C
from kr.tests.test_collect_missing import D, World, env  # noqa: F401 — fixture


def _status(env):
    return json.loads((env["outdir"] / C.STATUS_FILE).read_text(encoding="utf-8"))["files"]


def _krx(monkeypatch, pct=1.0, upto=None):
    def fake(candidates, closes, report_date):
        rows = candidates if upto is None else candidates[:upto]
        return [{"name": c["name"], "change_pct": pct, "close": 100, "value": c["value"]} for c in rows]
    monkeypatch.setattr(collect_kr_data, "krx_changes", fake)


def test_normal_run_stamps_every_gate_file(env, monkeypatch):
    _krx(monkeypatch)
    m = env["run"]()
    c = m["collect"]
    assert c["status"] == "ok" and c["required_ok"] is True and c["as_of"] == D
    assert c["missing"] == ["flows_intraday"]                  # 비-코어 결측은 그대로 옮긴다
    for name in ("kr_flows.json", "kr_intraday.json", "kr_movers.json", "kr_stance_eval.json",
                 "kr_fund_view.json"):
        got = env["read"](name)["collect"]
        assert got["as_of"] == D, name
    assert env["read"]("kr_flows.json")["collect"]["status"] == "ok"
    assert env["read"]("kr_intraday.json")["collect"]["status"] == "ok"
    mv = env["read"]("kr_movers.json")
    assert mv["groups"] and mv["collect"]["empty"] == "has_data" and mv["collect"]["checked"] == 15
    st = _status(env)
    assert st["kr_top_value.json"]["status"] == "ok" and st["kr_top_value.json"]["collect_in"] == "sidecar"
    assert st["kr_index_etf.json"]["as_of"] == D


def test_quiet_day_fully_measured_is_confirmed_none(env, monkeypatch):
    _krx(monkeypatch, pct=0.3)
    w = World()
    for r in w.top:
        r["cap"] = 0                                          # 기여 후보 없음, ±5% 없음
    env["run"](w)
    mv = env["read"]("kr_movers.json")
    assert mv["groups"] == [] and "error" not in mv
    assert mv["collect"]["status"] == "ok" and mv["collect"]["empty"] == "confirmed_none"


def test_unmeasured_day_is_failed_not_confirmed_none(env):
    """yfinance 가 그날 KRX 봉을 안 줬다(가짜 yf 는 종목 봉이 없다) — 옛 코드는 오류 없이 groups [] 였다."""
    env["run"]()
    mv = env["read"]("kr_movers.json")
    assert mv["groups"] == [] and "error" not in mv               # 옛 칸은 그대로(덧붙임만)
    assert mv["collect"]["status"] == "failed" and mv["collect"]["empty"] == "unknown"


def test_low_coverage_is_partial(env, monkeypatch):
    _krx(monkeypatch, upto=1)
    env["run"]()
    c = env["read"]("kr_movers.json")["collect"]
    assert c["status"] == "partial" and c["missing"] == ["coverage:1/15"]


def test_top_value_failure_fails_top_value_and_movers(env, monkeypatch):
    _krx(monkeypatch)
    w = World()
    w.top_error = "HTTP 502"
    m = env["run"](w)
    assert m["collect"]["status"] == "partial" and m["collect"]["required_ok"] is False
    st = _status(env)
    assert st["kr_top_value.json"]["status"] == "failed" and st["kr_index_etf.json"]["status"] == "failed"
    assert env["read"]("kr_movers.json")["collect"]["status"] == "failed"


def test_one_market_flows_failure_is_partial(env, monkeypatch):
    _krx(monkeypatch)
    w = World()
    w.flows["KOSDAQ"] = "error"
    env["run"](w)
    c = env["read"]("kr_flows.json")["collect"]
    assert c["status"] == "partial" and c["missing"] == ["flows:KOSDAQ:error"]
    assert set(env["read"]("kr_flows.json")) == {"KOSPI", "KOSDAQ", "collect"}


def test_econ_without_response_is_failed(env, monkeypatch):
    _krx(monkeypatch)
    env["run"]()                                               # 시험 하네스의 ECOS 가짜는 {} 를 준다
    c = env["read"]("kr_econ.json")["collect"]
    assert c["status"] == "failed" and c["as_of"] == D


def test_stance_absent_is_confirmed_none_but_corrupt_is_failed(env, monkeypatch):
    _krx(monkeypatch)
    env["run"]()
    c = env["read"]("kr_stance_eval.json")["collect"]
    assert c["status"] == "ok" and c["empty"] == "confirmed_none"
    (env["outdir"] / "kr_stance.json").write_text("{ broken", encoding="utf-8")
    env["run"]()
    c = env["read"]("kr_stance_eval.json")["collect"]
    assert c["status"] == "failed" and c["missing"] == ["kr_stance.json"]


# ── 순수 함수 ────────────────────────────────────────────────────────────

def test_econ_collect_rules():
    from kr import econ as kr_econ
    labels = [s[0] for s in kr_econ.SPECS]
    series = {lab: {"date": D, "value": 1.0} for lab in labels}
    series["한국은행 기준금리"] = {"date": "2026-10", "value": 2.5}
    ok = collect_kr_data.econ_collect(D, {"series": series, "missing": []})
    assert ok["status"] == "ok"
    stale = dict(series, **{labels[0]: {"date": "2026-11-11", "value": 1.0}})
    c = collect_kr_data.econ_collect(D, {"series": stale, "missing": []})
    assert c["status"] == "partial" and c["missing"] == [f"stale:{labels[0]}:2026-11-11"]
    c = collect_kr_data.econ_collect(D, {"pending": True, "note": "ECOS_API_KEY 미설정"})
    assert c["status"] == "failed"
    c = collect_kr_data.econ_collect(D, {"series": {}, "missing": labels})
    assert c["status"] == "failed"


def test_stance_collect_partial_when_close_missing():
    c = collect_kr_data.stance_collect(D, {"verdict": "판정불가", "metric": "KOSPI"}, "ok")
    assert c["status"] == "partial" and c["missing"] == ["indices.KOSPI"]
    c = collect_kr_data.stance_collect(D, {"verdict": "판정불가"}, "ok")
    assert c["missing"] == ["invalidation.level"]


def test_session_collect_counts_what_failed():
    # 계산된 창으로 판정한다(1a 구현 검토 #4) — 자세한 경우는 test_collect_freshness.py
    from kr import session as S
    hol = {"us": {"dates": [], "valid_through": "2027-12-31"}, "jp": {"dates": [], "valid_through": "2027-12-31"}}
    ctx = {"us_prev": {"as_of": "2026-11-11"},
           "us_futures_during_kr": {lab: {"pct": 0.1, "last_t": "15:30"} for lab, _ in S.FUTURES},
           "asia_peers": {"rows": {n: 0.1 for n, _ in S.PEERS}, "dates": {n: D for n, _ in S.PEERS}},
           "usdkrw_intraday": {"close": 1.0, "last_t": "15:30"}}
    assert collect_kr_data.session_collect(D, ctx, hol)["status"] == "ok"
    c = collect_kr_data.session_collect(D, dict(ctx, us_prev=None, usdkrw_intraday=None), hol)
    assert c["status"] == "partial" and "usdkrw" in c["missing"] and "us_market_data" in c["missing"]
