"""Daily append-only log of the numbers that matter, so we can see them move.

The single most informative number for these three names is where consensus FY1 EPS is
*heading* — the market cannot agree whether 2027 is up or down, and the direction it
converges is the real news. yfinance serves today's consensus and nothing else, so a
30-day change is only knowable if we record it ourselves. One missed day is one day of
blindness; the collector marks gaps rather than interpolating over them.

Lookups fall back to the nearest earlier date on purpose: exchange holidays mean the row
exactly N days back usually does not exist.

Pure file I/O — no network.

Design: docs/superpowers/specs/2026-08-24-thesis-watch-design.md
"""

import json
from datetime import date, timedelta
from pathlib import Path


def load(path):
    """Rows sorted by date. Missing file is empty; a corrupt line is skipped, not fatal."""
    p = Path(path)
    if not p.exists():
        return []
    rows = []
    for line in p.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and row.get('date'):
            rows.append(row)
    rows.sort(key=lambda r: r['date'])
    return rows


def append(path, row):
    """Add today's row, replacing any existing row for the same date."""
    rows = [r for r in load(path) if r['date'] != row['date']]
    rows.append(row)
    rows.sort(key=lambda r: r['date'])
    Path(path).write_text(
        '\n'.join(json.dumps(r, ensure_ascii=False) for r in rows) + '\n',
        encoding='utf-8')
    return rows


def value_on(rows, target_date, ticker, key):
    """Value as of `target_date`, falling back to the nearest earlier row.

    None when history does not reach back that far, or the ticker/key is absent — the
    caller must disable the dependent trigger rather than guess.
    """
    best = None
    for row in rows:
        if row['date'] > target_date:
            break
        value = row.get('tickers', {}).get(ticker, {}).get(key)
        if value is not None:
            best = value
    return best


def previous(rows, today, ticker):
    """The nearest observation of `ticker` strictly *before* `today`, or None.

    This is the baseline every crossing trigger is judged against. Strictly earlier
    matters: the collector appends today's row before the routine runs, so comparing
    against "the latest row" would compare today with itself and no state change could
    ever be detected. A gap is stepped over rather than interpolated — the last thing we
    actually saw is the honest comparison, and it is also the one a reader would make.
    """
    for row in sorted(rows, key=lambda r: r['date'], reverse=True):
        if row['date'] >= today:
            continue
        snapshot = row.get('tickers', {}).get(ticker)
        if snapshot:
            return snapshot
    return None


def days_ago(today, n):
    return (date.fromisoformat(today) - timedelta(days=n)).isoformat()


def has_depth(rows, minimum):
    """Whether the log is long enough for a lookback of `minimum` rows to mean anything."""
    return len(rows) >= minimum
