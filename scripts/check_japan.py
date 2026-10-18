#!/usr/bin/env python3
"""일본 주간 발행 게이트.

    python3 scripts/check_japan.py --html japan_2026-W39.html --key 2026-W39

Exit 0 = 발행 가능. Exit 1 = 위반을 한 줄씩 — 작성자에게 그대로 돌려주고 다시 돌린다.
로직: scripts/japan/gate.py
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT))
from japan.gate import check, number_sources  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--html', required=True)
    ap.add_argument('--key', required=True)
    ap.add_argument('--datadir', default='japan/data',
                    help='진단·뉴스 파일 폴더 (발행 뒤 재검사는 발행 커밋에서 꺼낸 것)')
    args = ap.parse_args(argv)
    try:
        html = Path(args.html).read_text(encoding='utf-8')
        data = Path(args.datadir)
        diag = json.loads((data / f'{args.key}.json').read_text(encoding='utf-8'))
        news = json.loads((data / f'{args.key}.news.json').read_text(encoding='utf-8'))
    except (OSError, ValueError) as e:
        print(f'FATAL: {e}', file=sys.stderr)
        return 2
    # 수치 원천은 실을 수 있는 요약 + 일본어 원제목, 「이번 주 뉴스」 후보는 `digest` 행만
    v = check(html, diag, number_sources(news), [n for n in news if n.get('digest')])
    if not v:
        print('일본 주간 게이트 통과')
        return 0
    print(f'일본 주간 게이트 실패 — {len(v)}건')
    for x in v:
        print(f'  - {x}')
    return 1


if __name__ == '__main__':
    sys.exit(main())
