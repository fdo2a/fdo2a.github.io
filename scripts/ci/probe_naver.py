"""임시 진단 스크립트 — Naver 410 원인 규명과 대체 엔드포인트 탐색.

레거시 finance.naver.com/sise/*.naver 가 2026-09-17 수집분부터 410 Gone 을 뱉는다.
호스트 차단인지 경로 폐지인지 가르고, 살아있는 JSON API 중 대체재를 찾는다.
실측 환경은 GitHub Actions — 루틴 샌드박스는 금융 호스트가 막혀 있다.

발견이 끝나면 이 파일은 지운다.
"""
import json
import re
import sys

import requests

HDRS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"),
    "Referer": "https://finance.naver.com/",
}
MHDRS = dict(HDRS, Referer="https://m.stock.naver.com/")
BIZ = "20260921"


def probe(label, url, headers=None, method="GET", data=None):
    try:
        r = requests.request(method, url, headers=headers or HDRS, data=data, timeout=15)
        body = r.text
        ctype = r.headers.get("content-type", "")[:40]
        snippet = re.sub(r"\s+", " ", body[:220])
        print(f"[{r.status_code}] {label}\n      {url}\n      ctype={ctype} len={len(body)}\n      {snippet}")
        return r
    except Exception as e:  # noqa: BLE001 — 진단 스크립트라 전부 삼킨다
        print(f"[ERR] {label}\n      {url}\n      {type(e).__name__}: {e}")
        return None


print("=" * 100)
print("A. 진단 — finance.naver.com 이 호스트째 죽었나, /sise/*.naver 경로만 죽었나")
print("=" * 100)
probe("root", "https://finance.naver.com/")
probe("sise index page", "https://finance.naver.com/sise/")
probe("sise_index.naver", "https://finance.naver.com/sise/sise_index.naver?code=KOSPI")
probe("item/main (개별종목)", "https://finance.naver.com/item/main.naver?code=005930")
probe("BROKEN investorDealTrendDay",
      f"https://finance.naver.com/sise/investorDealTrendDay.naver?bizdate={BIZ}&sosok=01")
probe("BROKEN investorDealTrendTime",
      f"https://finance.naver.com/sise/investorDealTrendTime.naver?bizdate={BIZ}&sosok=01&page=1")
probe("BROKEN programDealTrendDay",
      f"https://finance.naver.com/sise/programDealTrendDay.naver?bizdate={BIZ}&sosok=01")
probe("BROKEN sise_quant", "https://finance.naver.com/sise/sise_quant.naver?sosok=0")
probe("BROKEN theme", "https://finance.naver.com/sise/theme.naver?page=1")
probe("api.finance siseJson (레거시 JSON)",
      "https://api.finance.naver.com/siseJson.naver?symbol=005930&requestType=1"
      "&startTime=20260901&endTime=20260921&timeframe=day")

print()
print("=" * 100)
print("B. 살아있다고 확인된 JSON API (대조군)")
print("=" * 100)
probe("m.stock index basic", "https://m.stock.naver.com/api/index/KOSPI/basic", MHDRS)
probe("m.stock industry", "https://m.stock.naver.com/api/stocks/industry?menu=industry&pageSize=5", MHDRS)
probe("api.stock minute chart",
      "https://api.stock.naver.com/chart/domestic/index/KOSPI/minute?count=5", MHDRS)

print()
print("=" * 100)
print("C. 대체 후보 — 시장 투자자별 매매동향(수급). CORE")
print("=" * 100)
for host in ("https://m.stock.naver.com/api", "https://api.stock.naver.com"):
    for path in ("/index/KOSPI/investors", "/index/KOSPI/investorTrend",
                 "/index/KOSPI/investor", "/index/KOSPI/trend",
                 "/index/KOSPI/dealTrend", "/index/KOSPI/investorDealTrend"):
        probe(f"flows candidate {host}{path}", f"{host}{path}", MHDRS)

print()
print("=" * 100)
print("D. 대체 후보 — 거래대금 상위(top_value). CORE")
print("=" * 100)
for url in (
    "https://m.stock.naver.com/api/stocks/tradingValue/KOSPI?page=1&pageSize=20",
    "https://m.stock.naver.com/api/stocks/marketValue/KOSPI?page=1&pageSize=20",
    "https://m.stock.naver.com/api/stocks/tradingValue/all?page=1&pageSize=20",
    "https://api.stock.naver.com/stock/exchange/KOSPI/ranking/tradingValue?page=1&pageSize=20",
    "https://m.stock.naver.com/api/stocks/ranking/tradingValue/KOSPI?page=1&pageSize=20",
):
    probe("top_value candidate", url, MHDRS)

print()
print("=" * 100)
print("E. 발견 — 모바일 SPA 페이지 HTML 에서 실제 API 경로를 긁어낸다")
print("=" * 100)
for label, page in (
    ("투자자별 매매동향 페이지", "https://m.stock.naver.com/domestic/index/KOSPI/investor"),
    ("지수 홈", "https://m.stock.naver.com/domestic/index/KOSPI/total"),
    ("거래대금 상위 랭킹", "https://m.stock.naver.com/domestic/ranking/tradingValue"),
    ("랭킹 홈", "https://m.stock.naver.com/domestic/ranking"),
):
    r = probe(label, page, MHDRS)
    if r is not None and r.status_code == 200:
        paths = sorted(set(re.findall(r'["\'](/api/[A-Za-z0-9_\-/{}.?=&]+)["\']', r.text)))
        stock_urls = sorted(set(re.findall(r'https?://(?:m|api)\.stock\.naver\.com[A-Za-z0-9_\-/{}.?=&]*', r.text)))
        print(f"      >>> /api/ 경로 {len(paths)}개: {paths[:40]}")
        print(f"      >>> 절대 URL {len(stock_urls)}개: {stock_urls[:25]}")
        m = re.search(r'id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.S)
        if m:
            try:
                nd = json.loads(m.group(1))
                print(f"      >>> __NEXT_DATA__ pageProps keys: "
                      f"{list(nd.get('props', {}).get('pageProps', {}).keys())[:20]}")
            except Exception as e:  # noqa: BLE001
                print(f"      >>> __NEXT_DATA__ 파싱 실패: {e}")

print()
print("=" * 100)
print("F. 플랜 B — KRX 공식 데이터 (확정치 원본, pykrx 없이 직접)")
print("=" * 100)
KRX = "http://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd"
KRX_HDRS = dict(HDRS, Referer="http://data.krx.co.kr/contents/MDC/MDI/mdiLoader/index.cmd")
probe("KRX 투자자별 거래실적(MDCSTAT02201)", KRX, KRX_HDRS, "POST", {
    "bld": "dbms/MDC/STAT/standard/MDCSTAT02201",
    "locale": "ko_KR", "mktId": "STK", "trdVolVal": "2", "askBid": "3",
    "strtDd": "20260915", "endDd": BIZ, "share": "1", "money": "1",
})
probe("KRX 거래대금 상위(MDCSTAT01501)", KRX, KRX_HDRS, "POST", {
    "bld": "dbms/MDC/STAT/standard/MDCSTAT01501",
    "locale": "ko_KR", "mktId": "ALL", "trdDd": BIZ, "share": "1", "money": "1",
})
probe("KRX 지수 시세(MDCSTAT00301)", KRX, KRX_HDRS, "POST", {
    "bld": "dbms/MDC/STAT/standard/MDCSTAT00301",
    "locale": "ko_KR", "idxIndMidclssCd": "02", "trdDd": BIZ,
})

print()
print("probe done", file=sys.stderr)
