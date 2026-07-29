from kr.etf_normalize import classify_ticker, normalize_top_value


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
