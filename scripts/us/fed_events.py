"""연준 이벤트 — 무엇이 열렸는지 가리고, 원문을 어디서 가져올지 정하고,
발행본의 인용이 그 원문에 실제로 있는지 대조하는 순수 함수들.

**이 파일에 네트워크는 없다.** 수집은 `scripts/collect_fed_events.py`, 검사는
`scripts/us/fed_gate.py` 가 맡고 여기는 둘이 공유하는 판정만 담는다 —
`macro_metrics.py` / `macro_gate.py` 와 같은 갈래다.

존재 이유는 하나다. FOMC 와 잭슨홀은 **의장이 무슨 말을 했느냐가 그날의 전부**인데,
그 말은 데이터 파일에 숫자로 안 들어온다. 그렇다고 기억이나 기사 요약으로 옮겨 적으면
**따옴표 안의 문장을 지어내는 일**이 된다 — 수치 창작보다 나쁘다. 숫자는 게이트가
데이터와 맞대 볼 수 있지만, 지어낸 인용문은 그럴듯할수록 안 걸린다.

그래서 규율을 뒤집었다. **원문을 먼저 받아 두고, 발행본의 인용이 그 원문에 글자
그대로 있는지 대조한다.** 원문을 못 받은 이벤트는 인용 자체를 금지한다(삭제 > 창작).

의장이 누구인지는 하드코딩하지 않는다. 2026-09-02 실측에서 연설 피드의 제목은
「Warsh, In Our Time」처럼 **성만 있고 직함이 없다.** 직함은 연설문 페이지 본문의
서명줄(「Chairman Kevin Warsh」)에 있으므로 거기서 읽는다. 의장은 바뀐다.
"""

import datetime as _dt
import difflib
import re

# 피드 셋. 통화정책 보도자료(성명·의사록·경제전망)와 연설·증언.
FEEDS = {
    'press_monetary': 'https://www.federalreserve.gov/feeds/press_monetary.xml',
    'speeches': 'https://www.federalreserve.gov/feeds/speeches.xml',
    'testimony': 'https://www.federalreserve.gov/feeds/testimony.xml',
}

# 며칠 전 문서까지 훑을 것인가. 하루 한 번 도는 수집이 주말·휴일에 걸려 빠지는 것을
# 메우는 폭이지, 오래된 문서를 오늘 것처럼 싣기 위한 폭이 아니다 — 실제 발행 여부는
# `first_seen` 이 정한다.
WINDOW_DAYS = 4

_ITEM_RE = re.compile(r'<item>(.*?)</item>', re.S)
_CDATA = re.compile(r'^\s*<!\[CDATA\[(.*?)\]\]>\s*$', re.S)
_TAG = re.compile(r'<[^>]+>')
_SLUG_DATE = re.compile(r'/([a-z]+)(\d{8})[a-z]?\d?\.(?:htm|pdf)', re.I)


def _field(block, name):
    m = re.search(r'<%s>(.*?)</%s>' % (name, name), block, re.S)
    if not m:
        return ''
    raw = m.group(1)
    c = _CDATA.match(raw)
    return _unescape(c.group(1) if c else raw).strip()


def _unescape(s):
    import html as _h
    return _h.unescape(s)


_MONTHS = {m: i + 1 for i, m in enumerate(
    'Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec'.split())}


def parse_pubdate(raw):
    """RFC-822 pubDate -> 'YYYY-MM-DD'. 못 읽으면 None.

    `email.utils` 를 쓰지 않는 이유는 시간대 변환을 하지 않기 위해서다 — 피드는
    GMT 로 찍히고 우리가 쓰는 것은 «어느 날 공개된 문서인가» 뿐이다. 21:00 GMT 를
    현지시로 옮기면 날짜가 하루 밀린다.
    """
    m = re.search(r'(\d{1,2})\s+([A-Z][a-z]{2})\s+(\d{4})', raw or '')
    if not m or m.group(2) not in _MONTHS:
        return None
    return '%04d-%02d-%02d' % (int(m.group(3)), _MONTHS[m.group(2)], int(m.group(1)))


def parse_feed(xml):
    """RSS -> [{title, link, description, published}]. 순서는 피드 순서."""
    out = []
    for m in _ITEM_RE.finditer(xml or ''):
        b = m.group(1)
        link = _field(b, 'link')
        if not link:
            continue
        out.append({
            'title': _field(b, 'title'),
            'link': link,
            'description': _field(b, 'description'),
            'published': parse_pubdate(_field(b, 'pubDate')),
        })
    return out


def slug_date(link):
    """연준 URL 안의 날짜. `/speech/warsh20260828a.htm` -> '20260828'."""
    m = _SLUG_DATE.search(link or '')
    return m.group(2) if m else None


def slug_name(link):
    """연설 URL 안의 성. `/speech/warsh20260828a.htm` -> 'warsh'."""
    m = _SLUG_DATE.search(link or '')
    return m.group(1).lower() if m else None


def in_window(items, report_date, days=WINDOW_DAYS):
    """`report_date` 이하이고 그로부터 `days` 일 이내에 공개된 항목."""
    try:
        end = _dt.date.fromisoformat(report_date)
    except (TypeError, ValueError):
        return []
    start = end - _dt.timedelta(days=days)
    out = []
    for it in items:
        try:
            d = _dt.date.fromisoformat(it.get('published') or '')
        except ValueError:
            continue
        if start <= d <= end:
            out.append(it)
    return out


# ── 분류 ────────────────────────────────────────────────────────────────────
# tier 1 = 그날 리포트가 한 섹션을 통째로 내주는 자리. tier 2 = 있으면 다루되
# 섹션을 열 이유는 되지 않는 것.

KINDS = {
    'fomc_statement':   ('FOMC 성명', 1),
    'fomc_projections': ('FOMC 경제전망(SEP)', 1),
    'presconf':         ('FOMC 기자회견 전문', 1),
    'jackson_hole':     ('잭슨홀 의장 연설', 1),
    'chair_speech':     ('의장 연설', 1),
    'chair_testimony':  ('의장 의회 증언', 1),
    'fomc_minutes':     ('FOMC 의사록', 2),
}

_PRESS_RULES = (
    (re.compile(r'issues FOMC statement', re.I), 'fomc_statement'),
    (re.compile(r'release[s]? .*economic projections', re.I), 'fomc_projections'),
    (re.compile(r'Minutes of the Federal Open Market Committee', re.I), 'fomc_minutes'),
)

# 「Minutes of the Board's discount rate meetings」는 FOMC 의사록이 아니다 —
# 할인율은 지역 연은 이사회가 신청하고 이사회가 승인하는 별개 절차다.
_PRESS_EXCLUDE = re.compile(r"Minutes of the Board", re.I)


def press_kind(title):
    """통화정책 보도자료 제목 -> 종류. 해당 없으면 None."""
    t = title or ''
    if _PRESS_EXCLUDE.search(t):
        return None
    for rx, kind in _PRESS_RULES:
        if rx.search(t):
            return kind
    return None


# 「Vice Chair for Supervision」이 「Chair」로 읽히면 부의장 연설이 의장 발언으로
# 실린다. 긴 직함부터 맞춘다.
_ROLES = ('Vice Chair for Supervision', 'Vice Chairman', 'Vice Chairwoman',
          'Vice Chair', 'Chairman', 'Chairwoman', 'Chair', 'Governor')
# 이름은 대문자 낱말 1~3 개인데, 서명줄 바로 뒤에 오는 「At the …」·「Before the …」도
# 대문자로 시작한다. 그것까지 이름으로 삼으면 「Kevin Warsh At」이 된다.
_NOT_NAME = r'(?!At\b|Before\b|Share\b|On\b|In\b|To\b|For\b|Via\b)'
_NAME = _NOT_NAME + r"[A-Z][A-Za-z.'’-]+"
_ROLE_RE = re.compile(
    r'\b(' + '|'.join(_ROLES) + r')\s+(' + _NAME + r'(?:\s+' + _NAME + r'){0,2})')
CHAIR_ROLES = frozenset(('Chairman', 'Chairwoman', 'Chair'))

_JACKSON = re.compile(r'Jackson Hole|economic policy symposium', re.I)


def flatten(html_doc):
    """페이지 -> 한 줄 텍스트. 서명줄과 개최지를 읽기 위한 최소 처리."""
    t = re.sub(r'<(script|style)[^>]*>.*?</\1>', ' ', html_doc or '', flags=re.S)
    return re.sub(r'\s+', ' ', _unescape(_TAG.sub(' ', t))).strip()


def byline(page_text, speech_title=''):
    """(직함, 이름). 못 찾으면 (None, None).

    제목 바로 뒤를 본다 — 페이지 머리말·안내문에도 「Chair」가 나오므로 문서 전체를
    훑으면 엉뚱한 직함을 집는다. 제목을 못 찾으면 앞부분만 훑는 폴백을 쓴다.
    """
    text = page_text or ''
    start = text.find(speech_title) + len(speech_title) if speech_title and speech_title in text else 0
    m = _ROLE_RE.search(text[start:start + 400] if start else text[:3000])
    if not m:
        return None, None
    return m.group(1), m.group(2).strip()


def speech_kind(item, page_text, feed='speeches'):
    """연설·증언 항목 -> (kind, 직함, 이름). 의장이 아니면 None.

    의장 여부는 **연설문 페이지의 서명줄**이 정한다. 피드 제목에는 성만 있고
    직함이 없다(2026-09-02 실측: 「Warsh, In Our Time」).
    """
    title = (item.get('title') or '')
    speech_title = title.split(',', 1)[1].strip() if ',' in title else title
    role, name = byline(page_text, speech_title)
    if role not in CHAIR_ROLES:
        return None
    if feed == 'testimony':
        return 'chair_testimony', role, name
    blob = ' '.join((title, item.get('description') or '', (page_text or '')[:2000]))
    if _JACKSON.search(blob):
        return 'jackson_hole', role, name
    return 'chair_speech', role, name


def event_key(kind, date8):
    """파일 이름이자 발행본의 `data-fed-quote` 키. 사람이 읽을 수 있게 둔다."""
    return '%s-%s' % (kind.replace('_', '-'), date8)


# ── 원문 후보 ────────────────────────────────────────────────────────────────

def statement_sources(date8, link):
    """FOMC 성명일에 열어 볼 문서들. 순서가 곧 중요도다.

    기자회견 전문은 회의 3주쯤 뒤에 올라오므로 성명 당일에는 대개 404 다(2026-09-02
    실측: 06-17 전문 200 / 08-19 전문 404). 그래서 **실패가 정상인 후보**로 두고,
    나중에 올라오면 그날 `presconf` 이벤트로 따로 뜬다.
    """
    base = 'https://www.federalreserve.gov'
    return [
        {'role': 'statement', 'label': 'FOMC 성명 전문', 'url': link},
        {'role': 'impl_note', 'label': '정책 실행 지침',
         'url': '%s/newsevents/pressreleases/monetary%sa1.htm' % (base, date8)},
        {'role': 'projections', 'label': '경제전망 요약(SEP)',
         'url': '%s/monetarypolicy/files/fomcprojtabl%s.pdf' % (base, date8)},
        {'role': 'presconf', 'label': '기자회견 전문',
         'url': '%s/mediacenter/files/FOMCpresconf%s.pdf' % (base, date8)},
    ]


def presconf_url(date8):
    base = 'https://www.federalreserve.gov'
    return '%s/mediacenter/files/FOMCpresconf%s.pdf' % (base, date8)


def sources_for(kind, date8, link):
    if kind == 'fomc_statement':
        return statement_sources(date8, link)
    if kind == 'presconf':
        return [{'role': 'presconf', 'label': '기자회견 전문', 'url': presconf_url(date8)}]
    label = KINDS.get(kind, (kind, 2))[0]
    return [{'role': 'primary', 'label': label, 'url': link}]


# ── 인용 대조 ────────────────────────────────────────────────────────────────

# 발행본은 조판된 따옴표·줄표를 쓰고 원문 PDF 는 또 다른 문자를 쓴다. 같은 문장을
# 다른 글자로 적었다는 이유로 막으면 게이트가 매일 오탐으로 죽고, 그러면 꺼진다.
_QUOTE_MAP = {
    '“': '"', '”': '"', '‘': "'", '’': "'", '‚': "'",
    '–': '-', '—': '-', '−': '-', ' ': ' ', '‐': '-',
    '‑': '-', 'ﬁ': 'fi', 'ﬂ': 'fl',
}
# 인용 중간을 생략한 표시. 여기서 문장이 끊기므로 조각을 나눠 각각 대조한다.
_ELLIPSIS = re.compile(r'\[\s*\.\.\.\s*\]|\[\s*…\s*\]|…|\.\.\.')
# 조각이 이보다 짧으면 대조에 의미가 없다 — 짧은 구절은 아무 문서에나 들어 있다.
SEGMENT_MIN = 25
QUOTE_MIN = 40
# 생략은 두 번까지. 세 번 넘게 끊긴 인용은 발언이 아니라 편집물이다.
MAX_ELISIONS = 2
# 조각 사이 허용 거리. 2026-07-29 기자회견 속기록 실측에서 «한 사람의 한 발언»은
# 90분위 1,799자·95분위 1,967자였다. 2,000자면 한 답변 안의 생략은 전부 통과하고,
# 서로 다른 질문에 대한 답을 잇는 것은 막힌다.
SEGMENT_GAP_MAX = 2000


def normalize(text):
    """대조용 표준형 — 따옴표·줄표를 통일하고 공백을 하나로 접는다."""
    t = _unescape(_TAG.sub(' ', text or ''))
    for a, b in _QUOTE_MAP.items():
        t = t.replace(a, b)
    return re.sub(r'\s+', ' ', t).strip()


def quote_fragments(quote):
    """생략 표시로 나눈 **모든** 조각. 짧다고 버리지 않는다.

    버리면 안 되는 이유가 이 함수의 존재 이유다. 예전에는 짧은 조각을 조용히
    걸러냈고, 그래서 「We do [...] expect it would be appropriate to reduce」가
    통과했다 — 부정어를 담은 「We do not」의 「not」만 생략 표시 뒤로 숨기면 남는
    조각은 원문 그대로라 대조를 통과하고, 지면에는 정반대 뜻이 남는다
    (2026-09-02 codex 검토에서 실증).
    """
    return [f for f in (s.strip(' ,;:-"\'') for s in _ELLIPSIS.split(normalize(quote))) if f]


def quote_segments(quote):
    """조각 중 **근거로 쓸 만큼 긴 것**. 변경점 블록 대조에 쓴다."""
    return [f for f in quote_fragments(quote) if len(f) >= SEGMENT_MIN]


def verify_quote(quote, corpus):
    """인용이 원문과 어긋나는 지점을 설명하는 문장. 어긋남이 없으면 None.

    조각이 저마다 원문 어딘가에 있다는 것으로는 모자란다. **순서대로, 서로 가까이**
    나와야 한다 — 40,000자짜리 기자회견 속기록에서 9,000자 떨어진 두 답변을 이으면
    각 조각은 진짜인데 이어 붙인 문장은 의장이 한 적 없는 말이 된다(2026-09-02
    자체 공격에서 실증: 「경제가 견조하다」와 「우리는 그것을 두려워하지 않았다」가
    한 인용으로 붙었다).
    """
    frags = quote_fragments(quote)
    if not frags:
        return '인용에 대조할 내용이 없다'
    if len(frags) - 1 > MAX_ELISIONS:
        return (f'생략이 {len(frags) - 1}번이다 — {MAX_ELISIONS}번까지만 쓴다. '
                '토막을 이어 붙인 인용은 원문에 없는 문장이 된다')
    for f in frags:
        if len(f) < SEGMENT_MIN:
            return (f'대조하기에 너무 짧은 조각 — 「{f[:40]}」({len(f)}자). '
                    f'{SEGMENT_MIN}자 미만 조각은 생략 표시로 감싸 넘길 수 없다')
    norm = normalize(corpus)
    at = None
    for f in frags:
        i = norm.find(f) if at is None else norm.find(f, at)
        if i < 0:
            if f in norm:
                return f'원문에는 있지만 인용이 원문 순서를 뒤집었다 — 「{f[:50]}」'
            return f'원문에 없는 조각 — 「{f[:50]}」'
        if at is not None and i - at > SEGMENT_GAP_MAX:
            return (f'앞 조각에서 {i - at:,}자 떨어진 조각 — 「{f[:50]}」. '
                    f'{SEGMENT_GAP_MAX:,}자 넘게 떨어진 발언을 이으면 따로 한 말이 '
                    '한 문장이 된다')
        at = i + len(f)
    return None


# 원문이 «단위를 달고» 적은 수치만 허용 집합에 넣는다. 예전에는 원문의 모든 숫자를
# 넣었고, 그러면 40,000자 속기록의 페이지 번호·전화번호까지 허용돼 무관한 거짓 주장이
# 세탁됐다(2026-09-02 codex 검토: 원문의 「2 percent」가 근거 없는 「하이일드 스프레드
# 2%」를 통과시켰다). 좁혀도 남는 한계는 분명하다 — **어느 값이 어느 지표에 속하는지는
# 못 본다.** 그럴듯한 값끼리의 뒤바뀜은 사람이 잡는다(채권 게이트와 같은 한계).
_UNIT = re.compile(r'percentage points?|percent|per cent|basis points?|\bbps?\b|%', re.I)
# 연준은 금리를 분수로 적는다 — 「4-1/4 to 4-1/2 percent」·「3¾ percent」.
# 한국어 발행본은 소수로 인쇄하므로 그 변환까지 허용 집합에 넣는다.
_VULGAR = {'¼': .25, '½': .5, '¾': .75, '⅛': .125, '⅜': .375, '⅝': .625, '⅞': .875,
           '⅓': 1 / 3, '⅔': 2 / 3}
_NUM_EXPR = re.compile(
    r'(\d[\d,]*(?:\.\d+)?)\s*(?:[-–—]\s*(\d+)\s*/\s*(\d+)|([¼½¾⅛⅜⅝⅞⅓⅔]))?')
# 단위 앞 이 폭 안의 수치를 그 단위의 값으로 본다. 「4-1/4 to 4-1/2 percent」처럼
# 범위로 적힌 두 끝을 모두 잡을 만큼은 넓고, 앞 문장까지 끌어오지는 않을 만큼 좁다.
UNIT_WINDOW = 40


def source_numbers(text):
    """원문이 단위를 달고 적은 수치. 발행본이 인용해도 되는 값에 더한다.

    성명문의 「2 percent」나 「4-1/4 to 4-1/2 percent」를 옮겨 적는 것이 이 섹션의
    일인데 그 값은 어느 데이터 파일에도 없다. 그래서 **그 이벤트로 실제로 받아 둔
    문서**가 단위와 함께 적은 값만 넣는다.
    """
    t = normalize(text)
    out = set()

    def add(v):
        out.add(round(v, 4))
        for d in (1, 2, 3):
            out.add(round(v, d))

    for u in _UNIT.finditer(t):
        window = t[max(0, u.start() - UNIT_WINDOW):u.start()]
        for m in _NUM_EXPR.finditer(window):
            try:
                v = float(m.group(1).replace(',', ''))
            except ValueError:
                continue
            add(v)
            if m.group(2) and m.group(3):
                try:
                    add(v + float(m.group(2)) / float(m.group(3)))
                except (ValueError, ZeroDivisionError):
                    pass
            elif m.group(4):
                add(v + _VULGAR[m.group(4)])
    return out


# ── 성명문 변경점 ─────────────────────────────────────────────────────────────

_SENT_SPLIT = re.compile(r'(?<=[.?!])\s+(?=["\'(]?[A-Z])')
# 성명 페이지 앞뒤의 항해·안내 문구를 걷어낸다. 본문은 「Recent indicators」나
# 「The Committee」로 시작하고 「Voting for the monetary policy action」에서 끝난다.
_BODY_START = re.compile(r'(Recent indicators|Information received|Available information|Economic activity|The Committee)')
_BODY_END = re.compile(r'(Voting (?:for|against) the monetary policy action|'
                       r'Implementation Note issued|For media inquiries)')


def statement_body(text):
    """성명 페이지 텍스트에서 본문만. 본문 시작을 못 찾으면 **None**.

    못 찾았을 때 원문을 그대로 돌려주면 안 된다. 페이지 머리말(「Skip to main
    content」·쿠키 안내)이 통째로 본문이 되어 변경점이 스무 건씩 잡히고, 그러면
    「무엇이 바뀌었나」가 신호가 아니라 소음이 된다(2026-09-02 실측: 성명이 아닌
    의사록 페이지를 넣었을 때 add 20·removed 7). 자를 수 없으면 비교하지 않는다.
    """
    t = normalize(text).lstrip('\ufeff').strip()
    s = _BODY_START.search(t)
    if not s:
        return None
    t = t[s.start():]
    e = _BODY_END.search(t)
    if not e:
        # 끝 앵커가 없으면 자르지 않는다. 예전에는 통째로 본문 삼았고, 그러면
        # 페이지 푸터 문구 변화가 「성명이 이렇게 바뀌었다」로 인쇄된다
        # (2026-09-02 codex 검토: 푸터 변경이 ratio 0.939 로 변경점에 올랐다).
        return None
    return t[:e.start()].strip()


def sentences(text):
    return [s.strip() for s in _SENT_SPLIT.split(text or '') if s.strip()]


def redline(prev_text, curr_text, cutoff=0.55):
    """직전 성명 대비 변경점. {'added', 'removed', 'changed', 'kept'}. 자를 수 없으면 None.

    문장 단위로 맞춘 뒤 남은 것끼리 닮은 정도로 짝을 짓는다. 짝이 지어지면
    「고쳐 쓴 문장」이고, 안 지어지면 통째로 들어오거나 빠진 문장이다. 성명문은
    한 단어를 바꿔 신호를 주는 문서라 **어느 문장이 어떻게 바뀌었는지**가 알맹이다.
    """
    prev_body, curr_body = statement_body(prev_text), statement_body(curr_text)
    if prev_body is None or curr_body is None:
        return None
    a, b = sentences(prev_body), sentences(curr_body)
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    removed, added, kept = [], [], 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == 'equal':
            kept += i2 - i1
        else:
            removed.extend(a[i1:i2])
            added.extend(b[j1:j2])

    changed, used = [], set()
    for new in list(added):
        best, score = None, cutoff
        for old in removed:
            if id(old) in used:
                continue
            r = difflib.SequenceMatcher(None, old, new, autojunk=False).ratio()
            if r > score:
                best, score = old, r
        if best is not None:
            used.add(id(best))
            changed.append({'before': best, 'after': new, 'ratio': round(score, 3)})
            added.remove(new)
    removed = [s for s in removed if id(s) not in used]
    return {'added': added, 'removed': removed, 'changed': changed, 'kept': kept}
