"""KR 기간 집계 — 세션 단위로 누적한다.

US 와 달리 업종·거래대금은 그날 스냅샷만 있고 과거 계열이 없다. 그래서 기간 파일이
날짜 키로 세션을 담고, 매 실행이 그날치를 **갈아끼운다**(upsert). 두 번 돌아도 두 번
더해지지 않고, 실패한 날은 다음 실행이 메운다.

수급은 확정치만 담는다. 잠정치를 섞으면 나중에 정정되면서 수치가 조용히 틀려진다
(2026-08-05 실측: 장중 +15,116 vs 확정 +14,464).
"""

LEADING_CAP = 5

MARKETS = ('KOSPI', 'KOSDAQ')
INDEX_NAMES = MARKETS          # 원장 지수 이름(kr_market_data.json indices 키와 같다)
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
    # 미판정(leading None — 올랐지만 상승 종목 비율을 못 읽었다)은 「주도 없음」과 다르다. 이름을 남겨 두어야
    # 같은 날 재수집 병합이 앞 실행의 판정을 지우지 않는다. 있을 때만 싣는다(평소 세션 모양은 그대로).
    und = [r for r in (kr_industry or []) if r.get('leading') is None and 'leading' in r and r.get('name')]
    und.sort(key=lambda r: -(r.get('change_pct') or 0))
    if und:
        out['leading_undecided'] = [r['name'] for r in und]

    for row in (kr_top_value or []):
        if row.get('label') is not None:
            out['top_value'][row['label']] = row.get('value') or 0
    return out


def _empty(v):
    return v in (None, {}, [], '')


def merge_session(existing, new):
    """같은 날 세션 재수집 — 있던 값을 지우지 않는다(2026-11-12). 결과는 new 세션이되:

    - new 의 flows 에 없는 시장은 existing 의 그 시장 flows 를 유지한다. flows 가 비지 않으면 flows_note 를 뺀다.
    - 업종 묶음(industry + leading_industries + leading_undecided)은 new 의 industry 하나로 고른다 — 비었으면
      전부 existing, 비지 않으면 전부 new(new 의 leading 이 빈 목록이어도 — 주도 업종이 없는 날은 정상이다).
      단 new 가 판정하지 못한 업종(leading_undecided) 가운데 existing 이 주도로 적어 둔 것은 그대로 주도로
      남긴다 — 미판정 재수집이 앞 실행의 판정을 지우지 못한다(순서는 new 등락률, 상위 LEADING_CAP).
    - 거래대금 묶음(top_value)은 new 가 비었으면 existing, 아니면 new 로 통째 교체.
    수집 실패는 빈 값([]·{})으로 오므로, 실패한 재실행이 앞선 정상 실행의 값을 지우지 못한다.
    확정 여부는 따로 보지 않는다 — 당일 잠정 수급은 애초에 세션에 들어오지 않는다(session_from).
    """
    if not existing:
        return new
    out = dict(new)
    flows = dict(existing.get('flows') or {})
    flows.update(new.get('flows') or {})
    out['flows'] = flows
    if flows:
        out.pop('flows_note', None)
    if _empty(new.get('industry')) and not _empty(existing.get('industry')):
        out['industry'] = existing.get('industry')
        out['leading_industries'] = existing.get('leading_industries') or []
        out.pop('leading_undecided', None)
        if existing.get('leading_undecided'):
            out['leading_undecided'] = existing['leading_undecided']
    elif new.get('leading_undecided'):
        was = existing.get('leading_industries') or []
        kept = [n for n in new['leading_undecided'] if n in was]
        if kept:
            ind = new.get('industry') or {}
            lead = list(dict.fromkeys(list(new.get('leading_industries') or []) + kept))
            lead.sort(key=lambda n: -(ind.get(n) or 0))
            out['leading_industries'] = lead[:LEADING_CAP]
            rest = [n for n in new['leading_undecided'] if n not in kept]
            if rest:
                out['leading_undecided'] = rest
            else:
                out.pop('leading_undecided', None)
    if _empty(new.get('top_value')) and not _empty(existing.get('top_value')):
        out['top_value'] = existing.get('top_value')
    return out


def upsert_session(agg, session):
    agg.setdefault('sessions', {})
    d = session.get('date')
    if d is None:
        return agg
    body = {k: v for k, v in session.items() if k != 'date'}
    agg['sessions'][d] = merge_session(agg['sessions'].get(d), body)
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

    # 시장별로 따로 센다. 「어느 한쪽이라도 있으면 확정 하루」로 세면 코스피만 확정된
    # 날이 「N일 확정치」에 들어가 양쪽 합계가 서로 다른 일수 위에 얹힌다
    # (2026-08-30 codex 검토).
    flows, per_market = {}, dict.fromkeys(MARKETS, 0)
    for d in dates:
        f = (sess[d].get('flows') or {})
        if not f:
            continue
        for mkt in f:
            if mkt in per_market:
                per_market[mkt] += 1
        for mkt, vals in f.items():
            tgt = flows.setdefault(mkt, dict.fromkeys(SIDES, 0))
            for s in SIDES:
                if vals.get(s) is not None:
                    tgt[s] += vals[s]
    out['flows'] = flows
    out['flows_sessions_by_market'] = per_market
    # 대표값은 «관측된 시장 모두가 확정된 날»이다 — 적게 잡는 쪽이 안전하다.
    # 그 기간에 아예 나타나지 않은 시장은 대표값을 0으로 끌어내리지 않되 missing 에 남는다.
    seen = [n for n in per_market.values() if n]
    n_flow = min(seen) if seen else 0
    out['flows_sessions'] = n_flow
    out['flows_note'] = '확정치만 합산'
    for mkt, n in per_market.items():
        if n < len(dates):
            out['missing'].append(f'flows.{mkt}: {len(dates) - n}일 잠정/결측')
    if any(n != n_flow for n in per_market.values()):
        out['missing'].append('flows: 시장별 확정 일수가 다르다 — 합계를 나란히 읽지 말 것')

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
    if dates and not (index_closes or {}):
        # 원장이 통째로 비면 지수 칸이 조용히 사라진다 — 이름이 없으니 아래 루프가
        # 한 번도 돌지 않는다(2026-08-30 codex 검토).
        out['complete'] = False
        out['missing'].append('indices: 지수 원장이 비었다')
    for name, series in (index_closes or {}).items():
        p = _pct(series or [], out['start_date'], out['end_date']) if dates else None
        if p is None:
            out['complete'] = False
            out['missing'].append(f'indices.{name}')
            continue
        window = [(d, v) for d, v in series if out['start_date'] <= d <= out['end_date']]
        if window[-1][0] != out['end_date']:
            # 끝값이 마지막 거래일 값이 아니면 성과표가 발행본과 갈린다.
            out['complete'] = False
            out['missing'].append(
                f"indices.{name}: {out['end_date']} 종가 없음 (원장 끝 {window[-1][0]})")
            continue
        idx[name] = {'pct': round(p, 4), 'end': window[-1][1]}
    out['indices'] = idx

    # 세션 날짜 × 지수의 빈 칸. 위 검사는 끝값·기준값만 보므로 중간 날 누락과 원장에 아예
    # 없는 지수는 complete 를 바꾸지 않은 채 지나간다. 발행 때 빠진 지수는 새벽 재수집으로
    # 자동 보완하지 않고 사람이 정정하므로 빈 칸을 이름 붙여 남긴다.
    # 기록만 — complete 는 그대로(미발행일의 일시 결측까지 막지 않는다). 「발행된 날」의 빈 칸에 대한
    # 주간 보류는 판 관리 enforce 가 건다(scripts/kr/versions_kr.hold_published_gaps). 매일 검증 알림이 읽는다.
    for name in sorted(set(INDEX_NAMES) | set(index_closes or {})):
        have = {d for d, v in (index_closes or {}).get(name) or [] if v is not None}
        for d in dates:
            if d not in have:
                out['missing'].append(f'indices.{name}.{d}')

    # leading_undecided_count: 그날 주도 여부를 판정하지 못한 업종 수(있을 때만) — 「주도 없음」과 구분한다.
    out['daily'] = [{'date': d,
                     'leading_industries': sess[d].get('leading_industries') or [],
                     **({'leading_undecided_count': len(sess[d]['leading_undecided'])}
                        if sess[d].get('leading_undecided') else {})}
                    for d in dates]
    return out
