"""수집기 배선 — 날짜가 틀린 실행은 아무것도 쓰기 전에 멈춘다.

2026-10-13 02:27 KST: Actions 지연으로 늦게 돈 10/12 예약 실행에서 yfinance ^KS11 은
10/08 이 마지막 행, 네이버는 10/12 종가 → 원장·주간·월간·뉴스의 10/08 이 10/12 값으로 덮였다.
"""
import json
import os

import pytest

import collect_kr_data
from kr import sources
from kr.history import StaleIndexData

LEDGER = [{"report_date": "2026-10-07", "indices": {"KOSPI": 6803.9, "KOSDAQ": 898.43}},
          {"report_date": "2026-10-08", "indices": {"KOSPI": 6625.93, "KOSDAQ": 892.27}},
          {"report_date": "2026-10-12", "indices": {"KOSPI": 6384.24, "KOSDAQ": 849.19}}]
CLOSE_1012 = {"KOSPI": (6384.24, -3.65), "KOSDAQ": (849.19, -4.83)}


def _setup(tmp_path, monkeypatch, naver_date, yf_date):
    outdir = tmp_path / "data"
    (outdir / "history").mkdir(parents=True)
    ledger = outdir / "history" / "kr_market.jsonl"
    ledger.write_text("".join(json.dumps(r) + "\n" for r in LEDGER))
    monkeypatch.setattr(sources, "fetch_index", lambda code: {
        "close": CLOSE_1012[code][0], "change_pct": CLOSE_1012[code][1],
        "trade_date": naver_date})
    monkeypatch.setattr(collect_kr_data, "_yf_last_date", lambda: yf_date)
    return outdir, ledger


def _files(root):
    return sorted(os.path.relpath(os.path.join(d, f), root)
                  for d, _, fs in os.walk(root) for f in fs)


def test_a_relabelled_run_writes_nothing(tmp_path, monkeypatch):
    # 네이버 거래일을 못 읽은 채 야후의 옛 날짜로 물러선 경우 — 마지막 방어선
    outdir, ledger = _setup(tmp_path, monkeypatch, None, "2026-10-08")
    before = ledger.read_bytes()
    with pytest.raises(StaleIndexData):
        collect_kr_data.main(str(outdir), str(tmp_path / "assets"))
    assert ledger.read_bytes() == before
    assert _files(tmp_path) == ["data/history/kr_market.jsonl"]


def test_naver_trade_date_wins_over_a_lagging_yahoo(tmp_path, monkeypatch):
    outdir, _ = _setup(tmp_path, monkeypatch, "2026-10-12", "2026-10-08")
    got = {}

    def stop(outdir_, report_date, indices):
        got.update(report_date=report_date, indices=indices)
        raise SystemExit  # 가드 통과 여부만 본다 — 뒤의 네트워크 수집은 돌리지 않는다

    monkeypatch.setattr(collect_kr_data, "guard_session", stop)
    with pytest.raises(SystemExit):
        collect_kr_data.main(str(outdir), str(tmp_path / "assets"))
    assert got["report_date"] == "2026-10-12"
    assert "trade_date" not in got["indices"]["KOSPI"]   # kr_market_data.json 모양 유지


def test_cli_exits_2_on_a_stale_session(tmp_path, monkeypatch):
    outdir, _ = _setup(tmp_path, monkeypatch, None, "2026-10-08")
    monkeypatch.setattr("sys.argv", ["collect_kr_data.py", "--outdir", str(outdir),
                                     "--assetdir", str(tmp_path / "assets")])
    import runpy
    import yfinance

    def offline(*a, **k):
        raise RuntimeError("offline")

    # run_module 은 모듈을 새로 읽어 _yf_last_date 패치가 닿지 않는다 — 원천 쪽을 막는다
    monkeypatch.setattr(yfinance, "download", offline)
    with pytest.raises(SystemExit) as e:
        runpy.run_module("collect_kr_data", run_name="__main__")
    assert e.value.code == 2
