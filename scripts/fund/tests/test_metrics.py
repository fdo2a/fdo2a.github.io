import math

import pytest

from fund import metrics as m


def geometric(n, daily):
    """n+1 closes growing by `daily` per session, oldest first."""
    return [100 * (1 + daily) ** i for i in range(n + 1)]


def test_ret_counts_sessions_back_from_last():
    closes = [100, 110, 121]
    assert m.ret(closes, 1) == pytest.approx(10.0)
    assert m.ret(closes, 2) == pytest.approx(21.0)


def test_ret_none_when_history_too_short():
    assert m.ret([100, 101], 2) is None


def test_mom_12_1_skips_last_month():
    closes = list(range(1, 300))
    want = (closes[-22] / closes[-253] - 1) * 100
    assert m.mom_12_1(closes) == pytest.approx(want)
    assert m.mom_12_1(closes[:252]) is None


def test_vol_is_annualised_sample_stdev_of_log_returns():
    closes = [100, 102, 99, 101, 103, 100]
    lr = [math.log(b / a) for a, b in zip(closes, closes[1:])]
    mean = sum(lr) / len(lr)
    sd = math.sqrt(sum((x - mean) ** 2 for x in lr) / (len(lr) - 1))
    assert m.vol(closes, 5) == pytest.approx(sd * math.sqrt(252) * 100)


def test_vol_of_constant_growth_is_zero():
    assert m.vol(geometric(80, 0.01), 60) == pytest.approx(0.0, abs=1e-9)


def test_var_is_positive_loss_at_lower_quantile_linear_interpolation():
    # 21 closes -> 20 returns of -10%..+9% (1% steps). numpy-style linear
    # percentile at 5% of 20 points: position 0.95 between -10% and -9%.
    rets = [(-10 + i) / 100 for i in range(20)]
    closes = [100.0]
    for r in rets:
        closes.append(closes[-1] * (1 + r))
    got = m.hist_var(closes, 20, 0.95)
    assert got == pytest.approx(-(-0.10 + 0.95 * 0.01) * 100)


def test_var_floors_at_zero_when_tail_is_a_gain():
    closes = [100 * 1.01 ** i for i in range(30)]
    assert m.hist_var(closes, 20, 0.95) == 0.0


def test_var_none_when_short():
    assert m.hist_var([100, 101, 102], 60, 0.95) is None


def test_sma_and_drawdown():
    closes = [10, 20, 30, 40]
    assert m.sma(closes, 2) == pytest.approx(35)
    assert m.sma(closes, 5) is None
    assert m.drawdown(closes + [20], 5) == pytest.approx(-50.0)
    assert m.drawdown(closes + [20], 252) is None


def test_beta_aligns_on_dates_not_positions():
    dates_a = ['d1', 'd2', 'd3', 'd4']
    a = [100, 102, 100.98, 103.0]
    # benchmark has an extra session 'dx' that the asset does not trade
    dates_b = ['d1', 'dx', 'd2', 'd3', 'd4']
    b = [100, 50, 101, 100.495, 101.5]
    got = m.beta(a, dates_a, b, dates_b, 3)
    # on shared dates asset returns are exactly 2x benchmark returns (approximately)
    assert got == pytest.approx(2.0, rel=0.05)


def test_relative_return_aligned_on_dates():
    a, da = [100, 110], ['d1', 'd2']
    b, db = [100, 105], ['d1', 'd2']
    assert m.rel_ret(a, da, b, db, 1) == pytest.approx(5.0)
