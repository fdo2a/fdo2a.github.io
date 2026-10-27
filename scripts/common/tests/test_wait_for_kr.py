"""wait_for_kr.sh — 일본 일간은 KR 브리프가 올라온 직후 시작한다 (2026-10-27)."""
import os
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, '..', '..', 'ci', 'wait_for_kr.sh')


def _run(tmp_path, lines, max_s='3'):
    # 호출마다 다음 줄을 내는 가짜 routine_due
    state = tmp_path / 'n'
    state.write_text('0')
    fake = tmp_path / 'due.sh'
    body = '\n'.join(f'  {i}) echo "{l}";;' for i, l in enumerate(lines))
    fake.write_text('#!/usr/bin/env bash\n'
                    f'n=$(cat {state}); echo $((n+1)) > {state}\n'
                    f'case $n in\n{body}\n  *) echo "{lines[-1]}";;\nesac\n')
    fake.chmod(0o755)
    env = dict(os.environ, ROUTINE_DUE=str(fake), WAIT_STEP='0.2')
    return subprocess.run(['bash', SCRIPT, max_s], capture_output=True, text=True, env=env, timeout=30)


def test_done_at_once(tmp_path):
    r = _run(tmp_path, ['DONE 2026-10-27 발행 완료'])
    assert r.returncode == 0 and r.stdout.startswith('DONE')


def test_waits_until_done(tmp_path):
    r = _run(tmp_path, ['DUE 2026-10-27 미발행', 'BUSY 작성 중', 'DONE 2026-10-27 발행 완료'])
    assert r.returncode == 0 and 'DONE' in r.stdout


def test_timeout_exit_2(tmp_path):
    r = _run(tmp_path, ['DUE 2026-10-27 미발행'], max_s='1')
    assert r.returncode == 2 and '미발행' in r.stdout
