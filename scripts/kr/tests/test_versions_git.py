"""판 관리 commit·promote 를 가짜 원격(로컬 bare repo)으로 — 동결·그림자·경합·폴백·수동 승격(2026-11-10).

spec: docs/superpowers/specs/2026-11-10-kr-data-versions.md
"""
import json
import os
import shutil
import subprocess
import sys

import pytest

SCRIPTS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
VERSIONS = os.path.join(SCRIPTS, 'common', 'versions.py')
PUSH = os.path.join(SCRIPTS, 'ci', 'push_with_retry.sh')
D = '2026-11-06'
PREV = '2026-11-05'

ENV = {**os.environ, 'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@t', 'GIT_COMMITTER_NAME': 't',
       'GIT_COMMITTER_EMAIL': 't@t', 'PUSH_RETRY_SLEEP': '0'}
# Actions 안에서 돌아도(수집 워크플로가 수집 전에 이 시험을 돈다) 로컬과 같은 조건 — 구현 검토 4회 #1
for _k in ('GITHUB_ACTIONS', 'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT', 'GITHUB_EVENT_NAME', 'RUNNER_TEMP'):
    ENV.pop(_k, None)
ENV.pop('VERSIONS_TEST_FAIL', None)
ENV.pop('VERSIONS_TEST_BEFORE_PUSH', None)


def sh(cwd, *args, check=True, env=None):
    r = subprocess.run(args, cwd=cwd, capture_output=True, env=env or ENV)
    if check and r.returncode != 0:
        raise AssertionError(f'{args}: {r.stderr.decode()}')
    return r


def wj(root, path, obj):
    full = os.path.join(root, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, 'w', encoding='utf-8') as f:
        if path.endswith('.jsonl'):
            f.write(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in obj))
        elif isinstance(obj, str):
            f.write(obj)
        else:
            json.dump(obj, f, ensure_ascii=False, indent=2)


def rj(root, path):
    with open(os.path.join(root, path), encoding='utf-8') as f:
        return [json.loads(l) for l in f if l.strip()] if path.endswith('.jsonl') else json.load(f)


def data(date, ind_it=1.15, kosdaq=644.27, peers_date=None):
    peers_date = peers_date or date
    idx = {'KOSPI': {'close': 5059.69, 'change_pct': -6.02}}
    if kosdaq is not None:
        idx['KOSDAQ'] = {'close': kosdaq, 'change_pct': -5.03}
    return {
        'kr/data/kr_market_data.json': {'report_date': date, 'complete': True, 'missing': [], 'indices': idx},
        'kr/data/kr_industry.json': [{'name': 'IT서비스', 'change_pct': ind_it, 'breadth': 0.2, 'leading': True}],
        'kr/data/kr_top_value.json': [{'label': 'SK하이닉스', 'value': 8730799}],
        'kr/data/kr_flows.json': {m: {'rows': [{'date': date, 'individual': 1, 'foreign': 2, 'institution': 3},
                                              {'date': PREV, 'individual': 4, 'foreign': 5, 'institution': 6}],
                                     'latest_date': date, 'flows_provisional': True} for m in ('KOSPI', 'KOSDAQ')},
        'kr/data/kr_session.json': {'asia_peers': {'rows': {'닛케이': -5.96}, 'dates': {'닛케이': peers_date}}},
        'kr/data/kr_technical.json': {'코스피': {'as_of': date, 'close': 5059.69}},
        'kr/data/kr_stock_moves.json': [{'name': 'SK하이닉스', 'change_pct': -10.44}],
        f'kr/data/news/{date}.json': {'date': date, 'items': [{'title': 'evening'}]},
        'kr/data/kr_sector.html': '<table></table>',
    }


def ledger(kosdaq=644.27):
    row = {'KOSPI': 5059.69}
    if kosdaq is not None:
        row['KOSDAQ'] = kosdaq
    return [{'report_date': '2026-10-30', 'indices': {'KOSPI': 5730.74, 'KOSDAQ': 700.0}},
            {'report_date': PREV, 'indices': {'KOSPI': 5383.0, 'KOSDAQ': 678.0}},
            {'report_date': D, 'indices': row}]


def weekly(ind_it=1.15):
    return {'span': 'weekly', 'key': '2026-W45', 'complete': True, '_sessions': {
        PREV: {'industry': {'IT서비스': 0.5}, 'top_value': {}, 'leading_industries': [], 'flows': {}},
        D: {'industry': {'IT서비스': ind_it}, 'top_value': {'SK하이닉스': 8730799},
            'leading_industries': ['IT서비스'], 'flows': {}}}}


def write_day(root, files, led, wk):
    for p, o in files.items():
        wj(root, p, o)
    wj(root, 'kr/data/history/kr_market.jsonl', led)
    wj(root, 'kr/data/weekly/2026-W45.json', wk)


@pytest.fixture
def world(tmp_path):
    origin = tmp_path / 'origin.git'
    sh(tmp_path, 'git', 'init', '-q', '--bare', '-b', 'main', str(origin))
    seed = tmp_path / 'seed'
    sh(tmp_path, 'git', 'clone', '-q', str(origin), str(seed))
    os.makedirs(seed / 'scripts' / 'ci')
    shutil.copy(PUSH, seed / 'scripts' / 'ci' / 'push_with_retry.sh')
    write_day(seed, data(D), ledger(), weekly())
    sh(seed, 'git', 'add', '-A')
    sh(seed, 'git', 'commit', '-q', '-m', 'data: kr market data for 2026-11-06')
    sh(seed, 'git', 'push', '-q', 'origin', 'HEAD:main')
    return tmp_path, origin, seed


def publish(seed, html='<p>코스피 5,059.69 코스닥 644.27</p>'):
    sh(seed, 'git', 'pull', '-q', '--rebase')
    wj(seed, f'kr/posts/{D}.html', html)
    wj(seed, f'verification/kr/{D}.json', {'inputs': {'files': [], 'incomplete': False}})
    sh(seed, 'git', 'add', '-A')
    sh(seed, 'git', 'commit', '-q', '-m', 'Add KR brief 2026-11-06')
    sh(seed, 'git', 'push', '-q', 'origin', 'HEAD:main')


def clone(tmp, origin, name='runner'):
    c = tmp / name
    sh(tmp, 'git', 'clone', '-q', str(origin), str(c))
    return c


def night(c, kosdaq=644.27):
    """자정 뒤 재수집처럼 — 업종 값이 바뀌고 닛케이 날짜가 전날로 회귀."""
    files = data(D, ind_it=1.11, kosdaq=kosdaq, peers_date=PREV)
    files[f'kr/data/news/{D}.json'] = {'date': D, 'items': [{'title': 'night'}]}
    files['kr/data/kr_technical.json'] = {'코스피': {'as_of': PREV, 'close': 5383.0}}
    led = ledger(kosdaq=kosdaq)
    led[-1]['indices']['KOSPI'] = 5059.69
    write_day(c, files, led, weekly(ind_it=1.11))


def run(c, *args, env=None, scratch=True):
    extra = ('--scratch-checkout',) if args and args[0] == 'commit' and scratch else ()
    return sh(c, sys.executable, VERSIONS, *args, *extra, '--repo', str(c), check=False, env={**ENV, **(env or {})})


def remote(tmp, origin, path):
    v = tmp / 'view'
    if v.exists():
        sh(v, 'git', 'pull', '-q')
    else:
        sh(tmp, 'git', 'clone', '-q', str(origin), str(v))
    return rj(v, path) if os.path.exists(v / path) else None


def manifests(tmp, origin):
    v = tmp / 'view'
    remote(tmp, origin, 'kr/data/kr_market_data.json')
    base = v / 'versions' / 'kr' / D / 'runs'
    return [rj(base / r, 'manifest.json') for r in sorted(os.listdir(base))] if base.exists() else []


def test_enforce_published_day_keeps_published_values(world):
    tmp, origin, seed = world
    publish(seed)
    c = clone(tmp, origin)
    night(c)
    r = run(c, 'commit', '--mode', 'enforce', '--message', 'data: kr market data for 2026-11-06')
    assert r.returncode == 0, r.stderr.decode()
    assert remote(tmp, origin, 'kr/data/kr_industry.json')[0]['change_pct'] == 1.15
    assert remote(tmp, origin, f'kr/data/news/{D}.json')['items'][0]['title'] == 'evening'
    wk = remote(tmp, origin, 'kr/data/weekly/2026-W45.json')
    assert wk['_sessions'][D]['industry']['IT서비스'] == 1.15
    assert wk['_sessions'][PREV]['flows']['KOSPI']['individual'] == 4      # 다음 거래일 관측값은 반영
    m = manifests(tmp, origin)[-1]
    assert m['frozen'] is True and m['published_on_remote'] is True
    assert m['field_status']['asia_peers.닛케이'] in ('unverified_target_date', 'stale_or_holiday')
    assert m['diff_vs_published']['kr/data/kr_industry.json']['class'] == 'changed'
    assert remote(tmp, origin, f'versions/kr/{D}/published/published.json')['source'] == 'publish_commit_tree'


def test_shadow_keeps_todays_bytes_but_records(world):
    tmp, origin, seed = world
    publish(seed)
    c = clone(tmp, origin)
    night(c)
    r = run(c, 'commit', '--mode', 'shadow', '--message', 'data: kr market data for 2026-11-06')
    assert r.returncode == 0, r.stderr.decode()
    assert remote(tmp, origin, 'kr/data/kr_industry.json')[0]['change_pct'] == 1.11   # 오늘과 같다
    m = manifests(tmp, origin)[-1]
    assert m['would_freeze'] is True and m['frozen'] is False


def test_enforce_unpublished_day_applies_like_today(world):
    tmp, origin, seed = world
    c = clone(tmp, origin)
    night(c)
    r = run(c, 'commit', '--mode', 'enforce', '--message', 'data: kr market data for 2026-11-06')
    assert r.returncode == 0, r.stderr.decode()
    assert remote(tmp, origin, 'kr/data/kr_industry.json')[0]['change_pct'] == 1.11


def test_race_publish_lands_before_push_then_freezes(world):
    tmp, origin, seed = world
    c = clone(tmp, origin)
    night(c)
    hook = f'cd {seed} && git pull -q --rebase && mkdir -p kr/posts verification/kr && ' \
           f'echo "<p>644.27</p>" > kr/posts/{D}.html && echo "{{}}" > verification/kr/{D}.json && ' \
           f'git add -A && git commit -q -m pub && git push -q origin HEAD:main'
    r = run(c, 'commit', '--mode', 'enforce', '--message', 'data: kr market data for 2026-11-06',
            env={'VERSIONS_TEST_BEFORE_PUSH': hook})
    assert r.returncode == 0, r.stderr.decode()
    assert remote(tmp, origin, 'kr/data/kr_industry.json')[0]['change_pct'] == 1.15
    assert manifests(tmp, origin)[-1]['frozen'] is True


def test_enforce_published_failure_holds_instead_of_overwriting(world):
    # 사용자 정책: enforce + 발행 완료일 실패 = 무보호 덮어쓰기 금지, 반영 보류
    tmp, origin, seed = world
    publish(seed)
    c = clone(tmp, origin)
    before = sh(c, 'git', 'ls-remote', str(origin), 'main').stdout
    night(c)
    for fail in ('reconcile1',):
        r = run(c, 'commit', '--mode', 'enforce', '--message', 'm', env={'VERSIONS_TEST_FAIL': fail})
        assert r.returncode == 0, r.stderr.decode()
        assert b'::warning::versions hold' in r.stdout
    assert sh(c, 'git', 'ls-remote', str(origin), 'main').stdout == before       # 원격 무변경
    assert remote(tmp, origin, 'kr/data/kr_industry.json')[0]['change_pct'] == 1.15


def test_enforce_unpublished_failure_uses_guarded_fallback(world):
    tmp, origin, seed = world
    c = clone(tmp, origin)
    night(c)
    r = run(c, 'commit', '--mode', 'enforce', '--message', 'm', env={'VERSIONS_TEST_FAIL': 'reconcile1'})
    assert r.returncode == 0, r.stderr.decode()
    assert b'fallback(enforce' in r.stdout
    assert remote(tmp, origin, 'kr/data/kr_industry.json')[0]['change_pct'] == 1.11   # 미발행일 — 오늘처럼


def test_enforce_failure_after_publish_landed_holds(world):
    # checkout 때는 미발행, 그 사이 발행 → fetch 로 확인한 뒤 실패 = 보류(덮지 않는다)
    tmp, origin, seed = world
    c = clone(tmp, origin)
    night(c)
    publish(seed)
    before = sh(c, 'git', 'ls-remote', str(origin), 'main').stdout
    r = run(c, 'commit', '--mode', 'enforce', '--message', 'm', env={'VERSIONS_TEST_FAIL': 'reconcile1'})
    assert r.returncode == 0 and b'versions hold' in r.stdout
    assert sh(c, 'git', 'ls-remote', str(origin), 'main').stdout == before


def test_enforce_first_fetch_fails_then_guarded_fallback_rechecks(world):
    # 첫 fetch 만 일시 실패 — 미발행일이면 보호 폴백이 다시 fetch 해 오늘처럼 반영(구현 검토 3회 #20)
    tmp, origin, seed = world
    c = clone(tmp, origin)
    night(c)
    r = run(c, 'commit', '--mode', 'enforce', '--message', 'm', env={'VERSIONS_TEST_FAIL': 'fetch1'})
    assert r.returncode == 0, r.stderr.decode()
    assert remote(tmp, origin, 'kr/data/kr_industry.json')[0]['change_pct'] == 1.11


def test_enforce_fetch_never_works_and_checkout_unpublished_holds(world):
    tmp, origin, seed = world
    c = clone(tmp, origin)
    night(c)
    sh(c, 'git', 'remote', 'set-url', 'origin', str(tmp / 'nowhere.git'))
    r = run(c, 'commit', '--mode', 'enforce', '--message', 'm')
    assert r.returncode == 0 and b'versions hold' in r.stdout


def test_enforce_published_without_publish_commit_holds(world):
    # 발행 글은 있는데 발행 커밋을 못 찾는 경우(이력 이상) — 덮지 않고 보류(#18)
    tmp, origin, seed = world
    publish(seed)
    c = clone(tmp, origin)
    night(c)
    before = sh(c, 'git', 'ls-remote', str(origin), 'main').stdout
    r = run(c, 'commit', '--mode', 'enforce', '--message', 'm',
            env={'VERSIONS_TEST_FAIL': 'no_publish_commit'})
    assert r.returncode == 0 and b'versions hold' in r.stdout
    assert sh(c, 'git', 'ls-remote', str(origin), 'main').stdout == before


def test_guarded_fallback_holds_from_ledger_even_without_missing_marker(world):
    # 주간 파일에 빈 칸 표식이 없어도 원장으로 계산해 보류(구현 검토 4회 #3)
    tmp, origin, seed = world
    sh(seed, 'git', 'pull', '-q', '--rebase')
    wj(seed, f'kr/posts/{PREV}.html', '<p>x</p>')
    led = ledger()
    led[1]['indices'].pop('KOSDAQ')
    wj(seed, 'kr/data/history/kr_market.jsonl', led)
    sh(seed, 'git', 'add', '-A')
    sh(seed, 'git', 'commit', '-q', '-m', 'prev published with gap')
    sh(seed, 'git', 'push', '-q', 'origin', 'HEAD:main')
    c = clone(tmp, origin)
    night(c)
    led2 = ledger()
    led2[1]['indices'].pop('KOSDAQ')
    wj(c, 'kr/data/history/kr_market.jsonl', led2)
    wk = rj(c, 'kr/data/weekly/2026-W45.json')
    wk['complete'] = True
    wk['missing'] = []
    wj(c, 'kr/data/weekly/2026-W45.json', wk)
    r = run(c, 'commit', '--mode', 'enforce', '--message', 'm', env={'VERSIONS_TEST_FAIL': 'reconcile1'})
    assert r.returncode == 0, r.stderr.decode()
    assert remote(tmp, origin, 'kr/data/weekly/2026-W45.json')['complete'] is False


def test_guarded_fallback_internal_failure_fails_without_unprotected_push(world):
    # enforce 의 보호 폴백 자신이 실패하면 무보호 스크립트로 내려가지 않는다(구현 검토 5회 #1·#2)
    tmp, origin, seed = world
    c = clone(tmp, origin)
    night(c)
    before = sh(c, 'git', 'ls-remote', str(origin), 'main').stdout
    r = run(c, 'commit', '--mode', 'enforce', '--message', 'm',
            env={'VERSIONS_TEST_FAIL': 'reconcile1,guarded_worktree'})
    assert r.returncode == 1 and '무보호 push 를 하지 않는다' in r.stderr.decode()
    assert sh(c, 'git', 'ls-remote', str(origin), 'main').stdout == before


def test_guarded_fallback_keeps_published_gap_hold(world):
    # 발행된 이전 날의 지수 빈 칸 → 폴백으로 올려도 주간 보류는 유지(#19)
    tmp, origin, seed = world
    sh(seed, 'git', 'pull', '-q', '--rebase')
    wj(seed, f'kr/posts/{PREV}.html', '<p>x</p>')
    led = ledger()
    led[1]['indices'].pop('KOSDAQ')                                       # PREV 의 코스닥 빈 칸
    wj(seed, 'kr/data/history/kr_market.jsonl', led)
    sh(seed, 'git', 'add', '-A')
    sh(seed, 'git', 'commit', '-q', '-m', 'prev published with gap')
    sh(seed, 'git', 'push', '-q', 'origin', 'HEAD:main')
    c = clone(tmp, origin)
    night(c)
    wk = rj(c, 'kr/data/weekly/2026-W45.json')
    wk['complete'] = True
    wk['missing'] = [f'indices.KOSDAQ.{PREV}']
    wj(c, 'kr/data/weekly/2026-W45.json', wk)
    r = run(c, 'commit', '--mode', 'enforce', '--message', 'm', env={'VERSIONS_TEST_FAIL': 'reconcile1'})
    assert r.returncode == 0, r.stderr.decode()
    assert remote(tmp, origin, 'kr/data/weekly/2026-W45.json')['complete'] is False


def test_commit_refused_outside_actions_without_scratch_flag(world):
    tmp, origin, seed = world
    c = clone(tmp, origin)
    night(c)
    r = run(c, 'commit', '--mode', 'shadow', '--message', 'm', scratch=False)
    assert r.returncode == 2 and b'scratch-checkout' in r.stderr


def test_enforce_published_known_from_checkout_even_if_fetch_fails(world):
    tmp, origin, seed = world
    publish(seed)
    c = clone(tmp, origin)
    night(c)
    sh(c, 'git', 'remote', 'set-url', 'origin', str(tmp / 'nowhere.git'))      # fetch 실패
    r = run(c, 'commit', '--mode', 'enforce', '--message', 'm')
    assert r.returncode == 0 and b'versions hold' in r.stdout


def test_shadow_failure_falls_back_to_todays_path_with_warning(world):
    tmp, origin, seed = world
    publish(seed)
    c = clone(tmp, origin)
    night(c)
    r = run(c, 'commit', '--mode', 'shadow', '--message', 'data: kr market data for 2026-11-06',
            env={'VERSIONS_TEST_FAIL': 'reconcile1'})
    assert r.returncode == 0, r.stderr.decode()
    assert b'::warning::versions fallback' in r.stdout
    assert remote(tmp, origin, 'kr/data/kr_industry.json')[0]['change_pct'] == 1.11   # 오늘 경로 그대로
    v = tmp / 'view' / 'versions' / 'kr' / D / 'fallback'
    recs = os.listdir(v)
    assert len(recs) == 1 and rj(v, recs[0])['protection'] == 'disabled'
    assert not (tmp / 'view' / 'versions' / 'kr' / D / 'runs').exists()   # 동결 성공으로 세지 않는다


def test_fallback_record_failure_still_pushes(world):
    tmp, origin, seed = world
    c = clone(tmp, origin)
    night(c)
    r = run(c, 'commit', '--mode', 'shadow', '--message', 'm',
            env={'VERSIONS_TEST_FAIL': 'reconcile1,fallback_record'})
    assert r.returncode == 0, r.stderr.decode()
    assert b'\xed\x8f\xb4\xeb\xb0\xb1 \xea\xb8\xb0\xeb\xa1\x9d \xec\x8b\xa4\xed\x8c\xa8' in r.stderr   # 「폴백 기록 실패」
    assert remote(tmp, origin, 'kr/data/kr_industry.json')[0]['change_pct'] == 1.11      # 그래도 올라갔다
    assert not (tmp / 'view' / 'versions').exists()


def test_local_uncommitted_change_outside_stage_survives(world):
    tmp, origin, seed = world
    publish(seed)
    c = clone(tmp, origin)
    night(c)
    wj(c, 'scripts/ci/push_with_retry.sh', open(PUSH).read() + '\n# local edit\n')
    wj(c, 'notes.txt', 'untracked')
    r = run(c, 'commit', '--mode', 'enforce', '--message', 'm')
    assert r.returncode == 0, r.stderr.decode()
    assert open(c / 'scripts/ci/push_with_retry.sh').read().endswith('# local edit\n')
    assert (c / 'notes.txt').exists()


def test_dated_file_absent_at_publish_is_removed_when_frozen(world):
    tmp, origin, seed = world
    publish(seed)
    # 발행 뒤 다른 실행이 동결 전에 intraday 차트를 원격에 올렸다고 하자
    sh(seed, 'git', 'pull', '-q', '--rebase')
    wj(seed, f'kr/assets/kr_flows_intraday_{D}.png', 'PNGBYTES')
    sh(seed, 'git', 'add', '-A')
    sh(seed, 'git', 'commit', '-q', '-m', 'late chart')
    sh(seed, 'git', 'push', '-q', 'origin', 'HEAD:main')
    c = clone(tmp, origin)
    night(c)
    wj(c, f'kr/assets/kr_flows_intraday_{D}.png', 'OTHERBYTES')
    assert run(c, 'commit', '--mode', 'enforce', '--message', 'm').returncode == 0
    v = tmp / 'view'
    remote(tmp, origin, 'kr/data/kr_market_data.json')
    assert not (v / f'kr/assets/kr_flows_intraday_{D}.png').exists()        # 발행 커밋에 없었다
    m = manifests(tmp, origin)[-1]
    assert m['stored'][f'kr/assets/kr_flows_intraday_{D}.png'] == 'copied'    # 원본 바이트는 남는다
    run_dir = v / 'versions' / 'kr' / D / 'runs' / m['run_id'] / 'files'
    assert (run_dir / f'kr/assets/kr_flows_intraday_{D}.png').read_text() == 'OTHERBYTES'


def test_shadow_ignores_promotions(world):
    tmp, origin, seed = world
    publish(seed)
    sh(seed, 'git', 'pull', '-q', '--rebase')
    wj(seed, f'versions/kr/{D}/promotions/001.json', {'field': 'ledger.indices.KOSDAQ', 'value': 1.0})
    sh(seed, 'git', 'add', '-A')
    sh(seed, 'git', 'commit', '-q', '-m', 'promo')
    sh(seed, 'git', 'push', '-q', 'origin', 'HEAD:main')
    c = clone(tmp, origin)
    night(c)
    assert run(c, 'commit', '--mode', 'shadow', '--message', 'm').returncode == 0
    led = remote(tmp, origin, 'kr/data/history/kr_market.jsonl')
    assert [r for r in led if r['report_date'] == D][0]['indices']['KOSDAQ'] == 644.27   # 오늘과 같은 바이트


def test_promote_refused_inside_actions(world):
    tmp, origin, seed = world
    publish(seed)
    p = clone(tmp, origin, 'promoter')
    r = run(p, 'promote', '--date', D, '--field', 'ledger.indices.KOSDAQ', '--value', '644.27', '--reason', 'x',
            env={'GITHUB_ACTIONS': 'true'})
    assert r.returncode == 4


def test_no_change_no_push(world):
    tmp, origin, seed = world
    publish(seed)
    c = clone(tmp, origin)
    head = sh(c, 'git', 'rev-parse', 'HEAD').stdout
    r = run(c, 'commit', '--mode', 'enforce', '--message', 'm', env={'VERSIONS_TEST_FAIL': 'reconcile1'})
    assert r.returncode == 0
    assert sh(c, 'git', 'ls-remote', str(origin), 'main').stdout.split()[0] == head.strip()


def test_scenario2_and_3_missing_index_then_promote(world):
    tmp, origin, seed = world
    # 발행본부터 코스닥이 없다(데이터·원장·글 모두)
    sh(seed, 'git', 'pull', '-q', '--rebase')
    f = data(D, kosdaq=None)
    write_day(seed, f, ledger(kosdaq=None), weekly())
    sh(seed, 'git', 'add', '-A')
    sh(seed, 'git', 'commit', '-q', '-m', 'data: missing kosdaq')
    sh(seed, 'git', 'push', '-q', 'origin', 'HEAD:main')
    publish(seed, html='<p>코스피 5,059.69</p>')
    c = clone(tmp, origin)
    night(c)                                    # 새벽 재수집은 코스닥을 갖고 있다
    assert run(c, 'commit', '--mode', 'enforce', '--message', 'data: kr market data for 2026-11-06').returncode == 0
    wk = remote(tmp, origin, 'kr/data/weekly/2026-W45.json')
    led = remote(tmp, origin, 'kr/data/history/kr_market.jsonl')
    assert 'KOSDAQ' not in [r for r in led if r['report_date'] == D][0]['indices']   # 자동 보완 없음
    assert wk['complete'] is False and f'indices.KOSDAQ.{D}' in wk['missing']        # 주간 보류
    run_id = manifests(tmp, origin)[-1]['run_id']
    # 글이 그 수치를 싣지 않았으면 승격 거부 — 글 정정이 먼저
    p = clone(tmp, origin, 'promoter')
    r = run(p, 'promote', '--date', D, '--field', 'ledger.indices.KOSDAQ', '--from', run_id, '--reason', '원자료 확인')
    assert r.returncode == 3 and '글 정정이 먼저' in r.stderr.decode()
    # 글을 정정한 뒤 승격 → 원장·주간 재계산
    sh(seed, 'git', 'pull', '-q', '--rebase')
    wj(seed, f'kr/posts/{D}.html', '<p>코스피 5,059.69 코스닥 644.27</p>')
    sh(seed, 'git', 'commit', '-qam', 'fix(kr): 코스닥 정정')
    sh(seed, 'git', 'push', '-q', 'origin', 'HEAD:main')
    r = run(p, 'promote', '--date', D, '--field', 'ledger.indices.KOSDAQ', '--from', run_id, '--reason', '원자료 확인')
    assert r.returncode == 0, r.stderr.decode()
    v = tmp / 'view'
    remote(tmp, origin, 'kr/data/kr_market_data.json')
    prec = rj(v / 'versions' / 'kr' / D / 'promotions', '001.json')
    assert prec['source_manifest_sha256'] and prec['post_sha256_at_promotion'] and prec['source_files_sha256']
    led = remote(tmp, origin, 'kr/data/history/kr_market.jsonl')
    assert [r for r in led if r['report_date'] == D][0]['indices']['KOSDAQ'] == 644.27
    assert remote(tmp, origin, 'kr/data/weekly/2026-W45.json')['complete'] is True
    # 같은 날 재수집이 또 와도 승격값이 유지된다
    c2 = clone(tmp, origin, 'runner2')
    night(c2, kosdaq=None)
    assert run(c2, 'commit', '--mode', 'enforce', '--message', 'data: kr market data for 2026-11-06').returncode == 0
    led = remote(tmp, origin, 'kr/data/history/kr_market.jsonl')
    assert [r for r in led if r['report_date'] == D][0]['indices']['KOSDAQ'] == 644.27
    assert remote(tmp, origin, 'kr/data/weekly/2026-W45.json')['complete'] is True


def test_verify_published_reports_record_none_and_ok(world):
    tmp, origin, seed = world
    publish(seed)
    c = clone(tmp, origin)
    night(c)
    assert run(c, 'commit', '--mode', 'shadow', '--message', 'm').returncode == 0
    v = tmp / 'view'
    remote(tmp, origin, 'kr/data/kr_market_data.json')
    r = run(v, 'verify-published', '--date', D)
    assert r.returncode == 0 and r.stdout.decode().startswith(('ok', 'record_none', 'partial_record'))


def test_concurrent_unrelated_push_is_kept(world):
    # 판정 뒤 push 전에 다른 작업이 원격에 다른 파일을 올리면 거절 → 원격에서 다시 세워 둘 다 남는다
    tmp, origin, seed = world
    c = clone(tmp, origin)
    night(c)
    hook = f'cd {seed} && git pull -q --rebase && mkdir -p data && echo "{{}}" > data/other.json && ' \
           f'git add -A && git commit -q -m other && git push -q origin HEAD:main'
    for mode in ('shadow',):
        r = run(c, 'commit', '--mode', mode, '--message', 'm', env={'VERSIONS_TEST_BEFORE_PUSH': hook})
        assert r.returncode == 0, r.stderr.decode()
    assert remote(tmp, origin, 'data/other.json') == {}
    assert remote(tmp, origin, 'kr/data/kr_industry.json')[0]['change_pct'] == 1.11
    assert manifests(tmp, origin)


def test_commit_runs_in_actions_without_scratch_flag(world, tmp_path):
    tmp, origin, seed = world
    c = clone(tmp, origin)
    night(c)
    r = run(c, 'commit', '--mode', 'shadow', '--message', 'm', scratch=False,
            env={'GITHUB_ACTIONS': 'true', 'GITHUB_RUN_ID': '7', 'GITHUB_RUN_ATTEMPT': '1',
                 'RUNNER_TEMP': str(tmp_path / 'rt')})
    assert r.returncode == 0, r.stderr.decode()
    assert (tmp_path / 'rt' / 'versions' / 'kr' / D / 'runs').exists()        # artifact 원본
    assert manifests(tmp, origin)[-1]['run_id'].endswith('-gh7.1')
