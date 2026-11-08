#!/usr/bin/env python3
"""다음 열흘을 **수집**하는 쪽 — 경제지표 일정(FRED)과 국채 입찰(Treasury).

`calendar.py` 가 계산으로 아는 것(만기·블랙아웃)을 맡고, 여기는 물어봐야 아는 것을 맡는다.
둘 다 `calendar.build(extra=…)` 로 들어간다.

**둘 다 비-코어다.** 실패하면 기록하고 건너뛴다 — 없는 일정을 지어내지 않고, 어제 받은
일정을 오늘 것처럼 인쇄하지도 않는다.
"""

import datetime as dt
import json
import urllib.parse
import urllib.request

from .calendar import event
from .census_calendar import CENSUS_NAMES, CENSUS_SERIES, CENSUS_TIME_ET
from .fred import _ssl_context

# --- A. 경제지표 일정 (FRED) --------------------------------------------------

# **release_id 를 코드에 박지 않는다.** 열세 개를 손으로 적으면 그것은 수집이 아니라
# 기억이고, 하나가 틀리면 다른 지표의 일정을 그 지표 이름으로 인쇄한다 — 화면에서는
# 안 보이는 오류다.
#
# 이름으로 거르지도 않는다(2026-11-07). 부분 문자열 매칭은 유사 이름 릴리스에 걸려
# 10/19-28 사이 15일 중 7일 GDP 를(「Debt to Gross Domestic Product Ratios」),
# 11/04-05 CPI 를 일정표에서 지웠고, 진짜가 창 밖인 날에는 유사 릴리스를 진짜 이름으로
# 인쇄할 수 있었다. 대신 대시보드가 이미 받는 **시리즈 하나**를 FRED 에 물어
# (`fred/series/release`) 그 시리즈가 속한 릴리스의 id 를 실행 때 얻고, 일정 행을
# **그 id 로만** 거른다. 시리즈 id 는 `collect_market_data.ECON` 과 같다(테스트가 묶는다).
RELEASE_SERIES = {
    'cpi': 'CPIAUCSL', 'employment': 'PAYEMS', 'pce': 'PCEPI',
    'gdp': 'A191RL1Q225SBEA', 'ppi': 'PPIFIS', 'claims': 'ICSA', 'jolts': 'JTSJOL',
    'industrial-production': 'INDPRO', 'existing-home-sales': 'EXHOSLUSM495S', 'michigan': 'UMCSENT',
}
# **Census 지표(소매·신규주택·내구재 + 일정 전용 넷)는 이 길로 오지 않는다**(2026-11-08). FRED 의
# 그 릴리스 달력에는 공식 발표가 아닌 날이 섞인다 — rid 95(M3)는 내구재 속보(8:30)와 전체
# 보고서(10:00)가 한 id 로 번갈아, rid 9(소매)는 2026-09-28, rid 27(주택착공)은 신규주택 판매일
# 10개와 1/27. API 는 날짜만 줘서 못 가른다. 그래서 날짜는 Census 일정표(`census_calendar`)에서 받고
# FRED 로 확인만 한다(`census_events`).
ALL_SERIES = {**RELEASE_SERIES, **CENSUS_SERIES}

# 한 FRED 릴리스를 함께 써도 되는 지표 — 같은 M3 릴리스의 속보(내구재)와 전체 보고서(공장주문).
# Census 표가 날짜를 가른다. 그 밖의 공유는 시리즈가 엇갈린 것으로 보고 둘 다 비운다.
SHARED_RELEASE_OK = frozenset({'durable-goods', 'factory-orders'})

# FRED 가 그 지표의 릴리스를 **다른 Census 지표의 발표일에도** 갱신하는 짝(2026-11-08 실측:
# rid 27 New Residential Construction 2026 달력의 공식 밖 11일 중 10일이 New Residential Sales 발표일,
# 1/27 은 Census 표에 아무 지표도 없는 날 — 그 창에서 주택착공은 빈다).
# `census_events` 가 FRED 쪽에만 있는 날을 「설명된 날」로 칠 수 있는 유일한 근거다.
FRED_CO_RELEASE = {'housing-starts': ('new-home-sales',)}

# 일정에만 나오는 Census 지표 — `macro_metrics.RELEASES` 에 없어 4축 표·발표 해부의 대상이 아니다
# (2026-11-08 설계 검토 #8). (티어, 기관, 한글명, 원문 URL) — `RELEASES` 와 같은 모양.
CALENDAR_ONLY = {
    'housing-starts': (2, 'Census', '주택착공',
                       'https://www.census.gov/construction/nrc/pdf/newresconst.pdf'),
    'trade-balance': (2, 'Census·BEA', '무역수지',
                      'https://www.census.gov/foreign-trade/Press-Release/current_press_release/ft900.pdf'),
    'construction-spending': (2, 'Census', '건설지출',
                              'https://www.census.gov/construction/c30/pdf/release.pdf'),
    'factory-orders': (2, 'Census', '공장주문',
                       'https://www.census.gov/manufacturing/m3/prel/pdf/s-i-o.pdf'),
}

# 풀린 릴리스 이름의 **확인 관문** — FRED 가 쓰는 릴리스 이름과 **정확히** 같아야 한다
# (대소문자·공백만 무시). 부분 문자열은 「Gross Domestic Product by Industry」 같은 유사
# 릴리스를 통과시킨다(codex 2026-11-07 구현 #1). 시리즈 id 오타·소속 이동으로 다른
# 릴리스가 돌아오면 여기서 걸려 `unresolved` 에 실제 이름과 함께 남는다 — 잘못 붙인
# 이름보다 빈 칸이 낫고, 빈 칸은 그 이유가 보인다.
#
# 출처: 전부 2026-11-08 FRED 시리즈 페이지(fred.stlouisfed.org/series/<id>)의
# 「Release:」 이름과 대조했다. cpi·gdp·retail-sales·claims 는 10·11월 Actions 로그의
# API 응답과도 같다. 이름으로 일정을 고르는 데는 쓰지 않는다.
RELEASE_NAMES = {
    'cpi': ('Consumer Price Index',),
    'employment': ('Employment Situation',),
    'pce': ('Personal Income and Outlays',),
    'retail-sales': ('Advance Monthly Sales for Retail and Food Services',),
    'gdp': ('Gross Domestic Product',),
    'ppi': ('Producer Price Index',),
    'claims': ('Unemployment Insurance Weekly Claims Report',),
    'jolts': ('Job Openings and Labor Turnover Survey',),
    'industrial-production': ('G.17 Industrial Production and Capacity Utilization',),
    'new-home-sales': ('New Residential Sales',),
    'existing-home-sales': ('Existing Home Sales',),
    'michigan': ('Surveys of Consumers',),
    # Census 경로의 FRED 확인용(같은 날 FRED 시리즈 페이지).
    'durable-goods': ("Manufacturer's Shipments, Inventories, and Orders (M3) Survey",),
    'factory-orders': ("Manufacturer's Shipments, Inventories, and Orders (M3) Survey",),
    'housing-starts': ('New Residential Construction',),
    'trade-balance': ('U.S. International Trade in Goods and Services',),
    'construction-spending': ('Construction Spending',),
}

# 해결 조회가 이만큼 실패하면 나머지는 묻지 않는다 — 호출마다 25초 타임아웃이라
# 13번 연속이면 5분이 넘는다(codex 2026-11-07 #5).
RESOLVE_MAX_FAILURES = 2

# FRED 는 **날짜만** 준다. 벽시계 시각은 발표 기관이 오래 고정해 둔 것이라 정적 표로
# 둔다(ET 기준, 서머타임과 무관한 «벽시계»다). 표에 없으면 `None` — 날짜만 인쇄하고
# 한국 시각을 지어내지 않는다.
RELEASE_TIME_ET = {
    'cpi': '08:30', 'employment': '08:30', 'ppi': '08:30', 'claims': '08:30',
    'retail-sales': '08:30', 'pce': '08:30', 'gdp': '08:30', 'durable-goods': '08:30',
    'industrial-production': '09:15',
    'jolts': '10:00', 'new-home-sales': '10:00', 'existing-home-sales': '10:00',
    'michigan': '10:00',
}

# 그 발표가 움직이는 자산. 티어 1 은 시장이 실제로 거래하는 프린트다.
RELEASE_ASSETS = {
    'cpi': ('금리', '달러', '주식'), 'employment': ('금리', '달러', '주식'),
    'pce': ('금리', '주식'), 'gdp': ('금리', '주식'), 'retail-sales': ('주식',),
    'ppi': ('금리',), 'claims': ('금리',), 'jolts': ('금리',),
    'trade-balance': ('달러', '금리'),
}


def _norm(name):
    return ' '.join((name or '').lower().split())


def name_fits(slug, name):
    """풀린 릴리스 이름이 그 슬러그의 것인가 — 확인 관문(정확 일치)."""
    return _norm(name) in {_norm(n) for n in RELEASE_NAMES.get(slug, ())}


def resolve_releases(lookup, series=None):
    """-> (resolved {slug: (release_id, name)}, unresolved {slug: 이유}).

    `lookup(series_id) -> (release_id, name)` 은 `FredClient.series_release`. 슬러그 하나가
    실패해도 나머지는 계속 묻는다. 키가 거부되거나 실패가 `RESOLVE_MAX_FAILURES` 번이면
    멈추고, 이미 푼 것은 그대로 둔다.
    """
    series = ALL_SERIES if series is None else series
    resolved, unresolved, failures, stop = {}, {}, 0, None
    for slug, sid in series.items():
        if stop:
            unresolved[slug] = f'조회 중단({stop})'
            continue
        try:
            rid, name = lookup(sid)
        except Exception as e:      # FredError 는 이미 살균돼 있다
            failures += 1
            unresolved[slug] = f'{sid} 조회 실패: {e}'
            if getattr(e, 'auth', False):
                stop = '키 거부'
            elif failures >= RESOLVE_MAX_FAILURES:
                stop = f'실패 {failures}회'
            continue
        if not name_fits(slug, name):
            unresolved[slug] = f'{sid} → 「{name}」 (그 지표의 릴리스가 아니다)'
            continue
        resolved[slug] = (rid, name)
    return resolved, unresolved


def _shared_conflicts(resolved):
    """-> {slug: 이유}. 두 지표가 한 FRED 릴리스로 풀렸는데 허락된 짝(`SHARED_RELEASE_OK`)이
    아니면 어느 쪽인지 모른다 — 둘 다 비운다."""
    by_id = {}
    for slug, (rid, _n) in (resolved or {}).items():
        by_id.setdefault(rid, []).append(slug)
    out = {}
    for rid, owners in by_id.items():
        if len(owners) > 1 and not set(owners) <= SHARED_RELEASE_OK:
            for slug in owners:
                out[slug] = f'다른 지표와 같은 릴리스 {rid}'
    return out


def release_events(rows, releases_meta, resolved):
    """-> (events, unresolved {slug: 이유}). `rows` 는 `FredClient.release_dates()` 의 결과.

    `resolved` 는 `resolve_releases()` 가 푼 것 — 여기 없는 슬러그는 **인쇄하지 않는다**
    (이름으로 짐작하지 않는다). `releases_meta` 는 `macro_metrics.RELEASES` — 티어·기관·
    한글명이 이미 거기 있다.
    """
    # 두 지표가 한 릴리스로 풀리면(허락된 Census 짝 말고) 어느 쪽인지 모른다 — 둘 다 비운다.
    unresolved = {s: w for s, w in _shared_conflicts(resolved).items() if s in RELEASE_SERIES}
    # Census 경로 지표는 여기서 인쇄하지 않는다(`census_events`). 남은 id 는 주인이 하나다.
    by_id = {rid: (slug, name) for slug, (rid, name) in (resolved or {}).items()
             if slug in RELEASE_SERIES and slug not in unresolved}

    hits = {}
    for day, rid, row_name in rows or ():
        owner = by_id.get(rid) if rid is not None else None
        if owner is None:
            continue
        slug, name = owner
        if _norm(row_name) != _norm(name):
            # 시리즈 조회와 일정 행이 같은 id 에 다른 이름을 댄다 — 어느 쪽도 믿지 않는다.
            unresolved[slug] = f'릴리스 {rid} 이름 불일치: 「{name}」 vs 「{row_name}」'
            continue
        hits.setdefault(slug, []).append(day)

    events = []
    for slug, days in hits.items():
        meta = releases_meta.get(slug)
        if slug in unresolved or not meta:
            continue
        tier, agency, label_ko, _url = meta
        for day in sorted(set(days)):
            events.append(event(
                f'release-{slug}-{day:%Y%m%d}', 'release', label_ko, day,
                time_et=RELEASE_TIME_ET.get(slug), status='confirmed',
                source=f'{agency} 공표 일정(FRED)',
                assets=RELEASE_ASSETS.get(slug, ('금리',)),
                watch='컨센서스 대비 서프라이즈' if tier == 1 else '추세 확인'))
    return events, unresolved


def _seen(census, slug):
    """Census 표에 보인 그 지표의 창 안 날짜(실을 수 없는 지표라도)."""
    slot = (census or {}).get(slug) or {}
    return set(slot.get('seen') or ()) | set(slot.get('dates') or {})


def census_events(census, rows, resolved, releases_meta):
    """-> (events, unresolved {slug: 이유}, notes {slug: 시각을 뺀 이유}). Census 지표의 일정.

    `census` 는 `census_calendar.collect()` 의 결과, `rows` 는 FRED 일정 행, `resolved` 는
    `resolve_releases()` 결과. 창 안의 Census 날짜마다 **같은 날 같은 FRED 릴리스 행**이 있어야
    한다 — 하나라도 없으면 그 지표 전체를 비운다(FRED 가 일정 변경을 늦게 반영하면 맞는 날짜도
    빈다 — 알고 고른 대가, plan.md 2026-11-08 #9). FRED 쪽에만 있는 날은 쓰지 않는다(공식 아닌
    날이 섞여 있다). 시각은 Census 값이다.
    """
    meta_all = {**CALENDAR_ONLY, **(releases_meta or {})}
    conflicts = _shared_conflicts(resolved)
    notes = {}
    fred_days = {}
    for day, rid, name in rows or ():
        if rid is not None:
            fred_days.setdefault(rid, {}).setdefault(day, set()).add(_norm(name))
    events, unresolved = [], {}
    for slug in CENSUS_NAMES:
        got = (census or {}).get(slug) or {'dates': {}, 'why': 'Census 일정표 결과가 없다'}
        if got.get('why'):
            unresolved[slug] = got['why']
            continue
        if slug in conflicts:
            unresolved[slug] = conflicts[slug]
            continue
        # 한 FRED id 를 나눠 쓰는 짝(내구재·공장주문)은 함께 산다 — 한쪽 Census 행이 의심스러우면
        # 그 행이 다른 쪽의 FRED 날짜를 「설명」해 누락을 가릴 수 있다(codex 11/08 구현 3회 #1).
        partner = [o for o in SHARED_RELEASE_OK if o != slug and slug in SHARED_RELEASE_OK
                   and ((census or {}).get(o) or {}).get('why')]
        if partner:
            unresolved[slug] = f'같은 FRED 릴리스를 쓰는 {partner[0]} 를 확인하지 못했다'
            continue
        # 짝이 같은 날에 겹치면 한쪽 날짜가 잘못 적힌 것이다 — 같은 id 라 FRED 가 못 가른다
        # (codex 11/08 구현 4회 #1). 2026·2027 표에서 두 지표는 한 번도 같은 날이 아니었다.
        if slug in SHARED_RELEASE_OK:
            mine = _seen(census, slug)
            both = sorted(d for o in SHARED_RELEASE_OK if o != slug for d in mine & _seen(census, o))
            if both:
                unresolved[slug] = f'같은 FRED 릴리스를 쓰는 짝과 {both[0]} 에 겹친다'
                continue
        if slug not in (resolved or {}):
            unresolved[slug] = f'FRED 확인용 시리즈 {CENSUS_SERIES[slug]} 를 풀지 못했다'
            continue
        rid, name = resolved[slug]
        dates = got.get('dates') or {}
        missing = [d for d in sorted(dates) if d not in fred_days.get(rid, {})]
        # 그날 그 id 의 행 이름이 **전부** 풀린 이름이어야 한다 — 하나라도 다르면 어느 쪽인지
        # 모른다(codex 11/08 구현 #4).
        wrong = [d for d in sorted(dates) if d in fred_days.get(rid, {})
                 and fred_days[rid][d] != {_norm(name)}]
        if missing:
            unresolved[slug] = f'Census {missing[0]} 가 FRED 릴리스 {rid} 일정에 없다'
            continue
        # 반대쪽: 창 안의 FRED 날짜는 Census 로 설명돼야 한다 — 그 id 를 쓰는 Census 지표의 날짜이거나
        # 알려진 동시 갱신(`FRED_CO_RELEASE`)의 날짜. 같은 달 두 번째 발표 행이 Census 표에서
        # 빠지면 월별 확인으로는 못 잡는다(codex 11/08 구현 2회 #1). 설명 못 하는 날이 있으면 비운다
        # — rid 9 의 2026-09-28(연간 개정 추정)이 창에 들면 소매판매는 그 창에서 빈다(조심하는 쪽).
        explained = set()
        for other, (orid, _n) in (resolved or {}).items():
            if orid == rid and other in CENSUS_NAMES:
                explained |= _seen(census, other)
        for other in FRED_CO_RELEASE.get(slug, ()):
            explained |= _seen(census, other)
        extra = [d for d in sorted(fred_days.get(rid, {})) if d not in explained]
        if extra:
            unresolved[slug] = (f'FRED 릴리스 {rid} 의 {extra[0]} 가 Census 표에 없다 — '
                                f'Census 행이 빠졌는지 알 수 없다')
            continue
        if wrong:
            unresolved[slug] = f'FRED 릴리스 {rid} 의 {wrong[0]} 행 이름이 「{name}」 이 아니다'
            continue
        meta = meta_all.get(slug)
        if not meta:
            unresolved[slug] = '지표 정보(티어·기관·이름)가 없다'
            continue
        tier, agency, label_ko, _url = meta
        for day in sorted(dates):
            clock = dates[day]
            if clock != CENSUS_TIME_ET.get(slug):
                notes[slug] = (f'Census {day} 시각 {clock} 가 평소 {CENSUS_TIME_ET.get(slug)} 와 '
                               f'다르다 — 날짜만 싣는다')
                clock = None
            events.append(event(
                f'release-{slug}-{day:%Y%m%d}', 'release', label_ko, day,
                time_et=clock, status='confirmed',
                source=f'{agency} 공표 일정(Census·FRED 대조)',
                assets=RELEASE_ASSETS.get(slug, ('금리',)),
                watch='컨센서스 대비 서프라이즈' if tier == 1 else '추세 확인'))
    return events, unresolved, notes


# --- B. 국채 입찰 (Treasury FiscalData) ---------------------------------------

AUCTIONS = ('https://api.fiscaldata.treasury.gov/services/api/fiscal_service'
            '/v1/accounting/od/auctions_query')
# 공고→입찰 리드타임은 실측 39건에서 중앙 4일·최대 7일이다(2026-09-14). 지평을 열흘로
# 잡아도 뒤쪽은 «아직 공고되지 않은» 구간이라 비어 있다 — 「입찰 없음」이 아니다.
ANNOUNCE_LEAD_DAYS = 7
_FIELDS = ('auction_date,issue_date,security_type,security_term,original_security_term,'
           'offering_amt,announcemt_date,high_yield,bid_to_cover_ratio,'
           'indirect_bidder_accepted,primary_dealer_accepted,total_accepted,'
           'total_tendered,closing_time_comp')


def auctions_url(start, end, page_size=200):
    q = [('fields', _FIELDS),
         ('filter', f'auction_date:gte:{start.isoformat()},'
                    f'auction_date:lte:{end.isoformat()}'),
         ('sort', 'auction_date'), ('page[size]', str(page_size))]
    # 대괄호는 그대로 보낸다 — FiscalData 가 `page[size]` 를 그 모양으로 읽는다.
    return AUCTIONS + '?' + urllib.parse.urlencode(q, safe='[]:,')


def fetch_auctions(start, end, opener=None, timeout=25):
    """-> [row]. 키가 필요 없다. 실패는 예외 — 호출부가 비-코어로 처리한다."""
    url = auctions_url(start, end)
    if opener is not None:
        body = opener(url, timeout)
    else:
        # 인증서 경로는 FRED 와 같은 것을 쓴다 — certifi 폴백이 이미 거기 있다.
        body = urllib.request.urlopen(
            url, timeout=timeout, context=_ssl_context()).read()
    return json.loads(body.decode('utf-8') if isinstance(body, bytes) else body
                      ).get('data') or []


def _num(value):
    """FiscalData 는 없는 값을 문자열 'null' 로 준다 — `float('null')` 은 터진다."""
    if value in (None, '', 'null'):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def term_label(row):
    """시장이 부르는 이름.

    재정증권은 **남은 만기**로, 쿠폰물은 **원래 만기**로 부른다(재무부 공고 관행).
    `original_security_term` 을 한 줄로 쓰면 6주 재정증권이 「52-Week」로 인쇄된다 —
    재발행 표시가 아니라 CUSIP 의 원래 만기라서 그렇다(실측 2026-09-14).
    """
    if (row.get('security_type') or '').lower() == 'bill':
        return row.get('security_term') or ''
    return row.get('original_security_term') or row.get('security_term') or ''


def closing_time_et(row):
    """-> 'HH:MM' | None. 경쟁입찰 마감 시각 = 그 입찰이 끝나는 시각.

    재무부가 행마다 실어 주는 값이라(`closing_time_comp`, 예: '01:00 PM') 지어내지
    않는다. 쿠폰물은 13:00, 재정증권은 11:30 이 흔하지만 **행마다 다르므로** 표를
    만들지 않고 그때그때 읽는다. 못 읽으면 None — 날짜만 인쇄한다.
    """
    raw = (row.get('closing_time_comp') or '').strip()
    try:
        return dt.datetime.strptime(raw, '%I:%M %p').strftime('%H:%M')
    except ValueError:
        return None


def auction_events(rows, start, end):
    """구간 안의 «앞으로 있을» 입찰. 결과가 아직 없는 행이 일정이다."""
    out = []
    for row in rows or ():
        try:
            day = dt.date.fromisoformat(row.get('auction_date') or '')
        except ValueError:
            continue
        if not start <= day <= end:
            continue
        label = term_label(row)
        amt = _num(row.get('offering_amt'))
        # 억 달러 단위. 십억으로 세고 0 을 붙이면 75억 달러가 「80억」이 된다.
        size = f' {amt / 1e8:,.0f}억 달러' if amt else ''
        out.append(event(
            f'auction-{day:%Y%m%d}-{label.replace(" ", "")}', 'auction',
            f'{label} 국채 입찰{size}', day,
            time_et=closing_time_et(row), status='confirmed', source='재무부 입찰 공고',
            assets=['금리'], watch='응찰배율과 간접 낙찰 비중'))
    return out


def auction_results(rows, report_date, lookback_days=7):
    """직전 입찰의 **수요**. 채권 섹션이 수급을 원인 후보로 들 때 쓸 값이다.

    비율을 여기서 만들지 않는다 — 응찰배율은 API 가 주고, 간접 낙찰 비중의 분모
    `total_accepted` 도 API 가 주는 필드다. 검산은 테스트가 한다.
    """
    floor = report_date - dt.timedelta(days=lookback_days)
    out = []
    for row in rows or ():
        try:
            day = dt.date.fromisoformat(row.get('auction_date') or '')
        except ValueError:
            continue
        btc = _num(row.get('bid_to_cover_ratio'))
        if not (floor <= day <= report_date) or btc is None:
            continue        # 결과가 아직 안 붙었다 ≠ 수요가 없었다
        accepted = _num(row.get('total_accepted'))
        indirect = _num(row.get('indirect_bidder_accepted'))
        dealer = _num(row.get('primary_dealer_accepted'))
        out.append({
            'date': day.isoformat(),
            'term': term_label(row),
            'type': row.get('security_type'),
            'offering_amt': _num(row.get('offering_amt')),
            'high_yield': _num(row.get('high_yield')),
            'bid_to_cover': btc,
            'indirect_pct': round(indirect / accepted * 100, 1)
            if indirect is not None and accepted else None,
            'dealer_pct': round(dealer / accepted * 100, 1)
            if dealer is not None and accepted else None,
        })
    return sorted(out, key=lambda r: r['date'], reverse=True)
