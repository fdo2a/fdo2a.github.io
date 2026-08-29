#!/usr/bin/env python3
"""기간 복기 스코어카드 -> scorecard.json.

그 기간 내내 들고 있던 포지션을 기간 실현치로 채점한다. 등급 변경 하나하나를 이후
20영업일로 채점하는 일간 성적표(us/scorecard.py)와는 재는 것이 다르다.

  python3 scripts/build_scorecard.py --agg data/weekly/2026-W35.json \
      --datadir data --spans 4,12 --out data/scorecard.json

월간은 `--spans 3,12 --no-append` — 월간은 주간 행을 롤업하므로 같은 기간을 두 번
세면 안 된다.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from us.history import append_jsonl, read_jsonl  # noqa: E402
from us.period_scorecard import (regime_check, rollup, score,  # noqa: E402
                                 trigger_hygiene)


def _load(path, default=None):
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--agg', required=True)
    ap.add_argument('--datadir', default='data')
    ap.add_argument('--spans', default='4,12')
    ap.add_argument('--out', default='data/scorecard.json')
    ap.add_argument('--history', default=None,
                    help='기본 <datadir>/history/period_scorecard.jsonl')
    ap.add_argument('--no-append', action='store_true',
                    help='이력에 추가하지 않는다 — 월간은 주간 행을 롤업하므로 필수')
    args = ap.parse_args()

    agg = _load(args.agg)
    if not agg:
        print(f'FATAL: cannot read {args.agg}', file=sys.stderr)
        sys.exit(2)

    hist_dir = os.path.join(args.datadir, 'history')
    stance_rows = read_jsonl(os.path.join(hist_dir, 'stance.jsonl'))
    macro_rows = read_jsonl(os.path.join(hist_dir, 'macro.jsonl'))
    metrics = _load(os.path.join(args.datadir, 'macro_metrics.json'), {})

    start, end = agg.get('start_date'), agg.get('end_date')
    out = score(stance_rows, agg)
    out['span'] = agg.get('span')
    out['key'] = agg.get('key')
    out['start_date'], out['end_date'] = start, end
    out['regime'] = regime_check(macro_rows, metrics, start, end)
    out['triggers'] = trigger_hygiene(stance_rows, end)

    spans = tuple(int(x) for x in args.spans.split(',') if x.strip())
    path = args.history or os.path.join(hist_dir, 'period_scorecard.jsonl')
    out['rollup'] = rollup(read_jsonl(path), spans=spans)

    with open(args.out, 'w', encoding='utf-8') as fh:
        json.dump(out, fh, indent=2, ensure_ascii=False)

    if not args.no_append:
        os.makedirs(hist_dir, exist_ok=True)
        append_jsonl(path, {'key': out['key'], 'span': out['span'],
                            'end_date': end, 'weighted': out.get('weighted'),
                            'judged': out.get('judged'),
                            'neutral_share': out.get('neutral_share')}, key='key')

    print(f"{out['span']} {out['key']}: 가중 점수 {out.get('weighted')} "
          f"(판정 {out.get('judged')}건, 무포지션 {out.get('neutral')}건) -> {args.out}")


if __name__ == '__main__':
    main()
