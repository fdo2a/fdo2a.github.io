"""실패의 종류 — 한도 반납, 차단 시각, 정정 회차, 오류 표시.

여기서 막는 것은 전부 「고장을 한 칸에 뭉쳐서 다음에 뭘 할지 알 수 없게 만드는」 부류다 —
공급자 한도로 죽은 호출이 우리 하루 예산을 태우는 것(2026-09-19 실측), 구문만 맞는 먼
미래 시각이 러너를 영영 세우는 것, 같은 발행본의 자동 정정이 날짜만 바뀌면 무한히
되풀이되는 것.
"""

from datetime import datetime, timedelta, timezone

from review.runner import (BLOCK_HORIZON_HOURS, HUMAN, LIMIT, LIMIT_RETRY_CAP,
                           ROUND_CAP, UNKNOWN, blocked_until, clear_rounds,
                           err, err_detail, err_kind, err_line, is_limit_error,
                           limit_hits, may_release, note_limit, note_round,
                           release, reserve, retry_at, rounds, stalled,
                           used)

TODAY = '2026-09-19'
TZ = timezone(timedelta(hours=9))
NOW = datetime(2026, 9, 19, 23, 0, tzinfo=TZ)

# 2026-09-19 reviews/runner.json 에 실제로 남은 문구.
REAL = ("ERROR: You've hit your usage limit. Upgrade to Pro "
        "(https://chatgpt.com/explore/pro), visit "
        "https://chatgpt.com/codex/settings/usage to purchase more credits "
        "or try again at 7:47 PM.")


# ── 한도 판별 ──────────────────────────────────────────────────────────────────
def test_the_real_usage_limit_message_is_recognised():
    """실측 문구를 못 잡으면 이 작업 전체가 무의미하다."""
    assert is_limit_error(1, '', REAL)


def test_a_successful_call_is_never_a_limit_error():
    """종료 코드 0 이면 초안이 나온 것이다. 본문이 뭘 인용했든 반납할 일이 없다."""
    assert not is_limit_error(0, REAL, '')


def test_a_post_quoting_the_limit_message_does_not_refund_the_budget():
    """검토 대상 글이나 codex 요약이 문구를 인용해도 문장 중간이라 안 걸린다.

    이게 뚫리면 매 tick 반납·재호출이 되면서 하루 상한이 사라진다.
    """
    quoted = "지적 3 — 본문이 \"You've hit your usage limit\" 를 인용하고 있다."
    assert not is_limit_error(1, quoted, '')


def test_stderr_wins_when_both_streams_have_text():
    """`review_one` 은 stdout 이 있으면 stderr 를 버린다. 분류는 그 반대로 봐야 한다."""
    assert is_limit_error(1, '초안 일부가 여기까지 나왔다', REAL)


def test_a_line_leading_error_in_stdout_still_counts():
    """stderr 가 비어 있으면 stdout 의 줄 머리는 CLI 오류로 인정한다."""
    assert is_limit_error(1, 'some output\n' + REAL, '')


def test_an_ordinary_failure_is_not_a_limit_error():
    assert not is_limit_error(3, 'boom', 'Traceback ...')


# ── 반납 ───────────────────────────────────────────────────────────────────────
def test_a_provider_limit_refunds_the_slot():
    """2026-09-19 의 고장 그 자체 — 한도로 죽은 호출이 하루 두 칸을 태웠다."""
    state = reserve({}, TODAY, 'us')
    assert used(state, TODAY, 'us') == 1
    assert used(release(state, TODAY, 'us'), TODAY, 'us') == 0


def test_refunding_never_goes_below_zero():
    assert used(release({}, TODAY, 'us'), TODAY, 'us') == 0


def test_refunding_one_section_leaves_the_other_alone():
    state = reserve(reserve({}, TODAY, 'us'), TODAY, 'kr')
    after = release(state, TODAY, 'us')
    assert used(after, TODAY, 'us') == 0 and used(after, TODAY, 'kr') == 1


def test_the_daily_cap_survives_repeated_refunds():
    """무조건 반납하면 `calls` 가 실제 호출 수가 아니게 되고 상한이 사라진다."""
    state = {}
    for _ in range(LIMIT_RETRY_CAP):
        assert may_release(state, TODAY)
        state = note_limit(state, TODAY)
    assert not may_release(state, TODAY)
    assert limit_hits(state, TODAY) == LIMIT_RETRY_CAP


def test_limit_hits_are_counted_per_day():
    state = note_limit({}, TODAY)
    assert limit_hits(state, '2026-09-20') == 0


def test_a_damaged_limit_counter_reads_as_none_used():
    assert limit_hits({'limit_hits': '망가짐'}, TODAY) == 0
    assert limit_hits({'limit_hits': {TODAY: -3}}, TODAY) == 0


# ── 재시도 시각 ────────────────────────────────────────────────────────────────
def test_the_real_message_gives_an_absolute_time():
    """실측 문구는 「try again at 7:47 PM」이다 — 상대시간 파서만 두면 이 고장을 놓친다."""
    got = retry_at(REAL, NOW)
    assert got is not None and datetime.fromisoformat(got).hour == 19


def test_a_time_that_already_passed_today_rolls_to_tomorrow():
    """23:00 에 「7:47 PM」을 받으면 오늘이 아니라 내일 19:47 이다 — 실측이 그 모양이다."""
    got = datetime.fromisoformat(retry_at(REAL, NOW))
    assert (got.date() - NOW.date()).days == 1 and got.hour == 19 and got.minute == 47


def test_a_relative_message_is_also_accepted():
    got = retry_at('or try again in 2 hours 34 minutes', NOW)
    assert datetime.fromisoformat(got) == NOW + timedelta(hours=2, minutes=34)


def test_no_retry_hint_means_no_guess():
    """추측하지 않는다. 없으면 다음 tick 이 그냥 다시 부른다 — 예산은 안 쓴다."""
    assert retry_at('ERROR: something else', NOW) is None
    assert retry_at('', NOW) is None


def test_a_nonsense_clock_is_refused():
    assert retry_at('try again at 99:99', NOW) is None
    assert retry_at('try again at 13:00 PM', NOW) is None


def test_the_stored_time_is_absolute_so_the_block_cannot_keep_extending():
    """상대시간을 저장해 매 tick 다시 재면 차단이 영영 연장된다."""
    first = retry_at('try again in 1 hours', NOW)
    later = retry_at('try again in 1 hours', NOW + timedelta(minutes=30))
    assert first != later and datetime.fromisoformat(first) < datetime.fromisoformat(later)


# ── 차단 시각 ──────────────────────────────────────────────────────────────────
def test_a_far_future_block_never_stops_the_runner_forever():
    """구문만 맞는 9999 년이 「미래면 참」을 통과하면 러너가 영영 안 돈다."""
    assert blocked_until({'blocked_until': '9999-01-01T00:00:00+09:00'}, NOW) is None


def test_a_naive_timestamp_is_refused():
    """tz 가 없으면 비교 기준이 기계마다 달라진다."""
    assert blocked_until({'blocked_until': '2026-09-19T23:30:00'}, NOW) is None


def test_an_expired_block_reads_as_not_blocked():
    past = (NOW - timedelta(minutes=1)).isoformat()
    assert blocked_until({'blocked_until': past}, NOW) is None


def test_a_live_block_is_returned():
    soon = (NOW + timedelta(hours=1)).isoformat()
    assert blocked_until({'blocked_until': soon}, NOW) == NOW + timedelta(hours=1)


def test_a_damaged_block_field_reads_as_not_blocked():
    for bad in (None, '', 12, 'tomorrow', {'at': 'x'}):
        assert blocked_until({'blocked_until': bad}, NOW) is None


def test_the_horizon_is_the_documented_one():
    edge = (NOW + timedelta(hours=BLOCK_HORIZON_HOURS, minutes=1)).isoformat()
    assert blocked_until({'blocked_until': edge}, NOW) is None


# ── 정정 회차 ──────────────────────────────────────────────────────────────────
def test_rounds_accumulate_across_days():
    """하루 상한과 달리 이건 누적이라야 의미가 있다 — 날짜로 초기화되면 무한 반복이다."""
    state = {}
    for _ in range(ROUND_CAP):
        state = note_round(state, 'posts/2026-09-18.html')
    assert rounds(state, 'posts/2026-09-18.html') == ROUND_CAP
    assert stalled(state, 'posts/2026-09-18.html')


def test_a_post_below_the_cap_is_not_stalled():
    state = note_round({}, 'posts/2026-09-18.html')
    assert not stalled(state, 'posts/2026-09-18.html')


def test_rounds_are_per_post():
    state = note_round({}, 'posts/2026-09-18.html')
    assert rounds(state, 'kr/2026-09-18.html') == 0


def test_a_passing_correction_clears_the_debt():
    """안 지우면 다음 발행본이 남의 빚을 물려받는다."""
    state = note_round({}, 'posts/2026-09-18.html')
    assert rounds(clear_rounds(state, 'posts/2026-09-18.html'),
                  'posts/2026-09-18.html') == 0
    assert clear_rounds({}, 'posts/x.html') == {}


# ── 오류 표시 ──────────────────────────────────────────────────────────────────
def test_an_old_string_error_still_reads():
    """스키마를 바꿨다고 디스크의 지난 상태가 못 읽히면 훅 한 줄이 통째로 사라진다."""
    old = 'posts/2026-09-18.html: codex 종료 코드 1'
    assert err_kind(old) == UNKNOWN
    assert err_detail(old) == old
    assert '판정불가' in err_line('us', old)


def test_a_new_error_carries_its_kind():
    value = err(LIMIT, 'posts/2026-09-18.html: 한도')
    assert err_kind(value) == LIMIT
    assert err_line('us', value) == 'us [한도] posts/2026-09-18.html: 한도'


def test_a_damaged_error_object_does_not_crash_the_hook():
    for bad in ({'kind': 7}, {}, {'detail': 'x'}, 12, None):
        assert err_kind(bad) == UNKNOWN
        assert isinstance(err_line('us', bad), str)


def test_the_human_kind_exists_for_a_stalled_post():
    assert err_kind(err(HUMAN, 'x')) == HUMAN
