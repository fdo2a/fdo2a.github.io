"""큐에 글이 남지 않은 섹션의 오류는 풀린다 — 2026-11-07 실측.

일본 주간 W44 의 codex 한도 오류가 섹션 오류로 남은 뒤, W44 는 11/06 손 검토로 원장에 들어가
큐에서 빠졌다. 섹션 오류는 「그 섹션이 초안을 낼 때만」 풀리는데 낼 글이 없으니 영영 남았고,
`last_ok` 는 오류가 하나라도 있으면 갱신되지 않아 훅이 「러너 마지막 성공 43시간 전」을 보였다 —
그동안 US·KR 은 검토·정정·푸시가 다 됐는데도.
"""
from review.runner import HUMAN, LIMIT, UNKNOWN, drop_resolved, err


def test_a_section_with_nothing_left_in_the_queue_loses_its_error():
    errs = {'japan/posts': err(LIMIT, 'japan/posts/2026-W44.html: usage limit')}
    assert drop_resolved(errs, live_sections={'us', 'kr'}) == {}


def test_a_section_still_waiting_keeps_its_error():
    errs = {'japan/posts': err(LIMIT, 'japan/posts/2026-W45.html: usage limit')}
    assert drop_resolved(errs, live_sections={'japan/posts'}) == errs


def test_a_correction_error_follows_its_section():
    errs = {'정정-kr': err(HUMAN, 'kr/posts/2026-11-05.html: 자동 정정 3회 실패')}
    assert drop_resolved(errs, live_sections={'us'}) == {}
    assert drop_resolved(errs, live_sections={'kr'}) == errs


def test_runner_wide_errors_are_never_dropped_here():
    errs = {'러너': err(UNKNOWN, 'fetch 실패'), '근거': err(HUMAN, '자동 검토 제외'),
            '근거-기간': err(HUMAN, '자동 검토 제외'), '러너-코드': err(HUMAN, '코드가 다르다')}
    assert drop_resolved(errs, live_sections=set()) == errs


def test_the_input_is_not_mutated():
    errs = {'japan/posts': err(LIMIT, 'x')}
    drop_resolved(errs, live_sections=set())
    assert 'japan/posts' in errs


# ── tick 수준 ───────────────────────────────────────────────────────────────────
import json  # noqa: E402

from review.tests.test_run_cli import fake_codex, repo, run, state_of, write  # noqa: E402,F401


def test_a_stale_error_from_a_section_that_left_the_queue_lets_last_ok_move(repo, tmp_path):
    stale = {'japan/posts': err(LIMIT, 'japan/posts/2026-W44.html: codex 종료 코드 1 — usage limit')}
    write(repo, 'reviews/runner.json', json.dumps({'errors': stale}))
    run(repo, 'run', codex=fake_codex(tmp_path))
    state = state_of(repo)
    assert 'japan/posts' not in (state.get('errors') or {})
    assert state.get('last_ok')
