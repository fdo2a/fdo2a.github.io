"""codex 구현 검토 1회차 지적 5건의 재현 시험(2026-11-12).

spec: docs/superpowers/specs/2026-11-12-kr-missing-vs-zero.md
"""
import json

import pytest

import collect_kr_data
from kr import index_check as IC
from kr import sources
from kr.history import StaleIndexData, ledger_conflicts
from kr.leadership import flag_leadership
from kr.tests.test_collect_missing import D, D0, World, env  # noqa: F401


# ── #1 검증된 진짜 보합일이 2026-10-17 원장 가드(종가 중복)에 막힌다 ────────────

def _flat_world(biz_ok=True):
    w = World()
    w.basic = {"KOSPI": dict(close=1000.0, change_pct=0.0, prev_diff=0.0),
               "KOSDAQ": dict(close=500.0, change_pct=0.0, prev_diff=0.0)}
    w.integ = {"KOSPI": dict(prevClose=1000.0, high=1005.0, low=995.0),
               "KOSDAQ": dict(prevClose=500.0, high=505.0, low=495.0)}
    return w


def _seed_ledger(env_, row):
    p = env_["outdir"] / "history"
    p.mkdir(parents=True, exist_ok=True)
    (p / "kr_market.jsonl").write_text(json.dumps({"report_date": D0, "indices": row}) + "\n")


def test_verified_flat_day_passes_the_duplicate_close_guard(env):
    _seed_ledger(env, {"KOSPI": 1000.0, "KOSDAQ": 500.0})
    m = env["run"](_flat_world())
    assert m["checks"]["index_pct"]["KOSPI"]["status"] == "ok_flat"
    assert m["checks"]["index_pct"]["KOSDAQ"]["status"] == "ok_flat"
    assert m["complete"] is True
    assert env["ledger"]()[D] == {"KOSPI": 1000.0, "KOSDAQ": 500.0}


def test_duplicate_closes_without_flat_verification_still_stop(env):
    # 같은 세션이 두 날짜에 적히는 경우(가드의 목적) — 등락률이 0 이 아니면 보합 증명이 없다
    _seed_ledger(env, {"KOSPI": 5342.73, "KOSDAQ": 700.0})
    with pytest.raises(StaleIndexData):
        env["run"](World())
    assert not (env["outdir"] / "kr_market_data.json").exists()


def test_flat_without_session_marker_still_stops(env, monkeypatch):
    # integration 이 이 세션 값이라는 표식(flow_bizdate)이 없으면 날짜 오기록을 배제할 수 없다
    _seed_ledger(env, {"KOSPI": 1000.0, "KOSDAQ": 500.0})
    real = sources.fetch_index_ohlc
    monkeypatch.setattr(sources, "fetch_index_ohlc", lambda code: {**real(code), "flow_bizdate": "20261111"})
    with pytest.raises(StaleIndexData):
        env["run"](_flat_world())


def test_single_surviving_index_equal_to_other_day_stays_stopped(env):
    # 보수적으로 정했다: 한 지수만 남은 실행은 보합이 검증돼도 통과시키지 않는다(이 실행은 어차피 발행 불가)
    _seed_ledger(env, {"KOSPI": 1000.0, "KOSDAQ": 480.0})
    w = _flat_world()
    w.basic.pop("KOSDAQ")
    with pytest.raises(StaleIndexData):
        env["run"](w)


def test_ledger_conflicts_verified_flat_only_skips_the_duplicate_check():
    rows = [{"report_date": "2026-11-11", "indices": {"KOSPI": 1.0, "KOSDAQ": 2.0}}]
    rec = {"report_date": "2026-11-12", "indices": {"KOSPI": 1.0, "KOSDAQ": 2.0}}
    assert ledger_conflicts(rows, rec)
    assert ledger_conflicts(rows, rec, verified_flat={"KOSPI", "KOSDAQ"}) == []
    assert ledger_conflicts(rows, rec, verified_flat={"KOSPI"})
    early = {"report_date": "2026-11-10", "indices": {"KOSPI": 9.0, "KOSDAQ": 9.0}}
    assert ledger_conflicts(rows, early, verified_flat={"KOSPI", "KOSDAQ"})   # 이른 날짜는 그대로 막는다


# ── #2 업종 상승 종목 수 결측이 0 으로 ───────────────────────────────────

def test_fetch_industry_missing_counts_stay_missing(monkeypatch):
    monkeypatch.setattr(sources, "fetch_json", lambda url, timeout=12: {"groups": [
        {"no": 1, "name": "반도체", "changeRate": "1.0", "totalCount": 10},
        {"no": 2, "name": "은행", "changeRate": "0.5", "riseCount": "3"},
        {"no": 3, "name": "건설", "changeRate": "0.2", "totalCount": "0", "riseCount": "0"},
        {"no": 4, "name": "화학", "changeRate": "0.3", "totalCount": 10, "riseCount": "4"}]})
    rows = {r["name"]: r for r in sources.fetch_industry()}
    assert rows["반도체"]["rise"] is None and rows["반도체"]["breadth"] is None
    assert rows["은행"]["total"] is None and rows["은행"]["breadth"] is None
    assert rows["건설"]["breadth"] is None                  # 0 종목 — 비율을 낼 수 없다
    assert rows["화학"]["breadth"] == 0.4


def test_leadership_with_missing_breadth_is_neither_leading_nor_narrow():
    items = [{"name": "A", "change_pct": 2.0, "breadth": None},
             {"name": "B", "change_pct": 1.0, "breadth": 0.8},
             {"name": "C", "change_pct": 0.5, "breadth": 0.2}]
    out = {r["name"]: r for r in flag_leadership(items, ret_key="change_pct", value_key="breadth",
                                                  strong_note="폭넓은 상승 주도", weak_note="좁은 상승·개별종목")}
    assert out["A"]["leading"] is False and out["A"]["liquidity_backed"] is None and out["A"]["note"] == ""
    assert out["B"]["leading"] is True
    assert out["C"]["note"] == "좁은 상승·개별종목"
    assert flag_leadership([{"name": "A", "change_pct": 1.0, "breadth": None}],
                           ret_key="change_pct", value_key="breadth")[0]["leading"] is False


# ── #5 비 UTF-8 설정이 수집을 멈춘다 ─────────────────────────────────────

def test_non_utf8_config_reads_as_block(tmp_path, capsys):
    p = tmp_path / "kr_index_check.json"
    p.write_bytes(b'{"format": "kr-index-check/1", "mismatch": "warn\xff"}')
    assert IC.load_mode(str(p)) == ("block", "invalid_block")
    assert "::warning::" in capsys.readouterr().out
