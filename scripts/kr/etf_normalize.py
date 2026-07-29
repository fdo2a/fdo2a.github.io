"""거래대금 상위 종목의 ETF 정규화.

원시 거래대금 상위는 레버리지·인버스·단일종목·해외 ETF로 대부분 오염된다.
실제 자금 쏠림만 남기기 위해:
  - 단일종목 레버리지/인버스 ETF → 기초자산별 1줄로 병합
  - 지수 관련 ETF(레버리지·인버스·순수 지수추종) → 제외 (2026-07-29 사용자 지시)
  - 해외 ETF → 제외
  - 일반 종목·섹터/테마 ETF → 유지
"""

ETF_BRANDS = ("KODEX", "TIGER", "SOL", "ARIRANG", "KBSTAR", "HANARO",
              "PLUS", "ACE", "KOSEF", "RISE", "TIMEFOLIO", "WOORI", "FOCUS")
LEV_KW = ("레버리지", "인버스", "2X", "선물", "곱버스")
OVERSEAS_KW = ("미국", "S&P", "나스닥", "차이나", "중국", "일본", "인도",
               "베트남", "유로", "글로벌", "다우", "필라델피아")
INDEX_KW = ("200", "코스닥150", "코스피", "KRX", "KTOP30", "코스닥")
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


def _direction(name: str) -> str:
    """레버리지(롱) vs 인버스(숏) 방향. 인버스·곱버스는 하락 베팅."""
    return "short" if ("인버스" in name or "곱버스" in name) else "long"


def _is_index_product(name: str) -> bool:
    """브랜드·레버리지 수식어·지수명을 걷어내고 남는 기초자산이 없으면 순수 지수 상품.

    'KODEX 200'·'KODEX 200선물인버스2X'·'KODEX 레버리지' → 지수. 반대로 지수 토큰이
    있어도 잔여물이 남으면('TIGER 200 IT' → 'IT', 'TIGER 코스피고배당' → '고배당')
    섹터/테마로 남긴다 — INDEX_KW 단순 부분일치는 '200'·'코스닥' 때문에 과잉 제외를 낸다.
    """
    out = _underlying(name)
    for k in sorted(INDEX_KW, key=len, reverse=True):
        out = out.replace(k, "")
    return out.strip(" ()·") == ""


def classify_ticker(name: str) -> dict:
    if not _is_etf(name):
        return {"is_etf": False, "kind": "stock", "underlying": None, "direction": None}
    if any(k in name for k in OVERSEAS_KW):
        return {"is_etf": True, "kind": "overseas_etf", "underlying": None, "direction": None}
    if "단일종목" in name:
        return {"is_etf": True, "kind": "single_stock_lev",
                "underlying": _underlying(name), "direction": _direction(name)}
    is_lev = any(k in name for k in LEV_KW)
    if _is_index_product(name):
        # 레버리지/인버스든 순수 추종이든 둘 다 지수 관련 — normalize_top_value에서 제외된다
        return {"is_etf": True, "kind": "index_lev" if is_lev else "index_etf",
                "underlying": "지수", "direction": _direction(name) if is_lev else None}
    return {"is_etf": True, "kind": "sector_theme_etf",
            "underlying": _underlying(name), "direction": None}


DROP_KINDS = ("overseas_etf", "index_lev", "index_etf")


def normalize_top_value(rows: list, top_n: int = 10) -> list:
    """거래대금 상위를 정규화. 단일종목 레버리지/인버스는 기초자산+방향별로 병합해
    롱(레버리지)과 숏(인버스)을 별도 줄로 구분하고, 해외·지수 관련 ETF는 버린다
    (2026-07-29 사용자 지시 — 지수 ETF는 실체 있는 종목 쏠림을 가린다)."""
    groups: dict = {}
    for r in rows:
        c = classify_ticker(r["name"])
        kind, d = c["kind"], c["direction"]
        if kind in DROP_KINDS:
            continue
        if kind == "single_stock_lev":
            dl = "레버리지" if d == "long" else "인버스"
            key, label = f"single::{c['underlying']}::{d}", f"{c['underlying']} {dl}"
        else:  # stock or sector_theme_etf → 이름 유지
            key, label = f"{kind}::{r['name']}", r["name"]
        g = groups.setdefault(key, {"label": label, "kind": kind, "direction": d,
                                    "value": 0, "volume": 0, "members": []})
        g["value"] += r.get("value", 0)
        g["volume"] += r.get("volume", 0)
        g["members"].append(r["name"])
    return sorted(groups.values(), key=lambda x: -x["value"])[:top_n]
