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
