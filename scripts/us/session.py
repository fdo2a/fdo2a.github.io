"""「오늘의 장」 — 하루를 시간 축으로 읽기 위한 판정.

가격 맥락(price_context)이 「이 움직임이 큰가」를 답한다면 여기는 「하루가 어떻게
흘러갔나」를 답한다. 아시아·유럽이 어디서 끝났고, 밤사이 선물이 무엇을 했고,
평균적인 종목이 지수를 따라갔고, 어디서 끝났는가.

compute()는 순수하다 — 이미 받아 온 종가·봉 리스트가 들어오고 dict가 나간다.
네트워크는 collect_market_data.py에만 있다. price_context.compute()와 같은 계약이다.

글로벌 지수는 collect_market_data.py의 GROUPS에 넣지 않는다. 그쪽은
completeness()가 순회하는 코어 목록이라, 도쿄나 홍콩이 쉬는 날 발행이 멈춘다.
"""

import datetime as _dt

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


FUTURES = (('ES', 'ES=F'), ('NQ', 'NQ=F'))
GAP_FLAT_PCT = 0.15
_OPEN = (9, 30)      # ET 정규장 개장
_CLOSE = (16, 0)     # ET 정규장 마감
_MAX_GAP_DAYS = 4    # 주말·연휴를 건너뛴 직전 거래일까지만


def _parse_et(t):
    try:
        return _dt.datetime.fromisoformat(str(t))
    except (ValueError, TypeError):
        return None


def overnight(bars, report_date):
    """전일 16:00 ET 초과 ~ 당일 09:30 ET 미만의 고·저와 그 시각.

    이 창은 ET 달력 경계를 넘는다. 날짜 하나로 거르면 앞 절반(전날 저녁)이
    통째로 사라진다 — 수집 쪽이 tz-aware로 변환해 넘기는 이유다.
    """
    day = _dt.date.fromisoformat(str(report_date))
    usable = []
    for b in bars or []:
        ts = _parse_et(b.get('t'))
        if ts is None or not (_finite(b.get('high')) and _finite(b.get('low'))):
            continue
        usable.append((ts, b))

    # 저녁 쪽은 **직전 한 세션만** 담는다. 며칠치 저녁을 한 창에 넣으면 고·저가
    # 그날 밤 값이 아니게 된다 — 2026-08-27 실전 수집에서 ES 봉이 33개가 아니라
    # 61개로 나왔고 저점이 이틀 전 값이었다.
    evenings = [ts.date() for ts, _ in usable
                if ts.date() < day and (ts.hour, ts.minute) >= _CLOSE
                and (day - ts.date()).days <= _MAX_GAP_DAYS]
    prev = max(evenings) if evenings else None

    picked = []
    for ts, b in usable:
        hm = (ts.hour, ts.minute)
        if ts.date() == day and hm < _OPEN:
            picked.append((ts, b))
        elif prev and ts.date() == prev and hm >= _CLOSE:
            picked.append((ts, b))
    if not picked:
        return None
    hi = max(picked, key=lambda p: p[1]['high'])
    lo = min(picked, key=lambda p: p[1]['low'])
    high, low = float(hi[1]['high']), float(lo[1]['low'])
    return {'high': round(high, 2), 'high_t': hi[0].strftime('%H:%M'),
            'low': round(low, 2), 'low_t': lo[0].strftime('%H:%M'),
            'range_pct': round((high / low - 1) * 100, 2) if low else None,
            'bars': len(picked)}


def gap(market_data, intraday, name):
    """정규장 시가 대비 전일 종가. **현물 지수 기준.**

    선물로 계산하면 계약 롤오버 때 불연속이 섞인다. 선물은 야간 궤적에만 쓴다.
    """
    row = ((market_data or {}).get('indices') or {}).get(name) or {}
    day = (intraday or {}).get(name) or {}
    last, chg, op = row.get('last'), row.get('chg'), day.get('open')
    if not (_finite(last) and _finite(chg) and _finite(op)):
        return None
    prev = last - chg
    if not prev:
        return None
    return round((op / prev - 1) * 100, 2)


def gap_direction(gap_pct):
    if gap_pct is None:
        return None
    if abs(gap_pct) < GAP_FLAT_PCT:
        return '보합 출발'
    return '상승 출발' if gap_pct > 0 else '하락 출발'


PARTICIPATION_MIN_PP = 0.4   # 2년치 |차| 중앙값 0.33%p 바로 위. 최적값이 아니라 읽기용 컷.
TAPE_INDICES = ('S&P 500', 'Nasdaq', 'Russell 2000')
# 경계는 1일차 관측 뒤 확정한다(스펙 「열린 항목」). 초안값.
TAPE_HIGH, TAPE_LOW = 75, 25


def participation(closes, dates, report_date=None):
    """동일가중이 시총가중을 따라갔나 — 「평균적인 종목이 지수를 따라갔나」.

    시장 폭(breadth)이 아니다. 등락 종목 수를 세지 않으므로 그렇게 부르지도
    않는다. 섹터·시총 구성 차이만으로도 이 값은 움직인다.
    """
    pairs, seen = {}, set()
    for t in (CAP_WEIGHT, EQUAL_WEIGHT):
        cs = (closes or {}).get(t) or []
        ds = (dates or {}).get(t) or []
        if len(cs) != len(ds) or len(cs) < 2:
            return None
        pairs[t] = {d: c for d, c in zip(ds, cs) if _finite(c)}
        seen |= {str(d) for d in ds}
    common = sorted(set(pairs[CAP_WEIGHT]) & set(pairs[EQUAL_WEIGHT]))
    if len(common) < 2:
        return None
    a, b = common[-2], common[-1]
    if report_date and b != str(report_date):
        return None       # 오늘 값이 아니면 오늘 것인 양 내보내지 않는다
    # 한쪽 종가가 비어 세션을 건너뛰면 이틀치가 하루치로 둔갑한다. 어느 쪽 달력에든
    # 그 사이 세션이 있으면 구멍이 있는 것 — 주말은 양쪽 모두에 없으므로 통과한다.
    if any(a < d < b for d in seen):
        return None

    def pct(t):
        prev, cur = pairs[t][a], pairs[t][b]
        return None if not prev else (cur / prev - 1) * 100

    cap, eq = pct(CAP_WEIGHT), pct(EQUAL_WEIGHT)
    if cap is None or eq is None:
        return None
    g = round(eq - cap, 2)
    if abs(g) < PARTICIPATION_MIN_PP:
        band = '중립'
    elif cap > 0:
        band = '고르게 오름' if g > 0 else '소수가 끌어올림'
    else:
        band = '소수가 끌어내림' if g > 0 else '고르게 내림'
    return {'gap_pp': g, 'spy_pct': round(cap, 2), 'date': b, 'band': band}


def tape(intraday):
    """종가가 당일 등락폭의 몇 % 지점인가.

    입력은 intraday.json 값만이다. 그 파일의 close는 30분 마지막 봉이라
    market_data.json의 일간 확정 종가와 다르다(2026-08-27 실측: 7,730.11 vs
    7,730.99). 두 출처를 섞지 않고, 이 종가를 그날 종가로 인용하지도 않는다.
    """
    out = {}
    for name in TAPE_INDICES:
        d = (intraday or {}).get(name)
        if not d:
            continue
        hi, lo, cl = d.get('high'), d.get('low'), d.get('close')
        if not (_finite(hi) and _finite(lo) and _finite(cl)) or hi == lo:
            out[name] = None
            continue
        raw = (cl - lo) / (hi - lo) * 100
        # 판정은 반올림 **전** 값으로. 74.6을 75로 올린 뒤 고점권이라 부르면
        # 경계가 실제보다 0.5 넓어진다.
        band = ('고점권 마감' if raw >= TAPE_HIGH
                else '저점권 마감' if raw <= TAPE_LOW else '중단 마감')
        out[name] = {'close_position': round(raw), 'band': band}
    return out


def compute(closes, dates, market_data, intraday, futures_bars, report_date):
    """「오늘의 장」 블록. 어느 조각이 없어도 나머지는 나온다."""
    us_pct = (((market_data or {}).get('indices') or {}).get('S&P 500') or {}).get('pct')
    g = {}
    for key, pairs in (('asia', ASIA), ('europe', EUROPE)):
        rows = region_rows(closes, dates, pairs, report_date)
        g[key] = {'rows': rows, 'alignment': alignment(rows, us_pct)}

    contracts = {}
    for label, ticker in FUTURES:
        w = overnight((futures_bars or {}).get(ticker), report_date)
        if w:
            contracts[label] = w

    gaps = {n: gap(market_data, intraday, n) for n in TAPE_INDICES}
    gaps = {n: v for n, v in gaps.items() if v is not None}
    return {
        'report_date': str(report_date),
        'global_close': g,
        'futures': {'contracts': contracts, 'gap': gaps,
                    'direction': gap_direction(gaps.get('S&P 500'))},
        'participation': participation(closes, dates, report_date),
        'tape': tape(intraday),
    }
