#!/usr/bin/env python3
"""One Telegram channel -> japan/data/telegram/<session>.json for the Japan daily close brief (2026-11-15).

Runs in `collect-japan-daily.yml` after 「Collect」, non-blocking. Separate from the US/KR path
(`fetch_telegram.py`): no cursor and nothing carried between sessions. The posts of session S are
those stamped in (16:30 JST of --prev, 16:30 JST of S] — rules in `common/tg_jp.py`.

The file is written once, at the end. `usable: true` only when the run started at or after the
cut, the channel was read all the way down to the floor, and the summariser was not stopped; a
file without it counts as absent everywhere (this collector's refusal, `build_japan_daily.py diag`,
the gate). A usable file is never rewritten, and a published session is never collected again —
what was not summarised by publication is dropped. Only summaries are committed; post text and
article bodies stay in --bodydir (gitignored /_workspace/).

  python3 scripts/fetch_telegram_jp.py --session 2026-11-13 --prev 2026-11-12 \
      --datadir japan/data --bodydir _workspace/telegram_jp
Design: docs/superpowers/specs/2026-11-15-telegram-japan-daily.md
"""
import argparse
import os
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fetch_telegram as ft  # noqa: E402
from common import tg_jp  # noqa: E402
from common.tg_links import pool_key  # noqa: E402
from common.tg_use import skip_reason  # noqa: E402

STOPPED = ('요약 클라이언트 없음', '인증 실패')       # tg_summary: the summariser never ran / was cut off


def _origin():
    """item -> (body, outlet, published) with the news collector's TLS context and extractor."""
    import fetch_news
    from us.news import extract_body, page_published
    ctx = fetch_news._context()
    return lambda item: ft.fetch_origin(item, ctx, ft.get_final, extract_body, page_published)


def build_items(cands, floor, origin):
    """[(item, post)] -> (items, bodies, how many stale articles were dropped). A report whose
    original cannot be read becomes an opinion of the post, crediting what the post credits."""
    items, bodies, dropped = [], {}, 0
    old = (floor - timedelta(days=ft.STALE_DAYS)).date().isoformat()
    for item, post in cands:
        text = post.get('text') or ''
        if (item.get('article_date') or old) < old:
            dropped += 1
            continue
        if item['kind'] == 'report':
            try:
                body, name, published = origin(item)
            except Exception as e:                    # noqa: BLE001
                body, name, published = None, None, None
                item['summary_note'] = f'원문 실패 {type(e).__name__}'
            if published and published[:10] < old:
                dropped += 1
                continue
            if body and name:
                item['source']['name'] = name
                bodies[item['id']] = body
            else:
                item['kind'] = 'opinion'
                item['source'] = tg_jp.credit_source(text, tg_jp.title_prefix(text)[1])
                bodies[item['id']] = text
        else:
            bodies[item['id']] = text
        items.append(item)
    return items, bodies, dropped


def run(session, prev, datadir, bodydir, now=None, read=ft.read_channel, fetch=ft.curl_get, sleep=time.sleep,
        summarize=None, origin=None, log=print):
    outdir = os.path.join(datadir, 'telegram')
    path = os.path.join(outdir, f'{session}.json')
    if os.path.exists(os.path.join(datadir, 'daily', f'{session}.json')):
        log(f'{session} 은 이미 발행됐다 — 텔레그램 파일을 만들지 않는다')
        return 0
    old = ft.load(path) or {}
    if old.get('usable') is True and old.get('report_date') == session:
        log(f'{path} — 이미 쓸 수 있는 파일이다(다시 쓰지 않는다)')
        return 0
    now = now or datetime.now(timezone.utc)
    floor, ceiling = tg_jp.window(session, prev)
    posts, st = read(tg_jp.JP_CHANNEL, None, floor - timedelta(hours=tg_jp.READ_MARGIN_H), fetch, sleep,
                     max_pages=tg_jp.MAX_PAGES, track_reached=True)
    cands, stats = tg_jp.candidates(posts, session, floor, ceiling)
    cands, stats['valve_dropped'] = tg_jp.valve(cands)
    items, bodies, stats['stale_dropped'] = build_items(cands, floor, origin or _origin())
    os.makedirs(bodydir, exist_ok=True)
    for it in items:                          # bodies stay out of the repo
        with open(os.path.join(bodydir, it['id'].replace('/', '_') + '.txt'), 'w', encoding='utf-8') as f:
            f.write(bodies.get(it['id'], ''))
    if old.get('report_date') == session:     # this session's earlier, non-usable file only
        ft.carry_summaries(items, {it['id']: it for it in old.get('items') or [] if it.get('summary_ko')})
    if summarize is None:
        from common.tg_summary import summarize
    summarize(items, bodies)
    stopped = any((it.get('summary_note') or '').startswith(STOPPED) for it in items if not it.get('summary_ko'))
    news = ft.load(os.path.join(datadir, 'news', 'daily', f'{session}.json')) or {}
    news_keys = {k for k in (pool_key(n) for n in news.get('items') or []) if k}
    for it in items:
        why = skip_reason(it, (), news_keys)
        it['news_use'] = why is None
        it.pop('news_skip', None)
        if why:
            it['news_skip'] = why
    stats.update(items=len(items), summarized=sum(1 for it in items if it.get('summary_ko')),
                 news_use=sum(1 for it in items if it['news_use']))
    why_not = [w for w, bad in (('컷 전에 시작한 실행', now < ceiling),
                                (f'채널 읽기 {st.get("status")}', st.get('status') != 'ok'),
                                ('바닥까지 읽지 못함', st.get('reached') is not True),
                                ('요약기 중단', stopped)) if bad]
    payload = {'report_date': session, 'market': 'jp', 'collected_utc': ft.iso(now),
               'window': {'floor': floor.isoformat(), 'ceiling': ceiling.isoformat()},
               'channels': {tg_jp.JP_CHANNEL: st}, 'items': items, 'stats': stats, 'usable': not why_not}
    if why_not:
        payload['unusable_why'] = why_not
    os.makedirs(outdir, exist_ok=True)
    ft._save(path, payload)                   # the only save: a killed run leaves what was there
    log(f'{path} — 읽은 글 {stats["read"]} → 후보 {len(items)}건(쓸 수 있는 {stats["news_use"]}), '
        + ('usable' if not why_not else '쓸 수 없음: ' + ' · '.join(why_not)))
    return 1 if why_not else 0


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--session', required=True, help='Tokyo session YYYY-MM-DD')
    ap.add_argument('--prev', required=True, help='the previous Tokyo session (routine_due.py jp-session)')
    ap.add_argument('--datadir', required=True)
    ap.add_argument('--bodydir', required=True)
    a = ap.parse_args(argv)
    return run(a.session, a.prev, a.datadir, a.bodydir)


if __name__ == '__main__':
    sys.exit(main())
