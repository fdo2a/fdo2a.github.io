"""수집 워크플로가 장부의 실행 판정(`stamp_collect.py --begin`·단계 id·`COLLECT_STEPS`)에 맞게 엮여 있는가 —
정적 확인(2026-11-17, 1a 구현 검토 2회차 F3). **워크플로를 실행해 보지는 못한다.**
"""
import os

import pytest
import yaml

import stamp_collect as S

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

WF = {'us': ('.github/workflows/collect-market-data.yml', 'collect', 'data'),
      'kr': ('.github/workflows/collect-kr-data.yml', 'collect', 'kr/data')}


def _steps(market):
    path, job, _ = WF[market]
    doc = yaml.safe_load(open(os.path.join(ROOT, path), encoding='utf-8'))
    jobs = doc['jobs']
    return jobs[job]['steps'] if job in jobs else next(
        j['steps'] for j in jobs.values() if any('stamp_collect.py' in str(s.get('run')) for s in j['steps']))


@pytest.mark.parametrize('market', ['us', 'kr'])
def test_workflow_wires_begin_steps_and_stamp(market):
    steps = _steps(market)
    datadir = WF[market][2]
    runs = [str(s.get('run') or '') for s in steps]
    ids = {s['id'] for s in steps if 'id' in s}
    assert set(S.STEP_OF[market].values()) <= ids, set(S.STEP_OF[market].values()) - ids
    begin = next(i for i, r in enumerate(runs) if 'stamp_collect.py' in r and '--begin' in r)
    stamp = next(i for i, r in enumerate(runs) if 'stamp_collect.py' in r and '--begin' not in r)
    first_write = min(i for i, s in enumerate(steps) if s.get('id') in set(S.STEP_OF[market].values()))
    assert begin < first_write < stamp
    assert f'--datadir {datadir}' in runs[begin] and f'--datadir {datadir}' in runs[stamp]
    assert steps[stamp]['env'][S.STEPS_ENV] == '${{ toJSON(steps) }}'
    # 두 단계가 같은 실행 ID 를 받는다(3회차 G4) — 시작 기록은 그것을 연 실행의 stamp 만 쓴다
    rid = '${{ github.run_id }}-${{ github.run_attempt }}'
    assert steps[begin]['env'][S.RUN_ID_ENV] == rid and steps[stamp]['env'][S.RUN_ID_ENV] == rid
    # 장부 갱신 실패는 조용히 넘어가지 않는다 — 자료 커밋은 그대로 하되 마지막에 실행을 실패로 끝낸다
    assert steps[begin].get('id') == 'stamp_begin' and steps[stamp].get('id') == 'stamp'
    last = steps[-1]
    assert "steps.stamp.outcome == 'failure'" in last['if'] and "steps.stamp_begin.outcome == 'failure'" in last['if']
    assert 'always()' in last['if'] and 'exit 1' in last['run'] and not last.get('continue-on-error')


@pytest.mark.parametrize('market', ['us', 'kr'])
def test_every_step_id_runs_the_script_that_writes_its_files(market):
    by_id = {s['id']: str(s.get('run') or '') for s in _steps(market) if 'id' in s}
    want = {'us': {'collect': 'collect_market_data.py', 'macro_eval': 'eval_macro_regime.py',
                   'releases': 'fetch_releases.py --datadir data', 'fed': 'collect_fed_events.py',
                   'calendar': 'build_calendar.py', 'auctions': 'build_auctions.py',
                   'liquidity': 'build_liquidity.py', 'telegram': 'fetch_telegram.py'},
            'kr': {'collect': 'collect_kr_data.py', 'telegram': 'fetch_telegram.py'}}[market]
    for sid, script in want.items():
        assert script in by_id[sid], (sid, by_id.get(sid))
    assert set(want) == set(S.STEP_OF[market].values())


