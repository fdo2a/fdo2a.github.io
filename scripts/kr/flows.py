"""시장 수급 파싱 + 신선도 판정.

소스는 m.stock `/api/index/{code}/trend?bizdate=` 다. 레거시 investorDealTrendDay 는
2026-09-17 폐지(410). 한 호출이 하루치 한 행만 주므로 `sources.fetch_market_flows` 가
날짜를 거슬러 모으고, 여기서는 행 하나를 표준형으로 바꾸는 일만 한다.

당일 확정치가 발행 시점(18:00)에 없을 수 있으므로 최신 가용일을 감지해 라벨링한다.
"""
from kr.parse import num_or_none

SIDES = (("individual", "personalValue"), ("foreign", "foreignValue"),
         ("institution", "institutionalValue"))


def classify_row(payload, requested=None):
    """수급 응답 한 건 → (status, row | None, fields). 못 읽은 값은 0 이 아니다(2026-11-12).

    - unreadable: bizdate 가 8자리 숫자가 아니거나 요청한 날짜와 다르다, 또는 세 주체를 모두 못 읽었다.
    - partial: 일부 주체만 못 읽었다(fields = 못 읽은 주체 이름).
    - zero: 세 주체 모두 **관측된** 0 — 휴장·미래·아직 안 올라온 당일(실측 문자열 "0").
    - ok: 세 주체 모두 수이고 하나 이상 0 이 아니다 → 행 {date, individual, foreign, institution}.
    """
    payload = payload if isinstance(payload, dict) else {}
    bizdate = str(payload.get("bizdate") or "")
    if len(bizdate) != 8 or not bizdate.isdigit() or (requested is not None and bizdate != str(requested)):
        return "unreadable", None, [k for k, _ in SIDES]
    vals = {k: num_or_none(payload.get(src), "int") for k, src in SIDES}
    missing = [k for k, _ in SIDES if vals[k] is None]
    if len(missing) == len(SIDES):
        return "unreadable", None, missing
    if missing:
        return "partial", None, missing
    if not any(vals.values()):
        return "zero", None, []
    return "ok", {"date": f"{bizdate[:4]}-{bizdate[4:6]}-{bizdate[6:]}", **vals}, []


def parse_flows_row(payload: dict):
    """수급 응답 한 건 → {date, individual, foreign, institution}. ok 가 아니면 None(반환형 그대로).

    휴장일·미래 일자도 200 을 주되 세 주체가 전부 0 이다. 0 을 데이터로 받으면 그 날이
    '수급 0원'인 거래일로 집계에 섞여 들어가므로 여기서 떨어뜨린다. 못 읽은 주체가 있으면
    0 으로 채우지 않고 행을 버린다 — 이유는 `classify_row` 가 돌려준다.
    """
    status, row, _ = classify_row(payload)
    return row if status == "ok" else None


def build_market_flows(rows: list) -> dict:
    """행 목록 → 레거시 parse_market_flows 와 같은 모양. 최신일이 rows[0]."""
    rows = sorted([r for r in rows if r], key=lambda r: r["date"], reverse=True)
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
