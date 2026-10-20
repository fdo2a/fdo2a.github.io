#!/usr/bin/env python3
"""쟁점 분석 수집 — KR(2단계). 로컬 러너(`contested_local.py`)가 부른다. 네트워크만 쓴다(모델 호출 없음).

US 수집기(`collect_contested.py`)와 같은 묶음 모양을 돌려줘 `contested_build.analyze` 를 그대로 쓴다.
다른 점은 출처다:
- **발견 = 네이버 검색 API(NAVER API HUB)** — `naverapihub.apigw.ntruss.com/search/v1/news`, 키는 환경
  변수 `NAVER_CLIENT_ID`·`NAVER_CLIENT_SECRET`(러너가 키체인에서 넣는다). 로그·결과·예외에 남기지 않는다.
  **약관(검색 API 특약 2.1-2.3: 검색결과 표시 목적만, AI 입력 금지)과 충돌한다 — 사용자 결정
  「약관 무시하고 진행해」(2026-10-21).** 그래서 검색 결과(제목·요약)는 **모델에 넣지 않는다**: 사건
  고르기는 코드가 하고, 모델은 언론사 사이트에서 받은 본문만 본다. 공개 JSON 의 제목도 언론사 면에서
  읽은 것이다. 키가 막히면(인증·정지·한도 오류) 그날은 언론사 RSS(`RssSource`)로 자동 전환하고 사유를
  `source_switch` 에 남긴다 — 사용자 「네이버로 진행해보고 키 정지가 되면 그때 rss로 전환하는 방법으로
  해보자」(2026-10-21). 두 출처는 `discover`·`expand` 경계를 공유한다.
- **본문 = `originallink` 의 언론사 사이트.** `link`(n.news.naver.com)는 열지 않는다 — 네이버 뉴스
  robots.txt 가 `Disallow: /` 이고 「AI 학습·RAG 목적 봇 접근 엄격 금지」를 적어 두었다.
- **발행사 허용 목록**(`_OUTLETS`). 다양성 한도는 **발행사 기준** — 한 발행사가 여러 호스트를 쓴다
  (chosun.com·biz.chosun.com). 목록 밖 호스트는 읽지 않는다.
- **robots.txt 를 런타임에 따른다** — 자체 UA 토큰으로 `*` 그룹을 따르고, 보수 정책으로 `Claude-User` 를
  명시적으로 막은 곳(한겨레)도 뺀다(표준상 의무가 아니라 우리 선택, 설계 검토 K12). 리다이렉트는 매
  이동 전에 다시 본다(K11). 403 을 우회(브라우저 흉내)하지 않는다.
- **편집 기준 시각 고정**(K04): 기준일 D 20:00 KST. 그 뒤 기사는 쓰지 않는다 — 다음 날 채워도 같다.
- 본문 하한 300자(KR 계약, `kr.news.MIN_BODY`), 한국어 통신사(연합·뉴시스·뉴스1) 출처 묶음.

**본문은 레포에 쓰지 않는다** — 묶음은 러너의 임시 폴더에만 있다.
"""

import argparse
import email.utils
import hashlib
import html as _html
import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from collections import Counter
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import contested as C  # noqa: E402

KST = timezone(timedelta(hours=9))
BODY_MIN, BODY_MAX = 300, 20000

# 호스트 접미사 → (발행사 열쇠, 이름). 2026-10-21 robots 실측에서 `*` 또는 Claude-User 로 기사 경로를
# 막은 곳(news.mt.co.kr·asiae·imbc·thebell·hani)은 넣지 않는다. 런타임 robots 검사가 한 번 더 본다.
_OUTLETS = (
    ('yna.co.kr', 'yna', '연합뉴스'), ('newsis.com', 'newsis', '뉴시스'), ('news1.kr', 'news1', '뉴스1'),
    ('mk.co.kr', 'mk', '매일경제'), ('hankyung.com', 'hankyung', '한국경제'),
    ('sedaily.com', 'sedaily', '서울경제'), ('edaily.co.kr', 'edaily', '이데일리'),
    ('heraldcorp.com', 'herald', '헤럴드경제'), ('fnnews.com', 'fnnews', '파이낸셜뉴스'),
    ('mt.co.kr', 'mt', '머니투데이'), ('etnews.com', 'etnews', '전자신문'), ('dt.co.kr', 'dt', '디지털타임스'),
    ('bizwatch.co.kr', 'bizwatch', '비즈워치'), ('newspim.com', 'newspim', '뉴스핌'),
    ('etoday.co.kr', 'etoday', '이투데이'), ('ajunews.com', 'aju', '아주경제'),
    ('businesspost.co.kr', 'bpost', '비즈니스포스트'), ('inews24.com', 'inews24', '아이뉴스24'),
    ('chosun.com', 'chosun', '조선일보'), ('joongang.co.kr', 'joongang', '중앙일보'),
    ('donga.com', 'donga', '동아일보'), ('khan.co.kr', 'khan', '경향신문'),
    ('hankookilbo.com', 'hankook', '한국일보'), ('kmib.co.kr', 'kmib', '국민일보'),
    ('segye.com', 'segye', '세계일보'), ('seoul.co.kr', 'seoul', '서울신문'),
    ('nocutnews.co.kr', 'nocut', '노컷뉴스'), ('dailian.co.kr', 'dailian', '데일리안'),
    ('ytn.co.kr', 'ytn', 'YTN'), ('news.kbs.co.kr', 'kbs', 'KBS'), ('news.sbs.co.kr', 'sbs', 'SBS'),
)
_BLOCKED_HOSTS = ('news.mt.co.kr',)          # 같은 발행사라도 이 호스트는 robots 가 막는다


def outlet_of(url):
    """(발행사 열쇠, 이름) — 허용 목록 밖이면 (None, None). 접미사는 점 경계에서만 맞춘다."""
    host = urllib.parse.urlsplit(url or '').netloc.lower().split(':')[0]
    if any(host == b for b in _BLOCKED_HOSTS):
        return None, None
    for suffix, key, name in _OUTLETS:
        if host == suffix or host.endswith('.' + suffix):
            return key, name
    return None, None


# ── 본문 ─────────────────────────────────────────────────────────────────
_DROP = re.compile(r'<(script|style|figure|figcaption|table|noscript|iframe|button)\b.*?</\1>|<!--.*?-->',
                   re.S | re.I)
_BREAK = re.compile(r'<br\s*/?>|</p\s*>|</div\s*>|</h\d\s*>|</li\s*>', re.I)
_TAG = re.compile(r'<[^>]+>')
_SP = re.compile(r'[ \t 　]+')
# 기자 서명·저작권 줄 — 요약의 재료가 아니고 원문 대조(span)에도 쓰지 않는다.
_TAIL = re.compile(r'^\s*(?:[^\s]{1,10}\s*기자\s*\(?[\w.-]+@[\w.-]+\)?|[\w.-]+@[\w.-]+\.\w+|'
                   r'.*(?:무단\s*전재|재배포\s*금지|ⓒ|©|Copyright).*)\s*$', re.I)
_LD = re.compile(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', re.S | re.I)
_ITEMPROP = re.compile(r'<(div|article|section)\b[^>]*itemprop=["\']articleBody["\'][^>]*>', re.I)
# 흔한 본문 상자 이름(파이낸셜뉴스 article-view__body·연합 story-news·이데일리 news_body, 10/21 실측).
_BOX = re.compile(r'<(div|article|section)\b[^>]*(?:id|class)=["\'][^"\']*(?:article[-_]?(?:body|content|txt|text)|'
                  r'article-view__body|news[-_]?(?:body|content|txt|text)|view[-_]?(?:con|content|text)|'
                  r'story-news|art_txt|articleText)\b[^"\']*["\'][^>]*>', re.I)
_PARA = re.compile(r'<p\b[^>]*>(.*?)</p>', re.S | re.I)
# 언론사 꼬리말(발행인·사업자 정보) — 본문 `<p>` 와 같은 꼴로 붙어 나온다(파이낸셜뉴스·뉴시스 실측).
_CORP = re.compile(r'자동화된 기술로 생성|NAVER MEDIA API|\d{4}-\d{2}-\d{2} \d{2}:\d{2}$|(?:대표이사|발행인|편집인|편집국장|인쇄인|사업자\s*등록번호|통신판매업|청소년\s*보호|'
                   r'고충처리인|등록번호|주소)\s*[:·(]|영문기사 보기')
_BOILER = ('로그인', '구독하기', '페이지를 찾을 수 없', '자바스크립트', 'javascript', '기사 공유', '많이 본 뉴스')


def _lines(fragment):
    raw = _BREAK.sub('\n', _DROP.sub(' ', fragment))
    text = _html.unescape(_TAG.sub(' ', raw))
    out = [_SP.sub(' ', ln).strip() for ln in text.split('\n')]
    return '\n'.join(ln for ln in out if ln and not _TAIL.match(ln) and not _CORP.search(ln))


def _element(html, m):
    """`m` 이 연 요소의 안쪽 — 같은 이름 태그의 짝을 세어 닫히는 곳까지."""
    tag = m.group(1).lower()
    depth, pos = 1, m.end()
    rx = re.compile(rf'<(/?){tag}\b[^>]*>', re.I)
    for t in rx.finditer(html, pos):
        depth += -1 if t.group(1) else 1
        if depth == 0:
            return html[pos:t.start()]
    return html[pos:]


def _ld_body(html):
    for m in _LD.finditer(html):
        try:
            d = json.loads(m.group(1).strip())
        except ValueError:
            continue
        stack = [d]
        while stack:
            x = stack.pop()
            if isinstance(x, list):
                stack += x
            elif isinstance(x, dict):
                typ = x.get('@type')
                typ = ' '.join(typ) if isinstance(typ, list) else str(typ or '')
                # 기사 형 객체만 — 관련 기사·목록 객체의 본문을 집지 않는다(설계 검토 K10)
                if isinstance(x.get('articleBody'), str) and 'Article' in typ:
                    return _lines(x['articleBody'])
                stack += [v for k, v in x.items() if k == '@graph']
    return ''


def _paragraphs(html):
    kept = []
    for raw in _PARA.findall(_DROP.sub(' ', html)):
        t = _lines(raw).replace('\n', ' ')
        if len(t) >= 40 and not _TAIL.match(t) and not _CORP.search(t) and not any(b in t for b in _BOILER):
            kept.append(t)
    return '\n'.join(kept)


def extract_body(html, max_chars=BODY_MAX):
    """언론사 기사면 → 본문. ① JSON-LD articleBody(기사 형) ② itemprop=articleBody 요소 ③ 흔한 본문
    상자 ④ `<p>` — 앞 단계가 있으면 뒤로 가지 않는다. 한국 언론사는 본문을 `<p>` 가 아니라 `<br>` 로 나누는 곳이 많다
    (뉴시스·이데일리·노컷, 2026-10-21 실측)."""
    if not html:
        return ''
    # 신뢰 순서대로 첫 번째로 하한을 넘는 것 — 더 길다는 이유로 앞 단계를 버리지 않는다(설계 검토 K10).
    # 본문 상자를 밝힌 면(JSON-LD·itemprop)은 그것만 믿는다 — 짧으면(속보 한 줄) `<p>` 로 넘어가 꼬리말·
    # 관련 기사를 본문으로 집지 않는다(뉴시스 10/20 실측: 속보 본문 30자 → `<p>` 1,219자가 전부 꼬리말).
    bare = _DROP.sub(' ', html)          # 스크립트·주석 속 `<div` 가 짝 세기를 흐트러뜨린다(뉴시스 실측)
    m = _ITEMPROP.search(bare)
    structured = [_ld_body(html), _lines(_element(bare, m)) if m else '']
    if any(structured):
        body = next((x for x in structured if len(x) >= BODY_MIN), '')
    else:
        body = ''
        for b in _BOX.finditer(bare):
            text = _lines(_element(bare, b))
            if len(text) >= BODY_MIN:
                body = text
                break
        if not body:
            body = _paragraphs(html)
    if len(body) < BODY_MIN:
        return ''
    return body[:max_chars]


# 「(서울=연합뉴스) 김기자 기자 =」 꼴. 지역명은 자유. 앞머리에만 있어야 전재다 — 본문 상자가 부제·
# 기자 이름을 먼저 싣는 면이 있어(연합 10/21 실측: 표기가 130자 뒤) 앞 400자까지 본다.
_WIRE = re.compile(r'[\(\[][^\)\]=]{1,12}=\s*(연합뉴스|뉴시스|뉴스1)\s*[\)\]]')


def wire_of(body):
    m = _WIRE.search((body or '')[:400])
    return m.group(1) if m else None


# ── 시각 ─────────────────────────────────────────────────────────────────
CUTOFF_HOUR = 20              # D 20:00 KST — 마감 브리프(18:00 루틴)와 그날 저녁 보도까지
DISCOVER_HOURS = 24           # 발견 창: 그날의 사건
WINDOW_HOURS = 72             # 확장·본문 창(US 와 같다)


def cutoff_of(date):
    d = datetime.fromisoformat(date)
    return d.replace(hour=CUTOFF_HOUR, tzinfo=KST)


def _rfc822(s):
    try:
        w = email.utils.parsedate_to_datetime(s or '')
    except (TypeError, ValueError):
        return None
    return w if w and w.tzinfo else None


def _clean(s):
    return _SP.sub(' ', _html.unescape(_TAG.sub('', s or ''))).strip()


# ── 검색 API (출처 경계 ①) ─────────────────────────────────────────────────
HUB = 'https://naverapihub.apigw.ntruss.com/search/v1/news'
PAGE = 100
DISCOVER_PAGES = 3            # 검색어당 — 넓은 검색어(코스피)는 100건이 10시간치다(10/21 실측)
EXPAND_PAGES = 5
QUERIES = ('코스피', '증시', '금리', '환율', '반도체', '미국 관세', '정부 대책', '외국인 매도')


class SearchError(Exception):
    """검색 API 실패 — `code` 는 공개 결과에 남겨도 되는 사유 코드(naver_auth·naver_throttled·search_failed)."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _keys():
    i, s = os.environ.get('NAVER_CLIENT_ID', ''), os.environ.get('NAVER_CLIENT_SECRET', '')
    if not i or not s:
        raise SearchError('naver_keys_missing')
    return i, s


def search_page(query, start, ctx=None, opener=urllib.request.urlopen):
    """검색 한 쪽 → (행 목록, total). 키는 헤더로만 — URL·예외 문자열에 들어가지 않는다."""
    kid, ksec = _keys()
    qs = urllib.parse.urlencode({'query': query, 'display': PAGE, 'start': start, 'sort': 'date',
                                 'format': 'json'})
    req = urllib.request.Request(f'{HUB}?{qs}', headers={'X-NCP-APIGW-API-KEY-ID': kid,
                                                         'X-NCP-APIGW-API-KEY': ksec})
    try:
        with opener(req, timeout=20, **({'context': ctx} if ctx else {})) as r:
            d = json.loads(r.read().decode('utf-8', 'replace'))
    except urllib.error.HTTPError as e:
        raise SearchError('naver_auth' if e.code in (401, 403) else
                          'naver_throttled' if e.code == 429 else 'search_failed') from None
    except (OSError, ValueError):
        raise SearchError('search_failed') from None
    rows = []
    for it in d.get('items') or []:
        if not isinstance(it, dict):
            continue
        rows.append({'title': _clean(it.get('title')), 'url': (it.get('originallink') or '').strip(),
                     'published': _rfc822(it.get('pubDate'))})
    return rows, d.get('total') if isinstance(d.get('total'), int) else 0


def window_search(query, start_at, end_at, pages, page_fn):
    """최신순 쪽넘김으로 [start_at, end_at] 안의 행 → (행, 창 시작까지 닿았는가).

    `sort=date` 는 지금부터 거꾸로 온다 — 기준 시각 뒤 기사는 건너뛰고, 창 시작보다 오래된 행이
    나오면 멈춘다. 쪽 상한에 먼저 닿으면 창을 다 못 본 것이다(설계 검토 K09)."""
    got, reached = [], False
    for n in range(pages):
        rows, total = page_fn(query, 1 + n * PAGE)
        for r in rows:
            w = r['published']
            if w is None or w > end_at:
                continue
            if w < start_at:
                reached = True
                continue
            got.append(r)
        if reached or len(rows) < PAGE or 1 + (n + 1) * PAGE > min(total, 1000):
            return got, True
    return got, False


# ── 사건 묶음 (코드가 고른다 — 검색 결과는 모델에 넣지 않는다) ──────────────
_STOP = set('''오늘 내일 지난 올해 대한 위해 통해 관련 이번 다시 가장 기자 단독 종합 속보 포토 사진 영상
            사설 칼럼 오피니언 인터뷰 이슈 분석 전망 시장 국내 정부 뉴스 그래픽 2보 3보 특징주 마감'''.split())
_MARKET = re.compile(r'코스피|코스닥|증시|금리|환율|원·?달러|외국인|반도체|관세|수출|금통위|한은|한국은행|'
                     r'기준금리|국채|유가|연준|Fed|부동산|대책|규제|공급')


def toks(title):
    t = re.sub(r'\[[^\]]{0,12}\]|\([^)]{0,6}보\)|\(종합\)', ' ', title or '')
    return {w for w in re.findall(r'[가-힣A-Za-z0-9·]{2,}', t)} - _STOP


def related(a, b):
    """같은 사건 — 공통 내용어 ≥3 이고 자카드 ≥0.25(10/21 언론사 RSS 1,222건 실측: 매체 4-7곳 묶음이
    이 기준에서 섞이지 않았다)."""
    common = a & b
    return len(common) >= 3 and len(common) / max(1, len(a | b)) >= 0.25


def cluster(rows):
    T = [toks(r['title']) for r in rows]
    parent = list(range(len(rows)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            if related(T[i], T[j]):
                parent[find(j)] = find(i)
    groups = {}
    for i, r in enumerate(rows):
        groups.setdefault(find(i), []).append(r)
    return sorted(groups.values(), key=lambda g: -score(g))


# 시황·속보·지수 레벨 제목 — 그날 지수 움직임은 브리프 본문이 이미 다룬다. 엇갈리는 주장이 나올 사건은
# 정책·전망·논쟁 쪽이다(10/20 실측: 코스피 마감 기사 40건이 1순위를 차지하고 「5500선」·「5550선」 묶음이
# 따로 생겼다). 모델 순위를 쓰지 않으므로(약관 위험 축소) 이 규칙이 고르기를 맡는다.
_WRAP = re.compile(r'마감|출발|개장|장중|시황|\[속보\]|\[포토\]|\d{4}선|코스[피닥]\s?[\d,.]+|업무보고|인사\]|부고')
_DEBATE = re.compile(r'엇갈|논란|반박|공방|갑론을박|이견|대립|반발|비판|우려|경고|vs|VS|어디까지|딜레마|쟁점')


def score(g):
    """독립 발행사 수가 가장 무겁고, 논쟁 신호가 그다음. 시황 묶음은 낮춘다(사건 고르기를 코드가 한다)."""
    pubs = {outlet_of(r['url'])[0] for r in g} - {None}
    n = max(1, len(g))
    s = 2 * len(pubs) + len(g) / 2 + 2 * sum(bool(_MARKET.search(r['title'])) for r in g) / n
    s += min(12, 4 * len({m.group(0) for r in g for m in _DEBATE.finditer(r['title'])}))
    if sum(bool(_WRAP.search(r['title'])) for r in g) / n > 0.5:
        s *= 0.25
    return s


def query_of(group):
    c = Counter()
    for r in group:
        c.update(toks(r['title']))
    return ' '.join(w for w, n in c.most_common(3) if n >= 2) or ' '.join(w for w, _ in c.most_common(2))


def member(title, group_toks):
    """확장 결과가 그 사건의 기사인가 — 묶음 제목 둘 이상과 같은 사건 규칙을 만족할 때만(K15)."""
    t = toks(title)
    return sum(related(t, g) for g in group_toks) >= min(2, len(group_toks))


def discover(page_fn, cutoff, run):
    """(묶음 후보, discovery 상태)."""
    pool, seen, complete = [], set(), True
    for q in QUERIES:
        rows, reached = window_search(q, cutoff - timedelta(hours=DISCOVER_HOURS), cutoff,
                                      DISCOVER_PAGES, page_fn)
        complete &= reached
        for r in rows:
            k = C.canonical_url(r['url'])
            if k and k not in seen and outlet_of(r['url'])[0]:
                seen.add(k)
                pool.append(r)
    groups = [g for g in cluster(pool) if len({outlet_of(r['url'])[0] for r in g}) >= 2]
    run.notes.append(f'discover:{len(pool)}')
    return groups, ('ok' if complete else 'truncated'), len(pool)


def expand(group, page_fn, cutoff):
    """후보 사건의 기사 → (기사 목록, 창을 다 봤는가). 묶음 자신도 포함."""
    gt = [toks(r['title']) for r in group]
    q = query_of(group)
    rows, reached = window_search(q, cutoff - timedelta(hours=WINDOW_HOURS), cutoff, EXPAND_PAGES, page_fn)
    out, seen = [], set()
    for r in list(group) + [r for r in rows if member(r['title'], gt)]:
        k = C.canonical_url(r['url'])
        if k and k not in seen and outlet_of(r['url'])[0]:
            seen.add(k)
            out.append(r)
    return q, out, reached


# ── 언론사 면 받기 (robots·리다이렉트) ─────────────────────────────────────
UA_TOKEN = 'fdo2a-contested'
UA = f'Mozilla/5.0 (compatible; {UA_TOKEN}/1.0; +https://fdo2a.github.io/)'


class Blocked(Exception):
    """허용 목록 밖·robots 금지 — 영구. 다시 해도 같다."""


class Transient(Exception):
    """네트워크·5xx·robots 조회 실패 — 다음 tick 에 다시 볼 만하다(K08)."""


def _naver(host):
    return host == 'naver.com' or host.endswith('.naver.com')


class Robots:
    """호스트별 robots.txt — tick 당 한 번. 404·410 은 「제한 없음」, 그 밖의 실패는 일시 실패."""

    def __init__(self, fetch_text):
        self.fetch_text = fetch_text
        self.cache = {}

    def check(self, url):
        p = urllib.parse.urlsplit(url)
        host = p.netloc.lower()
        if p.scheme not in ('http', 'https') or _naver(host.split(':')[0]) or not outlet_of(url)[0]:
            raise Blocked('outlet')
        if host not in self.cache:
            try:
                code, text = self.fetch_text(f'{p.scheme}://{host}/robots.txt')
            except Exception:
                self.cache[host] = 'unavailable'
            else:
                if code in (404, 410):
                    self.cache[host] = None
                elif code == 200:
                    rp = urllib.robotparser.RobotFileParser()
                    rp.parse(text.splitlines())
                    self.cache[host] = rp
                else:
                    self.cache[host] = 'unavailable'
        rp = self.cache[host]
        if rp == 'unavailable':
            raise Transient('robots_unavailable')
        if rp is not None and not (rp.can_fetch(UA_TOKEN, url) and rp.can_fetch('Claude-User', url)):
            raise Blocked('robots')


def _decode(raw, ctype):
    m = re.search(r'charset=([\w-]+)', ctype or '', re.I) or \
        re.search(rb'<meta[^>]+charset=["\']?([\w-]+)', raw[:4000], re.I)
    cs = m.group(1) if m else 'utf-8'
    cs = cs.decode() if isinstance(cs, bytes) else cs
    if cs.lower() in ('euc-kr', 'ks_c_5601-1987', 'x-windows-949'):
        cs = 'cp949'
    try:
        return raw.decode(cs, 'replace')
    except LookupError:
        return raw.decode('utf-8', 'replace')


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def http_get(url, ctx=None, timeout=20):
    """(코드, 헤더 Location, 본문 글자) — 리다이렉트를 따라가지 않는다(따라갈지는 호출자가 정한다)."""
    opener = urllib.request.build_opener(_NoRedirect(), urllib.request.HTTPSHandler(context=ctx))
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept-Language': 'ko-KR,ko;q=0.9'})
    try:
        with opener.open(req, timeout=timeout) as r:
            return r.status, None, _decode(r.read(3_000_000), r.headers.get('Content-Type'))
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get('Location'), ''


def fetch_page(url, robots, get=http_get, hops=5):
    """허용·robots 를 매 이동 전에 확인하며 받는다 → (최종 URL, HTML)."""
    for _ in range(hops):
        robots.check(url)
        code, loc, text = get(url)
        if code in (301, 302, 303, 307, 308) and loc:
            url = urllib.parse.urljoin(url, loc)
            continue
        if code == 200:
            return url, text
        if code in (401, 402, 403, 404, 410, 451):
            raise Blocked(f'http_{code}')
        raise Transient(f'http_{code}')
    raise Blocked('redirects')


# ── 본문 받기 ────────────────────────────────────────────────────────────
MAX_BODIES, MAX_TRIES, PER_PUBLISHER = 6, 12, 2
_GARBAGE = ('로그인이 필요', '구독자 전용', '페이지를 찾을 수 없', '존재하지 않는 기사', '삭제된 기사',
            '자바스크립트를 활성화', 'enable javascript', 'access denied')
_OG_TITLE = re.compile(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)', re.I)
_TITLE = re.compile(r'<title[^>]*>(.*?)</title>', re.S | re.I)
_LD_DATE = re.compile(r'"datePublished"\s*:\s*"([^"]+)"')
_META_DATE = re.compile(r'<meta[^>]+(?:property|name)=["\'](?:article:published_time|pubdate|'
                        r'og:regDate|dable:published_time)["\'][^>]+content=["\']([^"\']+)', re.I)


def page_title(html):
    """og:title 이 너무 짧으면(아이뉴스24 「기관」 — 10/20 실측) `<title>` 에서 사이트 이름 꼬리를 떼어 쓴다."""
    og = _OG_TITLE.search(html or '')
    og = _clean(og.group(1)) if og else ''
    if len(og) >= 8:
        return og[:300]
    t = _TITLE.search(html or '')
    t = re.split(r'\s+[|\-–—:]\s+(?=[^|\-–—:]{1,20}$)', _clean(t.group(1)) if t else '')[0]
    return (t if len(t) > len(og) else og)[:300]


def page_published(html):
    for rx in (_LD_DATE, _META_DATE):
        for m in rx.finditer(html or ''):
            s = m.group(1).strip()
            if re.fullmatch(r'\d{14}', s):
                s = f'{s[:4]}-{s[4:6]}-{s[6:8]}T{s[8:10]}:{s[10:12]}:{s[12:]}+09:00'
            try:
                w = datetime.fromisoformat(s.replace('Z', '+00:00'))
            except ValueError:
                continue
            return w if w.tzinfo else w.replace(tzinfo=KST)
    return None


def admit(html, search_title):
    """(본문, 사유). 길이만 보지 않는다 — 쓰레기 문구, 제목 일치."""
    body = extract_body(html)
    if not body:
        return None, 'short'
    if any(g in body[:600].lower() for g in _GARBAGE):
        return None, 'garbage'
    a = toks(search_title)
    b = toks(page_title(html) + ' ' + body[:400])
    if len(a) >= 2 and len(a & b) < 2:
        return None, 'title_mismatch'
    return body, 'ok'


def fetch_bodies(rows, robots, cutoff, run, get=http_get, status=None):
    """`status` 에 시도마다 사유를 쌓는다. 일시 실패는 'fail'·'robots_unavailable' — 이것이 남으면
    그날 결론(none)을 동결하지 않는다(K08)."""
    status = status if status is not None else []
    got, per_pub, tried, seen = [], Counter(), 0, set()
    for i, r in enumerate(rows):
        if len(got) >= MAX_BODIES or tried >= MAX_TRIES:
            break
        if run.left() < 120:
            # 시간이 모자라 남은 기사를 못 봤다 — 「출처 부족」과 구별해 그날 결론을 동결하지 않는다(구현 검토 #6)
            if any(outlet_of(x['url'])[0] and per_pub[outlet_of(x['url'])[0]] < PER_PUBLISHER for x in rows[i:]):
                status.append('time_cap')
            break
        key, name = outlet_of(r['url'])
        if not key or per_pub[key] >= PER_PUBLISHER:
            continue
        tried += 1
        try:
            final, html = fetch_page(r['url'], robots, get=lambda u: get(u))
        except Blocked as e:
            status.append('blocked')
            run.hosts[key] = f'blocked:{e}'
            continue
        except Transient as e:
            status.append('robots_unavailable' if str(e) == 'robots_unavailable' else 'fail')
            run.hosts[key] = f'fail:{e}'
            continue
        except (OSError, socket.timeout) as e:
            status.append('fail')
            run.hosts[key] = f'fail:{type(e).__name__}'
            continue
        fkey, fname = outlet_of(final)
        cid = C.canonical_url(final)
        if not fkey or not cid or cid in seen or per_pub[fkey] >= PER_PUBLISHER:
            # 리다이렉트 뒤 발행사로 한도를 다시 본다 — 이동 전 발행사로만 세면 우회된다(구현 검토 #9)
            status.append('blocked')
            continue
        body, why = admit(html, r['title'])
        run.hosts[fkey] = why
        status.append(why)
        if not body:
            continue
        when = page_published(html) or r.get('published')
        if not when or not (cutoff - timedelta(hours=WINDOW_HOURS) <= when <= cutoff):
            status[-1] = 'out_of_window'
            continue
        seen.add(cid)
        per_pub[fkey] += 1
        got.append({'article_id': C.article_id(final), 'url': cid,
                    'title': page_title(html) or '(제목 없음)', 'source': fname, 'publisher': fkey,
                    'published_at': when.isoformat(timespec='seconds'),
                    'truncated': len(body) >= BODY_MAX, 'body': body})
    return origin_groups(got)


def _shingles(text, n=5):
    w = re.findall(r'\w+', (text or '').lower())
    return {' '.join(w[i:i + n]) for i in range(max(0, len(w) - n + 1))}


def origin_groups(arts):
    """출처 = 통신사 전재 > 발행사 > 본문 지문(5-gram 자카드 0.6)."""
    sh = {a['article_id']: _shingles(a['body']) for a in arts}
    for a in arts:
        wire = wire_of(a['body'])
        a['wire'] = wire or ''
        a['origin_group'] = f'wire:{wire}' if wire else f'pub:{a["publisher"]}'
    for i, a in enumerate(arts):
        for b in arts[:i]:
            x, y = sh[a['article_id']], sh[b['article_id']]
            if x and y and len(x & y) / len(x | y) >= 0.6:
                a['origin_group'] = b['origin_group']
                break
    return arts


# ── 묶음 ─────────────────────────────────────────────────────────────────
CANDIDATES = 3
KR_FILES = ('kr_market_data.json', 'kr_econ.json', 'kr_flows.json', 'kr_session.json')


class Deadline(BaseException):
    pass


class Run:
    def __init__(self, seconds, now=None):
        self.now = now or datetime.now(timezone.utc)
        self.t0 = time.monotonic()
        self.limit = seconds
        self.notes = []
        self.hosts = {}

    def left(self):
        return self.limit - (time.monotonic() - self.t0)


def _sha(path):
    with open(path, 'rb') as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def snapshot(datadir, commit=None):
    main = os.path.join(datadir, KR_FILES[0])
    extra = {f: _sha(os.path.join(datadir, f)) for f in KR_FILES[1:]
             if os.path.exists(os.path.join(datadir, f))}
    return {'path': 'kr/data/kr_market_data.json', 'commit': commit, 'sha256': _sha(main), 'extra': extra}


def load_files(datadir):
    out = {}
    for f in KR_FILES:
        try:
            with open(os.path.join(datadir, f), encoding='utf-8') as fh:
                out[f] = json.load(fh)
        except (OSError, ValueError):
            out[f] = None
    return out


# ── 출처 어댑터 (경계: discover·expand) ────────────────────────────────────
class NaverSource:
    """NAVER API HUB 뉴스 검색 — 1순위. 약관 위험은 모듈 머리 참조."""
    name = 'naver'

    def __init__(self, page_fn):
        self.page_fn = page_fn

    def discover(self, cutoff, run):
        return discover(self.page_fn, cutoff, run)

    def expand(self, group, cutoff):
        return expand(group, self.page_fn, cutoff)


# 언론사 자체 RSS — 키가 막힌 날의 대체 경로(사용자 2026-10-21 「네이버로 진행해보고 키 정지가 되면 그때 rss로
# 전환하는 방법으로 해보자」). 10/21 실측 18곳 1,222건, 매체 4-7곳 묶음 10개 이상. 피드는 최근 N건만 싣는다 —
# 기준 시각 창을 다 덮지 못한 피드가 있으면 `truncated` 로 남겨 그날 결론을 동결하지 않는다.
RSS_FEEDS = (
    'https://www.yna.co.kr/rss/economy.xml', 'https://www.yna.co.kr/rss/market.xml',
    'https://www.mk.co.kr/rss/50200011/', 'https://www.hankyung.com/feed/finance',
    'https://www.newsis.com/RSS/economy.xml', 'http://rss.edaily.co.kr/stock_news.xml',
    'https://www.sedaily.com/rss/finance', 'https://www.fnnews.com/rss/r20/fn_realnews_stock.xml',
    'https://www.khan.co.kr/rss/rssdata/economy_news.xml', 'https://rss.donga.com/economy.xml',
    'https://www.chosun.com/arc/outboundfeeds/rss/category/economy/?outputType=xml',
    'https://rss.etnews.com/Section901.xml', 'https://biz.heraldcorp.com/rss/google/finance',
    'https://www.kmib.co.kr/rss/data/kmibEcoRss.xml', 'https://www.seoul.co.kr/xml/rss/rss_economy.xml',
    'https://www.segye.com/Articles/RSSList/segye_economy.xml', 'https://rss.nocutnews.co.kr/category/economy.xml',
    'https://www.dailian.co.kr/rss/economy',
)
_ITEM = re.compile(r'<item[\s>].*?</item>', re.S | re.I)
_CDATA = re.compile(r'<!\[CDATA\[(.*?)\]\]>', re.S)
_MON = {m: i for i, m in enumerate('jan feb mar apr may jun jul aug sep oct nov dec'.split(), 1)}


def _field(item, tag):
    m = re.search(rf'<{tag}\b[^>]*>(.*?)</{tag}>', item, re.S | re.I)
    if not m:
        return ''
    v = m.group(1)
    c = _CDATA.search(v)
    return (c.group(1) if c else v).strip()


def rss_time(s):
    """피드마다 날짜 꼴이 다르다(10/21 실측: RFC 822, 「Tue,20 Oct」, 「2026-10-20 17:33:16」, 「Tue, 20 10 2026」)."""
    s = (s or '').strip()
    if not s:
        return None
    w = _rfc822(s) or _rfc822(re.sub(r'^(\w{3}),(\S)', r'\1, \2', s))
    if w:
        return w
    m = re.match(r'(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?(.*)$', s)
    if m:
        y, mo, d, h, mi, sec, tz = m.groups()
        try:
            base = datetime(int(y), int(mo), int(d), int(h), int(mi), int(sec or 0))
            tail = datetime.fromisoformat(f'2000-01-01T00:00:00{tz.strip()}') if tz.strip() else None
        except ValueError:
            return None
        return base.replace(tzinfo=tail.tzinfo if tail and tail.tzinfo else KST)
    m = re.match(r'(?:\w{3},\s*)?(\d{1,2})\s+(\d{1,2}|\w{3})\s+(\d{4})\s+(\d{2}):(\d{2})(?::(\d{2}))?', s)
    if m:
        d, mo, y, h, mi, sec = m.groups()
        mo = int(mo) if mo.isdigit() else _MON.get(mo.lower())
        try:
            return datetime(int(y), mo, int(d), int(h), int(mi), int(sec or 0), tzinfo=KST)
        except (TypeError, ValueError):
            return None
    return None


def parse_rss(xml):
    rows = []
    for it in _ITEM.findall(xml or ''):
        url = _field(it, 'link') or _field(it, 'guid')
        when = rss_time(_field(it, 'pubDate') or _field(it, 'dc:date'))
        title = _clean(_field(it, 'title'))
        if url and title:
            rows.append({'title': title, 'url': _html.unescape(url).strip(), 'published': when})
    return rows


class RssSource:
    name = 'rss'

    def __init__(self, robots, get=http_get, feeds=RSS_FEEDS):
        self.robots, self.get, self.feeds = robots, get, feeds
        self.pool, self.covered, self.covered_window = None, True, True

    def _load(self, cutoff, run):
        if self.pool is not None:
            return
        rows, ok, seen = [], 0, set()
        start = cutoff - timedelta(hours=WINDOW_HOURS)
        for f in self.feeds:
            try:
                _, xml = fetch_page(f, self.robots, get=self.get)
            except (Blocked, Transient, OSError) as e:
                run.notes.append(f'rss:{outlet_of(f)[0]}:{type(e).__name__}')
                self.covered = self.covered_window = False
                continue
            got = [r for r in parse_rss(xml) if r['published']]
            if not got:
                self.covered = self.covered_window = False
                continue
            ok += 1
            oldest = min(r['published'] for r in got)
            # 발견(24시간)과 확장(72시간)은 따로 센다 — 앞의 것만 덮어도 반론 기사는 이미 밀려났을 수 있다(#5)
            if oldest > cutoff - timedelta(hours=DISCOVER_HOURS):
                self.covered = False               # 이 피드는 발견 창 앞쪽을 이미 밀어냈다
            if oldest > start:
                self.covered_window = False
            for r in got:
                k = C.canonical_url(r['url'])
                if k and k not in seen and start <= r['published'] <= cutoff and outlet_of(r['url'])[0]:
                    seen.add(k)
                    rows.append(r)
        if ok < len(self.feeds) / 2:
            raise SearchError('rss_failed')
        self.pool = rows

    def discover(self, cutoff, run):
        self._load(cutoff, run)
        fresh = [r for r in self.pool if r['published'] >= cutoff - timedelta(hours=DISCOVER_HOURS)]
        groups = [g for g in cluster(fresh) if len({outlet_of(r['url'])[0] for r in g}) >= 2]
        run.notes.append(f'discover_rss:{len(fresh)}')
        return groups, ('ok' if self.covered else 'truncated'), len(fresh)

    def expand(self, group, cutoff):
        gt = [toks(r['title']) for r in group]
        out, seen = [], set()
        for r in list(group) + [r for r in self.pool if member(r['title'], gt)]:
            k = C.canonical_url(r['url'])
            if k and k not in seen:
                seen.add(k)
                out.append(r)
        return query_of(group), out, self.covered_window


def build(date, datadir, run, source, get=http_get, robots=None, commit=None):
    files = load_files(datadir)
    md = files['kr_market_data.json'] or {}
    if md.get('report_date') != date or not md.get('complete'):
        return {'status': 'error', 'reason': 'market_data_not_ready'}
    cutoff = cutoff_of(date)
    if run.now < cutoff:
        # 기준 시각 전에 그날을 확정하면 18-20시 보도가 빠진 채 동결된다(구현 검토 #2) — 러너도 기다린다
        return {'status': 'error', 'reason': 'before_cutoff'}
    robots = robots or Robots(lambda u: http_get(u)[::2])
    groups, disc, n_pool = source.discover(cutoff, run)
    base = {'status': 'ok', 'source': source.name, 'discovery': disc, 'harvest': n_pool,
            'cutoff_at': cutoff.isoformat(), 'market_snapshot': snapshot(datadir, commit),
            'registry': C.market_registry_kr(files), 'candidates': []}
    if not groups:
        if disc != 'ok':
            return dict(base, status='error', reason='search_truncated')
        return dict(base, status='none', reason='no_candidate')
    for i, g in enumerate(groups[:CANDIDATES]):
        q, rows, reached = source.expand(g, cutoff)
        status = []
        arts = fetch_bodies(rows, robots, cutoff, run, get=get, status=status)
        seen_pubs = sorted({outlet_of(r['url'])[1] for r in rows})
        base['candidates'].append({'cand_id': f'k{i + 1}', 'score': round(score(g), 2), 'query': q,
                                   'titles': [], 'outlets_seen': seen_pubs, 'articles': arts,
                                   'fetch': dict(Counter(status)), 'expanded': reached})
        if not reached:
            base['discovery'] = 'truncated'
        if len({a['origin_group'] for a in arts}) >= C.MIN_ORIGINS:
            break
    return base


# 키 정지·인증 실패·한도 초과 — 그날은 RSS 로 바꾼다. 네트워크·5xx(`search_failed`)는 일시 실패라 바꾸지 않는다.
SWITCH = ('naver_auth', 'naver_throttled', 'naver_keys_missing')
NAVER_STATE = os.path.expanduser('~/Library/Caches/fdo2a-contested-naver.json')


def naver_down(today):
    """오늘(KST) 이미 막혔다고 적어 둔 사유 — 없으면 None."""
    try:
        with open(NAVER_STATE, encoding='utf-8') as fh:
            st = json.load(fh)
        return st.get(today) if isinstance(st, dict) and isinstance(st.get(today), str) else None
    except (OSError, ValueError):
        return None


def mark_naver_down(today, code):
    """읽기·고치기·교체를 잠금 하나로 — 러너와 수집기 CLI 가 같이 써도 서로 덮지 않는다(구현 검토 #7)."""
    if os.environ.get('CONTESTED_DRY'):
        return                                  # 시험 운행은 상태를 남기지 않는다
    import fcntl
    import tempfile
    d = os.path.dirname(NAVER_STATE) or '.'
    os.makedirs(d, exist_ok=True)
    with open(NAVER_STATE + '.lock', 'w') as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        try:
            with open(NAVER_STATE, encoding='utf-8') as fh:
                st = json.load(fh)
            st = st if isinstance(st, dict) else {}
        except (OSError, ValueError):
            st = {}
        st[today] = code
        fd, tmp = tempfile.mkstemp(dir=d, suffix='.tmp')
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            json.dump(dict(sorted(st.items())[-14:]), fh)
        os.replace(tmp, NAVER_STATE)


def collect(date, datadir, deadline=900, now=None, page_fn=None, get=http_get, commit=None, feeds=RSS_FEEDS):
    """묶음 dict(본문 포함). 어떤 경우에도 status 를 가진 dict 를 돌려준다.

    출처: 네이버가 1순위. 그날 이미 막혔거나, 사전 점검·수집 중 인증·정지·한도 오류가 나면 언론사 RSS 로
    바꾸고 사유를 `source_switch` 에 남긴다(사용자 2026-10-21)."""
    now = now or datetime.now(timezone.utc)
    run = Run(deadline, now)
    today = now.astimezone(KST).date().isoformat()
    if page_fn is None or get is http_get:
        # python.org 판 Python 은 기본 CA 가 없다 — 검색과 언론사 면 모두 certifi 문맥으로(10/21 실측)
        from fetch_news import _context
        ctx = _context()
        if page_fn is None:
            page_fn = lambda q, s: search_page(q, s, ctx)  # noqa: E731
        if get is http_get:
            get = lambda u: http_get(u, ctx)  # noqa: E731
    old = None
    if hasattr(signal, 'SIGALRM'):
        def _alarm(*_):
            raise Deadline()
        old = signal.signal(signal.SIGALRM, _alarm)
        signal.alarm(max(60, deadline))
    switch = naver_down(today)
    try:
        robots = Robots(lambda u: (lambda c, _l, t: (c, t))(*get(u)))
        rss = RssSource(robots, get=get, feeds=feeds)
        if switch is None:
            ok, code = preflight(page_fn=page_fn)
            if not ok and code in SWITCH:
                switch = code
                mark_naver_down(today, code)
        try:
            b = build(date, datadir, run, rss if switch else NaverSource(page_fn), get=get, robots=robots,
                      commit=commit)
        except SearchError as e:
            if switch or e.code not in SWITCH:
                raise
            switch = e.code                      # 수집 도중 막혔다 — 남은 시간에 RSS 로 한 번 더
            mark_naver_down(today, e.code)
            run.notes.append(f'switch:{e.code}')
            b = build(date, datadir, run, rss, get=get, robots=robots, commit=commit)
    except Deadline:
        b = {'status': 'error', 'reason': 'deadline'}
    except SearchError as e:
        b = {'status': 'error', 'reason': e.code}
    except Exception as e:                       # 원인 종류만 — 본문·URL·키를 로그에 남기지 않는다
        b = {'status': 'error', 'reason': f'collect_{type(e).__name__}'}
    finally:
        if hasattr(signal, 'SIGALRM'):
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old or signal.SIG_DFL)
    b.update(report_date=date, collected_at=now.isoformat(timespec='seconds'),
             notes=run.notes[:40], hosts=run.hosts, source_switch=switch or '')
    b.setdefault('source', 'rss' if switch else 'naver')
    b.setdefault('discovery', 'failed')
    return b


def preflight(ctx=None, page_fn=None):
    """키가 있고 통하는가 → (통과, 사유 코드). 막히면 그날은 RSS 로 간다."""
    try:
        (page_fn or (lambda q, s: search_page(q, s, ctx)))('코스피', 1)
    except SearchError as e:
        return False, e.code
    return True, ''


def main(argv=None):
    """디버깅용 — 묶음을 로컬 파일로(레포 밖에 둔다. 본문이 들어 있다)."""
    ap = argparse.ArgumentParser()
    ap.add_argument('--date', required=True, type=C.iso_date)
    ap.add_argument('--datadir', default='kr/data')
    ap.add_argument('--out', required=True)
    ap.add_argument('--deadline', type=int, default=900)
    a = ap.parse_args(argv)
    b = collect(a.date, a.datadir, a.deadline)
    with open(a.out, 'w', encoding='utf-8') as fh:
        json.dump(b, fh, ensure_ascii=False)
    n = [len(c['articles']) for c in b.get('candidates', [])]
    print(f'bundle {b["status"]} {b.get("reason", "")} candidates={n} discovery={b.get("discovery")}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
