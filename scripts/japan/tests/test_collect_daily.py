"""일본 일간 수집기 — 네트워크는 주입한다 (codex 설계 검토 #1·#3·#10)."""
import json
import os
from datetime import datetime, timezone

import pytest

import collect_japan_daily as C

S, P = '2026-10-26', '2026-10-23'
NK = ('Date of Data,Close,Open,High,Low\r\n"2026/10/23","62693.16","1","1","1"\r\n'
      '"2026/10/26","62189.65","1","1","1"\r\n')
JGB = ('Date,1Y,2Y,5Y,10Y,30Y\r\n2026/10/22,1.3,1.63,1.86,2.31,3.92\r\n'
       '2026/10/23,1.3,1.642,1.872,2.325,3.904\r\n')


def _fx_bars(v_prev, v_today):
    out = []
    for day, v in ((P, v_prev), (S, v_today)):
        out.append((f'{day}T16:20:00+09:00', v - 0.1))
        out.append((f'{day}T16:25:00+09:00', v))
    return out


class Fake:
    def __init__(self, **over):
        self.over = over
        self.calls = []

    def nikkei_csv(self):
        if 'nikkei_csv' in self.over:
            v = self.over['nikkei_csv']
            if isinstance(v, Exception):
                raise v
            return v
        return NK

    def quote(self, ticker):
        q = self.over.get('quote', {})
        if ticker in q:
            return q[ticker]
        if ticker == '^N225':
            return {'last': 62189.65, 'bar_date': S}
        return {'last': 100.0, 'bar_date': S}

    def daily_closes(self, ticker):
        return self.over.get('closes', {}).get(ticker) or [[P, 99.0], [S, float('nan')]]

    def splits(self, ticker):
        return self.over.get('splits', {}).get(ticker, [])

    def fx_bars(self, ticker):
        if self.over.get('fx_fail'):
            raise TimeoutError('fx')
        return _fx_bars(157.0, 157.55)

    def jgb_rows(self):
        from common import weekly_sources as WS
        return self.over.get('jgb_rows') or WS.parse_jgb_csv(JGB)

    def boj(self, db, code):
        if code == 'STRDCLUCON':
            d = self.over.get('call_date', 20261022)
            return {'RESULTSET': [{'SERIES_CODE': code, 'FREQUENCY': 'DAILY', 'UNIT': '%',
                                   'VALUES': {'SURVEY_DATES': [d], 'VALUES': [1.227]}}]}
        return {'RESULTSET': [{'SERIES_CODE': code, 'FREQUENCY': 'MONTHLY', 'UNIT': 'CY2020 average=100',
                               'VALUES': {'SURVEY_DATES': [202608, 202609], 'VALUES': [100.0, 101.0]}}]}

    def boj_codes(self):
        return {'cgpi': ('PR01', 'A'), 'sppi': ('PR02', 'B'), 'money_stock': ('MD02', 'C'),
                'monetary_base': ('MD01', 'D')}


CAL = {'checked_at': S, 'events': []}
NOW = datetime(2026, 10, 26, 8, 0, tzinfo=timezone.utc)


def _run(tmp_path, fake=None, **kw):
    return C.collect(S, P, fake or Fake(), NOW, root=str(tmp_path), calendar=CAL, **kw)


def test_complete_with_official_match(tmp_path):
    snap = _run(tmp_path)
    assert snap['complete'] and snap['indices']['nikkei']['value'] == 62189.65
    assert snap['indices']['nikkei']['chg_pct'] == -0.8
    assert snap['indices']['nikkei']['denom'] == {'date': P, 'value': 62693.16, 'source': 'nikkei_official'}
    assert os.path.exists(tmp_path / 'japan' / 'data' / 'daily' / 'candidate' / f'{S}.json')


def test_complete_false_when_official_missing(tmp_path):
    snap = _run(tmp_path, Fake(nikkei_csv=NK.split('"2026/10/26"')[0]))
    assert not snap['complete'] and snap['fetch_status']['nikkei'] != 'ok'


def test_fetch_failure_recorded_and_blocks_core(tmp_path):
    snap = _run(tmp_path, Fake(nikkei_csv=TimeoutError('nikkei')))
    assert not snap['complete'] and 'TimeoutError' in snap['fetch_status']['nikkei_csv']


def test_noncore_failure_drops_block_only(tmp_path):
    snap = _run(tmp_path, Fake(fx_fail=True))
    assert snap['complete'] and snap['fx'] == {} and 'fx' in snap['fetch_status']
    assert snap['fetch_status']['fx'] != 'ok'


def test_stale_quote_excluded(tmp_path):
    snap = _run(tmp_path, Fake(quote={'1617.T': {'last': 50000.0, 'bar_date': P}}))
    row = next(s for s in snap['sectors'] if s['code'] == '1617')
    assert row['value'] is None and not row['ok']


def test_snapshot_records_basis_and_times(tmp_path):
    snap = _run(tmp_path)
    fx = snap['fx']['usdjpy']
    assert fx['value'] == 157.55 and fx['basis'] == 'bar_end_1630_jst' and fx['chg_pct'] == 0.35
    assert snap['jgb']['10Y']['period'] == P and snap['jgb']['10Y']['chg_bp'] == 1.5
    assert snap['call_rate']['period'] == '2026-10-22'
    assert snap['ran_at'] and snap['session'] == S and snap['prev_session'] == P
    assert snap['calendar']['version'] and snap['cut'] == '16:30'
    assert snap['fx']['krw_per_100jpy']['multiplier'] == 100


def test_refuses_to_overwrite_published(tmp_path):
    pub = tmp_path / 'japan' / 'data' / 'daily'
    pub.mkdir(parents=True)
    (pub / f'{S}.json').write_text('{}', encoding='utf-8')
    with pytest.raises(C.AlreadyPublished):
        _run(tmp_path)


def test_macro_periods_carried(tmp_path):
    snap = _run(tmp_path)
    assert snap['macro_periods']['cgpi'] == '2026-09'


def test_reconcile_never_touches_published(tmp_path):
    pub = {'session': P, 'indices': {'nikkei': {'value': 62693.16}}}
    rows = C.reconcile(pub, {'^N225': [[P, 62693.16]]})
    assert rows == []
    rows = C.reconcile(pub, {'^N225': [[P, 62000.0]]})
    assert rows[0]['kind'] == 'mismatch' and rows[0]['field'] == 'indices.nikkei'
    assert json.dumps(pub) == json.dumps({'session': P, 'indices': {'nikkei': {'value': 62693.16}}})


def test_split_not_reapplied_to_adjusted_daily_bars(tmp_path):
    # codex 구현 검토 #10 — yfinance 일봉 분모는 이미 분할조정이다
    fake = Fake(quote={'1617.T': {'last': 82.0, 'bar_date': S}}, closes={'1617.T': [[P, 100.0]]},
                splits={'1617.T': [[S, 2.0]]})
    row = next(r for r in _run(tmp_path, fake)['sectors'] if r['code'] == '1617')
    assert row['chg_pct'] == -18.0


def test_jgb_month_boundary(tmp_path):
    rows = [{'date': '2026-09-30', '10Y': 2.8}, {'date': '2026-10-01', '10Y': 2.85}]
    snap = C.collect('2026-10-02', '2026-10-01', Fake(jgb_rows=rows, nikkei_csv=NK), NOW,
                     root=str(tmp_path), calendar=CAL)
    assert snap['jgb']['10Y']['chg_bp'] == 5.0


def test_call_rate_freshness_counts_jp_holidays(tmp_path):
    snap = C.collect('2026-09-25', '2026-09-24', Fake(call_date=20260918), NOW, root=str(tmp_path),
                     calendar=CAL, holidays=('2026-09-21', '2026-09-22', '2026-09-23'))
    assert snap['call_rate'] and snap['call_rate']['period'] == '2026-09-18'


def test_stocks_recorded_for_history(tmp_path):
    snap = _run(tmp_path)
    codes = {r['code'] for r in snap['stocks']}
    assert '7203' in codes and all(r['value'] == 100.0 for r in snap['stocks'])


def test_sector_breadth_recorded(tmp_path):
    snap = _run(tmp_path, Fake(quote={'1617.T': {'last': 50000.0, 'bar_date': P}}))
    b = snap['sector_breadth']
    assert b == {'total': 17, 'counted': 16, 'up': 16, 'down': 0, 'flat': 0}
