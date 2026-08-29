#!/usr/bin/env python3
"""말투가 기관 보고서로 굳었는지 본다.

  python3 scripts/check_style.py posts/2026-08-25.html

「말하듯이 쓴다」 기준에서 셀 수 있는 부분만 검사한다 — 비인칭 피동, 번역투 연결,
서술어 없는 명사형 머리말, 「~한 상태다」식 종결, 같은 문단 머리말 반복, 「~다」 종결
연속. 나머지(주어를 드러냈는가, 한 문장에 한 관계인가)는 사람이 읽어야 안다.

종료 코드 0 = 이상 없음, 1 = 고칠 것이 있음.
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
    if not found:
        print(f'말투 이상 없음 — {args.html}')
        return 0
    print(f'고칠 것 {len(found)}건 — {args.html}')
    for f in found:
        print(f'  - {f["message"]}')
    return 1


if __name__ == '__main__':
    sys.exit(main())
