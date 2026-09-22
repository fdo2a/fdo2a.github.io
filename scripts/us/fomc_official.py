#!/usr/bin/env python3
"""연준 공표 FOMC 일정의 **파서**. 이것이 정본이다.

`scripts/us/calendar.py` 는 넘겨받은 회의일을 출처 「연준 공표 일정」·상태
`confirmed` 로 고정해 인쇄한다. 그 자리에 들어갈 자격은 연준 원문에만 있다.
moomoo 가 같은 날짜를 주더라도 그것은 **대조**이지 출처가 아니다.

두 가지를 원문에서 직접 읽는다 — 기존 코드가 추정하던 것들이다.

① **SEP 여부는 별표(`*`)다.** `calendar.py:30-32` 는 회의 월(3·6·9·12)로
   추정한다. 계산상 보조 규칙일 뿐이고, 원문에 표시가 있으면 그쪽이 맞다.
② **회의 마지막 날**이 성명 발표일이다. 원문은 '27-28' 처럼 기간으로 적는다.

원문의 각주: `* Meeting associated with a Summary of Economic Projections.`

When changing this: read `docs/superpowers/specs/2026-09-22-moomoo-forward-design.md`
before touching `scripts/us/fomc_official.py`.
"""

import datetime as dt
import re

URL = 'https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm'

MONTHS = {m: i for i, m in enumerate(
    ['january', 'february', 'march', 'april', 'may', 'june', 'july',
     'august', 'september', 'october', 'november', 'december'], start=1)}

_YEAR_PANEL = re.compile(
    r'panel-heading[^>]*>\s*<h4[^>]*>\s*<a[^>]*>\s*(\d{4})', re.S)
_ROW = re.compile(
    r'fomc-meeting__month[^>]*>(?:<strong>)?(.*?)(?:</strong>)?</div>\s*'
    r'<div class="fomc-meeting__date[^>]*>(.*?)</div>', re.S)


def _text(chunk):
    return re.sub(r'<[^>]+>', '', chunk or '').replace('&nbsp;', ' ').strip()


def parse_calendar(html):
    """연준 일정 페이지 → 회의 목록.

    각 항목: `{'year', 'month', 'days', 'date', 'sep', 'notation'}`.
    `date` 는 회의 **마지막 날**(성명 발표일)이다. 날짜를 못 읽으면 그 행을
    버린다 — 반쯤 읽은 행을 남기면 없는 회의를 인쇄한다.
    """
    marks = [(m.start(), m.group(1)) for m in _YEAR_PANEL.finditer(html or '')]
    if not marks:
        return []
    marks.append((len(html), None))

    out = []
    for i in range(len(marks) - 1):
        start, year = marks[i]
        if not year:
            continue
        segment = html[start:marks[i + 1][0]]
        for raw_month, raw_days in _ROW.findall(segment):
            item = _row(int(year), _text(raw_month), _text(raw_days))
            if item:
                out.append(item)
    out.sort(key=lambda r: r['date'])
    return out


def _row(year, month_text, days_text):
    # 달을 걸친 회의는 'January/February' 처럼 적힌다 — 마지막 달이 발표일이다.
    parts = [p.strip().lower() for p in re.split(r'[/-]', month_text) if p.strip()]
    month = None
    for p in reversed(parts):
        if p in MONTHS:
            month = MONTHS[p]
            break
    if month is None:
        return None

    sep = '*' in days_text
    notation = 'notation' in days_text.lower()
    nums = [int(n) for n in re.findall(r'\d+', days_text)]
    if not nums:
        return None
    # **월을 걸친 회의는 마지막 숫자가 작다.** 'April/May 30-1' 의 발표일은
    # 5월 1일이지 5월 30일이 아니다. `max()` 로 뽑으면 한 달을 통째로 밀고,
    # 'January/February 31-1' 은 2월 31일을 만들다 행째로 사라진다.
    last = nums[-1] if len(nums) > 1 and nums[-1] < nums[0] else max(nums)
    try:
        date = dt.date(year, month, last)
    except ValueError:
        return None
    return {'year': year, 'month': month, 'days': days_text,
            'date': date, 'sep': sep, 'notation': notation}


def book(html, *, verified_at, source=URL, keep_notation=False):
    """`data/fomc_dates.json` 이 먹는 형태로 만든다.

    `checked_at` 이 아니라 `verified_at` 을 쓴다 — 기존 로더의 `checked_at` 은
    수집 시각이고, 여기서 필요한 것은 **공식 원문을 확인한 시각**이다. 둘을
    한 필드로 뭉치면 오래된 표에 오늘 날짜만 붙는다.

    통지투표(notation vote)는 기본으로 뺀다. 성명·기자회견이 있는 정례 회의가
    아니라서 블랙아웃·SEP 계산의 전제와 다르다.
    """
    rows = [r for r in parse_calendar(html) if keep_notation or not r['notation']]
    return {
        'source': source,
        'verified_at': verified_at,
        'checked_at': verified_at,      # 기존 로더 호환
        'meetings': [r['date'].isoformat() for r in rows],
        'sep_meetings': [r['date'].isoformat() for r in rows if r['sep']],
        'notation_votes': [r['date'].isoformat()
                           for r in parse_calendar(html) if r['notation']],
    }
