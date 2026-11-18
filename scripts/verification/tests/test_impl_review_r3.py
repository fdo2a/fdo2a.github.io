"""1a 구현 검토 3회차(codex IMPL NO, 2026-11-18) — 검사 쪽.

G1 승인 예외는 식별자·기준월에 더해 **원인**(원천에 없는 비교 달)이 등록과 같아야 한다 — 2025-10 하나. 다른 달이 없거나
여러 달이 없거나 자료가 말하지 않으면 보류. 수집 쪽(G1 의 기록, G2, G5)은 `scripts/us/tests/test_impl_review_r3.py`.
"""
import json
import os
import sys

import pytest

from verification import inputs as I
from verification import record as R
from verification.tests.test_impl_review_r2 import (CPI, D, K1, K2, REAL, SCRIPTS, _chain, _econ, _real_us, acc,
                                                    ident, partial)


def _with_lacking(chain, lacking):
    chain = json.loads(json.dumps(chain))
    for c in chain:
        for r in (c.get('missing_ref') or {}).values():
            if lacking is None:
                r.pop('lacking', None)
            else:
                r['lacking'] = lacking
    return chain


def test_g1_only_the_registered_month_missing_matches(tmp_path, monkeypatch):
    monkeypatch.setattr(I, 'EFFECTIVE', None)
    h, s = _real_us(tmp_path, _chain(CPI))                                       # lacking ['2025-10']
    assert s['publish_ok'] and s['status'] == 'conditional'


@pytest.mark.parametrize('lacking', [[], ['2025-09'], ['2025-10', '2025-09'], ['2025-10', '2025-10'], None, '2025-10',
                                     ['2025-10-01'], [None]])
def test_g1_any_other_cause_blocks_with_the_real_policy(tmp_path, monkeypatch, lacking):
    # codex 재현: 식별자·기준월은 같은데 원인이 「2025-10 미발표」가 아니다 — 전에는 승인된 미발표로 통과
    monkeypatch.setattr(I, 'EFFECTIVE', None)
    h, s = _real_us(tmp_path, _with_lacking(_chain(CPI), lacking))
    assert not s['publish_ok'] and s['status'] == 'incomplete' and len(s['inputs']['blocking']) == 4, lacking
    assert not s['inputs']['accepted_missing']


def test_g1_one_file_with_another_cause_blocks_that_file(tmp_path, monkeypatch):
    monkeypatch.setattr(I, 'EFFECTIVE', None)
    _, f = _econ(tmp_path, partial([K1, K2], refs={K1: ident(K1), K2: ident(K2, lacking=['2025-09'])}),
                 [acc(K1), acc(K2)])
    assert f['blocking'] and 'accepted_missing' not in f
    _, f = _econ(tmp_path, partial([K1, K2]), [acc(K1), acc(K2)])
    assert not f['blocking']


@pytest.mark.parametrize('bad', [None, '', '2025-10-01', ['2025-10'], 202510])
def test_g1_registration_must_name_the_month(bad):
    from verification.tests.test_inputs import policy
    from verification.tests.test_impl_review_r2 import ECON
    with pytest.raises(I.PolicyError):
        policy([dict(ECON, accepted_missing=[acc(K1, lacking=bad)])])
    reg = {k: v for k, v in acc(K1).items() if k != 'lacking'}
    with pytest.raises(I.PolicyError):
        policy([dict(ECON, accepted_missing=[reg])])


def test_g1_the_cause_is_in_the_record_and_alert(tmp_path, monkeypatch):
    monkeypatch.setattr(I, 'EFFECTIVE', None)
    h, s = _real_us(tmp_path, _chain(CPI))
    cond = next(c for c in s['conditions'] if c['kind'] == 'accepted_missing')
    assert all(i['lacking'] == '2025-10' for i in cond['indicators'])
    assert '2025-10 없음' in s['inputs']['accepted_missing'][0]
