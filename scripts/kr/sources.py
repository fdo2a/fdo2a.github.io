"""Naver Finance / yfinance 네트워크 페처.

2026-09-17 네이버 금융이 Next.js SPA 로 개편되면서 레거시 `finance.naver.com/sise/*.naver`
서버렌더 페이지가 사라졌다. 두 갈래로 깨졌다 — `investorDealTrendDay`·`programDealTrendDay`
는 410 Gone, `sise_quant`·`theme` 는 200 을 주되 표가 없는 껍데기라 파서가 조용히 빈
리스트를 냈다. 뒤쪽이 더 위험했다: 에러가 안 나서 일주일 동안 아무도 몰랐다. 그래서 이
모듈의 fetch_* 는 **빈 결과를 성공으로 취급하지 않는다** — 비면 예외를 올린다.

살아남은 소스는 m.stock/api.stock 의 JSON API 다. 수급과 거래대금(코어 2종)은 여기로
옮겼고, 프로그램 매매·장중 수급·테마(전부 비-코어)는 대체재가 없어 폐지 상태다.
"""
from datetime import datetime, timedelta

import requests

NAVER_HDRS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"),
    "Referer": "https://m.stock.naver.com/",
}
MARKETVALUE_URL = "https://m.stock.naver.com/api/stocks/marketValue/all"
_RETIRED = ("Naver 레거시 페이지 폐지(2026-09-17 SPA 개편) — 대체 소스 없음: {}")


def _to_int(s) -> int:
    try:
        return int(str(s).replace(",", ""))
    except (TypeError, ValueError):
        return 0


def _to_float(s) -> float:
    try:
        return float(str(s).replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def fetch_json(url: str, timeout: int = 12):
    r = requests.get(url, headers=NAVER_HDRS, timeout=timeout)
    r.raise_for_status()
    return r.json()


def fetch_index(code: str) -> dict:
    """KR 지수 현재/종가 — Naver 네이티브(수급 소스와 일치). code: KOSPI|KOSDAQ."""
    j = fetch_json(f"https://m.stock.naver.com/api/index/{code}/basic")
    close = float(str(j.get("closePrice", "0")).replace(",", ""))
    try:
        chg = float(j.get("fluctuationsRatio"))
    except (TypeError, ValueError):
        chg = 0.0
    if close <= 0:
        # 0 을 종가로 흘리면 지수(코어)가 비지 않은 채 0 으로 발행된다 — 빈 [] 와 같은 실패다.
        raise RuntimeError(f"지수 종가가 비었다 — {code} basic 응답 확인 필요")
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
    return downsample_30min(
        fetch_json(f"https://api.stock.naver.com/chart/domestic/index/{code}/minute?count=400",
                   timeout=15))


def fetch_index_ohlc(code: str) -> dict:
    """당일 시가·고가·저가·전일종가 — 장중 궤적 서술용."""
    j = fetch_json(f"https://m.stock.naver.com/api/index/{code}/integration")
    ti = {x.get("code"): x.get("value") for x in j.get("totalInfos", [])}

    def num(k):
        try:
            return float(str(ti.get(k, "")).replace(",", ""))
        except (TypeError, ValueError):
            return None
    return {"open": num("openPrice"), "high": num("highPrice"),
            "low": num("lowPrice"), "prevClose": num("lastClosePrice")}


def fetch_market_flows(code: str, bizdate: str, days: int = 10, max_back: int = 25) -> list:
    """시장 수급 최근 N거래일 — m.stock JSON. code: KOSPI|KOSDAQ.

    이 API 는 한 번에 하루치만 준다. 레거시 표가 주던 10거래일을 맞추려고 bizdate 를
    하루씩 거슬러 호출한다. 휴장일도 200 을 주되 세 주체가 전부 0 이라
    `flows.parse_flows_row` 가 걸러낸다. 과거 일자를 받을 수 있어야 `period.py` 의
    extra_flows 자가치유가 산다.
    """
    from kr.flows import parse_flows_row
    day = datetime.strptime(bizdate, "%Y%m%d")
    rows = []
    for _ in range(max_back):
        if len(rows) >= days:
            break
        row = parse_flows_row(
            fetch_json(f"https://m.stock.naver.com/api/index/{code}/trend"
                       f"?bizdate={day.strftime('%Y%m%d')}"))
        if row:
            rows.append(row)
        day -= timedelta(days=1)
    if not rows:
        raise RuntimeError(f"수급 응답에 유효한 행이 없다 — {code} {bizdate} 기준 {max_back}일 소급")
    return rows


def fetch_top_value(sosok: str = "0", pages: int = 60) -> list:
    """거래대금 상위 — 시총 순 전체 목록을 받아 거래대금으로 다시 정렬한다.

    대체 API 에 거래대금 정렬이 없어 시총 순 전체를 훑고 이쪽에서 정렬한다. 한 페이지
    100종목이 상한이고, 새 종목이 안 나오면 멈춘다. sosok 은 레거시와 같은 뜻 —
    "0"=코스피, "1"=코스닥. 거래대금 단위는 백만원으로 레거시 컬럼과 같다.
    """
    rows, seen = [], set()
    for page in range(1, pages + 1):
        stocks = fetch_json(f"{MARKETVALUE_URL}?page={page}&pageSize=100",
                            timeout=15).get("stocks") or []
        fresh = [s for s in stocks if s.get("itemCode") not in seen]
        if not fresh:
            break
        seen.update(s.get("itemCode") for s in fresh)
        for s in fresh:
            if s.get("sosok") != sosok or not s.get("stockName"):
                continue
            rows.append({
                "name": s["stockName"],
                "value": _to_int(s.get("accumulatedTradingValue")),
                "volume": _to_int(s.get("accumulatedTradingVolume")),
                "change_pct": _to_float(s.get("fluctuationsRatio")),
            })
    if not rows:
        raise RuntimeError(f"거래대금 목록이 비었다 — marketValue 응답 확인 필요(sosok={sosok})")
    rows.sort(key=lambda r: r["value"], reverse=True)
    return rows


def fetch_intraday_flows(sosok: str, bizdate: str, page: int = 1):
    """장중 수급 궤적 — 소스 폐지(investorDealTrendTime 410). 비-코어."""
    raise RuntimeError(_RETIRED.format("investorDealTrendTime"))


def fetch_program_flows(sosok: str, bizdate: str):
    """프로그램 매매 — 소스 폐지(programDealTrendDay 410). 비-코어."""
    raise RuntimeError(_RETIRED.format("programDealTrendDay"))


def fetch_themes(pages: int = 7):
    """테마 랭킹 — 소스 폐지(theme.naver SPA 껍데기). 2026-07-29 이미 리포트 미사용."""
    raise RuntimeError(_RETIRED.format("theme.naver"))


def fetch_industry() -> list:
    """업종 등락률 + breadth(상승종목 비율). 업종 단위 거래대금은 Naver가 제공하지 않아
    상승/전체 종목수로 '폭넓은 상승 vs 좁은 상승'을 크로스체크한다(§4.3 유동성 대체 신호).
    실제 거래대금 쏠림은 거래대금 상위 종목(etf_normalize)이 종목 단위로 담당."""
    groups = fetch_json(
        "https://m.stock.naver.com/api/stocks/industry?menu=industry&pageSize=60"
    ).get("groups", [])
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
    if not out:
        raise RuntimeError("업종 목록이 비었다 — industry 응답 확인 필요")
    return out
