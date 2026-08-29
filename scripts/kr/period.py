"""KR 기간 집계 — 세션 단위로 누적한다.

US 와 달리 업종·거래대금은 그날 스냅샷만 있고 과거 계열이 없다. 그래서 기간 파일이
날짜 키로 세션을 담고, 매 실행이 그날치를 **갈아끼운다**(upsert). 두 번 돌아도 두 번
더해지지 않고, 실패한 날은 다음 실행이 메운다.

수급은 확정치만 담는다. 잠정치를 섞으면 나중에 정정되면서 수치가 조용히 틀려진다
(2026-08-05 실측: 장중 +15,116 vs 확정 +14,464).
"""

LEADING_CAP = 5

MARKETS = ('KOSPI', 'KOSDAQ')
SIDES = ('foreign', 'institution', 'individual')


def session_from(kr_market, kr_flows, kr_industry, kr_top_value):
    date = (kr_market or {}).get('report_date')
    out = {'date': date, 'flows': {}, 'industry': {}, 'top_value': {},
           'leading_industries': [], 'extra_flows': {}, 'extra_flow_dates': []}

    for mkt in MARKETS:
        blk = (kr_flows or {}).get(mkt) or {}
        for row in (blk.get('rows') or []):
            d = row.get('date')
            if d is None:
                continue
            if d == date and blk.get('flows_provisional'):
                continue                      # 당일 잠정치는 버린다
            vals = {s: row.get(s) for s in SIDES}
            if d == date:
                out['flows'][mkt] = vals
            else:
                out['extra_flows'].setdefault(d, {})[mkt] = vals
    out['extra_flow_dates'] = sorted(out['extra_flows'])
    if not out['flows']:
        out['flows_note'] = '잠정치 제외'

    for row in (kr_industry or []):
        if row.get('name') is not None:
            out['industry'][row['name']] = row.get('change_pct')
    # leading 은 그날 절반가량(60행 중 30행)에 붙는 폭넓은-상승 플래그다. 하루 30개를
    # 그대로 담으면 주간 5일치가 150개가 되어 서술 재료가 못 된다 — 등락률 상위만 남긴다.
    lead = [r for r in (kr_industry or []) if r.get('leading') and r.get('name')]
    lead.sort(key=lambda r: -(r.get('change_pct') or 0))
    out['leading_industries'] = [r['name'] for r in lead[:LEADING_CAP]]

    for row in (kr_top_value or []):
        if row.get('label') is not None:
            out['top_value'][row['label']] = row.get('value') or 0
    return out


def upsert_session(agg, session):
    agg.setdefault('sessions', {})
    d = session.get('date')
    if d is None:
        return agg
    agg['sessions'][d] = {k: v for k, v in session.items() if k != 'date'}
    return agg


def _pct(series, start, end):
    window = [(d, v) for d, v in series if start <= d <= end]
    before = [v for d, v in series if d < start]
    if not window or not before or not before[-1]:
        return None
    return (window[-1][1] / before[-1] - 1) * 100


def finalize(agg, index_closes):
    sess = agg.get('sessions') or {}
    dates = sorted(sess)
    out = {'span': agg.get('span'), 'key': agg.get('key'),
           'start_date': dates[0] if dates else None,
           'end_date': dates[-1] if dates else None,
           'sessions': len(dates), 'complete': bool(dates), 'missing': []}

    flows, n_flow = {}, 0
    for d in dates:
        f = (sess[d].get('flows') or {})
        if not f:
            continue
        n_flow += 1
        for mkt, vals in f.items():
            tgt = flows.setdefault(mkt, dict.fromkeys(SIDES, 0))
            for s in SIDES:
                if vals.get(s) is not None:
                    tgt[s] += vals[s]
    out['flows'] = flows
    out['flows_sessions'] = n_flow
    out['flows_note'] = '확정치만 합산'
    if n_flow < len(dates):
        out['missing'].append(f'flows: {len(dates) - n_flow}일 잠정/결측')

    ind = {}
    for d in dates:
        for name, pct in (sess[d].get('industry') or {}).items():
            if pct is not None:
                ind.setdefault(name, []).append(pct)
    rows = {n: {'pct': round(sum(v) / len(v), 4), 'sessions': len(v)} for n, v in ind.items()}
    for i, (n, _) in enumerate(sorted(rows.items(), key=lambda x: -x[1]['pct']), 1):
        rows[n]['rank'] = i
    out['industry'] = rows

    tv = {}
    for d in dates:
        for name, val in (sess[d].get('top_value') or {}).items():
            tv[name] = tv.get(name, 0) + (val or 0)
    out['top_value'] = [{'name': n, 'value': v}
                        for n, v in sorted(tv.items(), key=lambda x: -x[1])]

    idx = {}
    for name, series in (index_closes or {}).items():
        p = _pct(series or [], out['start_date'], out['end_date']) if dates else None
        if p is None:
            out['complete'] = False
            out['missing'].append(f'indices.{name}')
            continue
        idx[name] = {'pct': round(p, 4), 'end': series[-1][1]}
    out['indices'] = idx

    out['daily'] = [{'date': d,
                     'leading_industries': sess[d].get('leading_industries') or []}
                    for d in dates]
    return out
