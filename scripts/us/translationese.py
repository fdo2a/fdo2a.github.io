"""번역투 자리를 찾아 고칠 꼴을 귀띔한다 — 작성자 마감 점검(2026-10-22).

**고치는 것은 작성자다.** 이 모듈은 자리와 대안 문장을 보여 줄 뿐 글을 바꾸지 않는다. 근거와 문맥을
가진 작성자만 「에 대한」을 지워도 수식 관계가 그대로인지 안다 — 번호만 고르게 한 설계는 「앞으로의
감세 계획 → 앞으로 감세 계획」(시점 이동), 「환율에 대한 시장의 우려 → 환율 시장의 우려」를 막을 장치가
없었다(2026-10-22 codex 설계 검토 2·3차). 그래서 대안은 힌트이고, 판단과 수정은 마감 단계의 작성자 몫이다.

걸지 않는 것: 인과 표지(에 따른·로 인한), 한계 표지(것으로 보인다) — 판단을 싣는 말이라 기존
`style.TRANSLATIONESE` 상한과 작성자 지시문이 맡는다. 피동 전환(에 의해)·명사 수식(를 통한)처럼 국소적인
고칠 꼴이 없는 것도 걸지 않는다.

Pure — 문자열을 받아 목록을 돌려준다. CLI 는 `scripts/scan_translationese.py`.
"""

import re
from collections import namedtuple
from html.parser import HTMLParser

from us.prose_swap import _MARK_RE, _eligible, _mask

# options = [(설명, 바꿀 글)] — 고칠 꼴의 귀띔. 비어 있으면 작성자가 문장을 직접 고친다.
Hit = namedtuple('Hit', 'name start end text options')


def _jong(ch):
    """받침 번호(0 = 없음, 8 = ㄹ). 한글 음절이 아니면 None."""
    if not ch or not '가' <= ch <= '힣':
        return None
    return (ord(ch) - 0xAC00) % 28


def _instrument(text, start):
    j = _jong(text[start - 1:start])
    return [] if j is None else [('(으)로', '로' if j in (0, 8) else '으로')]


# 「과」로 끝나는 명사 — 「성과의 배경」의 과는 조사가 아니다.
_GWA_NOUNS = ('결과', '성과', '효과', '통과', '초과', '경과', '부과', '사과', '학과', '교과', '일과',
              '내과', '외과', '치과', '안과', '분과')
_PASSIVE = {'지': '되', '진': '된', '져': '돼', '졌': '됐', '질': '될'}


def _josa_ui(text, m):
    if m.group(1) == '과' and text[m.start() - 1:m.start() + 1] in _GWA_NOUNS:
        return None
    return [('「의」 삭제', m.group(1))]


# (이름, 정규식, 귀띔 만들기(text, match) → [(설명, 바꿀 글)], 또는 None = 걸지 않음).
# 뒤가 한글로 이어지면 다른 낱말이다(「대한항공」). 「에 대해」는 격을 서술어가 정하므로 귀띔 없이 건다.
RULES = (
    ('에 대한', r'에\s?대(?:한|해(?:서(?:는|도)?|선|도)?)(?![가-힣])',
     lambda t, m: [('삭제', ''), ('관련', ' 관련')] if m.group(0).endswith('한') else []),
    ('조사 결합', r'(와|과|에서|으로|로|에|까지|부터)의(?![가-힣])', _josa_ui),
    ('에 있어서', r'에\s?있어서(?![가-힣])', lambda t, m: [('에서', '에서')]),
    # 띄어 쓴 「는 데」만 — 「가운데 있어」는 자리다.
    ('데 있어', r'(?<=[는은])\s데\s?있어(?:서)?(?![가-힣])', lambda t, m: [('데', ' 데')]),
    ('를 통해', r'[을를]\s?통(?:해서?|하여)(?![가-힣])', lambda t, m: _instrument(t, m.start())),
    ('이중 피동', r'되어([지진져졌질])', lambda t, m: [('되', _PASSIVE[m.group(1)])]),
    ('가지고 있다', r'([을를])\s?가지고\s?있',
     lambda t, m: [('이/가 있', ('이' if m.group(1) == '을' else '가') + ' 있')]),
    ('하는 중이다', r'(?:고\s?있는|(?<=하)는)\s?중이(?=다|었)', lambda t, m: [('고 있', '고 있')]),
)
_COMPILED = [(n, re.compile(p), b) for n, p, b in RULES]

# 인용 안은 남의 말이다 — 다듬는 순간 그 사람이 하지 않은 말이 된다. 엔티티로 적힌 따옴표도 같다(codex 3차 #3).
# 표기를 섞거나(&ldquo;…&#8221;) 앞자리 0 을 붙여도(&#0034;) 풀리지 않게, 엔티티를 같은 길이의 글자로 바꾼
# 사본에서 인용을 찾는다 — 위치는 원문 그대로다(2026-11-05 codex 구현 검토 #1).
_OPEN_CLOSE = (('“', '”'), ('‘', '’'), ('「', '」'), ('『', '』'), ('"', '"'), ("'", "'"))
_QUOTE_CHARS = frozenset(c for pair in _OPEN_CLOSE for c in pair)
_QUOTE = re.compile('|'.join('%s.*?%s' % (re.escape(a), re.escape(b)) for a, b in _OPEN_CLOSE), re.S)
_ENTITY = re.compile(r'&(?:#0*(\d{1,7})|#[xX]0*([0-9a-fA-F]{1,6})|(quot|QUOT|apos|ldquo|rdquo|lsquo|rsquo));')
_NAMED = {'quot': '"', 'QUOT': '"', 'apos': "'", 'ldquo': '“', 'rdquo': '”', 'lsquo': '‘', 'rsquo': '’'}


def _quote_view(text):
    def sub(m):
        dec, hexa, name = m.groups()
        try:
            ch = _NAMED[name] if name else chr(int(dec) if dec else int(hexa, 16))
        except (ValueError, OverflowError):
            return m.group(0)
        if ch not in _QUOTE_CHARS:
            return m.group(0)
        return ch + '\x00' * (len(m.group(0)) - 1)
    return _ENTITY.sub(sub, text)


def find(text):
    """본문(자리표가 들어 있어도 된다)에서 걸린 자리 → [Hit], 문서 순서. 겹치면 앞의 것."""
    quotes = [(m.start(), m.end()) for m in _QUOTE.finditer(_quote_view(text))]
    hits = []
    for name, rx, build in _COMPILED:
        for m in rx.finditer(text):
            if any(a <= m.start() < b for a, b in quotes):
                continue
            options = build(text, m)
            if options is None:
                continue
            hits.append(Hit(name, m.start(), m.end(), m.group(0), options))
    out, last = [], -1
    for h in sorted(hits, key=lambda h: h.start):
        if h.start >= last:
            out.append(h)
            last = h.end
    return out


# 작성자가 다듬을 본문이 아닌 곳. 태그로 정하는 것(인용·목록·제목)과 표식으로 정하는 것(생성 구역)을
# 구조로 읽는다 — 대소문자나 값 없는 속성(`<SECTION DATA-CONTESTED>`)에도 풀리지 않게(codex 3차 #9·#10).
_PROTECT_TAGS = frozenset(('blockquote', 'q', 'li', 'figcaption', 'table',
                           'h1', 'h2', 'h3', 'h4', 'h5', 'h6'))
_PROTECT_ATTRS = ('data-contested', 'data-research-summary', 'data-editor-note', 'data-summary',
                  'data-fed-quote', 'data-fed-change', 'data-fund-board', 'data-fund-kr', 'data-news')
_PROTECT_CLASSES = frozenset(('caption', 'sub', 'muted', 'footer-note', 'source', 'sources', 'src',
                              'note', 'disclaimer', 'fed-trans', 'news-head'))
_VOID = frozenset(('br', 'hr', 'img', 'meta', 'link', 'input', 'source', 'wbr', 'area', 'base',
                   'embed', 'param', 'track', 'col'))


def _guard(tag, attrs):
    names = {k for k, _ in attrs}
    classes = {c.lower() for k, v in attrs if k == 'class' and v for c in v.split()}
    return (tag in _PROTECT_TAGS or any(a in names for a in _PROTECT_ATTRS)
            or bool(classes & _PROTECT_CLASSES))


class _Protected(HTMLParser):
    """보호 요소의 (시작, 끝) 오프셋. 못 닫힌 보호 요소는 문서 끝까지 — 덜 거는 쪽이 안전하다."""

    def __init__(self, html):
        super().__init__(convert_charrefs=False)
        self.offsets = [0]
        # getpos() 는 \n 만 줄로 센다 — splitlines() 는 U+2028 도 끊어 위치가 밀린다(codex 구현 검토 #5).
        for line in html.split('\n'):
            self.offsets.append(self.offsets[-1] + len(line) + 1)
        self.stack, self.spans = [], []
        self.feed(html)
        self.close()
        for _, start, guard in self.stack:
            if guard:
                self.spans.append((start, len(html)))

    def _here(self):
        row, col = self.getpos()
        return self.offsets[row - 1] + col

    def handle_starttag(self, tag, attrs):
        if tag in _VOID:
            return
        self.stack.append((tag, self._here(), _guard(tag, attrs)))

    def handle_endtag(self, tag):
        if not any(t == tag for t, _, _ in self.stack):
            return
        end = self._here() + len('</%s>' % tag)
        while self.stack:
            t, start, guard = self.stack.pop()
            if guard:
                self.spans.append((start, end))
            if t == tag:
                break


def _protected(html):
    try:
        return _Protected(html).spans
    except Exception:  # 구조를 못 읽으면 아무것도 걸지 않는다
        return [(0, len(html))]


class _StartTag(HTMLParser):
    """태그 하나 → (이름, 속성). 시작 태그가 아니면 None."""

    def __init__(self, raw):
        super().__init__(convert_charrefs=False)
        self.got = None
        self.feed(raw)
        self.close()

    def handle_starttag(self, tag, attrs):
        self.got = (tag, attrs)


_END_TAG = re.compile(r'</\s*([a-zA-Z][\w-]*)')
_START_NAME = re.compile(r'<\s*([a-zA-Z][\w-]*)')


def _inline_protected(masked, tags):
    """문단 안의 보호 요소(`<q>`, `<span class="sub">`, 값 없는 `data-contested` …) 구간, 자리표 기준.

    문단 시작점만 보던 판은 문단 안에서 열린 보호 요소를 걸었다(codex 구현 검토 #4). 못 닫히면 문단 끝까지.
    """
    spans, stack = [], []
    for m in _MARK_RE.finditer(masked):
        raw = tags[int(m.group(1))]
        close = _END_TAG.match(raw)
        if close:
            name = close.group(1).lower()
            if any(t == name for t, _, _ in stack):
                while stack:
                    t, start, guard = stack.pop()
                    if guard:
                        spans.append((start, m.end()))
                    if t == name:
                        break
            continue
        try:
            got = _StartTag(raw).got
        except Exception:
            got = None
        if got is None:
            # 못 읽는 시작 태그 — `_mask` 가 속성값 안의 `>` 에서 자른 `<q title="2 >` 따위. 이름만 읽고
            # 보호로 친다(덜 거는 쪽이 안전하다, codex 재검토 #2).
            name = _START_NAME.match(raw)
            if not name:
                continue
            got, guard = (name.group(1).lower(), []), True
        else:
            guard = _guard(*got)
        if got[0] in _VOID:
            continue
        stack.append((got[0], m.start(), guard))
    spans.extend((start, len(masked)) for _, start, guard in stack if guard)
    return spans


def flag(html):
    """문단 이름 → [Hit]. 이름은 prose_swap.extract 와 같고, 위치는 그 문단의 마스킹된 글 기준이다."""
    spans = _protected(html)
    out = {}
    for pid, m in _eligible(html):
        if any(a <= m.start() < b for a, b in spans):
            continue
        masked, tags = _mask(m.group(2))
        quoted = _inline_protected(masked, tags)
        hits = [h for h in find(masked) if not any(a <= h.start < b for a, b in quoted)]
        if hits:
            out[pid] = hits
    return out
