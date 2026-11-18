"""1a 구현 검토 4회차(codex IMPL NO, 2026-11-18) — H1 「미발표」의 근거, H2 표식은 축마다 하나, H3 들인 날은 조건.

H1: `not_published` 는 원천이 그 달 행을 주고 값 칸이 **명시적으로 빈 표기**일 때만 — 공식 API 의 `"."`, fredgraph.csv 의
빈 문자열·`.`. 값 필드가 없거나 null 이거나 알 수 없는 형식이면 근거가 없다 → `unknown`(보류).
"""
import json
import os
import subprocess
import sys

import pytest

import collect_market_data as cmd
from us import fred as F
from us import macro_gate as G
from us import macro_metrics as M
from us.tests.test_impl_review_r3 import D, monthly

SCRIPTS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def api_client(observations):
    c = F.FredClient(key='k' * 32)
    c.transport = 'api'
    c._json = lambda url: {'count': len(observations), 'observations': observations}
    return c


def csv_client(body):
    c = F.FredClient(key=None)
    c.transport = 'csv'
    c._get = lambda url: body.encode()
    return c


OK = [{'date': '2025-09-01', 'value': '324.3'}, {'date': '2025-11-01', 'value': '325.063'}]


@pytest.mark.parametrize('row,blank,unclear', [
    ({'date': '2025-10-01', 'value': '.'}, True, False),              # 공식 API 의 빈 표기
    ({'date': '2025-10-01'}, False, True),                            # codex 재현 — 값 필드가 없다(전에는 미발표)
    ({'date': '2025-10-01', 'value': None}, False, True),
    ({'date': '2025-10-01', 'value': ''}, False, True),               # API 는 빈 문자열을 쓰지 않는다 — 모르는 형식
    ({'date': '2025-10-01', 'value': 'N/A'}, False, True),
    ({'date': '2025-10-01', 'value': ' . '}, False, True),
])
def test_h1_api_only_the_dot_is_an_explicit_blank(row, blank, unclear):
    c = api_client([OK[0], row, OK[1]])
    assert c.series('CPIAUCSL') == [('2025-09-01', 324.3), ('2025-11-01', 325.063)]       # 계약은 그대로
    assert (c.blank_dates['CPIAUCSL'] == ['2025-10-01']) is blank
    assert (c.unclear_dates['CPIAUCSL'] == ['2025-10-01']) is unclear


@pytest.mark.parametrize('line,blank,unclear', [
    ('2025-10-01,', True, False),                                     # fredgraph.csv 의 빈칸
    ('2025-10-01,.', True, False),                                    # 옛 표기
    ('2025-10-01', False, True),                                      # 값 칸 자체가 없다
    ('2025-10-01,N/A', False, True),
    ('2025-10-01, ', False, True),
    ('2025-10-01,#N/A', False, True),
])
def test_h1_csv_only_empty_or_dot_is_an_explicit_blank(line, blank, unclear):
    c = csv_client(f'observation_date,CPIAUCSL\n2025-09-01,324.3\n{line}\n2025-11-01,325.063\n')
    assert c.series('CPIAUCSL') == [('2025-09-01', 324.3), ('2025-11-01', 325.063)]
    assert (c.blank_dates['CPIAUCSL'] == ['2025-10-01']) is blank
    assert (c.unclear_dates['CPIAUCSL'] == ['2025-10-01']) is unclear


def _states(monkeypatch, blanks, unclear):
    monkeypatch.setattr(cmd, 'ECON', [('Inflation', 'CPI YoY', 'CPIAUCSL', 'yoy_pct', '%')])
    monkeypatch.setattr(cmd, 'fred_series', lambda sid: monthly('2019-01', '2026-10', skip=('2025-10',)))
    monkeypatch.setattr(cmd, 'fred_blanks', lambda sid: blanks)
    monkeypatch.setattr(cmd, 'fred_unclear', lambda sid: unclear)
    monkeypatch.setattr(cmd.time, 'sleep', lambda s: None)
    reasons, refs = {}, {}
    rows, _ = cmd.collect_econ(reasons, refs)
    return cmd.econ_collect(rows, reasons, D, refs)['missing_ref']['no_value:CPI YoY']['lacking_why']


def test_h1_unclear_row_is_unknown_not_not_published(monkeypatch):
    assert _states(monkeypatch, ['2025-10-01'], []) == {'2025-10': 'not_published'}
    assert _states(monkeypatch, [], ['2025-10-01']) == {'2025-10': 'unknown'}            # 재현: 전에는 not_published
    assert _states(monkeypatch, ['2025-10-01'], ['2025-10-01']) == {'2025-10': 'unknown'}  # 둘 다면 모른다
    assert _states(monkeypatch, [], None) == {'2025-10': 'unknown'}                      # 형식 정보 자체가 없다
    assert _states(monkeypatch, [], []) == {'2025-10': 'not_collected'}


def test_h1_wrapper_reads_the_client(monkeypatch):
    c = api_client([OK[0], {'date': '2025-10-01'}, OK[1]])
    c.series('CPIAUCSL')
    monkeypatch.setattr(cmd, 'fred_client', lambda: c)
    assert cmd.fred_blanks('CPIAUCSL') == [] and cmd.fred_unclear('CPIAUCSL') == ['2025-10-01']
    assert cmd.fred_blanks('NOPE') is None and cmd.fred_unclear('NOPE') is None
