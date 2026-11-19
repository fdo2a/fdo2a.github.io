#!/usr/bin/env python3
"""발행 후 목록 JSON 과 sitemap 을 갱신한다.

  python3 scripts/update_archives.py --root . --kind weekly --key 2026-08-21 \
      --title "미국 증시 주간 정리 — 2026년 8월 3주" --headline "..."

--kind 는 daily / weekly / kr-weekly / news / kr-news / jp-daily.
kr-news 는 KR 뉴스(2026-11-05, `kr/news.json`, 키는 발행 기준일).
daily 는 US 브리프(`posts.json`, 항목 열쇠가 `date`), news 는 뉴스·산업 브리프(2026-09-26) —
둘 다 키가 발행 기준일(YYYY-MM-DD)이다. US 루틴은 sitemap 을 posts.json 으로 **재생성**했는데,
그러면 주간·KR·thesis·뉴스 URL 이 매일 지워진다 — 이 스크립트는 병합만 한다.
같은 키로 다시 돌리면 항목을 교체한다.

jp-daily(2026-11-19, 설계 20판 §6-5)는 **제목·요약 인자를 받지 않는다** — 일본 일간 발행 루틴의 rebase 충돌
복구에서만 쓰고, 항목은 발행 기록 `japan/data/daily/runs/<key>.json` 의 검증된 `title`·`summary` 로만 만든다.
기록이 없거나 그 세션의 통과 기록이 아니면 exit 2, 아무것도 쓰지 않는다.

  python3 scripts/update_archives.py --kind jp-daily --key 2026-11-18
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
            'kr-weekly': ('kr/weekly.json', 'kr/weekly'),
            'news': ('news.json', 'news'),
            'kr-news': ('kr/news.json', 'kr/news'),
            'jp-daily': ('japan/daily.json', 'japan/daily')}
BASE = 'https://fdo2a.github.io'
# 목록 항목의 열쇠 이름. posts.json 은 처음부터 `date` 였다(index.html 이 그 이름으로 읽는다).
ENTRY_KEY = {'daily': 'date', 'jp-daily': 'date'}


def _jp_daily_record(ap, root, key):
    """-> (title, summary) — 발행 단계가 쓴 기록(gates.json + published_at)에서만."""
    path = os.path.join(root, 'japan', 'data', 'daily', 'runs', f'{key}.json')
    try:
        with open(path, encoding='utf-8') as fh:
            rec = json.load(fh)
    except (OSError, ValueError) as e:
        ap.error(f'{path} 을 읽지 못했다: {e}')
    title, summary = str(rec.get('title') or '').strip(), str(rec.get('summary') or '').strip()
    if rec.get('session') != key or rec.get('verdict') != 'pass' or not title or not summary:
        ap.error(f'{path} 이 {key} 의 통과 기록이 아니다(session={rec.get("session")}, verdict={rec.get("verdict")})')
    return title, summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default='.')
    ap.add_argument('--kind', choices=sorted(LISTINGS), required=True)
    ap.add_argument('--key', required=True)
    ap.add_argument('--title', default=None, help='jp-daily 는 받지 않는다(발행 기록에서 읽는다)')
    ap.add_argument('--headline', default=None)
    ap.add_argument('--label', default='',
                    help='목록에 보일 날짜 표시(주간). 비우면 목록이 키(2026-W39)를 보인다')
    args = ap.parse_args()
    if args.kind == 'jp-daily':
        if args.title is not None or args.headline is not None or args.label:
            ap.error('jp-daily 는 --title·--headline·--label 을 받지 않는다 — runs/<key>.json 의 검증된 값만 쓴다')
        args.title, args.headline = _jp_daily_record(ap, args.root, args.key)
    elif args.title is None:
        ap.error('the following arguments are required: --title')
    if args.headline is None:
        args.headline = ''

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
        if args.kind == 'jp-daily':
            fh.write('\n')      # 발행기(publish_japan_daily)와 같은 바이트 — 충돌 안 난 목록을 rebase 중에 바꾸지 않게
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
