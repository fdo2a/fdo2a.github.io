"""1a 구현 검토 4회차(codex IMPL NO, 2026-11-18) — H1 「미발표」의 근거, H2 표식은 축마다 하나, H3 들인 날은 조건.

H1: `not_published` 는 원천이 그 달 행을 주고 값 칸이 **명시적으로 빈 표기**일 때만 — 공식 API 의 `"."`, fredgraph.csv 의
빈 문자열·`.`. 값 필드가 없거나 null 이거나 알 수 없는 형식이면 근거가 없다 → `unknown`(보류).
"""
import json
import os
import subprocess
import sys

import pytest

import collect_market_data as cmd
from us import fred as F
from us import macro_gate as G
from us import macro_metrics as M
from us.tests.test_impl_review_r3 import D, monthly

SCRIPTS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def api_client(observations):
    c = F.FredClient(key='k' * 32)
    c.transport = 'api'
    c._json = lambda url: {'count': len(observations), 'observations': observations}
    return c


def csv_client(body):
    c = F.FredClient(key=None)
    c.transport = 'csv'
    c._get = lambda url: body.encode()
    return c


OK = [{'date': '2025-09-01', 'value': '324.3'}, {'date': '2025-11-01', 'value': '325.063'}]


@pytest.mark.parametrize('row,blank,unclear', [
    ({'date': '2025-10-01', 'value': '.'}, True, False),              # 공식 API 의 빈 표기
    ({'date': '2025-10-01'}, False, True),                            # codex 재현 — 값 필드가 없다(전에는 미발표)
    ({'date': '2025-10-01', 'value': None}, False, True),
    ({'date': '2025-10-01', 'value': ''}, False, True),               # API 는 빈 문자열을 쓰지 않는다 — 모르는 형식
    ({'date': '2025-10-01', 'value': 'N/A'}, False, True),
    ({'date': '2025-10-01', 'value': ' . '}, False, True),
])
def test_h1_api_only_the_dot_is_an_explicit_blank(row, blank, unclear):
    c = api_client([OK[0], row, OK[1]])
    assert c.series('CPIAUCSL') == [('2025-09-01', 324.3), ('2025-11-01', 325.063)]       # 계약은 그대로
    assert (c.blank_dates['CPIAUCSL'] == ['2025-10-01']) is blank
    assert (c.unclear_dates['CPIAUCSL'] == ['2025-10-01']) is unclear


@pytest.mark.parametrize('line,blank,unclear', [
    ('2025-10-01,', True, False),                                     # fredgraph.csv 의 빈칸
    ('2025-10-01,.', True, False),                                    # 옛 표기
    ('2025-10-01', False, True),                                      # 값 칸 자체가 없다
    ('2025-10-01,N/A', False, True),
    ('2025-10-01, ', False, True),
    ('2025-10-01,#N/A', False, True),
])
def test_h1_csv_only_empty_or_dot_is_an_explicit_blank(line, blank, unclear):
    c = csv_client(f'observation_date,CPIAUCSL\n2025-09-01,324.3\n{line}\n2025-11-01,325.063\n')
    assert c.series('CPIAUCSL') == [('2025-09-01', 324.3), ('2025-11-01', 325.063)]
    assert (c.blank_dates['CPIAUCSL'] == ['2025-10-01']) is blank
    assert (c.unclear_dates['CPIAUCSL'] == ['2025-10-01']) is unclear


def _states(monkeypatch, blanks, unclear):
    monkeypatch.setattr(cmd, 'ECON', [('Inflation', 'CPI YoY', 'CPIAUCSL', 'yoy_pct', '%')])
    monkeypatch.setattr(cmd, 'fred_series', lambda sid: monthly('2019-01', '2026-10', skip=('2025-10',)))
    monkeypatch.setattr(cmd, 'fred_blanks', lambda sid: blanks)
    monkeypatch.setattr(cmd, 'fred_unclear', lambda sid: unclear)
    monkeypatch.setattr(cmd.time, 'sleep', lambda s: None)
    reasons, refs = {}, {}
    rows, _ = cmd.collect_econ(reasons, refs)
    return cmd.econ_collect(rows, reasons, D, refs)['missing_ref']['no_value:CPI YoY']['lacking_why']


def test_h1_unclear_row_is_unknown_not_not_published(monkeypatch):
    assert _states(monkeypatch, ['2025-10-01'], []) == {'2025-10': 'not_published'}
    assert _states(monkeypatch, [], ['2025-10-01']) == {'2025-10': 'unknown'}            # 재현: 전에는 not_published
    assert _states(monkeypatch, ['2025-10-01'], ['2025-10-01']) == {'2025-10': 'unknown'}  # 둘 다면 모른다
    assert _states(monkeypatch, [], None) == {'2025-10': 'unknown'}                      # 형식 정보 자체가 없다
    assert _states(monkeypatch, [], []) == {'2025-10': 'not_collected'}


def test_h1_wrapper_reads_the_client(monkeypatch):
    c = api_client([OK[0], {'date': '2025-10-01'}, OK[1]])
    c.series('CPIAUCSL')
    monkeypatch.setattr(cmd, 'fred_client', lambda: c)
    assert cmd.fred_blanks('CPIAUCSL') == [] and cmd.fred_unclear('CPIAUCSL') == ['2025-10-01']
    assert cmd.fred_blanks('NOPE') is None and cmd.fred_unclear('NOPE') is None


# ── H2. 표식은 축마다 정확히 하나, 그리고 그 하나가 보여야 한다 ──────────────────────────────

from us.tests.test_macro_coverage import _cov_violations, _marker, section  # noqa: E402


def test_h2_visible_and_hidden_copies_together_are_a_violation():
    # codex 재현: 보이는 표식 + 숨겨진 표식 — 전에는 위반 []
    v = _cov_violations(section(f' {_marker()} <div hidden>{_marker()}</div>'))
    assert len(v) == 1 and '숨겨진' in v[0]
    v = _cov_violations(section(f' <details><summary>x</summary>{_marker()}</details> {_marker()}'))
    assert len(v) == 1 and '숨겨진' in v[0]


def test_h2_two_visible_markers_are_a_violation():
    v = _cov_violations(section(f' {_marker()} {_marker()}'))
    assert len(v) == 1 and '하나만' in v[0]
    # 서로 다른 말을 하는 두 표식도 — 어느 것이 맞는지 독자가 알 수 없다
    other = _marker().replace('8개 중 6개', '8개 중 8개')
    assert _cov_violations(section(f' {_marker()} {other}'))


def test_h2_exactly_one_visible_marker_passes():
    assert _cov_violations(section(' ' + _marker())) == []


# ── H3. 지표를 들인 날의 제외는 자료 결측이 아니라 산출 규칙 — 막지 않고 조건으로, 단 넷을 확인한다 ──────────

NAMES = ('Industrial Production MoM', 'Durable Goods Orders MoM', 'New Home Sales', 'Existing Home Sales',
         'Real GDP Growth QoQ (ann.)')
NEW = 'Housing Starts'
EXPECTED = [('Activity', n) for n in NAMES + (NEW,)]
PREV = '2026-11-06'


def day(zs=(4.0,) * 5, new=None, since=PREV):
    ind = [{'name': n, 'axis': 'Activity', 'role': 'scored', 'introduced': False, 'signed_z': z, 'actual': 1.0}
           for n, z in zip(NAMES, zs)]
    row = {'name': NEW, 'axis': 'Activity', 'role': 'scored', 'introduced': True, 'signed_z': -0.6, 'actual': 1221.0}
    row.update(new or {})
    mm = {'indicators': ind + [row], 'book_state': 'ok', 'introduced': [NEW], 'introduced_since': {NEW: since},
          'axis_summary': {'Activity': {'label_ko': '생산·활동'}}}
    mm = M.with_coverage(mm, [], EXPECTED)
    mm['collect'] = cmd.macro_metrics_collect(mm, {'status': 'ok', 'missing': []}, D)
    return mm


def _gate(mm, prev=PREV):
    sys.path.insert(0, SCRIPTS)
    import check_macro
    return check_macro.coverage_hold(mm, prev_date=prev), check_macro.coverage_notes(mm)


def test_h3_introduction_day_is_a_condition_not_a_block():
    mm = day()
    c = mm['coverage']['Activity']
    assert (c['total'], c['used']) == (6, 5) and [(e['name'], e['why']) for e in c['excluded']] == [(NEW, 'introduced')]
    assert mm['collect']['status'] == 'ok' and mm['collect']['missing'] == []     # 재현: 전에는 partial·introduced:<이름>
    assert NEW in mm['collect']['detail']                                        # 수집 상태에도 적는다
    hold, notes = _gate(mm)
    assert hold is None                                                          # 축이 한쪽으로 치우쳐 판단이 안 바뀐다
    assert len(notes) == 1 and '주택착공' in notes[0] or NEW in notes[0]           # 조건으로 남는다(경고 줄)
    assert '6개 중 5개' in c['phrase_ko'] and '새로 들인 지표' in c['phrase_ko']     # 글의 산출 범위 표시는 그대로 필수


def test_h3_no_score_or_missing_value_cannot_hide_behind_introduced():
    # (a)(b) 값이 없거나 점수 계산이 안 된 행은 「들인 날」이 아니라 결측이다 — 막는다
    for bad in ({'signed_z': None}, {'actual': None}, {'actual': float('nan')}, {'actual': 'x'}):
        mm = day(new=bad)
        assert [(e['name'], e['why']) for e in mm['coverage']['Activity']['excluded']] == [(NEW, 'no_score')], bad
        assert mm['collect']['status'] == 'partial' and mm['collect']['missing'] == [f'no_score:{NEW}'], bad
    # 들인 날이 아닌데(자료의 그 칸이 False) 점수가 없는 것도 결측
    mm = day(new={'introduced': False, 'signed_z': None})
    assert mm['collect']['missing'] == [f'no_score:{NEW}']
    # 수집 상태가 「들인 날」이라 적어도 지표 행이 그렇게 말하지 않으면 게이트가 어긋남을 본다
    mm = day()
    mm['indicators'][-1]['signed_z'] = None
    hold, _ = _gate(mm)
    assert hold and '다르다' in hold
    mm = day()
    mm['indicators'][-1]['introduced'] = False                                   # 산출 범위는 들인 날이라는데 행은 아니다
    hold, _ = _gate(mm)
    assert hold is not None


def test_h3_sensitivity_applies_the_same_way():
    # (c) 들인 지표를 뺀 것이 축 판단을 바꿀 수 있으면 보류
    hold, _ = _gate(day(zs=(0.3,) * 5))
    assert hold and hold.startswith('승인된 결측이 판단을 바꿀 수 있음') is False and '판단을 바꿀 수 있음' in hold
    assert '사람 승인 필요' in hold


def test_h3_introduced_for_more_than_one_day_holds():
    # (d) 들인 상태가 다음 발행일에도 이어진다 — 어제 책이 아니라 그 전 책에 견준 것이다
    hold, _ = _gate(day(since='2026-11-05'))
    assert hold and '하루를 넘겨' in hold
    hold, _ = _gate(day(), prev=None)                                            # 어제 책의 날짜를 모르면 판정할 수 없다
    assert hold and '하루를 넘겨' in hold
    mm = day()
    mm.pop('introduced_since')
    assert _gate(mm)[0]


def test_h3_check_macro_prints_a_warning_line_instead_of_holding(tmp_path):
    """끝에서 끝까지 — 들인 날이고 판단이 안 바뀌는 날: exit 2 가 아니고, 실행기가 조건으로 읽을 경고 줄이 나온다."""
    d = tmp_path / 'data'
    (d / 'releases').mkdir(parents=True)
    files = {'macro.json': {'report_date': PREV, 'regime': [0, 1]}, 'macro_eval.json': {'report_date': D},
             'macro_next.json': {'report_date': D}, 'market_data.json': {'report_date': D},
             'econ_indicators.json': {'indicators': [{'name': NEW}]},
             'releases/index.json': {'report_date': D, 'status': 'complete', 'releases': []}}
    for name, obj in files.items():
        (d / name).write_text(json.dumps(obj), encoding='utf-8')
    html = tmp_path / f'{D}.html'
    html.write_text('<html><body><main><section><h2>매크로</h2><p>본문</p></section></main></body></html>', encoding='utf-8')

    def run(mm):
        (d / 'macro_metrics.json').write_text(json.dumps(dict(mm, report_date=D)), encoding='utf-8')
        return subprocess.run([sys.executable, os.path.join(SCRIPTS, 'check_macro.py'), '--html', str(html),
                               '--datadir', str(d)], capture_output=True, text=True, cwd=os.path.dirname(SCRIPTS))
    r = run(day())
    assert r.returncode != 2 and '경고: 생산·활동 축 점수는 6개 중 5개로 산출' in r.stdout
    r = run(day(zs=(0.3,) * 5))                                                  # 판단이 바뀔 수 있는 날 — 보류
    assert r.returncode == 2 and '새로 들인 지표의 제외가 판단을 바꿀 수 있음 — 사람 승인 필요' in r.stderr
    r = run(day(since='2026-11-05'))                                             # 하루를 넘겼다 — 보류
    assert r.returncode == 2 and '하루를 넘겨' in r.stderr
