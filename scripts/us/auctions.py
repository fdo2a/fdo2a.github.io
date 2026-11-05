#!/usr/bin/env python3
"""미 재무부 이표채 입찰 결과 — 수집·정규화·판정 (US 아침 브리프 「국채 입찰」 섹션).

출처는 TreasuryDirect TA_WS 다. FiscalData `auctions_query` 는 2026-10-22 입찰 뒤로 행이
끊겼는데(11-06 실측), 빈 목록은 예외가 아니라서 `calendar.json` 의 `recent_auctions` 가
2주 동안 조용히 0건이었다. 그래서 여기서는 **빈 결과를 실패로 센다** — 재정증권이 매주
입찰되므로 7일 창에 결과가 한 건도 없다는 것은 「입찰 없음」이 아니라 「못 받음」이다.

범위는 이표채(Note·Bond·TIPS·FRN)뿐이다. 재정증권은 주마다 네댓 번이라 데스크에는
잡음이다 — 대신 신선도 검사에는 쓴다.

수치는 전부 여기서 만든다. 작성자는 다시 계산하지 않고, 게이트는 이 값의 표시 문자열과
발행본을 맞댄다. WI(발행 전 거래) 금리가 없으므로 **테일은 만들지 않는다.**
"""

import datetime as dt
import json
import statistics
import urllib.request

from .fred import _ssl_context

BASE = 'https://www.treasurydirect.gov/TA_WS/securities/'
COUPON_TYPES = ('Note', 'Bond', 'TIPS', 'FRN')
HISTORY_DAYS = 800          # 분기 입찰(20·30년 TIPS 등)도 직전 여섯 번이 들어오는 폭
RECENT_DAYS = 7
AVG_N = 6
MIN_HIST = 3
# 「움직였다」고 볼 최소 폭. 응찰배율 0.05 와 딜러 비중 1%p 는 시장 기사가 「평균보다
# 높다/낮다」를 말하기 시작하는 폭이다 — 그 안쪽은 평균 수준으로 읽는다.
BTC_BAND = 0.05
DEALER_BAND_PP = 1.0

DEMAND_LABELS = ('수요 강함', '수요 약함', '평균 수준', '엇갈림')


class AuctionError(Exception):
    pass


def _get(path, opener=None, timeout=25):
    url = BASE + path
    if opener is not None:
        body = opener(url, timeout)
    else:
        body = urllib.request.urlopen(url, timeout=timeout, context=_ssl_context()).read()
    data = json.loads(body.decode('utf-8') if isinstance(body, bytes) else body)
    if not isinstance(data, list):
        raise AuctionError(f'TA_WS {path}: 목록이 아니다 ({type(data).__name__})')
    return data


def fetch_results(days, kind=None, opener=None):
    q = f'auctioned?format=json&days={int(days)}' + (f'&type={kind}' if kind else '')
    return _get(q, opener)


def fetch_announced(days=14, opener=None):
    return _get(f'announced?format=json&days={int(days)}', opener)


# --- 정규화 -------------------------------------------------------------------

def _num(v):
    if v in (None, '', 'null'):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _date(v):
    try:
        return dt.date.fromisoformat((v or '')[:10])
    except ValueError:
        return None


def kind_of(row):
    """-> 'nominal' | 'tips' | 'frn' | 'bill' | None. `type` 이 정본이다 —
    TIPS 는 securityType 이 Note/Bond 로 오므로 그것만 보면 명목채로 섞인다."""
    t = (row.get('type') or '').upper()
    if t == 'TIPS' or (row.get('inflationProtected') or '') == 'Yes':
        return 'tips'
    if t == 'FRN' or (row.get('floatingRate') or '') == 'Yes':
        return 'frn'
    if t in ('NOTE', 'BOND'):
        return 'nominal'
    if t in ('BILL', 'CMB') or (row.get('securityType') or '') == 'Bill':
        return 'bill'
    return None


def _years(term):
    """'10-Year' -> 10, '9-Year 10-Month' -> None (원래 만기는 정수 연이다)."""
    head = (term or '').split('-Year')[0]
    return int(head) if head.isdigit() and (term or '').strip() == f'{head}-Year' else None


def label_ko(kind, years, reopening):
    base = {'nominal': f'{years}년물', 'tips': f'{years}년 TIPS',
            'frn': f'{years}년 FRN'}[kind]
    return base + (' 재발행' if reopening else '')


def normalize(row):
    """TA_WS 한 행 -> dict | None (이표채가 아니거나 원래 만기를 못 읽으면 None)."""
    kind = kind_of(row)
    if kind not in ('nominal', 'tips', 'frn'):
        return None
    day = _date(row.get('competitiveAuctionCloseDate') or row.get('auctionDate'))
    years = _years(row.get('originalSecurityTerm') or row.get('securityTerm'))
    if day is None or years is None:
        return None
    reopening = (row.get('reopening') or '') == 'Yes'
    ind = _num(row.get('indirectBiddersCompetitiveParAwarded'))
    dirr = _num(row.get('directBiddersCompetitiveParAwarded'))
    pd = _num(row.get('primaryDealersCompetitiveParAwarded'))
    comp = sum(x for x in (ind, dirr, pd) if x is not None) \
        if None not in (ind, dirr, pd) else None

    def share(x):
        return round(x / comp * 100, 1) if comp else None

    out = {
        'date': day.isoformat(),
        'key': f'{kind}-{years}y',
        'kind': kind,
        'years': years,
        'reopening': reopening,
        'label_ko': label_ko(kind, years, reopening),
        'term': row.get('securityTerm'),
        'cusip': row.get('cusip'),
        'offering_amt': _num(row.get('offeringAmount')),
        'close_time_et': (row.get('competitiveAuctionCloseTime') or '').strip() or None,
        'bid_to_cover': _num(row.get('bidToCoverRatio')),
        'indirect_pct': share(ind),
        'direct_pct': share(dirr),
        'dealer_pct': share(pd),
    }
    if kind == 'frn':
        out['high_margin'] = _num(row.get('highDiscountMargin'))
        out['high_yield'] = None
    else:
        out['high_yield'] = _num(row.get('highYield'))
    return out


def has_result(item):
    """결과가 «다» 붙었는가 — 응찰배율·비중에 종류별 낙찰값(FRN 은 할인마진)까지.
    낙찰값이 비어 있으면 미도착으로 남긴다(codex 구현 검토 #9)."""
    rate = item.get('high_margin') if item.get('kind') == 'frn' else item.get('high_yield')
    return (item.get('bid_to_cover') is not None and item.get('dealer_pct') is not None
            and rate is not None)


# --- 비교·판정 -----------------------------------------------------------------

def _r(x, n):
    return round(x, n) if x is not None else None


def demand(btc_delta, dealer_delta):
    """고정 규칙(자체 기준). 차이는 **반올림한 값**(응찰 2자리·비중 1자리)으로 보고,
    경계는 포함한다 — +0.05 는 「높다」, -1.0%p 는 「낮다」. 하나라도 없으면 None."""
    if btc_delta is None or dealer_delta is None:
        return None
    b, d = round(btc_delta, 2), round(dealer_delta, 1)
    btc_up, btc_dn = b >= BTC_BAND, b <= -BTC_BAND
    pd_dn, pd_up = d <= -DEALER_BAND_PP, d >= DEALER_BAND_PP
    # 강한 신호 = 응찰배율 높음·딜러 비중 낮음, 약한 신호 = 그 반대. 한쪽만 움직이고
    # 다른 쪽이 평균 안이면 움직인 쪽으로 읽는다. 두 신호가 서로 반대면 엇갈림.
    pos, neg = btc_up + pd_dn, btc_dn + pd_up
    if pos and not neg:
        return '수요 강함'
    if neg and not pos:
        return '수요 약함'
    if not (pos or neg):
        return '평균 수준'
    return '엇갈림'


def compare(item, history):
    """`history` = 같은 key 의 결과 있는 입찰들(아무 순서). item 보다 앞선 것만 쓴다."""
    prior = sorted((h for h in history if h['key'] == item['key'] and has_result(h)
                    and h['date'] < item['date']), key=lambda h: h['date'], reverse=True)
    last = prior[:AVG_N]
    n = len(last)
    out = dict(item)
    out['n_hist'] = n
    if n:
        avg = {f: _r(statistics.fmean(h[f] for h in last), 2 if f == 'bid_to_cover' else 1)
               for f in ('bid_to_cover', 'indirect_pct', 'direct_pct', 'dealer_pct')}
    else:
        avg = None
    out['avg6'] = avg
    prev = prior[0] if prior else None
    out['prev_offering_amt'] = prev['offering_amt'] if prev else None
    out['prev_date'] = prev['date'] if prev else None
    if avg and has_result(item):
        out['btc_vs_avg'] = _r(item['bid_to_cover'] - avg['bid_to_cover'], 2)
        out['dealer_vs_avg_pp'] = _r(item['dealer_pct'] - avg['dealer_pct'], 1)
        out['indirect_vs_avg_pp'] = _r(item['indirect_pct'] - avg['indirect_pct'], 1)
    else:
        out['btc_vs_avg'] = out['dealer_vs_avg_pp'] = out['indirect_vs_avg_pp'] = None
    out['insufficient'] = n < MIN_HIST
    out['demand_ko'] = None if out['insufficient'] else demand(
        out['btc_vs_avg'], out['dealer_vs_avg_pp'])
    out['tail_bp'] = None
    out['tail_status'] = 'no_wi_source'
    return out


YIELD_TENOR = {('nominal', 2): '2Y', ('nominal', 5): '5Y', ('nominal', 10): '10Y',
               ('nominal', 30): '30Y'}


def yield_ref(item, yields, report_date):
    """그 만기의 그날 종가 행. 날짜가 report_date 가 아니면 붙이지 않는다."""
    tenor = YIELD_TENOR.get((item['kind'], item['years']))
    row = (yields or {}).get(tenor) if tenor else None
    if not row or row.get('date') != report_date or row.get('level') is None:
        return None
    return {'tenor': tenor, 'level': row.get('level'), 'bp': _r(row.get('bp'), 1),
            'date': row.get('date'), 'source': row.get('source')}


# --- 책 만들기 -----------------------------------------------------------------

def _closed_on(row):
    return _date(row.get('competitiveAuctionCloseDate') or row.get('auctionDate'))


def build(report_date, results, announced, yields=None, generated=None):
    """-> 책(dict). `results` = TA_WS auctioned 행 전부(재정증권 포함, 이력 포함),
    `announced` = TA_WS announced 행.

    **빈 결과는 실패다**: 재정증권은 매주 입찰되므로 report_date 까지 7일 창에 결과가
    한 건도 없으면 원천이 멈춘 것이다(2026-10-22 뒤 FiscalData 가 그랬다).
    **결과 미도착은 입찰 없음이 아니다**: report_date 에 마감이 공고된 이표채인데 결과가
    없으면 `pending` 에 두고 `complete` 를 끈다.
    """
    rd = report_date if isinstance(report_date, dt.date) else dt.date.fromisoformat(report_date)
    floor = rd - dt.timedelta(days=RECENT_DAYS)
    recent_any = [r for r in results or ()
                  if (d := _closed_on(r)) and floor <= d <= rd and _num(r.get('bidToCoverRatio'))]
    if not recent_any:
        raise AuctionError(f'{floor}~{rd} 에 결과가 붙은 입찰이 한 건도 없다 — 원천이 멈췄다')

    items, seen = [], set()
    for r in results or ():
        it = normalize(r)
        if it and has_result(it) and (it['cusip'], it['date']) not in seen:
            seen.add((it['cusip'], it['date']))
            items.append(it)

    def enrich(it):
        out = compare(it, items)
        out['yield_ref'] = yield_ref(out, yields, rd.isoformat())
        return out

    today = [enrich(it) for it in items if it['date'] == rd.isoformat()]
    recent = [enrich(it) for it in items if floor.isoformat() <= it['date'] < rd.isoformat()]

    expected, nxt = [], []
    for r in announced or ():
        it = normalize(r)
        if not it:
            continue
        if it['date'] == rd.isoformat():
            expected.append(it)
        elif rd.isoformat() < it['date'] <= (rd + dt.timedelta(days=10)).isoformat():
            nxt.append({k: it[k] for k in ('date', 'key', 'label_ko', 'offering_amt',
                                           'close_time_et', 'reopening')})
    got = {(t['cusip'], t['key']) for t in today}
    pending = [{'key': e['key'], 'label_ko': e['label_ko'], 'cusip': e['cusip']}
               for e in expected if (e['cusip'], e['key']) not in got]

    key = lambda t: (t['years'], t['kind'])  # noqa: E731
    return {
        'report_date': rd.isoformat(),
        'generated': generated,
        'source': 'TreasuryDirect TA_WS',
        'ok': True,
        'error': None,
        'complete': not pending,
        'pending': pending,
        'today': sorted(today, key=key),
        'recent': sorted(recent, key=lambda t: t['date'], reverse=True),
        'next': sorted(nxt, key=lambda t: t['date']),
        'rule': {'avg_n': AVG_N, 'min_hist': MIN_HIST, 'btc_band': BTC_BAND,
                 'dealer_band_pp': DEALER_BAND_PP},
    }


def failed(report_date, error, generated=None):
    return {'report_date': str(report_date), 'generated': generated,
            'source': 'TreasuryDirect TA_WS', 'ok': False, 'error': str(error)[:300],
            'complete': False, 'pending': [], 'today': [], 'recent': [], 'next': []}


# --- 표시 ---------------------------------------------------------------------
# 게이트와 렌더러가 **같은 함수**로 문자열을 만든다 — 둘이 따로 반올림하면 정상 표가 막힌다.

def fmt_size(amt):
    return f'{amt / 1e8:,.0f}억 달러' if amt else '—'


def fmt_rate(it):
    if it['kind'] == 'frn':
        v = it.get('high_margin')
        return f'할인마진 {v:.3f}%' if v is not None else '—'
    v = it.get('high_yield')
    if v is None:
        return '—'
    return (f'실질 {v:.3f}%' if it['kind'] == 'tips' else f'{v:.3f}%')


def _with_avg(v, avg, fmt):
    if v is None:
        return '—'
    return fmt(v) + (f' ({fmt(avg)})' if avg is not None else '')


def cells(it):
    # 표본이 짧으면 평균을 보이지 않는다 — 판정을 생략한 그 평균을 표가 대신 말하게 된다.
    avg = {} if it.get('insufficient') else (it.get('avg6') or {})
    pct = lambda x: f'{x:.1f}%'  # noqa: E731
    return [it['label_ko'], fmt_size(it.get('offering_amt')), fmt_rate(it),
            _with_avg(it.get('bid_to_cover'), avg.get('bid_to_cover'), lambda x: f'{x:.2f}배'),
            _with_avg(it.get('indirect_pct'), avg.get('indirect_pct'), pct),
            _with_avg(it.get('direct_pct'), avg.get('direct_pct'), pct),
            _with_avg(it.get('dealer_pct'), avg.get('dealer_pct'), pct),
            it.get('demand_ko') or '표본 부족']


HEAD = ['입찰', '규모', '낙찰', '응찰배율', '간접', '직접', '딜러', '판정']


def caption(book):
    ns = sorted({t['n_hist'] for t in book['today'] if not t.get('insufficient')})
    head = ''
    if ns:
        n = f'직전 {ns[0]}회' if len(ns) == 1 else '직전 ' + '·'.join(map(str, ns)) + '회'
        head = f'괄호는 같은 만기 {n} 평균. '
    short = ('같은 만기 입찰이 3회 미만인 행은 비교하지 않는다. '
             if any(t.get('insufficient') for t in book['today']) else '')
    return (head + short + '간접·직접·딜러는 경쟁입찰 낙찰액 중 비중. '
            f'판정은 응찰배율 ±{BTC_BAND:.2f}배와 딜러 비중 ±{DEALER_BAND_PP:.1f}%p 를 함께 본 '
            '자체 기준이다. 출처: 미 재무부 입찰 결과')


def render_table(book):
    """`today` 가 비면 ''. 작성자는 이 조각을 그대로 넣는다."""
    if not book.get('ok') or not book.get('today'):
        return ''
    head = ''.join(f'<th>{h}</th>' for h in HEAD)
    rows = ''.join(
        f'<tr data-auction-row="{t["key"]}">'
        + ''.join(f'<td data-label="{h}">{c}</td>' for h, c in zip(HEAD, cells(t)))
        + '</tr>' for t in book['today'])
    return (f'<div class="tbl-scroll"><table data-auction-table="{book["report_date"]}">'
            f'<thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table></div>\n'
            f'<div class="caption">{caption(book)}</div>\n')


# --- 일정표 어댑터 --------------------------------------------------------------

def _term_text(row):
    return row.get('securityTerm') or ''


def to_fiscal(row):
    """TA_WS 행 -> `upcoming.auction_events`·`auction_results` 가 읽는 FiscalData 모양.

    일정표 계약(재정증권 포함·마감 시각·키 형식)을 그대로 둔다. 비중 분모는 경쟁입찰
    낙찰액(세 부류 합)이다 — 예전 FiscalData `total_accepted` 와 다르다.
    """
    ind = _num(row.get('indirectBiddersCompetitiveParAwarded'))
    pd = _num(row.get('primaryDealersCompetitiveParAwarded'))
    dirr = _num(row.get('directBiddersCompetitiveParAwarded'))
    comp = ind + pd + dirr if None not in (ind, pd, dirr) else None
    kind = kind_of(row)
    hy = row.get('highDiscountMargin') if kind == 'frn' else row.get('highYield')
    if kind == 'bill':
        hy = row.get('highInvestmentRate') or row.get('investmentRate') or hy
    d = _closed_on(row)
    return {
        'auction_date': d.isoformat() if d else None,
        'security_type': row.get('securityType'),
        'security_term': _term_text(row),
        'original_security_term': row.get('originalSecurityTerm') or _term_text(row),
        'offering_amt': row.get('offeringAmount'),
        'announcemt_date': (row.get('announcementDate') or '')[:10] or None,
        'high_yield': hy if hy not in ('', None) else None,
        'bid_to_cover_ratio': row.get('bidToCoverRatio') or None,
        'indirect_bidder_accepted': ind,
        'primary_dealer_accepted': pd,
        'total_accepted': comp,
        'closing_time_comp': row.get('competitiveAuctionCloseTime'),
    }
