"""Deterministic axis scores behind the macro regime.

`fred_series()` in collect_market_data.py already downloads each series' *entire*
history and throws all but the last two observations away. This module spends that
history instead: per-indicator momentum, standardised against the indicator's own
past, aggregated into a growth axis and an inflation axis. No extra network calls.

Pure — `compute()` takes plain lists and dicts, so the whole regime read is testable
offline and reproduces exactly from the committed data.

Two rules earn their keep:

* **Momentum, not level.** The grid's vocabulary ("둔화 / 보합 / 가속") names a
  direction of travel, so the score has to measure change, not altitude.
* **Equal weight across sub-axes.** Labor ships seven series and Consumption two.
  Weighting by indicator count would make the growth axis a labour-market index
  wearing a broader name.
"""

import statistics

# polarity: +1 when a rising print means stronger growth (or hotter inflation).
# window: observations per momentum block — 3 months, 4 weeks, or 1 quarter.
_POLARITY = {
    'JOLTS Job Openings': (1, 3),
    'Initial Jobless Claims': (-1, 4),
    'Initial Claims 4-wk MA': (-1, 4),
    'Continuing Jobless Claims': (-1, 4),
    'Nonfarm Payrolls (chg)': (1, 3),
    'Unemployment Rate': (-1, 3),
    'Avg Hourly Earnings MoM': (1, 3),
    'Industrial Production MoM': (1, 3),
    'Durable Goods Orders MoM': (1, 3),
    'New Home Sales': (1, 3),
    'Existing Home Sales': (1, 3),
    'Real GDP Growth QoQ (ann.)': (1, 1),
    'Retail Sales MoM': (1, 3),
    'Michigan Consumer Sentiment': (1, 3),
    'CPI YoY': (1, 3),
    'CPI MoM': (1, 3),
    'Core CPI YoY': (1, 3),
    'Core CPI MoM': (1, 3),
    'PPI Final Demand MoM': (1, 3),
    'PCE Price Index YoY': (1, 3),
    'Core PCE YoY': (1, 3),
    'Michigan 1-Yr Inflation Exp': (1, 3),
}

GROWTH_AXES = ('Labor', 'Activity', 'Consumption')
INFLATION_AXES = ('Inflation',)

# Momenta older than this stop describing the same economy.
LOOKBACK = 60

_R3 = 3


def polarity_for(name):
    return _POLARITY.get(name, (1, 3))


def transform_series(vals, tf):
    """Raw (date, value) history -> the transformed series the dashboard prints."""
    xs = [float(v) for _, v in vals or []]
    if tf == 'level':
        return xs
    if tf == 'mom_pct':
        return [(xs[i] / xs[i - 1] - 1) * 100 for i in range(1, len(xs)) if xs[i - 1]]
    if tf == 'mom_diff':
        return [xs[i] - xs[i - 1] for i in range(1, len(xs))]
    if tf == 'yoy_pct':
        return [(xs[i] / xs[i - 12] - 1) * 100 for i in range(12, len(xs)) if xs[i - 12]]
    raise ValueError(tf)


def momentum(values, window):
    """Mean of the last `window` observations minus the mean of the `window` before."""
    if values is None or len(values) < 2 * window or window < 1:
        return None
    recent = values[-window:]
    prior = values[-2 * window:-window]
    return sum(recent) / window - sum(prior) / window


def momentum_z(values, window, lookback=LOOKBACK):
    """Today's momentum in units of this indicator's own typical momentum."""
    now = momentum(values, window)
    if now is None:
        return None
    history = []
    for end in range(2 * window, len(values) + 1):
        m = momentum(values[:end], window)
        if m is not None:
            history.append(m)
    history = history[-lookback:]
    if len(history) < 8:
        return None
    try:
        sd = statistics.pstdev(history)
    except statistics.StatisticsError:
        return None
    if not sd:
        return None
    return round(now / sd, _R3)


def _axis_mean(rows, axis):
    zs = [r['signed_z'] for r in rows if r['axis'] == axis and r['signed_z'] is not None]
    return sum(zs) / len(zs) if zs else None


def _group_score(rows, axes):
    means = [m for m in (_axis_mean(rows, a) for a in axes) if m is not None]
    return round(sum(means) / len(means), _R3) if means else None


def _diffusion(rows, axes):
    zs = [r['signed_z'] for r in rows
          if r['axis'] in axes and r['signed_z'] is not None]
    if not zs:
        return None
    return round(sum(1 for z in zs if z > 0) / len(zs), _R3)


def compute(series_by_id, econ_indicators, last_seen=None):
    """Full history + today's dashboard rows -> axis scores, diffusion, new releases.

    `last_seen` is yesterday's {name: [ref_period, actual]} carried in macro.json. An
    indicator whose reading is byte-identical to yesterday's did not release today, and
    a day with no releases cannot move the regime.
    """
    rows, releases, seen_now = [], [], {}

    for item in econ_indicators or []:
        name = item.get('name')
        axis = item.get('axis')
        pol, window = polarity_for(name)
        values = transform_series(series_by_id.get(item.get('fred_id')),
                                  item.get('transform', 'level'))
        z = momentum_z(values, window)
        rows.append({
            'name': name,
            'axis': axis,
            'polarity': pol,
            'window': window,
            'momentum_z': z,
            'signed_z': None if z is None else round(pol * z, _R3),
            'actual': item.get('actual'),
            'ref_period': item.get('ref_period'),
        })

        seen_now[name] = [item.get('ref_period'), item.get('actual')]
        if last_seen is None or seen_now[name] != (last_seen.get(name) or None):
            releases.append(name)

    for r in rows:
        r['is_new'] = r['name'] in releases

    return {
        'growth_score': _group_score(rows, GROWTH_AXES),
        'inflation_score': _group_score(rows, INFLATION_AXES),
        'growth_diffusion': _diffusion(rows, GROWTH_AXES),
        'inflation_diffusion': _diffusion(rows, INFLATION_AXES),
        'axis_scores': {a: (round(_axis_mean(rows, a), _R3)
                            if _axis_mean(rows, a) is not None else None)
                        for a in GROWTH_AXES + INFLATION_AXES},
        'indicators': rows,
        'new_releases': releases,
        'last_seen': seen_now,
    }
