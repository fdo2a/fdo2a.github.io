import pytest

from bond.curve import carry_roll, forward_rate, forwards, shape, spread_bp


class TestShape:
    def test_front_falls_more_is_bull_steepening(self):
        # 사용자가 든 예: 2Y -15bp, 10Y -5bp
        assert shape(-15, -5) == '불 스티프닝'

    def test_front_rises_more_is_bear_flattening(self):
        assert shape(15, 5) == '베어 플래트닝'

    def test_long_rises_more_is_bear_steepening(self):
        assert shape(5, 15) == '베어 스티프닝'

    def test_long_falls_more_is_bull_flattening(self):
        assert shape(-5, -15) == '불 플래트닝'

    def test_parallel_move_is_not_called_steepening(self):
        # 두 다리가 같은 폭이면 커브는 그대로다 — 이 날을 플래트닝이라 부르면 틀린다
        assert shape(1, 1) == '금리 상승(평행)'
        assert shape(-6, -6) == '금리 하락(평행)'

    def test_sub_bp_noise_is_flat(self):
        assert shape(-0.4, 0.6) == '보합'

    def test_missing_leg_returns_none(self):
        assert shape(None, 3) is None


class TestSpread:
    def test_basis_points(self):
        assert spread_bp(4.20, 4.67) == 47.0

    def test_missing(self):
        assert spread_bp(None, 4.67) is None


class TestForwards:
    def test_flat_curve_forward_equals_spot(self):
        assert forward_rate(1, 4.0, 2, 4.0) == pytest.approx(4.0, abs=0.01)

    def test_upward_curve_forward_above_spot(self):
        f = forward_rate(1, 4.04, 2, 4.20)
        assert f > 4.20

    def test_far_before_near_is_none(self):
        assert forward_rate(5, 4.0, 2, 4.0) is None

    def test_labels(self):
        out = forwards({1: 4.04, 2: 4.20, 3: 4.30, 5: 4.38, 10: 4.67})
        assert set(out) >= {'1y1y', '2y1y', '5y5y'}


class TestCarryRoll:
    def test_upward_curve_earns_without_rate_move(self):
        cr = carry_roll(4.67, 4.38, 10, 5)
        assert cr['rolldown_bp'] > 0
        assert cr['total_pct'] > cr['carry_pct']

    def test_inverted_curve_costs_rolldown(self):
        cr = carry_roll(4.00, 4.50, 10, 5)
        assert cr['rolldown_bp'] < 0
