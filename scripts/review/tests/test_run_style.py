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
