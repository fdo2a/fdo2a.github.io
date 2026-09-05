#!/usr/bin/env python3
"""중국 학습 리포트를 push 하기 전에 돌리는 게이트.

  python3 scripts/check_china.py china/posts/2026-W37.html

보는 것:
  1) 진도      — 정해진 다음 강의를 썼는가 (재탕·건너뛰기·표식 위조)
  2) 되짚기    — 큐가 지목한 강의의 «명제»를 다시 봤는가
  3) 수치 귀속 — 헤드라인이 그 지표·그 달에 묶여 있는가
  4) 수집 완전성 — 못 받은 tier 1 이 「발표 없음」으로 위장되지 않았는가
  5) 시황 상한 — 학습 리포트가 시황으로 미끄러지지 않았는가
  6) 포지션 어휘 — 설명이 매매 신호로 변질되지 않았는가
  7) 용어 풀이 — 중국 고유어를 처음 쓸 때 풀었는가
  8) 금칙어    — [확인필요]·TODO·buy-side

4)와 5)가 이 게이트의 존재 이유다. 「시황 얘기는 조금만 해」와 「못 받았으면 없다고 해」는
둘 다 프롬프트로 안 지켜진다.

조판 검사(`check_readability.py --strict`)와 문체 검사(`check_style.py`)는 별도로 돈다.

종료 코드 0 = 발행 가능, 1 = 확인할 것이 있음.

Design: docs/superpowers/specs/2026-09-05-china-learning-report-design.md
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from china import gate as G          # noqa: E402
from china import syllabus as S      # noqa: E402

DATA = 'china/data'
BANNED = ('[확인필요]', 'TODO', 'buy-side', 'buy side', '바이사이드')


def _load(path, default=None):
    if not os.path.exists(path):
        if default is None:
            raise SystemExit(f'없는 파일: {path}')
        return default
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


def _dumps(index, reldir):
    out = {}
    for row in index.get('releases', []):
        if row.get('fetch_status') != 'ok':
            continue
        path = os.path.join(reldir, f'{row["key"]}.txt')
        if os.path.exists(path):
            out[row['key']] = open(path, encoding='utf-8').read()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('post', help='발행본 HTML 경로')
    ap.add_argument('--datadir', default=DATA)
    args = ap.parse_args()

    html = open(args.post, encoding='utf-8').read()
    syl = S.load(_load(os.path.join(args.datadir, 'syllabus.json')))
    state = _load(os.path.join(args.datadir, 'curriculum_state.json'),
                  {'version': 1, 'completed': [], 'last_published_week': None})
    man = _load(os.path.join(args.datadir, 'manifest.json'), {})
    index = _load(os.path.join(args.datadir, 'releases', 'index.json'), {'releases': []})
    dumps = _dumps(index, os.path.join(args.datadir, 'releases'))
    # 시세는 시황 블록이 인용한다. 게이트가 안 읽으면 정상 인용 경로가 아예 없어
    # writer 지시와 어긋난다.
    markets = _load(os.path.join(args.datadir, 'markets.json'), {})
    if markets:
        dumps['markets'] = json.dumps(markets, ensure_ascii=False)

    checks = [
        ('진도', G.check_progress(html, state, syl, man=man)),
        ('되짚기', G.check_revisit(html, state)),
        ('수치 귀속', G.check_numbers(html, man, dumps)),
        ('수집 완전성', G.check_release_coverage(index)),
        ('시황 상한', G.check_recap_cap(html)),
        ('포지션 어휘', G.check_position_vocab(html)),
        ('용어 풀이', G.check_gloss(html)),
        ('금칙어', [f'금칙어: {w}' for w in BANNED if w in html]),
    ]

    bad = 0
    for name, findings in checks:
        if findings:
            bad += len(findings)
            print(f'\n[{name}]')
            for f in findings:
                print(f'  - {f}')
        else:
            print(f'[{name}] ok')

    if bad:
        print(f'\n{bad}건 — 발행 보류')
        return 1
    print('\n전부 통과 — 발행 가능')
    return 0


if __name__ == '__main__':
    sys.exit(main())
