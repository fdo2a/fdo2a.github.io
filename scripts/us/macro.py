"""Macro logic: regime grid, policy path, and asset transmission — all inherited.

§8-매크로 is to the economy what §9 is to positioning. The dashboard used to re-derive
its read of the cycle every morning from whatever numbers happened to be on the table,
so "국면" was really just a restatement of the day's tape. Here the read is a *book*:
it carries over from yesterday and may only move when the economy actually said
something new.

The gatekeeper is deliberately not a price trigger but a **new data release**. Economic
regimes change when data changes; on a day with no release the axis scores are computed
from the same observations as yesterday and therefore cannot move. Freezing is a
consequence of the arithmetic, not a rule bolted on top of it.

Everything here is pure — no network, no clock. `evaluate()` takes yesterday's book plus
today's metrics and returns what today's writer is permitted to say.

Design: docs/superpowers/specs/2026-08-18-us-macro-logic-persistence-design.md
"""

from .stance import business_days_inclusive

# Both axes are momentum, not level — the vocabulary ("둔화/보합/가속") names a direction
# of travel, and a level-based grid would park the regime in one cell for quarters.
GROWTH_LABELS = {-1: '둔화', 0: '보합', 1: '가속'}
INFLATION_LABELS = {-1: '둔화', 0: '교착', 1: '재가속'}

# (growth, inflation) -> the one name the writer may use for that cell.
REGIME_NAMES = {
    (1, -1): '리플레이션',
    (1, 0): '확장',
    (1, 1): '과열',
    (0, -1): '골디락스',
    (0, 0): '교착',
    (0, 1): '비용압박',
    (-1, -1): '연착륙',
    (-1, 0): '냉각',
    (-1, 1): '스태그플레이션',
}

# Same keys as stance.ASSETS on purpose: the two sections are cross-checked row by row,
# and a transmission taxonomy of its own would make that comparison a judgement call.
TRANSMISSION_ASSETS = ('equities', 'bonds', 'fx', 'energy', 'metals', 'memory', 'ai_infra')

# Direction is read on the same axis as the matching stance grade (bonds = duration,
# fx = dollar), so agreement and conflict are just a sign comparison.
TRANSMISSION_LABELS = {-1: '비우호', 0: '중립', 1: '우호'}

# Assets are narrated in channel groups, not one row each. A regime reaches bonds and
# gold through the same real-rate channel and equities and energy through the same
# final-demand channel, so a row per asset makes the writer say the same thing four
# times — and buries the mechanism in a table cell nobody can read on a phone.
# Fixed, like the label vocabulary: a grouping that shifts day to day would leave the
# reader unable to tell a changed view from a changed layout.
TRANSMISSION_GROUPS = (
    ('rates', '실질금리 경로', ('bonds', 'metals')),
    ('demand', '최종수요 경로', ('equities', 'energy')),
    ('dollar', '달러·상대금리 경로', ('fx',)),
    ('ai_cycle', 'AI 캐펙스 사이클', ('memory', 'ai_infra')),
)

HORIZON = '3-6개월'

# Longer than the stance lock: a regime that flips weekly is not a regime.
LOCK_BUSINESS_DAYS = 5

# Axis score is a cross-sectional mean of per-indicator momentum z-scores, so a third of
# a standard deviation is already a broad, one-directional shift.
CUT = 0.33


def group_of(asset):
    for key, _, assets in TRANSMISSION_GROUPS:
        if asset in assets:
            return key
    raise ValueError(f'unknown transmission asset: {asset}')


def regime_name(growth, inflation):
    try:
        return REGIME_NAMES[(growth, inflation)]
    except KeyError:
        raise ValueError(f'regime out of range: growth={growth}, inflation={inflation}')


def classify(score, cut=CUT):
    """Axis score -> -1 / 0 / +1. None in, None out (never guess a missing axis)."""
    if score is None:
        return None
    if score > cut:
        return 1
    if score < -cut:
        return -1
    return 0


def _step(current, target):
    """One step from current toward target, or None when already there."""
    if target is None or target == current:
        return None
    return current + (1 if target > current else -1)


def _allowed_regimes(regime, implied, can_move):
    g, i = regime['growth'], regime['inflation']
    allowed = [[g, i]]
    if not can_move:
        return allowed
    # One axis per day. A diagonal would let the book cross two cells at once, which is
    # exactly the "국면이 하루 만에 뒤집혔다" failure this module exists to prevent.
    gn = _step(g, implied.get('growth'))
    if gn is not None and -1 <= gn <= 1:
        allowed.append([gn, i])
    inn = _step(i, implied.get('inflation'))
    if inn is not None and -1 <= inn <= 1:
        allowed.append([g, inn])
    return sorted(allowed)


def _transmission(prev, report_date, can_move):
    out = {}
    rows = prev or {}
    for key in TRANSMISSION_ASSETS:
        row = rows.get(key) or {}
        d = row.get('direction', 0)
        since = row.get('since') or report_date
        allowed = {d}
        # Stepping toward neutral is always available — dropping a macro claim needs no
        # new evidence, the same asymmetry the stance book uses for de-risking.
        if d != 0:
            allowed.add(0)
        if can_move:
            for nxt in (d - 1, d + 1):
                if -1 <= nxt <= 1:
                    allowed.add(nxt)
        out[key] = {
            'direction': d,
            'label': TRANSMISSION_LABELS.get(d),
            'channel': row.get('channel'),
            'confirm': row.get('confirm'),
            'since': since,
            'days_held': business_days_inclusive(since, report_date),
            'allowed_directions': sorted(allowed),
        }
    return out


def evaluate(macro, metrics, report_date, max_gap_bd=3):
    """Yesterday's macro book + today's metrics -> what today's writer may do."""
    m = metrics or {}
    new_releases = list(m.get('new_releases') or [])
    implied_g = classify(m.get('growth_score'))
    implied_i = classify(m.get('inflation_score'))
    implied = {
        'growth': implied_g,
        'inflation': implied_i,
        'name': (regime_name(implied_g, implied_i)
                 if implied_g is not None and implied_i is not None else None),
    }

    scores = {k: m.get(k) for k in
              ('growth_score', 'inflation_score', 'growth_diffusion', 'inflation_diffusion')}

    base = {
        'report_date': report_date,
        'macro_date': (macro or {}).get('report_date'),
        'horizon': (macro or {}).get('horizon', HORIZON),
        'scores': scores,
        'implied': implied,
        'new_releases': new_releases,
        # The prints worth taking apart today. Empty on a quiet day, which is exactly
        # when the anatomy block should not appear at all.
        'headline_releases': list(m.get('headline_releases') or []),
    }

    prev_regime = (macro or {}).get('regime')
    if not prev_regime:
        return {**base, 'stale': False, 'bootstrap': True, 'regime': None,
                'regime_change_allowed': False, 'regime_block': 'bootstrap',
                'allowed_regimes': [],
                'policy': {**((macro or {}).get('policy_path') or {}),
                           'change_allowed': True, 'change_block': None},
                'transmission': _transmission((macro or {}).get('transmission'),
                                              report_date, True)}

    macro_date = macro.get('report_date')
    stale = bool(macro_date) and business_days_inclusive(macro_date, report_date) > max_gap_bd

    since = prev_regime.get('since') or report_date
    days_held = business_days_inclusive(since, report_date)
    g, i = prev_regime['growth'], prev_regime['inflation']
    regime = {
        'growth': g,
        'inflation': i,
        'growth_label': GROWTH_LABELS[g],
        'inflation_label': INFLATION_LABELS[i],
        'name': regime_name(g, i),
        'since': since,
        'days_held': days_held,
        'thesis': prev_regime.get('thesis'),
    }

    if not new_releases:
        can_move, block = False, 'no_new_release'
    elif days_held < LOCK_BUSINESS_DAYS and not stale:
        # A stale book means the routine skipped sessions; the calendar already supplied
        # the patience the lock exists to enforce.
        can_move, block = False, 'lock_5bd'
    else:
        can_move, block = True, None

    allowed = _allowed_regimes(regime, implied, can_move)
    if can_move and len(allowed) == 1:
        can_move, block = False, 'scores_agree'

    policy = dict((macro or {}).get('policy_path') or {})
    policy['change_allowed'] = bool(new_releases)
    policy['change_block'] = None if new_releases else 'no_new_release'

    return {
        **base,
        'stale': stale,
        'bootstrap': False,
        'regime': regime,
        'regime_change_allowed': can_move,
        'regime_block': block,
        'allowed_regimes': allowed,
        'policy': policy,
        'transmission': _transmission(macro.get('transmission'), report_date,
                                      bool(new_releases)),
    }


def validate_regime_transition(old, new, macro_eval):
    """Gate check for the regime the writer produced. -> (ok, reason)."""
    g, i = new
    if not (-1 <= g <= 1 and -1 <= i <= 1):
        return False, 'out_of_range'
    if abs(g - old[0]) + abs(i - old[1]) > 1:
        return False, 'two_step'
    if [g, i] not in (macro_eval or {}).get('allowed_regimes', []):
        return False, 'not_allowed'
    return True, None


def conflicts(transmission, stance):
    """Assets where the macro direction and the stance grade point opposite ways.

    Both are read on the same axis, so this is a sign comparison — a neutral on either
    side is not a conflict, it is simply one side declining to take the view.
    """
    assets = (stance or {}).get('assets') or {}
    out = []
    for key, row in (transmission or {}).items():
        d = (row or {}).get('direction') or 0
        grade = (assets.get(key) or {}).get('grade') or 0
        if d and grade and (d > 0) != (grade > 0):
            out.append(key)
    return sorted(out)
