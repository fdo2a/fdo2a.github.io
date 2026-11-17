"""원천 미발표로 점수에서 빠진 지표(2026-11-17 사용자 승인 조건 7·8).

7 — 일부 지표 없이 낸 축 점수를 온전한 점수와 같게 싣지 않는다: `macro_metrics.json` 의 `coverage`(몇 개 중 몇 개, 무엇이
빠졌나)와 글의 `data-axis-coverage` 표식, `check_macro` 가 대조한다.
8 — 빠진 지표가 있었다면 판단(축의 방향·강도, 레짐의 물가 다리)이 달라질 수 있는 날은 자동 발행하지 않는다: 빠진 지표가
모두 점수 범위의 아래 끝·위 끝일 때로 다시 계산해 지금과 같은지 본다. 다르면 `check_macro` 가 exit 2(보류).
"""
import json
import os
import subprocess
import sys

import pytest

from us import macro_gate as G
from us import macro_metrics as M

SCRIPTS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXCL = [{'name': 'CPI YoY', 'axis': 'Inflation', 'fred_id': 'CPIAUCSL', 'transform': 'yoy_pct', 'ref_period': '2026-10'},
        {'name': 'Core CPI YoY', 'axis': 'Inflation', 'fred_id': 'CPILFESL', 'transform': 'yoy_pct',
         'ref_period': '2026-10'}]
NAMES = ('CPI MoM', 'Core CPI MoM', 'PPI Final Demand MoM', 'PCE Price Index YoY', 'Core PCE YoY',
         'Michigan 1-Yr Inflation Exp')


def rows(zs, axis='Inflation'):
    return [{'name': n, 'axis': axis, 'role': 'scored', 'introduced': False, 'signed_z': z} for n, z in zip(NAMES, zs)]


def mm(zs):
    ind = rows(zs) + [{'name': 'Nonfarm Payrolls (chg)', 'axis': 'Labor', 'role': 'scored', 'introduced': False,
                       'signed_z': 0.4}]
    return {'indicators': ind, 'axis_summary': {'Inflation': {'label_ko': '물가', 'total': len(zs)},
                                                'Labor': {'label_ko': '고용', 'total': 1}}}


def test_coverage_says_how_many_of_how_many_and_what_is_left_out():
    out = M.with_coverage(mm([0.5] * 6), EXCL)
    c = out['coverage']['Inflation']
    assert (c['total'], c['used']) == (8, 6) and [e['name'] for e in c['excluded']] == ['CPI YoY', 'Core CPI YoY']
    assert c['excluded'][0] == {'name': 'CPI YoY', 'label_ko': '소비자물가 전년비', 'fred_id': 'CPIAUCSL',
                                'transform': 'yoy_pct', 'ref_period': '2026-10'}
    assert c['phrase_ko'] == '8개 중 6개로 산출, 소비자물가 전년비·근원 소비자물가 전년비는 원천 미발표로 제외'
    assert out['axis_summary']['Inflation']['coverage_ko'] == c['phrase_ko']
    assert 'Labor' not in out['coverage'] and 'coverage_ko' not in out['axis_summary']['Labor']
    # 빠진 지표가 없으면 아무것도 싣지 않는다, 값을 채워 넣지도 않는다
    assert 'coverage' not in M.with_coverage(mm([0.5] * 6), [])
    assert [r['name'] for r in out['indicators'] if r['axis'] == 'Inflation'] == list(NAMES)


def test_sensitivity_uses_both_ends_of_the_score_range():
    b = M.SENSITIVITY_Z
    # 평균 0.451(재가속, 레짐 다리 +1) — 빠진 둘이 아래 끝이면 (6·0.451 − 2·3)/8 = −0.41(둔화, −1): 판단이 달라진다
    s = M.sensitivity(rows([0.451] * 6), 'Inflation', 2)
    assert s['bound'] == b and s['now'][0] == '재가속' and s['now'][2] == 1
    assert s['low'][2] == -1 and s['high'][2] == 1 and s['stable'] is False
    # 축이 한쪽으로 크게 치우친 날 — 양 끝 어디여도 같은 판단
    s = M.sensitivity(rows([5.0] * 6), 'Inflation', 2)
    assert s['stable'] is True and s['now'] == s['low'] == s['high']
    # 결정적이다
    assert M.sensitivity(rows([0.451] * 6), 'Inflation', 2) == M.sensitivity(rows([0.451] * 6), 'Inflation', 2)
    # 점수가 하나도 없는 축은 판단할 수 없다
    assert M.sensitivity([], 'Inflation', 2)['stable'] is False
    # 도입일 행·해부 전용 행은 `compute` 처럼 점수에서 뺀다
    extra = rows([5.0] * 6) + [{'name': 'x', 'axis': 'Inflation', 'role': 'anatomy', 'signed_z': -99.0},
                               {'name': 'y', 'axis': 'Inflation', 'role': 'scored', 'introduced': True, 'signed_z': -99.0}]
    assert M.sensitivity(extra, 'Inflation', 2)['stable'] is True


def test_verdict_matches_the_regime_thresholds():
    from us import macro as U
    for mean in (-1.2, -0.34, -0.33, -0.2, 0.0, 0.26, 0.33, 0.34, 0.6, 1.5):
        d, s, leg = M.axis_verdict(mean, 'Inflation')
        assert (d, s) == M.describe(mean, 'Inflation') and leg == U.classify(mean)


# ── 글의 표시(게이트) ──────────────────────────────────────────────────────

def section(extra=''):
    return ('<section><h2>매크로</h2><div class="ax-strip"><span class="ax-item"><b>물가</b> '
            f'<span data-axis="Inflation">재가속</span> <span class="sub">6개 중 4개</span>{extra}</span></div></section>')


def cov_metrics(zs=(5.0,) * 6):
    return M.with_coverage(mm(list(zs)), EXCL)


def test_gate_requires_the_visible_coverage_marker():
    m = cov_metrics()
    phrase = m['coverage']['Inflation']['phrase_ko']
    v = []
    G._check_coverage(section(), m, v)
    assert len(v) == 1 and '8개 중 6개' in v[0] and 'data-axis-coverage="Inflation"' in v[0]     # 표시가 없다
    v = []
    G._check_coverage(section(f' <span class="sub" data-axis-coverage="Inflation">{phrase}</span>'), m, v)
    assert v == []
    for bad, why in ((phrase.replace('8개 중 6개', '8개 중 8개'), '8개 중 6개'), (phrase.replace('원천 미발표로 ', ''), '원천 미발표'),
                     (phrase.replace('근원 소비자물가 전년비', '근원 물가'), '근원 소비자물가 전년비'),
                     (phrase.replace('제외', '반영'), '제외')):
        v = []
        G._check_coverage(section(f'<span data-axis-coverage="Inflation">{bad}</span>'), m, v)
        assert len(v) == 1 and why in v[0], bad
    for hidden in ('hidden', 'style="display:none"', 'style="visibility: hidden"', 'aria-hidden="true"'):
        v = []
        G._check_coverage(section(f'<span {hidden} data-axis-coverage="Inflation">{phrase}</span>'), m, v)
        assert any('숨겨져' in x for x in v) and any('data-axis-coverage' in x for x in v), hidden


def test_gate_rejects_the_marker_on_a_day_without_exclusions():
    v = []
    G._check_coverage(section('<span data-axis-coverage="Inflation">8개 중 6개로 산출</span>'), mm([0.5] * 6), v)
    assert len(v) == 1 and '빠진 지표가 없는데' in v[0]
    v = []
    G._check_coverage(section(), mm([0.5] * 6), v)
    assert v == []


def test_phrase_passes_the_published_style_rules(tmp_path):
    # 발행본 문체: 작업 어휘·파일 이름이 없어야 한다(표식 안의 문장은 독자가 읽는다)
    phrase = cov_metrics()['coverage']['Inflation']['phrase_ko']
    html = tmp_path / '2026-11-16.html'
    html.write_text('<html><body data-register="da"><main><section><h2>매크로</h2>'
                    f'<p>물가 축 점수는 {phrase}했다.</p></section></main></body></html>', encoding='utf-8')
    r = subprocess.run([sys.executable, os.path.join(SCRIPTS, 'check_style.py'), str(html)], capture_output=True,
                       text=True, cwd=os.path.dirname(SCRIPTS))
    assert r.returncode == 0, r.stdout + r.stderr
    for word in ('json', 'no_value', 'coverage', 'missing', '수집', '게이트'):
        assert word not in phrase


# ── check_macro 의 보류(결정적) ────────────────────────────────────────────

def _hold(metrics):
    sys.path.insert(0, SCRIPTS)
    import check_macro
    return check_macro.coverage_hold(metrics)


def collect(names=('CPI YoY', 'Core CPI YoY')):
    return {'status': 'partial', 'missing': [f'econ:no_value:{n}' for n in names]}


def test_hold_when_the_excluded_indicators_could_change_the_judgment():
    m = dict(cov_metrics((0.451,) * 6), collect=collect())
    why = _hold(m)
    assert why and why.startswith('승인된 결측이 판단을 바꿀 수 있음 — 사람 승인 필요')
    assert '8개 중 6개' in why and '재가속' in why and '둔화' in why
    assert _hold(dict(cov_metrics((5.0,) * 6), collect=collect())) is None        # 양 끝 어디여도 같은 판단 — 보류하지 않는다
    assert _hold(dict(mm([0.451] * 6), collect={'status': 'ok', 'missing': []})) is None   # 빠진 지표가 없는 날


def test_hold_recomputes_and_does_not_trust_a_stored_flag():
    m = dict(cov_metrics((0.451,) * 6), collect=collect())
    m['coverage']['Inflation']['sensitivity'] = {'stable': True}                  # 자료가 「안정」이라고 적어도
    assert _hold(m).startswith('승인된 결측이 판단을 바꿀 수 있음')


def test_hold_when_the_data_cannot_be_judged():
    stable = cov_metrics((5.0,) * 6)
    assert '산출 범위(coverage)가 없다' in _hold(dict(mm([5.0] * 6), collect=collect()))
    assert '다르다' in _hold(dict(stable, collect=collect(('CPI YoY',))))            # 수집 상태와 제외 목록이 다르다
    bad = json.loads(json.dumps(stable))
    bad['coverage']['Inflation']['used'] = 8
    assert '맞지 않는다' in _hold(dict(bad, collect=collect()))
    bad = json.loads(json.dumps(stable))
    bad['coverage']['Inflation']['excluded'] = []
    assert _hold(dict(bad, collect=collect())) is not None


def test_check_macro_exits_2_on_a_sensitive_day(tmp_path):
    """끝에서 끝까지 — 다른 입력이 다 있어도 판단이 달라질 수 있는 날은 글을 보기 전에 보류(exit 2)."""
    d = tmp_path / 'data'
    (d / 'releases').mkdir(parents=True)
    D = '2026-11-16'
    files = {'macro.json': {'report_date': '2026-11-13', 'regime': [0, 1]}, 'macro_eval.json': {'report_date': D},
             'macro_next.json': {'report_date': D}, 'market_data.json': {'report_date': D},
             'econ_indicators.json': {'indicators': [{'name': 'CPI MoM'}]},
             'releases/index.json': {'report_date': D, 'status': 'complete', 'releases': []}}
    for name, obj in files.items():
        (d / name).write_text(json.dumps(obj), encoding='utf-8')
    html = tmp_path / f'{D}.html'
    html.write_text('<html><body><main><section><h2>매크로</h2><p>본문</p></section></main></body></html>', encoding='utf-8')

    def run(metrics):
        (d / 'macro_metrics.json').write_text(json.dumps(dict(metrics, report_date=D)), encoding='utf-8')
        return subprocess.run([sys.executable, os.path.join(SCRIPTS, 'check_macro.py'), '--html', str(html),
                               '--datadir', str(d)], capture_output=True, text=True, cwd=os.path.dirname(SCRIPTS))
    r = run(dict(cov_metrics((0.451,) * 6), collect=collect()))
    assert r.returncode == 2 and '승인된 결측이 판단을 바꿀 수 있음 — 사람 승인 필요' in r.stderr and '보류' in r.stderr
    r = run(dict(cov_metrics((5.0,) * 6), collect=collect()))
    assert r.returncode != 2 and '승인된 결측이 판단을 바꿀 수 있음' not in r.stderr   # 보류가 아니다 — 글 검사로 넘어간다
