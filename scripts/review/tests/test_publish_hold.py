"""세운 글을 몇 분 안에 텔레그램으로 — 감시 쪽(설계 instant_telegram v1.4 §4.3·4.4, §10-14, 2026-11-22).

막는 것(설계 §8 점검표): 보류 기록 push 가 감시를 안 깨움(1), 살아 있는 막힘에 사건이 없음(2), 같은 서명이 슬롯마다
다시 나감·A→B→A 가 흡수됨(4), 발행된 날짜·reviewed·7일 넘은 기록·훑지 못한 실행의 막힘이 실림(5), 닫힌 표 밖 글자(6),
기존 글 사건·「미발행 해소」가 바뀌거나 밀림(8·9). 5회차 지적 셋(§14): 막힘 칸이 깨져도 상태 전체를 초기화하지 않는다,
`born` 은 무작위 값, 막힘 때문에 생긴 넘침 알림이 기존 사건 자리를 차지하지 않는다.
"""
import json
import os
import re
import subprocess
from datetime import datetime

import pytest

import prepub_review as P
import verify_publish as CLI
from review import prepub_view as V
from review import publish_watch as W
from review.tests import prepub_fixture as F
from review.tests.test_publish_github import world  # noqa: F401 — pytest 픽스처

KST = W.KST
D = '2026-11-10'                         # US 세션 — 기준 시각은 11/11 12:00 KST
KEY = f'hold:us:{D}'
REL = f'reviews/prepublish/us/{D}.json'


def at(m, d, h, mi=0, s=0):
    return datetime(2026, m, d, h, mi, s, tzinfo=KST)


def run(st, repo, now, fetched=True):
    return W.step(st, str(repo), now, fetched, ref='HEAD', who=V.GITHUB)


def hold_rec(state='limit', nxt='retry', attempt=0, last=None, when='2026-11-10T22:10:00Z', shape='n', date=D, **over):
    """cmd_hold 가 쓰는 꼴. shape: m = 11/22 M(7칸), c = 횟수 꼴(9칸), n = 횟수+next(10칸)."""
    rec = {'section': 'us', 'date': date, 'request_id': None, 'state': state,
           'reason': P.PUBLIC_REASON.get(state, '') if isinstance(state, str) else '', 'hold': True, 'recorded_at': when}
    if shape in ('c', 'n'):
        rec['attempt'], rec['last_counted'] = attempt, last
    if shape == 'n':
        rec['next'] = nxt
    rec.update(over)
    return rec


def put(repo, rec, date=D, raw=None):
    rel = f'reviews/prepublish/us/{date}.json'
    if isinstance(raw, bytes):                       # UTF-8 이 아닌 바이트 — F.write 는 글자만 쓴다
        os.makedirs(os.path.dirname(os.path.join(str(repo), rel)), exist_ok=True)
        with open(os.path.join(str(repo), rel), 'wb') as fh:
            fh.write(raw)
    else:
        F.write(repo, rel, raw if raw is not None else P._dumps(rec))
    return F.commit(repo, f'Hold {date} brief')


def holds(st):
    return [e for e in st['events'] if e['key'].startswith('hold:')]


def others(st):
    return [(e['id'], e['kind'], e['key'], e['text'], e['status']) for e in st['events']
            if not e['key'].startswith('hold:')]


def shipped(st, now):
    return [e for e in W.build_outbox(st, now)['events'] if e['key'].startswith('hold:')]


def base_state(repo, now=None):
    st = run(W.new_state('x'), repo, now or at(11, 11, 7))
    for e in st['events']:
        e['status'] = 'sent'                         # 앞 사건은 이미 갔다 — 이 시험은 막힘만 본다
    return st


# ── 1. 보류 기록 push 가 감시를 깨운다 ─────────────────────────────────────────

def test_a_hold_record_push_wakes_the_watch():
    import fnmatch
    path = os.path.join(os.path.dirname(CLI.__file__), '..', '.github', 'workflows', 'publish-watch.yml')
    y = open(path, encoding='utf-8').read()
    push = y.split('push:', 1)[1].split('schedule:', 1)[0]
    pats = re.findall(r"- '([^']+)'", push)
    assert 'reviews/prepublish/**' in pats
    for p in ("posts/**", "kr/posts/**", "verification/**"):          # 원래 경로는 그대로
        assert p in pats
    assert any(fnmatch.fnmatch(REL, p.replace('**', '*')) for p in pats)


# ── 2. 살아 있는 막힘 → 사건 하나 ────────────────────────────────────────────────

def test_a_live_hold_makes_one_event_with_the_closed_text(tmp_path):
    repo = F.init(tmp_path)
    st = base_state(repo)
    put(repo, hold_rec('limit', 'retry', attempt=0))
    run(st, repo, at(11, 11, 8))
    ev = holds(st)
    assert len(ev) == 1 and ev[0]['kind'] == 'missing' and ev[0]['key'] == KEY and ev[0]['held'] == 1
    assert ev[0]['text'] == ('[글 막힘] US 일간 11/10 · 자동 재시도 예정\n'
                             '발행 전 검사를 끝내지 못해 글을 올리지 않았어요\n'
                             '이유: codex 사용 한도\n'
                             '다음: 재시도 루틴이 다음 차례에 처음부터 다시 써요(언제인지는 기록에 없어요)\n'
                             '기록 11/11 07:10 KST · 이 날짜의 센 실패 0번')
    assert [e['id'] for e in shipped(st, at(11, 11, 8))] == [ev[0]['id']]
    assert st['holds'][KEY] == {'n': 1, 'sig': 'limit|retry', 'live': True}


def test_person_next_and_old_shape_records(tmp_path):
    repo = F.init(tmp_path)
    st = base_state(repo)
    put(repo, hold_rec('timeout', 'person', attempt=2, last='timeout', when='2026-11-11T01:41:00Z'))
    run(st, repo, at(11, 11, 11))
    t = holds(st)[-1]['text']
    assert t.startswith('[글 막힘] US 일간 11/10 · 사람 확인 필요\n')
    assert '이유: 마감까지 검토가 오지 않았어요\n' in t
    assert '다음: 자동으로 다시 쓰지 않아요 — 원인을 고친 뒤 잠금을 풀어야 해요(unhold)\n' in t
    assert t.endswith('기록 11/11 10:41 KST · 이 날짜의 센 실패 2번')
    for shape, code in (('c', 'auth_missing'), ('m', 'failed')):     # next 가 없는 옛 꼴 — 부호로 미루어 채우지 않는다
        put(repo, hold_rec(code, shape=shape, attempt=0))
        run(st, repo, at(11, 11, 11, 5))
        t = holds(st)[-1]['text']
        assert t.startswith('[글 막힘] US 일간 11/10 · 다음 동작 모름\n') and '다음: 다음 동작은 기록에 없어요' in t
        assert ('센 실패 수는 기록에 없어요' in t) == (shape == 'm')
    assert st['holds'][KEY]['sig'] == 'failed|?' and [e['held'] for e in holds(st)] == [1, 2, 3]


def test_the_first_run_baseline_sends_no_hold(tmp_path):
    repo = F.init(tmp_path)
    put(repo, hold_rec())
    st = run(W.new_state('처음 실행했어요', baseline=True), repo, at(11, 11, 8))
    assert holds(st) == [] and st['holds'][KEY]['live'] is True
    run(st, repo, at(11, 11, 9))                                      # 같은 서명 — 기준선 뒤에도 보내지 않는다
    assert holds(st) == []


# ── 4. 같은 서명은 한 번, A→B→A 는 매번 ───────────────────────────────────────────

def test_the_same_signature_across_retry_slots_is_one_event(tmp_path):
    repo = F.init(tmp_path)
    st = base_state(repo)
    for i, when in enumerate(('2026-11-10T22:10:00Z', '2026-11-11T00:10:00Z', '2026-11-11T02:10:00Z')):
        put(repo, hold_rec('limit', 'retry', attempt=1, last='timeout', when=when))
        run(st, repo, at(11, 11, 8 + i))
        if i == 0:
            first = holds(st)[0]
            W.apply_acks(st, {(first['id'], W.text_hash(first['text']))}, set(), at(11, 11, 8, 30))
    assert len(holds(st)) == 1 and holds(st)[0]['status'] == 'sent'
    assert shipped(st, at(11, 11, 10)) == []


def test_a_b_a_makes_a_new_round_each_time_even_in_the_same_second(tmp_path):
    repo = F.init(tmp_path)
    st = base_state(repo)
    now = at(11, 11, 8)
    for state, nxt in (('limit', 'retry'), ('timeout', 'person'), ('limit', 'retry')):
        put(repo, hold_rec(state, nxt, attempt=1, last='timeout'))
        run(st, repo, now)                                            # 같은 초 — 시각은 번호에 들지 않는다
    ev = holds(st)
    assert [e['held'] for e in ev] == [1, 2, 3] and len({e['id'] for e in ev}) == 3
    assert [e['status'] for e in ev] == ['cancelled', 'cancelled', 'pending']    # 지금 회차가 아닌 대기는 닫는다
    assert [e['id'] for e in shipped(st, now)] == [ev[2]['id']]
    assert ev[0]['text'] == ev[2]['text']                             # 본문은 같아도 회차가 달라 다른 사건


def test_a_lost_state_does_not_fold_the_new_round_into_old_acks(tmp_path):
    """상태를 잃고 회차가 1 부터 다시 시작해도 born 이 달라 옛 전송 확인에 흡수되지 않는다(§13-4, §14-2)."""
    repo = F.init(tmp_path)
    put(repo, hold_rec())
    a = run(W.new_state('x'), repo, at(11, 11, 8))
    b = run(W.new_state('x'), repo, at(11, 11, 8))                   # 같은 판·같은 초에 새로 시작
    ea, eb = holds(a)[0], holds(b)[0]
    assert ea['held'] == eb['held'] == 1 and ea['text'] == eb['text']
    assert a['born'] != b['born'] and re.fullmatch(r'[0-9a-f]{32}', a['born'])
    assert ea['id'] != eb['id'] and ea['base'] != eb['base']
    W.apply_acks(b, {(ea['id'], W.text_hash(ea['text']))}, set(), at(11, 11, 9))
    assert eb['status'] == 'pending'


def test_born_is_a_random_token_not_a_clock(tmp_path, monkeypatch):
    import secrets
    calls = []
    real = secrets.token_hex
    monkeypatch.setattr(secrets, 'token_hex', lambda n=None: calls.append(n) or real(n))
    repo = F.init(tmp_path)
    put(repo, hold_rec())
    st = run(W.new_state('x'), repo, at(11, 11, 8))
    assert calls and st['born'] not in json.dumps(at(11, 11, 8).isoformat())
    born = st['born']
    run(st, repo, at(11, 11, 9))
    assert st['born'] == born                                        # 한 번 적고 그대로 쓴다


# ── 5. 발행·reviewed·7일 창 밖·훑지 못한 실행 ──────────────────────────────────────

def test_publishing_the_held_date_cancels_the_pending_hold_and_makes_none(tmp_path):
    repo = F.init(tmp_path)
    st = base_state(repo)
    put(repo, hold_rec())
    run(st, repo, at(11, 11, 8))
    F.publish(repo, 'us', D)                                          # 재시도가 글을 올렸다(기록은 남아 있다)
    run(st, repo, at(11, 11, 9))
    assert [e['status'] for e in holds(st)] == ['cancelled'] and shipped(st, at(11, 11, 9)) == []
    assert st['holds'][KEY]['live'] is False
    assert any(e['kind'] == 'publish' and e['key'] == f'posts/{D}.html' for e in st['events'])   # 글 알림이 닫는다


@pytest.mark.parametrize('rec', [
    hold_rec(state='reviewed'),                                      # hold:true 여도 reviewed 는 살아 있지 않다
    hold_rec(hold=False), hold_rec(hold='true'), hold_rec(hold=1),
    {'section': 'us', 'date': D, 'state': 'reviewed', 'facts_done': True},
    '[1, 2]', 'null', '"hold"', '{}',                                # 읽히지만 세움 기록이 아니다(못 읽는 글자는 아래 2회차 절)
])
def test_records_that_are_not_live_holds_make_none(tmp_path, rec):
    repo = F.init(tmp_path)
    st = base_state(repo)
    put(repo, rec if isinstance(rec, dict) else None, raw=None if isinstance(rec, dict) else rec)
    run(st, repo, at(11, 11, 8))
    assert holds(st) == [] and KEY not in st['holds']


def test_an_old_record_makes_none_and_ages_out_of_the_live_list(tmp_path):
    repo = F.init(tmp_path)
    st = base_state(repo, at(11, 11, 7))
    put(repo, hold_rec(date='2026-11-02'), date='2026-11-02')        # 9일 전 — 창 밖
    run(st, repo, at(11, 11, 8))
    assert holds(st) == []
    put(repo, hold_rec())
    run(st, repo, at(11, 11, 9))
    assert len(holds(st)) == 1
    run(st, repo, at(11, 18, 9))                                     # 같은 기록이 7일 창 밖으로
    assert holds(st)[0]['status'] == 'cancelled' and shipped(st, at(11, 18, 9)) == []


@pytest.mark.parametrize('name', ['2026-11-31.json', '2026-11-10.json.bak', 'x2026-11-10.json', '2026-11-1.json'])
def test_the_date_comes_only_from_a_real_file_name(tmp_path, name):
    repo = F.init(tmp_path)
    st = base_state(repo)
    F.write(repo, f'reviews/prepublish/us/{name}', P._dumps(hold_rec()))
    F.commit(repo, 'odd name')
    run(st, repo, at(11, 11, 8))
    assert holds(st) == []


def test_a_run_that_could_not_scan_ships_no_pending_hold(tmp_path, monkeypatch):
    repo = F.init(tmp_path)
    st = base_state(repo)
    put(repo, hold_rec())
    run(st, repo, at(11, 11, 8))
    ev = holds(st)[0]
    run(st, repo, at(11, 11, 9), fetched=False)                       # step 이 일찍 돌아가는 갈래
    assert ev['status'] == 'pending' and shipped(st, at(11, 11, 9)) == []
    real = V._git

    def broken(root, *args):
        if 'reviews/prepublish/us/' in args or args[:2] == ('cat-file', 'blob'):
            raise V.GitError('읽기 실패')
        return real(root, *args)
    monkeypatch.setattr(V, '_git', broken)                             # 글 읽기는 되고 기록 훑기만 실패
    before = others(st)
    run(st, repo, at(11, 11, 10))
    assert ev['status'] == 'pending' and shipped(st, at(11, 11, 10)) == []
    assert others(st) == before and st['fetch'] == {}                  # 기존 판정·조회 실패 표시는 그대로
    monkeypatch.setattr(V, '_git', real)
    run(st, repo, at(11, 11, 11))                                     # 다시 훑으면 같은 회차가 실린다
    assert [e['id'] for e in shipped(st, at(11, 11, 11))] == [ev['id']] and len(holds(st)) == 1


def test_a_corrupt_read_failure_mid_main_tree_also_ships_none(tmp_path, monkeypatch):
    repo = F.init(tmp_path)
    st = base_state(repo)
    put(repo, hold_rec())
    run(st, repo, at(11, 11, 8))
    monkeypatch.setattr(W, '_tree', lambda root, rev: (_ for _ in ()).throw(V.GitError('x')))
    run(st, repo, at(11, 11, 9))
    assert shipped(st, at(11, 11, 9)) == [] and holds(st)[0]['status'] == 'pending'


# ── 6. 닫힌 표 밖의 글자는 싣지 않는다 ──────────────────────────────────────────────

JUNK = 'eyJhbGciOi 검토 답 원문 rid-us-2026'
ALLOWED_LINES = (
    {f'[글 막힘] US 일간 11/10 · {h}' for h in ('자동 재시도 예정', '사람 확인 필요', '다음 동작 모름')}
    | {'발행 전 검사를 끝내지 못해 글을 올리지 않았어요'}
    | {f'이유: {r}' for r in W.HOLD_REASON.values()} | {'이유: 이유 부호를 읽지 못했어요'}
    | {f'다음: {t}' for t in W.HOLD_NEXT_TEXT.values()} | {'다음: 다음 동작은 기록에 없어요'}
)
LAST_LINE = re.compile(r'(기록 \d{1,2}/\d{2} \d{2}:\d{2} KST|기록 시각 모름) · '
                       r'(이 날짜의 센 실패 \d{1,2}번|센 실패 수는 기록에 없어요)')


@pytest.mark.parametrize('rec', [
    hold_rec(reason=JUNK, request_id=JUNK, extra=JUNK),
    hold_rec(state=JUNK), hold_rec(state=['limit']), hold_rec(next=JUNK), hold_rec(next='stop'),
    hold_rec(attempt=JUNK), hold_rec(attempt=100), hold_rec(attempt=-1), hold_rec(attempt=True), hold_rec(attempt=1.0),
    hold_rec(recorded_at=JUNK), hold_rec(recorded_at='9999-12-31T23:59:59Z'), hold_rec(recorded_at='2026-13-40T99:99:99Z'),
    hold_rec(recorded_at='2026-11-10T22:10:00Z\n' + JUNK), hold_rec(section=JUNK, date=JUNK),
    dict(hold_rec(), **{JUNK: JUNK}),
])
def test_the_text_comes_only_from_closed_tables(tmp_path, rec):
    repo = F.init(tmp_path)
    st = base_state(repo)
    put(repo, rec)
    run(st, repo, at(11, 11, 8))
    (ev,) = holds(st)                                                # 꼴이 틀려도 사건은 만든다
    lines = ev['text'].split('\n')
    assert len(lines) == 5 and all(x in ALLOWED_LINES for x in lines[:4]) and LAST_LINE.fullmatch(lines[4])
    assert 'eyJ' not in ev['text'] and '원문' not in ev['text'] and 'rid-' not in ev['text']
    blob = W.dumps_state(st)
    assert 'eyJ' not in blob and '원문' not in blob                    # 상태(공개 가지)에도 기록의 글자가 없다
    assert st['holds'][KEY]['sig'] in W._HOLD_SIGS


def test_the_reason_table_is_exactly_the_eighteen_codes():
    assert set(W.HOLD_REASON) == set(P.NOT_RUN) | set(P.HOLD_CODES) and len(W.HOLD_REASON) == 18
    assert set(W.HOLD_NEXT_TEXT) == set(P.NEXT_VALUES)
    assert W.HOLD_SECTIONS == ('us',)


def test_the_kst_overflow_is_an_unknown_time_not_a_crash(tmp_path):
    repo = F.init(tmp_path)
    st = base_state(repo)
    put(repo, hold_rec(recorded_at='9999-12-31T23:59:59Z'))
    run(st, repo, at(11, 11, 8))
    assert holds(st)[0]['text'].endswith('기록 시각 모름 · 이 날짜의 센 실패 0번')


# ── 8·9. 기존 글 사건은 그대로 ─────────────────────────────────────────────────────

def test_existing_post_events_are_unchanged_by_holds(tmp_path, monkeypatch):
    """같은 레포·같은 시각을 두 상태로 나란히 계산한다 — 하나는 보류 기록 훑기를 끈다. 기존 사건(id·본문·상태·순서)과
    세션·글 상태가 같아야 한다. 막힘 → 발행(기준 시각 뒤) → 「해소」, 훑기 실패 실행, 둘째 날짜 막힘을 지난다."""
    repo = F.init(tmp_path)
    real = W._hold_scan
    on, off = W.new_state('x'), W.new_state('x')
    steps = [
        (at(11, 10, 8), None),
        (at(11, 11, 8), lambda: put(repo, hold_rec())),
        (at(11, 11, 9), lambda: put(repo, hold_rec('timeout', 'person', attempt=2, last='timeout'))),
        (at(11, 11, 10), 'nofetch'),
        (at(11, 11, 13), lambda: F.publish(repo, 'us', D)),          # 기준 시각 뒤에 올라옴 — 미발행 → 해소
        (at(11, 11, 14), lambda: F.publish(repo, 'kr', '2026-11-11')),
        (at(11, 12, 13), lambda: put(repo, hold_rec(date='2026-11-11'), date='2026-11-11')),
        (at(11, 12, 14), lambda: F.publish(repo, 'us', '2026-11-11')),
    ]
    for now, act in steps:
        if callable(act):
            act()
        for st, scan in ((on, real), (off, lambda *a, **k: None)):
            monkeypatch.setattr(W, '_hold_scan', scan)
            run(st, repo, now, fetched=act != 'nofetch')
            doc = W.build_outbox(st, now)
            # 기존 사건 앞 3건만 전송 확인 — 막힘은 맨 뒤라 이 확인에 끼지 않는다
            first3 = [e for e in doc['events'] if not e['key'].startswith('hold:')][:3]
            W.apply_acks(st, {(e['id'], e['hash']) for e in first3}, set(), now)
        assert others(on) == others(off)
        assert on['sessions'] == off['sessions'] and on['posts'] == off['posts']
        assert [e for e in W.build_outbox(on, now)['events'] if not e['key'].startswith('hold:')] == \
            W.build_outbox(off, now)['events']
    assert holds(on) and not holds(off)
    kinds = [x[1] for x in others(on)]
    assert 'resolved' in kinds and 'missing' in kinds and 'publish' in kinds   # 「미발행」·「해소」·발행 알림은 그대로
    assert all(e['status'] == 'cancelled' for e in holds(on))         # 두 날짜 모두 글이 올라와 막힘은 닫혔다


def test_existing_events_come_first_in_the_outbox(tmp_path):
    repo = F.init(tmp_path)
    st = W.new_state('x')
    put(repo, hold_rec())                                           # 막힘이 먼저 쌓여도
    run(st, repo, at(11, 11, 8))
    F.publish(repo, 'kr', '2026-11-10')
    run(st, repo, at(11, 11, 9))
    keys = [e['key'] for e in W.build_outbox(st, at(11, 11, 9))['events']]
    i = keys.index(KEY)
    assert i == len(keys) - 1 and all(not k.startswith('hold:') for k in keys[:i])


def test_cancel_never_touches_events_without_the_hold_mark(tmp_path):
    repo = F.init(tmp_path)
    st = W.new_state('x')
    run(st, repo, at(11, 11, 13))                                    # US 11/10 미발행 경고(대기 중)
    W.add_event(st, 'missing', 'hold:us:2026-11-09', '손으로 만든 held 없는 사건', at(11, 11, 13))
    put(repo, hold_rec())
    run(st, repo, at(11, 11, 14))
    run(st, repo, at(11, 11, 15))
    assert {e['status'] for e in st['events'] if 'held' not in e} == {'pending'}


def _state_with(n, size=20):
    st = W.new_state('x')
    st.update(reset=None, last_seen='a' * 40, last_ok=at(11, 10, 13).isoformat())
    for i in range(n):
        W.add_event(st, 'publish', f'posts/2027-01-{i:04d}.html', '가' * size, at(11, 10, 13), extra=str(i))
    return st


def _with_holds(st, k):
    st['born'] = 'b' * 32
    for j in range(k):
        key = f'hold:us:2026-11-{10 + j:02d}'
        eid = W.add_event(st, 'missing', key, f'[글 막힘] {j}', at(11, 10, 12), extra=f'held|{"b" * 32}|1')
        ev = next(e for e in st['events'] if e['id'] == eid)
        ev['held'] = 1
        st['events'].insert(0, st['events'].pop())                   # 막힘이 기존 사건보다 먼저 쌓였다
    st[W.HOLD_SHIP] = [e['id'] for e in st['events'] if 'held' in e]
    return st


@pytest.mark.parametrize('n, size, k', [(498, 20, 1), (499, 20, 1), (500, 20, 1), (499, 20, 2), (620, 20, 1),
                                        (86, 3000, 1), (87, 3000, 1), (88, 3000, 3)])
def test_holds_never_displace_existing_events_or_their_overflow(n, size, k):
    plain = _state_with(n, size)
    want = W.build_outbox(plain, at(11, 10, 13))['events']
    st = _with_holds(_state_with(n, size), k)
    got = W.build_outbox(st, at(11, 10, 13))['events']
    base = [e for e in got if not e['key'].startswith('hold:')]
    front = [e for e in base if e['key'] != W.OVERFLOW_KEY]
    assert [e['id'] for e in front] == [e['id'] for e in want if e['key'] != W.OVERFLOW_KEY]
    # 기존 사건 부분은 막힘이 없을 때와 같은 자리·같은 순서로 맨 앞
    assert [e['key'] for e in got[:len(front)]] == [e['key'] for e in front]
    assert len(got) <= W.MAX_EVENTS and len(W.dumps_outbox({'events': got}).encode()) <= W.MAX_BYTES
    if any(e['key'] == W.OVERFLOW_KEY for e in want):                # 기존 사건이 넘쳤으면 막힘은 싣지 않는다
        assert not [e for e in got if e['key'].startswith('hold:')]
    hold_at = [i for i, e in enumerate(got) if e['key'].startswith('hold:')]
    assert all(i >= len(front) for i in hold_at)                      # 막힘은 늘 기존 사건 뒤


def test_an_overflow_caused_by_holds_goes_after_existing_events():
    st = _with_holds(_state_with(498), 3)                            # 498 + 막힘 3 = 501 → 넘침
    got = W.build_outbox(st, at(11, 10, 13))['events']
    keys = [e['key'] for e in got]
    assert len(got) == W.MAX_EVENTS and keys[:498] == [f'posts/2027-01-{i:04d}.html' for i in range(498)]
    assert keys.count(W.OVERFLOW_KEY) == 1 and keys.index(W.OVERFLOW_KEY) >= 498
    assert sum(k.startswith('hold:') for k in keys) == 1


def test_an_overflow_caused_by_holds_never_takes_an_existing_slot_on_a_later_run():
    """막힘 넘침 알림은 다음 실행에도 기존 사건의 자리 계산에 끼지 않는다(§14-3 — 한 번의 계산만이 아니라)."""
    st = _with_holds(_state_with(498), 3)
    W.build_outbox(st, at(11, 10, 13))                               # 여기서 막힘 넘침 알림이 생긴다
    notice = [e for e in W.pending(st) if e['key'] == W.OVERFLOW_KEY]
    assert len(notice) == 1 and notice[0].get('held_overflow') is True
    for i in (498, 499):
        W.add_event(st, 'publish', f'posts/2027-01-{i:04d}.html', '가' * 20, at(11, 10, 13), extra=str(i))
    got = W.build_outbox(st, at(11, 10, 14))['events']
    want = W.build_outbox(_state_with(500), at(11, 10, 14))['events']
    front = [e['id'] for e in got if not e['key'].startswith('hold:') and e['key'] != W.OVERFLOW_KEY]
    assert front == [e['id'] for e in want] and len(front) == 500     # 기존 500건이 전부 — 하나도 밀리지 않았다
    assert len(got) == 500                                           # 막힘·막힘 넘침 알림은 자리가 없어 다음에
    assert notice[0]['status'] == 'pending' and len(W.pending(st)) == 504
    for e in [x for x in W.pending(st) if not x['key'].startswith('hold:') and x['key'] != W.OVERFLOW_KEY]:
        e['status'] = 'sent'                                         # 기존 사건이 다 나가면
    rest = W.build_outbox(st, at(11, 10, 15))['events']
    keys = [e['key'] for e in rest]
    assert keys.count(W.OVERFLOW_KEY) == 1 and sum(k.startswith('hold:') for k in keys) == 3 and len(keys) == 4


def test_old_cancelled_holds_are_pruned_but_other_cancelled_events_stay(tmp_path):
    repo = F.init(tmp_path)
    st = base_state(repo)
    put(repo, hold_rec())
    run(st, repo, at(11, 11, 8))
    F.publish(repo, 'us', D)
    run(st, repo, at(11, 11, 9))
    assert holds(st)[0]['status'] == 'cancelled'
    W.add_event(st, 'missing', 'us:2026-11-09', '맥 경로에서 취소된 옛 경고', at(11, 11, 9))
    st['events'][-1]['status'] = 'cancelled'
    run(st, repo, at(11, 11, 9) + __import__('datetime').timedelta(days=59))
    assert len(holds(st)) == 1
    run(st, repo, at(11, 11, 9) + __import__('datetime').timedelta(days=61))
    assert holds(st) == [] and any(e['text'] == '맥 경로에서 취소된 옛 경고' for e in st['events'])


def test_unconfirmed_holds_are_never_shipped():
    st = _with_holds(_state_with(3), 2)
    st.pop(W.HOLD_SHIP)
    assert [e['key'] for e in W.build_outbox(st, at(11, 10, 13))['events']] == [
        f'posts/2027-01-{i:04d}.html' for i in range(3)]
    assert len([e for e in W.pending(st) if 'held' in e]) == 2       # 상태에는 대기로 남는다


def test_the_ship_list_is_never_saved():
    st = _with_holds(_state_with(1), 1)
    assert W.HOLD_SHIP not in json.loads(W.dumps_state(st))
    assert W.HOLD_SHIP not in W.loads_state(W.dumps_state(st))


# ── §14-1 막힘 칸만 깨졌으면 막힘 칸만 비운다 ──────────────────────────────────────

@pytest.mark.parametrize('bad', [
    {'holds': 'x'}, {'holds': None}, {'holds': {KEY: 'x'}}, {'holds': {KEY: {'n': 'x', 'sig': 'limit|retry', 'live': True}}},
    {'holds': {'us:2026-11-10': {'n': 1, 'sig': 'limit|retry', 'live': True}}},
    {'holds': {KEY: {'n': 1, 'sig': 'eyJ 원문', 'live': True}}}, {'holds': {KEY: {'n': 1, 'sig': 'limit|retry', 'live': 1}}},
    {'holds': {KEY: {'n': 1, 'sig': 'limit|retry', 'live': True, 'x': 1}}},
    {'born': 7}, {'born': '2026-11-10T22:10:00'}, {'born': None},
])
def test_broken_hold_fields_reset_only_themselves(tmp_path, bad):
    repo = F.init(tmp_path)
    st = base_state(repo)
    put(repo, hold_rec())
    run(st, repo, at(11, 11, 8))
    first, born = holds(st)[0], st['born']
    st.update(bad)
    loaded = W.loads_state(W.dumps_state(st))                         # 공용 검증은 막힘 칸을 보지 않는다
    before = others(loaded), loaded['sessions'], loaded['posts'], loaded['last_seen']
    run(loaded, repo, at(11, 11, 9))
    assert (others(loaded), loaded['sessions'], loaded['posts']) == before[:3]
    assert not any(e['kind'] == 'reset' and e['status'] == 'pending' for e in loaded['events'])
    assert loaded['born'] != born and loaded['holds'][KEY] == {'n': 1, 'sig': 'limit|retry', 'live': True}
    ev = holds(loaded)
    assert len(ev) == 2 and ev[0]['id'] == first['id'] and ev[0]['status'] == 'cancelled'   # 중복이 유실보다 낫다
    assert [e['id'] for e in shipped(loaded, at(11, 11, 9))] == [ev[1]['id']]


def test_broken_hold_fields_do_not_reset_the_state_branch(world):          # noqa: F811
    put(world.src, hold_rec())
    world.sync()
    world.now[0] = at(11, 11, 8)
    assert CLI.main(['--github']) == 0
    st = world.state()
    st['holds'], st['born'] = {'bad': 1}, 7
    bad = world.tmp / 'bad'
    subprocess.run(['git', 'clone', '-q', '-b', CLI.STATE_BRANCH, str(world.origin), str(bad)], check=True)
    (bad / CLI.STATE_FILE).write_text(W.dumps_state(st) + '\n')
    F.commit(bad, 'holds broken')
    F.git(bad, 'push', '-q', 'origin', f'HEAD:{CLI.STATE_BRANCH}')
    world.now[0] = at(11, 11, 9)
    assert CLI.main(['--github']) == 0
    names = F.git(world.origin, 'ls-tree', '--name-only', CLI.STATE_BRANCH).split()
    assert sorted(names) == ['outbox.json', 'verify_publish.json']    # 손상 복사본 없음 = 전체 초기화 없음
    after = world.state()
    assert [e['kind'] for e in after['events'] if e['kind'] == 'reset'] == ['reset']
    assert after['sessions'] == st['sessions'] and isinstance(after['born'], str)
    assert [e['key'] for e in world.outbox()['events']][-1] == KEY


# ── 맥 요약 이름표 ─────────────────────────────────────────────────────────────

def test_the_mac_summary_names_hold_keys():
    assert W._key_label(KEY) == 'US 일간 11/10 글 막힘'
    for k in ('hold:kr:2026-11-10', 'hold:us:2026-11-31', 'hold:us:x', 'hold:us:2026-11-10:1'):
        assert W._key_label(k) == '알 수 없는 항목'
    st = W.new_state('x')
    W.add_event(st, 'missing', KEY, '본문', at(11, 11, 8), extra='held|x|1')
    assert any('US 일간 11/10 글 막힘' in x for x in W.summary_lines_from(st, at(11, 11, 8)))

# ── codex 구현 2회차 #2·#4·#5 — 기록을 읽는 길은 하나, 결과는 셋(살아 있음·아님·못 읽음) ─────────────

BIG = '가' * 30000                                  # UTF-8 90 KB — 옛 64 KiB 갈래를 넘는 크기
DEEP = '[' * 20000 + ']' * 20000                    # 64 KiB 미만이지만 json.loads 가 RecursionError 를 내는 깊이


def raw_rec(rec, extra):
    """정상 기록 글자 끝에 칸 하나(`"extra": <글자 그대로>`)를 더 붙인 유효 JSON."""
    return P._dumps(rec).rstrip()[:-1].rstrip() + ',\n  "extra": ' + extra + '\n}\n'


def test_the_deep_fixture_really_breaks_the_plain_parser():
    with pytest.raises(RecursionError):
        json.loads(raw_rec(hold_rec(), DEEP))


@pytest.mark.parametrize('extra', [DEEP, json.dumps(BIG), '{"a": ' + DEEP + ', "b": "' + BIG + '"}'])
def test_a_deep_or_big_live_hold_is_read_like_any_other(tmp_path, extra):
    repo = F.init(tmp_path)
    st = base_state(repo)
    put(repo, None, raw=raw_rec(hold_rec('limit', 'retry', attempt=2), extra))
    run(st, repo, at(11, 11, 8))
    ev = holds(st)
    assert len(ev) == 1 and st['holds'][KEY]['sig'] == 'limit|retry'
    assert '자동 재시도 예정' in ev[0]['text'] and '센 실패 2번' in ev[0]['text'] and '가가' not in ev[0]['text']


def test_a_signature_change_between_two_big_records_is_a_new_round(tmp_path):
    repo = F.init(tmp_path)
    st = base_state(repo)
    put(repo, None, raw=raw_rec(hold_rec('limit', 'retry'), json.dumps(BIG)))
    run(st, repo, at(11, 11, 8))
    put(repo, None, raw=raw_rec(hold_rec('timeout', 'person'), json.dumps(BIG)))
    run(st, repo, at(11, 11, 9))
    assert [e['held'] for e in holds(st)] == [1, 2] and [e['status'] for e in holds(st)] == ['cancelled', 'pending']
    assert st['holds'][KEY] == {'n': 2, 'sig': 'timeout|person', 'live': True}


@pytest.mark.parametrize('rec, extra', [
    (hold_rec(state='reviewed'), json.dumps(BIG)), (hold_rec(state='reviewed'), DEEP),
    (hold_rec(hold=False), json.dumps(BIG)), (hold_rec(hold=False), DEEP),
])
def test_a_big_or_deep_record_that_is_not_a_hold_is_not_live_and_closes_the_pending_one(tmp_path, rec, extra):
    repo = F.init(tmp_path)
    st = base_state(repo)
    put(repo, hold_rec())
    run(st, repo, at(11, 11, 8))
    put(repo, None, raw=raw_rec(rec, extra))
    run(st, repo, at(11, 11, 9))
    assert [e['status'] for e in holds(st)] == ['cancelled'] and shipped(st, at(11, 11, 9)) == []
    assert st['holds'][KEY]['live'] is False
    (tmp_path / 'b').mkdir()
    other = F.init(tmp_path / 'b')
    fresh = base_state(other)
    put(other, None, raw=raw_rec(rec, extra))
    run(fresh, other, at(11, 11, 8))
    assert holds(fresh) == [] and KEY not in fresh['holds']


UNREADABLE = ['not json', '', '{"hold": true, "state": "limit"', '{"hold": true, "hold": false, "state": "limit"}',
              b'\xff\xfe{"hold": true}', '{"hold": true}]', '{"hold": true} {"hold": false}',
              '{"hold": true, "state": "reviewed", "state": "limit"}', '{"hold": true, "next": "retry", "next": "person"}',
              '{"hold": true, "x": [1,,2]}', '{"hold": true, "x": {"a" 1}}', '{"hold": true, "x": [[}]}', '{"hold": true, "x": NaN}',
              '{"hold": true, "x": 01}', '{"hold": true,}', '{"hold": true, "x": "a\tb"}', '\ufeff{"hold": true}']


@pytest.mark.parametrize('raw', UNREADABLE)
def test_an_unreadable_record_is_a_live_hold_with_every_value_unknown(tmp_path, raw):
    repo = F.init(tmp_path)
    st = base_state(repo)
    put(repo, None, raw=raw)
    run(st, repo, at(11, 11, 8))
    ev = holds(st)
    assert len(ev) == 1 and ev[0]['text'] == (
        '[글 막힘] US 일간 11/10 · 다음 동작 모름\n발행 전 검사를 끝내지 못해 글을 올리지 않았어요\n'
        '이유: 이유 부호를 읽지 못했어요\n다음: 다음 동작은 기록에 없어요\n기록 시각 모름 · 센 실패 수는 기록에 없어요')
    sig = st['holds'][KEY]['sig']
    assert re.fullmatch(r'\?\|\?\|[0-9a-f]{16}', sig) and sig[4:] not in json.dumps(ev[0], ensure_ascii=False)


def test_unreadable_records_round_by_their_bytes_not_by_the_push(tmp_path):
    repo = F.init(tmp_path)
    st = base_state(repo)
    put(repo, None, raw='{"hold": true, "state": "limit"')
    run(st, repo, at(11, 11, 8))
    run(st, repo, at(11, 11, 8, 10))                                  # 같은 판을 다시 — 상태 칸 검사를 지나야 한다
    assert [e['held'] for e in holds(st)] == [1] and st['holds'][KEY]['n'] == 1
    F.write(repo, 'reviews/prepublish/us/2026-11-09.json', P._dumps({'state': 'reviewed'}))
    F.commit(repo, 'other push, same bytes for the held date')
    run(st, repo, at(11, 11, 8, 20))
    assert [e['held'] for e in holds(st)] == [1]
    put(repo, None, raw='{"hold": true, "state": "timeout"')          # 바이트가 달라졌다 — 둘 다 못 읽는 기록
    run(st, repo, at(11, 11, 9))
    assert [e['held'] for e in holds(st)] == [1, 2] and [e['status'] for e in holds(st)] == ['cancelled', 'pending']
    put(repo, hold_rec('timeout', 'person'))                          # 읽히는 기록으로 — 또 새 회차
    run(st, repo, at(11, 11, 10))
    assert [e['held'] for e in holds(st)] == [1, 2, 3] and st['holds'][KEY]['sig'] == 'timeout|person'


@pytest.mark.parametrize('sig', ['?|?|0123456789abcdef', '?|?'])
def test_the_state_accepts_only_closed_signatures(tmp_path, sig):
    st = {'born': 'ab' * 16, 'holds': {KEY: {'n': 3, 'sig': sig, 'live': True}}}
    assert W._hold_state(st)[0] == {KEY: {'n': 3, 'sig': sig, 'live': True}}
    for bad in ('?|?|0123456789abcdeg', '?|?|0123', 'limit|retry|0123456789abcdef', '?|?|0123456789abcdef\n'):
        st = {'born': 'ab' * 16, 'holds': {KEY: {'n': 3, 'sig': bad, 'live': True}}}
        assert W._hold_state(st)[0] == {}


def _plain_top(text):
    """보통 해석기로 읽은 맨 위 층 — 안쪽은 None, 0-99 밖의 숫자는 `_HOLD_NUM`."""
    def scalar(x):
        if isinstance(x, (dict, list)):
            return None
        if isinstance(x, bool) or x is None or isinstance(x, str) or type(x) is int:
            return x
        return W._HOLD_NUM
    v = json.loads(text, parse_int=lambda t: int(t) if len(t) <= 2 and t.isdigit() else 1.5, parse_float=lambda t: 1.5)
    return ({k: scalar(x) for k, x in v.items()} if isinstance(v, dict)
            else [scalar(x) for x in v] if isinstance(v, list) else scalar(v))


@pytest.mark.parametrize('text', [
    P._dumps(hold_rec()), P._dumps(hold_rec(shape='m')), P._dumps(hold_rec(state='reviewed')),
    '{"a": "]}[{\\"", "b\\\\": "\\\\", "c": [1, {"d": "}"}], "e": {"f": ["\\"]"]}, "g": 1.5e3, "h": null}',
    '[1, [2, [3]], {"a": {"b": 1}}, "x]"]', '"just a string [{"', '7', ' \n{"a"\t:\r\n[ ] , "b" : { } }\n',
    '{"\\u0068old": true, "state": "\\u006cimit", "x": [[["]"]]], "n": 99, "m": 100, "z": -0, "e": 1E+2}',
    '{}', '[]', 'null', 'true', '-1.5e-3', '""',
])
def test_the_top_reader_agrees_with_the_plain_parser_on_ordinary_json(text):
    assert W._hold_top(text.encode('utf-8')) == _plain_top(text)


def test_the_top_reader_accepts_exactly_what_the_plain_parser_accepts():
    """문법 검사가 보통 해석기와 같은가 — 정상 글자를 한 군데씩 망가뜨린 수천 개로 대조한다(NaN·Infinity 만 다르다: 받지 않는다)."""
    import random
    rnd = random.Random(20261122)
    seeds = [P._dumps(hold_rec()), '{"a": [1, {"b": "x\\"y", "c": [true, null, -0.5e+3]}], "d": {}, "e": []}',
             '[{"k": "\\u00e9\\n"}, 12, "s", [[]], {"a": {"b": {"c": 1}}}]']
    alphabet = '{}[],:"\\ \n0123456789.-+eEtrufalsn\x01'
    n = same = 0
    for seed in seeds:
        for _ in range(4000):
            t = list(seed)
            for _ in range(rnd.choice((1, 1, 2, 3))):
                i = rnd.randrange(len(t))
                op = rnd.random()
                if op < 0.4:
                    t[i] = rnd.choice(alphabet)
                elif op < 0.7:
                    del t[i]
                else:
                    t.insert(i, rnd.choice(alphabet))
            text = ''.join(t)
            if 'NaN' in text or 'Infinity' in text:
                continue
            try:
                want = ('ok', _plain_top(text)) if not _dup(text) else ('bad',)
            except ValueError:
                want = ('bad',)
            try:
                got = ('ok', W._hold_top(text.encode('utf-8')))
            except ValueError:
                got = ('bad',)
            n += 1
            same += want[0] == 'ok'
            assert got == want, text
    assert n > 10000 and same > 500                  # 망가뜨린 뒤에도 유효한 글자가 충분히 섞였다


def _dup(text):
    """맨 위 층 객체에 판정에 쓰는 칸이 두 번 있는가(보통 해석기는 받지만 이 읽기는 못 읽은 것으로 본다)."""
    tops = []

    def pairs(items):
        tops.append(items)
        return dict(items)
    v = json.loads(text, object_pairs_hook=pairs)
    return isinstance(v, dict) and any([k for k, _ in tops[-1]].count(x) > 1 for x in ('hold', 'state', 'next'))


def test_the_top_reader_raises_on_what_it_cannot_read():
    for raw in UNREADABLE:
        with pytest.raises(Exception):
            W._hold_top(raw if isinstance(raw, bytes) else raw.encode('utf-8'))


# ── codex 구현 3회차(sol) 다섯 지적 — 사용자 「고치고 4회차」 ─────────────────────────────────

HUGE = '7' * 5000                                   # 파이썬의 정수 변환 한도(4300 자리)를 넘는 맨 위 층 숫자


# 3회차 #3 — 안쪽 값의 괄호 종류([ 와 })가 어긋난 글자를 읽힌 것으로 본다
def test_r3_mismatched_inner_brackets_are_unreadable(tmp_path):
    repo = F.init(tmp_path)
    st = base_state(repo)
    put(repo, None, raw='{"hold":true,"state":"limit","next":"retry","extra":[}}')
    run(st, repo, at(11, 11, 8))
    assert '다음 동작 모름' in holds(st)[0]['text']


# 3회차 #4 — 안 쓰는 칸의 긴 정수가 읽기를 깨 같은 limit|retry 가 재시도마다 새 회차
def test_r3_a_huge_number_in_an_unused_field_does_not_change_the_signature(tmp_path):
    repo = F.init(tmp_path)
    st = base_state(repo)
    put(repo, None, raw=raw_rec(hold_rec('limit', 'retry'), HUGE))
    run(st, repo, at(11, 11, 8))
    put(repo, None, raw=raw_rec(hold_rec('limit', 'retry', when='2026-11-10T23:10:00Z'), HUGE))
    run(st, repo, at(11, 11, 9))
    assert [e['held'] for e in holds(st)] == [1] and st['holds'][KEY]['sig'] == 'limit|retry'


# 3회차 #5 — 안 쓰는 칸의 긴 정수 때문에 reviewed 기록이 모름 막힘으로 나간다
def test_r3_a_reviewed_record_with_a_huge_number_is_not_live(tmp_path):
    repo = F.init(tmp_path)
    st = base_state(repo)
    put(repo, None, raw=raw_rec(hold_rec(state='reviewed'), HUGE))
    run(st, repo, at(11, 11, 8))
    assert holds(st) == []


# 3회차 #4 — holds 만 비고 born·사건 이력이 남으면 새 회차 1 이 옛 전송 확인에 흡수된다
def test_r3_losing_only_the_round_table_still_makes_a_new_event(tmp_path):
    repo = F.init(tmp_path)
    st = base_state(repo)
    put(repo, hold_rec('limit', 'retry'))
    run(st, repo, at(11, 11, 8))
    holds(st)[0]['status'] = 'sent'
    st['holds'] = {}                                                  # born 과 사건 이력은 그대로
    put(repo, hold_rec('timeout', 'person'))
    run(st, repo, at(11, 11, 9))
    assert len(holds(st)) == 2 and len(shipped(st, at(11, 11, 9))) == 1


# 3회차 #9 — 막힘 칸의 긴 정수가 공용 상태 해석(loads_state)을 깨 상태 전체가 새로 시작한다
def test_r3_a_huge_number_in_the_hold_fields_does_not_fail_the_whole_state(tmp_path):
    repo = F.init(tmp_path)
    st = base_state(repo)
    put(repo, hold_rec())
    run(st, repo, at(11, 11, 8))
    raw = W.dumps_state(st)
    raw = raw if isinstance(raw, str) else raw.decode('utf-8')
    cut = re.sub(r'"n":\s*1\b', '"n": ' + HUGE, raw, count=1)
    assert cut != raw and W.loads_state(raw)['events']               # 고친 칸이 실제로 있고, 원래 글자는 읽힌다
    assert W.loads_state(cut)['events']


def test_a_huge_number_outside_the_hold_fields_is_still_a_corrupt_state(tmp_path):
    """막힘 칸 밖의 긴 숫자는 종전대로 상태 전체 손상이다 — 사유 글자도 그대로(JSON 으로 읽지 못함)."""
    repo = F.init(tmp_path)
    st = base_state(repo)
    put(repo, hold_rec())
    run(st, repo, at(11, 11, 8))
    raw = W.dumps_state(st)
    raw = raw if isinstance(raw, str) else raw.decode('utf-8')
    obj = json.loads(raw)
    for cut in (raw.replace('{', '{"x": ' + HUGE + ', ', 1),                       # 맨 위 층의 다른 칸
                re.sub(r'"n":\s*1\b', '"n": ' + HUGE, raw, count=1).replace('{', '{"x": ' + HUGE + ', ', 1),  # 안팎 둘 다
                raw[:-5]):                                                          # 잘린 글자
        with pytest.raises(W.StateError) as err:
            W.loads_state(cut)
        assert isinstance(err.value.__cause__, ValueError) and not str(err.value).startswith('상태 파일 내용이')
    kept = W.loads_state(re.sub(r'"n":\s*1\b', '"n": ' + HUGE, raw, count=1))
    assert 'holds' not in kept and 'born' not in kept
    assert {k: v for k, v in kept.items()} == {k: v for k, v in obj.items() if k not in ('holds', 'born')}
    run(kept, repo, at(11, 11, 9))                                    # 막힘 칸만 새로 — 다시 저장할 수 있다
    assert W.loads_state(W.dumps_state(kept))['born'] != obj['born']


# ── codex 구현 4회차(sol) #9 — 상태 파일의 막힘 칸은 공용 해석 **전에** 떼어 따로 읽는다 ─────────────────

def _state_text(tmp_path):
    repo = F.init(tmp_path)
    st = base_state(repo)
    put(repo, hold_rec())
    run(st, repo, at(11, 11, 8))
    raw = W.dumps_state(st)
    raw = raw if isinstance(raw, str) else raw.decode('utf-8')
    assert re.search(r'"n":\s*1\b', raw) and '"born": "' in raw
    return raw, json.loads(raw)


def _n(raw, value):
    return re.sub(r'"n":\s*1\b', lambda m: '"n": ' + value, raw, count=1)


@pytest.mark.parametrize('damage', [
    lambda raw: _n(raw, HUGE + ', "n": 1'),                                  # 같은 칸 두 번 — 뒤 값이 앞의 긴 숫자를 덮는다
    lambda raw: _n(raw, '[' * 30000 + ']' * 30000),                          # 보통 해석기의 재귀 한도를 넘는 깊이
    lambda raw: re.sub(r'"born": "[0-9a-f]+"', lambda m: '"born": "\\ud800"', raw, count=1),   # 저장할 수 없는 글자
    lambda raw: re.sub(r'"born": "[0-9a-f]+"', lambda m: '"born": ' + HUGE, raw, count=1),
    lambda raw: re.sub(r'"born": "[0-9a-f]+"', lambda m: '"born": "' + 'ab' * 16 + '", "born": 1', raw, count=1),
    lambda raw: _n(raw, 'NaN'), lambda raw: _n(raw, '1.0'), lambda raw: _n(raw, '"1"'),
])
def test_r4_damage_inside_the_hold_fields_drops_only_those_fields(tmp_path, damage):
    raw, obj = _state_text(tmp_path)
    cut = damage(raw)
    assert cut != raw
    st = W.loads_state(cut)
    assert 'holds' not in st and 'born' not in st
    assert st == {k: v for k, v in obj.items() if k not in ('holds', 'born')}     # 기존 칸은 한 글자도 다르지 않다
    W.dumps_state(st).encode('utf-8') if isinstance(W.dumps_state(st), str) else W.dumps_state(st)   # 훑기 전에도 저장된다


def test_r4_sound_hold_fields_load_unchanged(tmp_path):
    raw, obj = _state_text(tmp_path)
    assert W.loads_state(raw) == obj and W.loads_state(raw.encode('utf-8')) == obj


# ── codex 구현 5회차(sol, 상한) 지적 — 사용자 「고쳐서 받아」로 고쳤다. 이 수정은 codex 미검토 ─────────────

# 5회차 #4 — 안 쓰는 칸(meta)이 두 번이면 기록 전체를 못 읽은 것으로 봐 같은 limit|retry 가 재시도마다 새 회차
def test_r5_a_duplicate_unused_key_does_not_change_the_signature(tmp_path):
    repo = F.init(tmp_path)
    st = base_state(repo)
    put(repo, None, raw='{"hold":true,"state":"limit","next":"retry","recorded_at":"2026-11-10T22:10:00Z","meta":1,"meta":2}')
    run(st, repo, at(11, 11, 8))
    put(repo, None, raw='{"hold":true,"state":"limit","next":"retry","recorded_at":"2026-11-10T23:10:00Z","meta":1,"meta":2}')
    run(st, repo, at(11, 11, 9))
    assert [e['held'] for e in holds(st)] == [1] and st['holds'][KEY]['sig'] == 'limit|retry'


# 5회차 #5 — 안 쓰는 칸이 두 번인 reviewed 기록이 모름 막힘으로 나간다
def test_r5_a_reviewed_record_with_a_duplicate_unused_key_is_not_live(tmp_path):
    repo = F.init(tmp_path)
    st = base_state(repo)
    put(repo, None, raw='{"hold":true,"state":"reviewed","meta":1,"meta":2}')
    run(st, repo, at(11, 11, 8))
    assert holds(st) == []


# 5회차 #9 — 막힘 칸 안의 문법 오류·NaN+긴 숫자·잘못된 UTF-8 은 분리기가 못 갈라 상태 전체가 손상으로 간다
@pytest.mark.parametrize('damage', [
    lambda raw: _n(raw, '1,').encode('utf-8'),                                # holds[날짜] 안의 남는 쉼표
    lambda raw: _n(raw, 'NaN, "x": ' + HUGE).encode('utf-8'),                 # NaN 과 긴 숫자가 함께
    lambda raw: re.sub(r'"born": "[0-9a-f]', lambda m: '"born": "\x00', raw, count=1).encode('utf-8').replace(b'\x00', b'\xff'),
])
def test_r5_syntax_damage_inside_the_hold_fields_drops_only_those_fields(tmp_path, damage):
    raw, obj = _state_text(tmp_path)
    st = W.loads_state(damage(raw))
    assert st == {k: v for k, v in obj.items() if k not in ('holds', 'born')}


def test_a_duplicate_unused_key_takes_the_last_value_like_the_plain_parser():
    assert W._hold_top(b'{"hold": true, "attempt": 1, "attempt": 2, "meta": [1], "meta": "x"}') == {
        'hold': True, 'attempt': 2, 'meta': 'x'}


@pytest.mark.parametrize('damage', [
    lambda raw: raw.replace('{', '{"x": [1,], ', 1),                              # 막힘 칸 밖의 남는 쉼표
    lambda raw: _n(raw, '1,').replace('{', '{"x": [1,], ', 1),                    # 안팎 둘 다
    lambda raw: raw.replace('{', '{"x": "\x00", ', 1).encode('utf-8').replace(b'\x00', b'\xff'),   # 밖의 깨진 바이트
    lambda raw: _n(raw, '1}}}'),                                                  # 막힘 칸이 바깥 괄호까지 닫아 버린다
    lambda raw: raw.rstrip()[:-1],                                                # 맨 끝 괄호가 없다
])
def test_damage_outside_the_hold_fields_is_still_a_corrupt_state(tmp_path, damage):
    raw, _ = _state_text(tmp_path)
    with pytest.raises(W.StateError) as err:
        W.loads_state(damage(raw))
    assert isinstance(err.value.__cause__, (ValueError, UnicodeDecodeError)) and not str(err.value).startswith('상태 파일 내용이')
