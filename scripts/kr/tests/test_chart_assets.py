"""KR 차트를 날짜별 파일로 내보내는 계약.

임베드는 원래 아카이브 장치였다 — `kr/data/kr_charts.png` 가 날짜 없는 한 이름이라
매일 덮어써지므로, 외부 참조로 바꾸면 과거 발행본 전부가 오늘 차트를 가리켰다. 날짜를
파일명에 넣어 그 이유를 없앤다.

날짜만으로는 부족하다. KR 워크플로는 하루 두 번(08:00·08:30) 돌고 수동 실행도 되므로
같은 거래일이 두 번 수집되면 이미 **발행된** 차트가 다른 바이트로 덮어써진다
(2026-09-06 codex 검토 1.3). 그래서 다른 바이트로는 덮어쓰지 않는다.
"""
import json

import pytest

from scripts.kr import charts as C

RAW = b"\x89PNG\r\n\x1a\n" + b"one" * 100
OTHER = b"\x89PNG\r\n\x1a\n" + b"two" * 100


def test_publish_writes_a_dated_file(tmp_path):
    rel = C.publish(str(tmp_path), "kr_charts", "2026-09-03", RAW)
    assert rel == "kr_charts_2026-09-03.png"
    assert (tmp_path / rel).read_bytes() == RAW


def test_publish_is_idempotent_for_the_same_bytes(tmp_path):
    C.publish(str(tmp_path), "kr_charts", "2026-09-03", RAW)
    assert C.publish(str(tmp_path), "kr_charts", "2026-09-03", RAW) == "kr_charts_2026-09-03.png"


def test_publish_refuses_to_overwrite_with_different_bytes(tmp_path):
    C.publish(str(tmp_path), "kr_charts", "2026-09-03", RAW)
    with pytest.raises(C.AssetConflict):
        C.publish(str(tmp_path), "kr_charts", "2026-09-03", OTHER)
    assert (tmp_path / "kr_charts_2026-09-03.png").read_bytes() == RAW


def test_manifest_records_what_was_produced(tmp_path):
    man = C.manifest({"kr_charts": RAW, "kr_flows_intraday": None}, "2026-09-03")
    assert man["report_date"] == "2026-09-03"
    assert man["charts"]["kr_charts"]["file"] == "kr_charts_2026-09-03.png"
    assert len(man["charts"]["kr_charts"]["sha256"]) == 64
    # 실패한 차트는 「없다」고 분명히 적는다 — 조용히 빠지면 writer 가 없는 파일을 가리킨다
    assert man["charts"]["kr_flows_intraday"] is None


def test_manifest_is_json_serialisable(tmp_path):
    json.dumps(C.manifest({"kr_charts": RAW}, "2026-09-03"))


def test_conflict_is_recorded_without_losing_the_collection(tmp_path):
    """차트는 프로젝트 계약상 비-코어다 —「없어도 발행 게이트 통과, 그 블록만 생략」.
    충돌이 예외로 올라가면 하루 두 번 도는 워크플로의 2회차가 시장·수급 JSON 저장에도
    닿지 못한다(2026-09-06 codex 검토 3)."""
    C.publish(str(tmp_path), "kr_charts", "2026-09-03", RAW)
    produced, notes = C.publish_all(str(tmp_path), "2026-09-03",
                                    {"kr_charts": OTHER, "kr_flows_intraday": RAW})
    assert produced["kr_charts"] is None          # 못 냈다
    assert produced["kr_flows_intraday"] is RAW   # 나머지는 살았다
    assert "충돌" in notes["kr_charts"]
    assert (tmp_path / "kr_charts_2026-09-03.png").read_bytes() == RAW  # 원본 보존


def test_manifest_carries_the_conflict_note():
    man = C.manifest({"kr_charts": None}, "2026-09-03", notes={"kr_charts": "충돌 — …"})
    assert man["charts"]["kr_charts"] is None
    assert man["notes"]["kr_charts"].startswith("충돌")
