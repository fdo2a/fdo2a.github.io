#!/usr/bin/env python3
"""Publication gate for §8 (매크로).

Run from the repo clone, against the writer's output in the routine workspace:

  python scripts/check_macro.py --html morning_brief_2026-08-19.html --datadir .

Exit 0 = publishable. Exit 1 = violations printed, one per line; hand them back to
the writer subagent verbatim and re-run. Exit 2 = incomplete input (2026-11-17): a book,
market_data, econ_indicators, macro_metrics or (when publishing now) the releases index is
missing, unreadable or from another session — re-collect, do not rewrite the post. The old
"bootstrap" pass with both books absent and the skipped axis-table check are gone.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from us.macro_gate import check  # noqa: E402


class Corrupt(Exception):
    pass


def load(path):
    """Absent -> None. Unreadable -> Corrupt (a broken file is not an absent one)."""
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except FileNotFoundError:
        return None
    except Exception as e:
        raise Corrupt(f'could not read {path}: {e}')


def incomplete(why):
    print(f'FATAL: {why} — 미완료, 수집을 다시 돌린다(글을 고쳐서 풀리지 않는다)', file=sys.stderr)
    sys.exit(2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--html', required=True)
    ap.add_argument('--datadir', default='.',
                    help='workspace holding macro.json / macro_eval.json / '
                         'macro_next.json')
    ap.add_argument('--next', dest='next_path', default=None,
                    help='override the macro_next.json path')
    ap.add_argument('--legacy-releases', action='store_true',
                    help="re-checking a past post against its own commit's data: a missing "
                         'releases index keeps the pre-2026-11-06 strict reading')
    args = ap.parse_args()

    try:
        with open(args.html, encoding='utf-8') as fh:
            html = fh.read()
    except OSError as e:
        print(f'FATAL: cannot read {args.html}: {e}', file=sys.stderr)
        sys.exit(2)

    d = args.datadir
    try:
        prev = load(os.path.join(d, 'macro.json'))
        ev = load(os.path.join(d, 'macro_eval.json'))
        nxt = load(args.next_path or os.path.join(d, 'macro_next.json'))
        market = load(os.path.join(d, 'market_data.json'))
        econ_book = load(os.path.join(d, 'econ_indicators.json'))
        metrics = load(os.path.join(d, 'macro_metrics.json'))
        releases = load(os.path.join(d, 'releases', 'index.json'))
    except Corrupt as e:
        incomplete(str(e))

    # 2026-11-17: 지금 발행하는 글은 책이 없으면 부트스트랩으로 넘기지 않는다 — 자료가 없어 판단할 수 없으면 미완료.
    # --legacy-releases(지난 글을 그 커밋 자료로 재검사)만 옛 판정을 유지한다 — 그때의 자료 폴더에는 없던 파일이 있다.
    from verification.inputs import legacy_recheck
    if legacy_recheck(args.legacy_releases, args.html):     # 1a 적용일 전 글에만(구현 검토 #9)
        market = market or {}
        econ = (econ_book or {}).get('indicators') if isinstance(econ_book, dict) else None
        if prev is None and ev is None:
            print('macro.json / macro_eval.json 둘 다 없다 — 부트스트랩 실행으로 간주하고 '
                  '§8 어휘·표 완성도만 검사한다', file=sys.stderr)
        if releases and releases.get('status') is not None \
                and releases.get('report_date') != market.get('report_date'):
            releases = {'status': 'stale', 'releases': []}
        return _finish(html, prev, ev, nxt, econ, metrics, market, releases)
    if prev is None or ev is None:
        incomplete('macro.json / macro_eval.json 이 없다')
    if not isinstance(market, dict) or not market.get('report_date'):
        incomplete('market_data.json 이 없거나 report_date 가 없다')
    # 축 표 게이트의 기준일은 세션(market_data)이다.
    econ = (econ_book or {}).get('indicators') if isinstance(econ_book, dict) else None
    if not econ:
        incomplete('econ_indicators.json 이 없거나 indicators 가 비었다 — §9 축 표를 대조할 정본이 없다')
    if not isinstance(metrics, dict) or metrics.get('report_date') != market.get('report_date'):
        incomplete(f"macro_metrics.json report_date={(metrics or {}).get('report_date')} ≠ 세션 "
                   f"{market.get('report_date')}")
    # 원문 index (2026-11-06 계약). 지금 발행하는 글은 오늘 세션의 완료된 index 가 있어야 한다.
    if releases is None or releases.get('status') is None:
        incomplete('releases/index.json 이 없거나 2026-11-06 전 형식이다')
    if releases.get('report_date') != market.get('report_date'):
        incomplete(f"releases/index.json 이 {releases.get('report_date')} 것이다")
    if releases.get('status') != 'complete':
        incomplete(f"releases/index.json status={releases.get('status')!r} — 원문 수집이 끝나지 않았다")
    return _finish(html, prev, ev, nxt, econ, metrics, market, releases)


def _finish(html, prev, ev, nxt, econ, metrics, market, releases):
    violations = check(html, prev, ev, nxt, econ=econ, metrics=metrics,
                       report_date=market.get('report_date'), releases=releases)
    if not violations:
        print('매크로 게이트 통과')
        return
    print(f'매크로 게이트 실패 — {len(violations)}건')
    for x in violations:
        print(f'  - {x}')
    sys.exit(1)


if __name__ == '__main__':
    main()
