"""Naver 테마 페이지(theme.naver) 파싱 + 등락률 랭킹."""
import re
from bs4 import BeautifulSoup

_PCT = re.compile(r"([+\-]?\d+\.\d+)%")


def parse_themes(html: str) -> list:
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for tr in soup.select("table.type_1 tr"):
        a = tr.select_one("td.col_type1 a")
        if not a:
            continue
        pct = None
        for td in tr.select("td"):
            m = _PCT.search(td.get_text())
            if m:
                pct = float(m.group(1))
                break
        if pct is not None:
            out.append({"name": a.get_text(strip=True), "change_pct": pct})
    return out


def rank_themes(themes: list, top: int = 15) -> list:
    uniq = {t["name"]: t for t in themes}
    return sorted(uniq.values(), key=lambda x: -x["change_pct"])[:top]
