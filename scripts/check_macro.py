#!/usr/bin/env python3
"""Publication gate for §8 (매크로).

Run from the repo clone, against the writer's output in the routine workspace:

  python scripts/check_macro.py --html morning_brief_2026-08-19.html --datadir .

Exit 0 = publishable. Exit 1 = violations printed, one per line; hand them back to
the writer subagent verbatim and re-run.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from us import moomoo_forward as MF  # noqa: E402
from us.macro_gate import check  # noqa: E402


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
                    help='workspace holding macro.json / macro_eval.json / '
                         'macro_next.json')
    ap.add_argument('--next', dest='next_path', default=None,
                    help='override the macro_next.json path')
    args = ap.parse_args()

    try:
        with open(args.html, encoding='utf-8') as fh:
            html = fh.read()
    except OSError as e:
        print(f'FATAL: cannot read {args.html}: {e}', file=sys.stderr)
        sys.exit(2)

    d = args.datadir
    prev = load(os.path.join(d, 'macro.json'))
    ev = load(os.path.join(d, 'macro_eval.json'))
    nxt = load(args.next_path or os.path.join(d, 'macro_next.json'))

    if prev is None and ev is None:
        print('macro.json / macro_eval.json 둘 다 없다 — 부트스트랩 실행으로 간주하고 '
              '§8 어휘·표 완성도만 검사한다', file=sys.stderr)

    # FedWatch 원천 승인: 파일이 있다는 사실이 아니라 **상태·대상 세션·회차**가
    # 정본과 맞을 때만 대조에 쓴다(2026-09-22 codex 검토).
    market = load(os.path.join(d, 'market_data.json')) or {}
    fw_env = load(os.path.join(d, 'moomoo', 'fedwatch.json'))
    manifest = load(os.path.join(d, 'moomoo', 'manifest.json')) or {}
    if fw_env and manifest.get('run_id') and fw_env.get('run_id') != manifest['run_id']:
        print('FedWatch 파일의 run_id 가 manifest 와 다르다 — 원천 대조를 건너뛴다',
              file=sys.stderr)
        fw_env = None
    fedwatch = None
    if fw_env and market.get('report_date'):
        fedwatch = MF.approved_fedwatch(fw_env, report_date=market['report_date'])
        if fw_env.get('status') == 'ok' and fedwatch is None:
            print('FedWatch 파일은 있으나 상태·세션·관측시각이 정본과 맞지 않는다 — '
                  '원천 대조를 건너뛴다', file=sys.stderr)

    # 축 표 게이트의 기준일은 세션(market_data)이다. metrics 가 그 날짜·현행 스키마가
    # 아니면 추세 칸은 「—」만 허용된다 — 어제 추세가 오늘 숫자 옆에 나가지 않게.
    econ = (load(os.path.join(d, 'econ_indicators.json')) or {}).get('indicators')
    if not econ and market.get('report_date'):
        print('WARN: econ_indicators.json 이 없거나 읽을 수 없다 — §9 축 표(직전 대비·추세) '
              '검사를 건너뛴다. 표의 Actual/Previous 를 대조할 정본이 없다', file=sys.stderr)
    metrics = load(os.path.join(d, 'macro_metrics.json'))
    if econ and metrics and metrics.get('report_date') != market.get('report_date'):
        print(f"WARN: macro_metrics.json report_date={metrics.get('report_date')}, "
              f"세션 {market.get('report_date')} — 추세 칸은 「—」만 허용", file=sys.stderr)
    violations = check(html, prev, ev, nxt, fedwatch, fw_env is not None,
                       econ=econ, metrics=metrics, report_date=market.get('report_date'))
    if not violations:
        print('매크로 게이트 통과')
        return
    print(f'매크로 게이트 실패 — {len(violations)}건')
    for x in violations:
        print(f'  - {x}')
    sys.exit(1)


if __name__ == '__main__':
    main()
