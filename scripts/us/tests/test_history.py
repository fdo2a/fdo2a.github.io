import json
import os

import pytest

from us.history import append_jsonl, macro_record, read_jsonl, stance_record

STANCE = {
    "report_date": "2026-08-21",
    "horizon": "2-6주",
    "assets": {
        "equities": {
            "grade": 1, "label": "소폭확대", "since": "2026-08-21",
            "thesis": "브레드스 확산 트리거 충족.",
            "tilt": "소재·헬스케어 확대",
            "triggers": {"increase": [{"kind": "metric", "metric": "spx_vs_50dma_pct",
                                       "op": ">", "value": 4.0, "toward": "+",
                                       "desc": "추세 확장 추가 확인"}],
                         "decrease": []},
        }
    },
}

MACRO = {
    "report_date": "2026-08-21",
    "regime": {"growth": 0, "inflation": 0, "since": "2026-08-17",
               "name": "교착", "thesis": "축 점수가 컷포인트 안쪽."},
    "policy_path": {"next_move": "인하", "timing": "2026-10", "prob": 0.62},
}


def test_stance_record_keeps_grades_and_drops_trigger_prose():
    r = stance_record(STANCE)
    assert r["report_date"] == "2026-08-21"
    eq = r["assets"]["equities"]
    assert eq["grade"] == 1
    assert eq["label"] == "소폭확대"
    assert eq["since"] == "2026-08-21"
    assert eq["thesis"] == "브레드스 확산 트리거 충족."
    # 트리거는 발동 판정에 필요한 필드만 남는다 — desc 산문은 버린다
    t = eq["triggers"]["increase"][0]
    assert t == {"kind": "metric", "metric": "spx_vs_50dma_pct",
                 "op": ">", "value": 4.0, "toward": "+"}


def test_macro_record_keeps_regime_and_policy():
    r = macro_record(MACRO)
    assert r["regime"]["growth"] == 0
    assert r["regime"]["name"] == "교착"
    assert r["policy_path"]["timing"] == "2026-10"


def test_append_jsonl_is_idempotent_on_report_date(tmp_path):
    p = os.path.join(tmp_path, "stance.jsonl")
    assert append_jsonl(p, stance_record(STANCE)) is True
    assert append_jsonl(p, stance_record(STANCE)) is False  # 같은 날짜 두 번 → 무시
    rows = read_jsonl(p)
    assert len(rows) == 1


def test_append_jsonl_keeps_rows_sorted_by_date(tmp_path):
    p = os.path.join(tmp_path, "stance.jsonl")
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
    p = os.path.join(tmp_path, "stance.jsonl")
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
