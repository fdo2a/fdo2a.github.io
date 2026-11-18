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


@pytest.mark.parametrize('state', ['not_collected', 'collect_failed', 'unknown', None, 'published'])
def test_h2_exception_only_when_the_month_was_not_published(tmp_path, monkeypatch, state):
    # 같은 달이 없어도 「기관이 내지 않았다」가 아니면(원천에 아직 없음·수집 실패·모름) 승인된 미발표가 아니다
    monkeypatch.setattr(I, 'EFFECTIVE', None)
    chain = json.loads(json.dumps(_chain(CPI)))
    for c in chain:
        for r in c['missing_ref'].values():
            if state is None:
                r.pop('lacking_why')
            else:
                r['lacking_why'] = {'2025-10': state}
    h, s = _real_us(tmp_path, chain)
    assert not s['publish_ok'] and len(s['inputs']['blocking']) == 4, state
    h, s = _real_us(tmp_path, _chain(CPI))                                        # not_published — 조건부
    assert s['publish_ok'] and s['status'] == 'conditional'


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
    assert '2025-10 미발표' in s['inputs']['accepted_missing'][0]


# ── G5. 2026-12-10 뒤 — 2026-11 전년 대비는 있고 2026-10 전년 대비는 없다: 예외 없이 통과해야 한다 ───────────

def test_g5_after_december_cpi_us_passes_without_the_exception(tmp_path, monkeypatch):
    """합성 원자료(2025-10 만 원천에 없다, 최신 달 2026-11)를 수집 함수들에 그대로 흘린다 — 수집 → 점수 → 수집 상태 넷 →
    실제 정책의 자료 판정(글 날짜 2026-12-10, 예외 만료 뒤) → check_macro 의 보류 판정 → 축 표 게이트.
    한계: 실제 FRED 응답·실제 발행 글이 아니다(그날이 오지 않았다)."""
    sys.path.insert(0, SCRIPTS)
    import check_macro
    import collect_market_data as cmd
    import eval_macro_regime
    import fetch_releases
    from us import macro_metrics as M
    from us import macro_table_gate as T
    from us.tests.test_impl_review_r3 import TABLE, monthly
    day = '2026-12-10'
    monkeypatch.setattr(I, 'EFFECTIVE', None)
    table = [('Inflation', 'CPI YoY', 'CPIAUCSL', 'yoy_pct', '%'), ('Inflation', 'CPI MoM', 'CPIAUCSL', 'mom_pct', '%'),
             ('Inflation', 'Core CPI YoY', 'CPILFESL', 'yoy_pct', '%')]
    series = {'CPIAUCSL': monthly('2018-01', '2026-11', skip=('2025-10',), step=1.3),
              'CPILFESL': monthly('2018-01', '2026-11', skip=('2025-10',), step=0.9)}
    monkeypatch.setattr(cmd, 'ECON', table)
    monkeypatch.setattr(cmd, 'fred_series', lambda sid: series[sid])
    monkeypatch.setattr(cmd, 'fred_blanks', lambda sid: ['2025-10-01'])          # 원천 응답: 그 달 행은 있고 값이 빈칸
    monkeypatch.setattr(cmd.time, 'sleep', lambda s: None)
    reasons, refs = {}, {}
    rows, by_id = cmd.collect_econ(reasons, refs)
    assert reasons == {} and [r['name'] for r in rows] == ['CPI YoY', 'CPI MoM', 'Core CPI YoY']
    yoy = rows[0]
    assert yoy['ref_period'] == '2026-11-01' and yoy['previous'] is None       # 직전(2026-10 전년 대비)은 비운다
    assert yoy['previous_why'] == 'not_published'                               # 왜 비었나 — 기관이 내지 않았다
    assert rows[1]['previous'] is not None                                     # 전월 대비는 평소대로
    econ = cmd.econ_collect(rows, reasons, day, refs)
    assert econ['status'] == 'ok' and econ['missing'] == []
    for r in rows:
        r['vs_prev'] = M.vs_prev(r['name'], r['axis'], r['actual'], r['previous'])
    seen = {r['name']: [r['ref_period'], r['actual']] for r in rows}            # 어제 책이 이미 아는 지표(들인 날이 아니다)
    mm = M.compute(by_id, rows, seen, book_state='ok')
    mm = M.with_coverage(mm, cmd.excluded_scored(reasons, refs), cmd.expected_scored())
    assert 'coverage' not in mm                                                # 축 점수에 셋 다 쓰였다
    assert all(r['signed_z'] is not None for r in mm['indicators'])            # 점수는 이력으로 — 직전 칸과 무관
    mmc = cmd.macro_metrics_collect(mm, econ, day)
    ev = eval_macro_regime.eval_collect(day, 'fresh', {'collect': mmc}, 'ok')
    idx = fetch_releases.index_collect({'report_date': day, 'releases': [{'key': 'cpi', 'ok': True}]}, 'fresh', mmc)
    assert [c['status'] for c in (mmc, ev, idx)] == ['ok', 'ok', 'ok']
    # 자료 판정 — 실제 정책, 예외는 만료됐고(2026-12-09) 걸릴 결측도 없다
    h, s = _real_us(tmp_path, (econ, mmc, ev, idx), date=day)
    assert s['publish_ok'] and not s['inputs']['blocking'] and not s['inputs']['accepted_missing']
    assert not [c for c in s['conditions'] if c['kind'] == 'accepted_missing']
    # 판단 민감도 보류 — 빠진 지표가 없으니 걸리지 않는다
    assert check_macro.coverage_hold(dict(mm, report_date=day, collect=mmc)) is None
    # 축 표 — Previous·직전 대비 「—」가 통과한다
    trend = next(r for r in mm['indicators'] if r['name'] == 'CPI YoY')['trend_cell_ko']
    page = TABLE.format(actual=f"{yoy['actual']}%", prev='— (미발표)', vs='—', trend=trend)
    assert T.check_tables(page, [yoy], dict(mm, report_date=day), day) == []
    assert T.check_tables(page.replace('— (미발표)', '—'), [yoy], dict(mm, report_date=day), day)   # 사유 없는 「—」는 위반
    # 같은 날 최신 달(2026-11)을 못 받았으면(원천이 2026-10 에서 멈춤) 예외도 만료라 막힌다
    series2 = {k: [x for x in v if x[0] <= '2026-10-01'] for k, v in series.items()}
    monkeypatch.setattr(cmd, 'fred_series', lambda sid: series2[sid])
    reasons, refs = {}, {}
    rows2, _ = cmd.collect_econ(reasons, refs)
    econ2 = cmd.econ_collect(rows2, reasons, day, refs)
    mmc2 = cmd.macro_metrics_collect({'indicators': [], 'book_state': 'ok'}, econ2, day)
    ev2 = eval_macro_regime.eval_collect(day, 'fresh', {'collect': mmc2}, 'ok')
    idx2 = fetch_releases.index_collect({'report_date': day, 'releases': [{'key': 'cpi', 'ok': True}]}, 'fresh', mmc2)
    assert not _real_us(tmp_path, (econ2, mmc2, ev2, idx2), date=day)[1]['publish_ok']
    assert _real_us(tmp_path, (econ2, mmc2, ev2, idx2), date='2026-12-09')[1]['publish_ok']   # 만료 전날까지는 예외
