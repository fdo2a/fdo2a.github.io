import pytest

from china import syllabus as S


def lesson(lid, track='structure', prereq=(), order=None, status='fixed', **kw):
    return dict(id=lid, track=track, title=f'{lid} 제목', prereq=list(prereq),
                order=order if order is not None else int(lid[1:]),
                required_data=list(kw.get('required_data', [])),
                core_question=kw.get('core_question', f'{lid}?'), status=status)


def book(*lessons):
    return {'version': 1, 'lessons': list(lessons)}


# ── 그래프 검증 (C9) ──

def test_valid_book_loads():
    s = S.load(book(lesson('A01'), lesson('A02', prereq=['A01'])))
    assert [l['id'] for l in s.lessons] == ['A01', 'A02']


def test_unknown_prereq_is_rejected():
    with pytest.raises(S.SyllabusError, match='A99'):
        S.load(book(lesson('A01', prereq=['A99'])))


def test_self_reference_is_rejected():
    with pytest.raises(S.SyllabusError, match='자기 자신'):
        S.load(book(lesson('A01', prereq=['A01'])))


def test_cycle_is_rejected():
    with pytest.raises(S.SyllabusError, match='순환'):
        S.load(book(lesson('A01', prereq=['A02']), lesson('A02', prereq=['A01'])))


def test_duplicate_id_is_rejected():
    with pytest.raises(S.SyllabusError, match='중복'):
        S.load(book(lesson('A01'), lesson('A01', order=2)))


def test_duplicate_order_is_rejected():
    with pytest.raises(S.SyllabusError, match='order'):
        S.load(book(lesson('A01', order=1), lesson('A02', order=1)))


def test_fixed_lesson_may_not_depend_on_draft():
    with pytest.raises(S.SyllabusError, match='draft'):
        S.load(book(lesson('A01', status='draft'), lesson('A02', prereq=['A01'])))


def test_draft_may_depend_on_fixed():
    S.load(book(lesson('A01'), lesson('A02', prereq=['A01'], status='draft')))


def test_prereq_must_come_earlier_in_order():
    with pytest.raises(S.SyllabusError, match='order'):
        S.load(book(lesson('A01', order=1, prereq=['A02']), lesson('A02', order=2)))


# ── 다음 강의 선택 (C9·C10) ──

def test_next_is_lowest_order_uncompleted_fixed():
    s = S.load(book(lesson('A01'), lesson('A02', prereq=['A01'])))
    assert s.next_lesson([]) == 'A01'
    assert s.next_lesson(['A01']) == 'A02'


def test_next_skips_draft_even_when_eligible():
    s = S.load(book(lesson('A01'), lesson('B01', order=2, status='draft')))
    assert s.next_lesson(['A01']) is None


def test_next_skips_lesson_whose_prereq_is_unmet():
    # order 일관성이 강제되므로 `load()` 를 지난 책에서는 이 분기가 사실상 닿지
    # 않는다. 그래도 남겨 둔다 — state 를 손으로 고쳐 completed 가 어긋난 날의
    # 방어선이다. 그 상황을 만들려면 검증을 우회해 직접 조립해야 한다.
    a01, a02 = lesson('A01'), lesson('A02', order=2, prereq=['A01'])
    s = S.Syllabus(lessons=[a01, a02], by_id={'A01': a01, 'A02': a02})
    assert s.next_lesson(['A02']) == 'A01'
    # A01 을 건너뛴 채 A02 만 완료로 적혀 있어도 A02 를 다시 주지 않는다
    assert s.eligible(['A02']) == ['A01']


def test_exhausted_syllabus_returns_none():
    s = S.load(book(lesson('A01')))
    assert s.next_lesson(['A01']) is None


def test_get_returns_lesson_and_raises_on_unknown():
    s = S.load(book(lesson('A01')))
    assert s.get('A01')['title'] == 'A01 제목'
    with pytest.raises(KeyError):
        s.get('Z99')
