"""임시 진단 스크립트 2차 — 대체 엔드포인트 확정 + 단위 검증.

1차 결론: Naver Finance 가 Next.js SPA("Npay 증권")로 개편됐다.
  - investorDealTrendDay/Time, programDealTrendDay → 410 Gone
  - sise_quant, theme → 200 이지만 SPA 껍데기라 파서가 조용히 [] 를 낸다
  - m.stock.naver.com/api/index/KOSPI/trend 가 수급을 준다(발견)

2차 목표:
  - SPA 의 __NEXT_DATA__ dehydratedState 에서 실제 API 경로·데이터를 캔다
  - /trend 의 단위·범위를 저장된 확정치(2026-09-16)와 대조한다
  - 거래대금 상위·프로그램·장중수급 대체재를 찾는다
"""
import json
import re

import requests

HDRS = {
    "User-Agent": ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
                   "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"),
    "Referer": "https://m.stock.naver.com/",
}
PCHDRS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"),
    "Referer": "https://finance.naver.com/",
}
BIZ = "20260921"


def get(url, headers=None, timeout=15):
    try:
        return requests.get(url, headers=headers or HDRS, timeout=timeout)
    except Exception as e:  # noqa: BLE001
        print(f"      [ERR] {type(e).__name__}: {e}")
        return None


def short(url, headers=None, label=""):
    r = get(url, headers)
    if r is None:
        print(f"[ERR] {label or url}")
        return None
    body = re.sub(r"\s+", " ", r.text[:400])
    print(f"[{r.status_code}] {label or ''} {url}\n      {body}")
    return r


def next_data(url, headers=None, label=""):
    """SPA 페이지의 __NEXT_DATA__ 를 파싱해 React Query 캐시(queryKey + data)를 보여준다."""
    print(f"--- {label} {url}")
    r = get(url, headers, timeout=20)
    if r is None or r.status_code != 200:
        print(f"    [{r.status_code if r else 'ERR'}] 건너뜀")
        return
    m = re.search(r'id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.S)
    if not m:
        print("    __NEXT_DATA__ 없음")
        return
    try:
        nd = json.loads(m.group(1))
    except Exception as e:  # noqa: BLE001
        print(f"    파싱 실패: {e}")
        return
    queries = nd.get("props", {}).get("pageProps", {}).get("dehydratedState", {}).get("queries", [])
    print(f"    queries {len(queries)}개")
    for q in queries:
        key = q.get("queryKey")
        data = q.get("state", {}).get("data")
        blob = re.sub(r"\s+", " ", json.dumps(data, ensure_ascii=False))[:700]
        print(f"    * queryKey={json.dumps(key, ensure_ascii=False)[:180]}")
        print(f"      data={blob}")


print("=" * 100)
print("G. SPA __NEXT_DATA__ 캐시에서 실제 데이터·쿼리키를 캔다")
print("=" * 100)
next_data("https://m.stock.naver.com/domestic/index/KOSPI/investor", HDRS, "[모바일 투자자별]")
next_data("https://finance.naver.com/sise/sise_quant.naver?sosok=0", PCHDRS, "[PC 거래대금상위]")
next_data("https://finance.naver.com/sise/investorDealTrendDay.naver", PCHDRS, "[PC 투자자별]")

print()
print("=" * 100)
print("H. /trend 확정 — 시장별·단위·과거일자 지원 여부")
print("=" * 100)
for code in ("KOSPI", "KOSDAQ"):
    short(f"https://m.stock.naver.com/api/index/{code}/trend", HDRS, f"[{code} trend]")
# 과거 일자를 받는가? 받는다면 2026-09-16 저장본과 대조해 단위·범위를 확정할 수 있다.
for q in (f"?bizdate=20260916", f"?date=20260916", f"?trdDd=20260916",
          f"?bizdate=20260916&pageSize=10", f"?count=10", f"?page=1&pageSize=10"):
    short(f"https://m.stock.naver.com/api/index/KOSPI/trend{q}", HDRS, "[trend 과거]")
# 시계열 형태의 이웃 엔드포인트
for path in ("trends", "trend/daily", "trendDaily", "investorTrends", "price", "trend/list"):
    short(f"https://m.stock.naver.com/api/index/KOSPI/{path}?pageSize=5", HDRS, f"[이웃 {path}]")

print()
print("=" * 100)
print("I. 거래대금 상위 — /api/stocks/{sortType}/{category} 의 sortType 탐색")
print("=" * 100)
r = get("https://m.stock.naver.com/api/stocks/marketValue/KOSPI?page=1&pageSize=1", HDRS)
if r is not None and r.status_code == 200:
    try:
        st = r.json().get("stocks", [{}])[0]
        print(f"    종목 객체 필드: {sorted(st.keys())}")
        print(f"    샘플: {json.dumps(st, ensure_ascii=False)[:600]}")
    except Exception as e:  # noqa: BLE001
        print(f"    파싱 실패: {e}")
for sort_type in ("accumulatedTradingValue", "tradingValue", "transactionValue", "tradeValue",
                  "accumulatedTradingVolume", "tradingVolume", "amount", "value",
                  "upsurge", "quant", "trading"):
    r = get(f"https://m.stock.naver.com/api/stocks/{sort_type}/KOSPI?page=1&pageSize=3", HDRS)
    if r is None:
        continue
    body = re.sub(r"\s+", " ", r.text[:260])
    print(f"[{r.status_code}] sortType={sort_type}: {body}")

print()
print("=" * 100)
print("J. 프로그램 매매 · 장중 수급 대체 후보")
print("=" * 100)
for path in ("program", "programTrend", "programDeal", "trend/program",
             "trend/time", "trendTime", "intradayTrend", "investorTime"):
    short(f"https://m.stock.naver.com/api/index/KOSPI/{path}", HDRS, f"[{path}]")
short("https://api.stock.naver.com/chart/domestic/index/KOSPI/investor?count=5", HDRS, "[api.stock investor chart]")

print()
print("=" * 100)
print("K. 대조군 — 저장된 2026-09-16 확정치")
print("=" * 100)
print("    kr_flows.json 09-16 KOSPI: individual=-12061 foreign=-16726 institution=+12251 (억원)")
print("    kr_flows.json 09-16 KOSDAQ 도 같은 파일에 있음 — 단위 판별용")
print("probe2 done")
