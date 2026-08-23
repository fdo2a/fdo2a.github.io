"""Mechanical triggers: the part of "did anything change?" that must not be a judgment call.

An agent asked every evening whether a thesis moved will eventually find that it did.
These functions answer the numeric half of the question arithmetically, from today's
snapshot against the recorded past, so that on a quiet day the honest answer — nothing —
is produced by the machine rather than resisted by the writer.

The event half (a customer name, an order, a guidance revision) cannot be computed and
stays with the routine, but it is held to a stricter standard: primary sources only.

Every threshold here is deliberately loose. A trigger does not mean the grade moves; it
means the day is worth a human sentence. Tight thresholds would produce daily noise,
which is the failure this whole pipeline exists to prevent.

Pure — no network, no clock.

Design: docs/superpowers/specs/2026-08-24-thesis-watch-design.md
"""

TRIGGER_KEYS = (
    'consensus_swing',       # FY1 컨센이 크게 이동 — 밸류 재계산
    'consensus_floor',       # FY1 컨센 평균이 추정치 하단으로 수렴 — kill 후보
    'band_entry',            # 주가가 관심 밴드 진입
    'bear_proximity',        # 주가가 bear 시나리오 가치에 근접
    'dispersion_widening',   # 추정치 분산 확대 — 시장 합의 붕괴
)

SEVERITIES = ('info', 'watch', 'kill_candidate')

CONSENSUS_SWING_PCT = 20.0      # ±20% 이상 이동
CONSENSUS_FLOOR_PCT = 15.0      # 평균이 하단 대비 +15% 이내
BEAR_PROXIMITY_PCT = 10.0       # bear 가치 ±10% 이내
DISPERSION_WIDENING_PCT = 30.0  # high/low 비율이 30% 이상 확대
LOOKBACK_DAYS = 30
MIN_HISTORY_ROWS = 20           # 이보다 짧으면 되돌아볼 게 없다


def _pct_change(now, before):
    if now is None or before in (None, 0):
        return None
    return (now - before) / abs(before) * 100


def _ratio(snapshot):
    low, high = snapshot.get('eps_fy1_low'), snapshot.get('eps_fy1_high')
    if not low or not high or low <= 0:
        return None
    return high / low


def evaluate(today, past, fair_value, has_depth):
    """Triggers fired by today's numbers. Empty list is the expected daily result.

    `past` is the snapshot ~LOOKBACK_DAYS ago (None when history is too short), and
    `has_depth` gates every lookback comparison so a young log cannot manufacture swings.
    `fair_value` may be None, which disables only the price-based triggers.
    """
    hits = []
    price = today.get('price')
    eps = today.get('eps_fy1')

    # ── 컨센 급변 ──
    if has_depth and past:
        change = _pct_change(eps, past.get('eps_fy1'))
        if change is not None and abs(change) >= CONSENSUS_SWING_PCT:
            direction = '상향' if change > 0 else '하향'
            hits.append({
                'key': 'consensus_swing',
                'severity': 'watch',
                'value': round(change, 1),
                'message': f'FY1 컨센서스 EPS가 {LOOKBACK_DAYS}일간 {change:+.1f}% {direction}'
                           f' — 밸류에이션 재계산 대상',
            })

    # ── 하단 수렴 ──
    low = today.get('eps_fy1_low')
    if eps and low and low > 0:
        headroom = (eps - low) / low * 100
        if headroom <= CONSENSUS_FLOOR_PCT:
            hits.append({
                'key': 'consensus_floor',
                'severity': 'kill_candidate',
                'value': round(headroom, 1),
                'message': f'FY1 컨센 평균이 추정치 하단 대비 +{headroom:.1f}%까지 접근'
                           f' — 시장 합의가 약세 시나리오로 수렴 중',
            })

    # ── 밴드 진입 · Bear 근접 ──
    if fair_value and price is not None:
        if price <= fair_value['band2']:
            hits.append({
                'key': 'band_entry', 'severity': 'info', 'level': 'band2',
                'value': price,
                'message': f'주가가 2차 관심선({fair_value["band2"]:,}) 아래로 진입',
            })
        elif price <= fair_value['band1']:
            hits.append({
                'key': 'band_entry', 'severity': 'info', 'level': 'band1',
                'value': price,
                'message': f'주가가 1차 관심선({fair_value["band1"]:,}) 아래로 진입',
            })

        bear = fair_value['bear']
        if bear and abs(price - bear) / bear * 100 <= BEAR_PROXIMITY_PCT:
            hits.append({
                'key': 'bear_proximity', 'severity': 'watch', 'value': price,
                'message': f'주가가 Bear 시나리오 가치({bear:,}) ±{BEAR_PROXIMITY_PCT:.0f}% 안에'
                           f' 들어옴 — 시장이 약세 시나리오를 가격에 반영 중',
            })

    # ── 분산 확대 ──
    if has_depth and past:
        now_ratio, past_ratio = _ratio(today), _ratio(past)
        if now_ratio and past_ratio:
            widening = (now_ratio - past_ratio) / past_ratio * 100
            if widening >= DISPERSION_WIDENING_PCT:
                hits.append({
                    'key': 'dispersion_widening', 'severity': 'watch',
                    'value': round(widening, 1),
                    'message': f'FY1 추정치 분산이 {LOOKBACK_DAYS}일간 {widening:+.1f}% 확대'
                               f' (최고/최저 {past_ratio:.1f}배 → {now_ratio:.1f}배)'
                               f' — 시장 합의가 오히려 흩어지는 중',
                })

    return hits


def kill_axes(hits, event_axes=()):
    """Which of the two required kill axes today's evidence covers.

    Numeric triggers can only ever supply the price axis; the contract axis has to come
    from a disclosed event. That asymmetry is the point — a chart alone never kills.
    """
    axes = set(event_axes)
    if any(h['key'] in ('consensus_floor', 'bear_proximity') for h in hits):
        axes.add('price')
    return tuple(sorted(axes))
