"""일본 일간 실행 격리와 발행 경로 — 입력 고정, gates.json, 발행기, manifest, verify-head (설계 20판 §6, §11-9·§11-10).
git 동작은 전부 임시 저장소 + 가짜 origin 에서 돈다. 게이트 명령은 시험에서 갈아 끼운다(일간 게이트 본체는 1부 몫)."""
import hashlib
import json
import subprocess
import sys

import pytest

import jp_daily_gates as JG
import publish_japan_daily as PUB
from japan.tests import jpd_git as G
from japan.tests.jpd_git import S

P = '2026-11-17'
CAND = f'japan/data/daily/candidate/{S}.json'
NEWS = f'japan/data/news/daily/{S}.json'
TGF = f'japan/data/telegram/{S}.json'
POST = f'japan/daily/{S}.html'
SNAPF = f'japan/data/daily/{S}.json'
RUNS = f'japan/data/daily/runs/{S}.json'
PIN = f'japan/data/telegram/published/{S}.json'


def sha(b):
    return hashlib.sha256(b).hexdigest()


def cand(**kw):
    d = {'schema': 2, 'session': S, 'prev_session': P, 'complete': True, 'jgb_recollect': False,
         'indices': {'nikkei': {'value': 49000.5, 'ok': True}},
         'stocks': [{'code': '7203', 'value': 3117.0, 'ok': True}],
         'facts': [{'field_id': 'topix.close', 'value': '3824.00', 'status': 'current'}]}
    d.update(kw)
    return json.dumps(d, ensure_ascii=False, indent=1) + '\n'


def tgdata(usable=True):
    return json.dumps({'report_date': S, 'market': 'jp', 'usable': usable,
                       'items': [{'id': 'ch/1', 'summary_ko': '요약'}]}, ensure_ascii=False) + '\n'


def page(title='일본 증시 마감 — 11월 18일', summary='TOPIX & 닛케이 "엇갈림" <요약>', body='<p>본문 3,824.00</p>'):
    from scripts.common import post_shell as SH
    return (f'<!DOCTYPE html>\n<html lang="ko">\n<head>\n<title>{SH.escape(title)}</title>\n'
            f'<meta name="description" content="{SH.escape(summary)}">\n</head>\n<body>{body}</body>\n</html>\n')


OK = [sys.executable, '-c', 'import sys; sys.exit(0)']
FAIL = [sys.executable, '-c', 'import sys; print("위반: TOPIX 금지 글자", file=sys.stderr); sys.exit(1)']


def stub(*codes):
    names = ['apply_readability', 'check_japan_daily', 'check_news', 'check_readability', 'check_style']
    return lambda run_dir, session, html: [(n, c) for n, c in zip(names, codes)]


ALL_OK = stub(OK, OK, OK, OK, OK)


@pytest.fixture
def repo(tmp_path):
    files = {CAND: cand(), NEWS: '{"items": []}\n', TGF: tgdata(True)}
    remote, seed, clone = G.setup(tmp_path, files=files)
    return remote, seed, clone


def run_dir(clone, n='1'):
    return clone / '_workspace' / 'jpd' / f'jpd-{S}-1763460000-{n}'


def pinned(clone, n='1'):
    d = run_dir(clone, n)
    JG.pin(str(clone), str(d), S)
    return d


def gated(clone, html=None, commands=ALL_OK, n='1'):
    d = pinned(clone, n)
    (d / f'jpd_{S}.html').write_text(html or page(), encoding='utf-8')
    ok, _ = JG.run_gates(str(d), S, commands=commands)
    return d, ok


def publish(clone, d, run_id=None):
    return PUB.main(['--root', str(clone), '--run-dir', str(d), '--run-id', run_id or d.name])


def changes(clone):
    return G.status(clone)


# ── 입력 고정(§6-4) ──────────────────────────────────────────────────────

def test_pin_takes_inputs_from_head_not_the_working_tree(repo):
    _, _, clone = repo
    G.write(clone, CAND, cand(indices={'nikkei': {'value': 1.0}}))          # 로컬에서 고친 후보
    (clone / TGF).unlink()
    d = pinned(clone)
    assert (d / 'root' / CAND).read_text(encoding='utf-8') == cand()
    assert (d / 'root' / TGF).read_text(encoding='utf-8') == tgdata(True)
    rec = json.loads((d / 'inputs.json').read_text())
    assert rec['input_commit'] == G.head(clone) and rec['files'][CAND] == sha(cand().encode())


def test_absent_input_in_head_is_absent(tmp_path):
    _, _, clone = G.setup(tmp_path, files={CAND: cand()})
    d = pinned(clone)
    rec = json.loads((d / 'inputs.json').read_text())
    assert rec['files'][NEWS] is None and not (d / 'root' / NEWS).exists()


def test_pin_refuses_an_existing_run_folder(repo):
    _, _, clone = repo
    pinned(clone)
    with pytest.raises(JG.GateError):
        pinned(clone)


def test_pin_refuses_a_folder_not_named_for_the_session(repo):
    _, _, clone = repo
    with pytest.raises(JG.GateError):
        JG.pin(str(clone), str(clone / '_workspace' / 'jpd' / 'jpd-2026-11-17-1-2'), S)


# ── gates.json(§6-4-1) ───────────────────────────────────────────────────

def test_all_gates_pass_writes_the_record(repo):
    _, _, clone = repo
    d, ok = gated(clone)
    assert ok
    g = json.loads((d / 'gates.json').read_text(encoding='utf-8'))
    assert g['run_id'] == d.name and g['session'] == S and g['verdict'] == 'pass'
    assert g['html_sha256'] == sha((d / f'jpd_{S}.html').read_bytes())
    assert g['snapshot_sha256'] == sha(cand().encode()) and g['news_sha256'] == sha(b'{"items": []}\n')
    assert g['telegram_sha256'] == sha(tgdata(True).encode())
    assert g['title'] == '일본 증시 마감 — 11월 18일' and g['summary'] == 'TOPIX & 닛케이 "엇갈림" <요약>'
    assert [x['name'] for x in g['gates']] == ['apply_readability', 'check_japan_daily', 'check_news',
                                               'check_readability', 'check_style']
    assert all(x['exit'] == 0 for x in g['gates']) and g['finished_at']


def test_a_failing_gate_writes_no_record_and_removes_an_old_one(repo, capsys):
    _, _, clone = repo
    d, ok = gated(clone)
    assert ok and (d / 'gates.json').exists()
    ok, log = JG.run_gates(str(d), S, commands=stub(OK, OK, FAIL, OK, OK))
    assert not ok and not (d / 'gates.json').exists()
    assert 'TOPIX 금지 글자' in log and 'check_news' in log


def test_unusable_views_file_gets_no_hash(tmp_path):
    _, _, clone = G.setup(tmp_path, files={CAND: cand(), TGF: tgdata(False)})
    d, ok = gated(clone)
    g = json.loads((d / 'gates.json').read_text())
    assert ok and g['telegram_sha256'] is None and g['news_sha256'] is None


def test_broken_views_file_gets_no_hash(tmp_path):
    _, _, clone = G.setup(tmp_path, files={CAND: cand(), TGF: '{"items": ['})
    d, ok = gated(clone)
    assert ok and json.loads((d / 'gates.json').read_text())['telegram_sha256'] is None


def test_input_changed_after_pinning_fails(repo):
    _, _, clone = repo
    d = pinned(clone)
    (d / f'jpd_{S}.html').write_text(page(), encoding='utf-8')
    (d / 'root' / CAND).write_text(cand(indices={'nikkei': {'value': 2.0}}), encoding='utf-8')
    ok, log = JG.run_gates(str(d), S, commands=ALL_OK)
    assert not ok and not (d / 'gates.json').exists() and CAND in log


def test_html_changed_while_gates_ran_fails(repo):
    _, _, clone = repo
    d = pinned(clone)
    h = d / f'jpd_{S}.html'
    h.write_text(page(), encoding='utf-8')
    touch = [sys.executable, '-c', f'open({str(h)!r}, "a").write("x")']
    ok, log = JG.run_gates(str(d), S, commands=stub(OK, OK, touch, OK, OK))
    assert not ok and not (d / 'gates.json').exists()


def test_typography_runs_before_the_hash(repo):
    _, _, clone = repo
    d = pinned(clone)
    h = d / f'jpd_{S}.html'
    h.write_text(page(), encoding='utf-8')
    typo = [sys.executable, '-c', f'p={str(h)!r}; t=open(p).read(); open(p, "w").write(t.replace("본문", "본문 "))']
    ok, _ = JG.run_gates(str(d), S, commands=stub(typo, OK, OK, OK, OK))
    assert ok and json.loads((d / 'gates.json').read_text())['html_sha256'] == sha(h.read_bytes())


def test_missing_title_fails(repo):
    _, _, clone = repo
    d, ok = gated(clone, html='<html><head></head><body></body></html>')
    assert not ok and not (d / 'gates.json').exists()


def test_default_commands_point_the_gates_at_the_pinned_copy(repo):
    _, _, clone = repo
    d = pinned(clone)
    cmds = dict(JG.gate_commands(str(d), S, str(d / f'jpd_{S}.html')))
    assert list(cmds) == ['apply_readability', 'check_japan_daily', 'check_news', 'check_readability', 'check_style']
    root = str(d / 'root')
    assert cmds['check_japan_daily'][-4:] == ['--root', root, '--html', str(d / f'jpd_{S}.html')]
    assert ['--datadir', str(d / 'root' / 'japan' / 'data')] == cmds['check_news'][4:6]
    assert '--strict' in cmds['check_readability']


def test_real_gates_pass_on_a_clean_old_schema_page(tmp_path):
    """실제 다섯 게이트를 한 번 — 인자 꼴이 맞는지(옛 스냅샷 SNAP + 정상 본문)."""
    from japan.tests.test_daily_render import SNAP
    from japan.tests.test_daily_views import page as vpage, DATA
    s = SNAP['session']
    files = {f'japan/data/daily/candidate/{s}.json': json.dumps(SNAP, ensure_ascii=False),
             f'japan/data/telegram/{s}.json': json.dumps(DATA, ensure_ascii=False)}
    _, _, clone = G.setup(tmp_path, files=files)
    d = clone / '_workspace' / 'jpd' / f'jpd-{s}-1-1'
    JG.pin(str(clone), str(d), s)
    (d / f'jpd_{s}.html').write_text(vpage(), encoding='utf-8')
    ok, log = JG.run_gates(str(d), s)
    assert ok, log
    assert json.loads((d / 'gates.json').read_text())['telegram_sha256']


# ── 발행기는 완료된 검증에만 묶인다(§6-5) ─────────────────────────────────

def test_publish_writes_the_verified_bytes_and_the_manifest(repo):
    _, _, clone = repo
    d, _ = gated(clone)
    assert publish(clone, d) == 0
    assert (clone / POST).read_bytes() == (d / f'jpd_{S}.html').read_bytes()
    snap = json.loads((clone / SNAPF).read_text(encoding='utf-8'))
    assert snap['published'] and {k: v for k, v in snap.items() if k != 'published'} == json.loads(cand())
    runs = json.loads((clone / RUNS).read_text(encoding='utf-8'))
    assert runs['run_id'] == d.name and runs['published_at'] and runs['verdict'] == 'pass'
    assert (clone / PIN).read_bytes() == tgdata(True).encode()
    listing = json.loads((clone / 'japan' / 'daily.json').read_text(encoding='utf-8'))
    assert listing == [{'date': S, 'title': '일본 증시 마감 — 11월 18일', 'headline': 'TOPIX & 닛케이 "엇갈림" <요약>'}]
    man = (d / 'manifest.txt').read_text().split()
    assert sorted(man) == sorted([POST, SNAPF, RUNS, PIN, 'japan/data/history/jp_daily.jsonl',
                                  'japan/daily.json', 'sitemap.xml'])
    pub = json.loads((d / 'publish.json').read_text())
    assert pub['published_snapshot_sha256'] == sha((clone / SNAPF).read_bytes())
    assert pub['runs_sha256'] == sha((clone / RUNS).read_bytes()) and pub['telegram_pin_sha256'] == sha(tgdata().encode())
    hist = [json.loads(x) for x in (clone / 'japan/data/history/jp_daily.jsonl').read_text().splitlines()]
    assert hist == [{'session': S, 'nikkei': 49000.5, 'prices': {'7203': 3117.0}}]


def test_unusable_views_day_pins_nothing(tmp_path):
    _, _, clone = G.setup(tmp_path, files={CAND: cand(), TGF: tgdata(False)})
    d, _ = gated(clone)
    assert publish(clone, d) == 0
    assert not (clone / PIN).exists() and PIN not in (d / 'manifest.txt').read_text()
    assert json.loads((d / 'publish.json').read_text())['telegram_pin_sha256'] is None


def _assert_nothing_written(clone):
    assert changes(clone) == ''


def test_failed_gates_means_exit_4_and_nothing_written(repo):
    """§11-9: 넷째 판도 게이트 위반 → gates.json 없음 → 발행기 exit 4, japan/ 아래 변경 0."""
    _, _, clone = repo
    d, ok = gated(clone, commands=stub(OK, FAIL, OK, OK, OK))
    assert not ok
    assert publish(clone, d) == 4
    _assert_nothing_written(clone)


def test_record_of_another_run_is_exit_4(repo):
    _, _, clone = repo
    d1, _ = gated(clone, n='1')
    d2 = pinned(clone, n='2')
    (d2 / f'jpd_{S}.html').write_text(page(), encoding='utf-8')
    (d2 / 'gates.json').write_bytes((d1 / 'gates.json').read_bytes())     # 남의 검증 기록
    assert publish(clone, d2) == 4
    assert publish(clone, d1, run_id=d2.name) == 4
    _assert_nothing_written(clone)


@pytest.mark.parametrize('what', ['html', 'candidate', 'news', 'telegram', 'title'])
def test_bytes_changed_after_verification_is_exit_4(repo, what):
    _, _, clone = repo
    d, _ = gated(clone)
    if what == 'html':
        p = d / f'jpd_{S}.html'
        p.write_bytes(p.read_bytes().replace(b'3,824.00', b'3,825.00'))
    elif what == 'candidate':
        (d / 'root' / CAND).write_text(cand(indices={'nikkei': {'value': 3.0}}), encoding='utf-8')
    elif what == 'news':
        (d / 'root' / NEWS).unlink()
    elif what == 'telegram':
        (d / 'root' / TGF).write_text(tgdata(True).replace('요약', '바뀐 요약'), encoding='utf-8')
    else:
        g = json.loads((d / 'gates.json').read_text())
        g['title'] = '검증 밖 제목'
        (d / 'gates.json').write_text(json.dumps(g, ensure_ascii=False))
    assert publish(clone, d) == 4
    _assert_nothing_written(clone)


def test_candidate_recollected_in_the_repo_after_gates_uses_the_pinned_copy(repo):
    _, _, clone = repo
    d, _ = gated(clone)
    G.write(clone, CAND, cand(indices={'nikkei': {'value': 9.9}}))
    assert publish(clone, d) == 0
    snap = json.loads((clone / SNAPF).read_text())
    assert snap['indices']['nikkei']['value'] == 49000.5


def test_old_schema_candidate_is_exit_2(tmp_path):
    _, _, clone = G.setup(tmp_path, files={CAND: cand(schema=None)})
    d, _ = gated(clone)
    assert publish(clone, d) == 2
    _assert_nothing_written(clone)


def test_already_published_is_exit_2(repo):
    _, seed, clone = repo
    d, _ = gated(clone)
    G.write(clone, SNAPF, '{}')
    assert publish(clone, d) == 2


def test_publisher_takes_no_title_or_headline():
    with pytest.raises(SystemExit):
        PUB.main(['--run-dir', 'x', '--run-id', 'x', '--title', 't'])
    with pytest.raises(SystemExit):
        PUB.main(['--session', S, '--title', 't'])                      # 옛 꼴 — 검증 없는 발행 경로는 없다


# ── manifest 스테이징(§6-7) ──────────────────────────────────────────────

def _stage(clone, d):
    man = (d / 'manifest.txt').read_text().split()
    G.git(clone, 'add', '--', *man)


def check_staged(clone, d):
    return PUB.main(['check-staged', '--root', str(clone), '--run-dir', str(d)])


def test_staged_set_equal_to_manifest_passes(repo):
    _, _, clone = repo
    d, _ = gated(clone)
    publish(clone, d)
    _stage(clone, d)
    assert check_staged(clone, d) == 0


def test_a_file_outside_the_manifest_staged_is_refused(repo):
    _, _, clone = repo
    d, _ = gated(clone)
    publish(clone, d)
    _stage(clone, d)
    G.write(clone, 'scripts/x.py', 'x = 3\n')
    G.git(clone, 'add', 'scripts/x.py')
    assert check_staged(clone, d) == 4


def test_a_manifest_file_left_unstaged_is_refused(repo):
    _, _, clone = repo
    d, _ = gated(clone)
    publish(clone, d)
    _stage(clone, d)
    G.git(clone, 'reset', '-q', '--', PIN)
    assert check_staged(clone, d) == 4


# ── verify-head(§6-7-1) ──────────────────────────────────────────────────

def committed(clone, d):
    publish(clone, d)
    _stage(clone, d)
    assert check_staged(clone, d) == 0
    G.git(clone, 'commit', '-q', '-m', f'Add JP daily [{S}]')


def verify_head(clone, d):
    return PUB.main(['verify-head', '--root', str(clone), '--run-dir', str(d)])


def test_normal_run_commit_files_equal_manifest_and_verify_head_passes(repo):
    remote, _, clone = repo
    d, _ = gated(clone)
    committed(clone, d)
    files = G.git(clone, 'show', '--name-only', '--format=', 'HEAD').stdout.split()
    assert sorted(files) == sorted((d / 'manifest.txt').read_text().split())
    assert verify_head(clone, d) == 0
    G.git(clone, 'push', '-q', 'origin', 'HEAD:main')


def test_unusable_views_day_first_push_verify_head_passes(tmp_path):
    _, _, clone = G.setup(tmp_path, files={CAND: cand(), TGF: tgdata(False), NEWS: '{"items": []}\n'})
    d, _ = gated(clone)
    committed(clone, d)
    assert verify_head(clone, d) == 0


def test_no_news_day_publishes_with_null_hash(tmp_path):
    _, _, clone = G.setup(tmp_path, files={CAND: cand()})
    d, _ = gated(clone)
    committed(clone, d)
    assert json.loads((d / 'gates.json').read_text())['news_sha256'] is None
    assert verify_head(clone, d) == 0


def test_post_edited_after_publish_before_staging_fails_verify_head(repo):
    """§11-10: 발행기가 옮긴 뒤 스테이징 전에 3,824.00 → 3,825.00 — 경로 집합은 같다."""
    _, _, clone = repo
    d, _ = gated(clone)
    publish(clone, d)
    p = clone / POST
    p.write_bytes(p.read_bytes().replace(b'3,824.00', b'3,825.00'))
    _stage(clone, d)
    assert check_staged(clone, d) == 0
    G.git(clone, 'commit', '-q', '-m', f'Add JP daily [{S}]')
    assert verify_head(clone, d) == 4


@pytest.mark.parametrize('rel', [SNAPF, RUNS, PIN])
def test_one_byte_changed_in_a_published_file_fails_verify_head(repo, rel):
    _, _, clone = repo
    d, _ = gated(clone)
    publish(clone, d)
    p = clone / rel
    p.write_bytes(p.read_bytes() + b' ')
    _stage(clone, d)
    G.git(clone, 'commit', '-q', '-m', f'Add JP daily [{S}]')
    assert verify_head(clone, d) == 4


def test_listing_entry_different_from_the_verified_title_fails_verify_head(repo):
    _, _, clone = repo
    d, _ = gated(clone)
    publish(clone, d)
    p = clone / 'japan' / 'daily.json'
    p.write_text(p.read_text(encoding='utf-8').replace('11월 18일', '11월 19일'), encoding='utf-8')
    _stage(clone, d)
    G.git(clone, 'commit', '-q', '-m', f'Add JP daily [{S}]')
    assert verify_head(clone, d) == 4


def test_pin_removed_from_the_commit_fails_verify_head(repo):
    _, _, clone = repo
    d, _ = gated(clone)
    publish(clone, d)
    _stage(clone, d)
    G.git(clone, 'reset', '-q', '--', PIN)
    G.git(clone, 'commit', '-q', '-m', f'Add JP daily [{S}]')
    assert verify_head(clone, d) == 4


def test_news_arriving_by_rebase_after_a_no_news_verification_fails_verify_head(tmp_path):
    """§11-10(9회차 #1): 뉴스 없음으로 검증 → rebase 로 뉴스 파일이 들어옴 → push 안 함."""
    _, seed, clone = G.setup(tmp_path, files={CAND: cand()})
    d, _ = gated(clone)
    committed(clone, d)
    assert verify_head(clone, d) == 0
    G.push_from_seed(seed, NEWS, '{"items": [{"id": 1}]}\n')
    G.git(clone, 'pull', '-q', '--rebase', 'origin', 'main')
    assert verify_head(clone, d) == 4


def test_rebase_onto_an_unrelated_commit_still_passes(repo):
    _, seed, clone = repo
    d, _ = gated(clone)
    committed(clone, d)
    G.push_from_seed(seed, 'kr/posts/2026-11-18.html', 'kr')
    G.git(clone, 'pull', '-q', '--rebase', 'origin', 'main')
    assert verify_head(clone, d) == 0


def test_a_second_local_commit_fails_verify_head(repo):
    _, _, clone = repo
    d, _ = gated(clone)
    committed(clone, d)
    G.write(clone, 'scripts/x.py', 'x = 9\n')
    G.commit_all(clone, f'Add JP daily [{S}] extra')
    assert verify_head(clone, d) == 4


def test_extra_file_in_the_commit_fails_verify_head(repo):
    _, _, clone = repo
    d, _ = gated(clone)
    publish(clone, d)
    _stage(clone, d)
    G.write(clone, 'scripts/x.py', 'x = 4\n')
    G.git(clone, 'add', 'scripts/x.py')
    G.git(clone, 'commit', '-q', '-m', f'Add JP daily [{S}]')
    assert verify_head(clone, d) == 4


def test_verify_head_reads_head_not_the_working_tree(repo):
    _, _, clone = repo
    d, _ = gated(clone)
    committed(clone, d)
    (clone / POST).write_text('tampered after commit', encoding='utf-8')
    assert verify_head(clone, d) == 0          # 커밋된 바이트가 검증 기록과 같다 — 미커밋 변경은 push 되지 않는다


def test_failed_push_commit_is_reverted_by_the_guard_next_time(repo):
    """§11-10: push 에 실패한 `Add JP daily [S]` 커밋이 남은 채 다음 실행(잠금 보유) → 가드가 되돌린다."""
    _, seed, clone = repo
    d, _ = gated(clone)
    committed(clone, d)
    G.acquire(clone)
    from japan.tests.test_jpd_clean_start import guard
    r = guard(clone)
    assert r.returncode == 0, r.stderr
    assert G.head(clone) == G.head(seed) and not (clone / POST).exists() and changes(clone) == ''


# ── rebase 충돌 복구(update_archives.py, §6-5) ───────────────────────────

def _ua(*args):
    return subprocess.run([sys.executable, str(G.SCRIPTS / 'update_archives.py'), *args],
                          capture_output=True, text=True)


def test_update_archives_jp_daily_reads_the_run_record(repo):
    _, _, clone = repo
    d, _ = gated(clone)
    publish(clone, d)
    p = clone / 'japan' / 'daily.json'
    p.write_text('[{"date": "2026-11-17", "title": "전날", "headline": "h"}]', encoding='utf-8')   # 원격 판
    r = _ua('--root', str(clone), '--kind', 'jp-daily', '--key', S)
    assert r.returncode == 0, r.stderr
    got = json.loads(p.read_text(encoding='utf-8'))
    assert {'date': S, 'title': '일본 증시 마감 — 11월 18일', 'headline': 'TOPIX & 닛케이 "엇갈림" <요약>'} in got
    assert len(got) == 2


def test_update_archives_jp_daily_refuses_title_arguments(repo):
    _, _, clone = repo
    d, _ = gated(clone)
    publish(clone, d)
    r = _ua('--root', str(clone), '--kind', 'jp-daily', '--key', S, '--title', 't')
    assert r.returncode == 2


def test_update_archives_jp_daily_without_a_run_record_fails(tmp_path):
    r = _ua('--root', str(tmp_path), '--kind', 'jp-daily', '--key', S)
    assert r.returncode == 2 and not (tmp_path / 'japan' / 'daily.json').exists()


def test_update_archives_other_kinds_still_need_a_title(tmp_path):
    r = _ua('--root', str(tmp_path), '--kind', 'news', '--key', S)
    assert r.returncode == 2


# ── rebase 충돌을 STEP 4-4 그대로 풀어 본다 ───────────────────────────────

def _resolve_like_step_4_4(clone):
    """push 거절 → pull --rebase → 목록·sitemap 충돌은 원격 판 + update_archives(제목 인자 없음) → add → continue."""
    import os
    r = G.git(clone, 'pull', '-q', '--rebase', 'origin', 'main', check=False)
    assert r.returncode != 0                                     # 충돌이 났다
    conflicted = G.git(clone, 'diff', '--name-only', '--diff-filter=U').stdout.split()
    assert conflicted and set(conflicted) <= {'japan/daily.json', 'sitemap.xml'}
    G.git(clone, 'checkout', '--ours', '--', *conflicted)
    r = _ua('--root', str(clone), '--kind', 'jp-daily', '--key', S)
    assert r.returncode == 0, r.stderr
    G.git(clone, 'add', '--', 'japan/daily.json', 'sitemap.xml')
    env = dict(os.environ, GIT_EDITOR='true')
    r = subprocess.run(['git', *G.ENV_ID, 'rebase', '--continue'], cwd=clone, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr + r.stdout
    assert G.status(clone) == ''
    return conflicted


@pytest.mark.parametrize('rel,text', [
    ('sitemap.xml', '<urlset>\n<url><loc>https://fdo2a.github.io/kr/posts/2026-11-18.html</loc>'
                    '<lastmod>2026-11-18</lastmod></url>\n</urlset>\n'),
    ('japan/daily.json', json.dumps([{'date': P, 'title': '전날', 'headline': 'h'}], ensure_ascii=False, indent=2) + '\n'),
])
def test_rebase_conflict_recovery_then_verify_head(repo, rel, text):
    _, seed, clone = repo
    d, _ = gated(clone)
    committed(clone, d)
    G.push_from_seed(seed, rel, text, msg='other run')
    assert _resolve_like_step_4_4(clone) == [rel]
    assert verify_head(clone, d) == 0, 'rebase 뒤 verify-head'
    files = G.git(clone, 'show', '--name-only', '--format=', 'HEAD').stdout.split()
    assert sorted(files) == sorted((d / 'manifest.txt').read_text().split())
    listing = json.loads((clone / 'japan' / 'daily.json').read_text(encoding='utf-8'))
    assert {'date': S, 'title': '일본 증시 마감 — 11월 18일', 'headline': 'TOPIX & 닛케이 "엇갈림" <요약>'} in listing
    if rel == 'japan/daily.json':
        assert {'date': P, 'title': '전날', 'headline': 'h'} in listing
    else:
        assert 'kr/posts/2026-11-18.html' in (clone / 'sitemap.xml').read_text()
    G.git(clone, 'push', '-q', 'origin', 'HEAD:main')


def test_failed_gates_leave_the_violations_in_the_log_for_the_alert(repo):
    _, _, clone = repo
    d, ok = gated(clone, commands=stub(OK, FAIL, OK, OK, OK))
    assert not ok and 'TOPIX 금지 글자' in (d / 'gates.log').read_text(encoding='utf-8')


def test_cli_relative_run_dir_works_from_another_cwd(repo, monkeypatch):
    _, _, clone = repo
    monkeypatch.chdir(clone)
    rel = f'_workspace/jpd/jpd-{S}-1-9'
    assert JG.main(['--pin', '--run-dir', rel, '--session', S, '--root', '.']) == 0
    assert (clone / rel / 'root' / CAND).exists()


def test_v2_end_to_end_with_the_real_assembler_and_gates(tmp_path):
    """2판 고정 스냅샷(1부 시험의 v2()) — 고정 → assemble --root D/root → 실제 다섯 게이트 → 발행 → manifest → verify-head."""
    import build_japan_daily as BJD
    from japan.tests import test_daily_v2_gate as V
    snap = V.v2()
    s = snap['session']
    assert snap.get('schema') == 2 and snap.get('complete') is True
    files = {f'japan/data/daily/candidate/{s}.json': json.dumps(snap, ensure_ascii=False, indent=1),
             f'japan/data/news/daily/{s}.json': json.dumps(V.NEWS, ensure_ascii=False, indent=1)}
    _, _, clone = G.setup(tmp_path, files=files)
    d = clone / '_workspace' / 'jpd' / f'jpd-{s}-1-1'
    JG.pin(str(clone), str(d), s)
    (d / f'jpd_{s}.body.html').write_text(V.body(order=V.R.order((snap.get('calendar') or {}).get('event_day'))),
                                          encoding='utf-8')
    (d / f'jpd_{s}.meta.json').write_text(json.dumps({'title': '엔저 속 대형주만 올랐다', 'summary': '넓은 시장은 약했다.'},
                                                     ensure_ascii=False), encoding='utf-8')
    assert BJD.main(['assemble', '--session', s, '--root', str(d / 'root'), '--body', str(d / f'jpd_{s}.body.html'),
                     '--meta', str(d / f'jpd_{s}.meta.json'), '--out', str(d / f'jpd_{s}.html')]) == 0
    ok, log = JG.run_gates(str(d), s)
    assert ok, log
    assert PUB.main(['--root', str(clone), '--run-dir', str(d), '--run-id', d.name]) == 0
    G.git(clone, 'add', '--', *(d / 'manifest.txt').read_text().split())
    assert check_staged(clone, d) == 0
    G.git(clone, 'commit', '-q', '-m', f'Add JP daily [{s}]')
    assert PUB.main(['verify-head', '--root', str(clone), '--run-dir', str(d)]) == 0
    assert (clone / f'japan/daily/{s}.html').read_bytes() == (d / f'jpd_{s}.html').read_bytes()


# ── codex 구현 1회차 지적 2: 공유 파일(목록·이력·sitemap)의 다른 세션 변경 ─────────────

RICH_SITEMAP = ('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                '  <url><loc>https://fdo2a.github.io/kr/posts/2026-11-18.html</loc><lastmod>2026-11-18</lastmod></url>\n'
                '  <url><loc>https://fdo2a.github.io/posts/2026-11-18.html</loc><lastmod>2026-11-18</lastmod></url>\n'
                '</urlset>\n')
RICH = {CAND: cand(), NEWS: '{"items": []}\n', TGF: tgdata(True),
        'japan/daily.json': json.dumps([{'date': P, 'title': '전날 제목', 'headline': '전날'}], ensure_ascii=False, indent=2) + '\n',
        'japan/data/history/jp_daily.jsonl': json.dumps({'session': P, 'nikkei': 48000.0, 'prices': {}}) + '\n',
        'sitemap.xml': RICH_SITEMAP}


def _tamper_and_commit(clone, d, rel, fn):
    publish(clone, d)
    p = clone / rel
    p.write_text(fn(p.read_text(encoding='utf-8')), encoding='utf-8')
    _stage(clone, d)
    G.git(clone, 'commit', '-q', '-m', f'Add JP daily [{S}]')


def _drop_prev_listing(text):
    return json.dumps([e for e in json.loads(text) if e['date'] != P], ensure_ascii=False, indent=2) + '\n'


@pytest.mark.parametrize('rel,fn', [
    ('japan/daily.json', _drop_prev_listing),
    ('japan/data/history/jp_daily.jsonl', lambda t: ''.join(l + '\n' for l in t.splitlines() if P not in l)),
    ('sitemap.xml', lambda t: t.replace('  <url><loc>https://fdo2a.github.io/kr/posts/2026-11-18.html</loc>'
                                        '<lastmod>2026-11-18</lastmod></url>\n', '')),
    ('sitemap.xml', lambda t: f'<!-- <url><loc>https://fdo2a.github.io/japan/daily/{S}.html</loc></url> -->\n'),
])
def test_other_sessions_changes_in_shared_files_fail_verify_head(tmp_path, rel, fn):
    _, _, clone = G.setup(tmp_path, files=RICH)
    d, _ = gated(clone)
    _tamper_and_commit(clone, d, rel, fn)
    assert verify_head(clone, d) == 4


def test_rich_shared_files_untampered_pass_verify_head(tmp_path):
    _, _, clone = G.setup(tmp_path, files=RICH)
    d, _ = gated(clone)
    committed(clone, d)
    assert verify_head(clone, d) == 0


def test_shared_file_tampered_after_a_rebase_fails_verify_head(tmp_path):
    _, seed, clone = G.setup(tmp_path, files=RICH)
    d, _ = gated(clone)
    committed(clone, d)
    G.push_from_seed(seed, 'kr/posts/2026-11-18.html', 'kr')
    G.git(clone, 'pull', '-q', '--rebase', 'origin', 'main')
    assert verify_head(clone, d) == 0
    p = clone / 'japan' / 'daily.json'
    p.write_text(_drop_prev_listing(p.read_text(encoding='utf-8')), encoding='utf-8')
    G.git(clone, 'add', 'japan/daily.json')
    G.git(clone, 'commit', '-q', '--amend', '--no-edit')
    assert verify_head(clone, d) == 4


# ── 지적 4: 입력 고정 커밋과 검사 입력 ─────────────────────────────────────

def test_input_changed_during_typography_fails(repo):
    _, _, clone = repo
    d = pinned(clone)
    (d / f'jpd_{S}.html').write_text(page(), encoding='utf-8')
    cp = d / 'root' / CAND
    typo = [sys.executable, '-c', f'open({str(cp)!r}, "w").write("{{}}")']
    ok, log = JG.run_gates(str(d), S, commands=stub(typo, OK, OK, OK, OK))
    assert not ok and not (d / 'gates.json').exists() and CAND in log


def test_pin_reads_every_blob_from_the_one_commit_it_recorded(repo, monkeypatch):
    _, _, clone = repo
    seen = []
    real = JG._blob

    def spy(root, commit, rel):
        seen.append(commit)
        return real(root, commit, rel)
    monkeypatch.setattr(JG, '_blob', spy)
    rec = JG.pin(str(clone), str(run_dir(clone)), S)
    assert seen and set(seen) == {rec['input_commit']} and len(rec['input_commit']) >= 40


def test_pin_ignores_head_moving_after_the_sha_was_read(repo, monkeypatch):
    """SHA 를 읽은 뒤 HEAD 가 움직여도 모든 파일은 그 SHA 에서 온다."""
    _, seed, clone = repo
    real = JG._commit

    def moved(root):
        sha = real(root)
        G.write(clone, CAND, cand(indices={'nikkei': {'value': 7.0}}))
        G.commit_all(clone, 'moved')
        return sha
    monkeypatch.setattr(JG, '_commit', moved)
    d = run_dir(clone)
    JG.pin(str(clone), str(d), S)
    assert (d / 'root' / CAND).read_text(encoding='utf-8') == cand()


# ── 지적 1: 조립 실패 뒤 앞 판의 발행 자격 ─────────────────────────────────

def _v2_run(tmp_path):
    import build_japan_daily as BJD
    from japan.tests import test_daily_v2_gate as V
    snap = V.v2()
    s = snap['session']
    files = {f'japan/data/daily/candidate/{s}.json': json.dumps(snap, ensure_ascii=False, indent=1),
             f'japan/data/news/daily/{s}.json': json.dumps(V.NEWS, ensure_ascii=False, indent=1)}
    _, _, clone = G.setup(tmp_path, files=files)
    d = clone / '_workspace' / 'jpd' / f'jpd-{s}-1-1'
    JG.pin(str(clone), str(d), s)
    order = V.R.order((snap.get('calendar') or {}).get('event_day'))
    (d / f'jpd_{s}.meta.json').write_text(json.dumps({'title': '엔저 속 대형주만 올랐다', 'summary': '넓은 시장은 약했다.'},
                                                     ensure_ascii=False), encoding='utf-8')

    def assemble(body):
        (d / f'jpd_{s}.body.html').write_text(body, encoding='utf-8')
        return BJD.main(['assemble', '--session', s, '--root', str(d / 'root'), '--body', str(d / f'jpd_{s}.body.html'),
                         '--meta', str(d / f'jpd_{s}.meta.json'), '--out', str(d / f'jpd_{s}.html')])
    return clone, d, s, V.body(order=order), assemble


def test_pass_then_meaning_rejection_then_fourth_assembly_failure_is_exit_4(tmp_path):
    clone, d, s, good, assemble = _v2_run(tmp_path)
    assert assemble(good) == 0
    ok, log = JG.run_gates(str(d), s)
    assert ok, log
    assert JG.main(['--invalidate', '견해 문단이 요약과 뜻이 다르다 — 작성자에게 되돌림',
                    '--run-dir', str(d), '--session', s]) == 0      # 의미 대조 반려
    assert not (d / 'gates.json').exists()
    assert assemble(good.replace('<!--G:topix-->', '')) == 1         # 넷째 판: 조립 실패
    assert PUB.main(['--root', str(clone), '--run-dir', str(d), '--run-id', d.name]) == 4
    assert G.status(clone) == ''
    log = (d / 'gates.log').read_text(encoding='utf-8')
    assert '조립 실패' in log and 'topix' in log                       # 경보가 가리키는 로그는 마지막 시도의 것


def test_assembly_failure_alone_revokes_an_earlier_pass(tmp_path):
    clone, d, s, good, assemble = _v2_run(tmp_path)
    assert assemble(good) == 0
    assert JG.run_gates(str(d), s)[0]
    assert assemble(good.replace('<!--G:topix-->', '')) == 1         # 반려 표시를 잊어도
    assert not (d / 'gates.json').exists() and not (d / f'jpd_{s}.html').exists()
    assert PUB.main(['--root', str(clone), '--run-dir', str(d), '--run-id', d.name]) == 4
    assert G.status(clone) == ''


def test_successful_reassembly_also_needs_new_gates(tmp_path):
    clone, d, s, good, assemble = _v2_run(tmp_path)
    assert assemble(good) == 0 and JG.run_gates(str(d), s)[0]
    assert assemble(good) == 0
    assert not (d / 'gates.json').exists()
    assert PUB.main(['--root', str(clone), '--run-dir', str(d), '--run-id', d.name]) == 4


def test_guard_reverts_a_rebased_failed_publish_with_recovered_shared_files(tmp_path):
    """rebase 충돌 복구(update_archives) 뒤 push 없이 끝난 실행 — 목록 바이트가 기록과 달라도
    「부모 판 + 이 세션 변경」으로 설명되므로 가드가 되돌린다(지적 3 의 기록 묶기가 정상 중단 경로를 막지 않는다)."""
    from japan.tests.test_jpd_clean_start import guard
    _, seed, clone = G.setup(tmp_path, files=RICH)
    d, _ = gated(clone)
    committed(clone, d)
    G.push_from_seed(seed, 'japan/daily.json',
                     json.dumps([{'date': '2026-11-16', 'title': '그전', 'headline': 'x'}], ensure_ascii=False, indent=2) + '\n')
    _resolve_like_step_4_4(clone)
    G.acquire(clone)
    r = guard(clone)
    assert r.returncode == 0, r.stderr
    assert G.head(clone) == G.head(seed) and changes(clone) == '' and not (clone / POST).exists()


# ── 발행 도중 중단(codex 구현 2회차) — 어디서 죽어도 다음 실행의 가드가 되돌린다 ─────────────────
# 발행기는 산출물을 쓰기 **전에** 쓸 바이트의 해시를 publish.json 에 남긴다. 중단은 정리 코드가 돌지 않는
# BaseException·os._exit 로 넣는다(kill 과 같다). 기록은 꾸미지 않고 발행기가 실제로 남긴 것을 쓴다.

class Kill(BaseException):
    pass


N_WRITES = 9          # 기록 1 + 산출물 7 + manifest 1 (RICH + 견해 파일이 있는 날)


def _killed_publish(monkeypatch, clone, d, k, at='open'):
    """k번째(0부터) 쓰기 직전에 죽인다. at='replace' 면 임시 파일은 쓰고 제자리로 옮기기 직전에. -> 죽었나."""
    import builtins
    import os
    n = {'i': 0}

    def hit():
        n['i'] += 1
        if n['i'] - 1 == k:
            raise Kill()

    def opener(path, mode='r', *a, **kw):
        if at == 'open' and any(c in mode for c in 'wax'):
            hit()
        return builtins.open(path, mode, *a, **kw)
    real_replace = os.replace

    def replace(src, dst, **kw):
        if at == 'replace':
            hit()
        return real_replace(src, dst, **kw)
    with monkeypatch.context() as m:
        m.setattr(PUB, 'open', opener, raising=False)
        m.setattr(os, 'replace', replace)
        try:
            PUB.publish_run(str(clone), str(d), d.name)
        except Kill:
            return True
    return False


def _guard_recovers(clone, seed):
    from japan.tests.test_jpd_clean_start import guard
    G.acquire(clone)
    r = guard(clone)
    assert r.returncode == 0, r.stderr
    assert G.head(clone) == G.head(seed) and changes(clone) == '' and not (clone / POST).exists()


@pytest.mark.parametrize('at', ['open', 'replace'])
@pytest.mark.parametrize('k', range(N_WRITES + 1))
def test_publish_killed_at_any_write_is_recovered_by_the_next_start(tmp_path, monkeypatch, k, at):
    _, seed, clone = G.setup(tmp_path, files=RICH)
    d, _ = gated(clone)
    killed = _killed_publish(monkeypatch, clone, d, k, at)
    assert killed is (k < N_WRITES), '쓰기 횟수가 달라졌다 — N_WRITES 를 맞춘다'
    if killed:
        assert not (d / 'manifest.txt').exists()          # 완료 표식이 없다 — check-staged·verify-head 는 4
        assert check_staged(clone, d) == 4
    _guard_recovers(clone, seed)


def test_after_recovery_a_new_run_publishes_and_verifies(tmp_path, monkeypatch):
    remote, seed, clone = G.setup(tmp_path, files=RICH)
    d, _ = gated(clone)
    assert _killed_publish(monkeypatch, clone, d, 4)
    _guard_recovers(clone, seed)
    d2, ok = gated(clone, n='2')
    assert ok
    committed(clone, d2)
    assert verify_head(clone, d2) == 0
    G.git(clone, 'push', '-q', 'origin', 'HEAD:main')


def test_publish_killed_by_process_exit_is_recovered(tmp_path):
    """정리 코드가 전혀 돌지 않는 종료(os._exit) — 하위 프로세스에서 세 번째 쓰기 직전에 죽인다."""
    import os
    _, seed, clone = G.setup(tmp_path, files=RICH)
    d, _ = gated(clone)
    code = ('import builtins, os, sys\nimport publish_japan_daily as PUB\nn = [0]\n'
            'def opener(path, mode="r", *a, **kw):\n'
            '    if any(c in mode for c in "wax"):\n'
            '        n[0] += 1\n'
            '        if n[0] == 4:\n'
            '            os._exit(9)\n'
            '    return builtins.open(path, mode, *a, **kw)\n'
            'PUB.open = opener\n'
            'sys.exit(PUB.main(sys.argv[1:]))\n')
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(G.SCRIPTS.parent), str(G.SCRIPTS)]), PYTHONDONTWRITEBYTECODE='1')
    r = subprocess.run([sys.executable, '-c', code, '--root', str(clone), '--run-dir', str(d), '--run-id', d.name],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 9, (r.returncode, r.stderr)
    assert changes(clone) != ''                          # 산출물 일부가 실제로 남았다
    _guard_recovers(clone, seed)


def _partial(tmp_path, monkeypatch, k=5):
    from japan.tests.test_jpd_clean_start import _refused
    _, seed, clone = G.setup(tmp_path, files=RICH)
    d, _ = gated(clone)
    assert _killed_publish(monkeypatch, clone, d, k)
    G.acquire(clone)
    return clone, d, _refused


def test_partial_publish_then_a_human_byte_is_refused(tmp_path, monkeypatch):
    clone, d, refused = _partial(tmp_path, monkeypatch)
    assert (clone / POST).exists()
    (clone / POST).write_bytes((clone / POST).read_bytes() + b' ')
    assert '다른 바이트' in refused(clone).stderr


def test_partial_publish_then_an_unwritten_output_edited_by_hand_is_refused(tmp_path, monkeypatch):
    """아직 쓰지 않은 공유 파일을 사람이 고쳤다 — 예정 바이트도 origin 판도 아니다."""
    clone, d, refused = _partial(tmp_path, monkeypatch, k=2)
    (clone / 'sitemap.xml').write_text(RICH_SITEMAP + '<!-- 손 편집 -->\n', encoding='utf-8')
    assert '다른 바이트' in refused(clone).stderr


def test_partial_publish_then_a_deleted_shared_file_is_refused(tmp_path, monkeypatch):
    clone, d, refused = _partial(tmp_path, monkeypatch)
    (clone / 'japan' / 'daily.json').unlink()
    assert '삭제' in refused(clone).stderr


def test_partial_publish_record_of_another_run_or_session_does_not_justify(tmp_path, monkeypatch):
    clone, d, refused = _partial(tmp_path, monkeypatch)
    rec = json.loads((d / 'publish.json').read_text())
    for patch in ({'session': P}, {'run_id': f'jpd-{S}-1763460000-9'}):
        (d / 'publish.json').write_text(json.dumps(dict(rec, **patch)))
        assert '기록' in refused(clone).stderr


def test_killed_publish_committed_by_hand_fails_verify_head(tmp_path, monkeypatch):
    """마지막 표식(manifest) 직전에 죽은 발행을 손으로 커밋해도 push 전 확인이 막는다."""
    _, seed, clone = G.setup(tmp_path, files=RICH)
    d, _ = gated(clone)
    assert _killed_publish(monkeypatch, clone, d, N_WRITES - 1)
    G.git(clone, 'add', '-A')
    G.git(clone, 'commit', '-q', '-m', f'Add JP daily [{S}]')
    assert verify_head(clone, d) == 4


def test_no_temp_file_is_left_in_the_tracked_tree(tmp_path, monkeypatch):
    """임시 파일은 git 이 무시하는 실행 폴더에만 — 산출물 폴더에 남으면 가드가 「7경로 밖 미추적」 으로 거부한다."""
    _, seed, clone = G.setup(tmp_path, files=RICH)
    d, _ = gated(clone)
    assert _killed_publish(monkeypatch, clone, d, 3, at='replace')
    assert set(changes(clone).split()[1::2]) <= PUB_OUTPUTS


def test_run_dir_on_another_device_writes_nothing(tmp_path, monkeypatch):
    _, seed, clone = G.setup(tmp_path, files=RICH)
    d, _ = gated(clone)
    monkeypatch.setattr(PUB, '_same_device', lambda a, b: False)
    assert publish(clone, d) == 4
    assert changes(clone) == '' and not (d / 'publish.json').exists()


PUB_OUTPUTS = {POST, SNAPF, RUNS, PIN, 'japan/data/history/jp_daily.jsonl', 'japan/daily.json', 'sitemap.xml'}
