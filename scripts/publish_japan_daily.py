#!/usr/bin/env python3
"""일본 일간 발행 단계 — 수집 후보를 발행 스냅샷으로 고정하고 이력·목록·sitemap 을 갱신한다 (2026-10-27).

게이트를 다 통과한 뒤 오케스트레이터가 부른다. 커밋은 하지 않는다(오케스트레이터 STEP 3).
- `japan/data/daily/candidate/<s>.json` → `japan/data/daily/<s>.json`(발행 스냅샷). 발행된 세션은
  다시 발행하지 않는다 — 이후 수정은 review-gate 정정 경로다. 수집기도 발행 스냅샷을 덮지 않는다.
- 이력 `japan/data/history/jp_daily.jsonl` 에 발행 당시 가격(다음 세션의 분모)을 세션 키로 upsert.
- `japan/daily.json` 항목(같은 날짜는 교체)과 sitemap(기존 URL 보존, 병합만).

  python3 scripts/publish_japan_daily.py --session 2026-10-26 --title "…" --headline "…"
"""
import argparse
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from us.archives import merge_sitemap, upsert_entry  # noqa: E402

BASE = 'https://fdo2a.github.io'
DAILY = os.path.join('japan', 'data', 'daily')
HISTORY = os.path.join('japan', 'data', 'history', 'jp_daily.jsonl')
LISTING = os.path.join('japan', 'daily.json')


class AlreadyPublished(Exception):
    pass


def _write_json(path, obj, indent=1):
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=indent)
        fh.write('\n')


def history_row(snap):
    prices = {}
    etf = (snap.get('indices') or {}).get('topix_etf') or {}
    if etf.get('ok') and etf.get('value') is not None:
        prices['1306'] = etf['value']
    for row in (snap.get('sectors') or []) + (snap.get('stocks') or []):
        if row.get('value') is not None and row.get('ok', True):
            prices[row['code']] = row['value']
    return {'session': snap['session'], 'nikkei': snap['indices']['nikkei']['value'],
            'prices': dict(sorted(prices.items()))}


def _upsert_history(path, row):
    rows = []
    if os.path.exists(path):
        with open(path, encoding='utf-8') as fh:
            rows = [json.loads(line) for line in fh if line.strip()]
    rows = [r for r in rows if r.get('session') != row['session']] + [row]
    rows.sort(key=lambda r: r['session'])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + '\n')


def publish(root, session, title, headline):
    pub = os.path.join(root, DAILY, f'{session}.json')
    if os.path.exists(pub):
        raise AlreadyPublished(f'{session} 은 이미 발행됐다 — 고칠 때는 review-gate 정정 경로를 쓴다')
    with open(os.path.join(root, DAILY, 'candidate', f'{session}.json'), encoding='utf-8') as fh:
        snap = json.load(fh)
    if not snap.get('complete') or snap.get('session') != session:
        raise ValueError(f'{session} 수집 후보가 발행할 수 없는 상태다(complete={snap.get("complete")})')
    snap['published'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    _write_json(pub, snap)
    _upsert_history(os.path.join(root, HISTORY), history_row(snap))
    listing = os.path.join(root, LISTING)
    entries = []
    if os.path.exists(listing):
        with open(listing, encoding='utf-8') as fh:
            entries = json.load(fh)
    _write_json(listing, upsert_entry(entries, {'date': session, 'title': title, 'headline': headline},
                                      key='date'), indent=2)
    sp = os.path.join(root, 'sitemap.xml')
    existing = open(sp, encoding='utf-8').read() if os.path.exists(sp) else ''
    with open(sp, 'w', encoding='utf-8') as fh:
        fh.write(merge_sitemap(existing, [f'{BASE}/japan/daily/{session}.html'],
                               datetime.date.today().isoformat()))
    return snap


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default='.')
    ap.add_argument('--session', required=True)
    ap.add_argument('--title', required=True)
    ap.add_argument('--headline', default='')
    args = ap.parse_args(argv)
    try:
        publish(args.root, args.session, args.title, args.headline)
    except (AlreadyPublished, ValueError, FileNotFoundError) as e:
        print(e, file=sys.stderr)
        return 2
    print(f'japan/daily/{args.session} — 발행 스냅샷·이력·목록·sitemap 갱신')
    return 0


if __name__ == '__main__':
    sys.exit(main())
