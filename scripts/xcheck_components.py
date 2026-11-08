#!/usr/bin/env python3
"""Step two of the release anatomy: keep only components the agency's text confirms.

Runs in the Actions collector job after `fetch_releases.py` (and its `--sanitize`), and
before `eval_macro_regime.py`, so `macro_eval.json` inherits the result. Rewrites
`data/macro_metrics.json` in place: each headline release gets `components` (usable
only), `anatomy_status` and `anatomy_reason`, and the file gets `anatomy_gaps`.

**Every release is reset first.** The texts must be this run's (`index.json` complete,
same report date and run as the metrics' session); anything else — a crash upstream, a
stale index, yesterday's metrics — leaves every release with no components, never with
yesterday's. Spec: `us/anatomy.py`, ../plan.md 「A단계」.

  python scripts/xcheck_components.py --datadir data
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fetch_releases import fulldir_for, run_id  # noqa: E402
from us import anatomy  # noqa: E402


def load(path):
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except FileNotFoundError:
        return None
    except Exception as e:
        print(f'WARN: could not read {path}: {e}', file=sys.stderr)
        return None


def _read(path):
    try:
        with open(path, encoding='utf-8') as fh:
            return fh.read()
    except OSError:
        return None


def run(datadir, fulldir=None):
    fulldir = fulldir or fulldir_for(datadir)
    path = os.path.join(datadir, 'macro_metrics.json')
    metrics = load(path)
    if not metrics:
        print('macro_metrics.json 없음 — 대조할 것이 없다', file=sys.stderr)
        return None
    rels = metrics.get('headline_releases') or []
    for rel in rels:
        anatomy.reset(rel)

    market = load(os.path.join(datadir, 'market_data.json')) or {}
    index = load(os.path.join(datadir, 'releases', 'index.json')) or {}
    session = market.get('report_date')
    why = None
    if metrics.get('report_date') != session:
        why = f"macro_metrics.json report_date={metrics.get('report_date')}, 세션 {session}"
    elif index.get('status') != 'complete' or index.get('report_date') != session:
        why = f"원문 index 가 이 세션의 완료본이 아니다({index.get('status')}, {index.get('report_date')})"
    elif os.environ.get('GITHUB_RUN_ID') and index.get('run_id') != run_id():
        why = f"원문 index 가 이 실행의 것이 아니다({index.get('run_id')})"
    rows = {r.get('key'): r for r in index.get('releases') or []} if why is None else {}
    if why:
        print(f'구성 대조 건너뜀 — {why}', file=sys.stderr)

    for rel in rels:
        if why:
            continue
        key = rel.get('key')
        row = rows.get(key)
        text = _read(os.path.join(fulldir, f'{key}.txt'))
        if text is None and row and row.get('path'):
            text = _read(os.path.join(datadir, row['path']))
        anatomy.cross_check(rel, text, row)
        cands = (rel.get('anatomy') or {}).get('candidates') or []
        lost = [f"{c['label']}({c.get('reason')})" for c in cands if not c.get('text_ok')]
        print(f"  {key}: {rel['anatomy_status']} — 구성 {len(rel['components'])}개"
              + (f" · 제외 {', '.join(lost)}" if lost else ''))

    metrics['anatomy_gaps'] = anatomy.gaps(rels)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(metrics, fh, indent=2, default=str, ensure_ascii=False)
    os.replace(tmp, path)
    for gap in metrics['anatomy_gaps']:
        print(f"::warning::해부 미완 {gap['key']}: {gap['status']} ({gap['reason']})")
    return metrics


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--datadir', default='data')
    ap.add_argument('--fulldir', default=None)
    args = ap.parse_args()
    run(args.datadir, args.fulldir)


if __name__ == '__main__':
    main()
