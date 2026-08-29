#!/usr/bin/env python3
"""발행 후 목록 JSON 과 sitemap 을 갱신한다.

  python3 scripts/update_archives.py --root . --kind weekly --key 2026-08-21 \
      --title "미국 증시 주간 정리 — 2026년 8월 3주" --headline "..."

--kind 는 weekly / monthly / kr-weekly / kr-monthly.
같은 키로 다시 돌리면 항목을 교체한다.
"""

import argparse
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from us.archives import merge_sitemap, upsert_entry  # noqa: E402

LISTINGS = {'weekly': ('weekly.json', 'weekly'),
            'monthly': ('monthly.json', 'monthly'),
            'kr-weekly': ('kr/weekly.json', 'kr/weekly'),
            'kr-monthly': ('kr/monthly.json', 'kr/monthly')}
BASE = 'https://fdo2a.github.io'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default='.')
    ap.add_argument('--kind', choices=sorted(LISTINGS), required=True)
    ap.add_argument('--key', required=True)
    ap.add_argument('--title', required=True)
    ap.add_argument('--headline', default='')
    args = ap.parse_args()

    listing_rel, dir_rel = LISTINGS[args.kind]
    listing = os.path.join(args.root, listing_rel)
    entries = []
    if os.path.exists(listing):
        with open(listing, encoding='utf-8') as fh:
            entries = json.load(fh)
    entries = upsert_entry(entries, {'key': args.key, 'title': args.title,
                                     'headline': args.headline})
    os.makedirs(os.path.dirname(listing) or '.', exist_ok=True)
    with open(listing, 'w', encoding='utf-8') as fh:
        json.dump(entries, fh, ensure_ascii=False, indent=2)
    print(f'{listing_rel}: {len(entries)} entries')

    sp = os.path.join(args.root, 'sitemap.xml')
    existing = ''
    if os.path.exists(sp):
        with open(sp, encoding='utf-8') as fh:
            existing = fh.read()
    today = datetime.date.today().isoformat()
    merged = merge_sitemap(existing, [f'{BASE}/{dir_rel}/{args.key}.html'], today)
    with open(sp, 'w', encoding='utf-8') as fh:
        fh.write(merged)
    print(f'sitemap.xml merged (+1 url, {today})')


if __name__ == '__main__':
    main()
