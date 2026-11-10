"""발행 건별 알림의 GitHub 쪽(2.5단계, 2026-11-10) — `publish_watch` 의 outbox 계약과 `verify_publish.py --github`.

막는 것: outbox 에 실린 경고를 「안 보냈다」고 취소, 전송 확인 없이 outbox 에서 사건이 빠짐, 상한을 넘겨 Worker 가
outbox 를 통째로 거부, push 거절 때 다른 실행의 사건을 덮어씀, 네트워크 실패를 「처음 실행」으로 읽음, push 전에 poke.
원격은 전부 로컬 bare 레포다(네트워크 없음).
"""
import json
import re
import subprocess
from datetime import datetime, timedelta

import pytest

import verify_publish as CLI
from review import prepub_view as V
from review import publish_watch as W
from review.tests import prepub_fixture as F

KST = W.KST
HEX32, HEX64 = re.compile(r'^[0-9a-f]{32}$'), re.compile(r'^[0-9a-f]{64}$')
KINDS = set('publish changed missing resolved late gone back fetch fetch_ok gap reset overflow'.split())


def at(m, d, h, mi=0):
    return datetime(2026, m, d, h, mi, tzinfo=KST)


def pair(e):
    return (e['id'], W.text_hash(e['text']))


def kinds(st):
    return [e['kind'] for e in st['events']]


def run(st, repo, now, who=V.GITHUB):
    return W.step(st, str(repo), now, True, ref='HEAD', who=who)


# ── id·key·hash ───────────────────────────────────────────────────────────

def test_event_id_is_32_hex_of_sha256_and_hash_is_of_text():
    import hashlib
    eid = W.event_id('publish', 'posts/2026-11-10.html', 'fp')
    assert eid == hashlib.sha256('publish|posts/2026-11-10.html|fp'.encode()).hexdigest()[:32] and HEX32.match(eid)
    st = W.new_state('x')
    st['reset'] = None
    W.add_event(st, 'missing', 'us:2026-11-10', '문장', at(11, 10, 13))
    assert st['events'][0]['hash'] == hashlib.sha256('문장'.encode()).hexdigest()
    assert W.add_event(st, 'missing', 'us:2026-11-10', '다른 문장', at(11, 10, 14)) is None      # 같은 id 는 한 번만


def test_keys_follow_contract(tmp_path):
    repo = F.init(tmp_path)
    F.publish(repo, 'us', '2026-11-09')
    st = run(W.new_state('x'), repo, at(11, 10, 13))
    st['last_seen'] = '0' * 40                                           # 기준점을 못 찾게 → gap
    run(st, repo, at(11, 10, 13, 5))
    W.step(st, str(repo), at(11, 10, 16), False, who=V.GITHUB)            # fetch 실패 2시간 넘김
    run(st, repo, at(11, 10, 17))
    by = {e['kind']: e['key'] for e in st['events']}
    assert by == {'reset': 'sys:reset', 'missing': 'kr:2026-11-09', 'publish': 'posts/2026-11-09.html',
                  'gap': 'sys:gap', 'fetch': 'sys:fetch', 'fetch_ok': 'sys:fetch_ok'}
    doc = W.build_outbox(st, at(11, 10, 17))
    for e in doc['events']:
        assert set(e) == {'id', 'hash', 'key', 'kind', 'text', 'created'}
        assert HEX32.match(e['id']) and HEX64.match(e['hash']) and e['hash'] == W.text_hash(e['text'])
        assert e['kind'] in KINDS and 1 <= len(e['key']) <= 200 and 1 <= len(e['text']) <= 3900
        assert datetime.fromisoformat(e['created']).tzinfo is not None
    assert len({e['id'] for e in doc['events']}) == len(doc['events'])
    assert doc['format'] == 'alerts-outbox/1' and doc['last_seen'] == st['last_seen'] and len(doc['last_seen']) == 40
    assert doc['last_ok'] == at(11, 10, 17).isoformat() and doc['generated_at'] == at(11, 10, 17).isoformat()


def test_reset_event_hash_matches_final_text(tmp_path):
    repo = F.init(tmp_path)
    st = run(W.new_state('처음 실행했어요', baseline=True), repo, at(11, 10, 13))
    ev = st['events'][0]
    assert ev['kind'] == 'reset' and ev['text'] and ev['hash'] == W.text_hash(ev['text'])


# ── 확인 주체 ─────────────────────────────────────────────────────────────

def test_github_run_names_github_not_mac_and_same_ids(tmp_path):
    repo = F.init(tmp_path)
    F.publish(repo, 'us', '2026-11-09')
    gh = run(W.new_state('x'), repo, at(11, 10, 13))
    mac = run(W.new_state('x'), repo, at(11, 10, 13), who=V.MAC)
    g = next(e for e in gh['events'] if e['kind'] == 'publish')
    m = next(e for e in mac['events'] if e['kind'] == 'publish')
    assert '[GitHub이 직접 대조]' in g['text'] and 'GitHub 이 짝만 다시 확인했어요' in g['text'] and '맥' not in g['text']
    assert '[맥이 직접 확인]' in m['text'] and 'GitHub' not in m['text']
    assert g['id'] == m['id']                                             # 같은 사건 — 주체는 지문에 안 든다
    assert len(g['text']) < W.MAX_TEXT // 2                               # 지금 문장은 상한에 한참 못 미친다


def test_gone_before_seen_names_github(tmp_path):
    repo = F.init(tmp_path)
    st = run(W.new_state('x'), repo, at(11, 9, 8))
    F.publish(repo, 'us', '2026-11-09')
    F.git(repo, 'rm', '-q', 'posts/2026-11-09.html')
    F.commit(repo, 'remove')
    run(st, repo, at(11, 9, 9))
    gone = next(e for e in st['events'] if e['kind'] == 'gone')
    assert 'GitHub 이 확인하기 전에' in gone['text'] and '맥' not in gone['text']


# ── outbox 에 실린 사건 = 전송됐을 수 있다 ──────────────────────────────────

def test_pending_warning_is_resolved_not_cancelled_in_github_mode(tmp_path):
    repo = F.init(tmp_path)
    F.publish(repo, 'us', '2026-11-09')
    st = run(W.new_state('x'), repo, at(11, 10, 13))                   # KR 미발행 경고 — pending(outbox 에 실렸다)
    F.publish(repo, 'kr', '2026-11-09')
    run(st, repo, at(11, 10, 13, 5))
    warn = next(e for e in st['events'] if e['kind'] == 'missing')
    assert warn['status'] == 'pending' and 'late' not in kinds(st)       # 취소하지 않는다
    res = next(e for e in st['events'] if e['kind'] == 'resolved')
    assert '앞서 생성된 미발행 경고(기준 11/09 23:00 KST)가 풀렸어요' in res['text'] and '보낸' not in res['text']
    ids = [e['id'] for e in W.build_outbox(st, at(11, 10, 13, 5))['events']]
    assert ids.index(warn['id']) < ids.index(res['id'])                  # 같은 key 안에서 경고가 해소보다 앞


def test_only_acked_or_failed_leave_outbox(tmp_path):
    repo = F.init(tmp_path)
    F.publish(repo, 'us', '2026-11-09')
    st = run(W.new_state('x'), repo, at(11, 10, 13))
    ea, eb, ec = st['events']
    a, b, c = ea['id'], eb['id'], ec['id']
    assert W.apply_acks(st, None, None, at(11, 10, 14)) == 0             # 못 읽음 → 그대로
    assert len(W.build_outbox(st, at(11, 10, 14))['events']) == 3
    assert W.apply_acks(st, {pair(ea)}, None, at(11, 10, 14)) == 1       # 한쪽만 읽혀도 확인된 것은 뺀다
    assert W.apply_acks(st, {pair(ea)}, {pair(eb)}, at(11, 10, 14)) == 1
    by = {e['id']: e for e in st['events']}
    assert by[a]['status'] == 'sent' and by[b]['status'] == 'failed' and by[c]['status'] == 'pending'
    assert [e['id'] for e in W.build_outbox(st, at(11, 10, 14))['events']] == [c]
    for _ in range(3):                                                   # 시간이 지나도 저절로 빠지지 않는다
        run(st, repo, at(12, 25, 13))
    assert c in [e['id'] for e in W.pending(st)] and by[a]['status'] == 'sent'      # (새 미발행 경고가 더 쌓였을 뿐)


def test_removed_events_stay_60_days_so_they_are_not_recreated(tmp_path):
    repo = F.init(tmp_path)
    F.publish(repo, 'us', '2026-11-09')
    st = run(W.new_state('x'), repo, at(11, 10, 13))
    pub = next(e for e in st['events'] if e['kind'] == 'publish')
    W.apply_acks(st, {pair(pub)}, set(), at(11, 20, 13))                 # 열흘 뒤에야 전송 확인
    st['last_seen'] = '0' * 40                                           # 전부 다시 계산 — 같은 id 가 다시 나온다
    run(st, repo, at(12, 1, 13))
    assert [e['status'] for e in st['events'] if e['id'] == pub['id']] == ['sent']
    run(st, repo, at(11, 20, 13) + timedelta(days=59))
    assert any(e['id'] == pub['id'] for e in st['events'])               # 확인한 때부터 60일 — 만든 때부터가 아니다
    run(st, repo, at(11, 20, 13) + timedelta(days=61))
    assert not any(e['id'] == pub['id'] for e in st['events'])


# ── 상한 ──────────────────────────────────────────────────────────────────

def _state_with(n, size=20):
    st = W.new_state('x')
    st.update(reset=None, last_seen='a' * 40, last_ok=at(11, 10, 13).isoformat())
    for i in range(n):
        W.add_event(st, 'publish', f'posts/2027-01-{i:04d}.html', '가' * size, at(11, 10, 13), extra=str(i))
    return st


def test_event_count_cap_holds_back_newest_and_adds_one_overflow():
    st = _state_with(620)
    doc = W.build_outbox(st, at(11, 10, 13))
    assert len(doc['events']) == W.MAX_EVENTS
    over = [e for e in doc['events'] if e['key'] == W.OVERFLOW_KEY]
    assert len(over) == 1 and over[0]['kind'] in KINDS and over[0]['text'] == W.OVERFLOW_TEXT
    kept = [e['key'] for e in doc['events'] if e['key'] != W.OVERFLOW_KEY]
    assert kept == [f'posts/2027-01-{i:04d}.html' for i in range(499)]   # 오래된 쪽을 싣고 새 사건을 멈춘다
    assert len(W.pending(st)) == 621                                     # 남긴 것은 상태에 그대로 — 버리지 않는다
    assert over[0]['id'] == W.event_id(W.OVERFLOW_KIND, W.OVERFLOW_KEY, st['events'][499]['id'])   # 처음 남겨진 사건 기준
    again = W.build_outbox(st, at(11, 10, 14))
    assert [e['id'] for e in again['events']] == [e['id'] for e in doc['events']]     # 넘침 알림은 하나만
    W.apply_acks(st, {(e['id'], e['hash']) for e in doc['events']}, set(), at(11, 10, 15))
    rest = W.build_outbox(st, at(11, 10, 15))
    assert len(rest['events']) == 121 and not [e for e in rest['events'] if e['key'] == W.OVERFLOW_KEY]


def test_file_size_cap_binds_before_count():
    st = _state_with(200, size=3000)                                     # 200 × 9KB ≫ 256KB
    doc = W.build_outbox(st, at(11, 10, 13))
    assert len(W.dumps_outbox(doc).encode('utf-8')) <= W.MAX_BYTES
    assert 1 < len(doc['events']) < 200 and doc['events'][-1]['key'] == W.OVERFLOW_KEY
    assert all(len(e['text']) == 3000 for e in doc['events'][:-1])       # 자르지 않는다


def test_oversize_text_is_never_truncated_or_emitted():
    st = _state_with(2)
    W.add_event(st, 'publish', 'posts/2027-02-01.html', '나' * (W.MAX_TEXT + 1), at(11, 10, 13))
    doc = W.build_outbox(st, at(11, 10, 13))
    assert [len(e['text']) for e in doc['events'][:2]] == [20, 20] and doc['events'][2]['key'] == W.OVERFLOW_KEY
    big = next(e for e in st['events'] if e['key'] == 'posts/2027-02-01.html')
    assert big['status'] == 'oversize' and len(big['text']) == W.MAX_TEXT + 1
    W.loads_state(W.dumps_state(st))                                     # 그 상태는 여전히 읽힌다


def test_same_id_with_different_hash_stays_pending(tmp_path):
    # codex 구현 1회 #3 — Worker 가 보낸 것은 옛 본문 A 다. 지금 본문 B 는 전송된 적이 없으니 id 만 보고 빼지 않는다
    repo = F.init(tmp_path)
    F.publish(repo, 'us', '2026-11-09')
    st = run(W.new_state('x'), repo, at(11, 10, 13))
    pub = next(e for e in st['events'] if e['kind'] == 'publish')
    old = (pub['id'], W.text_hash('옛 본문 A'))
    assert W.apply_acks(st, {old}, set(), at(11, 10, 14)) == 0 and pub['status'] == 'pending'
    assert W.apply_acks(st, set(), {old}, at(11, 10, 14)) == 0 and pub['status'] == 'pending'     # /failed 도 같다
    assert pub['id'] in [e['id'] for e in W.build_outbox(st, at(11, 10, 14))['events']]
    pub['hash'] = old[1]                              # 저장된 해시가 낡았어도 지금 문장으로 다시 계산해 견준다
    assert W.apply_acks(st, {old}, set(), at(11, 10, 14)) == 0 and pub['status'] == 'pending'
    assert W.apply_acks(st, {old, pair(pub)}, set(), at(11, 10, 14)) == 1 and pub['status'] == 'sent'


def test_clean_pairs_rejects_anything_odd():
    ok = {'id': 'a' * 32, 'hash': 'b' * 64}
    assert W.clean_pairs([ok]) == {('a' * 32, 'b' * 64)} and W.clean_pairs([]) == set()
    for bad in (None, ok, ['a' * 32], [{'id': 'a' * 32}], [{'id': 'a' * 8, 'hash': 'b' * 64}],
                [{'id': 'a' * 32, 'hash': 'b' * 32}], [{'id': 'A' * 32, 'hash': 'b' * 64}], [ok, 1],
                [{'id': 'a' * 32, 'hash': None}]):
        assert W.clean_pairs(bad) is None


def test_summary_accepts_github_stale_threshold(tmp_path):
    repo = F.init(tmp_path)
    st = run(W.new_state('처음 실행했어요', baseline=True), repo, at(11, 10, 13))
    assert any('마지막 정상 확인이 4시간 전' in x for x in W.summary_lines_from(st, at(11, 10, 17)))
    assert not any('마지막 정상 확인' in x for x in W.summary_lines_from(st, at(11, 10, 17), stale=W.GITHUB_STALE))
    assert any('마지막 정상 확인이 10시간 전' in x for x in W.summary_lines_from(st, at(11, 10, 23), stale=W.GITHUB_STALE))


# ── verify_publish.py --github ─────────────────────────────────────────────

@pytest.fixture
def world(tmp_path, monkeypatch):
    """src(루틴이 글을 올리는 자리) → origin.git(bare) ← work(Actions checkout)."""
    src = F.init(tmp_path)
    origin = tmp_path / 'origin.git'
    subprocess.run(['git', 'clone', '-q', '--bare', str(src), str(origin)], check=True)
    work = tmp_path / 'work'
    subprocess.run(['git', 'clone', '-q', str(origin), str(work)], check=True)

    class Wd:
        pass
    w = Wd()
    w.src, w.origin, w.work, w.tmp = src, origin, work, tmp_path
    w.now = [at(11, 10, 13)]
    w.pokes, w.acks, w.failed = [], None, None
    w.sync = lambda: F.git(src, 'push', '-q', str(origin), 'main')
    w.state = lambda: json.loads(F.git(origin, 'show', f'{CLI.STATE_BRANCH}:{CLI.STATE_FILE}'))
    w.outbox = lambda: json.loads(F.git(origin, 'show', f'{CLI.STATE_BRANCH}:{CLI.OUTBOX_FILE}'))
    w.commits = lambda: F.git(origin, 'rev-list', CLI.STATE_BRANCH).split()
    monkeypatch.setattr(CLI, 'now_kst', lambda: w.now[0])
    monkeypatch.setattr(CLI, 'read_pairs', lambda url, name: w.acks if name == 'acks' else w.failed)
    monkeypatch.setattr(CLI, 'poke', lambda url: w.pokes.append(len(w.commits())))
    monkeypatch.delenv(CLI.WORKER_ENV, raising=False)
    monkeypatch.chdir(work)
    return w


def test_first_run_without_branch_is_baseline(world):
    F.publish(world.src, 'us', '2026-11-09')
    world.sync()
    assert CLI.main(['--github']) == 0
    st, out = world.state(), world.outbox()
    assert [e['kind'] for e in st['events']] == ['reset'] and '기준선으로만' in st['events'][0]['text']
    assert st['sessions']['kr:2026-11-09'] == 'missing_quiet'
    assert out['format'] == 'alerts-outbox/1' and [e['id'] for e in out['events']] == [st['events'][0]['id']]
    assert out['last_ok'] == at(11, 10, 13).isoformat() and out['last_seen'] == F.git(world.src, 'rev-parse', 'HEAD')
    assert len(world.commits()) == 1 and world.pokes == [1]              # 한 커밋, push 뒤 poke 한 번
    assert 'github-actions[bot]' in F.git(world.origin, 'log', '-1', '--format=%an <%ae>|%cn', CLI.STATE_BRANCH)
    assert F.git(world.work, 'status', '--porcelain') == ''              # 작업 트리·index 를 건드리지 않는다
    assert F.git(world.work, 'rev-parse', '--abbrev-ref', 'HEAD') == 'main'


def test_second_run_appends_events_on_top(world):
    F.publish(world.src, 'us', '2026-11-09')
    world.sync()
    CLI.main(['--github'])
    F.publish(world.src, 'kr', '2026-11-09')
    world.sync()
    world.now[0] = at(11, 10, 13, 5)
    assert CLI.main(['--github']) == 0
    assert [e['kind'] for e in world.state()['events']] == ['reset', 'late', 'publish']
    out = world.outbox()
    assert [e['kind'] for e in out['events']] == ['reset', 'late', 'publish']       # 전송 확인을 못 읽었다 → 하나도 안 뺀다
    assert '[GitHub이 직접 대조]' in out['events'][-1]['text']
    assert len(world.commits()) == 2 and world.pokes == [1, 2]


def test_acked_and_failed_ids_leave_outbox_but_stay_in_state(world):
    F.publish(world.src, 'us', '2026-11-09')
    world.sync()
    CLI.main(['--github'])
    F.publish(world.src, 'kr', '2026-11-09')
    world.sync()
    CLI.main(['--github'])
    ids = {e['kind']: (e['id'], e['hash']) for e in world.outbox()['events']}
    world.acks, world.failed = {ids['reset']}, None                      # /failed 를 못 읽어도 /acks 에 나온 것은 뺀다
    CLI.main(['--github'])
    assert [e['kind'] for e in world.outbox()['events']] == ['late', 'publish']
    world.acks, world.failed = {ids['reset'], (ids['publish'][0], 'f' * 64)}, {ids['late']}
    CLI.main(['--github'])
    assert [e['kind'] for e in world.outbox()['events']] == ['publish']  # 같은 id·다른 해시 — 남긴다
    world.acks, world.failed = {ids['reset'], ids['publish']}, {ids['late']}
    CLI.main(['--github'])
    assert world.outbox()['events'] == []
    assert {e['kind']: e['status'] for e in world.state()['events']} == {'reset': 'sent', 'late': 'failed',
                                                                        'publish': 'sent'}


def test_read_pairs_unreadable_or_no_url_is_none(monkeypatch):
    monkeypatch.undo()
    ev = [{'id': 'a' * 32, 'hash': 'b' * 64}]
    assert CLI.read_pairs('', 'acks') is None
    monkeypatch.setattr(CLI, 'http_json', lambda url: (_ for _ in ()).throw(TimeoutError()))
    assert CLI.read_pairs('https://w.example', 'acks') is None
    monkeypatch.setattr(CLI, 'http_json', lambda url: {'format': 'alerts-acks/2', 'events': [{'id': 'zz', 'hash': 'b' * 64}]})
    assert CLI.read_pairs('https://w.example', 'acks') is None           # 형식이 하나라도 다르면 못 읽은 것
    for fmt, body in (('alerts-acks/1', {'ids': ['a' * 32]}), ('alerts-acks/1', {'events': ev}),
                      ('alerts-acks/3', {'events': ev}), (None, {'events': ev})):
        monkeypatch.setattr(CLI, 'http_json', lambda url, f=fmt, b=body: dict(b, format=f))
        assert CLI.read_pairs('https://w.example', 'acks') is None       # 모르는 판(옛 /1 포함) — 아무것도 빼지 않는다
    monkeypatch.setattr(CLI, 'http_json', lambda url: {'format': 'alerts-acks/2', 'ids': ['a' * 32]})
    assert CLI.read_pairs('https://w.example', 'acks') is None           # 새 판인데 events 가 없다
    monkeypatch.setattr(CLI, 'http_json', lambda url: {'format': 'alerts-failed/2', 'events': ev})
    assert CLI.read_pairs('https://w.example', 'acks') is None           # 다른 주소의 응답
    assert CLI.read_pairs('https://w.example', 'failed') == {('a' * 32, 'b' * 64)}


def test_real_http_against_local_server():
    # read_pairs·poke 의 실제 urllib 경로 — 예외를 전부 「못 읽음」으로 삼키므로, 여기가 틀리면 outbox 가 영영 안 비워진다
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer
    seen = []

    class H(BaseHTTPRequestHandler):
        def _send(self, code, obj):
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            seen.append(('GET', self.path))
            if self.path == '/acks':
                self._send(200, {'format': 'alerts-acks/2', 'events': [{'id': 'a' * 32, 'hash': 'c' * 64},
                                                                       {'id': 'b' * 32, 'hash': 'd' * 64}]})
            elif self.path == '/failed':
                self._send(500, {'error': 'x'})
            else:
                self._send(404, {})

        def do_POST(self):
            seen.append(('POST', self.path, self.headers.get('Authorization')))
            self._send(202, {'ok': True})

        def log_message(self, *a):
            pass
    srv = HTTPServer(('127.0.0.1', 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        url = f'http://127.0.0.1:{srv.server_address[1]}'
        assert CLI.read_pairs(url, 'acks') == {('a' * 32, 'c' * 64), ('b' * 32, 'd' * 64)}
        assert CLI.read_pairs(url, 'failed') is None                       # 5xx = 못 읽음
        assert CLI.poke(url) is True
        assert seen == [('GET', '/acks'), ('GET', '/failed'), ('POST', '/poke', None)]      # 인증 헤더 없음
    finally:
        srv.shutdown()
        srv.server_close()
    assert CLI.read_pairs(url, 'acks') is None and CLI.poke(url) is False  # 서버가 없으면 — 예외 없이 못 읽음


def test_worker_url_must_be_https(monkeypatch):
    monkeypatch.setenv(CLI.WORKER_ENV, 'http://w.example/')
    assert CLI.worker_url() == ''
    monkeypatch.setenv(CLI.WORKER_ENV, ' https://w.example/ ')
    assert CLI.worker_url() == 'https://w.example'
    monkeypatch.delenv(CLI.WORKER_ENV)
    assert CLI.worker_url() == '' and CLI.poke('') is False


def test_rejected_push_recomputes_on_newest_main_and_state(world, monkeypatch):
    F.publish(world.src, 'us', '2026-11-09')
    world.sync()
    CLI.main(['--github'])
    other = world.tmp / 'other'
    subprocess.run(['git', 'clone', '-q', str(world.origin), str(other)], check=True)
    real, calls = CLI.push, []

    def racing(root, sha):
        calls.append(sha)
        if len(calls) == 1:                      # 이 실행이 올리기 직전에: main 에 새 글 + 다른 실행이 상태를 먼저 올린다
            F.publish(world.src, 'kr', '2026-11-09')
            world.sync()
            world.now[0] = at(11, 10, 13, 5)
            assert CLI.github(str(other)) == 0
            world.now[0] = at(11, 10, 13, 6)
        return real(root, sha)
    monkeypatch.setattr(CLI, 'push', racing)
    world.now[0] = at(11, 10, 13, 4)
    assert CLI.main(['--github']) == 0
    assert len(calls) == 3                       # 이 실행 2번(거절 → 성공) + 끼어든 실행 1번
    st = world.state()
    assert [e['kind'] for e in st['events']] == ['reset', 'late', 'publish']          # 다른 실행의 사건을 덮지 않았다
    assert st['last_seen'] == F.git(world.src, 'rev-parse', 'HEAD') and st['last_ok'] == at(11, 10, 13, 6).isoformat()
    assert len(world.commits()) == 3             # 기준선 · 끼어든 실행 · 이 실행(fast-forward)
    assert world.pokes == [1, 2, 3]              # 거절된 push 뒤에는 poke 하지 않는다


def test_gives_up_after_three_rejections(world, monkeypatch):
    F.publish(world.src, 'us', '2026-11-09')
    world.sync()
    calls = []
    monkeypatch.setattr(CLI, 'push', lambda root, sha: calls.append(sha) or 'rejected')
    assert CLI.main(['--github']) == 1
    assert len(calls) == CLI.MAX_REJECTED + 1 and world.pokes == []


def test_remote_refusal_is_failure_not_retry(world):
    F.publish(world.src, 'us', '2026-11-09')
    world.sync()
    hook = world.origin / 'hooks' / 'pre-receive'
    hook.write_text('#!/bin/sh\necho no >&2\nexit 1\n')
    hook.chmod(0o755)
    assert CLI.main(['--github']) == 1
    assert world.pokes == [] and F.git(world.origin, 'branch', '--list', CLI.STATE_BRANCH) == ''


def test_unreachable_origin_is_failure_not_first_run(world):
    F.publish(world.src, 'us', '2026-11-09')
    world.sync()
    CLI.main(['--github'])
    before = world.commits()
    F.git(world.work, 'remote', 'set-url', 'origin', str(world.tmp / 'nowhere.git'))
    assert CLI.main(['--github']) == 1
    F.git(world.work, 'remote', 'set-url', 'origin', str(world.origin))
    assert world.commits() == before and world.pokes == [1]


def test_corrupt_state_is_kept_in_branch_and_recomputed(world):
    F.publish(world.src, 'us', '2026-11-09')
    world.sync()
    CLI.main(['--github'])
    first = world.state()['events'][0]
    bad = world.tmp / 'bad'
    subprocess.run(['git', 'clone', '-q', '-b', CLI.STATE_BRANCH, str(world.origin), str(bad)], check=True)
    (bad / CLI.STATE_FILE).write_text('{broken')
    F.commit(bad, 'corrupt')
    F.git(bad, 'push', '-q', 'origin', f'HEAD:{CLI.STATE_BRANCH}')
    world.now[0] = at(11, 10, 14)
    world.acks, world.failed = {pair(first)}, set()
    assert CLI.main(['--github']) == 0
    names = F.git(world.origin, 'ls-tree', '--name-only', CLI.STATE_BRANCH).split()
    assert sorted(names) == ['outbox.json', 'verify_publish.corrupt-20261110140000.json', 'verify_publish.json']
    assert F.git(world.origin, 'show', f'{CLI.STATE_BRANCH}:verify_publish.corrupt-20261110140000.json') == '{broken'
    st = world.state()
    assert [e['kind'] for e in st['events']] == ['reset', 'missing', 'publish']       # 기준선이 아니라 전부 다시
    assert '손상' in st['events'][0]['text'] and '다시 올 수 있어요' in st['events'][0]['text']
    world.now[0] = at(11, 10, 15)
    CLI.main(['--github'])                                                          # 손상본은 다음 커밋에도 남는다
    assert 'verify_publish.corrupt-20261110140000.json' in F.git(world.origin, 'ls-tree', '--name-only',
                                                                 CLI.STATE_BRANCH)


def test_branch_without_state_file_is_not_a_quiet_baseline(world):
    F.publish(world.src, 'us', '2026-11-09')
    world.sync()
    CLI.main(['--github'])
    bad = world.tmp / 'bad'
    subprocess.run(['git', 'clone', '-q', '-b', CLI.STATE_BRANCH, str(world.origin), str(bad)], check=True)
    F.git(bad, 'rm', '-q', CLI.STATE_FILE)
    F.commit(bad, 'lost')
    F.git(bad, 'push', '-q', 'origin', f'HEAD:{CLI.STATE_BRANCH}')
    assert CLI.main(['--github']) == 0
    assert [e['kind'] for e in world.state()['events']] == ['reset', 'missing', 'publish']


def test_dry_run_and_bare_call_write_nothing(world, capsys):
    F.publish(world.src, 'us', '2026-11-09', summ=F.summary(status='fail', publish_ok=False, verified=False,
                                                           blocking=['g1']))
    world.sync()
    assert CLI.main(['--dry-run']) == 0
    out = capsys.readouterr().out
    assert '[GitHub이 직접 대조]' in out and 'outbox 2건' in out
    assert CLI.main([]) == 2
    assert F.git(world.origin, 'branch', '--list', CLI.STATE_BRANCH) == '' and world.pokes == []


def test_entry_never_sends_telegram_and_launcher_has_no_publish_entry():
    import runner_launch
    src = open(CLI.__file__, encoding='utf-8').read()
    assert 'send_telegram' not in src and 'review.digest' not in src and 'from review import digest' not in src
    assert 'publish' not in runner_launch.ENTRIES


def test_workflow_has_no_secrets_and_only_contents_write():
    import os
    path = os.path.join(os.path.dirname(CLI.__file__), '..', '.github', 'workflows', 'publish-watch.yml')
    y = open(path, encoding='utf-8').read()
    code = '\n'.join(line for line in y.splitlines() if not line.lstrip().startswith('#'))
    assert 'secrets.' not in code and 'pip ' not in code and 'id-token' not in code
    assert re.search(r'^permissions:\n  contents: write\n\n', code, re.M)
    for cron in ('10 3 * * *', '40 4 * * *', '10 14 * * *', '40 15 * * *', '37 */3 * * *'):
        assert f"cron: '{cron}'" in code
    for p in ("'posts/**'", "'kr/posts/**'", "'verification/**'"):
        assert p in code
    assert 'group: publish-watch' in code and 'cancel-in-progress: false' in code and 'fetch-depth: 0' in code
    assert 'ALERTS_WORKER_URL: ${{ vars.ALERTS_WORKER_URL }}' in code
    assert 'python3 scripts/verify_publish.py --github' in code and 'workflow_dispatch' in code
