#!/usr/bin/env python3
"""네이버증권 주요뉴스를 받아 kr/data/news/<date>.json 으로 커밋한다.

KR 수집 잡(`collect-kr-data.yml`)에서 돈다. US `fetch_news.py` 와 같은 계약이다 — 본문은
`--bodydir`(gitignore)에만 두고, 이 잡 안에서 한국어 요약(`summary_ko`)을 만든 뒤 메타데이터와
요약만 커밋한다. 발행 게이트는 `check_news.py --market kr` 이다. 순수 로직은 `kr/news.py`.

비-코어다. 목록이 죽으면 빈 수집분과 사유를 남기고 **종료 코드 1** 로 끝난다 — 워크플로
단계가 빨갛게 보이되(`continue-on-error`) 수집 잡은 서지 않는다. 그날 뉴스 섹션만 빠진다.

  python3 scripts/fetch_kr_news.py --datadir kr/data --date 2026-09-25
"""

import argparse
import json
import os
import sys
import time
import urllib.error
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fetch_news import _context, get, save_json  # noqa: E402
from kr.news import (KST, LIST_URL, MAX_PAGES, PAGE_SIZE, SECTION_URL,  # noqa: E402
                     WORLD_SECTIONS, article_published, body_note, categorize, dedupe,
                     extract_body, older_than, on_date, parse_list, parse_section, select,
                     trim)
from us.news_summary import SYSTEM_KO_SOURCE, summarize_items  # noqa: E402

GAP = 0.5              # 같은 호스트를 붙여 때리지 않는다


def _why(e):
    return f'HTTP {e.code}' if isinstance(e, urllib.error.HTTPError) else type(e).__name__


def harvest(report_date, ctx, fetch=None, pages=MAX_PAGES):
    """(발행일까지 닿은 목록 행, 사유 목록). 발행일보다 앞선 기사가 나오면 멈춘다."""
    fetch = fetch or get
    rows, notes = [], []
    for page in range(1, pages + 1):
        if page > 1:
            time.sleep(GAP)
        try:
            got = parse_list(json.loads(fetch(LIST_URL.format(page=page, size=PAGE_SIZE), ctx)))
        except Exception as e:
            notes.append(f'주요뉴스 {page}쪽: {_why(e)} {str(e)[:160]}')
            break
        if not got:
            notes.append(f'주요뉴스 {page}쪽: 0건')
            break
        rows.extend(got)
        if older_than(got, report_date):
            break
    else:
        notes.append(f'주요뉴스 {pages}쪽까지 {report_date} 이전 기사에 닿지 못했다 — 앞쪽 기사가 빠졌을 수 있다')
    return rows, notes


def harvest_world(report_date, ctx, fetch=None, gap=GAP):
    """(세계 섹션 행, 사유 목록). 섹션 하나가 죽어도 나머지는 읽는다 — 글로벌 칸이 얇아질 뿐이다."""
    fetch = fetch or get
    rows, notes = [], []
    day = report_date.replace('-', '')
    for i, (sid1, sid2, name) in enumerate(WORLD_SECTIONS):
        if i and gap:
            time.sleep(gap)
        try:
            got = parse_section(fetch(SECTION_URL.format(sid1=sid1, sid2=sid2, date=day), ctx))
        except Exception as e:
            notes.append(f'세계 {name}: {_why(e)} {str(e)[:160]}')
            continue
        if not got:
            notes.append(f'세계 {name}: 0건')
        rows.extend(got)
    return rows, notes


def fetch_bodies(chosen, bodydir, ctx, fetch=None):
    """선정 기사 본문을 bodydir 에 떨어뜨린다. 실패는 건별로 적고 넘어간다.

    세계 섹션 행은 목록에 날짜가 없다 — 기사면의 입력 시각을 적는다(`trim` 이 발행일과 대조).
    """
    fetch = fetch or get
    os.makedirs(bodydir, exist_ok=True)
    for i, it in enumerate(chosen, 1):
        try:
            page = fetch(it['url'], ctx)
        except Exception as e:
            it['body_chars'], it['body_note'] = 0, _why(e)
            print(f'  [{i}] 본문 실패({_why(e)}) {it["url"]}', file=sys.stderr)
            continue
        if not it.get('published'):
            it['published'] = article_published(page)
        body = extract_body(page)
        if not body:
            it['body_chars'], it['body_note'] = 0, body_note(page)
            print(f'  [{i}] 본문 아님({it["body_note"]}) {it["url"]}', file=sys.stderr)
            continue
        name = f'{i:02d}-{it["category"]}.txt'
        try:
            with open(os.path.join(bodydir, name), 'w', encoding='utf-8') as fh:
                fh.write(f'# {it.get("title")}\n# {it.get("source")} · {it.get("published")}\n'
                         f'# {it["url"]}\n\n{body}\n')
        except OSError as e:
            it['body_chars'], it['body_note'] = 0, f'저장 실패 {type(e).__name__}'
            continue
        it['body_chars'], it['body_file'] = len(body), name
        print(f'  [{i}] {it["category"]:8s} 본문 {len(body):5d}자  {(it.get("title") or "")[:40]}')
        time.sleep(GAP)
    return chosen


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--datadir', default='kr/data')
    ap.add_argument('--bodydir', default='_workspace/kr_news')
    ap.add_argument('--date', default=datetime.now(KST).date().isoformat(),
                    help='발행일(KST). 수집 잡은 kr_market_data.json 의 report_date 를 준다')
    ap.add_argument('--per-category', type=int, default=3)
    args = ap.parse_args(argv)

    ctx = _context()
    harvested, notes = harvest(args.date, ctx)
    world, world_notes = harvest_world(args.date, ctx)
    notes += world_notes
    todays = on_date(harvested, args.date)
    # 주요뉴스가 먼저 — 같은 기사가 세계 섹션에도 있으면 주요뉴스 갈래로 남는다
    chosen = select(categorize(dedupe(todays + world)), per_category=args.per_category)
    print(f'주요뉴스 {len(harvested)}건 → {args.date} {len(todays)}건 · 세계 섹션 {len(world)}건 '
          f'→ 선정 {len(chosen)}건(글로벌은 후보)')
    for n in notes:
        print(f'  {n}', file=sys.stderr)

    fetch_bodies(chosen, args.bodydir, ctx)
    chosen = trim(chosen, args.date)       # 글로벌 확정 — 본문이 있고 기사면 날짜가 발행일인 것만

    outdir = os.path.join(args.datadir, 'news')
    os.makedirs(outdir, exist_ok=True)
    path = os.path.join(outdir, f'{args.date}.json')
    payload = {'report_date': args.date, 'source': '네이버증권 주요뉴스',
               'harvested': len(harvested), 'harvested_world': len(world),
               'notes': notes, 'items': chosen}
    save_json(path, payload)             # 요약이 어떻게 죽어도 수집분은 남는다
    try:
        summarized = summarize_items(chosen, args.bodydir, system=SYSTEM_KO_SOURCE)
    except Exception as e:
        summarized = 0
        notes.append(f'요약 단계 실패: {type(e).__name__}')
    save_json(path, payload)
    got = sum(1 for it in chosen if it.get('body_chars'))
    print(f'{path} — 본문 {got}/{len(chosen)}건 · 요약 {summarized}건')
    return 0 if harvested else 1


if __name__ == '__main__':
    sys.exit(main())
