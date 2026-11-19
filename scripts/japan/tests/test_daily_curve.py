"""일본 일간 v2 — 금리 스프레드: 원시 호가 Decimal, 한 번만 반올림, 구간별 상태 (설계 §2 JGB·§11-5)."""
from decimal import Decimal

from japan import daily_rates as R

S, P = '2026-11-18', '2026-11-17'


def leg(period=S, prev=P, source='naver'):
    return {'value': 0.0, 'period': period, 'prev_period': prev, 'chg_bp': 0.0, 'unit': '%', 'source': source}


def block(source='naver', period=S, tenors=('2Y', '5Y', '10Y', '30Y')):
    return {t: leg(period, P if period == S else '2026-11-16', source) for t in tenors}


def test_exact_change_rounds_once():
    """2Y 1.8800→1.8804·10Y 2.7880→2.7876 → −0.08bp → −0.1(만기별 반올림 차로는 0.0 이 된다)."""
    raw = {'2Y': ('1.8804', '1.8800'), '10Y': ('2.7876', '2.7880'), '30Y': ('3.9000', '3.9000')}
    got = R.spreads(block(), raw, S)['s2s10']
    assert got['status'] == 'current' and got['chg'] == Decimal('-0.0008')
    assert R.round_bp(got['chg']) == Decimal('-0.1')


def test_half_bp_rounds_up_not_float():
    """2Y 1.8800 불변·10Y 2.7000→2.7035 → 정확히 +0.35bp → +0.4(float 면 0.3, 12회차 (b)2)."""
    raw = {'2Y': ('1.8800', '1.8800'), '10Y': ('2.7035', '2.7000'), '30Y': ('3.9000', '3.9000')}
    got = R.spreads(block(), raw, S)['s2s10']
    assert R.round_bp(got['chg']) == Decimal('0.4')
    assert round((2.7035 - 1.8800 - (2.7000 - 1.8800)) * 100, 1) == 0.3       # float 가 틀리는 자리


def test_levels_and_signs():
    raw = {'2Y': ('1.8670', '1.8740'), '10Y': ('2.8760', '2.8840'), '30Y': ('4.0620', '4.0450')}
    got = R.spreads(block(), raw, S)
    assert R.round_bp(got['s2s10']['spread']) == Decimal('100.9') and R.round_bp(got['s2s10']['chg']) == Decimal('-0.1')
    assert R.round_bp(got['s10s30']['spread']) == Decimal('118.6') and R.round_bp(got['s10s30']['chg']) == Decimal('2.5')


def test_tiny_negative_change_keeps_sign():
    raw = {'2Y': ('1.8804', '1.8800'), '10Y': ('2.7800', '2.7800'), '30Y': ('3.9', '3.9')}
    chg = R.spreads(block(), raw, S)['s2s10']['chg']
    assert chg == Decimal('-0.0004') and R.round_bp(chg) == Decimal('0.0') and chg < 0


def test_mof_fallback_is_stale():
    b = block('mof', '2026-11-17')
    raw = {'2Y': ('1.87', '1.86'), '10Y': ('2.88', '2.87'), '30Y': ('4.06', '4.05')}
    got = R.spreads(b, raw, S)
    assert got['s2s10']['status'] == 'stale' and got['s10s30']['status'] == 'stale'


def test_missing_leg_invalidates_that_segment_only():
    b = block()
    b['2Y'] = None
    raw = {'10Y': ('2.8760', '2.8840'), '30Y': ('4.0620', '4.0450')}
    got = R.spreads(b, raw, S)
    assert got['s2s10']['status'] == 'invalid' and got['s10s30']['status'] == 'current'


def test_legs_with_different_dates_invalid():
    b = block()
    b['30Y'] = leg(prev='2026-11-16')
    raw = {'2Y': ('1.8', '1.8'), '10Y': ('2.8', '2.8'), '30Y': ('4.0', '4.0')}
    assert R.spreads(b, raw, S)['s10s30']['status'] == 'invalid'


def test_naver_raw_text_and_mof_repr():
    from japan.tests.test_daily_rates import MOF, P as NP, READY, S as NS, _payloads
    raw = {}
    jgb, why, _ = R.jgb_naver(_payloads(), NS, NP, READY, MOF, raw=raw)
    assert jgb, why
    assert raw['10Y'] == ('2.8250', '2.7880')
    raw2 = {}
    R.jgb_block([{'date': '2026-10-22', '2Y': 1.63}, {'date': '2026-10-23', '2Y': 1.642}], '2026-10-23',
                tenors=('2Y',), raw=raw2)
    assert raw2 == {'2Y': ('1.642', '1.63')}
