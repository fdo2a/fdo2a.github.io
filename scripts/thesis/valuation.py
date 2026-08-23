"""Mid-cycle fair value for memory names, computed two independent ways.

Peak-cycle memory earnings make P/E useless as a signal: the multiple is lowest at the
top, because the market is already discounting the fall. So a single earnings multiple
cannot be trusted here. This module runs two methods that fail differently —

  A. normalized earnings: FY1 consensus EPS x normalization ratio x normalized P/E
  B. asset:               book value two years out x scenario P/B

— and averages them. When the two land near each other the estimate is worth something;
when they diverge, the divergence itself is the finding.

The scenario probabilities and normalization ratios are *judgments*, not measurements,
and the result is almost entirely driven by them (raising Bull to 50% flips all three
names to undervalued). Callers must surface that, not hide it.

Pure — no network, no clock.

Design: docs/superpowers/specs/2026-08-24-thesis-watch-design.md
"""

# (normalization ratio applied to FY1 consensus EPS, probability weight)
SCENARIOS = {
    'bull': (0.80, 0.30),   # LTA/take-or-pay actually hold the floor; tight into 2028
    'base': (0.48, 0.45),   # 2027 peak, normalizes over 2028-29
    'bear': (0.25, 0.25),   # 2028 greenfield capacity lands into a glut
}

# Normalized P/E by scenario. Korean names carry a governance/cyclical discount that has
# persisted across cycles; pricing it away would be wishful, so it is explicit here.
MULTIPLES = {
    '005930.KS': {'bull': 11.0, 'base': 9.0, 'bear': 7.0},
    '000660.KS': {'bull': 11.0, 'base': 9.0, 'bear': 6.5},
    'MU':        {'bull': 14.0, 'base': 11.0, 'bear': 8.0},
}
DEFAULT_MULTIPLES = {'bull': 12.0, 'base': 10.0, 'bear': 7.0}

# Scenario P/B applied to projected book value.
PB_TARGETS = {
    '005930.KS': {'bull': 3.5, 'base': 2.3, 'bear': 1.4},
    '000660.KS': {'bull': 4.0, 'base': 2.6, 'bear': 1.5},
    'MU':        {'bull': 6.0, 'base': 3.8, 'bear': 2.0},
}
DEFAULT_PB = {'bull': 3.5, 'base': 2.3, 'bear': 1.4}

# Annual book-value accumulation by scenario, compounded over PROJECTION_YEARS.
BV_GROWTH = {
    '005930.KS': {'bull': 0.45, 'base': 0.28, 'bear': 0.10},
    '000660.KS': {'bull': 0.55, 'base': 0.30, 'bear': 0.10},
    'MU':        {'bull': 0.60, 'base': 0.35, 'bear': 0.12},
}
DEFAULT_BV_GROWTH = {'bull': 0.50, 'base': 0.30, 'bear': 0.10}

PROJECTION_YEARS = 2

# Safety margin off the probability-weighted value. Sized against the bear case's loss
# (-54% to -69% on these names) and its 25% weight, not picked round.
BAND1_DISCOUNT = 0.80
BAND2_DISCOUNT = 0.68


def _table(mapping, ticker, default):
    return mapping.get(ticker, default)


def fair_value(ticker, data):
    """Scenario fair values for one ticker, or None when EPS is missing.

    `data` needs `eps_fy1`; `bvps` is optional and its absence downgrades the result to
    the earnings method alone (reported via `method`) rather than failing.
    """
    eps = data.get('eps_fy1')
    if eps in (None, 0):
        return None
    bvps = data.get('bvps')

    pe = _table(MULTIPLES, ticker, DEFAULT_MULTIPLES)
    pb = _table(PB_TARGETS, ticker, DEFAULT_PB)
    growth = _table(BV_GROWTH, ticker, DEFAULT_BV_GROWTH)

    out = {'method': 'blended' if bvps else 'earnings_only'}
    for name, (ratio, _weight) in SCENARIOS.items():
        earnings_fv = eps * ratio * pe[name]
        if bvps:
            projected_bv = bvps * (1 + growth[name]) ** PROJECTION_YEARS
            asset_fv = projected_bv * pb[name]
            out[name] = round((earnings_fv + asset_fv) / 2)
        else:
            out[name] = round(earnings_fv)

    weighted = round(sum(out[name] * weight for name, (_r, weight) in SCENARIOS.items()))
    out['weighted'] = weighted
    # Derived from the *rounded* weighted value so a reader can reproduce the bands from
    # the number the page actually shows them.
    out['band1'] = round(weighted * BAND1_DISCOUNT)
    out['band2'] = round(weighted * BAND2_DISCOUNT)
    return out


def position_vs_scenarios(price, fv):
    """Where today's price sits against the scenario ladder, as plain labels.

    Used by the page and the notifier so both describe the same thing the same way.
    """
    if not fv or price is None:
        return None
    return {
        'vs_weighted_pct': round((price / fv['weighted'] - 1) * 100, 1),
        'vs_base_pct': round((price / fv['base'] - 1) * 100, 1),
        'upside_bull_pct': round((fv['bull'] / price - 1) * 100, 1),
        'downside_bear_pct': round((fv['bear'] / price - 1) * 100, 1),
        'in_band1': price <= fv['band1'],
        'in_band2': price <= fv['band2'],
    }
