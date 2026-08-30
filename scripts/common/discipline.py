"""승계되는 등급의 이동 규율 — 자산 스펙과 무관한 순수 코어.

US 멀티에셋 스탠스(`us/stance.py`)와 글로벌 채권 뷰(`bond/stance.py`)는 라벨과
트리거 재료가 다르지만 «어떻게 움직여도 되는가»의 규칙은 글자 그대로 같다.

  - 중립(0)에서 «멀어지는» 이동만 트리거 MET 를 요구한다. 0 은 베팅이 없다는 뜻이라
    거기서 멀어지는 것이 곧 베팅을 거는 행위다. 이 한 규칙이 리스크 축의 방향이
    서로 다른 자산군에 그대로 통한다.
  - 축소는 언제나 허용한다 — 감축은 즉시, 증대는 인내.
  - 하루 한 단계. 부호 전환은 0 을 거치므로 하루 만에 뒤집을 수 없다.
  - 마지막 변경 후 N 영업일 확대 잠금.

규칙이 한 벌이어야 하는 이유는 단순하다 — 두 벌이면 한쪽만 고쳐지는 날이 온다.
파이프라인별로 다른 것은 `assets` 스펙과 잠금 일수뿐이므로 그 둘만 인자로 받는다.

설계: docs/superpowers/specs/2026-08-31-global-bond-emp-design.md
"""

from datetime import date, timedelta

_OPS = {
    '>': lambda a, b: a > b,
    '>=': lambda a, b: a >= b,
    '<': lambda a, b: a < b,
    '<=': lambda a, b: a <= b,
}

DEFAULT_LOCK_BUSINESS_DAYS = 3


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


def increase_directions(grade, met_triggers):
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


class Discipline:
    """One pipeline's asset spec + the shared movement rules.

    `assets` maps key -> {'name', 'axis', 'labels': {grade: label}}. Extra keys in the
    spec are ignored here and belong to whoever renders it.
    """

    def __init__(self, assets, lock_business_days=DEFAULT_LOCK_BUSINESS_DAYS,
                 default_horizon='2-6주', extra_state_keys=()):
        self.assets = assets
        self.lock_business_days = lock_business_days
        self.default_horizon = default_horizon
        # Per-asset nuance fields carried through evaluation untouched (US uses
        # 'tilt'/'curve'); listing them keeps the core from knowing what they mean.
        self.extra_state_keys = tuple(extra_state_keys)

    def _asset(self, key):
        if key not in self.assets:
            raise ValueError(f'unknown asset: {key}')
        return self.assets[key]

    def grade_bounds(self, key):
        grades = self._asset(key)['labels']
        return min(grades), max(grades)

    def label_for(self, key, grade):
        labels = self._asset(key)['labels']
        if grade not in labels:
            lo, hi = min(labels), max(labels)
            raise ValueError(f'{key}: grade {grade} out of range [{lo}, {hi}]')
        return labels[grade]

    def evaluate_asset(self, key, state, metrics, report_date, stale=False):
        lo, hi = self.grade_bounds(key)
        grade = state['grade']
        if grade not in self._asset(key)['labels']:
            raise ValueError(f'{key}: stored grade {grade} out of range [{lo}, {hi}]')

        triggers = state.get('triggers') or {}
        inc = [evaluate_trigger(t, metrics) for t in triggers.get('increase') or []]
        dec = [evaluate_trigger(t, metrics) for t in triggers.get('decrease') or []]

        days_held = business_days_inclusive(state.get('since') or report_date, report_date)
        at_max = (grade > 0 and grade == hi) or (grade < 0 and grade == lo)
        met = [t for t in inc if t['status'] == 'MET']
        manual = [t for t in inc if t['status'] == 'MANUAL']

        directions = increase_directions(grade, met + manual)
        can_increase, block = False, None
        if at_max:
            block = 'at_max'
        elif days_held < self.lock_business_days and not stale:
            # A stale book means the routine skipped days; the calendar already
            # supplied the patience the lock exists to enforce.
            block = f'lock_{self.lock_business_days}bd'
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

        out = {
            'name': self._asset(key)['name'],
            'axis': self._asset(key)['axis'],
            'grade': grade,
            'label': self.label_for(key, grade),
            'since': state.get('since'),
            'days_held': days_held,
            'thesis': state.get('thesis'),
            'increase': inc,
            'decrease': dec,
            'can_increase': can_increase,
            'increase_block': block,
            'can_decrease': can_decrease,
            'allowed_grades': sorted(allowed),
            'manual_pending': [t.get('desc') for t in inc + dec
                               if t['status'] == 'MANUAL'],
        }
        for k in self.extra_state_keys:
            out[k] = state.get(k)
        return out

    def evaluate(self, book, metrics, report_date, max_gap_bd=3):
        """Yesterday's book + today's metrics -> what today's writer may do.

        Staleness is a business-day gap rather than an exact previous-session match,
        so a market holiday doesn't masquerade as a skipped routine run.
        """
        assets = (book or {}).get('assets') or {}
        if not assets:
            return {
                'report_date': report_date,
                'stance_date': None,
                'stale': False,
                'bootstrap': True,
                'horizon': (book or {}).get('horizon', self.default_horizon),
                'assets': {},
            }

        stance_date = book.get('report_date')
        stale = (bool(stance_date)
                 and business_days_inclusive(stance_date, report_date) > max_gap_bd)

        return {
            'report_date': report_date,
            'stance_date': stance_date,
            'stale': stale,
            'bootstrap': False,
            'horizon': book.get('horizon', self.default_horizon),
            'assets': {k: self.evaluate_asset(k, v, metrics, report_date, stale)
                       for k, v in assets.items()},
        }

    def validate_transition(self, key, old_grade, new_grade, asset_eval):
        """Gate check for a grade the writer produced. -> (ok, reason)."""
        lo, hi = self.grade_bounds(key)
        if not (lo <= new_grade <= hi):
            return False, 'out_of_range'
        if abs(new_grade - old_grade) > 1:
            # Sign flips fall out of this too: -1 -> +1 is two steps, so reversing a
            # position always costs a day at neutral.
            return False, 'two_step'
        if new_grade not in asset_eval.get('allowed_grades', []):
            return False, 'not_allowed'
        return True, None
