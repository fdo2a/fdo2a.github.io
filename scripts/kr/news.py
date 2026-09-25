"""네이버증권 「주요뉴스」를 읽고 KR 「오늘의 뉴스」 후보로 줄이는 순수 로직.

2026-09-24 사용자 지시 「네이버증권에서 불러오는 방법으로 kr에 새로 만들자」. US 뉴스
(`us/news.py`)와 같은 계약이다 — 기사는 수집 잡이 받고, 본문은 커밋하지 않고, 수집 잡이
만든 한국어 요약(`summary_ko`)만 커밋하며, 발행본은 `data-news` 로 수집분과 대조된다
(`us/news_gate.check`, `categories=DIGEST_CATEGORIES`).

**왜 주요뉴스인가.** m.stock 의 뉴스 API 가 받는 갈래는 `mainnews`·`flashnews`·`ranknews`
셋뿐이다(2026-09-24 실측 — 그 밖의 값은 400 「expected one of」). 속보는 보도자료·생활
기사가 섞이고, 많이 본 뉴스는 절세·용돈 기사가 위를 차지한다. 주요뉴스는 증권 편집이
고른 것이라 하루 60건 안팎이 시황·종목·정책 기사다. 갈래는 우리가 제목으로 가른다.

**네트워크는 여기 없다** — `fetch_kr_news.py` 가 받아 온다. 형식이 바뀌어 조용히 빈 값이
나오는 실패를 테스트가 지키려면 순수 함수여야 한다. KR 규칙대로 **목록 응답이 기대한
모양이 아니면 예외를 올린다** — 빈 `[]` 를 성공으로 치지 않는다(`kr/sources.py` 와 같다).

**본문 원문은 커밋하지 않는다.** 국내 언론 기사도 상업 저작물이다. 목록 응답의 `body`
(기사 앞머리 발췌)는 「무슨 기사인지」까지만 남기도록 자른다.
"""

import html as _html
import re
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher

KST = timezone(timedelta(hours=9))

LIST_URL = ('https://m.stock.naver.com/front-api/news/category'
            '?category=mainnews&page={page}&pageSize={size}')
ARTICLE_URL = 'https://n.news.naver.com/mnews/article/{office}/{article}'
PAGE_SIZE = 20          # 100 은 400 이다(2026-09-24 실측). 20 은 된다.
MAX_PAGES = 12          # 당일 수집이면 4~5쪽에서 멈춘다. 연휴 뒤 전 거래일분은 8쪽(160건)으로
                        # 모자랐다(2026-09-24 run 35981964976, 9/23 76건까지).

LABELS = {'macro': '매크로', 'policy': '정책·정치', 'market': '증시', 'industry': '산업·기업',
          'global': '글로벌'}
DIGEST_CATEGORIES = ('macro', 'policy', 'market', 'industry', 'global')

DEFAULT_PER_CATEGORY = 3
MAX_SUMMARY = 200       # 목록의 `body` 발췌 — 앞머리 150자 안팎이 온다
MIN_BODY = 300          # 한국어는 영어보다 촘촘하다 — US 400 보다 낮게
DEFAULT_MAX_BODY = 12000
TITLE_DUP = 0.6         # 같은 기사를 매체마다 다시 쓴 제목. 실측 0.62·0.74, 별개 기사 최고 0.55

# ── 갈래 ─────────────────────────────────────────────────────────────────
# **제목만 본다.** 목록의 발췌는 기사 첫머리라 생활·기획 기사도 금리·환율을 들먹인다.
# 순서가 우선순위다 — 매크로가 정책보다 앞서는 이유: 「채권시장 변수는…미중 정상회담·유가」
# 는 정책 기사가 아니라 금리 기사다. 증시가 산업보다 앞서는 이유: 「삼성전자 내년 63만원 vs
# 27만원…증권가 전망」 은 기업 뉴스가 아니라 주가 전망이다.
_MACRO = re.compile(
    r'한은|한국은행|금통위|기준금리|금리|환율|원[·/-]?달러|달러|물가|CPI|PCE|연준|\bFed\b|FOMC|'
    r'파월|국채|국고채|채권|수출|수입|무역수지|경상수지|GDP|성장률|고용|실업률|유가|인플레')
_POLICY = re.compile(
    r'정부|국회|대통령|여당|야당|민주당|국민의힘|금융위|금감원|금융당국|기재부|기획재정부|산업부|'
    r'공정위|국세청|세법|세제|과세|법안|개정안|상법|밸류업|규제|정책|추경|예산|관세|통상|'
    r'정상회담|트럼프|시진핑|선거')
_MARKET = re.compile(
    r'코스피|코스닥|증시|지수|외국인|기관|개인|순매수|순매도|수급|공매도|ETF|상장|IPO|시총|'
    r'시가총액|증권가|목표가|주가|급등|급락|반등|박스피')
_INDUSTRY = re.compile(
    r'반도체|HBM|메모리|D램|낸드|파운드리|\bAI\b|인공지능|데이터센터|전력|2차전지|배터리|자동차|'
    r'조선|방산|원전|바이오|제약|철강|화학|정유|건설|수주|실적|영업이익|매출|출시|공장|인수|'
    r'합병|M&A|삼성|SK|현대|LG')
_ORDER = (('macro', _MACRO), ('policy', _POLICY), ('market', _MARKET), ('industry', _INDUSTRY))

# 해외 증시 마감 기사는 US 리포트의 몫이다(「유가↑·금리↑ 3대지수 하락」이 매크로로 들어왔다,
# 2026-09-24 실측). 코스피·국내를 함께 말하면 남긴다.
_FOREIGN = re.compile(r'(?:日|中|美|뉴욕|유럽|홍콩|대만|일본|중국)\s*증시|닛케이|상하이종합|3대\s*지수|월가')
_DOMESTIC = re.compile(r'코스피|코스닥|국내')
# 개인 재테크·생활 기획. 주요뉴스에도 섞여 온다(2026-09-24 실측: 절세·전세·용돈).
_LIFESTYLE = re.compile(r'절세|전세|월세|용돈|청약|재테크|노후|\[하우스리뷰\]|\[머니뭐니\]')


def classify(title):
    """제목 -> 갈래. 어디에도 안 맞거나 걸러야 할 기사는 None."""
    t = title or ''
    if _LIFESTYLE.search(t):
        return None
    if _FOREIGN.search(t) and not _DOMESTIC.search(t):
        return None
    for name, rx in _ORDER:
        if rx.search(t):
            return name
    return None


# ── 목록 ─────────────────────────────────────────────────────────────────
def _kst(stamp):
    """'20260924180417' -> ISO 8601(+09:00). 못 읽으면 None — 날짜를 추측하지 않는다."""
    try:
        return datetime.strptime(stamp or '', '%Y%m%d%H%M%S').replace(tzinfo=KST).isoformat()
    except ValueError:
        return None


def _clean(text):
    return re.sub(r'\s+', ' ', _html.unescape(re.sub(r'<[^>]+>', '', text or ''))).strip()


def parse_list(payload):
    """`front-api/news/category` 응답 -> [{guid, url, title, summary, published, source, …}].

    모양이 다르면 ValueError. 행 하나가 식별자를 잃은 것은 건너뛴다 — 가리킬 수 없는 것은
    출처가 아니다.
    """
    if not isinstance(payload, dict) or payload.get('isSuccess') is not True:
        raise ValueError(f'주요뉴스 응답이 성공이 아니다: {str(payload)[:160]}')
    result = payload.get('result')
    if not isinstance(result, list):
        raise ValueError(f'주요뉴스 응답에 result 목록이 없다: {str(payload)[:160]}')
    out = []
    for row in result:
        office, article = (row or {}).get('officeId'), (row or {}).get('articleId')
        if not office or not article:
            continue
        summary = _clean(row.get('body'))
        out.append({
            'guid': f'{office}-{article}',
            'url': ARTICLE_URL.format(office=office, article=article),
            'title': _clean(row.get('titleFull') or row.get('title')) or None,
            'summary': summary[:MAX_SUMMARY] or None,
            'published': _kst(row.get('datetime')),
            'source': row.get('officeName') or None,
        })
    return out


def on_date(items, report_date):
    """발행일(KST) 기사만. 날짜를 못 읽은 행은 버린다 — 어제 기사가 오늘로 섞인다."""
    return [it for it in items or [] if (it.get('published') or '')[:10] == report_date]


def older_than(items, report_date):
    """이 쪽이 발행일보다 앞선 기사에 닿았나 — 페이지를 더 넘길지 정한다."""
    return any((it.get('published') or '9999')[:10] < report_date for it in items or [])


def _title_key(title):
    return re.sub(r'[\W_]+', '', re.sub(r'\[[^\]]*\]', '', title or ''))


def dedupe(items):
    """같은 기사(guid)와 같은 소식을 매체마다 다시 쓴 기사(제목 유사도)를 하나로.

    목록은 최신순이므로 먼저 온 것 — 가장 최근 기사 — 이 남는다.
    """
    out, keys = [], []
    for it in items or []:
        key = _title_key(it.get('title'))
        if any(it.get('guid') == o.get('guid') for o in out):
            continue
        if key and any(SequenceMatcher(None, key, k).ratio() >= TITLE_DUP for k in keys):
            continue
        out.append(dict(it))
        keys.append(key)
    return out


def categorize(items):
    """주요뉴스 행은 예전 규칙, 세계 섹션 행(`feed == 'world'`)은 글로벌 규칙."""
    out = []
    for it in items or []:
        if it.get('feed') == 'world':
            if classify_global(it.get('title')):
                out.append(dict(it, category='global', region=region(it.get('title'))))
            continue
        cat = classify(it.get('title'))
        if cat:
            out.append(dict(it, category=cat))
    return out


def select(items, per_category=DEFAULT_PER_CATEGORY):
    """갈래별 상한. 얇은 갈래를 다른 갈래로 채우지 않는다(US `select` 와 같은 이유)."""
    buckets = {}
    for it in items or []:
        buckets.setdefault(it['category'], []).append(it)
    out = []
    for cat in DIGEST_CATEGORIES:
        if cat == 'global':          # 후보만 — 날짜는 기사면에서 읽고 `trim()` 이 확정한다
            out.extend(_spread(_rank(buckets.get(cat, [])), PRESELECT_GLOBAL))
            continue
        rows = sorted(buckets.get(cat, []), key=lambda r: r.get('published') or '', reverse=True)
        out.extend(rows[:per_category])
    return out


# ── 본문 ─────────────────────────────────────────────────────────────────
_DIC = re.compile(r'<article\b[^>]*\bid="dic_area"[^>]*>(.*?)</article>', re.S | re.I)
# 사진 묶음(캡션 포함)·표·스크립트는 본문이 아니다.
_DROP = re.compile(
    r'<(script|style|table|figure)\b.*?</\1>|'
    r'<span\b[^>]*class="[^"]*end_photo_org[^"]*"[^>]*>.*?</span>|'
    r'<em\b[^>]*class="[^"]*img_desc[^"]*"[^>]*>.*?</em>|<!--.*?-->', re.S | re.I)
_BR = re.compile(r'<br\s*/?>', re.I)
# 기자 서명·저작권 고지 줄. 요약의 재료가 아니다.
_TAIL = re.compile(r'^\s*(?:\[[^\]]{1,20}기자\]|[^\s]{1,10}\s*기자\s*[\w.-]+@[\w.-]+|'
                   r'.*(?:무단\s*전재|재배포\s*금지|ⓒ|©).*)\s*$')


def extract_body(html, max_chars=DEFAULT_MAX_BODY):
    """네이버 기사 페이지 -> 본문 텍스트. 본문 영역이 없거나 짧으면 ''."""
    m = _DIC.search(html or '')
    if not m:
        return ''
    raw = _BR.sub('\n', _DROP.sub(' ', m.group(1)))
    text = _html.unescape(re.sub(r'<[^>]+>', ' ', raw))
    lines = [re.sub(r'[ \t ]+', ' ', ln).strip() for ln in text.split('\n')]
    lines = [ln for ln in lines if ln and not _TAIL.match(ln)]
    body = '\n'.join(lines)
    if len(body) < MIN_BODY:
        return ''
    return body[:max_chars]


def body_note(html):
    """`extract_body` 가 왜 비었는지."""
    if not _DIC.search(html or ''):
        return '본문 영역 없음'
    return '짧다'


# ── 글로벌 (2026-09-26) ──────────────────────────────────────────────────
# 사용자 지시 「미국, 한국을 제외한 나라 뉴스 중 정책이나 경제에 큰 영향을 준 뉴스…대표적으로
# 일본, 중국, 유럽, 중동」. 주요뉴스에는 해외 기사가 드물어 **네이버 뉴스 세계 섹션**을 따로
# 읽는다. `?date=` 가 그날 기사만 준다(2026-09-26 실측). 목록 시각은 「4시간전」 꼴이라
# 날짜는 기사면의 `data-date-time` 에서 읽는다 — US `news.trim` 과 같은 2단 선정이다.
SECTION_URL = 'https://news.naver.com/breakingnews/section/{sid1}/{sid2}?date={date}'
WORLD_SECTIONS = ((101, 262, '세계경제'), (104, 231, '아시아/호주'), (104, 233, '유럽'),
                  (104, 234, '중동/아프리카'))
PRESELECT_GLOBAL = 8
FINAL_GLOBAL = 4        # 사용자가 든 지역 넷이 한 건씩 들어갈 자리

_LI = re.compile(r'<li\b[^>]*class="sa_item\b[^"]*"[^>]*>(.*?)</li>', re.S | re.I)
_SA_TITLE = re.compile(
    r'<a\s+href="https://n\.news\.naver\.com/mnews/article/(\d+)/(\d+)[^"]*"[^>]*'
    r'class="sa_text_title[^"]*"[^>]*>\s*<strong[^>]*>(.*?)</strong>', re.S | re.I)
_SA_LEDE = re.compile(r'class="sa_text_lede"[^>]*>(.*?)</div>', re.S | re.I)
_SA_PRESS = re.compile(r'class="sa_text_press"[^>]*>(.*?)</div>', re.S | re.I)


def parse_section(html):
    """세계 섹션 목록 HTML -> 행. 목록 틀(`sa_list`)조차 없으면 ValueError — 조용한 0건 금지."""
    if 'sa_list' not in (html or '') and 'sa_item' not in (html or ''):
        raise ValueError(f'세계 섹션 목록 모양이 아니다: {_clean(html)[:120]}')
    out = []
    for chunk in _LI.findall(html):
        m = _SA_TITLE.search(chunk)
        if not m:
            continue
        office, article, title = m.group(1), m.group(2), _clean(m.group(3))
        lede, press = _SA_LEDE.search(chunk), _SA_PRESS.search(chunk)
        out.append({
            'guid': f'{office}-{article}',
            'url': ARTICLE_URL.format(office=office, article=article),
            'title': title or None,
            'summary': _clean(lede.group(1))[:MAX_SUMMARY] or None if lede else None,
            'published': None,
            'source': _clean(press.group(1)) or None if press else None,
            'feed': 'world',
        })
    return out


# 제목에서 지역을 찾는다. 한 글자 약칭(中·日·英·러)은 붙는 말에 조심한다 — 中企(중소기업),
# 달러의 「러」, 조사 「~이란」, 동사 「가자」.
_REGIONS_KO = (
    ('japan', re.compile(r'일본|日|도쿄|(?<![가-힣])엔(?:화|저)')),
    # 「미중 무역협상」 은 中 도 중국 도 쓰지 않는다(2026-09-25 실측)
    ('china', re.compile(r'중국|中(?!企)|미·?중|시진핑|習|인민은행|위안|베이징|홍콩')),
    ('europe', re.compile(
        r'유럽|유로존|유로화|(?<![A-Za-z])EU(?![A-Za-z])|ECB|라가르드|독일|獨|프랑스|佛|영국|英|'
        r'영란은행|이탈리아|스페인|스위스|네덜란드|폴란드|러시아|(?<![가-힣])대?러(?![가-힣])|露|'
        r'크렘린|푸틴|우크라|젤렌스키|나토|NATO|브뤼셀')),
    ('mideast', re.compile(
        r'중동|(?<![가-힣])이란|테헤란|이스라엘|가자\s?지구|하마스|헤즈볼라|레바논|사우디|UAE|'
        r'아랍에미리트|두바이|카타르|쿠웨이트|이라크|시리아|예멘|후티|OPEC|오펙|호르무즈|홍해|걸프')),
)
# 정책·경제 어휘 묶음 — 몇 묶음이 걸렸나가 후보 순위다. 「회담」 은 만찬·농담 기사를 끌어와 뺐다.
_CENTRAL = re.compile(r'금리|통화정책|중앙은행|인민은행|일본은행|日銀|ECB|BOE|영란은행')
_POLICY_KO = (
    _CENTRAL,
    re.compile(r'물가|인플레|CPI|GDP|성장률|경기|경제|침체'),
    re.compile(r'부양|재정|예산|국채|채권|부채|적자'),
    re.compile(r'관세|무역|교역|통상|수출|수입|제재|보복'),
    re.compile(r'유가|원유|석유|가스|LNG|OPEC|오펙|감산|증산|호르무즈|에너지'),
    re.compile(r'휴전|종전|전쟁|공습|봉쇄|침공|파병|군사\s?지원'),
    re.compile(r'선거|총선|대선|총리|내각|의회|정부|장관|사임'),
    re.compile(r'부동산|주택|제조업|PMI|고용|실업|임금'),
    re.compile(r'환율|엔화|엔저|위안|유로화|외환|개입'),
    re.compile(r'협상|합의|협정'),
)
# 미국 시황은 US 리포트의 몫이고, 해외 증시 마감도 정책 기사가 아니다 — 금리 결정이 걸린 것만 남긴다.
_US_MARKET = re.compile(r'뉴욕증시|월가|3대\s*지수|나스닥|다우지수|S&P')


def region(title):
    """제목 -> 'japan'|'china'|'europe'|'mideast'|None. 여럿이면 먼저 나온 것."""
    best = None
    for name, rx in _REGIONS_KO:
        m = rx.search(title or '')
        if m and (best is None or m.start() < best[1]):
            best = (name, m.start())
    return best[0] if best else None


def policy_score(title):
    return sum(1 for rx in _POLICY_KO if rx.search(title or ''))


def classify_global(title):
    t = title or ''
    if _LIFESTYLE.search(t) or not region(t) or not policy_score(t):
        return None
    if (_US_MARKET.search(t) or _FOREIGN.search(t)) and not _CENTRAL.search(t):
        return None
    return 'global'


def _rank(rows):
    """정책 어휘 묶음 수 → 목록 순서(섹션 목록은 최신순)."""
    return sorted(rows, key=lambda r: -policy_score(r.get('title')))


def _spread(rows, cap):
    """지역을 돌아가며 뽑는다. 같은 소식의 재탕은 `dedupe` 가 이미 접었다."""
    lanes, order = {}, []
    for r in rows:
        lane = r.get('region') or ''
        if lane not in lanes:
            lanes[lane] = []
            order.append(lane)
        lanes[lane].append(r)
    if 'japan' in order:          # 일본을 맨 앞에(2026-09-26 사용자 지시, US `news.FIRST_LANE` 과 같다)
        order.remove('japan')
        order.insert(0, 'japan')
    out = []
    while len(out) < cap and any(lanes.values()):
        for lane in order:
            if lanes[lane] and len(out) < cap:
                out.append(lanes[lane].pop(0))
    return out


def trim(items, report_date):
    """본문을 받은 뒤 글로벌을 확정한다 — 본문이 있고 기사면 날짜가 발행일인 것만. 다른 갈래는 그대로."""
    out, pool = [], []
    for it in items or []:
        if it.get('category') != 'global':
            out.append(it)
        elif it.get('body_chars') and (it.get('published') or '')[:10] == report_date:
            pool.append(it)
    return out + _spread(_rank(pool), FINAL_GLOBAL)


_DATE_TIME = re.compile(r'_ARTICLE_DATE_TIME"[^>]*data-date-time="([^"]+)"|'
                        r'data-date-time="([^"]+)"[^>]*_ARTICLE_DATE_TIME')


def article_published(html):
    """네이버 기사면의 입력 시각('2026-09-24 23:45:06', KST) -> ISO. 못 읽으면 None."""
    m = _DATE_TIME.search(html or '')
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1) or m.group(2), '%Y-%m-%d %H:%M:%S') \
            .replace(tzinfo=KST).isoformat()
    except ValueError:
        return None
