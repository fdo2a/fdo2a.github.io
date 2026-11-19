#!/usr/bin/env python3
"""재시도 판정 게이트 — 판정은 Actions 에서, 클라우드 세션은 DUE 일 때만 띄운다 (2026-11-19).

    python3 scripts/ci/retry_gate.py --schedule '<cron 문자열>'          # 예약 실행 (github.event.schedule)
    python3 scripts/ci/retry_gate.py --kinds us,kr [--mode check|gate|force]   # 손 실행, 기본 check

재시도 루틴은 주 116회 떴고 거의 전부 `routine_due.py` → DONE 으로 8초 만에 끝났다. 그래도 매번 새 클라우드
세션을 냈다. 여기서 같은 `routine_due.py <kind>` 를 부르고(루틴이 보는 것과 같은 한 줄), 줄이 `DUE` 로 시작하고
그 세션 본 런 뒤일 때만 그 루틴의 API 트리거(`/fire`)를 친다. 루틴 프롬프트의 Step 1 재판정은 그대로라
잘못 쏜 발화는 8초짜리 no-op 이다. 이중 발화는 `run_lock.sh` 가 가른다.

**창**: 예약은 2-5시간 늦게 온다(AGENTS 규칙 10). 늦은 틱이 다음 세션의 「본 런 전」 구간에 떨어지면 `routine_due`
는 DUE 를 낸다 — 세션은 본 런보다 먼저 넘어간다(US 17:00 NY vs 본 런 17:30, KR 16:00 KST vs 18:00). 그 세션의
본 런 시작 + 여유 전에는 쏘지 않는다.

**묶인 주간**: 주간 판정이 본 런 창(토 15:00 KST + 여유) 뒤에도 `WAIT` 면 쏘지 않고 **실행을 빨갛게 끝낸다**
(`held`) — 집계가 주 끝까지 못 왔거나 휴장 달력이 끝난 것이라 재시도로 풀리지 않는다. Actions 실패 메일이 알림이다.

토큰: 레포 비밀값 `ROUTINE_FIRE_TOKEN_<KIND>`(루틴마다 하나, 웹 화면에서만 만든다). 없으면 `RETRY_GATE_LIVE=true`
전에는 경고, 뒤에는 실패. 토큰은 출력하지 않는다.

설계: docs/superpowers/specs/2026-11-19-retry-gate.md
"""
import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, time, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import routine_due as rd  # noqa: E402

FIRE_URL = 'https://api.anthropic.com/v1/claude_code/routines/{}/fire'
FIRE_HEADERS = {
    'anthropic-beta': 'experimental-cc-routine-2026-04-01',
    'anthropic-version': '2023-06-01',
    'Content-Type': 'application/json',
}

# 종류 → (쏠 루틴, 토큰 비밀값 이름). 일본 주간은 재시도 루틴 하나로 모은다 — 옛 일요일 재시도(trig_01QoHr…)에 평일 재시도의
# 지시문을 옮겨 쓴다. 평일 재시도(trig_019f…)·MOF 본 루틴(trig_01Vo5…)은 대화에서 만든 루틴이라 웹 화면에 없어 토큰을
# 만들 수 없었다(11/19). 둘은 끈다. 알림 규칙은 시각(서울 21시)으로 정한다.
ROUTINES = {
    'us': ('trig_01HteZubmVtg18xyKfKU5gGV', 'ROUTINE_FIRE_TOKEN_US'),
    'kr': ('trig_01NtKZrNrQj1veWCbuQhL4Eh', 'ROUTINE_FIRE_TOKEN_KR'),
    'jp_daily': ('trig_016v1gDVjFtuYP7KnTfXxudt', 'ROUTINE_FIRE_TOKEN_JP_DAILY'),
    'japan': ('trig_01QoHrHqXPEy2m3eKdrsjpo2', 'ROUTINE_FIRE_TOKEN_JAPAN'),
    'weekly': ('trig_01KoxpP7cSdkWXyh36YzGYpe', 'ROUTINE_FIRE_TOKEN_WEEKLY'),
}

# 예약 문자열(UTC) → 판정할 종류. 지금 재시도 슬롯과 같은 시(정각은 7분 밀었다 — KR 과 같은 분에 걸리는 일본 일간·주간은
# 17·22분: 두 줄이 같은 분에 맞을 때 실행이 줄마다 따로 뜨는지 확인되지 않는다, 시험 test_no_two_slots_share_a_minute). 일요일 일본 재시도는 뺐다 —
# 일요일에는 언제나 WAIT(시험 test_sunday_japan_is_never_due). 워크플로의 cron 과 글자까지 같아야 한다(시험).
# US 20:30·KR 06:xx 는 아래 안전망 cron 이 제시각에 맡는다 — 세션 경계 직전의 마지막 기회라 예약 지연을 태우지 않는다.
SLOTS = {
    '30 0,2,5,8,11,14,17 * * 2-6': ('us',),
    '7 0,3,12,15,18,21 * * 1-6': ('kr',),
    '17 12 * * 1-5': ('jp_daily',),
    '7 4,7,10,13 * * 1-5': ('japan',),          # 13·16·19·22 KST — 13시는 MOF 게시일 본 런 자리
    '22 9,12,15,18,21 * * 6': ('weekly',),
}

# 루틴 쪽에 남기는 안전망 cron(claude.ai 스케줄러 — 제시각에 뜬다). 레포가 루틴을 바꾸지는 않는다 — 본 세션이 이 값으로
# RemoteTrigger 를 고친다. 세션 경계 직전의 마지막 기회 자리다(codex 구현 2회차 #4). 시험이 게이트 슬롯과 합쳐 옛 시각을 덮는지 본다.
BACKSTOPS = {
    'us': '30 20 * * 2-6',                       # 15:30 EST · 16:30 EDT — 경계 17:00 ET 전
    'kr': '30 6 * * 1-6',                        # 15:30 KST — 경계 16:00 KST 전
    'jp_daily': '30 20 * * 1-5',                 # 05:30 KST — 보충 창 06:00 JST 전
    'japan': 'CRON_TZ=Asia/Seoul 30 23 * * 1-5',  # 23:30 KST — 21시 이후 STALE 알림 규칙이 산다
    'weekly': '30 20 * * 6',                     # 일 05:30 KST
}

GRACE = timedelta(hours=2)
BOUNDARY_MARGIN = timedelta(minutes=30)
TOKEN_PREFIX = 'ROUTINE_FIRE_TOKEN_'
FIRE_TEXT = 'retry-gate workflow fire (no payload)'


def expand(field):
    """cron 의 시·요일 칸(숫자, 쉼표, a-b)만 — 시험이 슬롯 시각을 펼칠 때 쓴다."""
    out = set()
    for part in field.split(','):
        a, _, b = part.partition('-')
        out.update(range(int(a), int(b or a) + 1))
    return out


def _at(day, hh, mm, tz):
    return datetime.combine(date.fromisoformat(day) if isinstance(day, str) else day,
                            time(hh, mm), tzinfo=tz).astimezone(timezone.utc)


def not_before(kind, now, holidays):
    """그 시각 기대 세션의 본 런 시작 + 여유(UTC). 이보다 이르면 쏘지 않는다. holidays = {'us','kr','jp': (...)}."""
    if kind == 'us':
        return _at(rd.us_session(now, holidays['us']), 17, 30, rd.NY) + GRACE
    if kind == 'kr':
        return _at(rd.kr_session(now, holidays['kr']), 18, 0, rd.SEOUL) + GRACE
    if kind == 'jp_daily':
        return _at(rd.jp_session(now, holidays['jp']), 18, 20, rd.SEOUL) + GRACE
    if kind == 'weekly':
        s = date.fromisoformat(rd.us_session(now, holidays['us']))
        return _at(s + timedelta(days=(5 - s.weekday()) % 7), 15, 0, rd.SEOUL) + GRACE
    if kind == 'japan':
        post = rd.japan_post_day(rd.japan_key(now), holidays['jp'])
        return _at(post, 13, 0, rd.SEOUL)          # 이 게이트가 본 런 자리다 — 여유 없음
    raise ValueError(kind)


def session_key(kind, now, holidays):
    """routine_due 가 그 시각에 판정하는 세션·주 키. 판정 앞뒤로 같아야 쏜다(codex 구현 검토 #1)."""
    if kind == 'us':
        return rd.us_session(now, holidays['us'])
    if kind == 'kr':
        return rd.kr_session(now, holidays['kr'])
    if kind == 'jp_daily':
        return rd.jp_session(now, holidays['jp'])
    if kind == 'weekly':
        return rd.week_of(now, holidays['us'])
    if kind == 'japan':
        return rd.japan_key(now)
    raise ValueError(kind)


def action(kind, line, now, holidays, mode):
    """(행동, 이유). 행동: fire · would-fire · early · boundary · noop · held."""
    word = line.split(' ', 1)[0]
    due = word == 'DUE'
    if mode == 'force':
        return 'fire', 'force'
    # 주간이 본 런 창 뒤에도 WAIT 면 그 주는 묶였다(집계가 주 끝까지 못 옴·달력 끝). 재시도로는 풀리지 않고,
    # noop 으로 넘기면 주 키가 넘어갈 때까지 아무도 모른다 — 빨갛게 끝내 Actions 실패 메일로 알린다
    # (2026-11-19 사용자 결정). 주 중간·본 런 전의 WAIT 는 정상이라 조용히 둔다.
    if kind == 'weekly' and word == 'WAIT' and now >= not_before(kind, now, holidays):
        return 'held', '본 런 창이 지났는데 WAIT — 이번 주 주간이 묶였다'
    if not due:
        return 'noop', 'DUE 아님'
    # 경계 직전에 쏘면 루틴이 뜨는 사이 세션이 넘어가 루틴 Step 1 이 다음 세션 DUE 를 보고 본 런 전에 돈다(codex 구현 2회차 #3).
    if session_key(kind, now + BOUNDARY_MARGIN, holidays) != session_key(kind, now, holidays):
        return 'boundary', f'세션 경계 {int(BOUNDARY_MARGIN.total_seconds() // 60)}분 안 — 다음 틱·안전망이 본다'
    nb = not_before(kind, now, holidays)
    if now < nb:
        return 'early', f'본 런 전 — {nb.isoformat()} 부터'
    return ('would-fire' if mode == 'check' else 'fire'), 'DUE'


def run_due(kind):
    """루틴 Step 1 과 같은 명령. 실패는 예외 — DONE 으로 읽지 않는다."""
    # 판정 자식에게는 발화 토큰을 넘기지 않는다(codex 구현 검토 #5).
    env = {k: v for k, v in os.environ.items() if not k.startswith(TOKEN_PREFIX)}
    r = subprocess.run([sys.executable, os.path.join(HERE, 'routine_due.py'), kind],
                       capture_output=True, text=True, timeout=300, env=env)
    line = (r.stdout.strip().split('\n') or [''])[0].strip()
    if r.returncode or not line:
        raise RuntimeError(f'routine_due {kind} exit {r.returncode}: {r.stderr.strip()[-300:]}')
    return line


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """3xx 를 따라가지 않는다 — urllib 는 리다이렉트에 Authorization 을 실어 다른 호스트로 GET 하고, 그 200 을
    「발화 성공」으로 읽게 된다(codex 구현 검토 #4). 3xx 는 HTTPError 로 올라와 실패가 된다."""

    def redirect_request(self, *a, **kw):
        return None


DEFAULT_OPENER = urllib.request.build_opener(_NoRedirect).open


def fire(trig, token, text, opener):
    req = urllib.request.Request(FIRE_URL.format(trig), method='POST',
                                 data=json.dumps({'text': text[:900]}, ensure_ascii=False).encode(),
                                 headers=dict(FIRE_HEADERS, Authorization=f'Bearer {token}'))
    try:
        with opener(req, timeout=30) as resp:
            body = json.loads(resp.read() or b'{}')
            if not isinstance(body, dict):
                raise ValueError('응답이 JSON 객체가 아니다')
            # 성공 = 문서의 응답 모양(type routine_fire + 새 세션 id). 아니면 2xx 라도 실패로 돌린다(codex 구현 2회차 #5).
            sid = body.get('claude_code_session_id')
            if body.get('type') != 'routine_fire' or not (isinstance(sid, str) and sid.strip()):
                return 0, f'응답 모양이 다르다(type={str(body.get("type"))[:30]})'
            return resp.status, 'routine_fire'
    except urllib.error.HTTPError as e:
        return e.code, str(e.reason or '')[:80]


def load_holidays():
    return {m: rd._holidays(m) for m in ('us', 'kr', 'jp')}


def main(argv=None, env=None, run_due=run_due, opener=None, now=None,
         holidays=None, out=None, clock=None):
    env = os.environ if env is None else env
    out = out or sys.stdout
    p = argparse.ArgumentParser()
    p.add_argument('--schedule')
    p.add_argument('--kinds')
    p.add_argument('--mode', choices=('check', 'gate', 'force'))
    a = p.parse_args(argv)

    def say(s):
        print(s, file=out, flush=True)

    if a.schedule:
        if a.schedule not in SLOTS:
            say(f'::error::모르는 예약 문자열: {a.schedule!r}')
            return 1
        kinds, mode = SLOTS[a.schedule], a.mode or 'gate'
    else:
        kinds = tuple(k.strip() for k in (a.kinds or '').split(',') if k.strip())
        mode = a.mode or 'check'
        bad = [k for k in kinds if k not in ROUTINES]
        if not kinds or bad:
            say(f'::error::종류를 모른다: {bad or "(없음)"} — {", ".join(ROUTINES)}')
            return 1
    opener = opener or DEFAULT_OPENER
    clock = clock or ((lambda: now) if now else (lambda: datetime.now(timezone.utc)))
    fixed_holidays = holidays
    # 토큰은 지역 사전으로 옮기고 프로세스 환경에서 지운다 — 휴장 조회·판정의 git·python 자식이 상속하지 않게(codex 구현 2회차 #2).
    tokens = {k: v for k, v in env.items() if k.startswith(TOKEN_PREFIX)}
    for k in [k for k in os.environ if k.startswith(TOKEN_PREFIX)]:
        del os.environ[k]
    live = (env.get('RETRY_GATE_LIVE') or '').strip().lower() == 'true'
    failed = False
    for kind in kinds:
        trig, secret = ROUTINES[kind]
        before = clock()
        try:
            line = run_due(kind)
        except Exception as e:                 # noqa: BLE001 — 판정 실패는 쏘지 않고 빨갛게
            say(f'::error::retry-gate {kind}: 판정 실패 — {e}')
            failed = True
            continue
        # 휴장 달력은 자식이 fetch 한 뒤의 판으로 읽는다 — 앞서 읽은 판과 자식의 판이 다르면 세션이 갈린다(codex 구현 2회차 #1).
        holidays = fixed_holidays if fixed_holidays is not None else load_holidays()
        # 시각은 휴장 조회 뒤, 발화 직전에 읽는다 — 조회가 늦으면 앞서 읽은 시각으로는 경계 여유를 잘못 잰다(3회차).
        after = clock()
        # 자식의 판정 시각은 before 와 after 사이다. 그 사이 세션이 넘어갔으면 판정이 어느 세션 것인지 모른다 —
        # 쏘지 않고 다음 틱에 맡긴다. 창은 after(발화 직전) 시각으로 본다.
        if mode != 'force' and session_key(kind, before, holidays) != session_key(kind, after, holidays):
            say(f'retry-gate {kind}: {line} → noop (판정 중 세션이 넘어감 — 다음 틱이 다시 본다)')
            continue
        act, why = action(kind, line, after, holidays, mode)
        if act == 'held':
            say(f'::error::retry-gate {kind}: {line} → held ({why})')
            failed = True
            continue
        say(f'retry-gate {kind}: {line} → {act} ({why})')
        if act != 'fire':
            continue
        token = (tokens.get(secret) or '').strip()
        if not token:
            if live or mode == 'force':          # force = 토큰 시험 — 비밀값이 없으면 시험이 실패한 것이다
                say(f'::error::retry-gate {kind}: DUE 인데 비밀값 {secret} 이 없다 — 재시도가 뜨지 않았다')
                failed = True
            else:
                say(f'::warning::retry-gate {kind}: 비밀값 {secret} 없음 — 쏘지 않음(RETRY_GATE_LIVE 전)')
            continue
        try:
            # 판정 줄을 싣지 않는다 — 루틴 Step 2 는 낱말 DUE 로 멈출지 정하고, 그 판단은 Step 1 의 출력만 봐야 한다.
            status, kind_ = fire(trig, token, FIRE_TEXT, opener)
        except Exception as e:                 # noqa: BLE001 — 응답 모양 오류도 이 종류만 실패, 나머지는 마저 본다
            say(f'::error::retry-gate {kind}: 발화 실패 — {type(e).__name__}')
            failed = True
            continue
        if 200 <= status < 300:
            say(f'retry-gate {kind}: fired {trig} (HTTP {status}, {kind_})')
        else:
            say(f'::error::retry-gate {kind}: 발화 거부 HTTP {status} {kind_}')
            failed = True
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
