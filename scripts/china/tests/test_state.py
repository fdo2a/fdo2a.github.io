import pytest

from china import state as S


def st(**kw):
    base = {'version': 1, 'updated': None, 'completed': [], 'last_published_week': None}
    base.update(kw)
    return base


def done(lid, week, last_reviewed=None, claims=None):
    return {'id': lid, 'week': week, 'url': f'/china/posts/{week}.html',
            'last_reviewed_week': last_reviewed,
            'claims': claims if claims is not None else [
                {'claim_id': f'{lid}-c1', 'text': f'{lid} 명제'}]}


# ── ISO 주차 키 (C15) ──

def test_week_key_uses_iso_week_year_not_calendar_year():
    # 2027-01-01 은 금요일이라 ISO 로는 2026-W53 이다. 달력 연도를 쓰면 키가 어긋난다.
    assert S.week_key('2027-01-01') == '2026-W53'
    assert S.week_key('2026-09-05') == '2026-W36'


def test_week_key_rejects_garbage():
    with pytest.raises(ValueError):
        S.week_key('2026-13-99')


# ── 되짚기 선택 (C2) ──

def test_bootstrap_has_no_revisit_target():
    assert S.revisit_target(st()) is None


def test_revisit_picks_never_reviewed_oldest_completion():
    s = st(completed=[done('A01', '2026-W36'), done('A02', '2026-W37')])
    assert S.revisit_target(s) == 'A01'


def test_revisit_prefers_least_recently_reviewed_over_completion_order():
    s = st(completed=[done('A01', '2026-W36', last_reviewed='2026-W38'),
                      done('A02', '2026-W37', last_reviewed='2026-W37')])
    assert S.revisit_target(s) == 'A02'


def test_never_reviewed_beats_already_reviewed():
    s = st(completed=[done('A01', '2026-W36', last_reviewed='2026-W37'),
                      done('A02', '2026-W37')])
    assert S.revisit_target(s) == 'A02'


def test_revisit_is_deterministic_on_ties():
    s = st(completed=[done('A02', '2026-W36'), done('A01', '2026-W36')])
    assert S.revisit_target(s) == 'A01'  # id 로 갈린다


def test_revisit_does_not_rotate_back_to_same_lesson():
    """배열 회전의 결함 — A01 을 되짚은 주에 A02 를 추가하면 다음 주도 A01 이 선두가 된다."""
    s = st(completed=[done('A01', '2026-W36')])
    nxt = S.advance(s, lesson='A02', week='2026-W37', revisited='A01',
                    claims=[{'claim_id': 'A02-c1', 'text': 'x'}])
    assert S.revisit_target(nxt) == 'A02'


# ── 전이 (C1) ──

def test_advance_is_pure_and_does_not_mutate_input():
    s = st(completed=[done('A01', '2026-W36')])
    before = S.state_hash(s)
    S.advance(s, lesson='A02', week='2026-W37', revisited='A01',
              claims=[{'claim_id': 'A02-c1', 'text': 'x'}])
    assert S.state_hash(s) == before


def test_advance_records_completion_and_week():
    s = st()
    nxt = S.advance(s, lesson='A01', week='2026-W36', revisited=None,
                    claims=[{'claim_id': 'A01-c1', 'text': 'x'}])
    assert [c['id'] for c in nxt['completed']] == ['A01']
    assert nxt['last_published_week'] == '2026-W36'
    assert nxt['completed'][0]['url'] == '/china/posts/2026-W36.html'


def test_advance_stamps_last_reviewed_on_the_revisited_lesson():
    s = st(completed=[done('A01', '2026-W36')])
    nxt = S.advance(s, lesson='A02', week='2026-W37', revisited='A01',
                    claims=[{'claim_id': 'A02-c1', 'text': 'x'}])
    assert nxt['completed'][0]['last_reviewed_week'] == '2026-W37'


def test_advance_is_idempotent_for_the_same_week():
    """같은 주에 두 번 돌아도 같은 결과여야 한다 — 두 번 더해지면 진도가 앞서 나간다."""
    s = st()
    once = S.advance(s, lesson='A01', week='2026-W36', revisited=None,
                     claims=[{'claim_id': 'A01-c1', 'text': 'x'}])
    twice = S.advance(once, lesson='A01', week='2026-W36', revisited=None,
                      claims=[{'claim_id': 'A01-c1', 'text': 'x'}])
    assert twice == once


def test_advance_rejects_relapse_to_an_earlier_week():
    s = st(completed=[done('A01', '2026-W37')], last_published_week='2026-W37')
    with pytest.raises(S.StateError, match='주차'):
        S.advance(s, lesson='A02', week='2026-W36', revisited='A01',
                  claims=[{'claim_id': 'A02-c1', 'text': 'x'}])


def test_advance_rejects_relearning_a_completed_lesson():
    s = st(completed=[done('A01', '2026-W36')], last_published_week='2026-W36')
    with pytest.raises(S.StateError, match='이미'):
        S.advance(s, lesson='A01', week='2026-W37', revisited='A01',
                  claims=[{'claim_id': 'A01-c1', 'text': 'x'}])


def test_advance_rejects_revisiting_an_uncompleted_lesson():
    s = st(completed=[done('A01', '2026-W36')], last_published_week='2026-W36')
    with pytest.raises(S.StateError, match='되짚기'):
        S.advance(s, lesson='A02', week='2026-W37', revisited='A09',
                  claims=[{'claim_id': 'A02-c1', 'text': 'x'}])


def test_advance_rejects_revisiting_the_lesson_being_published():
    s = st(completed=[done('A01', '2026-W36')], last_published_week='2026-W36')
    with pytest.raises(S.StateError, match='되짚기'):
        S.advance(s, lesson='A02', week='2026-W37', revisited='A02',
                  claims=[{'claim_id': 'A02-c1', 'text': 'x'}])


# ── claims 구조화 (C11) ──

def test_claims_must_be_structured_with_ids():
    with pytest.raises(S.StateError, match='claim_id'):
        S.advance(st(), lesson='A01', week='2026-W36', revisited=None,
                  claims=['자유 산문 명제'])


def test_claims_must_not_be_empty():
    with pytest.raises(S.StateError, match='claim'):
        S.advance(st(), lesson='A01', week='2026-W36', revisited=None, claims=[])


def test_duplicate_claim_ids_are_rejected():
    with pytest.raises(S.StateError, match='중복'):
        S.advance(st(), lesson='A01', week='2026-W36', revisited=None,
                  claims=[{'claim_id': 'A01-c1', 'text': 'a'},
                          {'claim_id': 'A01-c1', 'text': 'b'}])


def test_claim_ids_of_a_lesson_are_findable():
    s = st(completed=[done('A01', '2026-W36',
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

def test_two_lessons_cannot_land_in_the_same_week():
    s = st(completed=[done('A01', '2026-W36')], last_published_week='2026-W36')
    with pytest.raises(S.StateError, match='같은 주'):
        S.advance(s, lesson='A02', week='2026-W36', revisited='A01',
                  claims=[{'claim_id': 'A02-c1', 'text': 'x'}])


def test_malformed_week_is_rejected():
    for bad in ('2026-W99', 'junk', '2026-36', ''):
        with pytest.raises(S.StateError, match='주차'):
            S.advance(st(), lesson='A01', week=bad, revisited=None,
                      claims=[{'claim_id': 'A01-c1', 'text': 'x'}])


def test_revisiting_something_other_than_the_queue_target_is_rejected():
    """게이트가 지면을 보고 막지만 상태 전이도 같은 규율을 지켜야 한다."""
    s = st(completed=[done('A01', '2026-W36', last_reviewed='2026-W38'),
                      done('A02', '2026-W37')])
    with pytest.raises(S.StateError, match='큐'):
        S.advance(s, lesson='A03', week='2026-W39', revisited='A01',
                  claims=[{'claim_id': 'A03-c1', 'text': 'x'}])
    ok = S.advance(s, lesson='A03', week='2026-W39', revisited='A02',
                   claims=[{'claim_id': 'A03-c1', 'text': 'x'}])
    assert ok['last_published_week'] == '2026-W39'


def test_week_key_rejects_lookalikes():
    """`$` 는 끝의 개행을 받고 `\\d` 는 전각 숫자를 받는다 — 둘 다 다른 키를 만든다."""
    for bad in ('2026-W36\n', '２０２６-W３６', ' 2026-W36', '2026-w36'):
        assert not S.valid_week(bad), bad
    assert S.valid_week('2026-W36')
