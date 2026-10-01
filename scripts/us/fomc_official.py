#!/usr/bin/env python3
"""연준 공표 FOMC 일정의 **파서**. 이것이 정본이다.

`scripts/us/calendar.py` 는 넘겨받은 회의일을 출처 「연준 공표 일정」·상태
`confirmed` 로 고정해 인쇄한다. 그 자리에 들어갈 자격은 연준 원문에만 있다.
갱신은 `scripts/update_fomc_dates.py`(Actions), 읽기는 `load()` 다.

두 가지를 원문에서 직접 읽는다 — 기존 코드가 추정하던 것들이다.

① **SEP 여부는 별표(`*`)다.** `calendar.py:30-32` 는 회의 월(3·6·9·12)로
   추정한다. 계산상 보조 규칙일 뿐이고, 원문에 표시가 있으면 그쪽이 맞다.
② **회의 마지막 날**이 성명 발표일이다. 원문은 '27-28' 처럼 기간으로 적는다.

원문의 각주: `* Meeting associated with a Summary of Economic Projections.`

When changing this: read `docs/superpowers/specs/2026-09-22-moomoo-forward-design.md`
(§FOMC 일정 — the moomoo half was removed 2026-10-01) before touching
`scripts/us/fomc_official.py`.
"""

import datetime as dt
import json
import re
import ssl
import urllib.request

URL = 'https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm'

MONTHS = {m: i for i, m in enumerate(
    ['january', 'february', 'march', 'april', 'may', 'june', 'july',
     'august', 'september', 'october', 'november', 'december'], start=1)}

_ABBR = {m[:3]: i for m, i in MONTHS.items()}

# 정례회의는 해마다 8회다. 이보다 적게 읽힌 해가 있으면 원문 구조가 바뀐 것이다.
REGULAR_PER_YEAR = 8

_YEAR_PANEL = re.compile(
    r'panel-heading[^>]*>\s*<h4[^>]*>\s*<a[^>]*>\s*(\d{4})', re.S)
_ROW = re.compile(
    r'fomc-meeting__month[^>]*>(?:<strong>)?(.*?)(?:</strong>)?</div>\s*'
    r'<div class="fomc-meeting__date[^>]*>(.*?)</div>', re.S)


# 공식 확인의 유효기간. 갱신이 멈춰도 파일은 남으므로 **읽는 쪽**이 따진다 —
# 미래 날짜가 하나 남았다는 사실을 최신 확인의 대용물로 쓰지 않는다.
MAX_AGE_DAYS = 45


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
    # 원문은 달을 걸친 회의를 'Jan/Feb'·'Oct/Nov' 처럼 **줄여** 적는다. 전체 이름만
    # 찾으면 그 회의가 행째로 사라진다(2023 은 8회 중 6회만 잡혔다) — 앞 세 글자로 찾는다.
    month = None
    for p in reversed(parts):
        if p[:3] in _ABBR:
            month = _ABBR[p[:3]]
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


def fetch(timeout=30):
    """연준 일정 페이지 원문."""
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except Exception:
        ctx = ssl.create_default_context()
    req = urllib.request.Request(URL, headers={'User-Agent': 'fdo2a-report/1.0'})
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
        return r.read().decode('utf-8', 'replace')


def load(path, *, as_of, max_age_days=MAX_AGE_DAYS):
    """`data/fomc_dates.json` → `(회의일 목록, 사유)`.

    못 읽거나, 날짜 하나라도 형식이 틀리거나, 공식 확인이 `as_of` 기준으로
    `max_age_days` 보다 낡았거나 `as_of` 보다 미래면 **빈 목록**이다 — 없는 일정을 지어내지 않는다.
    직전 회의는 버리지 않는다(블랙아웃은 회의 다음 목요일까지다).
    """
    try:
        with open(path, encoding='utf-8') as fh:
            book = json.load(fh)
    except FileNotFoundError:
        return [], f'{path} 없음'
    except Exception as e:
        return [], f'{path} 읽기 실패: {e}'
    if not isinstance(book, dict):
        return [], f'{path} 형식이 객체가 아니다'
    # `checked_at` 은 옛 형식의 수집 시각이다 — 연준 원문 확인의 증거가 아니다.
    verified = book.get('verified_at')
    try:
        age = (as_of - dt.date.fromisoformat(str(verified))).days
    except (TypeError, ValueError):
        return [], f'{path} 에 공식 확인일(verified_at)이 없다'
    if age < 0:
        return [], f'{path} 공식 확인 {verified} 가 기준일 {as_of} 보다 미래다'
    if age > max_age_days:
        return [], f'{path} 공식 확인 {verified} — {age}일 지나 낡았다'
    out = []
    for raw in book.get('meetings') or []:
        try:
            out.append(dt.date.fromisoformat(raw))
        except Exception:
            return [], f'{path} 의 날짜 형식이 잘못됐다: {raw!r}'
    return sorted(out), f'{len(out)}건 (공식 확인 {verified})'


def problems(book, *, previous=None, today, require_previous=False,
             allowed_removals=()):
    """새로 파싱한 일정으로 파일을 바꿔도 되는가 — 안 되는 이유 목록.

    일부만 읽힌 원문으로 정상 파일을 덮지 않으려는 검사다(2026-10-01 codex 검토).
    「비어 있지 않음」은 회의 하나만 읽혀도 통과하고, 「해마다 8회」는 연준이
    다음 해를 단계적으로 올리면 정상 원문도 막는다. 그래서 셋을 본다.

    ① 중복 날짜가 없다. ② **처음·끝 해를 뺀** 중간 해는 정례회의 8회다.
    ③ 어제 표(`previous`)에 있던 **오늘 이후** 회의가 사라지지 않았다 — 한 해
    패널이 통째로 빠지면 개수로는 안 보인다. 실제 일정 변경이면 사람이 확인한
    날짜만 `allowed_removals`(`--allow-removal YYYY-MM-DD`)로 넘긴다. 어제 표가
    없으면 ③ 이 꺼지므로 `require_previous` 면 그 자체를 문제로 본다.
    """
    meetings = [str(d) for d in book.get('meetings') or []]
    if not meetings:
        return ['회의가 하나도 읽히지 않았다']
    out = []
    dup = sorted({d for d in meetings if meetings.count(d) > 1})
    if dup:
        out.append(f'중복 날짜: {", ".join(dup)}')
    count = {}
    for d in meetings:
        count[d[:4]] = count.get(d[:4], 0) + 1
    years = sorted(count)
    short = [y for y in years[1:-1] if count[y] < REGULAR_PER_YEAR]
    if short:
        out.append(f'정례회의 {REGULAR_PER_YEAR}회 미만인 해: {", ".join(short)}')
    if not (previous and previous.get('meetings')):
        if require_previous:
            out.append('어제 표가 없거나 읽히지 않는다 — 누락 대조 불가')
    else:
        keep = set(meetings) | {str(d) for d in allowed_removals}
        gone = sorted(str(d) for d in previous['meetings']
                      if str(d) >= today.isoformat() and str(d) not in keep)
        if gone:
            out.append(f'앞으로의 회의가 사라졌다: {", ".join(gone)}')
    return out
