#!/usr/bin/env python3
"""Publication gate for §8 (멀티에셋 매니저 전략).

Run from the repo clone, against the writer's output in the routine workspace:

  python scripts/check_stance.py --html morning_brief_2026-08-18.html --datadir .

Exit 0 = publishable. Exit 1 = violations printed, one per line; hand them back to
the writer subagent verbatim and re-run.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from us.stance_gate import check  # noqa: E402


def load(path):
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except FileNotFoundError:
        return None
    except Exception as e:
        print(f'WARN: could not read {path}: {e}', file=sys.stderr)
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--html', required=True)
    ap.add_argument('--datadir', default='.',
                    help='workspace holding stance.json / stance_eval.json / '
                         'stance_metrics.json / stance_next.json')
    ap.add_argument('--next', dest='next_path', default=None,
                    help='override the stance_next.json path')
    args = ap.parse_args()

    try:
        with open(args.html, encoding='utf-8') as fh:
            html = fh.read()
    except OSError as e:
        print(f'FATAL: cannot read {args.html}: {e}', file=sys.stderr)
        sys.exit(2)

    d = args.datadir
    prev = load(os.path.join(d, 'stance.json'))
    ev = load(os.path.join(d, 'stance_eval.json'))
    nxt = load(args.next_path or os.path.join(d, 'stance_next.json'))
    metrics_file = load(os.path.join(d, 'stance_metrics.json')) or {}
    metric_names = tuple((metrics_file.get('metrics') or {}).keys())

    if prev is None and ev is None:
        print('stance.json / stance_eval.json 둘 다 없다 — 부트스트랩 실행으로 간주하고 '
              '§8 어휘·표 완성도만 검사한다', file=sys.stderr)

    violations = check(html, prev, ev, nxt, metric_names)
    if not violations:
        print('스탠스 게이트 통과')
        return
    print(f'스탠스 게이트 실패 — {len(violations)}건')
    for x in violations:
        print(f'  - {x}')
    sys.exit(1)


if __name__ == '__main__':
    main()
