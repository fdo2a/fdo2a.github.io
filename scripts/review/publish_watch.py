"""발행 건별 알림의 판단 — 5분마다 origin/main 을 보고 사건을 만든다(2단계, 2026-11-08).

진입점은 `scripts/verify_publish.py`. 매일 요약(`verify_digest.py`)과 **상태 파일·실행 경로가 따로**다 — 한쪽이
보냈다고 다른 쪽이 건너뛰지 않는다. 글의 상태 계산(`review.prepub_view`)만 함께 쓴다.

계약:
- 기준점은 **마지막으로 정상 확인한 원격 커밋**(`last_seen`)이다. 시간이 아니다. 기준점이 지금 이력의 조상이
  아니면(강제 push·이력 손상) 그 사이를 다 봤다고 하지 않고 알린 뒤 전부 다시 계산한다.
- 조회 실패는 미발행이 아니다. 조회에 실패한 회차는 미발행 판정을 하지 않고 기준점도 옮기지 않는다.
- 휴장 달력을 못 읽으면 그 시장의 미발행 판정을 멈춘다(빈 달력으로 휴일을 거래일로 보지 않는다).
- 사건 식별자는 내용에서 정해진다 — 저장 실패로 같은 사건이 다시 만들어져도 같은 식별자라 한 번만 쌓인다.
  전송은 pending → (보냄) → sent. 보낸 뒤 저장이 실패하면 다음 회차에 다시 보낸다: **재전송 시 중복 가능**,
  유실보다 낫다.
설계: docs/superpowers/specs/2026-11-08-telegram-prepub-records.md
"""
import hashlib
import importlib.util
import json
import os
import tempfile
from datetime import date, datetime, timedelta

from review import prepub_view as V
from review.digest import KST, SendError

FORMAT = 'verify-publish/1'
REF = 'origin/main'
STATE_ENV = 'VERIFY_PUBLISH_STATE'
DEFAULT_STATE = os.path.expanduser('~/Library/Application Support/fdo2a/verify_publish.json')
DEADLINE = {'us': (1, 12), 'kr': (0, 23)}     # 세션 D 의 (며칠 뒤, KST 시) — US 는 다음 날 12:00, KR 은 그날 23:00
FETCH_STALE = timedelta(hours=2)
KEEP_SENT = timedelta(days=60)
HERE = os.path.dirname(os.path.abspath(__file__))


class StateError(Exception):
    pass


def _routine_due():
    spec = importlib.util.spec_from_file_location('routine_due', os.path.join(HERE, '..', 'ci', 'routine_due.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── 상태 파일 ───────────────────────────────────────────────────────────────

def state_path():
    return os.environ.get(STATE_ENV) or DEFAULT_STATE


def new_state(reason):
    return {'format': FORMAT, 'last_seen': None, 'last_ok': None, 'posts': {}, 'sessions': {},
            'events': [], 'fetch': {}, 'calendar': {}, 'send_fail': 0, 'reset': reason}


def load_state(path):
    """None = 파일 없음(처음 실행). 손상은 StateError — 이전 상태를 정상으로 가정하지 않는다."""
    try:
        with open(path, encoding='utf-8') as fh:
            obj = json.load(fh)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        raise StateError(f'{type(exc).__name__}: {exc}') from exc
    if not isinstance(obj, dict) or obj.get('format') != FORMAT or not isinstance(obj.get('events'), list):
        raise StateError('상태 파일 형식이 다르다')
    for k, empty in (('posts', {}), ('sessions', {}), ('fetch', {}), ('calendar', {})):
        if not isinstance(obj.get(k), dict):
            obj[k] = empty
    return obj


def save_state(path, st):
    """임시 파일 + os.replace — 매일 요약이 반쯤 쓰인 파일을 읽지 않게(설계 검토 #7)."""
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix='.publish-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            json.dump(st, fh, ensure_ascii=False, indent=1, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ── 사건 ─────────────────────────────────────────────────────────────────

def event_id(kind, key, extra=''):
    return hashlib.sha1(f'{kind}|{key}|{extra}'.encode()).hexdigest()[:8]


def add_event(st, kind, key, text, now, extra=''):
    eid = event_id(kind, key, extra)
    if any(e.get('id') == eid for e in st['events']):
        return None
    st['events'].append({'id': eid, 'kind': kind, 'key': key, 'text': text, 'created': now.isoformat(),
                         'status': 'pending', 'tries': 0})
    return eid


def pending(st):
    return [e for e in st['events'] if e.get('status') == 'pending']


def _label(market, session):
    return f'{V.LABEL[market]} {int(session[5:7])}/{session[8:]}'


# ── 세션 ─────────────────────────────────────────────────────────────────

def deadline(market, session):
    days, hour = DEADLINE[market]
    d = date.fromisoformat(session) + timedelta(days=days)
    return datetime(d.year, d.month, d.day, hour, tzinfo=KST)


def load_holidays(root, market, rev):
    """그 커밋의 휴장 달력. 못 읽거나 형식이 다르면 None(빈 목록으로 바꾸지 않는다 — 설계 검토 #9)."""
    try:
        cal = json.loads(V._git(root, 'show', f'{rev}:data/market_holidays.json').decode('utf-8'))
    except (V.GitError, ValueError, UnicodeDecodeError):
        return None
    dates = (cal.get(market) or {}).get('dates') if isinstance(cal, dict) else None
    if not isinstance(dates, list) or not all(isinstance(x, str) for x in dates):
        return None
    return tuple(dates)


def sessions_due(market, now, holidays):
    """적용일부터 지금 기대 세션까지의 거래 세션 — routine_due 와 같은 세션 함수·달력."""
    rd = _routine_due()
    cur = (rd.us_session if market == 'us' else rd.kr_session)(now, holidays)
    d = rd._trading_forward(date.fromisoformat(V.EFFECTIVE), holidays)
    out = []
    while d.isoformat() <= cur:
        out.append(d.isoformat())
        d = rd._trading_forward(d + timedelta(days=1), holidays)
    return out


# ── 한 회차 ──────────────────────────────────────────────────────────────

def _fetch_failed(st, now, why):
    f = st['fetch']
    f.setdefault('since', now.isoformat())
    f['why'] = why[:160]
    base = datetime.fromisoformat(st.get('last_ok') or f['since'])
    if now - base >= FETCH_STALE and not f.get('alerted'):
        hours = int((now - base).total_seconds() // 3600)
        add_event(st, 'fetch', f['since'], f'[발행 알림] GitHub 조회가 {hours}시간 넘게 실패하고 있어요 — 미발행 여부를 '
                                           f'몰라요(그동안 미발행 판정을 멈춰요). 사유: {f["why"]}', now)
        f['alerted'] = True


def _tree(root, rev):
    raw = V._git(root, 'ls-tree', '-r', '--name-only', '-z', rev, '--', 'posts', 'kr/posts', 'verification')
    return {p for p in raw.decode('utf-8', 'replace').split('\0') if p}


def _is_ancestor(root, old, new):
    import subprocess
    out = subprocess.run(['git', '-C', root, 'merge-base', '--is-ancestor', old, new], capture_output=True, timeout=60)
    if out.returncode in (0, 1):
        return out.returncode == 0
    return False                                   # 객체가 없다(gc·강제 push) — 조상이라고 하지 않는다


def _changed(root, old, new):
    raw = V._git(root, 'diff', '--name-only', '-z', old, new, '--', 'posts', 'kr/posts', 'verification')
    return {p for p in raw.decode('utf-8', 'replace').split('\0') if p}


def _target_of_any(path):
    t = V.target_of(path)
    if t:
        return t
    parts = path.split('/')
    if len(parts) == 3 and parts[0] == 'verification' and parts[1] in V.TARGETS and parts[2].endswith('.json'):
        d = parts[2][:-5]
        if d >= V.EFFECTIVE:
            return parts[1], d
    return None


def step(st, root, now, fetched, ref=REF):
    """사건을 pending 으로 쌓는다. 조회·읽기에 실패하면 기준점을 옮기지 않는다."""
    if st.get('reset'):
        add_event(st, 'reset', f'{st["reset"]}|{now.date().isoformat()}',
                  f'[발행 알림] {st["reset"]} — {V.EFFECTIVE} 이후 글을 전부 다시 계산해요'
                  '(이미 받은 알림이 다시 올 수 있어요).', now)
        st['reset'] = None
    if not fetched:
        _fetch_failed(st, now, 'git fetch 실패')
        return st
    try:
        tip = V._git(root, 'rev-parse', '--verify', f'{ref}^{{commit}}').decode().strip()
        tree = _tree(root, tip)
        last = st.get('last_seen')
        full = last is None
        if last and not _is_ancestor(root, last, tip):
            add_event(st, 'gap', f'{last}->{tip}',
                      f'[발행 알림] 지난 확인 기준점({last[:7]})을 지금 이력에서 못 찾았어요 — 그 사이 사건을 다 봤다고 '
                      f'할 수 없어요. {V.EFFECTIVE} 이후 글을 전부 다시 계산해요.', now)
            full = True
        paths = tree if full else _changed(root, last, tip)
        targets = sorted({t for t in map(_target_of_any, paths) if t})
        views = {}
        for market, d in targets:
            path = V.post_path(market, d)
            if path in tree:
                views[path] = V.view(root, tip, market, d)
        cals = {m: load_holidays(root, m, tip) for m in V.TARGETS}
    except V.GitError as exc:
        _fetch_failed(st, now, f'읽기 실패 — {exc}')
        return st

    # 미발행·해소 먼저 — 「해소」가 그 글의 발행 알림보다 앞에 오게
    for market, hol in cals.items():
        if hol is None:
            st['calendar'].setdefault(market, now.isoformat())
            continue
        st['calendar'].pop(market, None)
        for s in sessions_due(market, now, hol):
            key, path = f'{market}:{s}', V.post_path(market, s)
            seen = st['sessions'].get(key)
            if path in tree:
                if seen == 'missing':
                    add_event(st, 'resolved', key, f'[미발행 해소] {_label(market, s)} 세션 보고서가 올라왔어요.', now)
                    st['sessions'][key] = 'resolved'
            elif seen is None and now >= deadline(market, s):
                dl = deadline(market, s)
                add_event(st, 'missing', key,
                          f'[미발행] {_label(market, s)} 세션 보고서 미발행 확인\n'
                          f'기준 시각: {dl.month}/{dl.day:02d} {dl:%H:%M} KST\n'
                          '원인: 확인 불가 — 발행 루틴·데이터 수집 상태 점검 필요', now)
                st['sessions'][key] = 'missing'

    for path, v in views.items():
        fp = V.fingerprint(v)
        prev = st['posts'].get(path)
        if prev is None:
            add_event(st, 'publish', path, V.render_publish(v), now, extra=fp)
            st['posts'][path] = {'fp': fp, 'first_seen': tip}
        elif prev.get('fp') != fp:
            add_event(st, 'changed', path, V.render_publish(v, head='[상태 바뀜]'), now, extra=fp)
            prev['fp'] = fp

    if st['fetch'].get('alerted'):
        add_event(st, 'fetch_ok', st['fetch'].get('since', ''), '[발행 알림] GitHub 조회가 다시 돼요 — 밀린 판정을 이어서 해요.', now)
    st['fetch'] = {}
    st['last_seen'], st['last_ok'] = tip, now.isoformat()
    cutoff = now - KEEP_SENT
    st['events'] = [e for e in st['events'] if e.get('status') != 'sent'
                    or datetime.fromisoformat(e['created']) >= cutoff]
    return st


def deliver(st, send, save, now):
    """pending 을 차례로 보낸다. 한 건이 실패하면 거기서 멈춘다(순서 유지) — 다음 회차에 같은 식별자로 다시."""
    for e in pending(st):
        try:
            send(f'{e["text"]}\n#{e["id"]}')
        except SendError as exc:
            e['tries'] = e.get('tries', 0) + 1
            e['last_error'] = str(exc)[:160]
            st['send_fail'] = st.get('send_fail', 0) + 1
            save(st)
            return False
        e['status'], e['sent'] = 'sent', now.isoformat()
        st['send_fail'] = 0
        save(st)                    # 여기서 실패하면 다음 회차에 다시 보낸다 — 중복 가능, 유실 없음
    return True


# ── 매일 요약이 읽는 스냅샷 ───────────────────────────────────────────────

def summary_lines(path, now):
    """매일 요약 꼬리 — 읽기만 한다. 못 읽으면 「미발행 없음」이 아니라 「조회 실패」."""
    try:
        st = load_state(path)
    except StateError:
        return ['발행 알림: 상태를 못 읽었어요 — 미발행·전송 여부를 몰라요']
    if st is None:
        return ['발행 알림: 아직 실행 기록이 없어요']
    return summary_lines_from(st, now)


def summary_lines_from(st, now):
    out = []
    ok = st.get('last_ok')
    if not ok:
        out.append('발행 알림: 아직 정상 확인이 한 번도 없어요')
    else:
        gap = now - datetime.fromisoformat(ok)
        if gap > FETCH_STALE:
            out.append(f'발행 알림: 마지막 정상 확인이 {int(gap.total_seconds() // 3600)}시간 전이에요 — 그 뒤 사건은 못 봤어요')
    open_ = sorted(k for k, s in st['sessions'].items() if s == 'missing')
    if open_:
        out.append('아직 안 올라온 세션: ' + ', '.join(_label(*k.split(':', 1)) for k in open_[:6]))
    if st['calendar']:
        out.append('휴장 달력을 못 읽어 미발행 판정을 멈춘 시장: ' + ', '.join(sorted(st['calendar'])))
    n = len(pending(st))
    if n:
        out.append(f'발행 알림 미전송 {n}건(연속 실패 {st.get("send_fail", 0)}회)')
    return out
