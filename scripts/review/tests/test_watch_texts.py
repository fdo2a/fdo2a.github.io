"""발행 감시 알림 문구(2026-11-19 사용자 「모든 검증 알림에 적용해」) — 발행 건별 알림과 같은 틀.

첫 줄 = 「[종류] 대상 · 상태」(휴대폰 미리보기는 첫 줄만 보인다), 다음 줄부터 무엇·왜, 마지막에 할 일.
파일 경로 대신 「KR 일간 11/09」 같은 이름, 판정·사건 종류·id 규칙은 그대로.
"""
import pytest

from review import prepub_view as V
from review import publish_watch as W
from review.tests import prepub_fixture as F
from review.tests.test_publish_watch import _mark_sent, at, kinds, run


def _ev(st, kind):
    return [e for e in st['events'] if e['kind'] == kind][-1]


def test_missing_head_and_cause(tmp_path):
    repo = F.init(tmp_path)
    F.publish(repo, 'us', '2026-11-09')
    st = run(W.new_state('처음 실행했어요'), repo, at(11, 10, 13))
    lines = _ev(st, 'missing')['text'].split('\n')
    assert lines[0] == '[미발행] KR 일간 11/09 · 확인 필요'
    assert lines[1] == '기준 시각 11/09 23:00 KST 이 지났는데 이번에 확인한 공개 판에 글이 없어요'   # 본 범위만(d1 #5)
    assert lines[2].startswith('원인(확정 아님): ') and '확정하지 못했어요' not in lines[2]


def test_resolved_and_late_heads(tmp_path):
    repo = F.init(tmp_path)
    F.publish(repo, 'us', '2026-11-09')
    st = run(W.new_state('x'), repo, at(11, 10, 13))
    _mark_sent(st)
    F.publish(repo, 'kr', '2026-11-09')
    run(st, repo, at(11, 10, 13, 5))
    t = _ev(st, 'resolved')['text'].split('\n')
    assert t[0] == '[미발행 해소] KR 일간 11/09 · 해결' and '앞서 보낸 미발행 경고(기준 11/09 23:00 KST)' in t[1]

    (tmp_path / 'b').mkdir()
    repo2 = F.init(tmp_path / 'b')
    F.publish(repo2, 'us', '2026-11-09')
    st2 = run(W.new_state('x'), repo2, at(11, 10, 13))               # 경고는 아직 못 보냈다
    F.publish(repo2, 'kr', '2026-11-09')
    run(st2, repo2, at(11, 10, 13, 5))
    t2 = _ev(st2, 'late')['text'].split('\n')
    assert t2[0] == '[늦은 발행] KR 일간 11/09 · 확인만' and '보내기 전에 해소돼 보내지 않았어요' in t2[-1]


def test_gone_and_back_use_names_not_paths(tmp_path):
    repo = F.init(tmp_path)
    F.publish(repo, 'us', '2026-11-09')
    st = run(W.new_state('x'), repo, at(11, 9, 8))
    F.git(repo, 'rm', '-q', 'posts/2026-11-09.html')
    F.commit(repo, 'remove post')
    run(st, repo, at(11, 9, 8, 5))
    g = _ev(st, 'gone')['text'].split('\n')
    assert g[0] == '[사라짐] US 일간 11/09 · 확인 필요'
    assert g[1] == '발행됐던 글이 지금 공개 판에 없어요'
    assert '「remove post」' in g[2] and g[2].endswith('루틴·정정 이력 확인')
    F.write(repo, 'posts/2026-11-09.html', '<p>다시</p>')
    F.commit(repo, 're-add')
    run(st, repo, at(11, 9, 8, 10))
    b = _ev(st, 'back')['text']
    assert b.split('\n')[0] == '[다시 올라옴] US 일간 11/09 · 확인만' and 'posts/' not in b


def test_baseline_notice_no_longer_points_at_removed_digest_lines(tmp_path):
    repo = F.init(tmp_path)
    F.publish(repo, 'us', '2026-11-09')
    st = run(W.new_state('처음 실행했어요'), repo, at(11, 10, 13))
    reset = _ev(st, 'reset')['text']
    assert reset.split('\n')[0] in ('[발행 알림] 처음 실행했어요 · 기준선만 잡음', '[발행 알림] 처음 실행했어요 · 전부 다시 계산')
    assert '[발행 전 기록] 줄' not in reset                          # 아침 요약에서 뺀 줄을 가리키지 않는다


def test_body_is_in_the_id_so_old_ids_never_carry_new_text():
    # 상태를 잃고 다시 계산해도 「옛 id + 새 본문」이 Worker 로 가지 않게(codex d1 #3) — 문구가 바뀌면 id 도 바뀐다
    from datetime import datetime
    now = datetime(2026, 11, 10, tzinfo=W.KST)
    st = {'events': []}
    eid = W.add_event(st, 'missing', 'kr:2026-11-09', 'x', now, extra='h')
    assert eid == W.event_id('missing', 'kr:2026-11-09', f'h|{W.text_hash("x")}') != W.event_id('missing', 'kr:2026-11-09', 'h')
    other = W.add_event({'events': []}, 'missing', 'kr:2026-11-09', 'y', now, extra='h')
    assert other != eid                                                    # 같은 사건·다른 본문 = 다른 id
    pid = W.add_event(st, 'publish', 'posts/a.html', 'y', now, extra='fp|hash')
    assert pid == W.event_id('publish', 'posts/a.html', 'fp|hash')          # 발행 사건은 본문 해시가 이미 id 에


def test_same_event_is_still_added_once_even_if_its_text_would_differ():
    # 상태가 남아 있으면 종전대로 (종류·key·extra) 하나에 한 번 — id 에 본문을 넣었다고 같은 사건이 두 번 쌓이지 않는다
    from datetime import datetime
    now = datetime(2026, 11, 10, tzinfo=W.KST)
    st = {'events': []}
    assert W.add_event(st, 'late', 'us:2026-11-09', '가', now)
    assert W.add_event(st, 'late', 'us:2026-11-09', '나', now) is None
    old = {'events': [{'id': W.event_id('late', 'us:2026-11-09'), 'kind': 'late', 'key': 'us:2026-11-09'}]}
    assert W.add_event(old, 'late', 'us:2026-11-09', '나', now) is None      # 문구를 바꾸기 전에 쌓인 사건도 같은 사건


def _worker(seen, st):
    """Worker 의 받기 규칙(core.js mergeOutbox)만 — 같은 id 에 다른 본문이면 그 사건을 거부한다. → 거부한 id 들."""
    bad = []
    for e in W.build_outbox(st, at(11, 10, 17))['events']:
        if seen.setdefault(e['id'], e['hash']) != e['hash']:
            bad.append(e['id'])
    return bad


@pytest.mark.parametrize('who', [V.MAC, V.GITHUB])
def test_late_recomputed_after_state_loss_never_reuses_an_id_for_another_body(tmp_path, who):
    # codex d2 #1: 기준선으로 잡아 둔 세션이 늦게 올라온 알림과, 상태를 잃고 커밋 시각으로 다시 계산한 알림은 본문이 다르다
    def go(st, now):
        return W.step(st, str(repo), now, True, ref='HEAD', who=who)
    repo = F.init(tmp_path)
    st = go(W.new_state('처음 실행했어요', baseline=True), at(11, 10, 13))             # US 11/09 없음 — 조용히 잡아 둔다
    assert st['sessions']['us:2026-11-09'] == 'missing_quiet'
    F.publish(repo, 'us', '2026-11-09', when='2026-11-10T15:30:00+09:00')
    go(st, at(11, 10, 16))
    a = _ev(st, 'late')
    st2 = go(W.new_state('상태를 잃었어요'), at(11, 10, 16, 5))                        # 같은 공개 판을 처음부터 다시
    b = _ev(st2, 'late')
    assert a['key'] == b['key'] and a['text'] != b['text']
    assert a['id'] != b['id']
    seen = {}
    assert _worker(seen, st) == [] and _worker(seen, st2) == []


def test_new_events_survive_saving_and_are_still_added_once(tmp_path):
    # 상태 파일을 거쳐도 「같은 사건」 단위(base)가 남는다 — 잃으면 다음 실행이 같은 사건을 다시 쌓는다
    from datetime import datetime
    now = datetime(2026, 11, 10, tzinfo=W.KST)
    st = W.new_state('x')
    assert W.add_event(st, 'late', 'us:2026-11-09', '가', now)
    back = W.loads_state(W.dumps_state(st))
    assert back['events'][0]['base'] == W.event_id('late', 'us:2026-11-09')
    assert W.add_event(back, 'late', 'us:2026-11-09', '나', now) is None
    assert set(W._out(back['events'][0])) == {'id', 'hash', 'key', 'kind', 'text', 'created'}   # outbox 계약 칸은 그대로


def test_reset_notice_id_follows_its_final_text(tmp_path):
    # 기준선 안내는 글 수·이름이 뒤에 채워진다 — 같은 날 같은 사유로 다시 계산해 본문이 달라지면 id 도 달라야 한다
    repo = F.init(tmp_path)
    F.publish(repo, 'us', '2026-11-09')
    a = _ev(run(W.new_state('처음 실행했어요'), repo, at(11, 10, 13)), 'reset')
    b = _ev(run(W.new_state('처음 실행했어요', baseline=True), repo, at(11, 10, 13)), 'reset')
    c = _ev(run(W.new_state('처음 실행했어요'), repo, at(11, 10, 13, 30)), 'reset')
    assert a['text'] != b['text'] and a['id'] != b['id']
    assert a['text'] == c['text'] and a['id'] == c['id']                      # 같은 본문은 같은 id — 다시 계산해도 중복 아님
    assert a['hash'] == W.text_hash(a['text'])
