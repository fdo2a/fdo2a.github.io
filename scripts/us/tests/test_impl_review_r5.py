"""1a 구현 검토 5회차(codex IMPL NO, 2026-11-19) — I1 섞인 축의 민감도, I2 CSV 행의 필드 수, I3 표식은 문서 전체에서 하나.

I1: 한 축에 들인 지표(점수를 안다)와 모르는 값(미발표·점수 없음·행 없음)이 섞이면 **둘 다** 본다 — 들인 지표는 실제 점수를
넣은 판정과 견줘 방향·레짐 다리가 다르면 보류, 모르는 값은 들인 지표를 넣은 상태와 넣지 않은 상태 양쪽에서 ±3.0 양 끝.
어느 하나라도 걸리면 보류(가장 엄격한 쪽).
"""
import os
import sys

import pytest

from us import fred as F
from us import macro_gate as G
from us import macro_metrics as M
from us.tests.test_macro_coverage import _cov_violations, _marker, cov_metrics, section

SCRIPTS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PREV = '2026-11-06'
AX = 'Inflation'


def axis_day(used, introduced=(), unknown=()):
    """used = 점수에 쓰인 값들, introduced = 들인 지표의 실제 점수들, unknown = 모르는 값의 까닭들(no_value·no_score·no_row)."""
    ind = [{'name': f'u{i}', 'axis': AX, 'role': 'scored', 'introduced': False, 'signed_z': z, 'actual': 1.0}
           for i, z in enumerate(used)]
    ind += [{'name': f'n{i}', 'axis': AX, 'role': 'scored', 'introduced': True, 'signed_z': z, 'actual': 1.0}
            for i, z in enumerate(introduced)]
    ex = [{'name': f'n{i}', 'label_ko': f'n{i}', 'why': 'introduced'} for i in range(len(introduced))]
    for i, why in enumerate(unknown):
        name = f'x{i}'
        if why == 'no_score':
            ind.append({'name': name, 'axis': AX, 'role': 'scored', 'introduced': False, 'signed_z': None, 'actual': 1.0})
        ex.append({'name': name, 'label_ko': name, 'why': why})
    return {'indicators': ind, 'introduced_since': {f'n{i}': PREV for i in range(len(introduced))},
            'coverage': {AX: {'total': len(used) + len(ex), 'used': len(used), 'excluded': ex}}}


def hold(mm):
    sys.path.insert(0, SCRIPTS)
    import check_macro
    return check_macro.coverage_hold(mm, prev_date=PREV)


def test_i1_codex_case_introduced_minus_60_with_one_unpublished():
    # 기존 점수 4.0 다섯, 들인 지표 −60.0 하나, 미발표 하나 — 전에는 None(±3 양 끝만 보고 실제 점수 비교를 건너뛰었다)
    why = hold(axis_day([4.0] * 5, introduced=[-60.0], unknown=['no_value']))
    assert why and '판단을 바꿀 수 있음' in why and '실제 점수' in why


# (쓰인 점수, 들인 지표의 실제 점수, 모르는 값의 까닭) → 보류인가
TABLE = [
    ([4.0] * 5, [], [], False),                         # 빠진 것 없음(coverage 가 없어야 정상 — 아래에서 따로)
    ([4.0] * 5, [4.0], [], False),                      # 들인 것만, 판단 그대로
    ([4.0] * 5, [-60.0], [], True),                     # 들인 것만, 실제 점수로 방향이 뒤집힌다
    ([4.0] * 5, [], ['no_value'], False),               # 모르는 값만, 양 끝 어디여도 그대로
    ([0.45] * 5, [], ['no_value'], True),               # 모르는 값만, 양 끝이면 달라진다
    ([4.0] * 5, [4.0], ['no_value'], False),            # 섞임 — 둘 다 괜찮다
    ([4.0] * 5, [-60.0], ['no_value'], True),           # 섞임 — 들인 지표가 뒤집는다(codex 재현)
    ([0.45] * 5, [0.45], ['no_value'], True),           # 섞임 — 모르는 값이 뒤집는다
    ([4.0] * 5, [-18.4], ['no_value'], True),           # 섞임 — 넣지 않은 상태는 안정, 넣은 상태(평균 0.27)는 양 끝에 흔들린다
    ([4.0] * 5, [4.0], ['no_score'], False),            # 들인 것 + 점수 없는 행 — 점수 없는 행은 모르는 값으로 양 끝
    ([0.45] * 5, [0.45], ['no_score'], True),
    ([4.0] * 5, [-60.0], ['no_score'], True),
    ([0.45] * 5, [], ['no_score', 'no_value'], True),   # 점수 없는 행 + 미발표 — 둘 다 모르는 값
    ([4.0] * 5, [], ['no_score', 'no_value'], False),
    ([4.0] * 5, [4.0], ['no_score', 'no_value', 'no_row'], False),   # 까닭 넷이 섞여도
    ([1.2] * 5, [1.2], ['no_score', 'no_value', 'no_row'], True),    # 모르는 값 셋이 아래 끝이면 강도가 달라진다
]


@pytest.mark.parametrize('used,intro,unknown,held', TABLE)
def test_i1_mixed_reasons_fall_to_the_strictest(used, intro, unknown, held):
    mm = axis_day(used, intro, unknown)
    if not intro and not unknown:
        mm.pop('coverage')
    why = hold(mm)
    assert bool(why) is held, (used, intro, unknown, why)


def test_i1_sensitivity_can_include_the_introduced_scores():
    rows = axis_day([4.0] * 5, introduced=[-18.4])['indicators']
    assert M.sensitivity(rows, AX, 1)['stable'] is True                           # 들인 지표를 넣지 않은 상태
    assert M.sensitivity(rows, AX, 1, include_introduced=True)['stable'] is False  # 넣은 상태(평균 0.27)


# ── I2. CSV 행의 필드 수가 정확히 둘이 아니면 모른다 ────────────────────────────────────────

def csv_client(body):
    c = F.FredClient(key=None)
    c.transport = 'csv'
    c._get = lambda url: body.encode()
    return c


@pytest.mark.parametrize('line,blank,unclear', [
    ('2025-10-01,', True, False),
    ('2025-10-01,.', True, False),
    ('2025-10-01,.,unexpected', False, True),          # codex 재현 — 여분 필드(전에는 미발표)
    ('2025-10-01,,', False, True),
    ('2025-10-01,,x', False, True),
    ('2025-10-01', False, True),                       # 필드 부족
])
def test_i2_csv_row_must_have_exactly_two_fields(line, blank, unclear):
    c = csv_client(f'observation_date,CPIAUCSL\n2025-09-01,324.3\n{line}\n2025-11-01,325.063\n')
    assert c.series('CPIAUCSL') == [('2025-09-01', 324.3), ('2025-11-01', 325.063)]
    assert (c.blank_dates['CPIAUCSL'] == ['2025-10-01']) is blank
    assert (c.unclear_dates['CPIAUCSL'] == ['2025-10-01']) is unclear


def test_i2_value_rows_with_extra_fields_keep_the_old_parse():
    # 값이 있는 행의 파싱 계약(앞의 두 칸)은 그대로다 — 여기서 바꾸는 것은 「빈칸」의 근거뿐
    c = csv_client('observation_date,X\n2025-09-01,324.3,extra\n2025-10-01,325.0\n')
    assert c.series('X') == [('2025-09-01', 324.3), ('2025-10-01', 325.0)]
    assert c.blank_dates['X'] == [] and c.unclear_dates['X'] == []


# ── I3. 표식은 문서 전체에서 축마다 정확히 하나, 보이는 글자가 있어야 한다 ───────────────────────

def test_i3_hidden_copy_outside_the_macro_section_is_a_violation():
    sec = section(' ' + _marker())
    doc = f'<html><body><main>{sec}<section><h2>주식</h2><div hidden>{_marker()}</div></section></main></body></html>'
    v = _cov_violations(sec, doc=doc)
    assert len(v) == 1 and '숨겨진' in v[0]                                       # 재현: 전에는 []
    doc = f'<html><body><main>{sec}<section><h2>주식</h2><p>{_marker()}</p></section></main></body></html>'
    v = _cov_violations(sec, doc=doc)
    assert len(v) == 1 and '2개' in v[0]                                          # 보이는 사본이 §8 밖에 하나 더
    # §8 밖에만 있으면 §8 에는 없는 것이다
    doc = f'<html><body><main>{section()}<section><h2>주식</h2><p>{_marker()}</p></section></main></body></html>'
    assert _cov_violations(section(), doc=doc)


def test_i3_empty_marker_and_opacity_zero():
    empty = '<span data-axis-coverage="Inflation"></span>'
    v = _cov_violations(section(f' {_marker()} {empty}'))
    assert len(v) == 1 and ('2개' in v[0] or '빈' in v[0])                        # 재현: 빈 요소가 개수에서 빠졌다
    v = _cov_violations(section(f' {empty}'))
    assert len(v) == 1 and '빈' in v[0]
    v = _cov_violations(section(' ' + _marker().replace('<span ', '<span style="opacity:0" ')))
    assert len(v) == 1 and '보이는 자리' in v[0]                                   # 재현: 전에는 통과
    v = _cov_violations(section(f' <div style="opacity: 0;">{_marker()}</div>'))
    assert len(v) == 1 and '보이는 자리' in v[0]
    for ok in ('opacity:0.6', 'opacity: 1', 'opacity:.5'):
        assert _cov_violations(section(' ' + _marker().replace('<span ', f'<span style="{ok}" '))) == [], ok


def test_i3_exactly_one_visible_marker_in_the_whole_document_passes():
    sec = section(' ' + _marker())
    assert _cov_violations(sec, doc=f'<html><body><main>{sec}<section><h2>주식</h2><p>본문</p></section></main></body></html>') == []
