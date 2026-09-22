"""OpenDART filings: the event half of "did anything change?", mechanized.

`triggers.evaluate()` answers the numeric half arithmetically. The event half — a contract,
a guidance revision, a share issue — was left to the routine's prompt, and a prompt asked
every evening whether something happened will eventually answer yes. This module supplies
that half from the regulator's own filing index, so a quiet day stays quiet by arithmetic.

Three seams already existed for it and are filled here, not widened:

    triggers.kill_axes(hits, event_axes)   the contract axis a chart can never supply
    gate.check_silence(triggers, events)   `confirmed` is what licenses a page edit
    state.propose(..., kill_evidence)      two axes, or no kill

**Only a whitelisted filing is `confirmed`.** These names file dozens of documents a day —
affiliate notices, insider holdings, corrections — and marking them all as events would
make every day an event day, which is precisely the failure this pipeline exists to
prevent. Everything else is recorded and stays silent.

Security: DART puts the key in the **query string** (`crtfc_key=`), where ECOS puts it in
the URL path. `kr/econ.py`'s scrub pattern does not match here — this module has its own,
and every string that can reach a log or an exception goes through it.

Non-core: no key, no network, or a DART outage all mean "no events today", which fails in
the safe direction. It never blocks collection.

Pure except for the `fetch_*` helpers and `collect()`.

Design: docs/superpowers/specs/2026-09-21-dart-disclosure-integration.md
"""

import json
import os
import re
import urllib.parse
import urllib.request
from datetime import date, timedelta

BASE = 'https://opendart.fss.or.kr/api'
RECEIPT = 'https://dart.fss.or.kr/dsaf001/main.do?rcpNo={}'

_KEY_IN_QS = re.compile(r'(crtfc_key=)[^&\s]+')

# DART mixes three middle dots in the same report name. Matching the literal string
# silently misses filings, and a trigger that silently misses is worse than no trigger.
_NOISE = re.compile(r'[ㆍ·・\s()\[\]]+')

# Filings that license a page edit, and the axis each one speaks to. Substring match
# against the noise-stripped name, longest first so a specific rule wins.
#
# `contract` is the only axis a kill can use (state.KILL_AXES). `capital`, `ownership`
# and `financials` are events worth a sentence, not evidence that a thesis broke.
CONFIRMED = (
    ('단일판매공급계약체결', 'contract'),
    ('영업잠정실적', 'contract'),
    ('매출액또는손익구조', 'contract'),
    ('유상증자결정', 'capital'),
    ('무상증자결정', 'capital'),
    ('전환사채권발행결정', 'capital'),
    ('신주인수권부사채권발행결정', 'capital'),
    ('교환사채권발행결정', 'capital'),
    ('자기주식취득결정', 'capital'),
    ('자기주식처분결정', 'capital'),
    ('자기주식소각결정', 'capital'),
    ('주식등의대량보유상황보고서', 'ownership'),
    ('분기보고서', 'financials'),
    ('반기보고서', 'financials'),
    ('사업보고서', 'financials'),
)

# A correction restates a filing already counted. Counting it again reports one event
# twice — the same failure `triggers._armed` exists to prevent on the numeric side.
CORRECTIONS = ('기재정정', '첨부정정', '첨부추가', '첨부생략', '변경등록', '발행조건확정')

# Quarterly report codes, newest-looking first when probed.
REPRT_CODES = {1: '11013', 2: '11012', 3: '11014', 4: '11011'}

MAX_WINDOW_DAYS = 30


# ────────────────────────────── 키 마스킹 ──────────────────────────────

def scrub(text) -> str:
    """Mask the key. Apply to every string that can reach a log or an exception.

    Both halves are needed: the query pattern catches a URL even when the environment
    variable is unset or different, and the literal value catches an echo of the key that
    did not arrive inside a URL.
    """
    s = _KEY_IN_QS.sub(r'\1***', str(text))
    key = os.environ.get('DART_API_KEY')
    return s.replace(key, '***') if key else s


# ────────────────────────────── 분류 ──────────────────────────────

def _norm(report_nm: str) -> str:
    return _NOISE.sub('', report_nm or '')


def classify(report_nm: str) -> dict:
    """What this filing is, and whether it is allowed to license a page edit.

    Always returns a dict — an unrecognised name is not an error, it is a quiet day.
    """
    norm = _norm(report_nm)
    correction = any(c in norm for c in CORRECTIONS)
    axis = kind = None
    for pattern, pattern_axis in sorted(CONFIRMED, key=lambda p: -len(p[0])):
        if pattern in norm:
            axis, kind = pattern_axis, pattern
            break
    return {'axis': axis, 'kind': kind, 'correction': correction,
            'confirmed': bool(axis) and not correction}


# ────────────────────────────── 응답 파싱 ──────────────────────────────

def _check_status(payload) -> str:
    """DART status, raising on a real error. '013' (no data) is a normal empty day.

    Treating '013' as a failure would make collection fail on every quiet day, which is
    most days — the same trap ECOS's INFO-200 set for `kr/econ.py`.
    """
    if not isinstance(payload, dict):
        raise RuntimeError('DART 응답이 객체가 아니다')
    status = payload.get('status')
    if status in ('000', '013'):
        return status
    raise RuntimeError(scrub(f'DART {status}: {payload.get("message")}'))


def parse_list(payload) -> list:
    """Filing index rows. Empty list when there were none."""
    return list(payload.get('list') or []) if _check_status(payload) == '000' else []


def _amount(text):
    """DART money strings: thousands separators, and negatives in parentheses."""
    s = str(text or '').strip().replace(',', '')
    if not s or s == '-':
        return None
    negative = s.startswith('(') and s.endswith(')')
    if negative:
        s = s[1:-1]
    try:
        value = float(s)
    except ValueError:
        return None
    return -value if negative else value


def parse_equity(payload):
    """Shareholders' equity from `fnlttSinglAcntAll`, controlling interest preferred.

    P/B's numerator is the controlling shareholders' share. Falling back to total equity
    folds in the non-controlling interest and quietly overstates book value, so the
    specific line wins whenever the filing carries it.
    """
    if _check_status(payload) != '000':
        return None
    total = controlling = None
    for row in payload.get('list') or []:
        if (row.get('sj_div') or 'BS') != 'BS':
            continue
        name = _norm(row.get('account_nm'))
        value = _amount(row.get('thstrm_amount'))
        if value is None:
            continue
        if '지배기업' in name and controlling is None:
            controlling = value
        elif name == '자본총계' and total is None:
            total = value
    return controlling if controlling is not None else total


def parse_share_counts(payload):
    """(issued, treasury) for common stock, from `stockTotqySttus`. None when absent.

    Preferred stock and the 합계 row are skipped: BVPS here is per common share, and the
    totals row would double-count.
    """
    if _check_status(payload) != '000':
        return None
    for row in payload.get('list') or []:
        if '보통주' not in _norm(row.get('se')):
            continue
        issued = _amount(row.get('istc_totqy'))
        treasury = _amount(row.get('tesstk_co')) or 0
        if issued:
            return int(issued), int(treasury)
    return None


def bvps(equity, shares_issued, treasury=0):
    """Book value per common share. None when an input is missing — never a guess.

    Treasury shares are netted out because they carry no claim on equity. A missing or
    non-positive count returns None rather than a number nobody can defend.
    """
    if equity is None or not shares_issued:
        return None
    net = shares_issued - (treasury or 0)
    return equity / net if net > 0 else None


def verify_corp(payload, stock_code: str) -> bool:
    """Whether this 고유번호 really is that 종목코드.

    The mapping table is a 20MB download, so the two codes we need are constants. ECOS's
    lesson was not "never hardcode" but "never fail silently" — a wrong code returns an
    empty result that reads exactly like a quiet day, so it is checked instead.
    """
    try:
        if _check_status(payload) != '000':
            return False
    except RuntimeError:
        return False
    return (payload.get('stock_code') or '').strip() == stock_code


# ────────────────────────────── 조회 창 ──────────────────────────────

def window(rows, today, max_days=MAX_WINDOW_DAYS):
    """(bgn_de, end_de) covering everything since the last recorded day.

    Starting at the last history row rather than today fills the days a failed or skipped
    collection left behind, and catches filings accepted after the 17:40 KST run — DART
    accepts until 18:00, so the tail of each day arrives in the next day's window. The cap
    keeps a long outage from requesting a year of filings in one call.
    """
    end = date.fromisoformat(today)
    floor = end - timedelta(days=max_days)
    dates = [r['date'] for r in rows or () if r.get('date')]
    start = max(date.fromisoformat(max(dates)), floor) if dates else floor
    return start.strftime('%Y%m%d'), end.strftime('%Y%m%d')


# ────────────────────────────── 사건 ──────────────────────────────

def _iso(yyyymmdd: str):
    s = str(yyyymmdd or '').strip()
    return f'{s[:4]}-{s[4:6]}-{s[6:8]}' if len(s) == 8 else None


def to_event(item: dict) -> dict:
    """A filing index row as an event `gate.check_silence` and the writer can both read.

    `url` is the permanent receipt page. It is what the writer cites, and it is why this
    module closes `gate.check`'s `fact_sourcing` requirement without anyone hand-pasting a
    link: the primary source arrives attached to the fact.
    """
    verdict = classify(item.get('report_nm'))
    return {
        'rcept_no': item.get('rcept_no'),
        'date': _iso(item.get('rcept_dt')),
        'title': (item.get('report_nm') or '').strip(),
        'corp': item.get('corp_name'),
        'filer': item.get('flr_nm'),
        'url': RECEIPT.format(item.get('rcept_no')),
        **verdict,
    }


def event_axes(events) -> tuple:
    """Axes today's **confirmed** filings cover, for `triggers.kill_axes`.

    Unconfirmed filings contribute nothing on purpose: a correction or an insider holding
    notice must not be able to move a grade, let alone open a kill.
    """
    return tuple(sorted({e['axis'] for e in events or ()
                         if e.get('confirmed') and e.get('axis')}))


# ────────────────────────────── 네트워크 ──────────────────────────────

def _get(path: str, timeout: int = 20, **params):
    """One DART call. Returns None when no key is configured — non-core, so silent.

    The raw exception never escapes: it carries the full URL, and the URL carries the key.
    """
    key = os.environ.get('DART_API_KEY')
    if not key:
        return None
    url = f'{BASE}/{path}?' + urllib.parse.urlencode({'crtfc_key': key, **params})
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return json.loads(response.read().decode('utf-8'))
    except Exception as e:
        raise RuntimeError(f'DART {path} 실패: {scrub(e)}') from None


def fetch_list(corp_code, bgn_de, end_de, page_count=100):
    return _get('list.json', corp_code=corp_code, bgn_de=bgn_de, end_de=end_de,
                page_count=page_count)


def fetch_company(corp_code):
    return _get('company.json', corp_code=corp_code)


def fetch_equity(corp_code, bsns_year, reprt_code, fs_div='CFS'):
    return _get('fnlttSinglAcntAll.json', corp_code=corp_code, bsns_year=str(bsns_year),
                reprt_code=reprt_code, fs_div=fs_div)


def fetch_shares(corp_code, bsns_year, reprt_code):
    return _get('stockTotqySttus.json', corp_code=corp_code, bsns_year=str(bsns_year),
                reprt_code=reprt_code)


def recent_reports(today, back=5):
    """(bsns_year, reprt_code, label) newest-first, to probe for the latest statement.

    A quarterly report is accepted about 45 days after the quarter ends, so the newest
    period usually has nothing yet and the probe steps back. This is the honest limit of
    the whole exercise: DART shortens yfinance's lag by roughly a quarter, it does not
    make book value same-day.
    """
    d = date.fromisoformat(today)
    year, quarter = d.year, (d.month - 1) // 3 + 1
    out = []
    for _ in range(back):
        out.append((year, REPRT_CODES[quarter], f'{year}-Q{quarter}'))
        quarter -= 1
        if quarter == 0:
            year, quarter = year - 1, 4
    return out


def book_value(corp_code, today, back=5):
    """Latest filed BVPS, with the period it came from. (None, None) when unavailable.

    Equity and the share count are taken from the **same** report. Mixing a fresh equity
    figure with a stale share count would produce a number that exists in no filing — the
    kind of invented number this pipeline exists to prevent.
    """
    for bsns_year, reprt_code, label in recent_reports(today, back):
        try:
            equity = parse_equity(fetch_equity(corp_code, bsns_year, reprt_code) or {})
            counts = parse_share_counts(fetch_shares(corp_code, bsns_year, reprt_code) or {})
        except RuntimeError:
            continue
        if equity is None or not counts:
            continue
        value = bvps(equity, counts[0], counts[1])
        if value:
            return value, label
    return None, None


def collect(corps, rows, today, max_days=MAX_WINDOW_DAYS):
    """Today's filings for each tracked name, as a writable payload.

    `corps` maps ticker -> (corp_code, stock_code). A name whose code fails verification is
    skipped and recorded in `missing`, never queried blind.
    """
    bgn_de, end_de = window(rows, today, max_days)
    out = {'as_of': today, 'window': {'bgn': bgn_de, 'end': end_de},
           'note': 'DART 는 18:00 까지 접수한다 — 17:40 수집 이후 공시는 다음 창에 잡힌다',
           'tickers': {}, 'missing': []}

    if not os.environ.get('DART_API_KEY'):
        out['pending'] = True
        return out

    for ticker, (corp_code, stock_code) in corps.items():
        try:
            if not verify_corp(fetch_company(corp_code) or {}, stock_code):
                out['missing'].append(f'{ticker}:corp_code')
                continue
            events = [to_event(i) for i in parse_list(fetch_list(corp_code, bgn_de, end_de))]
        except RuntimeError as e:
            out['missing'].append(f'{ticker}:{scrub(e)[:80]}')
            continue
        events.sort(key=lambda e: (e['date'] or '', e['rcept_no'] or ''), reverse=True)
        out['tickers'][ticker] = {
            'corp_code': corp_code,
            'events': events,
            'axes': list(event_axes(events)),
            'confirmed_count': sum(1 for e in events if e['confirmed']),
        }
    return out
