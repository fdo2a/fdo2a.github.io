"""주간 스냅샷 소스 파서 — 픽스처는 전부 2026-09-26 실측 원문에서 잘라 왔다."""
from datetime import date
from pathlib import Path

import pytest

from scripts.common import weekly_sources as W

FIX = Path(__file__).resolve().parent / 'fixtures'


def _week_text():
    return (FIX / 'mof_week_sample.csv').read_text(encoding='utf-8')


def test_mof_week_parses_every_period_row_and_nothing_else():
    rows = W.parse_mof_week(_week_text())
    # 픽스처의 데이터 행은 일곱 줄 — 머리말·각주는 행이 아니다.
    assert [r['week_end'] for r in rows] == [
        '2005-01-08', '2005-01-29', '2025-12-27', '2026-01-03', '2026-01-10', '2026-09-05', '2026-09-12']


def test_mof_week_period_that_crosses_the_year_carries_the_new_year():
    # 「2025．12．28〜2026．1．3」 — 끝 날짜에 연도가 붙는 유일한 꼴.
    row = next(r for r in W.parse_mof_week(_week_text()) if r['week_start'] == '2025-12-28')
    assert row['week_end'] == '2026-01-03'


def test_mof_week_columns_follow_the_published_order():
    last = W.parse_mof_week(_week_text())[-1]
    # 2026．9．6〜9．12 원문: 거주자 해외 중장기채 순취득 10,829 · 비거주자 일본주식 -15,228 (억 엔)
    assert last['res_foreign_equity_net'] == 1692
    assert last['res_foreign_ltdebt_net'] == 10829
    assert last['nonres_jp_equity_net'] == -15228
    assert last['nonres_jp_ltdebt_net'] == 22362


def test_mof_week_decodes_cp932_bytes():
    raw = _week_text().encode('cp932', errors='replace')
    assert W.parse_mof_week(W.decode_cp932(raw))[-1]['res_foreign_ltdebt_net'] == 10829


def test_jgb_curve_rows_are_dated_and_keyed_by_tenor():
    rows = W.parse_jgb_csv((FIX / 'jgbcme_sample.csv').read_text(encoding='utf-8'))
    assert rows[-1]['date'] == '2026-09-24'
    assert rows[-1]['2Y'] == 1.912 and rows[-1]['10Y'] == 3.073 and rows[-1]['40Y'] == 4.103
    assert [r['date'] for r in rows] == ['2026-09-01', '2026-09-02', '2026-09-18', '2026-09-24']


def test_jgb_curve_missing_cells_are_absent_not_zero():
    text = 'Date,1Y,2Y,10Y\n2026/9/1,-,1.8,3.0\n'
    row = W.parse_jgb_csv(text)[0]
    assert '1Y' not in row and row['2Y'] == 1.8


def test_cftc_row_keeps_both_classifications_as_integers():
    raw = {'report_date_as_yyyy_mm_dd': '2026-09-15T00:00:00.000',
           'lev_money_positions_long': '110302', 'lev_money_positions_short': '87132',
           'asset_mgr_positions_long': '118873', 'asset_mgr_positions_short': '65028',
           'open_interest_all': '300000'}
    row = W.cftc_tff_row(raw)
    assert row == {'date': '2026-09-15', 'lev_long': 110302, 'lev_short': 87132,
                   'am_long': 118873, 'am_short': 65028, 'oi': 300000}


def test_fed_funds_contract_symbols_follow_cme_month_codes():
    # ZQ=F 는 쓰지 않는다 — 2026-09-25 에 9월물에서 11월물 값으로 조용히 롤했다.
    got = W.fed_funds_contracts(date(2026, 9, 26), months=4)
    assert got == [('2026-09', 'ZQU26.CBT'), ('2026-10', 'ZQV26.CBT'),
                   ('2026-11', 'ZQX26.CBT'), ('2026-12', 'ZQZ26.CBT')]


def test_fed_funds_contracts_roll_into_the_next_year():
    assert W.fed_funds_contracts(date(2026, 12, 3), months=2) == [
        ('2026-12', 'ZQZ26.CBT'), ('2027-01', 'ZQF27.CBT')]


def test_implied_rate_is_hundred_minus_price():
    assert W.implied_rate(95.965) == pytest.approx(4.035)


def test_copied_rows_are_dropped_only_when_close_and_volume_both_repeat():
    # 2026-09-24 ZQX26: 9/23 과 종가·거래량이 같았다(전일 복사).
    rows = [['2026-09-22', 95.98, 131681], ['2026-09-23', 95.945, 221008],
            ['2026-09-24', 95.95, 221008], ['2026-09-25', 95.965, 105561],
            ['2026-09-26', 95.965, 105561]]
    kept, dropped = W.drop_copied_rows(rows)
    assert dropped == ['2026-09-26']
    assert [d for d, _ in kept] == ['2026-09-22', '2026-09-23', '2026-09-24', '2026-09-25']
