"""기간 복기 스코어카드 — 스탠스 등급 부호를 실현치로 채점한다.

등급이 곧 방향 베팅이다. 메모리·AI 인프라는 «주식 대비 상대비중»이므로 절대수익이 아니라
초과수익으로 채점한다 — 절대수익으로 재면 그 판단이 아니라 시장 방향을 채점하게 된다.


main 의 `scorecard.py` 와 이름이 비슷하지만 재는 것이 다르다. 그쪽은 «등급 변경
하나하나»를 이후 20영업일 수익률로 채점하고, 이쪽은 «그 기간 내내 들고 있던 포지션»을
기간 실현치로 채점한다. 부호 규약(채권 확대 = 금리 하락 베팅)만 공유한다.
여기서 나온 숫자는 작성 에이전트가 만지지 않는다 (macro_metrics 의 z 와 같은 규율).
"""

ASSET_KEYS = ('equities', 'bonds', 'fx', 'energy', 'metals', 'memory', 'ai_infra')
PCT_THRESHOLD = 0.5      # 이보다 작은 움직임은 잡음 — 점수를 주지 않는다
BP_THRESHOLD = 3.0


def realized(agg):
    """자산군 → 등급 부호와 같은 방향으로 정렬된 실현치."""
    def g(d, *path):
        cur = d
        for p in path:
            cur = (cur or {}).get(p)
        return cur

    tenner = g(agg, 'yields', '10Y', 'chg_bp')
    return {
        'equities': g(agg, 'indices', 'S&P 500', 'pct'),
        # 롱 듀레이션(+) = 금리 하락 베팅이므로 부호를 뒤집는다
        'bonds': (-tenner) if tenner is not None else None,
        'fx': g(agg, 'fx', 'DXY', 'pct'),
        'energy': g(agg, 'commodities', 'WTI', 'pct'),
        'metals': g(agg, 'commodities', 'Gold', 'pct'),
        'memory': g(agg, 'memory', 'basket_excess_pct'),
        'ai_infra': g(agg, 'ai_infra', 'basket_excess_pct'),
    }


def _grade_at(rows, key, when):
    """`when` 시점에 유효했던 등급 — 그 날짜 이하의 마지막 기록."""
    prior = [r for r in rows if (r.get('report_date') or '') <= when]
    if not prior:
        return None
    a = (prior[-1].get('assets') or {}).get(key) or {}
    return a.get('grade')


def segments(stance_rows, start, end):
    """자산군별 [{grade, from, to}] — 기간 중 등급이 바뀌면 쪼갠다."""
    rows = sorted(stance_rows, key=lambda r: r.get('report_date') or '')
    out = {}
    for key in ASSET_KEYS:
        opening = _grade_at(rows, key, start)
        if opening is None:
            continue
        segs, cur, since = [], opening, start
        for r in rows:
            d = r.get('report_date') or ''
            if not (start < d <= end):
                continue
            g = ((r.get('assets') or {}).get(key) or {}).get('grade')
            if g is not None and g != cur:
                segs.append({'grade': cur, 'from': since, 'to': d})
                cur, since = g, d
        segs.append({'grade': cur, 'from': since, 'to': end})
        out[key] = segs
    return out


def _threshold(key):
    return BP_THRESHOLD if key == 'bonds' else PCT_THRESHOLD


def score(stance_rows, agg):
    real = realized(agg)
    segs = segments(stance_rows, agg.get('start_date'), agg.get('end_date'))
    assets, num, den, judged, neutral, total = {}, 0.0, 0.0, 0, 0, 0

    for key in ASSET_KEYS:
        if key not in segs:
            continue
        total += 1
        r = real.get(key)
        # 구간별 실현치를 따로 재려면 일별 계열이 필요하다. 기간 집계만 있는 지금은
        # 기간 실현치를 모든 구간에 공통으로 적용하고, 가중치만 |등급| 로 나눈다.
        units = []
        for s in segs[key]:
            gr = s['grade']
            if gr == 0:
                continue
            if r is None or abs(r) < _threshold(key):
                units.append({'grade': gr, 'verdict': '무판정', 'weight': 0.0})
                continue
            hit = (r > 0) == (gr > 0)
            units.append({'grade': gr, 'verdict': '적중' if hit else '미스',
                          'weight': float(abs(gr)), 'signed': (1 if hit else -1) * abs(gr)})
        if not units:
            neutral += 1
            assets[key] = {'grade': 0, 'realized': r, 'verdict': '중립', 'segments': segs[key]}
            continue
        w = sum(u['weight'] for u in units)
        if w == 0:
            assets[key] = {'grade': units[0]['grade'], 'realized': r,
                           'verdict': '무판정', 'segments': segs[key]}
            continue
        signed = sum(u.get('signed', 0) for u in units)
        judged += 1
        num += signed
        den += w
        assets[key] = {'grade': units[-1]['grade'], 'realized': r,
                       'verdict': '적중' if signed > 0 else '미스',
                       'score': round(signed / w, 4), 'segments': segs[key]}

    out = {'start_date': agg.get('start_date'), 'end_date': agg.get('end_date'),
           'key': agg.get('key'), 'assets': assets, 'judged': judged,
           'neutral': neutral, 'total': total,
           'neutral_share': round(neutral / total, 4) if total else None,
           'weighted': round(num / den, 4) if den else None}
    if not den:
        out['note'] = '판정 가능한 포지션 없음'
    return out


_AXIS_SIGN = {'개선': 1, '악화': -1, '보합': 0}


def regime_check(macro_rows, macro_metrics, start, end):
    prints = [i for i in ((macro_metrics or {}).get('indicators') or [])
              if start <= (i.get('released') or '') <= end]
    rows = sorted(macro_rows or [], key=lambda r: r.get('report_date') or '')
    regime = (rows[-1].get('regime') if rows else None) or {}
    if not prints:
        return {'verdict': '판정불가', 'prints': 0, 'regime': regime,
                'note': '기간 중 신규 발표 없음'}
    growth = regime.get('growth') or 0
    agree = 0
    for i in prints:
        s = _AXIS_SIGN.get(i.get('direction'), 0)
        if s == 0:
            continue
        # 성장축이 마이너스면 악화 프린트가 정합, 플러스면 개선이 정합, 0이면 상쇄가 정합
        if growth == 0 or (s > 0) == (growth > 0):
            agree += 1
    ratio = agree / len(prints)
    verdict = '정합' if ratio >= 0.5 else '불일치'
    return {'verdict': verdict, 'prints': len(prints), 'agree': agree,
            'ratio': round(ratio, 4), 'regime': regime}


def trigger_hygiene(stance_rows, end, stale_days=20):
    """발동한 트리거와, 오래 잠들어 있는(=임계가 너무 빡빡한) 조건."""
    rows = sorted(stance_rows or [], key=lambda r: r.get('report_date') or '')
    recent = [r for r in rows if (r.get('report_date') or '') <= end]
    dormant, seen = [], {}
    for r in recent:
        for key, a in (r.get('assets') or {}).items():
            for direction in ('increase', 'decrease'):
                for t in ((a.get('triggers') or {}).get(direction) or []):
                    sig = (key, direction, t.get('metric'), t.get('op'), t.get('value'))
                    seen.setdefault(sig, 0)
                    seen[sig] += 1
    for (key, direction, metric, op, value), days in seen.items():
        if days >= stale_days:
            dormant.append({'asset': key, 'direction': direction, 'metric': metric,
                            'op': op, 'value': value, 'days': days})
    dormant.sort(key=lambda x: -x['days'])
    return {'dormant': dormant, 'stale_days': stale_days}


def rollup(history_rows, spans=(4, 12)):
    rows = [r for r in (history_rows or []) if r.get('weighted') is not None]
    rows.sort(key=lambda r: r.get('key') or '')
    out = {}
    for n in spans:
        tail = rows[-n:]
        out[f'last_{n}'] = {
            'periods': len(tail),
            'weighted': round(sum(r['weighted'] for r in tail) / len(tail), 4) if tail else None,
            'insufficient': len(tail) < n,
        }
    out['all'] = {'periods': len(rows),
                  'weighted': round(sum(r['weighted'] for r in rows) / len(rows), 4)
                  if rows else None,
                  'insufficient': len(rows) < 2}
    return out
