#!/usr/bin/env python3
"""기간 복기 스코어카드 -> period_scorecard.json.

**data/scorecard.json 을 쓰지 않는다** — 그 이름은 일간 수집기가 20세션 스키마로
매일 덮어쓰는 파일이다. 같은 경로에 다른 스키마를 쓰면 일간 게이트가 순서에 따라
깨진다(2026-08-30 codex 검토).

그 기간 내내 들고 있던 포지션을 기간 실현치로 채점한다. 등급 변경 하나하나를 이후
20영업일로 채점하는 일간 성적표(us/scorecard.py)와는 재는 것이 다르다.

  python3 scripts/build_scorecard.py --agg data/weekly/2026-W35.json \
      --datadir data --spans 4,12 --out data/scorecard.json

**단위는 「행」이다** — 이력에 주간 행이 쌓이므로 4,12는 최근 주간 4회·12회를 뜻한다.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from us.history import append_jsonl, read_jsonl  # noqa: E402
from us import release_ledger  # noqa: E402
from us.period_scorecard import regime_check, rollup, score  # noqa: E402


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
    ap.add_argument('--out', default='data/period_scorecard.json')
    ap.add_argument('--history', default=None,
                    help='기본 <datadir>/history/period_scorecard.jsonl')
    args = ap.parse_args()

    agg = _load(args.agg)
    if not agg:
        print(f'FATAL: cannot read {args.agg}', file=sys.stderr)
        sys.exit(2)

    hist_dir = os.path.join(args.datadir, 'history')
    macro_rows = read_jsonl(os.path.join(hist_dir, 'macro.jsonl'))
    # 레짐 점검은 오늘 macro_metrics.json 이 아니라 **기간 전체의 새 발표 원장**을 읽는다 —
    # 오늘 파일만 보면 월요일 발표가 금요일에 사라진다(2026-11-08).
    try:
        ledger = release_ledger.load(os.path.join(args.datadir, release_ledger.LEDGER))
    except (OSError, ValueError) as e:
        # 손상된 원장으로 세면 빠진 줄이 「발표 없음」으로 읽힌다 — 통째로 판정불가.
        print(f'경고: 새 발표 원장을 읽지 못했다 — {e}', file=sys.stderr)
        ledger = None
    holidays = _load(os.path.join(args.datadir, 'market_holidays.json'))

    start, end = agg.get('start_date'), agg.get('end_date')
    out = score(macro_rows, agg)
    out['span'] = agg.get('span')
    out['key'] = agg.get('key')
    out['start_date'], out['end_date'] = start, end
    if ledger is None:
        # 원장을 못 읽은 주는 축마다 같은 사유로 판정불가 — 빈 원장으로 세면 「수집 누락」으로
        # 읽혀 사유가 틀린다(codex 구현 #4).
        out['regime'] = regime_check(macro_rows, [], start, end, holidays)
        note = '새 발표 기록을 읽지 못했다'
        out['regime'].update({'verdict': '판정불가', 'partial': False, 'note': note, 'prints': []})
        for key in ('growth', 'inflation'):
            out['regime'][key].update({'verdict': '판정불가', 'note': note})
    else:
        out['regime'] = regime_check(macro_rows, ledger, start, end, holidays)

    spans = tuple(int(x) for x in args.spans.split(',') if x.strip())
    path = args.history or os.path.join(hist_dir, 'period_scorecard.jsonl')

    # 당기를 이력에 먼저 넣고 롤업을 잰다. 순서를 뒤집으면 첫 실행은 당기를 빼고
    # 재실행은 넣어 같은 입력에 다른 답이 나온다(2026-08-30 codex 검토).
    os.makedirs(hist_dir, exist_ok=True)
    append_jsonl(path, {'key': out['key'], 'span': out['span'],
                        'end_date': end, 'weighted': out.get('weighted'),
                        'judged': out.get('judged'),
                        'neutral_share': out.get('neutral_share')}, key='key')

    out['rollup'] = rollup(read_jsonl(path), spans=spans)
    out['rollup_unit'] = '주'

    with open(args.out, 'w', encoding='utf-8') as fh:
        json.dump(out, fh, indent=2, ensure_ascii=False)

    print(f"{out['span']} {out['key']}: 가중 점수 {out.get('weighted')} "
          f"(판정 {out.get('judged')}건, 무포지션 {out.get('neutral')}건) -> {args.out}")


if __name__ == '__main__':
    main()
