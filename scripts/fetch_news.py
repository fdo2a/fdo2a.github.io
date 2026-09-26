#!/usr/bin/env python3
"""오늘의 CNBC·Yahoo 뉴스를 받아 data/news/<date>.json 으로 커밋한다.

Actions 수집 잡에서 돈다 — `fetch_releases.py` 와 같은 자리, 같은 이유다. 루틴이
대시보드를 옮겨 적는 대신 실제 기사를 읽게 하고, 그 기사가 실재했음을 발행 게이트가
사후에 대조할 수 있게 한다.

**본문은 커밋하지 않는다.** 이 레포는 공개이고(`fdo2a.github.io`) CNBC·Yahoo 기사는
상업 저작물이다. 본문은 `--bodydir`(기본값 `_workspace/`, gitignore 됨)에만 떨어뜨리고,
**이 잡 안에서 한국어 요약(`summary_ko`)까지 만든 뒤** 메타데이터와 요약만 커밋한다
(2026-09-24). 예전에는 루틴이 `--bodies-only` 로 본문을 다시 받게 했는데, 클라우드 루틴
환경은 CNBC·Yahoo 에 403 이라 한 번도 성공하지 못했고 뉴스 섹션은 한 번도 발행되지 않았다.

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
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from us.news import (FEEDS, body_note, categorize, dedupe,  # noqa: E402
                     extract_body, page_published, pages, parse_feed_strict, pdf_text,
                     select, title_wire, trim, wire_of)
from us.news_summary import SYSTEM_ANALYSIS, summarize_items  # noqa: E402

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

# **간격으로는 안 풀렸다.** 9/22·9/23 모두 종목 피드 넷이 전부 429 였고(재시도 포함),
# 로컬에서도 첫 요청부터 429 다 — 속도 제한이 아니라 파이썬·curl 의 TLS 지문을 막는
# 것이다. 브라우저 지문(curl_cffi)으로는 넷 다 200·기사 42건(2026-09-24 실측).
# `fetch_releases.py`·`collect_fed_events.py` 가 기관 사이트 403 에 쓰는 것과 같은 처리다.
# curl_cffi 는 수집 잡이 이미 설치한다. 없으면 예전처럼 urllib 결과를 그대로 올린다.
IMPERSONATE = ('chrome', 'safari')


def _impersonated(url):
    """urllib 이 거절당한 주소를 브라우저 TLS 지문으로 한 번 더. 실패하면 None."""
    try:
        from curl_cffi import requests as creq
    except ImportError:
        return None
    for imp in IMPERSONATE:
        try:
            r = creq.get(url, impersonate=imp, timeout=TIMEOUT)
        except Exception:
            continue
        if r.status_code == 200:
            return r.text
    return None


def get(url, ctx, retries=2, impersonated=_impersonated):
    req = urllib.request.Request(
        url, headers={'User-Agent': UA,
                      'Accept': 'application/rss+xml,application/xml;q=0.9,*/*;q=0.8'})
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as r:
                return r.read().decode('utf-8', 'replace')
        except urllib.error.HTTPError as e:
            if e.code in (403, 429):
                text = impersonated(url)
                if text is not None:
                    return text
            if e.code == 429 and attempt < retries:
                time.sleep(RETRY_WAIT)
                continue
            raise


def get_bytes(url, ctx):
    """PDF 처럼 글자로 풀면 깨지는 응답(일본은행 정책 발표문)."""
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as r:
        return r.read()


def fetch_bodies(chosen, bodydir, ctx, fetch=None, fetch_bytes=None):
    """선정된 기사의 본문을 bodydir 에 떨어뜨린다. 실패는 건별로 기록하고 넘어간다.

    피드에 날짜가 없던 기사(Investing.com 뉴스)는 기사면의 발행 시각을 적는다 — 글로벌·칼럼
    확정(`trim`)이 그 날짜로 창을 본다. 피드 날짜는 덮지 않는다.
    """
    fetch, fetch_bytes = fetch or get, fetch_bytes or get_bytes
    os.makedirs(bodydir, exist_ok=True)
    for i, it in enumerate(chosen, 1):
        try:
            if it['url'].lower().endswith('.pdf'):
                page, body = '', pdf_text(fetch_bytes(it['url'], ctx))
            else:
                page = fetch(it['url'], ctx)
                body = extract_body(page)
            if not it.get('published'):
                it['published'] = page_published(page)
                if it['published']:
                    it['published_from'] = 'page'
            wire = wire_of(body) or (title_wire(it.get('title'))
                                     if 'yahoo.co.jp' in it['url'] else None)
            if wire:
                it['wire'] = wire
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


def summarize_chosen(chosen, bodydir, summarize=summarize_items):
    """뉴스는 기사 프롬프트로, 리포트·칼럼은 견해를 필자에게 귀속하는 프롬프트로 요약한다."""
    columns = [it for it in chosen if it.get('category') == 'insight']
    news = [it for it in chosen if it.get('category') != 'insight']
    done = summarize(news, bodydir) if news else 0
    if columns:
        done += summarize(columns, bodydir, system=SYSTEM_ANALYSIS)
    return done


def frozen(path):
    """그날 파일에 요약된 기사가 하나라도 있으면 동결한다 — 다시 긁지 않는다.

    재수집은 기사 선정도 요약 문장도 바꾼다(요약 모델은 매번 다른 문장을 낸다). 루틴이 이미
    그 요약으로 글을 쓰는 중이면 발행 직전에 게이트가 어긋난다(2026-09-26 9/25 브리프 유실).
    요약이 하나도 없는 날(자격 증명 실패 등)은 동결하지 않는다 — 다시 받아야 한다.
    """
    try:
        with open(path, encoding='utf-8') as fh:
            items = json.load(fh).get('items') or []
    except (OSError, ValueError):
        return False
    return any(it.get('summary_ko') for it in items)


def carry_summaries(path, chosen):
    """--refresh 로 다시 받을 때, 같은 guid 의 기존 요약을 그대로 옮긴다. 옮긴 건수."""
    try:
        with open(path, encoding='utf-8') as fh:
            old = {it.get('guid'): it for it in json.load(fh).get('items') or []}
    except (OSError, ValueError):
        return 0
    n = 0
    for it in chosen:
        prev = old.get(it.get('guid'))
        if prev and prev.get('summary_ko'):
            for k in ('summary_ko', 'summary_model'):
                if prev.get(k):
                    it[k] = prev[k]
            n += 1
    return n


def save_json(path, payload):
    """원자적 교체 — 'w' 로 직접 덮어쓰다 실패하면 기존 수집분까지 깨진다(2차 #13)."""
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--datadir', default='data')
    ap.add_argument('--bodydir', default='_workspace/news')
    ap.add_argument('--date', default=_date.today().isoformat())
    ap.add_argument('--per-category', type=int, default=3)
    ap.add_argument('--refresh', action='store_true',
                    help='이미 요약된 날도 다시 받는다(같은 기사는 기존 요약을 재사용)')
    args = ap.parse_args()

    path = os.path.join(args.datadir, 'news', f'{args.date}.json')
    if frozen(path) and not args.refresh:
        print(f'{path} — 이미 요약된 날이라 동결한다(다시 받으려면 --refresh)')
        return 0

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

    now = datetime.now(timezone.utc)
    # 피드가 없는 출처(일본은행 정책 발표문·연설 목록, 2026-09-26)
    for category, rows in pages(now.year).items():
        for url, parse in rows:
            time.sleep(GAP)
            try:
                got = parse(get(url, ctx), category)
            except Exception as e:
                why = (f'HTTP {e.code}' if isinstance(e, urllib.error.HTTPError)
                       else f'{type(e).__name__} {str(e)[:120]}')
                notes.append(f'{category} {url}: {why}')
                continue
            harvested.extend(got)
            print(f'  {category}: {len(got)}건 ({url.split("/")[2]} 목록)')
    chosen = select(dedupe(categorize(harvested)), per_category=args.per_category, now=now)
    print(f'수집 {len(harvested)}건 → 중복 제거·선정 {len(chosen)}건(글로벌·칼럼은 후보)')

    fetch_bodies(chosen, args.bodydir, ctx)
    chosen = trim(chosen, now)             # 글로벌·칼럼 확정 — 본문·날짜가 확인된 것만

    os.makedirs(os.path.dirname(path), exist_ok=True)
    carried = carry_summaries(path, chosen)
    if carried:
        print(f'  기존 요약 {carried}건 재사용')
    payload = {'report_date': args.date, 'harvested': len(harvested),
               'notes': notes, 'items': chosen}
    # 요약 **전에** 한 번 저장한다 — 요약(외부 API·인증)이 어떤 식으로 죽어도 메타데이터와
    # MLCC 행은 남아야 한다(2026-09-24 구현 검토 #2).
    save_json(path, payload)
    try:
        summarized = summarize_chosen(chosen, args.bodydir)
    except Exception as e:             # summarize_items 는 삼키게 짰지만, 저장을 걸지 않는다
        summarized = 0
        notes.append(f'요약 단계 실패: {type(e).__name__}')
        print(f'  요약 단계 실패 ({type(e).__name__})', file=sys.stderr)
    save_json(path, payload)
    got = sum(1 for it in chosen if it.get('body_chars'))
    print(f'{path} — 본문 {got}/{len(chosen)}건 · 요약 {summarized}건')


if __name__ == '__main__':
    sys.exit(main() or 0)
