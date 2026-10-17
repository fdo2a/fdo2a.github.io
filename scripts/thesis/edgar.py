"""SEC EDGAR filings: the US half of `disclosure.py`, for the names DART cannot see.

Micron files with the SEC, not with DART, so until this module the only thing that caught
a Micron event was the Friday full sweep in `quiet.py`. This reads the regulator's own
submissions index for each tracked CIK and maps every filing onto the **same event keys**
`disclosure.to_event()` produces, so `quiet.decide()`, `event_axes()` and the routine read
an 8-K exactly the way they read a DART filing.

Two flags, two jobs:

    confirmed   a narrow whitelist with DART's axis discipline. It is what can supply a
                kill axis, so widening it is the dangerous direction (DART spec).
    notable     filings that must not be skipped but cannot be classified from the index
                alone — an 8-K 1.01 is as often a bond indenture as a supply contract, and
                Micron has announced guidance, a China ruling and CHIPS awards under 7.01
                and 8.01. They break the quiet (`quiet.py`) and the routine reads them;
                they never supply an axis.

Window: SEC `filingDate` (an ET business date) from the day before the last collection
through today — the same one-day overlap DART uses. Timestamps are not usable:
`acceptanceDateTime` is labelled UTC but is Eastern time shifted by twice the offset
(measured against EDGAR index pages, see `accepted_et`), and a cursor cannot survive two
collections before one routine read. The overlap reports a filing on two consecutive
collections, exactly as DART does.

Access: data.sec.gov refuses urllib's default User-Agent (403) and asks for a declared one
with a contact address. `SEC_USER_AGENT` (a repository *variable*, so no address sits in
the public repo) overrides the declared default. One request per ticker per day.

Non-core: any failure is recorded in `missing`, which makes the day "not provably quiet".
It never blocks collection.

Pure except for `fetch_submissions()` and `collect()`.

Design: docs/superpowers/specs/2026-10-17-sec-edgar-micron-feed.md
"""

import gzip
import json
import os
import ssl
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

SUBMISSIONS = 'https://data.sec.gov/submissions/CIK{}.json'
ARCHIVE = 'https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}'
ET = ZoneInfo('America/New_York')

# Measured 2026-10-17: SEC's WAF lets this through on data.sec.gov from an Actions runner,
# and refuses urllib's default as well as any UA mentioning "github" or a bare URL.
DEFAULT_USER_AGENT = 'fdo2a-report thesis-watch'

MAX_WINDOW_DAYS = 30

# 8-K items that are `confirmed`, and their axis. `contract` is the only kill axis
# (state.KILL_AXES); 2.02 (results) sits where DART's 영업(잠정)실적 does.
ITEM_AXES = {
    '2.02': 'contract',
    '2.01': 'capital', '2.03': 'capital', '2.04': 'capital', '3.02': 'capital',
    '3.03': 'capital',
    '2.05': 'financials', '2.06': 'financials', '4.01': 'financials', '4.02': 'financials',
}
AXIS_RANK = ('contract', 'capital', 'financials', 'ownership')

# 8-K items that break the quiet but supply no axis — see the module docstring.
NOTABLE_ITEMS = frozenset({'1.01', '1.02', '1.05', '5.01', '5.02', '7.01', '8.01'})

FORM_AXES = {
    '10-K': 'financials', '10-Q': 'financials',
    'SCHEDULE 13D': 'ownership', 'SC 13D': 'ownership',
}
# A late-filing notice says the periodic report is not ready — worth a look, no axis.
NOTABLE_FORMS = frozenset({'NT 10-K', 'NT 10-Q'})


# ────────────────────────────── 분류 ──────────────────────────────

def parse_items(raw) -> list:
    return [s.strip() for s in str(raw or '').split(',') if s.strip()]


def classify(form, items) -> dict:
    """What this filing is: its axis, and whether it is confirmed or notable. Never raises.

    An amendment (`/A`) restates a filing already counted, so it is never `confirmed` —
    DART's 기재정정 rule. An amended 8-K is still `notable`: an 8-K/A to a 2.02 can carry
    revised numbers.
    """
    form = (form or '').strip().upper()
    correction = form.endswith('/A')
    base = form[:-2] if correction else form
    parsed = parse_items(items)
    axis = kind = None
    if base == '8-K':
        hits = [(ITEM_AXES[i], i) for i in parsed if i in ITEM_AXES]
        if hits:
            axis, item = min(hits, key=lambda h: AXIS_RANK.index(h[0]))
            kind = f'8-K {item}'
        elif any(i in NOTABLE_ITEMS for i in parsed):
            kind = f'8-K {next(i for i in parsed if i in NOTABLE_ITEMS)}'
    elif base in FORM_AXES:
        axis, kind = FORM_AXES[base], base
    elif base in NOTABLE_FORMS:
        kind = base
    confirmed = bool(axis) and not correction
    notable = not confirmed and (
        (base == '8-K' and (bool(axis) or any(i in NOTABLE_ITEMS for i in parsed)))
        or base in NOTABLE_FORMS)
    return {'axis': axis, 'kind': kind, 'correction': correction,
            'confirmed': confirmed, 'notable': notable}


# ────────────────────────────── 응답 파싱 ──────────────────────────────

def verify(payload, ticker) -> bool:
    """Whether this CIK really is that ticker. A wrong CIK reads like a quiet day."""
    return isinstance(payload, dict) and ticker in (payload.get('tickers') or [])


def filings(payload) -> list:
    """`filings.recent` parallel arrays as row dicts. Raises on a malformed payload.

    An empty list and a broken response are different things — a broken response
    silently read as "no filings" is a false quiet day.
    """
    try:
        recent = payload['filings']['recent']
        acc = recent['accessionNumber']
    except (KeyError, TypeError):
        raise RuntimeError('SEC submissions: filings.recent 없음') from None
    keys = [k for k, v in recent.items() if isinstance(v, list) and len(v) == len(acc)]
    return [{k: recent[k][i] for k in keys} for i in range(len(acc))]


def accepted_et(row):
    """EDGAR's acceptance time in Eastern time, 'YYYY-MM-DD HH:MM:SS ET', or None.

    `acceptanceDateTime` says `Z` but is ET wall time plus **twice** the UTC offset:
    the 2026-09-30 earnings 8-K reads `2026-10-01T00:02:22Z` against 16:02:22 EDT on its
    index page (+8 h), the 2025-12-17 one `2025-12-18T02:03:26Z` against 16:03:26 EST
    (+10 h). Reading it as UTC would move an after-close release into the next session.
    """
    raw = str(row.get('acceptanceDateTime') or '').strip()
    try:
        shifted = datetime.fromisoformat(raw.replace('Z', '+00:00')).replace(tzinfo=None)
    except ValueError:
        return None
    for hours in (4, 5):                         # EDT, EST
        local = shifted - timedelta(hours=2 * hours)
        if local.replace(tzinfo=ET).utcoffset() == timedelta(hours=-hours):
            return local.strftime('%Y-%m-%d %H:%M:%S') + ' ET'
    return None


def to_event(row, cik, corp) -> dict:
    """A submissions row with DART's event keys plus SEC's own (`form`, `items`, `accepted_et`).

    `url` is the primary document in the EDGAR archive — the primary source arrives attached
    to the fact, as DART's receipt link does. `filer` is None: the submissions index does
    not name who filed (a Form 4 or 144 is the insider's or the broker's, not the issuer's),
    and a guessed name is worse than none.
    """
    acc = str(row.get('accessionNumber') or '').strip()
    form = str(row.get('form') or '').strip()
    items = parse_items(row.get('items'))
    doc = str(row.get('primaryDocument') or '').strip() or f'{acc}-index.htm'
    return {
        'rcept_no': acc,
        'date': row.get('filingDate') or None,
        'title': f'{form} Item {", ".join(items)}' if items else form,
        'corp': corp,
        'filer': None,
        'url': ARCHIVE.format(cik=str(int(cik)), acc=acc.replace('-', ''), doc=doc),
        'form': form,
        'items': items,
        'accepted_et': accepted_et(row),
        **classify(form, row.get('items')),
    }


def event_axes(events) -> tuple:
    """Axes today's **confirmed** filings cover, for `triggers.kill_axes`."""
    return tuple(sorted({e['axis'] for e in events or ()
                         if e.get('confirmed') and e.get('axis')}))


# ────────────────────────────── 창 ──────────────────────────────

def window(rows, today, max_days=MAX_WINDOW_DAYS):
    """(first, last) SEC filing dates to report, both inclusive, as ISO strings.

    From the day **before** the last recorded collection: a collection can run while the
    US day is still open (a manual run at 01:00 KST is 12:00 ET), and that day's later
    filings must land in the next collection. Through today: a late-night KST run can see
    the current ET day. The cap keeps a long outage from dumping a year of filings.
    """
    end = date.fromisoformat(today)
    floor = end - timedelta(days=max_days)
    dates = [r['date'] for r in rows or () if r.get('date')]
    start = floor
    if dates:
        start = max(date.fromisoformat(max(dates)) - timedelta(days=1), floor)
    return start.isoformat(), end.isoformat()


def in_window(row, first, last) -> bool:
    filed = str(row.get('filingDate') or '')
    return bool(filed) and first <= filed <= last


# ────────────────────────────── 네트워크 ──────────────────────────────

def user_agent() -> str:
    """The declared UA. Actions passes an unset `vars.X` as an empty string."""
    return (os.environ.get('SEC_USER_AGENT') or '').strip() or DEFAULT_USER_AGENT


def _context():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001 — fall back to the system store
        return ssl.create_default_context()


def fetch_submissions(cik, timeout=20, attempts=3, pause=2.0):
    """One submissions JSON. 403 is not retried — a WAF block is not transient."""
    req = urllib.request.Request(SUBMISSIONS.format(cik), headers={
        'User-Agent': user_agent(), 'Accept-Encoding': 'gzip'})
    last = None
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=timeout,  # noqa: S310 — fixed https
                                        context=_context()) as resp:
                body = resp.read()
                if resp.headers.get('Content-Encoding') == 'gzip':
                    body = gzip.decompress(body)
                return json.loads(body.decode('utf-8'))
        except urllib.error.HTTPError as e:
            if e.code < 500 and e.code != 429:
                raise RuntimeError(f'SEC {e.code}') from None
            last = f'SEC {e.code}'
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            last = f'SEC {type(e).__name__}: {str(e)[:80]}'
        time.sleep(pause * (attempt + 1))
    raise RuntimeError(last or 'SEC 실패')


def collect(ciks, rows, today, fetch=fetch_submissions):
    """Filings dated inside the window for each ticker, as rows for `disclosures.json`.

    `ciks` maps ticker -> CIK (10 digits); `rows` is history.jsonl **before** today's row
    is appended, as for `disclosure.collect`. Returns `{'tickers', 'missing', 'sec'}`.
    """
    first, last = window(rows, today)
    out = {'tickers': {}, 'missing': [],
           'sec': {'window': {'first': first, 'last': last},
                   'note': 'SEC filingDate(미 동부 영업일) 기준, 직전 수집 전날부터 — DART 와 같이 하루 겹친다'}}
    for ticker, cik in ciks.items():
        try:
            payload = fetch(cik)
            if not verify(payload, ticker):
                out['missing'].append(f'{ticker}:cik')
                continue
            corp = payload.get('name') or ticker
            events = [to_event(r, cik, corp) for r in filings(payload)
                      if in_window(r, first, last)]
        except RuntimeError as e:
            out['missing'].append(f'{ticker}:{str(e)[:80]}')
            continue
        events.sort(key=lambda e: (e['date'] or '', e['accepted_et'] or '',
                                   e['rcept_no'] or ''), reverse=True)
        out['tickers'][ticker] = {
            'cik': cik,
            'events': events,
            'axes': list(event_axes(events)),
            'confirmed_count': sum(1 for e in events if e['confirmed']),
            'notable_count': sum(1 for e in events if e['notable']),
        }
    return out


def merge(disclosures, sec):
    """Fold SEC rows into DART's payload in place. DART rows and `missing` are kept."""
    disclosures.setdefault('tickers', {}).update(sec.get('tickers') or {})
    disclosures['missing'] = list(disclosures.get('missing') or []) + list(sec.get('missing') or [])
    disclosures['sec'] = sec.get('sec') or {}
    return disclosures
