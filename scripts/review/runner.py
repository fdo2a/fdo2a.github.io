"""로컬 검토 러너의 순수 로직 — 무엇을 읽을지 고르고, 한도를 예약하고, 초안을 받을지 정한다.

git·codex·파일 I/O 는 `review_gate.py` 의 `cmd_run` 이 한다. 여기 있는 것은 전부 인자만
보고 답이 나오는 함수라 테스트가 프로세스를 안 띄운다.

설계: docs/superpowers/specs/2026-09-10-local-review-runner-design.md
"""

import re
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .queue import _DATE

# 러너가 미리 읽어 두는 섹션. 나머지는 사람이 기존 수동 경로로 처리한다 — 게이트의 감시
# 범위를 좁히는 게 아니라, 자동으로 앞당겨 읽는 대상만 좁힌다.
SECTIONS = ('us', 'kr')

# 섹션당 하루 호출 수. 구독 한도를 사람이 세션에서 쓰는 codex 와 나눠 쓴다 — 2026-09-10
# 이 설계의 검토 한 번이 한도를 태웠다.
#
# 1 편이면 지연이 상시 하루로 굳는다(사용자 지시 2026-09-10 로 2 편). 자정~발행 시각
# 사이의 tick 이 어제 글로 할당량을 태우면, 몇 시간 뒤 올라오는 그날 글은 다음 날로
# 밀린다. 2 편이면 그 두 편이 같은 날 안에 들어온다.
DAILY_CAP = 2

# 이보다 오래된 글은 자동 대상이 아니다. 러너의 목적은 새 글의 지연을 없애는 것이고,
# 밀린 백로그는 큐에 남아 사람이 읽는다.
#
# **1 이어야 상한 2 가 제 일을 한다.** 2 였을 때는 자정 tick 에서 어제·그제 글이 두 칸을
# 모두 먹어, 몇 시간 뒤 올라오는 그날 글이 다시 다음 날로 밀렸다 — 상한만 올려서는 그
# 지연이 안 없어진다(2026-09-10 codex 검토가 재현). 1 이면 자동 대상이 「어제분과 그날분」
# 둘로 좁혀져 상한 2 와 정확히 맞는다.
MAX_AGE_DAYS = 1

# 공급자(ChatGPT) 한도로 실패한 호출은 **우리 예산을 쓴 게 아니다** — 2026-09-19 에
# 그 실패 두 번이 하루 두 칸을 다 태웠고 초안은 0 건이었다. 그래서 되돌린다.
#
# 그렇다고 무조건 되돌리면 `calls` 가 실제 호출 수가 아니게 되고 하루 상한이 사라진다.
# 한도 실패로 되돌릴 수 있는 횟수를 **따로 세서** 그 구멍을 막는다. 매시 tick 이므로
# 4 회면 반나절이고, 넘으면 그날은 소진으로 둔다.
LIMIT_RETRY_CAP = 4

# `blocked_until` 이 이보다 먼 미래면 버린다. 구문만 맞는 「9999 년」이 들어오면
# 러너가 영영 안 돈다 — 파싱 실수 하나가 영구 정지가 되면 안 된다.
#
# **24 이어야 실측 메시지가 통과한다.** 2026-09-19 23:00 의 실패는 「try again at
# 7:47 PM」이었고, 그건 다음 날 19:47 = 20 시간 뒤다. 12 로 잡았을 때는 이 정상적인
# 대기를 「이상한 값」으로 버렸다. 파싱이 틀려도 최악이 하루 쉬는 것이고, 훅이 그동안
# 「codex 대기 — 시각」을 계속 보여준다.
BLOCK_HORIZON_HOURS = 24

# 같은 발행본의 자동 정정이 이만큼 실패하면 멈추고 사람에게 넘긴다. 세 번 같은 자리에서
# 실패한다는 건 대개 고칠 대상이 본문이 아니라 게이트나 계약이라는 뜻이다.
# **날짜로 초기화되지 않는다** — 하루 상한과 달리 이건 누적이어야 의미가 있다.
ROUND_CAP = 3

# codex CLI 자체가 내는 한도 오류. **줄 머리**에서만 인정한다 — 검토 대상 글이나 codex
# 요약이 이 문구를 인용해도 문장 중간이므로 걸리지 않는다. 애매하면 반납하지 않는다.
_LIMIT_LINE = re.compile(
    r'^\s*(?:ERROR:\s*)?(?:You\W?ve|You have)\s+hit\s+your\s+usage\s+limit',
    re.IGNORECASE)

# 「try again at 7:47 PM」(실측 형태) 과 「try again in 2 hours 34 minutes」 둘 다 받는다.
_RETRY_AT = re.compile(
    r'try\s+again\s+at\s+(\d{1,2}):(\d{2})\s*(AM|PM)?', re.IGNORECASE)
_RETRY_IN = re.compile(
    r'try\s+again\s+in\s+(?:(\d+)\s*hours?)?\s*(?:(\d+)\s*minutes?)?',
    re.IGNORECASE)

KST = timezone(timedelta(hours=9))


def today_kst(now=None):
    """실행일. 루틴도 발행도 KST 기준이라 한도도 같은 날짜로 가른다."""
    return (now or datetime.now(KST)).astimezone(KST).date().isoformat()


def _dated(path):
    found = _DATE.search(path.rsplit('/', 1)[-1])
    if not found or len(found.group(1)) != 10:
        return None
    try:
        return date.fromisoformat(found.group(1))
    except ValueError:
        return None


def used(state, day, section):
    calls = state.get('calls') if isinstance(state, dict) else None
    if not isinstance(calls, dict):
        return 0
    got = calls.get(day)
    if not isinstance(got, dict):
        return 0
    n = got.get(section)
    return n if isinstance(n, int) and n > 0 else 0


def eligible(queue, published, state, day, have=(), sections=SECTIONS, cap=DAILY_CAP,
             max_age_days=MAX_AGE_DAYS):
    """자동으로 읽을 항목 — 섹션·공개판 일치·신선도·한도를 전부 통과한 것만.

    `published` 는 **고정한 origin 커밋의 트리**다. 큐 항목의 SHA 가 그 트리의 것과 같을
    때만 대상이 된다. 작업 폴더에만 있는 판(손편집분, 아직 push 안 한 것)은 지금 공개돼
    있는 글이 아니므로 사람에게 남긴다 — 러너가 그걸 읽으면 독자가 안 보는 판에 한도를
    쓰고, 결과 파일은 공개판 것인 양 남는다.

    `have` 는 이미 놓인 초안 파일 이름들이다. **날짜가 바뀌면 한도가 새로 열리므로**,
    이걸 안 보면 자정 직후 어제 글을 다시 읽고 그날 할당량을 태운다 — 그리고 몇 시간 뒤
    올라오는 그날 글은 한도가 없어 못 읽는다.

    큐는 최신 순이라 섹션마다 앞에서부터 채우면 그날 것이 먼저 잡힌다.
    """
    limit = (date.fromisoformat(day) - timedelta(days=max_age_days)
             if max_age_days is not None else None)
    left = {s: max(0, cap - used(state, day, s)) for s in sections}
    have = set(have)
    picked = []
    for item in queue:
        if left.get(item.section, 0) <= 0:
            continue
        if published.get(item.path) != item.sha:
            continue
        if draft_name(item) in have:
            continue
        when = _dated(item.path)
        if when is None or (limit is not None and when < limit):
            continue
        picked.append(item)
        left[item.section] -= 1
    return picked


def reserve(state, day, section):
    """호출 **전에** 한 칸 쓴다. 성공만 세면 한도를 태우고 실패한 호출이 매시 되풀이된다.

    망가진 `calls` 를 만나면 버리고 새로 센다. `used()` 는 이미 그렇게 읽으므로 여기서
    예외가 나면 두 함수가 같은 상태를 서로 다르게 보는 것이고, 러너는 그 자리에서 죽는다.
    """
    got = state.get('calls')
    calls = dict(got) if isinstance(got, dict) else {}
    slot = calls.get(day)
    slot = dict(slot) if isinstance(slot, dict) else {}
    slot[section] = used(state, day, section) + 1
    calls[day] = slot
    return {**state, 'calls': _prune({d: v for d, v in calls.items()
                                      if _is_day(d)}, day)}


def _is_day(text):
    try:
        date.fromisoformat(text)
        return True
    except (TypeError, ValueError):
        return False


def _prune(calls, day, keep=7):
    """오래된 날짜는 버린다. 상태 파일이 heartbeat 이므로 무한히 자라면 안 된다."""
    floor = (date.fromisoformat(day) - timedelta(days=keep)).isoformat()
    return {d: v for d, v in calls.items() if d >= floor}


def draft_name(item):
    """`<날짜>-<섹션>-<sha7>.md`. 파일명이 「어느 판을 읽었나」를 들고 있어야, 사람이
    정정할 때 현재 큐 SHA 와 대조해 낡은 초안을 버릴 수 있다."""
    when = _dated(item.path)
    stamp = when.isoformat() if when else 'undated'
    return f'{stamp}-{item.section.replace("/", "_")}-{item.sha[:7]}.md'


def accept_draft(returncode, text, sha_now, sha_want):
    """초안을 최종 이름으로 확정해도 되는가 — (된다, 안 되면 이유).

    셋 다 통과해야 한다. 하나라도 놓치면 빈 파일이나 잘린 파일이 최종 이름으로 남고,
    다음 tick 은 「파일이 있다」는 이유로 그 글을 건너뛴다. 2026-09-10 실측이 그 모양이다 —
    이 설계의 1차 codex 검토가 한도로 끊겨 지적 목록 없이 토큰만 태웠다.
    """
    if returncode != 0:
        return False, f'codex 종료 코드 {returncode}'
    if not (text or '').strip():
        return False, '출력이 비어 있다'
    if sha_now != sha_want:
        return False, f'읽는 사이 글이 바뀌었다 ({sha_want[:7]} → {sha_now[:7]})'
    return True, None


# ── 실패의 종류 ────────────────────────────────────────────────────────────────
# 셋(PASS/FAIL/BLOCK)으로 시작했다가 부족해진 남의 사례를 따랐다 — 「판정 불가」한 칸이
# 못 읽음·한도·재발행을 다 흡수하면, 훅을 보고도 다음에 뭘 해야 할지 알 수 없다.
LIMIT = '한도'          # 공급자 사용량 한도. 예산을 되돌리고 나중에 다시 부른다
TIMEOUT = '타임아웃'     # 우리 제한 시간 안에 안 끝났다
RESHIPPED = '재발행됨'   # 읽는 사이 공개판이 바뀌었다 — 다음 tick 이 새 판을 읽는다
UNKNOWN = '판정불가'     # 나머지 전부. 사람이 봐야 한다
HUMAN = '사람검토'       # 자동 정정을 ROUND_CAP 회 실패했다 — 더 고치지 않는다


def is_limit_error(returncode, stdout, stderr):
    """이 실패가 공급자 사용량 한도인가.

    분류에는 **자르지 않은** 출력을 쓴다. `review_one` 이 훅에 남기는 이유 문자열은
    200 자로 잘리므로 그걸로 판정하면 긴 메시지에서 문구를 놓친다.

    stderr 가 있으면 stderr 만 본다 — CLI 자체 오류가 나오는 자리다. stdout 은 검토
    대상 글과 codex 요약이 섞이는 자리라, 줄 머리에서만 인정한다. 본문이 이 문구를
    인용하면 문장 중간이므로 걸리지 않고, **애매하면 한도가 아니라고 답한다** —
    잘못 반납하면 하루 상한이 사라지지만, 잘못 안 반납하면 하루 늦어질 뿐이다.
    """
    if returncode == 0:
        return False
    where = stderr if (stderr or '').strip() else stdout
    return any(_LIMIT_LINE.match(line) for line in (where or '').splitlines())


def release(state, day, section):
    """`reserve` 의 역 — 한 칸 되돌린다. 0 밑으로는 안 내려간다.

    공급자 한도로 죽은 호출은 **우리 예산을 쓴 게 아니다.** 되돌리지 않으면 초안 0 건인
    채로 그날 자동 검토가 끝난다(2026-09-19 실측).
    """
    got = state.get('calls')
    calls = dict(got) if isinstance(got, dict) else {}
    slot = calls.get(day)
    slot = dict(slot) if isinstance(slot, dict) else {}
    left = used(state, day, section) - 1
    if left > 0:
        slot[section] = left
    else:
        slot.pop(section, None)
    if slot:
        calls[day] = slot
    else:
        calls.pop(day, None)
    return {**state, 'calls': {d: v for d, v in calls.items() if _is_day(d)}}


def limit_hits(state, day):
    got = state.get('limit_hits') if isinstance(state, dict) else None
    n = got.get(day) if isinstance(got, dict) else None
    return n if isinstance(n, int) and n > 0 else 0


def note_limit(state, day):
    """한도 실패를 센다. `calls` 와 따로 세야 「되돌려도 되는 횟수」에 바닥이 생긴다."""
    got = state.get('limit_hits')
    hits = dict(got) if isinstance(got, dict) else {}
    hits[day] = limit_hits(state, day) + 1
    return {**state, 'limit_hits': _prune({d: v for d, v in hits.items()
                                           if _is_day(d)}, day)}


def may_release(state, day):
    """아직 되돌려도 되는가. 넘으면 그날은 소진으로 둔다 — 상한이 사라지면 안 된다."""
    return limit_hits(state, day) < LIMIT_RETRY_CAP


def retry_at(text, now=None):
    """codex 가 알려준 재시도 시각을 **절대 시각 한 번으로** 굳힌다 — 없으면 None.

    받은 시점에 한 번만 계산한다. 저장된 상대시간을 매 tick 다시 재면 차단이 계속
    연장된다. 추측하지 않는다 — 문구가 없으면 None 이고, 그러면 다음 tick 이 그냥
    다시 부른다(한도가 아직이면 또 실패하지만 예산은 안 쓴다).
    """
    now = (now or datetime.now().astimezone())
    if now.tzinfo is None:
        now = now.astimezone()
    body = text or ''
    found = _RETRY_AT.search(body)
    if found:
        hour, minute, ampm = int(found.group(1)), int(found.group(2)), found.group(3)
        if minute > 59 or hour > 23 or (ampm and hour > 12):
            return None
        if ampm:
            hour = hour % 12 + (12 if ampm.upper() == 'PM' else 0)
        when = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if when <= now:                      # 이미 지난 시각이면 다음 날 같은 시각
            when += timedelta(days=1)
        return _horizon(when, now)
    found = _RETRY_IN.search(body)
    if found and (found.group(1) or found.group(2)):
        span = timedelta(hours=int(found.group(1) or 0),
                         minutes=int(found.group(2) or 0))
        return _horizon(now + span, now)
    return None


def _horizon(when, now):
    if when <= now or when - now > timedelta(hours=BLOCK_HORIZON_HOURS):
        return None
    return when.isoformat()


# Claude CLI 한도. codex 와 문구가 다르고, 주간 한도는 초기화가 며칠 뒤라 codex 의 24 시간
# 지평으로는 버려진다. 한도 거부는 0 초에 끝나 토큰을 안 쓰지만, 회차로 세면 멀쩡한 글이
# 세 번 만에 사람검토로 넘어간다(2026-09-24 posts/2026-09-22.html).
CLAUDE_BLOCK_HORIZON_HOURS = 24 * 8
_CLAUDE_LIMIT = re.compile(r"claude exited \d+: You\W?ve hit your [\w-]+ limit")
_CLAUDE_RESET = re.compile(
    r"resets\s+(?:(?P<mon>[A-Z][a-z]{2})\s+(?P<day>\d{1,2}),?\s+(?:at\s+)?)?"
    r"(?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s*(?P<ap>am|pm)\s*\((?P<tz>[^)]+)\)", re.I)
_MONTHS = ('jan', 'feb', 'mar', 'apr', 'may', 'jun',
           'jul', 'aug', 'sep', 'oct', 'nov', 'dec')


def is_claude_limit(why):
    """정정기의 Claude 호출이 계정 한도로 거부됐는가 — CLI 실패 줄의 머리에서만 인정한다."""
    return bool(_CLAUDE_LIMIT.search(why or ''))


def claude_retry_at(text, now=None):
    """Claude 가 알려 준 초기화 시각(절대 시각 ISO) — 못 읽으면 None."""
    found = _CLAUDE_RESET.search(text or '')
    if not found:
        return None
    try:
        zone = timezone.utc if found.group('tz').upper() == 'UTC' else ZoneInfo(found.group('tz'))
    except (ZoneInfoNotFoundError, ValueError):
        return None
    now = (now or datetime.now(timezone.utc)).astimezone(zone)
    hour, minute = int(found.group('h')), int(found.group('m') or 0)
    if hour > 12 or minute > 59:
        return None
    hour = hour % 12 + (12 if found.group('ap').lower() == 'pm' else 0)
    if found.group('mon'):
        mon = found.group('mon').lower()
        if mon not in _MONTHS:
            return None
        try:
            when = now.replace(month=_MONTHS.index(mon) + 1, day=int(found.group('day')),
                               hour=hour, minute=minute, second=0, microsecond=0)
        except ValueError:
            return None
        if when < now - timedelta(days=1):       # 12월에 받은 「Jan 2」
            when = when.replace(year=when.year + 1)
    else:
        when = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if when <= now:
            when += timedelta(days=1)
    if when <= now or when - now > timedelta(hours=CLAUDE_BLOCK_HORIZON_HOURS):
        return None
    return when.isoformat()


def blocked_until(state, now=None, key='blocked_until', horizon_hours=None):
    """차단이 아직 유효하면 그 시각, 아니면 None — 손상·과도한 미래는 전부 None.

    구문만 맞는 「9999 년」이 「미래면 참」을 통과해 러너를 영영 세우는 경로를 여기서
    막는다. tz 없는 값도 버린다 — 비교 기준이 기계마다 달라진다.
    """
    horizon_hours = horizon_hours or BLOCK_HORIZON_HOURS
    raw = state.get(key) if isinstance(state, dict) else None
    if not isinstance(raw, str) or not raw:
        return None
    try:
        when = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if when.tzinfo is None:
        return None
    now = now or datetime.now().astimezone()
    if when <= now or when - now > timedelta(hours=horizon_hours):
        return None
    return when


def rounds(state, path):
    got = state.get('rounds') if isinstance(state, dict) else None
    n = got.get(path) if isinstance(got, dict) else None
    return n if isinstance(n, int) and n > 0 else 0


def note_round(state, path):
    """같은 발행본의 자동 정정 실패를 누적한다. **날짜로 초기화되지 않는다.**"""
    got = state.get('rounds')
    seen = dict(got) if isinstance(got, dict) else {}
    seen[path] = rounds(state, path) + 1
    return {**state, 'rounds': seen}


def clear_rounds(state, path):
    """정정이 통과했으면 회차를 지운다. 안 지우면 다음 발행본이 남의 빚을 물려받는다."""
    got = state.get('rounds')
    if not isinstance(got, dict) or path not in got:
        return state
    return {**state, 'rounds': {k: v for k, v in got.items() if k != path}}


def stalled(state, path):
    """이 발행본은 자동 정정을 그만두고 사람에게 넘겨야 하는가."""
    return rounds(state, path) >= ROUND_CAP


# ── 오류 표시 ──────────────────────────────────────────────────────────────────
def err(kind, detail):
    return {'kind': kind, 'detail': detail}


def err_kind(value):
    """디스크의 옛 문자열도 읽는다 — 스키마를 바꿨다고 지난 상태가 못 읽히면 안 된다.

    **읽을 수 있는 것과 그걸 근거로 예산을 되돌리는 것은 다르다.** 반납은 이번 tick 의
    분류로만 하고, 여기서 복원한 kind 는 표시에만 쓴다.
    """
    if isinstance(value, dict):
        kind = value.get('kind')
        return kind if isinstance(kind, str) and kind else UNKNOWN
    return UNKNOWN


def err_detail(value):
    if isinstance(value, dict):
        detail = value.get('detail')
        return detail if isinstance(detail, str) else str(value)
    return value if isinstance(value, str) else str(value)


def err_line(where, value):
    """훅과 콘솔이 같은 문장을 쓰게 한다. 두 벌이면 한쪽만 고치고 끝난다."""
    return f'{where} [{err_kind(value)}] {err_detail(value)}'
