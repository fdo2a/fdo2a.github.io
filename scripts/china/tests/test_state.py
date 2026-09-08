from datetime import date

import pytest

from china import state as S


def st(**kw):
    base = {'version': 1, 'updated': None, 'completed': [], 'last_published': None}
    base.update(kw)
    return base


def done(lid, day, last_reviewed=None, claims=None):
    return {'id': lid, 'date': day, 'url': f'/china/posts/{day}.html',
            'last_reviewed': last_reviewed,
            'claims': claims if claims is not None else [
                {'claim_id': f'{lid}-c1', 'text': f'{lid} 명제'}]}


# ── 발행일 키 (C15, 2026-09-08 3일 주기) ──

def test_period_key_is_the_publication_date():
    assert S.period_key('2026-09-05') == '2026-09-05'
    assert S.period_key(date(2027, 1, 1)) == '2027-01-01'


def test_period_key_rejects_garbage():
    with pytest.raises(ValueError):
        S.period_key('2026-13-99')


# ── 되짚기 선택 (C2) ──

def test_bootstrap_has_no_revisit_target():
    assert S.revisit_target(st()) is None


def test_revisit_picks_never_reviewed_oldest_completion():
    s = st(completed=[done('A01', '2026-09-05'), done('A02', '2026-09-08')])
    assert S.revisit_target(s) == 'A01'


def test_revisit_prefers_least_recently_reviewed_over_completion_order():
    s = st(completed=[done('A01', '2026-09-05', last_reviewed='2026-09-11'),
                      done('A02', '2026-09-08', last_reviewed='2026-09-08')])
    assert S.revisit_target(s) == 'A02'


def test_never_reviewed_beats_already_reviewed():
    s = st(completed=[done('A01', '2026-09-05', last_reviewed='2026-09-08'),
                      done('A02', '2026-09-08')])
    assert S.revisit_target(s) == 'A02'


def test_revisit_is_deterministic_on_ties():
    s = st(completed=[done('A02', '2026-09-05'), done('A01', '2026-09-05')])
    assert S.revisit_target(s) == 'A01'  # id 로 갈린다


def test_revisit_does_not_rotate_back_to_same_lesson():
    """배열 회전의 결함 — A01 을 되짚은 회차에 A02 를 추가하면 다음 회차도 A01 이 선두가 된다."""
    s = st(completed=[done('A01', '2026-09-05')])
    nxt = S.advance(s, lesson='A02', period='2026-09-08', revisited='A01',
                    claims=[{'claim_id': 'A02-c1', 'text': 'x'}])
    assert S.revisit_target(nxt) == 'A02'


# ── 전이 (C1) ──

def test_advance_is_pure_and_does_not_mutate_input():
    s = st(completed=[done('A01', '2026-09-05')])
    before = S.state_hash(s)
    S.advance(s, lesson='A02', period='2026-09-08', revisited='A01',
              claims=[{'claim_id': 'A02-c1', 'text': 'x'}])
    assert S.state_hash(s) == before


def test_advance_records_completion_and_date():
    s = st()
    nxt = S.advance(s, lesson='A01', period='2026-09-05', revisited=None,
                    claims=[{'claim_id': 'A01-c1', 'text': 'x'}])
    assert [c['id'] for c in nxt['completed']] == ['A01']
    assert nxt['last_published'] == '2026-09-05'
    assert nxt['completed'][0]['url'] == '/china/posts/2026-09-05.html'


def test_advance_stamps_last_reviewed_on_the_revisited_lesson():
    s = st(completed=[done('A01', '2026-09-05')])
    nxt = S.advance(s, lesson='A02', period='2026-09-08', revisited='A01',
                    claims=[{'claim_id': 'A02-c1', 'text': 'x'}])
    assert nxt['completed'][0]['last_reviewed'] == '2026-09-08'


def test_advance_is_idempotent_for_the_same_day():
    """같은 날 두 번 돌아도 같은 결과여야 한다 — 두 번 더해지면 진도가 앞서 나간다."""
    s = st()
    once = S.advance(s, lesson='A01', period='2026-09-05', revisited=None,
                     claims=[{'claim_id': 'A01-c1', 'text': 'x'}])
    twice = S.advance(once, lesson='A01', period='2026-09-05', revisited=None,
                      claims=[{'claim_id': 'A01-c1', 'text': 'x'}])
    assert twice == once


def test_advance_rejects_relapse_to_an_earlier_date():
    s = st(completed=[done('A01', '2026-09-08')], last_published='2026-09-08')
    with pytest.raises(S.StateError, match='뒤로'):
        S.advance(s, lesson='A02', period='2026-09-05', revisited='A01',
                  claims=[{'claim_id': 'A02-c1', 'text': 'x'}])


def test_advance_rejects_relearning_a_completed_lesson():
    s = st(completed=[done('A01', '2026-09-05')], last_published='2026-09-05')
    with pytest.raises(S.StateError, match='이미'):
        S.advance(s, lesson='A01', period='2026-09-08', revisited='A01',
                  claims=[{'claim_id': 'A01-c1', 'text': 'x'}])


def test_advance_rejects_revisiting_an_uncompleted_lesson():
    s = st(completed=[done('A01', '2026-09-05')], last_published='2026-09-05')
    with pytest.raises(S.StateError, match='되짚기'):
        S.advance(s, lesson='A02', period='2026-09-08', revisited='A09',
                  claims=[{'claim_id': 'A02-c1', 'text': 'x'}])


def test_advance_rejects_revisiting_the_lesson_being_published():
    s = st(completed=[done('A01', '2026-09-05')], last_published='2026-09-05')
    with pytest.raises(S.StateError, match='되짚기'):
        S.advance(s, lesson='A02', period='2026-09-08', revisited='A02',
                  claims=[{'claim_id': 'A02-c1', 'text': 'x'}])


# ── claims 구조화 (C11) ──

def test_claims_must_be_structured_with_ids():
    with pytest.raises(S.StateError, match='claim_id'):
        S.advance(st(), lesson='A01', period='2026-09-05', revisited=None,
                  claims=['자유 산문 명제'])


def test_claims_must_not_be_empty():
    with pytest.raises(S.StateError, match='claim'):
        S.advance(st(), lesson='A01', period='2026-09-05', revisited=None, claims=[])


def test_duplicate_claim_ids_are_rejected():
    with pytest.raises(S.StateError, match='중복'):
        S.advance(st(), lesson='A01', period='2026-09-05', revisited=None,
                  claims=[{'claim_id': 'A01-c1', 'text': 'a'},
                          {'claim_id': 'A01-c1', 'text': 'b'}])


def test_claim_ids_of_a_lesson_are_findable():
    s = st(completed=[done('A01', '2026-09-05',
                           claims=[{'claim_id': 'A01-c1', 'text': 'x'},
                                   {'claim_id': 'A01-c2', 'text': 'y'}])])
    assert S.claim_ids(s, 'A01') == ['A01-c1', 'A01-c2']
    assert S.claim_ids(s, 'A99') == []


# ── CAS (C1) ──

def test_state_hash_changes_with_content_and_ignores_key_order():
    a = {'version': 1, 'completed': [], 'updated': '2026-09-05'}
    b = {'updated': '2026-09-05', 'completed': [], 'version': 1}
    assert S.state_hash(a) == S.state_hash(b)
    assert S.state_hash(a) != S.state_hash({**a, 'completed': [1]})


# ── codex 2차 검토 (2026-09-05) ──

def test_two_lessons_cannot_land_on_the_same_day():
    s = st(completed=[done('A01', '2026-09-05')], last_published='2026-09-05')
    with pytest.raises(S.StateError, match='같은 날'):
        S.advance(s, lesson='A02', period='2026-09-05', revisited='A01',
                  claims=[{'claim_id': 'A02-c1', 'text': 'x'}])


def test_two_lessons_may_land_in_the_same_iso_week():
    """3일 주기의 존재 이유 — 09-07(월)과 09-10(목)은 같은 ISO 주다. 주차 키를 쓰면
    이 두 번째 발행이 「같은 주에 두 강의」로 거부됐다. 이제는 정상 회차다."""
    s = st(completed=[done('A01', '2026-09-07')], last_published='2026-09-07')  # 월요일
    nxt = S.advance(s, lesson='A02', period='2026-09-10', revisited='A01',  # 같은 ISO 주 목요일
                    claims=[{'claim_id': 'A02-c1', 'text': 'x'}])
    assert nxt['last_published'] == '2026-09-10'
    assert date.fromisoformat('2026-09-07').isocalendar()[1] == \
        date.fromisoformat('2026-09-10').isocalendar()[1]


def test_malformed_period_is_rejected():
    for bad in ('2026-W36', 'junk', '2026-09', '2026-02-31', '2026-9-5', ''):
        with pytest.raises(S.StateError, match='발행일'):
            S.advance(st(), lesson='A01', period=bad, revisited=None,
                      claims=[{'claim_id': 'A01-c1', 'text': 'x'}])


def test_revisiting_something_other_than_the_queue_target_is_rejected():
    """게이트가 지면을 보고 막지만 상태 전이도 같은 규율을 지켜야 한다."""
    s = st(completed=[done('A01', '2026-09-05', last_reviewed='2026-09-11'),
                      done('A02', '2026-09-08')])
    with pytest.raises(S.StateError, match='큐'):
        S.advance(s, lesson='A03', period='2026-09-14', revisited='A01',
                  claims=[{'claim_id': 'A03-c1', 'text': 'x'}])
    ok = S.advance(s, lesson='A03', period='2026-09-14', revisited='A02',
                   claims=[{'claim_id': 'A03-c1', 'text': 'x'}])
    assert ok['last_published'] == '2026-09-14'


def test_period_key_rejects_lookalikes():
    """`$` 는 끝의 개행을 받고 `\\d` 는 전각 숫자를 받는다 — 둘 다 다른 키를 만든다.
    `date.fromisoformat` 은 3.11 부터 `20260905` 같은 다른 표기까지 받아 준다."""
    for bad in ('2026-09-05\n', '２０２６-０９-０５', ' 2026-09-05', '20260905'):
        assert not S.valid_period(bad), bad
    assert S.valid_period('2026-09-05')
