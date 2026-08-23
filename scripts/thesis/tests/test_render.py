from thesis import render as R


ROW = {
    'name': 'Micron', 'currency': 'USD', 'price': 966.78, 'price_date': '2026-08-21',
    'pct_from_52w_high': -20.32, 'eps_fy1': 155.03, 'eps_fy1_low': 106.89,
    'eps_fy1_high': 221.27, 'pe_fy1': 6.24, 'pb': 10.84, 'bvps_as_of': '2026-05-31',
    'next_earnings_date': '2026-09-24',
    'fair_value': {'bull': 1553, 'base': 718, 'bear': 267, 'weighted': 856,
                   'band1': 685, 'band2': 582},
    'position': {'vs_weighted_pct': 12.9, 'vs_base_pct': 34.6, 'upside_bull_pct': 60.6,
                 'downside_bear_pct': -72.4, 'in_band1': False, 'in_band2': False},
}


def test_valuation_block_carries_the_gate_marker():
    html = R.valuation_block(ROW, '2026-08-24')
    assert 'data-block="valuation"' in html
    assert 'data-computed="2026-08-24"' in html


def test_valuation_block_prints_every_scenario():
    html = R.valuation_block(ROW, '2026-08-24')
    for value in ('267', '718', '1,553', '856'):
        assert value in html


def test_valuation_block_survives_missing_consensus():
    html = R.valuation_block({'currency': 'USD', 'price': 10}, '2026-08-24')
    assert 'data-block="valuation"' in html
    assert '계산하지 않았다' in html


def test_valuation_block_states_the_assumption_caveat():
    assert '가정이 결과를 지배한다' in R.valuation_block(ROW, '2026-08-24')


def test_snapshot_names_the_balance_sheet_date():
    html = R.snapshot_block(ROW, '2026-08-24')
    assert '2026-05-31' in html
    assert 'data-block="snapshot"' in html


def test_snapshot_reports_dispersion_ratio():
    assert '2.1배' in R.snapshot_block(ROW, '2026-08-24')


def test_snapshot_survives_missing_dispersion():
    row = dict(ROW, eps_fy1_low=None)
    assert R.snapshot_block(row, '2026-08-24')


def test_money_formats_by_currency():
    assert R.money(966.78, 'USD') == '$966.78'
    assert R.money(281500, 'KRW') == '281,500원'
    assert R.money(None, 'KRW') == '—'


def test_card_shows_grade_badge_class():
    html = R.ticker_card('MU', ROW, {'grade': '주의', 'grade_since': '2026-08-24'}, 'micron.html')
    assert 'g-watch' in html and '주의' in html


def test_card_inverts_sign_so_upside_reads_positive():
    """가중가치 대비 −12.9%(주가가 위)면 카드엔 여력이 −로 보여야 한다."""
    html = R.ticker_card('MU', ROW, {'grade': '주의'}, 'micron.html')
    assert '-12.9%' in html
