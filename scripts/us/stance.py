"""Multi-asset stance: controlled vocabulary, movement discipline, trigger evaluation.

The US morning brief's §8 used to re-derive its positioning from scratch every day,
so a single session's price move could flip the whole book (2026-07-29 "비중축소" ->
2026-07-30 "선별적 리스크온"). This module makes the stance a *position*: it carries
over from the previous day and may only move when a pre-declared trigger fires.

Everything here is pure — no network, no clock. `evaluate()` takes yesterday's stance
plus today's metrics and returns what today's writer is permitted to do.

Design: docs/superpowers/specs/2026-08-17-us-multiasset-stance-persistence-design.md
"""

from datetime import date, timedelta

# Direction is defined against 0 (neutral), not against "risk on/off" — neutral means
# no bet, so moving away from it is always the act of putting a bet on. That keeps one
# rule working across asset classes whose risk axes point different ways.
ASSETS = {
    'equities': {
        'name': '주식', 'axis': '절대비중',
        'labels': {-2: '비중축소', -1: '소폭축소', 0: '중립', 1: '소폭확대', 2: '비중확대'},
    },
    'bonds': {
        'name': '채권', 'axis': '듀레이션',
        'labels': {-2: '숏 듀레이션', -1: '숏 바이어스', 0: '중립 듀레이션',
                   1: '롱 바이어스', 2: '롱 듀레이션'},
    },
    'fx': {
        'name': 'FX', 'axis': '달러 방향',
        'labels': {-2: '달러 숏', -1: '달러 소폭 숏', 0: '달러 중립',
                   1: '달러 소폭 롱', 2: '달러 롱'},
    },
    'energy': {
        'name': '원자재·에너지', 'axis': '절대비중',
        'labels': {-2: '비중축소', -1: '소폭축소', 0: '중립', 1: '소폭확대', 2: '비중확대'},
    },
    'metals': {
        'name': '원자재·귀금속', 'axis': '절대비중',
        'labels': {-2: '비중축소', -1: '소폭축소', 0: '중립', 1: '소폭확대', 2: '비중확대'},
    },
    'memory': {
        'name': '메모리', 'axis': '주식 대비 상대비중',
        'labels': {-1: 'UW', 0: '중립', 1: 'OW'},
    },
    'ai_infra': {
        'name': 'AI 인프라', 'axis': '주식 대비 상대비중',
        'labels': {-1: 'UW', 0: '중립', 1: 'OW'},
    },
}

# Bond curve shape rides alongside the duration grade — same closed-vocabulary rule.
CURVE_LABELS = ('플래트너', '커브 중립', '스티프너', '벨리 OW')

LOCK_BUSINESS_DAYS = 3

_OPS = {
    '>': lambda a, b: a > b,
    '>=': lambda a, b: a >= b,
    '<': lambda a, b: a < b,
    '<=': lambda a, b: a <= b,
}


def _asset(key):
    if key not in ASSETS:
        raise ValueError(f'unknown asset: {key}')
    return ASSETS[key]


def grade_bounds(key):
    grades = _asset(key)['labels']
    return min(grades), max(grades)


def label_for(key, grade):
    labels = _asset(key)['labels']
    if grade not in labels:
        lo, hi = min(labels), max(labels)
        raise ValueError(f'{key}: grade {grade} out of range [{lo}, {hi}]')
    return labels[grade]


def business_days_inclusive(start, end):
    """Weekdays in [start, end], both ends counted. Never less than 1.

    Holidays are ignored — a lock that runs one session long on a holiday week is a
    far smaller error than the whipsaw this exists to prevent.
    """
    a, b = date.fromisoformat(str(start)), date.fromisoformat(str(end))
    if b < a:
        return 1
    n, cur = 0, a
    while cur <= b:
        if cur.weekday() < 5:
            n += 1
        cur += timedelta(days=1)
    return max(n, 1)


def evaluate_trigger(trigger, metrics):
    """One trigger against today's metrics -> MET / NOT_MET / UNKNOWN / MANUAL."""
    out = dict(trigger)
    if trigger.get('kind') == 'event':
        out['status'] = 'MANUAL'
        out['actual'] = None
        return out

    name = trigger.get('metric')
    actual = metrics.get(name) if metrics else None
    op = _OPS.get(trigger.get('op'))
    out['actual'] = actual
    if actual is None or op is None:
        # A metric we failed to collect can never justify adding risk. Holding is the
        # safe default, so UNKNOWN is deliberately not NOT_MET (which would read as a
        # tested-and-failed condition in the published brief).
        out['status'] = 'UNKNOWN'
    else:
        out['status'] = 'MET' if op(actual, trigger.get('value')) else 'NOT_MET'
    return out


def _increase_directions(grade, met_triggers):
    """Which way |grade| may grow. Away from zero is implied once a side is picked;
    at neutral the trigger must say which side it is opening."""
    if grade > 0:
        return {1}
    if grade < 0:
        return {-1}
    dirs = set()
    for t in met_triggers:
        toward = t.get('toward')
        if toward == '+':
            dirs.add(1)
        elif toward == '-':
            dirs.add(-1)
    return dirs


def evaluate_asset(key, state, metrics, report_date, stale=False):
    lo, hi = grade_bounds(key)
    grade = state['grade']
    if grade not in ASSETS[key]['labels']:
        raise ValueError(f'{key}: stored grade {grade} out of range [{lo}, {hi}]')

    triggers = state.get('triggers') or {}
    inc = [evaluate_trigger(t, metrics) for t in triggers.get('increase') or []]
    dec = [evaluate_trigger(t, metrics) for t in triggers.get('decrease') or []]

    days_held = business_days_inclusive(state.get('since') or report_date, report_date)
    at_max = (grade > 0 and grade == hi) or (grade < 0 and grade == lo)
    met = [t for t in inc if t['status'] == 'MET']
    manual = [t for t in inc if t['status'] == 'MANUAL']

    directions = _increase_directions(grade, met + manual)
    can_increase, block = False, None
    if at_max:
        block = 'at_max'
    elif days_held < LOCK_BUSINESS_DAYS and not stale:
        # A stale stance means the routine skipped days; the calendar already supplied
        # the patience the lock exists to enforce.
        block = 'lock_3bd'
    elif not met and not manual:
        block = 'no_trigger_met'
    elif not directions:
        block = 'no_direction'
    else:
        can_increase = True
        block = None if met else 'manual'

    can_decrease = grade != 0

    allowed = {grade}
    if can_decrease:
        allowed.add(grade - 1 if grade > 0 else grade + 1)
    if can_increase:
        for d in directions:
            nxt = grade + d
            if lo <= nxt <= hi:
                allowed.add(nxt)

    return {
        'name': ASSETS[key]['name'],
        'axis': ASSETS[key]['axis'],
        'grade': grade,
        'label': label_for(key, grade),
        'tilt': state.get('tilt'),
        'curve': state.get('curve'),
        'since': state.get('since'),
        'days_held': days_held,
        'thesis': state.get('thesis'),
        'increase': inc,
        'decrease': dec,
        'can_increase': can_increase,
        'increase_block': block,
        'can_decrease': can_decrease,
        'allowed_grades': sorted(allowed),
        'manual_pending': [t.get('desc') for t in inc + dec if t['status'] == 'MANUAL'],
    }


def evaluate(stance, metrics, report_date, max_gap_bd=3):
    """Yesterday's stance + today's metrics -> what today's writer may do.

    Staleness is measured as a business-day gap rather than an exact previous-session
    match, so a market holiday doesn't masquerade as a skipped routine run.
    """
    assets = (stance or {}).get('assets') or {}
    if not assets:
        return {
            'report_date': report_date,
            'stance_date': None,
            'stale': False,
            'bootstrap': True,
            'horizon': (stance or {}).get('horizon', '2-6주'),
            'assets': {},
        }

    stance_date = stance.get('report_date')
    stale = bool(stance_date) and business_days_inclusive(stance_date, report_date) > max_gap_bd

    return {
        'report_date': report_date,
        'stance_date': stance_date,
        'stale': stale,
        'bootstrap': False,
        'horizon': stance.get('horizon', '2-6주'),
        'assets': {k: evaluate_asset(k, v, metrics, report_date, stale)
                   for k, v in assets.items()},
    }


def validate_transition(key, old_grade, new_grade, asset_eval):
    """Gate check for a grade the writer produced. -> (ok, reason)."""
    lo, hi = grade_bounds(key)
    if not (lo <= new_grade <= hi):
        return False, 'out_of_range'
    if abs(new_grade - old_grade) > 1:
        # Sign flips fall out of this too: -1 -> +1 is two steps, so reversing a
        # position always costs a day at neutral.
        return False, 'two_step'
    if new_grade not in asset_eval.get('allowed_grades', []):
        return False, 'not_allowed'
    return True, None
