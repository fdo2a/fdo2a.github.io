import json

import pytest

from kr import econ


def _search(rows):
    return {"StatisticSearch": {"list_total_count": len(rows), "row": rows}}


def _items(rows):
    return {"StatisticItemList": {"list_total_count": len(rows), "row": rows}}


def test_parse_search_takes_latest_non_empty_observation():
    payload = _search([
        {"TIME": "20260724", "DATA_VALUE": "2.812", "UNIT_NAME": "연%",
         "ITEM_NAME1": "국고채(3년)"},
        {"TIME": "20260727", "DATA_VALUE": "2.845", "UNIT_NAME": "연%",
         "ITEM_NAME1": "국고채(3년)"},
        {"TIME": "20260728", "DATA_VALUE": "", "UNIT_NAME": "연%",
         "ITEM_NAME1": "국고채(3년)"},
    ])
    out = econ.parse_series(payload)
    assert out["value"] == 2.845 and out["date"] == "2026-07-27"
    assert out["prev"] == 2.812 and out["prev_date"] == "2026-07-24"
    assert out["unit"] == "연%"


def test_parse_search_computes_change_in_bp_for_rate_units():
    payload = _search([
        {"TIME": "20260727", "DATA_VALUE": "2.800", "UNIT_NAME": "연%", "ITEM_NAME1": "x"},
        {"TIME": "20260728", "DATA_VALUE": "2.845", "UNIT_NAME": "연%", "ITEM_NAME1": "x"},
    ])
    assert econ.parse_series(payload)["bp"] == pytest.approx(4.5)


def test_parse_search_single_observation_has_no_prev():
    payload = _search([{"TIME": "20260728", "DATA_VALUE": "2.5",
                        "UNIT_NAME": "연%", "ITEM_NAME1": "x"}])
    out = econ.parse_series(payload)
    assert out["value"] == 2.5 and out["prev"] is None and out["bp"] is None


def test_parse_search_monthly_time_normalizes_to_month():
    payload = _search([{"TIME": "202606", "DATA_VALUE": "2.50",
                        "UNIT_NAME": "연%", "ITEM_NAME1": "기준금리"}])
    assert econ.parse_series(payload)["date"] == "2026-06"


def test_parse_search_returns_none_on_error_payload():
    err = {"RESULT": {"CODE": "INFO-200", "MESSAGE": "해당하는 데이터가 없습니다."}}
    assert econ.parse_series(err) is None
    assert econ.parse_series({"StatisticSearch": {"row": []}}) is None


def test_resolve_item_code_matches_by_name():
    payload = _items([
        {"ITEM_CODE": "010190000", "ITEM_NAME": "국고채(1년)", "CYCLE": "D"},
        {"ITEM_CODE": "010200000", "ITEM_NAME": "국고채(3년)", "CYCLE": "D"},
        {"ITEM_CODE": "010210000", "ITEM_NAME": "국고채(10년)", "CYCLE": "D"},
    ])
    assert econ.resolve_item_code(payload, "국고채(3년)") == "010200000"
    assert econ.resolve_item_code(payload, "국고채(10년)") == "010210000"


def test_resolve_item_code_ignores_whitespace_and_returns_none_when_absent():
    payload = _items([{"ITEM_CODE": "1", "ITEM_NAME": " 국고채(3년) ", "CYCLE": "D"}])
    assert econ.resolve_item_code(payload, "국고채(3년)") == "1"
    assert econ.resolve_item_code(payload, "회사채(3년, AA-)") is None
    assert econ.resolve_item_code({"RESULT": {"CODE": "INFO-100"}}, "국고채(3년)") is None


def test_build_url_never_returns_key_in_scrubbed_form():
    url = econ._url("SECRETKEY", "StatisticSearch", "json", "kr", 1, 5)
    assert "SECRETKEY" in url                      # 실제 호출 URL에는 키가 들어간다
    assert "SECRETKEY" not in econ.scrub(url)      # 로그·예외에 나가는 형태에는 없어야
    assert "***" in econ.scrub(url)


def test_scrub_masks_key_anywhere_in_text():
    txt = "HTTPError for https://ecos.bok.or.kr/api/StatisticSearch/ABCD1234EFGH/json/kr/1/5"
    assert "ABCD1234EFGH" not in econ.scrub(txt)


def test_collect_returns_pending_stub_without_key(monkeypatch):
    monkeypatch.delenv("ECOS_API_KEY", raising=False)
    out = econ.collect()
    assert out["pending"] is True and "series" not in out


def test_collect_shapes_series_and_marks_complete(monkeypatch):
    monkeypatch.setenv("ECOS_API_KEY", "TESTKEY")
    calls = []

    def fake_get(url, timeout=15):
        calls.append(url)
        if "StatisticItemList" in url:
            return _items([{"ITEM_CODE": "C1", "ITEM_NAME": n, "CYCLE": "D"}
                           for n in ("국고채(3년)", "국고채(10년)", "CD(91일)",
                                     "회사채(3년, AA-)")]
                          + [{"ITEM_CODE": "B1", "ITEM_NAME": "한국은행 기준금리",
                              "CYCLE": "M"}])
        return _search([
            {"TIME": "20260727", "DATA_VALUE": "2.800", "UNIT_NAME": "연%", "ITEM_NAME1": "x"},
            {"TIME": "20260728", "DATA_VALUE": "2.845", "UNIT_NAME": "연%", "ITEM_NAME1": "x"},
        ])

    monkeypatch.setattr(econ, "_get_json", fake_get)
    out = econ.collect()
    assert out.get("pending") is not True
    assert "국고채 3년" in out["series"]
    assert out["series"]["국고채 3년"]["value"] == 2.845
    assert out["series"]["국고채 3년"]["bp"] == pytest.approx(4.5)
    assert out["missing"] == []
    # 키가 산출물 어디에도 실리면 안 된다
    assert "TESTKEY" not in json.dumps(out, ensure_ascii=False)


def test_collect_survives_partial_failure(monkeypatch):
    monkeypatch.setenv("ECOS_API_KEY", "TESTKEY")

    def fake_get(url, timeout=15):
        if "StatisticItemList" in url:
            return _items([{"ITEM_CODE": "C1", "ITEM_NAME": "국고채(3년)", "CYCLE": "D"}])
        raise RuntimeError("boom")

    monkeypatch.setattr(econ, "_get_json", fake_get)
    out = econ.collect()
    # 전부 실패해도 예외를 던지지 않고 missing만 채운다 (econ은 비-코어)
    assert out["series"] == {} and out["missing"]
