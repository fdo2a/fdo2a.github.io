"""일본 일간 금리 — MOF JGB(T+1)·BOJ API (codex 설계 검토 #4)."""
import pytest

from japan import daily_rates as R

ROWS = [
    {'date': '2026-10-21', '2Y': 1.60, '5Y': 1.85, '10Y': 2.30, '30Y': 3.90},
    {'date': '2026-10-22', '2Y': 1.63, '5Y': 1.86, '10Y': 2.31, '30Y': 3.92},
    {'date': '2026-10-23', '2Y': 1.642, '5Y': 1.872, '10Y': 2.325, '30Y': 3.904},
]

# 2026-10-27 00:04 KST 에 받은 FM01/STRDCLUCON 응답(일부).
CALL = {'STATUS': 200, 'RESULTSET': [{
    'SERIES_CODE': 'STRDCLUCON', 'NAME_OF_TIME_SERIES': 'Call Rate, Uncollateralized Overnight, Average (Daily)',
    'UNIT': 'percent per annum', 'FREQUENCY': 'DAILY', 'LAST_UPDATE': 20261026,
    'VALUES': {'SURVEY_DATES': [20261019, 20261020, 20261021, 20261022, 20261024],
               'VALUES': [1.227, 1.228, 1.227, 1.227, None]}}]}


def test_jgb_uses_prev_session_row():
    got = R.jgb_block(ROWS, '2026-10-23')
    assert got['10Y']['value'] == 2.325 and got['10Y']['period'] == '2026-10-23'
    assert got['10Y']['prev_period'] == '2026-10-22'


def test_jgb_bp_against_previous_bond_day():
    got = R.jgb_block(ROWS, '2026-10-23')
    assert got['10Y']['chg_bp'] == 1.5 and got['2Y']['chg_bp'] == 1.2


def test_jgb_ignores_rows_after_prev_session():
    got = R.jgb_block(ROWS, '2026-10-22')
    assert got['10Y']['period'] == '2026-10-22'


def test_jgb_stale_returns_none():
    got = R.jgb_block(ROWS[:2], '2026-10-23')
    assert got['10Y'] is None and 'why' in got


def test_jgb_missing_tenor_is_none():
    rows = [dict(r) for r in ROWS]
    del rows[-1]['30Y']
    assert R.jgb_block(rows, '2026-10-23')['30Y'] is None


def test_boj_values_drop_null():
    got = R.boj_values(CALL)
    assert len(got) == 1
    s = got[0]
    assert s['code'] == 'STRDCLUCON' and s['freq'] == 'DAILY'
    assert s['points'][-1] == ['2026-10-22', 1.227] and len(s['points']) == 4


def test_boj_period_formats():
    assert R.period('MONTHLY', 202609) == '2026-09'
    assert R.period('QUARTERLY', 202602) == '2026Q2'
    assert R.period('DAILY', 20261022) == '2026-10-22'


def test_call_rate_lag_ok():
    got = R.call_rate(CALL, '2026-10-26')
    assert got['value'] == 1.227 and got['period'] == '2026-10-22'


def test_call_rate_too_old():
    assert R.call_rate(CALL, '2026-10-30') is None


def test_resolve_series():
    meta = {'RESULTSET': [{'SERIES_CODE': 'A', 'NAME_OF_TIME_SERIES': 'Corporate Goods Price Index, All commodities'},
                          {'SERIES_CODE': 'B', 'NAME_OF_TIME_SERIES': 'Export Price Index'}]}
    assert R.resolve_series(meta, r'^Corporate Goods Price Index, All commodities$') == 'A'
    assert R.resolve_series(meta, r'^Nothing$') is None


def test_resolve_series_ambiguous_raises():
    meta = {'RESULTSET': [{'SERIES_CODE': 'A', 'NAME_OF_TIME_SERIES': 'X index'},
                          {'SERIES_CODE': 'B', 'NAME_OF_TIME_SERIES': 'X index (yen basis)'}]}
    with pytest.raises(ValueError):
        R.resolve_series(meta, r'^X index')
