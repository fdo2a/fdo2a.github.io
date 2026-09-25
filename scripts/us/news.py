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
import json
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

# 2026-09-24 사용자 지시 「정치, 경제, 매크로, 산업, AI 관련 뉴스 위주로」. 그 전의
# 넷(주요·시장·경제·정치)을 이 다섯으로 바꿨다. CNBC 에 매크로·AI 전용 피드는 없다 —
# 그래서 **피드는 출처 묶음이고, 갈래는 기사마다 `classify()` 가 정한다.**
# MLCC 산업 뉴스는 종목 피드에서 수집하며 뉴스 게이트가 근거를 검증한다.
# **MLCC 뉴스 피드는 유동성 있는 넷만 본다.** 표는 여덟 종목을 그대로 싣지만(시세는
# `collect_market_data.MLCC`), 뉴스 피드까지 여덟 개를 연속 호출하면 Yahoo 가 429 를
# 준다(2026-09-19 실측). 월신·홀리스톤·싼환·펑화는 애초에 영문 기사가 1~2건뿐이라
# 빼도 잃는 것이 거의 없다 — 요청을 절반으로 줄이는 쪽이 남는 장사다.
#
# Google News RSS 도 재 봤다(헤드라인 100건, 쓰로틀 없음). **본문을 못 받아서 탈락했다** —
# 링크가 news.google.com 안에 머무는 595 KB JS 페이지라 원문에 닿지 못하고, 그러면
# 300자 요약의 재료가 없다. 헤드라인만 있는 뉴스는 이 리포트가 쓰지 않는다.
MLCC_TICKERS = ('6981.T', '009150.KS', '6976.T', '2327.TW')
_YAHOO_TICKER = 'https://feeds.finance.yahoo.com/rss/2.0/headline?s={}&region=US&lang=en-US'

_CNBC = 'https://www.cnbc.com/id/{}/device/rss/rss.html'
_INVESTING = 'https://www.investing.com/rss/{}.rss'

# 출처 묶음 -> 피드. `pool` 은 갈래가 정해지지 않은 종합 피드라, 키워드로 매크로·AI 에
# 걸리지 않은 기사는 버린다(「주요 뉴스」 칸이 따로 없다).
FEEDS = {
    'politics': (_CNBC.format('10000113'),),                  # Politics & Policy
    'economy': (_CNBC.format('20910258'),),                   # Economy
    'industry': tuple(_CNBC.format(i) for i in (
        '10001147',     # Business
        '19836768',     # Energy
        '10000108',     # Health Care
        '10000101',     # Autos
        '10000116',     # Retail
    )),
    'tech': (_CNBC.format('19854910'),),                      # Technology
    'pool': (_CNBC.format('100003114'),                       # Top News
             _CNBC.format('10000664'),                        # Finance
             'https://finance.yahoo.com/news/rssindex'),
    'mlcc': tuple(_YAHOO_TICKER.format(t) for t in MLCC_TICKERS),
    # 2026-09-26 「글로벌」 — 미·한 밖의 정책·경제 뉴스. 출처 실측은 `../plan.md` 2026-09-26 표.
    # 로이터는 reuters.com 이 401(DataDome)이라 Investing.com 이 전재한 판으로 받는다.
    'global': (_CNBC.format('100727362'),                     # World
               _CNBC.format('19794221'),                      # Europe
               _CNBC.format('19832390'),                      # Asia
               _INVESTING.format('news_14'),                  # Economy (로이터 전재)
               _INVESTING.format('news_287'),                 # World (로이터 전재)
               'https://www.theguardian.com/business/rss',
               'https://www.aljazeera.com/xml/rss/all.xml',
               'https://feeds.bbci.co.uk/news/business/rss.xml',
               'https://www.ecb.europa.eu/rss/press.html',
               'https://www.bankofengland.co.uk/rss/news',
               # 일본(2026-09-26 「일본 관련 뉴스…방법을 찾아서 추가해」) — 교도·지지 등 통신 기사.
               # NHK(JS 렌더)·지지(무료판 본문 없음)·Japan Times(403)·교도 영문(유료)은 실측 탈락.
               'https://news.yahoo.co.jp/rss/categories/business.xml'),
    # 2026-09-26 「리포트·칼럼」 — 「인사이트를 얻을 수 있는 내용이라면 다 좋아」.
    # Investing 분석의 Technical·Fundamental·ideas 피드는 8월에 멈춰 뺐다.
    'insight': tuple(_INVESTING.format(f) for f in (
                   'market_overview', 'forex', 'commodities', 'bonds')) + (
               'https://think.ing.com/rss/',
               'https://www.ecb.europa.eu/rss/blog.html',
               'https://www.bis.org/doclist/cbspeeches.rss',
               'https://www.nli-research.co.jp/RSS.rdf?site=nli'),          # 닛세이기초연구소(Atom)
}

LABELS = {'politics': '정치', 'economy': '경제', 'macro': '매크로', 'industry': '산업',
          'ai': 'AI', 'global': '글로벌', 'insight': '리포트·칼럼', 'mlcc': 'MLCC'}

# 「오늘의 뉴스」 섹션이 싣는 갈래. `mlcc` 는 MLCC 섹션의 뉴스 층으로 가므로 빠진다.
DIGEST_CATEGORIES = ('politics', 'economy', 'macro', 'industry', 'ai', 'global', 'insight')

# 겹친 기사는 더 좁은 갈래에 남긴다. 숫자가 작을수록 좁다. MLCC 가 가장 좁다 — 종목
# 피드에서 왔으므로 그 종목 기사가 맞다.
NARROWNESS = {'mlcc': 0, 'insight': 1, 'global': 1, 'ai': 1, 'macro': 1, 'politics': 2,
              'industry': 2, 'economy': 3}

# 제목·RSS 요약에서 찾는다. 대문자가 뜻을 가르는 약어(AI·Fed·HBM)는 대소문자를 구분하고,
# 일반 단어는 구분하지 않는다. 2026-09-24 구현 검토가 실제 헤드라인 모양으로 잡은 오분류 —
# 「fed up」·Dollar General·동사 yields·가상자산 거래소 Gemini — 를 막는 형태다.
_AI = re.compile(
    r'\bAI\b|\bA\.I\.|\bHBM\b|\bGenAI\b|\bGPUs?\b|\bLLMs?\b|\bNvidia\b|\bOpenAI\b|'
    r'\bChatGPT\b|\bAnthropic\b|\bCopilot\b|\bGoogle Gemini\b|'
    r'(?i:\b(?:artificial intelligence|generative|chatbots?|data cent(?:er|re)s?|'
    r'semiconductors?|chips?|chipmakers?|superintelligence)\b)')
_MACRO = re.compile(
    r'\bFed\b(?!\s+up)|\bFOMC\b|\bPowell\b|\bCPI\b|\bPCE\b|\bGDP\b|\bECB\b|\bBOJ\b|'
    r'(?i:\b(?:Federal Reserve|interest rates?|rate (?:cut|hike)s?|inflation|'
    r'Treasur(?:y|ies)|(?:bond|treasury|10-year|2-year|30-year) yields?|bond market|'
    r'central banks?|Bank of (?:Japan|England)|(?:the|U\.S\.) dollar|dollar index|greenback|'
    r'tariffs?|recession|jobs report|payrolls?|unemployment|jobless|deficit|debt ceiling)\b)')
# Yahoo 종목 피드는 그 종목 기사만 주지 않는다 — 2026-09-24 실측 42건 중 절반이 아시아
# 증시 시황·리튬 배터리 시장·같은 번호의 일본 종목(NS Solutions, TSE:2327 ↔ Yageo 2327.TW)·
# 동종 업종 비교 기사(IDEX)였다. **제목**에 회사명이나 MLCC 가 있어야 MLCC 기사로 친다.
# 요약은 보지 않는다: 동종 비교 기사가 요약에서 Murata 를 들먹여 통과한다.
_MLCC = re.compile(
    r'(?i:\b(?:Murata|MRAAY|Samsung Electro-Mechanics|Taiyo Yuden|Yageo|Walsin|Holy Stone|'
    r'Sanhuan|Fenghua|MLCCs?|multilayer ceramic|capacitors?)\b)')
_HINT = {'politics': 'politics', 'economy': 'economy', 'industry': 'industry',
         'tech': 'industry', 'pool': None, 'global': None, 'insight': None}

# ── 글로벌 (2026-09-26) ──────────────────────────────────────────────────
# When changing this: read `docs/superpowers/specs/2026-09-26-global-news-sources.md` first —
# 출처 실측(무엇이 403·유료벽인지)과 오분류 사례가 거기 있다.
# 사용자 지시 「미국, 한국을 제외한 나라 뉴스 중 정책이나 경제에 큰 영향을 준 뉴스…대표적으로
# 일본, 중국, 유럽, 중동」. **제목**에서 지역을 찾는다 — 요약은 「중국과의 경쟁」 같은 곁가지를
# 들먹인다. 통화 이름(yen·yuan)은 지역으로 치지 않는다: 「The dollar slides against the yen」
# 은 매크로 기사다. 영국·스위스·러시아·우크라이나는 유럽에 넣는다.
_REGIONS = (
    ('japan', re.compile(r'\b(?:Japan(?:ese)?|Tokyo|BOJ|BoJ|Bank of Japan)\b')),
    ('china', re.compile(r"\b(?:China|Chinese|Beijing|Xi|PBOC|PBoC|People's Bank of China|"
                         r'Hong Kong|Shanghai|Shenzhen)\b')),
    ('europe', re.compile(
        r'\b(?:Europe|European|EU|euro ?zone|Eurozone|ECB|Lagarde|German[y]?|Berlin|France|'
        r'French|Britain|British|UK|U\.K\.|England|BoE|BOE|London|Ital(?:y|ian)|Spain|Spanish|'
        r'Switzerland|Swiss|SNB|Netherlands|Dutch|Poland|Polish|Russia|Russian|Kremlin|Putin|'
        r'Moscow|Ukraine|Ukrainian|Zelenskyy?|Kyiv|NATO|Brussels)\b')),
    # 「Gulf」 만으로는 멕시코만이 걸린다
    ('mideast', re.compile(
        r'\b(?:Middle East|Mideast|Iran(?:ian)?|Tehran|Israel(?:i)?|Gaza|Hamas|Hezbollah|'
        r'Lebanon|Saudi|Riyadh|UAE|Emirates|Dubai|Abu Dhabi|Qatar|Kuwait|Iraq|Syria|Yemen|'
        r'Houthis?|OPEC\+?|Hormuz|Red Sea|Gulf states|Gulf Cooperation)\b')),
)
# 공식 기관 피드는 제목에 나라 이름을 쓰지 않는다(「Monetary policy decisions」).
# 일본 출처는 제목에 「日本」 을 쓰지 않는다(국내 기사다) — 다른 지역을 말하면 제목이 이긴다.
_HOST_REGION = {'www.ecb.europa.eu': 'europe', 'www.bankofengland.co.uk': 'europe',
                'news.yahoo.co.jp': 'japan', 'www.boj.or.jp': 'japan',
                'www.nli-research.co.jp': 'japan'}
# 일본어 제목. 「米中」 은 미중(중국 쪽 기사)이다.
_REGIONS_JA = (
    ('japan', re.compile(r'日本|日銀|東京|円相場|円安|円高|強い円')),
    ('china', re.compile(r'中国|米中|日中|習近平|人民銀|人民元|香港')),
    # 한 글자 약칭(独·仏·露)은 뒤에 기관·직함이 올 때만 — 独自·独占·披露 가 걸린다.
    ('europe', re.compile(r'欧州|ユーロ|EU|ECB|ドイツ|英国|イギリス|英中銀|フランス|イタリア|スイス|'
                          r'ロシア|ウクライナ|NATO|'
                          r'(?:独|仏|露)(?:首相|大統領|政府|経済|中銀|連銀|外相|財務相|軍|産)')),
    ('mideast', re.compile(r'中東|イラン|イスラエル|ガザ|サウジ|UAE|カタール|OPEC|ホルムズ|紅海|フーシ')),
)

# 정책·경제 어휘. **몇 개가 걸렸는지**가 후보 순위다 — 「큰 영향」을 기계가 잴 수는 없으니
# 정책·경제 어휘가 촘촘한 기사를 앞에 둔다. 「fiscal」 은 「fiscal first quarter」(회계연도)가
# 걸려 정책 뒤에 오는 형태만 센다. 「summit」 은 판다 외교 기사를 끌어와 뺐다.
_POLICY_TERMS = tuple(re.compile(p) for p in (
    r'(?i:\binterest rates?\b|\brates?\b|\brate (?:cut|hike)s?\b)',
    r'(?i:\bcentral bank|\bmonetary\b|\bpolicy\b|\bpolicymakers?\b)',
    r'(?i:\binflation|\bdeflation|\bCPI\b|\bGDP\b|\brecession|\bgrowth\b|\beconom(?:y|ic|ies)\b)',
    r'(?i:\bstimulus|\bfiscal (?:policy|stimulus|deficit|package|spending|rules?)|\bbudget|'
    r'\bdebt\b|\bdeficit|\bbonds?\b|\byields?\b|\bborrowing)',
    r'(?i:\btariffs?\b|\btrade\b|\bexports?\b|\bimports?\b|\bsanctions?\b|'
    r'\bexport controls?\b|\bembargo)',
    r'(?i:\boil\b|\bcrude\b|\bgas\b|\bLNG\b|\bOPEC|\boutput\b|\benergy\b)',
    r'(?i:\bceasefire|\btruce\b|\bwar\b|\binvasion)',
    r'(?i:\belection|\bprime minister|\bparliament|\bgovernment\b|\bminister|\bresign)',
    r'(?i:\bproperty\b|\bhousing\b|\bmanufacturing|\bPMI\b|\bunemployment|\bjobs\b|\bwages?\b)',
    r'(?i:\bcurrency|\byen\b|\byuan\b|\beuro\b|\bintervention)',
    r'(?i:\btalks\b|\bdeal\b|\bnegotiat|\bagreement)',
    r'(?i:\bdecisions?\b|\bcuts?\b|\bhikes?\b)',
))

_POLICY_TERMS_JA = tuple(re.compile(p) for p in (
    r'金利|利上げ|利下げ|金融政策|日銀|中央銀行|政策金利',
    r'物価|インフレ|デフレ|CPI|GDP|成長率|景気|経済',
    r'財政|予算|国債|補正|減税|増税|補助金|税',
    r'関税|貿易|輸出|輸入|制裁|通商|農産物|大豆',
    r'原油|石油|ガス|LNG|エネルギー|OPEC|減産|増産',
    r'為替|円安|円高|強い円|介入|人民元|ユーロ',
    r'賃金|春闘|雇用|失業|労働|最低賃金|年金|社会保険',
    r'選挙|首相|内閣|国会|政府|大臣|財務相|規制|法案',
    r'停戦|戦争|攻撃|封鎖|首脳会談|合意|協議|交渉',
    r'不動産|住宅|設備投資|消費|生産',
))
# Yahoo!ニュース 경제의 정례 시세표·시황. 시장 섹션의 몫이다.
_JA_ROUTINE = re.compile(r'為替相場|日経平均|東証|NY株|NY外為|終値|前場|後場|寄り付き|株価|相場概況')
# 생활 리포트가 섞이는 연구소 — 경제 어휘가 제목에 있어야 싣는다.
_NEEDS_POLICY = {'www.nli-research.co.jp'}

# 칼럼 피드의 종목 나열형·셋업 글. 「9 Stocks Still Flying…」「These 2 Bond ETFs…」
_LISTICLE = re.compile(
    r'(?i:^\s*(?:top\s+)?\d+\s+(?:[\w-]+\s+){0,3}?(?:stocks?|etfs?|picks|setups|names|'
    r'dividend)\b|\bthese\s+\d+\s|live levels|pre-?market setups)')


def region(title):
    """제목 -> 'japan'|'china'|'europe'|'mideast'|None. 여럿이면 먼저 나온 것."""
    best = None
    for name, rx in _REGIONS + _REGIONS_JA:
        m = rx.search(title or '')
        if m and (best is None or m.start() < best[1]):
            best = (name, m.start())
    return best[0] if best else None


def _host(url):
    return (url or '').split('/')[2] if (url or '').count('/') >= 2 else ''


def region_of(item):
    return region(item.get('title')) or _HOST_REGION.get(_host(item.get('url')))


def policy_score(text):
    """정책·경제 어휘 묶음 가운데 몇 개가 걸렸나."""
    return sum(1 for rx in _POLICY_TERMS + _POLICY_TERMS_JA if rx.search(text or ''))


def classify(item):
    """출처 묶음 + 제목·요약 -> 최종 갈래. 어디에도 안 맞는 종합 피드 기사는 None."""
    hint = item.get('category')
    if hint == 'mlcc':          # 무관한 종목 피드 기사는 다른 갈래로도 보내지 않는다 — 대개 몇 달 전 시황이다
        return 'mlcc' if _MLCC.search(item.get('title') or '') else None
    title = item.get('title') or ''
    if hint == 'insight':       # 칼럼은 지역어가 있어도 칼럼 칸에 남는다
        if _LISTICLE.search(title):
            return None
        if _host(item.get('url')) in _NEEDS_POLICY and not policy_score(title):
            return None
        return 'insight'
    if hint == 'global' and item.get('kind') == 'official':     # 일본은행 정책 발표문
        return 'global'
    text = f"{title} {item.get('summary') or ''}"
    if region_of(item) and policy_score(text) and not _JA_ROUTINE.search(title):
        return 'global'
    if hint == 'global':        # 세계 피드의 판다·만찬·사건 기사는 다른 갈래로 보내지 않는다
        return None
    if _AI.search(text):
        return 'ai'
    if _MACRO.search(text):
        return 'macro'
    return _HINT.get(hint, hint if hint in NARROWNESS else None)


def categorize(items):
    """각 기사에 최종 갈래를 매기고, 갈래가 없는 것은 버린다."""
    out = []
    for it in items or []:
        cat = classify(it)
        if cat == 'global':
            out.append(dict(it, category=cat, region=region_of(it)))
        elif cat == 'insight' and _HOST_REGION.get(_host(it.get('url'))):
            # 칼럼의 칸은 발행 기관이 정한다 — 제목에 Japan 이 든 서구 칼럼이 일본 기관 리포트를
            # 밀어내지 않게(2026-09-26 실수집). 나머지 칼럼은 매체별로 돈다.
            out.append(dict(it, category=cat, region=_HOST_REGION[_host(it['url'])]))
        elif cat:
            out.append(dict(it, category=cat))
    return out


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

# `<item\b` 가 아니면 RDF 의 `<items><rdf:Seq>` 가 첫 item 으로 읽힌다(BIS, 2026-09-26).
_ITEM = re.compile(r'<item(?:\s[^>]*)?>(.*?)</item>', re.S | re.I)
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


def _iso8601(stamp):
    """ISO 8601(dc:date·JSON-LD) -> 정규화한 ISO. 시간대가 없거나 못 읽으면 None."""
    try:
        dt = datetime.fromisoformat((stamp or '').strip().replace('Z', '+00:00'))
    except ValueError:
        return None
    return dt.replace(microsecond=0).isoformat() if dt.tzinfo else None


# 호스트 -> 발행본에 적는 매체 이름. 없는 호스트는 호스트 그대로 둔다(추측하지 않는다).
SOURCES = {
    'www.cnbc.com': 'CNBC', 'finance.yahoo.com': 'Yahoo Finance',
    'www.investing.com': 'Investing.com', 'www.ecb.europa.eu': 'ECB',
    'www.bankofengland.co.uk': 'Bank of England', 'www.bis.org': 'BIS',
    'think.ing.com': 'ING THINK', 'www.theguardian.com': 'The Guardian',
    'www.aljazeera.com': 'Al Jazeera', 'www.bbc.com': 'BBC', 'www.bbc.co.uk': 'BBC',
    'news.yahoo.co.jp': 'Yahoo!ニュース', 'www.boj.or.jp': 'Bank of Japan',
    'www.nli-research.co.jp': 'ニッセイ基礎研究所',
}


def source_name(url):
    host = _host(url)
    if host.endswith('yahoo.com'):
        return 'Yahoo Finance'
    return SOURCES.get(host, host or None)


def parse_feed(xml, category):
    """RSS 문자열 -> [{guid, url, title, summary, published, category, source}].

    피드가 죽어 HTML 오류 페이지를 돌려주는 날이 있다. 그때는 빈 목록이다 —
    비-코어라 그날 뉴스 섹션이 빠질 뿐, 브리프 전체가 서지는 않는다.
    """
    if not xml:
        return []
    if _ATOM.search(xml):
        return _parse_atom(xml, category)
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
            'published': (_iso(_field(chunk, 'pubDate'))
                          or _iso8601(_field(chunk, 'dc:date'))),      # RDF·ING
            'category': category,
            'source': source_name(url),
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
    if '■要旨' in html:            # 닛세이기초연구소 — 요지부터 공유 버튼 앞까지, <p> 가 아니다
        return _nli_body(html, max_chars)
    # Investing.com·Yahoo!ニュース 는 기사 위에 위젯·순위를 <p> 로 싣는다 — 본문 상자부터 읽는다.
    # 끝 표식: Yahoo 는 본문 상자 뒤에 추천 기사·순위·푸터가 <p> 로 이어진다(2026-09-26 실수집).
    for marker, ends in (('id="article"', ()), ('class="article_body', ('【関連記事】', '<section'))):
        start = html.find(marker)
        if start >= 0:
            html = html[start:]
            stops = [i for i in (html.find(e) for e in ends) if i > 0]
            if stops:
                html = html[:min(stops)]
            break
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


def select(items, per_category=DEFAULT_PER_CATEGORY, now=None):
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
        if cat in TWO_PHASE:          # 후보만 — 확정은 본문을 받은 뒤 `trim()`
            out.extend(_two_phase(rows, PRESELECT[cat], now, undated_ok=True))
            continue
        dated = sorted((r for r in rows if r.get('published')),
                       key=lambda r: r['published'], reverse=True)
        undated = [r for r in rows if not r.get('published')]
        out.extend((dated + undated)[:per_category])
    return out


_NS_ITEM = re.compile(r'<\w+:item\b', re.I)


_ATOM = re.compile(r'<feed\b[^>]*xmlns="http://www\.w3\.org/2005/Atom"', re.I)
_ENTRY = re.compile(r'<entry\b[^>]*>(.*?)</entry>', re.S | re.I)
_ATOM_LINK = re.compile(r'<link\b[^>]*\bhref="([^"]+)"', re.I)


def _parse_atom(xml, category):
    """Atom <entry> -> parse_feed 와 같은 행(닛세이기초연구소, 2026-09-26)."""
    out = []
    for chunk in _ENTRY.findall(xml):
        m = _ATOM_LINK.search(chunk)
        if not m:
            continue
        url = _html.unescape(m.group(1))
        summary = _field(chunk, 'summary') or _field(chunk, 'content')
        out.append({
            'guid': _field(chunk, 'id') or url,
            'url': url,
            'title': _field(chunk, 'title'),
            'summary': (summary or '')[:MAX_SUMMARY] or None,
            'published': (_iso8601(_field(chunk, 'published'))
                          or _iso8601(_field(chunk, 'updated'))),
            'category': category,
            'source': source_name(url),
        })
    return out


def parse_feed_strict(xml, category):
    """(rows, note) — 형식이 바뀌어 0건인 것과 진짜 빈 피드를 가른다(#15).

    조용히 빈 목록을 돌려주면 그날 뉴스가 통째로 사라진 것을 아무도 모른다.
    """
    rows = parse_feed(xml, category)
    if rows or not xml:
        return rows, None
    if _ATOM.search(xml):
        return [], 'Atom 피드인데 entry 가 없다 — 형식이 바뀌었을 수 있다'
    if _NS_ITEM.search(xml):
        return [], '네임스페이스 접두사가 붙은 item — 피드 형식이 바뀌었다'
    if '<item' not in xml.lower() and '<channel' not in xml.lower():
        return [], 'RSS 가 아닌 응답(오류 페이지일 수 있다)'
    return [], None


# ── 글로벌·칼럼의 2단 선정 (2026-09-26) ──────────────────────────────────
# 후보를 넉넉히 골라 본문을 받고(`fetch_news.fetch_bodies`), 본문·날짜가 확인된 것만 확정한다.
# Investing.com 뉴스 피드에는 날짜가 없어 기사면에서 읽어야 하고, 확정 전에는 몇 건이 살아남을지
# 모른다. 요약(유료 호출)은 확정분만 만든다.
TWO_PHASE = ('global', 'insight')
PRESELECT = {'global': 8, 'insight': 6}
# 글로벌 넷 = 사용자가 든 지역 넷(일본·중국·유럽·중동)이 한 건씩 들어갈 자리.
FINAL = {'global': 4, 'insight': 4}
# 일본을 맨 앞에 돌린다(2026-09-26 사용자 지시) — 후보가 있으면 일본 한 건은 반드시 들어간다.
FIRST_LANE = 'japan'
WINDOW = timedelta(hours=36)
SAME_EVENT = 0.5            # 제목 단어 자카드. 같은 사건을 CNBC·로이터·가디언이 따로 쓴다
_WORD = re.compile(r'[a-z0-9]{3,}')
_STOP = {'the', 'and', 'for', 'with', 'from', 'says', 'said', 'after', 'over', 'into', 'its'}


def _words(title):
    return {w for w in _WORD.findall((title or '').lower()) if w not in _STOP}


def same_event(a, b):
    wa, wb = _words(a), _words(b)
    return bool(wa and wb) and len(wa & wb) / len(wa | wb) >= SAME_EVENT


def _when(row):
    """aware datetime 만. 시간대 없는 값(RFC 2822 「-0000」)은 날짜 없음으로 친다 — 비교가 터진다."""
    try:
        when = datetime.fromisoformat(row.get('published') or '')
    except ValueError:
        return None
    return when if when.tzinfo else None


def _fresh(row, now, undated_ok):
    when = _when(row)
    if when is None:
        return undated_ok
    return now - WINDOW <= when <= now + timedelta(hours=1)


def _rank(rows):
    """정책·경제 어휘 수 → 최신순. 날짜 없는 행은 같은 점수 안에서 뒤로."""
    def key(r):
        when = _when(r)
        return (-policy_score(f"{r.get('title') or ''} {r.get('summary') or ''}"),
                when is None, -(when.timestamp() if when else 0))
    return sorted(rows, key=key)


def _spread(rows, cap):
    """지역을 돌아가며 뽑는다 — 중국 기사 넷이 다른 지역을 밀어내지 않게. 같은 사건은 한 번."""
    lanes, order = {}, []
    for r in rows:
        lane = r.get('region') or r.get('source') or ''
        if lane not in lanes:
            lanes[lane] = []
            order.append(lane)
        lanes[lane].append(r)
    if FIRST_LANE in order:
        order.remove(FIRST_LANE)
        order.insert(0, FIRST_LANE)
    out = []
    while len(out) < cap and any(lanes.values()):
        for lane in order:
            while lanes[lane]:
                r = lanes[lane].pop(0)
                if not any(same_event(r.get('title'), o.get('title')) for o in out):
                    out.append(r)
                    break
            if len(out) >= cap:
                break
    return out


def _two_phase(rows, cap, now, undated_ok):
    if now is not None:
        rows = [r for r in rows if _fresh(r, now, undated_ok)]
    return _spread(_rank(rows), cap)


def trim(items, now):
    """본문을 받은 뒤 글로벌·칼럼을 확정한다. 다른 갈래는 그대로 둔다.

    본문이 없거나 날짜가 끝내 없거나(기사면에서도 못 읽은 것) 창 밖이면 버린다 — 날짜를
    수집 시각으로 채우지 않는다.
    """
    out, pools = [], {c: [] for c in TWO_PHASE}
    for it in items or []:
        if it.get('category') in pools:
            if it.get('body_chars'):
                pools[it['category']].append(it)
        else:
            out.append(it)
    for cat in TWO_PHASE:
        out.extend(_two_phase(pools[cat], FINAL[cat], now, undated_ok=False))
    return out


_LD_DATE = re.compile(r'"datePublished"\s*:\s*"([^"]+)"')
_META_DATE = re.compile(
    r'<meta[^>]+(?:property|name)="(?:article:published_time|pubdate|DC\.date\.issued)"'
    r'[^>]+content="([^"]+)"', re.I)


def page_published(html):
    """기사면의 발행 시각(JSON-LD → OpenGraph). 못 읽으면 None."""
    for rx in (_LD_DATE, _META_DATE):
        for m in rx.finditer(html or ''):
            got = _iso8601(m.group(1))
            if got:
                return got
    return None


_WIRE = re.compile(r'\((Reuters|AP|AFP|Bloomberg)\)\s*[-–—]')


def wire_of(body):
    """본문 첫머리의 통신사 표기(「PARIS, Sept 25 (Reuters) -」). 앞머리에만 있어야 전재다."""
    m = _WIRE.search((body or '')[:120])
    return m.group(1) if m else None


# ── 일본 (2026-09-26) ────────────────────────────────────────────────────
_NLI_END = ('はてなブックマーク', 'メルマガ配信中', '関連レポート')


def _nli_body(html, max_chars=DEFAULT_MAX_BODY):
    """닛세이기초연구소 리포트면 — 「■要旨」 부터 공유 버튼 앞까지를 글자로. 길면 PDF 가 본판이라
    HTML 은 앞머리만 싣는다(실측 1,500자 안팎) — 300자 요약의 재료로는 넉넉하다."""
    seg = html[html.find('■要旨') + len('■要旨'):]
    ends = [i for i in (seg.find(m) for m in _NLI_END) if i >= 0]
    if ends:
        seg = seg[:min(ends)]
    seg = _DROP.sub(' ', seg)
    seg = re.sub(r'<(?:br|/p|/div|/li|/h\d)\b[^>]*>', '\n', seg, flags=re.I)
    lines = [_WS.sub(' ', _html.unescape(_TAG.sub('', ln))).strip() for ln in seg.split('\n')]
    body = '\n\n'.join(ln for ln in lines if len(ln) >= 20)
    if len(body) < MIN_BODY:
        return ''
    return body[:max_chars]


def pdf_text(data, max_chars=DEFAULT_MAX_BODY):
    """PDF 바이트 -> 글자(일본은행 정책 발표문). pypdf 가 없거나 못 읽으면 ''."""
    try:
        import io
        import pypdf
        reader = pypdf.PdfReader(io.BytesIO(data))
        text = '\n'.join(page.extract_text() or '' for page in reader.pages)
    except Exception:
        return ''
    text = re.sub(r'[ \t]+', ' ', text).strip()
    return text[:max_chars] if len(text) >= MIN_BODY else ''


_TITLE_WIRE = re.compile(r'[(（]([^()（）]{2,20})[)）]\s*$')


def title_wire(title):
    """Yahoo!ニュース 제목 끝의 제공사 「(共同通信)」."""
    m = _TITLE_WIRE.search(title or '')
    return m.group(1) if m else None


_BOJ = 'https://www.boj.or.jp'
_BOJ_ROW = re.compile(r'<tr\b[^>]*>(.*?)</tr>', re.S | re.I)
_BOJ_CELL = re.compile(r'<t[dh]\b[^>]*>(.*?)</t[dh]>', re.S | re.I)
_BOJ_LINK = re.compile(r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.S | re.I)
_MONTHS = {m: i for i, m in enumerate(
    ('jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'), 1)}


def _boj_date(cell):
    """「Sept.&nbsp;10,&nbsp;2026」 -> 그날 00:00 JST. 시각은 목록에 없다 — 날짜만 믿는다."""
    m = re.match(r'([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2}),\s*(\d{4})', _clean_cell(cell))
    if not m or m.group(1).lower() not in _MONTHS:
        return None
    jst = timezone(timedelta(hours=9))
    return datetime(int(m.group(3)), _MONTHS[m.group(1).lower()], int(m.group(2)),
                    tzinfo=jst).isoformat()


def _clean_cell(text):
    return _WS.sub(' ', _html.unescape(_TAG.sub(' ', text or '')).replace('\xa0', ' ')).strip()


def _boj_rows(html):
    if '<table' not in (html or '').lower():
        raise ValueError(f'일본은행 목록에 표가 없다: {_clean_cell(html)[:120]}')
    for tr in _BOJ_ROW.findall(html):
        cells = _BOJ_CELL.findall(tr)
        link = _BOJ_LINK.search(tr)
        if len(cells) >= 2 and link:
            yield cells, link


def _boj_row(url, title, published, category, **extra):
    url = url if url.startswith('http') else _BOJ + url
    return dict({'guid': url, 'url': url, 'title': title, 'summary': None,
                 'published': published, 'category': category,
                 'source': 'Bank of Japan'}, **extra)


def parse_boj_speeches(html, category):
    """일본은행 연설 목록(날짜·연사·제목) -> 행. 연설문 본문은 HTML 이다."""
    out = []
    for cells, link in _boj_rows(html):
        speaker = _clean_cell(cells[1]) if len(cells) >= 3 else ''
        title = _clean_cell(link.group(2))
        out.append(_boj_row(link.group(1), f'{speaker}: {title}' if speaker else title,
                            _boj_date(cells[0]), category))
    return out


def parse_boj_statements(html, category):
    """일본은행 정책 발표문 목록 -> 행. 「(Reference)」 요약본은 뺀다. 본문은 PDF 다."""
    out = []
    for cells, link in _boj_rows(html):
        title = re.sub(r'\s*\[PDF[^\]]*\]\s*$', '', _clean_cell(link.group(2)))
        if title.startswith('(Reference)'):
            continue
        out.append(_boj_row(link.group(1), title, _boj_date(cells[0]), category, kind='official'))
    return out


def pages(year):
    """피드가 없는 출처 — 갈래 -> [(목록 URL, 파서)]. 일본은행 새소식 RSS 에는 연설이 없고
    정책 발표문은 운영 공지 수십 건에 묻힌다(2026-09-26 실측)."""
    return {
        'global': [(f'{_BOJ}/en/mopo/mpmdeci/state_{year}/index.htm', parse_boj_statements)],
        'insight': [(f'{_BOJ}/en/about/press/koen_{year}/index.htm', parse_boj_speeches)],
    }
