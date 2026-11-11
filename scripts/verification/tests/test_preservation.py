"""입력 보존 참조(`record._preservation`) — 2026-11-11.

막는 것: 레포 이력에 같은 바이트가 있는 입력을 「작업 공간 전용」으로 세는 것(11/10 US: telegram.json·macro.json),
그리고 반대로 되살릴 수 없는 참조(로컬에만 있는 커밋, 옛 blob)를 「보존됨」으로 적는 것.
"""
import hashlib
import os

from review.tests import prepub_fixture as F
from verification import record as R
from verification import repo_check as C

DATE = '2026-11-10'
OLD, NEW = '{"book": "old"}\n', '{"book": "new"}\n'


def sha(t):
    return hashlib.sha256(t.encode()).hexdigest()


def setup(tmp_path, push=True):
    """레포(어제 판 macro.json 이 커밋돼 있다) + 레포 밖 작업 공간. push=True 면 origin/main 이 그 커밋을 가리킨다."""
    repo = F.init(tmp_path)
    F.write(repo, 'data/macro.json', OLD)
    base = F.commit(repo, 'Add 2026-11-09 brief')
    if push:
        F.git(repo, 'update-ref', 'refs/remotes/origin/main', base)
    ws = tmp_path / 'ws'
    ws.mkdir()
    (ws / 'macro.json').write_text(OLD)          # 루틴 STEP 1 이 복사한 어제 책
    (ws / 'market_data.json').write_text('{"a": 1}\n')
    F.write(repo, 'data/macro.json', NEW)        # 게이트 뒤 macro_next → data/macro.json 승격(아직 커밋 전)
    return repo, ws, base


def pres(repo, ws, **kw):
    ctx = dict(repo=str(repo), datadir=str(ws), date=DATE, **kw)
    inputs = R._inputs(ctx)
    p = R._preservation(inputs, ctx)
    return {f['path']: f['ref'] for f in inputs['files']}, p


def test_promoted_macro_book_refers_to_the_pushed_commit(tmp_path):
    repo, ws, base = setup(tmp_path)
    refs, p = pres(repo, ws)
    assert refs['<datadir>/macro.json'] == f'git:{base}:data/macro.json'
    assert refs['<datadir>/market_data.json'] == 'repo:data/market_data.json'
    assert p['workspace_only'] == 0


def test_macro_book_only_in_a_local_commit_stays_workspace_only(tmp_path):
    # 루틴의 미푸시 커밋은 pull --rebase 로 sha 가 바뀐다 — 그 참조는 GitHub 에서 끊긴다
    repo, ws, _ = setup(tmp_path, push=False)
    refs, p = pres(repo, ws)
    assert refs['<datadir>/macro.json'] == 'workspace-only' and p['workspace_only'] == 1


def test_amended_publish_commit_still_finds_the_previous_book(tmp_path):
    # verify exit 1 → record 다시: 그때 HEAD 는 이미 승격된 책을 담은 발행 커밋이다
    repo, ws, base = setup(tmp_path)
    F.commit(repo, 'Add 2026-11-10 brief')
    refs, _ = pres(repo, ws)
    assert refs['<datadir>/macro.json'] == f'git:{base}:data/macro.json'


def test_old_blob_of_a_change_is_not_taken_as_that_commits_file(tmp_path):
    # codex 설계 검토 #1: C 에서 A→B 로 바뀌었으면 C:path 는 B 다. A 를 C 로 가리키면 발행 뒤 불일치가 된다
    repo = F.init(tmp_path)
    F.write(repo, 'data/macro.json', OLD)
    a = F.commit(repo, 'a')
    F.write(repo, 'data/macro.json', NEW)
    b = F.commit(repo, 'b')
    F.git(repo, 'update-ref', 'refs/remotes/origin/main', b)
    ws = tmp_path / 'ws'
    ws.mkdir()
    (ws / 'macro.json').write_text(OLD)
    F.write(repo, 'data/macro.json', '{"book": "newer"}\n')
    refs, _ = pres(repo, ws)
    assert refs['<datadir>/macro.json'] == f'git:{a}:data/macro.json'


def test_bytes_never_committed_stay_workspace_only(tmp_path):
    repo, ws, _ = setup(tmp_path)
    (ws / 'macro.json').write_text('{"book": "edited"}\n')
    refs, _ = pres(repo, ws)
    assert refs['<datadir>/macro.json'] == 'workspace-only'


def test_history_search_only_for_macro_book(tmp_path):
    # codex 설계 검토 #2: 입력 수천 개를 전부 이력에서 찾지 않는다
    repo, ws, base = setup(tmp_path)
    F.write(repo, 'data/macro_eval.json', OLD)
    F.commit(repo, 'eval')
    F.write(repo, 'data/macro_eval.json', NEW)
    (ws / 'macro_eval.json').write_text(OLD)
    refs, _ = pres(repo, ws)
    assert refs['<datadir>/macro_eval.json'] == 'workspace-only'


def test_git_failure_falls_back_to_workspace_only(tmp_path, monkeypatch):
    repo, ws, _ = setup(tmp_path)
    monkeypatch.setattr(R, '_git', lambda *a, **k: None)
    refs, _ = pres(repo, ws)
    assert refs['<datadir>/macro.json'] == 'workspace-only'


def test_workspace_telegram_copy_refers_to_committed_snapshot(tmp_path):
    repo, ws, _ = setup(tmp_path)
    tg = '{"report_date": "2026-11-10", "items": []}\n'
    F.write(repo, f'data/telegram/{DATE}.json', tg)
    (ws / 'telegram.json').write_text(tg)
    refs, _ = pres(repo, ws, tg=str(ws / 'telegram.json'))
    assert refs['<datadir>/telegram.json'] == f'repo:data/telegram/{DATE}.json'
    assert refs['<tg>/telegram.json'] == f'repo:data/telegram/{DATE}.json'


def test_kr_roots_keep_their_candidates(tmp_path):
    # KR 은 datadir 이 레포 안(kr/data) — --tg·--stance-next 후보가 그대로인지(codex 설계 검토 #5)
    repo = F.init(tmp_path)
    tg = '{"report_date": "2026-11-10"}\n'
    stance = '{"stance": 1}\n'
    F.write(repo, f'kr/data/telegram/{DATE}.json', tg)
    F.write(repo, 'kr/data/kr_stance.json', stance)
    F.write(repo, 'kr/data/kr_market.json', '{}\n')
    ws = tmp_path / 'ws'
    ws.mkdir()
    (ws / 'kr_telegram.json').write_text(tg)
    (ws / 'kr_stance_next.json').write_text(stance)
    refs, p = pres(repo, repo / 'kr' / 'data', tg=str(ws / 'kr_telegram.json'),
                   stance_next=str(ws / 'kr_stance_next.json'))
    assert refs['<tg>/kr_telegram.json'] == f'repo:kr/data/telegram/{DATE}.json'
    assert refs['<stance_next>/kr_stance_next.json'] == 'repo:kr/data/kr_stance.json'
    assert p['workspace_only'] == 0


# ── 맥(GitHub) 쪽 대조 ───────────────────────────────────────────────────

def publish_with(repo, ref, content=OLD):
    files = [{'path': '<datadir>/market_data.json', 'sha256': sha('{"a": 1}\n'), 'ref': 'repo:data/market_data.json'},
             {'path': '<datadir>/macro.json', 'sha256': sha(content), 'ref': ref}]
    import json
    c = F.publish(repo, workspace=False)
    p = os.path.join(str(repo), R.record_path('us', '2026-11-09'))
    rec = json.load(open(p, encoding='utf-8'))
    rec['inputs']['files'] = files
    F.write(repo, R.record_path('us', '2026-11-09'), json.dumps(rec, ensure_ascii=False))
    return F.commit(repo, 'record') if c else None


def check(repo, rev):
    return C.check(str(repo), 'us', '2026-11-09', rev)


def test_history_ref_matches(tmp_path):
    repo = F.init(tmp_path)
    F.write(repo, 'data/macro.json', OLD)
    base = F.commit(repo, 'book')
    F.write(repo, 'data/macro.json', NEW)
    r = check(repo, publish_with(repo, f'git:{base}:data/macro.json'))
    assert r['cats']['repo_inputs'] == C.MATCH and r['repo_input_count'] == 2
    assert r['cats']['workspace_inputs'] == C.NONE


def test_history_ref_with_other_bytes_is_mismatch(tmp_path):
    repo = F.init(tmp_path)
    F.write(repo, 'data/macro.json', OLD)
    base = F.commit(repo, 'book')
    r = check(repo, publish_with(repo, f'git:{base}:data/macro.json', content=NEW))
    assert r['cats']['repo_inputs'] == C.MISMATCH


def test_history_ref_not_an_ancestor_is_unknown(tmp_path):
    repo = F.init(tmp_path)
    F.git(repo, 'checkout', '-q', '-b', 'side')
    F.write(repo, 'data/macro.json', OLD)
    side = F.commit(repo, 'side book')
    F.git(repo, 'checkout', '-q', 'main')
    r = check(repo, publish_with(repo, f'git:{side}:data/macro.json'))
    assert r['cats']['repo_inputs'] == C.UNKNOWN
    assert any('조상' in w for w in r['why'])


def test_history_ref_missing_object_is_unknown(tmp_path):
    repo = F.init(tmp_path)
    r = check(repo, publish_with(repo, 'git:' + 'ab' * 20 + ':data/macro.json'))
    assert r['cats']['repo_inputs'] == C.UNKNOWN


def test_history_ref_malformed_is_unknown(tmp_path):
    repo = F.init(tmp_path)
    r = check(repo, publish_with(repo, 'git:HEAD:data/macro.json'))     # 40자 sha 만 받는다
    assert r['cats']['repo_inputs'] == C.UNKNOWN


def test_history_ref_git_failure_raises(tmp_path, monkeypatch):
    repo = F.init(tmp_path)
    F.write(repo, 'data/macro.json', OLD)
    base = F.commit(repo, 'book')
    rev = publish_with(repo, f'git:{base}:data/macro.json')
    real = R._git

    def flaky(repo_, *args, **kw):
        if args[:1] == ('merge-base',):
            return None
        return real(repo_, *args, **kw)
    monkeypatch.setattr(R, '_git', flaky)
    import pytest
    with pytest.raises(C.ReadError):
        check(repo, rev)


def test_unpushed_copy_of_the_bytes_does_not_hide_the_pushed_one(tmp_path):
    # codex 구현 검토 #1: origin 에 A(old)→B(new), 로컬 미푸시 C(old) — C 에서 멈추지 말고 A 를 찾는다
    repo = F.init(tmp_path)
    F.write(repo, 'data/macro.json', OLD)
    a = F.commit(repo, 'a')
    F.write(repo, 'data/macro.json', NEW)
    b = F.commit(repo, 'b')
    F.git(repo, 'update-ref', 'refs/remotes/origin/main', b)
    F.write(repo, 'data/macro.json', OLD)
    F.commit(repo, 'c local')
    F.write(repo, 'data/macro.json', NEW)
    ws = tmp_path / 'ws'
    ws.mkdir()
    (ws / 'macro.json').write_text(OLD)
    refs, _ = pres(repo, ws)
    assert refs['<datadir>/macro.json'] == f'git:{a}:data/macro.json'


def test_history_ref_missing_path_says_why(tmp_path):
    repo = F.init(tmp_path)
    base = F.git(repo, 'rev-parse', 'HEAD')
    r = check(repo, publish_with(repo, f'git:{base}:data/nope.json'))
    assert r['cats']['repo_inputs'] == C.UNKNOWN
    assert any('파일이 없다' in w for w in r['why'])


def test_history_ref_in_shallow_clone_does_not_claim_not_ancestor(tmp_path):
    # codex 구현 검토 #2: 얕은 클론의 merge-base 1 은 이력 부족일 수 있다
    src = F.init(tmp_path)
    F.write(src, 'data/macro.json', OLD)
    base = F.commit(src, 'book')
    F.commit(src, 'mid')
    rev = publish_with(src, f'git:{base}:data/macro.json')
    import subprocess
    dst = tmp_path / 'shallow'
    subprocess.run(['git', 'clone', '-q', '--depth', '1', f'file://{src}', str(dst)], check=True)
    subprocess.run(['git', '-C', str(dst), 'fetch', '-q', '--depth', '1', 'origin', base], check=True)
    r = check(dst, rev)
    assert r['cats']['repo_inputs'] == C.UNKNOWN
    assert any('얕은 이력' in w for w in r['why'])
