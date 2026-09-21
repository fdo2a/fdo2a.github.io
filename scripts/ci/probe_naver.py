"""임시 진단 3차 — 거래대금 상위 랭킹 API 확정 (+ 프로그램·장중수급 잔여 탐색).

확정된 것:
  - 수급(CORE): m.stock /api/index/{KOSPI|KOSDAQ}/trend?bizdate=YYYYMMDD
    2026-09-16 응답이 저장된 확정치와 정확히 일치 — 단위 억원, 드롭인 대체재.
  - 종목 객체에 accumulatedTradingValue(백만원, 레거시 sise_quant 와 같은 단위)가 있다.
    남은 건 "거래대금 순으로 정렬된 목록"을 주는 경로를 찾는 것.
"""
import json
import re

import requests

M = {
    "User-Agent": ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
                   "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"),
    "Referer": "https://m.stock.naver.com/",
}
PC = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"),
    "Referer": "https://finance.naver.com/",
}


def get(url, headers=None, timeout=15):
    try:
        return requests.get(url, headers=headers or M, timeout=timeout)
    except Exception as e:  # noqa: BLE001
        print(f"      [ERR] {type(e).__name__}: {e}")
        return None


print("=" * 100)
print("L. 새 PC SPA 에서 거래대금 상위 경로/데이터를 캔다 (RSC flight payload)")
print("=" * 100)
for label, url in (
    ("sise_quant(구 거래대금상위)", "https://finance.naver.com/sise/sise_quant.naver?sosok=0"),
    ("sise 홈", "https://finance.naver.com/sise/"),
):
    r = get(url, PC, timeout=25)
    if r is None or r.status_code != 200:
        print(f"[{r.status_code if r else 'ERR'}] {label}")
        continue
    t = r.text
    print(f"[200] {label} len={len(t)}")
    apis = sorted(set(re.findall(r'(?:https?://(?:api|m)\.stock\.naver\.com|/api)[A-Za-z0-9_\-/{}]*', t)))
    print(f"      API 흔적 {len(apis)}개: {apis[:40]}")
    # 새 라우트(링크) 수집 — 거래대금 상위가 어디로 갔는지
    hrefs = sorted(set(re.findall(r'href="(/[A-Za-z0-9_\-/]*(?:rank|quant|trade|sise)[A-Za-z0-9_\-/]*)"', t, re.I)))
    print(f"      관련 링크 {len(hrefs)}개: {hrefs[:40]}")
    # RSC flight payload 안에 종목 리스트가 들어 있나
    if "accumulatedTradingValue" in t:
        i = t.find("accumulatedTradingValue")
        print(f"      >>> accumulatedTradingValue 발견! 주변: {re.sub(r'\\s+', ' ', t[max(0,i-400):i+400])}")
    else:
        print("      accumulatedTradingValue 없음 (SSR 데이터 아님)")
    if "stockListSortType" in t:
        i = t.find("stockListSortType")
        print(f"      >>> stockListSortType 주변: {re.sub(r'\\s+',' ', t[max(0,i-200):i+300])}")

print()
print("=" * 100)
print("M. sortType 열거 — marketValue 만 살아있나, 다른 이름이 있나")
print("=" * 100)
for sort_type in ("marketValue", "tradingValue", "accumulatedTradingValue", "TRADING_VALUE",
                  "tradeVolume", "volume", "rise", "fall", "upper", "lower",
                  "marketCap", "capitalization", "turnover", "dealValue", "quantValue"):
    for cat in ("KOSPI",):
        r = get(f"https://m.stock.naver.com/api/stocks/{sort_type}/{cat}?page=1&pageSize=2", M)
        if r is None:
            continue
        ok = r.status_code == 200
        body = re.sub(r"\s+", " ", r.text[:150]) if ok else f"len={len(r.text)}"
        print(f"[{r.status_code}] sortType={sort_type}/{cat}: {body}")

print()
print("=" * 100)
print("N. marketValue 의 category 열거 — 전체시장/ETF 를 받는 값이 있나")
print("=" * 100)
for cat in ("KOSPI", "KOSDAQ", "ALL", "all", "KRX", "ETF", "etf", "KOSPI200"):
    r = get(f"https://m.stock.naver.com/api/stocks/marketValue/{cat}?page=1&pageSize=2", M)
    if r is None:
        continue
    body = re.sub(r"\s+", " ", r.text[:160]) if r.status_code == 200 else f"len={len(r.text)}"
    print(f"[{r.status_code}] marketValue/{cat}: {body}")

print()
print("=" * 100)
print("O. marketValue 페이지네이션 한계 — 상위 몇 개까지 받아올 수 있나")
print("=" * 100)
for ps in (100, 200, 300):
    r = get(f"https://m.stock.naver.com/api/stocks/marketValue/KOSPI?page=1&pageSize={ps}", M, timeout=25)
    if r is None or r.status_code != 200:
        print(f"[{r.status_code if r else 'ERR'}] pageSize={ps}")
        continue
    try:
        stocks = r.json().get("stocks", [])
        tv = [(s["stockName"], s.get("accumulatedTradingValueRaw") or s.get("accumulatedTradingValue"))
              for s in stocks]
        def raw(x):
            try:
                return int(str(x[1]).replace(",", ""))
            except (TypeError, ValueError):
                return 0
        top = sorted(tv, key=raw, reverse=True)[:12]
        print(f"[200] pageSize={ps} → {len(stocks)}건. 거래대금 상위 12(백만원): {top}")
    except Exception as e:  # noqa: BLE001
        print(f"      파싱 실패: {e}")

print()
print("=" * 100)
print("P. api.stock.naver.com 랭킹 경로 브루트포스")
print("=" * 100)
for path in ("/stock/ranking/tradingValue", "/stock/ranking/KOSPI/tradingValue",
             "/ranking/tradingValue", "/stocks/ranking?type=tradingValue",
             "/stock/exchange/KOSPI/ranking", "/domestic/ranking/tradingValue",
             "/domestic/stock/ranking?type=TRADING_VALUE"):
    r = get(f"https://api.stock.naver.com{path}", M)
    if r is None:
        continue
    body = re.sub(r"\s+", " ", r.text[:180])
    print(f"[{r.status_code}] {path}: {body}")

print()
print("=" * 100)
print("Q. 프로그램 매매 · 장중 수급 — 마지막 탐색")
print("=" * 100)
for url in ("https://m.stock.naver.com/api/index/KOSPI/programTradingTrend",
            "https://m.stock.naver.com/api/index/KOSPI/trend/intraday",
            "https://m.stock.naver.com/api/index/KOSPI/investorTrendByTime",
            "https://api.stock.naver.com/chart/domestic/index/KOSPI/investorTrend?count=5",
            "https://m.stock.naver.com/api/index/KOSPI/trend?bizdate=20260921&timeUnit=30"):
    r = get(url, M)
    if r is None:
        continue
    print(f"[{r.status_code}] {url}: {re.sub(r'\\s+', ' ', r.text[:160])}")
# 모바일 투자자 페이지가 장중/프로그램 탭을 따로 가지고 있나
for page in ("https://m.stock.naver.com/domestic/index/KOSPI/program",
             "https://m.stock.naver.com/domestic/index/KOSPI/investor?tab=time"):
    r = get(page, M, timeout=20)
    if r is None:
        continue
    print(f"[{r.status_code}] page {page}")
    if r.status_code == 200:
        m = re.search(r'id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.S)
        if m:
            try:
                qs = json.loads(m.group(1))["props"]["pageProps"]["dehydratedState"]["queries"]
                for q in qs:
                    print(f"      queryKey={json.dumps(q.get('queryKey'), ensure_ascii=False)[:160]}")
            except Exception as e:  # noqa: BLE001
                print(f"      {e}")

print("probe3 done")
