"""러너 한 tick 이 문체 수정까지 잇는가 — 가짜 codex 가 `prose_in.txt` 를 실제로 고친다.

codex 호출은 글당 한 번 그대로다. 그 한 번이 문장을 고치고 지적을 낸다. 푸시가 끝난 뒤에만
초안이 새 판 이름을 받고, 뒤따르는 Claude 정정은 그 새 판을 원래 발행 커밋의 데이터로 본다.
"""
import json
import os

import review_gate as gate
from review import style_pass
from review.tests.test_run_cli import repo, git, POST, KR_POST, TODAY  # noqa: F401
from review.tests.test_run_correct import invoke


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _apply_on(request, monkeypatch):
    """아래 반영 경로 테스트는 반영을 다시 켤 때의 계약이다. 2026-10-13 부터 기본값은
    반영 중지(APPLY=False) — 기본값 동작은 test_default_* 가 본다."""
    if not request.node.name.startswith(('test_default_', 'test_findings_only_')):
        monkeypatch.setattr(style_pass, 'APPLY', True)
        monkeypatch.setattr(gate, 'STYLE_REWRITE', True)   # 옛 고쳐 쓰기 경로 — 코드는 남겼다(2026-11-06)


def editing_codex(tmp_path, reply):
    path = tmp_path / 'codex'
    path.write_text(
        '#!/bin/sh\n'
        'cd "$(echo "$@" | tr " " "\\n" | grep -A1 -x -- -C | tail -1)" || exit 9\n'
        'echo "$@" | grep -q workspace-write || { echo "쓰기 권한 없이 불렸다" >&2; exit 5; }\n'
        'test -f .claude/agents/STYLE_EXEMPLARS.md || { echo "문장 표본이 없다" >&2; exit 6; }\n'
        "sed -i '' 's/유가가 올랐다\\./유가는 올랐다./' prose_in.txt\n"
        f'printf "{reply}"\n')
    path.chmod(0o755)
    return str(path)


def seed_refs(repo):
    full = os.path.join(repo, '.claude/agents/STYLE_EXEMPLARS.md')
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, 'w', encoding='utf-8') as fh:
        fh.write('표본\n')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'refs')
    git(repo, 'push', '-q', 'origin', 'main')


def remote_blob(repo, path):
    git(repo, 'fetch', '-q', 'origin')
    return git(repo, 'rev-parse', f'origin/main:{path}').stdout.strip()


def test_clean_style_pass_still_goes_to_claude_under_the_new_version(repo, tmp_path, monkeypatch):
    """「지적 없음」도 Claude 가 확인한 뒤 원장에 남긴다(REVIEW_GATE, 2026-09-10 지시)."""
    seed_refs(repo)
    monkeypatch.setattr(style_pass, 'gate_commands', lambda *a: [])
    monkeypatch.setattr(gate, 'CODEX', editing_codex(tmp_path, '검토 판본: 윤문 후\\n지적 없음'))
    before = remote_blob(repo, POST)
    called = []
    assert invoke(repo, monkeypatch,
                  lambda root, item, *a: called.append((item.path, item.sha)) or ('', None)) == 0
    after = remote_blob(repo, POST)
    assert after != before
    assert '유가는 올랐다.' in git(repo, 'show', f'origin/main:{POST}').stdout
    assert (POST, after) in called
    assert os.path.exists(os.path.join(repo, 'reviews/pending', f'{TODAY}-us-{after[:7]}.md'))
    log = json.load(open(os.path.join(repo, 'reviews/runner.json')))['style_log']
    assert {x['path'] for x in log} == {POST, KR_POST} and all(x['to'] for x in log)


def test_findings_go_to_claude_under_the_new_version(repo, tmp_path, monkeypatch):
    seed_refs(repo)
    monkeypatch.setattr(style_pass, 'gate_commands', lambda *a: [])
    monkeypatch.setattr(gate, 'CODEX', editing_codex(tmp_path, '검토 판본: 윤문 후\\n1. 지적'))
    seen = []

    def correct(root, item, draft, commit, timeout):
        seen.append((item.path, item.sha, draft))
        return 'checked', None
    invoke(repo, monkeypatch, correct)
    styled = remote_blob(repo, POST)
    assert (POST, styled, '검토 판본: 윤문 후\n1. 지적') in seen
    # 근거는 여전히 원래 발행 커밋 — 문체 커밋이 아니다.
    commit = gate.publish_commit(repo, POST, styled)
    assert not style_pass.is_style_commit(git(repo, 'log', '-1', '--format=%B', commit).stdout)


def test_rejected_edit_keeps_the_draft_on_the_published_version(repo, tmp_path, monkeypatch):
    seed_refs(repo)
    monkeypatch.setattr(style_pass, 'gate_commands',
                        lambda *a: [['sh', '-c', 'grep -q 유가는 "$0" && exit 1 || exit 0', a[1]]])
    monkeypatch.setattr(gate, 'CODEX', editing_codex(tmp_path, '검토 판본: 윤문 후\\n지적 없음'))
    before = remote_blob(repo, POST)
    invoke(repo, monkeypatch, lambda *a: ('checked', None))
    assert remote_blob(repo, POST) == before
    log = json.load(open(os.path.join(repo, 'reviews/runner.json')))['style_log']
    assert all(x['to'] == '' and '게이트 거부' in x['reason'] for x in log)


def test_a_rejected_edit_tells_claude_the_findings_quote_unpublished_text(repo, tmp_path, monkeypatch):
    """지적은 codex 가 고친 문장 기준인데 공개판은 원문이다 — 인용이 안 맞는다고 기각하면 안 된다
    (2026-09-30 codex 구현 검토)."""
    seed_refs(repo)
    monkeypatch.setattr(style_pass, 'gate_commands',
                        lambda *a: [['sh', '-c', 'grep -q 유가는 "$0" && exit 1 || exit 0', a[1]]])
    monkeypatch.setattr(gate, 'CODEX', editing_codex(tmp_path, '검토 판본: 윤문 후\\n1. 지적'))
    seen = []
    invoke(repo, monkeypatch, lambda root, item, draft, *a: seen.append(draft) or ('checked', None))
    assert seen and all(d.startswith(gate.STYLE_NOTE_HEAD) and '공개되지 않았다' in d
                        and d.endswith('검토 판본: 윤문 후\n1. 지적') for d in seen)


def test_a_fully_applied_edit_leaves_the_draft_as_codex_wrote_it():
    assert gate._style_note(style_pass.Result(sha='abc', skipped=())) == ''


def test_a_partly_applied_edit_names_the_paragraphs_left_as_written():
    note = gate._style_note(style_pass.Result(sha='abc', skipped=(('P003', 'x'), ('P007', 'y'))))
    assert note.startswith(gate.STYLE_NOTE_HEAD) and 'P003' in note and 'P007' in note


def test_default_runner_publishes_nothing_and_logs_the_proposal(repo, tmp_path, monkeypatch):
    """반영 중지(2026-10-13): codex 가 고쳐도 공개판은 원문, 정정 단계에는 「공개되지 않았다」,
    러너 로그에는 바뀌었을 문단과 기록 경로가 남는다."""
    assert style_pass.APPLY is False
    monkeypatch.setattr(gate, 'STYLE_REWRITE', True)
    seed_refs(repo)
    monkeypatch.setattr(style_pass, 'gate_commands', lambda *a: [])
    monkeypatch.setattr(gate, 'CODEX', editing_codex(tmp_path, '검토 판본: 윤문 후\\n1. 지적'))
    before = remote_blob(repo, POST)
    seen = []
    invoke(repo, monkeypatch, lambda root, item, draft, *a: seen.append(draft) or ('checked', None))
    assert remote_blob(repo, POST) == before
    assert seen and all('공개되지 않았다' in d for d in seen)
    log = json.load(open(os.path.join(repo, 'reviews/runner.json')))['style_log']
    mine = [x for x in log if x['path'] == POST]
    assert mine and mine[-1]['to'] == '' and mine[-1]['proposed'] and mine[-1]['proposal']
    assert os.path.isfile(mine[-1]['proposal'])


# ---- 2026-11-06 C안: 발행 뒤 codex 문체 몫은 지적만


def findings_codex(tmp_path, reply):
    path = tmp_path / 'codex'
    path.write_text(
        '#!/bin/sh\n'
        'echo "$@" | grep -q read-only || { echo "읽기 전용이 아니다" >&2; exit 5; }\n'
        'cd "$(echo "$@" | tr " " "\\n" | grep -A1 -x -- -C | tail -1)" || exit 9\n'
        'test ! -f prose_in.txt || { echo "고쳐 쓰기 파일이 준비됐다" >&2; exit 7; }\n'
        f'printf "{reply}"\n')
    path.chmod(0o755)
    return str(path)


def test_findings_only_is_the_default():
    assert gate.STYLE_REWRITE is False


def test_findings_only_publishes_nothing_and_keeps_findings_out_of_the_draft(repo, tmp_path, monkeypatch):
    seed_refs(repo)
    called = []
    monkeypatch.setattr(style_pass, 'apply', lambda *a, **k: called.append(1))
    reply = ('1. 사실 지적\\n%s\\n- [끊긴 흐름] 「유가가 올랐다」 — 짧은 문장이 이어진다 / 이유와 잇는다\\n'
             '- [이상한분류] 「x」 — y\\n' % gate.STYLE_FINDINGS_HEAD)
    monkeypatch.setattr(gate, 'CODEX', findings_codex(tmp_path, reply))
    before = remote_blob(repo, POST)
    seen = []
    invoke(repo, monkeypatch, lambda root, item, draft, *a: seen.append((item.path, item.sha, draft)) or ('checked', None))
    assert remote_blob(repo, POST) == before and not called
    mine = [d for p, sha, d in seen if p == POST]
    assert mine and all(gate.STYLE_FINDINGS_HEAD not in d and '사실 지적' in d and '끊긴 흐름' not in d
                        for d in mine)
    assert all(sha == before for p, sha, _ in seen if p == POST)
    log = json.load(open(os.path.join(repo, 'reviews/runner.json')))['style_log']
    row = [x for x in log if x['path'] == POST][-1]
    assert set(row) == {'ts', 'path', 'sha', 'findings', 'by_kind'}
    assert row['findings'] == 2 and row['by_kind'] == {'끊긴 흐름': 1, '기타': 1}
    files = os.listdir(os.path.join(repo, gate.STYLE_FINDINGS))
    assert files
    rec = json.load(open(os.path.join(repo, gate.STYLE_FINDINGS, sorted(files)[0])))
    assert rec['findings'][0]['quote'] == '유가가 올랐다'
    assert not os.path.isdir(os.path.join(repo, style_pass.PROPOSALS))


def test_findings_only_without_marker_counts_zero(repo, tmp_path, monkeypatch):
    seed_refs(repo)
    monkeypatch.setattr(gate, 'CODEX', findings_codex(tmp_path, '지적 없음'))
    seen = []
    invoke(repo, monkeypatch, lambda root, item, draft, *a: seen.append(draft) or ('checked', None))
    # 표식이 없으면 문체 지적이 섞였을 수 있다고 초안 머리에 알린다(codex 구현 검토 #4)
    assert seen and all(d.startswith(gate.STYLE_MARKER_MISSING) and d.strip().endswith('지적 없음') for d in seen)
    log = json.load(open(os.path.join(repo, 'reviews/runner.json')))['style_log']
    assert all(x['findings'] == 0 and x['marker_missing'] for x in log)


def test_findings_only_caps_at_five():
    text = gate.STYLE_FINDINGS_HEAD + '\n' + '\n'.join('- [반복] 「a%d」 — b' % i for i in range(9))
    _, f = gate.split_style_findings(text)
    assert len(f) == gate.STYLE_FINDINGS_MAX


def test_findings_dir_is_git_ignored():
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    with open(os.path.join(root, '.gitignore'), encoding='utf-8') as fh:
        assert 'reviews/style_findings/' in fh.read().split()
