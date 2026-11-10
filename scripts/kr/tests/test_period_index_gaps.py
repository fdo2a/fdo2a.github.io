"""주간 세션 날짜 × 지수 빈 칸을 missing 에 적는다 — complete 는 그대로(2026-11-10). 발행된 날의 빈 칸 보류는 versions_kr.

발행 때 지수 한쪽이 빠진 날은 새벽 재수집으로 자동 보완하지 않고 수동 정정한다. 그러려면
빈 칸이 사람에게 보여야 한다. spec: docs/superpowers/specs/2026-11-10-kr-data-versions.md
"""
from kr.period import finalize

SESS = {d: {"industry": {"반도체": 1.0}, "top_value": {}, "flows": {}} for d in
        ("2026-11-02", "2026-11-03", "2026-11-04")}


def _agg():
    return {"span": "weekly", "key": "2026-W45", "sessions": dict(SESS)}


def test_middle_day_gap_is_listed_and_complete_unchanged():
    closes = {"KOSPI": [("2026-10-30", 100.0), ("2026-11-02", 101.0), ("2026-11-03", 102.0), ("2026-11-04", 103.0)],
              "KOSDAQ": [("2026-10-30", 10.0), ("2026-11-02", 10.1), ("2026-11-04", 10.3)]}
    out = finalize(_agg(), closes)
    assert "indices.KOSDAQ.2026-11-03" in out["missing"]
    assert out["complete"] is True


def test_whole_index_absent_is_listed():
    closes = {"KOSPI": [("2026-10-30", 100.0), ("2026-11-02", 101.0), ("2026-11-03", 102.0), ("2026-11-04", 103.0)]}
    out = finalize(_agg(), closes)
    for d in SESS:
        assert f"indices.KOSDAQ.{d}" in out["missing"]


def test_last_day_gap_still_blocks_as_before():
    closes = {"KOSPI": [("2026-10-30", 100.0), ("2026-11-02", 101.0), ("2026-11-03", 102.0), ("2026-11-04", 103.0)],
              "KOSDAQ": [("2026-10-30", 10.0), ("2026-11-02", 10.1), ("2026-11-03", 10.2)]}
    out = finalize(_agg(), closes)
    assert out["complete"] is False
    assert "indices.KOSDAQ.2026-11-04" in out["missing"]


def test_no_gap_no_entry():
    closes = {n: [("2026-10-30", 1.0)] + [(d, 1.0) for d in SESS] for n in ("KOSPI", "KOSDAQ")}
    out = finalize(_agg(), closes)
    assert out["complete"] is True
    assert not [m for m in out["missing"] if m.startswith("indices.") and m.count(".") == 2]
