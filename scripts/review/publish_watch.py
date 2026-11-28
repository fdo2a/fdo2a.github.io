"""발행 건별 알림의 판단 — origin/main 을 보고 사건을 만든다(2단계 2026-11-08, 2.5단계 2026-11-10).

진입점은 `scripts/verify_publish.py --github`(GitHub Actions `publish-watch.yml`). 2.5단계부터 이 계산은 GitHub 에서
돌고, 상태는 `alerts-state` 브랜치의 `verify_publish.json`, 보낼 사건은 같은 브랜치의 `outbox.json` 에 둔다.
전송은 공개 레포 밖 Cloudflare Worker 가 한다 — **이 모듈과 진입점은 텔레그램 토큰을 만지지 않는다.**
매일 요약(`verify_digest.py`)은 그 상태를 읽기만 한다(`summary_lines_from`). 글의 상태 계산(`review.prepub_view`)만 함께 쓴다.

2.5단계 계약(`who=V.GITHUB`):
- outbox 에 쓴 사건은 「전송됐을 수 있다」. 대기 중 미발행 경고를 취소하는 길을 쓰지 않고, 해소 문구는 「앞서 생성된
  미발행 경고」(사용자가 받았다고 단정하지 않는다).
- outbox 에서 빠지는 것은 Worker `/acks`·`/failed` 에 **id 와 본문 해시가 둘 다** 나온 사건뿐(`apply_acks`). 못 읽으면
  아무것도 빼지 않고, 같은 id·다른 해시는 남긴다.
  빠진 사건은 상태에 `sent`·`failed` 로 60일 남아 같은 사건이 다시 만들어지지 않는다.
- 상한(사건 500·문장 3,900자·파일 256 KB)은 outbox 에 옮길 때 지킨다(`build_outbox`) — 자르지 않고 남겨 둔 뒤
  `sys:overflow` 사건 하나로 알린다.

판단 계약(2단계 그대로):
- 기준점은 **마지막으로 정상 확인한 원격 커밋**(`last_seen`)이다. 시간이 아니다. 기준점이 지금 이력의 조상이
  아니면(강제 push·이력 손상) 그 사이를 다 봤다고 하지 않고 알린 뒤 전부 다시 계산한다.
- 조회 실패는 미발행이 아니다. 조회에 실패한 회차는 미발행 판정을 하지 않고 기준점도 옮기지 않는다.
- 휴장 달력을 못 읽으면 그 시장의 미발행 판정을 멈춘다(빈 달력으로 휴일을 거래일로 보지 않는다).
- 사건 식별자는 내용에서 정해진다 — push 가 거절돼 같은 회차를 다시 계산해도 같은 식별자라 한 번만 쌓인다.
- 사건 추가와 기준점 갱신은 메모리에서 함께 하고 상태·outbox 를 **한 커밋으로** 올린다(`verify_publish.github`) — 기준점만
  앞서 가는 순간이 없다. push 전에 죽으면 둘 다 안 남고, 다음 실행이 옛 기준점에서 같은 사건(같은 식별자)을 다시 만든다.
- `who=V.MAC` 의 취소 경로와 `deliver`·`save_state`·`state_path` 는 2단계(맥이 직접 보내던 때)의 것이다 — 지금 진입점은 쓰지 않는다.
설계: docs/superpowers/specs/2026-11-08-telegram-prepub-records.md
"""
import hashlib
import importlib.util
import json
import os
import secrets
import sys
import tempfile
import re
from datetime import date, datetime, timedelta, timezone

from review import prepub_view as V

KST = timezone(timedelta(hours=9))            # review.digest 를 불러오지 않는다 — Actions 계산이 요약 코드에 기대지 않게

FORMAT = 'verify-publish/1'
REF = 'origin/main'
STATE_ENV = 'VERIFY_PUBLISH_STATE'
DEFAULT_STATE = os.path.expanduser('~/Library/Application Support/fdo2a/verify_publish.json')
DEADLINE = {'us': (1, 12), 'kr': (0, 23)}     # 세션 D 의 (며칠 뒤, KST 시) — US 는 다음 날 12:00, KR 은 그날 23:00
FETCH_STALE = timedelta(hours=2)
GITHUB_STALE = timedelta(hours=9)             # 3시간 심장 박동 + 예약 지연 5시간 + 여유(설계 v5) — 요약이 넘겨 쓴다
KEEP_SENT = timedelta(days=60)

# outbox 계약(alerts-outbox/1) — 생산자 상한. Worker 는 넘는 outbox 를 통째로 거부한다.
OUTBOX_FORMAT = 'alerts-outbox/1'
MAX_EVENTS, MAX_TEXT, MAX_KEY, MAX_BYTES = 500, 3900, 200, 256 * 1024
OVERFLOW_KEY = 'sys:overflow'
# 계약 §1 의 kind 목록에 overflow 를 넣었다(2026-11-10) — Worker 검증 목록과 같이 바꾼다.
OVERFLOW_KIND = 'overflow'
OVERFLOW_TEXT = ('[발행 알림] 알림 일부 대기 중 · 확인 필요\n한 번에 실을 수 있는 양(500건·256KB)을 넘었거나 '
                 '한 건이 3,900자를 넘어요. 자르지 않고 남겨 뒀어요\n양이 넘은 알림은 앞의 것이 전송되면 이어서 나가고, '
                 '너무 긴 알림은 나가지 않아요 — 상태 브랜치의 계산 상태에서 직접 확인')
_ID = re.compile(r'^[0-9a-f]{32}$')
_HASH = re.compile(r'^[0-9a-f]{64}$')
HERE = os.path.dirname(os.path.abspath(__file__))

# ── 글 막힘(즉시 알림, 2026-11-22 — 설계 instant_telegram v1.4, spec 2026-11-22-prepub-hold.md 「글 막힘 알림」) ──
# 대상 섹션. 발행 전 검토가 붙는 섹션이 생기면 여기에 한 줄을 더한다 — key·이름표·글 경로는 섹션 공통이다.
HOLD_SECTIONS = ('us', 'us-news')            # us-news = US 뉴스·산업 브리프 news/<D>.html (2026-11-28)
HOLD_DIR = 'reviews/prepublish/{section}'
HOLD_WINDOW = timedelta(days=7)               # 파일 이름의 날짜가 오늘(KST)에서 7일 안인 것만 본다
HOLD_SHIP = '_hold_ship'                      # 이번 실행이 살아 있다고 확인한 막힘 사건 id — 상태 파일에 저장하지 않는다
# 부호 → 이유(닫힌 표). 기록의 `reason` 글자는 옮기지 않는다. 집합은 prepub_review 의 NOT_RUN ∪ HOLD_CODES 와 같다(시험).
HOLD_REASON = {
    'submit_failed': '초안을 올리거나 검토를 띄우지 못했어요', 'timeout': '마감까지 검토가 오지 않았어요',
    'limit': 'codex 사용 한도', 'failed': '검토 실행이 실패했어요', 'mismatch': '다른 초안의 검토 결과가 왔어요',
    'not_reviewed': 'codex 가 검토하지 못했어요', 'suspicious_output': '검토 답이 이상해 버렸어요(인코딩 덩어리)',
    'sandbox_failed': '검토 샌드박스가 실패했어요', 'manifest_mismatch': '검토 묶음의 해시가 맞지 않아요',
    'auth_missing': '검토 로그인 비밀값이 없어요', 'bad_input': '검토 입력 형식이 틀렸어요',
    'no_status': '검토 상태 파일이 없어요', 'fallback': '검토 상태를 알 수 없어요',
    'stale_html': '기다리는 사이 초안이 바뀌었어요', 'mark_failed': '판정 중 표시를 달지 못해 판정하지 않았어요',
    'recovery_needed': '받아들인 수정을 반영하지 못했어요', 'style_abort': '문체 마감이 중단을 요구했어요',
    'facts_unmarked': '정확성 판정 완료 표시가 없어요',
}
HOLD_NEXT_HEAD = {'retry': '자동 재시도 예정', 'person': '사람 확인 필요'}
HOLD_NEXT_TEXT = {'retry': '재시도 루틴이 다음 차례에 처음부터 다시 써요(언제인지는 기록에 없어요)',
                  'person': '자동으로 다시 쓰지 않아요 — 원인을 고친 뒤 잠금을 풀어야 해요(unhold)'}
HOLD_UNKNOWN = '?'
# 서명 = 「state|next」 — 검증한 부호와 고정 표시(?)만으로 짓는다(상태 가지는 공개다 — 기록의 글자를 남기지 않는다)
_HOLD_SIGS = frozenset(f'{a}|{b}' for a in (*HOLD_REASON, HOLD_UNKNOWN) for b in (*HOLD_NEXT_TEXT, HOLD_UNKNOWN))
_HOLD_BLIND = re.compile(r'\?\|\?\|[0-9a-f]{16}')   # 못 읽은 기록의 서명 — 뒤는 git blob id 앞 16자(바이트가 바뀌면 바뀐다)
# JSON 토큰 하나(앞 공백 포함): 문자열 / 숫자 / true·false·null / 구두점. 문법은 RFC 8259 그대로 — NaN·Infinity 는 받지 않는다.
_HOLD_TOKEN = re.compile(
    r'[ \t\n\r]*(?:(?P<s>"[^"\\\x00-\x1f]*(?:\\(?:["\\/bfnrt]|u[0-9a-fA-F]{4})[^"\\\x00-\x1f]*)*")'
    r'|(?P<n>-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)|(?P<l>true|false|null)|(?P<p>[\[\]{},:]))')
_HOLD_LITERAL = {'true': True, 'false': False, 'null': None}
_HOLD_NUM = type('_Num', (), {'__repr__': lambda self: '<숫자>'})()   # 변환하지 않은 숫자 — 어떤 값과도 같지 않다
_HOLD_KEY = re.compile(r'hold:(' + '|'.join(map(re.escape, HOLD_SECTIONS)) + r'):(\d{4}-\d{2}-\d{2})')
_HOLD_FILE = re.compile(r'(\d{4}-\d{2}-\d{2})\.json')
_BLOB = re.compile(r'[0-9a-f]{40,64}')
_HOLD_STAMP = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z')
_BORN = re.compile(r'[0-9a-f]{32}')


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


def new_state(reason, baseline=False):
    """baseline=True(처음 실행): 이미 있는 글·세션은 알리지 않고 기준선으로만 잡는다(설계 v3 #4, codex 구현 검토 #8).
    손상 복구는 baseline=False — 전부 다시 계산해 보낸다(중복이 유실보다 낫다)."""
    return {'format': FORMAT, 'last_seen': None, 'last_ok': None, 'posts': {}, 'sessions': {},
            'events': [], 'fetch': {}, 'calendar': {}, 'send_fail': 0, 'reset': reason, 'baseline': baseline}


def load_state(path):
    """None = 파일 없음(처음 실행). 손상은 StateError — 이전 상태를 정상으로 가정하지 않는다."""
    try:
        with open(path, 'rb') as fh:
            raw = fh.read()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise StateError(f'{type(exc).__name__}: {exc}') from exc
    return loads_state(raw)


_LOOSE = re.compile(rb'"[^"\\]*(?:\\.[^"\\]*)*"|[\[\]{},:]', re.S)   # 문자열 하나 또는 구두점 — 문법은 따지지 않는다


def _split_hold_fields(raw):
    """상태 바이트 → (막힘 칸 값 자리를 null 로 바꾼 바이트, 검증을 지난 {holds, born} 또는 None). 가를 수 없으면 None.

    막힘 칸(`holds`·`born`)은 공용 해석 **전에** 떼어 따로 읽는다. 여기서는 맨 위 층 객체에서 두 칸 값의 **바깥 경계만**
    찾는다(문자열과 괄호 깊이만 센다 — 문법·UTF-8 은 보지 않는다). 그래서 그 칸 안이 어떻게 틀렸든(남는 쉼표·NaN·긴 숫자·
    깊은 중첩·같은 칸 두 번·깨진 바이트) 나머지 상태의 해석·검증·저장에 닿지 않는다(codex 구현 3-5회차 #9, 설계 §14-1).
    나머지 바이트는 종전 그대로 공용 해석기가 읽는다 — 막힘 칸 밖의 손상은 종전대로 상태 전체 손상이다.
    떼어 낸 두 칸은 둘 다 한 번씩 있고 `_hold_ok` 를 지날 때만 돌려준다 — 아니면 둘 다 버린다(`_hold_state` 가 새로 만든다)."""
    depth, want, key, start, spans = 0, 'open', None, None, []
    for m in _LOOSE.finditer(raw):
        c = m.group()
        if depth == 0:
            if c != b'{' or want != 'open' or raw[:m.start()].strip(b' \t\n\r'):
                return None                             # 맨 위 층이 객체 하나가 아니다
            depth, want = 1, 'key'
        elif depth == 1 and want == 'key':
            if c == b'}':
                depth, want = 0, 'closed'
            elif c[:1] == b'"':
                key, want = c, 'colon'
            else:
                return None
        elif depth == 1 and want == 'colon':
            if c != b':':
                return None
            start, want = m.end(), 'value'
        elif c in (b'{', b'['):
            depth += 1
        elif c in (b'}', b']', b',') and depth == 1:    # 맨 위 층의 값 하나가 여기서 끝났다
            if key in (b'"holds"', b'"born"'):
                spans.append((key, start, m.start()))
            depth, want = (1, 'key') if c == b',' else (0, 'closed')
            if c == b']':
                return None
        elif c in (b'}', b']'):
            depth -= 1
    if want != 'closed' or depth:
        return None
    rest, got = raw, {}
    for _, i, j in reversed(spans):
        rest = rest[:i] + b' null ' + rest[j:]

    def pairs_once(items):
        d = dict(items)
        if len(d) != len(items):
            raise ValueError('duplicate key')
        return d
    try:
        for key, i, j in spans:
            name = key[1:-1].decode('ascii')
            if name in got:
                raise ValueError('duplicate key')
            got[name] = json.loads(raw[i:j].decode('utf-8'), object_pairs_hook=pairs_once)
        if not _hold_ok(got.get('holds'), got.get('born')):
            got = None
    except Exception:  # noqa: BLE001 — 막힘 칸만 못 읽었다
        got = None
    return rest, got


def loads_state(raw):
    """바이트·문자열에서 — `git show origin/alerts-state:verify_publish.json` 의 출력을 그대로 받는다.
    돌려주는 상태에는 막힘 칸이 **검증을 지난 채로 둘 다 있거나 둘 다 없다**."""
    try:
        try:
            split = _split_hold_fields(raw if isinstance(raw, bytes) else raw.encode('utf-8'))
        except Exception:  # noqa: BLE001 — 가르지 못하면 종전 길(공용 해석)로
            split = None
        if split is None:
            obj = json.loads(raw.decode('utf-8') if isinstance(raw, bytes) else raw)
        else:
            obj = json.loads(split[0].decode('utf-8'))
    except (ValueError, UnicodeDecodeError) as exc:
        raise StateError(f'{type(exc).__name__}: {exc}') from exc
    if isinstance(obj, dict):
        held = split[1] if split is not None else {k: obj[k] for k in ('holds', 'born') if k in obj}
        if split is None:
            try:
                held = held if _hold_ok(held.get('holds'), held.get('born')) else None
            except Exception:  # noqa: BLE001
                held = None
        obj.pop('holds', None)
        obj.pop('born', None)
        if held:
            obj.update(held)
    try:
        _validate(obj)
    except (TypeError, ValueError) as exc:
        raise StateError(f'상태 파일 내용이 이상하다 — {exc}') from exc
    return obj


def _saved(st):
    """저장하는 상태 — 이번 실행만의 값(HOLD_SHIP)은 빼고. 다음 실행이 지난 실행의 「살아 있음」을 물려받지 않게."""
    return {k: v for k, v in st.items() if k != HOLD_SHIP}


def dumps_state(st):
    return json.dumps(_saved(st), ensure_ascii=False, indent=1, sort_keys=True)


def _validate(obj):
    """형식이 맞아 보여도 안이 틀리면 손상이다 — 매일 요약까지 넘어지지 않게 여기서 거른다(codex 구현 검토 #6)."""
    def bad(why):
        raise StateError(f'상태 파일 내용이 이상하다 — {why}')
    if not isinstance(obj, dict) or obj.get('format') != FORMAT:
        bad('형식')
    for k in ('posts', 'sessions', 'fetch', 'calendar'):
        if not isinstance(obj.get(k), dict):
            bad(k)
    if not isinstance(obj.get('events'), list):
        bad('events')
    # 11/11 추가 — 칸이 없는 옛 상태만 받는다. 있으면 문자열 사전이어야 한다(null 도 손상, codex 재검토 #1)
    if 'calendar_why' in obj and not (isinstance(obj['calendar_why'], dict) and all(
            isinstance(k, str) and isinstance(v, str) for k, v in obj['calendar_why'].items())):
        bad('calendar_why')
    for e in obj['events']:
        if not (isinstance(e, dict) and all(isinstance(e.get(f), str) for f in ('id', 'kind', 'key', 'text', 'status',
                                                                             'created'))):
            bad('사건')
        if datetime.fromisoformat(e['created']).tzinfo is None:
            bad('사건')                       # 시간대 없는 시각은 지금과 빼면 TypeError(codex 재검토 8회 #3)
    for k in ('last_ok',):
        if obj.get(k) is not None:
            try:
                if datetime.fromisoformat(obj[k]).tzinfo is None:
                    bad(k)
            except (TypeError, ValueError):
                bad(k)
    if obj.get('last_seen') is not None and not (isinstance(obj['last_seen'], str)
                                                 and re.fullmatch(r'[0-9a-f]{40}', obj['last_seen'])):
        bad('last_seen')                      # git 인자로 넘어간다 — 커밋 id 모양만(재검토 9회 #3)
    since = obj['fetch'].get('since')
    if since is not None:
        try:
            if datetime.fromisoformat(since).tzinfo is None:
                bad('fetch')
        except (TypeError, ValueError):
            bad('fetch')                      # 조회 실패 처리에서 지금과 뺀다(재검토 9회 #1)
    if not all(isinstance(v, str) for v in obj['sessions'].values()):
        bad('sessions')
    if not all(_SESSION_KEY.fullmatch(str(k)) and _real_date(k[3:]) for k in obj['sessions']):
        bad('sessions')                       # 요약 꼬리가 「시장:날짜」로 쪼갠다(codex 재검토 8회 #3)
    if not all(isinstance(v, dict) for v in obj['posts'].values()):
        bad('posts')
    if not isinstance(obj.get('send_fail', 0), int):
        bad('send_fail')


def save_state(path, st):
    """임시 파일 + os.replace — 매일 요약이 반쯤 쓰인 파일을 읽지 않게(설계 검토 #7)."""
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix='.publish-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            json.dump(_saved(st), fh, ensure_ascii=False, indent=1, sort_keys=True)
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
    """sha256(`kind|key|extra`) 앞 32 hex(128비트) — 계약 §1. 내용에서 정해져, 다시 계산해도 같은 사건은 같은 id."""
    return hashlib.sha256(f'{kind}|{key}|{extra}'.encode('utf-8')).hexdigest()[:32]


def text_hash(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


# 본문이 id 에 들어간다 — 같은 id 에 다른 본문이 가면 Worker 가 그 사건을 거부한다(core.js mismatch).
# ① 문구를 바꾼 뒤 상태를 잃고 다시 계산해도 옛 id·새 본문이 되지 않고(codex 구현 검토 d1 #3),
# ② 같은 사건을 다른 경로로 다시 계산해 본문이 달라져도(기준선으로 잡아 둔 세션의 「늦은 발행」 ↔ 커밋 시각으로 본
#    「늦은 발행」, 「사라짐」 두 문장 — d2 #1) 다른 id 가 된다. 다른 id 는 한 번 더 갈 수 있다 — 계약은 「중복 전송 허용」.
# publish·changed 는 호출부가 본문 해시를 extra 에 이미 넣는다(맥·GitHub 가 같은 id 를 쓰도록 GitHub 문장 기준).
BODY_IN_EXTRA = ('publish', 'changed')


def _base_id(kind, key, extra=''):
    """상태 안에서 「같은 사건」을 가리는 값 — 종전의 id 그대로다. 본문을 넣기 전에 쌓인 사건은 id 가 곧 이 값이다."""
    return event_id(kind, key, extra)


def _body_id(kind, key, extra, text):
    return event_id(kind, key, extra if kind in BODY_IN_EXTRA else f'{extra}|{text_hash(text)}')


def add_event(st, kind, key, text, now, extra=''):
    """key 는 순서 단위(계약 §1): 글 경로 / `us:2026-11-10` / `sys:<kind>`. 같은 key 안에서 달라야 할 것은 extra 로.
    한 번만 쌓는 단위는 종전대로 (kind, key, extra) 다 — id 에 본문이 들어가도 같은 사건이 두 번 쌓이지 않는다."""
    base = _base_id(kind, key, extra)
    if any(e.get('base', e.get('id')) == base for e in st['events']):
        return None
    eid = _body_id(kind, key, extra, text)
    st['events'].append({'id': eid, 'base': base, 'kind': kind, 'key': key, 'text': text, 'hash': text_hash(text),
                         'created': now.isoformat(), 'status': 'pending', 'tries': 0})
    return eid


def _set_text(ev, text):
    ev['text'], ev['hash'] = text, text_hash(text)


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
    return _holidays(root, market, rev)[0]


def _holiday_reasons(market):
    """`_holidays` 가 만드는 문장 전부 — 요약 꼬리는 이 밖의 값을 싣지 않는다(codex 재검토 3회 #1)."""
    return {'그 커밋에서 data/market_holidays.json 을 읽지 못했어요', 'data/market_holidays.json 이 JSON 이 아니에요',
            f'data/market_holidays.json 에 {market}.dates 목록이 없어요', '이유를 몰라요'}


def _holidays(root, market, rev):
    """(달력 | None, 못 읽은 이유) — 이유는 요약 꼬리에 붙는다(사용자 11/11 「이유까지」)."""
    try:
        raw = V._git(root, 'show', f'{rev}:data/market_holidays.json')
    except V.GitError:
        return None, '그 커밋에서 data/market_holidays.json 을 읽지 못했어요'
    try:
        cal = json.loads(raw.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        return None, 'data/market_holidays.json 이 JSON 이 아니에요'
    mk = cal.get(market) if isinstance(cal, dict) else None
    dates = mk.get('dates') if isinstance(mk, dict) else None          # 시장 값이 객체가 아니어도 달력 오류로(재검토 9회 #2)
    if not isinstance(dates, list) or not all(isinstance(x, str) for x in dates):
        return None, f'data/market_holidays.json 에 {market}.dates 목록이 없어요'
    return tuple(dates), None


def _real_date(x):
    """있는 날짜(YYYY-MM-DD)인가 — 형식만 보면 2026-99-99 가 「다음 판」이 된다(codex 재검토 6회)."""
    if not isinstance(x, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', x):
        return False
    try:
        date.fromisoformat(x)
    except ValueError:
        return False
    return True


KR_CORE = {'indices': '지수', 'flows': '수급', 'top_value': '거래대금', 'sectors': '섹터'}
KR_FLOW_WHY = {'blocked': '최신 날짜 수급을 못 읽음', 'error': '수급 요청 실패'}


def _kr_block_reasons(d):
    """KR 미발행 줄 꼬리 — 빠진 코어 토큰과 검사 status 를 고정 문구로(2026-11-12). 원문·긴 값은 싣지 않는다.
    사전 밖 값은 「알 수 없는 상태/항목」. 읽을 것이 없으면 빈 문자열(지금 문구 그대로)."""
    from review.digest import KR_IDX, KR_PCT_WHY
    parts = []
    miss = d.get('missing') if isinstance(d.get('missing'), list) else []
    core = [KR_CORE[m] for m in KR_CORE if m in miss]
    if any(isinstance(m, str) and m not in KR_CORE and m not in ('econ', 'themes', 'flows_intraday') for m in miss):
        core.append('알 수 없는 항목')
    ck = d.get('checks') if isinstance(d.get('checks'), dict) else {}
    ip = ck.get('index_pct') if isinstance(ck.get('index_pct'), dict) else {}
    for name, label in KR_IDX.items():
        st = (ip.get(name) or {}).get('status') if isinstance(ip.get(name), dict) else None
        if st is None or st in ('ok', 'ok_flat'):
            continue
        if st == 'mismatch':
            why = '종가로 계산한 값과 어긋남' + (' — 차단 켜짐' if ip.get('mode') == 'block' else '(기록만)')
        else:
            why = KR_PCT_WHY.get(st, '알 수 없는 상태')
        parts.append(f'{label} 등락률 — {why}')
    fl = ck.get('flows') if isinstance(ck.get('flows'), dict) else {}
    for name, label in KR_IDX.items():
        st = (fl.get(name) or {}).get('state') if isinstance(fl.get(name), dict) else None
        if st is None or st == 'ok':
            continue
        parts.append(f'{label} 수급 — {KR_FLOW_WHY.get(st, "알 수 없는 상태")}')
    tv = ck.get('top_value')
    if isinstance(tv, dict):
        if 'error' in tv:
            parts.append('거래대금 — 수집 실패')
        elif isinstance(tv.get('positive_rows'), int) and tv['positive_rows'] < 10:
            parts.append('거래대금 — 상위 표가 10행이 안 됨')
    out = ''
    if core:
        out += f'. 빠진 코어: {"·".join(core)}'
    if parts:
        out += f' ({"; ".join(parts)})'
    return out


def _collection_note(root, rev, market, session):
    """미발행 사건의 「원인」 줄 — 그 시각 레포의 수집 판만 보고, 원인을 단정하지 않는다(codex 설계 검토 #4)."""
    path = {'us': 'data/market_data.json', 'kr': 'kr/data/kr_market_data.json'}[market]
    try:
        d = json.loads(V._git(root, 'show', f'{rev}:{path}').decode('utf-8'))
        rd, done = d.get('report_date'), d.get('complete')
    except (V.GitError, ValueError, UnicodeDecodeError, AttributeError):
        return f'원인: 확정하지 못했어요 — 레포의 수집 데이터({path})를 읽지 못했어요. 발행 루틴·데이터 수집 상태 점검 필요'
    if not _real_date(rd):
        # 원문을 싣지 않는다 — 긴 값이면 사건이 3,900자를 넘어 경고 자체가 안 나간다(codex 재검토 5회 #2)
        return '원인: 확정하지 못했어요 — 수집 데이터의 report_date 가 없거나 날짜 형식이 아니에요. 발행 루틴·데이터 수집 상태 점검 필요'
    if rd == session and done is True:
        return ('원인: 확정하지 못했어요 — 이 세션의 완전한 수집 데이터는 레포에 있어요'
                f'(report_date {rd}). 데이터는 있으니 작성 루틴이 돌지 않았거나 도중에 멈췄을 수 있어요')
    if rd == session and done is False:
        return ('원인: 확정하지 못했어요 — 이 세션 수집 데이터가 완전하지 않아요'
                f'(report_date {rd}, complete false). 루틴은 불완전한 데이터로는 발행하지 않아요'
                + (_kr_block_reasons(d) if market == 'kr' else ''))
    if rd == session:
        return ('원인: 확정하지 못했어요 — 이 세션 수집 데이터는 있는데 완전한지 표시(complete)를 읽지 못했어요'
                f'(report_date {rd}). 발행 루틴·데이터 수집 상태 점검 필요')
    if rd < session:
        return ('원인: 확정하지 못했어요 — 레포의 최신 수집 데이터가 이 세션보다 앞선 판이에요'
                f'(report_date {rd}). 이 세션 수집이 아직 안 됐거나 실패했을 수 있어요')
    return ('원인: 확정하지 못했어요 — 레포의 최신 수집 데이터가 이미 다음 판이에요'
            f'(report_date {rd}). 이 세션 데이터가 수집됐었는지는 이 파일로 알 수 없어요')


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
        add_event(st, 'fetch', 'sys:fetch', f'[발행 알림] GitHub 조회 실패 · 확인 필요\n{hours}시간 넘게 실패하고 있어요 — '
                                            f'미발행 여부를 몰라서 그동안 미발행 판정을 멈춰요\n사유: {f["why"]}', now,
                  extra=f['since'])
        f['alerted'] = True


# 기록·건별 알림이 보는 경로 — US 뉴스·산업 글(news/)은 2026-11-20 부터(그 전 글은 V.start_of 가 거른다)
WATCH_PATHS = ('posts', 'kr/posts', 'news', 'verification')


def _tree(root, rev):
    raw = V._git(root, 'ls-tree', '-r', '--name-only', '-z', rev, '--', *WATCH_PATHS)
    return {p for p in raw.decode('utf-8', 'replace').split('\0') if p}


def _ancestry(root, old, new):
    """(조상인가, 아니면 그 이유) — gap 알림에 붙는다."""
    import subprocess
    out = subprocess.run(['git', '-C', root, 'merge-base', '--is-ancestor', old, new], capture_output=True, timeout=60)
    if out.returncode == 0:
        return True, None
    if out.returncode == 1:
        return False, '기준점이 지금 이력의 조상이 아니에요(이력이 다시 쓰였을 수 있어요)'
    have = subprocess.run(['git', '-C', root, 'rev-parse', '--verify', '--quiet', f'{old}^{{commit}}'],
                          capture_output=True, timeout=60)
    if have.returncode == 1:
        return False, '기준점 커밋이 이 클론에 없어요(강제 push·이력 정리 가능)'
    return False, f'git 이 조상 관계를 판단하지 못했어요(종료 코드 {out.returncode})'   # 조상이라고 하지 않는다


def _deleted_by(root, tip, path):
    """사라진 글을 지운 커밋 — 짧은 sha·제목(공개 이력). 못 찾으면 그렇다고."""
    try:
        out = V._git(root, 'log', '-1', '--diff-filter=D', '--format=%h %s', tip, '--', path).decode('utf-8', 'replace')
    except V.GitError:
        return '지운 커밋을 읽지 못했어요.'
    out = out.strip()
    if not out:
        return '지운 커밋을 찾지 못했어요(이력이 다시 쓰였을 수 있어요).'
    h, _, subj = out.partition(' ')
    subj = ' '.join(subj.split())
    return f'지운 커밋 {h}「{subj[:60]}{"…" if len(subj) > 60 else ""}」.'


def _changed(root, old, new):
    """두 시점의 트리 비교가 아니라 사이 커밋마다의 변경 — 그 사이에 올라왔다 사라진 글도 잡는다(codex 구현 검토 #2)."""
    # -m: merge 커밋의 변경도 부모마다, --no-renames: 옮긴 글의 옛 경로를 삭제로 남긴다(codex 재검토 #2).
    raw = V._git(root, 'log', '-m', '--no-renames', '--format=', '--name-only', '-z', f'{old}..{new}', '--',
                 *WATCH_PATHS)
    return {p.strip('\n') for p in raw.decode('utf-8', 'replace').split('\0') if p.strip('\n')}


def _target_of_any(path):
    t = V.target_of(path)
    if t:
        return t
    parts = path.split('/')
    if len(parts) == 3 and parts[0] == 'verification' and parts[1] in V.RECORD_TARGETS and parts[2].endswith('.json'):
        d = parts[2][:-5]
        if d >= V.start_of(parts[1]):
            return parts[1], d
    return None


def _mark_gone(st, key):
    """기준 시각 전에 지워진 글은 「미발행」이 아니라 「사라짐」. 이미 미발행 경고가 걸린 세션은 그대로 둔다 — 덮어쓰면
    나중에 다시 올라와도 그 경고를 해소·취소하지 않는다(codex 재검토 3회 #5)."""
    if st['sessions'].get(key) not in ('missing', 'missing_quiet'):
        st['sessions'][key] = 'gone'


def _short(path):
    t = V.target_of(path)
    return f'{V.LABEL[t[0]]} {int(t[1][5:7])}/{t[1][8:]}' if t else path


def _when(dl):
    return f'{dl.month}/{dl.day:02d} {dl:%H:%M} KST'


def _late_or_ok(st, root, tip, market, s, path, dl, now, emit=None):
    emit = emit or add_event
    try:
        adds = V._adding(root, tip, path)
        if len(adds) != 1:
            return 'ok'
        ct = datetime.fromisoformat(V._git(root, 'log', '-1', '--format=%cI', adds[0]).decode().strip())
    except (V.GitError, ValueError):
        return 'ok'
    if ct <= dl:
        return 'ok'
    ct = ct.astimezone(KST)
    emit(st, 'late', f'{market}:{s}', f'[늦은 발행] {_label(market, s)} · 확인만\n기준 시각({_when(dl)}) 뒤에 '
                                           f'올라온 것으로 보여요(커밋 시각 {ct.month}/{ct.day:02d} {ct:%H:%M} 기준 — 실제 '
                                           '공개 시각과 다를 수 있어요)\n미발행 경고는 보내지 않았어요', now)
    return 'late'


def step(st, root, now, fetched, ref=REF, who=V.MAC):
    """사건을 pending 으로 쌓는다. 조회·읽기에 실패하면 기준점을 옮기지 않는다.

    who=V.GITHUB(2.5단계): 문장의 확인 주체가 GitHub 이고, pending 은 「outbox 에 실려 전송됐을 수 있음」이다 —
    대기 중 미발행 경고를 취소하지 않는다(설계 v3 #1)."""
    github = who == V.GITHUB
    st.pop(HOLD_SHIP, None)                          # 막힘 사건은 이번 훑기가 확인한 것만 싣는다 — 일찍 돌아가는 갈래 포함
    if not fetched:
        _fetch_failed(st, now, 'git fetch 실패')
        return st
    try:
        tip = V._git(root, 'rev-parse', '--verify', f'{ref}^{{commit}}').decode().strip()
        tree = _tree(root, tip)
        last = st.get('last_seen')
        full = last is None
        anc, anc_why = _ancestry(root, last, tip) if last else (True, None)
        if not anc:
            add_event(st, 'gap', 'sys:gap',
                      f'[발행 알림] 확인 기준점을 잃음 · 확인 필요\n지난 확인 기준점({last[:7]})을 지금 이력에서 못 찾았어요 '
                      f'— {anc_why}\n그 사이 사건을 다 봤다고 할 수 없어요. {V.EFFECTIVE} 이후 글을 전부 다시 계산해요', now,
                      extra=f'{last}->{tip}')
            full = True
        paths = tree if full else _changed(root, last, tip)
        targets = {t for t in map(_target_of_any, paths) if t}
        if full:                                     # 전부 다시 볼 때는 알던 글(지금 없을 수 있다)도
            targets |= {t for t in map(_target_of_any, st['posts']) if t}
        targets = sorted(targets)
        views = {}
        for market, d in targets:
            path = V.post_path(market, d)
            if path in tree:
                views[path] = V.view(root, tip, market, d)
        cal_why = {}
        cals = {}
        for m in V.TARGETS:
            cals[m], cal_why[m] = _holidays(root, m, tip)
    except V.GitError as exc:
        _fetch_failed(st, now, f'읽기 실패 — {exc}')
        return st

    quiet = bool(st.get('baseline')) and last is None
    emit = (lambda *a, **k: None) if quiet else add_event
    reset = st.get('reset')
    if reset:
        st['reset'] = None
        rextra = f'{reset}|{now.date().isoformat()}'
        rid = add_event(st, 'reset', 'sys:reset', '', now, extra=rextra)      # 본문은 아래에서 채운다 — id 도 그때 다시
    st['baseline'] = False

    # 미발행·해소 먼저 — 「해소」가 그 글의 발행 알림보다 앞에 오게
    for market, hol in cals.items():
        if hol is None:
            st['calendar'].setdefault(market, now.isoformat())
            st.setdefault('calendar_why', {})[market] = cal_why.get(market) or '이유를 몰라요'
            continue
        st['calendar'].pop(market, None)
        (st.get('calendar_why') or {}).pop(market, None)
        for s in sessions_due(market, now, hol):
            key, path = f'{market}:{s}', V.post_path(market, s)
            seen = st['sessions'].get(key)
            dl = deadline(market, s)
            if path in tree:
                if seen == 'gone':
                    st['sessions'][key] = 'ok'                     # 다시 올라왔다 — 글 쪽 알림이 따로 간다
                elif seen == 'missing_quiet':
                    # 기준선(첫 실행)에서 경고 없이 잡아 둔 세션 — 경고를 보낸 적이 없으니 「해소」가 아니다
                    emit(st, 'late', key, f'[늦은 발행] {_label(market, s)} · 확인만\n기준 시각({_when(dl)}) 뒤에 '
                                          '올라왔어요\n이 세션의 미발행 경고는 보낸 적이 없어요(처음 실행 때 기준선)', now)
                    st['sessions'][key] = 'resolved'
                elif seen == 'missing':
                    warn = next((e for e in st['events'] if e.get('kind') == 'missing' and e.get('key') == key), None)
                    # 한 번이라도 보내려 했으면 텔레그램이 받았을 수 있다 — 「안 보냈다」고 하지 않는다(codex 구현 검토 #3)
                    if github:
                        # outbox 에 실린 경고는 Worker 가 이미 보냈을 수 있다 — 취소하지 않고, 받았다고도 하지 않는다
                        emit(st, 'resolved', key, f'[미발행 해소] {_label(market, s)} · 해결\n글이 올라왔어요 '
                                                  f'— 앞서 생성된 미발행 경고(기준 {_when(dl)})가 풀렸어요', now)
                    elif warn is not None and warn.get('status') == 'pending' and not warn.get('attempted'):
                        # 경고를 아직 못 보냈다 — 보내지 않고 「늦은 발행」 하나로 바꾼다(받은 적 없는 경고의 해소를 보내지 않는다)
                        warn['status'] = 'cancelled'
                        emit(st, 'late', key, f'[늦은 발행] {_label(market, s)} · 확인만\n기준 시각'
                                                   f'({_when(dl)}) 뒤에 올라왔어요\n미발행 경고는 보내기 전에 해소돼 '
                                                   '보내지 않았어요', now)
                    else:
                        emit(st, 'resolved', key, f'[미발행 해소] {_label(market, s)} · 해결\n글이 올라왔어요 '
                                                       f'— 앞서 보낸 미발행 경고(기준 {_when(dl)})가 풀렸어요', now)
                    st['sessions'][key] = 'resolved'
                elif seen is None and now >= dl:
                    # 기준 시각을 넘겨 처음 봤다 — 그때 맥이 못 봤을 수 있다. 커밋 시각으로 늦었는지만 추정한다
                    st['sessions'][key] = _late_or_ok(st, root, tip, market, s, path, dl, now, emit)
            elif seen in ('ok', 'late', 'resolved'):
                _mark_gone(st, key)                                # 올라갔던 글이 없다 — 글 쪽 「사라짐」 알림이 간다(#5)
            elif seen is None and now >= dl:
                st['sessions'][key] = 'missing_quiet' if quiet else 'missing'
                note = _collection_note(root, tip, market, s)
                # 원인 줄은 그 시각 수집 판에 따라 바뀐다 — id 에 넣어 같은 id·다른 본문이 되지 않게(Fable #4)
                # 첫 줄 = 대상·상태(미리보기는 첫 줄만), 원인은 단정하지 않는다(11/19 알림 틀)
                emit(st, 'missing', key,
                          f'[미발행] {_label(market, s)} · 확인 필요\n'
                          f'기준 시각 {_when(dl)} 이 지났는데 이번에 확인한 공개 판에 글이 없어요\n'
                          + note.replace('원인: 확정하지 못했어요 — ', '원인(확정 아님): ', 1), now, extra=text_hash(note))

    flagged, unverified = 0, []
    for path, v in views.items():
        fp = V.fingerprint(v)
        prev = st['posts'].get(path)
        if prev is None:
            # 기준선(첫 실행)이어도 문제가 있는 글은 알린다 — 조용히 저장하면 그 경로가 다시 안 바뀌는 한 영영 안 나온다(#8)
            text = V.render_publish(v, who=who)
            # 본문 해시도 id 에 — 문구가 바뀐 뒤 상태를 새로 시작해도 같은 id·다른 본문이 되지 않게(codex 최종 검토)
            # 해시는 GitHub 판 문장으로 — 확인 주체(맥/GitHub)가 달라도 같은 사건은 같은 id(전환 계약)
            canon = text if who == V.GITHUB else V.render_publish(v, who=V.GITHUB)
            (add_event if quiet and not V.clean(v) else emit)(st, 'publish', path, text, now,
                                                              extra=f'{fp}|{text_hash(canon)}')
            flagged += quiet and not V.clean(v)
            if quiet and V.clean(v) and not V.fully_verified(v):
                unverified.append(path)
            st['posts'][path] = {'fp': fp, 'first_seen': tip}
        else:
            if prev.get('gone'):
                prev['gone'] = False
                emit(st, 'back', path, f'[다시 올라옴] {_short(path)} · 확인만\n사라졌던 글이 다시 공개 판에 있어요', now,
                     extra=tip)
            if prev.get('fp') != fp:
                text = V.render_publish(v, head='[상태 바뀜]', who=who)
                canon = text if who == V.GITHUB else V.render_publish(v, head='[상태 바뀜]', who=V.GITHUB)
                emit(st, 'changed', path, text, now, extra=f'{fp}|{text_hash(canon)}')
                prev['fp'] = fp
    # 공개 판에서 사라진 글 — 알던 글이든, 맥이 보기 전에 올라왔다 사라진 글이든(codex 구현 검토 #2·#5)
    for market, d in targets:
        path = V.post_path(market, d)
        if path in tree:
            continue
        prev = st['posts'].get(path)
        if prev is not None and not prev.get('gone'):
            prev['gone'] = True
            _mark_gone(st, f'{market}:{d}')
            emit(st, 'gone', path, f'[사라짐] {_label(market, d)} · 확인 필요\n발행됐던 글이 지금 공개 판에 없어요\n'
                                  f'{_deleted_by(root, tip, path)} 루틴·정정 이력 확인', now, extra=tip)
        elif prev is None and path in paths:
            st['posts'][path] = {'fp': None, 'first_seen': None, 'gone': True}
            _mark_gone(st, f'{market}:{d}')
            emit(st, 'gone', path, f'[사라짐] {_label(market, d)} · 확인 필요\n{V.subject(who)} 확인하기 전에 '
                                  f'올라왔다가 지금은 없어요\n{_deleted_by(root, tip, path)} 루틴·정정 이력 확인', now,
                 extra=tip)

    try:
        _hold_scan(st, root, tip, tree, now, quiet)
    except Exception as exc:  # noqa: BLE001 — 훑지 못한 실행: 막힘을 닫지도 싣지도 않는다. 기존 판정은 그대로 간다
        st.pop(HOLD_SHIP, None)
        print(f'보류 기록을 훑지 못했다 — {type(exc).__name__}', file=sys.stderr)

    if reset and rid:
        ev = next(e for e in st['events'] if e['id'] == rid)
        # 아침 요약은 11/19 부터 발행 전 기록 내역을 싣지 않는다 — 그 줄을 가리키지 않는다
        _set_text(ev, f'[발행 알림] {reset} · 기준선만 잡음\n이미 올라온 글·세션은 알림 없이 기준선으로 잡았어요. '
                      f'즉시 확인이 필요한 이상이 있는 글 {flagged}편만 따로 알려요\n'
                      f'이상은 아니지만 설정된 검사가 다 끝나지 않은 글(경고·미실행·범위 밖 숫자·숫자 대조 없음) '
                      f'{len(unverified)}편' + (': ' + ', '.join(_short(p) for p in unverified[:10])
                                                 + (f' 외 {len(unverified) - 10}편' if len(unverified) > 10 else '')
                                                 if unverified else '')
                      + '\n아직 안 올라온 세션은 아침 요약에 있어요'
                      if quiet else
                      f'[발행 알림] {reset} · 전부 다시 계산\n{V.EFFECTIVE} 이후 글을 전부 다시 계산해요(이미 받은 알림이 다시 올 수 있어요)')
        ev['id'] = _body_id('reset', 'sys:reset', rextra, ev['text'])       # 글 수·이름이 본문에 있다 — 본문이 다르면 다른 id
    if st['fetch'].get('alerted'):
        add_event(st, 'fetch_ok', 'sys:fetch_ok', '[발행 알림] GitHub 조회 복구 · 해결\n밀린 판정을 이어서 해요', now,
                  extra=st['fetch'].get('since', ''))
    st['fetch'] = {}
    st['last_seen'], st['last_ok'] = tip, now.isoformat()
    cutoff = now - KEEP_SENT
    st['events'] = [e for e in st['events'] if (e.get('status') not in ('sent', 'failed') or _closed_at(e) >= cutoff)
                    and not (_is_hold(e) and e.get('status') == 'cancelled' and _closed_at(e) < cutoff)]
    return st


# ── 글 막힘 ───────────────────────────────────────────────────────────────

def _is_hold(e):
    """막힘 사건 — `hold:` key 와 회차 표시(`held`)가 둘 다 있을 때만. 기존 사건은 이 둘을 갖지 않는다."""
    return str(e.get('key', '')).startswith('hold:') and type(e.get('held')) is int


def _hold_notice(e):
    """막힘 때문에 생긴 넘침 알림 — 다음 실행에도 기존 사건의 자리 계산에 끼지 않고, 막힘과 함께 남은 자리에만 실린다."""
    return e.get('key') == OVERFLOW_KEY and e.get('held_overflow') is True


def _hold_ok(holds, born):
    """막힘 칸 둘의 닫힌 꼴 — 상태를 읽을 때(`loads_state`)와 훑을 때(`_hold_state`) 같은 검사를 쓴다."""
    return bool(isinstance(born, str) and _BORN.fullmatch(born) is not None and isinstance(holds, dict) and all(
        isinstance(k, str) and _HOLD_KEY.fullmatch(k) and _real_date(k.rsplit(':', 1)[1])
        and isinstance(v, dict) and set(v) == {'n', 'sig', 'live'} and type(v['n']) is int and 0 <= v['n'] <= 10 ** 6
        and isinstance(v['sig'], str) and (v['sig'] in _HOLD_SIGS or _HOLD_BLIND.fullmatch(v['sig']))
        and type(v['live']) is bool
        for k, v in holds.items()))


def _hold_state(st):
    """막힘 칸(`holds`·`born`)을 **따로** 검사한다 — 공용 `_validate` 에 넣으면 이 칸만 깨져도 상태 전체가 새로
    시작한다(설계 §14-1). 깨졌으면(또는 처음이면) 둘을 함께 새로 만든다: 회차가 1 부터 다시 시작하니 `born` 도 새 값이어야
    옛 사건과 번호가 겹치지 않는다."""
    if not _hold_ok(st.get('holds'), st.get('born')):
        st['holds'], st['born'] = {}, secrets.token_hex(16)     # 시각이 아니라 무작위 값 — 같은 초의 복구에서도 겹치지 않는다
    return st['holds'], st['born']


def _hold_when(at):
    """검증한 `recorded_at` → 「M/DD HH:MM」(KST). 꼴·값이 틀리거나 바꾸다 넘치면 None."""
    if not (isinstance(at, str) and _HOLD_STAMP.fullmatch(at)):
        return None
    try:
        t = datetime.strptime(at, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc).astimezone(KST)
        return f'{t.month}/{t.day:02d} {t:%H:%M}'
    except (ValueError, OverflowError):
        return None


def _json_top(text):
    """JSON 글자 → 맨 위 층. 객체면 (`'{'`, [(칸, 값)…], [(값 시작, 값 끝)…]), 배열이면 (`'['`, [값…], None), 그 밖은
    (None, 값, None). 안쪽 `{}`·`[]` 의 값은 None, 숫자는 0-99 의 정수만 값으로(나머지는 `_HOLD_NUM`). 못 읽으면 예외.

    읽는 길은 하나다: 글자 전체를 **재귀 없이** 토큰 단위로 훑으며 JSON 문법을 끝까지 검사하고(괄호 짝·쉼표·콜론·문자열·숫자
    꼴), 맨 위 층의 값만 꺼낸다. 크기·중첩 깊이·숫자 길이가 달라도 같은 길이고, 문법이 틀린 글자는 어디가 틀렸든 못 읽은
    것이다(codex 구현 1-3회차 — 「너무 크면」「너무 깊으면」「숫자가 길면」「안쪽 괄호가 어긋나면」을 따로 다루다 뚫렸다).
    쓰지 않는 값은 변환하지 않는다 — 긴 숫자가 읽기를 깨지 않는다."""
    stack, pos, want = [], 0, 'value'            # want: value·first(값 또는 닫기)·key·firstkey·colon·after·end
    kind0 = top = key = spans = None
    while True:
        m = _HOLD_TOKEN.match(text, pos)
        if not m:
            break
        pos, kind, tok = m.end(), m.lastgroup, m.group(m.lastgroup)
        if (kind != 'p' or tok in '{[') and want in ('value', 'first'):
            if kind == 's':
                val = json.loads(tok)             # 문자열 하나 — 중첩이 없다
            elif kind == 'n':
                val = int(tok) if len(tok) <= 2 and tok.isdigit() else _HOLD_NUM
            elif kind == 'l':
                val = _HOLD_LITERAL[tok]
            else:
                val = None
            if not stack:
                if kind == 'p':
                    kind0, top, spans = tok, [], ([] if tok == '{' else None)
                else:
                    top = val
            elif len(stack) == 1 and kind0 == '{':
                top.append((key, val))
                spans.append((m.start(kind), pos))
            elif len(stack) == 1:
                top.append(val)
            if kind == 'p':
                stack.append(tok)
                want = 'firstkey' if tok == '{' else 'first'
            else:
                want = 'after' if stack else 'end'
        elif kind == 's' and want in ('key', 'firstkey'):
            if len(stack) == 1:
                key = json.loads(tok)
            want = 'colon'
        elif tok == ':' and want == 'colon':
            want = 'value'
        elif tok == ',' and want == 'after':
            want = 'key' if stack[-1] == '{' else 'value'
        elif kind == 'p' and tok in '}]' and (want == 'after' or want == ('firstkey' if tok == '}' else 'first')) \
                and stack and stack[-1] == ('{' if tok == '}' else '['):
            stack.pop()
            if len(stack) == 1 and kind0 == '{':
                spans[-1] = (spans[-1][0], pos)   # 안쪽 값이 여기서 끝났다
            want = 'after' if stack else 'end'
        else:
            raise ValueError('bad token')
    if want != 'end' or text[pos:].strip(' \t\n\r'):
        raise ValueError('not json')
    return kind0, top, spans


def _hold_top(body):
    """기록 바이트 → 맨 위 층의 값(`_json_top`). 판정에 쓰는 칸(`hold`·`state`·`next`)이 두 번이면 어느 값이 맞는지
    모른다 — 못 읽은 것이다. 쓰지 않는 칸이 두 번인 것은 읽기에 닿지 않는다(codex 구현 5회차 #4·#5)."""
    kind, top, _ = _json_top(body.decode('utf-8'))
    if kind != '{':
        return top
    names = [k for k, _ in top]
    if any(names.count(k) > 1 for k in ('hold', 'state', 'next')):
        raise ValueError('duplicate key')
    return dict(top)


def _hold_fields(body, blob):
    """보류 기록 바이트 → 살아 있는 막힘이면 값(모르는 칸은 None)과 서명, 아니면 None. 결과는 셋뿐이다.

    - 읽혔고 `hold` 가 true 이고 `state` 가 reviewed 가 아니다 → 살아 있다. 서명 = `state|next`(모르면 `?`).
    - 읽혔고 그 밖이다(발행 기록·hold 아님·객체 아님) → 살아 있지 않다.
    - **못 읽었다**(JSON·UTF-8 아님, 잘림, 같은 칸 두 번, 그 밖의 어떤 예외) → **살아 있다고 본다**, 값은 전부 모름.
      글 없는 날짜의 보류 기록 자리에 못 읽는 파일이 있는 것부터 정상이 아니고, 잘린 세움 기록을 조용히 넘기는 쪽이
      모름 알림 한 통보다 나쁘다. 서명에 blob id 를 붙여 **바이트가 바뀔 때만** 새 회차다(같은 바이트의 다시 push 는 아니다).
      이 값은 상태에만 남고 알림 글에는 싣지 않는다."""
    try:
        rec = _hold_top(body)
    except Exception:  # noqa: BLE001
        return {'state': None, 'next': None, 'attempt': None, 'when': None,
                'sig': f'{HOLD_UNKNOWN}|{HOLD_UNKNOWN}|{blob[:16]}'}
    if not isinstance(rec, dict) or rec.get('hold') is not True or rec.get('state') == 'reviewed':
        return None
    state, nxt, att = rec.get('state'), rec.get('next'), rec.get('attempt')
    state = state if isinstance(state, str) and state in HOLD_REASON else None
    nxt = nxt if isinstance(nxt, str) and nxt in HOLD_NEXT_TEXT else None
    return {'state': state, 'next': nxt, 'attempt': att if type(att) is int and 0 <= att <= 99 else None,
            'when': _hold_when(rec.get('recorded_at')), 'sig': f'{state or HOLD_UNKNOWN}|{nxt or HOLD_UNKNOWN}'}


def _hold_text(section, d, f):
    """닫힌 표와 검증한 값만으로 짓는다 — 기록의 글자(reason·요청 id·그 밖의 칸)는 한 글자도 옮기지 않는다."""
    return '\n'.join((
        f'[글 막힘] {_label(section, d)} · {HOLD_NEXT_HEAD.get(f["next"], "다음 동작 모름")}',
        '발행 전 검사를 끝내지 못해 글을 올리지 않았어요',
        '이유: ' + (HOLD_REASON[f['state']] if f['state'] else '이유 부호를 읽지 못했어요'),
        '다음: ' + (HOLD_NEXT_TEXT[f['next']] if f['next'] else '다음 동작은 기록에 없어요'),
        (f'기록 {f["when"]} KST' if f['when'] else '기록 시각 모름') + ' · '
        + (f'이 날짜의 센 실패 {f["attempt"]}번' if f['attempt'] is not None else '센 실패 수는 기록에 없어요')))


def _hold_live(root, tip, tree, today):
    """이번 판의 살아 있는 막힘 {key: (섹션, 날짜, 값)}. git 을 못 읽으면 GitError — 훑지 못한 실행이다."""
    found = {}
    for section in HOLD_SECTIONS:
        folder = HOLD_DIR.format(section=section) + '/'
        raw = V._git(root, 'ls-tree', '-z', tip, '--', folder)
        for row in raw.decode('utf-8', 'replace').split('\0'):
            meta, _, path = row.partition('\t')
            parts = meta.split()
            if len(parts) != 3 or parts[1] != 'blob' or not path.startswith(folder):
                continue
            m = _HOLD_FILE.fullmatch(path[len(folder):])       # 날짜는 파일 이름에서만
            if not m or not _real_date(m.group(1)):
                continue
            d = m.group(1)
            if not today - HOLD_WINDOW <= date.fromisoformat(d) <= today + timedelta(days=1):
                continue
            if V.post_path(section, d) in tree:                 # 그 날짜 글이 이 판에 있다 — 막힘이 아니다
                continue
            if not _BLOB.fullmatch(parts[2]):
                raise V.GitError('ls-tree 줄을 읽지 못했다')
            f = _hold_fields(V._git(root, 'cat-file', 'blob', parts[2]), parts[2])
            if f is not None:
                found[f'hold:{section}:{d}'] = (section, d, f)
    return found


def _hold_scan(st, root, tip, tree, now, quiet):
    """글 막힘 사건(설계 §4.3). 회차 = 서명(state|next)이 바뀔 때만 +1, 사건 번호 = `held|<born>|<회차>`.
    이번 훑기의 살아 있는 목록에 없는 막힘의 대기 사건은 닫고, 있는 것만 HOLD_SHIP 에 적는다(build_outbox 가 싣는다).
    기존 사건·`sessions`·전송 확인은 읽지도 고치지도 않는다."""
    today = now.astimezone(KST).date()
    found = _hold_live(root, tip, tree, today)                  # 읽기 실패는 여기서 — 아래는 아무것도 바꾸지 않았다
    holds, born = _hold_state(st)
    cur = {}
    for key, (section, d, f) in sorted(found.items()):
        sig = f['sig']
        h = holds.get(key)
        if not (h and h['live'] and h['sig'] == sig):
            n = (h['n'] if h else 0) + 1
            used = {e.get('base') for e in st['events'] if e.get('key') == key}
            while _base_id('missing', key, f'held|{born}|{n}') in used:
                n += 1                                          # 회차 칸만 잃었을 때 — 이력에 남은 번호를 다시 쓰면 옛 전송 확인에 흡수된다
            h = holds[key] = {'n': n, 'sig': sig, 'live': True}
            if not quiet:                                       # 처음 실행(기준선)에는 보내지 않는다
                extra = f'held|{born}|{h["n"]}'
                add_event(st, 'missing', key, _hold_text(section, d, f), now, extra=extra)
                base = _base_id('missing', key, extra)
                for e in st['events']:
                    if e.get('base') == base:
                        e['held'] = h['n']
        cur[key] = _base_id('missing', key, f'held|{born}|{h["n"]}')
    for key, h in holds.items():
        if key not in found:
            h['live'] = False
    for e in st['events']:
        if _is_hold(e) and e.get('status') == 'pending' and cur.get(e['key']) != e.get('base'):
            e['status'], e['closed'] = 'cancelled', now.isoformat()
    cutoff = today - KEEP_SENT
    for key in [k for k in holds if date.fromisoformat(k.rsplit(':', 1)[1]) < cutoff]:
        del holds[key]
    st[HOLD_SHIP] = [e['id'] for e in st['events']
                     if _is_hold(e) and e.get('status') == 'pending' and cur.get(e['key']) == e.get('base')]


def _closed_at(e):
    """끝난 사건을 언제부터 60일 세나 — 만든 때가 아니라 전송 성공·영구 실패를 확인한 때(Worker 이력도 60일)."""
    try:
        return max(datetime.fromisoformat(e['created']), datetime.fromisoformat(e.get('sent') or e.get('closed')
                                                                                 or e['created']))
    except (TypeError, ValueError):
        return datetime.fromisoformat(e['created'])


# ── outbox(GitHub → Worker) ───────────────────────────────────────────────

def clean_pairs(events):
    """Worker 응답의 `events` → {(id, hash)}. 형식이 하나라도 다르면 None(못 읽은 것으로 — 아무것도 빼지 않는다)."""
    if not isinstance(events, list):
        return None
    out = set()
    for x in events:
        if not (isinstance(x, dict) and isinstance(x.get('id'), str) and isinstance(x.get('hash'), str)
                and _ID.match(x['id']) and _HASH.match(x['hash'])):
            return None
        out.add((x['id'], x['hash']))
    return out


def apply_acks(st, acked, failed, now):
    """outbox 에서 빼는 유일한 길. acked·failed 는 (id, 보낸 본문 해시) 집합, None = 못 읽음(그쪽으로는 아무것도 빼지 않는다).

    **id 와 해시가 둘 다 지금 사건과 맞을 때만** 뺀다(codex 구현 1회 #3). Worker 가 같은 id 의 옛 본문 A 를 보냈고
    지금 상태의 본문이 B 라면, B 는 전송된 적이 없다 — id 만 보고 빼면 B 가 조용히 사라진다. 그런 사건은 pending 으로
    남는다(Worker 가 같은 id·다른 본문을 거부·경보한다). 해시는 저장해 둔 값이 아니라 지금 문장에서 다시 계산한다.
    뺀 사건은 상태에 남긴다 — 60일 안에 같은 사건이 다시 계산돼도 `add_event` 가 새로 만들지 않는다."""
    n = 0
    for e in pending(st):
        pair = (e['id'], text_hash(e['text']))
        if acked is not None and pair in acked:
            e['status'], e['sent'] = 'sent', now.isoformat()
        elif failed is not None and pair in failed:
            e['status'], e['closed'] = 'failed', now.isoformat()
        else:
            continue
        n += 1
    if acked is not None and failed is not None:
        st['send_fail'] = 0
    return n


def _out(e):
    return {'id': e['id'], 'hash': text_hash(e['text']), 'key': e['key'], 'kind': e['kind'], 'text': e['text'],
            'created': e['created']}


def dumps_outbox(doc):
    return json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True) + '\n'


def build_outbox(st, now):
    """pending 사건을 계약 §1 모양으로. 상한을 넘으면 **자르지 않고 남겨 둔다**: 너무 긴 사건은 `oversize` 로 상태에만,
    양이 넘은 사건은 pending 그대로(앞의 것이 빠지면 다음 실행에 실린다) — 그리고 `sys:overflow` 하나로 알린다.

    글 막힘 사건은 이번 실행이 살아 있다고 확인한 것(HOLD_SHIP)만, **기존 사건을 다 실은 뒤 남은 자리에** 싣는다 —
    기존 사건의 계산은 막힘이 없을 때와 한 바이트도 다르지 않다. 막힘 때문에 생기는 넘침 알림도 남은 자리에 들어갈 때만
    만든다(설계 §13-8·§14-3)."""
    ship = set(st.get(HOLD_SHIP) or ())
    bad = bad_hold = None
    for e in pending(st):
        if not (1 <= len(e['text']) <= MAX_TEXT and 1 <= len(e['key']) <= MAX_KEY):
            e['status'] = 'oversize'
            if _is_hold(e):
                bad_hold = bad_hold or e
            else:
                bad = bad or e

    def doc(events):
        return {'format': OUTBOX_FORMAT, 'generated_at': now.isoformat(), 'last_ok': st.get('last_ok'),
                'last_seen': st.get('last_seen'), 'events': [_out(e) for e in events]}

    def fits(out):
        return len(out['events']) <= MAX_EVENTS and len(dumps_outbox(out).encode('utf-8')) <= MAX_BYTES

    over = [e for e in pending(st) if e['key'] == OVERFLOW_KEY and not _hold_notice(e)]
    cand = [e for e in pending(st) if e['key'] != OVERFLOW_KEY and not _is_hold(e)]
    hcand = [e for e in pending(st) if _is_hold(e) and e['id'] in ship]
    # 넘침 알림이 들어갈 자리를 먼저 잡고 잰다 — 그 알림의 id 는 「처음 남겨진 사건」에서 나오므로 몇 건이 실리는지 정해진 뒤에 만든다
    spare = {'id': '0' * 32, 'hash': text_hash(OVERFLOW_TEXT), 'key': OVERFLOW_KEY, 'kind': OVERFLOW_KIND,
             'text': OVERFLOW_TEXT, 'created': now.isoformat()}
    n = len(cand)
    while True:
        new = (bool(bad) or n < len(cand)) and not over      # 한 번에 하나만 — 앞의 넘침 알림이 아직 안 나갔으면 더 만들지 않는다
        out = doc(over + cand[:n])
        out['events'] += [spare] if new else []
        if fits(out) or n == 0:
            break
        n -= 1
    if new:
        add_event(st, OVERFLOW_KIND, OVERFLOW_KEY, OVERFLOW_TEXT, now, extra=(bad or cand[n])['id'])
    chosen = {e['id'] for e in cand[:n]}
    hchosen = set()
    hover = [e for e in pending(st) if _hold_notice(e)]
    if n == len(cand) and (hcand or bad_hold or hover):      # 기존 사건이 다 실렸을 때만 — 남은 자리에
        over = [e for e in pending(st) if e['key'] == OVERFLOW_KEY and not _hold_notice(e)]
        head = over + cand
        if not fits(doc(head + hover)):
            hover = []                                       # 앞서 만든 막힘 넘침 알림도 자리가 없으면 다음에
            hcand = []
        m = len(hcand)
        while True:
            hnew = (bool(bad_hold) or m < len(hcand)) and not over and not hover
            out = doc(head + hover + hcand[:m])
            out['events'] += [spare] if hnew else []
            if fits(out):
                break
            if m == 0:
                hnew = False                                 # 넘침 알림 자리도 없다 — 기존 사건을 밀어내지 않는다
                break
            m -= 1
        if hnew:
            eid = add_event(st, OVERFLOW_KIND, OVERFLOW_KEY, OVERFLOW_TEXT, now, extra=(bad_hold or hcand[m])['id'])
            for e in st['events']:
                if eid and e['id'] == eid:
                    e['held_overflow'] = True
                    hover = [e]
        hchosen = {e['id'] for e in hover + hcand[:m]}
    first = [e for e in st['events'] if e.get('status') == 'pending' and not _is_hold(e) and not _hold_notice(e)
             and (e['id'] in chosen or e['key'] == OVERFLOW_KEY)]
    return doc(first + [e for e in st['events'] if e.get('status') == 'pending' and e['id'] in hchosen])


# ── 2단계의 맥 전송(지금 진입점은 쓰지 않는다) ─────────────────────────────

def deliver(st, send, save, now):
    """pending 을 차례로 보낸다. 한 건이 실패하면 거기서 멈춘다(순서 유지) — 다음 회차에 같은 식별자로 다시."""
    for e in pending(st):
        e['attempted'] = True        # 보내려 한 사실을 먼저 남긴다 — 이 뒤로는 텔레그램이 받았을 수 있다(#3)
        save(st)
        try:
            send(f'{e["text"]}\n#{e["id"]}')
        except Exception as exc:     # noqa: BLE001 — 시간 초과(TimeoutExpired) 등도 실패로 센다(codex 구현 검토 #10)
            e['tries'] = e.get('tries', 0) + 1
            e['last_error'] = str(exc)[:160]
            st['send_fail'] = st.get('send_fail', 0) + 1
            save(st)
            return False
        e['status'], e['sent'] = 'sent', now.isoformat()
        st['send_fail'] = 0
        save(st)                    # 여기서 실패하면 다음 회차에 다시 보낸다 — 중복 가능(상태 파일이 살아 있는 한 다시 보낸다)
    return True


# ── 매일 요약이 읽는 스냅샷 ───────────────────────────────────────────────

def summary_lines(path, now):
    """매일 요약 꼬리 — 읽기만 한다. 못 읽으면 「미발행 없음」이 아니라 「조회 실패」."""
    try:
        st = load_state(path)
    except StateError:
        return ['발행 알림: 상태를 못 읽었어요(상태 파일을 읽지 못했거나 내용 검증 실패) — 미발행·전송 여부를 몰라요']
    if st is None:
        return ['발행 알림: 아직 실행 기록이 없어요']
    try:
        return summary_lines_from(st, now)
    except Exception as exc:  # noqa: BLE001 — 발행 알림 상태가 이상해도 매일 요약은 나가야 한다(#6)
        # 원문은 싣지 않는다 — 예외 종류 이름만(맥 요약 계약)
        return [f'발행 알림: 상태를 못 읽었어요(상태 파일 내용 형식 오류: {type(exc).__name__}) — 미발행·전송 여부를 몰라요']


def _fetch_kind(why):
    """요약 꼬리용 고정 분류 — git 오류 원문은 싣지 않는다(맥 요약 계약, codex 재검토 #2)."""
    if not why:
        return None
    if str(why).startswith('git fetch 실패'):
        return 'git fetch 실패'
    if str(why).startswith('읽기 실패'):
        return '레포를 읽지 못함(git 읽기 오류)'
    return '기타 실패'


_SESSION_KEY = re.compile(r'(us|kr):(\d{4}-\d{2}-\d{2})')


def _key_label(key):
    """사건 key → 사람이 읽는 이름. 알려진 모양(글 경로·세션·sys)만 — 나머지는 고정 문구(codex 재검토 4회 #3)."""
    if V.target_of(key):
        return _short(key)
    m = _SESSION_KEY.fullmatch(str(key))
    if m:
        return f'{_label(m.group(1), m.group(2))} 세션'
    m = _HOLD_KEY.fullmatch(str(key))
    if m and _real_date(m.group(2)):
        return f'{_label(m.group(1), m.group(2))} 글 막힘'
    return '시스템 알림' if str(key).startswith('sys:') else '알 수 없는 항목'


def summary_lines_from(st, now, stale=FETCH_STALE):
    """st = 계산 상태(맥 로컬 파일이든 `origin/alerts-state:verify_publish.json` 이든). GitHub 상태를 넘길 때는
    `stale=GITHUB_STALE` — 3시간 심장 박동이라 2시간 기준이면 매일 「n시간 전」이 뜬다."""
    out = []
    ok = st.get('last_ok')
    if not ok:
        out.append('발행 알림: 아직 정상 확인이 한 번도 없어요')
    else:
        gap = now - datetime.fromisoformat(ok)
        if gap > stale:
            why = _fetch_kind((st.get('fetch') or {}).get('why'))
            out.append(f'발행 알림: 마지막 정상 확인이 {int(gap.total_seconds() // 3600)}시간 전이에요 — 그 뒤 사건은 못 봤어요'
                       + (f'(마지막 실패: {why})' if why else '(그 뒤 실패 기록이 없어요 — 계산이 돌지 않았을 수 있어요)'))
    open_ = sorted(k for k, s in st['sessions'].items() if s in ('missing', 'missing_quiet'))
    if open_:
        out.append('아직 안 올라온 세션: ' + ', '.join(_label(*k.split(':', 1)) for k in open_[:6]))
    gone = sorted(k for k, s in st['sessions'].items() if s == 'gone')
    if gone:
        out.append('올라갔다가 지금 없는 세션: ' + ', '.join(_label(*k.split(':', 1)) for k in gone[:6]))
    if st['calendar']:
        why = st.get('calendar_why') or {}
        def reason(m):
            w = why.get(m)
            if m not in V.LABEL:                       # us·kr 밖의 코드로 문장을 만들지 않는다(codex 재검토 4회 #2)
                return '기타 사유'
            return '이유 기록 없음' if not w else w if w in _holiday_reasons(m) else '기타 사유'
        out.append('휴장 달력을 못 읽어 미발행 판정을 멈춘 시장: ' + ', '.join(
            f'{V.LABEL.get(m, "모르는 시장")}({reason(m)})' for m in sorted(st['calendar'])))
    pend = pending(st)
    if pend:
        names = ', '.join(_key_label(e['key']) for e in pend[:3]) + (f' 외 {len(pend) - 3}건' if len(pend) > 3 else '')
        # GitHub 모드에서 send_fail 은 늘 0 이다(전송은 Worker 몫) — 맥 모드에서만 연속 실패를 적는다
        tail = f', 연속 실패 {st["send_fail"]}회' if st.get('send_fail') else ''
        out.append(f'발행 알림 미전송 {len(pend)}건({names}{tail}) — 전송 결과는 Worker 쪽 줄을 보세요')
    return out
