"""Naver Finance / yfinance 네트워크 페처.

파서(parse_top_value)는 순수 함수라 유닛테스트, 나머지 fetch_*는 스모크로 검증.
sise_quant 거래대금 컬럼 단위는 백만원.
"""
import re
import requests
from bs4 import BeautifulSoup

NAVER_HDRS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"),
    "Referer": "https://finance.naver.com/",
}
_PCT = re.compile(r"([+\-]?\d+\.\d+)%")


def _to_int(s: str) -> int:
    try:
        return int(s.replace(",", ""))
    except ValueError:
        return 0


def fetch(url: str, timeout: int = 12) -> str:
    r = requests.get(url, headers=NAVER_HDRS, timeout=timeout)
    r.encoding = "euc-kr"
    r.raise_for_status()
    return r.text


def parse_top_value(html: str) -> list:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one("table.type_2")
    rows = []
    if not table:
        return rows
    for tr in table.select("tr"):
        a = tr.select_one("a.tltle")
        if not a:
            continue
        cells = [c.get_text(strip=True) for c in tr.select("td")]
        # 컬럼: [N, 종목명, 현재가, 전일비, 등락률, 거래량, 거래대금(백만원), ...]
        if len(cells) < 7:
            continue
        pctm = _PCT.search(cells[4])
        rows.append({
            "name": a.get_text(strip=True),
            "value": _to_int(cells[6]),
            "volume": _to_int(cells[5]),
            "change_pct": float(pctm.group(1)) if pctm else 0.0,
        })
    return rows


def fetch_index(code: str) -> dict:
    """KR 지수 현재/종가 — Naver 네이티브(수급 소스와 일치). code: KOSPI|KOSDAQ."""
    r = requests.get(f"https://m.stock.naver.com/api/index/{code}/basic",
                     headers=NAVER_HDRS, timeout=12)
    r.raise_for_status()
    j = r.json()
    close = float(str(j.get("closePrice", "0")).replace(",", ""))
    try:
        chg = float(j.get("fluctuationsRatio"))
    except (TypeError, ValueError):
        chg = 0.0
    return {"close": round(close, 2), "change_pct": chg}


def downsample_30min(bars: list) -> list:
    """분봉 리스트를 30분 앵커(:00/:30)로 다운샘플. 마지막 봉(종가) 보장.
    bars: [{"localDateTime":"YYYYMMDDHHMMSS","currentPrice":float}, ...]"""
    out = {}
    for b in bars:
        t = str(b.get("localDateTime", ""))
        if len(t) < 12:
            continue
        if t[10:12] in ("00", "30"):
            out[f"{t[8:10]}:{t[10:12]}"] = round(float(b["currentPrice"]), 2)
    if bars:
        last = bars[-1]
        t = str(last["localDateTime"])
        out[f"{t[8:10]}:{t[10:12]}"] = round(float(last["currentPrice"]), 2)
    return [{"t": k, "close": v} for k, v in out.items()]


def fetch_intraday(code: str) -> list:
    """KR 지수 30분봉 장중 궤적 — Naver 분봉을 30분 앵커로 다운샘플."""
    r = requests.get(f"https://api.stock.naver.com/chart/domestic/index/{code}/minute?count=400",
                     headers=NAVER_HDRS, timeout=15)
    r.raise_for_status()
    return downsample_30min(r.json())


def fetch_index_ohlc(code: str) -> dict:
    """당일 시가·고가·저가·전일종가 — 장중 궤적 서술용."""
    r = requests.get(f"https://m.stock.naver.com/api/index/{code}/integration",
                     headers=NAVER_HDRS, timeout=12)
    r.raise_for_status()
    ti = {x.get("code"): x.get("value") for x in r.json().get("totalInfos", [])}

    def num(k):
        try:
            return float(str(ti.get(k, "")).replace(",", ""))
        except (TypeError, ValueError):
            return None
    return {"open": num("openPrice"), "high": num("highPrice"),
            "low": num("lowPrice"), "prevClose": num("lastClosePrice")}


def fetch_market_flows(sosok: str, bizdate: str) -> str:
    return fetch(f"https://finance.naver.com/sise/investorDealTrendDay.naver"
                 f"?bizdate={bizdate}&sosok={sosok}")


def fetch_top_value(sosok: str = "0") -> list:
    return parse_top_value(fetch(f"https://finance.naver.com/sise/sise_quant.naver?sosok={sosok}"))


def fetch_themes(pages: int = 7) -> list:
    from kr.themes import parse_themes
    out = []
    for pg in range(1, pages + 1):
        out += parse_themes(fetch(f"https://finance.naver.com/sise/theme.naver?page={pg}"))
    return out


def fetch_industry() -> list:
    """업종 등락률 + breadth(상승종목 비율). 업종 단위 거래대금은 Naver가 제공하지 않아
    상승/전체 종목수로 '폭넓은 상승 vs 좁은 상승'을 크로스체크한다(§4.3 유동성 대체 신호).
    실제 거래대금 쏠림은 거래대금 상위 종목(etf_normalize)이 종목 단위로 담당."""
    r = requests.get("https://m.stock.naver.com/api/stocks/industry?menu=industry&pageSize=60",
                     headers=NAVER_HDRS, timeout=12)
    r.raise_for_status()
    groups = r.json().get("groups", [])
    out = []
    for it in groups:
        nm = it.get("name") or it.get("groupName")
        try:
            cr = float(it.get("changeRate"))
        except (TypeError, ValueError):
            cr = None
        total = it.get("totalCount", 0) or 0
        rise = it.get("riseCount", 0) or 0
        breadth = (rise / total) if total else 0.0
        if nm and cr is not None:
            out.append({"name": nm, "change_pct": cr, "total": total,
                        "rise": rise, "breadth": round(breadth, 3)})
    return out
