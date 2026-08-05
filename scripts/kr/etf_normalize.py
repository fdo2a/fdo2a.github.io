"""거래대금 상위 종목의 ETF 정규화.

원시 거래대금 상위는 레버리지·인버스·단일종목·해외 ETF로 대부분 오염된다.
실제 자금 쏠림만 남기기 위해:
  - 단일종목 레버리지/인버스 ETF → 기초자산별 1줄로 병합
  - 지수 관련 ETF(레버리지·인버스·순수 지수추종) → 제외 (2026-07-29 사용자 지시)
  - 해외 ETF → 제외
  - **같은 테마 섹터 ETF → 테마 1줄로 병합** (2026-08-06 사용자 지시)
  - 일반 종목 → 유지

테마 병합 배경: 07-29 지수 ETF를 걷어낸 뒤 매일 2~5칸을 반도체 ETF가 쪼개서 차지했다
(08-03엔 5칸 1.49조). 각각은 개별 종목보다 작아 보이지만 사실 같은 베팅이라, 묶어야
"반도체는 개별주로 얼마·바스켓으로 얼마"라는 선별매수 vs 패시브 쏠림 대비가 읽힌다.
섹터 ETF를 빼버리는 선택지도 있었지만, Naver가 업종 단위 거래대금을 안 주기 때문에
리포트에서 업종별 **자금량**이 드러나는 곳이 여기뿐이라 유지 쪽으로 결정했다.
"""

ETF_BRANDS = ("KODEX", "TIGER", "SOL", "ARIRANG", "KBSTAR", "HANARO",
              "PLUS", "ACE", "KOSEF", "RISE", "TIMEFOLIO", "WOORI", "FOCUS")
LEV_KW = ("레버리지", "인버스", "2X", "선물", "곱버스")
OVERSEAS_KW = ("미국", "S&P", "나스닥", "차이나", "중국", "일본", "인도",
               "베트남", "유로", "글로벌", "다우", "필라델피아")
INDEX_KW = ("200", "코스닥150", "코스피", "KRX", "KTOP30", "코스닥")
_STRIP = ("단일종목", "레버리지", "인버스", "선물", "2X", "1X", "합성",
          "(H)", "TR", "액티브")

# 섹터/테마 ETF 병합 사전. 키워드가 이름에 있으면 그 테마로 본다 — 긴 것부터 검사해
# '2차전지소재'가 '소재'보다 먼저 걸리게 한다. 사전에 없으면 None(제 이름으로 남는다).
THEME_KEYWORDS = (
    ("2차전지", "2차전지"), ("배터리", "2차전지"),
    ("반도체", "반도체"),
    ("바이오", "바이오·헬스케어"), ("헬스케어", "바이오·헬스케어"), ("제약", "바이오·헬스케어"),
    ("방산", "방산"), ("우주항공", "우주항공"),
    ("조선", "조선"), ("원자력", "원자력"), ("로봇", "로봇"),
    ("자동차", "자동차"), ("철강", "철강"), ("건설", "건설"),
    ("은행", "은행"), ("증권", "증권"), ("보험", "보험"),
    ("인터넷", "인터넷·플랫폼"), ("게임", "게임"), ("엔터", "엔터"),
    ("화장품", "화장품"), ("리츠", "리츠"), ("전력", "전력·에너지"),
)


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


def resolve_theme(name: str):
    """ETF 이름에서 병합용 테마를 뽑는다. 매칭 실패 시 None.

    'TIGER 반도체TOP10'·'SOL AI반도체TOP2플러스'·'KODEX 반도체레버리지'는 넓은 바스켓,
    집중 바스켓, 레버리지로 성격이 다르지만 셋 다 반도체 바스켓에 들어간 돈이다.
    """
    for kw, theme in sorted(THEME_KEYWORDS, key=lambda x: -len(x[0])):
        if kw in name:
            return theme
    return None


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
            "underlying": _underlying(name), "direction": _direction(name),
            "theme": resolve_theme(name)}


DROP_KINDS = ("overseas_etf", "index_lev", "index_etf")


def normalize_top_value(rows: list, top_n: int = 10) -> list:
    """거래대금 상위를 정규화.

    - 단일종목 레버리지/인버스 → 기초자산+방향별 병합(롱·숏 별도 줄)
    - 같은 테마 섹터 ETF → 테마+방향별 병합(2026-08-06 사용자 지시)
    - 해외·지수 관련 ETF → 제외(2026-07-29 사용자 지시 — 실체 있는 종목 쏠림을 가린다)
    """
    groups: dict = {}
    for r in rows:
        c = classify_ticker(r["name"])
        kind, d, theme = c["kind"], c["direction"], c.get("theme")
        if kind in DROP_KINDS:
            continue
        if kind == "single_stock_lev":
            dl = "레버리지" if d == "long" else "인버스"
            key, label = f"single::{c['underlying']}::{d}", f"{c['underlying']} {dl}"
        elif kind == "sector_theme_etf" and theme:
            suffix = " (인버스)" if d == "short" else ""
            key, label = f"theme::{theme}::{d}", f"{theme} 테마 ETF{suffix}"
        else:  # 일반 종목, 테마 미매칭 ETF → 이름 유지
            key, label = f"{kind}::{r['name']}", r["name"]
        g = groups.setdefault(key, {"label": label, "kind": kind, "direction": d,
                                    "theme": theme, "value": 0, "volume": 0,
                                    "members": []})
        g["value"] += r.get("value", 0)
        g["volume"] += r.get("volume", 0)
        g["members"].append(r["name"])

    # 한 종목뿐인 테마는 병합이 일어나지 않았으므로 '테마 ETF'라 부르지 않는다.
    for g in groups.values():
        if g["kind"] == "sector_theme_etf" and len(g["members"]) == 1:
            g["label"] = g["members"][0]
    return sorted(groups.values(), key=lambda x: -x["value"])[:top_n]
