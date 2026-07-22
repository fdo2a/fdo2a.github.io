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
        {"name": "모나리자", "value": 250, "volume": 25},
    ]
    out = normalize_top_value(rows, top_n=10)
    labels = [g["label"] for g in out]
    # 해외 ETF 제거
    assert not any("S&P500" in l for l in labels)
    # 지수 인버스 = 900+500 = 1400 (인버스2X + 인버스), 최상위
    assert out[0]["label"] == "지수 인버스 ETF" and out[0]["value"] == 1400
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
