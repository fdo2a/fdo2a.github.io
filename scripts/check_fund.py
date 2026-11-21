#!/usr/bin/env python3
"""펀드 섹션 발행 게이트 — US 「트렌드 유닛 점검」, KR 「아시아 세션 유닛 관측」.

  python3 scripts/check_fund.py --html morning_brief_2026-10-07.html --datadir <workspace>
  python3 scripts/check_fund.py --html kr_brief_2026-10-07.html --datadir kr/data --market kr

글 날짜는 파일명의 YYYY-MM-DD 다(없으면 --date). 적용일(fund.gate.EFFECTIVE) 이전 글은
검사하지 않는다. Exit 0 = 발행 가능, 1 = 위반, 2 = 미완료(2026-11-17): 적용일 이후 글인데 자료가 없거나 읽히지
않거나 오늘 것이 아니거나 `status` 가 ok 가 아니다(partial·unavailable) — 섹션을 빼고 발행하지 않는다, 재수집.
Logic: scripts/fund/gate.py.
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fund.gate import check  # noqa: E402

FILES = {'us': 'fund_board.json', 'kr': 'kr_fund_view.json'}


def _load(path):
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--html', required=True)
    ap.add_argument('--datadir', default='data')
    ap.add_argument('--market', choices=sorted(FILES), default='us')
    ap.add_argument('--date', help='글 날짜(파일명에 없을 때)')
    ap.add_argument('--recheck', action='store_true',
                    help='지난 글을 그 커밋 자료로 재검사(정정기·윤문기) — 2026-11-17 전 판정(자료가 오늘 것이 아니거나 '
                         'unavailable·partial 이면 섹션이 없어야 통과). 발행 실행 목록은 쓰지 않는다')
    ap.add_argument('--print-block', action='store_true',
                    help='그 날 자료로 다시 그린 정본 블록을 출력하고 끝낸다 — 블록 불일치는 '
                         '손으로 고치지 않고 이 출력으로 블록 전체를 바꾼다')
    args = ap.parse_args(argv)
    m = re.search(r'\d{4}-\d{2}-\d{2}', os.path.basename(args.html))
    if m and args.date and args.date != m.group(0):
        print(f'FAIL --date {args.date} 가 파일명 날짜 {m.group(0)} 와 다르다')
        return 1
    post_date = m.group(0) if m else args.date
    if args.print_block:
        from fund.gate import SPEC
        data = _load(os.path.join(args.datadir, FILES[args.market])) or {}
        if post_date and data.get('report_date') != post_date:
            print(f"FAIL 자료 날짜 {data.get('report_date')} 가 글 날짜 {post_date} 와 다르다")
            return 1
        block = SPEC[args.market]['render'](data)
        if not block:
            print('FAIL 이 날 자료로는 블록을 그릴 수 없다(unavailable) — 섹션을 빼야 한다')
            return 1
        sys.stdout.write(block)
        return 0
    if not post_date:
        print('FAIL 글 날짜를 알 수 없다 — 파일명에 YYYY-MM-DD 를 넣거나 --date 를 준다')
        return 1
    with open(args.html, encoding='utf-8') as fh:
        html = fh.read()
    data = _load(os.path.join(args.datadir, FILES[args.market]))
    from fund.gate import EFFECTIVE
    from verification.inputs import legacy_recheck
    # --recheck(옛 판정)은 1a 적용일 전 글에만 — 새 글의 미완료를 재검사에서 통과로 두지 않는다(1a 구현 검토 #9).
    # 날짜는 정규 파일 이름(YYYY-MM-DD.html)으로만 정한다(2회차 F5)
    legacy = legacy_recheck(args.recheck, args.html, args.date)
    from verification.inputs import enforcing
    if enforcing() and post_date >= EFFECTIVE and not legacy:
        why = (f'{FILES[args.market]} 이 없거나 읽히지 않는다' if not isinstance(data, dict) else
               f"자료 날짜 {data.get('report_date')} ≠ 글 날짜 {post_date}" if data.get('report_date') != post_date else
               f"자료 상태 {data.get('status')}" if data.get('status') != 'ok' else None)
        if why:
            # 섹션을 빼고 발행하지 않는다 — 재수집 뒤에도 그러면 보류(2026-11-17)
            print(f'FATAL: {why} — 미완료, 수집을 다시 돌린다', file=sys.stderr)
            return 2
    violations = check(html, data, args.market, post_date)
    if not violations:
        print(f'펀드 섹션 이상 없음 — {args.html}')
        return 0
    for v in violations:
        print(f'FAIL {v}')
    return 1


if __name__ == '__main__':
    sys.exit(main())
