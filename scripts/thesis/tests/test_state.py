import pytest

from thesis import state as S


def book(grade='홀딩 강화', since='2026-08-20'):
    return {'grade': grade, 'grade_since': since, 'last_seen': {}, 'open_questions': []}


# ── 통제 어휘 ──

def test_grades_are_ordered_worst_last():
    assert S.GRADES.index('홀딩 강화') < S.GRADES.index('주의')
    assert S.GRADES.index('주의') < S.GRADES.index('비중 조절 검토')
    assert S.GRADES.index('비중 조절 검토') < S.GRADES.index('kill condition')


def test_unknown_grade_is_rejected():
    with pytest.raises(ValueError):
        S.propose(book(), '적극 매수', today='2026-08-24', triggers=['x'])


# ── 하루 한 단계 ──

def test_one_step_worse_is_allowed():
    r = S.propose(book('홀딩 강화'), '주의', today='2026-08-24', triggers=['bear_proximity'])
    assert r.allowed and r.grade == '주의'


def test_two_steps_worse_is_clamped_to_one():
    r = S.propose(book('홀딩 강화'), '비중 조절 검토', today='2026-08-24', triggers=['x'])
    assert r.grade == '주의'
    assert 'one_step' in r.reasons


def test_diagonal_to_kill_is_clamped():
    r = S.propose(book('홀딩 강화'), 'kill condition', today='2026-08-24',
                  triggers=['consensus_floor'], kill_evidence=('price', 'contract'))
    assert r.grade == '주의'


# ── kill 은 두 축이 함께 깨질 때만 ──

def test_kill_requires_two_axes():
    r = S.propose(book('비중 조절 검토'), 'kill condition', today='2026-08-24',
                  triggers=['consensus_floor'], kill_evidence=('price',))
    assert r.grade != 'kill condition'
    assert 'kill_needs_two_axes' in r.reasons


def test_kill_allowed_with_both_axes():
    r = S.propose(book('비중 조절 검토'), 'kill condition', today='2026-08-24',
                  triggers=['consensus_floor'], kill_evidence=('price', 'contract'))
    assert r.grade == 'kill condition'


# ── 악화는 즉시, 회복은 잠금 ──

def test_recovery_is_locked_for_three_business_days():
    r = S.propose(book('주의', since='2026-08-21'), '홀딩 강화',
                  today='2026-08-24', triggers=['x'])
    assert r.grade == '주의'
    assert 'recovery_locked' in r.reasons


def test_recovery_allowed_after_lock_expires():
    r = S.propose(book('주의', since='2026-08-14'), '홀딩 강화',
                  today='2026-08-24', triggers=['x'])
    assert r.grade == '홀딩 강화'


def test_worsening_is_never_locked():
    r = S.propose(book('홀딩 강화', since='2026-08-24'), '주의',
                  today='2026-08-24', triggers=['x'])
    assert r.grade == '주의'


# ── 트리거 없으면 못 움직인다 ──

def test_no_trigger_means_no_movement():
    r = S.propose(book('홀딩 강화'), '주의', today='2026-08-24', triggers=[])
    assert r.grade == '홀딩 강화'
    assert 'no_trigger' in r.reasons
    assert not r.allowed


def test_unchanged_grade_needs_no_trigger():
    r = S.propose(book('주의'), '주의', today='2026-08-24', triggers=[])
    assert r.grade == '주의'
    assert r.allowed


# ── grade_since ──

def test_grade_since_advances_only_on_change():
    r = S.propose(book('홀딩 강화', since='2026-08-01'), '주의',
                  today='2026-08-24', triggers=['x'])
    assert r.grade_since == '2026-08-24'
    same = S.propose(book('주의', since='2026-08-01'), '주의', today='2026-08-24', triggers=[])
    assert same.grade_since == '2026-08-01'


# ── last_seen 대조 ──

def test_unchanged_numbers_report_no_movement():
    seen = {'eps_fy1': 100.0, 'price': 50}
    assert S.numbers_moved(seen, {'eps_fy1': 100.0, 'price': 50}) == []


def test_changed_numbers_are_named():
    seen = {'eps_fy1': 100.0, 'price': 50}
    moved = S.numbers_moved(seen, {'eps_fy1': 130.0, 'price': 50})
    assert moved == ['eps_fy1']


def test_missing_today_value_is_not_a_move():
    assert S.numbers_moved({'eps_fy1': 100.0}, {'eps_fy1': None}) == []
