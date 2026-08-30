"""글로벌 채권 뷰 3축 — 듀레이션·커브·크레딧.

US 멀티에셋 스탠스와 같은 규율(`common/discipline.py`)을 쓰되 자산 스펙만 다르다.
채권 운용에서 «금리 방향」과 «커브 형태»와 «크레딧 리스크»는 서로 독립적인 베팅이라
한 축으로 뭉치면 표현이 안 된다 — 예컨대 듀레이션 중립이면서 스티프너는 흔한 포지션이고,
듀레이션 롱이면서 크레딧 UW(경기침체 베팅)도 마찬가지다.

부호 규약: **+ 는 언제나 «금리 하락·리스크 확대에 베팅»** 이 아니라 축마다 다르다.
  duration + = 듀레이션을 늘린다(금리 하락에 베팅)
  curve     + = 스티프너(장단기 금리차 확대에 베팅)
  credit    + = 크레딧 오버웨이트(스프레드 축소에 베팅)
복기 채점은 이 규약을 그대로 뒤집어 쓴다(`period_scorecard`).

설계: docs/superpowers/specs/2026-08-31-global-bond-emp-design.md
"""

from common.discipline import (  # noqa: F401  (재수출 — 게이트·평가 스크립트가 쓴다)
    Discipline,
    business_days_inclusive,
    evaluate_trigger,
)

AXES = {
    'duration': {
        'name': '듀레이션', 'axis': '벤치마크 대비 듀레이션',
        'labels': {-2: '숏 듀레이션', -1: '숏 바이어스', 0: '중립 듀레이션',
                   1: '롱 바이어스', 2: '롱 듀레이션'},
    },
    'curve': {
        'name': '커브', 'axis': '장단기 금리차',
        'labels': {-2: '플래트너', -1: '완만한 플래트너', 0: '커브 중립',
                   1: '완만한 스티프너', 2: '스티프너'},
    },
    'credit': {
        'name': '크레딧', 'axis': '국채 대비 스프레드 자산 비중',
        'labels': {-2: '크레딧 UW', -1: '소폭 UW', 0: '크레딧 중립',
                   1: '소폭 OW', 2: '크레딧 OW'},
    },
}

# 커브 축의 뉘앙스 — 2s10s 냐 5s30s 냐, 벨리를 어떻게 두느냐는 등급이 아니라 tilt 다.
SEGMENT_LABELS = ('프런트엔드', '벨리', '롱엔드', '전 구간')

LOCK_BUSINESS_DAYS = 3
HORIZON = '2-6주'

_D = Discipline(AXES, lock_business_days=LOCK_BUSINESS_DAYS,
                default_horizon=HORIZON, extra_state_keys=('tilt', 'segment'))


def grade_bounds(key):
    return _D.grade_bounds(key)


def label_for(key, grade):
    return _D.label_for(key, grade)


def evaluate_axis(key, state, metrics, report_date, stale=False):
    return _D.evaluate_asset(key, state, metrics, report_date, stale)


def evaluate(book, metrics, report_date, max_gap_bd=3):
    return _D.evaluate(book, metrics, report_date, max_gap_bd)


def validate_transition(key, old_grade, new_grade, axis_eval):
    return _D.validate_transition(key, old_grade, new_grade, axis_eval)


def bootstrap(report_date):
    """첫 회차 — 세 축 모두 중립에서 시작한다.

    중립 시작은 임의 선택이 아니다. 트리거 없이 등급을 못 움직이는 규율 아래에서
    0 이 아닌 값으로 시작하면 «근거 없이 걸린 베팅»이 잠금 기간 동안 유지된다.
    """
    return {
        'report_date': report_date,
        'horizon': HORIZON,
        'assets': {
            key: {
                'grade': 0,
                'since': report_date,
                'thesis': None,
                'tilt': None,
                'segment': None,
                'triggers': {'increase': [], 'decrease': []},
            }
            for key in AXES
        },
    }
