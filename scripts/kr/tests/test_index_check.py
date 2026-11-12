"""지수 등락률 검증 — 같은 응답 안 비교가 1차, 보합은 integration 으로 확인(2026-11-12).

못 읽었거나 검증하지 못한 날은 발행하지 않는다(사용자 방향 2). 원장은 판정 입력이 아니다(방향 4).
spec: docs/superpowers/specs/2026-11-12-kr-missing-vs-zero.md
"""
import inspect
import json
import os

import pytest

from kr import index_check as IC

RD = "2026-11-12"


def integ(prev, high=None, low=None, biz="20261112"):
    return {"prevClose": prev, "high": high, "low": low, "flow_bizdate": biz}


def chk(C, R, D, ig=None, mode="warn"):
    return IC.check_pct(C, R, D, ig, RD, mode)


def test_signature_has_no_ledger_input():
    assert list(inspect.signature(IC.check_pct).parameters) == ["C", "R", "D", "integ", "report_date", "mode"]


def test_measured_kospi_1112_is_ok():
    r = chk(5342.73, -0.61, -32.63, integ(5375.36, 5458.84, 5293.05))
    assert r["status"] == "ok"
    assert r["prev_source"] == "basic"
    assert r["prev_close"] == pytest.approx(5375.36)
    assert abs(r["derived_pct"] - (-0.61)) <= 0.01
    assert r["matched"] is True and r["cross_note"] is False
    assert not IC.is_blocking(r["status"], "warn")


def test_ratio_missing_blocks():
    r = chk(5342.73, None, -32.63, integ(5375.36))
    assert r["status"] == "ratio_missing"
    assert IC.is_blocking(r["status"], "warn")


def test_tolerance_boundary():
    # C=101, P=100 → 계산 1.00%. 0.010 차이는 통과, 0.011 은 어긋남
    assert chk(101.0, 1.01, 1.0)["status"] == "ok"
    assert chk(101.0, 0.99, 1.0)["status"] == "ok"
    assert chk(101.0, 1.011, 1.0)["status"] == "mismatch"
    assert chk(101.0, 0.989, 1.0)["status"] == "mismatch"


def test_mismatch_blocks_only_in_block_mode():
    r = chk(101.0, 1.5, 1.0)
    assert r["status"] == "mismatch"
    assert not IC.is_blocking("mismatch", "warn")
    assert IC.is_blocking("mismatch", "block")
    assert chk(101.0, 1.5, 1.0, mode="block")["status"] == "mismatch"


def test_d_missing_verifies_with_integration():
    r = chk(101.0, 1.0, None, integ(100.0, 102, 99))
    assert r["status"] == "ok" and r["prev_source"] == "integration"


@pytest.mark.parametrize("ig", [None, integ(None), integ(0.0), integ(-5.0)])
def test_d_missing_and_no_usable_integration_is_unverified(ig):
    r = chk(101.0, 1.0, None, ig)
    assert r["status"] == "unverified"
    assert IC.is_blocking(r["status"], "warn")


def test_nonpositive_basic_prev_falls_back_to_integration():
    # Pb = C − D = 100 − 150 < 0 → Pi 로
    r = chk(100.0, 1.01, 150.0, integ(99.0, 101, 98))
    assert r["prev_source"] == "integration"
    assert r["status"] == "ok"


def test_fake_zero_with_matched_integration_is_contradicted():
    # R=0·D=0 으로 함께 온 실패, 실제 등락 +2.6%
    r = chk(102.60, 0.0, 0.0, integ(100.0, 103.0, 99.5))
    assert r["status"] == "flat_contradicted"
    assert IC.is_blocking(r["status"], "warn")


def test_fake_zero_with_unmatched_integration_is_unverified():
    r = chk(102.60, 0.0, 0.0, integ(100.0, 103.0, 99.5, biz="20261111"))
    assert r["status"] == "flat_unverified"
    assert IC.is_blocking(r["status"], "warn")
    r = chk(102.60, 0.0, 0.0, integ(100.0, 101.0, 99.5))         # 종가가 고저 범위 밖 → 표식 아님
    assert r["status"] == "flat_unverified"


def test_fake_zero_without_integration_is_unverified():
    r = chk(102.60, 0.0, 0.0, None)
    assert r["status"] == "flat_unverified"
    assert IC.is_blocking(r["status"], "block") and IC.is_blocking(r["status"], "warn")


@pytest.mark.parametrize("biz", ["20261112", "20261111", None])
def test_true_flat_with_equal_integration_is_ok_flat(biz):
    r = chk(1000.0, 0.0, 0.0, integ(1000.0, 1005, 995, biz=biz))
    assert r["status"] == "ok_flat"
    assert not IC.is_blocking(r["status"], "warn")


def test_true_flat_with_stale_unmatched_integration_is_unverified_not_contradicted():
    # 2회차 #1 재현 — integration 이 다른 세션 값이면 contradicted 로 부르지 않는다
    r = chk(1000.0, 0.0, 0.0, integ(999.0, 1005, 995, biz="20261111"))
    assert r["status"] == "flat_unverified"


def test_cross_note_is_recorded_but_does_not_change_status():
    r = chk(5342.73, -0.61, -32.63, integ(5375.50, 5458.84, 5293.05))
    assert r["status"] == "ok"
    assert r["cross_note"] is True


def test_cross_note_needs_matched():
    r = chk(5342.73, -0.61, -32.63, integ(5375.50, 5458.84, 5293.05, biz="20261111"))
    assert r["cross_note"] is False


def test_non_finite_derived_is_not_used():
    # Pb 가 아주 작아 계산이 넘쳐도 판정표를 우회하지 않는다
    r = chk(1e308, 1.0, 1e308 - 1e-300, None)
    assert r["status"] in IC.BLOCKING or r["status"] == "mismatch"


def test_record_fields():
    r = chk(5342.73, -0.61, -32.63, integ(5375.36, 5458.84, 5293.05))
    assert set(r) == {"status", "naver_pct", "derived_pct", "prev_close", "prev_source",
                      "integ_prev", "matched", "cross_note"}
    assert r["naver_pct"] == -0.61 and r["integ_prev"] == 5375.36


# ── 설정 ────────────────────────────────────────────────────────────────

def _cfg(tmp_path, body):
    p = tmp_path / "kr_index_check.json"
    p.write_text(body if isinstance(body, str) else json.dumps(body), encoding="utf-8")
    return str(p)


@pytest.mark.parametrize("val", ["warn", "block"])
def test_config_ok(tmp_path, val):
    assert IC.load_mode(_cfg(tmp_path, {"format": "kr-index-check/1", "mismatch": val})) == (val, "ok")


def test_config_missing_defaults_to_warn(tmp_path, capsys):
    assert IC.load_mode(str(tmp_path / "nope.json")) == ("warn", "missing_default")
    assert "::warning::" in capsys.readouterr().out


@pytest.mark.parametrize("body", [
    "{broken", [], {"format": "kr-index-check/1"}, {"format": "kr-index-check/1", "mismatch": "blok"},
    {"format": "kr-index-check/2", "mismatch": "warn"}, {"mismatch": "warn"}, "null",
])
def test_config_invalid_reads_as_block(tmp_path, capsys, body):
    assert IC.load_mode(_cfg(tmp_path, body)) == ("block", "invalid_block")
    assert "::warning::" in capsys.readouterr().out


def test_committed_config_is_warn():
    assert IC.load_mode(IC.CONFIG) == ("warn", "ok")
    assert os.path.basename(os.path.dirname(IC.CONFIG)) == "config"
