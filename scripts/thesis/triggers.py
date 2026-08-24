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
    'consensus_floor',       # FY1 컨센 평균이 추정치 하단으로 «내려앉은 날» — kill 후보
    'bear_proximity',        # 주가가 bear 시나리오 가치권에 «들어선 날»
    'bear_exit',             # 주가가 bear 가치권 «위로 벗어난 날» — 회복도 사건이다
    'dispersion_widening',   # 추정치 분산 확대 — 시장 합의 붕괴
)

# 여기 없는 것: `band_entry`. 주가가 1·2차 관심선 아래에 있는 것은 상태이지 사건이
# 아니다. 수준 검사로 두면 조건이 유지되는 내내 매일 울리고, 그러면 오케스트레이터가
# 「트리거도 사건도 없는 날은 아무것도 하지 않는다」는 조용한 경로에 영영 못 들어간다.
# 그 위치는 watch.json의 `position.in_band1`·`in_band2`가 이미 상시 들고 있고,
# 페이지가 그대로 보여준다.

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


def _headroom(snapshot):
    """평균 FY1 EPS가 추정치 하단보다 몇 % 위인가. 작을수록 약세 시나리오에 가깝다."""
    eps, low = snapshot.get('eps_fy1'), snapshot.get('eps_fy1_low')
    if not eps or not low or low <= 0:
        return None
    return (eps - low) / low * 100


def _bear_zone(price, bear):
    """bear 가치 대비 오늘의 위치: 'above' | 'in' | 'below'. 모르면 None.

    bear가 0 이하면 판정하지 않는다 — 적자 구간에서는 정규화이익법이 음수 가치를 낼 수
    있고, 그러면 ±10% 띠의 위아래가 뒤집혀 조용히 반대로 읽힌다.
    """
    if price is None or not bear or bear <= 0:
        return None
    edge = bear * BEAR_PROXIMITY_PCT / 100
    if price > bear + edge:
        return 'above'
    if price < bear - edge:
        return 'below'
    return 'in'


def _ratio(snapshot):
    low, high = snapshot.get('eps_fy1_low'), snapshot.get('eps_fy1_high')
    if not low or not high or low <= 0:
        return None
    return high / low


def evaluate(today, past, fair_value, has_depth, prev=None):
    """Triggers fired by today's numbers. Empty list is the expected daily result.

    `past` is the snapshot ~LOOKBACK_DAYS ago (None when history is too short), and
    `has_depth` gates every lookback comparison so a young log cannot manufacture swings.
    `fair_value` may be None, which disables only the price-based triggers.

    `prev` is **yesterday's history row** — its numbers and the lines they were judged
    against. Everything that describes a standing condition is answered as a *crossing*
    against it: fired on the day the state changes, silent for as long as it holds. A
    level check would ring every day until the condition lifted, and a bell that rings
    every day is a bell nobody hears. Without `prev` (a ticker's first day, or a history
    row from before these lines were recorded) those triggers stay quiet — the page still
    shows where the price stands.

    Note the crossing compares each day against *that day's own* lines. When collapsing
    estimates lift the bear value up to a flat price, the state genuinely changed and it
    fires once, saying so. That is a real deterioration, not an artifact.
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

    # ── 하단 수렴 — 오늘 내려앉았고, 평균이 실제로 내려왔을 때만 ──
    headroom, was = _headroom(today), _headroom(prev) if prev else None
    if headroom is not None and was is not None:
        crossed_in = headroom <= CONSENSUS_FLOOR_PCT < was
        # 하단 추정치가 올라와서 좁혀진 것은 약세 수렴이 아니라 그 반대다. 평균이 실제로
        # 내려온 날만 kill 후보로 부른다.
        average_fell = (prev.get('eps_fy1') or 0) > (eps or 0)
        if crossed_in and average_fell:
            hits.append({
                'key': 'consensus_floor',
                'severity': 'kill_candidate',
                'value': round(headroom, 1),
                'message': f'FY1 컨센 평균이 추정치 하단 대비 +{headroom:.1f}%까지 내려앉음'
                           f' (어제 +{was:.1f}%) — 시장 합의가 약세 시나리오로 수렴 중',
            })

    # ── Bear 가치권 — 상태가 달라진 날에만 ──
    if fair_value and prev:
        bear = fair_value.get('bear')
        prev_bear = prev.get('bear')
        now = _bear_zone(price, bear)
        before = _bear_zone(prev.get('price'), prev_bear)
        if now and before and now != before:
            rank = {'above': 0, 'in': 1, 'below': 2}
            worse = rank[now] > rank[before]
            # 선을 어제 자리에 고정한 채 오늘 주가만 넣어 본다. 그래도 상태가 달라지면
            # 움직인 것은 주가고, 그대로면 움직인 것은 선이다. 단순 가격 일치 비교로는
            # 「주가는 올랐는데 기준선이 더 빨리 올라온」 날을 주가 탓으로 돌리게 된다.
            by_price = _bear_zone(price, prev_bear) != before
            cause = '주가 이동' if by_price else '추정치가 무너져 기준선이 이동'
            if worse:
                through = now == 'below' and before == 'above'
                hits.append({
                    'key': 'bear_proximity', 'severity': 'watch',
                    'level': 'through' if through else now,
                    'value': price,
                    'message': (
                        f'주가가 Bear 시나리오 가치({bear:,}) '
                        + ('아래로 통과 — ' if through
                           else '아래로 내려감 — ' if now == 'below'
                           else f'±{BEAR_PROXIMITY_PCT:.0f}% 안으로 진입 — ')
                        + f'{cause}. 시장이 약세 시나리오를 가격에 반영 중'),
                })
            else:
                # 회복도 사건이다. 등급을 되돌리려면 트리거가 있어야 하는데(state.propose),
                # 나아진 날에 아무것도 안 울리면 내려간 등급이 영영 못 올라온다.
                hits.append({
                    'key': 'bear_exit', 'severity': 'info', 'level': now,
                    'value': price,
                    'message': (
                        f'주가가 Bear 시나리오 가치({bear:,}) 권역에서 '
                        + ('위로 벗어남' if now == 'above' else '위로 올라옴')
                        + f' — {cause}'),
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
