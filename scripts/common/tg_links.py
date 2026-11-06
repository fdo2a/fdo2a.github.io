# Ported from fdo2a/telegram-shadow shadow/links.py (2026-11-06). Keep the two in step or retire the shadow.
"""Link -> (kind, match key). URL equality means 'the exact same article' only;
same-fact-different-URL is left to the human sample."""
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

NAVER_RE = re.compile(r'^/(?:mnews/)?article/(\d{3})/(\d{10})(?:/|$)')
TRACKING = re.compile(r'^(utm_.*|fbclid|gclid|igshid|si|ref|ref_src|cmpid|smid|mediaCodeNo|mc_cid|mc_eid)$', re.I)

KINDS = {
    'dart': ('dart.fss.or.kr', 'kind.krx.co.kr'),
    'reuters': ('reuters.com',),
    'bloomberg': ('bloomberg.com',),
    'ft': ('ft.com', 'giftarticle.ft.com'),
    'wsj': ('wsj.com',),
    'firm_research': ('kiwoom.com', 'bbn.kiwoom.com', 'invest.kiwoom.com', 'hanwhawm.com',
                      'hanwhainvestment.com'),
    'social': ('x.com', 'twitter.com', 'youtube.com', 'youtu.be', 'instagram.com', 'facebook.com',
               'threads.net', 'blog.naver.com', 'thebrink.co.kr'),
    'telegram': ('t.me', 'telegram.me'),
    'shortener': ('naver.me', 'buly.kr', 'bit.ly', 'cutt.ly', 'shorten.is', 'iii.ad', 'han.gl',
                  'me2.do', 'tinyurl.com', 'url.kr'),
}
NEWS = ('sedaily.com', 'edaily.co.kr', 'etoday.co.kr', 'newspim.com', 'hankyung.com', 'mk.co.kr',
        'yna.co.kr', 'biz.chosun.com', 'chosun.com', 'news.einfomax.co.kr', 'mt.co.kr', 'fnnews.com',
        'asiae.co.kr', 'heraldcorp.com', 'v.daum.net', 'ebn.co.kr', 'thelec.kr', 'zdnet.co.kr',
        'cnbc.com', 'nikkei.com', 'asia.nikkei.com', 'economist.com', 'theinformation.com',
        'wallstreetcn.com', 'money.udn.com', 'techpowerup.com', 'digitimes.com', 'nytimes.com',
        'washingtonpost.com', 'apnews.com', 'axios.com', 'semafor.com', 'barrons.com',
        'marketwatch.com', 'investing.com', 'finance.yahoo.com', 'businessinsider.com',
        'datatooza.com', 'market-ink.co.kr')
ORIGIN_KINDS = {'naver_article', 'dart', 'reuters', 'bloomberg', 'ft', 'wsj', 'firm_research',
                'news', 'other'}
RELAY_KINDS = {'social', 'telegram', 'shortener'}


def _host(netloc):
    h = netloc.lower().split('@')[-1].split(':')[0]
    return h[4:] if h.startswith('www.') else h


def _match(host, domains):
    return any(host == d or host.endswith('.' + d) for d in domains)


def normalize(url):
    """Drop fragment and tracking params only; keep params that identify the article."""
    try:
        s = urlsplit(url.strip())
    except ValueError:
        return None
    if s.scheme not in ('http', 'https') or not s.netloc:
        return None
    q = [(k, v) for k, v in parse_qsl(s.query, keep_blank_values=True) if not TRACKING.match(k)]
    path = s.path.rstrip('/') or '/'
    return urlunsplit(('https', _host(s.netloc), path, urlencode(q), ''))


def classify(url):
    """-> (kind, key). key is None when the URL is unusable."""
    n = normalize(url)
    if n is None:
        return 'invalid', None
    s = urlsplit(n)
    host = s.netloc
    if _match(host, ('n.news.naver.com', 'news.naver.com', 'm.news.naver.com')):
        m = NAVER_RE.match(s.path)
        if m:
            return 'naver_article', f'naver:{m.group(1)}-{m.group(2)}'
        return 'other', 'url:' + n
    for kind, domains in KINDS.items():
        if _match(host, domains):
            return kind, 'url:' + n
    if _match(host, NEWS):
        return 'news', 'url:' + n
    return 'other', 'url:' + n


def pool_key(item):
    """Baseline item (public pipeline row) -> match key, same scheme as classify()."""
    guid = item.get('guid') or ''
    if re.fullmatch(r'\d{3}-\d{10}', guid):
        return f'naver:{guid}'
    url = item.get('url') or (guid if guid.startswith('http') else None)
    if not url:
        return None
    return classify(url)[1]


def origin_status(kinds):
    if any(k in ORIGIN_KINDS for k in kinds):
        return 'origin_link'
    if any(k in RELAY_KINDS for k in kinds):
        return 'relay_only'
    return 'no_link'
