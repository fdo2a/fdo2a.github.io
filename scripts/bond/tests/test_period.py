from bond.period import (build, iso_week_key, month_key, month_range,
                         slice_rows, stance_changes, week_range)

ROWS = [
    {'report_date': '2026-08-24', 'us': {'10Y': 4.70}, 'credit': {'us_hy': 2.70},
     'fx': {'DXY': 99.00}, 'move': 73.98, 'etf': {'AGG': {'close': 97.55}}},
    {'report_date': '2026-08-25', 'us': {'10Y': 4.64}, 'credit': {'us_hy': 2.68},
     'fx': {'DXY': 98.92}, 'move': 71.92, 'etf': {'AGG': {'close': 98.01}}},
    {'report_date': '2026-08-27', 'us': {'10Y': 4.67}, 'credit': {'us_hy': 2.63},
     'fx': {'DXY': 99.16}, 'move': 69.86, 'etf': {'AGG': {'close': 97.83}}},
]


class TestKeys:
    def test_iso_week(self):
        assert iso_week_key('2026-08-27') == '2026-W35'

    def test_month(self):
        assert month_key('2026-08-27') == '2026-08'

    def test_week_range_starts_monday(self):
        assert week_range('2026-08-27')[0] == '2026-08-24'

    def test_month_range_covers_whole_month(self):
        assert month_range('2026-08-27') == ('2026-08-01', '2026-08-31')


class TestBuild:
    def test_rate_change_is_start_to_end(self):
        p = build(ROWS, '2026-08-24', '2026-08-30')
        assert p['rates']['us/10Y']['bp'] == -3.0
        assert p['rates']['us/10Y']['start_date'] == '2026-08-24'
        assert p['rates']['us/10Y']['end_date'] == '2026-08-27'

    def test_credit_in_basis_points(self):
        p = build(ROWS, '2026-08-24', '2026-08-30')
        assert p['credit']['us_hy']['bp'] == -7.0

    def test_fx_and_etf_in_percent(self):
        p = build(ROWS, '2026-08-24', '2026-08-30', etf_tickers=['AGG'])
        assert p['fx']['DXY']['pct'] == 0.162
        assert p['etf']['AGG']['pct'] == 0.287

    def test_unsorted_input_does_not_flip_endpoints(self):
        p = build(list(reversed(ROWS)), '2026-08-24', '2026-08-30')
        assert p['rates']['us/10Y']['start_date'] == '2026-08-24'
        assert p['rates']['us/10Y']['end_date'] == '2026-08-27'

    def test_partial_month_is_not_complete(self):
        p = build(ROWS, '2026-08-01', '2026-08-31')
        assert p['complete'] is False

    def test_single_session_yields_no_change(self):
        p = build(ROWS[:1], '2026-08-24', '2026-08-24')
        assert p['rates'] == {} and p['complete'] is False

    def test_empty_window(self):
        assert build(ROWS, '2026-01-01', '2026-01-07')['sessions'] == 0

    def test_slice_is_inclusive(self):
        assert len(slice_rows(ROWS, '2026-08-25', '2026-08-27')) == 2


class TestStanceChanges:
    def test_only_actual_moves_are_reported(self):
        rows = [
            {'report_date': '2026-08-24', 'assets': {'duration': {'grade': 0}}},
            {'report_date': '2026-08-25', 'assets': {'duration': {'grade': 0}}},
            {'report_date': '2026-08-26',
             'assets': {'duration': {'grade': 1, 'label': '롱 바이어스'}}},
        ]
        out = stance_changes(rows, '2026-08-24', '2026-08-30')
        assert len(out) == 1 and out[0]['to'] == 1 and out[0]['date'] == '2026-08-26'

    def test_baseline_comes_from_before_the_window(self):
        rows = [
            {'report_date': '2026-08-21', 'assets': {'duration': {'grade': 0}}},
            {'report_date': '2026-08-24',
             'assets': {'duration': {'grade': 1, 'label': '롱 바이어스'}}},
        ]
        out = stance_changes(rows, '2026-08-24', '2026-08-30')
        assert len(out) == 1 and out[0]['date'] == '2026-08-24'

    def test_no_moves_is_empty(self):
        rows = [{'report_date': '2026-08-24', 'assets': {'duration': {'grade': 0}}}]
        assert stance_changes(rows, '2026-08-24', '2026-08-30') == []
