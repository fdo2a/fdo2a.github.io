#!/usr/bin/env python3
"""고친 코드가 main 에 올라오면 세운 US 글을 자동으로 푼다 (2026-11-27).

    python3 scripts/ci/resume_on_fix.py --sha <push 한 main 끝> --pushed-at <push 시각 epoch|ISO>

retry-gate.yml 의 `resume` 잡이 main 에 `scripts/**`·`config/**`·`.claude/**` 를 바꾼 push 마다 부른다. 그 뒤
같은 실행의 `gate` 잡이 `retry_gate.py --kinds us --mode gate` 를 한 번 부른다 — 무엇을 쓸지는 `routine_due` 가
정한다(현재 세션 DUE, 지난 세션 LATE). 이 스크립트는 쏘지 않는다.

하는 일: 현재 US 세션과 그 앞 5거래일 중 글(`posts/D`·`news/D`)이 빠졌고 잠금이 `held` 이며 **그 세움이 이 push
보다 먼저인** 세션마다
  1. `refs/heads/resume/us-<D>/*` 가 이미 3개 이상이면 건너뛴다(자동 해제는 세션당 3번 — 그 뒤는 사람만).
  2. `refs/heads/resume/us-<D>/<push SHA 12자리>` 가 있으면 건너뛴다(이 push 로는 이미 풀었다).
  3. 그 ref 를 부모 없는 빈 커밋으로 **만든다**(덮지 않는다 — 있으면 push 가 거부된다). 잠금 ref 는 acquire·hold 마다
     새 커밋으로 바뀌어 제목에 둔 횟수가 사라지므로 따로 둔다.
  4. `run_lock.sh unhold us-<D>`.
세움만 푼다 — 판정·수정 표시(judging·fixing)와 release 되는 일시 멈춤은 지금 장치가 맡는다. 다시 같은 이유로 멈추면
기존 세는 규칙대로 다시 서고 즉시 텔레그램이 다시 알린다.

출력: 세션마다 한 줄. 표시를 만들지 못했거나 unhold 가 실패하면 exit 1(잡이 빨갛게 — 판정 잡은 그래도 돈다).
설계: ../plans/attachments/2026-11-17-prepub-all/auto_resume_design_v2.md §2.1 (로컬)
"""
import argparse
import os
import subprocess
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import routine_due as rd  # noqa: E402

MAX_RESUMES = 3
REMOTE = os.environ.get('RUN_LOCK_REMOTE') or 'origin'


def _git(*args, inp=None):
    return subprocess.run(['git', *args], capture_output=True, text=True, timeout=120, input=inp)


def parse_time(text):
    """epoch 초(정수 문자열) 또는 ISO 8601 → aware datetime. 못 읽으면 ValueError."""
    text = (text or '').strip()
    if text.isdigit():
        return datetime.fromtimestamp(int(text), timezone.utc)
    got = datetime.fromisoformat(text.replace('Z', '+00:00'))
    if got.tzinfo is None:
        raise ValueError(f'시간대 없는 시각: {text!r}')
    return got


def sessions(now, holidays):
    """푸는 대상이 될 수 있는 세션 — 현재 세션과 늦은 글 창(routine_due 와 같다)."""
    return rd.us_late_sessions(now, holidays) + [rd.us_session(now, holidays)]


def plan(candidates, tips, resumes, sha12, pushed_at):
    """[(세션, 행동, 이유)] — 행동: resume · skip. 순수 함수.

    candidates = 글이 빠진 세션들, tips = {세션: (커밋 시각 datetime, 제목) | None},
    resumes = {세션: 이미 있는 resume ref 이름(끝 칸) 집합}."""
    out = []
    for s in candidates:
        tip = tips.get(s)
        if not tip or not tip[1].startswith('held '):
            continue                                        # 세움이 아니다 — 이 장치의 일이 아니다
        if tip[0] >= pushed_at:
            out.append((s, 'skip', '세움이 이 push 뒤에 생겼다 — 이 push 가 고친 것이 아니다'))
            continue
        done = resumes.get(s, set())
        if sha12 in done:
            out.append((s, 'skip', f'이 push({sha12})로 이미 풀었다'))
        elif len(done) >= MAX_RESUMES:
            out.append((s, 'skip', f'자동 해제 {len(done)}번 다 썼다 — 사람이 unhold 한다'))
        else:
            out.append((s, 'resume', f'자동 해제 {len(done) + 1}번째'))
    return out


def lock_tip(name):
    """원격 잠금의 (커밋 시각, 제목) 또는 None(없음). 조회 실패는 RuntimeError."""
    ref = f'refs/heads/locks/{name}'
    out = _git('ls-remote', REMOTE, ref)
    if out.returncode:
        raise RuntimeError(f'ls-remote {ref}: {out.stderr.strip()[-200:]}')
    if not out.stdout.strip():
        return None
    got = _git('fetch', '-q', REMOTE, f'+{ref}:refs/run_lock/{name}')
    log = _git('log', '-1', '--format=%ct%n%s', f'refs/run_lock/{name}') if not got.returncode else got
    lines = log.stdout.split('\n')
    if log.returncode or len(lines) < 2 or not lines[0].strip().isdigit():
        raise RuntimeError(f'잠금 {name} 을 읽지 못했다: {(got.stderr or log.stderr).strip()[-200:]}')
    return datetime.fromtimestamp(int(lines[0]), timezone.utc), lines[1]


def resume_refs(session):
    out = _git('ls-remote', REMOTE, f'refs/heads/resume/us-{session}/*')
    if out.returncode:
        raise RuntimeError(f'ls-remote resume/us-{session}: {out.stderr.strip()[-200:]}')
    return {line.split('/')[-1] for line in out.stdout.split('\n') if line.strip()}


def make_marker(session, sha12):
    """부모 없는 빈 커밋을 resume ref 로 만든다(만들기만). 성공하면 True."""
    tree = _git('mktree', inp='')
    if tree.returncode:
        return False, tree.stderr.strip()[-200:]
    commit = _git('-c', 'user.name=resume-on-fix', '-c', 'user.email=resume-on-fix@users.noreply.github.com',
                  'commit-tree', tree.stdout.strip(), '-m', f'resume us-{session} after {sha12}')
    if commit.returncode:
        return False, commit.stderr.strip()[-200:]
    ref = f'refs/heads/resume/us-{session}/{sha12}'
    push = _git('push', '-q', REMOTE, f'{commit.stdout.strip()}:{ref}')
    return (not push.returncode), push.stderr.strip()[-200:]


def unhold(session):
    r = subprocess.run(['bash', os.path.join(HERE, 'run_lock.sh'), 'unhold', f'us-{session}'],
                       capture_output=True, text=True, timeout=120)
    return r.returncode, (r.stdout + r.stderr).strip()[-300:]


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument('--sha', required=True)
    p.add_argument('--pushed-at', required=True)
    p.add_argument('--files-ref', default='origin/main')
    a = p.parse_args(argv)
    try:
        pushed_at = parse_time(a.pushed_at)
    except ValueError as exc:
        print(f'::error::resume-on-fix: push 시각을 읽지 못했다 ({exc}) — 아무것도 풀지 않았다')
        return 1
    sha12 = a.sha.strip()[:12]
    if len(sha12) != 12:
        print(f'::error::resume-on-fix: push SHA 가 이상하다 ({a.sha!r})')
        return 1
    hol = rd._holidays('us', a.files_ref)
    listed = _git('ls-tree', '-r', '--name-only', a.files_ref, '--', 'posts', 'news')
    if listed.returncode:
        print(f'::error::resume-on-fix: {a.files_ref} 목록을 읽지 못했다 — {listed.stderr.strip()[-200:]}')
        return 1
    files = set(listed.stdout.split())
    missing = [s for s in sessions(pushed_at, hol) if any(f not in files for f in rd.us_want(s))]
    try:
        tips = {s: lock_tip(f'us-{s}') for s in missing}
        held = [s for s in missing if tips[s] and tips[s][1].startswith('held ')]
        resumes = {s: resume_refs(s) for s in held}
    except RuntimeError as exc:
        print(f'::error::resume-on-fix: {exc}')
        return 1
    failed = False
    steps = plan(missing, tips, resumes, sha12, pushed_at)
    for s, act, why in steps:
        if act == 'skip':
            print(f'resume-on-fix us-{s}: 건너뜀 — {why}')
            continue
        ok, err = make_marker(s, sha12)
        if not ok:
            print(f'::error::resume-on-fix us-{s}: 횟수 표시를 만들지 못했다 — 풀지 않았다 ({err})')
            failed = True
            continue
        code, out = unhold(s)
        if code:
            print(f'::error::resume-on-fix us-{s}: unhold exit {code} — {out}')
            failed = True
            continue
        print(f'resume-on-fix us-{s}: 풀었다 ({why}, push {sha12})')
    if not steps:
        print(f'resume-on-fix: 푼 세션 없음 (세운 US 세션 없음, push {sha12})')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
