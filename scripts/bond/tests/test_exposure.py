import pytest

from bond.exposure import (FACTORS, decompose, divergence, factors_of,
                           monitor_plan, per_etf, segment_of)

BENCH = [('AGG', 0.60), ('IGOV', 0.15), ('EMB', 0.10), ('HYG', 0.10), ('TIP', 0.05)]


class TestFactorMap:
    def test_every_ticker_sums_to_one(self):
        for t, (f, _) in FACTORS.items():
            assert sum(f.values()) == pytest.approx(1.0), t

    def test_long_treasury_is_pure_rates(self):
        assert factors_of('TLT') == {'us_rates': 1.00}

    def test_high_yield_is_credit_dominated(self):
        f = factors_of('HYG')
        assert f['credit'] > f['us_rates']

    def test_unhedged_foreign_carries_fx(self):
        assert factors_of('IGOV')['fx'] > 0.3

    def test_segments(self):
        assert segment_of('SHY') == 'front' and segment_of('TLT') == 'long'


class TestDecompose:
    def test_listing_country_does_not_decide(self):
        # 전부 미국 상장이지만 해외 금리 노출은 IGOV 에서만 나온다
        d = decompose(BENCH)
        f = {r['factor']: r['pct'] for r in d['factors']}
        assert f['us_rates'] > 50
        assert 5 < f['foreign_rates'] < 12

    def test_all_us_book_has_no_foreign_exposure(self):
        f = {r['factor'] for r in decompose([('AGG', 0.5), ('LQD', 0.5)])['factors']}
        assert 'foreign_rates' not in f and 'fx' not in f

    def test_foreign_heavy_book_raises_foreign_weight(self):
        f = {r['factor']: r['pct'] for r in decompose([('IGOV', 0.8), ('AGG', 0.2)])['factors']}
        assert f['foreign_rates'] > 40

    def test_unknown_ticker_is_reported_not_silently_dropped(self):
        assert decompose([('ZZZZ', 1.0)])['unknown'] == ['ZZZZ']


class TestMonitorPlan:
    def test_depth_follows_exposure(self):
        rows = {r['factor']: r for r in monitor_plan(BENCH)['factors']}
        assert rows['us_rates']['depth'] == '매일 깊게'
        assert rows['foreign_rates']['depth'] == '방향만 확인'

    def test_watch_list_is_attached(self):
        rows = {r['factor']: r for r in monitor_plan(BENCH)['factors']}
        assert any('MOVE' in w for w in rows['us_rates']['watch'])


class TestPerEtf:
    def test_percentages_are_emitted_for_the_page(self):
        rows = {r['ticker']: r for r in per_etf(['TLT', 'HYG'])}
        assert rows['TLT']['factors'][0]['pct'] == 100.0
        assert rows['HYG']['factors'][0]['factor'] == 'credit'


class TestDivergence:
    def test_co_movement(self):
        assert divergence(10.0, 10.0, '독일')['verdict'] == '동조'

    def test_us_only(self):
        d = divergence(10.0, 1.0, '독일')
        assert d['verdict'] == '미국 고유'
        assert '연준' in d['reading']

    def test_foreign_only(self):
        assert divergence(0.5, -8.0, '독일')['verdict'] == '독일 고유'

    def test_both_quiet(self):
        assert divergence(0.5, 0.5, '독일')['verdict'] == '둘 다 보합'

    def test_opposite_directions(self):
        assert divergence(8.0, -8.0, '독일')['verdict'] == '반대 방향'

    def test_missing_leg(self):
        assert divergence(None, 3.0, '독일') is None
