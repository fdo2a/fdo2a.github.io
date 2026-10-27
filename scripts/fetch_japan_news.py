#!/usr/bin/env python3
"""Yahoo!ファイナンス 뉴스를 받아 japan/data/news/<date>.json 으로 커밋한다.

일본 뉴스 수집 잡(`collect-japan-news.yml`)에서 돈다. US `fetch_news.py`·KR `fetch_kr_news.py` 와 같은
계약이다 — 본문은 `--bodydir`(gitignore)에만 두고, 이 잡 안에서 한국어 요약(`summary_ko`)을 만든 뒤
메타데이터와 요약만 커밋한다. 발행 게이트는 `check_japan.py`(「이번 주 뉴스」 절). 순수 로직은 `japan/news.py`.

**끝난 JST 날짜를 모은다**(codex 2026-10-18 #3). 그날 저녁에 받으면 그 뒤 기사가 빠지고, 동결이
다시 받지 못하게 막는다. 그래서 기본값은 오늘 이전 평일 다섯 날 가운데 아직 동결되지 않은 날 전부다 —
늦게 뜬 실행이나 실패한 날을 다음 실행이 메운다. 목록 페이지는 실행마다 한 번만 넘긴다.

비-코어다. 목록이 죽으면 그 날의 `complete` 가 거짓으로 남아 동결되지 않고, 다음 실행이 다시 받는다.

  python3 scripts/fetch_japan_news.py --datadir japan/data            # 밀린 평일 전부
  python3 scripts/fetch_japan_news.py --datadir japan/data --date 2026-10-16
  python3 scripts/fetch_japan_news.py --datadir japan/data --daily-session 2026-10-27   # 일본 일간

`--daily-session` 은 일본 일간 전용이다(2026-10-27) — 그날 16:30 JST 컷까지의 경제 기사를
`news/daily/<session>.json` 에만 쓴다. 주간의 `news/<date>.json` 은 읽지도 쓰지도 않는다
(동결 계약 유지). 순수 로직은 `japan/news_daily.py`.
"""

import argparse
import json
import os
import sys
import time
import urllib.error
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fetch_news import _context, carry_summaries, frozen, get, get_bytes, save_json  # noqa: E402
from japan import news as N  # noqa: E402
from japan import news_daily as ND  # noqa: E402
from us.news import (_nli_body, parse_boj_speeches, parse_boj_statements,  # noqa: E402
                     parse_feed_strict, pdf_text)
from us.news import extract_body as page_body  # noqa: E402
from us.news_summary import SYSTEM, SYSTEM_ANALYSIS, new_run, summarize_items  # noqa: E402

GAP = 0.5              # 같은 호스트를 붙여 때리지 않는다
BACK_DAYS = 5          # 목록이 닿는 깊이(bus_all 1,000건 ≈ 평일 5일 남짓) 안에서만 메운다


def _why(e):
    return f'HTTP {e.code}' if isinstance(e, urllib.error.HTTPError) else type(e).__name__


def pending_dates(datadir, today, back=BACK_DAYS, refresh=False):
    """오늘 이전 평일 `back` 개 중 다시 받아야 하는 날(오래된 순)."""
    out, d = [], date.fromisoformat(today)
    while len(out) < back:
        d -= timedelta(days=1)
        if d.weekday() < 5:
            out.append(d.isoformat())
    return sorted(day for day in out if refresh or not done(_path(datadir, day)))


def _path(datadir, day):
    return os.path.join(datadir, 'news', f'{day}.json')


def done(path):
    """동결 — 요약이 끝났고 **목록을 끝까지 읽은 날**만. 목록 하나가 죽은 날은 갈래 하나가 빈 채로
    굳지 않게 다시 받는다(codex #3)."""
    if not frozen(path):
        return False
    try:
        with open(path, encoding='utf-8') as fh:
            return bool(json.load(fh).get('complete'))
    except (OSError, ValueError):
        return False


def harvest(oldest, today, ctx, fetch=None, gap=GAP, max_pages=N.MAX_PAGES):
    """(목록 행, 사유, 목록별 도달 범위). 카테고리마다 `oldest` 보다 앞선 날짜에 닿을 때까지 넘긴다.

    도달 범위 `{feed: {ok, oldest, end}}` — 완주는 **날마다** 판정한다(`complete_for`). 밀린 5일을 한 번에
    메우면 일부 목록이 50쪽 안에 가장 오래된 날 앞에 못 닿는데, 그것을 모든 날의 실패로 치면 매 실행이
    5일을 다시 받는다(2026-10-18 첫 실행).
    """
    fetch = fetch or get
    rows, notes, reach = [], [], {}
    for feed in N.FEEDS:
        r = reach[feed] = {'ok': True, 'oldest': None, 'end': False}
        for page in range(1, max_pages + 1):
            if gap:
                time.sleep(gap)
            try:
                got = N.parse_list(fetch(N.LIST_URL.format(feed=feed, page=page), ctx), feed)
            except Exception as e:
                notes.append(f'{feed} {page}쪽: {_why(e)} {str(e)[:160]}')
                r['ok'] = False
                break
            if not got:
                r['end'] = True           # 목록 끝 — 끝까지 읽었다
                break
            rows.extend(got)
            undated = [x for x in got if not N.list_day(x.get('created'), today)]
            if undated:
                # 날짜를 못 읽은 기사는 어느 날에도 들어가지 않는다 — 그런 목록은 다 읽은 것이 아니다(codex)
                notes.append(f'{feed} {page}쪽: 날짜를 못 읽은 기사 {len(undated)}건(「{undated[0].get("created")}」)')
                r['ok'] = False
            days = [d for d in (N.list_day(x.get('created'), today) for x in got) if d]
            if days:
                r['oldest'] = min([r['oldest']] + days if r['oldest'] else days)
            if N.reached(got, oldest, today):
                break
        else:
            notes.append(f'{feed} {max_pages}쪽까지 {oldest} 이전에 닿지 못했다(가장 앞 {r["oldest"]})')
    return rows, notes, reach


def complete_for(day, reach):
    """그날을 다 읽었나 — 모든 목록이 실패 없이 그날보다 앞선 날짜에 닿았거나 끝까지 읽었다.
    덜 받은 날을 동결하지 않는다(codex 구현 #2)."""
    return bool(reach) and all(r['ok'] and (r['end'] or (r['oldest'] or '9999') < day)
                               for r in reach.values())


def harvest_official(ctx, year, fetch=None, month=None):
    """(행, 사유, 완주 여부). 일본은행 정책 발표문(매크로)·연설(리포트·칼럼), 닛세이기초연구소(리포트·칼럼).
    하나라도 못 읽으면 완주가 아니다 — 그날을 동결하지 않고 다음 실행이 다시 받는다(codex 구현 #3)."""
    fetch = fetch or get
    rows, notes = [], []
    for url, parse, cat in ((N.BOJ_STATEMENTS.format(year=year), parse_boj_statements, 'macro'),
                            (N.BOJ_SPEECHES.format(year=year), parse_boj_speeches, 'insight')):
        try:
            rows += N.official(parse(fetch(url, ctx), cat), cat)
        except Exception as e:
            # 새해 첫 회의 전(1월)에는 그해 목록 페이지가 없다(404) — 그때만 실패가 아니라 아직 없는 것이다.
            # 다른 달의 404 는 주소가 바뀐 것이니 실패로 둔다(codex 재검토 #3).
            if isinstance(e, urllib.error.HTTPError) and e.code == 404 and month == 1:
                continue
            notes.append(f'일본은행 {url}: {_why(e)} {str(e)[:120]}')
    try:
        got, why = parse_feed_strict(fetch(N.NLI_FEED, ctx), 'insight')
        if why:
            notes.append(f'닛세이 {why}')
        # 생활 리포트가 섞인다 — 경제 어휘가 제목에 있어야 싣는다(US `_NEEDS_POLICY` 와 같다)
        rows += N.official([r for r in got if N.policy_score(r.get('title'))], 'insight')
    except Exception as e:
        notes.append(f'닛세이 {N.NLI_FEED}: {_why(e)}')
    for r in rows:
        if r.get('published'):
            try:
                r['published'] = datetime.fromisoformat(r['published']).astimezone(N.JST).isoformat()
            except ValueError:
                r['published'] = None
    return rows, notes, not notes


def fetch_bodies(chosen, bodydir, ctx, fetch=None, fetch_bytes=None, gap=GAP):
    """후보 본문을 bodydir 에 떨어뜨린다. 실패는 건별로 적고 넘어간다."""
    fetch, fetch_bytes = fetch or get, fetch_bytes or get_bytes
    os.makedirs(bodydir, exist_ok=True)
    for i, it in enumerate(chosen, 1):
        url = it['url']
        try:
            if url.lower().endswith('.pdf'):
                page, body = '', pdf_text(fetch_bytes(url, ctx))
            elif 'nli-research.co.jp' in url or 'boj.or.jp' in url:
                page = fetch(url, ctx)
                # 닛세이는 「■要旨」 이 없으면 본문이 아니다 — 페이지 문단으로 대체하지 않는다(codex #10)
                body = _nli_body(page) if 'nli-research' in url else page_body(page)
            else:
                page = fetch(url, ctx)
                body = N.extract_body(page)
                it['published'] = N.page_published(page) or it.get('published')
        except Exception as e:
            it['body_chars'], it['body_note'] = 0, _why(e)
            print(f'  [{i}] 본문 실패({_why(e)}) {url}', file=sys.stderr)
            continue
        finally:
            if gap:
                time.sleep(gap)
        if not body:
            it['body_chars'] = 0
            it['body_note'] = N.body_note(page) if 'finance.yahoo' in url else '짧다·표식 없음'
            print(f'  [{i}] 본문 아님({it["body_note"]}) {url}', file=sys.stderr)
            continue
        name = f'{i:02d}-{it["category"]}.txt'
        try:
            with open(os.path.join(bodydir, name), 'w', encoding='utf-8') as fh:
                fh.write(f'# {it.get("title")}\n# {it.get("source")} · {it.get("published")}\n'
                         f'# {url}\n\n{body}\n')
        except OSError as e:
            it['body_chars'], it['body_note'] = 0, f'저장 실패 {type(e).__name__}'
            continue
        it['body_chars'], it['body_file'] = len(body), name
        print(f'  [{i}] {it["category"]:8s} 본문 {len(body):5d}자  {(it.get("title") or "")[:40]}')
    return chosen


def summarize_chosen(chosen, bodydir, summarize=summarize_items):
    """뉴스는 기사 프롬프트로, 리포트·칼럼은 견해를 필자에게 귀속하는 프롬프트로."""
    columns = [it for it in chosen if it.get('category') == 'insight']
    news = [it for it in chosen if it.get('category') != 'insight']
    n = summarize(news, bodydir, system=SYSTEM) if news else 0
    if columns:
        n += summarize(columns, bodydir, system=SYSTEM_ANALYSIS)
    return n


_KEEP = ('guid', 'url', 'title', 'source', 'published', 'category', 'feed', 'official', 'kind',
         'body_chars', 'body_file', 'body_note')


def collect_day(day, rows, official_rows, today, bodydir, ctx, complete, notes, fetch=None,
                summarize=summarize_items, datadir='japan/data'):
    """하루치를 고르고, 본문을 받고, 요약해 저장한다. 저장한 payload."""
    todays = [r for r in rows if N.list_day(r.get('created'), today) == day]
    kept, dropped = N.screen(N.dedupe(todays))
    offs = [r for r in official_rows if (r.get('published') or '')[:10] == day]
    candidates = N.preselect(offs + kept)
    print(f'{day}: 목록 {len(todays)}건 → 선별 {len(kept)}건 · 공식 {len(offs)}건 → 후보 {len(candidates)}건')
    sub = os.path.join(bodydir, day)
    fetch_bodies(candidates, sub, ctx, fetch=fetch)
    chosen = [{k: it[k] for k in _KEEP if k in it} for it in N.finalize(candidates, day)]
    path = _path(datadir, day)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    carried = carry_summaries(path, chosen)
    if carried:
        print(f'  기존 요약 {carried}건 재사용')
    payload = {'report_date': day, 'source': 'Yahoo!ファイナンス ニュース', 'complete': complete,
               'harvested': len(todays), 'dropped': dropped, 'notes': list(notes), 'items': chosen}
    save_json(path, payload)          # 요약이 어떻게 죽어도 수집분은 남는다
    try:
        n = summarize_chosen(chosen, sub, summarize=summarize)
    except Exception as e:
        n = 0
        payload['notes'].append(f'요약 단계 실패: {type(e).__name__}')
    save_json(path, payload)
    print(f'{path} — 확정 {len(chosen)}건 · 요약 {n}건')
    return payload


def _daily_path(datadir, session):
    return os.path.join(datadir, 'news', 'daily', f'{session}.json')


def save_daily(datadir, session, chosen, complete, notes, region_filter=None):
    path = _daily_path(datadir, session)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = {'report_date': session, 'cut': ND.CUT, 'source': 'Yahoo!ファイナンス ニュース',
               'complete': complete, 'notes': list(notes), 'items': chosen}
    if region_filter is not None:     # 국내/해외 필터의 감사 기록 — 게이트·검토는 `items` 만 읽는다
        payload['region_filter'] = region_filter
    save_json(path, payload)
    return payload


def capture_shadow(datadir, session, cut_rows, chosen, complete=None):
    """국내/해외 판정 섀도의 입력(`japan/region_shadow.py`). 판정은 여기서 하지 않는다 — 네트워크 없이 파일 하나.
    import 까지 이 안에 둔다: 섀도가 어떻게 깨져도 일간 뉴스는 그대로 나와야 한다(codex 설계 검토 #13)."""
    from japan import region_shadow as RS
    path = os.path.join(datadir, 'news', 'region_shadow', 'input', f'{session}.json')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    save_json(path, RS.build_input(session, cut_rows, [c.get('guid') for c in chosen],
                                   commit=os.environ.get('GITHUB_SHA'),
                                   captured_at=datetime.now(N.JST).isoformat(timespec='seconds'),
                                   collection_complete=complete))


def apply_region_filter(kept, post=None):
    """Jev 국내/해외 필터(`japan/region_filter.py`). 필터 코드가 어떻게 깨져도 정규식 결과로 되돌린다(codex 설계 검토 #2)."""
    try:
        from japan import region_filter as RF
        return RF.run(kept, os.environ, post=post)
    except Exception as e:
        return kept, {'mode': 'regex', 'stopped': f'crash:{type(e).__name__}'}


def collect_daily(session, today, bodydir, ctx, datadir='japan/data', fetch=None,
                  summarize=summarize_items, region_post=None):
    """일간 한 세션. 컷은 목록 단계(상한 전)와 기사면 시각(확정) 두 번 건다.

    **발행된 세션은 다시 받지 않는다**(codex 구현 검토 #2) — 늦은 실행이 발행 근거를 덮으면 검토 러너가
    다른 뉴스로 재검사한다. 발행 스냅샷 `<datadir>/daily/<session>.json` 이 있으면 손대지 않는다.
    """
    if os.path.exists(os.path.join(datadir, 'daily', f'{session}.json')):
        print(f'{session} 은 이미 발행됐다 — 일간 뉴스 근거를 덮지 않는다')
        return {'skipped': True, 'items': [], 'complete': True}
    rows, notes, reach = harvest(session, today, ctx, fetch=fetch)
    official_rows, off_notes, off_ok = harvest_official(ctx, int(session[:4]), fetch=fetch,
                                                        month=int(session[5:7]))
    # 목록 행은 갈래가 없다 — 컷(시각만 본다) → 분류(screen) → 일간 갈래(retag) 순서여야 한다
    todays = ND.cut_filter(rows, session, today)
    kept = ND.retag(N.screen(N.dedupe(todays))[0])
    # 정규식이 남긴 후보에서 Jev 가 conf ≥ 0.9 로 해외라고 한 것만 뺀다 — 갈래 상한(preselect) 전에
    kept, region = apply_region_filter(kept, post=region_post)
    print(f"{session} 지역 필터: {region.get('mode')} · 판정 {region.get('answered', 0)}/{region.get('asked', 0)}"
          f" · 뺌 {len(region.get('dropped') or [])} · 끝 {region.get('stopped')}")
    offs = ND.cut_filter(ND.retag(official_rows), session, today)
    candidates = N.preselect(offs + kept)
    print(f'{session} 일간: 컷 안 목록 {len(todays)}건 → 선별 {len(kept)}건 · 공식 {len(offs)}건 → 후보 {len(candidates)}건')
    sub = os.path.join(bodydir, 'daily', session)
    fetch_bodies(candidates, sub, ctx, fetch=fetch)
    chosen = [{k: it[k] for k in _KEEP if k in it} for it in ND.finalize_daily(candidates, session)]
    carry_summaries(_daily_path(datadir, session), chosen)
    complete = bool(rows) and off_ok and complete_for(session, reach)
    payload = save_daily(datadir, session, chosen, complete, notes + off_notes, region)
    # 섀도 입력은 일간 저장 **뒤에** — 일간 저장이 죽었는데 새 캡처만 남아 옛 근거와 엮이지 않게(codex 구현 검토 #5)
    try:
        capture_shadow(datadir, session, todays, chosen, complete)
    except Exception as e:                 # 섀도 실패는 일간 뉴스·notes 에 남기지 않는다
        print(f'  섀도 입력 실패(무시): {type(e).__name__}', file=sys.stderr)
    try:
        summarize_chosen(chosen, sub, summarize=summarize)
    except Exception as e:
        payload['notes'].append(f'요약 단계 실패: {type(e).__name__}')
    return save_daily(datadir, session, chosen, complete, payload['notes'], region)


def main(argv=None):
    new_run()                     # 승격 예산은 이 실행 몫부터 센다
    ap = argparse.ArgumentParser()
    ap.add_argument('--datadir', default='japan/data')
    ap.add_argument('--bodydir', default='_workspace/japan_news')
    ap.add_argument('--date', default=None, help='이 날 하나만(JST). 없으면 밀린 평일 전부')
    ap.add_argument('--today', default=datetime.now(N.JST).date().isoformat())
    ap.add_argument('--refresh', action='store_true', help='동결된 날도 다시(같은 기사는 기존 요약 재사용)')
    ap.add_argument('--daily-session', default=None, help='일본 일간 — 이 세션의 16:30 JST 컷 파일만')
    args = ap.parse_args(argv)

    if args.daily_session:
        payload = collect_daily(args.daily_session, args.today, args.bodydir, _context(),
                                datadir=args.datadir)
        return 0 if payload['items'] or payload['complete'] else 1

    if args.date and args.date >= args.today:
        # 끝나지 않은 날을 받으면 그 뒤 기사가 빠진 채 동결된다(codex 구현 #4)
        print(f'{args.date} 는 JST 오늘({args.today}) 이전이 아니다 — 끝난 날만 받는다', file=sys.stderr)
        return 2
    if args.date:
        days = [args.date] if args.refresh or not done(_path(args.datadir, args.date)) else []
    else:
        days = pending_dates(args.datadir, args.today, refresh=args.refresh)
    if not days:
        print('받을 날이 없다 — 최근 평일이 모두 동결됐다')
        return 0
    print(f'받을 날: {", ".join(days)}')
    ctx = _context()
    rows, notes, reach = harvest(days[0], args.today, ctx)
    year = int(args.today[:4])
    month = int(args.today[5:7])
    official_rows, off_notes, off_ok = harvest_official(ctx, year, month=month)
    if days[0][:4] != args.today[:4]:          # 1월 초에 지난해 12월분을 메울 때
        more, more_notes, more_ok = harvest_official(ctx, int(days[0][:4]), month=12)
        official_rows, off_notes = official_rows + more, off_notes + more_notes
        off_ok = off_ok and more_ok
    print(f'목록 {len(rows)}건 · 공식 {len(official_rows)}건')
    for n in notes + off_notes:
        print(f'  {n}', file=sys.stderr)
    for day in days:
        collect_day(day, rows, official_rows, args.today, args.bodydir, ctx,
                    off_ok and complete_for(day, reach), notes + off_notes, datadir=args.datadir)
    return 0 if rows else 1


if __name__ == '__main__':
    sys.exit(main())
