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

# Where the number actually comes from. The dashboard prints FRED's copy, but FRED only
# carries the headline series — the composition that explains it (which CPI basket line,
# which payroll industry) lives only in the issuing agency's release.
#
# Keyed by *release document*, not by indicator: CPI YoY and CPI MoM are two rows off one
# BLS press release, and dissecting the same document twice is waste on the page and in
# the collector's budget. tier 1 = the prints markets trade; tier 2 = context.
RELEASES = {
    'cpi': (1, 'BLS', '소비자물가(CPI)', 'https://www.bls.gov/news.release/cpi.nr0.htm'),
    'employment': (1, 'BLS', '고용상황(Employment Situation)',
                   'https://www.bls.gov/news.release/empsit.nr0.htm'),
    'pce': (1, 'BEA', '개인소비지출(PCE)',
            'https://www.bea.gov/data/personal-consumption-expenditures-price-index'),
    'retail-sales': (1, 'Census', '소매판매',
                     'https://www.census.gov/retail/marts/www/marts_current.pdf'),
    'gdp': (1, 'BEA', 'GDP', 'https://www.bea.gov/data/gdp/gross-domestic-product'),
    'ppi': (2, 'BLS', '생산자물가(PPI)', 'https://www.bls.gov/news.release/ppi.nr0.htm'),
    'claims': (2, 'DOL', '신규 실업수당 청구', 'https://www.dol.gov/ui/data.pdf'),
    'jolts': (2, 'BLS', 'JOLTS 구인·이직', 'https://www.bls.gov/news.release/jolts.nr0.htm'),
    'industrial-production': (2, 'Federal Reserve', '산업생산(G.17)',
                              'https://www.federalreserve.gov/releases/g17/current/'),
    'durable-goods': (2, 'Census', '내구재 주문',
                      'https://www.census.gov/manufacturing/m3/adv/pdf/durgd.pdf'),
    'new-home-sales': (2, 'Census', '신규주택 판매',
                       'https://www.census.gov/construction/nrs/pdf/newressales.pdf'),
    'existing-home-sales': (2, 'NAR', '기존주택 판매',
                            'https://www.nar.realtor/newsroom/existing-home-sales'),
    'michigan': (2, 'U. Michigan', '미시간대 소비자심리', 'http://www.sca.isr.umich.edu/'),
}

INDICATOR_RELEASE = {
    'CPI YoY': 'cpi', 'CPI MoM': 'cpi', 'Core CPI YoY': 'cpi', 'Core CPI MoM': 'cpi',
    'Nonfarm Payrolls (chg)': 'employment', 'Unemployment Rate': 'employment',
    'Avg Hourly Earnings MoM': 'employment',
    'Core PCE YoY': 'pce', 'PCE Price Index YoY': 'pce',
    'Retail Sales MoM': 'retail-sales',
    'Real GDP Growth QoQ (ann.)': 'gdp',
    'PPI Final Demand MoM': 'ppi',
    'Initial Jobless Claims': 'claims', 'Continuing Jobless Claims': 'claims',
    'Initial Claims 4-wk MA': 'claims',
    'JOLTS Job Openings': 'jolts',
    'Industrial Production MoM': 'industrial-production',
    'Durable Goods Orders MoM': 'durable-goods',
    'New Home Sales': 'new-home-sales',
    'Existing Home Sales': 'existing-home-sales',
    'Michigan Consumer Sentiment': 'michigan', 'Michigan 1-Yr Inflation Exp': 'michigan',
}

# What actually moved underneath the headline. The issuing agencies sit behind bot
# protection (bls.gov and dol.gov return 403 even to a real browser UA from a
# residential IP — verified 2026-08-18), but the components are redistributed on FRED,
# which this collector already reaches. So the decomposition is deterministic rather
# than a daily scraping gamble — the same move that fixed STEP 1 on 2026-07-15.
#
# The press release still has things FRED does not: prior-month revisions, one-off
# special factors, the agency's own framing. Those stay a job for web research.
RELEASE_COMPONENTS = {
    'cpi': (
        ('에너지', 'CPIENGSL', 'mom_pct'),
        ('식품', 'CPIUFDSL', 'mom_pct'),
        ('주거비(shelter)', 'CUSR0000SAH1', 'mom_pct'),
        ('중고차', 'CUSR0000SETA02', 'mom_pct'),
        ('의료', 'CPIMEDSL', 'mom_pct'),
        ('서비스 ex-에너지', 'CUSR0000SASLE', 'mom_pct'),
    ),
    'employment': (
        ('민간 고용', 'USPRIV', 'mom_diff'),
        ('정부 고용', 'USGOVT', 'mom_diff'),
        ('헬스케어·사회복지', 'USEHS', 'mom_diff'),
        ('레저·숙박', 'USLAH', 'mom_diff'),
        ('제조업', 'MANEMP', 'mom_diff'),
        ('경제활동참가율', 'CIVPART', 'level'),
        ('U-6 실업률', 'U6RATE', 'level'),
        ('주당 노동시간', 'AWHAETP', 'level'),
    ),
    'retail-sales': (
        ('자동차 제외', 'RSFSXMV', 'mom_pct'),
    ),
    'pce': (
        ('서비스', 'PCESV', 'mom_pct'),
        ('내구재', 'PCEDG', 'mom_pct'),
        ('실질 개인소비', 'PCEC96', 'mom_pct'),
    ),
}

# Anatomy is worth doing properly for a few releases, not thinly for a dozen. On the
# first run every indicator reads as new, so an uncapped list would send the collector
# after every press release the dashboard touches.
MAX_HEADLINE_RELEASES = 3

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


def release_key(name):
    """HTML-attribute-safe id for a release block marker."""
    out = []
    for ch in (name or '').lower():
        if ch.isalnum():
            out.append(ch)
        elif out and out[-1] != '-':
            out.append('-')
    return ''.join(out).strip('-')


def _headline_releases(rows, releases):
    """New prints grouped by the document that announced them, most market-moving first."""
    new = [r for r in rows if r['name'] in set(releases)]
    grouped = {}
    for r in new:
        key = INDICATOR_RELEASE.get(r['name']) or release_key(r['name'])
        grouped.setdefault(key, []).append(r)

    out = []
    for key, items in grouped.items():
        tier, agency, label, url = RELEASES.get(key, (3, None, items[0]['name'], None))
        ranked = sorted(items, key=lambda r: -abs(r['signed_z'] or 0.0))
        out.append({
            'key': key, 'label': label, 'tier': tier, 'agency': agency, 'url': url,
            'primary': ranked[0]['name'],
            'max_abs_z': abs(ranked[0]['signed_z'] or 0.0),
            'indicators': [{'name': r['name'], 'axis': r['axis'], 'actual': r['actual'],
                            'previous': r.get('previous'), 'ref_period': r['ref_period'],
                            'momentum_z': r['momentum_z']} for r in items],
        })
    out.sort(key=lambda r: (r['tier'], -r['max_abs_z']))
    return out[:MAX_HEADLINE_RELEASES]


def component_specs(headline_releases):
    """Which extra FRED series today's promoted releases need. Only those — at most a
    handful of fetches, and none at all on a day with no release worth dissecting."""
    out = []
    for rel in headline_releases or []:
        for label, sid, tf in RELEASE_COMPONENTS.get(rel.get('key'), ()):
            out.append({'release': rel['key'], 'label': label,
                        'fred_id': sid, 'transform': tf})
    return out


def attach_components(headline_releases, series_by_id):
    """Fill each promoted release's `components` in place from fetched history.

    A component we could not fetch is dropped rather than carried as a hole — the
    writer prints what is here, and a missing basket line is not worth failing on.
    """
    for rel in headline_releases or []:
        comps = []
        for label, sid, tf in RELEASE_COMPONENTS.get(rel.get('key'), ()):
            raw = (series_by_id or {}).get(sid)
            values = transform_series(raw, tf)
            if not raw or not values:
                continue
            comps.append({
                'label': label, 'fred_id': sid, 'transform': tf,
                'actual': round(values[-1], _R3),
                'previous': round(values[-2], _R3) if len(values) > 1 else None,
                'ref_period': raw[-1][0],
            })
        rel['components'] = comps


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
            'previous': item.get('previous'),
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
        'headline_releases': _headline_releases(rows, releases),
        'last_seen': seen_now,
    }
