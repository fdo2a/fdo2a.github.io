# 시황 정리 보강 (「오늘의 장」 섹션) 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** US·KR 브리프에 하루를 시간 축으로 읽는 「오늘의 장」 섹션을 신설하고, 그 섹션이 매일 실제로 채워지도록 데이터 계약과 발행 게이트를 붙인다.

**Architecture:** 수집 단계(GitHub Actions)가 판정이 끝난 `session` 블록을 만들고, writer는 그 값을 재계산하지 않고 서술만 한다. 발행 게이트가 누락·침묵·오칭을 막는다. `price_context`·`macro_metrics`가 이미 쓰는 패턴 그대로다. 계산 로직은 전부 순수 함수(네트워크 없음)로 두고, 네트워크는 `collect_*.py`에만 둔다.

**Tech Stack:** Python 3, 표준 라이브러리 + `yfinance`(수집 쪽만), `pytest`. 새 의존성 없음.

**Spec:** `docs/superpowers/specs/2026-08-28-market-recap-enrichment-design.md`

## Global Constraints

- **순수 함수 원칙**: `scripts/us/session.py`·`scripts/kr/session.py`는 네트워크를 호출하지 않는다. 입력은 이미 받아 온 종가·봉 리스트, 출력은 dict.
- **비-코어**: 이 블록의 실패는 데이터셋 전체를 실패시키지 않는다. 글로벌 6종을 `collect_market_data.py`의 `GROUPS`에 **넣지 않는다** — `completeness()`가 `GROUPS`를 순회하므로 일본·홍콩 휴장일에 발행이 멈춘다.
- **결측은 `None`**, 「모른다」를 「아니다」로 직렬화하지 않는다.
- **날짜 정렬**: 두 시리즈를 비교할 때 리스트 위치가 아니라 **세션 날짜로 맞춘다**(`price_context.aligned_changes`와 같은 규율).
- **표준시**: 야간 선물 창은 ET 달력 경계를 넘는다. tz-aware 변환 후 자른다. naive 날짜 필터 금지. `KRW=X`는 야후가 `Europe/London`으로 준다.
- **통제 어휘 (완전 일치, 자유 문구 금지)**
  - `alignment`: `이어감` · `엇갈림` · `보합`
  - `futures.direction`: `상승 출발` · `하락 출발` · `보합 출발`
  - `participation.band`: `고르게 오름` · `소수가 끌어올림` · `고르게 내림` · `소수가 끌어내림` · `중립`
  - `tape.band`: `고점권 마감` · `중단 마감` · `저점권 마감`
- **문턱값**: `FLAT_PCT = 0.1` / `GAP_FLAT_PCT = 0.15` / `PARTICIPATION_MIN_PP = 0.4` / `STALE_SESSIONS = 3`
- **금지 표현 (게이트가 차단)**: `상승 종목 비율`, `등락 종목 수`, `시장 폭`, `breadth`, 내부 필드명(`session`·`participation`·`gap_pct`·`tape`·`close_position`·`global_close`), 발행본 산문의 `§숫자`
- **테스트 실행**: 레포 루트에서 `python3 -m pytest scripts/us/tests/... -v` (루트의 `scripts/conftest.py`가 `sys.path`를 잡는다)
- **커밋 전 codex 검토** (2026-08-24 사용자 지시): 각 커밋 묶음은 `/codex:rescue` 검토를 거친다.

---

### Task 1: 글로벌 마감과 방향 판정

**Files:**
- Create: `scripts/us/session.py`
- Test: `scripts/us/tests/test_session.py`

**Interfaces:**
- Consumes: `closes = {ticker: [float]|None}`, `dates = {ticker: ['YYYY-MM-DD']|None}` — `collect_histories()`가 이미 만드는 모양 그대로.
- Produces: `ASIA`, `EUROPE`, `HISTORY_TICKERS`, `region_rows(closes, dates, pairs, report_date) -> list[dict]`, `alignment(rows, us_pct) -> dict|None`

- [ ] **Step 1: Write the failing test**

```python
# scripts/us/tests/test_session.py
from us import session


def _series(vals, start='2026-08-20'):
    import datetime as dt
    d0 = dt.date.fromisoformat(start)
    return vals, [str(d0 + dt.timedelta(days=i)) for i in range(len(vals))]


def test_region_rows_uses_last_session_on_or_before_report_date():
    c1, d1 = _series([100.0, 101.0, 99.0])          # 08-20, 08-21, 08-22
    closes = {'^N225': c1}
    dates = {'^N225': d1}
    rows = session.region_rows(closes, dates, (('닛케이', '^N225'),), '2026-08-21')
    assert rows == [{'name': '닛케이', 'ticker': '^N225', 'close': 101.0,
                     'pct': 1.0, 'date': '2026-08-21'}]


def test_region_rows_drops_series_without_two_bars():
    closes = {'^N225': [100.0]}
    dates = {'^N225': ['2026-08-21']}
    assert session.region_rows(closes, dates, (('닛케이', '^N225'),), '2026-08-21') == []


def test_alignment_divergent_when_region_and_us_disagree():
    rows = [{'pct': +0.31}, {'pct': -0.79}, {'pct': -0.71}]   # 평균 -0.40
    a = session.alignment(rows, us_pct=+0.72)
    assert a['label'] == '엇갈림'
    assert a['mixed'] is True          # 지역 안에서도 부호가 갈렸다


def test_alignment_needs_two_surviving_indices():
    assert session.alignment([{'pct': +1.0}], us_pct=+0.5) is None
    assert session.alignment([], us_pct=+0.5) is None


def test_alignment_flat_when_either_side_is_inside_the_dead_band():
    assert session.alignment([{'pct': 0.05}, {'pct': 0.02}], us_pct=+0.9)['label'] == '보합'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest scripts/us/tests/test_session.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'us.session'`

- [ ] **Step 3: Write minimal implementation**

```python
# scripts/us/session.py
"""「오늘의 장」 — 하루를 시간 축으로 읽기 위한 판정.

가격 맥락(price_context)이 「이 움직임이 큰가」를 답한다면 여기는 「하루가 어떻게
흘러갔나」를 답한다. 아시아·유럽이 어디서 끝났고, 밤사이 선물이 무엇을 했고,
평균적인 종목이 지수를 따라갔고, 어디서 끝났는가.

compute()는 순수하다 — 이미 받아 온 종가·봉 리스트가 들어오고 dict가 나간다.
네트워크는 collect_market_data.py에만 있다. price_context.compute()와 같은 계약이다.
"""

ASIA = (('닛케이', '^N225'), ('항셍', '^HSI'), ('상해종합', '000001.SS'))
EUROPE = (('DAX', '^GDAXI'), ('FTSE100', '^FTSE'), ('유로스톡스50', '^STOXX50E'))

# 참여도의 두 다리. 지수 거래량은 쓰지 않는다 — 야후가 ^RUT에 ^GSPC의 거래량을
# 그대로 돌려준다(2026-08-28 실측, 개별 조회에서도 동일).
EQUAL_WEIGHT, CAP_WEIGHT = 'RSP', 'SPY'

HISTORY_TICKERS = sorted({t for _, t in ASIA + EUROPE} | {EQUAL_WEIGHT, CAP_WEIGHT})

FLAT_PCT = 0.1              # 이 안이면 방향을 말하지 않는다
MIN_REGION_INDICES = 2      # 지수 하나로 지역을 대표시키지 않는다


def _finite(x):
    return isinstance(x, (int, float)) and x == x and x not in (float('inf'), float('-inf'))


def region_rows(closes, dates, pairs, report_date):
    """report_date 이하의 마지막 세션 종가와 전일 대비. 못 구한 지수는 빠진다."""
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
    """그 지역과 미국이 같은 방향이었나. 지역 내부의 일치 여부가 아니다."""
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest scripts/us/tests/test_session.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add scripts/us/session.py scripts/us/tests/test_session.py
git commit -m "시황: 글로벌 마감과 미국 대비 방향 판정"
```

---

### Task 2: 야간 선물 창과 현물 갭

**Files:**
- Modify: `scripts/us/session.py`
- Test: `scripts/us/tests/test_session.py`

**Interfaces:**
- Consumes: `bars = [{'t': '2026-08-26T18:30:00-04:00', 'high': float, 'low': float}]` — ET로 변환된 30분봉. 변환은 수집 쪽(Task 5)이 한다.
- Produces: `overnight(bars, report_date) -> dict|None`, `gap(market_data, intraday, name) -> float|None`, `gap_direction(gap_pct) -> str|None`

- [ ] **Step 1: Write the failing test**

```python
def test_overnight_window_spans_the_et_calendar_boundary():
    bars = [
        {'t': '2026-08-26T15:30:00-04:00', 'high': 9, 'low': 9},    # 정규장 — 제외
        {'t': '2026-08-26T18:30:00-04:00', 'high': 7741.25, 'low': 7700.0},
        {'t': '2026-08-27T04:30:00-04:00', 'high': 7730.0, 'low': 7690.25},
        {'t': '2026-08-27T10:00:00-04:00', 'high': 9, 'low': 9},    # 개장 후 — 제외
    ]
    w = session.overnight(bars, '2026-08-27')
    assert w['high'] == 7741.25 and w['high_t'] == '18:30'
    assert w['low'] == 7690.25 and w['low_t'] == '04:30'
    assert w['bars'] == 2


def test_overnight_returns_none_without_bars_in_the_window():
    bars = [{'t': '2026-08-27T10:00:00-04:00', 'high': 1, 'low': 1}]
    assert session.overnight(bars, '2026-08-27') is None


def test_gap_is_computed_on_the_cash_index_not_the_future():
    market = {'indices': {'S&P 500': {'last': 7730.99, 'chg': 55.0}}}
    intraday = {'S&P 500': {'open': 7710.34}}
    g = session.gap(market, intraday, 'S&P 500')
    assert round(g, 2) == 0.45          # 7710.34 / (7730.99-55.0) - 1
    assert session.gap_direction(g) == '상승 출발'
    assert session.gap_direction(0.05) == '보합 출발'
    assert session.gap_direction(-0.9) == '하락 출발'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest scripts/us/tests/test_session.py -k "overnight or gap" -v`
Expected: FAIL — `AttributeError: module 'us.session' has no attribute 'overnight'`

- [ ] **Step 3: Write minimal implementation**

```python
# scripts/us/session.py 에 추가
import datetime as _dt

FUTURES = (('ES', 'ES=F'), ('NQ', 'NQ=F'))
GAP_FLAT_PCT = 0.15
_OPEN = (9, 30)     # ET 정규장 개장
_CLOSE = (16, 0)    # ET 정규장 마감


def _parse_et(t):
    """'2026-08-27T04:30:00-04:00' → aware datetime. 실패하면 None."""
    try:
        return _dt.datetime.fromisoformat(str(t))
    except ValueError:
        return None


def overnight(bars, report_date):
    """전일 16:00 ET 초과 ~ 당일 09:30 ET 미만. ET 달력 경계를 넘으므로
    날짜 하나로 거르면 절반이 사라진다."""
    day = _dt.date.fromisoformat(str(report_date))
    picked = []
    for b in bars or []:
        ts = _parse_et(b.get('t'))
        if ts is None or not (_finite(b.get('high')) and _finite(b.get('low'))):
            continue
        hm = (ts.hour, ts.minute)
        if ts.date() == day and hm < _OPEN:
            picked.append((ts, b))
        elif ts.date() < day and hm >= _CLOSE:
            # 직전 거래일의 마감 이후. 주말·휴장은 봉이 없으므로 자연히 빠진다.
            if (day - ts.date()).days <= 4:
                picked.append((ts, b))
    if not picked:
        return None
    hi = max(picked, key=lambda p: p[1]['high'])
    lo = min(picked, key=lambda p: p[1]['low'])
    return {'high': round(float(hi[1]['high']), 2), 'high_t': hi[0].strftime('%H:%M'),
            'low': round(float(lo[1]['low']), 2), 'low_t': lo[0].strftime('%H:%M'),
            'bars': len(picked)}


def gap(market_data, intraday, name):
    """정규장 시가 대비 전일 종가. **현물 지수 기준** — 선물로 계산하면
    계약 롤오버 때 불연속이 섞인다."""
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest scripts/us/tests/test_session.py -v`
Expected: PASS (8 passed)

- [ ] **Step 5: Commit**

```bash
git add scripts/us/session.py scripts/us/tests/test_session.py
git commit -m "시황: 야간 선물 창(ET 경계 통과)과 현물 갭"
```

---

### Task 3: 참여도 (동일가중 − 시총가중)

**Files:**
- Modify: `scripts/us/session.py`
- Test: `scripts/us/tests/test_session.py`

**Interfaces:**
- Produces: `participation(closes, dates) -> dict|None` — `{'gap_pp': float, 'spy_pct': float, 'band': str}`

- [ ] **Step 1: Write the failing test**

```python
def test_participation_labels_a_narrow_rally():
    # SPY +0.66%, RSP -0.29% → 차 -0.95%p (2026-08-27 실측 근사)
    closes = {'SPY': [100.0, 100.66], 'RSP': [100.0, 99.71]}
    dates = {'SPY': ['2026-08-26', '2026-08-27'], 'RSP': ['2026-08-26', '2026-08-27']}
    p = session.participation(closes, dates)
    assert p['band'] == '소수가 끌어올림'
    assert p['gap_pp'] == -0.95


def test_participation_is_neutral_inside_the_threshold():
    closes = {'SPY': [100.0, 100.5], 'RSP': [100.0, 100.7]}
    dates = {'SPY': ['2026-08-26', '2026-08-27'], 'RSP': ['2026-08-26', '2026-08-27']}
    assert session.participation(closes, dates)['band'] == '중립'


def test_participation_labels_a_broad_decline():
    closes = {'SPY': [100.0, 99.5], 'RSP': [100.0, 99.0]}
    dates = {'SPY': ['2026-08-26', '2026-08-27'], 'RSP': ['2026-08-26', '2026-08-27']}
    assert session.participation(closes, dates)['band'] == '고르게 내림'


def test_participation_requires_a_shared_session_date():
    closes = {'SPY': [100.0, 100.5], 'RSP': [100.0, 101.0]}
    dates = {'SPY': ['2026-08-26', '2026-08-27'], 'RSP': ['2026-08-25', '2026-08-26']}
    assert session.participation(closes, dates) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest scripts/us/tests/test_session.py -k participation -v`
Expected: FAIL — `AttributeError: ... has no attribute 'participation'`

- [ ] **Step 3: Write minimal implementation**

```python
# scripts/us/session.py 에 추가
PARTICIPATION_MIN_PP = 0.4      # 2년치 |차| 중앙값 0.33%p 바로 위. 최적값이 아니라 읽기용 컷.


def participation(closes, dates):
    """동일가중이 시총가중을 따라갔나 — 「평균적인 종목이 지수를 따라갔나」.

    시장 폭(breadth)이 아니다. 등락 종목 수를 세지 않는다.
    """
    pairs = {}
    for t in (CAP_WEIGHT, EQUAL_WEIGHT):
        cs = (closes or {}).get(t) or []
        ds = (dates or {}).get(t) or []
        if len(cs) != len(ds) or len(cs) < 2:
            return None
        pairs[t] = {d: c for d, c in zip(ds, cs) if _finite(c)}
    common = sorted(set(pairs[CAP_WEIGHT]) & set(pairs[EQUAL_WEIGHT]))
    if len(common) < 2:
        return None
    a, b = common[-2], common[-1]

    def pct(t):
        p, c = pairs[t][a], pairs[t][b]
        return None if not p else (c / p - 1) * 100

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest scripts/us/tests/test_session.py -v`
Expected: PASS (12 passed)

- [ ] **Step 5: Commit**

```bash
git add scripts/us/session.py scripts/us/tests/test_session.py
git commit -m "시황: 참여도(동일가중 − 시총가중) 판정"
```

---

### Task 4: 마감 위치와 `compute()`

**Files:**
- Modify: `scripts/us/session.py`
- Test: `scripts/us/tests/test_session.py`

**Interfaces:**
- Produces: `tape(intraday) -> dict`, `compute(closes, dates, market_data, intraday, futures_bars, report_date) -> dict`

- [ ] **Step 1: Write the failing test**

```python
def test_tape_positions_the_close_inside_the_day_range():
    intraday = {'Nasdaq': {'open': 26365.29, 'close': 26539.56,
                           'low': 26273.87, 'high': 26553.27}}
    t = session.tape(intraday)
    assert t['Nasdaq']['close_position'] == 95      # (close-low)/(high-low)*100
    assert t['Nasdaq']['band'] == '고점권 마감'


def test_tape_is_null_when_the_range_is_degenerate_or_absent():
    assert session.tape({'Nasdaq': {'close': 1, 'low': 1, 'high': 1}})['Nasdaq'] is None
    assert session.tape({})== {}


def test_compute_assembles_every_block_and_survives_missing_pieces():
    closes = {'^N225': [100.0, 99.8], 'SPY': [100.0, 100.66], 'RSP': [100.0, 99.71]}
    dates = {t: ['2026-08-26', '2026-08-27'] for t in closes}
    market = {'indices': {'S&P 500': {'last': 7730.99, 'chg': 55.0, 'pct': 0.72}}}
    intraday = {'S&P 500': {'open': 7710.34, 'close': 7730.11,
                            'low': 7689.89, 'high': 7741.27}}
    out = session.compute(closes, dates, market, intraday,
                          futures_bars={}, report_date='2026-08-27')
    assert out['global_close']['asia']['rows'][0]['name'] == '닛케이'
    assert out['global_close']['asia']['alignment'] is None      # 살아남은 지수 1종
    assert out['global_close']['europe']['rows'] == []
    assert out['participation']['band'] == '소수가 끌어올림'
    assert out['futures']['contracts'] == {}                     # 봉이 없다
    assert out['futures']['gap']['S&P 500'] == 0.45
    assert out['report_date'] == '2026-08-27'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest scripts/us/tests/test_session.py -k "tape or compute" -v`
Expected: FAIL — `AttributeError: ... has no attribute 'tape'`

- [ ] **Step 3: Write minimal implementation**

```python
# scripts/us/session.py 에 추가
TAPE_INDICES = ('S&P 500', 'Nasdaq', 'Russell 2000')
# 경계는 1일차 관측 뒤 확정한다(스펙 「열린 항목」). 초안값.
TAPE_HIGH, TAPE_LOW = 75, 25


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
        pos = round((cl - lo) / (hi - lo) * 100)
        band = ('고점권 마감' if pos >= TAPE_HIGH
                else '저점권 마감' if pos <= TAPE_LOW else '중단 마감')
        out[name] = {'close_position': pos, 'band': band}
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

    gaps = {n: gap(market_data, intraday, n) for n in ('S&P 500', 'Nasdaq', 'Russell 2000')}
    gaps = {n: v for n, v in gaps.items() if v is not None}
    return {
        'report_date': str(report_date),
        'global_close': g,
        'futures': {'contracts': contracts, 'gap': gaps,
                    'direction': gap_direction(gaps.get('S&P 500'))},
        'participation': participation(closes, dates),
        'tape': tape(intraday),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest scripts/us/tests/test_session.py -v`
Expected: PASS (15 passed)

- [ ] **Step 5: Commit**

```bash
git add scripts/us/session.py scripts/us/tests/test_session.py
git commit -m "시황: 마감 위치 판정과 session 블록 조립"
```

---

### Task 5: 수집 배선 (US) — 1일차 롤아웃 지점

**Files:**
- Modify: `scripts/collect_market_data.py:127` (티커 합집합), `scripts/collect_market_data.py:388-406` (선물 봉), `scripts/collect_market_data.py:677` 부근 (`price_context` 호출 뒤)

**Interfaces:**
- Consumes: `session.HISTORY_TICKERS`, `session.compute(...)`, `session.FUTURES`
- Produces: `market_data.json`의 `session` 키. 커밋 대상 파일 목록은 그대로다.

- [ ] **Step 1: 이력 티커 합집합에 새 티커를 더한다**

`collect_histories()`(`scripts/collect_market_data.py:127`)의 import와 합집합을 고친다. **`GROUPS`에는 넣지 않는다** — `completeness()`가 `GROUPS`를 순회하므로 도쿄·홍콩 휴장일에 발행이 멈춘다.

```python
    from us.price_context import HISTORY_TICKERS as PC_TICKERS
    from us.stance_metrics import HISTORY_TICKERS as STANCE_TICKERS
    from us.session import HISTORY_TICKERS as SESSION_TICKERS

    tickers = sorted(set(STANCE_TICKERS) | set(PC_TICKERS) | set(SESSION_TICKERS)
                     | {t for _, t in SECTORS})
```

- [ ] **Step 2: 선물 30분봉을 ET로 변환해 받는 함수를 추가한다**

`collect_intraday()` 바로 아래에 넣는다.

```python
def collect_futures_bars():
    """야간 선물 봉. 야후 인덱스를 ET로 변환해 ISO 문자열로 넘긴다 —
    창이 ET 달력 경계를 넘으므로 순수 함수 쪽에서 naive 날짜로 자를 수 없다."""
    import yfinance as yf
    from us.session import FUTURES
    out = {}
    for _, t in FUTURES:
        def one(t=t):
            h = yf.Ticker(t).history(period='5d', interval='30m')
            if h is None or not len(h):
                return None
            h.index = h.index.tz_convert('America/New_York')
            return [{'t': i.isoformat(), 'high': float(r['High']), 'low': float(r['Low'])}
                    for i, r in h.iterrows()]
        out[t] = retry(one, attempts=2) or []
        time.sleep(1)
    return out
```

- [ ] **Step 3: `price_context` 계산 바로 뒤에서 `session`을 붙인다**

`scripts/collect_market_data.py:677` 부근, `data['price_context'] = pc` 블록 다음에 같은 모양으로 넣는다.

```python
    # 같은 계약: 비-코어, 실패해도 데이터셋은 산다. 「오늘의 장」이 읽을 재료.
    print('computing session context...')
    try:
        from us.session import compute as compute_session
        fut = collect_futures_bars()
        data['session'] = compute_session(closes, hist_dates, data, intraday,
                                          fut, report_date)
        s = data['session']
        for k, ko in (('asia', '아시아'), ('europe', '유럽')):
            al = s['global_close'][k]['alignment']
            print(f"  {ko}: {al['label'] if al else '판정 불가'}"
                  f"{' (지역 내 혼조)' if al and al['mixed'] else ''}")
        p = s['participation']
        print(f"  참여도: {p['band']} ({p['gap_pp']:+.2f}%p)" if p else '  참여도: 판정 불가')
    except Exception as e:
        print(f'session context failed: {e}', file=sys.stderr)
```

- [ ] **Step 4: 실제로 돌려 값을 확인한다**

Run: `python3 scripts/collect_market_data.py --outdir /tmp/session-check`
Expected: `computing session context...` 뒤에 아시아·유럽 판정과 참여도가 찍힌다. 그다음:

```bash
python3 -c "
import json; s=json.load(open('/tmp/session-check/market_data.json'))['session']
print(json.dumps(s, ensure_ascii=False, indent=2)[:1500])"
```

`global_close.asia.rows`가 3종, `futures.contracts`에 ES·NQ, `tape`에 지수 3종이 있어야 한다.

- [ ] **Step 5: Commit**

```bash
git add scripts/collect_market_data.py
git commit -m "시황: session 블록 수집 배선 (글로벌·선물·참여도)"
```

> **여기까지가 1일차다.** 발행본은 아직 바뀌지 않는다. Actions가 하루 돌아 실제 값이 쌓인 뒤 Task 10에서 `tape` 경계를 확정하고 Task 6~9를 켠다.

---

### Task 6: 발행 게이트 (US)

**Files:**
- Create: `scripts/us/session_gate.py`, `scripts/check_session.py`
- Test: `scripts/us/tests/test_session_gate.py`

**Interfaces:**
- Consumes: `session` 블록(Task 4의 `compute()` 산출), 발행본 HTML
- Produces: `check(html, session, market='us') -> list[str]` (빈 리스트 = 발행 가능)

- [ ] **Step 1: Write the failing test**

```python
# scripts/us/tests/test_session_gate.py
from us.session_gate import check

SESSION = {
    'global_close': {
        'asia': {'rows': [{'name': '닛케이', 'pct': -0.2}],
                 'alignment': {'label': '이어감', 'mixed': False, 'avg_pct': -0.2}},
        'europe': {'rows': [{'name': 'DAX', 'pct': 0.31}, {'name': 'FTSE100', 'pct': -0.79}],
                   'alignment': {'label': '엇갈림', 'mixed': True, 'avg_pct': -0.4}},
    },
    'futures': {'contracts': {'ES': {'high': 7741.25}}, 'gap': {'S&P 500': 0.45},
                'direction': '상승 출발'},
    'participation': {'gap_pp': -0.95, 'band': '소수가 끌어올림'},
    'tape': {'Nasdaq': {'close_position': 95, 'band': '고점권 마감'}},
}

FULL = ('<section><h2>오늘의 장</h2>'
        '<p data-session="global">유럽은 미국과 엇갈렸습니다. DAX 0.31%, FTSE100 -0.79%.</p>'
        '<p data-session="preopen">상승 출발이었습니다.</p>'
        '<p data-session="tape">소수가 끌어올림이었고 나스닥은 고점권 마감입니다.</p>'
        '<p data-session="causal">엔비디아 실적이 하루를 만들었습니다.</p></section>')


def test_clean_page_passes():
    assert check(FULL, SESSION) == []


def test_missing_marker_fails():
    html = FULL.replace(' data-session="causal"', '')
    assert any('causal' in v for v in check(html, SESSION))


def test_silence_on_a_divergent_region_fails():
    html = FULL.replace('유럽은 미국과 엇갈렸습니다.', '유럽도 올랐습니다.')
    assert any('엇갈' in v for v in check(html, SESSION))


def test_mentioning_participation_when_neutral_fails():
    s = dict(SESSION, participation={'gap_pp': 0.1, 'band': '중립'})
    assert any('중립' in v for v in check(FULL, s))


def test_calling_it_breadth_fails():
    html = FULL.replace('소수가 끌어올림이었고', '상승 종목 비율이 낮았고 소수가 끌어올림이었고')
    assert any('상승 종목 비율' in v for v in check(html, SESSION))


def test_section_number_notation_fails_but_css_comment_passes():
    assert check('<style>/* §8 스트립 */</style>' + FULL, SESSION) == []
    assert any('§' in v for v in check(FULL + '<p>§9 포지션은 유지합니다.</p>', SESSION))


def test_absent_block_is_not_enforced():
    assert check('<p>아무것도 없다</p>', None) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest scripts/us/tests/test_session_gate.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'us.session_gate'`

- [ ] **Step 3: Write minimal implementation**

```python
# scripts/us/session_gate.py
"""「오늘의 장」 발행 게이트.

두 가지를 막는다. 하나는 침묵 — 유럽이 미국과 엇갈린 날 그 사실을 안 쓰는 것은
가격 맥락의 관계 뒤집힘·§8의 해소 문단과 같은 급의 누락이다. 다른 하나는 채우기 —
평범한 날 「오늘은 폭이 보통이었습니다」를 쓰는 것. 그래서 참여도는 양방향으로 본다.

시장별로 다른 것은 어느 필드를 어느 문단에서 찾을지의 표 하나뿐이라, HTML 쪽
검사는 US·KR이 그대로 공유한다. style.py·readability.py가 이미 그렇게 쓰인다.
"""

import re

MARKERS = ('global', 'preopen', 'tape', 'causal')

PARTICIPATION_LABELS = ('고르게 오름', '소수가 끌어올림', '고르게 내림', '소수가 끌어내림')

MISNOMERS = ('상승 종목 비율', '등락 종목 수', '시장 폭', 'breadth')

INTERNAL = ('global_close', 'participation', 'gap_pp', 'close_position',
            'kr_session', 'data-session')


def _strip_style(html):
    return re.sub(r'<style\b.*?</style>', ' ', html or '', flags=re.S | re.I)


def _text(html):
    return re.sub(r'<[^>]+>', ' ', html or '')


def _blocks(html):
    out = {}
    for m in re.finditer(r'<(\w+)[^>]*\bdata-session="([^"]+)"[^>]*>(.*?)</\1>',
                         html or '', re.S):
        out.setdefault(m.group(2), []).append(_text(m.group(3)))
    return {k: ' '.join(v) for k, v in out.items()}


def check(html, session, market='us'):
    """위반 문자열 리스트. 빈 리스트 = 발행 가능."""
    if not session:
        return []          # 비-코어: 블록이 없으면 강제할 것도 없다
    v, body = [], _strip_style(html or '')
    blocks = _blocks(body)
    page = _text(body)

    for key in MARKERS:
        if key == 'global' and not any(
                (session.get('global_close') or {}).get(r, {}).get('rows')
                for r in ('asia', 'europe')):
            continue
        if not blocks.get(key, '').strip():
            v.append(f'「오늘의 장」 {key} 문단이 없거나 비었다 (data-session="{key}")')

    for region, ko in (('asia', '아시아'), ('europe', '유럽')):
        al = ((session.get('global_close') or {}).get(region) or {}).get('alignment')
        if al and al['label'] == '엇갈림' and '엇갈' not in blocks.get('global', ''):
            v.append(f'{ko}가 미국과 엇갈렸는데 서술이 없다 (평균 {al["avg_pct"]:+.2f}%). '
                     '어긋남은 허용, 침묵은 금지')

    p = session.get('participation')
    if p:
        said = [lab for lab in PARTICIPATION_LABELS if lab in page]
        if p['band'] == '중립' and said:
            v.append(f'참여도가 중립인데 「{said[0]}」이라 썼다 — 채우기 금지')
        if p['band'] != '중립' and p['band'] not in blocks.get('tape', ''):
            v.append(f'참여도 {p["band"]}({p["gap_pp"]:+.2f}%p)를 서술하지 않았다')

    for bad in MISNOMERS:
        if bad in page:
            v.append(f'「{bad}」는 이 값의 이름이 아니다 — 동일가중과 시총가중의 '
                     '수익률 차이지 종목 수가 아니다')
    for bad in INTERNAL:
        if bad in page:
            v.append(f'내부 표기 「{bad}」가 발행본에 노출됐다')
    if re.search(r'§\s*\d', page):
        v.append('「§N」 표기가 발행본에 있다 — 독자에게는 섹션 번호가 보이지 않는다. '
                 '이름으로 부르거나 주어를 바꿀 것')
    if '[확인필요]' in page:
        v.append('[확인필요] 마커가 남았다 — 없는 것은 지운다')
    return v
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest scripts/us/tests/test_session_gate.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: CLI를 만든다**

```python
#!/usr/bin/env python3
# scripts/check_session.py
"""「오늘의 장」 발행 게이트.

  python3 scripts/check_session.py --html morning_brief_2026-08-29.html --datadir . --market us
  python3 scripts/check_session.py --html kr_brief_2026-08-29.html --datadir kr/data --market kr

Exit 0 = 발행 가능. Exit 1 = 위반이 한 줄씩 찍힌다 — 그대로 writer에게 돌려주고 다시 돌린다.
비-코어: session 블록이 없는 데이터셋이면 강제할 것이 없으므로 통과한다.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from us.session_gate import check  # noqa: E402

SOURCES = {'us': ('market_data.json', 'session'),
           'kr': ('kr_session.json', None)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--html', required=True)
    ap.add_argument('--datadir', default='data')
    ap.add_argument('--market', choices=('us', 'kr'), default='us')
    args = ap.parse_args()

    try:
        with open(args.html, encoding='utf-8') as fh:
            html = fh.read()
    except OSError as e:
        print(f'FATAL: cannot read {args.html}: {e}', file=sys.stderr)
        sys.exit(2)

    fname, key = SOURCES[args.market]
    path = os.path.join(args.datadir, fname)
    try:
        with open(path, encoding='utf-8') as fh:
            blob = json.load(fh)
    except FileNotFoundError:
        print(f'no {path} — nothing to check')
        return
    except Exception as e:
        print(f'WARN: could not read {path}: {e}', file=sys.stderr)
        return

    violations = check(html, blob.get(key) if key else blob, market=args.market)
    if violations:
        for line in violations:
            print(line)
        sys.exit(1)
    print('session gate: OK')


if __name__ == '__main__':
    main()
```

- [ ] **Step 6: 실제 발행본에 돌려 본다**

Run: `python3 scripts/check_session.py --html posts/2026-08-27.html --datadir data`
Expected: 「§N」 위반 6건이 잡힌다(2026-08-27 발행본에 「§9 포지션은…」이 실려 있다). 이 판은 아직 「오늘의 장」이 없으므로 문단 위반도 함께 찍힌다 — 게이트가 살아 있다는 증거다.

- [ ] **Step 7: Commit**

```bash
git add scripts/us/session_gate.py scripts/check_session.py scripts/us/tests/test_session_gate.py
git commit -m "시황: 「오늘의 장」 발행 게이트 (침묵·채우기·오칭·§N 차단)"
```

---

### Task 7: KR 수집 (`kr_session.json`)

**Files:**
- Create: `scripts/kr/session.py`
- Test: `scripts/kr/tests/test_kr_session.py`
- Modify: `scripts/collect_kr_data.py`, `.github/workflows/collect-kr-data.yml`

**Interfaces:**
- Consumes: `data/market_data.json`(전일 미국장), `KRW=X`·`ES=F`·`NQ=F` 30분봉, 아시아 지수 종가
- Produces: `kr/data/kr_session.json` — `{'report_date', 'us_prev', 'us_futures_during_kr', 'asia_peers', 'usdkrw_intraday'}`

- [ ] **Step 1: Write the failing test**

```python
# scripts/kr/tests/test_kr_session.py
from kr import session as ks


def test_us_prev_carries_its_own_as_of_and_session_lag():
    md = {'report_date': '2026-08-26',
          'indices': {'S&P 500': {'pct': 0.72}, 'Nasdaq': {'pct': 1.57},
                      'Dow': {'pct': 0.31}}}
    out = ks.us_prev(md, report_date='2026-08-28')
    assert out['as_of'] == '2026-08-26'
    assert out['lag_sessions'] == 2          # 미국 휴장으로 벌어졌다
    assert out['rows']['S&P 500'] == 0.72


def test_us_prev_is_none_without_a_market_data_file():
    assert ks.us_prev(None, report_date='2026-08-28') is None


def test_kr_hours_window_converts_from_et_before_slicing():
    # 09:00~15:30 KST = 전날 20:00~익일 02:30 ET (서머타임 기준)
    bars = [
        {'t': '2026-08-26T19:30:00-04:00', 'close': 100.0},   # 08:30 KST — 제외
        {'t': '2026-08-26T20:00:00-04:00', 'close': 101.0},   # 09:00 KST — 시작
        {'t': '2026-08-27T02:00:00-04:00', 'close': 102.0},   # 15:00 KST — 끝
        {'t': '2026-08-27T03:00:00-04:00', 'close': 999.0},   # 16:00 KST — 제외
    ]
    w = ks.kr_hours_window(bars, '2026-08-27')
    assert w['pct'] == 0.99                  # 101.0 → 102.0
    assert w['bars'] == 3


def test_asia_peers_reports_kospi_relative_strength():
    peers = ks.asia_peers({'닛케이': -0.2, '항셍': -0.34}, kospi_pct=0.9)
    assert peers['relative_pp'] == 1.17       # 0.9 - (-0.27)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest scripts/kr/tests/test_kr_session.py -v`
Expected: FAIL — `ImportError: cannot import name 'session' from 'kr'`

- [ ] **Step 3: Write minimal implementation**

```python
# scripts/kr/session.py
"""KR 「오늘의 장」 재료.

US 쪽과 뼈대는 같고 시간 축만 한국 것이다 — 전일 미국장 → 아시아 동시간대 →
코스피 장중(미국 선물 오버레이) → 원달러.

이 파일은 자기 report_date를 갖는다. intraday.json이 기준일 없이 시각 문자열만
들고 있어 신선도를 증명하지 못하는 문제를 새 파일에서 반복하지 않는다.
"""

import datetime as _dt

PEERS = (('닛케이', '^N225'), ('항셍', '^HSI'),
         ('상해종합', '000001.SS'), ('대만가권', '^TWII'))
FUTURES = (('ES', 'ES=F'), ('NQ', 'NQ=F'))
KR_OPEN, KR_CLOSE = (9, 0), (15, 30)
KST = _dt.timezone(_dt.timedelta(hours=9))


def _finite(x):
    return isinstance(x, (int, float)) and x == x


def _sessions_between(a, b):
    """평일 수. 정확한 휴장 달력이 없으므로 주말만 뺀다 — 라벨을 붙일지
    말지를 정하는 데는 충분하고, 과대평가하지 않는다."""
    d0, d1 = _dt.date.fromisoformat(str(a)), _dt.date.fromisoformat(str(b))
    n, cur = 0, d0
    while cur < d1:
        cur += _dt.timedelta(days=1)
        if cur.weekday() < 5:
            n += 1
    return n


def us_prev(market_data, report_date):
    """전일 미국장. 같은 레포의 data/market_data.json을 읽고 재수집하지 않는다."""
    if not market_data:
        return None
    idx = market_data.get('indices') or {}
    rows = {n: idx[n]['pct'] for n in ('S&P 500', 'Nasdaq', 'Dow')
            if idx.get(n) and _finite(idx[n].get('pct'))}
    if not rows:
        return None
    as_of = str(market_data.get('report_date') or '')
    return {'as_of': as_of, 'rows': rows,
            'lag_sessions': _sessions_between(as_of, report_date) if as_of else None}


def kr_hours_window(bars, report_date):
    """한국 정규장 시간대(09:00~15:30 KST)의 선물 등락.

    이 창은 ET 달력에서 전날 밤에 걸린다. ET 날짜로 자르면 앞 절반이 사라지므로
    KST로 변환한 뒤 자른다.
    """
    day = _dt.date.fromisoformat(str(report_date))
    picked = []
    for b in bars or []:
        try:
            ts = _dt.datetime.fromisoformat(str(b.get('t'))).astimezone(KST)
        except (ValueError, TypeError):
            continue
        if ts.date() != day or not _finite(b.get('close')):
            continue
        if KR_OPEN <= (ts.hour, ts.minute) <= KR_CLOSE:
            picked.append((ts, float(b['close'])))
    if len(picked) < 2:
        return None
    picked.sort()
    first, last = picked[0][1], picked[-1][1]
    if not first:
        return None
    return {'pct': round((last / first - 1) * 100, 2), 'bars': len(picked),
            'first_t': picked[0][0].strftime('%H:%M'),
            'last_t': picked[-1][0].strftime('%H:%M')}


def asia_peers(pcts, kospi_pct):
    """아시아 이웃 시장과 코스피의 상대 강약."""
    rows = {k: round(v, 2) for k, v in (pcts or {}).items() if _finite(v)}
    if not rows or not _finite(kospi_pct):
        return None
    avg = sum(rows.values()) / len(rows)
    return {'rows': rows, 'avg_pct': round(avg, 2),
            'relative_pp': round(kospi_pct - avg, 2)}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest scripts/kr/tests/test_kr_session.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: 수집기와 워크플로에 배선한다**

`scripts/collect_kr_data.py`의 `main()` 끝, `_write(...)` 호출들 옆에 넣는다.

```python
    # 비-코어. 실패해도 나머지 산출물은 나간다.
    try:
        from kr import session as kr_session
        md = None
        for p in ('data/market_data.json', '../data/market_data.json'):
            if os.path.exists(p):
                md = json.load(open(p, encoding='utf-8'))
                break
        fut_bars = {}
        for _, t in kr_session.FUTURES:
            h = yf.Ticker(t).history(period='5d', interval='30m')
            if h is not None and len(h):
                h.index = h.index.tz_convert('America/New_York')
                fut_bars[t] = [{'t': i.isoformat(), 'close': float(r['Close'])}
                               for i, r in h.iterrows()]
        peer_pct = {}
        for name, t in kr_session.PEERS:
            c = yf.Ticker(t).history(period='10d')['Close'].dropna()
            if len(c) >= 2:
                peer_pct[name] = float(c.iloc[-1] / c.iloc[-2] - 1) * 100
        rd = bundle['kr_market_data']['report_date']
        _write(outdir, 'kr_session.json', {
            'report_date': rd,
            'us_prev': kr_session.us_prev(md, rd),
            'us_futures_during_kr': {
                lab: kr_session.kr_hours_window(fut_bars.get(t), rd)
                for lab, t in kr_session.FUTURES},
            'asia_peers': kr_session.asia_peers(
                peer_pct, bundle['kr_market_data']['indices']['코스피']['change_pct']),
        })
    except Exception as e:
        print(f'kr session failed: {e}')
```

`.github/workflows/collect-kr-data.yml`의 `git add` 목록에 `kr/data/kr_session.json`을 더한다.

- [ ] **Step 6: 실제로 돌려 본다**

Run: `python3 scripts/collect_kr_data.py --outdir /tmp/kr-session-check`
Expected: `/tmp/kr-session-check/kr_session.json`이 생기고 `us_prev.lag_sessions`·`asia_peers.relative_pp`·`us_futures_during_kr`가 채워진다.

- [ ] **Step 7: Commit**

```bash
git add scripts/kr/session.py scripts/kr/tests/test_kr_session.py \
        scripts/collect_kr_data.py .github/workflows/collect-kr-data.yml
git commit -m "시황: KR 오늘의 장 재료 수집 (전일 미국장·아시아·장중 선물)"
```

---

### Task 8: KR 게이트 배선

**Files:**
- Modify: `scripts/us/session_gate.py`, `scripts/us/tests/test_session_gate.py`

**Interfaces:**
- Consumes: `kr_session.json` 전체(래핑 키 없음 — Task 6의 `SOURCES['kr']`가 `None` 키로 넘긴다)
- Produces: `check(html, session, market='kr')` — KR 스키마에서는 `alignment`·`participation` 검사를 건너뛰고 표식 넷과 금지 표현만 본다

- [ ] **Step 1: Write the failing test**

```python
KR_SESSION = {
    'report_date': '2026-08-28',
    'us_prev': {'as_of': '2026-08-26', 'lag_sessions': 2,
                'rows': {'S&P 500': 0.72}},
    'asia_peers': {'rows': {'닛케이': -0.2}, 'avg_pct': -0.2, 'relative_pp': 1.1},
}

KR_FULL = ('<section><h2>오늘의 장</h2>'
           '<p data-session="global">26일 미국장은 올랐습니다. 코스피는 아시아 이웃보다 강했습니다.</p>'
           '<p data-session="preopen">갭 상승으로 출발했습니다.</p>'
           '<p data-session="tape">오후 들어 밀렸고 원달러는 1,374원에서 끝났습니다.</p>'
           '<p data-session="causal">외국인 매수가 하루를 만들었습니다.</p></section>')


def test_kr_page_passes_without_us_only_fields():
    assert check(KR_FULL, KR_SESSION, market='kr') == []


def test_kr_stale_us_session_must_be_labelled():
    html = KR_FULL.replace('26일 미국장은', '미국장은')
    assert any('미국장 기준' in v for v in check(html, KR_SESSION, market='kr'))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest scripts/us/tests/test_session_gate.py -k kr -v`
Expected: FAIL — KR 스키마에 `global_close`가 없어 `global` 문단 검사가 건너뛰어지고, `lag_sessions` 검사가 없어 두 번째 테스트가 실패한다

- [ ] **Step 3: Write minimal implementation**

`check()`의 지역 검사 앞에 시장 분기를 넣고, KR 전용 검사를 더한다.

```python
    if market == 'kr':
        up = session.get('us_prev') or {}
        lag = up.get('lag_sessions')
        if lag and lag >= 2 and '미국장 기준' not in page:
            v.append(f'전일 미국장이 {lag}거래일 전({up.get("as_of")})인데 '
                     '기준일 표기가 없다 — 「N일 미국장 기준」을 밝힐 것')
    else:
        for region, ko in (('asia', '아시아'), ('europe', '유럽')):
            ...  # 기존 블록 그대로
        p = session.get('participation')
        ...  # 기존 블록 그대로
```

`MARKERS` 순회의 `global` 예외 조건도 시장을 탄다:

```python
    for key in MARKERS:
        if key == 'global' and market == 'us' and not any(
                (session.get('global_close') or {}).get(r, {}).get('rows')
                for r in ('asia', 'europe')):
            continue
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest scripts/us/tests/test_session_gate.py -v`
Expected: PASS (9 passed)

- [ ] **Step 5: Commit**

```bash
git add scripts/us/session_gate.py scripts/us/tests/test_session_gate.py
git commit -m "시황: KR 게이트 배선 (전일 미국장 기준일 라벨 강제)"
```

---

### Task 9: writer 스펙과 오케스트레이터 배선

**Files:**
- Modify: `.claude/agents/brief-report-writer.md`, `.claude/agents/kr-report-writer.md`, `.claude/ORCHESTRATOR.md`, `.claude/KR_ORCHESTRATOR.md`

- [ ] **Step 1: US writer 스펙에 섹션을 넣는다**

`.claude/agents/brief-report-writer.md:13`의 구조 목록에서 현재 3번(주식) 앞에 새 항목을 넣고 이후 번호를 하나씩 민다. 「가격 맥락 — 전 섹션 공통 사양」의 §3·§5·§6·§7 참조도 밀린 번호로 고친다.

```markdown
3. **오늘의 장** — 하루를 시간 축으로 읽는다. 표 하나(글로벌 6종 + VIX)와 네 문단.
   판정은 `market_data.json`의 `session`에 끝난 상태로 온다 — **다시 계산하지 않는다.**
   - `<p data-session="global">` 아시아·유럽이 어디서 끝났고 미국이 이었나 엇갔나.
     `alignment`가 「엇갈림」이면 그것이 이 문단의 첫 문장이다. **침묵은 발행 중단 사유다.**
   - `<p data-session="preopen">` 야간 선물 궤적(고·저와 시각)과 현물 갭. 무엇이 그 시간에 있었나.
   - `<p data-session="tape">` 참여도와 마감 위치. **참여도가 `중립`인 날은 언급하지 않는다.**
   - `<p data-session="causal">` 무엇이 무엇을 움직인 날인가 + 시간외.
   - 「참여도」를 **「상승 종목 비율」·「등락 종목 수」·「시장 폭」이라 부르지 않는다** —
     등락 종목 수가 아니라 동일가중 지수와 시총가중 지수의 수익률 차이고,
     답하는 질문은 「평균적인 종목이 지수를 따라갔나」다.
   - 여기 쓴 **수치를 아래 자산 섹션에서 되풀이하지 않는다.** 판정 어휘를 이어받는 것은
     중복이 아니라 연결이다 — 근거 숫자를 다시 인쇄하지 말고 곧장 함의로 넘어간다.
```

같은 파일의 FX·원자재·주식 항목에 심화 규칙을 더한다.

```markdown
   - **FX** — 「달러가 왜 이 방향인가」를 한 문단으로 쓴다. 금리차·위험선호·개별 통화
     재료 중 **무엇인지 특정한다.** 방향만 되뇌는 문장은 쓰지 않는다.
   - **원자재** — 공급·수요·달러 중 무엇이 움직였나 + WTI−Brent 스프레드, 금과 실질금리.
   - **주식** — 「오늘의 장」의 참여도·마감 위치를 받아 「그래서 이 상승이 믿을 만한가」로 잇는다.
```

`§N` 규칙을 문체 절에 넣는다.

```markdown
- **「§N」을 산문에 쓰지 않는다** — 발행본에는 섹션 번호가 보이지 않으므로 독자가
  해석할 수 없다(2026-08-27 발행본에 「§9 포지션은…」이 6번 실렸다). 섹션은 이름으로
  부르거나(「멀티에셋 전략 섹션은」) 주어를 바꾼다(「우리는 달러 소폭 숏을 유지합니다」).
```

- [ ] **Step 2: KR writer 스펙에 같은 항목을 넣는다**

`.claude/agents/kr-report-writer.md`의 입력 목록에 파일을 더하고, 구조 목록 3번 앞에 섹션을 넣는다.

```markdown
- `kr_session.json` — 전일 미국장(`us_prev`, `as_of`·`lag_sessions` 포함)·한국 장중
  미국 선물(`us_futures_during_kr`)·아시아 이웃과 코스피 상대 강약(`asia_peers`)·
  원달러 장중(`usdkrw_intraday`). 비-코어
```

```markdown
3. **오늘의 장** — 네 문단(`data-session` 표식 US와 동일). 전일 미국장 → 아시아
   동시간대와 코스피 상대 강약 → 코스피 장중(미국 선물 오버레이) → 원달러 → 시간외.
   **원달러는 `tape` 문단에 들어간다 — 다섯 번째 문단을 만들지 않는다.**
   `us_prev.lag_sessions`가 2 이상이면 **「N일 미국장 기준」을 명시한다**(수급 신선도와 같은 규율).
```

- [ ] **Step 3: 두 오케스트레이터의 게이트 목록에 넣는다**

`.claude/ORCHESTRATOR.md`의 가격 맥락 게이트 문단(42번째 줄 부근) 바로 뒤에 넣는다.

```markdown
**시황 게이트 (「오늘의 장」)** — run `python3 scripts/check_session.py --html morning_brief_[DATE].html --datadir <workspace> --market us`. It fails the run when: a `data-session` paragraph is missing or empty; a region whose direction diverged from the US is not written about; the participation reading is narrated on a neutral day or omitted on a day it fired; the reading is called 「상승 종목 비율」·「등락 종목 수」·「시장 폭」; internal field names or a 「§N」 notation reached the page. Non-core: a dataset with no `session` block passes untouched.
```

STEP 2.5의 `finalize --gate` 목록에도 같은 줄을 더한다 — **조판 보정(`apply_readability.py`)이 게이트 통과 뒤에 HTML을 고치기 때문이다.** 긴 문단 분리가 `data-session` 문단을 쪼갤 수 있다.

```bash
  --gate "python3 scripts/check_session.py --html {f} --datadir <workspace> --market us"
```

`.claude/KR_ORCHESTRATOR.md`에도 같은 두 자리에 `--market kr --datadir kr/data`로 넣는다. **KR의 첫 데이터 게이트다.**

- [ ] **Step 4: 문서가 서로 어긋나지 않는지 확인한다**

Run:
```bash
grep -n "오늘의 장" .claude/agents/*.md .claude/*ORCHESTRATOR.md
grep -c "check_session" .claude/ORCHESTRATOR.md .claude/KR_ORCHESTRATOR.md
```
Expected: 네 파일 모두에 섹션이 있고, 두 오케스트레이터 각각 `check_session`이 **2번**씩(STEP 2 게이트 + STEP 2.5 finalize) 나온다.

- [ ] **Step 5: Commit**

```bash
git add .claude/agents/brief-report-writer.md .claude/agents/kr-report-writer.md \
        .claude/ORCHESTRATOR.md .claude/KR_ORCHESTRATOR.md
git commit -m "시황: writer 스펙·오케스트레이터에 「오늘의 장」 배선"
```

---

### Task 10: `tape` 경계 확정 (1일차 관측 뒤)

**Files:**
- Modify: `scripts/us/session.py`, `scripts/us/tests/test_session.py`
- Modify: `docs/superpowers/specs/2026-08-28-market-recap-enrichment-design.md` (열린 항목 해소)

**전제:** Task 5가 배포돼 Actions가 최소 하루 돌았고 `data/market_data.json`에 `session`이 커밋돼 있다.

- [ ] **Step 1: 실제 분포를 잰다**

```bash
python3 - <<'EOF'
import subprocess, json
pos = []
log = subprocess.run(['git', 'log', '--format=%H', '-40', '--', 'data/market_data.json'],
                     capture_output=True, text=True).stdout.split()
for sha in log:
    try:
        blob = subprocess.run(['git', 'show', f'{sha}:data/market_data.json'],
                              capture_output=True, text=True).stdout
        t = (json.loads(blob).get('session') or {}).get('tape') or {}
        for name, row in t.items():
            if row:
                pos.append(row['close_position'])
    except Exception:
        pass
pos.sort()
print('n =', len(pos))
for q in (10, 25, 50, 75, 90):
    print(f'  p{q}: {pos[int(len(pos)*q/100)]}')
EOF
```

- [ ] **Step 2: 경계를 정하고 테스트를 고친다**

관측된 p75·p25를 `TAPE_HIGH`·`TAPE_LOW`에 넣는다(초안은 75/25). 관측 표본이 20일 미만이면 **초안값을 유지하고** 이 태스크를 다시 미룬다 — 열흘 표본으로 정한 경계는 다음 달에 다시 바뀐다.

```python
# scripts/us/session.py
TAPE_HIGH, TAPE_LOW = 75, 25   # 2026-09-XX 관측 N일 기준 p75/p25
```

- [ ] **Step 3: 테스트를 돌린다**

Run: `python3 -m pytest scripts/us/tests/ -v`
Expected: PASS (전부)

- [ ] **Step 4: 스펙의 「열린 항목」을 갱신한다**

`docs/superpowers/specs/2026-08-28-market-recap-enrichment-design.md`의 첫 항목을 관측 결과로 대체한다.

- [ ] **Step 5: Commit**

```bash
git add scripts/us/session.py scripts/us/tests/test_session.py \
        docs/superpowers/specs/2026-08-28-market-recap-enrichment-design.md
git commit -m "시황: 마감 위치 밴드 경계를 실측 분포로 확정"
```
