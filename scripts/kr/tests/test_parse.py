"""못 읽은 값은 0 이 아니라 결측이다 — 네이버 숫자 한 개를 읽는 함수(2026-11-12).

spec: docs/superpowers/specs/2026-11-12-kr-missing-vs-zero.md
"""
import math

import pytest

from kr.parse import num_or_none


@pytest.mark.parametrize("raw,want", [
    ("0", 0.0), ("0.00", 0.0), ("+6,729", 6729.0), ("-7,145", -7145.0),
    ("5,342.73", 5342.73), ("-0.61", -0.61), (3, 3.0), (1.5, 1.5),
])
def test_numbers_are_read(raw, want):
    assert num_or_none(raw) == want


def test_int_kind():
    assert num_or_none("+6,729", "int") == 6729
    assert isinstance(num_or_none("+6,729", "int"), int)
    assert num_or_none("0", "int") == 0
    assert num_or_none("1.5", "int") is None          # 정수 칸에 소수 — 못 읽은 값


@pytest.mark.parametrize("raw", [
    None, "", "-", " ", "abc", "nan", "NaN", "inf", "-Infinity", "Infinity",
    float("nan"), float("inf"), True, False, [], {},
])
def test_unreadable_is_none(raw):
    assert num_or_none(raw) is None
    assert num_or_none(raw, "int") is None


def test_result_is_always_finite():
    for raw in ("1e400", "-1e400"):
        v = num_or_none(raw)
        assert v is None or math.isfinite(v)
