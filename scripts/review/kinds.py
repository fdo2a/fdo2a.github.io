"""글 종류 표 — 러너와 문체 단계가 같은 표를 본다 (2026-10-01).

일간(us·kr) 말고도 주간·일본 주간이 발행 뒤 codex 문체 수정을 받는다(사용자 지시
「주간, 월간, 일본 보고서도 codex가 검토하도록 해」; 월간은 2026-10-27 폐지). 이 글들은 파일명이 날짜가 아니라
주 키라서, 키에서 발행일을 정하고(주간 토요일, 일본 일요일) 발행 커밋에서
꺼낼 근거 파일을 정한다. 사실 정정(Claude)은 여전히 일간만이다 — `DAILY`.

설계: docs/superpowers/specs/2026-10-01-period-codex-style-pass.md
"""
import re
from datetime import date

DAILY = ('us', 'kr')
# 섹션 → (시장, 주기). 섹션 이름은 queue.section_of 가 붙이는 디렉터리 이름이다.
PERIOD = {
    'weekly': ('us', 'weekly'),
    'kr/weekly': ('kr', 'weekly'),
    'japan/posts': ('jp', 'weekly'),
    # 일본 일간(2026-10-27) — 파일명이 날짜지만 자동 Claude 정정(`DAILY`)에는 넣지 않는다. codex 검토
    # 초안은 수동 review-gate 로 간다. 근거는 발행 스냅샷과 일간 뉴스 파일 둘로 자기완결이다.
    'japan/daily': ('jp', 'daily'),
}
SECTIONS = DAILY + tuple(PERIOD)
# 신선도(일). 주간은 토·일에 맥이 꺼져 있을 수 있다.
MAX_AGE = {'weekly': 3, 'kr/weekly': 3, 'japan/posts': 3, 'japan/daily': 2}

_DAY = re.compile(r'(\d{4}-\d{2}-\d{2})\.html$')
_WEEK = re.compile(r'(\d{4})-W(\d{2})\.html$')


def section_of(path):
    head = path.rsplit('/', 1)[0] if '/' in path else ''
    return {'posts': 'us', 'kr/posts': 'kr'}.get(head, head)


def key_of(path):
    return path.rsplit('/', 1)[-1][:-len('.html')] if path.endswith('.html') else None


def publish_day(path):
    """글이 나오는 날 — 일간은 파일명 날짜, 주간·일본은 키에서."""
    name = path.rsplit('/', 1)[-1]
    section = section_of(path)
    try:
        m = _DAY.search(name)
        if m and (section in DAILY or (section in PERIOD and PERIOD[section][1] == 'daily')):
            return date.fromisoformat(m.group(1))
        m = _WEEK.fullmatch(name)
        if m and section in PERIOD and PERIOD[section][1] == 'weekly':
            return date.fromisocalendar(int(m.group(1)), int(m.group(2)),
                                        7 if section == 'japan/posts' else 6)
    except ValueError:
        return None
    return None


def evidence(section, key):
    """발행 커밋에서 꺼낼 게이트 근거 — 경로는 레포 기준."""
    market, span = PERIOD[section]
    if market == 'jp' and span == 'daily':
        return (f'japan/data/daily/{key}.json', f'japan/data/news/daily/{key}.json')
    if market == 'jp':
        return (f'japan/data/{key}.json', f'japan/data/{key}.news.json')
    base = 'kr/data' if market == 'kr' else 'data'
    out = [f'{base}/{span}/{key}.json']
    if section == 'weekly':
        out.append(f'data/weekly_ext/{key}.insight.json')
    out += [f'recap_{market}.json', 'data/period_scorecard.json']
    return tuple(out)
