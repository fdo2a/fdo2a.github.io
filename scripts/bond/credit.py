"""크레딧 스프레드 — 수준·위치·수익률 분해.

발행본이 「HY 스프레드 400bp」라고만 쓰면 독자는 그게 넓은 건지 좁은 건지 모른다.
이 모듈이 채우는 것은 「어디에 서 있나」다 — 이력 대비 백분위와, 그 백분위가 몇
거래일 위에서 계산됐는지(짧은 표본에 「5년 최저」라고 쓰지 않기 위해).

**백분위는 계산용 수이고 발행본이 인쇄하는 말이 아니다.** `plain` 이 같은 사실을
「이보다 좁았던 날은 사흘뿐」처럼 세어 볼 수 있는 말로 바꿔 함께 내려보낸다
(`common/standing.py`).

그리고 채권 수익률을 «국채 + 스프레드»로 쪼개는 습관을 코드로 강제한다. 회사채
6% 를 통째로 보면 국채가 4% 인지 5% 인지에 따라 완전히 다른 상품이라는 사실이 가려진다.
"""

from common import standing as standing_mod

# 기간 이름 규칙은 US 브리프와 공유한다 — 같은 규칙을 두 벌 두면 한쪽만 고쳐진다.
MIN_SESSIONS_FOR_YEARS = standing_mod.MIN_SESSIONS_FOR_YEARS
window_label = standing_mod.window_label


def percentile(series, value):
    """value 가 series 안에서 차지하는 백분위(0~100). 낮을수록 «좁다»."""
    vals = [v for v in series if v is not None]
    if not vals or value is None:
        return None
    below = sum(1 for v in vals if v < value)
    equal = sum(1 for v in vals if v == value)
    return round((below + equal / 2.0) / len(vals) * 100, 1)


def standing(series, value, kind='spread'):
    """수준 + 위치 + 표본 길이 + 극값 — 한 스프레드가 지금 어디에 있나.

    `kind` 는 그 위치를 부르는 말만 고른다 — 스프레드는 넓고 좁고, 금리·지수는
    높고 낮다.
    """
    vals = [v for v in series if v is not None]
    if not vals or value is None:
        return None
    pct = percentile(vals, value)
    # 날 수는 백분위에서 되돌리지 않고 **여기서 직접 센다** — 반올림된 백분위로
    # 되돌리면 표본의 최댓값이 「이보다 넓었던 날이 하루뿐」이 된다(실제 0일).
    above = sum(1 for v in vals if v > value)
    below = sum(1 for v in vals if v < value)
    return {
        # 인쇄하지 않는 파생 단위는 만들지 않는다. 예전엔 `level_bp`(값 ×100)를 담았는데,
        # 이 필드가 10년물 4.67 을 467 로 만들어 「하이일드 스프레드 467bp」라는
        # 거짓 문장의 알리바이가 됐다(2026-08-31 codex 검토).
        'value': value,
        'percentile': pct,
        'sessions': len(vals),
        'window': window_label(len(vals)),
        'min': round(min(vals), 3),
        'max': round(max(vals), 3),
        'band': _band(pct),
        # 발행본이 그대로 인쇄하는 말. 백분위라는 낱말은 여기서 끝난다.
        'plain': standing_mod.plain(pct, len(vals), window_label(len(vals)), kind,
                                    above=above, below=below),
    }


def _band(pct):
    if pct is None:
        return None
    if pct >= 90:
        return '매우 넓음'
    if pct >= 70:
        return '넓음'
    if pct > 30:
        return '보통'
    if pct > 10:
        return '좁음'
    return '매우 좁음'


def decompose(corporate_yield, treasury_yield):
    """회사채 수익률 -> 국채 + 스프레드. 둘 다 %."""
    if corporate_yield is None or treasury_yield is None:
        return None
    return {
        'yield_pct': round(corporate_yield, 3),
        'treasury_pct': round(treasury_yield, 3),
        'spread_bp': round((corporate_yield - treasury_yield) * 100, 1),
    }


def divergence(rate_bp, spread_bp_change):
    """금리와 스프레드가 반대로 간 날을 이름 붙인다.

    「금리 -10bp 인데 HY +40bp」는 채권시장이 좋았던 날이 아니라 무위험금리는
    내리고 신용위험은 커진 날이다. 국채 ETF 는 오르고 HY ETF 는 내릴 수 있다.
    """
    if rate_bp is None or spread_bp_change is None:
        return None
    if abs(rate_bp) < 1 and abs(spread_bp_change) < 1:
        return '보합'
    if rate_bp < 0 and spread_bp_change > 0:
        return '금리 하락·스프레드 확대'
    if rate_bp > 0 and spread_bp_change < 0:
        return '금리 상승·스프레드 축소'
    if rate_bp < 0 and spread_bp_change <= 0:
        return '동반 강세'
    return '동반 약세'
