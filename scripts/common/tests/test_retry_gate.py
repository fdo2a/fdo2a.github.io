"""재시도 판정 게이트 — 판정은 Actions 에서, 클라우드 세션은 DUE 일 때만 (2026-11-19).

재시도 루틴이 주 116회 떴고 거의 전부 `routine_due.py` → DONE 으로 8초 만에 끝났다. 그래도 매번 새
클라우드 세션 값을 냈다. 판정을 공짜인 Actions 로 옮기고, DUE 이고 그 세션 본 런 뒤일 때만 `/fire` 를 친다.
틀리는 방향은 둘이다 — DUE 인데 안 쏜다(복구가 사라진다), 본 런 전에 쏜다(수집 전 자료로 재시도가 돈다).
"""
from datetime import date, datetime, timezone
import importlib.util
import io
import json
import os
import urllib.error

import pytest
import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, '..', '..', '..')


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rg = _load('retry_gate', os.path.join(ROOT, 'scripts', 'ci', 'retry_gate.py'))
rd = _load('routine_due_for_gate', os.path.join(ROOT, 'scripts', 'ci', 'routine_due.py'))
WF = os.path.join(ROOT, '.github', 'workflows', 'retry-gate.yml')


def utc(*a):
    return datetime(*a, tzinfo=timezone.utc)


NO_HOL = {'us': (), 'kr': (), 'jp': ()}


# ── 창: 그 세션 본 런 시작 + 여유 전에는 쏘지 않는다 ─────────────────────────────────

def test_us_window_opens_two_hours_after_main_start_est():
    # 11/18(수) 세션 — 본 런 17:30 EST = 22:30 UTC, 창은 00:30 UTC(19:30 EST)부터
    assert rg.not_before('us', utc(2026, 11, 19, 3, 0), NO_HOL) == utc(2026, 11, 19, 0, 30)


def test_us_window_follows_dst():
    # 여름(EDT) 세션 — 17:30 EDT = 21:30 UTC, 창은 23:30 UTC
    assert rg.not_before('us', utc(2026, 10, 15, 3, 0), NO_HOL) == utc(2026, 10, 14, 23, 30)


def test_late_us_tick_inside_next_sessions_pre_main_gap_does_not_fire():
    # 20:30 UTC 슬롯이 2시간 늦게 22:20 UTC(17:20 EST)에 왔다 — us_session 은 이미 오늘이고 글이 없어 DUE 지만
    # 본 런(17:30 EST)은 아직 시작도 안 했다.
    now = utc(2026, 11, 19, 22, 20)
    assert rd.us_session(now) == '2026-11-19'
    assert now < rg.not_before('us', now, NO_HOL)
    assert rg.action('us', 'DUE 2026-11-19 미발행: posts/2026-11-19.html', now, NO_HOL, 'gate')[0] == 'early'


def test_kr_window_and_late_tick_before_main():
    # KR 세션은 16:00 KST 에 넘어간다. 06 UTC 슬롯이 늦게 08:00 UTC(17:00 KST)에 오면 본 런(18:00) 전이다.
    now = utc(2026, 11, 19, 8, 0)
    assert rd.kr_session(now) == '2026-11-19'
    assert rg.not_before('kr', now, NO_HOL) == utc(2026, 11, 19, 11, 0)       # 20:00 KST
    assert rg.action('kr', 'DUE x', now, NO_HOL, 'gate')[0] == 'early'
    assert rg.action('kr', 'DUE x', utc(2026, 11, 19, 12, 0), NO_HOL, 'gate')[0] == 'fire'


def test_jp_daily_window():
    assert rg.not_before('jp_daily', utc(2026, 11, 19, 12, 0), NO_HOL) == utc(2026, 11, 19, 11, 20)


def test_weekly_window_is_saturday_after_main():
    # 금요일 세션 주 — 본 런 토 15:00 KST(06 UTC), 창은 토 17:00 KST
    assert rg.not_before('weekly', utc(2026, 11, 21, 9, 0), NO_HOL) == utc(2026, 11, 21, 8, 0)


def test_weekly_window_when_friday_is_a_us_holiday():
    # 2026-04-03 Good Friday — 마지막 세션은 목요일, 본 런은 그래도 토요일
    hol = dict(NO_HOL, us=('2026-04-03',))
    assert rg.not_before('weekly', utc(2026, 4, 4, 9, 0), hol) == utc(2026, 4, 4, 8, 0)


def test_japan_window_is_post_day_main_slot():
    # W47 — 금 11/20, 게시일 월 11/23 은 근로감사의 날(휴장) → 화 11/24 13:00 KST
    hol = dict(NO_HOL, jp=('2026-11-23',))
    assert rg.not_before('japan', utc(2026, 11, 24, 5, 0), hol) == utc(2026, 11, 24, 4, 0)


def test_late_japan_tick_after_midnight_on_post_day_waits_for_main_slot():
    # 일요일 밤 22시(13 UTC) 틱은 없지만, 금요일 22시 틱이 아니라 월요일 00:30 KST 수동 실행이라도 MOF 게시 전이다.
    now = utc(2026, 11, 15, 15, 30)        # 월 11/16 00:30 KST, 게시일 = 11/16
    assert rg.action('japan', 'DUE 2026-W46 미발행', now, NO_HOL, 'gate')[0] == 'early'


def test_sunday_japan_is_never_due():
    """일요일 일본 재시도(trig_01QoHr…)를 끄는 근거 — 2026-2027 모든 일요일, 시각 4개, 달력 휴장 포함."""
    import json as _json
    with open(os.path.join(ROOT, 'data', 'market_holidays.json'), encoding='utf-8') as fh:
        jp = tuple(_json.load(fh)['jp']['dates'])
    d = date(2026, 1, 4)
    seen = 0
    while d.year < 2028:
        for h in (4, 7, 10, 13):
            now = datetime(d.year, d.month, d.day, h, tzinfo=timezone.utc)
            key = rd.japan_key(now)
            verdict, _ = rd.decide_japan(key, set(), None, now.astimezone(rd.SEOUL).date(), jp)
            assert verdict == 'WAIT', (now, key)
            seen += 1
        d = date.fromordinal(d.toordinal() + 7)
    assert seen > 400


# ── 판정 → 행동 ─────────────────────────────────────────────────────────────

LATE = utc(2026, 11, 19, 3, 0)        # US 11/18 세션 창 안


@pytest.mark.parametrize('line', [
    'DONE 2026-11-18 발행 완료',
    'BUSY 2026-11-18 작성 중 (잠금 12분 전)',
    'WAIT 2026-W47 집계 불완전: kr',
    'SKIP 2026-11-18 세션은 오늘 발행 대상이 아니다',
    'DUEX nonsense',
    '',
])
def test_only_exact_due_fires(line):
    assert rg.action('us', line, LATE, NO_HOL, 'gate')[0] == 'noop'


def test_due_in_window_fires():
    assert rg.action('us', 'DUE 2026-11-18 미발행: news/2026-11-18.html', LATE, NO_HOL, 'gate')[0] == 'fire'


def test_fetch_failure_due_still_fires():
    # routine_due 는 판정 불가를 DUE 로 보낸다 — 루틴이 다시 판정한다.
    assert rg.action('us', 'DUE fetch 실패 — 오케스트레이터가 판정한다', LATE, NO_HOL, 'gate')[0] == 'fire'


def test_check_mode_never_fires_and_force_always_fires():
    assert rg.action('us', 'DUE x', LATE, NO_HOL, 'check')[0] == 'would-fire'
    assert rg.action('us', 'DONE x', LATE, NO_HOL, 'force')[0] == 'fire'
    early = utc(2026, 11, 19, 22, 20)
    assert rg.action('us', 'DUE x', early, NO_HOL, 'force')[0] == 'fire'


# ── 예약 문자열 ↔ 워크플로 ────────────────────────────────────────────────────

def _wf():
    with open(WF, encoding='utf-8') as fh:
        text = fh.read()
    doc = yaml.safe_load(text)
    on = doc.get('on', doc.get(True))
    return text, doc, on


def test_workflow_crons_are_exactly_the_gate_slots():
    _, _, on = _wf()
    crons = [c['cron'] for c in on['schedule']]
    assert sorted(crons) == sorted(rg.SLOTS)
    assert len(set(crons)) == len(crons)


def test_slots_cover_current_retry_times():
    """지금 재시도 루틴의 슬롯 시각(시)을 게이트 + 안전망 cron 으로 하나도 잃지 않는다 — 일요일 일본만 뺀다(언제나 WAIT)."""
    want = {
        'us': {(wd, h) for wd in (2, 3, 4, 5, 6) for h in (0, 2, 5, 8, 11, 14, 17, 20)},
        'kr': {(wd, h) for wd in (1, 2, 3, 4, 5, 6) for h in (0, 3, 6, 12, 15, 18, 21)},
        'jp_daily': {(wd, 12) for wd in (1, 2, 3, 4, 5)},
        'japan': {(wd, h) for wd in (1, 2, 3, 4, 5) for h in (4, 7, 10, 13)},
        'weekly': {(6, h) for h in (9, 12, 15, 18, 21)},
    }
    got = {k: set() for k in want}
    pairs = list(rg.SLOTS.items()) + [(c, (k,)) for k, c in rg.BACKSTOPS.items() if not c.startswith('CRON_TZ')]
    for cron, kinds in pairs:
        _, hours, _, _, dows = cron.split()
        for k in kinds:
            for wd in rg.expand(dows):
                for h in rg.expand(hours):
                    got[k].add((wd, h))
    for k in want:
        assert got[k] >= want[k], (k, sorted(want[k] - got[k]))


def test_every_kind_has_a_routine_and_a_secret_in_the_workflow():
    text, doc, _ = _wf()
    step_env = {}
    for step in doc['jobs']['gate']['steps']:
        step_env.update(step.get('env') or {})
    for kind, (trig, secret) in rg.ROUTINES.items():
        assert trig.startswith('trig_')
        assert step_env.get(secret) == '${{ secrets.%s }}' % secret
    assert set(rg.ROUTINES) == {k for kinds in rg.SLOTS.values() for k in kinds}


def test_workflow_is_read_only_full_history_and_has_no_expressions_in_comments():
    text, doc, _ = _wf()
    assert doc['permissions'] == {'contents': 'read'}
    checkout = doc['jobs']['gate']['steps'][0]
    assert checkout['uses'].startswith('actions/checkout@')
    assert checkout['with']['fetch-depth'] == 0
    for line in text.split('\n'):
        if line.lstrip().startswith('#'):
            assert '${{' not in line, line
    assert 'cancel-in-progress: false' in text


# ── 실행: 판정 줄을 받아 쏘거나 말거나, 실패는 빨갛게 ─────────────────────────────────

OK_BODY = json.dumps({'type': 'routine_fire', 'claude_code_session_id': 'session_x'}).encode()


class FakeResp(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _run(monkeypatch, lines, env=None, now=LATE, argv=None, fire_exc=None):
    calls = []

    def due(kind):
        v = lines[kind]
        if isinstance(v, Exception):
            raise v
        return v

    def opener(req, timeout=None):
        calls.append(req)
        if fire_exc:
            raise fire_exc
        return FakeResp(OK_BODY)

    out = io.StringIO()
    code = rg.main(argv or ['--schedule', '30 0,2,5,8,11,14,17 * * 2-6'],
                   env=env if env is not None else {'ROUTINE_FIRE_TOKEN_US': 'sk-ant-oat01-SECRET'},
                   run_due=due, opener=opener, now=now, holidays=NO_HOL, out=out)
    return code, calls, out.getvalue()


def test_main_fires_on_due_with_the_documented_request(monkeypatch):
    code, calls, text = _run(monkeypatch, {'us': 'DUE 2026-11-18 미발행: news/2026-11-18.html'})
    assert code == 0 and len(calls) == 1
    req = calls[0]
    assert req.full_url == ('https://api.anthropic.com/v1/claude_code/routines/'
                            f'{rg.ROUTINES["us"][0]}/fire')
    assert req.get_method() == 'POST'
    h = {k.lower(): v for k, v in req.header_items()}
    assert h['authorization'] == 'Bearer sk-ant-oat01-SECRET'
    assert h['anthropic-beta'] == 'experimental-cc-routine-2026-04-01'
    assert h['anthropic-version'] == '2023-06-01'
    assert 'text' in json.loads(req.data)
    assert 'SECRET' not in text


def test_main_does_not_fire_on_done(monkeypatch):
    code, calls, _ = _run(monkeypatch, {'us': 'DONE 2026-11-18 발행 완료'})
    assert code == 0 and calls == []


def test_missing_token_warns_before_go_live_and_fails_after(monkeypatch):
    code, calls, text = _run(monkeypatch, {'us': 'DUE x'}, env={})
    assert code == 0 and calls == [] and '::warning::' in text
    code, calls, text = _run(monkeypatch, {'us': 'DUE x'}, env={'RETRY_GATE_LIVE': 'true'})
    assert code == 1 and calls == [] and '::error::' in text


def test_fire_http_error_fails_the_run(monkeypatch):
    err = urllib.error.HTTPError('u', 401, 'Unauthorized', {}, io.BytesIO(b'{}'))
    code, calls, text = _run(monkeypatch, {'us': 'DUE x'}, fire_exc=err)
    assert code == 1 and len(calls) == 1 and '401' in text and 'SECRET' not in text


def test_routine_due_crash_fails_without_firing_and_other_kinds_still_run(monkeypatch):
    code, calls, text = _run(
        monkeypatch, {'us': RuntimeError('boom'), 'kr': 'DUE x'},
        env={'ROUTINE_FIRE_TOKEN_KR': 't'}, now=utc(2026, 11, 19, 12, 30),
        argv=['--kinds', 'us,kr', '--mode', 'gate'])
    assert code == 1
    assert [r.full_url.split('/')[-2] for r in calls] == [rg.ROUTINES['kr'][0]]


def test_unknown_schedule_fails(monkeypatch):
    code, calls, text = _run(monkeypatch, {}, argv=['--schedule', '1 2 3 4 5'])
    assert code == 1 and calls == []


def test_manual_default_is_check(monkeypatch):
    code, calls, text = _run(monkeypatch, {'us': 'DUE x'}, argv=['--kinds', 'us'])
    assert code == 0 and calls == [] and 'would-fire' in text


def test_force_without_token_fails_even_before_go_live(monkeypatch):
    # force 는 토큰 시험이다 — 비밀값 이름을 틀렸는데 초록이면 시험이 거짓말을 한다.
    code, calls, text = _run(monkeypatch, {'us': 'DONE x'}, env={}, argv=['--kinds', 'us', '--mode', 'force'])
    assert code == 1 and calls == [] and '::error::' in text


def test_fire_text_does_not_carry_the_verdict(monkeypatch):
    # 루틴 Step 2 는 낱말 DUE 로 멈출지 정한다 — 그 판단은 루틴 자신의 Step 1 출력만 봐야 한다.
    code, calls, _ = _run(monkeypatch, {'us': 'DUE 2026-11-18 미발행: news/2026-11-18.html'})
    sent = json.loads(calls[0].data)['text']
    assert 'DUE' not in sent and '미발행' not in sent


def _holiday_calendar():
    with open(os.path.join(ROOT, 'data', 'market_holidays.json'), encoding='utf-8') as fh:
        cal = json.load(fh)
    return {m: tuple(cal[m]['dates']) for m in ('us', 'kr', 'jp')}


def test_window_never_blocks_an_on_time_slot():
    """창은 늦은 틱만 막아야 한다 — 제시각에 온 슬롯은 2026-2027 모든 날(서머타임 양쪽, 달력 휴장 포함) DUE 면 쏜다.
    일본 주간은 게시일 전에는 routine_due 가 DUE 를 내지 않으므로(WAIT) 게시일 이후만 본다."""
    hol = _holiday_calendar()
    checked = 0
    d = date(2026, 1, 1)
    while d.year < 2028:
        cron_dow = (d.weekday() + 1) % 7          # cron: 0 = 일요일
        for cron, kinds in rg.SLOTS.items():
            minute, hours, _, _, dows = cron.split()
            if cron_dow not in rg.expand(dows):
                continue
            for h in rg.expand(hours):
                now = datetime(d.year, d.month, d.day, h, int(minute), tzinfo=timezone.utc)
                for kind in kinds:
                    if kind == 'japan':
                        post = rd.japan_post_day(rd.japan_key(now), hol['jp'])
                        if now.astimezone(rd.SEOUL).date() < post:
                            continue
                    got = rg.action(kind, 'DUE x', now, hol, 'gate')
                    assert got[0] == 'fire', (kind, cron, now, got)
                    checked += 1
        d = date.fromordinal(d.toordinal() + 1)
    assert checked > 10000


# ── codex 구현 검토 1회차 지적 ────────────────────────────────────────────────

def test_session_rollover_during_judgement_does_not_fire(monkeypatch):
    # KR 12:07 슬롯이 늦게 15:59:59 KST 에 시작, 자식의 fetch 가 16:00 을 넘겨 오늘 세션으로 DUE 를 냈다.
    # 부모가 어제 세션의 열린 창으로 보면 본 런(18:00) 전에 쏜다.
    times = iter([utc(2026, 11, 19, 6, 59, 59), utc(2026, 11, 19, 7, 0, 2)])
    calls = []

    def opener(req, timeout=None):
        calls.append(req)
        return FakeResp(OK_BODY)

    out = io.StringIO()
    code = rg.main(['--kinds', 'kr', '--mode', 'gate'], env={'ROUTINE_FIRE_TOKEN_KR': 't'},
                   run_due=lambda k: 'DUE 2026-11-19 미발행: kr/posts/2026-11-19.html', opener=opener,
                   holidays=NO_HOL, out=out, clock=lambda: next(times))
    assert code == 0 and calls == [] and '세션이 넘어감' in out.getvalue()


def test_window_is_checked_at_the_time_after_judgement(monkeypatch):
    # 같은 세션 안이면 창은 판정 뒤 시각으로 본다(발화 직전).
    times = iter([utc(2026, 11, 19, 10, 59), utc(2026, 11, 19, 11, 0, 5)])
    calls = []
    out = io.StringIO()
    rg.main(['--kinds', 'kr', '--mode', 'gate'], env={'ROUTINE_FIRE_TOKEN_KR': 't'},
            run_due=lambda k: 'DUE x', opener=lambda r, timeout=None: calls.append(r) or FakeResp(OK_BODY),
            holidays=NO_HOL, out=out, clock=lambda: next(times))
    assert len(calls) == 1


def test_judge_child_never_sees_fire_tokens(monkeypatch):
    seen = {}

    class R:
        returncode, stdout, stderr = 0, 'DONE x\n', ''

    def fake_run(cmd, **kw):
        seen.update(kw.get('env') or {})
        seen['_had_env'] = 'env' in kw
        return R()

    monkeypatch.setenv('ROUTINE_FIRE_TOKEN_US', 'sk-ant-oat01-SECRET')
    monkeypatch.setenv('PATH_MARKER_FOR_TEST', 'kept')
    monkeypatch.setattr(rg.subprocess, 'run', fake_run)
    assert rg.run_due('us') == 'DONE x'
    assert seen['_had_env'] and 'ROUTINE_FIRE_TOKEN_US' not in seen and seen['PATH_MARKER_FOR_TEST'] == 'kept'


def test_redirect_is_not_followed_and_counts_as_failure(monkeypatch):
    import http.server
    import threading
    hits = []

    class H(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            hits.append(('POST', self.path, self.headers.get('Authorization')))
            self.send_response(302)
            self.send_header('Location', f'http://127.0.0.1:{self.server.server_port}/elsewhere')
            self.end_headers()

        def do_GET(self):
            hits.append(('GET', self.path, self.headers.get('Authorization')))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{}')

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(('127.0.0.1', 0), H)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        monkeypatch.setattr(rg, 'FIRE_URL', f'http://127.0.0.1:{srv.server_port}/v1/{{}}/fire')
        status, _ = rg.fire('trig_x', 'sk-ant-oat01-SECRET', 'x', rg.DEFAULT_OPENER)
    finally:
        srv.shutdown()
    assert status == 302
    assert [h[0] for h in hits] == ['POST']


def test_bad_response_shape_fails_only_that_kind(monkeypatch):
    calls = []

    def opener(req, timeout=None):
        calls.append(req)
        return FakeResp(b'[]' if len(calls) == 1 else OK_BODY)

    out = io.StringIO()
    code = rg.main(['--kinds', 'us,kr', '--mode', 'force'],
                   env={'ROUTINE_FIRE_TOKEN_US': 'a', 'ROUTINE_FIRE_TOKEN_KR': 'b'},
                   run_due=lambda k: 'DONE x', opener=opener, now=LATE, holidays=NO_HOL, out=out)
    assert code == 1 and len(calls) == 2
    assert 'fired trig_01NtK' in out.getvalue()


# ── codex 구현 검토 2회차 지적 ────────────────────────────────────────────────

def test_no_fire_within_margin_of_session_boundary():
    # KR 15:45 KST — 어제 세션 DUE 지만 루틴이 뜨는 사이 16:00 을 넘기면 루틴 Step 1 이 오늘 세션 DUE 를 본다.
    assert rg.action('kr', 'DUE x', utc(2026, 11, 19, 6, 45), NO_HOL, 'gate')[0] == 'boundary'
    assert rg.action('kr', 'DUE x', utc(2026, 11, 19, 6, 25), NO_HOL, 'gate')[0] == 'fire'


@pytest.mark.parametrize('body', [b'{}', b'{"type":"error"}', b'{"type":"routine_fire"}',
                                  b'{"type":"routine_fire","claude_code_session_id":7}'])
def test_success_needs_the_documented_response(monkeypatch, body):
    out = io.StringIO()
    code = rg.main(['--kinds', 'us', '--mode', 'force'], env={'ROUTINE_FIRE_TOKEN_US': 'a'},
                   run_due=lambda k: 'DONE x', opener=lambda r, timeout=None: FakeResp(body),
                   now=LATE, holidays=NO_HOL, out=out)
    assert code == 1 and 'fired' not in out.getvalue()


def test_tokens_leave_the_process_environment(monkeypatch):
    monkeypatch.setenv('ROUTINE_FIRE_TOKEN_US', 'sk-ant-oat01-SECRET')
    seen = []

    def due(kind):
        seen.append(os.environ.get('ROUTINE_FIRE_TOKEN_US'))
        return 'DUE x'

    calls = []
    out = io.StringIO()
    code = rg.main(['--kinds', 'us', '--mode', 'gate'], run_due=due,
                   opener=lambda r, timeout=None: calls.append(r) or FakeResp(OK_BODY),
                   now=LATE, holidays=NO_HOL, out=out)
    assert code == 0 and seen == [None] and len(calls) == 1
    assert dict(calls[0].header_items())['Authorization'] == 'Bearer sk-ant-oat01-SECRET'


def test_holidays_are_read_after_the_judge_fetched(monkeypatch):
    order = []
    monkeypatch.setattr(rg, 'load_holidays', lambda: order.append('hol') or NO_HOL)
    rg.main(['--kinds', 'us', '--mode', 'check'], env={},
            run_due=lambda k: order.append('due') or 'DONE x', now=LATE, out=io.StringIO())
    assert order == ['due', 'hol']
