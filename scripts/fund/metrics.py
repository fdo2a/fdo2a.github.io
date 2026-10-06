"""Price-only readings for the trend-unit board.

Pure functions over close lists (oldest first, auto-adjusted). Every reading that
needs more history than it has returns None — a short series is a blank cell, never
an approximation. Cross-series readings align on shared session dates, the same rule
price_context.py lives by: positional pairing compares different days as soon as one
series trades a session the other does not.
"""

import math

YEAR = 252
MONTH = 21


def _ok(x):
    try:
        return x is not None and math.isfinite(float(x)) and float(x) > 0
    except (TypeError, ValueError):
        return False


def ret(closes, n):
    """% return over the last n sessions."""
    if not closes or len(closes) < n + 1:
        return None
    a, b = closes[-1 - n], closes[-1]
    if not (_ok(a) and _ok(b)):
        return None
    return (b / a - 1) * 100


def mom_12_1(closes):
    """12-1 momentum: t-252 -> t-21, the classic skip of the reversal month."""
    if not closes or len(closes) < YEAR + 1:
        return None
    a, b = closes[-1 - YEAR], closes[-1 - MONTH]
    if not (_ok(a) and _ok(b)):
        return None
    return (b / a - 1) * 100


def _returns(closes, n, log=False):
    if not closes or len(closes) < n + 1:
        return None
    tail = closes[-(n + 1):]
    if not all(_ok(x) for x in tail):
        return None
    if log:
        return [math.log(b / a) for a, b in zip(tail, tail[1:])]
    return [b / a - 1 for a, b in zip(tail, tail[1:])]


def vol(closes, n=60):
    """Annualised sample stdev of the last n daily log returns, in %."""
    r = _returns(closes, n, log=True)
    if not r or len(r) < 2:
        return None
    mean = sum(r) / len(r)
    var = sum((x - mean) ** 2 for x in r) / (len(r) - 1)
    return math.sqrt(var) * math.sqrt(YEAR) * 100


def _percentile(xs, q):
    """numpy's default (linear) percentile, q in [0, 1]."""
    s = sorted(xs)
    pos = (len(s) - 1) * q
    lo = math.floor(pos)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def hist_var(closes, n=60, conf=0.95):
    """One-day historical VaR from the last n simple returns: max(0, -q) in %, where q
    is the (1-conf) linear percentile. A window whose lower tail is still a gain has
    no loss to report, so it is 0 rather than a negative "VaR"."""
    r = _returns(closes, n)
    if not r:
        return None
    return max(0.0, -_percentile(r, 1 - conf) * 100)


def sma(closes, n):
    if not closes or len(closes) < n:
        return None
    tail = closes[-n:]
    if not all(_ok(x) for x in tail):
        return None
    return sum(tail) / n


def drawdown(closes, n=YEAR):
    """% below the highest close of the last n sessions (0 at a high). Needs n valid
    closes — a shorter history is not a 52-week high."""
    if not closes or len(closes) < n:
        return None
    tail = closes[-n:]
    if not all(_ok(x) for x in tail):
        return None
    return (closes[-1] / max(tail) - 1) * 100


def _align(a, da, b, db):
    if not (a and da and b and db) or len(a) != len(da) or len(b) != len(db):
        return None, None
    bmap = dict(zip(db, b))
    pa, pb = [], []
    for d, x in zip(da, a):
        if d in bmap:
            pa.append(x)
            pb.append(bmap[d])
    return pa, pb


def rel_ret(a, da, b, db, n):
    """%p excess of a over b across the last n shared sessions."""
    pa, pb = _align(a, da, b, db)
    ra, rb = ret(pa, n), ret(pb, n)
    if ra is None or rb is None:
        return None
    return ra - rb


def beta(a, da, b, db, n=60):
    """OLS beta of a's daily returns on b's over the last n shared sessions."""
    pa, pb = _align(a, da, b, db)
    ra, rb = _returns(pa, n), _returns(pb, n)
    if not ra or not rb:
        return None
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    vb = sum((y - mb) ** 2 for y in rb)
    if vb == 0:
        return None
    return cov / vb
