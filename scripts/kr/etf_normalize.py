"""거래대금 상위 종목의 ETF 정규화.

원시 거래대금 상위는 레버리지·인버스·단일종목·해외 ETF로 대부분 오염된다.
실제 자금 쏠림만 남기기 위해:
  - 단일종목 레버리지/인버스 ETF → 기초자산별 1줄로 병합
  - 지수 레버리지/인버스 ETF → "지수 방향성 ETF" 단일 버킷
  - 해외 ETF → 제외
  - 일반 종목·섹터/테마 ETF → 유지
"""

ETF_BRANDS = ("KODEX", "TIGER", "SOL", "ARIRANG", "KBSTAR", "HANARO",
              "PLUS", "ACE", "KOSEF", "RISE", "TIMEFOLIO", "WOORI", "FOCUS")
LEV_KW = ("레버리지", "인버스", "2X", "선물", "곱버스")
OVERSEAS_KW = ("미국", "S&P", "나스닥", "차이나", "중국", "일본", "인도",
               "베트남", "유로", "글로벌", "다우", "필라델피아")
INDEX_KW = ("200", "코스닥150", "코스피", "KRX", "코스닥")
_STRIP = ("단일종목", "레버리지", "인버스", "선물", "2X", "1X", "합성",
          "(H)", "TR", "액티브")


def _is_etf(name: str) -> bool:
    return any(name.startswith(b) or b in name for b in ETF_BRANDS)


def _underlying(name: str) -> str:
    out = name
    for b in ETF_BRANDS:
        out = out.replace(b, "")
    for k in _STRIP:
        out = out.replace(k, "")
    return out.strip()


def classify_ticker(name: str) -> dict:
    if not _is_etf(name):
        return {"is_etf": False, "kind": "stock", "underlying": None}
    if any(k in name for k in OVERSEAS_KW):
        return {"is_etf": True, "kind": "overseas_etf", "underlying": None}
    if "단일종목" in name:
        return {"is_etf": True, "kind": "single_stock_lev", "underlying": _underlying(name)}
    is_lev = any(k in name for k in LEV_KW)
    if is_lev:
        u = _underlying(name)
        # 지수 토큰이 있거나(200·코스닥150 등) 남는 기초자산이 없는 맨몸 인버스/레버리지 → 지수 방향성
        if u == "" or any(k in name for k in INDEX_KW):
            return {"is_etf": True, "kind": "index_lev", "underlying": "지수"}
        return {"is_etf": True, "kind": "sector_theme_etf", "underlying": u}
    return {"is_etf": True, "kind": "sector_theme_etf", "underlying": _underlying(name)}


def normalize_top_value(rows: list, top_n: int = 10) -> list:
    groups: dict = {}
    for r in rows:
        c = classify_ticker(r["name"])
        kind = c["kind"]
        if kind == "overseas_etf":
            continue
        if kind == "single_stock_lev":
            key, label = f"single::{c['underlying']}", f"{c['underlying']} 레버리지군"
        elif kind == "index_lev":
            key, label = "index::dir", "지수 방향성 ETF"
        else:  # stock or sector_theme_etf → 이름 유지
            key, label = f"{kind}::{r['name']}", r["name"]
        g = groups.setdefault(key, {"label": label, "kind": kind,
                                    "value": 0, "volume": 0, "members": []})
        g["value"] += r.get("value", 0)
        g["volume"] += r.get("volume", 0)
        g["members"].append(r["name"])
    return sorted(groups.values(), key=lambda x: -x["value"])[:top_n]
