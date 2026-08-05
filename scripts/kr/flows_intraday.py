"""Naver 시간대별 투자자 매매동향(investorDealTrendTime) 파싱 + 장중 궤적 가공.

일별 수급(flows.py)이 "하루 결과"라면 여기는 "그 결과가 언제 만들어졌나"를 담는다.
엔드포인트는 **누적** 순매수를 2~3분 간격으로 스냅샷해 주므로(09:03~18:06, 약 180개
시점), 30분 앵커로 다운샘플하고 극값·부호 전환 시점을 뽑아 writer가 방향 전환을
서술할 수 있게 한다.

주의 두 가지:
- 15:30 이후 스냅샷은 시간외·정정이 섞이고 확정 일별 수치와도 또 다르다(2026-07-29
  코스피 외국인: 15:30 -12,445 → 16:00 -12,337 → 확정 -12,502). 정규장만 궤적으로 쓰고
  확정 수치는 kr_flows.json에서만 인용한다.
- 페이지 범위를 넘기면 마지막 페이지가 그대로 반복된다 → 반복 감지로 중단.
"""
import re

from bs4 import BeautifulSoup

_TIME = re.compile(r"^\d{2}:\d{2}$")

# td 11개의 헤더 순서(2행 헤더: 시간·개인·외국인·기관계·기관(colspan 6)·기타법인 /
# 금융투자·보험·투신(사모)·은행·기타금융기관·연기금등)
COLUMNS = ("t", "individual", "foreign", "institution", "fin_invest", "insurance",
           "trust", "bank", "other_fin", "pension", "other_corp")
INSTITUTION_SUBS = ("fin_invest", "insurance", "trust", "bank", "other_fin", "pension")
INVESTORS = ("individual", "foreign", "institution")

SESSION_END = "15:30"
ANCHORS = ["09:30", "10:00", "10:30", "11:00", "11:30", "12:00", "12:30",
           "13:00", "13:30", "14:00", "14:30", "15:00", "15:30"]


def _to_int(s: str) -> int:
    try:
        return int(s.replace(",", ""))
    except (ValueError, AttributeError):
        return 0


def parse_intraday_flows(html: str) -> list:
    """investorDealTrendTime HTML → [{t, individual, foreign, institution, ...}, ...].

    페이지가 준 순서(최신 → 과거)를 그대로 유지한다. 정렬은 collect_pages 담당.
    """
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one("table.type_1")
    rows = []
    if not table:
        return rows
    for tr in table.select("tr"):
        cells = [c.get_text(strip=True) for c in tr.select("td")]
        if len(cells) != len(COLUMNS) or not _TIME.match(cells[0]):
            continue
        row = {"t": cells[0]}
        row.update({k: _to_int(v) for k, v in zip(COLUMNS[1:], cells[1:])})
        rows.append(row)
    return rows


def collect_pages(fetch_page, max_pages: int = 45) -> list:
    """fetch_page(n) -> 파싱된 행 리스트. 1페이지부터 순회해 시간 오름차순으로 합친다.

    빈 페이지 또는 직전 페이지와 시각 집합이 같으면(= 마지막 페이지 반복) 중단한다.
    같은 시각이 여러 번 나오면 **먼저 본 쪽**(최신 페이지)을 유지한다.
    """
    merged = {}
    prev_times = None
    for page in range(1, max_pages + 1):
        rows = fetch_page(page) or []
        times = tuple(r["t"] for r in rows)
        if not rows or times == prev_times:
            break
        prev_times = times
        for r in rows:
            merged.setdefault(r["t"], r)
    return [merged[t] for t in sorted(merged)]


def _snap(rows: list, anchor: str):
    """앵커 시각 이하의 마지막 관측치. 없으면 None(보간·창작 금지)."""
    found = None
    for r in rows:
        if r["t"] <= anchor:
            found = r
        else:
            break
    return found


def _extreme(rows: list, key: str):
    if not rows:
        return None
    hi = lo = rows[0]
    for r in rows[1:]:
        if r[key] > hi[key]:
            hi = r
        if r[key] < lo[key]:
            lo = r
    return {"max": {"t": hi["t"], "v": hi[key]},
            "min": {"t": lo["t"], "v": lo[key]}}


def _runs(rows: list, key: str) -> list:
    """같은 부호가 이어지는 구간들. 0은 직전 부호를 잇는 것으로 본다(관망 구간 오탐 방지).

    각 run: {sign, t(시작 시각), peak{t, v}(절대값 최대 지점)}.
    """
    runs = []
    for r in rows:
        v = r[key]
        if not v:
            continue
        sign = 1 if v > 0 else -1
        if not runs or runs[-1]["sign"] != sign:
            runs.append({"sign": sign, "t": r["t"], "peak": {"t": r["t"], "v": v}})
        elif abs(v) > abs(runs[-1]["peak"]["v"]):
            runs[-1]["peak"] = {"t": r["t"], "v": v}
    return runs


def _turns(rows: list, key: str, min_ratio: float = 0.05) -> list:
    """누적 순매수의 **의미 있는** 방향 전환.

    개장 직후에는 누적이 0 근처에서 몇백억씩 흔들려 부호가 여러 번 뒤집힌다(2026-07-29
    코스피 외국인: 09:03·09:04). 그런 잡음을 서술에 올리면 "오전에 두 번 전환"처럼
    사실은 맞지만 무의미한 문장이 나온다. 그래서 구간 최대 절대값이 그날 최대 절대값의
    min_ratio에 못 미치는 구간은 버리고, 남은 같은 방향 구간끼리 이어 붙인 뒤 전환을 센다.
    """
    runs = _runs(rows, key)
    if not runs:
        return []
    threshold = max(abs(r["peak"]["v"]) for r in runs) * min_ratio
    kept = [r for r in runs if abs(r["peak"]["v"]) >= threshold]
    out = []
    for prev, cur in zip(kept, kept[1:]):
        if prev["sign"] != cur["sign"]:
            out.append({
                "t": cur["t"],
                "from": "순매수" if prev["sign"] > 0 else "순매도",
                "to": "순매수" if cur["sign"] > 0 else "순매도",
                "peak": cur["peak"],
            })
    return out


def build_series(rows: list, anchors: list = None) -> dict:
    """정규장(≤15:30) 컷 → 30분 앵커 스냅 + 극값 + 부호 전환 + 마지막 관측."""
    anchors = anchors or ANCHORS
    session = sorted((r for r in rows if r["t"] <= SESSION_END), key=lambda r: r["t"])
    points = []
    for a in anchors:
        hit = _snap(session, a)
        if hit:
            points.append({**hit, "t": a})
    return {
        "points": points,
        "extremes": {k: _extreme(session, k) for k in INVESTORS},
        "turns": {k: _turns(session, k) for k in INVESTORS},
        "session_last": session[-1] if session else None,
        "first_t": session[0]["t"] if session else None,
        "last_t": session[-1]["t"] if session else None,
        "obs_count": len(session),
    }
