#!/usr/bin/env python3
"""Telegram public channels -> <datadir>/telegram/<date>.json for the daily brief (2026-11-06).

Runs in the collection jobs (US `collect-market-data.yml`, KR `collect-kr-data.yml`), after news.
Non-core: any failure leaves a file that says so, and the brief simply has no Telegram items.

Window per channel = (that channel's cursor in the latest earlier file, now]. A channel that
failed keeps its old cursor; one that hit the page cap advances and records a `hole`.
A file that already has a summary is frozen (same-day re-collection must not change what the
brief used) unless --refresh. Only summaries are committed — post text and article bodies stay
in --bodydir (gitignored /_workspace/). Design: docs/superpowers/specs/2026-11-06-telegram-source.md

  python3 scripts/fetch_telegram.py --market us --datadir data --bodydir _workspace/telegram --date 2026-11-09
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import telegram as tg  # noqa: E402
from common.tg_parse import ParseError, parse_page  # noqa: E402

UA = 'Mozilla/5.0 (compatible; fdo2a-brief/1.0)'
GAP = 1.5
MAX_PAGES = 60
FALLBACK_H = 24
MAX_LOOKBACK_H = 72
PREV_DAYS = 7


def iso(dt):
    return dt.astimezone(timezone.utc).isoformat(timespec='seconds')


def curl_get(url):
    r = subprocess.run(['curl', '-sS', '-m', '25', '-A', UA, '-w', '\n%{http_code}', url], capture_output=True)
    if r.returncode:
        raise IOError(f'curl exit {r.returncode}')
    body, _, code = r.stdout.decode('utf-8', 'replace').rpartition('\n')
    if code != '200':
        raise IOError(f'HTTP {code}')
    return body


def previous_file(outdir, date):
    """Latest file strictly before `date` within PREV_DAYS, or None."""
    best = None
    for p in glob.glob(os.path.join(outdir, '*.json')):
        d = os.path.basename(p)[:-5]
        if d < date and d >= (datetime.fromisoformat(date) - timedelta(days=PREV_DAYS)).date().isoformat():
            best = max(best or d, d)
    if not best:
        return None
    try:
        with open(os.path.join(outdir, best + '.json'), encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def with_run_cursors(prev, datadir, market):
    """직전 파일의 채널 커서를 그날 실행 원본(versions/<market>/<D>/runs/*) 중 가장 앞선 ok 커서로 당긴다.

    발행된 날의 파일은 발행판 그대로 동결되고(2026-11-10), 발행 뒤 재수집의 커서는 실행 원본에만
    남는다 — 그 커서를 버리면 주말을 건너 72시간 상한에 걸릴 수 있다.
    spec: docs/superpowers/specs/2026-11-10-kr-data-versions.md
    """
    d = (prev or {}).get('report_date')
    if not prev or not d:
        return prev
    pat = os.path.join('versions', market, d, 'runs', '*', 'files', os.path.normpath(datadir),
                       'telegram', f'{d}.json')
    out = json.loads(json.dumps(prev))
    for p in sorted(glob.glob(pat)):
        run = load(p) or {}
        for ch, st in (run.get('channels') or {}).items():
            if st.get('status') != 'ok' or st.get('last_id') is None:
                continue
            cur = out.setdefault('channels', {}).get(ch) or {}
            if cur.get('last_id') is None or st['last_id'] > cur['last_id']:
                out['channels'][ch] = {**cur, 'last_id': st['last_id'], 'last_dt': st.get('last_dt'),
                                       'status': 'ok', 'cursor_from': 'run'}
    return out


def load(path):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def frozen(path):
    """Frozen = it has a summary and every channel was read completely. A day with a failed or
    partial channel is collected again (its summaries carried over by id)."""
    d = load(path)
    if not d:
        return False
    complete = all(c.get('status') == 'ok' for c in d.get('channels', {}).values())
    return complete and any(it.get('summary_ko') for it in d.get('items', []))


def read_channel(ch, cursor_id, floor_dt, fetch, sleep, max_pages=MAX_PAGES):
    """Newest -> older until the cursor (exclusive) or, without one, the time floor.
    -> (posts newer than the cursor/floor, status dict)."""
    got, pages, before = [], 0, None
    st = {'status': 'ok', 'pages': 0, 'truncated': False}
    while pages < max_pages:
        if pages:
            sleep(GAP)
        url = f'https://t.me/s/{ch}' + (f'?before={before}' if before else '')
        html = None
        for i in range(3):
            try:
                html = fetch(url)
                break
            except IOError as e:
                st['error'] = str(e)[:80]
                sleep(GAP * 2 ** (i + 1))
        if html is None:
            st['status'] = 'failed'
            break
        try:
            posts, nxt = parse_page(html, ch)
        except ParseError as e:
            st.update(status='failed', error=str(e)[:80])
            break
        pages += 1
        got.extend(posts)
        oldest = min(p['id'] for p in posts)
        reached = (cursor_id is not None and oldest <= cursor_id + 1) or \
                  (cursor_id is None and any(datetime.fromisoformat(p['dt_utc']) < floor_dt for p in posts))
        if reached or nxt is None or (before is not None and nxt >= before):
            break
        before = nxt
    else:
        st['truncated'] = True
    st['pages'] = pages
    if st['status'] == 'failed' and not got:
        return [], st
    keep = [p for p in got if (p['id'] > cursor_id if cursor_id is not None
                               else datetime.fromisoformat(p['dt_utc']) >= floor_dt)]
    uniq = {p['id']: p for p in keep}
    keep = sorted(uniq.values(), key=lambda p: p['id'])
    if st['truncated'] and keep:
        st['hole'] = [cursor_id, keep[0]['id']]
    if st['status'] == 'failed':
        st['status'] = 'partial'          # some pages read before the failure
    return keep, st


def collect(market, prev, now, fetch=curl_get, sleep=time.sleep):
    """-> (candidates [(item, post)], channels status, window_note)."""
    prev_ch = (prev or {}).get('channels', {})
    notes, cands, chans = [], [], {}
    for ch in tg.CHANNELS:
        pc = prev_ch.get(ch, {})
        cursor = pc.get('last_id')
        floor = now - timedelta(hours=FALLBACK_H)
        if cursor is not None and pc.get('last_dt'):
            if now - datetime.fromisoformat(pc['last_dt']) > timedelta(hours=MAX_LOOKBACK_H):
                cursor, floor = None, now - timedelta(hours=MAX_LOOKBACK_H)
                notes.append(f'{ch}: 직전 커서가 {MAX_LOOKBACK_H}시간보다 오래돼 {MAX_LOOKBACK_H}시간만 읽음')
        elif cursor is None:
            notes.append(f'{ch}: 직전 커서 없음 — {FALLBACK_H}시간')
        posts, st = read_channel(ch, cursor, floor, fetch, sleep,
                                 max_pages=tg.CHANNELS[ch].get('max_pages', MAX_PAGES))
        st['from_dt'] = pc.get('last_dt') if cursor is not None else floor.isoformat()
        if st['status'] in ('failed', 'partial'):
            # a page failed somewhere: what lies between is unknown, so do not advance
            st['last_id'], st['last_dt'] = pc.get('last_id'), pc.get('last_dt')
        else:
            newest = posts[-1] if posts else None
            st['last_id'] = newest['id'] if newest else pc.get('last_id')
            st['last_dt'] = newest['dt_utc'] if newest else pc.get('last_dt')
        st['read'] = len(posts)
        chans[ch] = st
        for p in posts:
            item = tg.classify_post(ch, p, market)
            if item:
                cands.append((item, p))
        sleep(GAP)
    return cands, chans, notes


MIN_BODY = 400          # chars; shorter is a teaser, a consent wall or a subscription page
WALL = ('subscribe', 'subscription', 'digital access', 'sign in to', 'cookie', 'personal data', 'consent',
        'manage your choices', 'privacy', 'enable javascript', 'are you a robot', '구독', '로그인 후', '쿠키',
        '개인정보', '자바스크립트')
STALE_DAYS = 2          # an article older than the window start by this much is not news


def get_final(url, ctx):
    """(page, final URL after redirects) with the news collector's UA and TLS context."""
    import urllib.request
    import fetch_news
    req = urllib.request.Request(url, headers={'User-Agent': fetch_news.UA})
    with urllib.request.urlopen(req, timeout=fetch_news.TIMEOUT, context=ctx) as r:
        return r.read().decode('utf-8', 'replace'), r.geturl()


def _host(url):
    from urllib.parse import urlsplit
    h = urlsplit(url or '').netloc.lower().split(':')[0]
    return h[4:] if h.startswith('www.') else h


def fetch_origin(item, ctx, get, extract_body, page_published):
    """(body, outlet, published) for a report item; body None when unusable. `get` returns
    (page, final_url) — a redirect to another host is not that outlet's article."""
    url = item['source']['url']
    page, final = get(url, ctx)
    if _host(final) != _host(url):
        return None, None, None
    body = extract_body(page) or ''
    head = body[:600].lower()
    sentences = len(re.findall(r'[.!?。]|다\.', body))
    if len(body) < MIN_BODY or any(w in head for w in WALL) or sentences < 3:
        body = None
    name = item['source'].get('name') or tg.outlet_for(url, page)
    return body, name, page_published(page)


def stale(item, window_start):
    """window_start = the window actually read for THIS item's channel."""
    d = item.get('article_date')
    if not d:
        return False
    return d < (window_start - timedelta(days=STALE_DAYS)).date().isoformat()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--market', choices=['us', 'kr'], required=True)
    ap.add_argument('--datadir', required=True)
    ap.add_argument('--bodydir', required=True)
    ap.add_argument('--date', required=True, help='report_date of the edition this collection feeds')
    ap.add_argument('--refresh', action='store_true')
    a = ap.parse_args(argv)
    outdir = os.path.join(a.datadir, 'telegram')
    path = os.path.join(outdir, f'{a.date}.json')
    if frozen(path) and not a.refresh:
        print(f'{path} — 이미 요약이 있어 동결(다시 받으려면 --refresh)')
        return 0
    now = datetime.now(timezone.utc)
    prev = with_run_cursors(previous_file(outdir, a.date), a.datadir, a.market)
    cands, chans, notes = collect(a.market, prev, now)
    chosen = tg.select(cands)

    import fetch_news                      # noqa: E402 — same TLS context and article extractor as news
    from us.news import extract_body, page_published   # noqa: E402
    ctx = fetch_news._context()
    os.makedirs(a.bodydir, exist_ok=True)
    items, bodies, dropped = [], {}, 0
    for item, post in chosen:
        f = chans.get(item['channel'], {}).get('from_dt')
        window_start = datetime.fromisoformat(f) if f else now - timedelta(hours=FALLBACK_H)
        if stale(item, window_start):
            dropped += 1
            continue
        if item['kind'] == 'report':
            try:
                body, name, published = fetch_origin(item, ctx, get_final, extract_body, page_published)
            except Exception as e:                    # noqa: BLE001
                body, name, published = None, None, None
                item['summary_note'] = f'원문 실패 {type(e).__name__}'
            if published and published[:10] < (window_start - timedelta(days=STALE_DAYS)).date().isoformat():
                dropped += 1
                continue
            if body and name:
                item['source']['name'] = name
                bodies[item['id']] = body
            else:
                # no readable original (or unknown outlet): fall back to an opinion of the post
                item['kind'] = 'opinion'
                credit = tg.credited_source(post.get('text'))
                item['source'] = {'name': credit, 'url': None, 'basis': 'credit'} if credit else None
                bodies[item['id']] = post.get('text') or ''
        else:
            bodies[item['id']] = post.get('text') or ''
        items.append(item)
    for item in items:                        # bodies stay out of the repo
        with open(os.path.join(a.bodydir, item['id'].replace('/', '_') + '.txt'), 'w', encoding='utf-8') as f:
            f.write(bodies.get(item['id'], ''))

    payload = {'report_date': a.date, 'market': a.market, 'collected_utc': iso(now),
               'window_from': {ch: st.get('last_dt') for ch, st in (prev or {}).get('channels', {}).items()},
               'window_note': notes, 'channels': chans, 'items': items}
    os.makedirs(outdir, exist_ok=True)
    old = {it['id']: it for it in (load(path) or {}).get('items', []) if it.get('summary_ko')}
    for it in items:                          # same post, same summary: re-collection must not churn
        o = old.get(it['id'])
        if o and o.get('kind') == it['kind'] and o.get('source') == it.get('source'):
            it['summary_ko'] = o['summary_ko']
            it.pop('summary_note', None)
    _save(path, payload)                      # metadata first: a summary crash must not lose it
    from common.tg_summary import summarize   # noqa: E402
    done, failed = summarize(items, bodies)
    payload['stats'] = {'items': len(items), 'summarized': done, 'summary_failed': failed,
                        'stale_dropped': dropped,
                        'channels_failed': sorted(c for c, s in chans.items() if s['status'] == 'failed'),
                        'holes': sorted(c for c, s in chans.items() if s.get('hole'))}
    _save(path, payload)
    print(f'{path} — 후보 {len(cands)} → {len(items)}건, 요약 {done} 실패 {failed}, '
          f'실패 채널 {payload["stats"]["channels_failed"] or "없음"}')
    return 1 if payload['stats']['channels_failed'] or (items and not done) else 0


def _save(path, payload):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


if __name__ == '__main__':
    sys.exit(main())
