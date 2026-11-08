"""맥의 짝 확인(`verification.repo_check`) — 2단계(2026-11-08).

막는 거짓말: 작업 공간 입력을 못 봤는데 「일치」, 나중 설정으로 과거 기록을 비교해 거짓 불일치, 읽지 못한 것을 불일치로.
"""
import json

from review.tests import prepub_fixture as F
from verification import repo_check as C


def test_all_repo_side_match_but_workspace_input_is_unknown(tmp_path):
    repo = F.init(tmp_path)
    c = F.publish(repo)
    r = C.check(str(repo), 'us', '2026-11-09', c)
    assert r['cats']['post'] == C.MATCH and r['cats']['gates'] == C.MATCH
    assert r['cats']['scripts'] == C.MATCH and r['cats']['repo_digest'] == C.MATCH
    assert r['cats']['repo_inputs'] == C.MATCH
    assert r['cats']['workspace_inputs'] == C.UNKNOWN and r['workspace_only'] == 1
    assert r['overall'] == C.PARTIAL                     # 「일치」라고 하지 않는다


def test_everything_visible_is_match(tmp_path):
    repo = F.init(tmp_path)
    c = F.publish(repo, workspace=False)
    r = C.check(str(repo), 'us', '2026-11-09', c)
    assert r['overall'] == C.MATCH and r['cats']['workspace_inputs'] == C.NONE


def test_later_config_does_not_break_old_record(tmp_path):
    # codex 설계 검토 #2 — 검사기가 늘어도 그 커밋의 설정으로 비교한다
    repo = F.init(tmp_path)
    c = F.publish(repo, workspace=False)
    cfg = json.loads(json.dumps(F.CONFIG))
    cfg['markets']['us']['gates'].append({'name': 'new_gate', 'script': 'scripts/g1.py'})
    F.write(repo, 'config/prepub_gates.json', json.dumps(cfg))
    later = F.commit(repo, 'add gate')
    assert C.check(str(repo), 'us', '2026-11-09', c)['overall'] == C.MATCH
    assert C.check(str(repo), 'us', '2026-11-09', later)['cats']['gates'] == C.MISMATCH


def test_post_hash_mismatch(tmp_path):
    repo = F.init(tmp_path)
    c = F.publish(repo, workspace=False)
    F.write(repo, 'posts/2026-11-09.html', '<p>바뀐 글</p>')
    bad = F.commit(repo, 'same commit tampering')
    # 기록은 c 에 있고 bad 에서도 그대로 — bad 기준으로 보면 글이 다르다
    r = C.check(str(repo), 'us', '2026-11-09', bad)
    assert r['cats']['post'] == C.MISMATCH and r['overall'] == C.MISMATCH


def test_script_changed_is_mismatch(tmp_path):
    repo = F.init(tmp_path)
    F.publish(repo, workspace=False)
    F.write(repo, 'scripts/g1.py', 'print("changed")\n')
    c2 = F.commit(repo, 'change')
    r = C.check(str(repo), 'us', '2026-11-09', c2)
    assert r['cats']['scripts'] == C.MISMATCH and r['overall'] == C.MISMATCH


def test_unreadable_config_is_unknown_not_mismatch(tmp_path):
    repo = F.init(tmp_path)
    F.publish(repo, workspace=False)
    F.write(repo, 'config/prepub_gates.json', '{broken')
    c2 = F.commit(repo, 'break config')
    r = C.check(str(repo), 'us', '2026-11-09', c2)
    assert r['cats']['gates'] == C.UNKNOWN and r['cats']['post'] == C.UNKNOWN
    assert r['overall'] != C.MATCH


def test_unreadable_record_is_unknown(tmp_path):
    repo = F.init(tmp_path)
    F.publish(repo, workspace=False)
    F.write(repo, 'verification/us/2026-11-09.json', '{broken')
    c2 = F.commit(repo, 'break record')
    r = C.check(str(repo), 'us', '2026-11-09', c2)
    assert r['overall'] == C.UNKNOWN


def test_repo_input_changed_is_mismatch(tmp_path):
    repo = F.init(tmp_path)
    F.publish(repo, workspace=False)
    F.write(repo, 'data/market_data.json', '{"a": 2}\n')
    c2 = F.commit(repo, 'data')
    r = C.check(str(repo), 'us', '2026-11-09', c2)
    assert r['cats']['repo_inputs'] == C.MISMATCH


def test_missing_repo_input_blob_is_unknown(tmp_path):
    repo = F.init(tmp_path)
    F.publish(repo, workspace=False)
    F.git(repo, 'rm', '-q', 'data/market_data.json')
    c2 = F.commit(repo, 'rm data')
    r = C.check(str(repo), 'us', '2026-11-09', c2)
    assert r['cats']['repo_inputs'] == C.UNKNOWN and r['overall'] == C.PARTIAL


def test_kr_record(tmp_path):
    repo = F.init(tmp_path)
    c = F.publish(repo, market='kr', workspace=False)
    assert C.check(str(repo), 'kr', '2026-11-09', c)['overall'] == C.MATCH


def test_routine_verify_untouched():
    # 루틴 경로는 바꾸지 않는다 — 맥 확인은 별도 모듈이다(codex 설계 검토 #10)
    from verification import record as R
    import inspect
    assert 'repo_check' not in inspect.getsource(R)
