"""수집기 `collect_cut_rows` 와 `close_cut.session_ends` 의 접합부.

2026-11-20 세션(S&P -3.7%)은 마지막 30분봉 종가와 공식 종가가 0.117% 벌어져 세션에서 빠졌고,
환율·원자재 8행이 전부 None 이 돼 발행이 멈췄다. `session_ends` 가 고저 범위를 볼 줄 알아도
수집기가 S&P 봉에 고저가를 싣지 않으면 고쳐지지 않는다 — 여기서는 그 연결을 본다.
"""
import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import collect_market_data as cmd  # noqa: E402

TZ = 'America/New_York'
SPX_DAILY = {'2026-11-19': 7175.83, '2026-11-20': 6910.39}
# (날짜, 종가, 고가, 저가) — 15:30-16:00 봉. 11/20 은 실측값.
SPX_LAST = {'2026-11-19': (7177.56, 7190.0, 7170.0), '2026-11-20': (6918.45, 6955.41, 6882.66)}


def _frame(rows):
    idx = pd.DatetimeIndex([pd.Timestamp(ts).tz_convert(TZ) for ts, *_ in rows])
    return pd.DataFrame([dict(zip(('Close', 'High', 'Low'), vals)) for _, *vals in rows], index=idx)


class FakeTicker:
    def __init__(self, sym):
        self.sym = sym

    def history(self, period=None, interval=None):
        if self.sym == cmd.ANCHOR_TICKER and interval is None:
            return _frame([(f'{d}T00:00:00-05:00', v, v, v) for d, v in SPX_DAILY.items()])
        if self.sym == cmd.ANCHOR_TICKER:
            return _frame([(f'{d}T15:30:00-05:00', *vals) for d, vals in SPX_LAST.items()])
        # 종목 봉: 양일 15:30 봉, 11/20 이 1% 높다.
        return _frame([('2026-11-19T15:30:00-05:00', 100.0, 100.0, 100.0),
                       ('2026-11-20T15:30:00-05:00', 101.0, 101.0, 101.0)])


@pytest.fixture
def fake_yf(monkeypatch):
    import types
    mod = types.SimpleNamespace(Ticker=FakeTicker)
    monkeypatch.setitem(sys.modules, 'yfinance', mod)
    monkeypatch.setattr(cmd.time, 'sleep', lambda *_: None)


def test_volatile_close_day_yields_every_cut_row(fake_yf):
    out = cmd.collect_cut_rows('2026-11-20')
    for group, pairs in (('fx', cmd.FX), ('commodities', cmd.CMDTY)):
        for name, _ in pairs:
            row = out[group][name]
            assert row is not None, f'{group}/{name}'
            assert row['prev_date'] == '2026-11-19' and row['cut_et'] == '16:00'
            assert row['pct'] == pytest.approx(1.0)


def test_instrument_bars_stay_close_only(fake_yf):
    # 종목 봉은 지금처럼 (시각, 종가) — 고저가는 S&P 세션 검증에만 쓴다.
    assert all(len(b) == 2 for b in cmd._bars30('CL=F'))
    assert all(len(b) == 4 for b in cmd._bars30(cmd.ANCHOR_TICKER, hl=True))
