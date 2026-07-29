from collect_kr_data import completeness


def test_completeness_flags_missing():
    ok, missing = completeness({"indices": {}, "flows": None, "top_value": [],
                                "sectors": [], "themes": []})
    assert ok is False
    assert "flows" in missing


def test_completeness_passes_when_core_present():
    ok, missing = completeness({
        "indices": {"KOSPI": {"close": 2700}},
        "flows": {"latest_date": "2024-06-07"},
        "top_value": [{"label": "모나리자"}],
        "sectors": [{"name": "반도체"}],
        "themes": [{"name": "로봇"}],
    })
    assert ok is True and missing == []


def test_completeness_ignores_missing_themes():
    """테마 섹션 폐지(2026-07-29 사용자 지시) 후 themes 결측은 발행을 막지 않는다."""
    ok, missing = completeness({
        "indices": {"KOSPI": {"close": 2700}},
        "flows": {"latest_date": "2024-06-07"},
        "top_value": [{"label": "모나리자"}],
        "sectors": [{"name": "반도체"}],
        "themes": [],
    })
    assert ok is True and missing == []
