#!/usr/bin/env python3
"""stance.json / macro.json 의 과거 판단을 git 히스토리에서 1회 백필한다.

두 파일은 매일 덮어쓰기라 이력이 커밋에만 남아 있다. 이 스크립트는 각 커밋의 blob 을
읽어 data/history/*.jsonl 로 옮긴다. 여러 번 돌려도 안전하다 (report_date 로 멱등).

  python3 scripts/backfill_history.py --repo . --outdir data/history
"""

import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from us.history import append_jsonl, macro_record, stance_record  # noqa: E402


def backfill(blobs, record_fn, out_path):
    written = 0
    for blob in blobs:
        try:
            obj = json.loads(blob)
        except ValueError:
            continue
        try:
            rec = record_fn(obj)
        except Exception:
            continue
        if append_jsonl(out_path, rec):
            written += 1
    return written


def git_blobs(repo, path):
    """Every committed version of `path`, oldest first."""
    rev = subprocess.run(['git', '-C', repo, 'log', '--format=%H', '--reverse', '--', path],
                         capture_output=True, text=True, check=True)
    out = []
    for sha in rev.stdout.split():
        show = subprocess.run(['git', '-C', repo, 'show', f'{sha}:{path}'],
                              capture_output=True, text=True)
        if show.returncode == 0:
            out.append(show.stdout)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--repo', default='.')
    ap.add_argument('--outdir', default='data/history')
    args = ap.parse_args()
    os.makedirs(args.outdir, exist_ok=True)
    for src, fn, name in (('data/stance.json', stance_record, 'stance.jsonl'),
                          ('data/macro.json', macro_record, 'macro.jsonl')):
        blobs = git_blobs(args.repo, src)
        n = backfill(blobs, fn, os.path.join(args.outdir, name))
        print(f'{src}: {len(blobs)} commits -> {n} new rows in {name}')


if __name__ == '__main__':
    main()
