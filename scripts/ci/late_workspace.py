#!/usr/bin/env python3
"""늦은 글의 작업 공간 — 그 세션의 마지막 수집 커밋 하나에서 `data/` 를 꺼낸다 (2026-11-27).

    python3 scripts/ci/late_workspace.py --date D --out <ws> [--ref HEAD]
      stdout 마지막 줄 = 기준 커밋 C (40자). exit 1 = 그날 수집 커밋 없음(이유는 stderr) — 아무것도 꺼내지 않는다.

`data/market_data.json` 의 `report_date == D` 인 **마지막** 커밋이 C 다. 이력을 최신부터 거꾸로 보며 그 판의
report_date 를 읽고, D 보다 이른 판을 만나면 멈춘다. C 의 `data/` 를 접두어 없이 <ws> 에 푼다 — 작업 공간의
배치(`<ws>/market_data.json`·`<ws>/news/D.json`·`<ws>/telegram/D.json`)와 같다. `_collect_status.json` 도 그 커밋 것이다.

늦은 글 런은 입력을 C 하나에서만 꺼낸다(ORCHESTRATOR 「늦은 글」). 11/24 를 11/27 에 내면 main 의 `data/` 는
11/25 판이다(MU 등락률 67d749c2 -11.01% ↔ 558fb265 -4.53%). `routine_due.py us` 도 이 함수로 「꺼낼 수 있는가」를
보고, 없으면 그 세션을 LATE 로 내지 않는다.
설계: ../plans/attachments/2026-11-17-prepub-all/auto_resume_design_v2.md §2.2 (로컬)
"""
import argparse
import json
import os
import subprocess
import sys


class LookupFailed(RuntimeError):
    """git 조회 자체가 실패했다 — 「수집 커밋 없음」과 다르다."""


def _git(*args):
    return subprocess.run(['git', *args], capture_output=True, text=True, timeout=120)


def find_commit(day, ref='HEAD', git=None):
    """D 의 마지막 수집 커밋(40자) 또는 None."""
    git = git or _git
    out = git('log', '--format=%H', ref, '--', 'data/market_data.json')
    if out.returncode:
        raise LookupFailed(out.stderr.strip()[-200:])
    for sha in out.stdout.split():
        shown = git('show', f'{sha}:data/market_data.json')
        if shown.returncode:
            continue                      # 그 커밋에서 파일이 지워졌다
        try:
            got = json.loads(shown.stdout).get('report_date')
        except (ValueError, AttributeError):
            continue
        if got == day:
            return sha
        if isinstance(got, str) and got < day:
            return None
    return None


def export(commit, out):
    """C 의 `data/` 를 접두어 없이 out 에 푼다."""
    os.makedirs(out, exist_ok=True)
    arch = subprocess.run(['git', 'archive', '--format=tar', f'{commit}:data'], capture_output=True, timeout=300)
    if arch.returncode:
        raise LookupFailed(arch.stderr.decode(errors='replace').strip()[-200:])
    tar = subprocess.run(['tar', '-xf', '-', '-C', out], input=arch.stdout, capture_output=True, timeout=300)
    if tar.returncode:
        raise LookupFailed(tar.stderr.decode(errors='replace').strip()[-200:])


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument('--date', required=True)
    p.add_argument('--out', required=True)
    p.add_argument('--ref', default='HEAD')
    a = p.parse_args(argv)
    try:
        commit = find_commit(a.date, a.ref)
        if not commit:
            print(f'late_workspace: {a.date} 의 수집 커밋이 {a.ref} 이력에 없다 — 늦은 글을 낼 수 없다', file=sys.stderr)
            return 1
        export(commit, a.out)
    except (LookupFailed, OSError, subprocess.TimeoutExpired) as exc:
        print(f'late_workspace: git 조회 실패 — {exc}', file=sys.stderr)
        return 2
    print(commit)
    return 0


if __name__ == '__main__':
    sys.exit(main())
