#!/usr/bin/env python3
"""Thesis routine, first command — collect now, wait for that run, pull, check freshness.

    python3 scripts/thesis_refresh.py

The publisher runs at 16:00 KST; the scheduled collection arrives 7.5-10 hours late and
reads MU mid-session, and the old «force only when as_of is not today» rule fired on
some days and not others (2026-11-23 investigation). So the publisher always asks for a
fresh collection of its own. `consumer=publisher` is also what lets that run write the
newsroom file (collect_thesis_data.py).

Exit 0 REFRESHED and fresh / 20 dispatch failed / 21 run not found / 22 run failed or
cancelled / 23 pull failed / 11 still stale. `thesis_quiet.py` re-checks freshness from
the files itself, so whatever this exits with, stale numbers cannot be judged.
"""
import json
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import thesis_evidence as TE              # noqa: E402
from thesis import fresh as F             # noqa: E402

WORKFLOW = 'collect-thesis-data.yml'
FIND_FOR_S = 180


def pick_run(listing, request):
    """The databaseId whose title carries `request`, or None."""
    for run in listing or ():
        if request in (run.get('displayTitle') or ''):
            return run.get('databaseId')
    return None


def _gh(*args):
    return subprocess.run(['gh', *args], capture_output=True, text=True)


def main():
    request = uuid.uuid4().hex[:12]
    sent = _gh('workflow', 'run', WORKFLOW, '-f', 'consumer=publisher', '-f', f'request={request}')
    if sent.returncode:
        print(f'THESIS_REFRESH_FAILED 수집 요청 실패: {sent.stderr.strip()[:300]}')
        return 20

    run_id, deadline = None, time.monotonic() + FIND_FOR_S
    while run_id is None and time.monotonic() < deadline:
        time.sleep(5)
        out = _gh('run', 'list', '--workflow', WORKFLOW, '--event', 'workflow_dispatch',
                  '--limit', '20', '--json', 'databaseId,displayTitle')
        if out.returncode == 0:
            try:
                run_id = pick_run(json.loads(out.stdout), request)
            except ValueError:
                pass
    if run_id is None:
        print(f'THESIS_REFRESH_FAILED 요청 {request} 의 실행을 {FIND_FOR_S}초 안에 찾지 못했다')
        return 21

    print(f'수집 실행 {run_id} (요청 {request}) 을 기다린다…')
    if subprocess.run(['gh', 'run', 'watch', str(run_id), '--exit-status',
                       '--interval', '15'], stdout=subprocess.DEVNULL).returncode:
        print(f'THESIS_REFRESH_FAILED 수집 실행 {run_id} 이 실패하거나 취소됐다')
        return 22
    pulled = subprocess.run(['git', 'pull', '--ff-only', '-q'], capture_output=True, text=True)
    if pulled.returncode:
        print(f'THESIS_REFRESH_FAILED git pull 실패: {pulled.stderr.strip()[:300]}')
        return 23

    try:
        watch = json.loads(Path('thesis/data/watch.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        watch = None
    today = datetime.now(F.KST).date().isoformat()
    reasons = TE.staleness(today, watch)
    if reasons:
        print(f'THESIS_REFRESH_STALE 수집 실행 {run_id} 뒤에도 낡았다')
        for r in reasons:
            print(f'  - {r}')
        return 11
    print(f'THESIS_REFRESHED 실행 {run_id} — as_of {watch["as_of"]} sessions {watch.get("sessions")}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
