#!/usr/bin/env python3
"""직접 고친 발행본을 푸시하기 전에 한 번 돌리는 검사.

  python3 scripts/verify_post.py posts/2026-08-19.html

세 가지를 본다.
  1) 수치 불변  — git에 있는 판(기본 HEAD)과 비교해 숫자·티커가 늘거나 준 곳
  2) 금지 표기  — [확인필요]·TODO 같은 미완 마커
  3) 모바일 레이아웃 — 390px·1280px에서 페이지가 가로로 밀리는지 (Playwright 있을 때만)

문장을 고치는 건 얼마든지 해도 되고, 숫자가 움직이면 걸린다. 일부러 문단을 지웠다면
1)이 그 문단의 숫자를 나열해줄 테니 눈으로 확인하고 넘어가면 된다.

종료 코드 0 = 이상 없음, 1 = 확인할 것이 있음.
"""

import argparse
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from us.post_check import report  # noqa: E402

MOBILE, DESKTOP = 390, 1280


def git_show(ref, path):
    """그 파일의 `ref` 시점 내용. 새 파일이거나 git 밖이면 None."""
    root = subprocess.run(['git', 'rev-parse', '--show-toplevel'],
                          capture_output=True, text=True)
    if root.returncode:
        return None
    rel = os.path.relpath(os.path.abspath(path), root.stdout.strip())
    out = subprocess.run(['git', 'show', f'{ref}:{rel}'], capture_output=True, text=True)
    return out.stdout if out.returncode == 0 else None


def layout_findings(path):
    """가로로 밀리는 뷰포트와 그 원인 요소. Playwright가 없으면 빈 목록."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print('  (Playwright가 없어 레이아웃 검사는 건너뛴다 — pip install playwright)')
        return []

    findings = []
    culprit = """() => {
      const e = [...document.querySelectorAll('body *')].find(x =>
        x.scrollWidth > x.clientWidth + 1 && getComputedStyle(x).overflowX === 'visible'
        && x.children.length === 0);
      return e ? e.textContent.trim().slice(0, 60) : '';
    }"""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for width in (MOBILE, DESKTOP):
            page = browser.new_page(viewport={'width': width, 'height': 900})
            page.goto('file://' + os.path.abspath(path))
            page.wait_for_timeout(400)
            actual = page.evaluate('document.documentElement.scrollWidth')
            if actual > width:
                where = page.evaluate(culprit)
                findings.append(f'{width}px에서 페이지가 {actual}px로 밀린다'
                                + (f' — 「{where}…」' if where else ''))
            page.close()
        browser.close()
    return findings


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('html', help='검사할 발행본 (예: posts/2026-08-19.html)')
    ap.add_argument('--base', default='HEAD', help='비교 기준 git ref (기본 HEAD)')
    ap.add_argument('--skip-layout', action='store_true')
    args = ap.parse_args()

    with open(args.html, encoding='utf-8') as fh:
        after = fh.read()
    before = git_show(args.base, args.html)
    if before is None:
        print(f'  ({args.base}에 이 파일이 없다 — 수치 대조는 건너뛰고 나머지만 본다)')

    findings = report(before, after)
    if not args.skip_layout:
        findings += layout_findings(args.html)

    if not findings:
        print(f'이상 없음 — {args.html}')
        return 0
    print(f'확인할 것 {len(findings)}건 — {args.html}')
    for f in findings:
        print(f'  - {f}')
    return 1


if __name__ == '__main__':
    sys.exit(main())
