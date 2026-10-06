"""US session calendar: weekdays minus NYSE holidays (data/market_holidays.json).

Independent of any price series, so a date every series dropped still counts as a
session and shows up as a gap instead of silently joining two days into one. Only
used inside the file's stated coverage (`valid_from`..`valid_through`); outside it
the caller falls back to a majority vote over the fund universe.
"""

import datetime
import json


def load(path):
    try:
        with open(path, encoding='utf-8') as fh:
            us = json.load(fh).get('us')
    except (OSError, ValueError):
        return None
    if not us or not us.get('valid_from') or not us.get('valid_through'):
        return None
    return us


def us_sessions(start, end, holidays):
    if not holidays or start < holidays['valid_from'] or end > holidays['valid_through']:
        return None
    closed = set(holidays.get('dates') or [])
    d, stop = datetime.date.fromisoformat(start), datetime.date.fromisoformat(end)
    out = []
    while d <= stop:
        s = d.isoformat()
        if d.weekday() < 5 and s not in closed:
            out.append(s)
        d += datetime.timedelta(days=1)
    return out
