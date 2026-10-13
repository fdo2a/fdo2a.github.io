"""수집기가 매일 만들어야 하는 파생 산출물이 main() 에 배선돼 있는가.

2026-09-22 병합 커밋(c7f6540)이 stance 블록을 지우면서 바로 아래의 매크로 지표·
가격 맥락·세션 맥락 블록까지 함께 지웠다. 셋 다 try/except 로 감싼 비-코어라
수집은 성공으로 끝났고, 모듈 단위 테스트 2,137개도 전부 통과했다 — 계산 함수는
멀쩡한데 부르는 곳이 없었기 때문이다. 그날 market_data.json 에서 `price_context`·
`session` 이 빠지고 macro_metrics.json 은 전날 날짜로 굳었다.

그래서 여기서는 함수가 아니라 **배선**을 본다.
"""
import inspect
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import collect_market_data as cmd  # noqa: E402

SRC = inspect.getsource(cmd.main)


def test_macro_metrics_are_computed_and_written():
    assert 'compute_macro_metrics(econ_series, econ, last_seen)' in SRC
    assert "'macro_metrics.json'" in SRC


def test_price_context_is_attached_to_market_data():
    assert "data['price_context'] = " in SRC


def test_session_context_is_attached_to_market_data():
    assert "data['session'] = " in SRC


def test_derived_blocks_run_before_market_data_is_written():
    # md_path 를 쓴 뒤에 붙이면 파일에는 안 들어간다.
    written = SRC.index('json.dump(data, open(md_path')
    for marker in ("data['price_context'] = ", "data['session'] = "):
        assert SRC.index(marker) < written


def test_econ_rows_carry_their_vs_prev_verdict():
    assert "e['vs_prev'] = vs_prev(" in SRC
    assert SRC.index("e['vs_prev'] = vs_prev(") < SRC.index("'econ_indicators.json'")


def test_econ_actual_previous_use_the_dated_transform_across_a_missing_month():
    """2025-10 CPI 결측 — Actual 은 BLS 와 같은 12개월 변화여야 한다(3.71 이 아니라)."""
    vals, y, m = [], 2024, 1
    for i in range(32):                                   # 2024-01 .. 2026-08
        d = f'{y:04d}-{m:02d}-01'
        if d != '2025-10-01':
            vals.append((d, 100.0 + i))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    actual, previous = cmd._econ_pair(vals, 'yoy_pct')
    assert round(actual, 4) == round((131 / 119 - 1) * 100, 4)
    assert round(previous, 4) == round((130 / 118 - 1) * 100, 4)


def test_econ_pair_refuses_when_the_latest_month_cannot_be_transformed():
    vals = [('2026-07-01', 100.0), ('2026-09-01', 101.0)]   # 08 결측 -> 09 MoM 없음
    assert cmd._econ_pair(vals, 'mom_pct') is None


def test_econ_pair_refuses_a_previous_that_is_not_the_month_before():
    vals = [('2026-06-01', 100.0), ('2026-07-01', 101.0), ('2026-09-01', 102.0), ('2026-10-01', 103.0)]
    assert cmd._econ_pair(vals, 'mom_pct') is None        # 09 MoM 없음 -> 10 의 직전이 07 이 된다
