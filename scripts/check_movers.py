#!/usr/bin/env python3
"""움직인 종목 발행 게이트 — 묶음마다 `<p data-mover="gN">` 문단과 대표 종목 등락률이 있는가.

  python3 scripts/check_movers.py --html morning_brief_2026-09-24.html --datadir <workspace>
  python3 scripts/check_movers.py --html kr_brief_2026-09-24.html --datadir kr/data --market kr

Exit 0 = 발행 가능, 1 = 위반, 2 = 미완료(자료가 없거나 읽히지 않거나 시장 데이터와 날짜가 다르다 — 글을 고쳐서
풀리지 않는다, 재수집). 묶음이 빈 날은 「볼 것 없음」(exit 0, nothing to check)이고, 그것이 정상 조회로 확인된
「해당 없음」인지는 실행기(run_gates)가 수집 상태로 따진다(2026-11-17). 묶음이 없는데 움직인 종목 문단이 있으면 위반.
Logic: scripts/common/movers.py.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.common.movers import check  # noqa: E402

FILES = {'us': ('movers.json', 'market_data.json'),
         'kr': ('kr_movers.json', 'kr_market_data.json')}


def _load(path):
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _has_mover_paragraph(html):
    """게이트 파서(common.movers)와 같은 문법으로 — 보이는 `<p data-mover="gN">` 가 있는가(공백·따옴표 변형 포함)."""
    from scripts.common import movers as M
    return any(not M._HIDDEN.search(attrs) for attrs, _gid, _inner in M._MARKED.findall(M._COMMENT.sub(' ', html or '')))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--html', required=True)
    ap.add_argument('--datadir', default='data')
    ap.add_argument('--market', choices=sorted(FILES), default='us')
    args = ap.parse_args(argv)
    with open(args.html, encoding='utf-8') as fh:
        html = fh.read()
    movers_name, market_name = FILES[args.market]
    movers = _load(os.path.join(args.datadir, movers_name))
    market = _load(os.path.join(args.datadir, market_name)) or {}
    # 자료가 없거나 읽히지 않거나 다른 날 것이면 미완료(2) — 「볼 것 없음」으로 통과시키면 수집 실패가 「움직인
    # 종목 0건」으로 발행된다(2026-11-17, 11/16 KR 의 not_run 이 자료 없음과 같은 문구였다).
    if not isinstance(movers, dict) or not isinstance(movers.get('groups'), list):
        print(f'FATAL: {movers_name} 이 없거나 읽히지 않는다 — 수집을 다시 돌린다', file=sys.stderr)
        return 2
    if not market.get('report_date') or movers.get('report_date') != market.get('report_date'):
        print(f"FATAL: {movers_name} 날짜 {movers.get('report_date')} ≠ {market_name} 날짜 "
              f"{market.get('report_date')} — 수집을 다시 돌린다", file=sys.stderr)
        return 2
    if not movers['groups']:
        if _has_mover_paragraph(html):
            print(f'FAIL 움직인 종목 묶음이 없는 날인데 움직인 종목 문단이 있다({movers_name}) — 문단을 뺀다')
            return 1
        print(f'movers: 묶음 없음({movers_name}) — nothing to check')
        return 0
    violations = check(html, movers, market.get('report_date'))
    if not violations:
        print(f'움직인 종목 이상 없음 — {args.html}')
        return 0
    for v in violations:
        print(f'FAIL {v}')
    return 1


if __name__ == '__main__':
    sys.exit(main())
