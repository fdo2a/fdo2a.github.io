"""수집기와 FRED 클라이언트의 접합부.

클라이언트 단위 검사(test_fred.py)가 다 통과해도 접합부는 따로 틀릴 수 있다 —
키를 너무 일찍 읽거나, 텔레메트리를 마지막 호출 전에 굳히거나, 진단 플래그가
정상 경로에 얹혀 산출물을 쓰거나. 여기 검사는 그 네 가지를 본다.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import collect_market_data as cmd  # noqa: E402
from scripts.us import fred  # noqa: E402


class Stub:
    def __init__(self):
        self.calls = []
        self.transport = 'api'
        self.reason = None

    def series(self, sid):
        self.calls.append(sid)
        return [('2026-09-01', 1.0)]

    def telemetry(self):
        return {'transport': 'api', 'requests': len(self.calls)}


@pytest.fixture(autouse=True)
def _reset():
    yield
    cmd.set_fred_client(None)


def test_fred_series_delegates_to_the_injected_client():
    stub = cmd.set_fred_client(Stub())
    assert cmd.fred_series('DGS10') == [('2026-09-01', 1.0)]
    assert stub.calls == ['DGS10']


def test_the_client_is_built_lazily_so_the_key_is_read_at_run_time(monkeypatch):
    """모듈 import 시점에 키를 읽으면 워크플로가 env 를 스텝에 주는 방식과 어긋난다."""
    cmd.set_fred_client(None)
    monkeypatch.setenv('FRED_API_KEY', 'LATEKEY')
    assert cmd.fred_client().key == 'LATEKEY'


def test_reset_clears_a_degraded_client_between_runs():
    stub = cmd.set_fred_client(Stub())
    assert cmd.fred_client() is stub
    cmd.set_fred_client(None)
    assert cmd.fred_client() is not stub


def test_production_sids_cover_yields_dashboard_and_yield_drivers():
    sids = cmd.production_sids()
    assert len(sids) == len(set(sids))          # 중복 없음
    for must in ('DGS2', 'DGS30', 'CPIAUCSL', 'UNRATE'):
        assert must in sids
    from scripts.us.yield_drivers import ROWS
    for row in ROWS:
        assert row[1] in sids


def test_fred_check_refuses_without_a_key_and_writes_nothing(monkeypatch, tmp_path):
    monkeypatch.delenv('FRED_API_KEY', raising=False)
    monkeypatch.chdir(tmp_path)
    assert cmd.fred_check() == 2
    assert list(tmp_path.iterdir()) == []


def test_diff_series_flags_a_shortened_history_not_just_changed_values():
    a = [('2026-09-01', 1.0), ('2026-09-02', 2.0)]
    off, notes = cmd._diff_series(a, a[1:])
    assert off == ['2026-09-01']
    assert any('count' in n for n in notes)


def test_diff_series_is_quiet_when_the_maps_match():
    a = [('2026-09-01', 1.0), ('2026-09-02', 2.0)]
    assert cmd._diff_series(a, list(a)) == ([], [])


def test_diff_series_spots_duplicate_dates():
    dupe = [('2026-09-01', 1.0), ('2026-09-01', 1.0)]
    _, notes = cmd._diff_series(dupe, [('2026-09-01', 1.0)])
    assert any('duplicate' in n for n in notes)


def test_the_csv_path_is_byte_for_byte_the_old_implementation():
    """무키 경로는 무동작이어야 한다 — 예전 `fred_series` 의 파싱과 같은 줄을 낸다."""
    body = ('observation_date,DGS10\n'
            '2026-08-31,4.75\n2026-09-01,.\n2026-09-02,4.79\n').encode()
    c = fred.FredClient(key=None, opener=lambda u, t: body, min_interval=0)
    assert c.series('DGS10') == [('2026-08-31', 4.75), ('2026-09-02', 4.79)]
