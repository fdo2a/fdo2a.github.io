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
from us.news_summary import SYSTEM, SYSTEM_ANALYSIS, new_run, summarize_items, usable_summary  # noqa: E402

GAP = 0.5              # 같은 호스트를 붙여 때리지 않는다
BACK_DAYS = 5          # 목록이 닿는 깊이(bus_all 1,000건 ≈ 평일 5일 남짓) 안에서만 메운다
MAX_ATTEMPTS = 4       # 목록·공식 출처·본문 실패가 이어져도 네 번(아침 두 번 × 이틀) 뒤에는 목록을 다시 넘기지 않는다


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


def _read(path):
    try:
        with open(path, encoding='utf-8') as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def _unsummarised(items):
    """본문을 받았는데 실을 수 있는 요약이 없는 기사 — 이것이 남으면 그날은 끝나지 않는다."""
    return [it for it in items or [] if it.get('body_chars') and not usable_summary(it.get('summary_ko'))]


def lists_ready(d):
    """목록을 다시 넘길 필요가 없나 — 다 읽었거나(`complete`), 더 읽어도 못 닿는다고 정해졌다(`lists_settled`)."""
    return bool(d) and bool(d.get('complete') or d.get('lists_settled'))


def done(path):
    """동결 — 다시 받지 않는다.

    2026-11-19 부터: 요약이 다 됐고(본문 있는 기사마다 실을 수 있는 요약) **목록이 정해졌고**(다 읽었거나
    50쪽 상한에 막혀 더 못 간다), 공식 출처를 읽었고, 본문 일시 실패(`retry`)가 남지 않은 날. 공식 출처·본문 실패는
    `MAX_ATTEMPTS` 번 뒤에는 기다리지 않는다. 빈 날(휴일·목록이 끝내 안 열린 날)도 정해지면 끝난다.
    이 칸들이 없는 옛 파일은 옛 규칙(`frozen` + `complete`) 그대로다.
    """
    d = _read(path)
    if d is None:
        return False
    if 'lists_settled' not in d:
        return frozen(path) and bool(d.get('complete'))
    if _unsummarised(d.get('items')):
        return False
    late = (d.get('attempts') or 0) >= MAX_ATTEMPTS
    return (lists_ready(d) and (bool(d.get('official_ok')) or late)
            and (not d.get('retry') or late))


def harvest(oldest, today, ctx, fetch=None, gap=GAP, max_pages=N.MAX_PAGES):
    """(목록 행, 사유, 목록별 도달 범위). 카테고리마다 `oldest` 보다 앞선 날짜에 닿을 때까지 넘긴다.

    도달 범위 `{feed: {ok, oldest, end}}` — 완주는 **날마다** 판정한다(`complete_for`). 밀린 5일을 한 번에
    메우면 일부 목록이 50쪽 안에 가장 오래된 날 앞에 못 닿는데, 그것을 모든 날의 실패로 치면 매 실행이
    5일을 다시 받는다(2026-10-18 첫 실행).
    """
    fetch = fetch or get
    rows, notes, reach = [], [], {}
    for feed in N.FEEDS:
        r = reach[feed] = {'ok': True, 'oldest': None, 'end': False, 'capped': False}
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
            r['capped'] = True            # 실패 없이 쪽 상한까지 — 목록 창은 앞으로만 밀리니 다음 실행도 더 못 간다
            notes.append(f'{feed} {max_pages}쪽까지 {oldest} 이전에 닿지 못했다(가장 앞 {r["oldest"]})')
    return rows, notes, reach


def complete_for(day, reach):
    """그날을 다 읽었나 — 모든 목록이 실패 없이 그날보다 앞선 날짜에 닿았거나 끝까지 읽었다.
    덜 받은 날을 동결하지 않는다(codex 구현 #2)."""
    return bool(reach) and all(r['ok'] and (r['end'] or (r['oldest'] or '9999') < day)
                               for r in reach.values())


def settled_for(day, reach):
    """그날 목록을 다시 넘겨도 더 얻을 게 없나 — 모든 목록이 실패 없이 그날을 덮었거나 쪽 상한에 닿았다.

    목록은 최신순 1,000건 창이고 창은 앞으로만 밀린다. 실패 없이 50쪽을 다 넘기고도 그날 앞에 못 닿았다면
    다음 실행은 더 못 닿는다(2026-11-19 — 재실행마다 그날 행이 줄기만 했다). 다시 시도할 가치는 일시 실패
    (`ok` 거짓: 쪽 실패·날짜 못 읽음)에만 있다. `complete` 는 정직하게 거짓으로 남는다.
    """
    return bool(reach) and all(r['ok'] and (r['end'] or r.get('capped') or (r['oldest'] or '9999') < day)
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


def fetch_bodies(chosen, bodydir, ctx, fetch=None, fetch_bytes=None, gap=GAP, avoid=None):
    """후보 본문을 bodydir 에 떨어뜨린다. 실패는 건별로 적고 넘어간다.

    `avoid` = 이미 쓰인 파일 이름 집합(주간 재수집 — 보관 기사의 옛 이름·앞 단계 이름). 주면 겹치지 않게 짓고 더한다."""
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
            it['_failed'] = True              # 일시 실패 — 주간 수집은 다음 실행에 다시 받는다(`_KEEP` 밖)
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
        if avoid is not None:
            k = 1
            while name in avoid:
                name, k = f'{i:02d}-{k}-{it["category"]}.txt', k + 1
            avoid.add(name)
        try:
            with open(os.path.join(bodydir, name), 'w', encoding='utf-8') as fh:
                fh.write(f'# {it.get("title")}\n# {it.get("source")} · {it.get("published")}\n'
                         f'# {url}\n\n{body}\n')
        except OSError as e:
            it['body_chars'], it['body_note'] = 0, f'저장 실패 {type(e).__name__}'
            it['_failed'] = True              # 저장 실패도 일시 실패다 — 기사 탓이 아니니 다음 실행이 다시 받는다
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
_RETRY_KEEP = ('guid', 'url', 'title', 'source', 'published', 'category', 'feed', 'official', 'kind')


def _invalid(it, day):
    """보관 기사를 지금 규칙으로 다시 본다(네트워크 없이). 뺄 이유 또는 None.
    이번 실행 목록에 없다는 것은 이유가 아니다 — 목록은 날마다 앞으로 밀린다(2026-11-19)."""
    if (it.get('published') or '')[:10] != day:
        return '날짜'
    if it.get('official'):
        return None
    if it.get('source') not in N.MEDIA_RANK:
        return '매체'
    if not N.classify(it.get('title'), it.get('feed')):
        return '갈래'
    return None


def _retry_row(it):
    return {k: it[k] for k in _RETRY_KEEP if k in it}


def _requeue(rows, day):
    """`retry` 행을 지금 선별 규칙으로 다시 건다(네트워크 없이). (통과한 행, 뺀 사유 줄).

    줄에 섰을 뿐 아직 고른 기사가 아니다 — 새 후보와 똑같이 `screen` 을 거쳐 매체·갈래를 지금 규칙으로 다시 받는다
    (갈래를 바꾸지 않는 것은 자리를 잡은 보관 기사뿐이다). 목록 행은 기사면을 읽기 전이라 발행 시각이 없다 —
    날짜는 본문을 받은 뒤 `finalize` 가 본다. 공식 출처 행은 `screen` 밖이라 새 공식 행처럼 날짜만 본다."""
    out, notes = [], []
    for r in rows:
        if r.get('official'):
            why = None if (r.get('published') or '')[:10] == day else '날짜'
            row = dict(r)
        else:
            kept, dropped = N.screen([r])
            why = None if kept else next(iter(dropped), '선별')
            row = kept[0] if kept else None
        if why:
            notes.append(f'다시 받을 후보 뺌({why}): {(r.get("title") or "")[:40]}')
        else:
            out.append(row)
    return out, notes


def _bare(it):
    """다시 받을 보관 기사 — 요약·본문 표식을 지운다(요약기는 `summary_ko` 가 있으면 건너뛰고,
    옛 `body_file` 이름은 이번 실행의 다른 기사 파일과 겹칠 수 있다)."""
    return {k: v for k, v in it.items()
            if k not in ('summary_ko', 'summary_model', 'summary_note', 'body_file', 'body_chars', 'body_note',
                         '_failed')}


def collect_day(day, rows, official_rows, today, bodydir, ctx, complete, notes, fetch=None,
                summarize=summarize_items, datadir='japan/data', reach=None, off_ok=None, lists_read=True):
    """하루치를 고르고, 본문을 받고, 요약해 저장한다. 저장한 payload.

    **그날 파일과 합친다**(2026-11-19). 재실행은 목록이 앞으로 밀려 그날 행이 줄어든 채 돈다 — 덮어쓰면 이미
    고르고 요약한 기사가 사라졌다(10/12-11/11 사이 105건). 실을 수 있는 요약이 있는 보관 기사는 그대로 두고
    자기 갈래 자리를 지키며, 지금 규칙에 어긋날 때만 뺀다(`_invalid`). 요약이 없는 보관 기사·본문 일시 실패
    후보(`retry`)는 주소로 다시 받는다. 새 후보는 빈 자리만 채운다.

    `complete` = 이번 실행이 그날을 다 읽었나(`reach` 를 주면 거기서 다시 센다). `lists_read=False` 는
    목록을 넘기지 않은 실행(요약·공식 출처·본문만 다시) — 목록 통계를 건드리지 않는다.
    """
    path = _path(datadir, day)
    old = _read(path) or {}
    off_ok = complete if off_ok is None else off_ok
    run_notes = []
    keep, again = [], []
    for it in old.get('items') or []:
        why = _invalid(it, day)
        if why:
            run_notes.append(f'보관 기사 뺌({why}): {(it.get("title") or "")[:40]}')
        elif usable_summary(it.get('summary_ko')):
            keep.append(it)
        else:
            again.append(dict(_bare(it), _old=it))
    stored = {it.get('guid') for it in old.get('items') or []}
    old_retry = [r for r in old.get('retry') or [] if r.get('guid') not in stored]
    stored |= {r.get('guid') for r in old_retry}          # 규칙에 걸려 빠질 행도 — 이번 목록에서 새 후보로 되살리지 않는다
    old_retry, requeue_notes = _requeue(old_retry, day)
    run_notes += requeue_notes

    todays = [r for r in rows if N.list_day(r.get('created'), today) == day]
    kept, dropped = N.screen(N.dedupe(todays))
    offs = [r for r in official_rows if (r.get('published') or '')[:10] == day]
    fresh = N.preselect([r for r in offs + kept if r.get('guid') not in stored])
    sub = os.path.join(bodydir, day)
    names = {it.get('body_file') for it in keep if it.get('body_file')}
    fetch_bodies(again, sub, ctx, fetch=fetch, avoid=names)      # 1단계: 요약이 없는 보관 기사

    held_again = []
    for it in again:
        prev = it.pop('_old')
        if it.get('body_chars') and (it.get('published') or '')[:10] != day:
            run_notes.append(f'보관 기사 뺌(기사면 날짜 {(it.get("published") or "")[:10]}): '
                             f'{(it.get("title") or "")[:40]}')
        elif it.get('body_chars'):
            held_again.append({k: it[k] for k in _KEEP if k in it})
        else:
            # 못 받았다(일시 실패·빈 쪽·저장 실패) — 본문이 없다는 것은 뺄 이유가 아니다. 그대로 두고 다음 실행이
            # 다시 받는다. `body_chars` 가 남아 그날은 열린 채이고, 옛 `body_file` 은 지운다(이름 겹침).
            back = _bare(prev)
            back['body_chars'] = prev.get('body_chars') or 1
            back['body_note'] = it.get('body_note')
            held_again.append(back)

    held = {}
    for it in keep + held_again:
        held[it.get('category')] = held.get(it.get('category'), 0) + 1
    # 2단계: 빈 자리가 남은 갈래만 새 후보 본문을 받는다
    newcands = [r for r in [dict(x) for x in old_retry] + fresh
                if held.get(r.get('category'), 0) < N.PER_CATEGORY]
    print(f'{day}: 목록 {len(todays)}건 → 선별 {len(kept)}건 · 공식 {len(offs)}건 → '
          f'보관 {len(keep)}건 · 다시 {len(again) + len(old_retry)}건 · 새 후보 {len(newcands) - len(old_retry)}건')
    fetch_bodies(newcands, sub, ctx, fetch=fetch, avoid=names)

    picked = N.finalize(newcands, day, keep=keep + held_again)
    mine = {id(it) for it in keep + held_again}          # 보관분은 그대로(요약 칸까지), 새 기사만 `_KEEP` 로 줄인다
    chosen = [it if id(it) in mine else {k: it[k] for k in _KEEP if k in it} for it in picked]
    taken = {it.get('guid') for it in chosen}
    counts = {}
    for it in chosen:
        counts[it.get('category')] = counts.get(it.get('category'), 0) + 1
    retry = [_retry_row(r) for r in newcands if r.get('_failed') and r.get('guid') not in taken
             and counts.get(r.get('category'), 0) < N.PER_CATEGORY]

    attempts = (old.get('attempts') or 0) + 1
    # `reach` 가 있으면 그것만 본다 — 실패 없이 빈 목록도 읽은 것이다. 없으면(옛 호출) `complete` 와 행 유무
    if reach is not None:
        covered_now = lists_read and complete_for(day, reach)
        settled_now = lists_read and settled_for(day, reach)
    else:
        covered_now = settled_now = lists_read and bool(rows) and bool(complete)
    legacy = bool(old.get('complete'))
    lists_covered = bool(old.get('lists_covered', legacy)) or covered_now
    official_ok = bool(old.get('official_ok', legacy)) or bool(off_ok)
    lists_settled = (bool(old.get('lists_settled')) or lists_covered or settled_now
                     or (lists_read and attempts >= MAX_ATTEMPTS))
    if lists_covered:
        why = None
    elif old.get('lists_settled'):
        why = old.get('settled_why')
    elif settled_now:
        capped = sorted(f for f, r in (reach or {}).items()
                        if r.get('capped') and not r['end'] and (r['oldest'] or '9999') >= day)
        why = (f'{"·".join(capped)} 목록이 {N.MAX_PAGES}쪽 상한에서 그날 앞에 못 닿았다 — '
               '목록 창은 앞으로만 밀려 다시 읽어도 더 못 간다')
    elif lists_settled:
        why = f'{attempts}회 시도에도 목록을 다 읽지 못했다(실패가 이어졌다) — 더 넘기지 않는다'
    else:
        why = None

    if lists_read and rows and len(todays) >= (old.get('harvested') or 0):
        harvested, drops = len(todays), dropped
    else:                                   # 더 좁게 읽었거나 목록을 넘기지 않았다 — 넓게 읽은 통계를 지킨다
        harvested, drops = old.get('harvested', len(todays)), old.get('dropped', dropped)
    if lists_read:
        all_notes = list(notes) + run_notes
    else:
        all_notes = list(old.get('notes') or []) + [n for n in notes if n not in (old.get('notes') or [])] + run_notes
    payload = {'report_date': day, 'source': 'Yahoo!ファイナンス ニュース',
               'complete': bool(legacy or (lists_covered and official_ok)),
               'harvested': harvested, 'dropped': drops, 'notes': all_notes, 'items': chosen,
               'lists_covered': lists_covered, 'lists_settled': lists_settled, 'official_ok': official_ok,
               'attempts': attempts, 'settled_why': why, 'retry': retry}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    save_json(path, payload)          # 요약이 어떻게 죽어도 수집분은 남는다
    try:
        n = summarize_chosen(chosen, sub, summarize=summarize)
    except Exception as e:
        n = 0
        payload['notes'].append(f'요약 단계 실패: {type(e).__name__}')
    save_json(path, payload)
    print(f'{path} — 확정 {len(chosen)}건(보관 {len(keep)}) · 요약 {n}건 · 다시 받을 후보 {len(retry)}건'
          + (f' · 정함: {why}' if why else ''))
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


def _saved_guids(path):
    try:
        from common.region_filter import guids_in
        return guids_in(path)
    except Exception:
        return set()


def apply_region_filter(kept, post=None, exempt=()):
    """Jev 국내/해외 필터(`common/region_filter.py`). 필터 코드가 어떻게 깨져도 정규식 결과로 되돌린다(codex 설계 검토 #2).
    `exempt` = 그날 파일에 이미 있는 기사 — 재수집이 빼지 않는다."""
    try:
        from common import region_filter as RF
        return RF.guard(kept, os.environ, 'japan', exempt=exempt, post=post)
    except Exception as e:
        return kept, {'mode': 'regex', 'market': 'japan', 'stopped': f'crash:{type(e).__name__}'}


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
    kept, region = apply_region_filter(kept, post=region_post,
                                       exempt=_saved_guids(_daily_path(datadir, session)))
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
    # 목록을 넘길 날은 목록이 아직 정해지지 않은 날뿐이다 — 나머지는 요약·공식 출처·본문만 다시(2026-11-19)
    list_days = [d for d in days if args.refresh or not lists_ready(_read(_path(args.datadir, d)))]
    print(f'받을 날: {", ".join(days)}' + (f' · 목록을 넘길 날: {", ".join(list_days)}' if list_days else
                                          ' · 목록은 넘기지 않는다'))
    ctx = _context()
    rows, notes, reach = harvest(list_days[0], args.today, ctx) if list_days else ([], [], {})
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
        lr = day in list_days
        collect_day(day, rows if lr else [], official_rows, args.today, args.bodydir, ctx,
                    off_ok and lr and complete_for(day, reach), (notes if lr else []) + off_notes,
                    datadir=args.datadir, reach=reach if lr else None, off_ok=off_ok, lists_read=lr)
    return 1 if list_days and not rows else 0

if __name__ == '__main__':
    sys.exit(main())
