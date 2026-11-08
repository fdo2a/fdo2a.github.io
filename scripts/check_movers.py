#!/usr/bin/env python3
"""움직인 종목 발행 게이트 — 묶음마다 `<p data-mover="gN">` 문단과 대표 종목 등락률이 있는가.

  python3 scripts/check_movers.py --html morning_brief_2026-09-24.html --datadir <workspace>
  python3 scripts/check_movers.py --html kr_brief_2026-09-24.html --datadir kr/data --market kr

movers 파일이 없거나, 묶음이 비었거나, 같은 폴더 시장 데이터와 report_date 가 다르면
강제하지 않는다(비-코어). Exit 0 = 발행 가능, 1 = 위반. Logic: scripts/common/movers.py.
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
    # 자료가 쓸 수 없으면 check() 는 강제하지 않고 빈 목록을 낸다(수집 실패한 날 어제 종목을 강요하지 않게).
    # 종료 코드는 그대로 두되 「검사해서 이상 없음」과 「볼 자료가 없음」을 출력으로 가른다 — 발행 전 검증 기록이
    # 앞의 것만 통과로 센다. 자료 없이 움직인 종목 문단이 실렸으면 그 수치는 대조되지 않은 것이다(2026-11-08).
    why = ('자료 없음·읽기 실패' if not movers else '묶음 없음' if not movers.get('groups')
           else '다른 날 자료' if movers.get('report_date') != market.get('report_date') else None)
    if why:
        if _has_mover_paragraph(html):
            print(f'FATAL: 움직인 종목 문단이 있는데 대조할 자료가 없다 — {why}({movers_name})')
        else:
            print(f'movers: {why}({movers_name}) — nothing to check')
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
