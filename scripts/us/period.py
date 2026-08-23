"""기간(주/월) 집계 — 순수 계산.

일간 data/*.json 은 매일 덮어쓰기라 기간 수익률이 없다. 여기서 dated close series 를
받아 다시 계산한다. 네트워크는 collect_market_data.py 가 맡는다.

기간 파일은 **기간 키로 나뉘어** 저장되므로(2026-W34.json / 2026-08.json) 주·달이 넘어가면
지난 기간 파일이 저절로 확정본이 된다 — 휴장 달력도, 동결 단계도 필요 없다.
"""

from datetime import date

GROUPS = ('indices', 'sectors', 'fx', 'commodities', 'memory', 'ai_infra')
BASKETS = ('memory', 'ai_infra')
BENCHMARK = 'S&P 500'
TENORS = ('2Y', '5Y', '10Y', '30Y')


def _d(s):
    y, m, dd = (int(x) for x in s.split('-'))
    return date(y, m, dd)


def week_key(d):
    y, w, _ = _d(d).isocalendar()
    return f'{y}-W{w:02d}'


def month_key(d):
    return d[:7]


def slice_series(series, start, end):
    return [(d, v) for d, v in series if start <= d <= end]


def pct_change(series, start, end):
    """직전 종가 대비 기간 수익률(%). 창 앞 종가가 없으면 None."""
    window = slice_series(series, start, end)
    if not window:
        return None
    before = [v for d, v in series if d < start]
    if not before:
        return None
    base, last = before[-1], window[-1][1]
    if not base:
        return None
    return (last / base - 1) * 100


def level_change(series, start, end):
    """금리처럼 레벨을 그대로 쓰는 계열 — (start_level, end_level, 변화)."""
    window = slice_series(series, start, end)
    if not window:
        return None, None, None
    before = [v for d, v in series if d < start]
    if not before:
        return None, None, None
    base = before[-1]
    return base, window[-1][1], window[-1][1] - base


def _bounds(closes, key, span):
    """기간에 실제로 존재한 거래일에서 start/end 를 뽑는다 — 날짜 산술을 쓰지 않는다."""
    keyer = week_key if span == 'weekly' else month_key
    dates = sorted({d for g in GROUPS for s in (closes.get(g) or {}).values()
                    for d, _ in (s or []) if keyer(d) == key})
    return (dates[0], dates[-1], len(dates)) if dates else (None, None, 0)


def build(span, key, closes, yields_hist, daily_headlines):
    start, end, sessions = _bounds(closes, key, span)
    out = {'span': span, 'key': key, 'start_date': start, 'end_date': end,
           'sessions': sessions, 'complete': True, 'missing': []}
    if start is None:
        out['complete'] = False
        out['missing'].append('no sessions in period')
        return out

    for g in GROUPS:
        rows = {}
        group_data = closes.get(g)
        if not group_data:
            out['complete'] = False
            out['missing'].append(f'{g}: group absent')
            out[g] = rows
            continue
        for name, series in group_data.items():
            p = pct_change(series or [], start, end)
            if p is None:
                out['complete'] = False
                out['missing'].append(f'{g}.{name}')
                rows[name] = None
                continue
            window = slice_series(series, start, end)
            before = [v for d, v in series if d < start]
            rows[name] = {'start': before[-1], 'end': window[-1][1], 'pct': round(p, 4)}
        out[g] = rows

    # 섹터 순위 — 좋은 것부터. 게이트가 이 rank 와 대조하므로 여기서 확정한다.
    ranked = sorted(((n, r['pct']) for n, r in (out.get('sectors') or {}).items() if r),
                    key=lambda x: -x[1])
    for i, (n, _) in enumerate(ranked, 1):
        out['sectors'][n]['rank'] = i

    spx = (out.get('indices') or {}).get(BENCHMARK)
    for g in BASKETS:
        vals = [r['pct'] for r in (out.get(g) or {}).values() if r]
        if vals:
            b = sum(vals) / len(vals)
            out[g]['basket_pct'] = round(b, 4)
            out[g]['basket_excess_pct'] = round(b - spx['pct'], 4) if spx else None

    yields = {}
    for tenor in TENORS:
        series = (yields_hist or {}).get(tenor)
        if not series:
            out['complete'] = False
            out['missing'].append(f'yields.{tenor}')
            continue
        s0, s1, chg = level_change(series, start, end)
        if chg is None:
            out['complete'] = False
            out['missing'].append(f'yields.{tenor}')
            continue
        yields[tenor] = {'start': s0, 'end': s1, 'chg_bp': round(chg * 100, 2)}
    out['yields'] = yields

    curve = {}
    for name, (short, long_) in (('spread_2s10s_bp', ('2Y', '10Y')),
                                 ('spread_5s30s_bp', ('5Y', '30Y'))):
        a, b = yields.get(short), yields.get(long_)
        if a and b:
            s0 = (b['start'] - a['start']) * 100
            s1 = (b['end'] - a['end']) * 100
            curve[name] = {'start': round(s0, 2), 'end': round(s1, 2), 'chg': round(s1 - s0, 2)}
    out['curve'] = curve

    out['daily'] = sorted((x for x in (daily_headlines or []) if start <= x['date'] <= end),
                          key=lambda x: x['date'])
    return out
