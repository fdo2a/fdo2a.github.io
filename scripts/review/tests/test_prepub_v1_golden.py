"""1판 기록(`prepub-record/1`) 12건의 알림 문구는 기록 형식 2판 도입 뒤에도 글자 그대로 같아야 한다(2026-11-17).

정답은 바꾸기 전 코드로 만들었다(`fixtures/prepub_v1_golden.json`, 기준 커밋 26cb41a5). 기준 커밋을 못 읽으면
건너뛰지 않고 실패한다 — 얕은 클론에서 돌리면 이 시험이 회귀를 증명하지 못한다.
"""
import json
import os

import pytest

from review import prepub_view as V

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
GOLDEN = json.load(open(os.path.join(HERE, 'fixtures', 'prepub_v1_golden.json'), encoding='utf-8'))


@pytest.mark.parametrize('key', sorted(GOLDEN['cases']))
def test_v1_alert_text_is_unchanged(key):
    m, d = key.split('/')
    v = V.view(ROOT, GOLDEN['ref'], m, d)
    want = GOLDEN['cases'][key]
    assert V.render_publish(v, who=V.GITHUB) == want['github']
    assert V.render_publish(v) == want['mac']
    assert V.digest_lines(v) == want['digest']
    assert V.anomaly_labels(v) == want['anomalies']
    assert V.fully_verified(v) == want['fully_verified']
    assert V.fingerprint(v) == want['fingerprint']
    assert V.clean(v) == want['clean']
