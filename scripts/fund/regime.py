"""Market regime on price alone: 강세 / 횡보 / 단기 약세 / 장기 약세.

The fund's own regime call reads a 12-month trend and a 3-month earnings revision.
We have no revision feed yet, so this is the price half only and says so in `basis`
— the renderer prints it every time, so the reader never mistakes it for the full
call. 「횡보」 is the residual: whatever meets neither the bull nor a bear rule,
including turning points. That is printed too.

No state file. Each day's raw call is recomputed from history for the last
LOOKBACK sessions. The confirmed state starts at the first run of CONFIRM identical
raw calls in that window — not at the first value, or an alternating prefix would
decide the answer — and changes only when another CONFIRM-run arrives. A state that
was already in force when the window opened has an unknown start: `since_exact` is
false and the page says 「최소 N거래일」.
"""

from fund import metrics as m

STATES = ('강세', '횡보', '단기 약세', '장기 약세')
BASIS = '가격 기준(이익 수정 미반영)'
RESIDUAL_NOTE = '횡보는 강세·약세 조건 어디에도 들지 않는 잔여 범주(전환 구간 포함)'

DD_THRESHOLD = -5.0    # % below the 52-week high that marks a correction
SLOPE_LAG = 20         # sessions back for the 200-day average's slope
CONFIRM = 3            # straight sessions before a new state is confirmed
LOOKBACK = 260         # raw calls recomputed
DAY_MIN = m.YEAR       # closes one raw call needs (52-week high; covers 200+20)
MIN_CLOSES = LOOKBACK + DAY_MIN - 1   # sessions: 260 calls, the first needing 252


def classify(close, s50, s200, s200_prev, r3m, dd):
    if any(x is None for x in (close, s50, s200, s200_prev, r3m, dd)):
        return None
    if close < s200 and s200 < s200_prev:
        return '장기 약세'
    if dd <= DD_THRESHOLD and close < s50:
        return '단기 약세'
    if close > s200 and close > s50 and r3m > 0 and dd > DD_THRESHOLD:
        return '강세'
    return '횡보'


def _win(pmap, cal, i, n):
    """Prices on cal[i-n+1..i], or None if any session lacks one."""
    if i - n + 1 < 0:
        return None
    out = [pmap.get(d) for d in cal[i - n + 1:i + 1]]
    return out if all(x is not None for x in out) else None


def inputs_on(pmap, cal, i):
    """The six inputs on session cal[i], every one anchored on the calendar. None if
    any window lacks a price — a gap is never bridged by the next observation."""
    w50, w200 = _win(pmap, cal, i, 50), _win(pmap, cal, i, 200)
    w200p, wyr = _win(pmap, cal, i - SLOPE_LAG, 200), _win(pmap, cal, i, m.YEAR)
    r0 = pmap.get(cal[i - 63]) if i >= 63 else None
    if not (w50 and w200 and w200p and wyr and r0):
        return None
    close = wyr[-1]
    return {'close': close, 'sma50': sum(w50) / 50, 'sma200': sum(w200) / 200,
            'sma200_prev': sum(w200p) / 200, 'ret_3m': (close / r0 - 1) * 100,
            'drawdown': (close / max(wyr) - 1) * 100}


def inputs_at(closes):
    """Inputs on the last of an unbroken close list (positions = sessions)."""
    cal = list(range(len(closes)))
    return inputs_on(dict(zip(cal, closes)), cal, len(closes) - 1)


def _raw(inp):
    if not inp:
        return None
    return classify(inp['close'], inp['sma50'], inp['sma200'], inp['sma200_prev'],
                    inp['ret_3m'], inp['drawdown'])


def confirm(seq, k=CONFIRM):
    """Confirmed state per position. None until the first k-run of one raw call;
    after that a change needs k in a row. A None raw call breaks the run."""
    out, state, run_label, run = [], None, None, 0
    for raw in seq:
        if raw is None:
            run_label, run = None, 0
        else:
            if raw == run_label:
                run += 1
            else:
                run_label, run = raw, 1
            if raw != state and run >= k:
                state = raw
        out.append(state)
    return out


def state(seq, dates, k=CONFIRM):
    states = confirm(seq, k)
    if not states or states[-1] is None:
        return None
    name = states[-1]
    i = len(states) - 1
    while i > 0 and states[i - 1] == name:
        i -= 1
    # the confirming run began on the raw call k-1 sessions before confirmation
    start = i
    while start > 0 and seq[start - 1] == name:
        start -= 1
    prev = states[i - 1] if i > 0 else None
    exact = prev is not None
    # trailing raw calls that differ from the confirmed state and have not confirmed
    pending, n = None, 0
    j = len(seq) - 1
    if seq[j] is not None and seq[j] != name:
        pending = seq[j]
        while j >= 0 and seq[j] == pending:
            n += 1
            j -= 1
    return {
        'name': name,
        'since': dates[start],
        'since_exact': exact,
        'prev': prev,
        'sessions_held': len(seq) - start,
        'pending_name': pending,
        'pending_sessions': n if pending else 0,
    }


def raw_series(closes, dates, cal):
    """(session dates, raw calls) for the last LOOKBACK sessions of `cal`."""
    pmap = dict(zip(dates, closes))
    first = len(cal) - LOOKBACK
    window = cal[first:]
    seq = [_raw(inputs_on(pmap, cal, i)) if cal[i] in pmap else None
           for i in range(first, len(cal))]
    return window, seq


def compute(closes, dates, cal=None):
    if not closes or len(closes) != len(dates):
        return None
    cal = list(cal) if cal is not None else list(dates)
    if len(cal) < MIN_CLOSES or cal[-1] != dates[-1]:
        return None
    ds, seq = raw_series(closes, dates, cal)
    st = state(seq, ds)
    if st is None:
        return None
    pmap = dict(zip(dates, closes))
    today = inputs_on(pmap, cal, len(cal) - 1) or dict.fromkeys(
        ('close', 'sma50', 'sma200', 'sma200_prev', 'ret_3m', 'drawdown'))
    inputs = {k: (round(v, 2) if v is not None else None) for k, v in today.items()}
    inputs['as_of'] = dates[-1]
    span = cal[-(LOOKBACK + DAY_MIN - 1):]
    return {
        **st,
        'raw_today': seq[-1],
        'history_start': ds[0],
        'missing_sessions': [x for x in span if x not in pmap],
        'inputs': inputs,
        'rules': {'drawdown_pct': DD_THRESHOLD, 'slope_lag': SLOPE_LAG,
                  'confirm_sessions': CONFIRM, 'lookback_sessions': LOOKBACK},
        'basis': BASIS,
        'residual_note': RESIDUAL_NOTE,
    }
