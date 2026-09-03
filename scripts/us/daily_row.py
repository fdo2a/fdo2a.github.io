"""일별 종가 행을 **하나의 기준일에 묶어** 만든다.

야후의 일봉은 종목마다 하루가 언제 시작하고 끝나는지가 다르다. 주식 지수는 16:00 ET
에 닫히고 그날 봉이 확정되지만, 통화쌍은 24시간 돌아서 다음 날짜 봉이 장중에 이미
열려 있다. 그래서 「마지막 봉」을 종목마다 각자 집으면 같은 표 안에서 기준일이 갈린다
— 2026-09-02 발행본에서 DXY 만 09-02 이고 USD/KRW·USD/JPY·EUR/USD 는 09-03 이었다.

기준일은 **S&P 500 이 닫힌 날**로 잡는다. 지수는 롤오버하지 않으므로 이 앵커 자체는
흔들리지 않고, 나머지는 전부 그 이하의 마지막 봉을 쓴다. 채권 파이프라인이 쓰는
「기준일 이하의 마지막 값」과 같은 규율이다 — 자르지 말고 그 이하에서 고른다.
"""


def anchor_date(series_dates, reference):
    """기준 종목이 닫힌 마지막 날짜. 그 종목이 없으면 앵커도 없다(None)."""
    dates = (series_dates or {}).get(reference) or []
    return max(dates) if dates else None


def row_from_closes(dates, values, as_of=None):
    """(dates, values) -> {last, chg, pct, date}. `as_of` 이후 봉은 안 본다.

    앵커 이하 세션이 둘 미만이면 전일 대비를 못 만들므로 None 을 돌려준다 — 없는
    비교를 지어내느니 그 행을 비우는 쪽이 낫다.
    """
    rows = [(d, v) for d, v in zip(dates or [], values or [])
            if v is not None and (as_of is None or d <= as_of)]
    rows.sort()
    if len(rows) < 2:
        return None
    (_, prev), (date, cur) = rows[-2], rows[-1]
    if not prev:
        return None
    return {'last': cur, 'chg': cur - prev, 'pct': (cur / prev - 1) * 100, 'date': date}


def clip_series(closes, dates, as_of):
    """이력을 기준일까지만 남긴다 — (closes, dates) 그대로의 모양으로 돌려준다.

    표만 앵커로 자르고 이력을 안 자르면 같은 발행본 안에서 시각이 갈린다. 표의 FX 는
    09-02 인데 스탠스 트리거와 가격 위치 판정은 09-03 봉을 보는 식이다. 통화쌍은
    3년 구간에서 주식 지수보다 26세션쯤 더 열리므로(2026-08-28 실측) 이 어긋남은
    드문 사고가 아니라 상시 조건이다.
    """
    if not closes or not dates or as_of is None:
        return closes, dates
    keep = [(d, c) for d, c in zip(dates, closes) if d <= as_of]
    return [c for _, c in keep], [d for d, _ in keep]
