"""주간·월간 집계 — 원장을 굴려서 만든다.

US·KR 주간이 2026-08-30 에 배운 것을 그대로 따른다. **시세를 다시 받지 않는다.**
집계는 그날 발행본이 인쇄한 값이 쌓인 원장(`bond_market.jsonl`)을 굴린 것이라
성과표 끝값이 그 기간 마지막 발행본과 갈릴 수 없다. 재수집하면 갈린다.

기간 서사는 발행본에서, 성과표는 이 집계에서 — 소스가 갈리는 이유도 같다.
「이번 주 10년물 +12bp」는 5편의 하루 변화를 더해야 나오고, 그 덧셈을 에이전트에게
맡기면 언젠가 틀린다.
"""

from datetime import date, timedelta

from .credit import standing


def iso_week_key(d):
    y, w, _ = date.fromisoformat(str(d)).isocalendar()
    return f'{y}-W{w:02d}'


def month_key(d):
    return str(d)[:7]


def week_range(d):
    dd = date.fromisoformat(str(d))
    mon = dd - timedelta(days=dd.weekday())
    return mon.isoformat(), (mon + timedelta(days=6)).isoformat()


def month_range(d):
    dd = date.fromisoformat(str(d))
    first = dd.replace(day=1)
    nxt = (first + timedelta(days=32)).replace(day=1)
    return first.isoformat(), (nxt - timedelta(days=1)).isoformat()


def slice_rows(rows, start, end):
    """구간 안의 행을 **날짜순으로, 중복 없이** 돌려준다.

    정렬을 여기서 보장해야 하는 이유는 `_change()` 가 첫 행과 마지막 행을 구간의
    양 끝으로 그대로 쓰기 때문이다. 원장이 뒤섞여 들어오면 시작·끝이 뒤바뀐
    수익률이 조용히 나온다.
    """
    win = {}
    for r in rows:
        d = r.get('report_date') or ''
        if start <= d <= end:
            win[d] = r
    return [win[d] for d in sorted(win)]


def _get(row, path):
    node = row
    for k in path:
        node = (node or {}).get(k) if isinstance(node, dict) else None
    return node


def _change(rows, path, scale=100):
    """기간 시작 대비 끝. scale=100 이면 bp, scale=None 이면 % 수익률."""
    vals = [(r['report_date'], _get(r, path)) for r in rows]
    vals = [(d, v) for d, v in vals if v is not None]
    if len(vals) < 2:
        return None
    (d0, v0), (d1, v1) = vals[0], vals[-1]
    out = {'start': v0, 'end': v1, 'start_date': d0, 'end_date': d1,
           'sessions': len(vals)}
    if scale is None:
        out['pct'] = round((v1 / v0 - 1) * 100, 3) if v0 else None
    else:
        out['bp'] = round((v1 - v0) * scale, 1)
    out['min'] = round(min(v for _, v in vals), 4)
    out['max'] = round(max(v for _, v in vals), 4)
    return out


RATE_PATHS = [('us', '2Y'), ('us', '5Y'), ('us', '10Y'), ('us', '30Y'),
              ('de', '2Y'), ('de', '10Y'), ('de', '30Y'),
              ('jp', '10Y'), ('jp', '30Y'), ('gb', '10Y')]
CREDIT_KEYS = ['us_ig', 'us_hy', 'us_hy_ccc', 'euro_hy', 'em_sov', 'em_corp']
FX_KEYS = ['DXY', 'EURUSD', 'USDJPY', 'USDKRW']


def build(rows, start, end, etf_tickers=()):
    """기간 성과표. 원장 밖의 값은 하나도 만들지 않는다."""
    win = slice_rows(rows, start, end)
    if not win:
        return {'start': start, 'end': end, 'sessions': 0, 'complete': False}

    rates = {}
    for path in RATE_PATHS:
        ch = _change(win, path)
        if ch:
            rates['/'.join(path)] = ch
    credit = {}
    for k in CREDIT_KEYS:
        ch = _change(win, ('credit', k))
        if ch:
            # 발행본은 크레딧을 bp 로 인쇄한다. 렌더 시점에 ×100 하면 그 값이 어느
            # 집계 파일에도 없어서 게이트가 창작으로 잡는다(일간에서 겪은 것과 같다).
            ch['start_bp'] = round(ch['start'] * 100, 1)
            ch['end_bp'] = round(ch['end'] * 100, 1)
            credit[k] = ch
    fx = {}
    for k in FX_KEYS:
        ch = _change(win, ('fx', k), scale=None)
        if ch:
            fx[k] = ch
    etf = {}
    for t in etf_tickers:
        ch = _change(win, ('etf', t, 'close'), scale=None)
        if ch:
            etf[t] = ch
    move = _change(win, ('move',), scale=1)

    us10 = [_get(r, ('us', '10Y')) for r in win]
    us10 = [v for v in us10 if v is not None]

    return {
        'start': start, 'end': end,
        'first_session': win[0]['report_date'], 'last_session': win[-1]['report_date'],
        'sessions': len(win),
        'rates': rates, 'credit': credit, 'fx': fx, 'etf': etf, 'move': move,
        'us10y_standing': standing(us10, us10[-1], 'level') if us10 else None,
        # 「완전하다」는 세션이 세 개 있다는 뜻이 아니라 **구간의 양 끝을 덮는다**는
        # 뜻이다. 8월 3~5일 세 세션으로 8월 전체를 완전하다고 표시하면 안 된다.
        'complete': len(win) >= 3 and _covers(win, start, end),
        'coverage_gap_days': _gap_days(win, start, end),
    }


def _business_days(start, end):
    d, out = date.fromisoformat(start), 0
    last = date.fromisoformat(end)
    while d <= last:
        if d.weekday() < 5:
            out += 1
        d += timedelta(days=1)
    return out


def _gap_days(win, start, end):
    """구간 양 끝과 실제 첫·마지막 세션 사이에 빈 영업일이 며칠인가.

    구간 경계가 주말이면 음수가 나올 수 있으므로 0 에서 자른다 — 「-1 영업일이
    비어 있다」는 문장은 발행본에 나가면 안 된다.
    """
    first, last = win[0]['report_date'], win[-1]['report_date']
    return (max(0, _business_days(start, first) - 1),
            max(0, _business_days(last, end) - 1))


def _covers(win, start, end):
    head, tail = _gap_days(win, start, end)
    return head <= 1 and tail <= 1


def stance_changes(stance_rows, start, end):
    """기간 안에서 뷰가 실제로 움직인 지점만 뽑는다 — 복기의 재료.

    기준선은 **구간 시작 직전 행**이다. 구간 안 첫 행을 기준선으로 쓰면 금요일 0 에서
    월요일 1 로 움직인 변화가 주간 복기에서 통째로 사라진다.
    """
    win = slice_rows(stance_rows, start, end)
    out = []
    earlier = [r for r in stance_rows if (r.get('report_date') or '') < start]
    prev = earlier[-1] if earlier else None
    for r in win:
        for key, a in (r.get('assets') or {}).items():
            before = ((prev or {}).get('assets') or {}).get(key, {}).get('grade')
            if prev is not None and before is not None and a.get('grade') != before:
                out.append({'date': r['report_date'], 'axis': key,
                            'from': before, 'to': a['grade'], 'label': a.get('label')})
        prev = r
    return out
