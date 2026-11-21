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


# ── 같은 날 여러 커밋: 매일 쌓는 경로와 같은 값을 고른다(2026-11-22) ─────────────────────
# 시세 원장은 매일 upsert(마지막 실행이 이김) — 발행본이 마지막 실행의 스냅샷이라서다.
# 메우기가 첫 커밋을 집으면 발행본과 다른 숫자가 원장에 들어간다.

from us.history import market_record  # noqa: E402
from kr.history import index_record, merge_index_record  # noqa: E402
from backfill_history import LAST, merge_with  # noqa: E402


def _mkt(date, spx, ten=None):
    d = {"report_date": date, "indices": {"S&P 500": {"last": spx}}}
    if ten is not None:
        d["yields"] = {"10Y": {"level": ten}}
    return json.dumps(d)


def test_market_backfill_takes_the_last_commit_of_the_day(tmp_path):
    out = os.path.join(tmp_path, "market.jsonl")
    n = backfill([_mkt("2026-08-20", 6000.0, 4.10), _mkt("2026-08-20", 6010.0, 4.12)],
                 market_record, out, pick=LAST)
    assert n == 1
    row, = read_jsonl(out)
    assert row["indices"]["S&P 500"] == 6010.0 and row["yields"]["10Y"] == 4.12


def test_last_pick_is_per_date_and_keeps_date_order(tmp_path):
    out = os.path.join(tmp_path, "market.jsonl")
    blobs = [_mkt("2026-08-19", 1.0), _mkt("2026-08-20", 2.0), _mkt("2026-08-19", 3.0)]
    backfill(blobs, market_record, out, pick=LAST)
    assert [(r["report_date"], r["indices"]["S&P 500"]) for r in read_jsonl(out)] == \
        [("2026-08-19", 3.0), ("2026-08-20", 2.0)]


def test_last_pick_never_overwrites_an_existing_row(tmp_path):
    out = os.path.join(tmp_path, "market.jsonl")
    backfill([_mkt("2026-08-20", 6000.0)], market_record, out, pick=LAST)
    assert backfill([_mkt("2026-08-20", 7000.0)], market_record, out, pick=LAST) == 0
    assert read_jsonl(out)[0]["indices"]["S&P 500"] == 6000.0


def test_last_pick_ignores_a_later_unparsable_blob(tmp_path):
    out = os.path.join(tmp_path, "market.jsonl")
    backfill([_mkt("2026-08-20", 6000.0), "{ not json"], market_record, out, pick=LAST)
    assert read_jsonl(out)[0]["indices"]["S&P 500"] == 6000.0


def test_macro_backfill_stays_first_come(tmp_path):
    # 판단 이력은 그날 책이 하나 — 매일 경로도 선착순이다
    out = os.path.join(tmp_path, "macro.jsonl")
    backfill([_blob("2026-08-20", 0), _blob("2026-08-20", 1)], macro_record, out)
    assert read_jsonl(out)[0]["transmission"]["equities"]["direction"] == 0


def _kr(date, **closes):
    return json.dumps({"report_date": date,
                       "indices": {k: {"close": v, "pct": 0.1} for k, v in closes.items()}})


def test_kr_backfill_folds_same_day_commits_like_the_daily_merge(tmp_path):
    out = os.path.join(tmp_path, "kr_market.jsonl")
    blobs = [_kr("2026-11-12", KOSPI=2500.0, KOSDAQ=800.0), _kr("2026-11-12", KOSPI=2510.0)]
    backfill(blobs, index_record, out, pick=merge_with(merge_index_record))
    row, = read_jsonl(out)
    # 매일 경로: merge_index_record(앞 행, 새 행) — 새 값이 이기고, 새 행에 없는 지수는 앞 값을 지킨다
    expect = merge_index_record(index_record(json.loads(blobs[0])), index_record(json.loads(blobs[1])))
    assert row == expect
