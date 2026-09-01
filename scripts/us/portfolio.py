"""§10 등급을 실제로 굴리는 모의 포트폴리오.

§10은 2026-08-17부터 «승계되는 포지션»이 됐지만, 그 표가 말하는 것은 방향뿐이었다.
「주식 소폭확대」가 몇 퍼센트인지, 그래서 지금까지 돈을 벌었는지를 발행본이 한 번도
말하지 않았다. 이 모듈이 그 자리를 메운다.

창작할 자리를 없애는 것이 설계의 전부다. **비중은 등급에서만 나오고**(아래 상수가
정본), **NAV는 좌수 곱하기 종가**이며, **성과는 원장의 양 끝**이다. 에이전트는
여기 계산된 결과를 렌더할 뿐 산술을 하지 않는다 — §9 축 점수 z를 만지지 않는 것과
같은 계약이다.

원장은 **다시 굴리지 않는다**. `auto_adjust` 종가는 배당이 나올 때마다 과거가
소급 조정되므로, 매일 전체를 재계산하면 지난주 NAV가 조용히 바뀐다.
"""

BASE_NAV = 1000.0        # 기준가 — 가짜 달러 잔고를 인쇄하지 않기 위한 지수
MIN_SESSIONS = 60        # 이만큼 쌓이기 전에는 연율·변동성을 말하지 않는다
GRADE_MIN, GRADE_MAX = -2, 2

ASSET_KEYS = ('equities', 'bonds', 'fx', 'energy', 'metals', 'memory', 'ai_infra')
NEUTRAL_GRADES = {k: 0 for k in ASSET_KEYS}

# ── 왜 이 비중인가 (2026-09-02 사용자 지시 「왜 그렇게 구성했는지 논리를 만드는 거야」)
#
# 두 가지를 따로 정한다. **중립 책이 무엇인가**와 **등급 한 칸이 얼마인가**.
#
# ① 중립 책 — 판단이 하나도 없을 때의 기본 자세.
#    · 주식 46%: 이 리포트는 주식시장 브리프이고 §10의 첫 축이 주식 절대비중이다.
#      장기 기대수익의 대부분을 여기서 받는다. **위험의 3분의 2를 주식이 지는 것은
#      의도한 것**이고, 나머지 자산군은 그 위험을 상쇄하거나 보완하는 자리에 둔다.
#    · 채권 28%를 **고정**: 듀레이션 축을 표현하려면 장·단기 두 칸이 필요한데,
#      합계를 고정해야 「배분을 바꾼 것」과 「듀레이션을 바꾼 것」이 섞이지 않는다.
#    · 귀금속 6.5% + 에너지 4%: 인플레·지정학 헤지. §10이 둘을 따로 판정하므로
#      슬리브도 둘로 나눈다.
#    · 현금 16%: **틸트 재원**이다. 확대 판단은 여기서 먼저 꺼내 쓰고, 다 쓰면
#      전 슬리브를 비례 축소한다(레버리지 금지). 「다 살 수는 없다」는 것 자체가
#      정보이므로 축소가 일어난 날은 발행본이 그 사실을 밝힌다.
#    · 메모리·AI 인프라 3.5%: §10에서 이 둘은 **주식 대비 상대비중**이다. 중립이
#      0이면 UW와 중립이 같은 책이 되므로 자리를 준다. 한 칸이 1.75%p라 −2에서
#      정확히 0(완전 배제), +2에서 중립의 두 배가 된다.
#
# ② 등급 한 칸 = **같은 크기의 베팅**. 자본 몇 %가 아니라 «연변동성 몇 %p»로 잰다.
#    금 한 칸과 채권 한 칸이 자본 기준으로 같으면 실제 베팅 크기는 다섯 배 차이가
#    난다 — 그러면 「소폭확대」가 자산군마다 다른 뜻이 된다. 예산은 아래 하나이고,
#    각 슬리브의 자본 이동폭은 **그 예산 ÷ 그 자산의 변동성**에서 나온다.
#    측정은 3년 일간 수익률(2026-09-02 실측): 주식 16.1% · 귀금속 22.9% ·
#    에너지 38.8% · 메모리 43.7% · AI 인프라 42.1% · 장기−단기 채권 차 11.3% ·
#    달러 6.8%.
#    · 환만 예산의 3분의 2를 쓴다 — 통화는 장기 기대수익이 0에 가까워 같은 위험을
#      져도 돌아오는 것이 적다. 실제 운용이라면 선물환으로 자본 없이 표현하는
#      자리인데, 여기서는 따라 살 수 있는 상품(UDN/UUP)을 쓰느라 자본을 쓴다.
#
# 상수는 **한 번 계산해 고정**한다. 매일 다시 계산하면 등급이 그대로인 날에도 목표가
# 움직여 「등급이 바뀐 날에만 리밸런싱」이 무너진다. 대신 변동성을 매일 다시 재서
# 한 칸의 실제 크기를 발행본에 인쇄하고, 예산에서 크게 벗어나면 재보정 신호를 띄운다
# (`portfolio_risk.py`).
NOTCH_RISK_PCT = 0.75    # 한 칸이 만드는 연변동성 (%p)
FX_RISK_SHARE = 2 / 3    # 환은 예산의 3분의 2만

EQUITY_FAMILY = 46.0     # 주식·메모리·AI 인프라를 합친 주식 패밀리
EQUITY_STEP = 4.75       # 0.75 / 16.1%
MEMORY_NEUTRAL, MEMORY_STEP = 3.5, 1.75      # 0.75 / 43.7%, −2에서 정확히 0
AI_NEUTRAL, AI_STEP = 3.5, 1.75              # 0.75 / 42.1%
FI_TOTAL = 28.0          # 채권 등급은 배분이 아니라 듀레이션 — 합계는 고정
FI_LONG_SHARE, FI_LONG_STEP = 0.5, 0.2       # 5.6%p 이동 × 11.3% = 0.63%p
METALS_NEUTRAL, METALS_STEP = 6.5, 3.25      # 0.75 / 22.9%
ENERGY_NEUTRAL, ENERGY_STEP = 4.0, 2.0       # 0.75 / 38.8%
FX_STEP = 7.25           # 0.50 / 6.8%

SLEEVES = (
    ('equity_core', '주식 코어', ('SPY',)),
    ('memory', '메모리', ('MU', 'WDC', 'STX')),
    ('ai_infra', 'AI 인프라', ('MRVL', 'COHR', 'LITE', 'GEV', 'VRT')),
    ('bonds_long', '채권 장기(20Y+)', ('TLT',)),
    ('bonds_short', '채권 단기(1-3Y)', ('SHY',)),
    ('metals', '귀금속', ('GLD',)),
    ('energy', '에너지(WTI)', ('USO',)),
    ('fx_short', '달러 약세', ('UDN',)),
    ('fx_long', '달러 강세', ('UUP',)),
    ('cash', '현금성', ('BIL',)),
)
SLEEVE_ORDER = tuple(k for k, _, _ in SLEEVES)
SLEEVE_LABEL = {k: label for k, label, _ in SLEEVES}
SLEEVE_TICKERS = {k: ts for k, _, ts in SLEEVES}
TICKERS = tuple(sorted({t for _, _, ts in SLEEVES for t in ts}))
HISTORY_TICKERS = TICKERS
TICKER_SLEEVE = {t: k for k, _, ts in SLEEVES for t in ts}

# §10 자산 키 → 이 책에서 그 등급이 움직이는 슬리브 (발행본이 둘을 잇게)
ASSET_SLEEVES = {
    'equities': ('equity_core',), 'bonds': ('bonds_long', 'bonds_short'),
    'fx': ('fx_short', 'fx_long'), 'energy': ('energy',), 'metals': ('metals',),
    'memory': ('memory',), 'ai_infra': ('ai_infra',),
}


def _grade(grades, key):
    try:
        v = int((grades or {}).get(key, 0) or 0)
    except (TypeError, ValueError):
        v = 0
    return max(GRADE_MIN, min(GRADE_MAX, v))


def _sleeve_weights(grades):
    """-> (비중, 축소배수, 요구 자본). 축소는 레버리지를 쓰지 않는다는 규칙의 결과다."""
    memory = max(0.0, MEMORY_NEUTRAL + MEMORY_STEP * _grade(grades, 'memory'))
    ai = max(0.0, AI_NEUTRAL + AI_STEP * _grade(grades, 'ai_infra'))
    family = max(0.0, EQUITY_FAMILY + EQUITY_STEP * _grade(grades, 'equities'))
    core = max(0.0, family - memory - ai)

    long_share = FI_LONG_SHARE + FI_LONG_STEP * _grade(grades, 'bonds')
    long_share = max(0.0, min(1.0, long_share))
    bonds_long = FI_TOTAL * long_share

    fx = _grade(grades, 'fx')
    w = {
        'equity_core': core, 'memory': memory, 'ai_infra': ai,
        'bonds_long': bonds_long, 'bonds_short': FI_TOTAL - bonds_long,
        'metals': max(0.0, METALS_NEUTRAL + METALS_STEP * _grade(grades, 'metals')),
        'energy': max(0.0, ENERGY_NEUTRAL + ENERGY_STEP * _grade(grades, 'energy')),
        'fx_short': FX_STEP * abs(fx) if fx < 0 else 0.0,
        'fx_long': FX_STEP * fx if fx > 0 else 0.0,
    }
    invested = sum(w.values())
    if invested > 100.0:
        # 레버리지 금지 — 틸트가 자본을 넘기면 전 슬리브를 비례 축소한다.
        # 「다 살 수는 없다」는 것 자체가 정보라 발행본이 그 사실을 밝힌다.
        scale = 100.0 / invested
        w = {k: v * scale for k, v in w.items()}
        w['cash'] = 0.0
    else:
        scale = 1.0
        w['cash'] = 100.0 - invested
    return w, scale, invested


def sleeve_weights(grades):
    """등급 → 슬리브별 비중(%). 합계는 언제나 100, 음수는 없다."""
    return _sleeve_weights(grades)[0]


def weight_detail(grades):
    """비중 + 「자본을 넘겨 비례 축소했는가」. 발행본이 그 사실을 밝혀야 한다."""
    w, scale, demand = _sleeve_weights(grades)
    return {'weights': w, 'scaled': scale < 1.0,
            'scale_pct': round(scale * 100, 2), 'demand_pct': round(demand, 2)}


def instrument_weights(grades):
    """등급 → 티커별 비중(%). 바스켓은 동일가중, 0인 슬리브는 담지 않는다."""
    out = {}
    for key, weight in sleeve_weights(grades).items():
        if weight <= 0:
            continue
        tickers = SLEEVE_TICKERS[key]
        for t in tickers:
            out[t] = out.get(t, 0.0) + weight / len(tickers)
    return out


# ── 책 굴리기 ───────────────────────────────────────────────────────────
def _require(prices, tickers, date):
    missing = [t for t in tickers if (prices or {}).get(t) in (None, 0)]
    if missing:
        raise ValueError(f'{date}: 종가 없음 — {", ".join(sorted(missing))}')


def _units(nav, weights, prices):
    return {t: nav * w / 100.0 / prices[t] for t, w in weights.items() if w > 0}


def _sleeve_view(units, prices, nav):
    out = {k: 0.0 for k in SLEEVE_ORDER}
    for t, u in units.items():
        out[TICKER_SLEEVE[t]] += u * prices[t] / nav * 100.0
    return out


def open_book(date, prices, grades, nav=BASE_NAV):
    """설정일의 책 — 그날 종가에 목표 비중대로 담는다."""
    weights = instrument_weights(grades)
    _require(prices, weights, date)
    units = _units(nav, weights, prices)
    px = {t: float(prices[t]) for t in units}
    return {'date': date, 'nav': float(nav), 'units': units, 'prices': px,
            'weights': _sleeve_view(units, px, nav), 'grades': dict(grades or {}),
            'rebalanced': True}


def advance(book, date, prices, grades, force_rebalance=False):
    """하루 굴린다 — 시가평가 → (목표가 바뀌었으면) 리밸런싱. (책, 행) 반환.

    값이 없는 날을 앞의 값으로 메우지 않는다. 메우는 순간 원장이 조용히 틀려진다.
    """
    held = book['units']
    _require(prices, held, date)
    nav = sum(u * prices[t] for t, u in held.items())
    prev_nav = book['nav']
    contrib = {k: 0.0 for k in SLEEVE_ORDER}
    for t, u in held.items():
        contrib[TICKER_SLEEVE[t]] += u * (prices[t] - book['prices'][t]) / prev_nav * 100.0

    target = instrument_weights(grades)
    rebalanced = bool(force_rebalance) or target != instrument_weights(book['grades'])
    if rebalanced:
        _require(prices, target, date)
        units = _units(nav, target, prices)
    else:
        units = dict(held)
    px = {t: float(prices[t]) for t in units}
    new = {'date': date, 'nav': nav, 'units': units, 'prices': px,
           'weights': _sleeve_view(units, px, nav), 'grades': dict(grades or {}),
           'rebalanced': rebalanced}
    row = {'report_date': date, 'nav': nav, 'ret_pct': (nav / prev_nav - 1) * 100.0,
           'contrib': contrib, 'weights': new['weights'],
           'grades': {k: _grade(grades, k) for k in ASSET_KEYS},
           'rebalanced': rebalanced}
    return new, row


def reanchor(book, fresh_prev_prices, tol=1e-6):
    """소급 조정된 종가 기준으로 좌수와 직전 종가를 다시 맞춘다 (가치 불변).

    `auto_adjust=True` 종가는 배당·분할이 있을 때마다 **과거가 소급 조정**된다.
    어제 저장해 둔 종가와 오늘 새로 받은 어제 종가가 다르면 기준이 바뀐 것이고,
    좌수를 그대로 두면 아무 일도 없었는데 2:1 분할이 −50% 손실로 인쇄된다
    (2026-09-01 codex 검토에서 실증 — 합성 분할로 −21% 가 나왔다).

    같은 값을 유지하는 방향으로만 고친다: 가격이 f 배가 되면 좌수는 1/f 배.
    """
    units, prices = dict(book['units']), dict(book['prices'])
    for t, stored in book['prices'].items():
        fresh = (fresh_prev_prices or {}).get(t)
        if not fresh or not stored:
            continue                       # 확인할 수 없는 것은 건드리지 않는다
        factor = fresh / stored
        if abs(factor - 1.0) <= tol:
            continue
        units[t] = units[t] / factor
        prices[t] = fresh
    return dict(book, units=units, prices=prices)


def open_state(date, prices, grades, nav=BASE_NAV):
    """액티브 책과 중립 벤치마크를 함께 연다."""
    return {'inception': date, 'active': open_book(date, prices, grades, nav),
            'bench': open_book(date, prices, NEUTRAL_GRADES, nav)}


def step(state, date, prices, grades):
    """두 책을 같은 하루만큼 굴린다.

    벤치마크는 **액티브가 리밸런싱하는 날 함께 리셋**한다. 표류 차이가 섞이면
    초과수익이 틸트만의 것이 아니게 된다.
    """
    active, row = advance(state['active'], date, prices, grades)
    bench, brow = advance(state['bench'], date, prices, NEUTRAL_GRADES,
                          force_rebalance=row['rebalanced'])
    row = dict(row, bench_nav=bench['nav'], bench_ret_pct=brow['ret_pct'],
               active_pct=row['ret_pct'] - brow['ret_pct'])
    return {'inception': state.get('inception', state['active']['date']),
            'active': active, 'bench': bench}, row


def replay(dates, prices_by_date, grades_for, state=None, base_nav=BASE_NAV):
    """세션을 순서대로 굴린다 -> (상태, 새 행들, 건너뛴 날들).

    값이 없는 날은 **건너뛴다**. 앞의 값으로 메우면 원장이 조용히 틀려지고, 좌수는
    그대로이므로 다음 성공한 날의 수익률이 그 구간을 정확히 덮는다. 건너뛴 날은
    감추지 않고 돌려보내 발행본이 고지하게 한다.
    """
    rows, gaps = [], []
    for d in dates:
        px = prices_by_date.get(d) or {}
        try:
            if state is None:
                state = open_state(d, px, grades_for(d), base_nav)
                continue
            state, row = step(state, d, px, grades_for(d))
        except ValueError:
            gaps.append(d)
            continue
        rows.append(row)
    return state, rows, gaps


# ── 성과 집계 ───────────────────────────────────────────────────────────
PERIODS = (('1d', 1), ('1w', 5), ('1m', 21))


def _period(rows, n, base_nav=BASE_NAV, gaps=(), inception=None):
    """n 거래일 구간. 구간 안에 결측 세션이 있으면 `spans_gap` 으로 알린다.

    「어제 하루」가 사실은 이틀치인 경우를 부르는 이름이 없으면 발행본이 그것을
    하루라고 쓴다 — 2026-09-01 codex 검토에서 실제 초안이 그랬다. 하루짜리 구간은
    결측이 끼면 아예 돌려주지 않는다(다른 이름으로 부를 방법이 없다).
    """
    if len(rows) < n or n <= 0:
        return None
    prev = rows[-(n + 1)] if len(rows) > n else None

    def leg(field):
        end = rows[-1].get(field)
        start = prev.get(field) if prev else base_nav
        if end is None or not start:
            return None
        return (end / start - 1) * 100.0

    p, b = leg('nav'), leg('bench_nav')
    if p is None:
        return None
    start_date = prev.get('report_date') if prev else inception
    end_date = rows[-1].get('report_date')
    spans = any(start_date and end_date and start_date < g <= end_date
                for g in (gaps or ()))
    if spans and n == 1:
        return None
    return {'portfolio': p, 'benchmark': b,
            'active': None if b is None else p - b,
            'from': start_date, 'to': end_date, 'sessions': n,
            'spans_gap': spans}


def summarize(rows, base_nav=BASE_NAV, inception=None, gaps=()):
    """원장 → 발행본이 그대로 렌더할 성과. 여기서 계산이 끝난다."""
    rows = list(rows or [])
    inception = inception or (rows[0]['report_date'] if rows else None)
    returns = {k: _period(rows, n, base_nav, gaps, inception) for k, n in PERIODS}
    returns['itd'] = (_period(rows, len(rows), base_nav, gaps, inception)
                      if rows else None)

    contrib = {}
    for key in SLEEVE_ORDER:
        itd = sum((r.get('contrib') or {}).get(key, 0.0) for r in rows)
        today = (rows[-1].get('contrib') or {}).get(key, 0.0) if rows else 0.0
        contrib[key] = {'label': SLEEVE_LABEL[key], 'itd': itd, 'today': today}
    residual = None
    if returns['itd']:
        residual = returns['itd']['portfolio'] - sum(c['itd'] for c in contrib.values())

    peak, dd = base_nav, 0.0
    for r in rows:
        nav = r.get('nav')
        if not nav:
            continue
        peak = max(peak, nav)
        dd = min(dd, (nav / peak - 1) * 100.0)

    rebalances, prev_grades = [], None
    for r in rows:
        grades = r.get('grades') or {}
        if r.get('rebalanced') and prev_grades is not None:
            changed = {k: {'from': prev_grades.get(k), 'to': v}
                       for k, v in grades.items() if prev_grades.get(k) != v}
            rebalances.append({'report_date': r.get('report_date'), 'changed': changed})
        prev_grades = grades

    neutral = sleeve_weights(NEUTRAL_GRADES)
    last_w = (rows[-1].get('weights') if rows else None) or neutral
    weights = [{'sleeve': k, 'label': SLEEVE_LABEL[k],
                'tickers': list(SLEEVE_TICKERS[k]),
                'weight_pct': last_w.get(k, 0.0), 'neutral_pct': neutral[k],
                'diff_pct': last_w.get(k, 0.0) - neutral[k]} for k in SLEEVE_ORDER]

    return {'inception': inception,
            'report_date': rows[-1]['report_date'] if rows else None,
            'sessions': len(rows), 'base_nav': base_nav,
            'nav': rows[-1]['nav'] if rows else base_nav,
            'bench_nav': rows[-1].get('bench_nav') if rows else base_nav,
            'insufficient': len(rows) < MIN_SESSIONS,
            'min_sessions': MIN_SESSIONS,
            'gaps': list(gaps or ()),
            'returns': returns, 'contrib': contrib, 'residual_pct': residual,
            'max_drawdown_pct': dd, 'rebalances': rebalances, 'weights': weights,
            'grades': (rows[-1].get('grades') if rows else dict(NEUTRAL_GRADES))}
