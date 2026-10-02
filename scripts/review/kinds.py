"""글 종류 표 — 러너와 문체 단계가 같은 표를 본다 (2026-10-01).

일간(us·kr) 말고도 주간·월간·일본 주간이 발행 뒤 codex 문체 수정을 받는다(사용자 지시
「주간, 월간, 일본 보고서도 codex가 검토하도록 해」). 이 글들은 파일명이 날짜가 아니라
주·월 키라서, 키에서 발행일을 정하고(주간 토요일, 일본 일요일, 월간 다음 달 1일) 발행 커밋에서
꺼낼 근거 파일을 정한다. 사실 정정(Claude)은 여전히 일간만이다 — `DAILY`.

설계: docs/superpowers/specs/2026-10-01-period-codex-style-pass.md
"""
import re
from datetime import date, timedelta

DAILY = ('us', 'kr')
# 섹션 → (시장, 주기). 섹션 이름은 queue.section_of 가 붙이는 디렉터리 이름이다.
PERIOD = {
    'weekly': ('us', 'weekly'),
    'kr/weekly': ('kr', 'weekly'),
    'monthly': ('us', 'monthly'),
    'kr/monthly': ('kr', 'monthly'),
    'japan/posts': ('jp', 'weekly'),
}
SECTIONS = DAILY + tuple(PERIOD)
# 신선도(일). 주간은 토·일에 맥이 꺼져 있을 수 있고, 월간은 수집이 늦으면 1일보다 늦게 나온다.
MAX_AGE = {'weekly': 3, 'kr/weekly': 3, 'japan/posts': 3, 'monthly': 7, 'kr/monthly': 7}

_DAY = re.compile(r'(\d{4}-\d{2}-\d{2})\.html$')
_WEEK = re.compile(r'(\d{4})-W(\d{2})\.html$')
_MONTH = re.compile(r'(\d{4})-(\d{2})\.html$')


def section_of(path):
    head = path.rsplit('/', 1)[0] if '/' in path else ''
    return {'posts': 'us', 'kr/posts': 'kr'}.get(head, head)


def key_of(path):
    return path.rsplit('/', 1)[-1][:-len('.html')] if path.endswith('.html') else None


def publish_day(path):
    """글이 나오는 날 — 일간은 파일명 날짜, 주간·월간·일본은 키에서."""
    name = path.rsplit('/', 1)[-1]
    section = section_of(path)
    try:
        m = _DAY.search(name)
        if m and section in DAILY:
            return date.fromisoformat(m.group(1))
        m = _WEEK.fullmatch(name)
        if m and section in PERIOD and PERIOD[section][1] == 'weekly':
            return date.fromisocalendar(int(m.group(1)), int(m.group(2)),
                                        7 if section == 'japan/posts' else 6)
        m = _MONTH.fullmatch(name)
        if m and section in PERIOD and PERIOD[section][1] == 'monthly':
            first = date(int(m.group(1)), int(m.group(2)), 1)
            return (first + timedelta(days=32)).replace(day=1)
    except ValueError:
        return None
    return None


def evidence(section, key):
    """발행 커밋에서 꺼낼 게이트 근거 — 경로는 레포 기준."""
    market, span = PERIOD[section]
    if market == 'jp':
        return (f'japan/data/{key}.json', f'japan/data/{key}.news.json')
    base = 'kr/data' if market == 'kr' else 'data'
    out = [f'{base}/{span}/{key}.json']
    if section == 'weekly':
        out.append(f'data/weekly_ext/{key}.insight.json')
    out += [f'recap_{market}.json', 'data/period_scorecard.json']
    return tuple(out)
