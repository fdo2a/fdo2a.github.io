"""가격에 반영된 기대 — 금리 스프레드와 그 스프레드가 제 이력에서 선 자리.

KR 에는 미국의 FedWatch·컨센서스 같은 「시장이 무엇을 예상하나」 자료가 없다. 대신
**금리가 이미 값을 매겨 둔 것**을 읽는다. 세 스프레드가 서로 다른 기대를 담는다.

  정책  국고채 3년 − 기준금리      정책 경로와 기간프리미엄
  성장  국고채 10년 − 국고채 3년   성장·물가 기대의 기울기
  신용  회사채 AA- 3년 − 국고채 3년 위험 가격

수치 하나로는 아무 말도 못 한다 — 105.6bp 가 넓은 건지 좁은 건지는 제 이력을 봐야
안다. 그래서 각 스프레드를 2년 표본 안에 세우고 `common.standing` 이 그것을 셀 수
있는 말로 옮긴다(「이보다 넓었던 날이 나흘뿐」). US 가격 섹션이 쓰는 그 장치다.

Pure — ECOS 이력 dict 를 받아 dict 를 돌려준다. 네트워크는 econ.py 가 맡는다.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import standing  # noqa: E402

# (키, 표시명, 빼는 쪽, 빼이는 쪽, 한 줄 설명)
SPREADS = [
    ("policy", "정책 기대", "국고채 3년", "한국은행 기준금리",
     "3년물이 기준금리보다 얼마나 위인가 — 정책 경로와 기간프리미엄이 섞여 있다"),
    ("growth", "성장 기대", "국고채 10년", "국고채 3년",
     "커브 기울기 — 장기 성장·물가 기대가 단기 정책 기대를 얼마나 웃도나"),
    ("credit", "신용 가격", "회사채 AA- 3년", "국고채 3년",
     "같은 만기에서 신용 위험에 매겨진 값"),
]
# 이보다 짧으면 「어디에 서 있다」를 말하지 않는다. standing 의 하한과 같다.
MIN_SESSIONS = standing.MIN_SESSIONS


def step_lookup(series: list, date: str):
    """월별 계열에서 그 날짜에 유효한 값. 기준금리처럼 계단으로 움직이는 계열용.

    ECOS 월 계열의 TIME 은 `2026-09` 꼴이라 일별 날짜와 직접 비교가 안 된다.
    날짜 이하의 마지막 관측을 쓴다 — 없으면 None.
    """
    out = None
    for d, v in series:
        if d <= date[:len(d)]:
            out = v
        else:
            break
    return out


def spread_series(numer: list, denom: list) -> list:
    """두 계열의 차이를 bp 로. 날짜는 분자(일별) 기준이고 분모는 계단 조회한다.

    계열은 [(날짜, 값)] 오름차순, 값 단위는 연%. 분모가 없는 날은 버린다.
    """
    out = []
    for d, v in numer:
        base = step_lookup(denom, d)
        if base is None:
            continue
        out.append((d, round((v - base) * 100, 2)))
    return out


def standing_of(series: list) -> dict:
    """스프레드 계열의 마지막 값과 그 값이 표본에서 선 자리.

    표본이 짧으면 `standing` 이 None 을 주고, 그때는 위치를 말하지 않는다 —
    자리가 비는 것이지 실패가 아니다.
    """
    if not series:
        return {}
    date, value = series[-1]
    prev = series[-2][1] if len(series) >= 2 else None
    vals = [v for _, v in series]
    n = len(vals)
    above = sum(1 for v in vals if v > value)
    below = sum(1 for v in vals if v < value)
    out = {"bp": value, "date": date, "sessions": n,
           "change_bp": round(value - prev, 2) if prev is not None else None,
           "prev_date": series[-2][0] if len(series) >= 2 else None}
    if n >= MIN_SESSIONS:
        pct = below / n * 100.0
        out["standing"] = standing.plain(pct, n, kind="spread",
                                         above=above, below=below)
    return out


def build(history: dict) -> dict:
    """{표시명: [(날짜, 연%)]} → 스프레드 셋. 재료가 없는 것은 자리를 비운다."""
    out = {}
    for key, label, numer, denom, note in SPREADS:
        a, b = history.get(numer), history.get(denom)
        if not a or not b:
            continue
        row = standing_of(spread_series(a, b))
        if not row:
            continue
        out[key] = {"label": label, "numerator": numer, "denominator": denom,
                    "note": note, **row}
    return out
