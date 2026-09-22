import json
import os

import pytest

from us.history import append_jsonl, macro_record, read_jsonl

MACRO = {
    "report_date": "2026-08-21",
    "regime": {"growth": 0, "inflation": 0, "since": "2026-08-17",
               "name": "교착", "thesis": "축 점수가 컷포인트 안쪽."},
    "policy_path": {"next_move": "인하", "timing": "2026-10", "prob": 0.62},
    "transmission": {
        "equities": {"direction": 1, "since": "2026-08-21",
                     "channel": "긴 산문 " * 40, "confirm": "ISM 50 상회"},
    },
}


def test_macro_record_keeps_direction_and_drops_the_channel_prose():
    r = macro_record(MACRO)
    assert r["report_date"] == "2026-08-21"
    eq = r["transmission"]["equities"]
    assert eq["direction"] == 1
    assert eq["since"] == "2026-08-21"
    assert eq["confirm"] == "ISM 50 상회"
    # 문단 하나가 자산마다 날마다 복사되면 원장이 산문으로 부푼다
    assert "channel" not in eq

def test_macro_record_keeps_regime_and_policy():
    r = macro_record(MACRO)
    assert r["regime"]["growth"] == 0
    assert r["regime"]["name"] == "교착"
    assert r["policy_path"]["timing"] == "2026-10"


def test_append_jsonl_is_idempotent_on_report_date(tmp_path):
    p = os.path.join(tmp_path, "macro.jsonl")
    assert append_jsonl(p, macro_record(MACRO)) is True
    assert append_jsonl(p, macro_record(MACRO)) is False  # 같은 날짜 두 번 → 무시
    rows = read_jsonl(p)
    assert len(rows) == 1


def test_append_jsonl_keeps_rows_sorted_by_date(tmp_path):
    p = os.path.join(tmp_path, "macro.jsonl")
    append_jsonl(p, {"report_date": "2026-08-21", "v": 2})
    append_jsonl(p, {"report_date": "2026-08-19", "v": 1})
    assert [r["report_date"] for r in read_jsonl(p)] == ["2026-08-19", "2026-08-21"]


def test_read_jsonl_missing_file_is_empty(tmp_path):
    assert read_jsonl(os.path.join(tmp_path, "nope.jsonl")) == []


def test_read_jsonl_skips_corrupt_line(tmp_path):
    p = os.path.join(tmp_path, "x.jsonl")
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"report_date": "2026-08-19"}) + "\n")
        fh.write("{ not json\n")
        fh.write(json.dumps({"report_date": "2026-08-20"}) + "\n")
    assert len(read_jsonl(p)) == 2


def test_append_jsonl_leaves_the_original_intact_when_writing_fails(tmp_path, monkeypatch):
    p = os.path.join(tmp_path, "macro.jsonl")
    append_jsonl(p, {"report_date": "2026-08-19", "v": 1})
    before = open(p, encoding="utf-8").read()

    import us.history as H

    real_open = open

    def boom(path, *a, **kw):
        if str(path).endswith(".tmp") or ".tmp" in str(path):
            raise OSError("disk full")
        return real_open(path, *a, **kw)

    monkeypatch.setattr(H, "open", boom, raising=False)
    with pytest.raises(OSError):
        append_jsonl(p, {"report_date": "2026-08-20", "v": 2})

    assert open(p, encoding="utf-8").read() == before
