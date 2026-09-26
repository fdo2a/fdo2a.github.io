#!/usr/bin/env python3
"""뉴스 자리표시를 요약 블록으로 채운다 (뉴스·산업 브리프, ORCHESTRATOR STEP 3.5).

    python3 scripts/expand_news_items.py --body news_industry_2026-09-25.body.html \
        --news news/2026-09-25.json --out news_industry_2026-09-25.body.expanded.html

Exit 1 이면 채우지 못한 자리표시를 나열한다 — 그 기사는 블록을 직접 쓰거나 뺀다.
로직: scripts/us/news_expand.py
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from us.news_expand import PLACEHOLDER, expand  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--body', required=True)
    ap.add_argument('--news', required=True)
    ap.add_argument('--out', required=True)
    a = ap.parse_args(argv)
    body = Path(a.body).read_text(encoding='utf-8')
    news = json.loads(Path(a.news).read_text(encoding='utf-8'))
    out, errors = expand(body, news)
    Path(a.out).write_text(out, encoding='utf-8')
    n = len(PLACEHOLDER.findall(body))
    print(f'{a.out} — 자리표시 {n}개 중 {n - len(errors)}개 채움')
    for e in errors:
        print(f'  - {e}')
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
