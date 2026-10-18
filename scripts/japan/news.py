"""Yahoo!ファイナンス 뉴스를 읽고 일본 주간 「이번 주 뉴스」 후보로 줄이는 순수 로직.

2026-10-18 사용자 지시 「일본 시장 레포트에 뉴스 기사들을 수집하는 것도 추가해. 조사 범위나
내용등은 미국이나 한국 방식을 똑같이」 + 「야후재팬이나 finance.yahoo.co.jp 등을 통해 가져올 수
있는지 확인 후 가능하면 거기서」. US(`us/news.py`)·KR(`kr/news.py`)과 같은 계약이다 — 기사는
수집 잡이 받고, 본문은 커밋하지 않고, 수집 잡이 만든 한국어 요약(`summary_ko`)만 커밋하며,
발행본은 `data-news` 로 수집분과 대조된다(`us/news_gate.check`).

**왜 finance.yahoo.co.jp 인가.** news.yahoo.co.jp 의 RSS 는 50건이라 하루 한 번 읽으면 3-8시간
분량만 남고 생활·자동차 매체가 대부분이다. finance 의 카테고리 목록은 서버가 그린 JSON
(`__PRELOADED_STATE__`)에 20건/쪽, 50쪽(1,000건)까지 거슬러 가고, 평일 주력이 로이터·지지통신
일본어판이다(2026-10-18 실측 — spec `2026-10-18-japan-news-design.md`).

**네트워크는 여기 없다** — `fetch_japan_news.py` 가 받아 온다. 모양이 다르면 예외를 올린다 —
빈 목록을 성공으로 치지 않는다(KR 과 같다).
"""

import html as _html
import json
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from difflib import SequenceMatcher
from html.parser import HTMLParser

from us.news import _POLICY_TERMS_JA

JST = timezone(timedelta(hours=9))

BASE = 'https://finance.yahoo.co.jp/news'
LIST_URL = BASE + '/{feed}?page={page}'
DETAIL_URL = BASE + '/detail/{id}'
# 経済総合·市況·株式·為替·海外·決算. 「headline」「column」 은 생활·재테크 매체가 대부분이라 뺐다.
FEEDS = ('bus_all', 'market', 'stocks', 'fx', 'world', 'settlement')
MAX_PAGES = 50          # 사이트 상한(paging.totalSize 1,000). 평일 하루는 bus_all 10쪽 안팎

LABELS = {'macro': '매크로', 'policy': '정책·정치', 'market': '증시', 'industry': '산업·기업',
          'global': '글로벌', 'insight': '리포트·칼럼'}
# KR 다섯 갈래 + US 의 리포트·칼럼(일본은행 연설·닛세이기초연구소)
DIGEST_CATEGORIES = ('macro', 'policy', 'market', 'industry', 'global', 'insight')

PER_CATEGORY = 3        # US·KR `DEFAULT_PER_CATEGORY`
PRESELECT = 6           # 본문이 실패해도 3건을 채울 대체 후보(US `TWO_PHASE` 와 같은 2단계)
MIN_BODY = 300          # KR 과 같다. 지지 단신(250자)은 요약 240-420자의 재료가 못 된다
MAX_BODY = 12000
TITLE_DUP = 0.6

# 생활·코인·게임 매체를 막는 허용 목록과 순위(작을수록 앞). 평일 bus_all 표본 260건에서
# CoinPost·NADA NEWS·LIMO·gamebiz 가 40% 였다.
MEDIA_RANK = {'ロイター': 0, '時事通信': 0, '共同通信': 0, 'ブルームバーグ': 0, '日本経済新聞': 0,
              '産経新聞': 1, '毎日新聞': 1, '読売新聞': 1, '朝日新聞': 1, '日刊工業新聞': 1,
              '株探ニュース': 2, 'フィスコ': 2}

# 시세표·일정표·종목 나열·속보 지표 단신. 그날 시세는 표가 말한다.
_ROUTINE = re.compile(
    r'午[前後]\d+時現在|現在値|レンジ|前引け|前場|午前の日経平均|寄り付[きく]|大引け直前|〔[^〕]*予測〕|今週の|来週の|週間展望|'
    r'相場観測|相場展望|ランキング|リスト|銘柄|注目トピック|指標フラッシュ|【速報】|ストップ高|ストップ安')

_MACRO = re.compile(
    r'日銀|日本銀行|植田|金融政策|利上げ|利下げ|政策金利|金利|国債|JGB|長期金利|円相場|円安|円高|'
    r'為替|物価|CPI|インフレ|デフレ|GDP|賃金|春闘|景気|雇用|失業|貿易収支|経常収支|日銀短観|短観')
_POLICY = re.compile(
    r'政府|首相|内閣|官房長官|財務省|財務相|経産省|経済産業省|金融庁|総務省|厚労省|予算|補正|財政|'
    r'関税|規制|法案|国会|与党|野党|自民|立憲|選挙|減税|増税|税制|補助金|経済対策|通商|首脳会談')
_MARKET = re.compile(
    r'日経平均|東証|TOPIX|株価|日本株|株式市場|先物|プライム|グロース市場|海外投資家|売買代金|'
    r'新興株|株高|株安|続伸|続落|反発|反落')
_INDUSTRY = re.compile(
    r'決算|業績|上方修正|下方修正|増益|減益|最高益|赤字|黒字|半導体|自動車|EV|電池|AI|データセンター|'
    r'買収|M&A|TOB|増産|減産|受注|工場|出資|提携|上場|株主|トヨタ|ソニー|日立|ソフトバンク|三菱|'
    r'任天堂|キーエンス|東京エレクトロン|ニデック|ホンダ|日産|パナソニック|TSMC|ラピダス')
_ORDER = (('macro', _MACRO), ('policy', _POLICY), ('market', _MARKET), ('industry', _INDUSTRY))

# 해외가 주어인 기사 — 제목에 일본 표지가 없을 때만 글로벌. 「米国の消費者物価」는 글로벌,
# 「日銀、米関税の影響を注視」는 매크로다.
_JAPAN = re.compile(r'日本|日銀|国内|東証|日経|円相場|円安|円高|財務省|経産省|内閣府|金融庁|官房長官|国会|自民')
# 한 글자 약칭(米·英·独·仏)은 뒤에 붙는 말이 있을 때만 — 米価(쌀값)·英語·独自 가 걸린다.
_FOREIGN = re.compile(
    r'米国|米(?=[\d政経株金雇大関中欧財商当長債製小住])|連銀|中国|欧州|ユーロ|EU|ECB|FRB|パウエル|英国|'
    r'英(?=[中政経首])|ドイツ|独(?=[首大政経])|フランス|仏(?=[首大政経])|ロシア|ウクライナ|中東|'
    r'イラン|イスラエル|サウジ|OPEC|インド|韓国|台湾|トランプ|習近平|IMF|G20|G7')
# 해외 증시 마감은 US 리포트의 몫이다(KR `_FOREIGN` 과 같은 이유).
_FOREIGN_MARKET = re.compile(r'NY株|NYダウ|米国株|米株|ダウ平均|ナスダック|欧州株|上海株|香港株|NY外為|NY円|'
                             r'〔NY|〔欧州|〔シカゴ|〔ロンドン|WTI|アジア株|アジア株式')

# 일본은행·닛세이기초연구소 — 공식 출처는 매체 허용 목록·제목 분류를 거치지 않는다(codex #11).
BOJ_STATEMENTS = 'https://www.boj.or.jp/en/mopo/mpmdeci/state_{year}/index.htm'
BOJ_SPEECHES = 'https://www.boj.or.jp/en/about/press/koen_{year}/index.htm'
NLI_FEED = 'https://www.nli-research.co.jp/RSS.rdf?site=nli'


# ── 목록 ─────────────────────────────────────────────────────────────────
def preloaded_state(html):
    """`window.__PRELOADED_STATE__ = {...}` -> dict. 없거나 못 읽으면 ValueError."""
    at = (html or '').find('__PRELOADED_STATE__')
    start = html.find('{', at) if at >= 0 else -1
    if start < 0:
        raise ValueError('__PRELOADED_STATE__ 가 없다 — 목록 모양이 바뀌었다')
    try:
        return json.JSONDecoder().raw_decode(html[start:])[0]
    except ValueError as e:
        raise ValueError(f'__PRELOADED_STATE__ 를 읽지 못했다: {e}') from None


_DETAIL_ID = re.compile(r'/news/detail/([0-9a-f]{40})\b')


def parse_list(html, feed):
    """카테고리 쪽 -> [{guid, url, title, source, created, paid, feed}]. 경로가 없으면 ValueError."""
    state = preloaded_state(html)
    try:
        articles = state['mainNewsCategory']['news']['articles']
    except (KeyError, TypeError):
        raise ValueError('mainNewsCategory.news.articles 가 없다 — 목록 모양이 바뀌었다') from None
    if not isinstance(articles, list):
        raise ValueError('articles 가 목록이 아니다')
    out = []
    for a in articles:
        m = _DETAIL_ID.search((a or {}).get('link') or '')
        if not m:
            continue                  # 가리킬 수 없는 것은 출처가 아니다
        out.append({'guid': m.group(1), 'url': DETAIL_URL.format(id=m.group(1)),
                    'title': _clean(a.get('headline')) or None,
                    'source': (a.get('mediaName') or '').strip() or None,
                    'created': (a.get('createTime') or '').strip(),
                    'paid': bool(a.get('isPaidArticle')), 'feed': feed})
    return out


def list_day(created, today):
    """목록 시각 -> 그 기사의 JST 날짜. 「19:30」 은 목록을 읽은 날(`today`), 「10/16」 은 그 날짜.

    연도는 목록에 없다 — 읽은 날보다 뒤의 월·일이면 지난해다(1월에 읽은 「12/30」).
    못 읽으면 None: 날짜를 추측하지 않는다.
    """
    today = date.fromisoformat(str(today))
    if re.fullmatch(r'\d{1,2}:\d{2}', created or ''):
        return today.isoformat()
    m = re.fullmatch(r'(\d{1,2})/(\d{1,2})', created or '')
    if not m:
        return None
    try:
        d = date(today.year, int(m.group(1)), int(m.group(2)))
    except ValueError:
        return None
    if d > today:
        d = date(today.year - 1, d.month, d.day)
    return d.isoformat()


def reached(rows, oldest, today):
    """이 쪽이 `oldest` 보다 앞선 날짜에 닿았나 — 쪽을 더 넘길지 정한다."""
    return any((list_day(r.get('created'), today) or '9999') < oldest for r in rows or [])


# ── 선별 ─────────────────────────────────────────────────────────────────
def _clean(text):
    return re.sub(r'\s+', ' ', _html.unescape(re.sub(r'<[^>]+>', '', text or ''))).strip()


def _nfkc(text):
    return unicodedata.normalize('NFKC', text or '')


def policy_score(title):
    t = _nfkc(title)
    return sum(1 for rx in _POLICY_TERMS_JA if rx.search(t))


def classify(title, feed=None):
    """제목 -> 갈래. 걸러야 하거나 어디에도 안 맞으면 None. **제목만 본다**(KR 과 같은 이유)."""
    t = _nfkc(title)
    if not t or _ROUTINE.search(t):
        return None
    if _FOREIGN_MARKET.search(t) and not _JAPAN.search(t):
        return None
    if not _JAPAN.search(t) and (_FOREIGN.search(t) or feed == 'world'):
        return 'global' if policy_score(t) or _MACRO.search(t) or _POLICY.search(t) else None
    for name, rx in _ORDER:
        if rx.search(t):
            return name
    return None


def screen(rows):
    """(남은 행, 버린 사유 집계). 유료·허용 밖 매체·분류 불가를 뺀다."""
    kept, dropped = [], {}

    def drop(why):
        dropped[why] = dropped.get(why, 0) + 1

    for r in rows or []:
        if r.get('paid'):
            drop('유료')
            continue
        if r.get('source') not in MEDIA_RANK:
            drop(f'매체 {r.get("source")}')
            continue
        cat = classify(r.get('title'), r.get('feed'))
        if not cat:
            drop('갈래 없음·정례')
            continue
        kept.append(dict(r, category=cat))
    return kept, dropped


_FIGURE = re.compile(r'\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?')


def _figures(title):
    return sorted(f.replace(',', '') for f in _FIGURE.findall(_nfkc(title)))


def _title_key(title):
    t = re.sub(r'[【〔\[(（][^】〕\])）]*[】〕\])）]', '', _nfkc(title))
    return re.sub(r'[\W_]+', '', t)


def same_event(a, b):
    """같은 사건의 재탕인가. 제목 숫자가 다르면 아니다 — 「米国の消費者物価…3.2%」 와 「英国の…2.8%」 는
    정규화한 글자로는 0.889 지만 별개 사건이다(codex 2026-10-18 #8)."""
    ka, kb = _title_key(a), _title_key(b)
    if not ka or not kb:
        return False
    # 숫자는 원제목(NFKC)에서 소수점째 — 키는 「1.2」 와 「12」 를 같게 만들고 괄호 안을 지운다(codex 구현 #5)
    if _figures(a) != _figures(b):
        return False
    return SequenceMatcher(None, ka, kb).ratio() >= TITLE_DUP


def dedupe(rows):
    """같은 guid 는 처음 것만(여러 카테고리 목록에 같은 기사가 나온다)."""
    seen, out = set(), []
    for r in rows or []:
        if r.get('guid') in seen:
            continue
        seen.add(r.get('guid'))
        out.append(r)
    return out


def _rank_key(r):
    return (MEDIA_RANK.get(r.get('source'), 9) if not r.get('official') else -1,
            -policy_score(r.get('title')))


def preselect(rows, cap=PRESELECT):
    """갈래별 후보. 순위 = 공식 출처 → 매체 등급 → 정책 어휘 수 → 목록 순서(최신)."""
    buckets = {}
    for r in rows or []:
        buckets.setdefault(r['category'], []).append(r)
    out = []
    for cat in DIGEST_CATEGORIES:
        out.extend(sorted(buckets.get(cat, []), key=_rank_key)[:cap])
    return out


def finalize(rows, report_date, per_category=PER_CATEGORY):
    """본문을 받은 뒤 확정 — 본문이 있고 기사면 날짜가 발행일이며 이미 고른 기사와 같은 사건이 아닌 것.

    얇은 갈래를 다른 갈래로 채우지 않는다(US·KR `select` 와 같다).
    """
    taken = []
    for cat in DIGEST_CATEGORIES:
        n = 0
        for r in rows or []:
            if r.get('category') != cat or n >= per_category:
                continue
            if not r.get('body_chars') or (r.get('published') or '')[:10] != report_date:
                continue
            if any(same_event(r.get('title'), t.get('title')) for t in taken):
                continue
            taken.append(r)
            n += 1
    return taken


# ── 기사면 ───────────────────────────────────────────────────────────────
_PUBLISHED = re.compile(r'"datePublished"\s*:\s*"([^"]+)"|<time\b[^>]*dateTime="([^"]+)"', re.I)
_ZW = re.compile('[\u200b-\u200f\u2060\ufeff]')
_BODY_CLASS = 'ArticleDetail__body'
_VOID = ('br', 'img', 'hr', 'meta', 'link', 'input', 'source', 'wbr')


class _Body(HTMLParser):
    """`ArticleDetail__body` 요소가 **닫힐 때까지**의 `<p>` 글자만 모은다(codex 구현 #8). 사진 캡션·
    그림·표·스크립트 아래는 건너뛴다."""

    _SKIP_TAGS = ('script', 'style', 'figure', 'table', 'aside', 'figcaption', 'noscript')

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []           # [(tag, in_body, skip)]
        self.paras, self._cur = [], None

    def handle_starttag(self, tag, attrs):
        if tag in _VOID:
            if tag == 'br' and self._cur is not None:
                self._cur.append('\n')
            return
        cls = dict(attrs).get('class') or ''
        top = self.stack[-1] if self.stack else ('', False, False)
        in_body = top[1] or _BODY_CLASS in cls
        skip = top[2] or tag in self._SKIP_TAGS or 'ArticleBody__caption' in cls
        self.stack.append((tag, in_body, skip))
        if tag == 'p' and in_body and not skip:
            self._cur = []

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break
        if tag == 'p' and self._cur is not None:
            self.paras.append(''.join(self._cur))
            self._cur = None

    def handle_data(self, data):
        top = self.stack[-1] if self.stack else None
        if self._cur is not None and top and top[1] and not top[2]:
            self._cur.append(data)


def page_published(html):
    """기사면 발행 시각(+09:00 ISO). 못 읽으면 None."""
    m = _PUBLISHED.search(html or '')
    if not m:
        return None
    stamp = m.group(1) or m.group(2)
    try:
        return datetime.fromisoformat(stamp).astimezone(JST).isoformat()
    except ValueError:
        return None


def extract_body(html, max_chars=MAX_BODY):
    """기사면 -> 본문. **`ArticleDetail__body` 요소 안**의 문단만 읽는다 — 추천 기사·면책 문구·순위가 `<p>` 로
    이어져 하한을 채운다(codex #10). 유료면이면 ''(앞머리만 있다)."""
    if not html or '_VipPurchase' in html or _BODY_CLASS not in html:
        return ''
    r = _Body()
    try:
        r.feed(html)
        r.close()
    except Exception:
        return ''
    kept = []
    for raw in r.paras:
        lines = [re.sub(r'[ \t\u3000]+', ' ', ln).strip() for ln in _ZW.sub('', raw).split('\n')]
        text = '\n'.join(ln for ln in lines if ln)
        if text:
            kept.append(text)
    body = '\n\n'.join(kept)
    if len(body) < MIN_BODY:
        return ''
    return body[:max_chars]


def body_note(html):
    """`extract_body` 가 왜 비었는지."""
    if '_VipPurchase' in (html or ''):
        return '유료'
    if _BODY_CLASS not in (html or ''):
        return '본문 영역 없음'
    return '짧다'


def official(rows, category):
    """일본은행·닛세이 행 -> 공식 출처 표시와 갈래를 붙인다(허용 목록·제목 분류 우회)."""
    return [dict(r, category=category, official=True) for r in rows or []]
