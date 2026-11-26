"""늦은 글의 작업 공간 — D 의 마지막 수집 커밋 하나에서 `data/` 를 꺼낸다 (2026-11-27).

11/24 를 지금 내면 main 의 `data/` 는 11/25 판이다(MU 등락률 67d749c2 -11.01% ↔ main -4.53%). 입력은 그날의
수집 커밋 하나에서만 온다.
"""
import importlib.util
import json
import os
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, '..', '..', 'ci', 'late_workspace.py')
spec = importlib.util.spec_from_file_location('late_workspace', SCRIPT)
lw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lw)


def _git(cwd, *args):
    return subprocess.run(['git', *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def _commit(repo, day, extra=None, msg=None):
    data = repo / 'data'
    data.mkdir(exist_ok=True)
    # 수집마다 시장 데이터가 바뀐다(같은 날 재수집도)
    (data / 'market_data.json').write_text(json.dumps({'report_date': day, 'run': msg or day}))
    for path, text in (extra or {}).items():
        (data / path).parent.mkdir(parents=True, exist_ok=True)
        (data / path).write_text(text)
    _git(repo, 'add', '-A')
    _git(repo, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', msg or f'data {day}')
    return _git(repo, 'rev-parse', 'HEAD')


def _repo(tmp_path):
    repo = tmp_path / 'r'
    repo.mkdir()
    _git(repo, 'init', '-q')
    a = _commit(repo, '2026-11-23')
    b1 = _commit(repo, '2026-11-24', {'news/2026-11-24.json': '{"n": 1}'})
    b2 = _commit(repo, '2026-11-24', {'telegram/2026-11-24.json': '{"t": 1}'}, 'data 2026-11-24 again')
    # D 뒤의 커밋 — 시장 데이터가 아닌 파일만 바꾼 것과 다음 날 수집
    (repo / 'posts').mkdir()
    (repo / 'posts' / 'x.html').write_text('x')
    _git(repo, 'add', '-A')
    _git(repo, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'post')
    c = _commit(repo, '2026-11-25', {'news/2026-11-24.json': '{"n": 2}'})
    return repo, a, b1, b2, c


def test_the_last_collection_commit_of_that_day_wins(tmp_path):
    repo, a, b1, b2, c = _repo(tmp_path)
    git = lambda *args: subprocess.run(['git', *args], cwd=repo, capture_output=True, text=True)
    assert lw.find_commit('2026-11-24', 'HEAD', git) == b2
    assert lw.find_commit('2026-11-23', 'HEAD', git) == a
    assert lw.find_commit('2026-11-25', 'HEAD', git) == c
    assert lw.find_commit('2026-11-20', 'HEAD', git) is None


def test_cli_exports_that_commits_data_without_the_prefix(tmp_path):
    repo, _, _, b2, _ = _repo(tmp_path)
    out = tmp_path / 'ws'
    r = subprocess.run(['python3', SCRIPT, '--date', '2026-11-24', '--out', str(out)],
                       cwd=repo, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip().split('\n')[-1] == b2
    assert json.loads((out / 'market_data.json').read_text())['report_date'] == '2026-11-24'
    assert json.loads((out / 'news' / '2026-11-24.json').read_text()) == {'n': 1}     # 뒤의 수정본이 아니다
    assert (out / 'telegram' / '2026-11-24.json').exists()


def test_cli_without_a_collection_commit_says_why(tmp_path):
    repo, *_ = _repo(tmp_path)
    r = subprocess.run(['python3', SCRIPT, '--date', '2026-11-20', '--out', str(tmp_path / 'ws')],
                       cwd=repo, capture_output=True, text=True)
    assert r.returncode == 1 and r.stdout == '' and '2026-11-20' in r.stderr
    assert not (tmp_path / 'ws' / 'market_data.json').exists()
