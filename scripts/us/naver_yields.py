"""네이버 국채 종가 — 발행용 미국 커브의 기준일을 하나로 맞춘다.

**왜 이 모듈이 있나.** 2026-07-28 이래 발행용 커브는 5Y/10Y/30Y 야후 스팟에 2Y 만
FRED DGS2(T-1) 였다. 야후에 2년 스팟 지수가 없어서(^UST2Y 부재, 2YY=F 는 선물이라
DGS2 와 20bp 이상 벌어진다) 어쩔 수 없이 만든 우회인데, 그 탓에 2s10s 의 두 다리가
서로 다른 날짜를 봤다 — 90영업일 실측으로 중앙 3.4bp·90분위 7.0bp·최대 11.8bp 가
날짜 차이만으로 생겼고, 40bp 짜리 스프레드에서 무시할 수 없는 크기다.

네이버는 전 만기를 **17:05 ET 종가**(SIFMA 국채 현물 마감) 한 날짜로 준다. 실측:

  - 종가 스탬프 432건 중 90.0% 가 정확히 17:05:00, 나머지는 막판 틱과 조기 폐장 14:30
  - 4개 만기 × 120영업일에서 **120/120 일 전 만기 날짜 일치, 결측 0**
  - FRED CMT 대비 중앙 0.1~0.4bp (2Y +0.10 · 5Y +0.10 · 10Y -0.40 · 30Y +0.20)

값이 FRED 와 사실상 같으면서 날짜만 맞는다는 것이 요점이다.

**시각이 아니라 날짜로 맞춘다.** 스탬프가 10% 는 17:05:00 이 아니므로(막판 틱
16:59:21, 조기 폐장 14:30:00) 시각 문자열로 매칭하면 그 날들이 통째로 빠진다.
"""


def parse_prices(payload):
    """네이버 `marketIndex/prices` 응답 -> [(date, level)] 오래된 것 -> 최신.

    `pageSize` 는 10 미만을 거부하므로(`too_small`) 호출부가 10 이상을 준다.
    """
    rows = []
    for row in ((payload or {}).get('result') or []):
        stamp, close = row.get('localTradedAt'), row.get('closePrice')
        if not stamp or close in (None, ''):
            continue
        try:
            rows.append((str(stamp)[:10], float(str(close).replace(',', ''))))
        except ValueError:
            continue
    return sorted(rows)


def shared_dates(series):
    """전 만기가 **모두** 값을 가진 날짜들. 비교일을 여기서만 고른다.

    합집합에서 고르면 한 만기에만 있는 날짜가 비교 기준이 되고, 그 만기를 뺀
    나머지는 전일 대비가 조용히 빈 채로 나간다(codex 검토 2026-09-04).
    """
    shared = None
    for rows in (series or {}).values():
        dates = {d for d, _ in rows}
        shared = dates if shared is None else (shared & dates)
    return sorted(shared or [])


def _gap_between(series, lo, hi):
    """어느 만기든 lo 와 hi 사이에 제 세션을 갖고 있으면 참 — 비교 구간이 늘어난 것."""
    return any(lo < d < hi for rows in (series or {}).values() for d, _ in rows)


def common_date(series):
    """전 만기가 공유하는 가장 최근 날짜. 하나라도 못 따라오면 그 날짜는 못 쓴다.

    만기별 마지막 행을 각자 집으면 지금 고치려는 어긋남이 그대로 재현된다.
    """
    dates = shared_dates(series)
    return dates[-1] if dates else None


def build_curve(series, week_back=5, source='Naver', expected_date=None):
    """만기 -> 발행용 행. 전 만기가 같은 기준일·같은 주간 비교일을 쓴다.

    공유 날짜가 없으면 **닫히면서 실패한다**(None). 만기마다 제 날짜를 집어 조용히
    어긋난 커브를 내보내느니 커브를 안 내보내는 쪽이 낫다.

    `expected_date` 를 주면 그 세션이 아닐 때도 None 이다. 크론은 서머타임을 몰라서
    두 슬롯이 연중 다 뜨는데, 겨울의 이른 슬롯(21:30 UTC = 16:30 EST)은 국채 마감
    17:05 EST **전**이라 네이버가 아직 전 거래일 종가만 갖고 있다. 그걸 받아 쓰면
    주식은 당일·커브는 전일인 리포트가 나가고, 게다가 그 회차가 complete 로 커밋되면
    제대로 된 회차가 멱등 가드에 막힌다(codex 검토 2026-09-04).
    """
    base = common_date(series)
    if not base or (expected_date and base != expected_date):
        return None
    ordered = [d for d in shared_dates(series) if d <= base]
    idx = ordered.index(base)
    prev = ordered[idx - 1] if idx >= 1 else None
    week = ordered[idx - week_back] if idx >= week_back else None
    # 교집합에서 고른 비교일이 **실제 전 거래일**인지 확인한다. 한 만기만 어제를
    # 빠뜨리면 공통 비교일이 그저께로 밀리고, 그 2세션 변화를 「전일比」로 인쇄하면
    # 조용히 틀린다. 지어내지 말고 비운다 (codex 검토 2026-09-04).
    if prev and _gap_between(series, prev, base):
        prev = None

    out = {}
    for tenor, rows in series.items():
        by_date = dict(rows)
        level = by_date.get(base)
        if level is None:
            return None
        before = by_date.get(prev)
        wk = by_date.get(week)
        out[tenor] = {
            'level': round(level, 3), 'date': base,
            'bp': (level - before) * 100 if before is not None else None,
            'week_ago': round(wk, 3) if wk is not None else None,
            'week_ago_date': week if wk is not None else None,
            'source': source,
        }
    return out
