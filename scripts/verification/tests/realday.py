"""실제 발행일 자료로 발행 전 검사 환경을 되살린다 — 오류 주입 영구 시험(`test_input_mutations.py`)의 고정 자료.

발행 커밋과 검증 기록(`verification/<m>/<D>.json`)의 입력 참조(`repo:`·`git:`)로 그날 작업 공간을 바이트 그대로
복원한다. 기록의 해시와 다르면 실패한다. 발행 커밋을 못 찾으면 **건너뛰지 않고 실패**한다(얕은 클론에서 돌리면
이 시험이 아무것도 증명하지 못한다). 작업 공간에만 있던 파일(작성자 초안·웹 조사 노트)은 내용을 되살릴 수
없어 자리표시 내용으로 둔다 — 정책상 writer·unused 분류여야 하고, gate 분류면 실패한다.

레포는 임시 폴더에 git 으로 만든다: 지금 작업 트리의 `scripts/`·`config/`(검사할 코드) + 발행 커밋의 `posts/`(US
유동성 원장)·`research/<m>/`(연구 원장)·그 글. 작업 트리에 있는 자료 폴더(`data/`·`kr/data/`)는 쓰지 않는다.
"""
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import io

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(os.path.dirname(HERE))
ROOT = os.path.dirname(SCRIPTS)
DAYS = {('us', '2026-11-12'): '입찰·유동성 발표·지표 원문이 있는 날',
        ('us', '2026-11-16'): '연준 의장 연설이 있는 날',
        ('kr', '2026-11-12'): '평범한 날',
        ('kr', '2026-11-13'): '평범한 날'}
# KR 11/16 은 「움직인 종목 0건이 확인된 날」이 아니다 — 그날 수집(0f38e943)의 kr_stock_moves.json 이 0행, 종목을
# 하나도 재지 못한 수집 실패다. 변이 시험의 원본(발행 가능)이 아니라 회귀 시험(미완료)에 쓴다.
INCIDENT = {('kr', '2026-11-16'): '종목을 하나도 재지 못한 날(kr_stock_moves 0행) — 미완료여야 한다'}
PLACEHOLDER = b'placeholder - workspace-only file, content not preserved\n'


def git(*args, cwd=ROOT, binary=True):
    out = subprocess.run(['git', '-C', cwd, *args], capture_output=True, timeout=120)
    if out.returncode:
        raise AssertionError(f'git {" ".join(args)} 실패: {out.stderr.decode("utf-8", "replace")[-300:]}')
    return out.stdout if binary else out.stdout.decode()


def publish_commit(market, date):
    rp = f'verification/{market}/{date}.json'
    c = git('log', '--format=%H', '--diff-filter=A', 'HEAD', '--', rp, binary=False).split()
    if len(c) != 1:
        raise AssertionError(f'{rp} 을 추가한 커밋을 하나로 정하지 못했다({len(c)}) — 얕은 클론이면 전체 이력이 필요하다')
    return c[0]


def _extract(commit, paths, dest):
    raw = git('archive', '--format=tar', commit, '--', *paths)
    with tarfile.open(fileobj=io.BytesIO(raw)) as tf:
        tf.extractall(dest, filter='data') if hasattr(tarfile, 'data_filter') else tf.extractall(dest)


def _copy_tree(src, dst):
    shutil.copytree(src, dst, symlinks=True,
                    ignore=shutil.ignore_patterns('__pycache__', '.pytest_cache', 'fixtures', 'tests'))


def build_repo(tmp, market, date):
    """→ (repo, commit). 지금 코드 + 그 발행 커밋의 원장·글."""
    commit = publish_commit(market, date)
    repo = os.path.join(tmp, 'repo')
    os.makedirs(repo)
    _copy_tree(os.path.join(ROOT, 'scripts'), os.path.join(repo, 'scripts'))
    _copy_tree(os.path.join(ROOT, 'config'), os.path.join(repo, 'config'))
    shutil.copyfile(os.path.join(ROOT, '.gitignore'), os.path.join(repo, '.gitignore'))   # __pycache__ 등
    post = f'posts/{date}.html' if market == 'us' else f'kr/posts/{date}.html'
    _extract(commit, ['posts', f'research/{market}'] if market == 'us' else [post, f'research/{market}'], repo)
    for a in (['init', '-q', '-b', 'main'], ['config', 'user.email', 't@t'], ['config', 'user.name', 't'],
              ['add', '-A'], ['commit', '-q', '-m', 'fixture']):
        subprocess.run(['git', '-C', repo, *a], check=True, capture_output=True)
    return repo, commit


def _bytes(ref, commit):
    if ref.startswith('repo:'):
        return git('show', f'{commit}:{ref[5:]}')
    if ref.startswith('git:'):
        _, c, p = ref.split(':', 2)
        return git('show', f'{c}:{p}')
    return None


def restore(tmp, market, date):
    """→ ctx(run_gates 에 넘길 것) + 'record'(그날 기록). 입력 바이트는 기록의 해시와 같다."""
    from verification import inputs as I
    repo, commit = build_repo(tmp, market, date)
    rec = json.loads(git('show', f'{commit}:verification/{market}/{date}.json'))
    pol = I.load(os.path.join(ROOT, 'config', 'prepub_inputs.json'))
    ws = os.path.join(tmp, 'ws')                   # US 작업 공간 / KR 자료 폴더(kr/data 사본)
    side = os.path.join(tmp, 'side')               # KR 작업 공간(--tg·--stance-next)
    os.makedirs(ws)
    os.makedirs(side)
    ctx = {'datadir': ws, 'repo': repo, 'date': date, 'cycle': None,
           'html': os.path.join(repo, f'posts/{date}.html' if market == 'us' else f'kr/posts/{date}.html')}
    for f in rec['inputs']['files']:
        root, rel = f['path'][1:].split('>/', 1)
        if root == 'datadir':
            dest = os.path.join(ws, rel)
        else:
            # US 는 --tg 가 작업 공간 안의 같은 파일이다
            dest = os.path.join(ws, rel) if (market == 'us' and root == 'tg') else os.path.join(side, rel)
            ctx[root] = dest
        raw = _bytes(f['ref'], commit)
        if raw is None:
            key = f'<datadir>/{rel}' if root == 'datadir' else f'<{root}>'
            cls = _class(pol, market, key, date)
            assert cls in ('writer', 'unused'), f'{f["path"]} 는 작업 공간에만 있었는데 분류가 {cls} 다'
            raw = PLACEHOLDER
        else:
            assert hashlib.sha256(raw).hexdigest() == f['sha256'], f'{f["path"]} 복원 바이트가 기록 해시와 다르다'
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        if os.path.exists(dest):
            with open(dest, 'rb') as fh:
                assert fh.read() == raw, f'{dest} 를 서로 다른 내용으로 두 번 복원하려 했다'
            continue
        with open(dest, 'wb') as fh:
            fh.write(raw)
    ctx['record'] = rec
    return ctx


def _class(pol, market, key, date):
    import fnmatch
    from verification import inputs as I
    files, disc = I.entries(pol, market)
    for e in files:
        if fnmatch.fnmatchcase(key, I._pat(e['path'], date)):
            return e['class']
    return 'discontinued' if any(fnmatch.fnmatchcase(key, d['path']) for d in disc) else None


STAMP = {'status': 'ok', 'collected_at': '2026-11-17T08:18:00+09:00', 'source': 'fixture', 'response': 'ok',
         'required_ok': True, 'missing': []}


def stamp(ctx, market, pol):
    """작업 2 의 수집 상태 표시를 손으로 흉내 낸다 — JSON 객체 gate 자료에는 `collect`, 목록형·txt 는
    `_collect_status.json`. 모든 수집기 산출 gate 파일의 sha256 도 적는다. 대상 목록이 비면 confirmed_none."""
    from verification import inputs as I
    date = ctx['date']
    h = I.assess(pol, market, ctx)
    files, _ = I.entries(pol, market)
    status = {}
    for key, f in sorted(h['files'].items()):
        if f['class'] != 'gate' or f['state'] == 'missing':
            continue
        e = _entry(files, key, date)
        produced = e.get('produced_by', 'collector')
        if produced not in I.LEDGER_PRODUCERS:
            continue
        full = path_of(ctx, key)
        if produced == 'reference':         # 수집 상태 칸 없이 해시만(stamp_collect 의 collect_in none)
            skey = (e.get('stamp_key') or key.split('>/', 1)[-1]).format(date=date)
            with open(full, 'rb') as fh:
                raw = fh.read()
            status[skey] = {'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw), 'collect_in': 'none'}
            continue
        c = dict(STAMP, as_of=date)
        obj = None
        if full.endswith('.json'):
            with open(full, encoding='utf-8') as fh:
                obj = json.load(fh)
        t = e.get('target')
        lst = (obj.get(t) if isinstance(obj, dict) else obj) if t else None
        c['empty'] = 'confirmed_none' if (t and isinstance(lst, list) and not lst) else 'has_data'
        if t == 'groups':                       # 움직인 종목 — 수집기는 잰 종목 수를 적는다(common.movers.stamp)
            c['checked'], c['expected'] = 60, 60
        if isinstance(obj, dict):
            obj['collect'] = c
            with open(full, 'w', encoding='utf-8') as fh:
                json.dump(obj, fh, ensure_ascii=False)
        skey = (e.get('stamp_key') or key.split('>/', 1)[-1]).format(date=date)
        with open(full, 'rb') as fh:
            raw = fh.read()
        ent = {'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}
        if not isinstance(obj, dict):
            ent.update(c)
        status[skey] = ent
    with open(os.path.join(ctx['datadir'], I.STATUS_FILE), 'w', encoding='utf-8') as fh:
        json.dump({'format': 'collect-status/1', 'files': status}, fh, ensure_ascii=False)


def restamp_hashes(ctx):
    """변이 뒤 해시만 다시 적는다 — 해시 불일치(changed_after_collect)가 다른 변이를 가리지 않게."""
    from verification import inputs as I
    p = os.path.join(ctx['datadir'], I.STATUS_FILE)
    try:
        with open(p, encoding='utf-8') as fh:
            st = json.load(fh)
    except (OSError, ValueError):
        return
    for skey, ent in st.get('files', {}).items():
        full = os.path.join(ctx['datadir'], skey)
        if skey.startswith('telegram/') and ctx.get('tg'):
            full = ctx['tg']
        try:
            with open(full, 'rb') as fh:
                raw = fh.read()
        except OSError:
            continue
        ent['sha256'], ent['bytes'] = hashlib.sha256(raw).hexdigest(), len(raw)
    with open(p, 'w', encoding='utf-8') as fh:
        json.dump(st, fh, ensure_ascii=False)


def _entry(files, key, date):
    import fnmatch
    from verification import inputs as I
    return next(e for e in files if fnmatch.fnmatchcase(key, I._pat(e['path'], date)))


def path_of(ctx, key):
    if key in ('<tg>', '<stance_next>'):
        return ctx[key[1:-1]]
    return os.path.join(ctx['datadir'], key.split('>/', 1)[1])
