#!/usr/bin/env python3
"""연준 H.4.1 과 재무부 분기조달계획(QRA) — 파싱·검증·판정·표 (US 아침 브리프 「유동성·수급」).

설계: docs/superpowers/specs/2026-11-07-us-liquidity-section.md. 국채 입찰 섹션과 같은 모양이다 —
수치는 전부 여기서 만들고, 작성자는 다시 계산하지 않으며, 게이트는 같은 함수로 만든 문자열과 발행본을 맞댄다.

두 원칙:

* **검증한 것만 넘긴다.** H.4.1 은 칸마다 붙은 열 머리(`header` 속성)로 값을 읽고 들여쓰기 깊이로 행의
  위아래를 가른다 — 「Others」는 표에 두 번 나온다(공급 쪽 RP 와 흡수 쪽 RRP). 네 항등식이 맞아야 통과.
  QRA 는 문서마다 정체성 문장을 찾고, 필수 필드를 못 읽으면 그 문서를 버린다.
* **실렸는가는 발행본이 안다.** 늦게 확인된 회차를 다음 글에 싣기 위한 원장은 따로 두지 않는다 —
  커밋된 US 일간 발행본의 `data-h41-release`·`data-qra-doc` 표식이 원장이다(`ledger_from_posts`).

순수 함수만 있다(네트워크 없음) — 수집은 `scripts/build_liquidity.py`.
"""

import datetime as dt
import glob
import html as _html
import os
import re
import statistics
from zoneinfo import ZoneInfo

ET = ZoneInfo('America/New_York')
SESSION_CUTOFF = dt.time(17, 30)        # US 수집 기준시각(ET)
H41_RELEASE_TIME = dt.time(16, 30)      # Fed 공시 시각(ET)
H41_CAP = 3                             # 한 글에 싣는 H.4.1 회차 상한(밀린 회차가 먼저)
OVERDUE_DAYS = 14
Z_WINDOW = 52
Z_MIN_N = 40
Z_MIN_SD = 1000                          # 백만 달러 = 10억 달러
Z_CUT = 2.00
FLAG_ROWS = ('reserves', 'tga', 'rrp_others')
TOL = 3                                  # 항등식 허용 오차(백만 달러 반올림)

H41_BASE = 'https://www.federalreserve.gov/releases/h41/'
QRA_LANDING = ('https://home.treasury.gov/policy-issues/financing-the-government/quarterly-refunding/'
               'most-recent-quarterly-refunding-documents')
TREASURY = 'https://home.treasury.gov'


class ParseError(Exception):
    """원문이 계약을 만족하지 못한다 — `code` 가 사유. 본문은 어디에도 남기지 않는다."""

    def __init__(self, code, detail=''):
        super().__init__(f'{code}: {detail}' if detail else code)
        self.code = code


# ── 달력 ────────────────────────────────────────────────────────────────

def _us_holidays(holidays):
    if isinstance(holidays, dict):
        us = holidays.get('us') or {}
        dates = us.get('dates') if isinstance(us, dict) else us
        return {str(d)[:10] for d in (dates or [])}
    return {str(d)[:10] for d in (holidays or [])}


def is_trading_day(d, holidays):
    return d.weekday() < 5 and d.isoformat() not in _us_holidays(holidays)


def prev_trading_day(d, holidays):
    x = d - dt.timedelta(days=1)
    while not is_trading_day(x, holidays):
        x -= dt.timedelta(days=1)
    return x


def cutoff(d):
    return dt.datetime.combine(d, SESSION_CUTOFF, ET)


def window(report_date, holidays):
    """(시작 미포함, 끝 포함] — 직전 거래일 기준시각부터 이번 세션 기준시각까지."""
    return cutoff(prev_trading_day(report_date, holidays)), cutoff(report_date)


def h41_release_at(release_date):
    return dt.datetime.combine(release_date, H41_RELEASE_TIME, ET)


# ── 금액 표시 — 렌더러와 게이트가 같은 함수를 쓴다 ─────────────────────────────

def eok(millions):
    """백만 달러 → 억 달러(float)."""
    return millions / 100.0


def fmt_usd(millions, signed=False):
    """백만 달러 → 「2조 9,628억 달러」「363억 달러」「2.3억 달러」."""
    if millions is None:
        return '—'
    sign = ''
    if signed:
        sign = '+' if millions > 0 else ('-' if millions < 0 else '')
    elif millions < 0:
        sign = '-'
    v = abs(millions) / 100.0
    if v >= 10000:
        whole = int(round(v))
        jo, rest = divmod(whole, 10000)
        body = f'{jo}조' + (f' {rest:,}억 달러' if rest else ' 달러')
    elif v >= 10:
        body = f'{int(round(v)):,}억 달러'
    elif v == 0:
        body = '0달러'
        sign = ''
    else:
        body = f'{v:.1f}억 달러'
    return sign + body


def printed_eok(millions):
    """`fmt_usd` 가 찍는 값의 절댓값(억 달러) — 게이트의 비교 단위."""
    v = abs(millions) / 100.0
    if v >= 10:
        return float(int(round(v)))
    return round(v, 1)


# ── H.4.1 ───────────────────────────────────────────────────────────────

# key -> (구역, 경로). 경로 = 들여쓰기 깊이를 따라 위에서 내려오는 라벨들(각주 숫자 제거).
H41_ROWS = {
    'securities': ('supplying', ('Reserve Bank credit', 'Securities held outright')),
    'treasuries': ('supplying', ('Reserve Bank credit', 'Securities held outright', 'U.S. Treasury securities')),
    'bills': ('supplying', ('Reserve Bank credit', 'Securities held outright', 'U.S. Treasury securities', 'Bills')),
    'notes_nominal': ('supplying', ('Reserve Bank credit', 'Securities held outright', 'U.S. Treasury securities',
                                    'Notes and bonds, nominal')),
    'notes_tips': ('supplying', ('Reserve Bank credit', 'Securities held outright', 'U.S. Treasury securities',
                                 'Notes and bonds, inflation-indexed')),
    'infl_comp': ('supplying', ('Reserve Bank credit', 'Securities held outright', 'U.S. Treasury securities',
                                'Inflation compensation')),
    'agency': ('supplying', ('Reserve Bank credit', 'Securities held outright', 'Federal agency debt securities')),
    'mbs': ('supplying', ('Reserve Bank credit', 'Securities held outright', 'Mortgage-backed securities')),
    'supplying_total': ('supplying', ('Total factors supplying reserve funds',)),
    'rrp_total': ('absorbing', ('Reverse repurchase agreements',)),
    'rrp_foreign': ('absorbing', ('Reverse repurchase agreements', 'Foreign official and international accounts')),
    'rrp_others': ('absorbing', ('Reverse repurchase agreements', 'Others')),
    'tga': ('absorbing', ('Deposits with F.R. Banks, other than reserve balances', 'U.S. Treasury, General Account')),
    'absorbing_total': ('absorbing', ('Total factors, other than reserve balances, absorbing reserve funds',)),
    'reserves': ('absorbing', ('Reserve balances with Federal Reserve Banks',)),
}

# 표에 싣는 행(순서 그대로) — 판정 행은 FLAG_ROWS.
TABLE_ROWS = ('reserves', 'tga', 'rrp_others', 'rrp_foreign', 'treasuries', 'mbs')
ROW_KO = {
    'reserves': '지급준비금', 'tga': 'TGA(재무부 계정)', 'rrp_others': '시장 역레포(ON RRP)',
    'rrp_foreign': '해외 역레포', 'treasuries': '보유 국채', 'mbs': '보유 MBS',
}
# 게이트가 문단에서 행을 알아보는 이름(구간 나누기). 앞의 것이 정식 이름.
ROW_NAMES = {
    'reserves': ('지급준비금', '지준'),
    'tga': ('재무부 일반계정', 'TGA', '정부 현금'),
    'rrp_others': ('ON RRP', '시장 역레포', '역레포 시설'),
    'rrp_foreign': ('해외 역레포', '해외 공식계정'),
    'treasuries': ('보유 국채', '국채 보유'),
    'mbs': ('MBS', '주택저당증권'),
}

_NUM_CELL = re.compile(r'^([+\-−])?\s*(\d{1,3}(?:,\d{3})*)$')
_FOOTNOTE_TAIL = re.compile(r'(?<=[A-Za-z)])\d{1,2}$')
_DATE_IN = re.compile(r'([A-Z][a-z]{2})\.?\s*(\d{1,2}),\s*(\d{4})')
_MON = {m: i for i, m in enumerate('Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec'.split(), 1)}


def _norm(s):
    return re.sub(r'\s+', ' ', (s or '').replace('\xa0', ' ')).strip()


def _label(s):
    return _FOOTNOTE_TAIL.sub('', _norm(s)).strip()


def _date_from(s):
    m = _DATE_IN.search(s or '')
    if not m or m.group(1) not in _MON:
        return None
    return dt.date(int(m.group(3)), _MON[m.group(1)], int(m.group(2)))


def _cell_number(s):
    s = _norm(s).replace('−', '-')
    m = _NUM_CELL.match(s.replace(' ', '') if s.startswith(('+', '-')) else s)
    if not m:
        m = _NUM_CELL.match(s)
    if not m:
        return None
    v = int(m.group(2).replace(',', ''))
    return -v if m.group(1) in ('-', '−') else v


def _depth(cell):
    p = cell.find('.//p')
    style = (p.get('style') if p is not None else '') or ''
    m = re.search(r'text-indent:\s*([\d.]+)pt', style)
    return int(round(float(m.group(1)) / 9.0)) if m else 0


def _release_date(doc):
    title = _norm(doc.findtext('.//title') or '')
    m = re.search(r'H\.4\.1\s*-\s*([A-Z][a-z]+)\s+(\d{1,2}),\s*(\d{4})', title)
    if not m:
        raise ParseError('title_date', title[:80])
    return dt.datetime.strptime(' '.join(m.groups()), '%B %d %Y').date()


def parse_h41(text):
    """H.4.1 HTML → 회차 dict. 계약을 못 지키면 ParseError."""
    from lxml import html as LH
    try:
        doc = LH.fromstring(text)
    except Exception as e:
        raise ParseError('html', type(e).__name__)
    release = _release_date(doc)
    flat = _norm(doc.text_content())
    if not re.search(r'Factors Affecting Reserve Balances of Depository Institutions\s*Millions of dollars', flat):
        raise ParseError('unit', 'Millions of dollars 머리가 없다')

    tables = [t for t in doc.iter('table')]
    k = next((i for i, t in enumerate(tables)
              if any(_label(r[0].text_content()) == 'Reserve balances with Federal Reserve Banks'
                     for r in ([c for c in tr if c.tag in ('td', 'th')] for tr in t.iter('tr')) if r)), None)
    if k is None or k == 0:
        raise ParseError('table1', 'Reserve balances 행이 있는 표가 없다')
    pair = tables[k - 1:k + 1]

    found, dates = {}, {}
    for zone, table in zip(('supplying', 'absorbing'), pair):
        heads = {c.get('id'): _norm(c.text_content()) for c in table.iter('td', 'th') if c.get('id')}
        stack = []
        for tr in table.iter('tr'):
            cells = [c for c in tr if c.tag in ('td', 'th')]
            if len(cells) < 5:
                continue
            lab = _label(cells[0].text_content())
            cols = {}
            for c in cells[1:]:
                hid = (c.get('headers') or c.get('header') or '').split()
                htxt = [heads.get(h, '') for h in hid]
                n = _cell_number(c.text_content())
                if n is None:
                    continue
                joined = ' | '.join(htxt)
                if 'Wednesday' in joined:
                    role = 'wed'
                    dates.setdefault('wednesday', _date_from(joined.split('Wednesday', 1)[1]))
                elif 'Change from week ended' in joined:
                    d = _date_from(htxt[-1]) if htxt else None
                    role = ('chg', d)
                elif 'Week ended' in joined:
                    role = 'avg'
                    dates.setdefault('week_ended', _date_from(joined.split('Week ended', 1)[1]))
                else:
                    continue
                if role in cols:
                    raise ParseError('duplicate_column', lab)
                cols[role] = n
            if not lab or not cols:
                continue
            depth = _depth(cells[0])
            stack = stack[:depth] + [lab]
            path = tuple(stack)
            for key, (z, want) in H41_ROWS.items():
                if z == zone and path == want:
                    if key in found:
                        raise ParseError('duplicate_row', key)
                    found[key] = cols
    missing = [k for k in H41_ROWS if k not in found]
    if missing:
        raise ParseError('missing_rows', ','.join(missing))
    we, wed = dates.get('week_ended'), dates.get('wednesday')
    if not we or not wed:
        raise ParseError('header_dates')
    rows = {}
    for key, cols in found.items():
        chg = {r[1]: v for r, v in cols.items() if isinstance(r, tuple)}
        prior = we - dt.timedelta(days=7)
        yago = [d for d in chg if d and d != prior]
        if 'avg' not in cols or 'wed' not in cols or prior not in chg or len(yago) != 1:
            raise ParseError('columns', key)
        rows[key] = {'avg': cols['avg'], 'chg_wk': chg[prior], 'chg_yr': chg[yago[0]], 'wed': cols['wed']}
    w = {k: r['wed'] for k, r in rows.items()}
    checks = {
        'reserves': abs(w['supplying_total'] - w['absorbing_total'] - w['reserves']) <= TOL,
        'rrp': abs(w['rrp_total'] - w['rrp_foreign'] - w['rrp_others']) <= TOL,
        'securities': abs(w['securities'] - w['treasuries'] - w['agency'] - w['mbs']) <= TOL,
        'treasuries': abs(w['treasuries'] - w['bills'] - w['notes_nominal'] - w['notes_tips']
                          - w['infl_comp']) <= TOL,
    }
    bad = [k for k, ok in checks.items() if not ok]
    if bad:
        raise ParseError('identity', ','.join(bad))
    return {'release_date': release.isoformat(), 'week_ended': we.isoformat(), 'wednesday': wed.isoformat(),
            'rows': rows, 'url': h41_url(release)}


def h41_url(release_date):
    if isinstance(release_date, str):
        release_date = dt.date.fromisoformat(release_date)
    return f'{H41_BASE}{release_date:%Y%m%d}/'


def _nth_weekday(year, month, weekday, n):
    d = dt.date(year, month, 1)
    d += dt.timedelta(days=(weekday - d.weekday()) % 7)
    return d + dt.timedelta(days=7 * (n - 1))


def _last_weekday(year, month, weekday):
    d = dt.date(year + (month == 12), month % 12 + 1, 1) - dt.timedelta(days=1)
    return d - dt.timedelta(days=(d.weekday() - weekday) % 7)


def _observed(d):
    return d - dt.timedelta(days=1) if d.weekday() == 5 else (d + dt.timedelta(days=1) if d.weekday() == 6 else d)


def federal_holidays(year):
    """연방 공휴일(대체 휴일 포함) — H.4.1 은 이 날이면 다음 영업일로 밀린다(Fed 공지 문구).

    임시 휴무(2025-01-09 전 대통령 장례)는 계산할 수 없다 — 그날 못 찾으면 다음 영업일들을 이어서 찾는다.
    """
    fixed = [dt.date(year, 1, 1), dt.date(year, 6, 19), dt.date(year, 7, 4), dt.date(year, 11, 11),
             dt.date(year, 12, 25)]
    out = {_observed(d) for d in fixed}
    out |= {_nth_weekday(year, 1, 0, 3), _nth_weekday(year, 2, 0, 3), _last_weekday(year, 5, 0),
            _nth_weekday(year, 9, 0, 1), _nth_weekday(year, 10, 0, 2), _nth_weekday(year, 11, 3, 4)}
    nxt = dt.date(year + 1, 1, 1)
    if nxt.weekday() == 5:                 # 다음 해 1/1 이 토요일이면 올해 12/31 이 대체 휴일
        out.add(dt.date(year, 12, 31))
    return out


def is_fed_business_day(d):
    return d.weekday() < 5 and d not in federal_holidays(d.year)


def next_fed_business_day(d):
    x = d + dt.timedelta(days=1)
    while not is_fed_business_day(x):
        x += dt.timedelta(days=1)
    return x


def h41_scheduled(thursday):
    """그 주 H.4.1 예정 발표일 — 목요일, 연방 공휴일이면 다음 영업일."""
    return thursday if is_fed_business_day(thursday) else next_fed_business_day(thursday)


def h41_probe_dates(thursday):
    """그 주 회차를 찾을 날짜 — 예정일부터 **다음 주 예정일 전날까지의 영업일 전부**.

    그 주 회차는 다음 주 회차보다 먼저 나오므로 이 범위 밖에 있을 수 없다. 범위가 유한해 못 찾은 주를 매 실행
    다시 봐도 요청이 몇 개로 묶인다(구현 검토: 고정 2영업일 창은 더 늦은 발표를 영영 놓쳤다).
    """
    d = h41_scheduled(thursday)
    end = h41_scheduled(thursday + dt.timedelta(days=7))
    out = []
    while d < end:
        out.append(d)
        d = next_fed_business_day(d)
    return out


def _thursdays_from(effective, now_date):
    d = effective.date() if isinstance(effective, dt.datetime) else effective
    d -= dt.timedelta(days=(d.weekday() - 3) % 7 or 7)        # EFFECTIVE 직전 목요일부터(7차 설계 검토 #2)
    out = []
    while d <= now_date:
        out.append(d)
        d += dt.timedelta(days=7)
    return out


def h41_due(history, effective, now):
    """**지금 확인해야 할** 주 — 예정 발표 시각이 지났는데 그 주에 배정할 회차가 이력에 없는 것. [(목요일, 대체 탐색 날짜)].

    발표일 전에는 확인하지 않는다(사용자 2026-11-07 「다음 발표일을 파악한 뒤 그 날만 확인」). 회차를 주에 붙이는 규칙은
    아래 주석 — 한 주를 넘긴 지연도 그 주를 채운다.
    못 찾은 주는 찾을 때까지 다음 실행이 다시 본다(늦은 발표도 싣는다). 대체 탐색 날짜는 Fed 발표일 목록을 못 읽을 때만 쓴다.
    """
    weeks = [th for th in _thursdays_from(effective, now.date()) if h41_release_at(h41_scheduled(th)) <= now]
    if not weeks:
        return []
    first = h41_scheduled(weeks[0])
    dates = sorted(d for d in (dt.date.fromisoformat(r['release_date']) for r in history) if d >= first)
    # 발표일마다 「예정일이 그날 이전인 주 중 아직 비어 있는 가장 늦은 주」에 붙인다 — 정상 주는 자기 주에,
    # 다음 주 예정일을 넘긴 지연은 비어 있는 앞 주에 붙는다
    taken = set()
    for d in dates:
        for th in reversed(weeks):
            if th not in taken and h41_scheduled(th) <= d:
                taken.add(th)
                break
    return [(th, [d for d in h41_probe_dates(th) if h41_release_at(d) <= now]) for th in weeks if th not in taken]


H41_DATES = H41_BASE + 'releaseDates.json'


def parse_release_dates(text):
    """Fed `releaseDates.json` → 발표일(date) 집합. 형식이 다르면 ParseError."""
    import json
    try:
        data = json.loads(text)
        out = {dt.datetime.strptime(d, '%Y%m%d').date()
               for y in data for m in y.get('Months') or [] for d in m.get('Dates') or []}
    except Exception as e:
        raise ParseError('release_dates', type(e).__name__)
    if not out:
        raise ParseError('release_dates', 'empty')
    return out


def h41_next_release(now):
    """다음 예정 발표일(ISO) — 책에 적어 「언제 다시 확인하나」를 보인다."""
    d = now.date()
    th = d + dt.timedelta(days=(3 - d.weekday()) % 7)
    while True:
        s = h41_scheduled(th)
        if h41_release_at(s) > now:
            return s.isoformat()
        th += dt.timedelta(days=7)


def upsert_history(history, rnd):
    """release_date 키 upsert, week_ended 정렬. 같은 week_ended 두 회차면 ValueError."""
    keep = {r['release_date']: r for r in history}
    slim = dict({k: rnd[k] for k in ('release_date', 'week_ended', 'wednesday', 'url')},
                rows={k: rnd['rows'][k] for k in TABLE_ROWS})
    keep[rnd['release_date']] = slim
    out = sorted(keep.values(), key=lambda r: r['week_ended'])
    wes = [r['week_ended'] for r in out]
    if len(wes) != len(set(wes)):
        raise ValueError('같은 week_ended 회차가 둘이다')
    return out


def wed_changes(history):
    """[(release_date, wednesday, {row: 수요일 잔고 주간 변화})] — 직전 행 wednesday 가 정확히 7일 전일 때만."""
    out = []
    for prev, cur in zip(history, history[1:]):
        a, b = dt.date.fromisoformat(prev['wednesday']), dt.date.fromisoformat(cur['wednesday'])
        if (b - a).days != 7:
            continue
        out.append((cur['release_date'], cur['wednesday'],
                    {k: cur['rows'][k]['wed'] - prev['rows'][k]['wed'] for k in FLAG_ROWS + TABLE_ROWS
                     if k in cur['rows'] and k in prev['rows']}))
    return out


def flags(history, release_date):
    """그 회차의 이례적 판정 — 회차 시점의 직전 52개 유효 변화만으로(나중 값이 섞이지 않게)."""
    ch = wed_changes(history)
    idx = next((i for i, c in enumerate(ch) if c[0] == release_date), None)
    rnd = next((r for r in history if r['release_date'] == release_date), None)
    out = {'rows': {}, 'window': None}
    prev = next((p for p, c in zip(history, history[1:]) if c['release_date'] == release_date), None)
    for k in TABLE_ROWS:
        wc = None
        if idx is not None:
            wc = ch[idx][2].get(k)
        out['rows'][k] = {'wed_chg': wc}
    if prev is not None and rnd is not None and (dt.date.fromisoformat(rnd['week_ended'])
                                                 - dt.date.fromisoformat(prev['week_ended'])).days == 7:
        out['prior_mismatch'] = sorted(k for k in TABLE_ROWS
                                       if abs(rnd['rows'][k]['avg'] - prev['rows'][k]['avg'] - rnd['rows'][k]['chg_wk'])
                                       > TOL)
    if idx is None or rnd is None or prev is None:
        return out
    hist = ch[max(0, idx - Z_WINDOW):idx]
    if hist:
        out['window'] = {'first': hist[0][1], 'last': hist[-1][1], 'n': len(hist)}
    for k in FLAG_ROWS:
        vals = [h[2][k] for h in hist if k in h[2]]
        wc = ch[idx][2].get(k)
        z = None
        if len(vals) >= Z_MIN_N and wc is not None:
            sd = statistics.pstdev(vals)
            if sd >= Z_MIN_SD:
                z = round((wc - statistics.mean(vals)) / sd, 2)
        out['rows'][k].update({'z': z, 'big': z is not None and abs(z) >= Z_CUT})
    return out


# ── QRA ─────────────────────────────────────────────────────────────────

_ROUND = re.compile(r'(\d{4})\s*-\s*(1st|2nd|3rd|4th)\s+Quarter')
_LAND_TIME = re.compile(r'^\s*(\d{1,2}):(\d{2})\s*([AP]M)\s+\w+day,\s*(\w+\s+\d{1,2},\s*\d{4})')
_QNUM = {'1st': 1, '2nd': 2, '3rd': 3, '4th': 4}
REFUND_MONTH = {1: 2, 2: 5, 3: 8, 4: 11}       # 회차 분기 → 발표·차환 월
_MONTHS = ('January February March April May June July August September October November December').split()


def _et(date_s, hh, mm, ampm):
    h = int(hh) % 12 + (12 if ampm == 'PM' else 0)
    d = dt.datetime.strptime(re.sub(r'\s+', ' ', date_s), '%B %d, %Y').date()
    return dt.datetime.combine(d, dt.time(h, int(mm)), ET)


def parse_landing(text):
    """most-recent 랜딩 → {round, round_name, times:{estimates, statement}, links:{borrowing, refunding, tbac}}."""
    m = re.search(r'<meta property="og:description" content="([^"]*)"', text)
    if not m:
        raise ParseError('landing_meta')
    desc = re.sub(r'\s+', ' ', _html.unescape(m.group(1)).replace('\u200b', ''))
    # 발표 묶음마다 「DOCUMENTS RELEASED at <시각>」 + 문서 이름들. 문서 이름으로 묶음을 고른다.
    times, nexts = {}, {}
    for block in desc.split('DOCUMENTS RELEASED at')[1:]:
        t = _LAND_TIME.match(block)
        if not t:
            continue
        at = _et(t.group(4), t.group(1), t.group(2), t.group(3))
        nx = re.search(r'next release is scheduled for (\w+ \d{1,2}, \d{4})', block)
        nxd = dt.datetime.strptime(nx.group(1), '%B %d, %Y').date().isoformat() if nx else None
        if 'Financing Estimates' in block:
            times['borrowing'] = at
            nexts['borrowing'] = nxd
        if 'Policy Statement' in block:
            times['refunding'] = at
            nexts['refunding'] = nxd
            if 'TBAC Report to Secretary' in block:
                times['tbac'] = at
    if 'borrowing' not in times or 'refunding' not in times:
        raise ParseError('landing_times', desc[:120])
    rm = _ROUND.findall(desc.split('Primary Dealer')[0])
    if not rm or len(set(rm)) != 1:
        raise ParseError('landing_round', str(rm))
    year, q = int(rm[0][0]), _QNUM[rm[0][1]]
    links = {}
    for a, b, label in re.findall(r'<a[^>]*href=(?:"([^"]+)"|([^\s>"]+))[^>]*>(.*?)</a>', text, re.S):
        href = a or b
        lab = _norm(_html.unescape(re.sub(r'<[^>]+>', ' ', label)))
        if not href.startswith('/news/press-releases/'):
            continue
        for kind, prefix in (('borrowing', 'Financing Estimates'), ('refunding', 'Policy Statement'),
                             ('tbac', 'TBAC Report to Secretary')):
            if lab.startswith(prefix) and kind not in links:
                links[kind] = TREASURY + href
    for kind in ('borrowing', 'refunding'):
        if kind not in links:
            raise ParseError('landing_links', kind)
    return {'round': f'{year}Q{q}', 'round_name': f'{year} - {rm[0][1]} Quarter',
            'times': {k: v.isoformat() for k, v in times.items()}, 'next': nexts,
            'links': links}


def _press(text):
    """보도자료 HTML → (제목, 발표 시각(UTC datetime), 본문 평문)."""
    title = _norm(_html.unescape(re.sub(r'<[^>]+>', ' ', (re.search(r'<title>(.*?)</title>', text, re.S)
                                                          or re.search(r'()', '')).group(1))))
    tm = re.search(r'<time datetime=["\']?([0-9T:\-+]+Z?)', text)
    when = dt.datetime.fromisoformat(tm.group(1).replace('Z', '+00:00')) if tm else None
    if when is not None and when.tzinfo is None:
        when = None
    i = text.find('field--name-field-news-body')
    if i < 0:
        raise ParseError('press_body')
    body = re.sub(r'<script.*?</script>|<style.*?</style>', ' ', text[i:], flags=re.S)
    body = re.sub(r'</(p|li|tr|h\d|div)>', '\n', body)
    body = _html.unescape(re.sub(r'<[^>]+>', ' ', body))
    body = '\n'.join(_norm(x) for x in body.split('\n') if _norm(x))
    return title, when, body


def _money_bn(num, unit):
    v = float(num.replace(',', ''))
    return v * 1000.0 if unit.lower().startswith('trillion') else v


def _quarter_of(month):
    return (month - 1) // 3 + 1


def _same_round_week(when, rnd):
    year, q = int(rnd[:4]), int(rnd[-1])
    return when is not None and when.year == year and when.astimezone(ET).month == REFUND_MONTH[q]


def parse_borrowing(text, rnd):
    title, when, body = _press(text)
    if not _same_round_week(when, rnd):
        raise ParseError('date', str(when))
    pat = re.compile(r'During the (\w+)[–-](\w+) (\d{4}) quarter, Treasury expects to borrow \$([\d,.]+) '
                     r'(billion|trillion) in privately-held net marketable debt, assuming an end-of-(\w+) '
                     r'cash balance of \$([\d,.]+) (billion|trillion)')
    found = pat.findall(body)
    if not found:
        raise ParseError('identity_not_found')
    rel_q = _quarter_of(when.astimezone(ET).month)
    cur = next((f for f in found if f[0] in _MONTHS and _quarter_of(_MONTHS.index(f[0]) + 1) == rel_q
                and int(f[2]) == when.astimezone(ET).year), None)
    if cur is None:
        raise ParseError('quarter_mismatch')
    out = {'kind': 'borrowing', 'title': title, 'released_at': when.isoformat(),
           'quarter': f'{cur[0]}–{cur[1]} {cur[2]}',
           'borrow_bn': _money_bn(cur[3], cur[4]), 'cash_bn': _money_bn(cur[6], cur[7]),
           'next': None, 'vs_prior': None}
    nxt = [f for f in found if f is not cur and f != cur]
    if nxt:
        f = nxt[0]
        out['next'] = {'quarter': f'{f[0]}–{f[1]} {f[2]}', 'borrow_bn': _money_bn(f[3], f[4]),
                       'cash_bn': _money_bn(f[6], f[7])}
    m = re.search(r'The borrowing estimate is \$([\d,.]+) (billion|trillion) (lower|higher) than announced in '
                  r'(\w+) (\d{4})', body)
    if m:
        out['vs_prior'] = {'diff_bn': _money_bn(m.group(1), m.group(2)), 'direction': m.group(3),
                           'month': m.group(4), 'year': int(m.group(5))}
    return out


def parse_refunding(text, rnd):
    title, when, body = _press(text)
    if not _same_round_week(when, rnd):
        raise ParseError('date', str(when))
    year, q = int(rnd[:4]), int(rnd[-1])
    m = re.search(r'is offering \$([\d,.]+) billion of Treasury securities to refund approximately \$([\d,.]+) '
                  r'billion of privately-held Treasury notes and bonds maturing on (\w+) 15, (\d{4})', body)
    if not m:
        raise ParseError('identity_not_found')
    if m.group(3) != _MONTHS[REFUND_MONTH[q] - 1] or int(m.group(4)) != year:
        raise ParseError('refund_date', f'{m.group(3)} 15, {m.group(4)}')
    new = re.search(r'raise new cash from private investors of approximately \$([\d,.]+) billion', body)
    if not new:
        raise ParseError('required_field', 'new_cash')
    sizes = {}
    for yrs, kind, amt in re.findall(r'A (\d+)-year (note|bond) in the amount of \$([\d,.]+) billion', body):
        sizes[int(yrs)] = float(amt.replace(',', ''))
    if not {3, 10, 30} <= set(sizes):
        raise ParseError('required_field', 'sizes')
    out = {'kind': 'refunding', 'title': title, 'released_at': when.isoformat(),
           'total_bn': float(m.group(1).replace(',', '')), 'refund_bn': float(m.group(2).replace(',', '')),
           'new_cash_bn': float(new.group(1).replace(',', '')), 'sizes_bn': {str(k): v for k, v in sorted(sizes.items())},
           'guidance': None}
    g = re.search(r'NOMINAL COUPON AND FRN FINANCING\n(.*?)(?:\n[A-Z][A-Z ,&-]{6,}\n|$)', body, re.S)
    if g:
        s = re.search(r'(Treasury anticipates [^.]*\.)', g.group(1))
        if s:
            out['guidance'] = _norm(s.group(1))
    return out


def check_ta_ws(refunding, rnd, announced):
    """보도자료의 3·10·30년 규모 ↔ TreasuryDirect 공고(같은 차환일). -> {만기: match|unmatched}, 불일치면 ParseError.

    공고는 입찰 몇 주 뒤 목록에서 빠진다 — 못 찾은 만기는 실패가 아니라 `unmatched`(확정 설계 v4 3절).
    """
    year, q = int(rnd[:4]), int(rnd[-1])
    dated = f'{year}-{REFUND_MONTH[q]:02d}-15'
    out = {}
    for y, size in refunding['sizes_bn'].items():
        rows = [r for r in announced or () if (r.get('securityTerm') or '') == f'{y}-Year'
                and (r.get('datedDate') or '')[:10] == dated and (r.get('type') in ('Note', 'Bond'))]
        if not rows:
            out[y] = 'unmatched'
            continue
        amt = [float(r.get('offeringAmount') or 0) / 1e9 for r in rows]
        if size not in amt:
            raise ParseError('ta_ws_mismatch', f'{y}년물 보도자료 {size} vs 공고 {amt}')
        out[y] = 'match'
    return out


def parse_tbac(text, rnd):
    title, when, body = _press(text)
    if not title.startswith('Report to the Secretary of the Treasury from the Treasury Borrowing Advisory Committee'):
        raise ParseError('title', title[:80])
    if not _same_round_week(when, rnd):
        raise ParseError('date', str(when))
    return {'kind': 'tbac', 'title': title, 'released_at': when.isoformat(), 'view': True}, body


def guidance_change(prev, cur):
    """-> (same|changed|unknown, 바뀐 낱말 목록)."""
    if not prev or not cur:
        return 'unknown', []
    a, b = prev.split(), cur.split()
    if a == b:
        return 'same', []
    import difflib
    diff = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b).get_opcodes():
        if op != 'equal':
            diff.append(' '.join(a[i1:i2] + (['→'] if i2 > i1 and j2 > j1 else []) + b[j1:j2]).strip())
    words = sorted({w.strip('.,') for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b).get_opcodes()
                    if op != 'equal' for w in a[i1:i2] + b[j1:j2] if w.strip('.,')})
    return 'changed', words


def prior_round(rounds, rnd):
    """현재 회차보다 앞선 가장 최근 회차 키."""
    olds = sorted(k for k in rounds if k < rnd)
    return olds[-1] if olds else None


# ── 원장·후보 ─────────────────────────────────────────────────────────────

_POST = re.compile(r'^\d{4}-\d{2}-\d{2}\.html$')
# 원장은 게이트가 받는 표기보다 **넓게** 읽는다(공백·따옴표·대소문자) — 실린 회차를 못 알아보면 중복 발행이다(재검토 #3).
_H41_MARK = re.compile(r'\bdata-h41-release\s*=\s*["\']?\s*(\d{4}-\d{2}-\d{2})', re.I)
_QRA_MARK = re.compile(r'\bdata-qra-doc\s*=\s*["\']?\s*(\d{4}Q[1-4]:(?:borrowing|refunding|tbac))', re.I)


def _ledger_scan(texts):
    h41, qra = set(), set()
    for t in texts:
        t = re.sub(r'<!--.*?-->', ' ', t, flags=re.S)
        h41 |= set(_H41_MARK.findall(t))
        qra |= {f'{k[:4]}Q{k[5]}:{k.split(":", 1)[1].lower()}' for k in _QRA_MARK.findall(t)}
    return h41, qra


def ledger_from_posts(repo, exclude_date):
    """**커밋된**(HEAD) US 일간 발행본 — 현재 후보 날짜만 뺀다 — 의 원장 표식 → (H.4.1 회차 집합, QRA 문서 키 집합).

    작업 트리가 아니라 HEAD 를 읽는다(구현 검토 #6): 커밋 안 된 글의 표식이 「실렸다」로 잡히거나, 커밋된 표식을
    작업 트리에서 지워 중복 발행하는 경로를 막는다. git 저장소가 아니면(테스트 임시 디렉터리) 파일을 읽는다.
    """
    import subprocess
    try:
        out = subprocess.run(['git', '-C', repo, 'grep', '-l', '-i', '-E', 'data-(h41-release|qra-doc)', 'HEAD', '--',
                              'posts/*.html'], capture_output=True, text=True, timeout=60)
        is_git = out.returncode in (0, 1) and subprocess.run(
            ['git', '-C', repo, 'rev-parse', '--is-inside-work-tree'], capture_output=True, text=True).stdout.strip() == 'true'
    except (OSError, subprocess.SubprocessError):
        is_git = False
    texts = []
    if is_git:
        for line in out.stdout.splitlines():
            path = line.split(':', 1)[1] if line.startswith('HEAD:') else line
            name = os.path.basename(path)
            if not _POST.match(name) or name[:10] == str(exclude_date) or os.path.dirname(path) != 'posts':
                continue
            show = subprocess.run(['git', '-C', repo, 'show', f'HEAD:{path}'], capture_output=True, text=True)
            if show.returncode == 0:
                texts.append(show.stdout)
        return _ledger_scan(texts)
    for path in glob.glob(os.path.join(repo, 'posts', '*.html')):
        name = os.path.basename(path)
        if not _POST.match(name) or name[:10] == str(exclude_date):
            continue
        try:
            with open(path, encoding='utf-8') as fh:
                texts.append(fh.read())
        except OSError:
            continue
    return _ledger_scan(texts)


def h41_candidates(history, ledger, report_date, holidays, effective):
    """이번 세션에 실을 H.4.1 회차(발표일 오름차순, 상한 3) + 밀린 경고."""
    end = cutoff(report_date)
    start = window(report_date, holidays)[0]
    pool = []
    for r in history:
        at = h41_release_at(dt.date.fromisoformat(r['release_date']))
        if at <= end and at > effective and r['release_date'] not in ledger:
            pool.append((at, r))
    pool.sort(key=lambda x: x[0])
    chosen = pool[:H41_CAP]
    overdue = [r['release_date'] for at, r in pool if (end - at).days > OVERDUE_DAYS]
    return [dict(r, late=not (start < at <= end)) for at, r in chosen], overdue


def qra_candidates(state_round, ledger, report_date, holidays, effective):
    """가장 최근 회차의 문서 중 이번 세션에 실을 것 — {kind: doc}."""
    if not state_round:
        return {}
    end = cutoff(report_date)
    start = window(report_date, holidays)[0]
    out = {}
    rnd = state_round['round']
    for kind, doc in (state_round.get('docs') or {}).items():
        if not doc or not doc.get('ok'):
            continue
        at = dt.datetime.fromisoformat(doc['released_at'])
        if at <= end and at > effective and f'{rnd}:{kind}' not in ledger:
            out[kind] = dict(doc, late=not (start < at <= end))
    if not ({'borrowing', 'refunding'} & set(out)):
        return {}           # TBAC 는 단독으로 싣지 않는다
    return out


# ── 표 ──────────────────────────────────────────────────────────────────

H41_HEAD = ['항목', '수요일 잔고', '잔고 주간 변화', '주간 평균 전주 대비', '전년 대비']


def h41_cells(rnd, key):
    r = rnd['rows'][key]
    wc = (rnd.get('flags') or {}).get('rows', {}).get(key, {}).get('wed_chg')
    return [ROW_KO[key], fmt_usd(r['wed']), fmt_usd(wc, signed=True) if wc is not None else '—',
            fmt_usd(r['chg_wk'], signed=True), fmt_usd(r['chg_yr'], signed=True)]


def _md(iso):
    d = dt.date.fromisoformat(iso[:10])
    return f'{d.month}/{d.day}'


def h41_caption(rnd):
    late = '지난 발표분 — ' if rnd.get('late') else ''
    w = (rnd.get('flags') or {}).get('window')
    z = (f'이례적 = {w["first"]} ~ {w["last"]} 수요일 잔고 주간 변화 {w["n"]}개 분포에서 2 표준편차 밖(자체 기준). '
         if w and w['n'] >= Z_MIN_N else '')
    return (f'{late}연준 H.4.1 {_md(rnd["release_date"])} 발표분. 잔고 기준 {_md(rnd["wednesday"])}(수요일), '
            f'주간 평균은 {_md(rnd["week_ended"])}까지 한 주. {z}출처: 연준 H.4.1')


QRA_HEAD = ['항목', '값']


def quarter_ko(q):
    """「October–December 2026」 → 「2026년 10-12월」."""
    m = re.match(r'(\w+)–(\w+) (\d{4})$', q or '')
    if not m or m.group(1) not in _MONTHS or m.group(2) not in _MONTHS:
        return q
    return f'{m.group(3)}년 {_MONTHS.index(m.group(1)) + 1}-{_MONTHS.index(m.group(2)) + 1}월'


def round_ko(round_name):
    """「2026 - 4th Quarter」 → 「2026년 4분기」."""
    m = _ROUND.search(round_name or '')
    return f'{m.group(1)}년 {_QNUM[m.group(2)]}분기' if m else round_name


def qra_rows(docs):
    """[(키, 셀들)] — 실리는 문서의 필드만."""
    out = []
    b = docs.get('borrowing')
    if b:
        out.append(('borrow', [f'{quarter_ko(b["quarter"])} 순차입 추정', fmt_usd(b['borrow_bn'] * 1000)]))
        out.append(('cash', [f'{quarter_ko(b["quarter"])} 말 현금잔고 가정', fmt_usd(b['cash_bn'] * 1000)]))
        if b.get('next'):
            out.append(('borrow_next', [f'{quarter_ko(b["next"]["quarter"])} 순차입 추정',
                                        fmt_usd(b['next']['borrow_bn'] * 1000)]))
    r = docs.get('refunding')
    if r:
        out.append(('total', ['이번 차환 총 발행', fmt_usd(r['total_bn'] * 1000)]))
        out.append(('refund', ['만기 상환분', fmt_usd(r['refund_bn'] * 1000)]))
        out.append(('new_cash', ['신규 조달', fmt_usd(r['new_cash_bn'] * 1000)]))
        for y, v in r['sizes_bn'].items():
            out.append((f'size_{y}', [f'{y}년물 발행 규모', fmt_usd(v * 1000)]))
    return out


def qra_caption(rnd_name, docs):
    late = '지난 발표분 — ' if any(d.get('late') for d in docs.values()) else ''
    when = ' · '.join(f'{ {"borrowing": "차입 추정", "refunding": "발행 계획", "tbac": "자문위원회 보고서"}[k]} '
                      f'{_md(d["released_at"])}' for k, d in docs.items())
    return f'{late}미 재무부 분기조달계획 {round_ko(rnd_name)} 회차. 발표: {when}. 출처: 미 재무부'


def h41_table_html(rnd):
    head = ''.join(f'<th>{h}</th>' for h in H41_HEAD)
    rows = ''.join(f'<tr data-liq-row="{k}">' + ''.join(f'<td data-label="{h}">{c}</td>'
                                                        for h, c in zip(H41_HEAD, h41_cells(rnd, k))) + '</tr>'
                   for k in TABLE_ROWS)
    return (f'<table data-h41-release="{rnd["release_date"]}">'
            f'<thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table>')


def qra_table_html(q, docs):
    head = ''.join(f'<th>{h}</th>' for h in QRA_HEAD)
    rows = ''.join(f'<tr data-liq-row="{k}">' + ''.join(f'<td data-label="{h}">{c}</td>'
                                                        for h, c in zip(QRA_HEAD, cells)) + '</tr>'
                   for k, cells in qra_rows(docs))
    return f'<table data-qra-table="{q["round"]}"><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table>'


def render_tables(book):
    """실을 표 전부(H.4.1 회차마다 하나 + QRA 하나). 작성자는 그대로 넣는다."""
    parts = []
    for rnd in (book.get('h41') or {}).get('candidates') or []:
        parts.append(f'<div class="tbl-scroll">{h41_table_html(rnd)}</div>\n'
                     f'<div class="caption">{h41_caption(rnd)}</div>\n')
    q = book.get('qra') or {}
    docs = q.get('candidates') or {}
    if docs:
        parts.append(f'<div class="tbl-scroll">{qra_table_html(q, docs)}</div>\n'
                     f'<div class="caption">{qra_caption(q["round_name"], docs)}</div>\n')
    return ''.join(parts)
