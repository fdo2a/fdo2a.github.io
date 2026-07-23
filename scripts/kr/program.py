"""Naver 프로그램 매매(programDealTrendDay) 파싱.

단위: 억원(flows와 동일, 페이지 `단위:억원` 표기). 컬럼은 차익거래·비차익거래·전체
각각 매수/매도/순매수. 당일 확정치가 발행 시점(18:00)에 없을 수 있으므로 신선도는
collector가 `flows.flows_freshness`로 판정한다(이 파서는 순수 파싱만).
"""
import re

from bs4 import BeautifulSoup

_DATE = re.compile(r"^(\d{2})\.(\d{2})\.(\d{2})$")


def _to_int(s: str) -> int:
    try:
        return int(s.replace(",", ""))
    except (ValueError, AttributeError):
        return 0


def parse_program_flows(html: str) -> dict:
    """programDealTrendDay HTML → {rows: [...], latest_date}.

    각 row: date + 차익(arb)·비차익(narb)·전체(total) 매수/매도/순매수(억원).
    """
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for tr in soup.select("table tr"):
        cells = [c.get_text(strip=True) for c in tr.select("td")]
        m = _DATE.match(cells[0]) if cells else None
        if m and len(cells) >= 10:
            y, mo, d = m.groups()
            rows.append({
                "date": f"20{y}-{mo}-{d}",
                "arb_buy": _to_int(cells[1]), "arb_sell": _to_int(cells[2]),
                "arb_net": _to_int(cells[3]),
                "narb_buy": _to_int(cells[4]), "narb_sell": _to_int(cells[5]),
                "narb_net": _to_int(cells[6]),
                "total_buy": _to_int(cells[7]), "total_sell": _to_int(cells[8]),
                "total_net": _to_int(cells[9]),
            })
    return {"rows": rows, "latest_date": rows[0]["date"] if rows else None}
