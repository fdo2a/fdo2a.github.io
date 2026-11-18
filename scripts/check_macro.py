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


HOLD_SENSITIVE = '승인된 결측이 판단을 바꿀 수 있음 — 사람 승인 필요'


def coverage_hold(metrics):
    """원천 미발표로 점수에서 빠진 지표가 있는 날 — 그 지표가 있었다면 축 판단이 달라질 수 있으면 자동 발행하지 않는다
    (2026-11-17 사용자 승인 조건 8). -> 보류 사유 | None. 판정은 결정적이다: 자료의 점수로 다시 계산한다
    (`us.macro_metrics.sensitivity` — 빠진 지표가 모두 점수 범위의 아래 끝·위 끝일 때 방향·강도·레짐 다리가 지금과 같은가).
    자료가 서로 맞지 않아 판정할 수 없으면 그것도 보류다. 사람 승인 절차는 아직 없다 — 보류로 끝난다."""
    from us import macro_metrics as M
    col = metrics.get('collect') if isinstance(metrics.get('collect'), dict) else {}
    cov = metrics.get('coverage')
    # 축 점수에 쓰이지 않은 지표 — 세 곳이 같은 것을 말해야 한다: 지표 행(여기서 직접 본다), 수집 상태, 산출 범위.
    # 행에서 직접 보는 것은 수집 상태와 산출 범위가 함께 빠뜨린 점수 결측을 잡으려는 것이다(3회차 G2).
    in_rows = sorted((why, name) for name, _axis, why in M.unused_scored(metrics.get('indicators')))
    named = sorted(tuple(str(m)[len('econ:'):].split(':', 1)) if str(m).startswith('econ:no_value:')
                   else tuple(str(m).split(':', 1))
                   for m in col.get('missing') or []
                   if str(m).startswith(('econ:no_value:', 'no_score:', 'introduced:')))
    if not named and not cov and not in_rows:
        return None
    if not isinstance(cov, dict) or not cov:
        return (f'축 점수에 쓰이지 않은 지표({", ".join(n for _w, n in sorted(set(named) | set(in_rows)))})가 있는데 '
                'macro_metrics.json 에 산출 범위(coverage)가 없다 — 그 축 점수가 몇 개 중 몇 개로 나왔는지 알 수 없다')
    listed = sorted((e.get('why'), e.get('name')) for c in cov.values() if isinstance(c, dict)
                    for e in c.get('excluded') or [] if isinstance(e, dict))
    rows_listed = [x for x in listed if x[0] in ('no_score', 'introduced')]
    if rows_listed != in_rows:
        return (f'지표 행에서 본 점수 결측({[n for _w, n in in_rows]})과 산출 범위의 제외 지표'
                f'({[n for _w, n in rows_listed]})가 다르다')
    if col and [x for x in listed if x[0] != 'no_row'] != named:
        return (f'수집 상태가 말하는 빠진 지표({[n for _w, n in named]})와 산출 범위의 제외 지표'
                f'({[n for _w, n in listed]})가 다르다')
    for axis, c in sorted(cov.items()):
        ex = c.get('excluded') if isinstance(c, dict) else None
        if not isinstance(ex, list) or not ex:
            return f'{axis} 축의 산출 범위 형식이 다르다'
        used = sum(1 for r in M.scored_rows(metrics.get('indicators')) if r.get('axis') == axis
                   and r.get('signed_z') is not None)
        if c.get('used') != used or c.get('total') != used + len(ex):
            return f'{axis} 축의 산출 범위({c.get("used")}/{c.get("total")})가 지표 행({used}개)과 맞지 않는다'
        s = M.sensitivity(metrics.get('indicators'), axis, len(ex))
        if not s['stable']:
            ko = M.AXIS_LABELS_KO.get(axis, axis)
            return (f'{HOLD_SENSITIVE}({ko} 축 {c.get("total")}개 중 {used}개로 산출: 지금 {s["now"]}, 빠진 {len(ex)}개가 '
                    f'점수 범위 아래 끝(-{s["bound"]})이면 {s["low"]}, 위 끝(+{s["bound"]})이면 {s["high"]})')
    return None


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
    hold = coverage_hold(metrics)
    if hold:
        print(f'FATAL: {hold} — 미완료, 보류한다(글을 고쳐서 풀리지 않는다)', file=sys.stderr)
        sys.exit(2)
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
