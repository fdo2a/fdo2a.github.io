#!/usr/bin/env python3
"""CNBC·Yahoo 뉴스 피드를 읽고 발행 가능한 후보로 줄이는 순수 로직.

2026-09-19 사용자 지시 「cnbc나 yahoo finance에서 주요 뉴스들, 시장 뉴스, 정치뉴스,
정책뉴스, 경제뉴스 같은것들의 내용을 정리하는걸 추가하자」 + 「300자 분량으로 줄이고
대신 여러 기사를 가져오자」.

**왜 에이전트 웹서치가 아니라 스크립트인가.** 지금까지 뉴스는 수집 담당이 검색해
`research_notes.md` 에 적었고, 그러면 발행본에 실린 뉴스가 실재했는지 **사후에 확인할
방법이 없다.** 파일로 받아 커밋하면 `source_gate` 와 같은 대조가 가능하다 — 발행본이
인용한 제목·URL 이 그날 수집분에 있는지 본다. 지어낸 뉴스가 막힌다.

**네트워크는 여기 없다.** 이 모듈은 문자열만 다룬다(`fetch_news.py` 가 받아 온다).
피드가 형식을 바꿔도 파서가 조용히 빈 값을 돌려주는 실패가 제일 무서운데, 순수 함수로
갈라 두어야 그 자리를 테스트가 지킬 수 있다 — `release_text.py` 와 같은 분담이다.

**본문 원문은 커밋하지 않는다.** 이 레포는 공개다(`fdo2a.github.io`). 커밋되는
`data/releases/*.txt` 는 미국 정부 저작물이라 가능한 것이고, CNBC·Yahoo 기사는 상업
저작물이라 같은 취급을 못 한다. 본문은 실행 중에만 읽고 버리며, 남는 것은 메타데이터와
우리가 쓴 한국어 요약이다.
"""

import html as _html
import re
from email.utils import parsedate_to_datetime

# 사용자가 말한 다섯 갈래 중 「정치」와 「정책」은 CNBC 에서 한 피드라 실제 갈래는 넷이다.
# MLCC 산업 뉴스는 종목 피드에서 수집하며 뉴스 게이트가 본문 근거를 검증한다.
# **뉴스 피드는 유동성 있는 넷만 본다.** 표는 여덟 종목을 그대로 싣지만(시세는
# `collect_market_data.MLCC`), 뉴스 피드까지 여덟 개를 연속 호출하면 Yahoo 가 429 를
# 준다(2026-09-19 실측). 월신·홀리스톤·싼환·펑화는 애초에 영문 기사가 1~2건뿐이라
# 빼도 잃는 것이 거의 없다 — 요청을 절반으로 줄이는 쪽이 남는 장사다.
#
# Google News RSS 도 재 봤다(헤드라인 100건, 쓰로틀 없음). **본문을 못 받아서 탈락했다** —
# 링크가 news.google.com 안에 머무는 595 KB JS 페이지라 원문에 닿지 못하고, 그러면
# 300자 요약의 재료가 없다. 헤드라인만 있는 뉴스는 이 리포트가 쓰지 않는다.
MLCC_TICKERS = ('6981.T', '009150.KS', '6976.T', '2327.TW')
_YAHOO_TICKER = 'https://feeds.finance.yahoo.com/rss/2.0/headline?s={}&region=US&lang=en-US'

FEEDS = {
    'top': ('https://www.cnbc.com/id/100003114/device/rss/rss.html',),
    'market': ('https://www.cnbc.com/id/15839069/device/rss/rss.html',
               'https://finance.yahoo.com/news/rssindex'),
    'economy': ('https://www.cnbc.com/id/20910258/device/rss/rss.html',),
    'politics': ('https://www.cnbc.com/id/10000113/device/rss/rss.html',),
    'mlcc': tuple(_YAHOO_TICKER.format(t) for t in MLCC_TICKERS),
}

LABELS = {'top': '주요', 'market': '시장', 'economy': '경제', 'politics': '정치·정책',
          'mlcc': 'MLCC'}

# 「오늘의 뉴스」 섹션이 싣는 갈래. `mlcc` 는 MLCC 섹션의 뉴스 층으로 가므로 빠진다.
DIGEST_CATEGORIES = ('top', 'market', 'economy', 'politics')

# 겹친 기사는 더 좁은 갈래에 남긴다 — 「경제」가 「주요」보다 독자에게 말해 주는 것이 많다.
# 숫자가 작을수록 좁다. MLCC 가 가장 좁다 — 종목 피드에서 왔으므로 그 종목 기사가 맞다.
NARROWNESS = {'mlcc': 0, 'economy': 1, 'politics': 1, 'market': 2, 'top': 3}

DEFAULT_PER_CATEGORY = 3
DEFAULT_MAX_BODY = 12000

# RSS `description` 은 한 줄 요약이 관례지만 **전문을 담아 보내는 피드가 있다**
# (2026-09-19 codex 검토 #2). 그대로 저장하면 상업 기사 전문이 공개 레포에 커밋된다.
# 우리가 쓰는 것은 「무슨 기사인지」까지이므로 자른다.
MAX_SUMMARY = 400

# 기사 페이지가 HTTP 200 으로 오류 안내문만 돌려주는 경우가 있다(#13). 그것을 본문으로
# 인정하면 `body_chars > 0` 이 되어 「본문 확보」 조건이 거짓으로 충족된다.
MIN_BODY = 400
# **문단 단위로, 앞머리에서만 본다**(2026-09-19 codex 2차 검토 #11). 전체 본문에 대한
# 부분문자열 검사는 장애를 «서술한» 정상 기사를 통째로 버렸고, 반대로 안내문이 길면
# 통과시켰다. 오류 페이지는 첫 문단부터 그 말을 한다.
_ERROR_PAGE = (
    'could not process your request', 'please try again later',
    'access denied', 'are you a robot', 'enable javascript', 'javascript is disabled',
    'page not found', 'temporarily unavailable', 'subscribe to continue',
    'this site requires', 'unusual traffic',
)

_ITEM = re.compile(r'<item[^>]*>(.*?)</item>', re.S | re.I)
_CDATA = re.compile(r'^\s*<!\[CDATA\[(.*?)\]\]>\s*$', re.S)
_DROP = re.compile(r'<(script|style|noscript|svg|head)\b.*?</\1>', re.S | re.I)
_PARA = re.compile(r'<p[^>]*>(.*?)</p>', re.S | re.I)
_TAG = re.compile(r'<[^>]+>')
_WS = re.compile(r'\s+')

# 기사 페이지에 같이 실려 오는 전역 네비게이션과 매체 소개문. 본문이 아니다.
_BOILERPLATE = (
    'livestream', 'sign in', 'create free account', 'watchlist',
    'cnbc is the world leader', 'find fast, actionable information',
    'subscribe to cnbc pro', 'all rights reserved', 'got a confidential news tip',
    'data is a real-time snapshot', 'sign up for free newsletters',
)

# 산문 한 문단의 하한. 캡션·크레딧·버튼 라벨을 걸러 내는 값이다.
MIN_PARAGRAPH = 60


def _field(chunk, name):
    m = re.search(rf'<{name}[^>]*>(.*?)</{name}>', chunk, re.S | re.I)
    if not m:
        return None
    raw = m.group(1)
    cd = _CDATA.match(raw)
    text = cd.group(1) if cd else raw
    return _WS.sub(' ', _html.unescape(_TAG.sub('', text))).strip() or None


def _norm_url(url):
    """중복 판정용 정규화 — 추적 파라미터와 프래그먼트는 같은 기사를 둘로 만든다(#14)."""
    if not url:
        return None
    base = url.split('#', 1)[0]
    if '?' in base:
        head, _, query = base.partition('?')
        keep = [q for q in query.split('&')
                if q and not q.split('=', 1)[0].lower().startswith(('utm_', 'ref', 'cmp'))]
        base = head + ('?' + '&'.join(keep) if keep else '')
    return base.rstrip('/')


def _iso(pubdate):
    """RFC 822 -> ISO 8601. 못 읽으면 None — 날짜를 추측하지 않는다."""
    if not pubdate:
        return None
    try:
        return parsedate_to_datetime(pubdate).isoformat()
    except Exception:
        return None


def parse_feed(xml, category):
    """RSS 문자열 -> [{guid, url, title, summary, published, category, source}].

    피드가 죽어 HTML 오류 페이지를 돌려주는 날이 있다. 그때는 빈 목록이다 —
    비-코어라 그날 뉴스 섹션이 빠질 뿐, 브리프 전체가 서지는 않는다.
    """
    if not xml:
        return []
    out = []
    for chunk in _ITEM.findall(xml):
        url = _field(chunk, 'link')
        if not url:
            continue                      # 가리킬 수 없는 것은 출처가 아니다
        summary = _field(chunk, 'description')
        out.append({
            'guid': _field(chunk, 'guid') or url,
            'url': url,
            'title': _field(chunk, 'title'),
            'summary': (summary or '')[:MAX_SUMMARY] or None,
            'published': _iso(_field(chunk, 'pubDate')),
            'category': category,
            'source': 'Yahoo Finance' if 'yahoo.com' in url else 'CNBC',
        })
    return out


def extract_body(html, max_chars=DEFAULT_MAX_BODY):
    """기사 HTML -> 읽을 수 있는 본문.

    `release_text.to_text` 와 달리 **`<p>` 만 본다.** 발표문은 표가 본체라 통째로
    평탄화하는 것이 맞지만, 뉴스 기사는 본문이 전부 `<p>` 에 있고 나머지는 추천 기사·
    시세 위젯·광고다. 좁게 잡는 쪽이 잡음을 덜 문다.
    """
    if not html:
        return ''
    stripped = _DROP.sub(' ', html)
    kept = []
    for raw in _PARA.findall(stripped):
        text = _WS.sub(' ', _html.unescape(_TAG.sub('', raw))).strip()
        if len(text) < MIN_PARAGRAPH:
            continue
        low = text.lower()
        if any(b in low for b in _BOILERPLATE):
            continue
        kept.append(text)
    if kept and any(e in kept[0].lower()[:200] for e in _ERROR_PAGE):
        return ''          # 첫 문단부터 안내문이면 기사가 아니다
    body = '\n\n'.join(kept)
    if len(body) < MIN_BODY:
        return ''          # 여기서 걸러야 게이트의 「본문 확보」가 참이 된다
    return body[:max_chars] if len(body) > max_chars else body


def body_note(body):
    """`extract_body` 가 왜 비었는지 — 「추출 실패」와 「짧다」를 가른다(2차 #12)."""
    if not body:
        return '추출 실패'
    if len(body) < MIN_BODY:
        return '짧다'
    return None


def dedupe(items):
    """같은 기사가 여러 피드에 걸린 것을 하나로. 더 좁은 갈래가 이긴다.

    2026-09-19 codex 검토 #14 로 세 군데를 고쳤다.
      · **열쇠가 잇는 그룹을 합친다** — 첫 일치만 보던 판은 `(a,u1) (b,u2) (a,u2)`
        처럼 세 번째 행이 앞의 두 그룹을 이을 때 둘을 남겼다. 합집합으로 푼다.
      · **guid 는 매체 안에서만 고유하다** — 두 매체가 같은 숫자를 쓰면 별개 기사가
        하나로 뭉개졌다. 출처로 범위를 나눈다.
      · **추적 파라미터를 걷어낸 URL 로 비교한다** — `?utm_source=rss` 하나가 같은
        기사를 둘로 만들었다.
    """
    rows = [it for it in (items or []) if it.get('guid') or it.get('url')]
    parent = {}

    def find(k):
        parent.setdefault(k, k)
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    def keys(it):
        out = []
        if it.get('guid'):
            out.append(('guid', it.get('source'), it['guid']))
        u = _norm_url(it.get('url'))
        if u:
            out.append(('url', None, u))
        return out

    every = [keys(it) for it in rows]
    for ks in every:
        for k in ks[1:]:
            a, b = find(ks[0]), find(k)
            if a != b:
                parent[b] = a

    out, seen = [], {}
    for it, ks in zip(rows, every):
        root = find(ks[0])
        if root not in seen:
            seen[root] = dict(it)
            out.append(seen[root])
            continue
        cur = seen[root]
        if NARROWNESS.get(it.get('category'), 9) < NARROWNESS.get(cur.get('category'), 9):
            cur['category'] = it['category']
        # **빈 칸은 뒤 행이 채운다**(2차 #10) — 첫 행의 결손 정보가 그룹을 대표하면
        # 제목 없는 기사나 옛 URL 이 남아 본문 수집이 실패한다.
        for k, val in it.items():
            if val and not cur.get(k):
                cur[k] = val
    return out


def select(items, per_category=DEFAULT_PER_CATEGORY):
    """갈래별 상한을 적용한다. 갈래가 얇으면 **다른 갈래에서 채우지 않는다.**

    상한이지 할당량이 아니다 — 쓸 만한 것이 둘뿐인 날 셋째를 고르는 것은 자리를 채우는
    것이고, 그러면 발행본이 「오늘 있었던 일 목록」으로 되돌아간다.
    """
    buckets = {}
    for it in items or []:
        buckets.setdefault(it.get('category'), []).append(it)
    out = []
    for cat in sorted(buckets, key=lambda c: NARROWNESS.get(c, 9)):
        rows = buckets[cat]
        dated = sorted((r for r in rows if r.get('published')),
                       key=lambda r: r['published'], reverse=True)
        undated = [r for r in rows if not r.get('published')]
        out.extend((dated + undated)[:per_category])
    return out


_ATOM = re.compile(r'<feed\b[^>]*xmlns="http://www\.w3\.org/2005/Atom"', re.I)
_NS_ITEM = re.compile(r'<\w+:item\b', re.I)


def parse_feed_strict(xml, category):
    """(rows, note) — 형식이 바뀌어 0건인 것과 진짜 빈 피드를 가른다(#15).

    조용히 빈 목록을 돌려주면 그날 뉴스가 통째로 사라진 것을 아무도 모른다.
    """
    rows = parse_feed(xml, category)
    if rows or not xml:
        return rows, None
    if _ATOM.search(xml):
        return [], 'Atom 피드 — RSS 파서가 읽지 못한다'
    if _NS_ITEM.search(xml):
        return [], '네임스페이스 접두사가 붙은 item — 피드 형식이 바뀌었다'
    if '<item' not in xml.lower() and '<channel' not in xml.lower():
        return [], 'RSS 가 아닌 응답(오류 페이지일 수 있다)'
    return [], None
