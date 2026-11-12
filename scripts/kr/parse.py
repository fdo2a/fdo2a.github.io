"""네이버 숫자 한 개 읽기 — 못 읽은 값은 0 이 아니라 결측(None)이다(2026-11-12).

수집기가 네이버에서 읽는 수는 이 함수를 거친다. 예전 `_to_int`·`_to_float` 는 실패를 0 으로
채워 「등락률 0.00%」「외국인 순매수 0」「거래대금 0」이 진짜 값처럼 흘렀다.
spec: docs/superpowers/specs/2026-11-12-kr-missing-vs-zero.md
"""
import math


def num_or_none(s, kind="float"):
    """쉼표·`+` 를 걷어 수로. None·빈 문자열·`-`·변환 불가·비유한 수(NaN·±Infinity)·bool → None.

    `"0"`·`"0.00"` 은 관측된 0 이다(결측이 아니다). kind="int" 는 정수만 받는다(`"1.5"` → None).
    """
    if s is None or isinstance(s, bool):
        return None
    if isinstance(s, (int, float)):
        v = float(s)
    elif isinstance(s, str):
        t = s.strip().replace(",", "")
        if t.startswith("+"):
            t = t[1:]
        if t in ("", "-"):
            return None
        try:
            v = float(t)
        except ValueError:
            return None
        if kind == "int":
            try:
                iv = int(t)
            except ValueError:
                return None
            return iv
    else:
        return None
    if not math.isfinite(v):
        return None
    if kind == "int":
        return int(v) if v == int(v) else None
    return v
