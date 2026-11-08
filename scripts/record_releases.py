#!/usr/bin/env python3
"""오늘 수집에서 처음 본 숫자를 새 발표 원장에 덧붙인다 -> data/history/releases.jsonl.

수집 워크플로가 「Collect」 뒤, 「Build calendar」 **앞**에서 부른다 — 공식
발표일을 이번 실행이 덮어쓰기 전의 `calendar.json`(어제 만든 앞으로 열흘 일정)에서 찾기
때문이다. 수집을 건너뛴 실행에서도 돈다(멱등) — 첫 슬롯에서 이 단계만 죽었으면 둘째
슬롯이 같은 날의 커밋된 파일로 채운다.

  python scripts/record_releases.py --datadir data

비핵심이다. 실패해도 수집을 막지 않는다 — 그날은 주간 점검에서 수집 누락일로 보인다.
설계: docs/superpowers/specs/2026-11-08-weekly-regime-ledger.md
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from us import release_ledger as L  # noqa: E402


def _load(path):
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except FileNotFoundError:
        return None
    except ValueError as e:
        print(f'경고: {path} 를 읽지 못했다: {e}', file=sys.stderr)
        return None


def run_id():
    rid = os.environ.get('GITHUB_RUN_ID')
    if rid:
        return f"{rid}-{os.environ.get('GITHUB_RUN_ATTEMPT', '1')}"
    return f'local-{os.getpid()}-{int(time.time())}'


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--datadir', default='data')
    ap.add_argument('--run-id', default=None)
    args = ap.parse_args(argv)

    d = args.datadir
    path = os.path.join(d, L.LEDGER)
    try:
        rows = L.load(path)
    except (OSError, ValueError) as e:
        # 손상된 원장 위에 쓰면 그 줄이 영영 사라진다 — 고칠 때까지 아무것도 안 쓴다.
        print(f'FATAL: 새 발표 원장을 읽지 못했다 — {e}', file=sys.stderr)
        return 1
    new, warnings = L.record(rows,
                             _load(os.path.join(d, 'macro_metrics.json')),
                             _load(os.path.join(d, 'econ_indicators.json')),
                             _load(os.path.join(d, 'market_data.json')),
                             _load(os.path.join(d, 'calendar.json')),
                             args.run_id or run_id())
    for w in warnings:
        print(f'경고: {w}', file=sys.stderr)
    n = L.append_rows(path, new)
    kinds = {}
    for r in new:
        kinds[r['kind']] = kinds.get(r['kind'], 0) + 1
    print(f'새 발표 원장: {n}행 추가 {kinds or ""} -> {path}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
