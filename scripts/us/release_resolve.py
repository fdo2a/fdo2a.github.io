"""Where is *this month's* release? Landing page -> dated document (2026-11-06).

Three releases had evergreen URLs that never held the release itself:

- BEA (PCE = Personal Income and Outlays, GDP): the landing page carries one summary
  paragraph and a "Current Release" link. There is no fixed "latest" URL; the RSS feed
  `apps.bea.gov/rss/rss.xml` lists every release with its dated page, its PDF and a
  pubDate. Some `<link>`s come without a scheme or cut short, so the PDF is the fallback.
- NAR existing-home sales: the old newsroom URL is a 404. The housing-statistics page
  links "Read the full news release"; the slug carries the month and the move, so it
  cannot be built — only followed.

Everything else (BLS `*.nr0.htm`, DOL `ui/data.pdf`, Census PDFs, the Fed's G.17
`current/`, the UMich home page) already is "the current release" at a fixed address;
`release_verify` decides whether what came back is the right round.

Pure: page text in, URL out. `fetch_releases.py` does the network.
"""
import datetime
import email.utils
import re
import urllib.parse

BEA_RSS = 'https://apps.bea.gov/rss/rss.xml'
NAR_PAGE = 'https://www.nar.realtor/research-and-statistics/housing-statistics/existing-home-sales'

# key -> (resolver, title prefixes for the BEA feed)
RESOLVERS = {
    'pce': ('bea_rss', ('Personal Income and Outlays',)),
    'gdp': ('bea_rss', ('GDP', 'Gross Domestic Product')),
    'existing-home-sales': ('nar_page', ()),
}
FRESH_DAYS = 10

_ITEM = re.compile(r'<item\b.*?</item>', re.S)


def _tag(item, name):
    m = re.search(rf'<{name}>\s*(.*?)\s*</{name}>', item, re.S)
    return m.group(1).strip() if m else None


def normalize_link(link, base='https://www.bea.gov'):
    """'www.bea.gov/news/…' and 'https://bea.gov/…' both -> an absolute https URL."""
    if not link:
        return None
    link = link.strip()
    if link.startswith('//'):
        link = 'https:' + link
    elif not re.match(r'https?://', link):
        link = urllib.parse.urljoin(base + '/', link) if link.startswith('/') else 'https://' + link
    return link


def same_site(a, b):
    """Registrable-domain equality: bea.gov == www.bea.gov == apps.bea.gov."""
    def reg(u):
        host = (urllib.parse.urlsplit(u or '').hostname or '').lower()
        return '.'.join(host.split('.')[-2:])
    return bool(reg(a)) and reg(a) == reg(b)


def bea_from_rss(xml, prefixes, today, fresh_days=FRESH_DAYS):
    """-> (html_url | None, pdf_url | None, pubdate | None). Newest item whose title
    starts with one of `prefixes` and was published within `fresh_days` of `today`."""
    best = None
    for item in _ITEM.findall(xml or ''):
        title = _tag(item, 'title') or ''
        if not any(title.startswith(p) for p in prefixes):
            continue
        try:
            pub = email.utils.parsedate_to_datetime(_tag(item, 'pubDate') or '').date()
        except (TypeError, ValueError):
            continue
        if not (0 <= (today - pub).days <= fresh_days):
            continue
        if best is None or pub > best[2]:
            best = (normalize_link(_tag(item, 'link')), normalize_link(_tag(item, 'pdf')), pub)
    if best is None:
        return None, None, None
    html_url, pdf_url, pub = best
    # A link cut short ('…-2nd-quarte') still parses; it will 404 and the PDF takes over.
    return html_url, pdf_url, pub


def nar_from_page(html, base=NAR_PAGE):
    m = re.search(r'<a\b[^>]*href="([^"]+)"[^>]*>\s*Read the full news release', html or '', re.I)
    if not m:
        return None
    return urllib.parse.urljoin(base, m.group(1))


def today_utc():
    return datetime.datetime.now(datetime.timezone.utc).date()
