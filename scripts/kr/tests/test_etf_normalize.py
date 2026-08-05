from kr.etf_normalize import classify_ticker, normalize_top_value, resolve_theme


def test_classify_plain_stock():
    c = classify_ticker("모나리자")
    assert c["is_etf"] is False and c["kind"] == "stock"


def test_classify_single_stock_leverage_extracts_underlying_and_direction():
    for nm in ("KODEX SK하이닉스단일종목레버리지", "TIGER SK하이닉스단일종목레버리지"):
        c = classify_ticker(nm)
        assert c["kind"] == "single_stock_lev"
        assert c["underlying"] == "SK하이닉스" and c["direction"] == "long"
    c = classify_ticker("SOL SK하이닉스선물단일종목인버스2X")
    assert c["kind"] == "single_stock_lev"
    assert c["underlying"] == "SK하이닉스" and c["direction"] == "short"


def test_classify_index_leverage_direction():
    assert classify_ticker("KODEX 코스닥150레버리지")["direction"] == "long"
    for nm in ("KODEX 200선물인버스2X", "KODEX 인버스"):
        c = classify_ticker(nm)
        assert c["kind"] == "index_lev" and c["direction"] == "short"


def test_classify_overseas_etf():
    assert classify_ticker("TIGER 미국S&P500")["kind"] == "overseas_etf"


def test_classify_plain_index_tracker():
    """레버리지가 아닌 순수 지수추종 ETF도 '지수 관련'으로 잡는다 (2026-07-29 사용자 지시)."""
    for nm in ("KODEX 200", "TIGER 200", "KODEX 코스닥150", "KOSEF 200TR", "KODEX 코스피"):
        assert classify_ticker(nm)["kind"] == "index_etf", nm


def test_classify_index_token_with_residual_stays_sector():
    """지수 토큰이 있어도 기초자산이 남으면 섹터/테마 ETF다 — 과잉 제외 방지."""
    for nm in ("TIGER 200 IT", "TIGER 코스피고배당", "TIGER 반도체TOP10"):
        assert classify_ticker(nm)["kind"] == "sector_theme_etf", nm


def test_normalize_merges_dedups_and_drops():
    rows = [
        {"name": "KODEX 200선물인버스2X", "value": 900, "volume": 100},
        {"name": "KODEX 인버스", "value": 500, "volume": 50},
        {"name": "SOL SK하이닉스선물단일종목인버스2X", "value": 300, "volume": 30},
        {"name": "KODEX SK하이닉스단일종목레버리지", "value": 400, "volume": 40},
        {"name": "TIGER SK하이닉스단일종목레버리지", "value": 200, "volume": 20},
        {"name": "KODEX 삼성전자단일종목레버리지", "value": 350, "volume": 35},
        {"name": "TIGER 삼성전자단일종목레버리지", "value": 150, "volume": 15},
        {"name": "TIGER 미국S&P500", "value": 600, "volume": 60},
        {"name": "KODEX 미국S&P500", "value": 550, "volume": 55},
        {"name": "KODEX 200", "value": 800, "volume": 80},
        {"name": "TIGER 반도체TOP10", "value": 120, "volume": 12},
        {"name": "모나리자", "value": 250, "volume": 25},
    ]
    out = normalize_top_value(rows, top_n=10)
    labels = [g["label"] for g in out]
    # 해외 ETF 제거
    assert not any("S&P500" in l for l in labels)
    # 지수 관련 ETF 전부 제거 — 레버리지·인버스·순수 지수추종 (2026-07-29 사용자 지시)
    assert not any(g["kind"] in ("index_lev", "index_etf") for g in out)
    assert not any("지수" in l or l == "KODEX 200" for l in labels)
    # 지수 줄이 빠진 자리에 실체 있는 종목이 올라온다
    assert out[0]["label"] == "SK하이닉스 레버리지" and out[0]["value"] == 600
    # 섹터/테마 ETF는 유지
    assert "TIGER 반도체TOP10" in labels
    # SK하이닉스 레버리지(롱) = 400+200 = 600, members 2 (인버스는 분리)
    sk_lev = next(g for g in out if g["label"] == "SK하이닉스 레버리지")
    assert sk_lev["value"] == 600 and len(sk_lev["members"]) == 2
    # SK하이닉스 인버스(숏) = 300, 별도 줄
    sk_inv = next(g for g in out if g["label"] == "SK하이닉스 인버스")
    assert sk_inv["value"] == 300 and sk_inv["direction"] == "short"
    # 삼성전자 레버리지 = 350+150 = 500
    ss = next(g for g in out if g["label"] == "삼성전자 레버리지")
    assert ss["value"] == 500 and len(ss["members"]) == 2
    # 실종목 유지
    assert any(g["label"] == "모나리자" and g["kind"] == "stock" for g in out)


# --- 섹터/테마 ETF 테마 병합 (2026-08-06 사용자 지시) --------------------------

def test_resolve_theme_maps_semiconductor_variants():
    """넓은 바스켓(반도체TOP10)과 집중 바스켓(AI반도체TOP2)을 같은 테마로 본다 —
    알고 싶은 건 '반도체 바스켓에 돈이 얼마 갔나'다."""
    for nm in ("TIGER 반도체TOP10", "SOL AI반도체TOP2플러스",
               "KODEX 반도체레버리지", "KODEX AI반도체TOP2플러스", "KODEX 반도체"):
        assert resolve_theme(nm) == "반도체", nm


def test_resolve_theme_returns_none_for_unmapped():
    """사전에 없으면 None — 폴백은 안전한 쪽(제 이름으로 남는다)."""
    assert resolve_theme("TIGER 코스피고배당") is None
    assert resolve_theme("모나리자") is None


def test_normalize_merges_same_theme_etfs_into_one_row():
    rows = [
        {"name": "TIGER 반도체TOP10", "value": 380, "volume": 38},
        {"name": "KODEX 반도체레버리지", "value": 320, "volume": 32},
        {"name": "SOL AI반도체TOP2플러스", "value": 280, "volume": 28},
        {"name": "대원전선", "value": 680, "volume": 68},
    ]
    out = normalize_top_value(rows, top_n=10)
    semi = next(g for g in out if g["kind"] == "sector_theme_etf")
    assert semi["label"] == "반도체 테마 ETF"
    assert semi["theme"] == "반도체"
    assert semi["value"] == 980
    assert semi["volume"] == 98
    assert len(semi["members"]) == 3
    # 쪼개져 있을 땐 셋 다 대원전선 아래였지만, 묶이면 위로 올라온다
    assert out[0]["label"] == "반도체 테마 ETF"


def test_normalize_keeps_own_name_when_theme_has_single_member():
    """한 종목뿐이면 병합이 일어나지 않았으므로 '테마 ETF'라 부르지 않는다."""
    rows = [{"name": "TIGER 반도체TOP10", "value": 380, "volume": 38}]
    out = normalize_top_value(rows, top_n=10)
    assert out[0]["label"] == "TIGER 반도체TOP10"
    assert out[0]["theme"] == "반도체"


def test_normalize_splits_theme_etfs_by_direction():
    """인버스 섹터 ETF는 기존 롱/숏 분리 규칙대로 별도 줄."""
    rows = [
        {"name": "TIGER 반도체TOP10", "value": 300, "volume": 30},
        {"name": "KODEX 반도체레버리지", "value": 200, "volume": 20},
        {"name": "KODEX 반도체인버스", "value": 150, "volume": 15},
        {"name": "TIGER 반도체인버스2X", "value": 90, "volume": 9},
    ]
    out = normalize_top_value(rows, top_n=10)
    lon = next(g for g in out if g["label"] == "반도체 테마 ETF")
    sht = next(g for g in out if g["label"] == "반도체 테마 ETF (인버스)")
    assert lon["value"] == 500 and lon["direction"] == "long"
    assert sht["value"] == 240 and sht["direction"] == "short"


def test_normalize_unmapped_theme_etfs_stay_separate():
    rows = [
        {"name": "TIGER 코스피고배당", "value": 300, "volume": 30},
        {"name": "TIGER 200 IT", "value": 200, "volume": 20},
    ]
    labels = [g["label"] for g in normalize_top_value(rows, top_n=10)]
    assert labels == ["TIGER 코스피고배당", "TIGER 200 IT"]


def test_normalize_does_not_merge_across_different_themes():
    rows = [
        {"name": "TIGER 반도체TOP10", "value": 300, "volume": 30},
        {"name": "KODEX 반도체레버리지", "value": 200, "volume": 20},
        {"name": "PLUS K방산", "value": 150, "volume": 15},
        {"name": "SOL 조선TOP3플러스", "value": 140, "volume": 14},
    ]
    out = normalize_top_value(rows, top_n=10)
    themes = {g.get("theme") for g in out}
    assert themes == {"반도체", "방산", "조선"}
    assert next(g for g in out if g.get("theme") == "반도체")["value"] == 500
