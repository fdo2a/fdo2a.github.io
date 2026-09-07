"""Statistical context for the price side of the brief.

The report already says how far something moved. What it has never said is whether
that move was large *for this asset* — so a 1.4% day in gold and a 0.6% day in oil
read as if the first were the bigger event, when gold's typical day is 1.6% and
oil's is 3.3%. Every number here answers "is that a lot?" and nothing else.

`compute()` is pure: close-price histories (plain lists, oldest first) plus their
session dates and the already-built market_data dict in, a nested dict out. The
network side stays in collect_market_data.py, which already downloads these
histories for the stance triggers — so this costs no extra requests, the same trade
macro_metrics.py makes against fred_series().

Two rules the readings live or die by:

  * Cross-series numbers are aligned on shared session dates, never by list
    position. FX carries ~26 more bars over three years than the equity indices
    (2026-08-28 measured), so a positional comparison of stocks against the dollar
    silently compares different days. Same failure yield_drivers.py was built to
    avoid. Without dates the cross-series readings are dropped, not approximated.
  * Series are differenced or returned depending on what the number means: a yield
    of 4.66 that becomes 4.71 moved 5bp, not 1.07%.
"""

import math

from common import standing as standing_mod

MOVE_WINDOW = 60        # sessions that define "a typical day"
PCTL_WINDOW = 504       # ~2 years of sessions
CORR_WINDOW = 60
WEIGHT_WINDOW = 252

# A sector the regression puts below this is not measurably in the index as far as a
# year of daily returns can tell. Printing it as a row ("Real Estate, 기여 -0.000%p")
# looks like a finding and is really a shrug — those sectors are named and their
# effect is left in the unexplained part instead.
MIN_IDENTIFIABLE_WEIGHT = 0.005

# Series quoted as a rate/spread, where the meaningful change is a difference.
_DIFF_TICKERS = {'^FVX', '^TNX', '^TYX'}

_R = 10  # float-noise guard on differences


def change_kind(ticker):
    """'d' for series whose change is a level difference, 'r' for returns."""
    return 'd' if ticker in _DIFF_TICKERS else 'r'


def _finite(x):
    try:
        return x is not None and math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


def _series(closes, ticker):
    """Close list with non-finite values dropped — yfinance emits NaN for stale bars,
    and a NaN that survives to json.dump writes invalid JSON and reads as an extreme
    move."""
    s = (closes or {}).get(ticker)
    if not s:
        return None
    s = [float(x) for x in s if _finite(x)]
    return s or None


def _one_change(prev, cur, kind):
    if kind == 'd':
        return round(cur - prev, _R)
    return round((cur / prev - 1) * 100, _R) if prev else None


def changes(closes, ticker):
    """Session-over-session change list, oldest first. Percent or level per kind."""
    s = _series(closes, ticker)
    if s is None or len(s) < 2:
        return None
    kind = change_kind(ticker)
    return [_one_change(p, c, kind) for p, c in zip(s, s[1:])]


def _stdev(vals):
    vals = [v for v in vals if _finite(v)]
    if len(vals) < 2:
        return None
    mean = sum(vals) / len(vals)
    var = sum((v - mean) ** 2 for v in vals) / (len(vals) - 1)
    return var ** 0.5


def move_multiple(closes, ticker, w=MOVE_WINDOW):
    """Today's change in units of this series' own typical day.

    The yardstick deliberately excludes today: a series that has been flat and then
    jumps must not be allowed to widen its own definition of normal.
    """
    ch = changes(closes, ticker)
    if not ch or len(ch) < w + 1:
        return None
    today = ch[-1]
    typical = _stdev(ch[-(w + 1):-1])
    if not _finite(today) or not typical:
        return None
    return round(today / typical, 2)


_MOVE_BANDS = ((0.5, '미미'), (1.5, '보통'), (2.5, '큼'))


def move_band(multiple):
    """Controlled vocabulary for move size — the writer gets the word, not the score."""
    if not _finite(multiple):
        return None
    a = abs(multiple)
    for edge, label in _MOVE_BANDS:
        if a < edge:
            return label
    return '매우 큼'


def level_percentile(closes, ticker, w=PCTL_WINDOW):
    """Where today's level sits inside its own trailing window, 0-100.

    A level means nothing on its own — VIX 14.4 is only informative once you know it
    is the bottom 5% of two years. Today is ranked against its history rather than
    against a window containing itself, so a fresh high reads a clean 100. Ties count
    half, so a dead-flat series lands at 50 rather than being called a record low.
    """
    s = _series(closes, ticker)
    if s is None or len(s) < 30:
        return None
    window = s[-(w + 1):]
    last, prior = window[-1], window[:-1]
    if not prior:
        return None
    below = sum(1 for v in prior if v < last)
    ties = sum(1 for v in prior if v == last)
    return round((below + 0.5 * ties) / len(prior) * 100, 1)


_PCTL_BANDS = ((10, '매우 낮음'), (25, '낮음'), (75, '중간'), (90, '높음'))


def percentile_band(pct):
    if pct is None:
        return None
    for edge, label in _PCTL_BANDS:
        if pct < edge:
            return label
    return '매우 높음'


def aligned_changes(closes, dates, tickers, w):
    """Change columns for several series over their shared sessions, last w each.

    An inner join on session date, not a positional slice. A day only one leg traded
    is dropped for every leg, so each column's i-th entry is the same session.
    Returns None when dates are absent — a cross-series number without provenance is
    worse than no number.
    """
    if not dates:
        return None
    by_date = {}
    for t in tickers:
        s = _series(closes, t)
        d = (dates or {}).get(t)
        if s is None or not d or len(d) != len(((closes or {}).get(t)) or []):
            return None
        # Re-pair dates with the finite closes they belong to.
        raw = (closes or {}).get(t)
        pairs = {dd: float(v) for dd, v in zip(d, raw) if _finite(v)}
        if not pairs:
            return None
        by_date[t] = pairs

    common = sorted(set.intersection(*(set(p) for p in by_date.values())))
    if len(common) < w + 1:
        return None

    cols = []
    for t in tickers:
        kind = change_kind(t)
        pairs = by_date[t]
        ch = [_one_change(pairs[a], pairs[b], kind) for a, b in zip(common, common[1:])]
        if any(not _finite(v) for v in ch[-w:]):
            return None
        cols.append(ch[-w:])
    return cols


def correlation(closes, dates, a, b, w=CORR_WINDOW, offset=0):
    """Correlation of the two series' changes over the last w shared sessions.

    Each leg is differenced or returned by its own kind, so an equity-vs-yield pair
    compares percent moves against basis-point moves rather than nonsense.

    `offset` steps the window back that many sessions, which is how the same pair is
    read twice to see whether the relationship has turned over.
    """
    cols = aligned_changes(closes, dates, [a, b], w + offset)
    if cols is None:
        return None
    end = -offset if offset else None
    xs, ys = cols[0][:end][-w:], cols[1][:end][-w:]
    if len(xs) < w:
        return None
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return None
    return round(sxy / (sxx * syy) ** 0.5, 3)


# 자산군 이름은 다섯 개로 고정한다. GS는 로딩 산점도를 사람이 눈으로 읽고 「PC1 =
# 성장/위험」이라 불렀는데, 그 해석을 매일 에이전트에게 맡기면 이름이 흔들린다.
# 우리는 자산군이 이미 정해져 있으니 «어느 군에 가장 크게 실렸나»를 기계적으로
# 고른다 — 통제 어휘 다섯 개 중 하나가 나온다.
# 공통 힘이 실제로 있을 때만 «주도 자산군»이라는 말이 성립한다. 서로 무관한 열
# 개에서는 1등이 매번 바뀌고(2026-08-28 codex 실측), 그걸 국면 전환이라 부르면
# 없는 사건이 만들어진다. 그래서 둘 다 넘어야 이름을 붙인다 — 상위 1개 요인이
# 균등분산(10자산이면 10%)을 크게 웃돌 것, 그리고 1등 자산군이 2등을 뚜렷이
# 앞설 것.
# 실측 보정(2026-08-28): 상위 1개 요인 비중은 서로 무관한 열 개에서 15.5~16.0%,
# 공통 움직임이 실제로 있는 경우 20.8~43.6%로 갈렸다.
MIN_DRIVER_SHARE = 20.0

# 1·2번 고유값이 붙어 있으면 1번 고유벡터의 «방향» 자체가 창을 하루 옮기는 것만
# 으로 돌아간다 — 그 위에서 읽은 그룹 순위는 아무것도 뜻하지 않는다. 실측 분포
# (3년 종가, 60세션 창 381개): 최소 0.167 / 하위 10% 0.301 / 중앙 0.495 / 최대
# 0.794, 0.20 미만인 창은 14개.
MIN_EIGEN_GAP = 0.20

# 1등이 아니라 «그다음»이 정보다. 3년 381개 창에서 1등은 전부 「주식」이었다 —
# 그룹 점수가 로딩의 평균이라 구조적으로 보장되는 것은 아니지만(원자재가 1등인
# 합성 사례는 실제로 통과한다) 이 구성과 이 관측 기간에서는 한 번도 안 바뀌었다.
# 반면 그다음 자리는 금리 258 / 원자재 86 / 달러 37창으로 돌았다.
#
# 이름을 붙일 조건 둘. 2·3위 «상대» 격차가 10% 미만이면 인접창(60세션 중 59를
# 공유) 일치율이 0.672 로 사실상 동전던지기이고, 10% 이상이면 0.925 다. 리드 대비
# 30% 문턱은 로딩이 0 근처인데 격차만 크게 나오는 창을 걸러 낸다(0.073 대 0.070
# 같은 창은 둘 다 애초에 요인 위에 없다). 표본 분할로 재검증했다 — 과거 구간
# (오프셋 190~380)에서 문턱을 고르고 최근 구간(0~189)에서 평가해 유지율 0.930 /
# 0.940. 시차별 지속성은 1세션 0.93, 5세션 0.81, 20세션 0.57, 60세션 0.29다.
#
# 절대 격차(옛 MIN_DRIVER_MARGIN = 0.05)는 버렸다. corr(상위 1개 요인 비중,
# 절대격차) = -0.84 로 «응집도가 높을수록 격차가 줄어드는» 구조라, 가장 읽을
# 값이 있는 날에 정확히 판정이 막혔다 — 381창 중 32창(8.4%)이 그렇게 사라졌다.
MIN_COMPANION_GAP = 0.10
MIN_COMPANION_RATIO = 0.30

# 응집도 백분위가 비교하는 과거 창의 수. 오늘은 자기 잣대에서 뺀다.
COHESION_LOOKBACK = 252

# VIX는 주식과 한 묶음이다. S&P 옵션에서 나온 지표라 같은 위험 요인의 거울이고,
# 따로 세워 두면 하나의 힘이 「주식 0.428 vs 변동성 0.400」으로 쪼개져 1등이
# 동전 던지기가 된다(2026-08-28 실측). 사람이 갈아타는 자산군이 아니다.
DRIVER_GROUPS = (
    ('주식', ('^GSPC', '^IXIC', '^RUT', '^VIX')),
    ('금리', ('^TNX', '^TYX')),
    ('달러', ('DX-Y.NYB', 'JPY=X')),
    ('원자재', ('CL=F', 'GC=F')),
)


def _corr_matrix(closes, dates, tickers, w, offset=0):
    cols = aligned_changes(closes, dates, tickers, w + offset)
    if cols is None or len(cols) < 3:
        return None, None
    import numpy as np

    m = np.array([c[:-offset] if offset else c for c in cols], dtype=float)
    if m.shape[1] < w or not np.all(m.std(axis=1, ddof=1) > 0):
        return None, None
    corr = np.corrcoef(m)
    return (corr, np.array(tickers)) if np.all(np.isfinite(corr)) else (None, None)


def market_drivers(closes, dates, tickers, w=CORR_WINDOW, offset=0):
    """Which asset group the market's biggest shared move is loading on.

    The largest eigenvector of the correlation matrix is the direction everything is
    moving along; whichever group sits heaviest on it is what the market is currently
    "about". The second force excludes the first group, because "첫 번째도 주식,
    두 번째도 주식" names nothing.
    """
    corr, names = _corr_matrix(closes, dates, tickers, w, offset)
    if corr is None:
        return None
    import numpy as np

    vals, vecs = np.linalg.eigh(corr)
    order = np.argsort(vals)[::-1]
    n = len(vals)
    idx = {t: i for i, t in enumerate(names)}

    def rank(vec):
        out = []
        for ko, members in DRIVER_GROUPS:
            loads = [abs(float(vec[idx[t]])) for t in members if t in idx]
            if loads:
                out.append((sum(loads) / len(loads), ko))
        return sorted(out, reverse=True)

    share = float(vals[order[0]]) / n * 100
    if share < MIN_DRIVER_SHARE:
        return None
    lam1, lam2 = float(vals[order[0]]), float(vals[order[1]])
    if lam1 <= 0 or (lam1 - lam2) / lam1 < MIN_EIGEN_GAP:
        return None
    first_rank = rank(vecs[:, order[0]])
    if len(first_rank) < 3:
        return None
    first_ko = first_rank[0][1]
    second_rank = [r for r in rank(vecs[:, order[1]]) if r[1] != first_ko]
    if not second_rank:
        return None
    return {
        'first': {'group_ko': first_ko, 'share_pct': round(share, 1)},
        'second': {'group_ko': second_rank[0][1],
                   'share_pct': round(lam2 / n * 100, 1)},
        'companion': _companion(first_rank),
    }


def _companion(first_rank):
    """The group riding hardest on the common factor after the leader.

    Loadings are absolute, so this says «moves with the same force», not «moves the
    same way» — direction needs the correlations, not this. None when the second and
    third places are too close to separate, or when the runner-up is barely on the
    factor at all.
    """
    lead, (load, ko) = first_rank[0][0], first_rank[1]
    third = first_rank[2][0]
    if not load or not lead:
        return None
    gap = (load - third) / load
    ratio = load / lead
    if gap < MIN_COMPANION_GAP or ratio < MIN_COMPANION_RATIO:
        return None
    return {'group_ko': ko, 'loading': round(load, 3),
            'gap_pct': round(gap * 100, 1), 'ratio_pct': round(ratio * 100, 1)}


def _eigs(m):
    """Sorted eigenvalues of the correlation matrix of one window, or None."""
    import numpy as np

    if m.shape[1] < 3 or not np.all(m.std(axis=1, ddof=1) > 0):
        return None
    corr = np.corrcoef(m)
    if not np.all(np.isfinite(corr)):
        return None
    return np.sort(np.linalg.eigvalsh(corr))[::-1]


def cohesion(closes, dates, tickers, w=CORR_WINDOW, lookback=COHESION_LOOKBACK):
    """How much of the market is one bet, and whether that is unusual for it.

    Standardise each asset's changes, take the correlation matrix, and read its
    eigenvalues: the largest one is the share of all movement that a single common
    factor explains. High does not mean the diversification is gone — assets moving
    exactly opposite load on the same factor too — it means one force is setting the
    day and the names are downstream of it.

    The level alone says nothing, because 43% is high for one market and low for
    another. So it is ranked against the same reading over the previous `lookback`
    windows, today excluded from its own yardstick, exactly as level_percentile does
    for a price. Without enough history the three ranking fields stay None rather
    than being computed off a handful of windows.
    """
    cols = aligned_changes(closes, dates, tickers, w + lookback)
    if cols is None:
        cols = aligned_changes(closes, dates, tickers, w)
    if cols is None or len(cols) < 3:
        return None
    import numpy as np

    full = np.array(cols, dtype=float)
    eig = _eigs(full[:, -w:]) if full.shape[1] >= w else None
    if eig is None:
        return None
    n = len(eig)
    top1 = float(eig[0]) / n * 100
    out = {
        'n_assets': n,
        'top1_pct': round(top1, 1),
        'top3_pct': round(float(eig[:3].sum()) / n * 100, 1),
        'percentile': None,
        'band': None,
        'history_windows': None,
    }
    hist = []
    for off in range(1, lookback + 1):
        end = full.shape[1] - off
        if end - w < 0:
            break
        e = _eigs(full[:, end - w:end])
        if e is not None:
            hist.append(float(e[0]) / len(e) * 100)
    # 부분 이력으로는 백분위를 만들지 않는다. 창 스무 개로 「2년 중 가장 높다」를
    # 쓰면 그건 맞는 말이 아니라 표본이 없다는 말이다.
    if len(hist) >= lookback:
        # 반올림 전 값끼리 비교한다 — 표시용 반올림을 순위에 끌어들이면 소수점
        # 한 자리가 같은 창들이 전부 동점이 된다.
        below = sum(1 for v in hist if v < top1)
        ties = sum(1 for v in hist if v == top1)
        pct = round((below + 0.5 * ties) / len(hist) * 100, 1)
        out['percentile'] = pct
        out['band'] = percentile_band(pct)
        out['history_windows'] = len(hist)
    return out


def estimate_weights(cols, y, iters=20000, tol=1e-12):
    """Non-negative least squares: the index weights that best explain its returns.

    Projected gradient rather than scipy.optimize.nnls — scipy is not in the
    collector's dependency set and this problem is 252x11. Non-negativity is not
    cosmetic: an unconstrained fit hands collinear sectors negative coefficients,
    and a negative portfolio weight is not a thing the index can have.

    Returns (weights, r2, converged). r2 is how much of the index's daily variation
    these sectors account for at all; `converged` says whether the iteration
    actually settled, so an unfinished fit is never passed off as a finished one.
    """
    import numpy as np

    x = np.array(cols, dtype=float).T
    y = np.array(y, dtype=float)
    if not (np.all(np.isfinite(x)) and np.all(np.isfinite(y))):
        return None, None, False
    lip = float(np.linalg.norm(x, 2) ** 2)
    if not lip:
        return None, None, False
    w = np.full(x.shape[1], 1.0 / x.shape[1])
    converged = False
    for _ in range(iters):
        nxt = np.clip(w - (x.T @ (x @ w - y)) / lip, 0, None)
        if float(np.abs(nxt - w).max()) < tol:
            w, converged = nxt, True
            break
        w = nxt
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = round(1 - float(((y - x @ w) ** 2).sum()) / ss_tot, 4) if ss_tot > 0 else None
    return [float(v) for v in w], r2, converged


def sector_contributions(closes, dates, sectors, index_ticker, w=WEIGHT_WINDOW):
    """Split the index's move into who actually caused it.

    Eleven sector percentages tell you what happened to each sector, not what
    happened to the index. The weights are not in the data we collect, so they are
    estimated (see estimate_weights) — from the sessions *before* today, so the day
    being explained never helps choose the weights that explain it.

    Estimates of the smallest sectors are not identifiable from a year of daily
    returns, which is why the per-sector weight is deliberately never published:
    "Real Estate 0.00%" would read as a fact about the index and be wrong. Those
    sectors do not get a row at all — they are listed in `unidentified` and their
    effect stays in the residual. What is published is each identifiable sector's
    contribution, plus the part of the move the split does not account for, so it is
    never made to look complete when it is not.
    """
    tickers = [t for _, t in sectors]
    cols = aligned_changes(closes, dates, tickers + [index_ticker], w + 1)
    if cols is None:
        return None

    train_x = [c[:-1] for c in cols[:-1]]      # every shared session except today
    train_y = cols[-1][:-1]
    weights, r2, converged = estimate_weights(train_x, train_y)
    if weights is None or r2 is None or not converged:
        return None

    index_change = cols[-1][-1]
    rows, unidentified = [], []
    for (name, _t), weight, col in zip(sectors, weights, cols[:-1]):
        if weight < MIN_IDENTIFIABLE_WEIGHT:
            unidentified.append(name)
            continue
        rows.append({'name': name,
                     'change': round(col[-1], 2),
                     'contribution': round(weight * col[-1], 3)})
    # Nothing identifiable means there is no split, not an empty one. An empty rows
    # list would clear the gate exactly as a real attribution does.
    if not rows:
        return None
    rows.sort(key=lambda r: abs(r['contribution']), reverse=True)
    explained = sum(r['contribution'] for r in rows)
    return {
        'index_change': round(index_change, 2),
        'estimated': True,
        'fit_r2': r2,
        'window_sessions': w,
        'rows': rows,
        'unidentified': unidentified,
        'residual': round(index_change - explained, 3),
    }


def _leg(rows, key):
    row = (rows or {}).get(key) or {}
    lvl = row.get('level')
    return (float(lvl), row.get('date'), row.get('chg_1d_bp')) if _finite(lvl) else (None, None, None)


def forward_5y5y(rows):
    """The 5-year rate the curve implies for five years from now: 2 x 10y - 5y.

    "The 10-year rose 5bp" mixes today's noise with the market's long view. This
    strips the first five years out and leaves the second half, which is where a
    change in the growth/inflation outlook actually shows up.

    Every leg must share one basis date — yield_drivers already aligns them, and a
    forward built from two different days is an artefact, not a rate.
    """
    n5, d5, c5 = _leg(rows, 'nominal_5y')
    n10, d10, c10 = _leg(rows, 'nominal_10y')
    if n5 is None or n10 is None or not d5 or d5 != d10:
        return None

    nominal = round(2 * n10 - n5, 3)
    out = {'nominal': nominal, 'date': d5, 'real': None, 'chg_1d_bp': None,
           'breakeven_implied': None, 'breakeven_gap_bp': None}

    if c5 is not None and c10 is not None:
        out['chg_1d_bp'] = round(2 * c10 - c5, 1)

    r5, dr5, _ = _leg(rows, 'real_5y')
    r10, dr10, _ = _leg(rows, 'real_10y')
    if r5 is not None and r10 is not None and dr5 == dr10 == d5:
        out['real'] = round(2 * r10 - r5, 3)
        out['breakeven_implied'] = round(nominal - out['real'], 3)

    # Cross-check against FRED's own 5y5y breakeven. The two are built from different
    # series, so a wide gap means one of the curves is stale — worth seeing, not hiding.
    be, dbe, _ = _leg(rows, 'breakeven_5y5y')
    if be is not None and out['breakeven_implied'] is not None and dbe == d5:
        out['breakeven_gap_bp'] = round((out['breakeven_implied'] - be) * 100, 1)
    return out


# What the brief actually talks about, in the order it talks about it.
TRACKED = [
    ('S&P 500', '^GSPC'), ('Nasdaq', '^IXIC'), ('Russell 2000', '^RUT'), ('VIX', '^VIX'),
    ('DXY', 'DX-Y.NYB'), ('USD/JPY', 'JPY=X'), ('USD/KRW', 'KRW=X'),
    ('WTI', 'CL=F'), ('Gold', 'GC=F'),
    ('10Y', '^TNX'), ('30Y', '^TYX'),
]

# Relationships the brief assumes every day without ever checking. A sign change in
# the first one invalidates the standing "yields up, stocks down" reflex.
CORR_PAIRS = [
    ('equity_rates', '주식과 금리', '^GSPC', '^TNX'),
    ('equity_dollar', '주식과 달러', '^GSPC', 'DX-Y.NYB'),
    ('gold_rates', '금과 금리', 'GC=F', '^TNX'),
    ('memory_nasdaq', '메모리와 나스닥', 'MU', '^IXIC'),
]

COHESION_SET = ['^GSPC', '^IXIC', '^RUT', '^VIX', 'DX-Y.NYB', 'JPY=X', 'CL=F', 'GC=F',
                '^TNX', '^TYX']

# Below this, a correlation is noise around zero and its sign means nothing — so a
# reading that crosses zero inside the band is not reported as a change of regime.
FLIP_FLOOR = 0.2



def _corr_band(v):
    if v is None:
        return None
    a = abs(v)
    if a < FLIP_FLOOR:
        return '거의 무관'
    lead = '같이 움직임' if v > 0 else '반대로 움직임'
    return f'{lead}({"강하게" if a >= 0.6 else "느슨하게"})'


def compute(closes, market_data, sectors, dates=None, index_ticker='^GSPC'):
    """Assemble every reading into the block the writer and gate read.

    Nothing here fails loudly: a series we could not download comes back as None so
    the writer drops that line, exactly as an absent stance metric becomes UNKNOWN
    rather than a decision. `flipped` is None — not False — when the comparison could
    not be made, so "we do not know" is never serialised as "it did not happen".
    """
    moves, levels = {}, {}
    for name, ticker in TRACKED:
        mult = move_multiple(closes, ticker)
        ch = changes(closes, ticker)
        today = ch[-1] if ch else None
        if mult is None and not _finite(today):
            moves[name] = None
        else:
            moves[name] = {
                'ticker': ticker,
                'change': round(today, 3) if _finite(today) else None,
                'unit': 'pp' if change_kind(ticker) == 'd' else '%',
                'multiple': mult,
                'band': move_band(mult),
            }
        pct = level_percentile(closes, ticker)
        # How many sessions actually backed the reading, so a caption cannot claim two
        # years of context off eight months of downloaded history.
        if pct is None:
            levels[name] = None
        else:
            s = _series(closes, ticker)
            n = min(len(s) - 1, PCTL_WINDOW)
            # 날 수는 세어서 넘긴다. 백분위에서 되돌리면 신고가가 「이보다 높았던
            # 날이 하루뿐」이 된다(2026-09-02 codex 검토).
            prior = s[-(PCTL_WINDOW + 1):][:-1]
            levels[name] = {
                'value': round(_series(closes, ticker)[-1], 3),
                'percentile': pct,
                'band': percentile_band(pct),
                'sessions': n,
                # 발행본이 그대로 쓸 말. 「96.4 백분위」는 계산에는 맞지만 읽는
                # 사람에게는 아무 그림도 안 그려 준다(2026-09-02 사용자 지적) —
                # writer 가 백분위를 옮겨 적지 않게 옮긴 말을 내려보낸다. 축 점수 z를
                # 만지지 않는 것(macro_metrics)과 같은 계약.
                'plain': standing_mod.plain(
                    pct, n,
                    above=sum(1 for v in prior if v > s[-1]),
                    below=sum(1 for v in prior if v < s[-1])),
            }

    correlations = []
    for key, label, a, b in CORR_PAIRS:
        now = correlation(closes, dates, a, b)
        prior = correlation(closes, dates, a, b, offset=CORR_WINDOW)
        if now is None or prior is None:
            flipped = None
        else:
            flipped = bool(abs(now) >= FLIP_FLOOR and abs(prior) >= FLIP_FLOOR
                           and (now > 0) != (prior > 0))
        correlations.append({'key': key, 'label_ko': label, 'value': now,
                             'prior': prior, 'flipped': flipped, 'band': _corr_band(now)})

    coh = cohesion(closes, dates, COHESION_SET)
    drivers = market_drivers(closes, dates, COHESION_SET)
    if drivers:
        prior = market_drivers(closes, dates, COHESION_SET, offset=CORR_WINDOW)
        # 둘 다 기록한다 — 발행본이 「순서가 같다」고 쓰려면 직전 2등도 알아야 한다.
        drivers['prior'] = None if not prior else {
            'first': prior['first']['group_ko'], 'second': prior['second']['group_ko']}
        now_ko = (drivers.get('companion') or {}).get('group_ko')
        was_ko = ((prior or {}).get('companion') or {}).get('group_ko')
        drivers['companion_prior'] = was_ko
        # 리드가 다르면 두 창은 서로 다른 그룹을 뺀 순위를 비교하게 된다 — 같은
        # 질문에 대한 두 답이 아니므로 「바뀌었다」고 말할 수 없다.
        same_lead = bool(prior and prior['first']['group_ko']
                         == drivers['first']['group_ko'])
        # 오늘 일어난 전환이 아니라 «직전 60세션 구간과 비교하면 다르다»는 뜻이다.
        # 실측(시차 60): 유지 29% / 교체 35% / 판정 불가 37%.
        drivers['companion_changed'] = bool(
            now_ko and was_ko and same_lead and now_ko != was_ko)
    factors = {}
    for key, label, basket in BASKETS:
        got = factor_decomposition(closes, dates, basket)
        if got:
            factors[key] = dict(got, label_ko=label)
    rows = ((market_data or {}).get('yield_drivers') or {}).get('rows')
    return {
        'windows': {'move': MOVE_WINDOW, 'percentile': PCTL_WINDOW,
                    'correlation': CORR_WINDOW, 'weights': WEIGHT_WINDOW},
        # Whether the cross-series readings actually landed, not merely whether dates
        # were handed in: a dates dict that is present but too short or too patchy to
        # join leaves every reading None, and a flag saying otherwise would mislead
        # whoever reads it next.
        'aligned': bool(coh) and any(c['value'] is not None for c in correlations),
        'moves': moves,
        'levels': levels,
        'correlations': correlations,
        'cohesion': coh,
        'drivers': drivers,
        'factor_decomposition': factors,
        'sector_contribution': sector_contributions(closes, dates, sectors, index_ticker),
        'forward_5y5y': forward_5y5y(rows) if rows else None,
    }


# ── 팩터 분해 ──────────────────────────────────────────────────────────────
#
# 「메모리가 나스닥을 앞섰다」는 그 자체로는 메모리 얘기인지 그냥 성장주가 오른
# 것인지 말해 주지 않는다. 시장을 뺀 초과수익을 세 개의 롱숏 스프레드에 회귀해서
# 스타일로 설명되는 몫과 그 바스켓 고유의 몫을 가른다. GS의 FactorRiskModel은
# 인증 벽 뒤지만 우리가 답하려는 질문에는 세 요인이면 충분하고, 네 다리 전부
# 이미 받고 있는 시세다.

FACTORS = (
    ('style', '성장−가치', 'IVW', 'IVE'),
    ('size', '대형−소형', '^GSPC', '^RUT'),
    # 반도체 축(2026-08-28 사용자 지시). 이걸 빼면 성장−가치 다리가 반도체 움직임을
    # 대신 떠안아 스타일 베타가 창 길이에 따라 +4.05~+1.52로 흔들렸다. 넣으면 스타일이
    # ≈0으로 수렴하고 반도체 베타가 +1.17~+1.47로 안정된다(실측). 모형이 잘못 지정돼
    # 있었다는 뜻이고, R²(메모리 0.49→0.74)보다 이쪽이 더 큰 소득이다.
    ('semis', '반도체', 'SOXX', '^GSPC'),
)

BASKETS = (
    ('memory', '메모리', ('MU', 'WDC', 'STX')),
    ('ai_infra', 'AI 인프라', ('MRVL', 'COHR', 'LITE', 'GEV', 'VRT')),
)

# Everything compute() reads, for the collector's one batched download. Sector ETFs
# are not here: they come from the collector's own SECTORS list.
HISTORY_TICKERS = sorted(
    {t for _, t in TRACKED}
    | set(COHESION_SET)
    | {a for _, _, a, _ in CORR_PAIRS}
    | {b for _, _, _, b in CORR_PAIRS}
    # 팩터 다리와 바스켓도 여기서 선언한다. 스탠스 쪽 목록에 얹어 두면 그쪽이
    # 바뀔 때 조용히 빠진다.
    | {t for _, _, a, b in FACTORS for t in (a, b)}
    | {t for _, _, basket in BASKETS for t in basket}
)

FACTOR_WINDOW = 60      # sessions the betas are fitted over
FACTOR_LONG_WINDOW = 252  # 같은 적합을 긴 창에서 한 번 더 — 안정성 근거를 함께 남긴다
FACTOR_HORIZON = 20     # sessions of excess return being split


def factor_decomposition(closes, dates, basket, market='^GSPC',
                         w=FACTOR_WINDOW, horizon=FACTOR_HORIZON):
    """Split a basket's excess return over the market into style, size and its own.

    남는 몫은 **「고유 요인」이 아니라 「이 축들로 설명되지 않는 몫」**이다. 반도체
    축이 들어오면서 메모리에 대해서는 사실상 «반도체 전반 대비 얼마나 달랐나»가 된다.
    SOXX 안에 마이크론이 들어 있어(메모리 3사가 SOXX 설명력에 +0.228을 더한다, 실측)
    반도체 몫과 남는 몫이 서로 얼마나 섞였는지는 이 산출만으로 가릴 수 없다 — 편향이
    어느 쪽으로 향하는지도 일반적으로는 정해지지 않는다(2026-08-28 codex 반례).
    그러니 「메모리 고유」라고 부르지 않고, 남는 몫을 원인 규명으로도 쓰지 않는다. 시장
    민감도가 1이 아니면 그 차이도 여기 섞여 들어온다(2026-08-28 codex 지적). 그
    몫을 회귀로 갈라내 보려 했으나 시장 다리와 성장−가치 다리가 실측 0.75로 붙어
    있어 시장 베타가 창 길이에 따라 -0.94~+1.17로 흔들렸다 — 공유된 변동을 어느
    다리에 줄지는 모형 선택이지 사실이 아니다. 갈라낸 척하는 대신 **단변량 시장
    베타를 `market_beta`로 따로 실어** 독자가 남은 몫을 그만큼 깎아 읽게 한다.

    Betas come from w sessions of daily data; the split is of the last `horizon`
    sessions. 일간 수익률에 선형이라 반올림 전에는 세 몫과 고유분이 초과수익에
    정확히 닫힌다(인쇄용으로 각각 반올림하면 0.01%p 안쪽 오차가 남을 수 있다).

    `fit_r2` says how much of the daily excess the factors account for at all. A low
    value does not invalidate the specific part; it means the specific part is most
    of the story, which is itself the finding.
    """
    legs = [market] + [t for _, _, a, b in FACTORS for t in (a, b)] + list(basket)
    cols = aligned_changes(closes, dates, legs, w)
    if cols is None:
        return None
    if horizon > w:
        return None
    import numpy as np

    by_ticker = dict(zip(legs, cols))
    mkt = np.array(by_ticker[market], dtype=float)
    names = np.array([by_ticker[t] for t in basket], dtype=float).mean(axis=0)
    excess = names - mkt

    # 시장 다리를 함께 회귀한다. 계수는 «시장 민감도 − 1»이라 기여가 곧 베타
    # 초과분이 만든 몫이 된다.
    x = np.array([np.array(by_ticker[a], dtype=float) - np.array(by_ticker[b], dtype=float)
                  for _, _, a, b in FACTORS]).T
    legs_meta = [(k, lab) for k, lab, _a, _b in FACTORS]
    try:
        betas, *_ = np.linalg.lstsq(x, excess, rcond=None)
    except np.linalg.LinAlgError:
        return None
    if not np.all(np.isfinite(betas)):
        return None

    ss_tot = float(((excess - excess.mean()) ** 2).sum())
    resid = excess - x @ betas
    r2 = round(1 - float((resid ** 2).sum()) / ss_tot, 4) if ss_tot > 0 else None

    tail = slice(-horizon, None)
    factors = {}
    for i, (key, label) in enumerate(legs_meta):
        factors[key] = {
            'label_ko': label,
            # 시장 다리의 계수는 «민감도 − 1»이므로 읽기 좋게 1을 더해 돌려준다.
            'beta': round(float(betas[i]), 3),
            'contribution': round(float(betas[i] * x[tail, i].sum()), 3),
        }
    # 단변량 시장 베타 — 스프레드끼리의 상관과 무관하게 잡히는, 해석 가능한 값.
    mvar = float((mkt * mkt).sum())
    market_beta = round(float((names * mkt).sum() / mvar), 3) if mvar else None

    # 안정성 근거를 산출에 담는다(2026-08-28 codex 지적). 손으로 재고 버리면 발행본의
    # 수치를 나중에 아무도 재검증할 수 없다. 긴 창에서 같은 적합을 한 번 더 하고,
    # 다리 사이 최대 상관도 남긴다 — 창을 바꿔 부호가 뒤집히는 다리는 인용하지 않는다.
    corrs = [abs(float(np.corrcoef(x[:, i], x[:, j])[0, 1]))
             for i in range(x.shape[1]) for j in range(i + 1, x.shape[1])]
    betas_long = None
    long_cols = aligned_changes(closes, dates, legs, FACTOR_LONG_WINDOW)
    if long_cols is not None:
        lt = dict(zip(legs, long_cols))
        lmkt = np.array(lt[market], dtype=float)
        lnames = np.array([lt[t] for t in basket], dtype=float).mean(axis=0)
        lx = np.array([np.array(lt[a], dtype=float) - np.array(lt[b], dtype=float)
                       for _, _, a, b in FACTORS]).T
        try:
            lb, *_ = np.linalg.lstsq(lx, lnames - lmkt, rcond=None)
            if np.all(np.isfinite(lb)):
                betas_long = {k: round(float(lb[i]), 3)
                              for i, (k, _lab, _a, _b) in enumerate(FACTORS)}
        except np.linalg.LinAlgError:
            betas_long = None

    return {
        'excess_pct': round(float(excess[tail].sum()), 3),
        'market_beta': market_beta,
        'factors': factors,
        'specific_pct': round(float(resid[tail].sum()), 3),
        'fit_r2': r2,
        'window_sessions': w,
        'horizon_sessions': horizon,
        'diagnostics': {
            'long_window_sessions': FACTOR_LONG_WINDOW,
            'betas_long': betas_long,
            'max_factor_corr': round(max(corrs), 3) if corrs else None,
        },
    }
