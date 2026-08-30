"""채권 ETF — 프리미엄/디스카운트, 추정 플로우, 벤치마크 바스켓 분해.

EMP 는 개별 채권이 아니라 상품을 조합하므로 「채권시장 분석」만으로는 모자란다.
이름이 같아도 듀레이션 8년 A등급 ETF 와 듀레이션 5년 BBB 중심 ETF 는 다른 물건이다.

플로우는 발행사가 직접 주지 않으므로 우리가 원장을 쌓아 뺄셈으로 만든다 —
AUM 변화에서 NAV 수익률로 설명되는 부분을 걷어낸 잔여가 순유입이다. 근사이고,
근사라는 사실을 필드 이름(`flow_est_usd`)과 캡션에 남긴다.
"""

# 교보재용 고정 벤치마크. 실제 펀드의 책이 아니라 «분해를 어떻게 하는가»를 보여주는
# 예제라서 비중을 승계시키지 않는다 — 고정이어야 매일 같은 기준으로 읽힌다.
BENCHMARK = (
    ('AGG', 0.60, 'core'),
    ('IGOV', 0.15, 'fx'),
    ('EMB', 0.10, 'credit'),
    ('HYG', 0.10, 'credit'),
    ('TIP', 0.05, 'inflation'),
)


def premium_discount(price, nav):
    """종가 대비 NAV 괴리(%). + 면 프리미엄.

    채권 ETF 에서 이 값은 유동성 신호다 — 기초자산 거래가 얼어붙으면 벌어진다.
    """
    if price is None or nav in (None, 0):
        return None
    return round((price / nav - 1) * 100, 3)


def flow_estimate(aum_today, aum_prev, nav_return_pct):
    """ΔAUM 에서 시장 수익분을 걷어낸 잔여 = 추정 순유입(USD)."""
    if None in (aum_today, aum_prev, nav_return_pct):
        return None
    expected = aum_prev * (1 + nav_return_pct / 100.0)
    return round(aum_today - expected)


def duration_impact(duration, bp_move):
    """듀레이션 D 인 포지션이 금리 bp 변화에 받는 가격 충격(%).

    부호가 뒤집힌다 — 금리가 오르면 가격은 내린다. 이 한 줄이 채권 산술의 출발점이라
    발행본에서 매일 실제 숫자로 보여준다.
    """
    if duration is None or bp_move is None:
        return None
    return round(-duration * bp_move / 100.0, 3)


def basket_return(rows, weights=BENCHMARK):
    """벤치마크 바스켓의 하루 수익률과 종목별 기여."""
    total, contrib, missing = 0.0, [], []
    for ticker, w, bucket in weights:
        r = (rows.get(ticker) or {}).get('change_pct')
        if r is None:
            missing.append(ticker)
            continue
        c = w * r
        total += c
        contrib.append({'ticker': ticker, 'weight': w,
                        'weight_pct': round(w * 100, 1),   # 발행본이 인쇄하는 단위
                        'return_pct': r,
                        'contribution_pct': round(c, 4), 'bucket': bucket})
    return {
        'total_pct': round(total, 4),
        'contributions': sorted(contrib, key=lambda x: -abs(x['contribution_pct'])),
        'missing': missing,
        'complete': not missing,
    }


def attribution(rows, weights=BENCHMARK):
    """바스켓 수익률을 버킷별로 묶는다 — 오늘 수익이 어디서 왔는가.

    실제 펀드의 attribution 은 벤치마크 대비 초과수익을 요인별로 쪼개지만, 우리에겐
    책이 없다. 대신 «이 바스켓을 들고 있었다면 어느 조각이 벌었나»를 보여준다.
    버킷 이름은 그대로 실전 attribution 의 요인 이름이다.
    """
    br = basket_return(rows, weights)
    buckets = {}
    for c in br['contributions']:
        b = buckets.setdefault(c['bucket'], {'bucket': c['bucket'],
                                             'contribution_pct': 0.0, 'tickers': []})
        b['contribution_pct'] = round(b['contribution_pct'] + c['contribution_pct'], 4)
        b['tickers'].append(c['ticker'])
    br['buckets'] = sorted(buckets.values(), key=lambda x: -abs(x['contribution_pct']))
    return br
