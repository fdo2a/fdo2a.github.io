"""The carried-over book: what we decided yesterday, and what today is allowed to do.

Without this, "is the thesis strengthening or breaking?" gets re-derived from scratch
every morning, and a single day's headline can flip the whole judgment — the failure the
brief's §8 and the multi-asset stance both had to be rebuilt to avoid.

The asymmetry is deliberate and matches the stance book: **worsening is immediate,
recovery waits.** Cutting risk on a suspicion is cheap; restoring conviction on one good
headline is how you get whipsawed.

Pure — no network, no clock. `today` is always passed in.

Design: docs/superpowers/specs/2026-08-24-thesis-watch-design.md
"""

from dataclasses import dataclass, field
from datetime import date, timedelta

# Controlled vocabulary, ordered best -> worst. Free-form wording is rejected: the whole
# point is that today's label is comparable to yesterday's.
GRADES = ('홀딩 강화', '주의', '비중 조절 검토', 'kill condition')

RECOVERY_LOCK_BUSINESS_DAYS = 3

# A kill needs corroboration from two different kinds of evidence. Price alone is noise;
# a contract loss alone might be priced in already. Both together is a thesis break.
KILL_AXES = ('price', 'contract')

# Relative change below which a number is treated as unmoved.
MOVE_EPSILON = 0.005


@dataclass
class Proposal:
    grade: str
    grade_since: str
    allowed: bool
    reasons: list = field(default_factory=list)


def _d(iso):
    return date.fromisoformat(iso)


def _business_days_between(start, end):
    days, cur = 0, start
    while cur < end:
        cur += timedelta(days=1)
        if cur.weekday() < 5:
            days += 1
    return days


def propose(current, wanted, today, triggers, kill_evidence=()):
    """Clamp a wanted grade to what the discipline permits.

    Returns a Proposal carrying the grade actually allowed plus the rule names that
    constrained it, so the page and the notification can quote the reason.
    """
    if wanted not in GRADES:
        raise ValueError(f'통제 어휘 밖의 등급: {wanted!r} (허용: {GRADES})')
    now = current.get('grade', GRADES[0])
    if now not in GRADES:
        raise ValueError(f'통제 어휘 밖의 기존 등급: {now!r}')

    since = current.get('grade_since') or today
    reasons = []

    if wanted == now:
        return Proposal(now, since, allowed=True, reasons=reasons)

    # Movement always needs a trigger. Re-reading the same facts is not a trigger.
    if not triggers:
        reasons.append('no_trigger')
        return Proposal(now, since, allowed=False, reasons=reasons)

    i_now, i_want = GRADES.index(now), GRADES.index(wanted)
    worsening = i_want > i_now

    if not worsening:
        elapsed = _business_days_between(_d(since), _d(today))
        if elapsed < RECOVERY_LOCK_BUSINESS_DAYS:
            reasons.append('recovery_locked')
            return Proposal(now, since, allowed=False, reasons=reasons)

    # One step per day, in either direction. No diagonals.
    step = 1 if worsening else -1
    target = i_now + step
    if abs(i_want - i_now) > 1:
        reasons.append('one_step')

    if GRADES[target] == 'kill condition':
        if not set(KILL_AXES).issubset(set(kill_evidence)):
            reasons.append('kill_needs_two_axes')
            target = i_now  # hold; a single broken axis stops at the prior grade

    grade = GRADES[target]
    changed = grade != now
    return Proposal(grade, today if changed else since, allowed=changed, reasons=reasons)


def numbers_moved(last_seen, today_values):
    """Names of the tracked numbers that actually moved since we last looked.

    If nothing moved, no numeric trigger can arithmetically fire — the gate uses this to
    catch a routine that "found" a change in identical data.
    """
    moved = []
    for key, before in sorted(last_seen.items()):
        after = today_values.get(key)
        if after is None or before is None:
            continue
        if not isinstance(before, (int, float)) or not isinstance(after, (int, float)):
            if before != after:
                moved.append(key)
            continue
        if before == 0:
            if after != 0:
                moved.append(key)
        elif abs(after - before) / abs(before) > MOVE_EPSILON:
            moved.append(key)
    return moved
