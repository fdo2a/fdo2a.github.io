#!/usr/bin/env python3
"""macro.json / market_data.json 의 과거분을 git 히스토리에서 1회 백필한다.

세 파일 모두 매일 덮어쓰기라 이력이 커밋에만 남아 있다. 이 스크립트는 각 커밋의 blob 을
읽어 data/history/*.jsonl 로 옮긴다. 여러 번 돌려도 안전하다 (report_date 로 멱등). 원장에
이미 있는 날은 건드리지 않고, 빈 날만 메운다.

같은 report_date 가 여러 커밋에 있으면 매일 쌓는 경로(`collect_market_data.py`,
`collect_kr_data.py`)가 남겼을 값을 고른다 — 시세는 마지막 커밋(그날 발행본이 나간 스냅샷,
upsert), KR 지수는 커밋 순서대로 `merge_index_record` 로 접은 값, 판단 이력(macro)은 첫 커밋.
처음에는 셋 다 첫 커밋을 집어 시세 원장이 발행본과 갈릴 수 있었다(2026-11-22).

  python3 scripts/backfill_history.py --repo . --outdir data/history
"""

import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from kr.history import index_record, merge_index_record  # noqa: E402
from us.history import append_jsonl, macro_record, market_record  # noqa: E402


FIRST = 'first'
LAST = 'last'


def merge_with(fn):
    """같은 날의 앞 행과 새 행을 fn(앞, 새) 로 접는다 — 매일 경로가 upsert 전에 합치는 방식."""
    return ('merge', fn)


def _records(blobs, record_fn):
    for blob in blobs:
        try:
            obj = json.loads(blob)
        except ValueError:
            continue
        try:
            rec = record_fn(obj)
        except Exception:
            continue
        if isinstance(rec, dict) and rec.get('report_date') is not None:
            yield rec


def backfill(blobs, record_fn, out_path, pick=FIRST):
    """blobs 는 오래된 커밋부터. pick: FIRST(첫 커밋)·LAST(마지막 커밋)·merge_with(fn)."""
    chosen = {}
    for rec in _records(blobs, record_fn):
        key = rec['report_date']
        if key not in chosen or pick == LAST:
            chosen[key] = rec
        elif pick != FIRST:
            chosen[key] = pick[1](chosen[key], rec)
    written = 0
    for key in sorted(chosen):
        if append_jsonl(out_path, chosen[key]):
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
    ap.add_argument('--kr-outdir', default='kr/data/history')
    args = ap.parse_args()
    os.makedirs(args.outdir, exist_ok=True)
    for src, fn, name, outdir, pick in (
            ('data/macro.json', macro_record, 'macro.jsonl', args.outdir, FIRST),
            ('data/market_data.json', market_record, 'market.jsonl', args.outdir, LAST),
            ('kr/data/kr_market_data.json', index_record, 'kr_market.jsonl',
             args.kr_outdir, merge_with(merge_index_record))):
        os.makedirs(outdir, exist_ok=True)
        blobs = git_blobs(args.repo, src)
        n = backfill(blobs, fn, os.path.join(outdir, name), pick=pick)
        print(f'{src}: {len(blobs)} commits -> {n} new rows in {name}')


if __name__ == '__main__':
    main()
