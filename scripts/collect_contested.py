#!/usr/bin/env python3
"""쟁점 분석 수집 — 로컬 러너(`contested_local.py`)가 부른다. 네트워크만 쓴다(모델 호출 없음).

2026-10-21 사용자 지시 「최대한 claude 주간한도를 사용하도록」 → 판단은 Mac 의 `claude -p`(구독)가
한다. 클라우드 루틴 환경은 GitHub 말고 어디에도 닿지 못해(같은 날 실측: GDELT·언론 18곳·네이버 API
전부 000) 로컬로 정했다(사용자 「로컬로 하자」).

하는 일: 피드 재수집(기존 `data/news` 불변) → 사건 묶음 점수 상위 3개 → 묶음마다 GDELT → 허용
매체 본문(묶음당 ≤6, 각 ≤20,000자) → 출처 묶음. **본문은 레포에 쓰지 않는다** — 묶음은 러너의
임시 폴더에만 있다.

마감(`--deadline`)은 알람으로 어디서든 끊는다. `Deadline` 은 BaseException 이라 일반 예외 처리에
삼켜지지 않는다(구현 검토 P1).
"""

import argparse
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import contested as C  # noqa: E402
from fetch_news import _context, get  # noqa: E402
from us.news import FEEDS, extract_body, page_published, parse_feed_strict, wire_of  # noqa: E402

CANDIDATES = 3                # 본문까지 받아 보는 후보 수
SHORTLIST = 8                 # 고르는 쪽에 보여 주는 후보 수
GDELT_CALLS = 2
MAX_BODIES = 6
MAX_TRIES = 12
PER_HOST = 2
BODY_MIN, BODY_MAX = 1500, 20000
WINDOW = timedelta(hours=72)
GDELT = 'https://api.gdeltproject.org/api/v2/doc/doc'
GDELT_GAP, GDELT_COOLDOWN = 20, 60      # 15초 간격에도 429 를 받았다(10/21 실측)

# 「공신력 있는 기관이라면 다 좋아」(2026-09-26 사용자). 유료벽 매체(FT·블룸버그·WSJ·닛케이)는
# 본문이 없어 뺀다. 목록에 없는 도메인은 GDELT 에 나와도 읽지 않는다.
OUTLETS = {
    'reuters.com': 'Reuters', 'apnews.com': 'AP', 'theguardian.com': 'The Guardian',
    'bbc.com': 'BBC', 'bbc.co.uk': 'BBC', 'aljazeera.com': 'Al Jazeera', 'cnbc.com': 'CNBC',
    'npr.org': 'NPR', 'cbsnews.com': 'CBS News', 'nbcnews.com': 'NBC News', 'abcnews.go.com': 'ABC News',
    'cnn.com': 'CNN', 'politico.com': 'Politico', 'politico.eu': 'Politico Europe', 'axios.com': 'Axios',
    'thehill.com': 'The Hill', 'marketwatch.com': 'MarketWatch', 'investing.com': 'Investing.com',
    'finance.yahoo.com': 'Yahoo Finance', 'euronews.com': 'Euronews', 'dw.com': 'DW',
    'france24.com': 'France 24', 'independent.co.uk': 'The Independent', 'scmp.com': 'SCMP',
    'straitstimes.com': 'The Straits Times', 'channelnewsasia.com': 'CNA',
    'economictimes.indiatimes.com': 'The Economic Times', 'koreatimes.co.kr': 'The Korea Times',
    'koreaherald.com': 'The Korea Herald', 'abc.net.au': 'ABC Australia', 'cbc.ca': 'CBC',
    'japantoday.com': 'Japan Today', 'kyodonews.net': 'Kyodo', 'timesofisrael.com': 'The Times of Israel',
    'arabnews.com': 'Arab News', 'thenationalnews.com': 'The National',
}
_GARBAGE = ('outdated browser', 'enable javascript', 'subscribe to continue', 'sign in to read',
            'access denied', 'are you a robot', 'page not found', 'cookies are disabled')
_EVENT_CATS = ('politics', 'economy', 'macro', 'industry', 'ai', 'global', 'tech')
_NEWS_FEEDS = ('politics', 'economy', 'industry', 'tech', 'global')


class Deadline(BaseException):
    pass


class Run:
    def __init__(self, seconds):
        self.t0 = time.monotonic()
        self.limit = seconds
        self.notes = []
        self.hosts = {}

    def left(self):
        return self.limit - (time.monotonic() - self.t0)


# ── 사건 묶음 ────────────────────────────────────────────────────────────
_STOP = set('the and for with from says said after over into its are was has have will this that '
            'not but you your how why what who new more than about amid could would may can his her '
            'their they them our out off one two all just as at by in of on to a an is be it or up us '
            'we he she news live update updates report reports here there when where week year today'
            .split())


def _toks(title, summary=''):
    t = f'{title or ""} {(summary or "")[:200]}'
    caps = {w.lower() for w in re.findall(r"\b[A-Z][a-zA-Z\-']{2,}\b", t)} - _STOP
    words = {w for w in re.findall(r'[a-z]{4,}', t.lower())} - _STOP
    return caps, words


def cluster(rows):
    """제목·요약의 고유명사 2개 이상 + 낱말 자카드 0.12 이상이면 같은 사건. 합집합으로 묶는다."""
    T = [_toks(r.get('title'), r.get('summary')) for r in rows]
    parent = list(range(len(rows)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            (ci, wi), (cj, wj) = T[i], T[j]
            if len(ci & cj) >= 2 and len(wi & wj) / max(1, len(wi | wj)) >= 0.12:
                parent[find(j)] = find(i)
    groups = {}
    for i, r in enumerate(rows):
        groups.setdefault(find(i), []).append(r)
    return sorted(groups.values(), key=lambda g: -score(g))


def score(g):
    """주목도 근사 — 독립 매체 수가 가장 무겁고, 같은 매체의 후속 기사·정책 갈래가 그다음."""
    return (2 * len({r.get('source') for r in g}) + len(g)
            + sum(r.get('category') in ('politics', 'global', 'macro') for r in g) / 2)


def query_of(group):
    """GDELT 검색어 — 묶음 제목에 가장 많이 나온 고유명사 둘 + 일반 낱말 하나."""
    caps, words = Counter(), Counter()
    for r in group:
        c, w = _toks(r.get('title'))
        caps.update(c)
        words.update(w - c)
    top = [w for w, n in caps.most_common(3) if n >= 2][:2]
    top += [w for w, _ in caps.most_common(4) if w not in top][:2 - len(top)]
    noun = [w for w, n in words.most_common(5) if n >= 2 and w not in top][:1]
    return ' '.join(top + noun)


def harvest(ctx, now, run, fetch=get):
    """(48시간 내 행, 성공한 피드 수, 전체 피드 수)."""
    rows, ok, total = [], 0, 0
    for cat in _NEWS_FEEDS:
        for url in FEEDS[cat]:
            total += 1
            if run.left() < 600:
                run.notes.append('harvest_time_cap')
                break
            try:
                got, why = parse_feed_strict(fetch(url, ctx), cat)
                if why:                          # 200 으로 온 오류 페이지는 성공이 아니다(3차 P2)
                    run.notes.append(f'feed:{cat}:malformed')
                    continue
                ok += 1
            except Exception as e:
                run.notes.append(f'feed:{cat}:{type(e).__name__}')
                continue
            rows += got
            time.sleep(0.5)
    fresh, seen = [], set()
    for r in rows:
        when = _when(r.get('published'))
        k = C.canonical_url(r.get('url'))
        if when and now - timedelta(hours=48) <= when <= now + timedelta(hours=1) and k and k not in seen:
            seen.add(k)
            fresh.append(r)
    return fresh, ok, total


def _when(s):
    try:
        w = datetime.fromisoformat(s or '')
    except ValueError:
        return None
    return w if w.tzinfo else None


# ── GDELT ────────────────────────────────────────────────────────────────
def outlet_of(url):
    host = urllib.parse.urlsplit(url or '').netloc.lower().removeprefix('www.')
    for dom, name in OUTLETS.items():
        if host == dom or host.endswith('.' + dom):
            return dom, name
    return None, None


def gdelt(query, ctx=None, opener=urllib.request.urlopen, sleep=time.sleep):
    """(행 목록, 상태). 429 는 한 번만 식혔다 다시 — 그래도 막히면 `throttled`(그날 GDELT 중단)."""
    qs = urllib.parse.urlencode({'query': f'{query} sourcelang:english', 'mode': 'artlist',
                                 'format': 'json', 'maxrecords': 75, 'timespan': '3d',
                                 'sort': 'hybridrel'})
    req = urllib.request.Request(f'{GDELT}?{qs}', headers={'User-Agent': 'Mozilla/5.0'})
    for attempt in (0, 1):
        try:
            # 인증서 문맥을 꼭 넘긴다 — python.org 판 Python 은 기본 CA 가 없어 URLError 로 죽는다(10/21 실측)
            with opener(req, timeout=45, **({'context': ctx} if ctx else {})) as r:
                raw = r.read().decode('utf-8', 'replace')
            try:
                return json.loads(raw).get('articles') or [], 'ok'
            except ValueError:
                return [], 'bad_response'
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt == 0:
                sleep(GDELT_COOLDOWN)
                continue
            return [], 'throttled' if e.code == 429 else f'http_{e.code}'
        except Exception as e:
            return [], type(e).__name__
    return [], 'throttled'


def _gdelt_time(s):
    m = re.match(r'(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z', s or '')
    return datetime(*map(int, m.groups()), tzinfo=timezone.utc).isoformat() if m else None


# ── 본문 ─────────────────────────────────────────────────────────────────
_TITLE = re.compile(r'<title[^>]*>(.*?)</title>', re.S | re.I)


def admit(html, feed_title):
    """(본문, 사유). 기사 본문으로 받아들일지 — 길이만 보지 않는다(F09)."""
    body = extract_body(html, max_chars=BODY_MAX) or ''
    if any(g in body[:1000].lower() for g in _GARBAGE):
        return None, 'garbage'
    if len(body) < BODY_MIN:
        return None, 'short'
    m = _TITLE.search(html or '')
    a = set().union(*_toks(feed_title))
    b = set().union(*_toks((m.group(1) if m else '') + ' ' + body[:400]))
    if len(a) >= 2 and len(a & b) < 2:
        return None, 'title_mismatch'
    return body, 'ok'


def _shingles(text, n=5):
    w = re.findall(r'\w+', (text or '').lower())
    return {' '.join(w[i:i + n]) for i in range(max(0, len(w) - n + 1))}


def origin_groups(arts):
    """출처 = 통신사 전재 > 발행 매체 > 본문 지문(5-gram 자카드 0.6). 같은 매체의 다른 기사는
    독립 출처가 아니다(구현 검토 P2)."""
    sh = {a['article_id']: _shingles(a['body']) for a in arts}
    for a in arts:
        wire = wire_of(a['body'])
        a['wire'] = wire or ''
        a['origin_group'] = f'wire:{wire}' if wire else f'pub:{a["source"]}'
    for i, a in enumerate(arts):
        for b in arts[:i]:
            x, y = sh[a['article_id']], sh[b['article_id']]
            if x and y and len(x & y) / len(x | y) >= 0.6:
                a['origin_group'] = b['origin_group']
                break
    return arts


def in_window(when, cutoff):
    w = _when(when)
    return bool(w) and cutoff - WINDOW <= w <= cutoff + timedelta(hours=1)


def fetch_bodies(cands, ctx, run, cutoff, fetch=get, status=None):
    """`status` 에 시도마다 결과를 쌓는다 — 후보마다 따로 남겨 다른 후보의 성공이 실패를 덮지
    않게 한다(4차 P1)."""
    status = status if status is not None else []
    got, per_host, tried = [], Counter(), 0
    for c in cands:
        if len(got) >= MAX_BODIES or tried >= MAX_TRIES or run.left() < 120:
            break
        dom, name = outlet_of(c['url'])
        if not dom or per_host[dom] >= PER_HOST:
            continue
        tried += 1
        try:
            html = fetch(c['url'], ctx)
        except Exception as e:
            run.hosts[dom] = f'fail:{type(e).__name__}'
            status.append('fail')
            continue
        body, why = admit(html, c['title'])
        run.hosts[dom] = why
        status.append(why)
        if not body:
            continue
        when = page_published(html) or c.get('published') or c.get('seen_at')
        if not in_window(when, cutoff):
            run.hosts[dom] = 'out_of_window'
            status[-1] = 'out_of_window'
            continue
        per_host[dom] += 1
        got.append({'article_id': C.article_id(c['url']), 'url': C.canonical_url(c['url']),
                    'title': (c['title'] or '')[:300], 'source': name, 'published_at': when,
                    'truncated': len(body) >= BODY_MAX, 'body': body})
    return origin_groups(got)


# ── 묶음 ─────────────────────────────────────────────────────────────────
def snapshot(path):
    try:
        commit = subprocess.run(['git', 'log', '-1', '--format=%H', '--', path], capture_output=True,
                                text=True, check=True).stdout.strip() or None
    except Exception:
        commit = None
    with open(path, 'rb') as fh:
        return {'path': path, 'commit': commit, 'sha256': hashlib.sha256(fh.read()).hexdigest()}


def build(args, run, now, rank=None):
    """`rank(views) -> [cand_id …]` 가 있으면 그 순서로 GDELT·본문을 쓴다 — GDELT 는 몇 번만에 막히므로
    (10/21 실측: 둘째 호출부터 429) 고르는 쪽이 먼저 순서를 정해야 1순위 사건에 쓰인다."""
    md_path = os.path.join(args.datadir, 'market_data.json')
    with open(md_path, encoding='utf-8') as fh:
        md = json.load(fh)
    if md.get('report_date') != args.date or not md.get('complete'):
        return {'status': 'error', 'reason': 'market_data_not_ready'}
    ctx = _context()
    pool, ok_feeds, total = harvest(ctx, now, run)
    if ok_feeds < total / 2:
        return {'status': 'error', 'reason': 'harvest_failed', 'feeds_ok': ok_feeds}
    groups = [g for g in cluster([r for r in pool if r.get('category') in _EVENT_CATS])
              if len(g) >= 3 or len({r.get('source') for r in g}) >= 2][:SHORTLIST]
    if not groups:
        return {'status': 'none', 'reason': 'no_candidate', 'harvest': len(pool)}
    views = [{'cand_id': f'k{i + 1}', 'query': query_of(g), 'titles': [r.get('title') for r in g][:8],
              'outlets': sorted({r.get('source') or '' for r in g})} for i, g in enumerate(groups)]
    order = list(range(len(groups)))
    if rank is not None:
        try:
            want = [v['cand_id'] for v in views]
            got = [c for c in rank(views) if c in want]
            order = [want.index(c) for c in dict.fromkeys(got)] + \
                [i for i in order if want[i] not in got]
        except Exception as e:
            run.notes.append(f'rank:{type(e).__name__}')
    cands, gstat, calls = [], 'ok', 0
    for i in order[:CANDIDATES]:
        g, v = groups[i], views[i]
        q, rows = v['query'], []
        if gstat != 'throttled' and calls < GDELT_CALLS:
            if calls:
                time.sleep(GDELT_GAP)
            rows, gstat = gdelt(q, ctx)
            calls += 1
        qtok = set(q.split())
        found = [{'url': r['url'], 'title': r.get('title') or '', 'published': r.get('published'),
                  'seen_at': None} for r in g]
        found += [{'url': r.get('url'), 'title': r.get('title') or '', 'published': None,
                   'seen_at': _gdelt_time(r.get('seendate'))} for r in rows]
        seen, uniq = set(), []
        for c in found:
            k = C.canonical_url(c['url'])
            if k and k not in seen and outlet_of(c['url'])[0]:
                seen.add(k)
                uniq.append(c)
        # 주목 트리거는 제목이 검색어와 두 낱말 이상 겹치는 발견분만 센다(구현 검토 P2)
        relevant = {outlet_of(c['url'])[1] for c in uniq
                    if len(qtok & set().union(*_toks(c['title']))) >= min(2, len(qtok))}
        status = []
        arts = fetch_bodies(uniq, ctx, run, now, status=status)
        cands.append({'cand_id': v['cand_id'], 'score': score(g), 'query': q, 'titles': v['titles'],
                      'outlets_seen': sorted(relevant), 'articles': arts,
                      'fetch': dict(Counter(status))})
        if len({a['origin_group'] for a in arts}) >= C.MIN_ORIGINS:
            break                                  # 1순위부터 — 쓸 수 있는 사건을 찾으면 멈춘다
    return {'status': 'ok', 'gdelt': gstat, 'discovery': gstat, 'harvest': len(pool),
            'market_snapshot': snapshot(md_path), 'registry': C.market_registry(md),
            'candidates': cands}


def collect(date, datadir, deadline=900, now=None, rank=None):
    """묶음 dict(본문 포함). 마감은 알람으로 강제하고, 어떤 경우에도 status 를 가진 dict 를 돌려준다."""
    run = Run(deadline)
    now = now or datetime.now(timezone.utc)
    a = argparse.Namespace(date=date, datadir=datadir)
    old = None
    if hasattr(signal, 'SIGALRM'):
        def _alarm(*_):
            raise Deadline()
        old = signal.signal(signal.SIGALRM, _alarm)
        signal.alarm(max(60, deadline))
    try:
        b = build(a, run, now, rank)
    except Deadline:
        b = {'status': 'error', 'reason': 'deadline'}
    except Exception as e:                       # 원인 종류만 — 본문·URL 을 로그에 남기지 않는다
        b = {'status': 'error', 'reason': f'collect_{type(e).__name__}'}
    finally:
        if hasattr(signal, 'SIGALRM'):
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old or signal.SIG_DFL)
    b.update(report_date=date, collected_at=now.isoformat(timespec='seconds'),
             notes=run.notes[:40], hosts=run.hosts)
    return b


def main(argv=None):
    """디버깅용 — 묶음을 로컬 파일로(레포 밖에 둔다. 본문이 들어 있다)."""
    ap = argparse.ArgumentParser()
    ap.add_argument('--date', required=True, type=C.iso_date)
    ap.add_argument('--datadir', default='data')
    ap.add_argument('--out', required=True)
    ap.add_argument('--deadline', type=int, default=900)
    a = ap.parse_args(argv)
    b = collect(a.date, a.datadir, a.deadline)
    with open(a.out, 'w', encoding='utf-8') as fh:
        json.dump(b, fh, ensure_ascii=False)
    n = [len(c['articles']) for c in b.get('candidates', [])]
    print(f'bundle {b["status"]} {b.get("reason", "")} candidates={n} gdelt={b.get("gdelt")}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
