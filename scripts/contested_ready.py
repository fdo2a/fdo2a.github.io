#!/usr/bin/env python3
"""루틴용 — 쟁점 분석 결과를 한 번에 확정해 워크스페이스로 가져온다(설계 검토 N04).

    python3 scripts/contested_ready.py --market us --date D --out <ws>/contested.json

1. origin/main 의 `data/contested/<market>/<D>.json` 을 읽는다(작업 트리를 건드리지 않는다).
2. 확정된 결과(ok·최종 none·시도 소진)면 그대로 복사하고 끝낸다.
3. 없거나 재시도 가능한 결과면 수집 워크플로를 한 번 띄우고 **스크립트 대기 한 번**
   (`wait_run.sh`, 기본 900초)으로 기다린 뒤 다시 읽는다. 루틴이 깨어나 반복 확인하지 않는다.
4. 그래도 없으면 출력 파일을 지우고 「미도착」 — 섹션 없이 발행하고 최종 보고에 적는다.

결과 파일은 동결 뒤 바뀌지 않으므로 이어쓰기 런이 다시 돌려도 같은 것을 받는다.
항상 exit 0. 마지막 줄 = `contested: <상태>(<사유>)`.
"""
import argparse
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import contested as C  # noqa: E402

WORKFLOW = 'collect-contested.yml'


def sh(args, check=False):
    return subprocess.run(args, capture_output=True, text=True, check=check)


def remote(market, date, run=sh):
    run(['git', 'fetch', '-q', 'origin', 'main'])
    r = run(['git', 'show', f'origin/main:data/contested/{market}/{date}.json'])
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except ValueError:
        return {'status': 'error', 'reason': 'unreadable'}


def settled(p):
    if not p:
        return False
    if p.get('status') == 'ok' or (p.get('status') == 'none' and p.get('reason') in C.FINAL_NONE):
        return True
    return not p.get('retryable', True) or p.get('attempts', 0) >= C.MAX_ATTEMPTS


def dispatch_and_wait(date, wait, run=sh, sleep=time.sleep):
    before = run(['gh', 'run', 'list', '--workflow', WORKFLOW, '--limit', '1',
                  '--json', 'databaseId', '--jq', '.[0].databaseId // 0']).stdout.strip() or '0'
    r = run(['gh', 'workflow', 'run', WORKFLOW, '-f', f'date={date}'])
    if r.returncode != 0:
        return f'dispatch_failed:{(r.stderr or "").strip()[:80]}'
    for _ in range(12):
        sleep(5)
        rid = run(['gh', 'run', 'list', '--workflow', WORKFLOW, '--event', 'workflow_dispatch',
                   '--limit', '1', '--json', 'databaseId', '--jq', '.[0].databaseId // 0']).stdout.strip()
        if rid and rid != '0' and rid != before:
            w = run(['bash', 'scripts/ci/wait_run.sh', rid, str(wait)])
            return {0: 'run_ok', 1: 'run_failed', 2: 'run_timeout'}.get(w.returncode, 'wait_error')
    return 'run_not_found'


def main(argv=None, run=sh, sleep=time.sleep):
    ap = argparse.ArgumentParser()
    ap.add_argument('--market', default='us')
    ap.add_argument('--date', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--wait', type=int, default=900)
    a = ap.parse_args(argv)
    p = remote(a.market, a.date, run)
    note = ''
    if not settled(p) and a.wait > 0:
        note = dispatch_and_wait(a.date, a.wait, run, sleep)
        p = remote(a.market, a.date, run) or p
    if p is None:
        if os.path.exists(a.out):
            os.remove(a.out)
        print(f'contested: 미도착({note or "no_file"})')
        return 0
    with open(a.out, 'w', encoding='utf-8') as fh:
        json.dump(p, fh, ensure_ascii=False)
    print(f'contested: {p.get("status")}({p.get("reason") or "-"}{", " + note if note else ""})')
    return 0


if __name__ == '__main__':
    sys.exit(main())
