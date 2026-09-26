#!/usr/bin/env python3
"""발행 후 목록 JSON 과 sitemap 을 갱신한다.

  python3 scripts/update_archives.py --root . --kind weekly --key 2026-08-21 \
      --title "미국 증시 주간 정리 — 2026년 8월 3주" --headline "..."

--kind 는 daily / weekly / monthly / kr-weekly / kr-monthly / news.
daily 는 US 브리프(`posts.json`, 항목 열쇠가 `date`), news 는 뉴스·산업 브리프(2026-09-26) —
둘 다 키가 발행 기준일(YYYY-MM-DD)이다. US 루틴은 sitemap 을 posts.json 으로 **재생성**했는데,
그러면 주간·KR·thesis·뉴스 URL 이 매일 지워진다 — 이 스크립트는 병합만 한다.
같은 키로 다시 돌리면 항목을 교체한다.
"""

import argparse
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from us.archives import merge_sitemap, upsert_entry  # noqa: E402

LISTINGS = {'daily': ('posts.json', 'posts'),
            'weekly': ('weekly.json', 'weekly'),
            'monthly': ('monthly.json', 'monthly'),
            'kr-weekly': ('kr/weekly.json', 'kr/weekly'),
            'kr-monthly': ('kr/monthly.json', 'kr/monthly'),
            'news': ('news.json', 'news')}
BASE = 'https://fdo2a.github.io'
# 목록 항목의 열쇠 이름. posts.json 은 처음부터 `date` 였다(index.html 이 그 이름으로 읽는다).
ENTRY_KEY = {'daily': 'date'}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default='.')
    ap.add_argument('--kind', choices=sorted(LISTINGS), required=True)
    ap.add_argument('--key', required=True)
    ap.add_argument('--title', required=True)
    ap.add_argument('--headline', default='')
    ap.add_argument('--label', default='',
                    help='목록에 보일 날짜 표시(주간·월간). 비우면 목록이 키(2026-W39)를 보인다')
    args = ap.parse_args()

    listing_rel, dir_rel = LISTINGS[args.kind]
    listing = os.path.join(args.root, listing_rel)
    entries = []
    if os.path.exists(listing):
        with open(listing, encoding='utf-8') as fh:
            entries = json.load(fh)
    field = ENTRY_KEY.get(args.kind, 'key')
    entry = {field: args.key, 'title': args.title, 'headline': args.headline}
    if args.label:
        entry['label'] = args.label
    entries = upsert_entry(entries, entry, key=field)
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
