"""econ_indicators.json 의 collect — 필수 지표의 계산 불가는 결측이다(2026-11-17, 1a 구현 검토 1회차 #5).

「아직 미발표」는 결측 사유가 되지 않는다: 새 달이 발표되기 전에는 원천의 마지막 달이 그 전 달이고, 그 달로
Actual/Previous 를 만든다(`ref_period` 가 한 달 이르다 — 결측이 아니다). `no_value` 는 원천에 있는 최신 달을
변환할 재료(비교 달)가 원천에 없다는 뜻이다 — 예: 2025-10 CPI 미발표로 2026-10 CPI YoY 를 만들 수 없다.
필수 = 축 점수에 들어가는 지표(`role` 이 `anatomy` 가 아닌 것, `us.macro_metrics` 의 scored). 해부 전용 지표의
계산 불가는 detail 에만 남긴다.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import collect_market_data as cmd  # noqa: E402

RD = '2026-11-16'
ANATOMY = next(e[1] for e in cmd.ECON if len(e) > 5 and e[5].get('role') == 'anatomy')


def test_scored_indicator_without_inputs_is_missing():
    rows = [{'name': 'x'}]
    c = cmd.econ_collect(rows, {'CPI YoY': 'no_value', 'Core CPI YoY': 'no_value'}, RD)
    # 재현: 전에는 status ok·missing [] — 정책의 indicators 비어 있지 않음 조건도 통과했다
    assert c['status'] == 'partial' and c['required_ok'] is False
    assert c['missing'] == ['no_value:CPI YoY', 'no_value:Core CPI YoY']


def test_anatomy_only_indicator_is_detail():
    c = cmd.econ_collect([{'name': 'x'}], {ANATOMY: 'no_value'}, RD)
    assert c['status'] == 'ok' and c['missing'] == [] and ANATOMY in c['detail']


def test_fetch_failure_and_transform_error_stay_missing():
    c = cmd.econ_collect([{'name': 'x'}], {'JOLTS Job Openings': 'fetch_failed', 'CPI MoM': 'transform_error'}, RD)
    assert c['status'] == 'partial' and c['missing'] == ['CPI MoM', 'JOLTS Job Openings']


def test_policy_reads_the_stamp_not_only_a_nonempty_list():
    """정책의 `indicators` 조건은 목록이 비지 않았는지만 본다 — 필수 지표의 결측은 collect 칸(required_ok·missing)이
    막는다. 적용일 전(표시 없음)에는 막지 못한다 — 그 구멍을 닫는 것이 적용일이다."""
    import json
    from verification import inputs as I
    pol = I.load(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'config', 'prepub_inputs.json'))
    files, _ = I.entries(pol, 'us')
    e = next(x for x in files if x['path'] == '<datadir>/econ_indicators.json')
    assert e['require'] == ['indicators'] and 'scored' in e.get('why', '')
