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

from common import standing as standing_mod
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


def thesis_for(key, m):
    """논거를 **저장하지 않고 매번 현재 데이터에서 만든다.**

    저장된 문자열로 두면 데이터가 갱신될 때마다 그 문장만 뒤처진다. 실제로 두 번 겪었다 —
    2026-08-31 에는 발행본 §6 과 §9 논거가 서로 다른 위치를 말했고,
    2026-09-01 에는 5년-30년 금리차가 76.1 대 75.4 로 갈렸다. 승계되는 것은
    **등급과 트리거**이지 문장이 아니다.
    """
    us = (m.get('curves') or {}).get('us') or {}
    ust = us.get('tenors') or {}
    st10 = (m.get('standing') or {}).get('us10y') or {}
    vol = m.get('vol') or {}
    vst = vol.get('standing') or {}
    hy = (m.get('credit') or {}).get('us_hy') or {}
    ccc = (m.get('credit') or {}).get('us_hy_ccc') or {}

    def num(v, d=2):
        return '—' if v is None else f'{v:,.{d}f}'

    # 위치는 **`plain` 이 만든 말**을 그대로 쓴다. 백분위는 계산에 맞는 말이지
    # 읽는 사람에게 그림을 그려 주는 말이 아니다(2026-09-02 사용자 지적).
    def where(st, short=False, form=None):
        pl = (st or {}).get('plain') or {}
        if form:
            return standing_mod.say(pl, form, short)
        return pl.get('short' if short else 'text') or ''

    if key == 'duration':
        # 변동성이 「낮아」는 손으로 박은 판단이었다 — MOVE 가 한가운데쯤인 날에도
        # 낮다고 우겼다(2026-09-01 실측). 값은 데이터가 말하고 문장은 판단만 한다.
        return (f'10년물 {num((ust.get("10Y") or {}).get("level"))}%는 '
                f'{where(st10, form="plain")}. 금리 변동성은 MOVE {num(vol.get("move"))}로 '
                f'{where(vst, short=True, form="plain")}. 방향을 걸 만한 촉매가 아직 약하다.')
    if key == 'curve':
        # 기준일이 어긋난 스프레드를 논거에 쓸 때는 그 사실을 숨기지 않는다.
        # 발행본 본문은 밝히는데 스탠스 표만 안 밝히면 같은 값이 두 얼굴을 갖는다.
        mark = '' if us.get('spread_2s10s_aligned') else '*'
        note = ('' if us.get('spread_2s10s_aligned')
                else ' (*는 만기별 기준일이 달라 근거를 본문에 병기)')
        return (f'2년-10년 {num(us.get("spread_2s10s_bp"), 1)}bp{mark}, '
                f'5년-30년 {num(us.get("spread_5s30s_bp"), 1)}bp. '
                f'어느 쪽으로도 치우치지 않은 구간이다.{note}')
    if key == 'credit':
        return (f'하이일드 스프레드 {num(hy.get("bp"), 0)}bp는 '
                f'{where(hy.get("standing"), form="clause")}, CCC 이하는 '
                f'{num(ccc.get("bp"), 0)}bp로 '
                f'{where(ccc.get("standing"), short=True, form="plain")}. '
                f'지수는 좁고 바닥층은 넓다.')
    return ''


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
