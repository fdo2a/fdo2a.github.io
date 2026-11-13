"""KR 표 숫자 대조(2026-11-13)가 발행 전 기록 알림에 어떻게 실리는가.

숫자가 있으면 US 와 같은 줄에 「표 N칸 대조, 미검증 M개」를 따로 적고 「검증 완료」라고 하지 않는다(codex 설계 검토 #10).
숫자가 없으면 도입 전·실행 안 함·판정 불가·기록 손상을 가른다.
"""
import copy
import json

import pytest

from review import prepub_view as V
from review.tests import prepub_fixture as F

NUMBERS = {'tokens_seen': 351, 'table_cells': 54, 'prose_judged': 0, 'unverified': 225, 'delegated': 44,
           'excluded': 28, 'unverified_by': {'KR 문장': 143, 'KR 업종 멀티기간': 71, 'KR 표(지도 밖)': 11}}


@pytest.fixture()
def kr_numbers_repo(tmp_path, monkeypatch):
    cfg = copy.deepcopy(F.CONFIG)
    cfg['markets']['kr']['gates'].append({'name': 'check_numbers', 'script': 'scripts/g2.py'})
    monkeypatch.setattr(F, 'CONFIG', cfg)
    repo = F.init(tmp_path)
    F.write(repo, 'config/prepub_gates.json', json.dumps(cfg))
    F.commit(repo, 'kr numbers gate')
    return repo


def _text(v):
    return '\n'.join(V.recorded_lines(v)), '\n'.join(V.digest_lines(v))


def test_kr_record_with_numbers(kr_numbers_repo):
    F.publish(kr_numbers_repo, 'kr', '2026-11-16', numbers=NUMBERS)
    v = V.view(str(kr_numbers_repo), 'HEAD', 'kr', '2026-11-16')
    full, digest = _text(v)
    assert '표 칸 54 대조' in full                                      # US 와 같은 줄
    assert '표 54칸 대조, 미검증 225개' in full and '숫자 검증 완료가 아니에요' in full
    assert 'KR 문장 143' in full
    assert '표 54칸 대조' in digest and '자동 대조하지 못한 수치 225개' in digest
    assert not V.fully_verified(v)


def test_kr_is_never_fully_verified_even_with_zero_unverified(kr_numbers_repo):
    F.publish(kr_numbers_repo, 'kr', '2026-11-16', numbers=dict(NUMBERS, unverified=0, unverified_by={}))
    v = V.view(str(kr_numbers_repo), 'HEAD', 'kr', '2026-11-16')
    assert V.clean(v) and not V.fully_verified(v)


@pytest.mark.parametrize('status,word', [('not_run', '실행 안 함'), ('indeterminate', '판정 불가'),
                                         ('pass', '기록 손상')])
def test_kr_record_without_numbers_says_why(kr_numbers_repo, status, word):
    F.publish(kr_numbers_repo, 'kr', '2026-11-16', gate_status={'check_numbers': status})
    v = V.view(str(kr_numbers_repo), 'HEAD', 'kr', '2026-11-16')
    full, digest = _text(v)
    assert word in full and word in digest
    assert '도입 전' not in full


def test_kr_record_from_before_the_gate(tmp_path):
    repo = F.init(tmp_path)                       # 기본 설정 — KR 목록에 check_numbers 가 없다
    F.publish(repo, 'kr', '2026-11-12')
    v = V.view(str(repo), 'HEAD', 'kr', '2026-11-12')
    full, digest = _text(v)
    assert '표 숫자 검사가 없어요(검사 도입 전 기록)' in full and '도입 전' in digest


def test_kr_unverified_kinds_reach_the_mac_summary():
    for k in ('KR 문장', 'KR 표(지도 밖)', 'KR 업종 멀티기간', 'KR 펀드 블록(위임 안 됨)'):
        assert k in V.UNVERIFIED_KINDS
    assert '분류 밖 이유' not in V._unverified_why(NUMBERS)
