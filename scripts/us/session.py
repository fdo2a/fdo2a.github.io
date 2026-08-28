"""「오늘의 장」 — 하루를 시간 축으로 읽기 위한 판정.

가격 맥락(price_context)이 「이 움직임이 큰가」를 답한다면 여기는 「하루가 어떻게
흘러갔나」를 답한다. 아시아·유럽이 어디서 끝났고, 밤사이 선물이 무엇을 했고,
평균적인 종목이 지수를 따라갔고, 어디서 끝났는가.

compute()는 순수하다 — 이미 받아 온 종가·봉 리스트가 들어오고 dict가 나간다.
네트워크는 collect_market_data.py에만 있다. price_context.compute()와 같은 계약이다.

글로벌 지수는 collect_market_data.py의 GROUPS에 넣지 않는다. 그쪽은
completeness()가 순회하는 코어 목록이라, 도쿄나 홍콩이 쉬는 날 발행이 멈춘다.
"""

ASIA = (('닛케이', '^N225'), ('항셍', '^HSI'), ('상해종합', '000001.SS'))
EUROPE = (('DAX', '^GDAXI'), ('FTSE100', '^FTSE'), ('유로스톡스50', '^STOXX50E'))

# 참여도의 두 다리. 지수 거래량은 쓰지 않는다 — 야후가 ^RUT에 ^GSPC의 거래량을
# 그대로 돌려준다(2026-08-28 실측, 배치가 아니라 개별 조회에서도 동일).
EQUAL_WEIGHT, CAP_WEIGHT = 'RSP', 'SPY'

HISTORY_TICKERS = sorted({t for _, t in ASIA + EUROPE} | {EQUAL_WEIGHT, CAP_WEIGHT})

FLAT_PCT = 0.1              # 이 안이면 방향을 말하지 않는다
MIN_REGION_INDICES = 2      # 지수 하나로 지역을 대표시키지 않는다


def _finite(x):
    return isinstance(x, (int, float)) and x == x and x not in (float('inf'), float('-inf'))


def region_rows(closes, dates, pairs, report_date):
    """report_date 이하의 마지막 세션 종가와 전일 대비.

    못 구한 지수는 조용히 빠진다 — 한 지역이 통째로 비는 날은 그 문단을 생략하고,
    한 종만 남는 날은 방향 판정을 포기한다(alignment 참조).
    """
    out = []
    for name, ticker in pairs:
        cs = (closes or {}).get(ticker) or []
        ds = (dates or {}).get(ticker) or []
        if len(cs) != len(ds) or len(cs) < 2:
            continue
        idx = [i for i, d in enumerate(ds) if str(d) <= str(report_date)]
        if len(idx) < 2:
            continue
        i = idx[-1]
        prev, cur = cs[i - 1], cs[i]
        if not (_finite(prev) and _finite(cur)) or prev == 0:
            continue
        out.append({'name': name, 'ticker': ticker, 'close': round(float(cur), 2),
                    'pct': round((cur / prev - 1) * 100, 2), 'date': str(ds[i])})
    return out


def _sign(v):
    if v is None or abs(v) < FLAT_PCT:
        return 0
    return 1 if v > 0 else -1


def alignment(rows, us_pct):
    """그 지역과 미국이 같은 방향이었나.

    지역 **내부**의 일치 여부가 아니다 — 그것은 `mixed`가 따로 말한다. 이 판정이
    「엇갈림」인 날 리포트가 침묵하면 발행 게이트가 막는다.
    """
    if len(rows) < MIN_REGION_INDICES:
        return None
    avg = sum(r['pct'] for r in rows) / len(rows)
    rs, us = _sign(avg), _sign(us_pct)
    if rs == 0 or us == 0:
        label = '보합'
    else:
        label = '이어감' if rs == us else '엇갈림'
    signs = {_sign(r['pct']) for r in rows}
    return {'label': label, 'avg_pct': round(avg, 2),
            'mixed': len({s for s in signs if s}) > 1}
