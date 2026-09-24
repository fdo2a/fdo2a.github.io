"""Official newsroom feeds: the part of STEP 2's research that a feed can answer.

`disclosure.py` mechanizes the regulator's filings. Company announcements (a customer
named, a production schedule, results) come first through the issuers' own newsrooms,
which the routine used to re-read by hand every evening to conclude, most days, that
nothing was new. This module records what each feed published since the previous
collection, so `quiet.py` can prove an empty day without a model call.

Coverage limit: Micron's IR feed and SEC's submissions API refuse this client (403,
2026-09-24), and customer newsrooms (NVIDIA, AMD) name suppliers too rarely to justify
a daily feed. Those are left to the earnings window and the Friday full sweep in
`quiet.py` — not to this file.

Non-core: a failed feed is recorded in `missing`, which makes the day "not provably
quiet" — the safe direction. It never blocks collection.

Pure except for `_fetch`.

Design: docs/superpowers/specs/2026-09-24-thesis-quiet-prefilter.md
"""

import ssl
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

FEEDS = (
    ('005930.KS', 'Samsung Newsroom · Semiconductors',
     'https://news.samsung.com/global/category/products/semiconductors/feed'),
    ('005930.KS', 'Samsung Newsroom · Corporate',
     'https://news.samsung.com/global/category/corporate/feed'),
    ('000660.KS', 'SK hynix Newsroom · Press', 'https://news.skhynix.com/en/category/press/feed/'),
    ('000660.KS', 'SK hynix Newsroom · IR', 'https://news.skhynix.com/en/category/ir/feed/'),
)

# No previous collection (first run, or a corrupt file): look back a day and a half so an
# item published between two weekday runs is not skipped.
FIRST_LOOKBACK = timedelta(hours=36)
# A previous stamp older than this is not trusted as the window start (a week of outage
# would otherwise dump every old item into one day).
MAX_WINDOW = timedelta(days=7)


def _context():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001 — fall back to the system store
        return ssl.create_default_context()


def _fetch(url, timeout=20):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (thesis-watch)'})
    with urllib.request.urlopen(req, timeout=timeout,  # noqa: S310 — fixed https URLs
                                context=_context()) as resp:
        return resp.read().decode('utf-8', errors='replace')


def parse(xml_text):
    """RSS 2.0 items → [{title, url, published(ISO UTC)}]; items without a date are dropped."""
    out = []
    for item in ET.fromstring(xml_text).iter('item'):
        title = (item.findtext('title') or '').strip()
        url = (item.findtext('link') or '').strip()
        raw = (item.findtext('pubDate') or '').strip()
        if not (title and url and raw):
            continue
        try:
            when = parsedate_to_datetime(raw)
        except (TypeError, ValueError):
            continue
        if when.tzinfo is None:
            continue
        out.append({'title': title, 'url': url,
                    'published': when.astimezone(timezone.utc).isoformat()})
    return out


def _since(prev, now):
    raw = (prev or {}).get('collected_at') if isinstance(prev, dict) else None
    try:
        when = datetime.fromisoformat(raw) if isinstance(raw, str) else None
    except ValueError:
        when = None
    if when is None or when.tzinfo is None or when >= now or now - when > MAX_WINDOW:
        return now - FIRST_LOOKBACK
    return when


def collect(prev, now, feeds=FEEDS, fetch=_fetch):
    """Items published in (previous collection, now]; never raises for a feed failure."""
    since = _since(prev, now)
    items, seen, missing = [], set(), []
    for ticker, source, url in feeds:
        try:
            parsed = parse(fetch(url))
        except Exception as exc:  # noqa: BLE001 — one dead feed must not stop the others
            missing.append(f'{source}: {type(exc).__name__}: {str(exc)[:120]}')
            continue
        for row in parsed:
            when = datetime.fromisoformat(row['published'])
            if since < when <= now and row['url'] not in seen:
                seen.add(row['url'])
                items.append({'ticker': ticker, 'source': source, **row})
    items.sort(key=lambda r: r['published'], reverse=True)
    return {'collected_at': now.isoformat(), 'since': since.isoformat(),
            'items': items, 'missing': missing}
