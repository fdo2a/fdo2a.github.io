"""임시 진단 4차 — 새 SPA 라우트(/market/stock/kr/...)가 부르는 API 확정.

3차에서 새 PC SPA 의 라우트가 드러났다:
  /market/stock/kr/stocklist/quantHigh  ← 거래대금 상위
  /market/stock/kr/trend/trader         ← 투자자별 매매동향
이 페이지의 RSC flight payload 와 호출 API 를 캔다.
"""
import html as htmllib
import json
import re

import requests

PC = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"),
    "Referer": "https://finance.naver.com/",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
API = dict(PC, Accept="application/json, text/plain, */*")


def get(url, headers=None, timeout=20):
    try:
        return requests.get(url, headers=headers or PC, timeout=timeout)
    except Exception as e:  # noqa: BLE001
        print(f"      [ERR] {type(e).__name__}: {e}")
        return None


def flight(text):
    """Next.js App Router 의 self.__next_f.push 조각을 이어 붙여 하나의 문자열로."""
    parts = re.findall(r'self\.__next_f\.push\(\[\d+,\s*"((?:[^"\\]|\\.)*)"\]\)', text)
    out = []
    for p in parts:
        try:
            out.append(json.loads(f'"{p}"'))
        except Exception:  # noqa: BLE001
            out.append(p)
    return "".join(out)


print("=" * 100)
print("R. 새 SPA 페이지 — RSC payload 에서 데이터·API 를 캔다")
print("=" * 100)
for label, url in (
    ("거래대금상위", "https://finance.naver.com/market/stock/kr/stocklist/quantHigh"),
    ("투자자별매매동향", "https://finance.naver.com/market/stock/kr/trend/trader"),
):
    r = get(url)
    print(f"--- [{r.status_code if r else 'ERR'}] {label} {url}")
    if r is None or r.status_code != 200:
        continue
    t = r.text
    f = flight(t)
    print(f"    html={len(t)} flight={len(f)}")
    for needle in ("accumulatedTradingValue", "삼성전자", "stockList", "personalValue",
                   "foreignValue", "tradingValue", "거래대금"):
        i = f.find(needle)
        if i >= 0:
            print(f"    >>> flight 에 '{needle}' 발견: {re.sub(r'\\s+', ' ', f[max(0, i-300):i+500])}")
            break
    else:
        print("    flight 안에 데이터 흔적 없음")
    # API URL 흔적 (html + flight 양쪽)
    both = t + f
    apis = sorted(set(re.findall(
        r'(?:https?://[a-z.]*(?:api|m)\.(?:stock|finance)\.naver\.com)?/(?:api|market|service)/[A-Za-z0-9_\-/]{3,60}', both)))
    print(f"    API 후보 {len(apis)}개: {apis[:45]}")

print()
print("=" * 100)
print("S. 새 라우트를 API 호스트에 그대로 물려 본다")
print("=" * 100)
cands = [
    "https://api.stock.naver.com/market/stock/kr/stocklist/quantHigh",
    "https://m.stock.naver.com/api/market/stock/kr/stocklist/quantHigh",
    "https://finance.naver.com/api/market/stock/kr/stocklist/quantHigh",
    "https://api.stock.naver.com/stocklist/quantHigh",
    "https://api.stock.naver.com/stock/kr/stocklist/quantHigh",
    "https://api.stock.naver.com/market/stock/kr/trend/trader",
    "https://m.stock.naver.com/api/market/stock/kr/trend/trader",
    # 랭킹류 관용 표현
    "https://api.stock.naver.com/stock/kr/stocklist?sortType=quantHigh&pageSize=20",
    "https://api.stock.naver.com/stocklist?type=quantHigh&pageSize=20",
]
for u in cands:
    r = get(u, API, timeout=15)
    if r is None:
        continue
    body = re.sub(r"\s+", " ", r.text[:200])
    print(f"[{r.status_code}] {u}\n      {body}")

print()
print("=" * 100)
print("T. marketValue/all 페이지네이션으로 거래대금 상위를 재구성할 수 있나 (플랜 A2)")
print("=" * 100)
seen, pages_ok = {}, 0
for page in range(1, 7):
    r = get(f"https://m.stock.naver.com/api/stocks/marketValue/all?page={page}&pageSize=100",
            API, timeout=25)
    if r is None or r.status_code != 200:
        print(f"    page={page} → [{r.status_code if r else 'ERR'}] 중단")
        break
    try:
        stocks = r.json().get("stocks", [])
    except Exception as e:  # noqa: BLE001
        print(f"    page={page} 파싱 실패: {e}")
        break
    if not stocks:
        print(f"    page={page} 빈 응답 — 끝")
        break
    pages_ok += 1
    for s in stocks:
        try:
            raw = int(str(s.get("accumulatedTradingValueRaw") or "0").replace(",", ""))
        except (TypeError, ValueError):
            raw = 0
        seen[s.get("itemCode")] = (s.get("stockName"), raw, s.get("sosok"))
print(f"    수집 {pages_ok}페이지 / 종목 {len(seen)}개")
top = sorted(seen.values(), key=lambda x: x[1], reverse=True)[:15]
print("    거래대금 상위 15 (원):")
for name, raw, sosok in top:
    print(f"      {name:<28} {raw:>18,}  sosok={sosok}")

print()
print("=" * 100)
print("U. 프로그램 매매 — 새 SPA 라우트 훑기")
print("=" * 100)
r = get("https://finance.naver.com/market/stock/kr/trend/trader")
if r is not None and r.status_code == 200:
    links = sorted(set(re.findall(r'href="(/market/[A-Za-z0-9_\-/]+)"', r.text)))
    print(f"    /market/ 링크 {len(links)}개: {links[:60]}")
for u in ("https://finance.naver.com/market/stock/kr/trend/program",
          "https://finance.naver.com/market/stock/kr/trend/trader?type=program"):
    r = get(u)
    print(f"[{r.status_code if r else 'ERR'}] {u}")

print("probe4 done")
