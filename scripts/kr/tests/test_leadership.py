from kr.leadership import flag_leadership


def test_leading_requires_return_and_liquidity():
    items = [
        {"name": "반도체", "ret": 5.0, "value": 1000},   # 상승 + 고유동성
        {"name": "잡주섹터", "ret": 8.0, "value": 10},    # 상승 but 저유동성
        {"name": "음식료", "ret": -2.0, "value": 1000},   # 하락
    ]
    out = {it["name"]: it for it in flag_leadership(items)}
    assert out["반도체"]["leading"] is True
    assert out["반도체"]["note"] == "유동성 동반 주도"
    assert out["잡주섹터"]["leading"] is False
    assert out["잡주섹터"]["note"] == "저유동성 급등·개별이슈"
    assert out["음식료"]["leading"] is False
    assert out["음식료"]["note"] == ""


def test_empty_list_is_safe():
    assert flag_leadership([]) == []
