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
    # 2026-11-08 Census 4. 무역수지는 「명목 무역수지 모멘텀」이다 — 적자가 줄면 +.
    'Housing Starts': (1, 3),
    'Trade Balance': (1, 3),
    'Construction Spending MoM': (1, 3),
    'Factory Orders MoM': (1, 3),
    # anatomy 행(점수 밖). 표의 「직전 대비」 극성만 쓴다.
    'Philly Fed Manufacturing': (1, 3),
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
    # 2026-11-06: the old newsroom URL is a 404 — the release is reached by following
    # 「Read the full news release」 from this page (us.release_resolve). PCE·GDP stay on
    # BEA's landing pages as *landing* URLs; the dated release comes off BEA's RSS feed.
    'existing-home-sales': (2, 'NAR', '기존주택 판매',
                            'https://www.nar.realtor/research-and-statistics/housing-statistics/existing-home-sales'),
    'michigan': (2, 'U. Michigan', '미시간대 소비자심리', 'https://www.sca.isr.umich.edu/'),
    # 2026-11-08 (A단계) — Census 4 + 필라델피아 연은. 필라는 달마다 주소가 바뀐다
    # (mbos-YYYY-MM, us.release_resolve 가 기준월로 만든다). 여기 URL 은 출발점이다.
    'housing-starts': (2, 'Census', '주택착공',
                       'https://www.census.gov/construction/nrc/pdf/newresconst.pdf'),
    'trade-balance': (2, 'Census·BEA', '무역수지',
                      'https://www.census.gov/foreign-trade/Press-Release/current_press_release/ft900.pdf'),
    'construction-spending': (2, 'Census', '건설지출',
                              'https://www.census.gov/construction/c30/pdf/release.pdf'),
    'factory-orders': (2, 'Census', '공장주문',
                       'https://www.census.gov/manufacturing/m3/prel/pdf/s-i-o.pdf'),
    'philly-fed': (2, 'Philadelphia Fed', '필라델피아 연은 제조업 경기',
                   'https://www.philadelphiafed.org/surveys-and-data/regional-economic-analysis/'
                   'manufacturing-business-outlook-survey'),
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
    'Housing Starts': 'housing-starts', 'Trade Balance': 'trade-balance',
    'Construction Spending MoM': 'construction-spending',
    'Factory Orders MoM': 'factory-orders',
    'Philly Fed Manufacturing': 'philly-fed',
}

# 공장주문 발표(전체 보고서)는 같은 달 내구재 주문을 수정해 다시 낸다. 두 행이 같은 날
# 같은 기준월로 새로 나오면 그것은 공장주문 날이다 — 내구재는 공장주문 블록 안에서
# 「수정」으로 다룬다. 기준월이 다르면 내구재 속보치이고 따로 쓴다(codex 1회 #4).
MERGE_INTO = {'Durable Goods Orders MoM': ('Factory Orders MoM', 'factory-orders')}
FIXED_PRIMARY = {'factory-orders': 'Factory Orders MoM'}

# What actually moved underneath the headline lives in `us.anatomy` since 2026-11-08 —
# a component is printed only when FRED (as of the release date) and the agency's own
# text agree on it. The old FRED-only list here had no round check and no second source.

# Tier-1 prints are never dropped. The cap on the context releases exists only for the
# first run — no book, so every indicator reads as new and the collector would chase a
# dozen press releases (0f5c60d2). With a book in hand a day's releases are what the
# economy published and all of them get a block (2026-11-08 사용자 지시 「하루 최대 2개
# 정할 이유 없어」). The book state is passed in explicitly: absent, corrupt and empty
# books are all 「first run」, and only `ok` lifts the cap (codex 1회 #3).
MAX_SECONDARY_RELEASES = 2
BOOK_STATES = ('absent', 'corrupt', 'empty', 'ok')

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
    'Housing Starts': '주택착공',
    'Trade Balance': '무역수지',
    'Construction Spending MoM': '건설지출',
    'Factory Orders MoM': '공장주문',
    'Philly Fed Manufacturing': '필라델피아 연은 제조업지수',
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

# 「직전 대비」 칸의 어휘 (2026-09-23). 표가 Actual/Previous 옆에 모멘텀 판정만 붙여
# 두자 +0.58% → +1.08% 인 내구재가 「악화」로 읽혔다 — 판정은 앞 3개월 평균과 최근
# 3개월 평균을 견준 것이었다. 두 비교를 나란히 싣는다. 물가 쪽은 일부러 추세 어휘
# (재가속/둔화/교착)와 다른 말을 쓴다 — 같은 말이면 두 열이 같은 비교로 읽힌다.
VS_PREV_WORDS = {
    'growth': {1: '개선', -1: '악화', 0: '보합'},
    'inflation': {1: '상승', -1: '하락', 0: '보합'},
}

# 계약이 바뀌면 올린다. 게이트는 이보다 낮은 파일의 추세 칸을 믿지 않는다.
SCHEMA = 2

TREND_NOTE_KO = ('직전 대비는 Actual을 Previous와 비교한 것이고, 추세는 최근 3개월 평균을 '
                 '그 앞 3개월 평균과 비교한 것입니다(주간 실업수당 청구는 4주 평균끼리). '
                 '추세의 세기는 그 지표가 평소 움직이는 폭에 견준 크기이고, 작은 변화는 '
                 '보합으로 봅니다. 분기 지표인 GDP는 두 비교가 같은 숫자를 보므로 직전 '
                 '대비만 싣습니다.')

_WINDOW_KO = {3: '3개월 평균', 4: '4주 평균'}

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


def _month(date):
    """'YYYY-MM-..' -> 연·월 일련번호. 월간 시계열의 이웃·1년 전을 날짜로 찾는 데 쓴다."""
    return int(date[:4]) * 12 + int(date[5:7]) - 1


def transform_pairs(vals, tf):
    """Raw (date, value) history -> [(date, transformed)], **날짜로 맞춘다**.

    행 위치로 1칸·12칸 뒤를 집으면 한 달이 통째로 빠진 시계열에서 두 달·13개월 변화가
    그 이름으로 찍힌다 — 2025-10 CPI(셧다운으로 미발표) 때문에 2026-08 CPI YoY 가
    BLS 3.4% 대신 3.71% 로 나갔다. 비교 대상 달이 없으면 그 달은 만들지 않는다.
    """
    pairs = [(d, float(v)) for d, v in vals or []]
    if tf == 'level':
        return pairs
    if tf in ('mom_pct', 'mom_diff'):
        out = []
        for (d0, x0), (d1, x1) in zip(pairs, pairs[1:]):
            if _month(d1) - _month(d0) != 1:
                continue
            if tf == 'mom_diff':
                out.append((d1, x1 - x0))
            elif x0:
                out.append((d1, (x1 / x0 - 1) * 100))
        return out
    if tf == 'yoy_pct':
        by_month = {_month(d): x for d, x in pairs}
        out = []
        for d, x in pairs:
            base = by_month.get(_month(d) - 12)
            if base:
                out.append((d, (x / base - 1) * 100))
        return out
    raise ValueError(tf)


def transform_series(vals, tf):
    """Raw (date, value) history -> the transformed series the dashboard prints."""
    return [v for _, v in transform_pairs(vals, tf)]


def momentum(values, window):
    """Mean of the last `window` observations minus the mean of the `window` before."""
    if values is None or len(values) < 2 * window or window < 1:
        return None
    recent = values[-window:]
    prior = values[-2 * window:-window]
    return sum(recent) / window - sum(prior) / window


def block_means(values, window):
    """(앞 블록 평균, 최근 블록 평균) — momentum() 이 빼는 바로 그 두 수."""
    if values is None or len(values) < 2 * window or window < 1:
        return None
    return (sum(values[-2 * window:-window]) / window, sum(values[-window:]) / window)


def vs_prev(name, axis, actual, previous):
    """표에 찍힌 두 수(Actual vs Previous)의 극성 반영 비교. 둘 중 하나라도 없으면 None."""
    if actual is None or previous is None:
        return None
    words = VS_PREV_WORDS['inflation' if axis == 'Inflation' else 'growth']
    diff = float(actual) - float(previous)
    if diff == 0:
        return words[0]
    sign = 1 if diff > 0 else -1
    if axis != 'Inflation':
        sign *= polarity_for(name)[0]
    return words[sign]


def window_label(window):
    return _WINDOW_KO.get(window, f'{window}기 평균')


def fmt_value(value, units, transform):
    """추세 칸의 평균값 표기. 변화량(MoM·차분)만 부호를 붙인다."""
    signed = transform in ('mom_pct', 'mom_diff')
    if units == '%':
        return f'{value:+.2f}%' if signed else f'{value:.2f}%'
    if units == 'K':
        return f'{value:+,.0f}K' if signed else f'{value:,.0f}K'
    if abs(value) >= 1000:
        return f'{value / 1000:+,.0f}K' if signed else f'{value / 1000:,.0f}K'
    return f'{value:+.1f}' if signed else f'{value:.1f}'


def trend_cell(direction, strength, window, prior, recent, units, transform):
    """「추세」 칸에 그대로 찍을 문자열. 판정이 없으면 None(칸은 「—」).

    창이 한 관측(GDP)이면 None — 평균 비교가 곧 직전 대비와 같은 두 수인데 판정만
    임계값 때문에 갈려, 「보합 · 2.10% → 1.50%」 옆에 「악화」가 서게 된다.
    """
    if direction is None or prior is None or recent is None or window < 2:
        return None
    word = direction if strength in (None, '미미') and direction in ('보합', '교착') \
        else f'{direction}({strength})'
    return (f'{word} · {window_label(window)} '
            f'{fmt_value(prior, units, transform)} → {fmt_value(recent, units, transform)}')


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


def _headline_releases(rows, releases, roles=None, capped=True):
    """New prints grouped by the document that announced them, most market-moving first.

    `roles` maps each new name to `scored` or `anatomy`; a release is `scored` when any
    of its new prints is. `capped` keeps the first-run cap on tier-2 releases.
    """
    wanted = set(releases)
    new = [r for r in rows if r['name'] in wanted]
    by_name = {r['name']: r for r in new}
    grouped = {}
    for r in new:
        key = INDICATOR_RELEASE.get(r['name']) or release_key(r['name'])
        target = MERGE_INTO.get(r['name'])
        if target and target[0] in by_name and \
                by_name[target[0]].get('ref_period') == r.get('ref_period'):
            key = target[1]
        grouped.setdefault(key, []).append(r)

    roles = roles or {}
    out = []
    for key, items in grouped.items():
        tier, agency, label, url = RELEASES.get(key, (3, None, items[0]['name'], None))
        ranked = sorted(items, key=lambda r: -abs(r['signed_z'] or 0.0))
        fixed = FIXED_PRIMARY.get(key)
        primary = fixed if fixed in {r['name'] for r in items} else ranked[0]['name']
        role = ('scored' if any(roles.get(r['name'], 'scored') == 'scored' for r in items)
                else 'anatomy')
        out.append({
            'key': key, 'label': label, 'tier': tier, 'agency': agency, 'url': url,
            'role': role,
            'primary': primary,
            'max_abs_z': abs(ranked[0]['signed_z'] or 0.0),
            'indicators': [{'name': r['name'], 'axis': r['axis'], 'actual': r['actual'],
                            'previous': r.get('previous'), 'ref_period': r['ref_period'],
                            'momentum_z': r['momentum_z'],
                            'fred_id': r.get('fred_id'), 'transform': r.get('transform'),
                            'units': r.get('units')} for r in items],
        })
    out.sort(key=lambda r: (r['tier'], -r['max_abs_z']))
    primary = [r for r in out if r['tier'] <= 1]
    secondary = [r for r in out if r['tier'] > 1]
    if capped:
        secondary = secondary[:MAX_SECONDARY_RELEASES]
    return primary + secondary


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


def _subj(n):
    return '가' if n == 1 else '이'      # 하나가 · 둘이


def _topic(n):
    return '는' if n == 1 else '은'      # 하나는 · 둘은


def breadth_counts(rows, axis):
    """축 판정을 지표별 판정(`describe`, 표의 추세 열과 같은 임계)으로 센다.

    부호만 세면 표에서 「교착」인 지표까지 둔화로 셌다 — 2026-10-13 발행본은 스트립에
    「8개 중 8개」, 표에는 미시간 기대인플레 「교착」이 나란히 실렸다(외부 평가 지적).
    support = 축 판정과 같은 방향, flat = 보합·교착, against = 반대 방향. 축 판정 자체가
    보합이면 support 는 0 이고 up/down 으로 나눠 센다.
    """
    scored = [r for r in rows if r['axis'] == axis and r['signed_z'] is not None]
    if not scored:
        return None
    words = DIRECTION_WORDS['inflation' if axis == 'Inflation' else 'growth']
    mean = sum(r['signed_z'] for r in scored) / len(scored)
    direction, _ = describe(mean, axis)
    labels = [describe(r['signed_z'], axis)[0] for r in scored]
    up = labels.count(words[1])
    down = labels.count(words[-1])
    flat = labels.count(words[0])
    if direction == words[0]:
        support, against = 0, 0
    else:
        support = up if direction == words[1] else down
        against = down if direction == words[1] else up
    return {'direction': direction, 'total': len(scored), 'support': support,
            'flat': flat, 'against': against, 'up': up, 'down': down}


def breadth_phrase(rows, axis):
    """Breadth without making the reader parse a ratio: 「일곱 중 다섯이 개선」.

    셈은 `breadth_counts` 하나에서 나온다 — 스트립 숫자와 문구와 표가 같은 판정을 본다.
    """
    c = breadth_counts(rows, axis)
    if c is None:
        return None
    words = DIRECTION_WORDS['inflation' if axis == 'Inflation' else 'growth']
    n = _ko_count(c['total'])
    if c['direction'] == words[0]:                     # axis is going nowhere
        parts = []
        if c['up']:
            parts.append(f"{_ko_count(c['up'])}{_subj(c['up'])} {words[1]}")
        if c['down']:
            parts.append(f"{_ko_count(c['down'])}{_subj(c['down'])} {words[-1]}")
        if c['flat']:
            parts.append(f"{_ko_count(c['flat'])}{_topic(c['flat'])} {words[0]}")
        return f"{n} 중 " + ', '.join(parts)
    # Count support for the verdict the badge shows, never against it — otherwise the
    # strip reads "물가 둔화 · 여덟 중 다섯이 재가속" and contradicts itself at a glance.
    k = c['support']
    particle = '만' if k * 2 < c['total'] else _subj(k)
    out = f"{n} 중 {_ko_count(k)}{particle} {c['direction']}"
    if c['flat']:
        out += f", {_ko_count(c['flat'])}{_topic(c['flat'])} {words[0]}"
    if c['against']:
        out += f", {_ko_count(c['against'])}{_topic(c['against'])} 반대"
    return out


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
            # 스트립 「N개 중 K개」의 K — breadth_ko 와 같은 셈(`breadth_counts`).
            'support': (breadth_counts(rows, axis) or {}).get('support'),
            'improving': sum(1 for r in scored if r['signed_z'] > 0),
            'total': len(scored),
            'leaders': [{'label_ko': r['label_ko'], 'name': r['name'],
                         'direction': r['direction'], 'strength': r['strength'],
                         'actual': r['actual'], 'previous': r.get('previous')}
                        for r in leaders],
        }
    return out


# ── 원천 미발표로 빠진 지표(2026-11-17 사용자 승인 조건 7·8) ─────────────────────────────
# 축 점수는 「있는 행」의 평균이다 — 빠진 지표가 있는 축을 온전한 점수와 같게 보이면 안 된다(coverage), 그리고 그 지표가
# 있었다면 판단이 달라질 수 있는 날은 자동으로 발행하지 않는다(sensitivity). 추정치·전월값으로 채우지 않는다.
#
# 점수(자기 모멘텀의 표준편차 단위)에는 코드상 위·아래 한계가 없다 — 그래서 「양 끝」을 ±SENSITIVITY_Z 로 둔다.
# 2026-10-15~11-16 발행 자료의 모든 지표에서 |점수| 최대는 2.54 였다.
SENSITIVITY_Z = 3.0
EXCLUDED_WHY_KO = '원천 미발표'


def scored_rows(indicators):
    """축 점수에 드는 행 — `compute` 가 점수에 쓰는 것과 같은 기준(scored·도입일 아님)."""
    return [r for r in indicators or [] if isinstance(r, dict)
            and (r.get('role') or 'scored') == 'scored' and not r.get('introduced')]


def axis_verdict(mean, axis):
    """축 평균 → 판단 (방향, 강도, 레짐 다리 -1/0/+1). 레짐 다리는 `us.macro.classify` 와 같은 문턱."""
    from .macro import classify
    direction, strength = describe(mean, axis)
    return [direction, strength, classify(mean)]


def sensitivity(indicators, axis, n_excluded, bound=SENSITIVITY_Z):
    """빠진 지표 n개가 모두 점수 범위의 아래 끝(-bound)·위 끝(+bound)이었다면 이 축의 판단이 지금과 같은가.

    평균은 빠진 값에 대해 단조라 두 경우면 충분하다. 결정적이다 — 자료의 점수와 상수만 쓴다.
    -> {'now', 'low', 'high', 'bound', 'stable'}; 축에 점수가 하나도 없으면 stable 은 False(판단할 수 없다)."""
    zs = [r['signed_z'] for r in scored_rows(indicators)
          if r.get('axis') == axis and isinstance(r.get('signed_z'), (int, float))]
    if not zs or n_excluded <= 0:
        return {'now': None, 'low': None, 'high': None, 'bound': bound, 'stable': bool(zs) and n_excluded <= 0}
    total = len(zs) + n_excluded
    now = axis_verdict(sum(zs) / len(zs), axis)
    low = axis_verdict((sum(zs) - n_excluded * bound) / total, axis)
    high = axis_verdict((sum(zs) + n_excluded * bound) / total, axis)
    return {'now': now, 'low': low, 'high': high, 'bound': bound, 'stable': now == low == high}


# 없는 값의 상태(2026-11-18 사용자 지시 — 「미발표」로 뭉뚱그리지 않는다):
#   not_published  원천 기관이 그 값을 내지 않았다(원천 응답에 그 달 행이 있고 값이 빈칸)
#   not_collected  원천에 그 달 자체가 아직 없거나 우리가 그 범위를 받지 않았다
#   collect_failed 받으려다 실패했다
#   unknown        가를 근거가 없다 — 추정하지 않는다(보류 쪽)
MISSING_STATES = ('not_published', 'not_collected', 'collect_failed', 'unknown')
PREVIOUS_WHY_KO = {'not_published': '미발표', 'not_collected': '미수집', 'collect_failed': '수집 실패',
                   'unknown': '확인 불가'}          # 축 표의 Previous 칸 「—」 옆에 싣는 말
NO_VALUE_WHY_KO = {'not_published': EXCLUDED_WHY_KO, 'not_collected': '원천에 비교 달 없음',
                   'collect_failed': '수집 실패', 'unknown': '비교 달 상태 확인 불가'}


def worst_state(states):
    """여러 달의 상태 → 하나(보수적으로): unknown > collect_failed > not_collected > not_published. 없으면 unknown."""
    for s in ('unknown', 'collect_failed', 'not_collected', 'not_published'):
        if s in states:
            return s
    return 'unknown'


# 축 점수에 쓰이지 않은 까닭 — 수집 상태의 키 접두어와 같은 말(`no_value` 는 econ 쪽 키 `econ:no_value:<이름>`).
WHY_KO = {'no_value': EXCLUDED_WHY_KO,        # 원천에 그 달을 만들 재료가 없다
          'no_score': '이력 부족',             # 행은 있는데 점수를 낼 이력이 모자란다(signed_z 없음)
          'introduced': '새로 들인 지표',       # 들인 날은 점수에서 뺀다(구성 변경이 혼자 축을 움직이지 못하게)
          'no_row': '수집 실패'}               # 행 자체가 없다(받지 못했거나 변환이 터졌다)
WHY_ORDER = ('no_value', 'no_score', 'introduced', 'no_row')


def _josa(word):
    last = (word or ' ')[-1]
    return '은' if '가' <= last <= '힣' and (ord(last) - 0xAC00) % 28 else '는'


def introduced_effect(indicators, axis):
    """들인 날이라 점수에서 뺀 지표는 값과 점수를 안다 — **실제 점수를 넣어 다시 낸 축 판정**과 지금 판정을 견준다
    (모르는 값에 쓰는 양 끝 `sensitivity` 와 다르다). -> {'now', 'with', 'direction_same', 'leg_same', 'strength_same'}
    또는 None(지금 점수가 없거나 들인 지표의 점수를 읽지 못한다 — 판정할 수 없다)."""
    rows = [r for r in indicators or [] if isinstance(r, dict) and (r.get('role') or 'scored') == 'scored'
            and r.get('axis') == axis]
    used = [r['signed_z'] for r in rows if not r.get('introduced') and _has_value(r.get('signed_z'))]
    new = [r for r in rows if r.get('introduced') is True]
    if not used or not new or not all(_has_value(r.get('signed_z')) for r in new):
        return None
    both = used + [r['signed_z'] for r in new]
    now, incl = axis_verdict(sum(used) / len(used), axis), axis_verdict(sum(both) / len(both), axis)
    return {'now': now, 'with': incl, 'direction_same': now[0] == incl[0], 'leg_same': now[2] == incl[2],
            'strength_same': now[1] == incl[1]}


def coverage_phrase(total, used, excluded):
    """글에 싣는 문장 — 「8개 중 6개로 산출, 소비자물가 전년비·근원 소비자물가 전년비는 원천 미발표로 제외」.
    `excluded` = `[{label_ko, why}]`(또는 이름 목록 — 그러면 모두 원천 미발표). 까닭이 여럿이면 까닭마다 한 구절."""
    items = [e if isinstance(e, dict) else {'label_ko': e, 'why': 'no_value'} for e in excluded]
    parts = []
    seen = []
    for e in items:                       # 까닭(독자에게 보이는 말)마다 한 구절, 나온 순서대로
        w = e.get('why_ko') or WHY_KO.get(e.get('why'), EXCLUDED_WHY_KO)
        if w not in seen:
            seen.append(w)
    for w in seen:
        labels = [e['label_ko'] for e in items if (e.get('why_ko') or WHY_KO.get(e.get('why'), EXCLUDED_WHY_KO)) == w]
        last = w[-1]
        ro = '으로' if '가' <= last <= '힣' and (ord(last) - 0xAC00) % 28 not in (0, 8) else '로'
        parts.append(f"{'·'.join(labels)}{_josa(labels[-1])} {w}{ro} 제외")
    return f"{total}개 중 {used}개로 산출, " + ', '.join(parts)


def _has_value(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and x == x and abs(x) != float('inf')


def unused_scored(indicators):
    """행은 있는데 축 점수에 쓰이지 않은 점수 대상 → `[(이름, 축, 까닭)]`.

    `introduced` = 들인 날이라 규칙대로 하루 뺀 것 — **자료의 그 칸(`introduced`)이 참이고, 최신값이 실제로 있고, 점수도
    계산된** 행만(4회차 H3). 값이 없거나 점수가 없는 행은 들인 날이어도 `no_score` 다 — 결측이 「들인 날」로 덮이지 않는다."""
    out = []
    for r in indicators or []:
        if not isinstance(r, dict) or (r.get('role') or 'scored') != 'scored':
            continue
        scored = _has_value(r.get('signed_z'))
        if r.get('introduced') is True and scored and _has_value(r.get('actual')):
            out.append((r.get('name'), r.get('axis'), 'introduced'))
        elif r.get('introduced') or not scored:
            out.append((r.get('name'), r.get('axis'), 'no_score'))
    return out


def with_coverage(mm, excluded, expected=None):
    """`compute` 결과에 축별 산출 범위를 싣는다 — **그 축에 정의된 점수 대상 가운데 실제로 점수에 쓰인 것**이 몇인가.

    `expected` = 정의된 점수 대상 `[(축, 이름)]`(수집기의 ECON 표, 해부 전용 제외). `excluded` = 원천에 최신 달을 만들
    재료가 없어 행을 만들지 못한 지표 `[{name, axis, fred_id, transform, ref_period, lacking}]`(수집기의 no_value).
    쓰이지 않은 것은 **전부** 싣는다(3회차 G2 — 전에는 no_value 만 세어, 행은 있는데 점수가 없는 지표가 가려졌고
    전체 수도 「쓴 수 + 2」였다): no_value / no_score / introduced / no_row. 쓰이지 않은 것이 없는 축은 싣지 않는다.

    `coverage[축] = {total, used, excluded: [{name, label_ko, why, why_ko, …}], phrase_ko, sensitivity}`,
    `axis_summary[축].coverage_ko` = 같은 문장. `expected` 를 모르면(옛 호출) 정의된 수는 「행 + excluded」로 센다."""
    excluded = [e for e in excluded or [] if isinstance(e, dict) and e.get('axis') in AXIS_LABELS_KO]
    rows = [r for r in mm.get('indicators') or [] if isinstance(r, dict) and (r.get('role') or 'scored') == 'scored']
    used_names = {r.get('name') for r in scored_rows(rows) if r.get('signed_z') is not None}
    row_why = {n: why for n, _a, why in unused_scored(rows)}
    by_ex = {e['name']: e for e in excluded}
    if expected is None:
        expected = [(r.get('axis'), r.get('name')) for r in rows] + [(e['axis'], e['name']) for e in excluded]
    out = dict(mm)
    cov = {}
    summary = {k: dict(v) for k, v in (mm.get('axis_summary') or {}).items()}
    for axis in AXIS_LABELS_KO:
        names = []
        for a, n in expected:
            if a == axis and n not in names:
                names.append(n)
        used = [n for n in names if n in used_names]
        items = []
        for n in names:
            if n in used_names:
                continue
            why = 'no_value' if n in by_ex else row_why.get(n, 'no_row')
            item = {'name': n, 'label_ko': LABELS_KO.get(n, n), 'why': why, 'why_ko': WHY_KO[why]}
            if n in by_ex:
                item.update({k: by_ex[n].get(k) for k in ('fred_id', 'transform', 'ref_period', 'lacking')})
                lw = by_ex[n].get('lacking_why')
                if isinstance(lw, dict):
                    # 왜 그 달을 만들 수 없나 — 미발표와 미수집을 가른다. 상태를 모르는 옛 호출은 전과 같은 말
                    item['lacking_why'] = lw
                    item['why_ko'] = NO_VALUE_WHY_KO[worst_state(set(lw.values()))]
            items.append(item)
        if not items:
            continue
        items.sort(key=lambda e: WHY_ORDER.index(e['why']))
        phrase = coverage_phrase(len(names), len(used), items)
        cov[axis] = {'total': len(names), 'used': len(used), 'excluded': items, 'phrase_ko': phrase,
                     'sensitivity': sensitivity(mm.get('indicators'), axis, len(items))}
        if axis in summary:
            summary[axis]['coverage_ko'] = phrase
    if not cov:
        return mm
    out['coverage'] = cov
    out['axis_summary'] = summary
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


def _book_state(last_seen, book_state):
    if book_state is not None:
        if book_state not in BOOK_STATES:
            raise ValueError(f'book_state: {book_state!r}')
        return book_state
    if last_seen is None:
        return 'absent'
    return 'ok' if last_seen else 'empty'


PENDING = 'pending'


def _pending_since(reading):
    """`last_seen` entry ['pending', since] -> since, else None."""
    if isinstance(reading, (list, tuple)) and len(reading) == 2 and reading[0] == PENDING:
        return reading[1]
    return None


def compute(series_by_id, econ_indicators, last_seen=None, book_state=None,
            introduced_new=None, introduced_unknown=None, book_date=None):
    """Full history + today's dashboard rows -> axis scores, diffusion, new releases.

    `last_seen` is yesterday's {name: [ref_period, actual]} carried in macro.json. An
    indicator whose reading is byte-identical to yesterday's did not release today, and
    a day with no releases cannot move the regime.

    2026-11-08 (A단계):

    * `role` on an econ row: `scored` (default) moves the axes; `anatomy` is on the page
      and gets an anatomy block, never a score. `new_releases` is scored prints only —
      the regime gate, the policy gate and the transmission read it — and
      `anatomy_releases` the rest. `headline_releases` is both.
    * `book_state` (absent|corrupt|empty|ok, inferred from `last_seen` when not given)
      decides the first-run cap.
    * A row the book has never seen while the book is `ok` is **introduced**: it is kept
      out of the scores that day, so a composition change cannot move an axis on its
      own, and it is seeded into `last_seen`. It is a release only when the collector
      established that its own release came after the book was written
      (`introduced_new`) — then it is dissected, still unscored.
    * A row missing today keeps yesterday's `last_seen` reading, so a failed fetch does
      not make tomorrow read an unchanged print as new.
    * When the collector could not tell when an introduced row was released
      (`introduced_unknown` — no key, a failed lookup), the row is **not** seeded: it is
      kept as `['pending', since]`, `since` the book date it was first seen against, and
      judged again the next day against that date (codex 구현 1회 #5). `introduced_since`
      in the output gives the date each introduced row is to be compared with.
    """
    state = _book_state(last_seen, book_state)
    seen_before = last_seen or {}
    introduced_new = set(introduced_new or ())
    introduced_unknown = set(introduced_unknown or ())
    rows, releases, anatomy, introduced, seen_now, roles = [], [], [], [], {}, {}
    since_of = {}

    for item in econ_indicators or []:
        name = item.get('name')
        axis = item.get('axis')
        role = item.get('role') or 'scored'
        pol, window = polarity_for(name)
        values = transform_series(series_by_id.get(item.get('fred_id')),
                                  item.get('transform', 'level'))
        z = momentum_z(values, window)
        signed = None if z is None else round(pol * z, _R3)
        direction, strength = describe(signed, axis)
        means = block_means(values, window)
        trend = None if means is None else {
            'window': window, 'label_ko': window_label(window),
            'prior_avg': round(means[0], _R3), 'recent_avg': round(means[1], _R3)}
        pending = _pending_since(seen_before.get(name))
        is_intro = state == 'ok' and (name not in seen_before or pending is not None)
        rows.append({
            'name': name,
            'label_ko': LABELS_KO.get(name, name),
            'axis': axis,
            'role': role,
            'introduced': is_intro,
            'fred_id': item.get('fred_id'),
            'transform': item.get('transform', 'level'),
            'units': item.get('units'),
            'direction': direction,
            'strength': strength,
            'polarity': pol,
            'window': window,
            'momentum_z': z,
            'signed_z': signed,
            'actual': item.get('actual'),
            'previous': item.get('previous'),
            'ref_period': item.get('ref_period'),
            'vs_prev': vs_prev(name, axis, item.get('actual'), item.get('previous')),
            'trend': trend,
            'trend_cell_ko': trend_cell(direction, strength, window,
                                        means and means[0], means and means[1],
                                        item.get('units'), item.get('transform', 'level')),
        })

        seen_now[name] = [item.get('ref_period'), item.get('actual')]
        if is_intro:
            introduced.append(name)
            since_of[name] = pending or book_date
            if name in introduced_unknown:
                seen_now[name] = [PENDING, since_of[name]]
            elif name in introduced_new:
                anatomy.append(name)
                roles[name] = 'anatomy'
            continue
        if last_seen is None or seen_now[name] != (seen_before.get(name) or None):
            if role == 'scored':
                releases.append(name)
            else:
                anatomy.append(name)
            roles[name] = role

    for name, reading in seen_before.items():
        seen_now.setdefault(name, reading)

    shown = set(releases) | set(anatomy)
    for r in rows:
        r['is_new'] = r['name'] in shown

    # Scores see the scored rows the book already knew — never anatomy, never a row on
    # the day it is introduced.
    scored = [r for r in rows if r['role'] == 'scored' and not r['introduced']]
    return {
        'schema': SCHEMA,
        'trend_note_ko': TREND_NOTE_KO,
        'book_state': state,
        'growth_score': _group_score(scored, GROWTH_AXES),
        'inflation_score': _group_score(scored, INFLATION_AXES),
        'growth_diffusion': _diffusion(scored, GROWTH_AXES),
        'inflation_diffusion': _diffusion(scored, INFLATION_AXES),
        'axis_summary': _axis_summary(scored),
        'axis_scores': {a: (round(_axis_mean(scored, a), _R3)
                            if _axis_mean(scored, a) is not None else None)
                        for a in GROWTH_AXES + INFLATION_AXES},
        'indicators': rows,
        'new_releases': releases,
        'anatomy_releases': anatomy,
        'introduced': introduced,
        'introduced_since': since_of,
        'headline_releases': _headline_releases(rows, releases + anatomy, roles,
                                                capped=state != 'ok'),
        'last_seen': seen_now,
    }
