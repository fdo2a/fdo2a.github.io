#!/usr/bin/env python3
"""그 기간 발행본을 총정리용 재료로 회수한다 -> recap_source.json.

주간·월간 정리는 시장을 새로 취재하는 글이 아니라 이미 나간 글들을 한 편으로 묶는
글이다. 그래서 주 소스가 원천 시세가 아니라 발행본이다. HTML을 통째로 넘기지 않는다 —
주간 5편이 34K토큰씩이라 컨텍스트가 감당하지 못한다.

  python3 scripts/build_recap_source.py --posts-dir posts --listing posts.json \
      --start 2026-08-24 --end 2026-08-28 --span weekly --key 2026-W35 \
      --out recap_source.json
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from us.recap_source import collect  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--posts-dir', required=True)
    ap.add_argument('--listing', required=True)
    ap.add_argument('--start', required=True)
    ap.add_argument('--end', required=True)
    ap.add_argument('--span', choices=('weekly', 'monthly'), required=True)
    ap.add_argument('--key', required=True)
    ap.add_argument('--out', default='recap_source.json')
    args = ap.parse_args()

    try:
        with open(args.listing, encoding='utf-8') as fh:
            listing = json.load(fh)
    except (OSError, ValueError) as e:
        print(f'FATAL: cannot read {args.listing}: {e}', file=sys.stderr)
        sys.exit(2)

    out = collect(args.posts_dir, listing, args.start, args.end, args.span, args.key)

    posts = out.get('posts') or []
    if not posts:
        print(f'FATAL: {args.start}~{args.end} 구간에 발행본이 없다 — 총정리할 원본이 없다',
              file=sys.stderr)
        sys.exit(1)

    with open(args.out, 'w', encoding='utf-8') as fh:
        json.dump(out, fh, indent=2, ensure_ascii=False)

    print(f'{args.span} {args.key}: 발행본 {len(posts)}편 회수 -> {args.out}')
    for m in (out.get('missing') or []):
        # 목록엔 있는데 파일이 없는 날. 총정리에서 하루가 통째로 빠지면 그날 사건이
        # 사라지므로 조용히 넘어가지 않는다.
        print(f'  주의: {m} 발행본을 찾지 못했다', file=sys.stderr)


if __name__ == '__main__':
    main()
