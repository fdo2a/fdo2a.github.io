"""국채 커브 — 형태 판정과 내재선도금리.

두 가지 일을 한다.

1) **커브 형태 판정.** 「10년물 -8bp」만으로는 아무것도 못 읽는다. 프런트엔드와
   롱엔드가 각각 어느 쪽으로 갔는지가 진짜 정보다. 금리 방향(bull=하락 / bear=상승)과
   기울기 변화(steepening=확대 / flattening=축소)를 곱해 네 이름 중 하나를 고른다.
   경계는 임의로 두지 않는다 — 하루 변화가 두 다리 모두 ±1bp 안이면 「보합」이다.
   1bp 는 반올림 잡음과 구분되는 최소 단위이고, 이보다 좁게 잡으면 매일 형태가 바뀐다.

2) **내재선도금리.** OIS 커브는 무료로 결정론적 수집이 안 되므로, 현물 커브에서
   선도금리를 뽑아 「시장이 이미 무엇을 반영하고 있나」를 잰다. 1y1y 가 3.5% 인데
   현재 정책금리가 4.5% 라면 시장은 1년 뒤까지 100bp 인하를 이미 깔고 있는 것이고,
   그렇다면 「인하할 것 같다」는 견해에는 값이 없다. 이 계산이 이 모듈의 존재 이유다.

무이표채 근사를 쓴다(연복리). 국채 현물 커브는 par yield 라 엄밀히는 부트스트랩이
필요하지만, 선도금리의 «방향과 크기»를 읽는 용도에서 그 차이는 판단을 바꾸지 않는다.
근사라는 사실은 발행본 캡션에 노출한다.
"""

FLAT_BP = 1.0  # 이 안쪽 움직임은 방향으로 읽지 않는다

SHAPES = {
    ('bull', 'steep'): '불 스티프닝',
    ('bull', 'flat'): '불 플래트닝',
    ('bear', 'steep'): '베어 스티프닝',
    ('bear', 'flat'): '베어 플래트닝',
}


def shape(short_bp, long_bp, flat_bp=FLAT_BP):
    """두 만기의 하루 bp 변화 -> 커브 형태 이름.

    short_bp/long_bp 는 각각 짧은 쪽·긴 쪽의 변화(bp, 상승이 +).
    """
    if short_bp is None or long_bp is None:
        return None
    if abs(short_bp) < flat_bp and abs(long_bp) < flat_bp:
        return '보합'

    slope_change = long_bp - short_bp          # + 면 커브 확대(스티프닝)
    # 방향은 두 다리의 평균이 아니라 «더 크게 움직인 다리»가 정한다 — 평균은
    # +10/-10 같은 순수 트위스트에서 0 이 되어 방향을 못 부른다.
    if abs(short_bp) == abs(long_bp) and short_bp != long_bp:
        # 정확히 같은 크기로 반대로 갔다. 어느 쪽이 «주도»했다고 말할 수 없다.
        return '트위스트'
    driver = short_bp if abs(short_bp) >= abs(long_bp) else long_bp
    direction = 'bear' if driver > 0 else 'bull'
    if abs(slope_change) < flat_bp:
        # 두 다리가 같은 크기로 움직인 날을 스티프닝·플래트닝이라 부르면 안 된다.
        # 커브는 그대로고 커브 전체가 위아래로 움직인 것이다.
        return '금리 상승(평행)' if direction == 'bear' else '금리 하락(평행)'
    tilt = 'steep' if slope_change > 0 else 'flat'
    return SHAPES[(direction, tilt)]


def spread_bp(short_level, long_level):
    """장단기 금리차(bp). 둘 중 하나라도 없으면 None."""
    if short_level is None or long_level is None:
        return None
    return round((long_level - short_level) * 100, 1)


def forward_rate(near_years, near_rate, far_years, far_rate):
    """near 만기 이후 (far-near) 구간의 내재선도금리(%, 연복리).

    (1+far)^far = (1+near)^near * (1+fwd)^(far-near)
    """
    if None in (near_rate, far_rate) or far_years <= near_years:
        return None
    n, f = near_rate / 100.0, far_rate / 100.0
    if n <= -1 or f <= -1:
        return None
    span = far_years - near_years
    growth = ((1 + f) ** far_years) / ((1 + n) ** near_years)
    if growth <= 0:
        return None
    return round((growth ** (1.0 / span) - 1) * 100, 3)


def forwards(curve):
    """만기(년) -> 금리(%) 딕셔너리에서 표준 선도구간을 뽑는다."""
    def g(y):
        return curve.get(y)

    out = {}
    for label, (a, b) in {
        '1y1y': (1, 2), '2y1y': (2, 3), '1y4y': (1, 5),
        '5y5y': (5, 10), '2y8y': (2, 10),
    }.items():
        fwd = forward_rate(a, g(a), b, g(b))
        if fwd is not None:
            out[label] = fwd
    return out


def carry_roll(level, level_shorter, years, years_shorter, horizon_years=1.0):
    """1년 보유 시 캐리 + 롤다운 근사(%).

    캐리는 표면금리(현물 수익률)이고, 롤다운은 커브를 타고 내려가며 얻는 가격 이득이다.
    커브가 우상향이면 금리가 하나도 안 움직여도 수익이 난다 — 채권 아이디어를
    「금리 방향」으로만 보면 안 되는 이유가 여기 있다.
    """
    if None in (level, level_shorter) or years <= years_shorter:
        return None
    slope_per_year = (level - level_shorter) / (years - years_shorter)
    roll_bp = slope_per_year * horizon_years * 100
    duration = years - horizon_years / 2  # 잔존만기 근사 듀레이션
    return {
        'carry_pct': round(level * horizon_years, 3),
        'rolldown_bp': round(roll_bp, 1),
        'rolldown_pct': round(roll_bp / 100 * duration, 3),
        'total_pct': round(level * horizon_years + roll_bp / 100 * duration, 3),
    }
