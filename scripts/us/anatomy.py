"""What moved underneath a headline — components both FRED and the agency confirm.

2026-11-08 (A단계, 사용자 지시 「헤드라인만 보지 말고 세부까지 해석」). A component is
usable on the page only when two independent sources agree on it **for this round**:

1. **FRED, as it stood on the release date D.** `fred/release/dates` gives D (the
   latest release of the headline's release id on or before the report date). The
   component's observation for the reference period must have a vintage row that
   *starts* on D — FRED published or revised that value that day. The previous period
   a change is computed against is the value valid on D. A component FRED did not
   touch on D (late load, unchanged revision) is left out: we cannot tell which round
   it belongs to.
2. **The agency's own text.** The verified release (`data/releases/index.json` says ok,
   its identity, period *and* headline value were checked) must carry a sentence that
   binds this component's name to a value in one fixed shape — 「The shelter index rose
   0.4 percent in September」. Each component has its own sentence patterns, written
   against real releases, with the period word in them. Numbers that follow 「average」,
   「since」, 「revised」 or sit in a table never fit a pattern, so they never count.
   All matches must agree; two different values is ambiguity and the component goes.

The value printed is FRED's, rounded to the text's precision. If the two disagree the
component goes — we do not know which is right.

Nothing here touches the network: `fred.py` fetches, `collect_market_data.py` runs
`produce()` (step one), `xcheck_components.py` runs `cross_check()` after the release
texts are in (step two). Design: ../plan.md 「A단계」 tables, codex 설계 검토 1-6회.
"""
import datetime as dt
import math
import re

from .release_text import TRUNCATED

MONTHS = ('January', 'February', 'March', 'April', 'May', 'June', 'July', 'August',
          'September', 'October', 'November', 'December')

UP = ('increased', 'rose', 'edged up', 'ticked up', 'moved up', 'advanced', 'climbed',
      'jumped', 'added', 'gained', 'above')
DOWN = ('decreased', 'fell', 'declined', 'edged down', 'ticked down', 'moved down',
        'dropped', 'lost', 'shed', 'below')
FLAT = ('was unchanged', 'were unchanged')
_VERBS = sorted(UP + DOWN + FLAT, key=len, reverse=True)
DIR = '(?P<dir>' + '|'.join(re.escape(v) for v in _VERBS) + ')'
# A printed number, optionally followed by its scale word. `−` is the Unicode minus.
V = r'(?P<v>[-−]?\d[\d,]*(?:\.\d+)?)(?P<mult> (?:thousand|million|billion))?'
_MULT = {None: 1.0, ' thousand': 1e3, ' million': 1e6, ' billion': 1e9}
# JOLTS and the like: 「changed little at」, 「increased to」.
LEVEL_VERB = (r'(?:(?:was|were) )?(?:little changed|changed little|unchanged|increased|decreased|'
              r'rose|fell|edged up|edged down|declined)(?: to| at)?')
# Inside one sentence: anything but a full stop, except the point of a decimal number.
SENT = r'(?:[^.]|\.(?=\d))'
PHILLY_VERB = (r'(?:rose|fell|declined|increased|decreased|edged up|edged down|moved up|'
               r'moved down|ticked up|ticked down|jumped|dropped|climbed|slipped)'
               r'(?: [\d.]+ points?)? to')


def _idx(noun):
    """BLS index sentence: 「The shelter index rose 0.4 percent in September」 /
    「The index for energy increased 5.2 percent over the month」."""
    n = re.escape(noun)
    return (rf'The (?:{n} index|index for {n}) {DIR}(?: {V} percent)? '
            rf'(?:in {{M}}|over the month)')


def _comp(label, fred_id, transform, patterns, aliases, scale=1.0, unit='%', sign='dir',
          period='same', step=None):
    """One component. `scale`: FRED value x scale = the value in the text's base unit
    (persons, units, dollars). `sign`: dir (verb or explicit +/−), literal (the number's
    own sign — rates, indexes), neg (a deficit). `step`: the text's rounding when the
    printed digits understate it (BLS payroll changes are to the thousand)."""
    return {'label': label, 'fred_id': fred_id, 'transform': transform,
            'patterns': tuple(patterns), 'aliases': tuple(aliases), 'scale': scale,
            'unit': unit, 'sign': sign, 'period': period, 'step': step}


_PH = r'[Tt]he (?:current )?{noun} index' + SENT + '{{0,100}}? ' + PHILLY_VERB + ' ' + V

COMPONENTS = {
    'cpi': (
        _comp('에너지', 'CPIENGSL', 'mom_pct', [_idx('energy')], ('에너지',)),
        _comp('식품', 'CPIUFDSL', 'mom_pct', [_idx('food')], ('식품', '먹거리')),
        _comp('주거비', 'CUSR0000SAH1', 'mom_pct', [_idx('shelter')],
              ('주거비', '주거', 'shelter')),
        _comp('중고차', 'CUSR0000SETA02', 'mom_pct', [_idx('used cars and trucks')],
              ('중고차',)),
        _comp('의료', 'CPIMEDSL', 'mom_pct', [_idx('medical care')], ('의료',)),
        _comp('휘발유', 'CUSR0000SETB01', 'mom_pct', [_idx('gasoline')],
              ('휘발유', '가솔린')),
    ),
    'ppi': (
        _comp('식품·에너지·무역서비스 제외', 'WPSFD49116', 'mom_pct',
              [rf'Prices for final demand less foods, energy, and trade services {DIR} {V} '
               rf'percent in {{M}}',
               rf'[Tt]he index for final demand less foods, energy, and trade services {DIR} '
               rf'{V} percent in {{M}}'],
              ('무역서비스 제외', '식품·에너지·무역서비스 제외', '근원 생산자물가')),
    ),
    'employment': (
        _comp('헬스케어', 'CES6562000101', 'mom_diff',
              [rf'Health care (?P<dir>added|lost|shed) {V} jobs in {{M}}',
               rf'[Ee]mployment in health care {DIR} by {V} in {{M}}'],
              ('헬스케어', '보건의료'), scale=1e3, unit='명', step=1e3),
        _comp('전문·사업서비스', 'USPBS', 'mom_diff',
              [rf'[Ee]mployment in professional and business services {DIR} by {V} in {{M}}',
               rf'[Pp]rofessional and business services (?P<dir>added|lost|shed) {V} jobs '
               rf'in {{M}}'],
              ('전문·사업서비스', '사업서비스'), scale=1e3, unit='명', step=1e3),
        _comp('운수·창고', 'CES4300000001', 'mom_diff',
              [rf'In {{M}}, transportation and warehousing (?P<dir>added|lost|shed) {V} jobs',
               rf'[Ee]mployment in transportation and warehousing {DIR} by {V} in {{M}}'],
              ('운수·창고', '운송·창고'), scale=1e3, unit='명', step=1e3),
        _comp('제조업', 'MANEMP', 'mom_diff',
              [rf'Manufacturing employment (?:continued to trend up|continued to trend down|'
               rf'changed little|was little changed|edged up|edged down) in {{M}} '
               rf'\((?P<sgn>[+−-]){V}\)',
               rf'[Ee]mployment in manufacturing {DIR} by {V} in {{M}}',
               rf'Manufacturing (?P<dir>added|lost|shed) {V} jobs in {{M}}'],
              ('제조업',), scale=1e3, unit='명', step=1e3),
        _comp('경제활동참가율', 'CIVPART', 'level',
              [rf'labor force participation rate, at {V} percent',
               rf'labor force participation rate (?:was|was unchanged at|changed little at|'
               rf'was little changed at|(?:increased|decreased|rose|fell|edged up|edged down|'
               rf'ticked up|ticked down)(?: by 0\.\d percentage point)? to) {V} percent'],
              ('경제활동참가율', '참가율'), sign='literal'),
        _comp('주당 노동시간', 'AWHAETP', 'level',
              [rf'The average workweek for all employees on private nonfarm payrolls '
               rf'(?:remained at|was unchanged at|was|(?:increased|decreased|rose|fell|'
               rf'edged up|edged down|declined|ticked up|ticked down) by 0\.\d hours? to) '
               rf'{V} hours'],
              ('주당 노동시간', '노동시간', '근로시간'), unit='시간', sign='literal'),
    ),
    'claims': (
        _comp('계절조정 전 청구', 'ICNSA', 'level',
              [rf'actual initial claims under state programs, unadjusted, totaled {V} in '
               rf'the week ending {{WE}}'],
              ('계절조정 전', '원계열'), unit='건', sign='literal'),
        _comp('보험 실업률', 'IURSA', 'level',
              [rf'advance seasonally adjusted insured unemployment rate was {V} percent for '
               rf'the week ending {{WE7}}'],
              ('보험 실업률', '피보험 실업률'), sign='literal', period='minus_7d'),
    ),
    'jolts': (
        _comp('채용', 'JTSHIL', 'level',
              [rf'The number and rate of hires {LEVEL_VERB} {V}',
               rf'The number of hires {LEVEL_VERB} {V}'],
              ('채용',), scale=1e3, unit='건', sign='literal'),
        _comp('자발적 이직', 'JTSQUL', 'level',
              [rf'The number of quits {LEVEL_VERB} {V}',
               rf'The number and rate of quits {LEVEL_VERB} {V}'],
              ('자발적 이직', '자발적 퇴직'), scale=1e3, unit='건', sign='literal'),
        _comp('해고', 'JTSLDL', 'level',
              [rf'[Tt]he number and rate of layoffs and discharges {LEVEL_VERB} {V}',
               rf'[Tt]he number of layoffs and discharges {LEVEL_VERB} {V}'],
              ('해고',), scale=1e3, unit='건', sign='literal'),
        _comp('이직률', 'JTSQUR', 'level',
              [rf'The number of quits {SENT}{{0,60}}?, while the rate (?:was |were )?'
               rf'(?:little changed|changed little|unchanged|increased|decreased|rose|fell|'
               rf'edged up|edged down)(?: to| at)? {V} percent',
               rf'The number and rate of quits {LEVEL_VERB} [\d.]+ million and {V} percent'],
              ('이직률', '자발적 이직률'), sign='literal'),
    ),
    'industrial-production': (
        _comp('제조업 생산', 'IPMAN', 'mom_pct',
              [rf'Manufacturing output {DIR}(?: {V} percent)? in {{M}}',
               rf'[Tt]he index for manufacturing {DIR}(?: {V} percent)? in {{M}}'],
              ('제조업',)),
        _comp('광업', 'IPMINE', 'mom_pct',
              [rf'In {{M}}, mining output {DIR}(?: {V} percent)?',
               rf'[Mm]ining output {DIR}(?: {V} percent)? in {{M}}'],
              ('광업',)),
        _comp('유틸리티', 'IPUTIL', 'mom_pct',
              [rf'[Tt]he index for utilities {DIR}(?: {V} percent)?(?:,| in {{M}})',
               rf'[Tt]he output of utilities {DIR}(?: {V} percent)? in {{M}}'],
              ('유틸리티',)),
        _comp('설비가동률', 'TCU', 'level',
              [rf'Capacity utilization (?:was unchanged at|was|(?:rose|fell|increased|'
               rf'decreased|declined|edged up|edged down|moved up|moved down|ticked up|'
               rf'ticked down)(?: [\d.]+ percentage points?)? to) {V} percent'],
              ('가동률',), sign='literal'),
    ),
    'durable-goods': (
        _comp('운송 제외', 'ADXTNO', 'mom_pct',
              [rf'Excluding transportation, new orders {DIR}(?: {V} percent)?'],
              ('운송 제외', '수송 제외', '운송장비 제외')),
        _comp('국방 제외', 'ADXDNO', 'mom_pct',
              [rf'Excluding defense, new orders {DIR}(?: {V} percent)?'],
              ('국방 제외', '방산 제외')),
    ),
    'new-home-sales': (
        _comp('재고 개월 수', 'MSACSR', 'level',
              [rf'This represents a supply of {V} months at the current sales rate'],
              ('개월', '재고 소진'), unit='개월', sign='literal'),
        _comp('판매가격 중위값', 'MSPNHSUS', 'level',
              [rf'The median sales price of new houses sold in {{M}} {{Y}} was \${V}'],
              ('중위', '중간값'), unit='달러', sign='literal'),
        _comp('판매 대기 재고', 'HNFSEPUSSA', 'level',
              [rf'The seasonally-adjusted estimate of new houses for sale at the end of '
               rf'{{M}} {{Y}} was {V}'],
              ('판매 대기', '매물', '판매용 재고'), scale=1e3, unit='채', sign='literal'),
    ),
    'housing-starts': (
        _comp('단독주택 착공', 'HOUST1F', 'level',
              [rf'Single-family housing starts in {{M}} were at a rate of {V}'],
              ('단독주택',), scale=1e3, unit='채', sign='literal'),
        _comp('완공', 'COMPUTSA', 'level',
              [rf'Privately-owned housing completions in {{M}} were at a seasonally adjusted '
               rf'annual rate of {V}'],
              ('완공',), scale=1e3, unit='채', sign='literal'),
    ),
    'trade-balance': (
        _comp('수출', 'BOPTEXP', 'level', [rf'{{M}} exports were \${V}'], ('수출',),
              scale=1e6, unit='$B', sign='literal'),
        _comp('수입', 'BOPTIMP', 'level', [rf'{{M}} imports were \${V}'], ('수입',),
              scale=1e6, unit='$B', sign='literal'),
        _comp('상품수지', 'BOPGTB', 'level',
              [rf'(?:a decrease|an increase) in the goods deficit of \$[\d.]+ billion to \${V}'],
              ('상품수지', '상품 적자', '재화 적자'), scale=1e6, unit='$B', sign='neg'),
    ),
    'construction-spending': (
        _comp('민간 건설', 'TLPRVCONS', 'mom_pct',
              [rf'Spending on private construction was at a seasonally adjusted annual rate '
               rf'of \$[\d,.]+ billion, {V} percent \(±[\d.]+ percent\)\*? (?P<dir>above|below)'],
              ('민간',)),
        _comp('주거용(민간)', 'PRRESCONS', 'mom_pct',
              [rf'Residential construction was at a seasonally adjusted annual rate of '
               rf'\$[\d,.]+ billion in {{M}}, {V} percent \(±[\d.]+ percent\)\*? '
               rf'(?P<dir>above|below)'],
              ('주거용',)),
        _comp('비주거용(민간)', 'PNRESCONS', 'mom_pct',
              [rf'Nonresidential construction was at a seasonally adjusted annual rate of '
               rf'\$[\d,.]+ billion in {{M}}, {V} percent \(±[\d.]+ percent\)\*? '
               rf'(?P<dir>above|below)'],
              ('비주거용',)),
        _comp('공공 건설', 'TLPBLCONS', 'mom_pct',
              [rf'seasonally adjusted annual rate of public construction spending was '
               rf'\$[\d,.]+ billion, {V} percent \(±[\d.]+ percent\)\*? (?P<dir>above|below)'],
              ('공공',)),
    ),
    'factory-orders': (
        _comp('출하', 'AMTMVS', 'mom_pct',
              [rf'Shipments, [^.$]{{0,60}}?(?P<dir>increased|decreased) \$[\d.,]+ billion or '
               rf'{V} percent'],
              ('출하',)),
        _comp('재고', 'AMTMTI', 'mom_pct',
              [rf'Inventories, [^.$]{{0,60}}?(?P<dir>increased|decreased) \$[\d.,]+ billion or '
               rf'{V} percent'],
              ('재고',)),
        _comp('미충족 주문', 'AMTMUO', 'mom_pct',
              [rf'Unfilled orders, [^.$]{{0,60}}?(?P<dir>increased|decreased) \$[\d.,]+ billion '
               rf'or {V} percent'],
              ('미충족', '수주잔고', '미처리 주문')),
        _comp('내구재 주문(수정)', 'DGORDER', 'mom_pct',
              [rf'New orders for manufactured durable goods in {{M}}, [^.$]{{0,60}}?'
               rf'(?P<dir>increased|decreased) \$[\d.,]+ billion or {V} percent'],
              ('내구재',)),
    ),
    'philly-fed': (
        _comp('신규주문', 'NOCDFSA066MSFRBPHI', 'level',
              [_PH.format(noun='new orders')], ('신규주문', '신규 주문'), unit='', sign='literal'),
        _comp('출하', 'SHCDFSA066MSFRBPHI', 'level',
              [_PH.format(noun='shipments')], ('출하',), unit='', sign='literal'),
        _comp('고용', 'NECDFSA066MSFRBPHI', 'level',
              [_PH.format(noun='employment')], ('고용',), unit='', sign='literal'),
        _comp('지불가격', 'PPCDFSA066MSFRBPHI', 'level',
              [_PH.format(noun='prices paid')], ('지불가격', '지불 가격', '투입가격', '투입 가격'),
              unit='', sign='literal'),
        _comp('수취가격', 'PRCDFSA066MSFRBPHI', 'level',
              [_PH.format(noun='prices received')], ('수취가격', '수취 가격', '판매가격'),
              unit='', sign='literal'),
        _comp('6개월 뒤 전망', 'GAFDFSA066MSFRBPHI', 'level',
              [r'[Tt]he diffusion index for future general activity' + SENT + '{0,60}? '
               + PHILLY_VERB + ' ' + V],
              ('6개월 뒤', '미래 활동', '향후 6개월'), unit='', sign='literal'),
    ),
}

# Releases whose verified text may not be committed to this public repository (2026-11-08:
# the Philadelphia Fed's pages say 「All rights reserved」). Their text is read inside the
# Actions job for the cross-check and never published.
PRIVATE_TEXT = frozenset({'philly-fed'})


# ----------------------------------------------------------------- periods

def _date(s):
    try:
        return dt.date.fromisoformat(str(s)[:10])
    except ValueError:
        return None


def period_dates(ref_period, transform, period='same'):
    """-> (current observation date, previous observation date | None) as ISO strings."""
    d = _date(ref_period)
    if d is None:
        return None, None
    if period == 'minus_7d':
        d = d - dt.timedelta(days=7)
    cur = d.isoformat()
    if transform not in ('mom_pct', 'mom_diff'):
        return cur, None
    y, m = (d.year, d.month - 1) if d.month > 1 else (d.year - 1, 12)
    return cur, dt.date(y, m, 1).isoformat()


def fill(template, ref_period):
    """Put the release's period words into a pattern: {M} month, {Y} year, {WE} and {WE7}
    the week-ending dates (「October 31」) of the reference week and the one before."""
    d = _date(ref_period)
    if d is None:
        return None
    w7 = d - dt.timedelta(days=7)
    return (template.replace('{M}', MONTHS[d.month - 1]).replace('{Y}', str(d.year))
            .replace('{WE7}', f'{MONTHS[w7.month - 1]} {w7.day}')
            .replace('{WE}', f'{MONTHS[d.month - 1]} {d.day}'))


# ------------------------------------------------------------- FRED round

def at(rows, obs_date, day):
    """The vintage row for `obs_date` valid on `day`, or None."""
    for r in rows or ():
        if r.get('date') != obs_date:
            continue
        if (r.get('realtime_start') or '') <= day <= (r.get('realtime_end') or '9999-12-31'):
            return r
    return None


def round_value(rows, ref_period, release_date, transform, period='same'):
    """-> (value | None, reason, detail). The component as FRED published it on D.

    `rows` are `output_type=1` vintage rows (date, realtime_start, realtime_end, value)
    covering D−40..D. The current observation must have a row **starting** on D; the
    previous one (for a change) is whatever was valid on D, and the detail records
    whether it too was revised that day.
    """
    cur_d, prev_d = period_dates(ref_period, transform, period)
    if cur_d is None or not release_date:
        return None, 'no_period', {}
    cur = at(rows, cur_d, release_date)
    if cur is None or cur.get('value') is None:
        return None, 'no_value_on_release_date', {}
    if cur.get('realtime_start') != release_date:
        return None, 'not_published_on_release_date', {'since': cur.get('realtime_start')}
    detail = {'observation': cur_d, 'changed': ['current']}
    if prev_d is None:
        return cur['value'], 'ok', detail
    prev = at(rows, prev_d, release_date)
    if prev is None or prev.get('value') is None:
        return None, 'no_previous_on_release_date', detail
    if prev.get('realtime_start') == release_date:
        detail['changed'].append('previous')
    if transform == 'mom_diff':
        return cur['value'] - prev['value'], 'ok', detail
    if not prev['value']:
        return None, 'zero_base', detail
    return (cur['value'] / prev['value'] - 1) * 100, 'ok', detail


def headline_on_release_date(rows, ref_period, release_date):
    """Did FRED publish the headline's reference observation on D? -> (ok, reason)."""
    cur_d, _ = period_dates(ref_period, 'level')
    row = at(rows, cur_d, release_date) if cur_d else None
    if row is None:
        return False, 'headline_missing_on_release_date'
    if row.get('realtime_start') != release_date:
        return False, 'headline_not_published_on_release_date'
    return True, 'ok'


# -------------------------------------------------------------- text match

_SPACE = re.compile(r'\s+')


def prose(text):
    """Flattened text, cut at the truncation marker (nothing after it is evidence)."""
    t = text or ''
    cut = t.find(TRUNCATED)
    if cut >= 0:
        t = t[:cut]
    return _SPACE.sub(' ', t)


def _number(m):
    raw = m.group('v').replace('−', '-').replace(',', '')
    mult = _MULT.get(m.groupdict().get('mult'), 1.0)
    try:
        val = float(raw)
    except ValueError:
        return None, None
    # The last printed digit is the precision — 「$280 billion」 is to the billion, not the
    # ten billion (codex 구현 1회 #2). A release that rounds coarser than it prints (BLS
    # payroll changes, to the thousand) says so with the component's `step`.
    precision = 10 ** -len(raw.split('.')[1]) if '.' in raw else 1
    return val * mult, precision * mult


def _signed(m, value, mode):
    """The text's value with the sign the sentence gives it, or None when it gives none."""
    g = m.groupdict()
    verb = (g.get('dir') or '').strip()
    if verb in FLAT:
        return 0.0
    if mode == 'literal':
        return value
    if mode == 'neg':
        return -abs(value)
    if value < 0:
        return value                          # 「(−19,000)」 already carries it
    sgn = g.get('sgn')
    if sgn:
        return value if sgn == '+' else -value
    if verb in UP:
        return value
    if verb in DOWN:
        return -value
    return None


def text_value(comp, text, ref_period):
    """-> (value in the text's base unit | None, precision, reason)."""
    body = prose(text)
    found = []
    for tpl in comp['patterns']:
        pat = fill(tpl, ref_period)
        if pat is None:
            return None, None, 'no_period'
        for m in re.finditer(pat, body):
            if m.groupdict().get('v') is None:
                if (m.groupdict().get('dir') or '').strip() in FLAT:
                    found.append((0.0, None))
                continue
            value, precision = _number(m)
            if value is None:
                continue
            signed = _signed(m, value, comp['sign'])
            if signed is None:
                return None, None, 'sign_unclear'
            found.append((signed, precision))
    if not found:
        return None, None, 'not_in_text'
    values = {round(v, 9) for v, _ in found}
    if len(values) > 1:
        return None, None, 'ambiguous_in_text'
    value = found[0][0]
    precs = [p for _, p in found if p is not None]
    precision = max(precs) if precs else None
    return value, precision, 'ok'


def agrees(fred_base, text_base, precision, step=None):
    """Does FRED's value print as the text's figure at the text's precision?"""
    if precision is None:                       # 「was unchanged」: zero at one decimal
        precision = 0.1
    if step:
        precision = max(precision, step)
    return abs(fred_base - text_base) <= precision / 2 + 1e-9 * max(1.0, abs(text_base))


# What a writer may print for a component: the agency's own figure, and the same figure
# in the units Korean prose uses (만 for counts, 억 for dollars) or FRED's (thousands).
_DIVISOR = {'$B': 1e9}


def cite_values(base, precision, unit):
    """-> (shown, [values the gate accepts]). `base` is FRED's value in the text's base
    unit, rounded to the text's precision first — the agency prints 42,000, not 41,600."""
    rounded = round(base / precision) * precision if precision else base
    div = _DIVISOR.get(unit, 1.0)
    shown = rounded / div
    digits = max(0, -int(math.floor(math.log10(precision / div)))) if precision else 2
    shown = round(shown, min(digits, 3))
    shown = int(shown) if float(shown).is_integer() else shown
    vals = [shown]
    if unit in ('명', '건', '채'):
        for d in (1e3, 1e4, 1e6):
            if abs(rounded) >= d:
                vals.append(round(rounded / d, 3))
    if unit == '$B':
        vals.append(round(rounded / 1e8, 1))           # 억 달러
    out = []
    for v in vals:
        v = int(v) if float(v).is_integer() else v
        if v not in out:
            out.append(v)
    return shown, out


# -------------------------------------------------------------- pipeline

def produce(rel, fetch_rows, release_date, headline_rows=None):
    """Step one, in the collector: each registered component's FRED value on D.

    `fetch_rows(fred_id, obs_start, obs_end)` returns vintage rows (or raises);
    `headline_rows` the same for the headline series. Writes `rel['anatomy']` and
    resets `rel['components']` to [] — nothing is usable until the text agrees.
    """
    comps = COMPONENTS.get(rel.get('key'), ())
    primary = next((i for i in rel.get('indicators') or []
                    if i.get('name') == rel.get('primary')), {}) or {}
    ref = primary.get('ref_period')
    out = {'release_date': release_date, 'round': 'ok', 'candidates': []}
    rel['components'] = []
    rel['anatomy'] = out
    if not comps:
        out['round'] = 'no_registry'
        return rel
    if not release_date:
        out['round'] = 'no_release_date'
    elif headline_rows is not None:
        ok, why = headline_on_release_date(headline_rows, ref, release_date)
        if not ok:
            out['round'] = why
    for c in comps:
        cand = {'label': c['label'], 'fred_id': c['fred_id'], 'transform': c['transform'],
                'unit': c['unit'], 'round_ok': False, 'reason': out['round']}
        out['candidates'].append(cand)
        if out['round'] != 'ok':
            continue
        cur_d, prev_d = period_dates(ref, c['transform'], c['period'])
        if cur_d is None:
            cand['reason'] = 'no_period'
            continue
        try:
            rows = fetch_rows(c['fred_id'], prev_d or cur_d, cur_d)
        except Exception as e:                       # noqa: BLE001 — recorded, not fatal
            cand['reason'] = f'fetch_failed: {type(e).__name__}'
            continue
        value, why, detail = round_value(rows, ref, release_date, c['transform'], c['period'])
        cand.update({'reason': why, 'observation': cur_d, **detail})
        if value is not None:
            cand.update({'round_ok': True, 'fred_value': value})
    return rel


def text_usable(row):
    """An index row whose document may serve as the second source: fetched this run,
    identity and period verified, **and** the headline value itself checked."""
    if not row or not row.get('ok') or not row.get('verified'):
        return False
    checks = row.get('checks') or {}
    return checks.get('value') is True or checks.get('primary_checked') is True


def cross_check(rel, text, index_row):
    """Step two, after the release texts: keep the candidates the text agrees with.

    Sets `components` (usable, in the order registered), each candidate's `text_ok` and
    reason, and `anatomy_status`: complete (≥2), partial (1), text (0, a publishable
    verified text), none.
    """
    anat = rel.get('anatomy') or {}
    cands = anat.get('candidates') or []
    regs = {c['fred_id']: c for c in COMPONENTS.get(rel.get('key'), ())}
    primary = next((i for i in rel.get('indicators') or []
                    if i.get('name') == rel.get('primary')), {}) or {}
    ref = primary.get('ref_period')
    usable_text = text_usable(index_row) and bool(text)
    comps = []
    for cand in cands:
        cand['text_ok'] = False
        reg = regs.get(cand.get('fred_id'))
        if not cand.get('round_ok') or reg is None:
            continue
        if not usable_text:
            cand['reason'] = 'no_verified_text'
            continue
        tval, precision, why = text_value(reg, text, ref)
        if tval is None:
            cand['reason'] = why
            continue
        fbase = cand['fred_value'] * reg['scale']
        if not agrees(fbase, tval, precision, reg['step']):
            cand.update({'reason': 'fred_text_disagree', 'text_value': tval})
            continue
        prec = max(precision or 0.1, reg['step'] or 0)
        # Print the agency's own figure. FRED agreed with it to the text's precision, and
        # rounding FRED again could land elsewhere (42,500 → 42,000 under round-half-even
        # while the text says 43,000 — codex 구현 1회 #1).
        shown, cites = cite_values(tval, prec, reg['unit'])
        cand.update({'text_ok': True, 'reason': 'ok', 'text_value': tval})
        comps.append({'label': reg['label'], 'fred_id': reg['fred_id'],
                      'transform': reg['transform'], 'unit': reg['unit'],
                      'aliases': list(reg['aliases']),
                      'actual': shown, 'cite_values': cites, 'text_value': tval,
                      'ref_period': cand.get('observation')})
    rel['components'] = comps
    publishable = usable_text and rel.get('key') not in PRIVATE_TEXT
    if len(comps) >= 2:
        status = 'complete'
    elif len(comps) == 1:
        status = 'partial'
    elif publishable:
        status = 'text'
    else:
        status = 'none'
    rel['anatomy_status'] = status
    rel['anatomy_reason'] = (None if status == 'complete' else
                             'no_verified_text' if not usable_text else
                             anat.get('round') if anat.get('round') != 'ok' else
                             'components_short')
    return rel


def reset(rel):
    """Before step two runs (or when it cannot): nothing is usable."""
    rel['components'] = []
    rel['anatomy_status'] = 'none'
    rel['anatomy_reason'] = 'not_cross_checked'
    for cand in (rel.get('anatomy') or {}).get('candidates') or []:
        cand['text_ok'] = False
    return rel


def gaps(headline_releases):
    """Releases the page could not fully take apart — for the log and the first weeks'
    review (설계 사각지대 1). Never printed on the page."""
    out = []
    for rel in headline_releases or []:
        status = rel.get('anatomy_status')
        if status in ('partial', 'none'):
            out.append({'key': rel.get('key'), 'status': status,
                        'reason': rel.get('anatomy_reason'),
                        'components': len(rel.get('components') or [])})
    return out
