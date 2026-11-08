"""기간 복기 스코어카드 — 매크로 전달경로 방향을 실현치로 채점한다.

**입력이 2026-09-19 에 스탠스 등급에서 매크로 전달경로로 바뀌었다** — 멀티에셋 섹션이
사용자 지시로 없어졌다. 방향이 곧 베팅이다. 메모리·AI 인프라는 «주식 대비 상대비중»이므로 절대수익이 아니라
초과수익으로 채점한다 — 절대수익으로 재면 그 판단이 아니라 시장 방향을 채점하게 된다.


main 의 `scorecard.py` 와 이름이 비슷하지만 재는 것이 다르다. 그쪽은 «등급 변경
하나하나»를 이후 20영업일 수익률로 채점하고, 이쪽은 «그 기간 내내 들고 있던 포지션»을
기간 실현치로 채점한다. 부호 규약(채권 확대 = 금리 하락 베팅)만 공유한다.
여기서 나온 숫자는 작성 에이전트가 만지지 않는다 (macro_metrics 의 z 와 같은 규율).
"""

import datetime as _dt

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
    """`when` 시점에 유효했던 방향 — 그 날짜 이하의 마지막 기록."""
    prior = [r for r in rows if (r.get('report_date') or '') <= when]
    if not prior:
        return None
    a = (prior[-1].get('transmission') or {}).get(key) or {}
    return a.get('direction')


def segments(macro_rows, start, end):
    """자산군별 [{grade, from, to}] — 기간 중 방향이 바뀌면 쪼갠다."""
    rows = sorted(macro_rows, key=lambda r: r.get('report_date') or '')
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
            g = ((r.get('transmission') or {}).get(key) or {}).get('direction')
            if g is not None and g != cur:
                segs.append({'grade': cur, 'from': since, 'to': d})
                cur, since = g, d
        segs.append({'grade': cur, 'from': since, 'to': end})
        out[key] = segs
    return out


def _threshold(key):
    return BP_THRESHOLD if key == 'bonds' else PCT_THRESHOLD


def _segment_realized(agg, key, frm, to):
    """등급이 유지된 구간의 실현치. (값, 구간정확여부). 계열이 없으면 (None, False)."""
    series = ((agg or {}).get('series') or {}).get(key)
    if not series or len(series) < 2:
        return None, False
    pts = [(d, v) for d, v in series]
    at_or_before = [v for d, v in pts if d <= frm]
    inside = [v for d, v in pts if frm < d <= to]
    if not at_or_before or not inside:
        return None, False
    a, b = at_or_before[-1], inside[-1]
    if key == 'bonds':
        # 금리는 레벨이다. 「롱 듀레이션(+) = 금리 하락 베팅」이므로 부호를 뒤집는다.
        return -((b - a) * 100), True
    if key in ('memory', 'ai_infra'):
        # 이미 초과수익(%p) 누적 계열이라 차분이 곧 구간 초과수익이다.
        return b - a, True
    if not a:
        return None, False
    return (b / a - 1) * 100, True


def score(macro_rows, agg):
    real = realized(agg)
    segs = segments(macro_rows, agg.get('start_date'), agg.get('end_date'))
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
            # 구간별 실현치. 계열이 있으면 그 구간만 재고, 없으면 기간 전체로 물러난다.
            # 물러난 경우에는 표식을 남긴다 — 등급이 중간에 뒤집힌 주에 두 판단이 다
            # 맞았어도 상쇄돼 0으로 나오던 자리다(2026-08-30 codex 검토).
            sr, exact = _segment_realized(agg, key, s['from'], s['to'])
            if sr is None:
                sr, exact = r, False
            if sr is None or abs(sr) < _threshold(key):
                units.append({'grade': gr, 'verdict': '무판정', 'weight': 0.0,
                              'realized': sr, 'segment_exact': exact})
                continue
            hit = (sr > 0) == (gr > 0)
            units.append({'grade': gr, 'verdict': '적중' if hit else '미스',
                          'weight': float(abs(gr)), 'realized': round(sr, 4),
                          'segment_exact': exact,
                          'signed': (1 if hit else -1) * abs(gr)})
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


# ---- 레짐 점검 (2026-11-08 새로 씀) ---------------------------------------------
#
# 「이 기간 새로 나온 지표가 그 발표 직전의 책과 같은 쪽이었나」를 성장·물가 따로 잰다.
# 입력은 새 발표 원장(`data/history/releases.jsonl`, `us.release_ledger`)이다 — 2026-11-08
# 전에는 아무도 쓰지 않는 `released` 필드로 발표를 골라 W40 이후 매주 「신규 발표 없음」이
# 나왔고, 물가 행을 성장축에 섞었다. 모르는 것은 끝까지 판정불가로 남긴다: 수집이 빠진
# 거래일, 마지막 날까지 안 보인 지표, 기간 경계에 걸친 날짜, 비교할 책이 없는 발표.
# When changing this: read `docs/superpowers/specs/2026-11-08-weekly-regime-ledger.md`.

REGIME_AXES = {
    'growth': (('Labor', 'Activity', 'Consumption'), {'개선': 1, '악화': -1, '보합': 0}),
    'inflation': (('Inflation',), {'재가속': 1, '둔화': -1, '교착': 0}),
}
UNDECIDED = '판정불가'
# 이보다 오래 관측되지 않은 지표는 수집 목록에서 뺀 것으로 본다 — 그 전까지는 「빠짐」이다.
RETIRE_DAYS = 35


def _d(s):
    try:
        return _dt.date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


def expected_days(start, end, holidays):
    """[start, end] 의 평일 − 주식시장 휴장일. 휴일표가 없거나 기간 끝까지 유효하지 않으면 None.

    채권만 쉬는 날(`us_bond`, 11/11 재향군인의 날)은 주식이 열려 브리프·수집이 돈다 — 기대일이다.
    """
    us = (holidays or {}).get('us') if isinstance(holidays, dict) else None
    a, b = _d(start), _d(end)
    if not isinstance(us, dict) or a is None or b is None:
        return None
    if not isinstance(us.get('valid_through'), str) or us['valid_through'] < end:
        return None
    dates = us.get('dates')
    # 목록이 없으면 「휴장일 없음」이 아니라 모른다 — 추수감사절이 기대일로 들어간다(codex 구현 #3).
    if not isinstance(dates, list) or any(_d(x) is None for x in dates):
        return None
    off = set(dates)
    out, cur = [], a
    while cur <= b:
        if cur.weekday() < 5 and cur.isoformat() not in off:
            out.append(cur.isoformat())
        cur += _dt.timedelta(days=1)
    return out


def _book_sign(rows, day, key):
    """`day` **전날까지** 쓰인 마지막 책의 그 축 값. 그날 책은 그날 발표를 보고 쓴 것이다."""
    prior = [r for r in rows if (r.get('report_date') or '') < day]
    if not prior:
        return None
    v = (prior[-1].get('regime') or {}).get(key)
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _window(row):
    """공식일이 있으면 그날 하나, 없으면 (since, detected_on] 의 모든 날. since 가 없으면 None."""
    if row.get('official_date'):
        return [row['official_date']]
    a, b = _d(row.get('since')), _d(row.get('detected_on'))
    if a is None or b is None or a >= b:
        return None
    out, cur = [], a + _dt.timedelta(days=1)
    while cur <= b:
        out.append(cur.isoformat())
        cur += _dt.timedelta(days=1)
    return out


def _empty_axis(note):
    return {'verdict': UNDECIDED, 'note': note, 'total': 0, 'scored': 0, 'agree': 0,
            'against': 0, 'flat': 0, 'neutral_book': 0, 'no_book': 0, 'no_trend': 0,
            'ratio': None, 'pct': None, 'lean': {'up': 0, 'down': 0, 'flat': 0},
            'stale': [], 'uncertain': []}


def _axis(key, ledger, macro_rows, start, end, last_day, universe, excluded):
    axes, signs = REGIME_AXES[key]
    out = _empty_axis(None)
    out['stale'] = sorted(n for n, (axis, last) in universe.items()
                          if axis in axes and n not in excluded and last < last_day)
    prints = []
    for r in ledger:
        if (r.get('kind') != 'release' or (r.get('role') or 'scored') != 'scored'
                or r.get('axis') not in axes or r.get('name') in excluded
                or (r.get('detected_on') or '') > end):
            continue
        days = _window(r)
        if days is None:
            if (r.get('detected_on') or '') >= start:
                out['uncertain'].append(r['name'])
            continue
        inside = [d for d in days if start <= d <= end]
        if not inside:
            continue
        if r.get('gap') or len(inside) != len(days):
            out['uncertain'].append(r['name'])
            continue
        book = {_book_sign(macro_rows, d, key) for d in days}
        if len(book) > 1:
            out['uncertain'].append(r['name'])
            continue
        prints.append((r, book.pop()))

    lean = out['lean']
    for r, b in prints:
        out['total'] += 1
        t = signs.get(r.get('trend'))
        if b is None:
            out['no_book'] += 1
        elif t is None:
            out['no_trend'] += 1
        elif b == 0:
            out['neutral_book'] += 1
            lean['up' if t > 0 else 'down' if t < 0 else 'flat'] += 1
        else:
            out['scored'] += 1
            out['agree' if t == b else 'against' if t == -b else 'flat'] += 1

    out['uncertain'] = sorted(set(out['uncertain']))
    if out['stale']:
        out['note'] = '마지막 거래일까지 수집되지 않은 지표가 있다'
    elif out['uncertain']:
        out['note'] = '발표일이 기간 경계에 걸쳐 어느 기간 것인지 가를 수 없다'
    elif not out['total']:
        out['note'] = '기간 중 새 발표 없음'
    elif out['no_book']:
        out['note'] = '발표 직전의 판단 기록이 없는 발표가 있다'
    elif out['scored']:
        ratio = out['agree'] / out['scored']
        out['ratio'], out['pct'] = round(ratio, 4), round(ratio * 100)
        out['verdict'] = '정합' if ratio >= 0.5 else '불일치'
    elif out['neutral_book']:
        out['verdict'] = '기준 보합'
        out['note'] = '발표 직전 판단이 보합이라 맞고 틀림 대신 기울기만 잰다'
    else:
        out['note'] = '방향을 읽을 수 없는 발표뿐이다'
    return out, prints


def regime_check(macro_rows, ledger_rows, start, end, holidays):
    """-> 축별 판정 + 최상위 요약. `ledger_rows` 는 새 발표 원장 전체."""
    rows = sorted((r for r in (macro_rows or []) if (r.get('report_date') or '') <= (end or '')),
                  key=lambda r: r.get('report_date') or '')
    regime = (rows[-1].get('regime') if rows else None) or {}
    ledger = [r for r in (ledger_rows or []) if isinstance(r, dict)]
    expected = expected_days(start, end, holidays)
    out = {'verdict': UNDECIDED, 'partial': False, 'regime': regime,
           'days_expected': len(expected) if expected is not None else None,
           'days_scanned': 0, 'missing_days': [], 'excluded_new': [], 'prints': []}

    scans = [r for r in ledger if r.get('kind') == 'scan'
             and start <= (r.get('report_date') or '') <= end]
    # 관측이 빈 scan 은 수집으로 치지 않는다(기록 단계도 쓰지 않지만 옛 줄·손 편집 대비).
    scanned = sorted({r['report_date'] for r in scans
                      if not r.get('baseline') and r.get('observed')})
    out['days_scanned'] = len(scanned)
    if expected is None:
        out['note'] = '휴장일 목록이 없거나 기간 끝까지 유효하지 않다'
    else:
        out['missing_days'] = [d for d in expected if d not in scanned]
        if out['missing_days']:
            out['note'] = '수집이 빠진 거래일이 있다'
    if expected is None or out['missing_days'] or not expected:
        out.setdefault('note', '기대 거래일이 없다')
        for key in REGIME_AXES:
            out[key] = _empty_axis(out['note'])
        return out

    out['excluded_new'] = sorted({r['name'] for r in ledger if r.get('kind') == 'baseline'
                                  and start <= (r.get('detected_on') or '') <= end})
    # 대상 = 기간 끝까지 **최근 RETIRE_DAYS 일** 안에 한 번이라도 관측된 채점 지표. 기간 안의
    # 관측만 세면 한 주 내내 빠진 지표가, 직전 수집만 보면 2주째 빠진 지표가 대상에서 사라져
    # 「새 발표 없음」이 된다(codex 구현 2·3회). 그런 지표는 마지막 관측이 마지막 기대일보다
    # 앞이라 stale 로 걸린다. 그 기간보다 오래 안 보인 이름은 목록에서 뺀 것으로 본다.
    floor = (_d(start) - _dt.timedelta(days=RETIRE_DAYS)).isoformat()
    universe = {}
    for s in ledger:
        d = s.get('report_date') or ''
        if s.get('kind') != 'scan' or s.get('baseline') or not (floor <= d <= end):
            continue
        for name, axis, role, *_ in s.get('observed') or []:
            if (role or 'scored') != 'scored':
                continue
            prev = universe.get(name, (axis, ''))
            universe[name] = (axis, max(prev[1], d))
    excluded = set(out['excluded_new'])
    known = {a for axes, _w in REGIME_AXES.values() for a in axes}
    # 채점 대상인데 축을 모르는 지표는 어느 축에서도 안 보인다 — 그 발표가 조용히 빠지고
    # 축이 「새 발표 없음」이 된다. 어느 축인지 모르니 둘 다 판정불가(codex 구현 #2).
    unknown = sorted({n for n, (axis, _l) in universe.items() if axis not in known and n not in excluded}
                     | {r['name'] for r in ledger if r.get('kind') == 'release'
                        and (r.get('role') or 'scored') == 'scored' and r.get('axis') not in known
                        and start <= (r.get('detected_on') or '') <= end})
    if unknown:
        out['unknown_axis'] = unknown
        out['note'] = '축을 알 수 없는 채점 대상 지표가 있다'
        for key in REGIME_AXES:
            out[key] = _empty_axis(out['note'])
        return out

    judged, shown = [], []
    for key in REGIME_AXES:
        out[key], prints = _axis(key, ledger, rows, start, end, expected[-1], universe, excluded)
        shown += prints
        if out[key]['verdict'] in ('정합', '불일치'):
            judged.append(out[key]['verdict'])
    out['prints'] = [{'name': r['name'], 'label_ko': r.get('label_ko') or r['name'],
                      'axis': r.get('axis'), 'ref_period': r.get('ref_period'),
                      'date': r.get('official_date'), 'trend': r.get('trend')}
                     for r, _b in sorted(shown, key=lambda p: (p[0].get('official_date')
                                                               or p[0].get('detected_on') or '',
                                                               p[0].get('name') or ''))]
    if judged:
        out['verdict'] = (judged[0] if len(set(judged)) == 1 else '엇갈림')
        out['partial'] = len(judged) < len(REGIME_AXES)
    elif any(out[k]['verdict'] == '기준 보합' for k in REGIME_AXES):
        out['verdict'] = '기준 보합'
    return out


# `trigger_hygiene` 는 2026-09-19 에 스탠스와 함께 없어졌다. 「오래 잠들어 있는 트리거」를
# 찾으려면 임계가 기계가 읽을 수 있는 형태여야 하는데(metric·op·value), 매크로의 `confirm`
# 은 산문이다 — 「Core PCE YoY가 3.0% 하회로 추가 둔화되거나 30Y가 5.05% 하회」. 이것을
# 파싱하는 것은 조건을 만들어 내는 것에 가깝다. 옮기지 않고 잃는 쪽을 택했다.


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
