#!/usr/bin/env python3
"""발행 게이트 — 「모의 포트폴리오」 섹션.

  python scripts/check_portfolio.py --html morning_brief_2026-09-01.html --datadir .

Exit 0 = 발행 가능. Exit 1 = 위반을 한 줄씩 출력 — writer 에게 그대로 돌려주고
다시 실행한다.

비-코어의 경계가 여기 있다. `data/portfolio.json` 이 **아예 없으면** 섹션을 싣지
않는 것이 정답이고 그 경우만 통과시킨다. 파일이 있는데 섹션이 없거나, 파일이 다른
기준일을 가리키면 **닫히면서 실패**한다 — 실을 수 있는 날 빼먹는 것은 비-코어가
아니라 누락이다.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from us.portfolio_gate import check, section  # noqa: E402


class Corrupt(Exception):
    pass


def load(path, strict=False):
    """없는 것과 깨진 것은 다르다.

    깨진 파일을 `None` 으로 돌려주면 「섹션을 안 실은 날」과 구분이 안 된다 —
    비-코어의 면제가 사고를 덮는다(2026-09-01 codex 검토).
    """
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except FileNotFoundError:
        return None
    except Exception as e:
        if strict:
            raise Corrupt(f'{path} 를 읽을 수 없다: {e}')
        print(f'WARN: could not read {path}: {e}', file=sys.stderr)
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--html', required=True)
    ap.add_argument('--datadir', default='.')
    args = ap.parse_args()

    try:
        with open(args.html, encoding='utf-8') as fh:
            html = fh.read()
    except OSError as e:
        print(f'FATAL: cannot read {args.html}: {e}', file=sys.stderr)
        sys.exit(2)

    try:
        book = load(os.path.join(args.datadir, 'portfolio.json'), strict=True)
    except Corrupt as e:
        print(str(e))
        sys.exit(1)
    market = load(os.path.join(args.datadir, 'market_data.json')) or {}

    if book is None:
        if section(html):
            print('portfolio.json 이 없는데 「모의 포트폴리오」 섹션이 실렸다 — '
                  '근거 없는 성과는 발행할 수 없다')
            sys.exit(1)
        print('portfolio.json 없음 — 섹션 없이 발행한다 (비-코어)', file=sys.stderr)
        return

    # 책이 오늘 세션을 가리키지 않으면 **섹션이 없어야 한다.** 여기서 리포트 전체를
    # 막으면 비-코어 한 조각이 발행을 세운다 — 게이트가 닫히면서 실패하는 것과
    # 「하루치 리포트를 통째로 잃는 것」은 다르다. 지난 성과를 오늘 날짜로 인쇄하는
    # 것만 막고, 섹션 없는 발행은 통과시킨다. 다음 수집이 책을 굴리면 저절로 돌아온다.
    rd, today = book.get('report_date'), market.get('report_date')
    if today and rd != today:
        if section(html):
            print(f'포트폴리오 책이 {rd} 자인데 오늘은 {today}다 — '
                  f'지난 성과를 오늘 날짜로 실을 수 없다')
            sys.exit(1)
        print(f'portfolio.json 이 {rd} 에서 멈춰 있다 — 섹션 없이 발행한다 (비-코어)',
              file=sys.stderr)
        return

    errs = check(html, book, book.get('performance'), market.get('report_date'))
    if errs:
        for e in errs:
            print(e)
        sys.exit(1)

    perf = book.get('performance') or {}
    itd = (perf.get('returns') or {}).get('itd') or {}
    print(f"모의 포트폴리오 OK — {perf.get('sessions')}거래일 · 기준가 "
          f"{perf.get('nav', 0):.2f} · 설정 이후 {itd.get('portfolio', 0):+.2f}% "
          f"(초과 {itd.get('active', 0):+.2f}%p)")


if __name__ == '__main__':
    main()
