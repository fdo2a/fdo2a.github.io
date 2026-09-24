#!/usr/bin/env python3
"""말투가 기관 보고서로 굳었는지 본다.

  python3 scripts/check_style.py posts/2026-08-25.html

「말하듯이 쓴다」 기준에서 셀 수 있는 부분만 검사한다 — 비인칭 피동, 번역투 연결,
서술어 없는 명사형 머리말, 「~한 상태다」식 종결, 같은 문단 머리말 반복, 「~다」 종결
연속. 나머지(주어를 드러냈는가, 한 문장에 한 관계인가)는 사람이 읽어야 안다.

`<body data-register="da">` 문서(US·KR 데스크)는 어미 혼합·수사의문·작업 어휘·「국채 급등」도
막고, 줄표·단서 문장·같은 수치 반복은 경고만 한다.

종료 코드 0 = 이상 없음(경고만 있어도 0), 1 = 고칠 것이 있음.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from us.style import findings  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('html')
    args = ap.parse_args()
    with open(args.html, encoding='utf-8') as fh:
        found = findings(fh.read())
    fails = [f for f in found if f.get('level', 'fail') == 'fail']
    warns = [f for f in found if f.get('level') == 'warn']
    if not found:
        print(f'말투 이상 없음 — {args.html}')
        return 0
    if fails:
        print(f'고칠 것 {len(fails)}건 — {args.html}')
        for f in fails:
            print(f'  - {f["message"]}')
    if warns:
        print(f'경고 {len(warns)}건(발행은 막지 않는다) — {args.html}')
        for f in warns:
            print(f'  · {f["message"]}')
    return 1 if fails else 0

if __name__ == '__main__':
    sys.exit(main())
