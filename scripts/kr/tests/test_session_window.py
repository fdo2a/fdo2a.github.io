"""KR 장중 세션 창의 완결성(2026-11-17, 1a 구현 검토 2회차 F2).

전에는 그날 한국 정규장 창(09:00~15:30 KST)에 봉이 **있기만 하면** 선물·환율이 성공이었다 — 선물 봉 둘(09:00·09:30),
환율 봉 하나(09:00)뿐이어도 「장중 등락」으로 실렸다. 창의 마지막 봉이 마감 근처(`S.WINDOW_END`)까지 와야 완결이다.
기준은 실측으로 정했다: origin/main 의 kr_session.json 92판(발행일 54일)에서 선물 창이 있는 91판·환율 92판의 마지막
봉이 전부 15:30 이었다(설계 docs/superpowers/specs/2026-11-17-input-health.md 「2회차」). 네트워크를 쓰지 않는다.
"""
import datetime as dt

import collect_kr_data
from kr import session as S

D = "2026-11-16"
PREV = "2026-11-13"
HOL = {"us": {"dates": [], "valid_through": "2027-12-31"}, "jp": {"dates": [], "valid_through": "2027-12-31"}}


def fut_bars(times, day=D):
    return [{"t": dt.datetime.fromisoformat(f"{day}T{t}:00+09:00").isoformat(), "close": 100.0 + i}
            for i, t in enumerate(times)]


def fx_bars(times, day=D):
    return [{"t": dt.datetime.fromisoformat(f"{day}T{t}:00+09:00").isoformat(),
             "high": 1401.0 + i, "low": 1399.0, "close": 1400.0 + i} for i, t in enumerate(times)]


FULL = [f"{h:02d}:{m:02d}" for h in range(9, 16) for m in (0, 30)]          # 09:00 … 15:30, 14개


def ctx(fut_times=FULL, fx_times=FULL):
    return {"report_date": D,
            "us_prev": {"as_of": PREV, "rows": {"S&P 500": 0.1}},
            "us_futures_during_kr": {lab: S.kr_hours_window(fut_bars(fut_times), D) for lab, _ in S.FUTURES},
            "asia_peers": {"rows": {n: 0.1 for n, _ in S.PEERS}, "dates": {n: D for n, _ in S.PEERS}},
            "usdkrw_intraday": S.usdkrw_window(fx_bars(fx_times), D)}


def test_full_window_is_ok():
    c = collect_kr_data.session_collect(D, ctx(), HOL)
    assert c["status"] == "ok" and c["missing"] == [] and c["required_ok"] is True
    assert "15:00" in c["detail"] and "달력 없음" in c["detail"] and "미완결" not in c["detail"]   # 기준은 늘 적는다


def test_early_bars_only_is_partial_not_ok():
    # codex 재현: 선물 봉 둘(09:00·09:30), 환율 봉 하나(09:00) — 전에는 status ok
    x = ctx(fut_times=["09:00", "09:30"], fx_times=["09:00"])
    assert x["us_futures_during_kr"]["ES"] and x["usdkrw_intraday"]          # 창 함수는 결과를 만든다
    c = collect_kr_data.session_collect(D, x, HOL)
    assert c["status"] == "partial" and c["required_ok"] is False
    assert {"incomplete_window:ES", "incomplete_window:NQ", "incomplete_window:usdkrw"} <= set(c["missing"])
    assert "09:30" in c["detail"] and "09:00" in c["detail"]                  # 어디서 끊겼는지


def test_each_market_is_judged_separately():
    c = collect_kr_data.session_collect(D, ctx(fx_times=FULL[:6]), HOL)
    assert c["status"] == "partial" and c["missing"] == ["incomplete_window:usdkrw"]
    c = collect_kr_data.session_collect(D, ctx(fut_times=FULL[:6]), HOL)
    assert c["status"] == "partial" and c["missing"] == ["incomplete_window:ES", "incomplete_window:NQ"]


def test_threshold_boundary():
    end = "%02d:%02d" % S.WINDOW_END
    i = FULL.index(end)
    assert collect_kr_data.session_collect(D, ctx(fut_times=FULL[:i + 1], fx_times=FULL[:i + 1]), HOL)["status"] == "ok"
    c = collect_kr_data.session_collect(D, ctx(fut_times=FULL[:i], fx_times=FULL[:i]), HOL)
    assert c["status"] == "partial" and len([m for m in c["missing"] if m.startswith("incomplete_window:")]) == 3


def test_window_without_a_readable_last_bar_is_not_assumed_complete():
    x = ctx()
    x["us_futures_during_kr"]["ES"] = {"pct": 0.1}                            # 마지막 봉 시각이 없다
    x["usdkrw_intraday"] = {"close": 1400.0, "last_t": "late"}
    c = collect_kr_data.session_collect(D, x, HOL)
    assert c["status"] == "partial"
    assert "incomplete_window:ES:unknown" in c["missing"] and "incomplete_window:usdkrw:unknown" in c["missing"]


def test_basis_is_stated_and_no_early_close_is_inferred():
    # 조기 마감·개장 지연 달력이 없다 — 기준(정규장 15:30 KST, 여유 한 봉)을 detail 에 적고 다른 시각을 추정하지 않는다
    assert S.window_complete({"last_t": "15:30"}) == (True, None)
    ok, why = S.window_complete({"last_t": "12:00"})
    assert ok is False and "12:00" in why
    assert S.window_complete({"last_t": None})[0] is None and S.window_complete({})[0] is None
    c = collect_kr_data.session_collect(D, ctx(fut_times=FULL[:4]), HOL)
    assert "15:30" in c["detail"] and "달력" in c["detail"]


def test_absent_window_stays_the_old_missing_key():
    x = ctx()
    x["us_futures_during_kr"]["NQ"] = None
    x["usdkrw_intraday"] = None
    c = collect_kr_data.session_collect(D, x, HOL)
    assert "futures:NQ" in c["missing"] and "usdkrw" in c["missing"]
    assert not [m for m in c["missing"] if m.startswith("incomplete_window:")]
