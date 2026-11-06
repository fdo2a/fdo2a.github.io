"""Telegram channels as a source for the US and KR daily briefs (2026-11-06 사용자 지시).

Three kinds of item, decided by code:
  view    — a sell-side post with its byline header; quoted as that firm and analyst
  report  — a post that links an original article; the ARTICLE is fetched and summarised,
            and it is attributed to that outlet (「로이터에 따르면」)
  opinion — everything else; written as 「…라는 의견도 나왔다」, naming the outlet the post
            itself credits (「*연합인포맥스*」, 「- 블룸버그」) when there is one
Channel names, 「텔레그램」 and t.me never reach a post (check_telegram.py).
Design: docs/superpowers/specs/2026-11-06-telegram-source.md
"""
import re

from .tg_links import classify, origin_status
from .tg_market import in_market, market_of

FIRM_KIWOOM = '키움증권'
FIRM_HANWHA = '한화투자증권'

CHANNELS = {
    'hedgecat0301':        {'group': 'firm', 'market': 'both', 'firm': FIRM_KIWOOM},
    'kwusa':               {'group': 'firm', 'market': 'us', 'firm': FIRM_KIWOOM},
    'lim_econ':            {'group': 'firm', 'market': 'both', 'firm': FIRM_HANWHA},
    'd_ticker':            {'group': 'individual', 'market': 'both'},
    # posts in bulk, often weeks-old articles (11/06 실측: 하루 1,000건+, 링크 기사 10/13-10/25)
    'aethersemiconductor': {'group': 'individual', 'market': 'both', 'max_pages': 15},
    'FastStockNews':       {'group': 'relay', 'market': 'kr'},
    'FastStockNewsUSA':    {'group': 'relay', 'market': 'us'},
    'insidertracking':     {'group': 'relay', 'market': 'us'},
}
# Words that would expose the source channel on a page (gate list). Display names included.
CHANNEL_WORDS = tuple(CHANNELS) + ('딘스티커', "Dean's Ticker", '급등일보', '에테르의', '미국 주식 인사이더',
                                    'US Stocks Insider', '키움증권 미국주식 톡톡')

MAX_VIEWS, MAX_OPINIONS = 6, 12          # collected per market per run
MAX_PER_CHANNEL = 3                       # non-view items per channel per run
# Paywalled: a fetch returns the subscription page, not the article (11/06 실측 Bloomberg·FT).
# Never summarised from the page — the post becomes an opinion crediting that outlet.
PAYWALLED = ('bloomberg.com', 'ft.com', 'wsj.com', 'economist.com', 'theinformation.com',
             'nikkei.com', 'barrons.com', 'nytimes.com', 'washingtonpost.com')
_URL_DATE = (re.compile(r'/(20\d{2})[-/](\d{2})[-/](\d{2})(?:/|-|$)'), re.compile(r'/(20\d{2})(\d{2})(\d{2})\d{4,}'))


def paywalled(url):
    key = classify(url)[1] or ''
    host = key[len('url:https://'):].split('/', 1)[0] if key.startswith('url:') else ''
    return any(host == d or host.endswith('.' + d) for d in PAYWALLED)


def url_date(url):
    """YYYY-MM-DD embedded in an article URL, or None."""
    for rx in _URL_DATE:
        m = rx.search(url or '')
        if m:
            return f'{m.group(1)}-{m.group(2)}-{m.group(3)}'
    return None
POST_MAX_VIEWS, POST_MAX_OPINIONS = 3, 3  # used per brief (gate)

# ── views ────────────────────────────────────────────────────────────────
_BRACKET = re.compile(r'^\s*\[([^\]\n]{2,60})\]')
_NAME = re.compile(r'^[가-힣]{2,4}$')


def _byline(text):
    m = _BRACKET.match(text or '')
    return m.group(1).strip() if m else None


def view_of(channel, post):
    """-> (firm, analyst) for a sell-side view, else None. Forwarded posts are never views."""
    cfg = CHANNELS.get(channel, {})
    if cfg.get('group') != 'firm' or post.get('forwarded_from'):
        return None
    text = post.get('text') or ''
    if channel == 'hedgecat0301':
        b = _byline(text)
        return (FIRM_KIWOOM, '한지영') if b and '키움 한지영' in b else None
    if channel == 'kwusa':
        b = _byline(text)
        if not b or not b.startswith('키움'):
            return None
        last = re.split(r'[\s/]+', b)[-1]
        if _NAME.match(last) and not last.endswith(('팀', '센터', '리서치')):
            return FIRM_KIWOOM, last
        team = re.sub(r'^키움(?:증권)?[\s/]*', '', b).strip()
        return (FIRM_KIWOOM, team) if team else None
    if channel == 'lim_econ':
        # her own notes; the 「개장전 꼭 알아야 할 5가지」 digest is a Bloomberg summary
        # her own note only: no digest header, no linked article, no outlet credited in the text
        if text.lstrip().startswith('<') or 'Bloomberg>' in text[:80] or len(text) < 200:
            return None
        # any sign of someone else's material comes first, even with her own report attached
        if (credited_source(text) or any(k in text for k in OUTLETS)
                or re.search(r'에 따르면|에 의하면|보도|인용|출처|via\b|source:', text, re.I)):
            return None
        doc = post.get('doc_title') or ''
        if '한화' in doc or '임혜윤' in doc:          # her own report attached (links allowed)
            return FIRM_HANWHA, '임혜윤'
        if post.get('links'):
            return None
        return FIRM_HANWHA, '임혜윤'
    return None


# ── credited sources (no link) ───────────────────────────────────────────
OUTLETS = {
    '연합인포맥스': '연합인포맥스', '연합뉴스': '연합뉴스', '블룸버그': '블룸버그', 'Bloomberg': '블룸버그',
    '로이터': '로이터', 'Reuters': '로이터', 'WSJ': '월스트리트저널', '월스트리트저널': '월스트리트저널',
    'FT': '파이낸셜타임스', '파이낸셜타임스': '파이낸셜타임스', 'CNBC': 'CNBC', '진시데이터': '진시데이터',
    '니케이': '니혼게이자이', '닛케이': '니혼게이자이', 'The Information': '디인포메이션',
    '디인포메이션': '디인포메이션', 'CNN': 'CNN', 'AP': 'AP통신', '뉴욕타임스': '뉴욕타임스',
}
_CREDIT_PATTERNS = (
    re.compile(r'\*([^*\n]{2,15})\*'),                       # *연합인포맥스*
    re.compile(r'[-–—]\s*([A-Za-z가-힣 ]{2,20})\s*$'),         # … - 블룸버그
    re.compile(r'_\d{1,2}/\d{1,2}\s+([A-Za-z]+)>'),           # <…_11/6 Bloomberg>
    re.compile(r'\d{1,2}월\s*\d{1,2}일,\s*([가-힣A-Za-z]{2,12})\s*[–-]'),  # 11월 6일, 진시데이터 –
)


def credited_source(text):
    t = (text or '').strip()
    for pat in _CREDIT_PATTERNS:
        for m in pat.finditer(t):
            name = m.group(1).strip()
            if name in OUTLETS:
                return OUTLETS[name]
    return None


# ── outlets for linked originals ─────────────────────────────────────────
DOMAIN_OUTLETS = {
    'reuters.com': '로이터', 'bloomberg.com': '블룸버그', 'ft.com': '파이낸셜타임스', 'wsj.com': '월스트리트저널',
    'cnbc.com': 'CNBC', 'nikkei.com': '니혼게이자이', 'asia.nikkei.com': '니혼게이자이',
    'economist.com': '이코노미스트', 'theinformation.com': '디인포메이션', 'nytimes.com': '뉴욕타임스',
    'apnews.com': 'AP통신', 'axios.com': '악시오스', 'barrons.com': '배런스', 'marketwatch.com': '마켓워치',
    'sedaily.com': '서울경제', 'edaily.co.kr': '이데일리', 'etoday.co.kr': '이투데이', 'newspim.com': '뉴스핌',
    'hankyung.com': '한국경제', 'mk.co.kr': '매일경제', 'yna.co.kr': '연합뉴스', 'biz.chosun.com': '조선비즈',
    'news.einfomax.co.kr': '연합인포맥스', 'mt.co.kr': '머니투데이', 'fnnews.com': '파이낸셜뉴스',
    'asiae.co.kr': '아시아경제', 'heraldcorp.com': '헤럴드경제', 'thelec.kr': '디일렉', 'zdnet.co.kr': '지디넷코리아',
    'dart.fss.or.kr': '금융감독원 전자공시', 'kind.krx.co.kr': '한국거래소 공시',
}
NAVER_AUTHOR = re.compile(r'<meta property="og:article:author" content="([^"|]+?)\s*(?:\|[^"]*)?"')


def outlet_for(url, page=None):
    """Outlet name for a linked original, or None. Naver articles take the press from the page."""
    kind, key = classify(url)
    if kind == 'naver_article':
        m = NAVER_AUTHOR.search(page or '')
        return m.group(1).strip() if m else None
    if not key or not key.startswith('url:'):
        return None
    host = key[len('url:https://'):].split('/', 1)[0]
    for dom, name in DOMAIN_OUTLETS.items():
        if host == dom or host.endswith('.' + dom):
            return name
    return None


def origin_link(post):
    """First link that is an original (news, wire, filing), else None."""
    for u in post.get('links', []):
        kind, key = classify(u)
        if key and kind in ('naver_article', 'dart', 'reuters', 'bloomberg', 'ft', 'wsj', 'news'):
            return u
    return None


# ── selection ────────────────────────────────────────────────────────────
MARKET_WORDS = re.compile(r'코스피|코스닥|나스닥|S&P|다우|연준|금리|국채|환율|달러|유가|반도체|실적|가이던스|'
                          r'수출|관세|AI|엔비디아|삼성전자|하이닉스|외국인|매도|매수|급등|급락|상승|하락')


def chatter(post):
    text = post.get('text') or ''
    return len(text) < 40 and not post.get('links')


def classify_post(channel, post, market):
    """-> item dict without summary, or None when it does not belong to `market`."""
    cfg = CHANNELS[channel]
    if chatter(post):
        return None
    pm = market_of(post.get('text'), cfg['market'])
    if pm == 'unknown' or not in_market(pm, market):
        return None
    base = {'id': f'{channel}/{post["id"]}', 'channel': channel, 'group': cfg['group'],
            'dt_utc': post['dt_utc'], 'url': post['url']}
    v = view_of(channel, post)
    if v:
        return dict(base, kind='view', firm=v[0], analyst=v[1], source=None)
    link = origin_link(post)
    if link and paywalled(link):
        name = outlet_for(link)
        return dict(base, kind='opinion', firm=None, analyst=None,
                    source={'name': name, 'url': None, 'basis': 'paywalled_link'} if name else None,
                    article_date=url_date(link))
    if link:
        return dict(base, kind='report', firm=None, analyst=None,
                    source={'name': outlet_for(link), 'url': link, 'basis': 'link'},
                    article_date=url_date(link))
    credit = credited_source(post.get('text'))
    return dict(base, kind='opinion', firm=None, analyst=None,
                source={'name': credit, 'url': None, 'basis': 'credit'} if credit else None)


def _score(item, post, shared):
    s = 0
    if item.get('source') and item['source'].get('name'):
        s += 2
    if shared:
        s += 2
    s += min(4, len(MARKET_WORDS.findall(post.get('text') or '')))
    return s


def select(candidates):
    """candidates: [(item, post)]. Dedupe by original link key (keep the earliest), then cap."""
    by_key, out = {}, []
    for item, post in sorted(candidates, key=lambda c: c[0]['dt_utc']):
        key = None
        if item['kind'] == 'report':
            key = classify(item['source']['url'])[1]
        if key and key in by_key:
            by_key[key][2] = True
            continue
        row = [item, post, False]
        if key:
            by_key[key] = row
        out.append(row)
    views = [r for r in out if r[0]['kind'] == 'view']
    others = [r for r in out if r[0]['kind'] != 'view']
    views = sorted(views, key=lambda r: r[0]['dt_utc'], reverse=True)[:MAX_VIEWS]
    ranked, per = [], {}
    for r in sorted(others, key=lambda r: (_score(r[0], r[1], r[2]), r[0]['dt_utc']), reverse=True):
        ch = r[0]['channel']
        if per.get(ch, 0) >= MAX_PER_CHANNEL:
            continue
        per[ch] = per.get(ch, 0) + 1
        ranked.append(r)
    others = ranked[:MAX_OPINIONS]
    return [(r[0], r[1]) for r in sorted(views + others, key=lambda r: r[0]['dt_utc'])]


__all__ = ['CHANNELS', 'CHANNEL_WORDS', 'classify_post', 'credited_source', 'origin_link',
           'outlet_for', 'select', 'view_of', 'origin_status']
