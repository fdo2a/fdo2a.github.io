"""Why yields moved, not just that they moved.

A nominal Treasury yield is a real yield plus a compensation for expected inflation.
FRED publishes both legs (DFII* and T*IE) on the same calendar, so the day's move
decomposes arithmetically: a 10Y that rose 8bp with real up 7bp and breakevens up 1bp
is a growth/term-premium move, not an inflation scare — and the brief should say which.

Everything else here is context the same question needs: forward inflation
compensation, the ACM term premium, credit spreads, and the front end.

Pure — `build()` takes {fred_id: [(date, value)]} and returns plain dicts.
"""

_R2 = 2

# key -> (fred_id, 한국어 라벨). Absent series simply do not appear.
ROWS = (
    ('nominal_5y', 'DGS5', '5년 명목금리'),
    ('nominal_10y', 'DGS10', '10년 명목금리'),
    ('nominal_30y', 'DGS30', '30년 명목금리'),
    ('real_5y', 'DFII5', '5년 실질금리'),
    ('real_10y', 'DFII10', '10년 실질금리'),
    ('real_30y', 'DFII30', '30년 실질금리'),
    ('breakeven_5y', 'T5YIE', '5년 기대인플레'),
    ('breakeven_10y', 'T10YIE', '10년 기대인플레'),
    ('breakeven_5y5y', 'T5YIFR', '5년 후 5년 기대인플레'),
    ('term_premium_10y', 'THREEFYTP10', '10년 기간프리미엄'),
    ('hy_spread', 'BAMLH0A0HYM2', '하이일드 스프레드'),
    ('ig_spread', 'BAMLC0A0CM', '투자등급 스프레드'),
    ('tbill_3m', 'DTB3', '3개월 T-bill'),
    ('sofr', 'SOFR', 'SOFR'),
)

TENORS = (('10Y', 'DGS10', 'DFII10', 'T10YIE'),
          ('5Y', 'DGS5', 'DFII5', 'T5YIE'),
          ('30Y', 'DGS30', 'DFII30', None))

# Below this the move is noise and attributing a cause would be storytelling.
FLAT_BP = 2.0
# One leg has to carry this much of the move before it gets named as the driver.
DOMINANT_SHARE = 0.65

DRIVER_KO = {'real': '실질금리', 'breakeven': '기대인플레',
             'mixed': '실질·기대인플레 동반', 'flat': '유의미한 변화 없음'}


def _bp(series, n):
    """Change over n observations, in basis points."""
    if not series or len(series) < n + 1:
        return None
    return round((series[-1][1] - series[-(n + 1)][1]) * 100, 1)


def _row(series, label):
    if not series:
        return None
    return {
        'label_ko': label,
        'level': round(series[-1][1], _R2),
        'date': series[-1][0],
        'chg_1d_bp': _bp(series, 1),
        'chg_5d_bp': _bp(series, 5) if len(series) > 5 else _bp(series, len(series) - 1),
    }


def classify(real_bp, be_bp):
    """Which leg carried the move. -> (driver, driver_ko)."""
    if real_bp is None or be_bp is None:
        return None, None
    total = abs(real_bp) + abs(be_bp)
    if total < FLAT_BP:
        return 'flat', DRIVER_KO['flat']
    if abs(real_bp) / total >= DOMINANT_SHARE:
        return 'real', DRIVER_KO['real']
    if abs(be_bp) / total >= DOMINANT_SHARE:
        return 'breakeven', DRIVER_KO['breakeven']
    return 'mixed', DRIVER_KO['mixed']


def _align(*series):
    """Trim every leg to the dates they all share, oldest first.

    FRED publishes DGS/DFII/BEI on different lags. Differencing them as-is produces a
    decomposition where 명목 ≠ 실질 + 기대, which is the same date-mismatch trap the
    2s10s spread already taught this project to declare rather than paper over.
    """
    if any(not s for s in series):
        return None
    common = set.intersection(*({d for d, _ in s} for s in series))
    if not common:
        return None
    return [[(d, v) for d, v in s if d in common] for s in series]


def build(series_by_id):
    rows = {}
    for key, sid, label in ROWS:
        row = _row((series_by_id or {}).get(sid), label)
        if row:
            rows[key] = row

    decomposition = {}
    for tenor, nom_id, real_id, be_id in TENORS:
        nom = (series_by_id or {}).get(nom_id)
        real = (series_by_id or {}).get(real_id)
        be = (series_by_id or {}).get(be_id) if be_id else None
        aligned = _align(nom, real, be)
        if not aligned:
            continue
        nom, real, be = aligned
        if len(nom) < 2:
            continue
        real_1d, be_1d = _bp(real, 1), _bp(be, 1)
        driver, driver_ko = classify(real_1d, be_1d)
        decomposition[tenor] = {
            'nominal_chg_1d_bp': _bp(nom, 1),
            'real_chg_1d_bp': real_1d,
            'breakeven_chg_1d_bp': be_1d,
            'nominal_chg_5d_bp': _bp(nom, 5) if len(nom) > 5 else _bp(nom, len(nom) - 1),
            'real_chg_5d_bp': _bp(real, 5) if len(real) > 5 else _bp(real, len(real) - 1),
            'breakeven_chg_5d_bp': _bp(be, 5) if len(be) > 5 else _bp(be, len(be) - 1),
            'driver': driver,
            'driver_ko': driver_ko,
            'as_of': nom[-1][0],
            'basis': f'FRED {nom_id}/{real_id}/{be_id} 동일자 정렬',
        }
    return {'rows': rows, 'decomposition': decomposition}
