"""게이트 CLI — 임시 레포에서 실제로 git을 돌려 본다.

순수 로직은 test_queue·test_prose가 본다. 여기서 잡는 것은 그 둘이 원리적으로 못 보는 것,
즉 **git과 파일시스템이 끼어드는 자리**다. 커밋 전 작업 폴더 파일의 blob은 object DB에 없고
(초안이 여기서 틀렸다), origin과 작업 폴더가 갈리는 것이 운영의 기본 상태이며, `cat-file
--batch` 응답은 어긋날 수 있다.
"""

import json
import os
import subprocess
import sys

import pytest

from review.tests.blocks import CUR, PREV

HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GATE = os.path.join(HERE, 'review_gate.py')

PAGE = """<html><head><style>
.stance-tbl thead { display: none; }
  %s
%s
</style></head><body><div class="card">
<p><strong%s>동인.</strong> 유가가 %s.</p></div></body></html>
"""
OLD = PAGE % ('.card p, p { font-size:16px; }', PREV, '', '올랐다')
NEW = PAGE % ('p { font-size:16px; }', CUR, ' class="p-label"', '올랐다')
EDITED = PAGE % ('p { font-size:16px; }', CUR, ' class="p-label"', '내렸다')
SMUGGLED = NEW.replace(CUR, CUR + '\nhtml, body { display:none !important; }')


def run(repo, *args):
    return subprocess.run([sys.executable, GATE, *args], cwd=repo,
                          capture_output=True, text=True)


def git(repo, *args):
    return subprocess.run(['git', '-C', repo, *args], capture_output=True, text=True,
                          check=True)


def write(repo, rel, text):
    full = os.path.join(repo, rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, 'w', encoding='utf-8') as fh:
        fh.write(text)


def ledger_of(repo):
    with open(os.path.join(repo, 'reviews/index.json'), encoding='utf-8') as fh:
        return json.load(fh)


def entry_of(repo, path='posts/2026-08-21.html'):
    return ledger_of(repo)['reviewed'][path]


@pytest.fixture()
def repo(tmp_path):
    """운영과 같은 모양 — bare origin 이 있고, 옛 판 한 편이 검토까지 끝나 있다."""
    origin = str(tmp_path / 'origin.git')
    root = str(tmp_path / 'site')
    subprocess.run(['git', 'init', '-q', '--bare', '-b', 'main', origin], check=True)
    subprocess.run(['git', 'clone', '-q', origin, root], check=True)
    git(root, 'config', 'user.email', 't@t')
    git(root, 'config', 'user.name', 't')
    write(root, 'posts/2026-08-21.html', OLD)
    git(root, 'add', '-A')
    git(root, 'commit', '-qm', 'first')
    git(root, 'push', '-q', 'origin', 'main')
    assert run(root, 'mark', 'posts/2026-08-21.html', '--findings', '2').returncode == 0
    # 원장도 커밋해 둔다 — 안 그러면 뒤의 `reset --hard`가 검토 기록을 함께 날린다.
    git(root, 'add', '-A')
    git(root, 'commit', '-qm', 'ledger')
    git(root, 'push', '-q', 'origin', 'main')
    return root


def publish(repo, rel, text, message='typeset'):
    """origin에만 올린다 — 루틴이 발행하고 노트북은 아직 모르는 상태."""
    write(repo, rel, text)
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', message)
    git(repo, 'push', '-q', 'origin', 'main')


def test_a_reviewed_page_is_quiet(repo):
    out = run(repo, 'pending')
    assert out.returncode == 0 and '미검토 없음' in out.stdout


def test_marking_records_what_was_read(repo):
    entry = entry_of(repo)
    assert entry['findings'] == 2 and entry['sha']
    assert 'accepted' not in entry


def test_a_typography_change_in_the_working_tree_is_not_queued(repo):
    """커밋 전 파일 — 그 blob은 object DB에 없다. 초안은 여기서 매번 「수정됨」이었다."""
    write(repo, 'posts/2026-08-21.html', NEW)
    out = run(repo, 'pending')
    assert '미검토 없음' in out.stdout, out.stdout
    assert '조판만 바뀐 1건' in out.stdout


def test_a_prose_change_in_the_working_tree_is_queued(repo):
    write(repo, 'posts/2026-08-21.html', EDITED)
    out = run(repo, 'pending')
    assert out.returncode == 1 and 'posts/2026-08-21.html — 수정됨' in out.stdout


def test_a_published_typography_change_is_not_queued(repo):
    """origin에만 있는 판 — 노트북이 뒤처져 있어도 본다."""
    publish(repo, 'posts/2026-08-21.html', NEW)
    git(repo, 'reset', '-q', '--hard', 'HEAD~1')
    assert '미검토 없음' in run(repo, 'pending').stdout


def test_css_smuggled_into_a_published_block_is_queued(repo):
    """등록되지 않은 블록은 조판이라 부르지 않는다."""
    publish(repo, 'posts/2026-08-21.html', SMUGGLED)
    git(repo, 'reset', '-q', '--hard', 'HEAD~1')
    got = json.loads(run(repo, 'pending', '--json').stdout)
    assert [p['reason'] for p in got['unavailable']] == ['판정 불가']
    assert got['typography'] == []


def test_pending_never_writes_the_ledger(repo):
    write(repo, 'posts/2026-08-21.html', NEW)
    before = ledger_of(repo)
    run(repo, 'pending')
    run(repo, 'pending', '--hook')
    assert ledger_of(repo) == before


def test_the_hook_always_exits_zero_even_with_a_queue(repo):
    write(repo, 'posts/2026-09-01.html', NEW)
    out = run(repo, 'pending', '--hook')
    assert out.returncode == 0 and '미검토 발행본 1건' in out.stdout


def test_json_separates_the_three_verdicts(repo):
    write(repo, 'posts/2026-08-21.html', NEW)
    write(repo, 'posts/2026-09-01.html', NEW)
    got = json.loads(run(repo, 'pending', '--json').stdout)
    assert [p['path'] for p in got['pending']] == ['posts/2026-09-01.html']
    assert [p['path'] for p in got['typography']] == ['posts/2026-08-21.html']
    assert got['unavailable'] == []


def test_refresh_is_a_dry_run_by_default(repo):
    write(repo, 'posts/2026-08-21.html', NEW)
    before = ledger_of(repo)
    assert 'dry-run' in run(repo, 'refresh').stdout
    assert ledger_of(repo) == before


def test_refresh_apply_keeps_the_reviewed_version_untouched(repo):
    """`sha`는 사람이 읽은 판이다. refresh가 그 자리를 옮기면 원장이 거짓말을 한다."""
    before = entry_of(repo)
    write(repo, 'posts/2026-08-21.html', NEW)
    assert run(repo, 'refresh', '--apply').returncode == 0
    after = entry_of(repo)
    assert after['sha'] == before['sha'] and after['at'] == before['at']
    assert after['findings'] == before['findings']
    assert after['accepted'][0]['reason'] == 'typography'
    assert after['accepted'][0]['sha'] != before['sha']


def test_refresh_is_stable_when_origin_and_the_working_tree_differ(repo):
    """origin 판과 작업 폴더 판이 둘 다 동등하면 둘 다 담는다 — 서로를 밀어내면 안 된다."""
    write(repo, 'posts/2026-08-21.html', NEW)
    run(repo, 'refresh', '--apply')
    publish(repo, 'posts/2026-08-21.html', NEW)
    run(repo, 'refresh', '--apply')
    first = json.dumps(entry_of(repo).get('accepted'), sort_keys=True)
    run(repo, 'refresh', '--apply')
    assert json.dumps(entry_of(repo).get('accepted'), sort_keys=True) == first
    assert '미검토 없음' in run(repo, 'pending').stdout


def test_refresh_never_touches_a_new_page(repo):
    write(repo, 'posts/2026-09-01.html', NEW)
    run(repo, 'refresh', '--apply')
    assert 'posts/2026-09-01.html' not in ledger_of(repo)['reviewed']
    assert run(repo, 'pending').returncode == 1


def test_an_accepted_version_stays_quiet_afterwards(repo):
    write(repo, 'posts/2026-08-21.html', NEW)
    run(repo, 'refresh', '--apply')
    out = run(repo, 'pending')
    assert '미검토 없음' in out.stdout and '조판만 바뀐' not in out.stdout


def test_a_locked_ledger_stops_a_writer(repo, tmp_path):
    import fcntl
    fd = os.open(os.path.join(repo, 'reviews/.index.lock'),
                 os.O_CREAT | os.O_WRONLY, 0o644)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        out = run(repo, 'mark', 'posts/2026-08-21.html')
        assert out.returncode != 0 and '잠겨 있다' in out.stderr
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def test_a_stale_lock_file_does_not_block_forever(repo):
    """프로세스가 죽어 파일만 남은 경우 — 커널이 flock을 풀었으므로 통과해야 한다."""
    open(os.path.join(repo, 'reviews/.index.lock'), 'w').close()
    assert run(repo, 'mark', 'posts/2026-08-21.html').returncode == 0


def test_a_baseline_we_cannot_reach_is_reported_not_swallowed(repo):
    """원장이 어느 저장소에도 없는 blob을 가리키면 조용히 통과시키지 않는다."""
    book = ledger_of(repo)
    book['reviewed']['posts/2026-08-21.html']['sha'] = '0' * 40
    with open(os.path.join(repo, 'reviews/index.json'), 'w', encoding='utf-8') as fh:
        json.dump(book, fh)
    write(repo, 'posts/2026-08-21.html', NEW)
    got = json.loads(run(repo, 'pending', '--json').stdout)
    # 발행된 판과 작업 폴더 판 둘 다 판정할 수 없다 — 둘 다 남는다.
    assert {p['reason'] for p in got['unavailable']} == {'판정 불가'}
    assert {p['path'] for p in got['pending']} == {'posts/2026-08-21.html'}
    assert len(got['unavailable']) == 2


def test_a_corrupt_sha_in_the_ledger_does_not_take_the_hook_down(repo):
    book = ledger_of(repo)
    book['reviewed']['posts/2026-08-21.html']['sha'] = 'not a sha'
    with open(os.path.join(repo, 'reviews/index.json'), 'w', encoding='utf-8') as fh:
        json.dump(book, fh)
    write(repo, 'posts/2026-08-21.html', NEW)
    out = run(repo, 'pending', '--hook')
    assert out.returncode == 0 and '확인 실패' not in out.stdout
