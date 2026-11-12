"""codex 구현 검토 2회차 지적 4건의 재현 시험(2026-11-12).

spec: docs/superpowers/specs/2026-11-12-kr-missing-vs-zero.md
"""
import inspect
import json
import subprocess

import pytest

import collect_kr_data
from fund import kr_view
from kr import index_check as IC
from kr.history import StaleIndexData, ledger_conflicts
from kr.leadership import flag_leadership
from kr.period import finalize, merge_session, session_from
from kr.tests.test_collect_missing import D, D0, WEEK, World, env  # noqa: F401
from kr.tests.test_impl_review_1 import _flat_world, _seed_ledger


# ── #1 종가 중복 가드에는 예외가 없다 — 보합 검증(ok_flat)은 「오늘 종가」의 증거가 아니다 ──────

def test_both_closes_equal_to_another_row_stop_even_when_ok_flat(env):
    # 2회차 #1 재현 입력: 전 세션 종가가 R=0·D=0 과 함께 새 날짜로 오고 integration 전일 종가·수급 날짜가 맞는다.
    # 진짜 보합일과 입력이 같다 — 이 실행 안에서는 둘을 가를 수 없으므로 멈춘다.
    _seed_ledger(env, {"KOSPI": 1000.0, "KOSDAQ": 500.0})
    with pytest.raises(StaleIndexData):
        env["run"](_flat_world())
    assert not (env["outdir"] / "kr_market_data.json").exists()
    assert set(env["ledger"]()) == {D0}                       # 원장도 그대로


def test_guard_has_no_flat_exception_parameter():
    assert "verified_flat" not in inspect.signature(ledger_conflicts).parameters
    assert "verified_flat" not in inspect.signature(collect_kr_data.guard_session).parameters


def test_flat_day_with_different_closes_than_the_ledger_still_passes(env):
    # 보합 판정 자체(ok_flat)는 그대로 통과한다 — 막는 것은 「원장의 다른 날과 두 지수 종가가 모두 같은」 경우뿐이다
    _seed_ledger(env, {"KOSPI": 1000.0, "KOSDAQ": 480.0})
    m = env["run"](_flat_world())
    assert m["checks"]["index_pct"]["KOSPI"]["status"] == "ok_flat" and m["complete"] is True


# ── #2 업종 미판정(상승 종목 비율 결측)은 비주도가 아니다 ───────────────────────

def _lead(items):
    return {r["name"]: r for r in flag_leadership(items, ret_key="change_pct", value_key="breadth",
                                                  strong_note="폭넓은 상승 주도", weak_note="좁은 상승·개별종목")}


def test_rising_industry_with_missing_breadth_is_undecided_not_false():
    out = _lead([{"name": "A", "change_pct": 2.0, "breadth": None},
                 {"name": "B", "change_pct": 1.0, "breadth": 0.8},
                 {"name": "C", "change_pct": -0.5, "breadth": None}])
    assert out["A"]["leading"] is None and out["A"]["liquidity_backed"] is None and out["A"]["note"] == ""
    assert out["B"]["leading"] is True
    # 내린 업종은 상승 종목 비율이 없어도 주도가 아니다(판정에 비율이 필요 없다)
    assert out["C"]["leading"] is False and out["C"]["liquidity_backed"] is None
    solo = flag_leadership([{"name": "A", "change_pct": 1.0, "breadth": None}],
                           ret_key="change_pct", value_key="breadth")[0]
    assert solo["leading"] is None                           # 읽은 값이 하나도 없다 — 중앙값 없음


IND1 = [{"name": "반도체", "change_pct": 1.2, "breadth": 0.8, "leading": True},
        {"name": "은행", "change_pct": -0.4, "breadth": 0.2, "leading": False}]
IND2 = [{"name": "반도체", "change_pct": 1.5, "breadth": None, "leading": None},
        {"name": "은행", "change_pct": -0.3, "breadth": 0.2, "leading": False}]
MKT = {"report_date": D}


def test_session_records_undecided_industries():
    s = session_from(MKT, {}, IND2, [])
    assert s["leading_industries"] == [] and s["leading_undecided"] == ["반도체"]
    assert "leading_undecided" not in session_from(MKT, {}, IND1, [])      # 평소 세션 모양은 그대로


def _body(s):
    return {k: v for k, v in s.items() if k != "date"}


def test_undecided_recollection_does_not_erase_same_day_leading():
    # 2회차 #2 재현: 앞 실행 반도체 breadth 0.8·주도 → 재수집에서 breadth 결측
    out = merge_session(_body(session_from(MKT, {}, IND1, [])), _body(session_from(MKT, {}, IND2, [])))
    assert out["leading_industries"] == ["반도체"]
    assert out["industry"] == {"반도체": 1.5, "은행": -0.3}      # 등락률은 새 값
    assert "leading_undecided" not in out                      # 앞 실행의 판정으로 풀렸다


def test_undecided_recollection_keeps_only_names_it_could_not_judge():
    ex = {"industry": {"A": 1.0, "B": 2.0}, "leading_industries": ["B", "A"]}
    new = _body(session_from(MKT, {}, [
        {"name": "A", "change_pct": 3.0, "breadth": None, "leading": None},      # 미판정 — 앞 판정 유지
        {"name": "B", "change_pct": 2.0, "breadth": 0.1, "leading": False},      # 판정됨(비주도) — 새 값
        {"name": "C", "change_pct": 1.0, "breadth": 0.9, "leading": True},
        {"name": "E", "change_pct": 0.5, "breadth": None, "leading": None}], []))
    out = merge_session(ex, new)
    assert out["leading_industries"] == ["A", "C"]             # 새 등락률 순
    assert out["leading_undecided"] == ["E"]                   # 앞 실행에도 판정이 없던 업종만 남는다


def test_decided_recollection_with_no_leaders_still_replaces():
    # 판정이 된 재수집의 「주도 없음」은 정상이다(4회차 설계 #1) — 미판정이 없으면 예전처럼 통째로 바꾼다
    ex = {"industry": {"반도체": 1.0}, "leading_industries": ["반도체"]}
    new = _body(session_from(MKT, {}, [{"name": "반도체", "change_pct": -1.0, "breadth": 0.1, "leading": False}], []))
    assert merge_session(ex, new)["leading_industries"] == []


def test_failed_industry_recollection_keeps_existing_undecided_list():
    ex = _body(session_from(MKT, {}, IND2, []))
    out = merge_session(ex, _body(session_from(MKT, {}, [], [])))
    assert out["industry"] == ex["industry"] and out["leading_undecided"] == ["반도체"]


def test_weekly_daily_row_shows_undecided_count():
    s = session_from(MKT, {}, IND2, [])
    fin = finalize({"span": "weekly", "key": WEEK, "sessions": {D: _body(s)}}, {})
    assert fin["daily"] == [{"date": D, "leading_industries": [], "leading_undecided_count": 1}]
    fin = finalize({"span": "weekly", "key": WEEK, "sessions": {D: _body(session_from(MKT, {}, IND1, []))}}, {})
    assert fin["daily"] == [{"date": D, "leading_industries": ["반도체"]}]


def test_collector_second_run_with_unread_breadth_keeps_weekly_leading(env):
    env["run"]()
    assert env["weekly"]()["_sessions"][D]["leading_industries"] == ["반도체"]
    w = World()
    w.industry = [{"name": "반도체", "change_pct": 1.2, "total": None, "rise": None, "breadth": None, "no": 1},
                  {"name": "은행", "change_pct": -0.4, "total": 10, "rise": 2, "breadth": 0.2, "no": 2}]
    env["run"](w)
    assert env["weekly"]()["_sessions"][D]["leading_industries"] == ["반도체"]
    rows = {r["name"]: r for r in env["read"]("kr_industry.json")}
    assert rows["반도체"]["leading"] is None                    # 작성자 입력: 미판정(null), 비주도(false) 아님
    assert rows["은행"]["leading"] is False


def test_fund_observation_carries_undecided_as_none():
    obs = kr_view._observations(None, [{"name": "반도체와반도체장비", "change_pct": 0.3, "breadth": None,
                                        "leading": None}], [], D)
    ind = next(o for o in obs if o["kind"] == "industry")
    assert ind["leading"] is None and ind["breadth"] is None


# ── #3 관찰 보고: 검사가 불완전한 실행에서 확인된 불일치도 합계에 든다 ─────────────

def _row(date, kospi, kosdaq, kx=False, qx=False, rid="r1"):
    def e(st, x):
        return None if st is None else {"status": st, "naver_pct": 1.0, "derived_pct": 1.0, "cross_note": x}
    ip = {"mode": "warn", "config_status": "ok"}
    for k, v in (("KOSPI", e(kospi, kx)), ("KOSDAQ", e(kosdaq, qx))):
        if v is not None:
            ip[k] = v
    return (date, rid, {"checks": {"index_pct": ip}})


def test_confirmed_mismatch_in_incomplete_run_is_counted():
    days = [f"2026-10-{d:02d}" for d in range(12, 22)]
    mans = [_row(d, "ok", "ok") for d in days]
    mans.append(_row("2026-10-22", "mismatch", "fetch_error"))
    mans.append(_row("2026-10-23", "fetch_error", "ok", qx=True))
    mans.append(("2026-10-24", "r1", None))
    s = IC.summary(IC.report_rows(mans))
    assert s["trade_days"] == 10 and s["runs"] == 10             # 관찰 일수는 그대로(불완전 실행은 세지 않는다)
    assert s["mismatch_or_cross_note_runs"] == 2
    assert s["mismatch_or_cross_note_days"] == ["2026-10-22", "2026-10-23"]
    assert s["mismatch_or_cross_note_incomplete_runs"] == 2
    assert s["unreadable_days"] == ["2026-10-22", "2026-10-23", "2026-10-24"]


def test_report_cli_prints_incomplete_run_mismatch_in_totals(monkeypatch, capsys):
    mans = [_row("2026-10-21", "ok", "ok"), _row("2026-10-22", "mismatch", "fetch_error")]
    monkeypatch.setattr(IC, "run_manifests", lambda root, rev="origin/main", dates=None: mans)
    assert IC.main(["--report"]) == 0
    out = capsys.readouterr().out
    assert "mismatch/cross_note 실행 1" in out and "2026-10-22" in out
    assert "검사 불완전 실행 1건 포함" in out


def test_run_manifests_survives_one_show_exception(monkeypatch):
    def fake(root, *args):
        if args[0] == "ls-tree":
            out = b"versions/kr/2026-11-11/runs/r1/manifest.json\nversions/kr/2026-11-12/runs/r1/manifest.json\n"
            return subprocess.CompletedProcess(args, 0, out, b"")
        if "2026-11-11" in args[1]:
            raise subprocess.TimeoutExpired("git", 120)
        return subprocess.CompletedProcess(args, 0, json.dumps({"checks": {}}).encode(), b"")
    monkeypatch.setattr(IC, "_git", fake)
    got = IC.run_manifests("x", "HEAD")
    assert [(d, m is None) for d, _, m in got] == [("2026-11-11", True), ("2026-11-12", False)]


# ── 3회차 #5: 표시용 상위 5개에서 밀린 앞 실행의 주도 판정도 다음 재수집까지 남는다 ────────

def _ind(*rows):
    return [{"name": n, "change_pct": c, "breadth": (None if lead is None else 0.5), "leading": lead}
            for n, c, lead in rows]


def test_carried_leader_cut_by_cap_survives_a_third_run():
    r1 = _body(session_from(MKT, {}, _ind(("A", 1.0, True), ("Z", -1.0, False)), []))
    r2 = _body(session_from(MKT, {}, _ind(("A", 1.0, None), *[(f"L{i}", 9.0 - i, True) for i in range(5)]), []))
    r3 = _body(session_from(MKT, {}, _ind(("A", 1.0, None), *[(f"L{i}", -1.0, False) for i in range(5)]), []))
    s2 = merge_session(r1, r2)
    assert s2["leading_industries"] == ["L0", "L1", "L2", "L3", "L4"]      # 표시는 상위 5개
    assert s2["leading_all"][-1] == "A" and "leading_undecided" not in s2  # 판정 상태는 따로 남는다
    s3 = merge_session(s2, r3)
    assert s3["leading_industries"] == ["A"] and "leading_undecided" not in s3
    assert "leading_all" not in s3                                         # 5개 이하면 표시 목록이 전부다


def test_leader_beyond_cap_in_first_run_survives_an_undecided_rerun():
    r1 = _body(session_from(MKT, {}, _ind(*[(f"L{i}", 9.0 - i, True) for i in range(6)]), []))
    assert r1["leading_industries"] == ["L0", "L1", "L2", "L3", "L4"] and r1["leading_all"][-1] == "L5"
    r2 = _body(session_from(MKT, {}, _ind(("L5", 3.0, None), *[(f"L{i}", -1.0, False) for i in range(5)]), []))
    s2 = merge_session(r1, r2)
    assert s2["leading_industries"] == ["L5"] and "leading_undecided" not in s2


def test_failed_industry_recollection_keeps_full_leading_state():
    r1 = _body(session_from(MKT, {}, _ind(*[(f"L{i}", 9.0 - i, True) for i in range(6)]), []))
    out = merge_session(r1, _body(session_from(MKT, {}, [], [])))
    assert out["leading_all"] == r1["leading_all"] and out["leading_industries"] == r1["leading_industries"]


def test_decided_rerun_drops_stale_full_state():
    r1 = _body(session_from(MKT, {}, _ind(*[(f"L{i}", 9.0 - i, True) for i in range(6)]), []))
    out = merge_session(r1, _body(session_from(MKT, {}, _ind(("L0", 1.0, True), ("L5", -1.0, False)), [])))
    assert out["leading_industries"] == ["L0"] and "leading_all" not in out
