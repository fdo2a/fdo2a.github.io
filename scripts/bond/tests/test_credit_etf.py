from bond.credit import decompose, divergence, percentile, standing, window_label
from bond.etf import (attribution, basket_return, duration_impact, flow_estimate,
                      premium_discount)


class TestPercentile:
    def test_midpoint(self):
        assert percentile([1, 2, 3, 4, 5], 3) == 50.0

    def test_bottom(self):
        assert percentile([1, 2, 3, 4, 5], 1) == 10.0

    def test_none_value(self):
        assert percentile([1, 2], None) is None


class TestWindowLabel:
    def test_short_sample_is_not_called_years(self):
        # 표본이 모자라면 「2년 최저」라고 부르지 않는다
        assert window_label(30) == '30거래일'

    def test_two_years(self):
        assert window_label(520) == '2년'


class TestStanding:
    def test_bands(self):
        assert standing(list(range(100)), 99)['band'] == '매우 넓음'
        assert standing(list(range(100)), 0)['band'] == '매우 좁음'

    def test_carries_sample_size(self):
        st = standing([1, 2, 3], 2)
        assert st['sessions'] == 3 and st['window'] == '3거래일'


class TestDivergence:
    def test_rates_down_spreads_wider(self):
        assert divergence(-10, 40) == '금리 하락·스프레드 확대'

    def test_both_improving(self):
        assert divergence(-8, -3) == '동반 강세'

    def test_quiet(self):
        assert divergence(0.2, -0.3) == '보합'


class TestDecompose:
    def test_splits_treasury_and_spread(self):
        d = decompose(6.0, 4.0)
        assert d['spread_bp'] == 200.0


class TestEtf:
    def test_premium(self):
        assert premium_discount(100.5, 100.0) == 0.5

    def test_premium_needs_nav(self):
        assert premium_discount(100.5, None) is None

    def test_flow_strips_market_return(self):
        # 순자산이 1% 늘었는데 가격도 1% 올랐으면 유입은 0 이다
        assert flow_estimate(1.01e9, 1.0e9, 1.0) == 0

    def test_duration_impact_sign_is_inverted(self):
        assert duration_impact(6, 10) == -0.6
        assert duration_impact(14.95, 1) == -0.149  # 소수점 3자리 반올림

    def test_basket_weights_times_returns(self):
        rows = {'AGG': {'change_pct': 1.0}, 'IGOV': {'change_pct': 0.0},
                'EMB': {'change_pct': 0.0}, 'HYG': {'change_pct': 0.0},
                'TIP': {'change_pct': 0.0}}
        assert basket_return(rows)['total_pct'] == 0.6

    def test_missing_leg_marks_incomplete(self):
        assert basket_return({'AGG': {'change_pct': 1.0}})['complete'] is False

    def test_attribution_groups_credit_together(self):
        rows = {'AGG': {'change_pct': 0.0}, 'IGOV': {'change_pct': 0.0},
                'EMB': {'change_pct': -1.0}, 'HYG': {'change_pct': -1.0},
                'TIP': {'change_pct': 0.0}}
        buckets = {b['bucket']: b['contribution_pct']
                   for b in attribution(rows)['buckets']}
        assert buckets['credit'] == -0.2
