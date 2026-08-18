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

# Tier-1 prints are never dropped — those are the ones the brief exists to explain, and
# in practice at most two or three land on the same morning. The cap applies only to the
# context releases, which is what keeps the first run (every indicator reads as new) from
# sending the collector after a dozen press releases.
MAX_SECONDARY_RELEASES = 2

# The dashboard table keeps the English series names (that is how they are published),
# but prose has to read in Korean. Without this the §8 paragraphs turn into a list of
# untranslated FRED tickers.
LABELS_KO = {
    'JOLTS Job Openings': '구인건수(JOLTS)',
    'Initial Jobless Claims': '신규 실업수당 청구',
    'Initial Claims 4-wk MA': '신규 청구 4주 평균',
    'Continuing Jobless Claims': '계속 실업수당 청구',
    'Nonfarm Payrolls (chg)': '비농업 고용',
    'Unemployment Rate': '실업률',
    'Avg Hourly Earnings MoM': '시간당 임금',
    'Industrial Production MoM': '산업생산',
    'Durable Goods Orders MoM': '내구재 주문',
    'New Home Sales': '신규주택 판매',
    'Existing Home Sales': '기존주택 판매',
    'Real GDP Growth QoQ (ann.)': '실질 GDP 성장률',
    'Retail Sales MoM': '소매판매',
    'Michigan Consumer Sentiment': '미시간대 소비자심리',
    'CPI YoY': '소비자물가 전년비',
    'CPI MoM': '소비자물가 전월비',
    'Core CPI YoY': '근원 소비자물가 전년비',
    'Core CPI MoM': '근원 소비자물가 전월비',
    'PPI Final Demand MoM': '생산자물가',
    'PCE Price Index YoY': 'PCE 물가 전년비',
    'Core PCE YoY': '근원 PCE 전년비',
    'Michigan 1-Yr Inflation Exp': '미시간대 1년 기대인플레',
}

# Direction is the polarity-adjusted read, never the raw z. The 2026-08-17 brief printed
# raw z for jobless claims and called a falling number "나쁜 방향" — the sign convention
# is a trap, so the writer is handed a verdict instead of a number to interpret.
AXIS_LABELS_KO = {'Labor': '고용', 'Activity': '생산·활동',
                  'Consumption': '소비', 'Inflation': '물가'}

# Growth axes read good/bad; the inflation axis reads hot/cold. Sharing one vocabulary
# would make "개선" ambiguous on the price side — the same class of trap as printing a
# raw z and asking the writer to remember the sign convention.
DIRECTION_WORDS = {
    'growth': {1: '개선', -1: '악화', 0: '보합'},
    'inflation': {1: '재가속', -1: '둔화', 0: '교착'},
}

_KO_NUM = ('영', '하나', '둘', '셋', '넷', '다섯', '여섯', '일곱', '여덟', '아홉', '열')

DIRECTION_CUT = 0.25          # below this an indicator is going nowhere
STRENGTH_BANDS = ((1.0, '뚜렷'), (0.5, '완만'))
MAX_LEADERS = 3

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
    primary = [r for r in out if r['tier'] <= 1]
    secondary = [r for r in out if r['tier'] > 1][:MAX_SECONDARY_RELEASES]
    return primary + secondary


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


def describe(signed_z, axis='Labor'):
    """Polarity-adjusted score -> (direction, strength) in words, per axis vocabulary."""
    words = DIRECTION_WORDS['inflation' if axis == 'Inflation' else 'growth']
    if signed_z is None:
        return None, None
    if abs(signed_z) < DIRECTION_CUT:
        return words[0], '미미'
    direction = words[1] if signed_z > 0 else words[-1]
    for cut, word in STRENGTH_BANDS:
        if abs(signed_z) >= cut:
            return direction, word
    return direction, '미미'


def _ko_count(n):
    return _KO_NUM[n] if 0 <= n < len(_KO_NUM) else str(n)


def breadth_phrase(rows, axis):
    """Breadth without making the reader parse a ratio: 「일곱 중 다섯이 개선」."""
    scored = [r for r in rows if r['axis'] == axis and r['signed_z'] is not None]
    if not scored:
        return None
    mean = sum(r['signed_z'] for r in scored) / len(scored)
    direction, _ = describe(mean, axis)
    words = DIRECTION_WORDS['inflation' if axis == 'Inflation' else 'growth']
    if direction == words[0]:                       # axis is going nowhere
        up = sum(1 for r in scored if r['signed_z'] > 0)
        return f'{_ko_count(len(scored))} 중 {_ko_count(up)}이 {words[1]}, 나머지는 반대'
    # Count support for the verdict the badge shows, never against it — otherwise the
    # strip reads "물가 둔화 · 여덟 중 다섯이 재가속" and contradicts itself at a glance.
    want = 1 if direction == words[1] else -1
    count = sum(1 for r in scored if (r['signed_z'] > 0) == (want > 0))
    particle = '만' if count * 2 < len(scored) else '이'
    return f'{_ko_count(len(scored))} 중 {_ko_count(count)}{particle} {direction}'


def _axis_summary(rows):
    """Per-axis verdict a reader can act on: which way, how broadly, driven by what."""
    out = {}
    for axis, ko in AXIS_LABELS_KO.items():
        members = [r for r in rows if r['axis'] == axis]
        scored = [r for r in members if r['signed_z'] is not None]
        mean = _axis_mean(rows, axis)
        direction, strength = describe(mean, axis)
        leaders = sorted(scored, key=lambda r: -abs(r['signed_z']))[:MAX_LEADERS]
        out[axis] = {
            'label_ko': ko,
            'score': round(mean, _R3) if mean is not None else None,
            'direction': direction,
            'strength': strength,
            'breadth_ko': breadth_phrase(rows, axis),
            'improving': sum(1 for r in scored if r['signed_z'] > 0),
            'total': len(scored),
            'leaders': [{'label_ko': r['label_ko'], 'name': r['name'],
                         'direction': r['direction'], 'strength': r['strength'],
                         'actual': r['actual'], 'previous': r.get('previous')}
                        for r in leaders],
        }
    return out


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
        signed = None if z is None else round(pol * z, _R3)
        direction, strength = describe(signed, axis)
        rows.append({
            'name': name,
            'label_ko': LABELS_KO.get(name, name),
            'axis': axis,
            'direction': direction,
            'strength': strength,
            'polarity': pol,
            'window': window,
            'momentum_z': z,
            'signed_z': signed,
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
        'axis_summary': _axis_summary(rows),
        'axis_scores': {a: (round(_axis_mean(rows, a), _R3)
                            if _axis_mean(rows, a) is not None else None)
                        for a in GROWTH_AXES + INFLATION_AXES},
        'indicators': rows,
        'new_releases': releases,
        'headline_releases': _headline_releases(rows, releases),
        'last_seen': seen_now,
    }
