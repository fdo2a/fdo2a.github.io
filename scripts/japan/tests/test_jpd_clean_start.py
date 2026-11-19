"""일본 일간 시작 가드 — 임시 git 저장소와 가짜 origin 으로만 돈다(설계 20판 §6-3, §11-10).
거부할 때는 HEAD 도 파일도 그대로여야 한다. 되돌릴 수 있는 것은 실패한 발행의 산출물 7경로뿐이다."""
import subprocess
import sys
from pathlib import Path

from japan.tests import jpd_git as G
from japan.tests.jpd_git import KEY, S

GUARD = G.SCRIPTS / 'ci' / 'jpd_clean_start.py'
POST = f'japan/daily/{S}.html'
RUNS = f'japan/data/daily/runs/{S}.json'


def guard(clone, key=KEY, session=S):
    return subprocess.run([sys.executable, str(GUARD), '--root', str(clone), '--key', key, '--session', session],
                          capture_output=True, text=True)


def snapshot(clone):
    """HEAD 와 작업 폴더의 모든 파일 바이트(.git 제외)."""
    files = {p.relative_to(clone).as_posix(): p.read_bytes() for p in Path(clone).rglob('*')
             if p.is_file() and '.git' not in p.relative_to(clone).parts}
    return G.head(clone), files


def failed_publish_commit(clone, session=S, subject=None, extra=None):
    G.write(clone, f'japan/daily/{session}.html', '<html>old</html>\n')
    G.write(clone, f'japan/data/daily/runs/{session}.json', '{}\n')
    G.write(clone, 'japan/daily.json', '[{"date": "%s"}]\n' % session)
    for rel, text in (extra or {}).items():
        G.write(clone, rel, text)
    return G.commit_all(clone, subject or f'Add JP daily [{session}]')


def record(clone, session=S, run_id=None, skip=()):
    """실패한 발행의 기록 — 발행기가 실행 폴더에 남기는 publish.json 의 `written`(쓴 바이트의 해시)을
    지금 작업 폴더의 산출물 경로 바이트로 꾸민다. 가드는 이 기록과 바이트가 같은 변경만 되돌린다."""
    import hashlib
    import json
    outputs = lambda s: {f'japan/daily/{s}.html', f'japan/data/daily/{s}.json', f'japan/data/daily/runs/{s}.json',  # noqa: E731
                         f'japan/data/telegram/published/{s}.json', 'japan/data/history/jp_daily.jsonl',
                         'japan/daily.json', 'sitemap.xml'}
    run_id = run_id or f'jpd-{session}-1763460000-1'
    written = {}
    for rel in sorted(outputs(session)):
        p = Path(clone) / rel
        if p.is_file() and rel not in skip:
            written[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    G.write(clone, f'_workspace/jpd/{run_id}/publish.json',
            json.dumps({'run_id': run_id, 'session': session, 'written': written,
                        'entry': {'date': session, 'title': 't', 'headline': 'h'},
                        'history_row': {'session': session, 'nikkei': 1.0, 'prices': {}}}))
    return run_id


# ── 깨끗한 시작 ─────────────────────────────────────────────────────────

def test_clean_copy_equal_to_origin_starts(tmp_path):
    _, _, clone = G.setup(tmp_path)
    r = guard(clone)
    assert r.returncode == 0, r.stderr


def test_behind_only_is_fast_forwarded(tmp_path):
    _, seed, clone = G.setup(tmp_path)
    G.push_from_seed(seed, 'japan/data/daily/candidate/%s.json' % S, '{"v": 1}\n')
    r = guard(clone)
    assert r.returncode == 0, r.stderr
    assert G.head(clone) == G.head(seed)


def test_ignored_run_folder_is_not_dirt(tmp_path):
    _, _, clone = G.setup(tmp_path)
    G.write(clone, '_workspace/jpd/jpd-x/gates.json', '{}')
    assert guard(clone).returncode == 0


# ── 되돌리기(잠금 보유 + 실패한 발행 산출물만) ───────────────────────────

def test_failed_push_commit_is_reset_when_the_lock_is_ours(tmp_path):
    _, seed, clone = G.setup(tmp_path)
    G.acquire(clone)
    failed_publish_commit(clone)
    G.write(clone, f'japan/data/telegram/published/{S}.json', '{}\n')        # untracked leftover
    G.write(clone, 'sitemap.xml', '<urlset>changed</urlset>\n')              # tracked modification
    record(clone)
    r = guard(clone)
    assert r.returncode == 0, r.stderr + r.stdout
    assert G.head(clone) == G.head(seed) and G.status(clone) == ''
    assert not (clone / POST).exists() and not (clone / RUNS).exists()
    assert not (clone / f'japan/data/telegram/published/{S}.json').exists()


def test_leftover_files_without_a_commit_are_removed(tmp_path):
    _, seed, clone = G.setup(tmp_path)
    G.acquire(clone)
    G.write(clone, POST, 'x')
    G.write(clone, RUNS, '{}')
    G.write(clone, 'japan/data/history/jp_daily.jsonl', '{"session": "x"}\n')
    record(clone)
    assert guard(clone).returncode == 0
    assert G.status(clone) == '' and G.head(clone) == G.head(seed)


def test_diverged_failed_commit_is_reset_to_the_new_origin(tmp_path):
    _, seed, clone = G.setup(tmp_path)
    G.acquire(clone)
    failed_publish_commit(clone)
    record(clone)
    G.push_from_seed(seed, 'japan/data/news/daily/%s.json' % S, '{"items": []}\n')
    assert guard(clone).returncode == 0
    assert G.head(clone) == G.head(seed) and G.status(clone) == ''


# ── 거부: 아무것도 건드리지 않는다 ───────────────────────────────────────

def _refused(clone, **kw):
    before = snapshot(clone)
    r = guard(clone, **kw)
    assert r.returncode == 3, (r.returncode, r.stdout, r.stderr)
    assert snapshot(clone) == before
    return r


def test_no_lock_file_with_output_dirt_only_is_refused(tmp_path):
    _, _, clone = G.setup(tmp_path)
    G.write(clone, POST, 'x')
    assert '잠금' in _refused(clone).stderr


def test_no_lock_with_failed_commit_is_refused(tmp_path):
    _, _, clone = G.setup(tmp_path)
    failed_publish_commit(clone)
    _refused(clone)


def test_lock_file_that_is_not_the_remote_tip_is_refused(tmp_path):
    _, _, clone = G.setup(tmp_path)
    G.acquire(clone)
    own = clone / '.git' / f'run_lock_{KEY}'
    own.write_text('0' * 40 + '\n')
    G.write(clone, POST, 'x')
    _refused(clone)


def test_lock_of_another_session_does_not_count(tmp_path):
    _, _, clone = G.setup(tmp_path)
    G.acquire(clone, 'jpd-2026-11-17')
    G.write(clone, POST, 'x')
    _refused(clone)


def test_key_must_be_the_sessions_lock_name(tmp_path):
    _, _, clone = G.setup(tmp_path)
    G.acquire(clone, 'jpd-2026-11-17')
    G.write(clone, 'japan/daily/2026-11-17.html', 'x')
    _refused(clone, key='jpd-2026-11-17')          # session S, key of another session


def test_ahead_commit_with_another_subject_is_refused(tmp_path):
    _, _, clone = G.setup(tmp_path)
    G.acquire(clone)
    failed_publish_commit(clone, subject='fix: hand edit')
    _refused(clone)


def test_ahead_commit_touching_another_sessions_post_is_refused(tmp_path):
    _, _, clone = G.setup(tmp_path)
    G.acquire(clone)
    failed_publish_commit(clone, extra={'japan/daily/2026-11-17.html': 'other'})
    _refused(clone)


def test_ahead_commit_touching_a_script_is_refused(tmp_path):
    _, _, clone = G.setup(tmp_path)
    G.acquire(clone)
    failed_publish_commit(clone, extra={'scripts/x.py': 'x = 2\n'})
    _refused(clone)


def test_outside_modification_with_the_lock_held_is_refused(tmp_path):
    _, _, clone = G.setup(tmp_path)
    G.acquire(clone)
    G.write(clone, POST, 'x')
    G.write(clone, 'scripts/x.py', 'x = 2\n')
    assert 'scripts/x.py' in _refused(clone).stderr


def test_outside_untracked_file_is_refused_even_when_head_equals_origin(tmp_path):
    _, _, clone = G.setup(tmp_path)
    G.acquire(clone)
    G.write(clone, 'notes/todo.txt', 'x')
    _refused(clone)


def test_local_candidate_edit_is_kept_and_refused(tmp_path):
    """잠금 보유·HEAD == origin·산출물 경로 깨끗 + 수집 후보만 로컬 수정 → 거부, 파일 보존(10회차 #2)."""
    _, seed, clone = G.setup(tmp_path, files={f'japan/data/daily/candidate/{S}.json': '{"close": "3,824.00"}\n'})
    G.acquire(clone)
    G.write(clone, f'japan/data/daily/candidate/{S}.json', '{"close": "3,825.00"}\n')
    _refused(clone)
    assert '3,825.00' in (clone / f'japan/data/daily/candidate/{S}.json').read_text()


def test_human_working_copy_shape_is_refused(tmp_path):
    """사람 폴더를 본뜬 사본: 잠금 없음 + plan.md 수정 + 미추적 메모 + 산출물 경로 잔재."""
    _, _, clone = G.setup(tmp_path)
    G.write(clone, 'plan.md', '# plan\n- 오늘 할 일\n')
    G.write(clone, 'design-drafts/note.md', 'draft')
    G.write(clone, POST, 'draft post')
    failed_publish_commit(clone)
    _refused(clone)


def test_human_copy_even_with_its_lock_file_is_refused_for_plan_md(tmp_path):
    _, _, clone = G.setup(tmp_path)
    G.acquire(clone)
    G.write(clone, 'plan.md', '# plan\n- edit\n')
    _refused(clone)


def test_unreachable_origin_is_refused(tmp_path):
    remote, _, clone = G.setup(tmp_path)
    G.git(clone, 'remote', 'set-url', 'origin', str(tmp_path / 'nowhere.git'))
    _refused(clone)


def test_rebase_in_progress_is_refused(tmp_path):
    _, _, clone = G.setup(tmp_path)
    G.acquire(clone)
    (clone / '.git' / 'rebase-merge').mkdir()
    G.write(clone, POST, 'x')
    before = snapshot(clone)
    r = guard(clone)
    assert r.returncode == 3 and snapshot(clone) == before


def test_non_ascii_path_outside_is_seen(tmp_path):
    _, _, clone = G.setup(tmp_path)
    G.acquire(clone)
    G.write(clone, '메모.md', 'x')
    assert '메모.md' in _refused(clone).stderr


# ── 지적 3(codex 구현 1회차): 잠금이 있어도 실패한 발행 기록에 묶이지 않은 변경은 지우지 않는다 ──

def test_human_listing_edit_with_a_valid_lock_is_refused(tmp_path):
    """사람 폴더에서 이 세션 잠금을 얻었고 HEAD == origin/main, 목록만 손으로 고침 → 거부, 편집 보존."""
    _, _, clone = G.setup(tmp_path)
    G.acquire(clone)
    G.write(clone, 'japan/daily.json', '[{"date": "2026-11-18", "title": "손으로 쓴 제목"}]\n')
    _refused(clone)
    assert '손으로 쓴 제목' in (clone / 'japan/daily.json').read_text(encoding='utf-8')


def test_change_edited_after_the_failed_publish_is_refused(tmp_path):
    _, _, clone = G.setup(tmp_path)
    G.acquire(clone)
    failed_publish_commit(clone)
    record(clone)
    G.write(clone, 'japan/daily.json', '[{"date": "2026-11-18", "title": "발행 뒤 사람이 고침"}]\n')
    _refused(clone)


def test_committed_bytes_not_in_the_record_are_refused(tmp_path):
    _, _, clone = G.setup(tmp_path)
    G.acquire(clone)
    failed_publish_commit(clone)
    record(clone, skip={'japan/daily.json'})          # 기록에 없는 목록 바이트가 커밋에 있다
    _refused(clone)


def test_record_of_another_session_does_not_justify(tmp_path):
    _, _, clone = G.setup(tmp_path)
    G.acquire(clone)
    failed_publish_commit(clone)
    rid = record(clone)
    (clone / '_workspace' / 'jpd' / rid).rename(clone / '_workspace' / 'jpd' / 'jpd-2026-11-17-1-1')
    _refused(clone)


def test_deleting_a_shared_file_is_never_justified(tmp_path):
    _, _, clone = G.setup(tmp_path)
    G.acquire(clone)
    record(clone)
    (clone / 'sitemap.xml').unlink()
    _refused(clone)
