"""표본이 짧은 날 렌더러가 깨진 문장을 만들지 않는가.

`plain` 이 30거래일 미만에서 None 을 돌려주게 되면서 생긴 경계다 — 위치를 말할 수
없는 날 그 절을 빼지 않으면 「CCC 이하는 200bp로 , 지수 전체는 라」가 나온다
(2026-09-02 codex 2차 검토에서 재현).
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from build_bond_report import ccc_reading, where  # noqa: E402
from bond.credit import standing  # noqa: E402


def _row(bp, series, value):
    return {'bp': bp, 'standing': standing(series, value)}


def test_short_sample_falls_back_instead_of_leaving_holes():
    hy = _row(300, [280, 290, 300], 300)
    ccc = _row(900, [880, 890, 900], 900)
    out = ccc_reading(hy, ccc)
    assert '표본이 아직 모자랍니다' in out
    assert ' , ' not in out and '는 라' not in out


def test_long_sample_speaks_the_counted_sentence():
    series = list(range(100, 100 + 60))
    hy = _row(300, series, series[-1])
    ccc = _row(900, series, series[0])
    out = ccc_reading(hy, ccc)
    assert '이보다' in out or '쪽' in out
    assert ' , ' not in out


def test_where_is_empty_when_the_sample_is_too_short():
    assert where({'plain': None}) == ''
    assert where(None, short=True, form='soft') == ''
