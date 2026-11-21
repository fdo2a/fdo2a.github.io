"""실제 자료 분류 정책(`config/prepub_inputs.json`)과 실행 목록이 맞물리는지 (2026-11-17 1a).

- 실제 설정은 정책을 반드시 가리킨다(정책 없이 돌면 자료 누락을 보지 않는다).
- gate 분류 자료는 모두 어떤 필수 검사기의 입력이다(아무도 안 보는 gate 는 분류가 틀린 것).
- 검증 기록 12건의 입력 파일과 레포 자료 폴더의 모든 파일이 분류된다(오차단 측정 — 분류 안 된 파일 = 미완료).
- 수집 중단 등록은 사람이 승인한 것뿐이다.
"""
import fnmatch
import glob
import json
import os

import pytest

from verification import inputs as I
from verification import record2 as R

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
CFG = os.path.join(ROOT, 'config', 'prepub_gates.json')


@pytest.fixture(scope='module')
def both():
    cfg = R.load_config(CFG)
    return cfg, R.load_policy(cfg, CFG)


def _class(pol, market, key, date):
    files, disc = I.entries(pol, market)
    for e in files:
        if fnmatch.fnmatchcase(key, I._pat(e['path'], date)):
            return e
    for d in disc:
        if fnmatch.fnmatchcase(key, I._pat(d['path'], date)):
            return dict(d, **{'class': 'discontinued'})
    return None


def test_real_config_points_at_the_policy(both):
    cfg, pol = both
    assert cfg.get('inputs_policy') == 'config/prepub_inputs.json' and pol is not None
    for market, m in cfg['markets'].items():
        for g in m['gates']:
            assert isinstance(g.get('inputs'), list), (market, g['name'])
            # 지난 글 재검사용 완화 플래그는 발행 실행 목록에 넣지 않는다
            assert '--legacy-releases' not in (g.get('argv') or []) and '--allow-missing-eval' not in (g.get('argv') or [])


def test_every_gate_file_is_read_by_a_required_gate(both):
    cfg, pol = both
    for market in ('us', 'kr'):
        files, _ = I.entries(pol, market)
        used = {p for g in cfg['markets'][market]['gates'] if g.get('required', True) for p in g['inputs']}
        for e in files:
            if e['class'] == 'gate' and e.get('produced_by') != 'meta':
                assert e['path'] in used, (market, e['path'])


def test_number_source_workspace_files_do_not_block_the_us_daily(both, tmp_path, monkeypatch):
    """숫자 출처 검사가 작업 공간에 남기는 파일(첫 판 사본·숫자 목록)은 US 일간에서 분류돼 있다 — 분류가 없으면
    1a 를 켠 날부터 2판이 「미분류 입력」으로 글을 미완료로 막는다(2026-11-22 codex 구현 4회차 지적)."""
    _, pol = both
    for rel in ('numsrc_first.html', 'numsrc_first_news.html', 'news/numbers/2026-11-23.json',
                'telegram/numbers/2026-11-23.json'):
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text('{}', encoding='utf-8')
    monkeypatch.setattr(I, 'EFFECTIVE', '2026-11-01')
    res = I.assess(pol, 'us', {'date': '2026-11-23', 'datadir': str(tmp_path)})
    assert res['unclassified'] == []
    for rel in ('numsrc_first.html', 'numsrc_first_news.html'):
        rec = res['files']['<datadir>/' + rel]
        assert rec['class'] == 'unused' and not rec['blocking']


def test_writer_entries_say_risk_and_coverage(both):
    _, pol = both
    for market in ('us', 'kr'):
        for e in I.entries(pol, market)[0]:
            if e['class'] == 'writer':
                assert e['risk'] and (e['covered_by'] is None or isinstance(e['covered_by'], str)), e['path']


def test_discontinued_is_user_approved(both):
    _, pol = both
    (d,) = I.entries(pol, 'kr')[1]
    assert d['path'] == '<datadir>/kr_flows_intraday.json' and d['approved_by'] == 'user'
    assert d['since'] == '2026-09-17' and d['missing_key'] == 'flows_intraday' and d['approved_at'] == '2026-11-17'
    assert I.entries(pol, 'us')[1] == []


@pytest.mark.parametrize('market', ['us', 'kr'])
def test_every_recorded_input_is_classified(both, market):
    _, pol = both
    recs = sorted(glob.glob(os.path.join(ROOT, 'verification', market, '*.json')))
    assert len(recs) >= 6
    for p in recs:
        rec = json.load(open(p, encoding='utf-8'))
        for f in rec['inputs']['files']:
            key = f['path'] if f['path'].startswith('<datadir>') else f['path'].split('/', 1)[0]
            assert _class(pol, market, key, rec['date']), (p, f['path'])


@pytest.mark.parametrize('market,root', [('us', 'data'), ('kr', 'kr/data')])
def test_every_file_in_the_repo_data_folder_is_classified(both, market, root):
    _, pol = both
    base = os.path.join(ROOT, root)
    for d, _dirs, names in os.walk(base):
        for n in names:
            if n.startswith('.'):
                continue
            key = '<datadir>/' + os.path.relpath(os.path.join(d, n), base).replace(os.sep, '/')
            assert _class(pol, market, key, '2026-11-16'), key
    assert _class(pol, market, '<datadir>/_collect_status.json', '2026-11-16')['class'] == 'gate'
