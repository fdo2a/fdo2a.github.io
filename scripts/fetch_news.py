#!/usr/bin/env python3
"""오늘의 CNBC·Yahoo 뉴스를 받아 data/news/<date>.json 으로 커밋한다.

Actions 수집 잡에서 돈다 — `fetch_releases.py` 와 같은 자리, 같은 이유다. 루틴이
대시보드를 옮겨 적는 대신 실제 기사를 읽게 하고, 그 기사가 실재했음을 발행 게이트가
사후에 대조할 수 있게 한다.

**본문은 커밋하지 않는다.** 이 레포는 공개이고(`fdo2a.github.io`) CNBC·Yahoo 기사는
상업 저작물이다. 본문은 `--bodydir`(기본값 `_workspace/`, gitignore 됨)에만 떨어뜨려
그날 루틴이 읽고 버리며, 커밋되는 것은 메타데이터와 거기서 쓴 한국어 요약이다.

비-코어다. 피드가 죽거나 기사가 안 열리면 그 사실을 적고 넘어간다 — 뉴스 섹션이
빠질 뿐 브리프는 발행된다.

  python3 scripts/fetch_news.py --datadir data --date 2026-09-19
"""

import argparse
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
from datetime import date as _date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from us.news import (FEEDS, body_note, dedupe,  # noqa: E402
                     extract_body, parse_feed_strict, select)

UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0 Safari/537.36')
TIMEOUT = 20


def _context():
    """certifi 가 있으면 그걸 쓴다 — 기본 컨텍스트는 CERTIFICATE_VERIFY_FAILED 로 죽는다
    (2026-09-19 실측, `us/fred.py` 의 재시도와 같은 처리)."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return None


# Yahoo 의 종목 피드는 연속 호출에 429 를 준다(2026-09-19 실측: 티커 8개를 붙여
# 때리면 전부 실패). 사이를 띄우고 한 번 더 기다렸다 재시도한다 — 여덟 종목이면
# 10여 초로, Actions 에서는 무시할 수 있는 비용이다.
GAP = 2.0
RETRY_WAIT = 15


def get(url, ctx, retries=2):
    req = urllib.request.Request(
        url, headers={'User-Agent': UA,
                      'Accept': 'application/rss+xml,application/xml;q=0.9,*/*;q=0.8'})
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as r:
                return r.read().decode('utf-8', 'replace')
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries:
                time.sleep(RETRY_WAIT)
                continue
            raise


def fetch_bodies(chosen, bodydir, ctx):
    """선정된 기사의 본문을 bodydir 에 떨어뜨린다. 실패는 건별로 기록하고 넘어간다."""
    os.makedirs(bodydir, exist_ok=True)
    for i, it in enumerate(chosen, 1):
        try:
            body = extract_body(get(it['url'], ctx))
        except Exception as e:
            why = (f'HTTP {e.code}' if isinstance(e, urllib.error.HTTPError)
                   else type(e).__name__)
            it['body_chars'], it['body_note'] = 0, why
            print(f'  [{i}] 본문 실패({why}) {it["url"]}', file=sys.stderr)
            continue
        if not body:
            it['body_chars'], it['body_note'] = 0, body_note(body)
            print(f'  [{i}] 본문 아님({it["body_note"]}) {it["url"]}', file=sys.stderr)
            continue
        title = it.get('title') or '(제목 없음)'
        name = f'{i:02d}-{it["category"]}.txt'
        try:                       # 쓰기 실패가 나머지 건을 끊지 않는다(2차 #13)
            with open(os.path.join(bodydir, name), 'w', encoding='utf-8') as fh:
                fh.write(f'# {title}\n# {it.get("source")} · {it.get("published")}\n'
                         f'# {it["url"]}\n\n{body}\n')
        except OSError as e:
            it['body_chars'], it['body_note'] = 0, f'저장 실패 {type(e).__name__}'
            print(f'  [{i}] 저장 실패 {name}', file=sys.stderr)
            continue
        it['body_chars'], it['body_file'] = len(body), name
        print(f'  [{i}] {it["category"]:8s} 본문 {len(body):5d}자  {title[:52]}')
    return chosen


def save_json(path, payload):
    """원자적 교체 — 'w' 로 직접 덮어쓰다 실패하면 기존 수집분까지 깨진다(2차 #13)."""
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def bodies_only(args):
    """커밋된 메타데이터로 본문만 다시 받는다 — 루틴의 워크스페이스용."""
    path = os.path.join(args.datadir, 'news', f'{args.date}.json')
    try:
        with open(path, encoding='utf-8') as fh:
            data = json.load(fh)
    except FileNotFoundError:
        print(f'{path} 없음 — 그날 뉴스 섹션 없이 발행한다')
        return
    items = data.get('items') or []
    if not items:
        print(f'{path} 에 항목 없음 — 뉴스 섹션 없이 발행한다')
        return
    fetch_bodies(items, args.bodydir, _context())
    save_json(path, data)
    got = sum(1 for it in items if it.get('body_chars'))
    print(f'{args.bodydir} — 본문 {got}/{len(items)}건 확보')
    if not got:
        print('본문을 한 건도 받지 못했다 — 그날은 뉴스 섹션 없이 발행한다',
              file=sys.stderr)
        return 1
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--datadir', default='data')
    ap.add_argument('--bodydir', default='_workspace/news')
    ap.add_argument('--date', default=_date.today().isoformat())
    ap.add_argument('--per-category', type=int, default=3)
    ap.add_argument('--bodies-only', action='store_true',
                    help='이미 커밋된 news/<date>.json 을 읽어 본문만 이 워크스페이스로 '
                         '다시 받는다. 루틴이 쓰는 모드다 — Actions 러너의 _workspace '
                         '는 그 잡이 끝나면 사라지므로 본문이 작성 환경에 도달하지 '
                         '않는다(2026-09-19 codex 검토 #3).')
    args = ap.parse_args()

    if args.bodies_only:
        return bodies_only(args) or 0

    ctx = _context()
    harvested, notes = [], []
    for category, urls in FEEDS.items():
        for i, url in enumerate(urls):
            if i:
                time.sleep(GAP)        # 같은 호스트를 붙여 때리지 않는다
            try:
                items, why_empty = parse_feed_strict(get(url, ctx), category)
                if why_empty:
                    notes.append(f'{category} {url}: {why_empty}')
                    print(f'  {category}: {why_empty}', file=sys.stderr)
            except Exception as e:
                why = (f'HTTP {e.code}' if isinstance(e, urllib.error.HTTPError)
                       else type(e).__name__)
                notes.append(f'{category} {url}: {why}')
                print(f'  {category}: 피드 실패 ({why}) {url[-40:]}', file=sys.stderr)
                continue
            if not items:
                notes.append(f'{category} {url}: 항목 0건')
            harvested.extend(items)
            print(f'  {category}: {len(items)}건 ({url.split("/")[2]})')

    chosen = select(dedupe(harvested), per_category=args.per_category)
    print(f'수집 {len(harvested)}건 → 중복 제거·선정 {len(chosen)}건')

    fetch_bodies(chosen, args.bodydir, ctx)

    outdir = os.path.join(args.datadir, 'news')
    os.makedirs(outdir, exist_ok=True)
    path = os.path.join(outdir, f'{args.date}.json')
    save_json(path, {'report_date': args.date, 'harvested': len(harvested),
                     'notes': notes, 'items': chosen})
    got = sum(1 for it in chosen if it.get('body_chars'))
    print(f'{path} — 본문 {got}/{len(chosen)}건 확보')


if __name__ == '__main__':
    sys.exit(main() or 0)
