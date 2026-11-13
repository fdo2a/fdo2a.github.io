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
import threading
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import date as _date
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from us.news import (EXTRA_FEEDS, FEEDS, ROTATE, TWO_PHASE, Stop, _nli_body,  # noqa: E402
                     body_note, candidates, categorize, confirm, dedupe, extract_body, identify,
                     legacy_fill, page_published, pages, parse_feed_strict, pdf_text, reconcile,
                     select, title_wire, trim, wire_of)
from us.news_summary import SYSTEM_ANALYSIS, new_run, summarize_items, usable_summary  # noqa: E402

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


def get(url, ctx, retries=2, impersonated=_impersonated, timeout=TIMEOUT):
    req = urllib.request.Request(
        url, headers={'User-Agent': UA,
                      'Accept': 'application/rss+xml,application/xml;q=0.9,*/*;q=0.8'})
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
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


def get_bytes(url, ctx, timeout=TIMEOUT):
    """PDF 처럼 글자로 풀면 깨지는 응답(일본은행 정책 발표문)."""
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
        return r.read()


# ── 시간 상한 (2026-11-12, 매체 넓히기) ────────────────────────────────────
# When changing this: read `docs/superpowers/specs/2026-11-12-us-news-source-spread.md` first.
# 새 매체 18곳은 Actions 에서 열리는지 재 본 적이 없다. 느리거나 막힌 매체가 수집을 붙잡으면
# 루틴(`timeout 900 gh run watch`)이 먼저 끊긴다. 그래서 새로 더한 일에는 벽시계 마감을 건다.
EXTRA_TIMEOUT = 10          # 새 매체 요청 한 건
EXTRA_FEED_BUDGET = 60      # 새 매체 피드 18개 합계
SPREAD_BUDGET = 150         # 미국 다섯 갈래를 매체 돌려 뽑기로 고르는 시간
STAGE_BUDGET = 240          # 그 단계 전체(돌려 뽑기 + 시간이 다 됐을 때의 옛 길)
BLOCK_AFTER = 2             # 한 실행에서 이만큼 요청이 실패한 매체는 더 묻지 않는다


class Late(Exception):
    """요청이 마감 안에 끝나지 않았다. 결과는 버린다."""


class Budget:
    """단조 시계 마감. `clock` 은 시험이 갈아 끼운다."""

    def __init__(self, seconds, clock=time.monotonic):
        self.clock, self.end = clock, clock() + seconds

    def left(self):
        return max(0.0, self.end - self.clock())

    def over(self):
        return self.left() <= 0


def bounded(fn, budget, per=EXTRA_TIMEOUT):
    """`fn()` 을 데몬 스레드에서 돌리고 min(per, 남은 시간)만 기다린다. 못 끝내면 `Late`.

    **`fn` 은 부작용이 없는 요청이어야 한다** — 늦은 스레드는 버려 둘 뿐 멈추지 못하므로, 그 안에서
    행을 고치거나 파일을 쓰면 마감 뒤에 결과가 바뀐다(codex 설계 검토 3회차 3-4). 소켓 timeout 은
    읽기 한 번의 상한이지 요청 전체의 상한이 아니고, 403·429 의 브라우저 지문 재시도는 요청을
    두 번 더 한다 — 그래서 요청마다 timeout 을 줄이는 대신 여기서 기다림을 끊는다
    (`common/region_filter.py` 와 같은 방식).
    """
    wait = min(per, budget.left())
    if wait <= 0:
        raise Late()
    box = {}

    def run():
        try:
            box['value'] = fn()
        except BaseException as e:          # 스레드 밖으로 새면 아무도 못 본다
            box['error'] = e

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(wait)
    if worker.is_alive():
        raise Late()
    if 'error' in box:
        raise box['error']
    return box['value']


def _host_of(url):
    parts = (url or '').split('/')
    return parts[2] if len(parts) > 2 else ''


def fetch_bodies(chosen, bodydir, ctx, fetch=None, fetch_bytes=None, start=1, hosted=False):
    """선정된 기사의 본문을 bodydir 에 떨어뜨린다. 실패는 건별로 기록하고 넘어간다.

    피드에 날짜가 없던 기사(Investing.com 뉴스)는 기사면의 발행 시각을 적는다 — 글로벌·칼럼
    확정(`trim`)이 그 날짜로 창을 본다. 피드 날짜는 덮지 않는다.

    `start` 는 본문 파일 번호의 시작이다 — 미국 다섯 갈래는 한 건씩 여러 번 부르므로 부르는 쪽이
    번호를 전진시킨다(같은 번호를 두 번 쓰면 요약이 다른 기사의 본문을 읽는다). `hosted` 는
    매체별 안내문 거르기를 켠다.
    """
    fetch, fetch_bytes = fetch or get, fetch_bytes or get_bytes
    os.makedirs(bodydir, exist_ok=True)
    for i, it in enumerate(chosen, start):
        try:
            if it['url'].lower().endswith('.pdf'):
                page, body = '', pdf_text(fetch_bytes(it['url'], ctx))
            else:
                page = fetch(it['url'], ctx)
                # 닛세이는 「■要旨」 이 없으면 본문이 아니다 — 페이지 문단으로 대체하지 않는다(codex 2026-10-18)
                body = (_nli_body(page) if 'nli-research.co.jp' in it['url']
                        else extract_body(page, host=_host_of(it['url']) if hosted else None))
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


def _why(e):
    return f'HTTP {e.code}' if isinstance(e, urllib.error.HTTPError) else type(e).__name__


def _fast_get(url, ctx):
    return get(url, ctx, retries=0, timeout=EXTRA_TIMEOUT)


def _fast_bytes(url, ctx):
    return get_bytes(url, ctx, timeout=EXTRA_TIMEOUT)


def harvest_extra(ctx, budget, notes, fetch=None, feeds=None):
    """새 매체 피드(`EXTRA_FEEDS`)를 받는다. 실패·시간 초과는 `notes` 에 적고 넘어간다.

    돌려주는 행은 `identify()` 를 거쳤다 — guid 가 URL 이다.
    """
    fetch = fetch or _fast_get
    rows = []
    for hint, urls in (EXTRA_FEEDS if feeds is None else feeds).items():
        for url in urls:
            if budget.over():
                notes.append('extra_time_cap: 새 매체 피드를 다 받지 못했다')
                return identify(rows)
            try:
                items, why_empty = parse_feed_strict(
                    bounded(lambda u=url: fetch(u, ctx), budget), hint)
            except Exception as e:
                notes.append(f'{hint} {url}: {_why(e)}')
                print(f'  {hint}: 피드 실패 ({_why(e)}) {url[-40:]}', file=sys.stderr)
                continue
            if why_empty:
                notes.append(f'{hint} {url}: {why_empty}')
            elif not items:
                notes.append(f'{hint} {url}: 항목 0건')
            rows.extend(items)
            print(f'  {hint}: {len(items)}건 ({_host_of(url)})')
    return identify(rows)


def existing_index(path):
    """그날 파일의 {guid: (source, url)} — `reconcile()` 이 후보와 대조한다."""
    try:
        with open(path, encoding='utf-8') as fh:
            items = json.load(fh).get('items') or []
    except (OSError, ValueError):
        return {}
    return {it['guid']: (it.get('source'), it.get('url')) for it in items if it.get('guid')}


def _tally(cands, log):
    """{매체: {candidates, tried, with_body, chosen, fail: {사유: n}}}.

    `fail` 의 사유는 본문 수집이 적은 값 그대로다(HTTP 403·Late·TimeoutError·추출 실패·blocked) —
    Actions 에서 어느 매체가 왜 빠졌는지를 이 숫자로 읽는다. 그 밖에 undated·stale·same_story.
    """
    out = {}

    def cell(source):
        return out.setdefault(source or '', {'candidates': 0, 'tried': 0, 'with_body': 0,
                                             'chosen': 0, 'fail': Counter()})
    for r in cands:
        cell(r.get('source'))['candidates'] += 1
    for r, outcome in log:
        c = cell(r.get('source'))
        if outcome == 'same_story':
            c['fail']['same_story'] += 1
            continue
        note = r.get('body_note')
        if outcome == 'no_body' and note == 'blocked':
            c['fail']['blocked'] += 1
            continue
        c['tried'] += 1
        if outcome == 'no_body':
            c['fail'][note or 'no_body'] += 1
            continue
        c['with_body'] += 1
        if outcome == 'chosen':
            c['chosen'] += 1
        else:
            c['fail'][outcome] += 1
    return {s: dict(c, fail=dict(c['fail'])) for s, c in out.items()}


def spread_stage(rows, bodydir, ctx, per_category, now, start, fetch=None, fetch_bytes=None,
                 clock=time.monotonic, spread_seconds=SPREAD_BUDGET, stage_seconds=STAGE_BUDGET):
    """미국 다섯 갈래를 매체 돌려 뽑기로 확정한다. (확정 행, funnel, 다음 본문 번호).

    `rows` 는 dedupe 를 거친 전체 후보다. 본문은 **고르면서** 한 건씩 받는다 — 안 열린 기사는
    자리를 차지하지 않고 같은 매체의 다음 기사, 그다음 매체로 넘어간다. 돌려 뽑기에 `spread_seconds`
    를 다 쓰면 그 갈래의 남은 자리와 뒤 갈래는 예전 방식(기존 피드의 최신순)으로 채우고, 그것도
    `stage_seconds` 안에서만 한다. 마감에 걸리면 덜 찬 채로 돌려준다.
    """
    fetch, fetch_bytes = fetch or _fast_get, fetch_bytes or _fast_bytes
    stage = Budget(stage_seconds, clock)
    spread = Budget(min(spread_seconds, stage_seconds), clock)
    state = {'next': start, 'stage_cap': False}
    fails = Counter()

    def ask(row, budget):
        n, state['next'] = state['next'], state['next'] + 1          # 시도마다 전진 — 성공·실패 불문
        fetch_bodies([row], bodydir, ctx,
                     fetch=lambda u, c: bounded(lambda: fetch(u, c), budget),
                     fetch_bytes=lambda u, c: bounded(lambda: fetch_bytes(u, c), budget),
                     start=n, hosted=True)
        return bool(row.get('body_chars'))

    def try_spread(row):
        if spread.over():
            raise Stop()
        if 'body_chars' in row:                 # 이미 물었다
            return bool(row['body_chars'])
        source = row.get('source')
        if fails[source] >= BLOCK_AFTER:
            row['body_chars'], row['body_note'] = 0, 'blocked'
            return False
        if ask(row, spread):
            return True
        if row.get('body_note') != '추출 실패':    # 껍데기 한두 건으로 매체를 막지 않는다 — 요청 실패만 센다
            fails[source] += 1
        return False

    def try_legacy(row):
        if stage.over():
            state['stage_cap'] = True
            raise Stop()
        if 'body_chars' in row:
            return bool(row['body_chars'])
        source = row.get('source')
        if fails[source] >= BLOCK_AFTER:          # 옛 길도 막힌 매체에는 다시 묻지 않는다(codex 구현 검토 1회차)
            row['body_chars'], row['body_note'] = 0, 'blocked'
            return False
        if ask(row, stage):
            return True
        if row.get('body_note') != '추출 실패':
            fails[source] += 1
        return False

    cands = candidates(rows, now)
    picked, cats, stopped, legacy_n = [], {}, [], 0
    for cat in ROTATE:
        chosen, log = [], []
        if not stopped:
            chosen, log, hit = confirm(cands[cat], try_spread, per_category, now)
            # 마지막 후보의 요청이 마감에 걸리면 `confirm` 은 Stop 없이 끝난다(더 물을 후보가 없다).
            # 그때도 시간이 다 된 것이다 — 이 갈래부터 옛 길로 간다(구현 검토 2회차).
            if hit or spread.over():
                stopped.append('spread_time_cap')
        if stopped:
            before = len(chosen)
            chosen, more = legacy_fill([r for r in rows if r.get('category') == cat], chosen,
                                       try_legacy, per_category)
            log += more
            legacy_n += len(chosen) - before
        picked.extend(chosen)
        cats[cat] = _tally(cands[cat], log)
    # 옛 길의 마지막 요청 중에 단계 마감이 끝나면 `try_legacy` 가 다시 불리지 않는다 — 여기서도 본다
    # (codex 구현 검토 4회차)
    if state['stage_cap'] or (stopped and stage.over()):
        stopped.append('stage_time_cap')
    funnel = {'categories': cats, 'legacy_filled': legacy_n, 'stopped': stopped,
              'blocked': sorted(s for s, n in fails.items() if n >= BLOCK_AFTER and s)}
    return picked, funnel, state['next']


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
    # 본문을 받았는데 요약이 없는 기사가 남아 있으면 동결하지 않는다 — 첫 실행에서 일부 API 호출만
    # 실패한 날이 그대로 굳던 길(codex 2026-09-27 #5). 다시 받을 때 기존 요약은 carry_summaries 가
    # 재사용하므로, 이미 쓰인 요약의 문장은 바뀌지 않는다.
    # 실을 수 없는 요약은 없는 것과 같다 — 일본어 요약만 있는 날이 동결돼 다시 요약되지 못했다(codex 2026-10-18).
    # 한자 조각·두 문단·자기 정정도 같다(summary_problem, 2026-10-18 게이트 방어)
    if any(it.get('body_chars') and not usable_summary(it.get('summary_ko')) for it in items):
        return False
    return any(usable_summary(it.get('summary_ko')) for it in items)


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
        # 실을 수 없는 요약은 옮기지 않는다 — 다시 요약하게 둔다(2026-10-18 일본어 요약·한자 조각)
        if prev and prev.get('summary_ko') and usable_summary(prev['summary_ko']):
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


US_REGION_CATEGORIES = ('economy', 'macro', 'politics')   # 사용자 결정 2026-10-28 — AI·산업은 해외 기업을 남긴다


def apply_region_filter(rows, exempt=(), post=None):
    """(행, region_filter 기록). 어떤 실패든 정규식 결과 그대로 — 수집을 멈추지 않는다."""
    try:
        from common import region_filter as RF
        rows, meta = RF.guard(rows, os.environ, 'us', categories=US_REGION_CATEGORIES, exempt=exempt,
                              post=post, deadline=RF.DEADLINE_SHORT, newest_first=True)
    except Exception as e:
        meta = {'mode': 'regex', 'market': 'us', 'stopped': f'crash:{type(e).__name__}'}
    print(f"  지역 필터: {meta.get('mode')} · 판정 {meta.get('answered', 0)}/{meta.get('asked', 0)}"
          f" · 뺌 {len(meta.get('dropped') or [])} · 끝 {meta.get('stopped')}")
    return rows, meta


def guids_in(path):
    try:
        from common.region_filter import guids_in as _g
        return _g(path)
    except Exception:
        return set()


def main():
    new_run()                     # 승격 예산은 이 실행 몫부터 센다
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

    # 새 매체(2026-11-12) — 시간 상한 안에서만. 막히거나 느리면 notes 에 적고 지금까지의 매체로 간다
    clock = time.monotonic()
    extra = harvest_extra(ctx, Budget(EXTRA_FEED_BUDGET), notes)
    harvested.extend(extra)
    seconds = {'extra_feeds': round(time.monotonic() - clock, 1)}

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
    # 국내/해외 필터(common/region_filter.py) — 경제·매크로·정치에서 Jev 가 conf≥0.9 로 해외라 한 것만 뺀다.
    # dedupe **전에**: 같은 기사의 글로벌 사본이 남는다. 그날 파일에 이미 있는 기사는 빼지 않는다
    # guid 충돌(매체도 URL 도 다른데 guid 가 같은 기사)은 지역 필터·dedupe **앞에서** 걷어낸다 — 요약 이월과
    # 면제가 guid 만 본다. 그날 파일에 이미 있는 기사가 이긴다
    rows, collided = reconcile(categorize(harvested), existing_index(path))
    if collided:
        notes.append(f'guid_collision: {len(collided)}건 버림')
    categorized, region = apply_region_filter(rows, exempt=guids_in(path))
    deduped = dedupe(categorized)
    chosen = select(deduped, per_category=args.per_category, now=now, defer=ROTATE)
    print(f'수집 {len(harvested)}건 → 중복 제거·선정 {len(chosen)}건(글로벌·칼럼은 후보, 미국 다섯 갈래는 따로)')

    fetch_bodies(chosen, args.bodydir, ctx)
    tried = len(chosen)
    chosen = trim(chosen, now)             # 글로벌·칼럼 확정 — 본문·날짜가 확인된 것만
    # 미국 다섯 갈래 — 매체를 돌려 가며 본문이 열리는 것만 확정한다
    clock = time.monotonic()
    picked, funnel, _ = spread_stage(deduped, args.bodydir, ctx, args.per_category, now, start=tried + 1)
    seconds['confirm'] = round(time.monotonic() - clock, 1)
    funnel.update(seconds=seconds, guid_collisions=collided)
    notes.extend(f'{why}: 미국 갈래를 시간 안에 다 고르지 못했다' for why in funnel['stopped'])
    # 예전 순서를 지킨다: MLCC, 미국 다섯 갈래, 글로벌, 칼럼
    chosen = ([it for it in chosen if it.get('category') not in TWO_PHASE] + picked
              + [it for it in chosen if it.get('category') in TWO_PHASE])
    for it in chosen:
        it.pop('_extra', None)             # 수집 중에만 쓰는 표시 — 저장하지 않는다
    mix = Counter(it.get('source') for it in picked)
    print(f'미국 다섯 갈래 {len(picked)}건 — ' + ', '.join(f'{s} {n}' for s, n in mix.most_common()))

    os.makedirs(os.path.dirname(path), exist_ok=True)
    carried = carry_summaries(path, chosen)
    if carried:
        print(f'  기존 요약 {carried}건 재사용')
    payload = {'report_date': args.date, 'harvested': len(harvested),
               'notes': notes, 'items': chosen, 'region_filter': region, 'funnel': funnel}
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
