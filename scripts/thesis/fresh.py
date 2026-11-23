"""Which session a thesis number belongs to, and whether a snapshot is fresh.

The collector used to stamp data with the wall-clock KST date. Scheduled runs arrive
7.5-10 hours late (01:00-04:00 KST, US mid-session), so MU intraday prices were recorded
as closes on 36 of 59 rows, KR closes two sessions old passed as "today", and a late run
opened the next day's row with an older KR price (2026-11-23 investigation). A label is
now a property of the data, decided by the exchange calendar:

    kr  the latest KR session whose close (16:00 KST) has passed
    us  the latest US session closed (17:00 ET) before that KR close — the pairing the
        page has always meant: "today's Samsung/Hynix close, Micron's previous close"

so a run at 16:05 and the same day's scheduled run arriving at 02:37 the next morning get
the same sessions. An observation is *confirmed* when it was taken after its session's
close; `observed_at` is what proves it.

Pure apart from the clock in `now_for`. Calendar: data/market_holidays.json (the same file
scripts/ci/routine_due.py reads; its kr_session/us_session use the same cut-offs).
"""

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

KST = timezone(timedelta(hours=9))
SEOUL = ZoneInfo('Asia/Seoul')
NY = ZoneInfo('America/New_York')
CUTOFF = {'kr': (SEOUL, time(16, 0)), 'us': (NY, time(17, 0))}
MARKET = {'005930.KS': 'kr', '000660.KS': 'kr', 'MU': 'us'}
STALE_AFTER = timedelta(hours=3)
PUBLISH_AT = time(16, 0)          # the local publisher's daily slot (codex automation)
# Carried as one block: they all come from the same bar series.
PRICE_FIELDS = ('price', 'price_date', 'observed_at', 'chg_20d_pct', 'pct_from_52w_high')


class CalendarGap(Exception):
    """The holiday calendar does not cover this date — do not guess a session."""


def calendar(raw):
    out = {}
    for market in ('kr', 'us'):
        block = (raw or {}).get(market) or {}
        out[market] = (frozenset(block.get('dates') or ()),
                       date.fromisoformat(block['valid_through']))
    return out


def _latest_closed(market, when, cal):
    zone, cut = CUTOFF[market]
    local = when.astimezone(zone)
    holidays, valid = cal[market]
    if local.date() > valid:
        raise CalendarGap(f'{market} 휴장 달력이 {valid} 에서 끝난다 — {local.date()} 의 세션을 정하지 않는다')
    d = local.date() if local.time() >= cut else local.date() - timedelta(days=1)
    while d.weekday() >= 5 or d.isoformat() in holidays:
        d -= timedelta(days=1)
    return d


def closed_at(market, session):
    zone, cut = CUTOFF[market]
    return datetime.combine(date.fromisoformat(session), cut, tzinfo=zone)


def sessions(now, cal):
    kr = _latest_closed('kr', now, cal)
    us = _latest_closed('us', closed_at('kr', kr.isoformat()), cal)
    return {'kr': kr.isoformat(), 'us': us.isoformat()}


def keep_upto(dates, session):
    """Mask of bars to keep — a bar dated after the expected session is unfinished
    (intraday) or a pre-open placeholder."""
    return [d <= session for d in dates]


def _when(stamp):
    try:
        value = datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return None
    return value if value.tzinfo else None


def confirmed(row, market):
    seen = _when((row or {}).get('observed_at'))
    day = (row or {}).get('price_date')
    return bool(seen and day) and seen >= closed_at(market, day)


def merge_price(new, old, market):
    """`new` with the price block of `old` when old is a *confirmed* later session.

    A late run whose Yahoo response lacks the latest bar must not pull the price back
    (11-16 196,800 → 11-17 row 206,000 of 11-13). Old values without `observed_at` —
    every row before this change, including intraday MU — never win.
    """
    out = dict(new)
    if old and confirmed(old, market) and (old.get('price_date') or '') > (new.get('price_date') or ''):
        for field in PRICE_FIELDS:
            out[field] = old.get(field)
    return out


def derive(row):
    price = row.get('price')
    if price and row.get('bvps'):
        row['pb'] = round(price / row['bvps'], 2)
    if price and row.get('eps_fy1'):
        row['pe_fy1'] = round(price / row['eps_fy1'], 2)
    return row


def stale(tickers, sess):
    reasons = []
    for sym, row in (tickers or {}).items():
        market = MARKET.get(sym)
        if market is None:
            continue
        day = (row or {}).get('price_date')
        if day != sess[market]:
            reasons.append(f'{sym} 주가가 {day} 것이다 — 기대 세션 {sess[market]}')
        elif not confirmed(row, market):
            reasons.append(f'{sym} 주가({day})를 장 마감 전에 받았다')
    return reasons


def check(now, watch, cal):
    """Reasons the snapshot cannot be judged as of `now`; [] means fresh."""
    if not isinstance(watch, dict) or not isinstance(watch.get('tickers'), dict):
        return ['watch.json 이 없다']
    try:
        sess = sessions(now, cal)
    except CalendarGap as e:
        return [str(e)]
    reasons = []
    if not watch.get('complete'):
        reasons.append(f'watch.json 불완전 — missing={watch.get("missing")} '
                       f'stale={watch.get("stale")}')
    if watch.get('as_of') != sess['kr']:
        reasons.append(f'watch.json as_of {watch.get("as_of")} — 기대 KR 세션 {sess["kr"]}')
    reasons += stale(watch['tickers'], sess)
    seen = _when(watch.get('collected_at'))
    if seen is None or seen < now - STALE_AFTER:
        reasons.append(f'수집 시각 {watch.get("collected_at")} — 3시간보다 오래됐다')
    return reasons


def now_for(today):
    """The moment a judgement for `today` is made: the real clock on the day itself,
    the publisher's slot when replaying a past day."""
    real = datetime.now(KST)
    if today == real.date().isoformat():
        return real
    return datetime.combine(date.fromisoformat(today), PUBLISH_AT, tzinfo=KST)
