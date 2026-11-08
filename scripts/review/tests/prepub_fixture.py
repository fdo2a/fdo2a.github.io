"""2단계 시험용 작은 레포 — 루틴이 글과 발행 전 기록을 같은 커밋에 넣는 모양을 흉내 낸다."""
import hashlib
import json
import os
import subprocess

from verification import record as R


def git(repo, *args, check=True):
    out = subprocess.run(['git', '-C', str(repo), *args], capture_output=True, text=True)
    if check and out.returncode:
        raise RuntimeError(out.stderr)
    return out.stdout.strip()


def sha(b):
    return hashlib.sha256(b if isinstance(b, bytes) else b.encode()).hexdigest()


def write(repo, rel, text):
    p = os.path.join(str(repo), rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'w', encoding='utf-8') as fh:
        fh.write(text)


def commit(repo, msg):
    git(repo, 'add', '-A')
    git(repo, '-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-q', '-m', msg, '--allow-empty')
    return git(repo, 'rev-parse', 'HEAD')


CONFIG = {'format': R.CONFIG_FORMAT, 'markets': {
    'us': {'post': 'posts/{date}.html', 'gates': [{'name': 'g1', 'script': 'scripts/g1.py'},
                                                  {'name': 'check_numbers', 'script': 'scripts/g2.py'}]},
    'kr': {'post': 'kr/posts/{date}.html', 'gates': [{'name': 'g1', 'script': 'scripts/g1.py'}]}}}


def init(tmp_path):
    repo = tmp_path / 'repo'
    repo.mkdir()
    git(repo, 'init', '-q', '-b', 'main')
    write(repo, 'config/prepub_gates.json', json.dumps(CONFIG))
    write(repo, 'scripts/g1.py', 'print(1)\n')
    write(repo, 'scripts/g2.py', 'print(2)\n')
    write(repo, 'data/market_data.json', '{"a": 1}\n')
    write(repo, 'data/market_holidays.json', json.dumps({'us': {'dates': ['2026-11-26']},
                                                         'kr': {'dates': ['2026-12-25']}}))
    commit(repo, 'base')
    return repo


def summary(**kw):
    s = {'status': 'pass', 'publish_ok': True, 'verified': True, 'blocking': [], 'not_run': [],
         'note_format': [], 'note_numbers': [], 'warned': [], 'integrity': []}
    s.update(kw)
    return s


def publish(repo, market='us', date='2026-11-09', body='<p>글</p>', workspace=True, summ=None,
            gate_status=None, record=True, numbers=None):
    """글과 기록을 같은 커밋에 넣는다(루틴 STEP 3 모양). → 커밋."""
    cfg = CONFIG
    pp = cfg['markets'][market]['post'].format(date=date)
    write(repo, pp, body)
    if record:
        digest, n = R.repo_digest(str(repo), market, pp, 'HEAD')
        files = [{'path': '<datadir>/market_data.json', 'sha256': sha('{"a": 1}\n'),
                  'ref': 'repo:data/market_data.json'}]
        if workspace:
            files.append({'path': '<datadir>/macro_next.json', 'sha256': sha('x'), 'ref': 'workspace-only'})
        gates = []
        for g in cfg['markets'][market]['gates']:
            st = (gate_status or {}).get(g['name'], 'pass')
            ent = {'name': g['name'], 'argv': [g['script']], 'required': g['name'] != 'ref_only',
                   'script_sha256': sha(open(os.path.join(str(repo), g['script']), 'rb').read()),
                   'status': st, 'exit': 0, 'kind': 'numbers'}
            if g['name'] == 'check_numbers' and numbers is not None:
                ent['numbers'] = numbers
            gates.append(ent)
        rec = {'format': R.FORMAT, 'market': market, 'date': date,
               'post': {'path': pp, 'sha256': sha(body)},
               'created_at': {'kst': f'{date}T07:00:00+09:00'},
               'repo_inputs': {'paths': R.repo_paths(market), 'digest': digest, 'files': n},
               'inputs': {'files': files}, 'gates': gates, 'summary': summ or summary(),
               'code': {'python': '3.11.9'}}
        write(repo, R.record_path(market, date), json.dumps(rec, ensure_ascii=False))
    return commit(repo, f'Add {market} {date}')
