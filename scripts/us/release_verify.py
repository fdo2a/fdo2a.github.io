"""Is this fetched document the release for *this* print? (2026-11-06)

`fetch_releases.py` used to call a page good when it answered 200 with more than 3,000
bytes. `pce.txt` passed that with 3,259 bytes of bea.gov navigation and nothing else —
the URL was an evergreen landing page. The writer was then told to read it.

So each release document gets one *identity sentence*: the agency's own lede, which
names the period and the headline value in the same breath ("The Consumer Price Index
… increased 0.6 percent on a seasonally adjusted basis in September"). We match that
sentence, read the period out of it and compare it with the `ref_period` FRED gave
the indicator, and compare the value — magnitude and the sign the verb carries — when
the sentence has one. No table parsing: a table row holds the current month, last
month and revisions side by side, and telling them apart is exactly the guess this
module exists to avoid. A document whose lede we cannot find fails — a missing
release costs the post its release-only detail, a wrong one costs it the truth.

The year: most ledes name the month only ("in September"). The document must then
mention the expected year somewhere in the scanned text; one that does not is
another year's release.

Verification runs on the *whole* flattened text, before `release_text.to_text` trims
the lede and truncates. Spec: docs/superpowers/specs/2026-11-07-release-contract.md.

Pure: text and dicts in, a dict out.
"""
import datetime
import re

MONTHS = ('January', 'February', 'March', 'April', 'May', 'June', 'July', 'August',
          'September', 'October', 'November', 'December')
QUARTERS = {'first': 1, 'second': 2, 'third': 3, 'fourth': 4}

_DIR = (r'(?P<dir>increased|rose|decreased|fell|declined|was unchanged|were unchanged|'
        r'edged up|edged down)')
_UP = ('increased', 'rose', 'edged up')
_DOWN = ('decreased', 'fell', 'declined', 'edged down')

# key -> [(indicator, pattern, period kind, unit scales)]. The first entry is the
# document's identity: it must match, and its period must equal that indicator's
# ref_period. Later entries add a value check when they are the release's primary.
# period kind: 'month', 'quarter', 'week' (ref_period = the week-ending date FRED
# stamps on the weekly series). Scales: FRED value x scale = the printed figure
# (JOLTS is in thousands on FRED, millions in the lede; new-home sales thousands vs
# units; existing-home sales units vs millions).
SPEC = {
    'cpi': [
        ('CPI MoM', r'Consumer Price Index for All Urban Consumers \(CPI-U\) ' + _DIR
         + r'(?: (?P<v>\d+\.\d) percent)? on a seasonally adjusted basis in (?P<m>[A-Z][a-z]+)',
         'month', (1,)),
    ],
    'ppi': [
        ('PPI Final Demand MoM', r'Producer Price Index for final demand ' + _DIR
         + r'(?: (?P<v>\d+\.\d) percent)? in (?P<m>[A-Z][a-z]+)', 'month', (1,)),
    ],
    'employment': [
        ('Nonfarm Payrolls (chg)', r'nonfarm payroll employment\b[^.]{0,200}? in (?P<m>[A-Z][a-z]+)\b',
         'month', (1,)),
        ('Unemployment Rate', r'unemployment rate \((?P<v>\d+\.\d) percent\)', 'month', (1,)),
    ],
    'claims': [
        ('Initial Jobless Claims', r'In the week ending (?P<m>[A-Z][a-z]+) (?P<d>\d{1,2}), the advance '
         r'figure for seasonally adjusted initial claims was (?P<v>[\d,]+)', 'week', (1,)),
    ],
    'jolts': [
        ('JOLTS Job Openings', r'number of job openings (?:was|were) (?:little changed|unchanged|'
         r'increased|decreased|rose|fell|edged up|edged down)(?: to| at)? (?P<v>\d+\.\d) million '
         r'in (?P<m>[A-Z][a-z]+)', 'month', (1e-3,)),
    ],
    'industrial-production': [
        ('Industrial Production MoM', r'Industrial production(?: \(IP\))? ' + _DIR
         + r'(?: (?P<v>\d+\.\d) percent)? in (?P<m>[A-Z][a-z]+)', 'month', (1,)),
    ],
    'durable-goods': [
        ('Durable Goods Orders MoM', r'New orders for manufactured durable goods in (?P<m>[A-Z][a-z]+)\b'
         r'[^$]{0,120}?(?P<dir>increased|decreased|rose|fell) \$[\d.]+ billion or (?P<v>\d+\.\d) percent',
         'month', (1,)),
    ],
    'new-home-sales': [
        ('New Home Sales', r'Sales of new single-family houses in (?P<m>[A-Z][a-z]+) (?P<y>\d{4}) were '
         r'at a seasonally-adjusted annual rate of (?P<v>[\d,]+)', 'month', (1e3,)),
    ],
    'retail-sales': [
        ('Retail Sales MoM', r'advance estimates of U\.S\. retail and food services sales for '
         r'(?P<m>[A-Z][a-z]+) (?P<y>\d{4})', 'month', (1,)),
    ],
    'gdp': [
        ('Real GDP Growth QoQ (ann.)', r'Real gross domestic product \(GDP\) (?P<dir>increased|decreased) '
         r'at an annual rate of (?P<v>\d+\.\d) percent in the (?P<q>first|second|third|fourth) quarter '
         r'of (?P<y>\d{4})', 'quarter', (1,)),
    ],
    'pce': [
        ('PCE Price Index YoY', r'Personal Income and Outlays, (?P<m>[A-Z][a-z]+) (?P<y>\d{4})', 'month', (1,)),
        ('PCE Price Index YoY', r'From the same month one year ago, the PCE price index for '
         r'(?P<m>[A-Z][a-z]+) (?P<dir>increased|decreased) (?P<v>\d+\.\d) percent', 'month', (1,)),
        ('Core PCE YoY', r'Excluding food and energy, the PCE price index (?P<dir>increased|decreased) '
         r'(?P<v>\d+\.\d) percent from one year ago', 'month', (1,)),
    ],
    'existing-home-sales': [
        ('Existing Home Sales', r'existing-home sales to a seasonally adjusted annual rate of '
         r'(?P<v>\d+\.\d+) million in (?P<m>[A-Z][a-z]+)', 'month', (1e-6,)),
    ],
    'michigan': [
        ('Michigan Consumer Sentiment', r'(?:Preliminary|Final) Results for (?P<m>[A-Z][a-z]+) '
         r'(?P<y>\d{4})\b.{0,200}?Index of Consumer Sentiment (?P<v>\d+\.\d)', 'month', (1,)),
    ],
}

_SPACE = re.compile(r'\s+')
SCAN_CHARS = 20000     # identity sentences sit at the top; the PIO title sits under the nav


def flatten(text):
    return _SPACE.sub(' ', text or '')


def _ref(rel, name):
    for row in (rel or {}).get('indicators') or []:
        if row.get('name') == name:
            return row
    return None


def _expected(ref_period, kind):
    try:
        d = datetime.date.fromisoformat(str(ref_period)[:10])
    except ValueError:
        return None
    if kind == 'month':
        return ('month', MONTHS[d.month - 1], d.year)
    if kind == 'quarter':
        return ('quarter', (d.month - 1) // 3 + 1, d.year)
    if kind == 'week':
        return ('week', (MONTHS[d.month - 1], d.day), d.year)
    return None


def _period_ok(m, want, body):
    g = m.groupdict()
    kind, which, year = want
    if kind == 'month':
        ok = g.get('m') == which
    elif kind == 'quarter':
        ok = QUARTERS.get((g.get('q') or '').lower()) == which
    else:
        ok = g.get('m') == which[0] and int(g.get('d') or 0) == which[1]
    if not ok:
        return False
    if g.get('y'):
        return int(g['y']) == year
    return re.search(rf'(?<!\d){year}(?!\d)', body) is not None


def _value_ok(m, actual, scales):
    """The sentence's figure against FRED's: magnitude at one of the indicator's unit
    scales within the printed rounding, and — when the sentence has a verb — the sign
    the verb carries. -> None when there is nothing to compare."""
    g = m.groupdict()
    captured = g.get('v')
    verb = g.get('dir')
    if actual is None:
        return None
    try:
        a = float(actual)
    except (TypeError, ValueError):
        return None
    if verb in ('was unchanged', 'were unchanged'):
        # 「was unchanged」 is a zero print at the agencies' one decimal (codex 재검토 2026-11-06).
        return abs(a) < 0.05
    if captured is None:
        return None
    try:
        c = float(captured.replace(',', ''))
    except ValueError:
        return None
    decimals = len(captured.split('.')[1]) if '.' in captured else 0
    tol = 0.5 * 10 ** -decimals + 1e-9
    if verb in _UP and not a > 0:
        return False
    if verb in _DOWN and not a < 0:
        return False
    return any(abs(round(abs(a) * s, 6) - c) <= tol for s in scales)


def verify(text, rel):
    """-> {ok, identity, period, value, primary_checked, note}.

    `rel` is one `headline_releases` row: key, primary (indicator name), indicators[].
    """
    out = {'ok': False, 'identity': False, 'period': False, 'value': None,
           'primary_checked': False, 'note': ''}
    spec = SPEC.get((rel or {}).get('key'))
    if not spec:
        out['note'] = 'no_spec'
        return out
    body = flatten(text)[:SCAN_CHARS]

    name, pattern, kind, scales = spec[0]
    m = re.search(pattern, body)
    if not m:
        out['note'] = 'identity_not_found'
        return out
    out['identity'] = True
    row = _ref(rel, name)
    want = _expected(row.get('ref_period'), kind) if row else None
    if want is None:
        # The identity indicator is not among today's rows (e.g. claims promoted only its
        # 4-week average). Date the document off the release's first dated row instead.
        for other in (rel or {}).get('indicators') or []:
            want = _expected(other.get('ref_period'), kind)
            if want:
                break
    if want is None or not _period_ok(m, want, body):
        out['note'] = 'period_mismatch'
        return out
    out['period'] = True
    if row:
        out['value'] = _value_ok(m, row.get('actual'), scales)
        if out['value'] is False:
            out['note'] = 'value_mismatch'
            return out

    primary = (rel or {}).get('primary')
    prow = _ref(rel, primary)
    for pname, ppat, _, pscales in spec:
        if pname != primary or prow is None:
            continue
        pm = re.search(ppat, body)
        if not pm or pm.groupdict().get('v') is None:
            continue
        ok = _value_ok(pm, prow.get('actual'), pscales)
        if ok is False:
            # The primary's own sentence is there and says something else: wrong round.
            out['note'] = 'primary_value_mismatch'
            return out
        if ok:
            out['primary_checked'] = True
            break
    out['ok'] = True
    out['note'] = 'verified'
    return out
