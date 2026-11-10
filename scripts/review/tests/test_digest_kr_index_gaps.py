"""매일 검증 알림이 KR 주간 지수 누락을 한 줄로 알린다(2026-11-10).

발행 때 지수가 빠진 날은 새벽 재수집으로 자동 보완하지 않고 주간을 보류한 뒤 수동 정정한다 —
그 사실이 사람에게 닿아야 복구 경로가 작동한다. spec: docs/superpowers/specs/2026-11-10-kr-data-versions.md
"""
from review import digest as D


def test_gap_keys_only():
    agg = {'missing': ['indices.KOSDAQ.2026-11-06', 'flows.KOSPI: 1일 잠정/결측', 'indices.KOSDAQ: 끝값 없음']}
    assert D.kr_index_gaps(agg) == ['indices.KOSDAQ.2026-11-06']


def test_notes_name_index_date_and_recovery():
    aggs = {'2026-W45': {'missing': ['indices.KOSDAQ.2026-11-06'], 'complete': False},
            '2026-W46': {'missing': [], 'complete': True}}
    notes = D.kr_index_gap_notes(aggs)
    assert len(notes) == 1
    n = notes[0]
    assert '2026-W45' in n and 'KOSDAQ' in n and '2026-11-06' in n
    assert '수동' in n and '자동 보완하지 않' in n


def test_no_gaps_no_notes():
    assert D.kr_index_gap_notes({'2026-W46': {'missing': []}}) == []
