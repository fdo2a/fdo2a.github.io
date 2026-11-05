"""검토 큐 만료 — 러너가 닿지 않는 오래된 신규 발행본은 미검토로 세지 않는다.

러너(`runner.eligible`)는 발행 1일(US·KR)·MAX_AGE(주간·일본) 안만 읽고 news 는 아예 읽지
않는다. 기한을 넘긴 「신규」는 영원히 큐에 남아, 훅이 매 세션 보여 주는 개수가 실제로 볼
것을 가렸다(2026-11-06 실측 34건). 사용자 결정 「오래된 건 편입 + 규칙」.

**원장은 쓰지 않는다.** `review_gate.py pending` 의 출력 단계에서만 가른다 — 분류·러너·
`refresh` 는 그대로다(codex 설계 검토 #5). 만료 항목도 목록으로 남겨 손으로 읽을 수 있다.

나이는 파일명 날짜가 아니라 **현재 판이 공개된 날**로 잰다. 미검토인 채로 고치거나 재발행한
판은 그날부터 다시 센다(#1·#2), 주간·일본은 키보다 늦게 나온다(#3). 다음은 만료하지 않는다:
「신규」가 아닌 것, 공개판과 sha 가 다른 판(작업 폴더에만 있음), 공개일을 못 구한 판,
sha 가 맞는 초안이 있는 판(#4), 명시하지 않은 섹션·형식(#6), 미래 날짜.

설계: ../plan.md 2026-11-06 「검토 큐 만료 규칙」.
"""
import re
from datetime import date

# 섹션 → (파일명 형식, 기한 일수). 오늘 − 공개일 > 기한이면 만료.
_DAY = re.compile(r'\d{4}-\d{2}-\d{2}\.html')
_WEEK = re.compile(r'(\d{4})-W(\d{2})\.html')
DEADLINE = {
    'us': (_DAY, 3), 'kr': (_DAY, 3), 'news': (_DAY, 3),
    'japan/daily': (_DAY, 4),
    'weekly': (_WEEK, 7), 'kr/weekly': (_WEEK, 7), 'japan/posts': (_WEEK, 7),
}


def _key_day(path, pattern):
    """파일명이 가리키는 날(주간은 그 주 월요일). 형식이 틀리면 None."""
    name = path.rsplit('/', 1)[-1]
    m = pattern.fullmatch(name)
    if not m:
        return None
    try:
        if pattern is _DAY:
            return date.fromisoformat(name[:10])
        return date.fromisocalendar(int(m.group(1)), int(m.group(2)), 1)
    except ValueError:
        return None


def is_expired(item, *, today, published, published_on, has_draft):
    """`published_on(path, sha) -> date | None` — 그 판이 공개된 날(KST)."""
    if item.reason != '신규':
        return False
    rule = DEADLINE.get(item.section)
    key = _key_day(item.path, rule[0]) if rule else None
    if key is None or key > today:
        return False                          # 형식 오류·미래 키(codex 구현 검토 #3)
    if published.get(item.path) != item.sha:
        return False
    if has_draft(item):
        return False
    when = published_on(item.path, item.sha)
    if not isinstance(when, date) or when > today:
        return False
    return (today - when).days > rule[1]


def split(queue, **kw):
    """(남길 것, 만료) — 순서는 그대로."""
    keep, gone = [], []
    for it in queue:
        (gone if is_expired(it, **kw) else keep).append(it)
    return keep, gone
