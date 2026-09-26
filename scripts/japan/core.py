"""일본 주간 — 코어 6 지표, 커브, 자금흐름, 포지션, 주식 전달, 시나리오 신호. 순수.

한 줄의 질문: **일본이 금리 정상화를 계속할 수 있는 경제인가.** 사슬은
BOJ → JGB → 엔화·자금흐름 → 일본 기업. 여기서 계산하는 것은 그 사슬의 숫자이고, 해석은
작성자가 한다.

계약:
- 창은 두 개 — 1주(그 주 시작 전 마지막 값 대비), 4주(시작 21일 전보다 앞선 마지막 값 대비).
  **기준일(asof)은 행마다 따로** 둔다. JGB 는 도쿄 마감, 미 국채는 뉴욕 마감이라 같은 날이
  아니다(US `daily_row.py` 에서 날짜가 섞였던 전례).
- MOF 순취득은 + 가 순매수. 거주자의 해외채권 순매수는 **자금 유출**, 순매도가 「귀환」쪽이다.
- 헤지 후 미국채는 **근사**다 — 헤지 비용을 미 3개월 − JGB 1년으로 잡는다. 실제 비용은
  선물환 포인트와 통화 베이시스(수십 bp)를 포함한다. `approx: True` 를 게이트가 본문 라벨로 강제.
- 시나리오 신호는 1차에서 **코드가 정한 고정 집합**이다. 작성자가 기준을 고르지 않는다.

설계: 프로젝트 루트 plan.md 「2026-09-26 US 주간 재구성 + 일본 주간 리포트」.
"""
from datetime import date, timedelta

JGB_TENORS = ('2Y', '5Y', '10Y', '20Y', '30Y', '40Y')
EQUITY = (('Nikkei 225', '닛케이 225', None), ('TOPIX ETF', 'TOPIX', '1306'),
          ('TOPIX Banks ETF', '은행', '1615'), ('J-REIT ETF', 'REIT', '1343'),
          ('TOPIX Autos ETF', '자동차', '1622'))


def week_bounds(key):
    y, w = key.split('-W')
    mon = date.fromisocalendar(int(y), int(w), 1)
    return mon.isoformat(), (mon + timedelta(days=4)).isoformat()


def _before(rows, day):
    xs = [(d, v) for d, v in rows if d < day and v is not None]
    return xs[-1] if xs else None


def level_changes(rows, start, end):
    """rows [(date, v)] -> {value, asof, chg_1w, chg_4w} (레벨 차)."""
    upto = [(d, v) for d, v in rows if d <= end and v is not None]
    if not upto:
        return None
    asof, val = upto[-1]
    four = (date.fromisoformat(start) - timedelta(days=21)).isoformat()
    b1, b4 = _before(rows, start), _before(rows, four)
    return {'value': round(val, 4), 'asof': asof,
            'chg_1w': round(val - b1[1], 4) if b1 else None,
            'chg_4w': round(val - b4[1], 4) if b4 else None}


def _bp(x):
    return None if x is None else round(x * 100, 1)


def _pct(val, base):
    return None if base in (None, 0) or val is None else round((val / base - 1) * 100, 2)


def _price_changes(rows, start, end):
    lc = level_changes(rows, start, end)
    if not lc:
        return None
    b1 = lc['value'] - lc['chg_1w'] if lc['chg_1w'] is not None else None
    b4 = lc['value'] - lc['chg_4w'] if lc['chg_4w'] is not None else None
    return {'value': round(lc['value'], 3), 'asof': lc['asof'],
            'pct_1w': _pct(lc['value'], b1), 'pct_4w': _pct(lc['value'], b4)}


def _pctile(rows, end, n=250):
    xs = [v for d, v in rows if d <= end and v is not None][-n:]
    if len(xs) < 50:
        return None
    return round(100 * sum(1 for v in xs if v <= xs[-1]) / len(xs))


def _jgb_rows(snap, tenor):
    return [(r['date'], r.get(tenor)) for r in snap.get('jgb') or [] if r.get(tenor) is not None]


def _fred(snap, sid):
    return [(d, v) for d, v in (snap.get('fred') or {}).get(sid) or []]


def _price(snap, name, kind='daily'):
    return [(d, v) for d, v in ((snap.get('prices') or {}).get(name) or {}).get(kind) or []]


def _rate_row(rows, start, end, label):
    lc = level_changes(rows, start, end)
    if not lc:
        return None
    return {'label': label, 'value': round(lc['value'], 3), 'asof': lc['asof'],
            'chg_1w_bp': _bp(lc['chg_1w']), 'chg_4w_bp': _bp(lc['chg_4w']),
            'pctile_1y': _pctile(rows, end)}


def spread_rows(a, b):
    """두 금리 계열의 날짜 교집합 차이(a−b)."""
    bm = dict(b)
    return [(d, round(v - bm[d], 4)) for d, v in a if d in bm]


def leg_spread(us, jp, start, end, label):
    """두 다리를 **각자의** 최신값으로 뺀다. 날짜 교집합으로 계산하면 한쪽 휴장 주에
    공통 날짜가 사라져 「변화 0」이 나온다(2026-W39 실측 — 일본 9/21-23 연휴)."""
    a, b = level_changes(us, start, end), level_changes(jp, start, end)
    if not a or not b:
        return None

    def diff(x, y):
        return None if x is None or y is None else _bp(x - y)
    return {'label': label, 'value': round(a['value'] - b['value'], 3),
            'asof': min(a['asof'], b['asof']), 'asof_us': a['asof'], 'asof_jp': b['asof'],
            'chg_1w_bp': diff(a['chg_1w'], b['chg_1w']), 'chg_4w_bp': diff(a['chg_4w'], b['chg_4w']),
            'pctile_1y': _pctile(spread_rows(us, jp), end)}


def with_published_close(rows, us_agg, tenor):
    """FRED 는 하루 이틀 늦다. US 주간 집계에 그 주 발행본 종가가 있으면 최신점으로 붙인다."""
    if not us_agg:
        return rows
    y = (us_agg.get('yields') or {}).get(tenor) or {}
    end = us_agg.get('end_date')
    if y.get('end') is None or not end or (rows and rows[-1][0] >= end):
        return rows
    return list(rows) + [(end, y['end'])]


def yen_positioning(snap, end):
    c = (snap.get('cftc') or {}).get('097741') or {}
    rows = [r for r in c.get('rows') or [] if r['date'] <= end
            and r.get('lev_long') is not None and r.get('lev_short') is not None]
    if not rows:
        return None
    nets = [r['lev_long'] - r['lev_short'] for r in rows][-156:]
    last = rows[-1]
    out = {'date': last['date'], 'lev_net': nets[-1],
           'lev_net_chg': nets[-1] - nets[-2] if len(nets) > 1 else None,
           'pct_3y': round(100 * sum(1 for v in nets if v <= nets[-1]) / len(nets))}
    if len(nets) >= 5:
        out['lev_net_chg_4w'] = nets[-1] - nets[-5]
    if last.get('nc_long') is not None and last.get('nc_short') is not None:
        out['nc_net'] = last['nc_long'] - last['nc_short']
    return out


def _word(x):
    if x is None or x == 0:
        return None
    return '순매수' if x > 0 else '순매도'


def flows(snap, end):
    rows = [r for r in snap.get('mof_flows') or [] if r['week_end'] <= end]
    if not rows:
        return None
    last, four = rows[-1], rows[-4:]
    bonds = [r.get('res_foreign_ltdebt_net') for r in four if r.get('res_foreign_ltdebt_net') is not None]
    eq = [r.get('nonres_jp_equity_net') for r in four if r.get('nonres_jp_equity_net') is not None]
    out = {'week_start': last['week_start'], 'week_end': last['week_end'],
           'res_foreign_ltdebt_net': last.get('res_foreign_ltdebt_net'),
           'res_foreign_ltdebt_4w': sum(bonds) if len(bonds) == 4 else None,
           'net_selling_weeks_of_4': sum(1 for x in bonds if x < 0) if len(bonds) == 4 else None,
           'nonres_jp_equity_net': last.get('nonres_jp_equity_net'),
           'nonres_jp_equity_4w': sum(eq) if len(eq) == 4 else None,
           'res_foreign_equity_net': last.get('res_foreign_equity_net'),
           'unit': '억 엔',
           'recent': [{'week_end': r['week_end'], 'bonds': r.get('res_foreign_ltdebt_net'),
                       'jp_equity': r.get('nonres_jp_equity_net')} for r in four]}
    out['res_foreign_ltdebt_word'] = _word(out['res_foreign_ltdebt_net'])
    out['res_foreign_ltdebt_4w_word'] = _word(out['res_foreign_ltdebt_4w'])
    out['nonres_jp_equity_word'] = _word(out['nonres_jp_equity_net'])
    return out


def hedged_ust(snap, end, ust10_rows=None):
    def last(rows):
        xs = [(d, v) for d, v in rows if d <= end and v is not None]
        return xs[-1] if xs else None
    ust, bill = last(ust10_rows or _fred(snap, 'DGS10')), last(_fred(snap, 'DTB3'))
    j1, j10 = last(_jgb_rows(snap, '1Y')), last(_jgb_rows(snap, '10Y'))
    if not (ust and bill and j1 and j10):
        return None
    cost = round(bill[1] - j1[1], 3)
    hedged = round(ust[1] - cost, 3)
    return {'approx': True, 'ust_10y': ust[1], 'bill_3m': bill[1], 'jgb_1y': j1[1],
            'jgb_10y': j10[1], 'hedge_cost': cost, 'hedged_ust10': hedged,
            'gap_vs_jgb10': round(hedged - j10[1], 3),
            'asof': {'ust': ust[0], 'bill': bill[0], 'jgb': j10[0]}}


def equities(snap, start, end):
    out = []
    for name, label, code in EQUITY:
        pc = _price_changes(_price(snap, name), start, end)
        if pc:
            out.append({'name': name, 'label': label, 'code': code, **pc})
    base = next((e for e in out if e['name'] == 'TOPIX ETF'), None)
    for e in out:
        if base and e is not base and e.get('pct_4w') is not None and base.get('pct_4w') is not None:
            e['rel_topix_4w'] = round(e['pct_4w'] - base['pct_4w'], 2)
    return out


# 시나리오 A = 인상 지속(정상화 계속), B = 인상 중단. 기준은 코드에 고정 — 작성자가 고르지 않는다.
SIGNALS = (
    ('jgb2y_4w', 'JGB 2년 4주 변화', 'bp', 5.0,
     'BOJ 정책 기대에 가장 민감하다. 오르면 추가 인상을 가격에 넣는 중'),
    ('usjp2y_4w', '미·일 2년 금리차 4주 변화', 'bp', -10.0,
     '좁혀지면(음수) 엔 캐리 매력이 줄어 인상 지속과 같은 방향'),
    ('usdjpy_4w', '엔·달러 4주 변화', '%', -1.5,
     '엔 강세(음수)가 인상 지속과 같은 방향'),
    ('banks_rel_4w', '은행주 − TOPIX 4주', '%p', 2.0,
     '금리 수혜 업종이 앞서면 시장이 금리 상승 지속에 베팅'),
    ('yen_lev_4w', '엔 레버리지 순포지션 4주 변화', '계약', 0.0,
     '엔 매수 쪽으로 늘면 인상 지속 쪽'),
)


def _side(key, x, thr):
    if x is None:
        return '중립'
    if key in ('usjp2y_4w', 'usdjpy_4w'):
        if x <= thr:
            return 'A'
        if x >= -thr:
            return 'B'
        return '중립'
    if key == 'yen_lev_4w':
        return 'A' if x > 0 else ('B' if x < 0 else '중립')
    if x >= thr:
        return 'A'
    if x <= -thr:
        return 'B'
    return '중립'


def signals(core, eq, pos):
    val = {
        'jgb2y_4w': (core.get('jgb2y') or {}).get('chg_4w_bp'),
        'usjp2y_4w': (core.get('usjp2y') or {}).get('chg_4w_bp'),
        'usdjpy_4w': (core.get('usdjpy') or {}).get('pct_4w'),
        'banks_rel_4w': next((e.get('rel_topix_4w') for e in eq if e['name'] == 'TOPIX Banks ETF'), None),
        'yen_lev_4w': (pos or {}).get('lev_net_chg_4w'),
    }
    items = []
    for key, label, unit, thr, why in SIGNALS:
        items.append({'key': key, 'label': label, 'value': val[key], 'unit': unit,
                      'threshold': thr, 'side': _side(key, val[key], thr), 'why': why})
    tally = {'A': 0, 'B': 0, '중립': 0}
    for i in items:
        tally[i['side']] += 1
    return {'items': items, 'tally': tally}


def next_events(calendar, end, days=14):
    hi = (date.fromisoformat(end) + timedelta(days=days)).isoformat()
    return [e for e in (calendar or {}).get('events') or [] if end < e.get('date', '') <= hi]


def build(snap, calendar, key, us_agg=None):
    start, end = week_bounds(key)
    jgb2 = _jgb_rows(snap, '2Y')
    ust2 = with_published_close(_fred(snap, 'DGS2'), us_agg, '2Y')
    ust10 = with_published_close(_fred(snap, 'DGS10'), us_agg, '10Y')
    core = {
        'jgb10y': _rate_row(_jgb_rows(snap, '10Y'), start, end, 'JGB 10년'),
        'ust10y': _rate_row(ust10, start, end, '미 국채 10년'),
        'jgb2y': _rate_row(jgb2, start, end, 'JGB 2년'),
        'usjp2y': leg_spread(ust2, jgb2, start, end, '미·일 2년 금리차'),
        'usdjpy': _price_changes(_price(snap, 'USD/JPY'), start, end),
    }
    curve = [r for r in (_rate_row(_jgb_rows(snap, t), start, end, f'JGB {t[:-1]}년')
                         for t in JGB_TENORS) if r]
    j10, j30 = _jgb_rows(snap, '10Y'), _jgb_rows(snap, '30Y')
    tenthirty = _rate_row(spread_rows(j30, j10), start, end, 'JGB 10-30년 차')
    pos = yen_positioning(snap, end)
    eq = equities(snap, start, end)
    return {
        'key': key, 'start_date': start, 'end_date': end,
        'core': core, 'curve': curve, 'curve_10s30s': tenthirty,
        'flows': flows(snap, end), 'hedged': hedged_ust(snap, end, ust10),
        'positioning': pos, 'equities': eq,
        'signals': signals(core, eq, pos),
        'next_events': next_events(calendar, end),
        'fetch_status': {k: v for k, v in (snap.get('fetch_status') or {}).items()
                         if v != 'ok' and _japan_source(k)},
    }


def _japan_source(src):
    return src.startswith(('mof:', 'cftc:097741', 'fred:DGS2', 'fred:DGS10', 'fred:DTB3',
                           'price:JPY=X', 'price:^N225', 'price:1306', 'price:1615',
                           'price:1343', 'price:1622'))
