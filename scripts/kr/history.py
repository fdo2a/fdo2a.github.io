"""KR 지수 종가 원장 — 기간 수익률을 시세 재수집이 아니라 발행본 스냅샷으로 잰다.

`kr_market_data.json` 은 매일 덮어쓰기라 과거 종가가 남지 않는다. 그래서 기간 집계가
yfinance 로 3개월치를 다시 받았는데, 조정계수와 기준 시각이 달라 총정리가 그날
발행본과 다른 숫자를 실을 수 있었다(US 쪽 2026-08-30 실측 사고와 같은 구조).
이제 그날 인쇄한 종가를 한 줄씩 쌓고 기간 집계는 그 원장만 읽는다.

쓰기는 `us.history.append_jsonl` 이 맡는다 — 같은 report_date 는 한 줄이다.
"""


def index_record(kr_market):
    """발행본이 인쇄한 지수 종가 그대로 한 행."""
    return {'report_date': (kr_market or {}).get('report_date'),
            'indices': {name: float(row['close'])
                        for name, row in ((kr_market or {}).get('indices') or {}).items()
                        if isinstance(row, dict) and row.get('close') is not None}}


def index_series(rows):
    """원장 → {지수: [(date, close), ...]} — finalize() 가 먹는 모양."""
    out = {}
    for row in sorted(rows or [], key=lambda r: r.get('report_date') or ''):
        d = row.get('report_date')
        if not d:
            continue
        for name, v in (row.get('indices') or {}).items():
            if v is None:
                continue
            out.setdefault(name, []).append((d, float(v)))
    return out


class StaleIndexData(RuntimeError):
    """종가와 거래일이 서로 다른 세션을 가리킨다 — 이 실행의 산출물은 전부 잘못 적힌다."""


def resolve_report_date(naver_dates, yf_date, today):
    """거래일 = 종가를 준 원천(네이버)의 거래일. → (date, notes)

    yfinance ^KS11 날짜를 썼더니, Actions 지연으로 10/12 예약 실행이 10/13 02:27 KST 에
    돌 때 야후는 아직 10/08 이 마지막 행이라 네이버의 10/12 종가가 10/08 로 적혔다.
    네이버 날짜가 없을 때만 yfinance → 오늘(KST) 순으로 물러선다.
    """
    seen = {d for d in (naver_dates or {}).values() if d}
    if len(seen) > 1:
        raise StaleIndexData(f"지수별 거래일이 다르다: {dict(naver_dates)}")
    notes = []
    if seen:
        got = seen.pop()
        if yf_date and yf_date != got:
            notes.append(f"yfinance ^KS11 마지막 행 {yf_date} ≠ 네이버 거래일 {got} — 네이버를 따른다")
        return got, notes
    return (yf_date or today), notes


def ledger_conflicts(rows, record):
    """이 행을 원장에 쓰면 역사를 고쳐 쓰게 되는가. 문제 목록(빈 목록 = 통과).

    - 원장 최신일보다 이른 날짜: 늦게 돈 실행이 지난 세션을 덮어쓴다(같은 날 재실행은 정상).
    - 다른 날짜와 모든 지수 종가가 같다: 한 세션이 두 날짜에 적혔다(어느 방향이든).
    직전 종가 연속성은 보지 않는다 — 하루만 수집을 놓쳐도 그 뒤 날마다 막힌다.
    """
    d = (record or {}).get('report_date')
    closes = (record or {}).get('indices') or {}
    problems = []
    dates = [r.get('report_date') for r in rows or [] if r.get('report_date')]
    latest = max(dates) if dates else None
    if d and latest and d < latest:
        problems.append(f"report_date {d} 가 원장 최신 {latest} 보다 이르다 — 늦게 돈 실행이 "
                        "지난 세션을 덮어쓰려 한다")
    if closes:
        for r in rows or []:
            other = r.get('report_date')
            ix = r.get('indices') or {}
            if other and other != d and all(ix.get(k) == v for k, v in closes.items()):
                problems.append(f"{d} 종가 {closes} 가 {other} 행과 같다 — 한 세션이 두 날짜에 "
                                "적힌다")
    return problems
