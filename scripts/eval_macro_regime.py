#!/usr/bin/env python3
"""Judge yesterday's macro book against today's axis scores -> data/macro_eval.json.

Runs in the GitHub Actions collector job, right after collect_market_data.py, so the
cloud routine reads a decided regime instead of re-deriving the cycle from whichever
numbers happen to be on the table that morning.

  python scripts/eval_macro_regime.py --datadir data
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from us.macro import evaluate  # noqa: E402


def load(path):
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except FileNotFoundError:
        return None
    except Exception as e:
        print(f'WARN: could not read {path}: {e}', file=sys.stderr)
        return None


def eval_collect(report_date, metrics_state, metrics, macro_state):
    """collect 칸(2026-11-17). 축 점수(macro_metrics)가 없거나 낡았거나 일부만 찼으면 오늘 판정의 재료가
    빠진 것이다(partial). 어제 책(macro.json)이 있는데 못 읽었으면 「처음 여는 날」로 읽히면 안 된다(failed)."""
    from common import collect_status as C
    src = 'macro_metrics.json + macro.json'
    if macro_state == 'unreadable':
        return C.failed(report_date, src, 'macro.json 을 읽지 못했다 — 처음 여는 날과 구별할 수 없다',
                        missing=['macro.json'])
    missing, ref = [], {}
    if metrics_state != 'fresh':
        missing.append(f'macro_metrics:{metrics_state}')
    else:
        # 축 점수가 일부 지표 없이 나왔으면 무엇이 빠졌는지를 그대로 옮긴다(`metrics:<키>` + 식별자·기준월) — 승인된
        # 예외가 이 파일에도 같은 지표·같은 기준월로만 걸린다. 무엇이 빠졌는지 모르면 전처럼 macro_metrics:partial.
        missing, ref = C.carry_upstream(metrics.get('collect'), 'metrics', 'macro_metrics:partial')
    return C.build('partial' if missing else 'ok', report_date, src, missing=missing, empty='has_data',
                   detail='bootstrap — 어제 책 없음' if macro_state == 'absent' else None, missing_ref=ref or None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--datadir', default='data')
    args = ap.parse_args()

    market = load(os.path.join(args.datadir, 'market_data.json'))
    if not market or not market.get('report_date'):
        print('FATAL: market_data.json missing or has no report_date', file=sys.stderr)
        sys.exit(1)
    report_date = market['report_date']

    macro_path = os.path.join(args.datadir, 'macro.json')
    macro = load(macro_path)
    macro_state = 'ok' if macro is not None else ('unreadable' if os.path.exists(macro_path) else 'absent')
    metrics = load(os.path.join(args.datadir, 'macro_metrics.json')) or {}
    metrics_state = 'fresh' if metrics.get('report_date') == report_date else (
        'stale' if metrics else 'absent')
    # Scores keyed to another session would judge today's regime against yesterday's
    # economy. Drop them: with no scores nothing is implied, so the book freezes.
    got = metrics.get('report_date')
    if metrics and got is not None and got != report_date:
        print(f'WARN: macro_metrics.json report_date={got}, not {report_date} — ignoring',
              file=sys.stderr)
        metrics = {}

    try:
        ev = evaluate(macro, metrics, report_date)
    except ValueError as e:
        print(f'FATAL: macro.json is invalid: {e}', file=sys.stderr)
        sys.exit(1)

    ev['collect'] = eval_collect(report_date, metrics_state, metrics, macro_state)
    with open(os.path.join(args.datadir, 'macro_eval.json'), 'w', encoding='utf-8') as fh:
        json.dump(ev, fh, indent=2, ensure_ascii=False)

    if ev['bootstrap']:
        print('no prior macro book — bootstrap mode, writer sets the opening regime')
        return

    r = ev['regime']
    print(f"regime {r['name']} (성장 {r['growth_label']} / 인플레 {r['inflation_label']}) "
          f"· {r['days_held']}bd" + (' (STALE)' if ev['stale'] else ''))
    s = ev['scores']
    print(f"  scores: growth {s.get('growth_score')} / inflation {s.get('inflation_score')}"
          f" -> implied {ev['implied'].get('name')}")
    if ev['new_releases']:
        print(f"  new releases ({len(ev['new_releases'])}): "
              + ', '.join(ev['new_releases']))
    else:
        print('  no new releases — regime and policy path are frozen')
    for gap in ev.get('anatomy_gaps') or []:
        print(f"  해부 미완 {gap['key']}: {gap['status']} ({gap['reason']})")
    allowed = ' / '.join(f"[{g},{i}]" for g, i in ev['allowed_regimes'])
    block = f" blocked:{ev['regime_block']}" if ev['regime_block'] else ''
    print(f'  allowed regimes: {allowed}{block}')
    for key, row in ev['transmission'].items():
        print(f"    {key:9s} {row['label']} · {row['days_held']}bd "
              f"· allowed {row['allowed_directions']}")


if __name__ == '__main__':
    main()
