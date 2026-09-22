"""공급자 한도와 우리 예산은 다른 것이다 — CLI 수준에서.

2026-09-19 실측: 한도로 죽은 호출 둘이 하루 예산 두 칸을 다 태웠고, 초안은 0 건인 채로
그날 자동 검토가 끝났다. 순수 함수 테스트는 분류만 본다. 여기서 잡는 것은 그것이
원리적으로 못 보는 자리다 — 반납이 **디스크에 남는지**, 차단이 **정정까지 멈추는지**,
같은 글의 정정이 날짜만 바뀌면 무한히 되풀이되는지.
"""

import json
import os
import sys
from datetime import datetime, timedelta
from types import SimpleNamespace

import review_gate as gate
from review.runner import LIMIT, LIMIT_RETRY_CAP, ROUND_CAP, HUMAN, UNKNOWN
from review.tests.test_run_cli import (POST, drafts, fake_codex,  # noqa: F401
                                       repo, run, state_of, write)

# 2026-09-19 reviews/runner.json 에 실제로 남은 문구.
REAL = ("ERROR: You've hit your usage limit. Upgrade to Pro "
        "(https://chatgpt.com/explore/pro) or try again in 2 hours 34 minutes.")


def spent(state):
    day = max(state.get('calls') or {'': {}})
    return sum((state.get('calls') or {}).get(day, {}).values())


def kinds(state):
    return {k: (v.get('kind') if isinstance(v, dict) else None)
            for k, v in (state.get('errors') or {}).items()}


def test_a_provider_limit_does_not_burn_the_daily_budget(repo, tmp_path):
    """이 한 줄이 이번 작업의 이유다 — 초안 0 건인데 예산 두 칸이 타 있었다."""
    out = run(repo, 'run', codex=fake_codex(tmp_path, code=1, stderr=REAL))
    assert out.returncode == 1 and drafts(repo) == []
    state = state_of(repo)
    assert spent(state) == 0                      # 되돌렸다
    assert kinds(state)['us'] == LIMIT            # 그리고 왜인지 말한다
    assert state['limit_hits']


def test_an_ordinary_failure_still_burns_the_budget(repo, tmp_path):
    """폭주 방지 의도는 그대로다. 한도가 아닌 실패는 지금처럼 예산을 쓴다."""
    run(repo, 'run', codex=fake_codex(tmp_path, code=3))
    state = state_of(repo)
    assert spent(state) == 1 and kinds(state)['us'] == UNKNOWN


def test_a_quoted_limit_message_does_not_refund_the_budget(repo, tmp_path):
    """검토 대상 글이 문구를 인용해도 반납하면 안 된다 — 하루 상한이 사라진다."""
    quoted = "지적 1 — 본문이 You've hit your usage limit 를 인용한다"
    run(repo, 'run', codex=fake_codex(tmp_path, body=quoted, code=1))
    state = state_of(repo)
    assert spent(state) == 1 and kinds(state)['us'] == UNKNOWN


def test_the_refund_survives_a_reload(repo, tmp_path):
    """반납이 메모리에만 있으면 다음 tick 이 예산을 태운 상태로 시작한다.

    재시도 시각이 없는 문구를 쓴다 — REAL 은 시각을 주므로 두 번째 tick 이 차단돼
    호출 자체를 안 한다(그건 별도 테스트가 본다).
    """
    bare = "ERROR: You've hit your usage limit."
    for _ in range(2):
        run(repo, 'run', codex=fake_codex(tmp_path, code=1, stderr=bare))
    state = state_of(repo)
    assert spent(state) == 0
    assert max(state['limit_hits'].values()) == 2


def test_a_retry_time_in_the_message_blocks_the_next_tick(repo, tmp_path):
    """시각을 알려줬으면 그때까지 안 부른다 — 실패만 쌓는 tick 을 줄인다."""
    run(repo, 'run', codex=fake_codex(tmp_path, code=1, stderr=REAL))
    assert state_of(repo)['blocked_until']
    run(repo, 'run', codex=fake_codex(tmp_path))   # 성공하는 가짜인데도
    assert drafts(repo) == []                      # 부르지 않는다


def test_the_refund_has_a_floor(repo, tmp_path):
    """무조건 되돌리면 `calls` 가 실제 호출 수가 아니게 된다. 바닥이 있어야 한다."""
    for _ in range(LIMIT_RETRY_CAP + 1):
        # 차단이 걸리면 호출 자체를 안 하므로, 재시도 시각 없는 한도로만 민다.
        run(repo, 'run', codex=fake_codex(tmp_path, code=1,
                                          stderr="ERROR: You've hit your usage limit."))
    state = state_of(repo)
    assert max(state['limit_hits'].values()) == LIMIT_RETRY_CAP + 1
    assert spent(state) >= 1                      # 마지막 한 번은 되돌리지 않았다


def test_a_live_block_makes_no_new_codex_call(repo, tmp_path):
    """차단 중에는 codex 를 부르지 않는다 — 부르면 sentinel 이 남는다."""
    when = (datetime.now().astimezone() + timedelta(hours=2)).isoformat()
    write(repo, 'reviews/runner.json', json.dumps({'blocked_until': when}))
    sentinel = tmp_path / 'called'
    codex = fake_codex(tmp_path, name='codex2')
    with open(codex, 'a') as fh:
        fh.write('')
    (tmp_path / 'codex3').write_text(
        f'#!/bin/sh\ntouch "{sentinel}"\nexit 0\n')
    (tmp_path / 'codex3').chmod(0o755)
    run(repo, 'run', codex=str(tmp_path / 'codex3'))
    assert not sentinel.exists()
    assert state_of(repo)['blocked_until'] == when


def test_an_expired_block_is_cleared_and_the_runner_resumes(repo, tmp_path):
    past = (datetime.now().astimezone() - timedelta(minutes=5)).isoformat()
    write(repo, 'reviews/runner.json', json.dumps({'blocked_until': past}))
    run(repo, 'run', codex=fake_codex(tmp_path))
    state = state_of(repo)
    assert 'blocked_until' not in state and drafts(repo)


def test_a_far_future_block_does_not_stop_the_runner_forever(repo, tmp_path):
    """구문만 맞는 9999 년 하나가 러너를 영영 세우면 안 된다."""
    write(repo, 'reviews/runner.json',
          json.dumps({'blocked_until': '9999-01-01T00:00:00+09:00'}))
    run(repo, 'run', codex=fake_codex(tmp_path))
    assert drafts(repo)


def test_a_blocked_tick_does_not_look_like_a_success(repo, tmp_path):
    """차단 tick 이 `last_ok` 를 갱신하면 훅에 「마지막 성공 방금」만 보인다."""
    when = (datetime.now().astimezone() + timedelta(hours=2)).isoformat()
    write(repo, 'reviews/runner.json', json.dumps({'blocked_until': when}))
    run(repo, 'run', codex=fake_codex(tmp_path))
    assert 'last_ok' not in state_of(repo)


def _invoke(repo, monkeypatch, correct):
    monkeypatch.setattr(gate, 'repo_root', lambda: repo)
    monkeypatch.setitem(sys.modules, 'review.corrector',
                        SimpleNamespace(correct_one=correct))
    return gate.cmd_run(SimpleNamespace(timeout=10, correct=True,
                                        correction_timeout=10))


def test_a_block_does_not_stop_a_ready_correction(repo, tmp_path, monkeypatch):
    """차단 대상은 codex 신규 검토뿐이다. 이미 읽어 둔 지적은 발행본에 반영돼야 한다."""
    run(repo, 'run', codex=fake_codex(tmp_path))
    when = (datetime.now().astimezone() + timedelta(hours=2)).isoformat()
    state = state_of(repo)
    state['blocked_until'] = when
    write(repo, 'reviews/runner.json', json.dumps(state))
    calls = []
    _invoke(repo, monkeypatch, lambda root, item, *a: (calls.append(item.path), ('검증', None))[1])
    assert calls


def test_a_post_that_keeps_failing_is_handed_to_a_human(repo, tmp_path, monkeypatch):
    """세 번 실패하면 멈춘다. **날짜가 바뀌어도 풀리지 않는다** — 누적이라야 의미가 있다."""
    from datetime import date
    run(repo, 'run', codex=fake_codex(tmp_path))
    calls = []

    def correct(root, item, *args):
        calls.append(item.path)
        return '', 'gate failed'

    for n in range(ROUND_CAP + 2):
        # 날짜를 밀어 하루 상한이 아니라 **회차**가 멈추는지 본다.
        monkeypatch.setattr(gate, 'today_kst',
                            lambda n=n: (date.today() + timedelta(days=n)).isoformat())
        _invoke(repo, monkeypatch, correct)
    # 회차는 **발행본별**이다. us 가 멈춰도 kr 은 제 회차를 따로 센다.
    assert calls.count(POST) == ROUND_CAP
    assert state_of(repo)['errors']['정정-us']['kind'] == HUMAN


def test_a_passing_correction_clears_the_round_debt(repo, tmp_path, monkeypatch):
    """안 지우면 다음 발행본이 남의 빚을 물려받는다."""
    run(repo, 'run', codex=fake_codex(tmp_path))
    _invoke(repo, monkeypatch, lambda *a: ('', 'gate failed'))
    assert state_of(repo)['rounds']
    _invoke(repo, monkeypatch, lambda *a: ('검증 완료', None))
    assert not state_of(repo).get('rounds')
