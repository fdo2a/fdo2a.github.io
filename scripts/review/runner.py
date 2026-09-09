"""로컬 검토 러너의 순수 로직 — 무엇을 읽을지 고르고, 한도를 예약하고, 초안을 받을지 정한다.

git·codex·파일 I/O 는 `review_gate.py` 의 `cmd_run` 이 한다. 여기 있는 것은 전부 인자만
보고 답이 나오는 함수라 테스트가 프로세스를 안 띄운다.

설계: docs/superpowers/specs/2026-09-10-local-review-runner-design.md
"""

from datetime import date, datetime, timedelta, timezone

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
    limit = date.fromisoformat(day) - timedelta(days=max_age_days)
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
        if when is None or when < limit:
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
