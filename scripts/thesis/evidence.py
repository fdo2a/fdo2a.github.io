"""What licenses a thesis edit or a grade move — computed here, never taken from the routine.

Until 2026-11 the routine hand-wrote `/tmp/run.json` {triggers, events, kill_evidence} and
the gate believed it, so a `kill condition` could be claimed with nothing behind it and
the silence gate could be licensed by a trigger nobody computed. This module recomputes
every piece of evidence from collector output:

    numeric       today's triggers (STEP 1 arithmetic) — deferred, not empty, when
                  watch.json is not today's or history.jsonl is not clean
    filings       confirmed filings in today's disclosures.json
    events        research events the routine records (title + http(s) source), which
                  can never carry a numeric trigger's name
    price axis    days in the last 30 on which a replay of STEP 1 over history.jsonl
                  hit consensus_floor / bear_proximity with ≥ MIN_HISTORY_ROWS behind it
    contract axis days in the last 30 with a confirmed `contract` filing (DART or SEC)

Evidence is positive-only: a failed feed, a pending file or a missing row adds nothing,
so every input failure fails toward "no licence / no kill".

Pure — no git, no clock. `scripts/thesis_evidence.py` reads the inputs from git HEAD and
checks who committed them; the gate (`scripts/check_thesis.py`) and the routine's STEP 3
both call `assess()` through it, so they cannot disagree about T.

Design: docs/superpowers/specs/2026-08-24-thesis-watch-design.md (2026-11-23 note)
"""

import json
import math
import re
from datetime import date, timedelta

from . import history as H
from . import triggers as T
from .state import KILL_AXES

WINDOW_DAYS = 30
CONTRACT = 'contract'
assert CONTRACT in KILL_AXES

_PAST_KEYS = ('eps_fy1', 'eps_fy1_low', 'eps_fy1_high', 'price')


def _iso(value):
    try:
        return isinstance(value, str) and date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


NUMERIC_KEYS = _PAST_KEYS + ('bear',)       # every field triggers.evaluate does arithmetic on


def bad_number(obj):
    """Why the numbers under `obj` cannot be replayed, or None.

    The fields the trigger arithmetic reads must each be absent, null or a real finite
    number — a whitelist of what a number is, not a list of bad values. `json.loads`
    reads `-Infinity` and `1e999` without complaint and a price of -inf sits below every
    bear line (codex 구현 3회차); `false` compares as 0 the same way (4회차). A price at
    or below zero is not an observation either. `bear` may be ≤ 0 (loss years) —
    `triggers._bear_zone` already declines to judge it. Non-finite numbers are refused
    anywhere in the object.
    """
    stack = [('', obj)]
    while stack:
        key, value = stack.pop()
        if isinstance(value, dict):
            if key in NUMERIC_KEYS:
                return f'수가 아닌 {key}'
            stack.extend(value.items())
        elif isinstance(value, (list, tuple)):
            if key in NUMERIC_KEYS:
                return f'수가 아닌 {key}'
            stack.extend((key, v) for v in value)
        elif isinstance(value, float) and not math.isfinite(value):
            return f'유한하지 않은 수({key}={value})'
        elif key in NUMERIC_KEYS and value is not None:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return f'수가 아닌 {key}({value!r})'
            if key == 'price' and value <= 0:
                return f'0 이하인 price({value})'
    return None


def window_start(today, window_days=WINDOW_DAYS):
    """Dates strictly after this and up to `today` are inside the window."""
    return (date.fromisoformat(today) - timedelta(days=window_days)).isoformat()


def parse_history(text):
    """history.jsonl read strictly for the replay: `(rows, None)` or `(None, reason)`.

    `H.load` skips a corrupt line, which is right for display and wrong for evidence: a
    dropped line silently changes which row is "yesterday", and a fake crossing follows.
    Missing weekdays are not a problem — the collector skips days and `H.previous()`
    steps over them exactly as STEP 1 does. A missing file is no rows, not an error.
    """
    if text is None:
        return [], None
    rows, seen = [], set()
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            return None, f'history.jsonl {n}번째 줄이 JSON 이 아니다'
        if not isinstance(row, dict):
            return None, f'history.jsonl {n}번째 줄이 객체가 아니다'
        if not _iso(row.get('date')):
            return None, f'history.jsonl {n}번째 줄에 ISO 날짜가 없다'
        if row['date'] in seen:
            return None, f'history.jsonl 에 {row["date"]} 가 두 번 나온다'
        tickers = row.get('tickers', {})
        if not isinstance(tickers, dict) or not all(
                isinstance(v, dict) for v in tickers.values()):
            return None, f'history.jsonl {n}번째 줄의 tickers 꼴이 틀렸다'
        bad = bad_number(row)
        if bad:
            return None, f'history.jsonl {n}번째 줄에 {bad}'
        seen.add(row['date'])
        rows.append(row)
    rows.sort(key=lambda r: r['date'])
    return rows, None


def numeric_triggers(watch, rows):
    """Exactly STEP 1 of THESIS_ORCHESTRATOR.md — the one copy (thesis_quiet uses it too)."""
    deep = H.has_depth(rows, T.MIN_HISTORY_ROWS)
    back = H.days_ago(watch['as_of'], T.LOOKBACK_DAYS)
    out = {}
    for sym, row in watch['tickers'].items():
        past = {k: H.value_on(rows, back, sym, k) for k in _PAST_KEYS}
        past = past if any(v is not None for v in past.values()) else None
        prev = H.previous(rows, watch['as_of'], sym)
        prior = T.prior_metrics(rows, sym, before=watch['as_of'])
        out[sym] = T.evaluate(row, past, row.get('fair_value'), has_depth=deep,
                              prev=prev, prior=prior)
    return out


def today_triggers(watch, rows, today):
    """`(hits_by_ticker, None)` or `(None, reason)` — deferred is not "nothing fired".

    A stale watch.json (weekend, late collection) must not be read as today's numbers.
    """
    if not isinstance(watch, dict) or not isinstance(watch.get('tickers'), dict) \
            or not watch['tickers']:
        return None, 'watch.json 이 없거나 종목이 없다 — 수치 판정 보류'
    if watch.get('as_of') != today:
        return None, f'watch.json 이 오늘 것이 아니다 ({watch.get("as_of")}) — 수치 판정 보류'
    bad = bad_number(watch)
    if bad:
        return None, f'watch.json 에 {bad} — 수치 판정 보류'
    return numeric_triggers(watch, rows), None


def price_axis_days(rows, today, sym, window_days=WINDOW_DAYS):
    """Dates in the window where replaying STEP 1 on that day's row gives the price axis.

    Every input is bounded to rows dated ≤ d, so a later row cannot leak into an earlier
    day. The final row stored for a date is canonical (history.append replaces same-date
    rows). A day counts for kill only with ≥ MIN_HISTORY_ROWS rows behind it: crossing
    triggers fire on a two-row log, and kill must not open on a log that young.
    `rows` must come from `parse_history` (unique dates, sorted).
    """
    start = window_start(today, window_days)
    out = []
    for i, row in enumerate(rows):
        day = row['date']
        if day > today:
            break
        if day <= start:
            continue
        upto = rows[:i + 1]
        if not H.has_depth(upto, T.MIN_HISTORY_ROWS):
            continue
        snapshot = row.get('tickers', {}).get(sym)
        if not snapshot:
            continue
        bear = snapshot.get('bear')
        fair_value = {'bear': bear} if bear is not None else None
        back = H.days_ago(day, T.LOOKBACK_DAYS)
        past = {k: H.value_on(upto, back, sym, k) for k in _PAST_KEYS}
        past = past if any(v is not None for v in past.values()) else None
        hits = T.evaluate(snapshot, past, fair_value, has_depth=True,
                          prev=H.previous(upto, day, sym),
                          prior=T.prior_metrics(upto, sym, before=day))
        if 'price' in T.kill_axes(hits):
            out.append(day)
    return out


def _ticker_events(payload, sym):
    if not isinstance(payload, dict) or not isinstance(payload.get('tickers'), dict):
        return []
    row = payload['tickers'].get(sym)
    if not isinstance(row, dict) or not isinstance(row.get('events'), list):
        return []
    return [e for e in row['events'] if isinstance(e, dict)]


def contract_axis_days(snapshots, today, sym, window_days=WINDOW_DAYS):
    """Dates of confirmed `contract` filings for `sym` inside the window, deduplicated by url.

    `snapshots` are disclosures.json versions that already passed the provenance check.
    The filing's own date counts, not the collection date.
    """
    start = window_start(today, window_days)
    seen, days = set(), set()
    for payload in snapshots or ():
        for e in _ticker_events(payload, sym):
            if e.get('confirmed') is not True or e.get('axis') != CONTRACT:
                continue
            day = e.get('date')
            if not _iso(day) or not start < day <= today:
                continue
            key = e.get('url') or (e.get('rcept_no'), day)
            if key in seen:
                continue
            seen.add(key)
            days.add(day)
    return sorted(days)


def kill_evidence(price_days, contract_days):
    """Axes with at least one day in the window — what `state.propose` receives."""
    axes = set()
    if price_days:
        axes.add('price')
    if contract_days:
        axes.add(CONTRACT)
    return tuple(sorted(axes))


def filing_licences(disclosures, today, sym):
    """Confirmed filings in today's disclosures.json. Any filing date inside the collector
    window counts — the window overlaps a day so a late filing is not lost."""
    if not isinstance(disclosures, dict) or disclosures.get('as_of') != today:
        return []
    return [{'title': e.get('title'), 'url': e.get('url'), 'date': e.get('date')}
            for e in _ticker_events(disclosures, sym) if e.get('confirmed') is True]


_LABEL = r'[^\W_](?:-*[^\W_])*'          # letters/digits, hyphens only inside (xn--… too)
_SOURCE = re.compile(
    r'https?://'
    rf'(?:{_LABEL}\.)+'                    # at least one dot: a named site
    rf'(?=[^\W\d_]){_LABEL}\.?'            # top label starts with a letter; root dot allowed
    r'(?::(?P<port>\d{1,5}))?'
    r'(?:[/?#]\S*)?',                      # the rest: anything visible
    re.IGNORECASE | re.ASCII)


def _http(value):
    """A source a reader can open: `http(s)://` + a dotted host name, nothing else in front.

    One whitelist over the whole string. A parser accepted what a browser refuses
    (`https:///www.sec.gov/x` 2회차, `https://[v1.sec.gov]/x` 3회차) because it was asked
    for parts and each part looked fine; here a character the pattern does not name —
    bracket, `@`, backslash, space — cannot appear before the path at all.
    Host labels are ASCII letters/digits/inner hyphens — an IDN host goes in as `xn--…`,
    the form a browser's address bar copies — so an IP literal and a bare word are refused. Whether the page says what the event claims is
    outside this check.
    """
    m = _SOURCE.fullmatch(value) if isinstance(value, str) and value.isprintable() else None
    return bool(m) and (m['port'] is None or 0 < int(m['port']) <= 65535)


def check_run(run, tickers, recomputed, axes):
    """Research events the routine may add, and claims it may no longer make.

    Returns (accepted_events_by_ticker, problems). A problem is (ticker, check, message).
    `recomputed` maps ticker -> list of numeric keys, or None when deferred; `axes` maps
    ticker -> kill_evidence tuple.
    """
    accepted = {sym: [] for sym in tickers}
    problems = []
    if not run:
        return accepted, problems
    if not isinstance(run, dict):
        return accepted, [('-', 'event_shape', 'run.json 이 객체가 아니다')]
    if run.get('_error'):
        return accepted, [('-', 'event_shape', run['_error'])]

    events = run.get('events') or {}
    if not isinstance(events, dict):
        problems.append(('-', 'event_shape', 'run.json events 가 종목별 객체가 아니다'))
        events = {}
    for sym, items in events.items():
        if sym not in accepted:
            problems.append((sym, 'event_shape', f'알 수 없는 종목: {sym!r}'))
            continue
        if not isinstance(items, list):
            problems.append((sym, 'event_shape', 'events 가 목록이 아니다'))
            continue
        for e in items:
            if not isinstance(e, dict):
                problems.append((sym, 'event_shape', f'사건이 객체가 아니다: {e!r}'))
                continue
            names = ' '.join(str(e.get(k) or '') for k in ('key', 'kind', 'title')).lower()
            if any(key in names for key in T.TRIGGER_KEYS):
                problems.append((sym, 'numeric_as_event',
                                 f'수치 트리거 이름을 단 사건: {e.get("title")!r} — 수치 관측은 '
                                 '재계산한 트리거로만 인정된다'))
                continue
            if not (isinstance(e.get('title'), str) and e['title'].strip()) \
                    or not _http(e.get('source')):
                problems.append((sym, 'event_shape',
                                 f'사건에 제목이나 http(s) 출처가 없다: {e.get("title")!r}'))
                continue
            if e.get('confirmed') is True:
                accepted[sym].append({'title': e['title'].strip(), 'source': e['source']})

    claimed = run.get('triggers') or {}
    if isinstance(claimed, dict):
        for sym, hits in claimed.items():
            keys = recomputed.get(sym)
            for hit in hits if isinstance(hits, list) else [hits]:
                key = hit.get('key') if isinstance(hit, dict) else hit
                if keys is None or key not in keys:
                    problems.append((sym, 'fabricated_evidence',
                                     f'지어낸 근거 — 재계산되지 않은 수치 트리거 {key!r}'))
    else:
        problems.append(('-', 'fabricated_evidence', 'run.json triggers 꼴이 틀렸다'))

    claimed_axes = run.get('kill_evidence') or {}
    if isinstance(claimed_axes, dict):
        for sym, items in claimed_axes.items():
            have = set(axes.get(sym, ()))
            for axis in items if isinstance(items, (list, tuple)) else [items]:
                if axis not in have:
                    problems.append((sym, 'fabricated_evidence',
                                     f'지어낸 근거 — 계산되지 않은 kill 축 {axis!r}'))
    else:
        problems.append(('-', 'fabricated_evidence', 'run.json kill_evidence 꼴이 틀렸다'))
    return accepted, problems


def assess(today, tickers, *, watch, history_text, disclosures, snapshots,
           history_problem=None, run=None, notes=()):
    """Everything the gate and STEP 3 need, per ticker.

    `watch`/`disclosures` are None and `history_problem` is set when the IO layer refused
    a version (not the collector's, unreadable). Returns
    {'today', 'notes', 'problems', 'tickers': {sym: {...}}} where each ticker carries
    `numeric` (keys or None = deferred), `numeric_hits`, `filings`, `events`,
    `licences` (what licenses an edit or a move — T for propose), `price_days`,
    `contract_days` and `kill_evidence`.
    """
    notes = list(notes)
    rows, bad = (None, history_problem) if history_problem else parse_history(history_text)
    if bad:
        notes.append(f'{bad} — 가격 축 판정 불가, 수치 판정 보류')
        hits, deferred = None, bad
    else:
        hits, deferred = today_triggers(watch, rows, today)
        if deferred:
            notes.append(deferred)
    if isinstance(disclosures, dict):
        if disclosures.get('pending'):
            notes.append('disclosures.json pending — DART 공시 근거 없음')
        if disclosures.get('missing'):
            notes.append(f'disclosures.json missing — {disclosures["missing"]}')

    out = {}
    for sym in tickers:
        sym_hits = None if hits is None else list(hits.get(sym) or [])
        price = [] if bad else price_axis_days(rows, today, sym)
        contract = contract_axis_days(snapshots, today, sym)
        out[sym] = {
            'numeric': None if sym_hits is None else sorted({h['key'] for h in sym_hits}),
            'numeric_hits': sym_hits or [],
            'filings': filing_licences(disclosures, today, sym),
            'price_days': price,
            'contract_days': contract,
            'kill_evidence': kill_evidence(price, contract),
        }

    accepted, problems = check_run(
        run, tickers, {s: v['numeric'] for s, v in out.items()},
        {s: v['kill_evidence'] for s, v in out.items()})
    for sym, entry in out.items():
        entry['events'] = accepted[sym]
        entry['licences'] = sorted(
            set(entry['numeric'] or ())
            | {f'filing:{f["url"] or f["title"]}' for f in entry['filings']}
            | {f'event:{e["title"]}' for e in entry['events']})
    return {'today': today, 'notes': notes, 'problems': problems, 'tickers': out}
