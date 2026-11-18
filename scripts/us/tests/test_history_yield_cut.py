"""국채 16:00 ET 전환 — 이력 기준 표시, 옛 행 소급, 기간 집계는 기준을 섞지 않는다."""
import json

from us import history as H
from us import period as P


def _cut(level):
    return {t: {'level': level, 'basis': 'cut_1600_et'} for t in ('2Y', '5Y', '10Y', '30Y')}


def test_market_record_marks_yields_basis_only_when_all_tenors_are_cut():
    assert H.market_record({'report_date': 'd', 'yields': _cut(4.0)})['basis']['yields'] == 'cut_1600_et'
    mixed = _cut(4.0)
    mixed['2Y'] = {'level': 4.0}
    assert 'yields' not in (H.market_record({'report_date': 'd', 'yields': mixed}).get('basis') or {})


def test_backfill_adds_cut_values_to_old_rows_and_keeps_printed(tmp_path):
    p = tmp_path / 'market.jsonl'
    old = {'report_date': '2026-11-05', 'yields': {'10Y': 4.90}}
    new = {'report_date': '2026-11-06', 'yields': {'10Y': 4.86}, 'basis': {'yields': 'cut_1600_et'}}
    p.write_text(json.dumps(old) + '\n' + json.dumps(new) + '\n')
    ledger = {'2026-11-05': {'tenors': {t: {'value': 4.8} for t in ('2Y', '5Y', '10Y', '30Y')}}}
    assert H.backfill_yield_cut(str(p), ledger) == 1
    rows = H.read_jsonl(str(p))
    assert rows[0]['yields'] == {'10Y': 4.90} and rows[0]['cut_1600']['yields']['10Y'] == 4.8
    assert H.backfill_yield_cut(str(p), ledger) == 0           # 멱등


def test_period_uses_cut_values_and_drops_old_rows_without_them():
    rows = [
        {'report_date': '2026-11-03', 'yields': {'10Y': 4.95}},                                   # 소급 없음 → 비움
        {'report_date': '2026-11-04', 'yields': {'10Y': 4.90}, 'cut_1600': {'yields': {'10Y': 4.88}}},
        {'report_date': '2026-11-05', 'yields': {'10Y': 4.83}, 'basis': {'yields': 'cut_1600_et'}},
    ]
    _, yh = P.series_from(rows)
    assert yh['10Y'] == [('2026-11-04', 4.88), ('2026-11-05', 4.83)]


def test_period_before_the_switch_is_unchanged():
    rows = [{'report_date': '2026-10-30', 'yields': {'10Y': 4.9}},
            {'report_date': '2026-11-06', 'yields': {'10Y': 4.8}, 'basis': {'yields': 'cut_1600_et'}}]
    # 지난 기간(전환 전)을 다시 굴리면 그때의 기준(종가 인쇄값) 그대로다 — 확정본과 같은 값.
    _, yh = P.series_from(rows, as_of='2026-10-30')
    assert ('2026-10-30', 4.9) in yh['10Y']


def _bench(dates):
    return {'indices': {'S&P 500': [(d, 100.0 + i) for i, d in enumerate(dates)]}}


def test_weekly_needs_the_exact_prior_session_cut():
    # 금요일(10/30) 컷이 없고 목요일만 있으면 W45 변화를 목요일부터 재지 않는다
    days = ['2026-10-29', '2026-10-30', '2026-11-02', '2026-11-03', '2026-11-04', '2026-11-05', '2026-11-06']
    closes = _bench(days)
    for g in ('sectors', 'fx', 'commodities', 'memory', 'ai_infra', 'mlcc'):
        closes.setdefault(g, {})
    yh = {t: [('2026-10-29', 4.6)] + [(d, 4.5) for d in days[2:]] for t in ('2Y', '5Y', '10Y', '30Y')}
    out = P.build('weekly', '2026-W45', closes, yh, {})
    assert 'yields' in out and not out['yields'].get('10Y')
    assert any('2026-10-30 기준값 없음' in m for m in out['missing'])


def test_yields_basis_helper():
    rows = [{'report_date': '2026-11-05'}, {'report_date': '2026-11-06', 'basis': {'yields': 'cut_1600_et'}}]
    assert P.yields_basis(rows) == 'cut_1600_et'
    assert P.yields_basis(rows, as_of='2026-11-05') is None


def test_backfill_bond_holiday_row_takes_the_prior_bond_session(tmp_path):
    # 2026-11-11(재향군인의 날)은 채권만 쉰다 — 그날 행은 11/10 컷을 붙인다
    p = tmp_path / 'market.jsonl'
    p.write_text(json.dumps({'report_date': '2026-11-11', 'yields': {'10Y': 4.9}}) + '\n')
    ledger = {'2026-11-10': {'tenors': {t: {'value': 4.7} for t in ('2Y', '5Y', '10Y', '30Y')}}}
    assert H.backfill_yield_cut(str(p), ledger, bond_closed={'2026-11-11'}) == 1
    assert H.read_jsonl(str(p))[0]['cut_1600']['yields']['10Y'] == 4.7
