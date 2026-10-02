"""러너 한 tick — 주간·월간·일본도 발행 뒤 codex 문체 수정을 받는다 (2026-10-01 사용자 지시).

가짜 codex 는 스냅샷에 그 글의 근거 파일(집계·recap·스코어카드·인사이트 / 일본 진단·뉴스)이
놓였는지 보고 `prose_in.txt` 를 고친다. 게이트 명령은 실제 목록을 만들되, 그 근거 경로가 실제로
꺼내져 있는지만 확인하고 돌리지는 않는다. 사실 정정(Claude)은 일간만이다.
"""
import json
import os
import subprocess
from datetime import date, timedelta

import pytest

import review_gate as gate
from review import kinds, style_pass
from review.runner import today_kst
from review.tests.test_run_cli import PAGE, git, write
from review.tests.test_run_correct import invoke

TODAY = date.fromisoformat(today_kst())
WEEK = TODAY.isocalendar()
KEY = f'{WEEK[0]}-W{WEEK[1]:02d}'
US_WEEKLY = f'weekly/{KEY}.html'
JAPAN = f'japan/posts/{KEY}.html'


def editing_codex(tmp_path, need):
    checks = ''.join(f'test -f "{p}" || {{ echo "근거 없음 {p}" >&2; exit 7; }}\n' for p in need)
    path = tmp_path / 'codex'
    path.write_text(
        '#!/bin/sh\n'
        'cd "$(echo "$@" | tr " " "\\n" | grep -A1 -x -- -C | tail -1)" || exit 9\n'
        + checks +
        "sed -i '' 's/유가가 올랐다\\./유가는 올랐다./' prose_in.txt\n"
        'printf "검토 판본: 윤문 후\\n지적 없음"\n')
    path.chmod(0o755)
    return str(path)


@pytest.fixture
def repo(tmp_path):
    origin = str(tmp_path / 'origin.git')
    root = str(tmp_path / 'site')
    subprocess.run(['git', 'init', '-q', '--bare', '-b', 'main', origin], check=True)
    subprocess.run(['git', 'clone', '-q', origin, root], check=True, capture_output=True)
    git(root, 'config', 'user.email', 't@t')
    git(root, 'config', 'user.name', 't')
    write(root, US_WEEKLY, PAGE)
    write(root, JAPAN, PAGE)
    for p in kinds.evidence('weekly', KEY):
        write(root, p, json.dumps({'k': KEY}))
    write(root, f'japan/data/{KEY}.json', '{}')          # 뉴스 파일은 일부러 뺀다
    write(root, '.claude/agents/STYLE_EXEMPLARS.md', '표본\n')
    write(root, 'reviews/index.json', '{"reviewed": {}}\n')
    git(root, 'add', '-A')
    git(root, 'commit', '-qm', 'publish weekly')
    git(root, 'push', '-q', 'origin', 'main')
    return root


def test_weekly_gets_the_style_pass_on_publish_evidence_and_no_claude_correction(
        repo, tmp_path, monkeypatch):
    seen = []
    real = style_pass.gate_commands

    def checked(section, post, root, original, key, *a):
        cmds = real(section, post, root, original, key, *a)
        for p in kinds.evidence(section, key):
            assert os.path.isfile(os.path.join(root, p)), p
        seen.append((section, key))
        return []
    monkeypatch.setattr(style_pass, 'gate_commands', checked)
    monkeypatch.setattr(gate, 'CODEX', editing_codex(tmp_path, kinds.evidence('weekly', KEY)
                                                     + (US_WEEKLY,)))
    corrected = []
    invoke(repo, monkeypatch, lambda root, item, *a: corrected.append(item.path) or ('', None))
    git(repo, 'fetch', '-q', 'origin')
    assert '유가는 올랐다.' in git(repo, 'show', f'origin/main:{US_WEEKLY}').stdout
    msg = git(repo, 'log', '-1', '--format=%B', 'origin/main', '--', US_WEEKLY).stdout
    assert style_pass.is_style_commit(msg)
    assert ('weekly', KEY) in seen
    assert corrected == []
    sat = kinds.publish_day(US_WEEKLY).isoformat()
    assert any(n.startswith(f'{sat}-weekly-') for n in os.listdir(os.path.join(repo, 'reviews/pending')))


def test_missing_evidence_is_dropped_before_codex_is_called(repo, tmp_path, monkeypatch):
    """codex 구현 검토: 근거 없이 검토한 「지적 없음」 초안이 남았다. 부르기 전에 거르고 한도도 안 쓴다."""
    monkeypatch.setattr(style_pass, 'gate_commands', lambda *a: [])
    calls = tmp_path / 'calls'
    path = tmp_path / 'codex'
    path.write_text('#!/bin/sh\n'
                    'cd "$(echo "$@" | tr " " "\\n" | grep -A1 -x -- -C | tail -1)" || exit 9\n'
                    f'ls -R . >> "{calls}"\n'
                    'printf "검토 판본: 윤문 후\\n지적 없음"\n')
    path.chmod(0o755)
    monkeypatch.setattr(gate, 'CODEX', str(path))
    invoke(repo, monkeypatch, lambda *a: ('', None))
    seen = calls.read_text() if calls.exists() else ''
    assert 'japan' not in seen
    state = json.load(open(os.path.join(repo, 'reviews/runner.json')))
    assert 'news' in json.dumps(state['errors'], ensure_ascii=False)
    assert not state['calls'].get(today_kst(), {}).get('japan/posts')
    assert not any('japan' in n for n in os.listdir(os.path.join(repo, 'reviews/pending')))
