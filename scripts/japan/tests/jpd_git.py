"""일본 일간 실행 격리 시험용 임시 git 저장소 — 가짜 `origin`(bare) + 루틴 사본.
진짜 원격·이 작업 폴더는 건드리지 않는다. 잠금은 실제 `run_lock.sh acquire` 로 잡는다."""
import subprocess
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2]
RUN_LOCK = SCRIPTS / 'ci' / 'run_lock.sh'
S = '2026-11-18'
KEY = f'jpd-{S}'
ENV_ID = ['-c', 'user.name=t', '-c', 'user.email=t@example.invalid', '-c', 'commit.gpgsign=false']


def git(cwd, *args, check=True):
    return subprocess.run(['git', *ENV_ID, *args], cwd=cwd, capture_output=True, text=True, check=check)


def write(root, rel, text):
    p = Path(root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding='utf-8')
    return p


def commit_all(root, msg):
    git(root, 'add', '-A')
    git(root, 'commit', '-q', '-m', msg)
    return git(root, 'rev-parse', 'HEAD').stdout.strip()


def setup(tmp_path, files=None):
    """-> (remote, seed, clone). seed 는 원격에 커밋을 올리는 「다른 런」, clone 은 시험 대상 사본."""
    remote = tmp_path / 'origin.git'
    subprocess.run(['git', 'init', '-q', '--bare', '-b', 'main', str(remote)], check=True)
    seed = tmp_path / 'seed'
    subprocess.run(['git', 'init', '-q', '-b', 'main', str(seed)], check=True)
    base = {'plan.md': '# plan\n', 'scripts/x.py': 'x = 1\n', 'japan/daily.json': '[]\n',
            'sitemap.xml': '<urlset></urlset>\n', '.gitignore': '/_workspace/\n',
            'japan/data/history/jp_daily.jsonl': ''}
    base.update(files or {})
    for rel, text in base.items():
        write(seed, rel, text)
    commit_all(seed, 'init')
    git(seed, 'remote', 'add', 'origin', str(remote))
    git(seed, 'push', '-q', 'origin', 'main')
    clone = tmp_path / 'clone'
    subprocess.run(['git', 'clone', '-q', str(remote), str(clone)], check=True, capture_output=True)
    return remote, seed, clone


def push_from_seed(seed, rel, text, msg='data: collector'):
    git(seed, 'pull', '-q', '--rebase', 'origin', 'main')
    write(seed, rel, text)
    commit_all(seed, msg)
    git(seed, 'push', '-q', 'origin', 'main')


def acquire(clone, key=KEY):
    r = subprocess.run(['bash', str(RUN_LOCK), 'acquire', key], cwd=clone, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr + r.stdout
    return r


def head(root):
    return git(root, 'rev-parse', 'HEAD').stdout.strip()


def status(root):
    return git(root, 'status', '--porcelain', '--untracked-files=all').stdout
