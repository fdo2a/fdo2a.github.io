"""발행 전 검증 기록(`verification.record`, CLI `scripts/run_gates.py`) — 2026-11-08.

지키는 것: 기록 상태와 발행 여부를 가른다(필수 검사의 판정 불가 = 현재 판을 올리지 않음), 건너뛴 검사를
통과로 세지 않는다, 노트 때문인 실패는 항목 단위로 가른다, 기록과 커밋된 글이 짝이 맞지 않으면 push 못 한다.
"""
import json
import os
import subprocess
import sys

import pytest

from verification import record as R

SCRIPTS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CLI = os.path.join(SCRIPTS, 'run_gates.py')

PASS = 'print("gate: OK")\n'
WARN = 'print("경고: 분량이 길다")\nprint("gate: OK")\n'
READ_WARN = 'print("   warn 문장이 길다")\n'
FAIL = 'import sys\nprint("[채권] 2Y 4.478% ≠ 4.477%")\nsys.exit(1)\n'
EXIT2 = 'import sys\nprint("FATAL: 입력을 읽지 못했다", file=sys.stderr)\nsys.exit(2)\n'
CRASH = 'raise KeyError("x")\n'
FATAL1 = 'import sys\nprint("FATAL: liquidity.json 을 읽지 못했다")\nsys.exit(1)\n'
SLOW = 'import time\ntime.sleep(5)\n'
# 노트 안의 문장에만 걸리는 검사기 — 글에 NOTE_BAD 가 있으면 실패
NOTE_GATE = ('import sys\nh = open(sys.argv[sys.argv.index("--html") + 1], encoding="utf-8").read()\n'
             'bad = [w for w in ("NOTE_BAD", "BODY_BAD") if w in h]\n'
             'for w in bad:\n    print(f"위반: {w} 가 있다")\nsys.exit(1 if bad else 0)\n')
NUMBERS_SKIP = 'import json\nprint(json.dumps({"skipped": True, "effective": "2026-10-01"}))\n'
NUMBERS_OK = ('import json\nprint(json.dumps({"skipped": False, "warnings": ["경고(문장): x"], "violations": [],'
              ' "summary": "number audit: …", "counts": {"tokens_seen": 9, "table_cells": 5, "prose_judged": 2,'
              ' "unverified": 2, "delegated": 0, "excluded": 0}}))\n')

POST = ('<!DOCTYPE html><html><body data-register="da"><section><h2>채권</h2><p>본문</p></section>'
        '</body></html>')
NOTE = ('<section id="editor-note" data-editor-note="2026-11-06" style="x"><h2>에디터 노트</h2>'
        '<p>NOTE_BAD</p></section>')


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / 'repo'
    (root / 'scripts').mkdir(parents=True)
    (root / 'posts').mkdir()
    (root / 'ws').mkdir()
    (root / 'ws' / 'market_data.json').write_text('{"report_date": "2026-11-06"}')
    subprocess.run(['git', 'init', '-q', '-b', 'main', str(root)], check=True)
    for k, v in (('user.email', 't@t'), ('user.name', 't')):
        subprocess.run(['git', '-C', str(root), 'config', k, v], check=True)
    return root


def gate(repo, name, body):
    (repo / 'scripts' / f'{name}.py').write_text(body, encoding='utf-8')
    return name


def config(repo, gates, market='us', disabled=None):
    cfg = {'format': 'prepub-gates/1', 'markets': {market: {'post': 'posts/{date}.html', 'gates': gates}},
           'disabled': disabled or {}}
    p = repo / 'gates.json'
    p.write_text(json.dumps(cfg, ensure_ascii=False))
    return str(p)


def g(name, required=True, extra=(), **kw):
    d = {'name': name, 'argv': [f'scripts/{name}.py', '--html', '{html}', *extra], 'required': required}
    d.update(kw)
    return d


def write_post(repo, text=POST, date='2026-11-06'):
    p = repo / 'posts' / f'{date}.html'
    p.write_text(text, encoding='utf-8')
    return str(p)


def run(repo, cfg, html, **kw):
    ctx = dict(html=html, datadir=str(repo / 'ws'), repo=str(repo), date='2026-11-06')
    ctx.update(kw)
    return R.run_gates(R.load_config(cfg), 'us', ctx, timeout=kw.pop('timeout', 3) if 'timeout' in kw else 3)


# ── 상태 해석 ─────────────────────────────────────────────────────────────

def test_status_mapping(repo):
    for n, b in (('a', PASS), ('b', WARN), ('c', READ_WARN), ('d', FAIL), ('e', EXIT2), ('f', CRASH),
                 ('h', FATAL1)):
        gate(repo, n, b)
    cfg = config(repo, [g(n) for n in 'abcdefh'] + [g('missing_script')])
    res = run(repo, cfg, write_post(repo))
    st = {x['name']: x['status'] for x in res['gates']}
    assert st == {'a': 'pass', 'b': 'warn', 'c': 'warn', 'd': 'fail', 'e': 'indeterminate',
                  'f': 'indeterminate', 'h': 'indeterminate', 'missing_script': 'indeterminate'}
    by = {x['name']: x for x in res['gates']}
    assert by['b']['warn_count'] == 1 and by['d']['exit'] == 1 and by['d']['items']
    assert all('started' in x and 'ended' in x for x in res['gates'])


def test_timeout_is_indeterminate(repo):
    gate(repo, 'slow', SLOW)
    res = R.run_gates(R.load_config(config(repo, [g('slow')])), 'us',
                      dict(html=write_post(repo), datadir=str(repo / 'ws'), repo=str(repo), date='2026-11-06'),
                      timeout=1)
    assert res['gates'][0]['status'] == 'indeterminate' and res['gates'][0]['timed_out']


def test_missing_required_input_is_indeterminate(repo):
    gate(repo, 'tg', PASS)
    cfg = config(repo, [g('tg', extra=('--tg', '{tg}'))])
    res = run(repo, cfg, write_post(repo))
    assert res['gates'][0]['status'] == 'indeterminate' and 'tg' in res['gates'][0]['reason']


def test_builtin_unconfirmed(repo):
    cfg = config(repo, [{'name': 'unconfirmed', 'builtin': 'unconfirmed', 'required': True}])
    assert run(repo, cfg, write_post(repo))['gates'][0]['status'] == 'pass'
    assert run(repo, cfg, write_post(repo, POST.replace('본문', '본문 [확인필요]')))['gates'][0]['status'] == 'fail'


def test_numbers_json_skip_is_not_run_and_counts_kept(repo):
    gate(repo, 'nums', NUMBERS_SKIP)
    cfg = config(repo, [g('nums', json=True)])
    r = run(repo, cfg, write_post(repo))['gates'][0]
    assert r['status'] == 'not_run' and '적용일' in r['reason']
    gate(repo, 'nums', NUMBERS_OK)
    r = run(repo, cfg, write_post(repo))['gates'][0]
    assert r['status'] == 'warn' and r['numbers']['unverified'] == 2 and r['numbers']['table_cells'] == 5


# ── 발행 여부는 기록 상태와 따로 ──────────────────────────────────────────────

def test_required_indeterminate_blocks_reference_does_not(repo):
    gate(repo, 'ok', PASS)
    gate(repo, 'broken', CRASH)
    gate(repo, 'ref', FAIL)
    res = run(repo, config(repo, [g('ok'), g('ref', required=False)]), write_post(repo))
    assert res['summary']['publish_ok'] and res['summary']['status'] == 'fail'   # 참고 검사 실패는 상태만
    res = run(repo, config(repo, [g('ok'), g('broken')]), write_post(repo))
    assert not res['summary']['publish_ok'] and res['summary']['status'] == 'indeterminate'
    assert res['summary']['blocking'] == ['broken']


def test_not_run_is_not_verified(repo):
    gate(repo, 'nums', NUMBERS_SKIP)
    res = run(repo, config(repo, [g('nums', json=True)]), write_post(repo))
    assert res['summary']['publish_ok'] and res['summary']['not_run'] == ['nums']
    assert res['summary']['status'] == 'pass_with_gaps'


# ── 편집자 노트 ───────────────────────────────────────────────────────────

def test_note_only_failure_depends_on_gate_kind(repo):
    gate(repo, 'n', NOTE_GATE)
    html = write_post(repo, POST.replace('</body>', NOTE + '</body>'))
    # 표현·형식 검사 — 기록하고 허용
    r = run(repo, config(repo, [g('n', kind='format')]), html)
    x = r['gates'][0]
    assert x['status'] == 'fail' and x['note']['stripped_status'] == 'pass'
    assert x['note']['note_items'] == ['위반: NOTE_BAD 가 있다'] and x['note']['body_items'] == []
    assert r['summary']['publish_ok'] and r['summary']['note_format'] == ['n']
    assert not r['summary']['verified']
    # 수치 검사 — 노트 수치 불일치, 검증 완료 아님
    r = run(repo, config(repo, [g('n', kind='numbers')]), html)
    assert r['summary']['note_numbers'] == ['n'] and not r['summary']['verified']
    # 구조·필수 표식(모르는 종류 포함) — 보류
    for kind in ('structure', None):
        spec = g('n') if kind is None else g('n', kind=kind)
        r = run(repo, config(repo, [spec]), html)
        assert not r['summary']['publish_ok'] and r['summary']['blocking'] == ['n']
    assert open(html, encoding='utf-8').read().count('NOTE_BAD') == 1          # 원본(노트)은 그대로


def test_failure_in_body_with_note_blocks(repo):
    gate(repo, 'n', NOTE_GATE)
    html = write_post(repo, POST.replace('본문', 'BODY_BAD').replace('</body>', NOTE + '</body>'))
    r = run(repo, config(repo, [g('n', kind='format')]), html)
    x = r['gates'][0]
    assert x['note']['body_items'] == ['위반: BODY_BAD 가 있다']
    assert x['note']['note_items'] == ['위반: NOTE_BAD 가 있다']
    assert not r['summary']['publish_ok'] and r['summary']['blocking'] == ['n']


# ── 기록 파일과 짝 확인 ───────────────────────────────────────────────────────

def cli(repo, *args, cfg=None):
    a = [sys.executable, CLI, *args]
    if cfg:
        a += ['--config', cfg]
    return subprocess.run(a, capture_output=True, text=True, cwd=str(repo), timeout=60)


def record_args(repo, html):
    return ['record', '--market', 'us', '--date', '2026-11-06', '--html', html, '--datadir', str(repo / 'ws'),
            '--repo', str(repo), '--out', str(repo / 'verification' / 'us' / '2026-11-06.json')]


def test_record_writes_hashes_and_evidence(repo):
    gate(repo, 'ok', PASS)
    cfg = config(repo, [g('ok')])
    html = write_post(repo)
    p = cli(repo, *record_args(repo, html), cfg=cfg)
    assert p.returncode == 0, p.stderr
    rec = json.load(open(repo / 'verification' / 'us' / '2026-11-06.json', encoding='utf-8'))
    import hashlib
    assert rec['format'] == 'prepub-record/1' and rec['post']['path'] == 'posts/2026-11-06.html'
    assert rec['post']['sha256'] == hashlib.sha256(open(html, 'rb').read()).hexdigest()
    assert rec['inputs']['files'][0]['path'] == 'ws/market_data.json' or rec['inputs']['files']
    assert rec['summary']['publish_ok'] is True and rec['code']['python']
    assert 'stdout' not in json.dumps(rec)                       # 원시 출력은 해시만
    assert str(repo) not in json.dumps(rec, ensure_ascii=False)  # 절대 경로가 공개 기록에 없다


def test_record_blocking_exit_1(repo):
    gate(repo, 'broken', CRASH)
    p = cli(repo, *record_args(repo, write_post(repo)), cfg=config(repo, [g('broken')]))
    assert p.returncode == 1 and 'broken' in p.stdout


def test_record_write_failure_exit_4_and_stale_removed(repo, monkeypatch, tmp_path):
    gate(repo, 'ok', PASS)
    cfg = config(repo, [g('ok')])
    out = repo / 'verification' / 'us' / '2026-11-06.json'
    out.parent.mkdir(parents=True)
    out.write_text('{"stale": true}')
    res = R.run_gates(R.load_config(cfg), 'us', dict(html=write_post(repo), datadir=str(repo / 'ws'),
                                                    repo=str(repo), date='2026-11-06'))
    res = {k: v for k, v in res.items() if k != 'post_bytes'}
    real = R._atomic_write

    def only_repo_fails(path, data):
        if str(repo) in path:
            raise OSError('disk full')
        return real(path, data)
    monkeypatch.setattr(R, '_atomic_write', only_repo_fails)
    fb = str(tmp_path / 'fb.json')
    assert R.save_record(res, str(out), fallback=fb) == 4 and not out.exists() and os.path.exists(fb)
    monkeypatch.setattr(R, '_atomic_write', lambda path, data: (_ for _ in ()).throw(OSError('x')))
    assert R.save_record(res, str(out), fallback=fb) == 5           # 증거가 어디에도 없다 — 보류


def commit_all(repo, msg='publish'):
    subprocess.run(['git', '-C', str(repo), 'add', '-A'], check=True)
    subprocess.run(['git', '-C', str(repo), 'commit', '-q', '-m', msg], check=True)


def verify(repo, *extra, cfg, datadir=True):
    d = ('--datadir', str(repo / 'ws')) if datadir else ()
    return cli(repo, 'verify', '--market', 'us', '--date', '2026-11-06', '--repo', str(repo), *d, *extra, cfg=cfg)


def test_verify_head_and_index(repo):
    gate(repo, 'ok', PASS)
    cfg = config(repo, [g('ok')])
    html = write_post(repo)
    assert cli(repo, *record_args(repo, html), cfg=cfg).returncode == 0
    subprocess.run(['git', '-C', str(repo), 'add', '-A'], check=True)
    assert verify(repo, '--index', cfg=cfg).returncode == 0
    commit_all(repo)
    assert verify(repo, '--rev', 'HEAD', cfg=cfg).returncode == 0


def test_post_changed_after_record_cannot_push(repo):
    # 재시도 중 글만 바뀌고 기록은 그대로 — 밀어 올릴 커밋의 짝이 어긋나 막힌다
    gate(repo, 'ok', PASS)
    cfg = config(repo, [g('ok')])
    html = write_post(repo)
    cli(repo, *record_args(repo, html), cfg=cfg)
    commit_all(repo)
    write_post(repo, POST.replace('본문', '본문 고침'))
    commit_all(repo, 'liquidity recompute')
    p = verify(repo, '--rev', 'HEAD', cfg=cfg)
    assert p.returncode == 1 and '해시' in p.stdout
    # 작업 폴더가 아니라 커밋을 읽는다 — 작업 폴더를 되돌려도 HEAD 는 여전히 어긋난다
    write_post(repo)
    assert verify(repo, '--rev', 'HEAD', cfg=cfg).returncode == 1


def test_verify_missing_record_is_4(repo):
    gate(repo, 'ok', PASS)
    cfg = config(repo, [g('ok')])
    write_post(repo)
    commit_all(repo)
    assert verify(repo, '--rev', 'HEAD', cfg=cfg).returncode == 4


def test_verify_rejects_blocked_or_foreign_record(repo):
    gate(repo, 'ok', PASS)
    cfg = config(repo, [g('ok')])
    html = write_post(repo)
    cli(repo, *record_args(repo, html), cfg=cfg)
    out = repo / 'verification' / 'us' / '2026-11-06.json'
    rec = json.load(open(out, encoding='utf-8'))
    rec['summary']['publish_ok'] = False
    out.write_text(json.dumps(rec))
    commit_all(repo)
    assert verify(repo, '--rev', 'HEAD', cfg=cfg).returncode == 1
    rec['summary']['publish_ok'] = True
    rec['date'] = '2026-11-05'
    out.write_text(json.dumps(rec))
    commit_all(repo, 'x')
    assert verify(repo, '--rev', 'HEAD', cfg=cfg).returncode == 1


def test_verify_rejects_record_with_different_gate_list(repo):
    gate(repo, 'ok', PASS)
    gate(repo, 'ok2', PASS)
    html = write_post(repo)
    cli(repo, *record_args(repo, html), cfg=config(repo, [g('ok')]))
    commit_all(repo)
    p = verify(repo, '--rev', 'HEAD', cfg=config(repo, [g('ok'), g('ok2')]))
    assert p.returncode == 1 and 'ok2' in p.stdout


def test_check_mode_prints_outputs_and_exit(repo):
    gate(repo, 'bad', FAIL)
    p = cli(repo, 'check', '--market', 'us', '--date', '2026-11-06', '--html', write_post(repo),
            '--datadir', str(repo / 'ws'), '--repo', str(repo), cfg=config(repo, [g('bad')]))
    assert p.returncode == 1 and '2Y 4.478%' in p.stdout and 'bad' in p.stdout


def test_verify_detects_changed_checker_code(repo):
    gate(repo, 'ok', PASS)
    cfg = config(repo, [g('ok')])
    html = write_post(repo)
    cli(repo, *record_args(repo, html), cfg=cfg)
    commit_all(repo)
    gate(repo, 'ok', PASS + '# changed\n')
    commit_all(repo, 'gate change')
    p = verify(repo, '--rev', 'HEAD', cfg=cfg)
    assert p.returncode == 1 and '검사 코드가 바뀌었다' in p.stdout


def test_verify_detects_changed_inputs(repo):
    gate(repo, 'ok', PASS)
    cfg = config(repo, [g('ok')])
    html = write_post(repo)
    cli(repo, *record_args(repo, html), cfg=cfg)
    commit_all(repo)
    assert verify(repo, '--rev', 'HEAD', '--datadir', str(repo / 'ws'), cfg=cfg).returncode == 0
    (repo / 'ws' / 'market_data.json').write_text('{"report_date": "2026-11-07"}')
    p = verify(repo, '--rev', 'HEAD', '--datadir', str(repo / 'ws'), cfg=cfg)
    assert p.returncode == 1 and '입력 데이터가 바뀌었다' in p.stdout


def test_record_tool_error_is_5_not_a_gate_failure(repo):
    p = cli(repo, *record_args(repo, write_post(repo)), cfg=str(repo / 'nope.json'))
    assert p.returncode == 5


def test_record_does_not_modify_post(repo):
    gate(repo, 'ok', PASS)
    html = write_post(repo)
    before = open(html, 'rb').read()
    cli(repo, *record_args(repo, html), cfg=config(repo, [g('ok')]))
    assert open(html, 'rb').read() == before


def test_record_of_file_outside_repo_hides_path(repo, tmp_path):
    gate(repo, 'ok', PASS)
    outside = tmp_path / 'ws2'
    outside.mkdir()
    html = outside / '2026-11-06.html'
    html.write_text(POST, encoding='utf-8')
    p = cli(repo, *record_args(repo, str(html)), cfg=config(repo, [g('ok')]))
    assert p.returncode == 0
    t = open(repo / 'verification' / 'us' / '2026-11-06.json', encoding='utf-8').read()
    assert str(tmp_path) not in t and '<레포 밖>/2026-11-06.html' in t


# ── codex 구현 검토 1회차 고침 ───────────────────────────────────────────────

def test_post_changed_during_check_blocks(repo, monkeypatch):
    # #1 — 검사 중 원본이 바뀌면 도구 오류(5)가 아니라 발행 보류
    gate(repo, 'ok', PASS)
    html = write_post(repo)
    real = R._exec

    def touching(spec, ctx, h, timeout):
        with open(html, 'a', encoding='utf-8') as fh:
            fh.write('<!-- x -->')
        return real(spec, ctx, h, timeout)
    monkeypatch.setattr(R, '_exec', touching)
    res = run(repo, config(repo, [g('ok')]), html)
    assert not res['summary']['publish_ok'] and 'integrity' in res['summary']['blocking']
    assert any('원본 글이 바뀌었다' in x for x in res['summary']['integrity'])


def test_gates_run_on_an_immutable_copy(repo):
    # #2 — 검사기는 원본이 아니라 사본을 본다(같은 파일 이름), 기록 해시는 그 바이트의 것
    gate(repo, 'where', 'import sys\nprint(sys.argv[sys.argv.index("--html") + 1])\n')
    html = write_post(repo)
    res = run(repo, config(repo, [g('where')]), html)
    assert res['gates'][0]['items'] == ['<html>']                 # 경로는 가려지되 원본 경로가 아니다
    import hashlib
    assert res['post_sha256'] == hashlib.sha256(open(html, 'rb').read()).hexdigest()


def test_inputs_changed_during_check_blocks(repo):
    # #7 — 검사 전후 입력이 다르면 섞인 결과다
    gate(repo, 'mut', 'import os\nopen(os.path.join("ws", "market_data.json"), "a").write(" ")\n')
    res = run(repo, config(repo, [g('mut')]), write_post(repo))
    assert not res['summary']['publish_ok']
    assert any('입력 파일이 바뀌었다' in x for x in res['summary']['integrity'])


def test_record_tool_error_blocks_now(repo, monkeypatch):
    # #1 — 기록 도구 오류(5)는 최종 판이 검사됐다는 근거가 없다(지시문이 보류로 다룬다)
    p = cli(repo, *record_args(repo, write_post(repo)), cfg=str(repo / 'nope.json'))
    assert p.returncode == 5


def test_research_error_is_indeterminate(repo):
    # #8 — 입력 오류(RESEARCH_ERROR, exit 1)는 위반이 아니라 판정 불가 → 필수면 보류
    gate(repo, 'rs', 'import sys\nprint("RESEARCH_ERROR: ledger broken", file=sys.stderr)\nsys.exit(1)\n')
    r = run(repo, config(repo, [g('rs')]), write_post(repo))
    assert r['gates'][0]['status'] == 'indeterminate' and not r['summary']['publish_ok']


def test_effective_date_makes_not_run(repo):
    # #8 — 적용일 전 글은 exit 0 이어도 검사되지 않았다
    gate(repo, 'f', PASS)
    spec = g('f', effective={'module': 'fund.gate', 'attr': 'EFFECTIVE'})
    r = R.run_gates(R.load_config(config(repo, [spec])), 'us',
                    dict(html=write_post(repo, date='2026-09-01'), datadir=str(repo / 'ws'), repo=str(repo),
                         date='2026-09-01'))
    assert r['gates'][0]['status'] == 'not_run' and r['summary']['not_run'] == ['f']
    bad = g('f', effective={'module': 'no.such', 'attr': 'X'})
    r = run(repo, config(repo, [bad]), write_post(repo))
    assert r['gates'][0]['status'] == 'indeterminate'


def test_verify_requires_same_input_roots(repo):
    # #4 — record 에 --tg 를 줬으면 verify 에도 줘야 한다(안 주면 맴돌지 않게 바로 이유를 말한다)
    gate(repo, 'ok', PASS)
    cfg = config(repo, [g('ok')])
    (repo / 'tg.json').write_text('{}')
    html = write_post(repo)
    cli(repo, *record_args(repo, html), '--tg', str(repo / 'tg.json'), cfg=cfg)
    commit_all(repo)
    p = verify(repo, '--rev', 'HEAD', cfg=cfg)
    assert p.returncode == 1 and '--tg' in p.stdout
    assert verify(repo, '--rev', 'HEAD', '--tg', str(repo / 'tg.json'), cfg=cfg).returncode == 0


def test_verify_detects_changed_module_or_ledger(repo):
    # #6 — 진입 스크립트가 아니라 판정 모듈·원장이 바뀌어도 기록은 무효
    gate(repo, 'ok', PASS)
    (repo / 'scripts' / 'helper.py').write_text('X = 1\n')
    (repo / 'research' / 'us').mkdir(parents=True)
    (repo / 'research' / 'us' / 'ledger.jsonl').write_text('{}\n')
    cfg = config(repo, [g('ok')])
    html = write_post(repo)
    cli(repo, *record_args(repo, html), cfg=cfg)
    commit_all(repo)
    assert verify(repo, '--rev', 'HEAD', cfg=cfg).returncode == 0
    (repo / 'research' / 'us' / 'ledger.jsonl').write_text('{}\n{}\n')
    commit_all(repo, 'ledger')
    p = verify(repo, '--rev', 'HEAD', cfg=cfg)
    assert p.returncode == 1 and '원장' in p.stdout


def test_save_failure_path_uses_fallback_record(repo, monkeypatch, tmp_path, capsys):
    # #3·#10 — 저장 실패 경로도 글뿐 아니라 코드·원장 변경까지 대조한다(레포 밖 대체 기록)
    import run_gates as RG
    gate(repo, 'ok', PASS)
    (repo / 'scripts' / 'helper.py').write_text('X = 1\n')
    cfg = config(repo, [g('ok')])
    commit_all(repo, 'base')
    html = write_post(repo)
    real = R._atomic_write
    monkeypatch.setattr(R, '_atomic_write', lambda path, data: (_ for _ in ()).throw(OSError('full'))
                        if 'verification' in path else real(path, data))
    monkeypatch.setattr(R, 'fallback_path', lambda m, d: str(tmp_path / 'fb.json'))
    monkeypatch.chdir(repo)
    assert RG.main(record_args(repo, html) + ['--config', cfg]) == 4
    assert 'fallback_record=' in capsys.readouterr().out
    commit_all(repo)
    fb = str(tmp_path / 'fb.json')
    assert verify(repo, '--rev', 'HEAD', cfg=cfg).returncode == 4
    assert verify(repo, '--rev', 'HEAD', '--record-file', fb, cfg=cfg).returncode == 0
    (repo / 'scripts' / 'helper.py').write_text('X = 2\n')
    commit_all(repo, 'rebase pulled a code change')
    p = verify(repo, '--rev', 'HEAD', '--record-file', fb, cfg=cfg)
    assert p.returncode == 1 and '원장' in p.stdout


def test_record_blob_unreadable_is_2_not_missing(repo, monkeypatch):
    # #3 — 경로는 있는데 blob 을 못 읽으면 「기록 없음」이 아니라 차단
    gate(repo, 'ok', PASS)
    cfg = config(repo, [g('ok')])
    html = write_post(repo)
    cli(repo, *record_args(repo, html), cfg=cfg)
    commit_all(repo)
    real = R._git

    def broken(r, *args):
        if args[:1] == ('show',) and args[1].endswith('verification/us/2026-11-06.json'):
            return subprocess.CompletedProcess(args, 128, b'', b'fatal: corrupt object')
        return real(r, *args)
    monkeypatch.setattr(R, '_git', broken)
    code, why = R.verify(R.load_config(cfg), 'us', '2026-11-06', str(repo), rev='HEAD', datadir=str(repo / 'ws'))
    assert code == 2


def test_exit0_contracts(repo):
    # #8 — exit 0 이어도 필수 입력이 없어 못 봤으면 판정 불가, 대상이 아니면 실행 안 함
    gate(repo, 'miss', 'print("no data/market_data.json — nothing to check")\n')
    gate(repo, 'skip', 'print("no price_context block in market_data.json — nothing to check")\n')
    cfg = config(repo, [g('miss', indeterminate_patterns=[r'^no \S+\.json — nothing to check']),
                        g('skip', indeterminate_patterns=[r'^no \S+\.json — nothing to check'])])
    r = run(repo, cfg, write_post(repo))
    st = {x['name']: x['status'] for x in r['gates']}
    assert st == {'miss': 'indeterminate', 'skip': 'not_run'} and r['summary']['blocking'] == ['miss']


def test_repo_changed_during_check_blocks(repo):
    # #7 — 검사 중 레포 안 코드·원장이 바뀌면 옛 원장으로 검사한 결과에 새 해시가 붙는다
    gate(repo, 'mut', 'open("scripts/late.py", "w").write("x = 1\\n")\n')
    commit_all(repo, 'base')
    r = run(repo, config(repo, [g('mut')]), write_post(repo))
    assert not r['summary']['publish_ok']
    assert any('레포 안 코드' in x for x in r['summary']['integrity'])


def test_git_failure_is_not_missing_record(repo, tmp_path):
    gate(repo, 'ok', PASS)
    cfg = config(repo, [g('ok')])
    p = cli(repo, 'verify', '--market', 'us', '--date', '2026-11-06', '--repo', str(tmp_path / 'not-a-repo'),
            '--rev', 'HEAD', cfg=cfg)
    assert p.returncode == 2


def test_record_prints_report_sha_and_preservation(repo):
    gate(repo, 'ok', PASS)
    cfg = config(repo, [g('ok')])
    (repo / 'data').mkdir()
    html = write_post(repo)
    p = cli(repo, *record_args(repo, html), cfg=cfg)
    assert 'report_sha256=' in p.stdout
    rec = json.load(open(repo / 'verification' / 'us' / '2026-11-06.json', encoding='utf-8'))
    # datadir 이 레포 안이면 같은 파일을 커밋 경로로 참조한다
    assert rec['inputs']['files'][0]['ref'] == 'repo:ws/market_data.json'
    assert rec['preservation']['workspace_only'] == 0
    assert rec['repo_inputs']['digest'] and 'scripts' in rec['repo_inputs']['paths']


def test_symlinks_in_scripts_do_not_break_the_pairing(repo):
    # 모의 발행(실제 검사기)에서 나온 결함 — scripts/<p>/AGENTS.md 는 심볼릭 링크다. 작업 폴더 다이제스트가 링크
    # 대상 내용을 해시하면 git 이 저장한 링크 blob 과 달라 record → verify 가 영영 맴돈다
    gate(repo, 'ok', PASS)
    (repo / 'scripts' / 'CLAUDE.md').write_text('doc\n')
    os.symlink('CLAUDE.md', repo / 'scripts' / 'AGENTS.md')
    cfg = config(repo, [g('ok')])
    commit_all(repo, 'base')
    html = write_post(repo)
    assert cli(repo, *record_args(repo, html), cfg=cfg).returncode == 0
    subprocess.run(['git', '-C', str(repo), 'add', '-A'], check=True)
    p = verify(repo, '--index', cfg=cfg)
    assert p.returncode == 0, p.stdout
    commit_all(repo)
    assert verify(repo, '--rev', 'HEAD', cfg=cfg).returncode == 0


def test_worktree_digest_does_not_touch_the_real_index(repo):
    gate(repo, 'ok', PASS)
    commit_all(repo, 'base')
    (repo / 'scripts' / 'new.py').write_text('x = 1\n')
    before = subprocess.run(['git', '-C', str(repo), 'status', '--porcelain'], capture_output=True, text=True).stdout
    R.repo_digest(str(repo), 'us', 'posts/2026-11-06.html', 'worktree')
    after = subprocess.run(['git', '-C', str(repo), 'status', '--porcelain'], capture_output=True, text=True).stdout
    assert before == after and '?? scripts/new.py' in after


def test_exit0_contracts_with_real_patterns(repo):
    # 3회차 — 공백 있는 경로, 손상된 입력 경고, 블록 없음(볼 것 없음)을 실제 설정의 패턴으로
    real = {g['name']: g for g in R.load_config(os.path.join(SCRIPTS, '..', 'config', 'prepub_gates.json'))
            ['markets']['us']['gates']}
    pats = real['check_price_context']['indeterminate_patterns']
    gate(repo, 'a', 'print("no /tmp/my work/market_data.json — nothing to check")\n')
    gate(repo, 'b', 'import sys\nprint("WARN: could not read x/market_data.json: bad", file=sys.stderr)\n')
    gate(repo, 'c', 'print("session block absent in market_data.json — nothing to check")\n')
    cfg = config(repo, [g(n, indeterminate_patterns=pats) for n in 'abc'])
    st = {x['name']: x['status'] for x in run(repo, cfg, write_post(repo))['gates']}
    assert st == {'a': 'indeterminate', 'b': 'indeterminate', 'c': 'not_run'}


def test_check_session_says_when_there_is_nothing_to_check(tmp_path):
    d = tmp_path / 'd'
    d.mkdir()
    (d / 'market_data.json').write_text(json.dumps({'report_date': '2026-11-06'}))
    h = tmp_path / '2026-11-06.html'
    h.write_text('<p>x</p>')
    p = subprocess.run([sys.executable, os.path.join(SCRIPTS, 'check_session.py'), '--html', str(h), '--datadir',
                        str(d), '--market', 'us'], capture_output=True, text=True)
    assert p.returncode == 0 and 'nothing to check' in p.stdout


def test_movers_without_data(tmp_path):
    # 4회차 — 자료 없이 문단이 있으면 판정 불가(필수라 보류), 문단도 없으면 실행 안 함
    cfg_real = R.load_config(os.path.join(SCRIPTS, '..', 'config', 'prepub_gates.json'))
    spec = next(g for g in cfg_real['markets']['us']['gates'] if g['name'] == 'check_movers')
    d = tmp_path / 'd'
    d.mkdir()
    repo = os.path.dirname(SCRIPTS)
    for body, want in (('<p data-mover="g1">현대건설 -7.77%</p>', 'indeterminate'),
                       ("<p class='x' data-mover = 'g1'>현대건설 -7.77%</p>", 'indeterminate'),   # 5회차
                       ('<p hidden data-mover="g1">x</p>', 'not_run'), ('<p>x</p>', 'not_run')):
        h = tmp_path / '2026-11-06.html'
        h.write_text(body)
        r = R._exec(spec, dict(repo=repo, datadir=str(d), date='2026-11-06'), str(h), 60)
        assert r['status'] == want, (body, r)


def test_partial_check_is_not_verified(repo):
    gate(repo, 'm', 'import sys\nprint("WARN: econ_indicators.json 이 없거나 읽을 수 없다 — 건너뛴다", file=sys.stderr)\n'
                    'print("매크로 게이트 통과")\n')
    r = run(repo, config(repo, [g('m', partial_patterns=[r'econ_indicators\.json 이 없거나 읽을 수 없다'])]),
            write_post(repo))
    assert r['gates'][0]['status'] == 'partial' and r['summary']['publish_ok'] and not r['summary']['verified']
