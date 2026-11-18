"""1a 구현 검토 3회차(codex IMPL NO, 2026-11-18) — 수집·점수 쪽.

G1 승인 예외는 「어느 비교 달이 원천에 없는가」까지 같아야 한다(2025-10 하나) · G2 축 점수에 실제로 쓰이지 않은 지표는
전부 결측·산출 범위에 든다, 전체 수는 그 축에 정의된 점수 대상 수 · G5 최신값이 계산되면 직전값이 없어도 행을 만든다
(previous·vs_prev 는 null, 대체값 없음). 검사 쪽(G1 의 일치 판정)은 `scripts/verification/tests/test_impl_review_r3.py`.
"""
import json
import os
import subprocess
import sys

import pytest

import collect_market_data as cmd
from us import macro_metrics as M
from us import macro_table_gate as T

SCRIPTS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
D = '2026-11-16'


def monthly(first, last, skip=(), base=300.0, step=1.0):
    y, m = int(first[:4]), int(first[5:7])
    out, i = [], 0
    while f'{y}-{m:02d}' <= last:
        k = f'{y}-{m:02d}'
        if k not in skip:
            out.append((f'{k}-01', base + step * i))
        i += 1
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


# ── G5. 최신값이 계산되면 직전값이 없어도 행을 만든다 ───────────────────────────────────────

def test_g5_latest_without_previous_is_a_row_with_null_previous():
    # 2026-12-10 뒤: 2025-10 이 원천에 없다 → 2026-10 전년 대비는 못 만들고, 2026-11 전년 대비는 만든다(2025-11 있음)
    vals = monthly('2023-01', '2026-11', skip=('2025-10',))
    pair = cmd._econ_pair(vals, 'yoy_pct')
    assert pair is not None                                   # 재현: 전에는 None(직전 달이 없다고 행을 버렸다)
    actual, previous = pair
    want = (dict(vals)['2026-11-01'] / dict(vals)['2025-11-01'] - 1) * 100
    assert actual == pytest.approx(want) and previous is None  # 2026-09 값을 「직전」으로 끌어오지 않는다
    # 전월 대비는 직전 달이 곧 비교 달이다 — 평소대로
    a, p = cmd._econ_pair(vals, 'mom_pct')
    assert p is not None
    # 최신값 자체를 만들 수 없으면 지금처럼 결측
    assert cmd._econ_pair(monthly('2023-01', '2026-10', skip=('2025-10',)), 'yoy_pct') is None
    assert cmd._econ_pair(monthly('2023-01', '2026-11', skip=('2026-10',)), 'mom_pct') is None
    # 평소(빠진 달 없음)는 그대로 둘 다
    a, p = cmd._econ_pair(monthly('2023-01', '2026-11'), 'yoy_pct')
    assert a is not None and p is not None


def test_g5_row_builder_keeps_previous_null(monkeypatch):
    vals = monthly('2019-01', '2026-11', skip=('2025-10',))
    monkeypatch.setattr(cmd, 'ECON', [('Inflation', 'CPI YoY', 'CPIAUCSL', 'yoy_pct', '%')])
    monkeypatch.setattr(cmd, 'fred_series', lambda sid: vals)
    monkeypatch.setattr(cmd.time, 'sleep', lambda s: None)
    reasons, refs = {}, {}
    rows, series = cmd.collect_econ(reasons, refs)
    assert reasons == {} and refs == {}
    (row,) = rows
    assert row['ref_period'] == '2026-11-01' and row['previous'] is None and isinstance(row['actual'], float)
    assert M.vs_prev('CPI YoY', 'Inflation', row['actual'], row['previous']) is None


def test_g5_score_comes_from_history_not_from_the_table_previous():
    vals = monthly('2019-01', '2026-11', skip=('2025-10',), step=1.3)
    item = {'axis': 'Inflation', 'name': 'CPI YoY', 'fred_id': 'CPIAUCSL', 'transform': 'yoy_pct', 'units': '%',
            'actual': 4.2, 'previous': None, 'ref_period': '2026-11-01'}
    with_prev = dict(item, previous=4.0)
    a = M.compute({'CPIAUCSL': vals}, [item])['indicators'][0]
    b = M.compute({'CPIAUCSL': vals}, [with_prev])['indicators'][0]
    assert a['signed_z'] is not None and a['signed_z'] == b['signed_z']       # 점수는 직전 표 칸과 무관하다
    assert a['previous'] is None and a['vs_prev'] is None and b['vs_prev'] is not None


TABLE = ('<section><h2>매크로</h2><div class="card"><h3>물가(Inflation)</h3><div class="tbl-scroll"><table>'
         '<tr><th>지표</th><th>Actual</th><th>Forecast</th><th>Previous</th><th>발표일</th><th>컨센 대비</th>'
         '<th>직전 대비</th><th>추세</th></tr>'
         '<tr data-indicator="CPI YoY"><td>소비자물가 전년비</td><td>{actual}</td><td>—</td><td>{prev}</td><td>12/10</td>'
         '<td>—</td><td data-vs-prev>{vs}</td><td data-trend>{trend}</td></tr></table></div>'
         '<div class="caption" data-trend-note>' + M.TREND_NOTE_KO + '</div></div></section>')


def test_g5_table_gate_accepts_dashes_for_the_missing_previous_and_rejects_a_filled_one():
    vals = monthly('2019-01', '2026-11', skip=('2025-10',), step=1.3)
    item = {'axis': 'Inflation', 'name': 'CPI YoY', 'fred_id': 'CPIAUCSL', 'transform': 'yoy_pct', 'units': '%',
            'actual': 4.2, 'previous': None, 'ref_period': '2026-11-01', 'vs_prev': None}
    mm = dict(M.compute({'CPIAUCSL': vals}, [item]), report_date='2026-12-10')
    trend = mm['indicators'][0]['trend_cell_ko']
    ok = TABLE.format(actual='4.2%', prev='—', vs='—', trend=trend)
    assert T.check_tables(ok, [item], mm, '2026-12-10') == []
    for bad in (TABLE.format(actual='4.2%', prev='4.0%', vs='—', trend=trend),      # 직전 칸을 다른 달 값으로 채웠다
                TABLE.format(actual='4.2%', prev='—', vs='상승', trend=trend),        # 직전 대비를 지어냈다
                TABLE.format(actual='4.0%', prev='—', vs='—', trend=trend)):         # 최신값이 다르다
        assert T.check_tables(bad, [item], mm, '2026-12-10'), bad


# ── G1. 어느 비교 달이 원천에 없는가 ─────────────────────────────────────────────────────────

def _run_econ(monkeypatch, vals):
    monkeypatch.setattr(cmd, 'ECON', [('Inflation', 'CPI YoY', 'CPIAUCSL', 'yoy_pct', '%'),
                                      ('Inflation', 'CPI MoM', 'CPIAUCSL', 'mom_pct', '%')])
    monkeypatch.setattr(cmd, 'fred_series', lambda sid: vals)
    monkeypatch.setattr(cmd.time, 'sleep', lambda s: None)
    reasons, refs = {}, {}
    rows, _ = cmd.collect_econ(reasons, refs)
    return rows, reasons, refs, cmd.econ_collect(rows, reasons, D, refs)


def test_g1_collector_states_which_comparison_month_is_absent(monkeypatch):
    rows, reasons, refs, col = _run_econ(monkeypatch, monthly('2019-01', '2026-10', skip=('2025-10',)))
    assert reasons == {'CPI YoY': 'no_value'}
    assert col['missing_ref']['no_value:CPI YoY'] == {'fred_id': 'CPIAUCSL', 'transform': 'yoy_pct',
                                                     'ref_period': '2026-10', 'lacking': ['2025-10']}


def test_g1_another_cause_is_not_recorded_as_the_approved_one(monkeypatch):
    # 비교 달(2025-10)은 있는데 값이 0 이라 변환이 안 된다 — 「그 달이 원천에 없다」가 아니다
    vals = [(d, 0.0 if d == '2025-10-01' else v) for d, v in monthly('2019-01', '2026-10')]
    rows, reasons, refs, col = _run_econ(monkeypatch, vals)
    assert reasons.get('CPI YoY') == 'no_value' and col['missing_ref']['no_value:CPI YoY']['lacking'] == []
    # 전월 대비가 못 만들어진 것은 다른 달(2026-09)이 없는 것이다
    rows, reasons, refs, col = _run_econ(monkeypatch, monthly('2019-01', '2026-10', skip=('2026-09',)))
    assert reasons == {'CPI MoM': 'no_value'}
    assert col['missing_ref']['no_value:CPI MoM']['lacking'] == ['2026-09']


def test_g1_lacking_travels_with_the_key_through_the_chain(monkeypatch):
    import eval_macro_regime
    import fetch_releases
    rows, reasons, refs, econ = _run_econ(monkeypatch, monthly('2019-01', '2026-10', skip=('2025-10',)))
    mm = cmd.macro_metrics_collect({'book_state': 'ok'}, econ, D)
    ev = eval_macro_regime.eval_collect(D, 'fresh', {'collect': mm}, 'ok')
    idx = fetch_releases.index_collect({'report_date': D, 'releases': [{'key': 'cpi', 'ok': True}]}, 'fresh', mm)
    assert mm['missing_ref']['econ:no_value:CPI YoY']['lacking'] == ['2025-10']
    assert ev['missing_ref']['metrics:econ:no_value:CPI YoY']['lacking'] == ['2025-10']
    assert idx['missing_ref'] == ev['missing_ref']


# ── G2. 축 점수에 쓰이지 않은 지표는 전부 결측·산출 범위에 든다 ──────────────────────────────

NAMES = ('CPI MoM', 'Core CPI MoM', 'PPI Final Demand MoM', 'PCE Price Index YoY', 'Core PCE YoY',
         'Michigan 1-Yr Inflation Exp')
EXPECTED = [('Inflation', n) for n in ('CPI YoY', 'Core CPI YoY') + NAMES] + [('Labor', 'Nonfarm Payrolls (chg)')]
EXCL = [{'name': 'CPI YoY', 'axis': 'Inflation', 'fred_id': 'CPIAUCSL', 'transform': 'yoy_pct', 'ref_period': '2026-10',
         'lacking': ['2025-10']},
        {'name': 'Core CPI YoY', 'axis': 'Inflation', 'fred_id': 'CPILFESL', 'transform': 'yoy_pct',
         'ref_period': '2026-10', 'lacking': ['2025-10']}]


def metrics(zs, **over):
    ind = [dict({'name': n, 'label_ko': M.LABELS_KO.get(n, n), 'axis': 'Inflation', 'role': 'scored',
                 'introduced': False, 'signed_z': z}, **over.get(n, {})) for n, z in zip(NAMES, zs)]
    ind.append({'name': 'Nonfarm Payrolls (chg)', 'axis': 'Labor', 'role': 'scored', 'introduced': False, 'signed_z': 0.4})
    return {'indicators': ind, 'book_state': 'ok',
            'axis_summary': {'Inflation': {'label_ko': '물가'}, 'Labor': {'label_ko': '고용'}}}


def test_g2_a_row_without_a_score_is_excluded_and_counted():
    # codex 재현: 승인된 두 행 말고 다른 물가 지표가 행은 있는데 점수가 없다 — 전에는 total 7(=5+2), excluded 2
    mm = M.with_coverage(metrics([0.5, 0.5, None, 0.5, 0.5, 0.5]), EXCL, EXPECTED)
    c = mm['coverage']['Inflation']
    assert (c['total'], c['used']) == (8, 5)                   # 전체 = 그 축에 정의된 점수 대상 수
    assert [(e['name'], e['why']) for e in c['excluded']] == [('CPI YoY', 'no_value'), ('Core CPI YoY', 'no_value'),
                                                              ('PPI Final Demand MoM', 'no_score')]
    assert '8개 중 5개' in c['phrase_ko'] and '원천 미발표' in c['phrase_ko'] and '이력 부족' in c['phrase_ko']
    # 수집 상태에도 사유를 가른 키로 — 다른 결측이 섞인 날은 승인 예외가 걸리지 않는다
    econ = {'status': 'partial', 'missing': ['no_value:CPI YoY', 'no_value:Core CPI YoY'],
            'missing_ref': {'no_value:CPI YoY': {'x': 1}, 'no_value:Core CPI YoY': {'x': 2}}}
    col = cmd.macro_metrics_collect(mm, econ, D)
    assert col['missing'] == ['econ:no_value:CPI YoY', 'econ:no_value:Core CPI YoY', 'no_score:PPI Final Demand MoM']
    assert col['status'] == 'partial' and 'no_score:PPI Final Demand MoM' not in col['missing_ref']


def test_g2_unused_rows_alone_also_make_the_file_partial():
    mm = M.with_coverage(metrics([0.5, None, 0.5, 0.5, 0.5, 0.5]), [], EXPECTED + [('Inflation', 'x')][:0])
    c = mm['coverage']['Inflation']
    assert (c['total'], c['used']) == (8, 5) and {e['why'] for e in c['excluded']} == {'no_row', 'no_score'}
    col = cmd.macro_metrics_collect(mm, {'status': 'ok', 'missing': []}, D)
    assert col['status'] == 'partial' and 'no_score:Core CPI MoM' in col['missing']


def test_g2_introduced_row_is_out_of_the_score_and_said_so():
    mm = M.with_coverage(metrics([0.5] * 6, **{'CPI MoM': {'introduced': True}}),
                         [], [e for e in EXPECTED if e[1] not in ('CPI YoY', 'Core CPI YoY')])
    c = mm['coverage']['Inflation']
    assert (c['total'], c['used']) == (6, 5) and [(e['name'], e['why']) for e in c['excluded']] == [('CPI MoM', 'introduced')]
    assert cmd.macro_metrics_collect(mm, {'status': 'ok', 'missing': []}, D)['missing'] == ['introduced:CPI MoM']


def test_g2_whole_axis_scored_means_no_coverage_block():
    full = [e for e in EXPECTED if e[1] not in ('CPI YoY', 'Core CPI YoY')]
    mm = M.with_coverage(metrics([0.5] * 6), [], full)
    assert 'coverage' not in mm
    assert cmd.macro_metrics_collect(mm, {'status': 'ok', 'missing': []}, D)['status'] == 'ok'


def test_g2_expected_comes_from_the_econ_table():
    exp = cmd.expected_scored()
    assert len(exp) == sum(1 for e in cmd.ECON if not (len(e) > 5 and (e[5] or {}).get('role') == 'anatomy'))
    assert sum(1 for a, _ in exp if a == 'Inflation') == 8 and ('Inflation', 'CPI YoY') in exp


def _hold(m):
    sys.path.insert(0, SCRIPTS)
    import check_macro
    return check_macro.coverage_hold(m)


def test_g2_gate_finds_unused_rows_even_when_both_records_omit_them():
    # 수집 상태도 산출 범위도 말하지 않은 점수 결측 — 게이트가 행에서 직접 본다
    m = dict(metrics([5.0, 5.0, None, 5.0, 5.0, 5.0]), collect={'status': 'ok', 'missing': []})
    assert 'PPI Final Demand MoM' in _hold(m)                  # 재현: 전에는 None(결측이 없다고 봤다)
    m = M.with_coverage(metrics([5.0] * 6), EXCL, EXPECTED)
    m['collect'] = {'status': 'partial', 'missing': ['econ:no_value:CPI YoY', 'econ:no_value:Core CPI YoY']}
    assert _hold(m) is None                                    # 승인된 둘뿐이고 판단이 안 바뀌는 날
    m['indicators'][2]['signed_z'] = None                      # 산출 범위가 말하지 않은 세 번째
    assert _hold(m) is not None
