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

