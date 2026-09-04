"""Multi-asset stance: controlled vocabulary, movement discipline, trigger evaluation.

The US morning brief's §8 used to re-derive its positioning from scratch every day,
so a single session's price move could flip the whole book (2026-07-29 "비중축소" ->
2026-07-30 "선별적 리스크온"). This module makes the stance a *position*: it carries
over from the previous day and may only move when a pre-declared trigger fires.

Everything here is pure — no network, no clock. `evaluate()` takes yesterday's stance
plus today's metrics and returns what today's writer is permitted to do.

이동 규율 자체는 `common/discipline.py` 로 옮겼다(2026-08-31). 여기 남은 것은 US
고유의 자산 스펙과, 기존 호출부를 그대로 유지하기 위한 얇은 위임뿐이다.

Design: docs/superpowers/specs/2026-08-17-us-multiasset-stance-persistence-design.md
"""

from common.discipline import (
    Discipline,
    business_days_inclusive,
    evaluate_trigger,
)


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

_D = Discipline(ASSETS, lock_business_days=LOCK_BUSINESS_DAYS,
                extra_state_keys=('tilt', 'curve'))

__all__ = ['ASSETS', 'CURVE_LABELS', 'LOCK_BUSINESS_DAYS', 'business_days_inclusive',
           'evaluate_trigger', 'grade_bounds', 'label_for', 'evaluate_asset',
           'evaluate', 'validate_transition']


def grade_bounds(key):
    return _D.grade_bounds(key)


def label_for(key, grade):
    return _D.label_for(key, grade)


def evaluate_asset(key, state, metrics, report_date, stale=False):
    return _D.evaluate_asset(key, state, metrics, report_date, stale)


def evaluate(stance, metrics, report_date, max_gap_bd=3):
    return _D.evaluate(stance, metrics, report_date, max_gap_bd)


def validate_transition(key, old_grade, new_grade, asset_eval):
    return _D.validate_transition(key, old_grade, new_grade, asset_eval)
