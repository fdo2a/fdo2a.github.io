"""인구조사국(Census) 경제지표 발표 일정표 — 발표 기관이 직접 올리는 1년치 표(2026-11-08).

왜 FRED 만으로는 안 되나: FRED 릴리스 달력에는 공식 발표가 아닌 날이 섞인다. rid 95(M3)에는
내구재 **속보**(8:30 ET)와 **전체 보고서**(10:00 ET)가 한 id 로 번갈아 있고, rid 27(주택착공)에는
신규주택 판매일 10개와 Census 표에 없는 1/27 이, rid 9(소매)에는 2026-09-28 이 있다. API `releases/dates` 는 날짜만 줘서
그 둘을 가를 수 없다. Census 표는 지표 이름·날짜·시각을 함께 준다.

그래서 **Census 날짜를 쓰고 FRED 로 확인한다**(`upcoming.census_events`). 둘 중 하나라도 확인이
안 되면 그 지표는 비운다 — 틀린 날짜보다 빈 칸이 낫다.

함정(전부 실측):
- 숨은 칸(`class="hiden"`)에 기계용 날짜 코드가 있고 **보이는 날짜와 다를 수 있다**(2026 표 4월
  내구재: 보이는 「April 7, 2026」, 숨은 `A202604270830`, FRED 는 4/7). 보이는 칸만 읽는다.
- 무판 주소는 **최신 연도**(2026-11 현재 2027)를 보여 주고, `-2027` 주소는 아직 표가 없다.
  판의 연도는 주소가 아니라 행 날짜로 정한다.
- 같은 지표·날짜·시각 행이 겹쳐 있다(신규주택 15행, 실제 12일).
- 이름 칸 안에 줄바꿈이 있다(「…Inventories and\\n Orders」) — 공백을 하나로 접어 비교한다.

순수 모듈이다: HTML 을 받아 행을 낸다. 네트워크는 호출자가 `get(url) -> str` 로 넘긴다.
"""
import datetime as dt
import html.parser
import re

LIST_URL = 'https://www.census.gov/economic-indicators/calendar-listview.html'
YEAR_URL = 'https://www.census.gov/economic-indicators/calendar-listview-{year}.html'
HEADER = ('indicator', 'release date', 'time', 'period covered')

# Census 표의 지표 이름(정확 일치, 공백만 접는다) — 2026-11-08 표에서 옮겼다.
CENSUS_NAMES = {
    'retail-sales': 'Advance Monthly Sales for Retail and Food Services',
    'new-home-sales': 'New Residential Sales',
    'durable-goods': ("Advance Report on Durable Goods--Manufacturers' Shipments, "
                      'Inventories, and Orders'),
    'factory-orders': "Full Report - Manufacturers' Shipments, Inventories and Orders",
    'housing-starts': ('New Residential Construction (Building Permits, Housing Starts, '
                       'and Housing Completions)'),
    'trade-balance': 'U.S. International Trade in Goods and Services',
    'construction-spending': 'Construction Spending (Construction Put in Place)',
}

# FRED 교차 확인에 쓰는 시리즈 — 이 시리즈가 속한 FRED 릴리스의 날짜에 Census 날짜가 있어야 한다.
# 이름은 2026-11-08 FRED 시리즈 페이지의 「Release:」로 확인(upcoming.RELEASE_NAMES).
CENSUS_SERIES = {
    'retail-sales': 'RSAFS', 'new-home-sales': 'HSN1F', 'durable-goods': 'DGORDER',
    'factory-orders': 'AMTMNO', 'housing-starts': 'HOUST', 'trade-balance': 'BOPGSTB',
    'construction-spending': 'TTLCONS',
}

# 발표 기관이 오래 고정해 둔 벽시계(ET). FRED 는 날짜만 확인해 주므로 시각은 이 표와 맞을 때만
# 싣는다 — 다르면 날짜만 싣고 시각은 비운다(모르는 시각은 적지 않는다, codex 11/08 구현 4회 #2).
# 2026·2027 Census 표의 모든 행이 이 시각이다(2026-11-08 측정).
CENSUS_TIME_ET = {
    'retail-sales': '08:30', 'new-home-sales': '10:00', 'durable-goods': '08:30',
    'factory-orders': '10:00', 'housing-starts': '08:30', 'trade-balance': '08:30',
    'construction-spending': '10:00',
}

# 한 해 판에 그 지표 행이 이만큼은 있어야 「그해 일정이 다 올라와 있다」고 본다. 월간 지표는
# 12~15행이다. 몇 행뿐이면 창 안에 없는 것이 「발표 없음」인지 「아직 안 올림」인지 모른다.
MIN_ROWS_PER_YEAR = 10

# 한 지표의 두 발표가 이보다 가까우면 표가 이상하다고 본다. 2026·2027 표의 최소 간격은 20일
# (셧다운 여파로 밀린 2026 년 포함, 2026-11-08 측정). 다른 지표의 행이 옮겨 적혔거나 겹쳐 적힌
# 경우를 잡는다 — 공유 FRED id(내구재·공장주문)에서는 그런 행이 누락을 가린다(codex 11/08 구현 3회 #1).
MIN_GAP_DAYS = 14


class CensusError(Exception):
    pass


def _norm(text):
    return ' '.join((text or '').split())


_BY_NAME = {_norm(v).lower(): k for k, v in CENSUS_NAMES.items()}
_DATE = re.compile(r'^([A-Z][a-z]+) (\d{1,2}), (\d{4})$')
_TIME = re.compile(r'^(\d{1,2}):(\d{2}) ([AP])M$')
_MONTHS = ('January', 'February', 'March', 'April', 'May', 'June', 'July', 'August',
           'September', 'October', 'November', 'December')


def to_date(text):
    """「November 25, 2026」 -> date. 다른 꼴(「Nov. 25」, 「TBD」)은 None."""
    m = _DATE.match(_norm(text))
    if not m or m.group(1) not in _MONTHS:
        return None
    try:
        return dt.date(int(m.group(3)), _MONTHS.index(m.group(1)) + 1, int(m.group(2)))
    except ValueError:
        return None


def to_time(text):
    """「8:30 AM」 -> 「08:30」(ET 벽시계). 다른 꼴은 None — 모르는 시각은 적지 않는다."""
    m = _TIME.match(_norm(text).upper())
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if not (1 <= h <= 12 and 0 <= mi <= 59):
        return None
    h = (h % 12) + (12 if m.group(3) == 'P' else 0)
    return f'{h:02d}:{mi:02d}'


_VOID = frozenset({'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta',
                   'source', 'track', 'wbr'})


def _is_hidden(attrs):
    """숨김 표시가 붙은 요소인가 — `hiden`/`hidden` 클래스, `hidden` 속성, `display:none`."""
    a = dict(attrs)
    cls = (a.get('class') or '').lower().split()
    style = (a.get('style') or '').replace(' ', '').lower()
    return ('hiden' in cls or 'hidden' in cls or 'hidden' in a
            or 'display:none' in style or 'visibility:hidden' in style)


class _Rows(html.parser.HTMLParser):
    """표의 행 -> [[보이는 칸 텍스트]]. 숨긴 요소(칸·행·그 조상)의 내용은 버린다.

    숨긴 행(`<tr class="hidden">`)이나 숨긴 조상 안의 행은 아예 행으로 치지 않는다 — 셀 클래스만
    보면 숨긴 행의 날짜를 일정으로 읽는다(codex 2026-11-08 구현 #2).
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows, self._row, self._cell = [], None, None
        self._stack = []        # 열린 요소마다 (태그, 「여기부터 숨김」)

    def _hidden_now(self):
        return any(h for _t, h in self._stack)

    def handle_starttag(self, tag, attrs):
        if tag in _VOID:
            return
        hidden = _is_hidden(attrs)
        if tag == 'tr':
            self._row = None if (hidden or self._hidden_now()) else []
        elif tag in ('td', 'th') and self._row is not None:
            self._cell = None if (hidden or self._hidden_now()) else []
        self._stack.append((tag, hidden))

    def handle_endtag(self, tag):
        if tag in _VOID:
            return
        if tag in ('td', 'th'):
            if self._cell is not None and self._row is not None:
                self._row.append(_norm(''.join(self._cell)))
            self._cell = None
        elif tag == 'tr':
            if self._row is not None:
                self.rows.append(self._row)
            self._row = None
        # 닫는 태그와 짝인 요소까지 걷어낸다 — 닫히지 않은 <p>·<li> 가 남아 짝이 어긋나도
        # 숨김 표시가 엉뚱한 요소에 남지 않게.
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i][0] == tag:
                del self._stack[i:]
                break

    def handle_data(self, data):
        if self._cell is not None and not self._hidden_now():
            self._cell.append(data)


def page_rows(html_text, year=None):
    """-> {slug: {'rows': [(date, 'HH:MM')], 'bad': [원문 행]}}. `year` 가 아닌 해의 행은 버린다
    (`None` 이면 다 둔다).

    머리행(Indicator·Release Date·Time·Period Covered)이 없으면 `CensusError` — 표가 바뀌었는데
    맞는 척 읽지 않는다. 대상 지표의 행인데 날짜·시각을 못 읽으면 `bad` 에 남긴다(그 지표는
    호출자가 비운다). 대상이 아닌 지표의 행은 보지 않는다.
    """
    p = _Rows()
    p.feed(html_text or '')
    start = None
    for i, cells in enumerate(p.rows):
        if tuple(c.lower() for c in cells[:4]) == HEADER:
            start = i + 1
            break
    if start is None:
        raise CensusError('Census 일정표 머리행(Indicator·Release Date·Time·Period Covered)이 없다')
    out = {slug: {'rows': [], 'bad': []} for slug in CENSUS_NAMES}
    for cells in p.rows[start:]:
        slug = _BY_NAME.get(cells[0].lower()) if cells else None
        if not slug:
            continue
        if len(cells) < 3:
            # 대상 지표의 행인데 칸이 모자라다 — 버리면 그 발표가 조용히 빠진다(codex 11/08 구현 #3).
            out[slug]['bad'].append(' | '.join(cells))
            continue
        day, clock = to_date(cells[1]), to_time(cells[2])
        if day is None or clock is None:
            out[slug]['bad'].append(' | '.join(cells[:3]))
            continue
        if year is None or day.year == year:
            out[slug]['rows'].append((day, clock))
    return out


def _year_of(rows):
    """행 날짜의 다수 연도. 행이 없으면 None."""
    years = [d.year for v in rows.values() for d, _t in v['rows']]
    return max(set(years), key=years.count) if years else None


def _page_for(get, year):
    """-> (rows, None) | (None, 이유). 연도 접미사 주소 → 무판 주소 순. 판의 연도는 행으로 정한다."""
    why = []
    for url in (YEAR_URL.format(year=year), LIST_URL):
        name = url.rsplit('/', 1)[-1]
        try:
            text = get(url)
            everything = page_rows(text)
        except Exception as e:      # 받기 실패·표 없음
            why.append(f'{name}: {e}')
            continue
        if _year_of(everything) != year:
            why.append(f'{name}: {year}년 판이 아니다')
            continue
        return page_rows(text, year), None
    return None, '; '.join(why)


def collect(get, start, end):
    """-> {slug: {'dates': {date: 'HH:MM'}, 'why': None | 이유, 'seen': {date}}} — 창 [start, end] 안만.

    `dates` 는 실어도 되는 일정, `seen` 은 표에 보인 날짜(설명용 — `upcoming.census_events`).

    창이 걸친 해마다 판 하나가 필요하다. 어느 해 판이든 못 읽으면 **모든** 지표가 그 이유로
    비고, 지표별로는 행을 못 읽었거나·그해 행이 `MIN_ROWS_PER_YEAR` 보다 적거나·창이 걸친 달에
    행이 없거나·같은 날에 시각이 둘이면 그 지표만 빈다. `why` 가 있으면 `dates` 는 늘 비어 있다.
    """
    out = {slug: {'dates': {}, 'why': None, 'seen': set()} for slug in CENSUS_NAMES}
    every = {slug: set() for slug in CENSUS_NAMES}      # 읽은 해 전부의 날짜 — 간격 검사용
    for year in range(start.year, end.year + 1):
        rows, why = _page_for(get, year)
        if rows is None:
            return {slug: {'dates': {}, 'why': f'Census {year}년 일정표를 못 읽었다 — {why}',
                           'seen': set()} for slug in CENSUS_NAMES}
        for slug, got in rows.items():
            slot = out[slug]
            # 표에 보인 창 안의 날짜 — 이 지표를 싣지 못해도 다른 지표의 FRED 날짜를 「설명」하는
            # 데는 쓴다(rid 27 의 신규주택 판매일). 인쇄에는 쓰지 않는다.
            slot['seen'] |= {d for d, _t in got['rows'] if start <= d <= end}
            every[slug] |= {d for d, _t in got['rows']}
            if slot['why']:
                continue
            if got['bad']:
                slot['why'] = f'Census {year}년 표의 행을 못 읽었다: {got["bad"][0]}'
                continue
            uniq = set(got['rows'])
            if len(uniq) < MIN_ROWS_PER_YEAR:
                slot['why'] = (f'Census {year}년 표에 {len(uniq)}행뿐이다 — 그해 일정이 다 '
                               f'올라왔는지 모른다')
                continue
            # 창이 걸친 그해의 달마다 그 지표 행이 하나는 있어야 한다. 연간 행 수만 보면 창 안의
            # 행 하나가 빠지거나 이름이 바뀌어도 「발표 없음」으로 통과한다(codex 11/08 구현 #1).
            # 2026 표의 4월 신규주택·건설지출처럼 정말 없는 달은 「확인 못 함」이 된다 — 조심하는 쪽.
            have = {d.month for d, _t in uniq}
            lo = max(start, dt.date(year, 1, 1))
            hi = min(end, dt.date(year, 12, 31))
            gap = [m for m in range(lo.month, hi.month + 1) if m not in have]
            if gap:
                slot['why'] = f'Census {year}년 표에 {gap[0]}월 행이 없다 — 그달 일정을 확인할 수 없다'
                continue
            for day, clock in sorted(uniq):
                if not (start <= day <= end):
                    continue
                if slot['dates'].get(day, clock) != clock:
                    slot['why'] = f'Census 표에 {day} 시각이 둘이다'
                    break
                slot['dates'][day] = clock
    for slug, slot in out.items():
        days = sorted(every[slug])
        close = [(a, b) for a, b in zip(days, days[1:]) if (b - a).days < MIN_GAP_DAYS]
        if close and not slot['why']:
            a, b = close[0]
            slot['why'] = f'Census 표에 {a}·{b} 가 {(b - a).days}일 간격이다 — 행이 잘못 적혔을 수 있다'
        if slot['why']:
            slot['dates'] = {}
    return out
