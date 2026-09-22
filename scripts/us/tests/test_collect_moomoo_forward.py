"""수집기의 **실패 분류**. 통과가 아니라 실패를 제대로 갈라내는지 본다.

2026-09-22 codex 구현 검토 P2-8·9·10·11 이 전부 여기로 들어온다.
"""

import importlib.util
import os

import pytest

_SPEC = importlib.util.spec_from_file_location(
    'collect_moomoo_forward',
    os.path.join(os.path.dirname(__file__), '..', '..', 'collect_moomoo_forward.py'))
C = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(C)


# --- 스키마 오류를 정상 0건으로 바꾸지 않는다 (P2-8) --------------------------

def test_an_unknown_payload_is_a_schema_error_not_an_empty_day():
    with pytest.raises(C.SchemaError):
        C._records('not rows')


def test_a_list_of_non_dicts_is_a_schema_error():
    with pytest.raises(C.SchemaError):
        C._records([1, 2, 3])


def test_a_schema_error_never_reads_as_empty():
    """query_range 가 있으면 빈 결과는 `empty` 가 된다 — 스키마 오류가 그 길로
    새면 파싱 실패와 「그날 발표가 없었다」가 구별되지 않는다."""
    rng = {'begin': 'x', 'end': 'y'}
    assert C._status_for([], 'schema: unexpected payload: str', rng) == 'invalid'
    assert C._status_for([], None, rng) == 'empty'


def test_none_is_still_an_honest_empty():
    assert C._records(None) == []


# --- 상태 분류 -----------------------------------------------------------------

@pytest.mark.parametrize('err,expected', [
    ('permission denied for US MarketOptions', 'unavailable'),
    ('ret=-1: Maximum 60 times per 30 seconds frequency', 'partial'),
    ('offline', 'unavailable'),
    ('sdk-missing: no module', 'unavailable'),
    ('unexpected-shape: len=1', 'invalid'),
])
def test_error_kinds_do_not_collapse_into_one(err, expected):
    assert C._status_for([], err, {'x': 1}) == expected


def test_a_short_payload_tuple_is_reported_not_crashed():
    """길이 1 튜플은 result[1] 에서 죽던 자리다 — 사유로 돌려준다."""
    assert C._safe_len(()) == 0
    assert C._safe_len(3) == 'n/a'


# --- 휴장 달력 (P2-12) --------------------------------------------------------

def test_missing_holiday_file_is_not_an_error(tmp_path):
    assert C._load_holidays(str(tmp_path)) == ()


def test_holidays_can_be_a_bare_list_or_a_dict(tmp_path):
    (tmp_path / 'us_market_holidays.json').write_text('["2026-09-07"]')
    assert C._load_holidays(str(tmp_path)) == ('2026-09-07',)
    (tmp_path / 'us_market_holidays.json').write_text(
        '{"holidays": ["2026-11-26"]}')
    assert C._load_holidays(str(tmp_path)) == ('2026-11-26',)


def test_a_broken_holiday_file_does_not_stop_collection(tmp_path, capsys):
    (tmp_path / 'us_market_holidays.json').write_text('{ not json')
    assert C._load_holidays(str(tmp_path)) == ()
