"""릴리스 인덱스 파싱과 원문 덤프 원장.

US 의 `fetch_releases.py` 와 같은 자리다 — 기관 릴리스를 **파싱하지 않고 텍스트로 덤프**
해 두고 읽는 일은 에이전트에 맡긴다. 다른 점 하나는 헤드라인 지표만 `manifest.py` 가
따로 뽑는다는 것이고, 그 이유는 거기 적어 뒀다.

## 두 가지가 조용한 실패를 막는다

**① 참조월은 제목에서 읽는다.** URL 의 `202608` 은 발표월이고 담긴 데이터는 7월분이다.
URL 로 키를 만들면 모든 지표가 한 달씩 밀린 채 발행된다.

**② 못 받은 것을 원장에 남긴다.** 실패를 버리면 WAF 에 막힌 주가 「발표가 없던 주」와
구분되지 않는다. `fetch_status`·`http_status`·`content_hash` 를 남기고, tier 1 이
발견됐는데 실패했으면 게이트가 발행을 막는다(`gate.check_release_coverage`).

**③ 영문은 늦게 뜬다.** 중문을 먼저 받은 키를 seen 으로 버리면 영영 중문만 남는다.
`should_refetch()` 가 언어 승급을 허용한다.

Design: docs/superpowers/specs/2026-09-05-china-learning-report-design.md
"""

import hashlib
import html as _html
import re
from urllib.parse import urljoin

NBS_INDEX_URL = 'https://www.stats.gov.cn/english/PressRelease/'

# 릴리스 제목 → kind. 제목은 「Consumer Price Index in July 2026」처럼 지표와 참조월을
# 함께 담는다. 여기 없는 제목은 릴리스로 치지 않는다 — 모르는 것을 받아 두는 것보다
# 안 받는 편이 낫고, 그 사실은 원장에 안 남는 것이 아니라 애초에 발견이 아니다.
TITLE_KINDS = (
    (re.compile(r'Purchasing Managers', re.I), 'nbs-pmi'),
    (re.compile(r'Consumer Price Index', re.I), 'nbs-cpi'),
    (re.compile(r'Industrial Producer Price', re.I), 'nbs-ppi'),
    (re.compile(r'Industrial Production Operation', re.I), 'nbs-ip'),
    (re.compile(r'Total Retail Sales', re.I), 'nbs-retail'),
    (re.compile(r'Investment in Fixed Assets', re.I), 'nbs-fai'),
    (re.compile(r'Investment in Real Estate', re.I), 'nbs-property'),
    (re.compile(r'Sales Prices of Commercial Residential', re.I), 'nbs-house-prices'),
    (re.compile(r'Profits of Industrial Enterprises', re.I), 'nbs-industrial-profits'),
    (re.compile(r'Gross Domestic Product', re.I), 'nbs-gdp'),
)

TIERS = {
    'nbs-pmi': 1, 'nbs-cpi': 1, 'nbs-ppi': 1, 'nbs-ip': 1, 'nbs-retail': 1,
    'nbs-fai': 1, 'nbs-property': 1, 'nbs-house-prices': 1, 'nbs-gdp': 1,
    'pboc-afre': 1, 'pboc-lpr': 1, 'customs-trade': 1, 'mof-fiscal': 1,
    'nbs-industrial-profits': 2, 'caixin-pmi': 2,
}

_MONTHS = {m: i + 1 for i, m in enumerate(
    ['January', 'February', 'March', 'April', 'May', 'June', 'July',
     'August', 'September', 'October', 'November', 'December'])}

# 「… in July 2026」·「… for August 2026」·「… from January to July 2026」 — 마지막 월이
# 참조월이다(누계 릴리스는 그 달까지의 누계를 싣는다).
# 월과 연도 사이에 `in`/`of` 가 끼는 표기가 실제로 있다(2026-08-28 공업기업 이익).
_PERIOD = re.compile(
    r'(?:in|for|to)\s+(' + '|'.join(_MONTHS) + r')\s+(?:in\s+|of\s+)?(\d{4})', re.I)
_PUBLISHED = re.compile(r'/t(\d{4})(\d{2})(\d{2})_')
# 앵커 **전체**를 잡는다 — 긴 제목은 링크 텍스트에서 「…Cities in...」로 잘리고 온전한
# 제목은 `title=` 속성에 있다. 텍스트만 보면 참조월이 사라져 tier 1 릴리스가 조용히
# 발견 목록에서 빠진다(2026-09-05 실제 인덱스에서 확인).
_LINK = re.compile(r'<a\b([^>]*)>(.*?)</a>', re.S | re.I)
_HREF = re.compile(r'href="([^"]+)"', re.I)
_TITLE_ATTR = re.compile(r'title="([^"]*)"', re.I)
_TAG = re.compile(r'<[^>]+>')


def _title_kind(title):
    for pat, kind in TITLE_KINDS:
        if pat.search(title):
            return kind
    return None


def parse_nbs_index(html, base=NBS_INDEX_URL):
    """인덱스 HTML → [{key, kind, period, tier, url, title, published}]."""
    out, seen = [], set()
    for attrs, raw in _LINK.findall(html):
        href_m = _HREF.search(attrs)
        if not href_m:
            continue
        href = href_m.group(1)
        attr_title = _TITLE_ATTR.search(attrs)
        text_title = _html.unescape(_TAG.sub('', raw)).strip()
        # 속성 제목이 더 길면 그쪽이 온전한 것이다.
        title = _html.unescape(attr_title.group(1)).strip() if attr_title else ''
        if len(text_title) > len(title):
            title = text_title
        title = re.sub(r'^\d+\.\s*', '', title)
        kind = _title_kind(title)
        if not kind:
            continue
        m = _PERIOD.search(title)
        if not m:
            continue
        period = f'{int(m.group(2)):04d}-{_MONTHS[m.group(1).capitalize()]:02d}'
        key = f'{kind}-{period}'
        if key in seen:
            continue
        seen.add(key)
        pub = _PUBLISHED.search(href)
        out.append({
            'key': key, 'kind': kind, 'period': period, 'tier': TIERS.get(kind, 2),
            'url': urljoin(base, href), 'title': title,
            'published': f'{pub.group(1)}-{pub.group(2)}-{pub.group(3)}' if pub else None,
        })
    return out


def extract_text(html):
    """본문 텍스트. 파싱이 아니라 덤프 — 읽는 일은 에이전트 몫이다."""
    s = re.sub(r'(?is)<(script|style|head)\b.*?</\1>', ' ', html)
    s = re.sub(r'(?s)<!--.*?-->', ' ', s)
    s = _html.unescape(_TAG.sub(' ', s))
    s = re.sub(r'[ \t\xa0]+', ' ', s)
    return '\n'.join(l.strip() for l in s.split('\n') if l.strip())


# 본문이 실제로 그 릴리스인지 본다. HTTP 200 이 곧 본문은 아니다 — WAF 안내문·로그인
# 페이지·오류 페이지가 200 으로 온다. 이걸 통과시키면 수집 장애가 「그 주엔 발표가
# 없었다」로 위장되고, 그것이 이 파이프라인에서 가장 위험한 조용한 실패다.
_BLOCK_CUES = re.compile(
    r'access denied|forbidden|not authorized|请稍后|访问被拒绝|验证码|captcha'
    r'|page not found|404 not found|服务器错误', re.I)

MIN_BODY_CHARS = 300
# 짧은 것이 정상인 공고들. LPR 고시는 두 문장이면 끝난다.
MIN_BODY_BY_KIND = {'pboc-lpr': 60}

_KIND_CUES = {
    'nbs-cpi': ('consumer price', '居民消费价格'),
    'nbs-ppi': ('producer price', '工业生产者'),
    'nbs-pmi': ('purchasing managers', '采购经理'),
    'nbs-ip': ('value added of industrial', '工业增加值'),
    'nbs-retail': ('retail sales', '社会消费品零售'),
    'nbs-fai': ('fixed assets', '固定资产投资'),
    'nbs-property': ('real estate', '房地产'),
    'nbs-house-prices': ('residential', '住宅销售价格'),
    'nbs-gdp': ('gross domestic product', '国内生产总值'),
    'nbs-industrial-profits': ('profits of industrial', '工业企业利润'),
    'pboc-afre': ('aggregate financing', '社会融资规模'),
    'pboc-lpr': ('loan prime rate', '贷款市场报价利率'),
    'customs-trade': ('imports and exports', '进出口'),
    'mof-fiscal': ('fiscal revenue', '财政收入', '一般公共预算收入',
                   '国有土地使用权出让收入', '政府性基金'),
}

_MONTH_NAMES = list(_MONTHS)


_CJK = re.compile(r'[\u4e00-\u9fff]')


def _cjk_ratio(text):
    sample = text[:4000]
    return len(_CJK.findall(sample)) / max(1, len(sample))


def valid_body(kind, text, period):
    """본문이 그 릴리스로 보이면 None, 아니면 사유 문자열."""
    floor = MIN_BODY_BY_KIND.get(kind, MIN_BODY_CHARS)
    # 한자는 같은 내용을 절반 이하 글자로 담는다. 영문 기준 하한을 그대로 들이대면
    # 정상 중문 릴리스가 「너무 짧다」로 걸린다.
    if text and _cjk_ratio(text) > 0.3:
        floor = max(60, floor // 3)
    if not text or len(text) < floor:
        return f'본문이 {len(text or "")}자로 너무 짧다(최소 {floor})'
    # 앞 2,000자만 보면 차단문을 뒤에 두는 것으로 우회된다(codex 3차).
    if _BLOCK_CUES.search(text):
        return '차단·오류 페이지로 보인다'
    low = text.lower()
    cues = _KIND_CUES.get(kind)
    if cues and not any(c.lower() in low for c in cues):
        return f'{kind} 릴리스의 지표 어휘가 본문에 없다'
    # 참조월이 본문에 있어야 한다 — 엉뚱한 달의 페이지를 그 달 것으로 저장하는 사고를
    # 막는다.
    try:
        year, month = period.split('-')
        name = _MONTH_NAMES[int(month) - 1]
    except (ValueError, IndexError):
        return f'참조월이 이상하다: {period!r}'
    # 월만 보면 다른 해의 같은 달 페이지가 통과한다. 연도까지 붙어 있어야 한다.
    abbr = name[:3].lower()
    # 월과 연도 사이에 in/of 가 끼는 표기가 실재한다(2026-08-28 공업기업 이익).
    en_ok = re.search(rf'{abbr}[a-z]*\.?,?\s+(?:in\s+|of\s+)?{year}', low) is not None
    zh_ok = f'{year}年{int(month)}月' in text or f'{int(month)}月' in text and year in text
    if not (en_ok or zh_ok):
        return f'본문에서 참조월({name} {year})을 찾지 못했다'
    return None


def index_looks_broken(discovered):
    """인덱스는 늘 최근 릴리스 십여 건을 싣는다. 0건은 「조용한 주」가 아니라 고장이다."""
    return not discovered


def should_refetch(prev_index, key, language):
    """이미 받은 키를 다시 받을 것인가.

    실패한 것은 언제나 다시 받는다. 성공한 것은 **중문 → 영문 승급일 때만** 다시 받는다
    — 영문 릴리스가 늦게 뜨는데 seen 으로 버리면 영영 중문만 남는다.
    """
    for row in prev_index.get('releases', []):
        if row.get('key') != key:
            continue
        if row.get('fetch_status') != 'ok':
            return True
        return language == 'en' and row.get('language') != 'en'
    return True


def ledger(discovered, fetched, errors, generated=None):
    """발견·성공·실패를 한 원장으로. 실패를 **버리지 않는 것**이 핵심이다."""
    rows = []
    for rel in discovered:
        key = rel['key']
        row = dict(rel)
        row['discovered'] = True
        if key in fetched:
            text, lang = fetched[key]
            why = valid_body(rel['kind'], text, rel['period'])
            row.update(http_status=200, language=lang,
                       content_hash=hashlib.sha256(text.encode('utf-8')).hexdigest(),
                       chars=len(text))
            # 「받았다」와 「그 릴리스를 받았다」는 다르다. 후자가 아니면 ok 가 아니고,
            # tier 1 이면 게이트가 발행을 막는다.
            row['fetch_status'] = 'ok' if why is None else 'invalid'
            if why:
                row['error'] = why
        else:
            code, msg = errors.get(key, (None, 'not attempted'))
            row.update(fetch_status='failed', http_status=code, language=None,
                       content_hash=None, error=msg)
        rows.append(row)
    return {'generated': generated, 'index_ok': True, 'releases': rows}
