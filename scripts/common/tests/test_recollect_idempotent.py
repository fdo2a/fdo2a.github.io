"""같은 값으로 다시 수집하면 자료 파일은 1a 전과 같은 방식으로만 바뀐다(2026-11-20 사용자 결정 「맞추고 올리기」).

1a 의 수집 상태 칸(`collect.collected_at`)과 장부(`_collect_status.json` 의 실행 ID·시각)는 실행마다 달라진다. 그대로 두면
값이 같은 재수집도 모든 파일의 바이트를 바꾼다 — US 건너뛴 실행이 매번 커밋하고, KR 판 관리가 실행마다 사본을 쌓고,
KR 발행 기록 뒤의 재수집이 `verify` 를 깨뜨린다. 끝의 stamp 가 「앞 판(HEAD)과 수집 시각만 다른 파일」을 앞 판 바이트로
되돌리고, 달라진 것이 없으면 장부도 앞 판 그대로 둔다.

기대값은 「1a 전 수집기라면 바뀌었을 파일」 = `collect` 칸을 뺀 내용이 앞 판과 다른 파일이다.
"""
import datetime as dt
import json
import os
import subprocess

import pytest

import stamp_collect as S
from common import collect_status as C

D = '2026-11-18'
KST = dt.timezone(dt.timedelta(hours=9))
T1 = dt.datetime(2026, 11, 19, 7, 0, tzinfo=KST)
T2 = dt.datetime(2026, 11, 19, 9, 30, tzinfo=KST)


def git(repo, *a):
    r = subprocess.run(['git', '-C', str(repo), *a], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout


def init(tmp_path):
    repo = tmp_path / 'repo'
    repo.mkdir()
    git(repo, 'init', '-q', '-b', 'main')
    git(repo, 'config', 'user.email', 't@t')
    git(repo, 'config', 'user.name', 't')
    return repo


def commit(repo, msg='run'):
    git(repo, 'add', '-A')
    git(repo, 'commit', '-q', '-m', msg, '--allow-empty')


def changed(repo):
    return sorted(line[3:] for line in git(repo, 'status', '--porcelain', '--untracked-files=all').splitlines())


def _sans_collect(raw):
    try:
        obj = json.loads(raw)
    except ValueError:
        return raw
    if isinstance(obj, dict):
        obj.pop('collect', None)
    # 정렬·정규화하지 않는다 — 키 순서·숫자 표기·타입이 다르면 바뀐 파일이다(codex 3회차 D8)
    return json.dumps(obj, ensure_ascii=False)


def pre_1a_changed(repo, datadir, written):
    """1a 전 수집기였다면 바뀌었을 파일 — 이번 실행이 쓴 내용(collect 칸 제외)이 HEAD 와 다른 것."""
    out = []
    for rel, raw in sorted(written.items()):
        path = f'{datadir}/{rel}'
        head = subprocess.run(['git', '-C', str(repo), 'show', f'HEAD:{path}'], capture_output=True, text=True)
        if head.returncode != 0 or _sans_collect(head.stdout) != _sans_collect(raw):
            out.append(path)
    return out


# ── US: 수집기 산출을 흉내 낸다(네트워크 없음) — 파일 모양·collect 칸은 실제 계약(`collect_status.build`) ──────────

def _c(when, **kw):
    return C.build('ok', D, 'fixture', collected_at=C.now_iso(when), empty='has_data', **kw)


def us_files(when, steps, yields=4.10, generated=None):
    """단계별로 그 단계가 쓰는 파일 → {상대경로: 본문}. market_data 의 `generated` 는 1a 전에도 실행마다 바뀌던 칸이다."""
    f = {}
    if 'collect' in steps:
        f['market_data.json'] = {'generated': generated or C.now_iso(when), 'report_date': D, 'complete': True,
                                 'missing': [], 'indices': {'SPX': 1}, 'yields': {'10y': yields}, 'collect': _c(when)}
        f['econ_indicators.json'] = {'indicators': [{'name': 'CPI MoM', 'actual': 0.3}], 'collect': _c(when)}
        f['intraday.json'] = {'SPX': [{'t': '09:30', 'close': 1.0}], 'collect': _c(when)}
        f['macro_metrics.json'] = {'report_date': D, 'indicators': [], 'collect': _c(when)}
        f['movers.json'] = {'report_date': D, 'groups': [], 'collect': _c(when, checked=60, expected=60)}
        f['fund_board.json'] = {'report_date': D, 'status': 'ok', 'collect': _c(when)}
        f['scorecard.json'] = {'report_date': D, 'sufficient': True}
    if 'patch' in steps:                                   # 수익률만 고치는 재실행 — market_data.json 하나만 다시 쓴다
        f['market_data.json'] = {'generated': generated or C.now_iso(when), 'report_date': D, 'complete': True,
                                 'missing': [], 'indices': {'SPX': 1}, 'yields': {'10y': yields},
                                 'yields_patched': {'at': C.now_iso(when)}, 'collect': _c(when)}
    if 'macro_eval' in steps:
        f['macro_eval.json'] = {'report_date': D, 'regime': 'x', 'collect': _c(when)}
    if 'releases' in steps:
        f['releases/index.json'] = {'report_date': D, 'status': 'complete', 'releases': [], 'collect': _c(when)}
    if 'fed' in steps:
        f['fed/events.json'] = {'report_date': D, 'events': [], 'diff': None, 'collect': _c(when)}
    if 'calendar' in steps:
        f['calendar.json'] = {'report_date': D, 'events': [{'d': D}], 'collect': _c(when)}
    if 'auctions' in steps:
        f['auctions.json'] = {'report_date': D, 'ok': True, 'today': [], 'pending': [], 'collect': _c(when)}
    if 'liquidity' in steps:
        f['liquidity/liquidity.json'] = {'report_date': D, 'status': 'complete', 'run_id': 'r',
                                         'h41': {'candidates': []}, 'collect': _c(when)}
    return {rel: json.dumps(body, ensure_ascii=False, indent=2) for rel, body in f.items()}


ALL = ('collect', 'macro_eval', 'releases', 'fed', 'calendar', 'auctions', 'liquidity')


def us_run(repo, when, ran, outputs=None, rid='r', **kw):
    """한 번의 수집 실행: 시작 기록 → 단계들이 파일을 쓴다 → 끝 기록. → 이번 실행이 쓴 {상대경로: 본문}."""
    datadir = repo / 'data'
    datadir.mkdir(exist_ok=True)
    S.begin(str(datadir), now=when, run_id=rid)
    written = us_files(when + dt.timedelta(minutes=1), ran, **kw)
    for rel, raw in written.items():
        p = datadir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(raw, encoding='utf-8')
    steps = {s: {'outcome': 'success' if (s in ran or (s == 'collect' and 'patch' in ran)) else 'skipped',
                 'outputs': {}} for s in ALL + ('telegram',)}
    steps['collect'] = {'outcome': 'success', 'outputs': dict(outputs or {})}
    S.stamp(str(datadir), market='us', now=when + dt.timedelta(minutes=5), steps=steps, run_id=rid)
    return written


@pytest.fixture
def us(tmp_path):
    repo = init(tmp_path)
    us_run(repo, T1, ALL, rid='run-1')
    commit(repo, 'first collection')
    assert changed(repo) == []
    return repo


def test_us_full_rerun_with_the_same_values_changes_only_what_pre_1a_changed(us):
    written = us_run(us, T2, ALL, rid='run-2')
    want = pre_1a_changed(us, 'data', written)
    assert want == ['data/market_data.json']                       # `generated` — 1a 전에도 바뀌던 파일
    # 장부는 market_data.json 의 새 해시를 따라간다(그 커밋에 함께 실린다) — 그 밖의 파일은 그대로
    assert changed(us) == ['data/_collect_status.json', 'data/market_data.json']


def test_us_skipped_run_leaves_nothing_to_commit(us):
    # 이미 끝난 날의 둘째 슬롯: Collect 는 건너뛰고(skipped=true) 유동성만 다시 쓴다 — 값이 같으면 「nothing new」
    written = us_run(us, T2, ('liquidity',), outputs={'skipped': 'true'}, rid='run-2')
    assert pre_1a_changed(us, 'data', written) == []
    assert changed(us) == []


def test_us_waiting_run_leaves_nothing_changed(us):
    # 네이버 종가를 기다리는 실행: 아무 단계도 쓰지 않는다(커밋 단계도 돌지 않는다) — 작업 폴더가 그대로다
    us_run(us, T2, (), outputs={'skipped': 'true', 'waiting': 'true'}, rid='run-2')
    assert changed(us) == []


def test_us_patched_run_changes_market_data_and_the_ledger_only(us):
    written = us_run(us, T2, ('patch', 'liquidity'), outputs={'patched': 'true'}, rid='run-2', yields=4.12)
    assert pre_1a_changed(us, 'data', written) == ['data/market_data.json']
    assert changed(us) == ['data/_collect_status.json', 'data/market_data.json']
    book = C.load_status(str(us / 'data'))
    assert book['run_id'] == 'run-2' and book['files']['market_data.json']['run'] == 'written'
    assert book['files']['econ_indicators.json']['run'] == 'skipped'


def test_a_real_change_is_kept_and_stamped_as_this_run(us):
    written = us_files(T2 + dt.timedelta(minutes=1), ('collect',))
    body = json.loads(written['econ_indicators.json'])
    body['indicators'][0]['actual'] = 0.4                        # 값이 바뀐 재수집
    S.begin(str(us / 'data'), now=T2, run_id='run-2')
    for rel, raw in written.items():
        (us / 'data' / rel).write_text(raw if rel != 'econ_indicators.json' else json.dumps(body), encoding='utf-8')
    steps = {s: {'outcome': 'success' if s == 'collect' else 'skipped', 'outputs': {}} for s in ALL}
    S.stamp(str(us / 'data'), market='us', now=T2 + dt.timedelta(minutes=5), steps=steps, run_id='run-2')
    assert 'data/econ_indicators.json' in changed(us)
    got = json.loads((us / 'data' / 'econ_indicators.json').read_text())
    assert got['indicators'][0]['actual'] == 0.4 and got['collect']['collected_at'] == C.now_iso(T2 + dt.timedelta(minutes=1))
    assert C.load_status(str(us / 'data'))['files']['econ_indicators.json']['run'] == 'written'


def test_a_failed_step_is_not_hidden_by_the_restore(us):
    # 단계는 돌았는데 파일을 다시 쓰지 못했다 — 앞 판 바이트가 남아 있어도 「이번 수집 실패」로 적힌다(되돌리기가 가리지 않는다)
    datadir = us / 'data'
    S.begin(str(datadir), now=T2, run_id='run-2')
    written = us_files(T2 + dt.timedelta(minutes=1), ('collect',))
    written.pop('macro_metrics.json')                             # 그 블록이 예외를 삼켰다
    for rel, raw in written.items():
        (datadir / rel).write_text(raw, encoding='utf-8')
    steps = {s: {'outcome': 'success' if s == 'collect' else 'skipped', 'outputs': {}} for s in ALL}
    S.stamp(str(datadir), market='us', now=T2 + dt.timedelta(minutes=5), steps=steps, run_id='run-2')
    book = C.load_status(str(datadir))
    assert book['files']['macro_metrics.json']['run'] == 'failed' and book['run_id'] == 'run-2'
    assert 'data/_collect_status.json' in changed(us)


def test_first_stamp_and_folders_outside_git_are_untouched(tmp_path):
    # git 밖(로컬 시험·작업 공간)에서는 견줄 앞 판이 없다 — 아무것도 되돌리지 않는다
    datadir = tmp_path / 'data'
    datadir.mkdir()
    for when, rid in ((T1, 'a'), (T2, 'b')):
        S.begin(str(datadir), now=when, run_id=rid)
        for rel, raw in us_files(when + dt.timedelta(minutes=1), ALL).items():
            p = datadir / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(raw, encoding='utf-8')
        steps = {s: {'outcome': 'success', 'outputs': {}} for s in ALL}
        book = S.stamp(str(datadir), market='us', now=when + dt.timedelta(minutes=5), steps=steps, run_id=rid)
    assert book['run_id'] == 'b'
    assert json.loads((datadir / 'econ_indicators.json').read_text())['collect']['collected_at'] == \
        C.now_iso(T2 + dt.timedelta(minutes=1))


# ── KR: 실제 수집기(`collect_kr_data.main`)를 고정 자료로 두 번 ───────────────────────────────

def test_kr_recollection_with_the_same_values_changes_only_what_pre_1a_changed(tmp_path, monkeypatch):
    import collect_kr_data
    from kr.tests import test_collect_missing as K
    repo = init(tmp_path)
    ref, leaks = [K.World()], []
    K.install(monkeypatch, repo, ref, leaks)
    outdir = repo / 'kr' / 'data'
    outdir.mkdir(parents=True)
    clock = [T1]
    monkeypatch.setattr(C, 'now_iso', lambda now=None: (now or clock[0]).astimezone(KST).isoformat(timespec='seconds'))

    def run(when, rid):
        clock[0] = when
        S.begin(str(outdir), now=when, run_id=rid)
        clock[0] = when + dt.timedelta(minutes=1)
        collect_kr_data.main(str(outdir), str(repo / 'kr' / 'assets'))
        # 기대값은 stamp **전**에 읽는다 — stamp 뒤에 읽으면 되돌리기가 지운 변경을 기대값으로 삼는다(codex 3회차 D8)
        out = {os.path.relpath(os.path.join(dp, f), outdir): open(os.path.join(dp, f), encoding='utf-8').read()
               for dp, _dn, fs in os.walk(outdir) for f in fs if f.endswith('.json') and f != '_collect_status.json'}
        steps = {'collect': {'outcome': 'success', 'outputs': {}}, 'telegram': {'outcome': 'skipped', 'outputs': {}}}
        clock[0] = when + dt.timedelta(minutes=5)
        S.stamp(str(outdir), market='kr', steps=steps, run_id=rid)
        return out

    run(T1, 'run-1')
    commit(repo, 'first collection')
    first = C.load_status(str(outdir))
    assert first['run_id'] == 'run-1' and first['files']['kr_market_data.json']['run'] == 'written'
    written = run(T2, 'run-2')
    want = pre_1a_changed(repo, 'kr/data', written)
    got = [p for p in changed(repo) if p.startswith('kr/data/')]
    # 1a 전에 바뀌던 파일만 바뀐다. 그런 파일이 하나라도 있으면 장부가 그 해시를 따라가고, 없으면 장부도 그대로다
    assert got == sorted(want + (['kr/data/_collect_status.json'] if want else []))
    assert not leaks


# ── codex 3회차 D4: 파이썬 == 가 같다고 보는 다른 JSON 값은 되돌리지 않는다 ────────────────────────────────

@pytest.mark.parametrize('before,after', [(1, True), (0, False), (1, 1.0), (0.0, -0.0), ({'a': 1, 'b': 2}, {'b': 2, 'a': 1})])
def test_restore_keeps_a_new_value_that_python_calls_equal(tmp_path, before, after):
    repo = init(tmp_path)
    d = repo / 'data'
    d.mkdir()
    (d / 'x.json').write_text(json.dumps({'v': before, 'collect': {'status': 'ok', 'collected_at': 'T1'}}), encoding='utf-8')
    commit(repo)
    new = json.dumps({'v': after, 'collect': {'status': 'ok', 'collected_at': 'T2'}})
    (d / 'x.json').write_text(new, encoding='utf-8')
    assert S.restore_unchanged(str(d), 'x.json') == 'T2'
    assert (d / 'x.json').read_text(encoding='utf-8') == new          # 새 값이 남는다


def test_restore_still_reverts_a_file_that_differs_only_in_collection_time(tmp_path):
    repo = init(tmp_path)
    d = repo / 'data'
    d.mkdir()
    old = json.dumps({'v': 1, 'collect': {'status': 'ok', 'collected_at': 'T1'}})
    (d / 'x.json').write_text(old, encoding='utf-8')
    commit(repo)
    (d / 'x.json').write_text(json.dumps({'v': 1, 'collect': {'status': 'ok', 'collected_at': 'T2'}}), encoding='utf-8')
    assert S.restore_unchanged(str(d), 'x.json') == 'T2'
    assert (d / 'x.json').read_text(encoding='utf-8') == old
