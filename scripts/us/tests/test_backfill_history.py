import json
import os

from backfill_history import backfill
from us.history import macro_record, read_jsonl


def _blob(date, direction):
    return json.dumps({"report_date": date, "horizon": "3-6개월",
                       "transmission": {"equities": {"direction": direction,
                                                     "since": date,
                                                     "confirm": "c"}}})


def test_backfill_writes_each_distinct_date(tmp_path):
    out = os.path.join(tmp_path, "macro.jsonl")
    n = backfill([_blob("2026-08-19", 0), _blob("2026-08-20", 1)], macro_record, out)
    assert n == 2
    assert [r["report_date"] for r in read_jsonl(out)] == ["2026-08-19", "2026-08-20"]


def test_backfill_is_idempotent(tmp_path):
    out = os.path.join(tmp_path, "macro.jsonl")
    blobs = [_blob("2026-08-19", 0), _blob("2026-08-20", 1)]
    backfill(blobs, macro_record, out)
    assert backfill(blobs, macro_record, out) == 0
    assert len(read_jsonl(out)) == 2


def test_backfill_skips_unparsable_blob(tmp_path):
    out = os.path.join(tmp_path, "macro.jsonl")
    n = backfill(["{ not json", _blob("2026-08-20", 1)], macro_record, out)
    assert n == 1


def test_backfill_dedupes_repeated_date_within_one_run(tmp_path):
    out = os.path.join(tmp_path, "macro.jsonl")
    # 같은 날짜가 여러 커밋에 걸쳐 나타난다 (그날 두 번 커밋된 경우)
    n = backfill([_blob("2026-08-20", 0), _blob("2026-08-20", 1)], macro_record, out)
    assert n == 1
