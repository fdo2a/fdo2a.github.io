#!/usr/bin/env python3
"""무게중심 게이트 — 시황·가격 대 판단·포지션.

  python3 scripts/check_weight.py --html morning_brief_2026-08-30.html --datadir . --market us
  python3 scripts/check_weight.py --html kr_brief_2026-08-30.html --datadir kr/data --market kr

Exit 0 = 발행 가능. Exit 1 = 위반이 한 줄씩 찍힌다 — 그대로 writer에게 돌려주고 다시 돌린다.
「경고:」 줄은 분량·균형 경고로 종료 코드에 영향이 없다(2026-10-13).
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from us.weight import check, narrative, warnings  # noqa: E402

MARKET_FILE = {'us': 'market_data.json', 'kr': 'kr_market_data.json'}


def _load(path):
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--html', required=True)
    ap.add_argument('--datadir', default='data')
    ap.add_argument('--market', choices=('us', 'kr'), default='us')
    ap.add_argument('--allow-missing-eval', action='store_true',
                    help='macro_eval.json 없이 검사한다 — 옛 발행본 점검용')
    args = ap.parse_args()

    try:
        with open(args.html, encoding='utf-8') as fh:
            doc = fh.read()
    except OSError as e:
        print(f'FATAL: cannot read {args.html}: {e}', file=sys.stderr)
        sys.exit(2)

    market_data = _load(os.path.join(args.datadir, MARKET_FILE[args.market]))
    macro_eval = _load(os.path.join(args.datadir, 'macro_eval.json'))

    # macro_eval이 없으면 축약일인지 알 수 없고, 모르는 채 평시 문턱(4,600/0.75)을
    # 적용하면 축약일이 느슨하게 통과한다. 모르면 막는다(2026-08-30 codex 검토).
    if args.market == 'us' and macro_eval is None and not args.allow_missing_eval:
        print(f'macro_eval.json을 {args.datadir}에서 읽지 못했다 — 축약일 여부를 모르는 채 '
              '문턱을 고를 수 없다. scripts/eval_macro_regime.py를 먼저 돌릴 것 '
              '(옛 발행본을 검사할 때만 --allow-missing-eval)')
        sys.exit(1)

    violations = check(doc, market=args.market, market_data=market_data,
                       macro_eval=macro_eval)
    # 경고는 발행을 막지 않는다(2026-10-13) — 위반과 함께 찍되 종료 코드는 위반만 정한다.
    # 분량은 매번 찍는다 — 1주 비교(10/13~10/19)를 루틴 로그와 발행본으로 다시 셀 수 있게.
    n = narrative(doc, market=args.market)
    print(f'분량: 본문 {n["body"]}자 · 뉴스 요약 {n["news"]}자 · 전체 {n["all"]}자 (공백 제외)')
    for w in warnings(doc, market=args.market):
        print(f'경고: {w}')
    if violations:
        for x in violations:
            print(x)
        sys.exit(1)
    day = '축약일' if (macro_eval or {}).get('abbreviated') else '발표일'
    print(f'OK — 무게중심 게이트 통과 ({day})')


if __name__ == '__main__':
    main()
