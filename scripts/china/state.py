"""승계되는 책 — 무엇을 배웠고, 다음에 무엇을 되짚을 것인가.

브리프의 stance.json·thesis_state.json 과 같은 자리이지만 지키는 것이 다르다. 저쪽은
「어제의 판단이 오늘 하루 만에 뒤집히지 않게」이고, 여기는 **「배운 것을 다시 쓰게」** 다.
되짚기가 없으면 학습이 아니라 열람이다.

세 가지가 순수 함수로 박혀 있다.

1. **되짚기 대상은 writer 가 고르지 않는다.** `revisit_target()` 이 «가장 오래 안 본
   강의»를 결정론적으로 지목한다. 고르게 두면 쉬운 것을 고른다.
2. **배열 회전을 쓰지 않는다.** 큐를 뒤로 미는 방식은 A01 을 되짚은 주에 A02 가 추가되면
   다음 주도 A01 이 선두가 된다(codex C2). 강의마다 `last_reviewed_week` 을 두고
   `(안 본 것 먼저, 오래 본 것 먼저, 완료가 이른 것 먼저, id)` 로 가른다.
3. **`advance()` 는 순수하고 멱등하다.** 입력 state 를 건드리지 않고, 같은 주로 두 번
   불러도 같은 결과다. 게이트·커밋·push 어디서 실패하든 상태만 앞서 나가지 않게 하려면
   전이가 «계산»이어야 하고, 기록은 전부 통과한 뒤 한 번에 이뤄져야 한다.

`state_hash()` 는 발행 직전 CAS 용이다 — 읽은 판이 그대로인지 커밋 전에 다시 본다.

Design: docs/superpowers/specs/2026-09-05-china-learning-report-design.md
"""

import copy
import hashlib
import json
import re
from datetime import date


class StateError(ValueError):
    """상태 전이가 규율을 어겼다."""


def week_key(day):
    """`YYYY-Www` — **ISO week-year** 를 쓴다.

    달력 연도를 쓰면 12월 말·1월 초에 키가 어긋난다. 2027-01-01 은 ISO 로 2026-W53 이다.
    state·URL·멱등 키가 전부 이 함수 하나를 지난다.
    """
    if isinstance(day, str):
        day = date.fromisoformat(day)
    iso = day.isocalendar()
    return f'{iso.year}-W{iso.week:02d}'


# `$` 는 끝의 개행을 받고 `\d` 는 전각 숫자까지 받는다 — 둘 다 원장에 다른 키를
# 남기면서 형식 검사를 통과한다. `\A…\Z` 와 ASCII 자릿수로 못 박는다.
_WEEK_RE = re.compile(r'\A([0-9]{4})-W([0-9]{2})\Z')


def valid_week(week):
    """`YYYY-Www` 이면서 실재하는 주차인가. 형식만 보면 `2026-W99` 가 통과한다."""
    m = _WEEK_RE.match(week or '')
    if not m:
        return False
    year, wk = int(m.group(1)), int(m.group(2))
    if not 1 <= wk <= 53:
        return False
    try:
        date.fromisocalendar(year, wk, 1)
    except ValueError:
        return False
    return True


def state_hash(state):
    """키 순서에 흔들리지 않는 내용 해시."""
    blob = json.dumps(state, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    return hashlib.sha256(blob.encode('utf-8')).hexdigest()


def completed_ids(state):
    return [c['id'] for c in state.get('completed', [])]


def claim_ids(state, lesson_id):
    for c in state.get('completed', []):
        if c['id'] == lesson_id:
            return [x['claim_id'] for x in c.get('claims', [])]
    return []


def _sort_key(entry):
    """안 본 것 먼저 → 오래 본 것 먼저 → 완료가 이른 것 먼저 → id."""
    reviewed = entry.get('last_reviewed_week')
    return (reviewed is not None, reviewed or '', entry.get('week') or '', entry['id'])


def revisit_target(state):
    """이번 편이 되짚어야 할 강의 id. 완료가 없으면 None(첫 발행 면제)."""
    done = state.get('completed') or []
    if not done:
        return None
    return min(done, key=_sort_key)['id']


def _validate_claims(claims):
    if not claims:
        raise StateError('claims 가 비었다 — 강의는 검증 가능한 명제를 하나 이상 남긴다')
    seen = set()
    for c in claims:
        if not isinstance(c, dict) or 'claim_id' not in c or 'text' not in c:
            raise StateError('claims 항목은 claim_id·text 를 가진 객체여야 한다 — '
                             '자유 산문은 되짚기가 기계적으로 겨눌 수 없다')
        if c['claim_id'] in seen:
            raise StateError(f'claim_id 중복: {c["claim_id"]}')
        seen.add(c['claim_id'])


def advance(state, *, lesson, week, revisited, claims, url=None):
    """다음 상태를 «계산»한다. 입력을 건드리지 않고, 같은 주로 두 번 불러도 같다."""
    _validate_claims(claims)
    if not valid_week(week):
        raise StateError(f'주차 키가 아니다: {week!r} (YYYY-Www)')

    done = list(state.get('completed') or [])
    ids = [c['id'] for c in done]

    # 멱등: 같은 주에 같은 강의가 이미 기록돼 있으면 그대로 돌려준다. 재실행이 진도를
    # 두 칸 밀지 않게 하는 유일한 방어선이다.
    for c in done:
        if c['id'] == lesson and c.get('week') == week:
            return copy.deepcopy(state)

    if lesson in ids:
        raise StateError(f'{lesson} 은 이미 완료된 강의다 — 재탕은 진도가 아니다')

    last = state.get('last_published_week')
    if last is not None and week < last:
        raise StateError(f'주차가 뒤로 간다: {last} → {week}')
    # 한 주에 두 강의를 실으면 진도가 두 칸 밀린다. 멱등 분기는 위에서 이미 걸렀으므로
    # 여기 걸리는 것은 «같은 주, 다른 강의» 뿐이다.
    if last is not None and week == last:
        raise StateError(f'같은 주에 두 강의를 발행할 수 없다: {last}')

    if revisited is not None:
        if revisited == lesson:
            raise StateError('되짚기 대상이 이번 강의와 같다 — 되짚기는 과거를 본다')
        if revisited not in ids:
            raise StateError(f'되짚기 대상 {revisited} 이 완료 목록에 없다')
        # 지면은 게이트가 보지만 상태 전이도 같은 규율을 지킨다 — 둘이 갈리면 원장과
        # 발행본이 다른 강의를 되짚은 것으로 남는다.
        target = revisit_target(state)
        if revisited != target:
            raise StateError(f'큐가 지목한 되짚기 대상은 {target} 인데 {revisited} 을 썼다')
    elif done:
        raise StateError('되짚기 대상이 없다 — 완료 강의가 있으면 하나를 되짚는다')

    nxt = copy.deepcopy(state)
    nxt['completed'] = [
        {**c, 'last_reviewed_week': week} if c['id'] == revisited else copy.deepcopy(c)
        for c in done
    ]
    nxt['completed'].append({
        'id': lesson,
        'week': week,
        'url': url or f'/china/posts/{week}.html',
        'last_reviewed_week': None,
        'claims': copy.deepcopy(claims),
    })
    nxt['last_published_week'] = week
    nxt['updated'] = week
    return nxt
