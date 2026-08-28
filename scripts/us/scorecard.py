"""§9 스탠스가 실제로 맞았는지 재는 성적표.

승계되는 판단 구조를 만들어 놓고 그것이 도움이 되는지 재지 않으면, 일관되게
틀리고 있어도 알 수가 없다. 이 모듈은 `stance.json`의 `history`에 남은 등급 변경
하나하나에 그 뒤 실제 가격을 붙여 «그 포지션이 돈을 벌었나»를 셈한다.

**대부분의 날에는 아무 말도 하지 않는다.** 등급 변경이 MIN_SAMPLE건에 못 미치면
`sufficient: False`만 돌려주고, 발행 게이트가 인용을 막는다 — thesis 파이프라인이
`history.jsonl` 20행 미만에서 되돌아보기 트리거를 자동으로 끄는 것과 같은 규율이다.
표본 여덟 개로 적중률을 인쇄하는 것은 성적표가 아니라 소음이다.

부호 규약이 이 모듈의 전부라고 해도 된다. 「채권 비중 확대」는 금리가 **내려야**
맞은 것이고, 그 뒤집힘을 놓치면 성적표가 정확히 거꾸로 나온다.
"""

MIN_SAMPLE = 20        # 이만큼 쌓이기 전에는 아무 말도 하지 않는다
HORIZON = 20           # §9의 시계가 2~6주이므로 20영업일

# (자산 키, 벤치마크 티커, 부호) — 부호는 «등급이 +일 때 이 벤치마크가 오르면
# 맞은 것인가»다. 채권만 -1: 비중 확대는 금리 하락에 베팅한 것이다.
BENCHMARKS = (
    ('equities', '^GSPC', 1),
    ('bonds', '^TNX', -1),
    ('fx', 'DX-Y.NYB', 1),
    ('energy', 'CL=F', 1),
    ('metals', 'GC=F', 1),
)
_BENCH = {k: (t, s) for k, t, s in BENCHMARKS}

# 메모리·AI 인프라 등급은 절대 비중이 아니라 **주식 대비 상대 비중**이다. 시장과
# 같이 오른 것은 맞힌 것이 아니므로 벤치마크를 뺀 초과수익으로 채점한다.
RELATIVE = (
    ('memory', ('MU', 'WDC', 'STX'), '^GSPC', 1),
    ('ai_infra', ('MRVL', 'COHR', 'LITE', 'GEV', 'VRT'), '^GSPC', 1),
)
_REL = {k: (tickers, bench, sign) for k, tickers, bench, sign in RELATIVE}


def _common_calendar(dates, tickers):
    """Sessions every one of these series actually has. None if any is missing."""
    sets = []
    for t in tickers:
        d = (dates or {}).get(t)
        if not d:
            return None
        sets.append(set(d))
    return sorted(set.intersection(*sets)) if sets else None


def _forward(closes, dates, ticker, start_date, horizon, calendar=None):
    """Change from the first session on/after start_date to `horizon` sessions later.

    With `calendar`, both endpoints are taken from that shared session list, so every
    leg of a basket is measured over exactly the same days.
    """
    d = (dates or {}).get(ticker)
    c = (closes or {}).get(ticker)
    if not d or not c or len(d) != len(c):
        return None
    by_date = dict(zip(d, c))
    if calendar is None:
        calendar = d
    at = next((i for i, x in enumerate(calendar) if x >= start_date), None)
    if at is None or at + horizon >= len(calendar):
        return None
    a, b = by_date.get(calendar[at]), by_date.get(calendar[at + horizon])
    if a is None or b is None:
        return None
    if ticker.startswith('^') and ticker in ('^TNX', '^TYX', '^FVX'):
        return float(b - a) * 100          # 금리는 bp 변화
    return None if not a else (float(b) / float(a) - 1) * 100


def score_change(entry, closes, dates, horizon=HORIZON):
    """One grade change scored against what the market then did.

    None when there is nothing to score: the bootstrap row, a move to neutral (no
    position is being taken), an asset with no declared benchmark, or a change too
    recent to have a full forward window yet.
    """
    asset = (entry or {}).get('asset')
    to = (entry or {}).get('to')
    if not asset or asset == '*' or to is None or to == 0:
        return None
    if asset in _REL:
        tickers, bench_ticker, sign = _REL[asset]
        # 다리마다 제 시작일을 고르게 두면 서로 다른 기간을 견주게 되고, 하루만
        # 어긋나도 없던 초과수익이 만들어진다(2026-08-28 codex 실측). 공통 거래일
        # 위에서만 재고, 한 종목이라도 빠지면 바스켓이 말없이 줄어드니 포기한다.
        cal = _common_calendar(dates, list(tickers) + [bench_ticker])
        if cal is None:
            return None
        legs = [_forward(closes, dates, t, entry.get('date'), horizon, calendar=cal)
                for t in tickers]
        base = _forward(closes, dates, bench_ticker, entry.get('date'), horizon, calendar=cal)
        if base is None or any(x is None for x in legs):
            return None
        fwd = sum(legs) / len(legs) - base
        ticker = f'{bench_ticker} 대비 바스켓'
    else:
        bench = _BENCH.get(asset)
        if not bench:
            return None
        ticker, sign = bench
        fwd = _forward(closes, dates, ticker, entry.get('date'), horizon)
        if fwd is None:
            return None
    # 등급의 부호 x 자산 규약 x 실제 움직임. 양수면 그 포지션이 옳았다.
    direction = 1 if to > 0 else -1
    return {
        'date': entry.get('date'),
        'asset': asset,
        'grade': to,
        'benchmark': ticker,
        'forward': round(fwd, 3),
        'score': round(direction * sign * fwd, 3),
    }


def build(history, closes, dates, horizon=HORIZON, min_sample=MIN_SAMPLE):
    """The whole record. `sufficient` is the only field a caller may act on first."""
    scored = [s for s in (score_change(e, closes, dates, horizon) for e in history or []) if s]
    by_asset = {}
    for s in scored:
        row = by_asset.setdefault(s['asset'], {'scored': 0, 'hits': 0, 'total': 0.0})
        row['scored'] += 1
        row['hits'] += 1 if s['score'] > 0 else 0
        row['total'] += s['score']
    for row in by_asset.values():
        row['hit_rate'] = round(row['hits'] / row['scored'] * 100, 1)
        row['avg_score'] = round(row['total'] / row['scored'], 3)
        del row['total']
    hits = sum(1 for s in scored if s['score'] > 0)
    return {
        'horizon_sessions': horizon,
        'min_sample': min_sample,
        'scored': len(scored),
        'sufficient': len(scored) >= min_sample,
        'hit_rate': round(hits / len(scored) * 100, 1) if scored else None,
        'by_asset': by_asset,
        'changes': scored,
    }
