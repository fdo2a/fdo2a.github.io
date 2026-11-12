"""판 관리 — 재수집이 못 읽은 지수를 지우지 않고, 실행 manifest 가 검사 기록 사본을 남긴다(2026-11-12).

모드별: shadow·enforce 미발행은 수집기가 이미 합친 원장을 그대로 올리고, enforce 미발행 + 승격은 merge_ledger 가
지수별로 합친 뒤 승격을 맨 마지막에 덮는다. 발행된 날의 동결(빈 지수는 빈 채)은 test_versions_git 이 고정한다.
spec: docs/superpowers/specs/2026-11-12-kr-missing-vs-zero.md
"""
import json

import pytest

from kr import versions_kr as V
from kr.tests.test_versions_git import (D, PREV, clone, data, ledger, manifests, remote, run, sh,  # noqa: F401
                                        weekly, wj, world, write_day)

CHECKS = {"index_pct": {"mode": "warn", "config_status": "ok",
                        "KOSPI": {"status": "ok", "naver_pct": -6.02, "derived_pct": -6.021, "cross_note": True},
                        "KOSDAQ": {"status": "fetch_error"}},
          "flows": {"KOSPI": {"state": "ok", "faults": [{"date": PREV, "status": "partial", "fields": ["foreign"]}]},
                    "KOSDAQ": {"state": "blocked", "faults": [{"date": D, "status": "unreadable",
                                                               "fields": ["individual", "foreign", "institution"]}]}},
          "top_value": {"rows": 950, "dash": 70, "bad": 0, "dash_top100": 0, "positive_rows": 10}}


def test_run_checks_copies_the_whole_record():
    files = {V.MARKET_DATA: json.dumps({"report_date": D, "checks": CHECKS}).encode()}
    assert V.run_checks(files) == CHECKS


@pytest.mark.parametrize("files", [{}, {V.MARKET_DATA: b"{broken"}, {V.MARKET_DATA: b"[]"},
                                   {V.MARKET_DATA: json.dumps({"report_date": D}).encode()}])
def test_run_checks_unreadable(files):
    assert V.run_checks(files) == {"error": "unreadable"}


def test_checks_field_status_summary():
    fs = V.checks_field_status(CHECKS)
    assert fs == {"index_pct.KOSPI": "ok", "index_pct.KOSDAQ": "fetch_error", "index_pct.mode": "warn/ok",
                  "flows.KOSPI": "ok", "flows.KOSDAQ": "blocked", "top_value": "rows=950/dash=70/bad=0"}
    assert V.checks_field_status({"error": "unreadable"}) == {"checks": "unreadable"}
    assert V.checks_field_status({"index_pct": {}, "flows": {}, "top_value": {"error": "x"}})["top_value"] == "error"


# ── 연속 실행: 1차 두 지수 → 2차 코스닥 실패 ─────────────────────────────

def second_run_without_kosdaq(c):
    """2차 실행이 남긴 작업 트리 — 수집기는 원장에서 코스닥을 지우지 않는다(이미 합친 원장)."""
    files = data(D, kosdaq=None)
    md = files["kr/data/kr_market_data.json"]
    md.update(complete=False, missing=["indices"], checks=CHECKS)
    write_day(c, files, ledger(), weekly())


def _row(tmp, origin):
    return [r for r in remote(tmp, origin, "kr/data/history/kr_market.jsonl") if r["report_date"] == D][0]


@pytest.mark.parametrize("mode", ["shadow", "enforce"])
def test_second_run_kosdaq_failure_keeps_ledger_unpublished(world, mode):
    tmp, origin, _seed = world
    c = clone(tmp, origin)
    second_run_without_kosdaq(c)
    r = run(c, "commit", "--mode", mode, "--message", "data: kr market data for 2026-11-06")
    assert r.returncode == 0, r.stderr.decode()
    assert _row(tmp, origin)["indices"] == {"KOSPI": 5059.69, "KOSDAQ": 644.27}
    assert remote(tmp, origin, "kr/data/kr_market_data.json")["complete"] is False
    m = manifests(tmp, origin)[-1]
    assert m["checks"] == CHECKS
    assert m["field_status"]["index_pct.KOSDAQ"] == "fetch_error"
    assert m["field_status"]["flows.KOSDAQ"] == "blocked"


def test_second_run_kosdaq_failure_enforce_unpublished_with_promotion(world):
    tmp, origin, seed = world
    # 그 주에 사람이 올린 승격이 있다 → enforce 미발행에서 merge_ledger 가 돈다
    sh(seed, "git", "pull", "-q", "--rebase")
    wj(seed, f"versions/kr/{PREV}/promotions/001.json",
       {"field": "session.flows.KOSPI", "value": {"foreign": 1, "institution": 2, "individual": 3}})
    sh(seed, "git", "add", "-A")
    sh(seed, "git", "commit", "-q", "-m", "promote")
    sh(seed, "git", "push", "-q", "origin", "HEAD:main")
    c = clone(tmp, origin)
    second_run_without_kosdaq(c)
    r = run(c, "commit", "--mode", "enforce", "--message", "data: kr market data for 2026-11-06")
    assert r.returncode == 0, r.stderr.decode()
    assert _row(tmp, origin)["indices"] == {"KOSPI": 5059.69, "KOSDAQ": 644.27}
    wk = remote(tmp, origin, "kr/data/weekly/2026-W45.json")
    assert wk["_sessions"][PREV]["flows"]["KOSPI"] == {"foreign": 1, "institution": 2, "individual": 3}


def test_manifest_without_checks_in_market_data_says_unreadable(world):
    tmp, origin, _seed = world
    c = clone(tmp, origin)
    files = data(D)
    files["kr/data/kr_industry.json"][0]["change_pct"] = 9.9
    write_day(c, files, ledger(), weekly())
    assert run(c, "commit", "--mode", "shadow", "--message", "m").returncode == 0
    m = manifests(tmp, origin)[-1]
    assert m["checks"] == {"error": "unreadable"}
    assert m["field_status"]["checks"] == "unreadable"
