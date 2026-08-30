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
    """기간 창은 벤치마크(S&P 500) 거래일만으로 정한다 — 날짜 산술을 쓰지 않는다.

    다른 자산군(특히 FX)은 미국 주식 거래 달력을 공유하지 않아 주말 바를 들고
    올 수 있다. 벤치마크만이 권위 있는 미국 거래 달력이므로, 창을 union 이 아니라
    벤치마크 하나로 고정한다 — 다른 계열의 튄 날짜는 slice_series 가 창 밖이라
    알아서 잘라낸다.
    """
    keyer = week_key if span == 'weekly' else month_key
    series = (closes.get('indices') or {}).get(BENCHMARK)
    if not series:
        return None, None, 0
    dates = sorted({d for d, _ in series if keyer(d) == key})
    return (dates[0], dates[-1], len(dates)) if dates else (None, None, 0)


def build(span, key, closes, yields_hist, daily_headlines):
    start, end, sessions = _bounds(closes, key, span)
    out = {'span': span, 'key': key, 'start_date': start, 'end_date': end,
           'sessions': sessions, 'complete': True, 'missing': []}
    if start is None:
        out['complete'] = False
        if not (closes.get('indices') or {}).get(BENCHMARK):
            out['missing'].append(f'indices.{BENCHMARK}')
        else:
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

    # 자산군별 일별 계열 — 복기가 «구간별»로 채점하려면 기간 전체 수익률이 아니라
    # 등급이 유지된 구간의 수익률이 필요하다. 이것이 없으면 등급이 중간에 뒤집힌 주에
    # 두 판단이 다 맞았어도 서로 상쇄돼 0으로 나온다(2026-08-30 codex 검토).
    # 기간 시작 직전 종가를 한 점 앞에 붙여 첫 구간도 잴 수 있게 한다.
    def _window(series):
        if not series:
            return []
        before = [(d, v) for d, v in series if d < start]
        return (before[-1:] ) + slice_series(series, start, end)

    series_out = {}
    for key, group, name in (('equities', 'indices', BENCHMARK),
                             ('fx', 'fx', 'DXY'),
                             ('energy', 'commodities', 'WTI'),
                             ('metals', 'commodities', 'Gold')):
        w = _window(((closes.get(group) or {}).get(name)) or [])
        if len(w) >= 2:
            series_out[key] = [[d, v] for d, v in w]

    ty = _window((yields_hist or {}).get('10Y') or [])
    if len(ty) >= 2:
        # 금리는 레벨(%%)이다. 부호 뒤집기는 채점 쪽이 한다.
        series_out['bonds'] = [[d, v] for d, v in ty]

    spx_w = dict(_window(((closes.get('indices') or {}).get(BENCHMARK)) or []))
    for key in BASKETS:
        members = [(closes.get(key) or {}).get(n) for n in (closes.get(key) or {})]
        rows = [_window(m) for m in members if m]
        if not rows or not spx_w:
            continue
        dates = sorted(set.intersection(*[{d for d, _ in r} for r in rows]) & set(spx_w))
        if len(dates) < 2:
            continue
        base = {}
        for r in rows:
            m = dict(r)
            b = m.get(dates[0])
            if b:
                for d in dates:
                    base.setdefault(d, []).append(m[d] / b)
        b0 = spx_w[dates[0]]
        series_out[key] = [[d, round((sum(base[d]) / len(base[d]) - spx_w[d] / b0) * 100, 4)]
                           for d in dates if base.get(d)]

    out['series'] = series_out

    curve = {}
    for name, (short, long_) in (('spread_2s10s_bp', ('2Y', '10Y')),
                                 ('spread_5s30s_bp', ('5Y', '30Y'))):
        a, b = yields.get(short), yields.get(long_)
        if a and b:
            s0 = (b['start'] - a['start']) * 100
            s1 = (b['end'] - a['end']) * 100
            curve[name] = {'start': round(s0, 2), 'end': round(s1, 2), 'chg': round(s1 - s0, 2)}
    out['curve'] = curve

    # daily: 각 헤드라인에 spx_pct 추가 (그 세션의 S&P 500 % 변화)
    spx_series = ((closes.get('indices') or {}).get(BENCHMARK) or [])
    daily_rows = []
    for headline in (daily_headlines or []):
        if not (start <= headline['date'] <= end):
            continue
        row = dict(headline)
        # 그 날 S&P 종가 찾기
        day_close = next((v for d, v in spx_series if d == headline['date']), None)
        if day_close is None:
            # 그 날 바가 없으면 spx_pct = None
            row['spx_pct'] = None
        else:
            # 그 날 이전의 마지막 종가 찾기 (pct_change 관례 동일)
            prev_closes = [v for d, v in spx_series if d < headline['date']]
            if not prev_closes:
                # 이전 종가가 없으면 spx_pct = None
                row['spx_pct'] = None
            else:
                prev_close = prev_closes[-1]
                row['spx_pct'] = round((day_close / prev_close - 1) * 100, 4)
        daily_rows.append(row)
    out['daily'] = sorted(daily_rows, key=lambda x: x['date'])
    return out
