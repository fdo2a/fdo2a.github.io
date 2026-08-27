#!/usr/bin/env python3
"""thesis 감시 페이지를 push하기 전에 돌리는 게이트.

  python3 scripts/check_thesis.py                      # 세 페이지 전부
  python3 scripts/check_thesis.py thesis/micron.html   # 하나만
  python3 scripts/check_thesis.py --triggers run.json  # 침묵 검사까지

보는 것:
  1) 등급 통제 어휘 · state ↔ 페이지 정합 · kill 두 축
  2) 변경 이력 항목의 7요소, 확정 사실의 출처 표기
  3) 금칙어 — [확인필요]·TODO·buy-side
  4) 수치 불변 — git HEAD 판과 대조해 손대지 않은 곳의 숫자가 움직였는지
  5) 침묵 — 트리거도 확정 사건도 없는데 페이지가 수정됐는지 (--triggers 있을 때)
  6) 모바일 레이아웃 390·1280px (Playwright 있을 때)

5)가 이 게이트의 존재 이유다. "변화 없으면 아무것도 하지 마"는 프롬프트로는 안 지켜진다.

종료 코드 0 = 발행 가능, 1 = 확인할 것이 있음.

Design: docs/superpowers/specs/2026-08-24-thesis-watch-design.md
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from thesis import gate as G          # noqa: E402
from us.post_check import report      # noqa: E402
from verify_post import git_show, layout_findings  # noqa: E402

PAGES = {
    '005930.KS': 'thesis/samsung.html',
    '000660.KS': 'thesis/skhynix.html',
    'MU': 'thesis/micron.html',
}
STATE = 'thesis/data/thesis_state.json'

_CHANGELOG = re.compile(
    r'<ol\b[^>]*\bdata-block="changelog"[^>]*>.*?</ol>', re.S)


def stable_page_content(html):
    """Page content whose existing numeric tokens must remain unchanged.

    A confirmed event is supposed to add a changelog entry, so its dates, source
    references, and factual figures cannot be compared with the pre-event page.
    """
    return _CHANGELOG.sub('', html)


def load_state(path=STATE):
    p = Path(path)
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding='utf-8')).get('tickers', {})


def changed_vs_head(path):
    """이 파일이 HEAD 이후 손댄 것인지.

    `git diff HEAD`만 쓰면 **untracked 파일이 '수정 없음'으로 잡혀** 침묵 검사가 눈이 먼다.
    새로 만든 페이지야말로 트리거 없이 만들어졌을 수 있는 파일이므로 `--porcelain`으로
    untracked까지 본다. 판단이 안 서면 수정된 쪽으로 —— 게이트는 보수적이어야 한다.
    """
    out = subprocess.run(['git', 'status', '--porcelain', '--', path],
                         capture_output=True, text=True)
    if out.returncode:
        return True  # git 밖이면 수정된 것으로 본다
    return bool(out.stdout.strip())


def check_page(symbol, path, state, run):
    findings = []
    book = state.get(symbol, {})
    html = Path(path).read_text(encoding='utf-8')

    kill_evidence = tuple(run.get('kill_evidence', {}).get(symbol, ()))
    for problem in G.check(html, state_grade=book.get('grade'),
                           kill_evidence=kill_evidence):
        where = f' [{problem["where"]}]' if problem.get('where') else ''
        findings.append(f'{problem["check"]}{where}: {problem["message"]}')

    if run:
        silence = G.check_silence(
            triggers=run.get('triggers', {}).get(symbol, []),
            events=run.get('events', {}).get(symbol, []),
            page_changed=changed_vs_head(path))
        if silence:
            findings.append(f'{silence["check"]}: {silence["message"]}')

    before = git_show('HEAD', path)
    if before is not None:
        findings += report(stable_page_content(before), stable_page_content(html))

    return findings


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('pages', nargs='*', help='검사할 페이지 (기본: 세 종목 전부)')
    ap.add_argument('--state', default=STATE)
    ap.add_argument('--triggers', help='오늘 run의 트리거·사건 JSON — 침묵 검사에 필요')
    ap.add_argument('--skip-layout', action='store_true')
    args = ap.parse_args()

    state = load_state(args.state)
    run = json.loads(Path(args.triggers).read_text(encoding='utf-8')) if args.triggers else {}

    targets = ({p: s for s, p in PAGES.items() if p in args.pages}
               if args.pages else {p: s for s, p in PAGES.items()})
    if args.pages and not targets:
        print(f'알 수 없는 페이지: {args.pages}', file=sys.stderr)
        return 1

    total = 0
    for path, symbol in targets.items():
        if not Path(path).exists():
            print(f'없는 파일: {path}')
            total += 1
            continue
        findings = check_page(symbol, path, state, run)
        if not args.skip_layout:
            findings += layout_findings(path)
        if findings:
            total += len(findings)
            print(f'\n확인할 것 {len(findings)}건 — {path}')
            for f in findings:
                print(f'  - {f}')
        else:
            print(f'이상 없음 — {path}')

    if total:
        print(f'\n총 {total}건 — 발행 중단')
        return 1
    print('\n전부 이상 없음 — 발행 가능')
    return 0


if __name__ == '__main__':
    sys.exit(main())
