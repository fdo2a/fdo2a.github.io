"""수집기 — 못 읽은 값은 결측, 검증 못 한 지수는 발행 멈춤, 재수집은 있던 값을 지우지 않는다(2026-11-12).

네트워크 없이 `collect_kr_data.main` 을 통째로 돌린다. 가짜가 없는 요청은 기록해 두고 시험 끝에 0건인지 본다
(main 은 거의 모든 단계를 except 로 감싸 「요청하면 예외」 만으로는 새는 요청을 못 잡는다).
spec: docs/superpowers/specs/2026-11-12-kr-missing-vs-zero.md
"""
import json
import os

import pandas as pd
import pytest

import collect_kr_data
from kr import charts, sectors, sources
from kr import econ as kr_econ

D0 = "2026-11-11"
D = "2026-11-12"
D1 = "2026-11-13"
WEEK = "2026-W46"

BASIC = {"KOSPI": (5342.73, -0.61, -32.63), "KOSDAQ": (700.00, 0.50, 3.48)}
INTEG = {"KOSPI": (5375.36, 5458.84, 5293.05), "KOSDAQ": (696.52, 705.0, 690.0)}
BASIC_D1 = {"KOSPI": (5352.73, 0.19, 10.0), "KOSDAQ": (705.00, 0.71, 5.0)}
INTEG_D1 = {"KOSPI": (5342.73, 5360.0, 5330.0), "KOSDAQ": (700.0, 710.0, 699.0)}
F_OK = {"individual": -2347, "foreign": 3812, "institution": -6704}


class World:
    """한 번의 수집이 볼 원천 — 시험마다 바꾼다."""

    def __init__(self, date=D):
        self.date = date
        basic, integ = (BASIC, INTEG) if date == D else (BASIC_D1, INTEG_D1)
        self.basic = {k: dict(close=v[0], change_pct=v[1], prev_diff=v[2]) for k, v in basic.items()}
        self.integ = {k: dict(prevClose=v[0], high=v[1], low=v[2]) for k, v in integ.items()}
        self.flows = {"KOSPI": "ok", "KOSDAQ": "ok"}
        self.top = [{"name": f"종목{i:02d}", "code": f"{i:06d}", "cap": 10 ** 12, "value": 5000 - i,
                     "volume": 100 + i, "change_pct": 1.0} for i in range(15)]
        self.top_stats = {"rows": 15, "dash": 0, "bad": 0, "dash_top100": 0}
        self.top_error = None
        self.industry = [{"name": "반도체", "change_pct": 1.2, "total": 10, "rise": 8, "breadth": 0.8, "no": 1},
                         {"name": "은행", "change_pct": -0.4, "total": 10, "rise": 2, "breadth": 0.2, "no": 2}]


def _compact(d):
    return d.replace("-", "")


def install(monkeypatch, tmp_path, world_ref, leaks):
    """world_ref[0] 을 바꿔 가며 같은 outdir 에서 여러 번 돌린다."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)

    def leak(*a, **k):
        leaks.append(a[:1])
        raise RuntimeError("시험 밖 요청")
    monkeypatch.setattr(sources, "fetch_json", leak)
    import requests
    monkeypatch.setattr(requests, "get", leak)

    def fetch_index(code):
        w = world_ref[0]
        b = w.basic.get(code)
        if b is None:
            raise RuntimeError("지수 종가가 비었다")
        return {**b, "trade_date": w.date}

    def fetch_index_ohlc(code):
        w = world_ref[0]
        g = w.integ.get(code)
        if g is None:
            raise RuntimeError("integration 실패")
        return {"open": None, **g, "flow_bizdate": _compact(w.date)}

    def walk(code, bizdate, days=10, max_back=25):
        w = world_ref[0]
        mode = w.flows[code]
        prev = D0 if w.date == D else D
        if mode == "error":
            raise sources.FlowsFetchError("수급 요청 실패 — HTTP 502", diagnostics=[])
        if mode == "blocked":
            return {"rows": [], "diagnostics": [{"date": w.date, "status": "partial", "fields": ["foreign"]}],
                    "blocked": "unreadable_before_latest"}
        rows = [{"date": w.date, **F_OK}, {"date": prev, **F_OK}]
        if w.date == D1:
            rows.append({"date": D0, **F_OK})
        return {"rows": rows, "diagnostics": [], "blocked": None}

    def top_stats(sosok="0", pages=60):
        w = world_ref[0]
        if w.top_error:
            raise RuntimeError(w.top_error)
        return [dict(r) for r in w.top], dict(w.top_stats)

    monkeypatch.setattr(sources, "fetch_index", fetch_index)
    monkeypatch.setattr(sources, "fetch_index_ohlc", fetch_index_ohlc)
    monkeypatch.setattr(sources, "walk_market_flows", walk)
    monkeypatch.setattr(sources, "fetch_top_value_stats", top_stats)
    monkeypatch.setattr(sources, "fetch_industry", lambda: [dict(r) for r in world_ref[0].industry])
    monkeypatch.setattr(sources, "fetch_industry_names", lambda: {})
    monkeypatch.setattr(sources, "fetch_stock_industry", lambda code: None)
    monkeypatch.setattr(sources, "fetch_intraday", lambda code: [{"t": "15:30", "close": 1.0}])
    monkeypatch.setattr(collect_kr_data, "_yf_last_date", lambda: None)
    # 커밋된 설정 값과 무관하게 — 사람이 block 으로 바꾼 날에도 수집 전 시험이 빨개지지 않게(고정은 test_index_check 하나)
    from kr import index_check
    monkeypatch.setattr(index_check, "load_mode", lambda path=None: ("warn", "ok"))
    monkeypatch.setattr(kr_econ, "collect", lambda: {})

    def no_chart(*a, **k):
        raise RuntimeError("시험에서는 그리지 않는다")
    monkeypatch.setattr(charts, "render_daily_charts", no_chart)
    monkeypatch.setattr(charts, "render_intraday_flow_chart", no_chart)

    idx = pd.date_range("2025-01-01", periods=300, freq="D")
    sector_close = pd.DataFrame({tk: [100.0 + i for i in range(300)] for tk in sectors.SECTOR_ETFS.values()},
                                index=idx)

    class FakeYF:
        @staticmethod
        def download(tickers, *a, **k):
            if isinstance(tickers, list):
                return {"Close": sector_close}
            raise RuntimeError("yfinance 단일 종목 — 시험에서는 없음")

        @staticmethod
        def Ticker(t):
            raise RuntimeError("yfinance Ticker — 시험에서는 없음")
    monkeypatch.setattr(collect_kr_data, "yf", FakeYF)


@pytest.fixture
def env(tmp_path, monkeypatch):
    ref = [World()]
    leaks = []
    install(monkeypatch, tmp_path, ref, leaks)
    outdir = tmp_path / "kr" / "data"

    def run(world=None):
        if world is not None:
            ref[0] = world
        collect_kr_data.main(str(outdir), str(tmp_path / "kr" / "assets"))
        return read("kr_market_data.json")

    def read(name):
        with open(outdir / name, encoding="utf-8") as f:
            return json.load(f)

    def ledger():
        p = outdir / "history" / "kr_market.jsonl"
        return {r["report_date"]: r["indices"] for r in map(json.loads, p.read_text().splitlines()) if r}

    def weekly(key=WEEK):
        return read(os.path.join("weekly", f"{key}.json"))

    yield {"run": run, "read": read, "ledger": ledger, "weekly": weekly, "outdir": outdir}
    assert leaks == [], f"가짜 없는 요청: {leaks}"


# ── 정상 ────────────────────────────────────────────────────────────────

def test_normal_run_is_complete_with_todays_tokens(env):
    m = env["run"]()
    assert m["complete"] is True
    assert m["missing"] == ["flows_intraday"]                       # 지금과 같은 토큰
    assert m["indices"]["KOSPI"] == {"close": 5342.73, "change_pct": -0.61}
    ck = m["checks"]
    assert ck["index_pct"]["mode"] == "warn" and ck["index_pct"]["config_status"] == "ok"
    assert ck["index_pct"]["KOSPI"]["status"] == "ok"
    assert ck["index_pct"]["KOSDAQ"]["status"] == "ok"
    assert ck["flows"]["KOSPI"] == {"state": "ok", "faults": []}
    assert ck["top_value"]["positive_rows"] == 10 and ck["top_value"]["dash"] == 0
    intraday = env["read"]("kr_intraday.json")
    assert "flow_bizdate" not in intraday["KOSPI_ohlc"]
    assert intraday["KOSPI_ohlc"]["prevClose"] == 5375.36
    assert env["read"]("kr_flows.json")["KOSPI"]["diagnostics"] == []


def test_ledger_state_does_not_change_the_index_verdict(env, tmp_path):
    a = env["run"]()["checks"]["index_pct"]
    hist = env["outdir"] / "history" / "kr_market.jsonl"
    hist.write_text("")                                            # 원장이 비어도
    b = env["run"]()["checks"]["index_pct"]
    hist.write_text(json.dumps({"report_date": "2026-11-01", "indices": {"KOSPI": 1.0, "KOSDAQ": 1.0}}) + "\n")
    c = env["run"]()["checks"]["index_pct"]                        # 전일 행이 빠지고 엉뚱한 행만 있어도
    assert a == b == c


# ── 지수 ────────────────────────────────────────────────────────────────

def test_kosdaq_fetch_failure_blocks_and_keeps_kospi_close_in_ledger(env):
    w = World()
    w.basic.pop("KOSDAQ")
    m = env["run"](w)
    assert m["complete"] is False and "indices" in m["missing"]
    assert m["checks"]["index_pct"]["KOSDAQ"] == {"status": "fetch_error"}
    assert env["ledger"]()[D] == {"KOSPI": 5342.73}


def test_ratio_missing_blocks_but_close_reaches_ledger(env):
    w = World()
    w.basic["KOSDAQ"]["change_pct"] = None
    m = env["run"](w)
    assert m["complete"] is False and "indices" in m["missing"]
    assert m["indices"]["KOSDAQ"] == {"close": 700.0, "change_pct": None}       # 계산값으로 바꾸지 않는다
    assert m["checks"]["index_pct"]["KOSDAQ"]["status"] == "ratio_missing"
    assert env["ledger"]()[D]["KOSDAQ"] == 700.0


def test_fake_zero_blocks(env):
    w = World()
    w.basic["KOSDAQ"].update(change_pct=0.0, prev_diff=0.0)       # 실제로는 +0.50%
    m = env["run"](w)
    assert m["complete"] is False and "indices" in m["missing"]
    assert m["checks"]["index_pct"]["KOSDAQ"]["status"] == "flat_contradicted"
    assert m["indices"]["KOSDAQ"]["change_pct"] == 0.0


def test_mismatch_in_warn_mode_keeps_complete(env, capsys):
    w = World()
    w.basic["KOSDAQ"]["change_pct"] = 0.80                         # 같은 응답의 C·D 로는 +0.50%
    m = env["run"](w)
    assert m["complete"] is True
    assert m["checks"]["index_pct"]["KOSDAQ"]["status"] == "mismatch"
    assert "::warning::" in capsys.readouterr().out


def test_mismatch_in_block_mode_blocks(env, monkeypatch):
    from kr import index_check
    monkeypatch.setattr(index_check, "load_mode", lambda path=None: ("block", "ok"))
    w = World()
    w.basic["KOSDAQ"]["change_pct"] = 0.80
    m = env["run"](w)
    assert m["complete"] is False and "indices" in m["missing"]


def test_integration_failure_on_a_flat_day_blocks_not_fills(env):
    w = World()
    w.basic["KOSDAQ"].update(close=696.52, change_pct=0.0, prev_diff=0.0)
    w.integ.pop("KOSDAQ")
    m = env["run"](w)
    assert m["checks"]["index_pct"]["KOSDAQ"]["status"] == "flat_unverified"
    assert m["complete"] is False


# ── 수급 ────────────────────────────────────────────────────────────────

def test_one_market_flows_blocked_blocks_publish(env):
    w = World()
    w.flows["KOSDAQ"] = "blocked"
    m = env["run"](w)
    assert m["complete"] is False and "flows" in m["missing"]
    f = env["read"]("kr_flows.json")["KOSDAQ"]
    assert f["blocked"] is True and f["rows"] == [] and f["latest_date"] is None
    assert f["error"] == "unreadable_before_latest"
    assert f["diagnostics"][0]["fields"] == ["foreign"]
    assert m["checks"]["flows"]["KOSDAQ"]["state"] == "blocked"
    assert m["checks"]["flows"]["KOSDAQ"]["faults"] == [{"date": D, "status": "partial", "fields": ["foreign"]}]
    assert m["checks"]["flows"]["KOSPI"]["state"] == "ok"


def test_flows_request_error_is_recorded(env):
    w = World()
    w.flows["KOSPI"] = "error"
    m = env["run"](w)
    assert "flows" in m["missing"]
    assert m["checks"]["flows"]["KOSPI"]["state"] == "error"
    assert env["read"]("kr_flows.json")["KOSPI"]["diagnostics"] == []


# ── 거래대금 ─────────────────────────────────────────────────────────────

def test_top_value_with_nine_positive_rows_is_missing(env):
    w = World()
    w.top = w.top[:9] + [dict(w.top[9], value=0)]
    m = env["run"](w)
    assert m["complete"] is False and "top_value" in m["missing"]
    assert env["read"]("kr_top_value.json") == []
    assert m["checks"]["top_value"]["positive_rows"] == 9


def test_top_value_failure_is_recorded(env):
    w = World()
    w.top_error = "거래대금 시총 상위 100행 중 빈 값 6건"
    m = env["run"](w)
    assert "top_value" in m["missing"]
    assert "error" in m["checks"]["top_value"]


def test_high_dash_ratio_warns_without_blocking(env, capsys):
    w = World()
    w.top_stats = {"rows": 100, "dash": 16, "bad": 0, "dash_top100": 0}
    m = env["run"](w)
    assert m["complete"] is True
    assert "::warning::" in capsys.readouterr().out


# ── 연속 실행 ────────────────────────────────────────────────────────────

def test_second_run_kosdaq_fails_ledger_keeps_kosdaq(env):
    assert env["run"]()["complete"] is True
    w = World()
    w.basic.pop("KOSDAQ")
    m = env["run"](w)
    assert m["complete"] is False
    assert env["ledger"]()[D] == {"KOSPI": 5342.73, "KOSDAQ": 700.0}
    wk = env["weekly"]()
    assert f"indices.KOSDAQ.{D}" not in wk["missing"]


def test_second_run_top_value_failure_keeps_session_snapshot(env):
    env["run"]()
    before = env["weekly"]()
    w = World()
    w.top_error = "거래대금 목록 장애"
    w.industry = []                                               # 업종 수집도 실패
    m = env["run"](w)
    assert m["complete"] is False
    after = env["weekly"]()
    assert after["_sessions"][D]["top_value"] == before["_sessions"][D]["top_value"]
    assert after["_sessions"][D]["industry"] == before["_sessions"][D]["industry"]
    assert after["_sessions"][D]["leading_industries"] == before["_sessions"][D]["leading_industries"]
    assert after["top_value"] == before["top_value"]


def test_second_run_nine_positive_rows_keeps_session_snapshot(env):
    env["run"]()
    before = env["weekly"]()
    w = World()
    w.top = w.top[:9] + [dict(w.top[9], value=0)]
    env["run"](w)
    assert env["weekly"]()["_sessions"][D]["top_value"] == before["_sessions"][D]["top_value"]


def test_same_day_partial_flows_keep_confirmed_values(env):
    # D 를 다음 거래일(D1) 실행이 채운다 → 같은 D1 재실행에서 코스닥이 막혀도 D 의 코스닥 수급은 남는다
    env["run"]()
    env["run"](World(D1))
    assert set(env["weekly"]()["_sessions"][D]["flows"]) == {"KOSPI", "KOSDAQ"}
    w = World(D1)
    w.flows["KOSDAQ"] = "blocked"
    m = env["run"](w)
    assert m["complete"] is False
    s = env["weekly"]()["_sessions"][D]
    assert s["flows"]["KOSDAQ"] == F_OK and s["flows"]["KOSPI"] == F_OK


def test_next_day_self_heals_a_blocked_market(env):
    w = World()
    w.flows["KOSDAQ"] = "blocked"
    env["run"](w)
    assert env["weekly"]()["_sessions"][D]["flows"] == {}
    env["run"](World(D1))
    s = env["weekly"]()["_sessions"][D]
    assert s["flows"]["KOSDAQ"] == F_OK and s["flows"]["KOSPI"] == F_OK
    assert "flows_note" not in s
