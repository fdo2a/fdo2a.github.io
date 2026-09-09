"""러너 선별·한도·확정 규칙.

여기서 막는 것은 전부 「게이트가 켜져 있는 것처럼 보이면서 꺼져 있는」 부류다 — 공개되지
않은 판을 읽고 공개판인 양 남기는 것, 잘린 초안이 완료로 세어지는 것, 실패한 호출이
한도를 안 쓴 것으로 남아 매시 되풀이되는 것.
"""

from review.queue import Pending
from review.runner import (accept_draft, draft_name, eligible, reserve,
                           today_kst, used)

TODAY = '2026-09-10'


def item(path, section, sha, reason='신규'):
    return Pending(path, section, sha, reason)


def test_the_published_version_is_the_one_that_gets_read():
    """작업 폴더에만 있는 판은 독자가 보는 글이 아니다. 그걸 읽으면 한도를 쓰고, 결과는
    공개판 지적인 양 남는다."""
    work_only = item('posts/2026-09-10.html', 'us', 'aaa')
    published = {'posts/2026-09-10.html': 'bbb'}
    assert eligible([work_only], published, {}, TODAY) == []


def test_a_matching_published_version_is_picked():
    got = item('posts/2026-09-10.html', 'us', 'aaa')
    assert eligible([got], {'posts/2026-09-10.html': 'aaa'}, {}, TODAY) == [got]


def test_only_us_and_kr():
    rows = [item('thesis/data/thesis_state.json', 'thesis/data', 'a'),
            item('weekly/2026-09-10.html', 'weekly', 'b'),
            item('kr/posts/2026-09-10.html', 'kr', 'c')]
    tree = {r.path: r.sha for r in rows}
    assert [p.section for p in eligible(rows, tree, {}, TODAY)] == ['kr']


def test_one_call_per_section_per_day():
    rows = [item('posts/2026-09-10.html', 'us', 'a'),
            item('posts/2026-09-09.html', 'us', 'b'),
            item('kr/posts/2026-09-10.html', 'kr', 'c')]
    tree = {r.path: r.sha for r in rows}
    got = eligible(rows, tree, {}, TODAY)
    assert [p.path for p in got] == ['posts/2026-09-10.html',
                                     'kr/posts/2026-09-10.html']


def test_a_used_slot_is_not_handed_out_again():
    """예약이 살아 있어야 실패한 호출이 매시 되풀이되지 않는다."""
    row = item('posts/2026-09-10.html', 'us', 'a')
    state = reserve({}, TODAY, 'us')
    assert eligible([row], {row.path: row.sha}, state, TODAY) == []


def test_backlog_does_not_eat_the_quota_on_a_quiet_day():
    """새 글이 없는 날 밀린 글이 자동 대상으로 살아나면, 백로그는 사람이 읽는다는 계약이
    깨지고 그날 새 글이 늦게 올라와도 한도가 없다."""
    old = item('posts/2026-09-01.html', 'us', 'a')
    assert eligible([old], {old.path: old.sha}, {}, TODAY) == []


def test_yesterdays_post_is_still_fresh_enough():
    row = item('posts/2026-09-09.html', 'us', 'a')
    assert eligible([row], {row.path: row.sha}, {}, TODAY) == [row]


def test_reserve_counts_before_the_call():
    state = reserve({}, TODAY, 'us')
    assert used(state, TODAY, 'us') == 1
    assert used(state, TODAY, 'kr') == 0


def test_old_days_are_pruned_so_the_heartbeat_file_does_not_grow():
    state = {'calls': {'2026-01-01': {'us': 1}}}
    assert '2026-01-01' not in reserve(state, TODAY, 'us')['calls']


def test_an_existing_draft_is_not_read_again_when_the_day_rolls_over():
    """자정이 지나면 한도가 새로 열린다. 초안이 이미 있는 판을 다시 읽으면 그날 할당량을
    태우고, 몇 시간 뒤 올라오는 그날 글은 읽을 한도가 없다."""
    row = item('posts/2026-09-09.html', 'us', 'a')
    tree = {row.path: row.sha}
    assert eligible([row], tree, {}, TODAY) == [row]          # 어제는 읽었고
    assert eligible([row], tree, {}, TODAY, have=[draft_name(row)]) == []


def test_a_fresher_post_still_gets_read_when_an_older_draft_exists():
    old_one = item('posts/2026-09-09.html', 'us', 'a')
    new_one = item('posts/2026-09-10.html', 'us', 'b')
    tree = {p.path: p.sha for p in (old_one, new_one)}
    got = eligible([new_one, old_one], tree, {}, TODAY, have=[draft_name(old_one)])
    assert [p.path for p in got] == ['posts/2026-09-10.html']


def test_reserve_survives_a_damaged_calls_field():
    """`used()` 는 망가진 상태를 0 으로 읽는데 `reserve()` 가 거기서 죽으면, 두 함수가 같은
    파일을 다르게 보고 러너는 매 tick 그 자리에서 넘어진다."""
    for junk in ({'calls': 'nope'}, {'calls': {'쓰레기': 1}}, {'calls': [1, 2]}):
        assert reserve(junk, TODAY, 'us')['calls'][TODAY]['us'] == 1


def test_a_damaged_state_file_reads_as_no_quota_used():
    """망가진 상태 파일에 막혀 러너가 조용히 멈추면 안 된다 — 원장의 실패 방향과 같다."""
    for junk in (None, [], {'calls': 'nope'}, {'calls': {TODAY: 5}}):
        assert used(junk if isinstance(junk, dict) else {}, TODAY, 'us') == 0


def test_a_truncated_draft_is_not_accepted():
    ok, why = accept_draft(0, '   \n', 'a' * 40, 'a' * 40)
    assert not ok and '비어' in why


def test_a_failed_call_is_not_accepted():
    ok, why = accept_draft(1, '지적 3건', 'a' * 40, 'a' * 40)
    assert not ok and '종료 코드' in why


def test_a_draft_for_a_version_that_moved_is_not_accepted():
    """읽는 사이 루틴이 같은 날짜를 재발행하면, 그 초안은 이제 아무도 안 보는 판의 것이다."""
    ok, why = accept_draft(0, '지적 3건', 'b' * 40, 'a' * 40)
    assert not ok and '바뀌었다' in why


def test_a_good_draft_is_accepted():
    assert accept_draft(0, '지적 3건', 'a' * 40, 'a' * 40) == (True, None)


def test_the_draft_name_carries_the_version_that_was_read():
    got = draft_name(item('kr/posts/2026-09-10.html', 'kr', 'abcdef1234'))
    assert got == '2026-09-10-kr-abcdef1.md'


def test_today_is_kst_not_the_machines_idea_of_a_day():
    from datetime import datetime, timezone
    # 2026-09-10 00:30 KST — UTC로는 아직 9월 9일이다.
    assert today_kst(datetime(2026, 9, 9, 15, 30, tzinfo=timezone.utc)) == '2026-09-10'
