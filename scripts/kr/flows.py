"""Naver 시장 수급(investorDealTrendDay) 파싱 + 신선도 판정.

주의: 이 엔드포인트는 유효한 bizdate가 있어야 데이터 행을 반환한다(빈 bizdate=헤더만).
당일 확정치가 발행 시점(18:00)에 없을 수 있으므로 최신 가용일을 감지해 라벨링한다.
"""
import re
from bs4 import BeautifulSoup

_DATE = re.compile(r"^(\d{2})\.(\d{2})\.(\d{2})$")


def _to_int(s: str) -> int:
    try:
        return int(s.replace(",", ""))
    except ValueError:
        return 0


def parse_market_flows(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one("table.type_1")
    rows = []
    if table:
        for tr in table.select("tr"):
            cells = [c.get_text(strip=True) for c in tr.select("td")]
            if len(cells) >= 4 and _DATE.match(cells[0]):
                y, m, d = _DATE.match(cells[0]).groups()
                rows.append({
                    "date": f"20{y}-{m}-{d}",
                    "individual": _to_int(cells[1]),
                    "foreign": _to_int(cells[2]),
                    "institution": _to_int(cells[3]),
                })
    return {"rows": rows, "latest_date": rows[0]["date"] if rows else None}


def flows_freshness(latest_date, report_date: str, provisional: bool = False) -> dict:
    if latest_date is None:
        return {"flows_date": None, "flows_provisional": False,
                "label": "수급 데이터 없음", "stale": True}
    if latest_date == report_date:
        return {"flows_date": latest_date, "flows_provisional": provisional,
                "label": "당일 잠정치" if provisional else "당일 확정", "stale": False}
    return {"flows_date": latest_date, "flows_provisional": False,
            "label": f"전 거래일 기준({latest_date})", "stale": True}
