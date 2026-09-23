"""수집기가 매일 만들어야 하는 파생 산출물이 main() 에 배선돼 있는가.

2026-09-22 병합 커밋(c7f6540)이 stance 블록을 지우면서 바로 아래의 매크로 지표·
가격 맥락·세션 맥락 블록까지 함께 지웠다. 셋 다 try/except 로 감싼 비-코어라
수집은 성공으로 끝났고, 모듈 단위 테스트 2,137개도 전부 통과했다 — 계산 함수는
멀쩡한데 부르는 곳이 없었기 때문이다. 그날 market_data.json 에서 `price_context`·
`session` 이 빠지고 macro_metrics.json 은 전날 날짜로 굳었다.

그래서 여기서는 함수가 아니라 **배선**을 본다.
"""
import inspect
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import collect_market_data as cmd  # noqa: E402

SRC = inspect.getsource(cmd.main)


def test_macro_metrics_are_computed_and_written():
    assert 'compute_macro_metrics(econ_series, econ, last_seen)' in SRC
    assert "'macro_metrics.json'" in SRC


def test_price_context_is_attached_to_market_data():
    assert "data['price_context'] = " in SRC


def test_session_context_is_attached_to_market_data():
    assert "data['session'] = " in SRC


def test_derived_blocks_run_before_market_data_is_written():
    # md_path 를 쓴 뒤에 붙이면 파일에는 안 들어간다.
    written = SRC.index('json.dump(data, open(md_path')
    for marker in ("data['price_context'] = ", "data['session'] = "):
        assert SRC.index(marker) < written
