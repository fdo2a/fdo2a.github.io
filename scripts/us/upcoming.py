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
from .fred import _ssl_context

# --- A. 경제지표 일정 (FRED) --------------------------------------------------

# **release_id 를 코드에 박지 않는다.** 열세 개를 손으로 적으면 그것은 수집이 아니라
# 기억이고, 하나가 틀리면 다른 지표의 일정을 그 지표 이름으로 인쇄한다 — 화면에서는
# 안 보이는 오류다. 구간 전체를 한 번 받아 **이름으로** 거른다.
#
# 이름도 정확한 문자열을 외우지 않는다. FRED 가 표기를 바꾸면 조용히 0건이 되기
# 때문에, 바뀌어도 살아남는 **부분 문자열**로 맞춘다. 대신 한 슬러그가 서로 다른
# 릴리스 둘 이상에 걸리면 **버린다** — 잘못 붙인 이름은 빈 칸보다 나쁘다.
RELEASE_PATTERNS = (
    ('cpi', ('consumer price index',)),
    ('employment', ('employment situation',)),
    ('pce', ('personal income and outlays',)),
    ('retail-sales', ('retail and food services', 'retail sales')),
    ('gdp', ('gross domestic product',)),
    ('ppi', ('producer price index',)),
    ('claims', ('unemployment insurance weekly claims',)),
    ('jolts', ('job openings and labor turnover',)),
    ('industrial-production', ('industrial production',)),
    ('durable-goods', ('durable goods',)),
    ('new-home-sales', ('new residential sales',)),
    ('existing-home-sales', ('existing home sales',)),
    ('michigan', ('surveys of consumers',)),
)

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
}


def _match(name):
    """-> 슬러그 | None. 이름이 어느 발표문인가."""
    low = (name or '').lower()
    for slug, needles in RELEASE_PATTERNS:
        if any(n in low for n in needles):
            return slug
    return None


def release_events(rows, releases_meta):
    """-> (events, dropped). `rows` 는 `FredClient.release_dates()` 의 결과.

    `releases_meta` 는 `macro_metrics.RELEASES` — 티어·기관·한글명이 이미 거기 있다.
    새 메타데이터를 만들지 않는다.
    """
    by_slug = {}
    for day, rid, name in rows or ():
        slug = _match(name)
        if slug:
            by_slug.setdefault(slug, []).append((day, rid, name))

    events, dropped = [], []
    for slug, hits in by_slug.items():
        ids = {rid for _d, rid, _n in hits if rid is not None}
        if len(ids) > 1:
            # 같은 슬러그에 릴리스 둘 — 어느 쪽이 그 지표인지 모른다.
            dropped.append((slug, sorted({n for _d, _r, n in hits})))
            continue
        meta = releases_meta.get(slug)
        if not meta:
            continue
        tier, agency, label_ko, _url = meta
        for day, _rid, _name in sorted(hits):
            events.append(event(
                f'release-{slug}-{day:%Y%m%d}', 'release', label_ko, day,
                time_et=RELEASE_TIME_ET.get(slug), status='confirmed',
                source=f'{agency} 공표 일정(FRED)',
                assets=RELEASE_ASSETS.get(slug, ('금리',)),
                watch='컨센서스 대비 서프라이즈' if tier == 1 else '추세 확인'))
    return events, dropped


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
