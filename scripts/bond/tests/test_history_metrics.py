import json
import os
import tempfile

from bond import history
from bond.metrics import compute, diff_summary


def _market():
    return {
        'report_date': '2026-08-27',
        'us_curve': {'2Y': {'level': 4.20, 'date': '2026-08-27', 'source': 'FRED'},
                     '10Y': {'level': 4.67, 'date': '2026-08-27', 'source': 'FRED'},
                     '30Y': {'level': 5.19, 'date': '2026-08-27', 'source': 'FRED'}},
        # 분해는 세 계열이 **같은 두 날짜** 사이에서 빠져야 항등식이 닫힌다
        'us_curve_fred': {'10Y': {'level': 4.67, 'date': '2026-08-27',
                                  'prev_level': 4.66, 'prev_date': '2026-08-26'}},
        'de_curve': {'10Y': {'level': 3.18, 'date': '2026-08-27',
                             'source': 'Bundesbank'}},
        'real_yields': {'10Y': {'level': 2.34, 'date': '2026-08-27',
                                'prev_level': 2.34, 'prev_date': '2026-08-26'}},
        'breakeven': {'10Y': {'level': 2.33, 'date': '2026-08-27',
                              'prev_level': 2.32, 'prev_date': '2026-08-26'}},
        'credit': {'us_hy': {'value': 2.63, 'date': '2026-08-27'}},
        'fx': {'DXY': {'level': 99.16, 'date': '2026-08-27'}},
        'vol': {'move': 69.86},
        'etf': {'AGG': {'close': 97.83, 'nav': 97.46, 'nav_as_of': '2026-08-27',
                        'close_date': '2026-08-27', 'aum_usd': 1.0e11}},
    }


ROWS = [{'report_date': '2026-08-26', 'us': {'2Y': 4.19, '10Y': 4.66, '30Y': 5.18},
         'de': {'10Y': 3.22}, 'real': {'10Y': 2.34}, 'bei': {'10Y': 2.32},
         'credit': {'us_hy': 2.67}, 'fx': {'DXY': 99.17}, 'move': 69.44,
         'etf': {'AGG': {'close': 97.86, 'nav': 97.50, 'aum_usd': 0.99e11}}}]


class TestLedger:
    def test_append_is_idempotent(self):
        p = os.path.join(tempfile.mkdtemp(), 'h.jsonl')
        history.append(p, {'report_date': '2026-08-27', 'x': 1})
        history.append(p, {'report_date': '2026-08-27', 'x': 2})
        rows = history.read(p)
        assert len(rows) == 1 and rows[0]['x'] == 2

    def test_sorted_and_previous(self):
        p = os.path.join(tempfile.mkdtemp(), 'h.jsonl')
        history.append(p, {'report_date': '2026-08-27'})
        history.append(p, {'report_date': '2026-08-25'})
        rows = history.read(p)
        assert [r['report_date'] for r in rows] == ['2026-08-25', '2026-08-27']
        assert history.previous(rows, '2026-08-27')['report_date'] == '2026-08-25'

    def test_previous_missing_on_first_session(self):
        assert history.previous([], '2026-08-27') is None


class TestCompute:
    def test_daily_bp_changes(self):
        m = compute(_market(), ROWS)
        assert m['curves']['us']['tenors']['10Y']['bp'] == 1.0
        assert m['curves']['de']['tenors']['10Y']['bp'] == -4.0

    def test_credit_change_and_standing(self):
        m = compute(_market(), ROWS)
        assert m['credit']['us_hy']['chg_bp'] == -4.0
        assert m['credit']['us_hy']['standing']['sessions'] == 1

    def test_decomposition_requires_common_date(self):
        mk = _market()
        m = compute(mk, ROWS)
        assert m['decomposition']['10Y']['driver_ko'] == '기대인플레'
        assert m['decomposition']['10Y']['residual_bp'] == 0.0
        mk['breakeven']['10Y']['date'] = '2026-08-26'
        assert compute(mk, ROWS)['decomposition'] == {}

    def test_decomposition_needs_a_common_previous_date(self):
        mk = _market()
        mk['breakeven']['10Y']['prev_date'] = '2026-08-25'
        assert compute(mk, ROWS)['decomposition'] == {}

    def test_source_change_suppresses_daily_change(self):
        mk = _market()
        mk['us_curve']['10Y']['source'] = 'Yahoo'
        rows = [dict(ROWS[0], dates={'us_source': {'10Y': 'FRED'}})]
        row = compute(mk, rows)['curves']['us']['tenors']['10Y']
        assert row['source_changed'] is True and row['bp'] is None

    def test_stale_row_reports_no_daily_change(self):
        mk = _market()
        mk['de_curve']['10Y']['date'] = '2026-08-26'
        m = compute(mk, ROWS)
        row = m['curves']['de']['tenors']['10Y']
        assert row['stale'] is True and row['bp'] is None

    def test_premium_only_when_dates_align(self):
        mk = _market()
        assert compute(mk, ROWS)['etf']['AGG']['premium_pct'] is not None
        mk['etf']['AGG']['nav_as_of'] = '2026-08-28'
        assert compute(mk, ROWS)['etf']['AGG']['premium_pct'] is None

    def test_movers_sorted_by_size(self):
        m = compute(_market(), ROWS)
        vals = [x['abs'] for x in m['diff_summary']['movers']]
        assert vals == sorted(vals, reverse=True)

    def test_trigger_metric_names_are_a_contract(self):
        t = compute(_market(), ROWS)['triggers']
        for key in ('us10y_level', 'spread_2s10s_bp', 'hy_oas_bp', 'move_level'):
            assert key in t

    def test_diff_summary_skips_missing(self):
        assert diff_summary({'curves': {}, 'credit': {}, 'fx': {},
                             'etf': {}, 'vol': {}})['count'] == 0
