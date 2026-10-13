"""collect_sector_performance 는 종목별 마지막 봉 날짜를 남긴다."""
import importlib
import sys
import types

import pandas as pd

cmd = importlib.import_module('collect_market_data')


def _frame(late_ticker=None):
    days = pd.bdate_range('2025-09-01', '2026-10-12')
    cols = {}
    for _, t in cmd.SECTORS:
        s = pd.Series(range(100, 100 + len(days)), index=days, dtype=float)
        if t == late_ticker:
            s.iloc[-1] = float('nan')        # 마지막 봉이 비어 하루 이른 날이 끝이 된다
        cols[(t, 'Close')] = s
    return pd.DataFrame(cols)


def _run(monkeypatch, df):
    fake = types.SimpleNamespace(download=lambda *a, **k: df)
    monkeypatch.setitem(sys.modules, 'yfinance', fake)
    return cmd.collect_sector_performance()


def test_rows_carry_their_own_last_bar_date(monkeypatch):
    out, as_of = _run(monkeypatch, _frame(late_ticker='XLC'))
    assert out['Communication Services']['date'] == '2026-10-09'
    assert out['Technology']['date'] == '2026-10-12'
    assert as_of == '2026-10-12'


def test_as_of_is_the_latest_row_even_when_the_first_ticker_is_late(monkeypatch):
    first = cmd.SECTORS[0][1]
    out, as_of = _run(monkeypatch, _frame(late_ticker=first))
    assert as_of == '2026-10-12'
