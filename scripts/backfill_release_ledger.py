#!/usr/bin/env python3
"""새 발표 원장을 git 이력으로 처음부터 다시 만든다 (한 번 쓰는 시드).

수집 커밋(`data/market_data.json` 을 바꾼 커밋)을 `--first-parent` 시간순으로 재생한다.
각 커밋에서 세 파일(market_data·econ_indicators·macro_metrics)을 그 커밋 그대로 읽고,
일정은 **부모 커밋**의 `calendar.json` — Actions 의 기록 단계가 본 것과 같은 파일이다.
세 파일의 `generated` 가 다르면 그 커밋은 건너뛴다(같은 실행의 결과라는 증거가 없다).
이력에 없는 날은 원장에도 없다 — 주간 점검이 그날을 수집 누락으로 본다.

  python scripts/backfill_release_ledger.py --out data/history/releases.jsonl

이미 있는 원장 위에는 쓰지 않는다(덧붙이기만 하는 원장이다). 과거 주간 글은 바뀌지 않는다.
설계: docs/superpowers/specs/2026-11-08-weekly-regime-ledger.md
"""
import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from us import release_ledger as L  # noqa: E402


def git(*args, repo='.'):
    r = subprocess.run(['git', '-C', repo, *args], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def show(repo, rev, path):
    out = git('show', f'{rev}:{path}', repo=repo)
    if out is None:
        return None
    try:
        return json.loads(out)
    except ValueError:
        return None


def replay(repo='.', since=None):
    """-> (원장 행 목록, 건너뛴 커밋 [(sha, 이유)])."""
    args = ['log', '--first-parent', '--reverse', '--format=%H']
    if since:
        args.append(f'--since={since}')
    log = git(*args, '--', 'data/market_data.json', repo=repo) or ''
    rows, skipped = [], []
    for sha in log.split():
        mm = show(repo, sha, 'data/macro_metrics.json')
        econ = show(repo, sha, 'data/econ_indicators.json')
        market = show(repo, sha, 'data/market_data.json')
        cal = show(repo, f'{sha}^', 'data/calendar.json')
        new, warnings = L.record(rows, mm, econ, market, cal, f'backfill-{sha[:10]}')
        if not new:
            skipped.append((sha[:10], '; '.join(warnings) or '같은 실행 재기록'))
            continue
        for r in new:
            r['source'] = 'backfill'
            r['commit'] = sha[:10]
        rows += new
    return rows, skipped


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--repo', default='.')
    ap.add_argument('--since', default=None)
    ap.add_argument('--out', default=os.path.join('data', L.LEDGER))
    args = ap.parse_args(argv)
    if os.path.exists(args.out):
        print(f'FATAL: {args.out} 가 이미 있다 — 덧붙이기만 하는 원장 위에 다시 만들지 않는다',
              file=sys.stderr)
        return 2
    rows, skipped = replay(args.repo, args.since)
    for sha, why in skipped:
        print(f'건너뜀 {sha}: {why}', file=sys.stderr)
    L.append_rows(args.out, rows)
    days = sorted({r['report_date'] for r in rows if r['kind'] == 'scan'})
    print(f'{len(rows)}행 ({len(days)}일, {days[0] if days else "-"} ~ {days[-1] if days else "-"}) -> {args.out}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
