"""Publication gate for Telegram-sourced sentences (2026-11-06). Used by scripts/check_telegram.py.

Contract (writers: brief-report-writer.md / kr-report-writer.md 「텔레그램 견해·의견」):
- every Telegram-derived sentence sits inside an element carrying data-tg="<item id>";
- view  : names the firm and the analyst (「키움증권 한지영 연구원은 …로 봤다」);
- report: names the outlet and reads as that outlet's report (「로이터에 따르면」);
- opinion: reads as an opinion (「…라는 의견도 나왔다」) and names the credited outlet if any;
- numbers inside the element come from that item's summary_ko; at most 3 views and 3 others;
- no channel name, 「텔레그램」 or t.me anywhere; firm/analyst names never outside the elements;
- a sentence outside the elements that largely repeats a Telegram summary is blocked.
What it cannot see: a sentence that says the OPPOSITE of the summary with the same words and
numbers — that is left to the post-publish review. The editor's note (human text) is exempt.

layout='news' (2026-11-12, the news posts `/news/`·`/kr/news/`) adds, on top of the above:
- all data-tg elements sit in ONE `<section data-tg-section>` whose tags are exactly
  h2(「증권사 견해·시장 의견」) · div.card · p+, each p = (text | span[data-tg])+ with at least one
  marker — nothing hidden, no other tag. 2026-11-14 (사용자 지시 「조각조각 요약한 것 밖에 안되잖아 …
  하나의 완성된 글이 되어 발행되도록」): a paragraph is a topic, not an item, so it may weave several
  markers and carry linking text between them;
- the file comes from `scripts/tg_news.py input` and the item is `news_use: true`;
- no cap on how many (2026-11-12 사용자 지시 — 그날 시장을 지배한 이슈·중요한 내용은 싣는다), but an
  item is quoted once, a marker is at most 300 chars, and its overlap with the summary >= 0.45;
- who is speaking is always written inside the marker, never inferred from the data alone: the
  name, or — right after a marker of the same source/analyst in the same paragraph, nothing but
  spaces between — a back-reference at the very start (「같은 보도는」, 「한 연구원은」). An unsourced
  item right after an attributed one starts with a new speaker (「시장에서는」);
- linking text (inside a p, outside the markers): no digit, no firm/analyst/outlet name, a piece
  <= 80 chars and not a copy of a summary (>= 0.7), all of it <= 20% of the section;
- a sentence OUTSIDE the elements that repeats any summary in the file (>= 0.7) FAILS — the news
  posts have no post-publish review. Block boundaries are kept when splitting, and only two things
  are left out: the stored news summary inside `p[data-summary]` and `section[data-contested]`.
layout='jp' (2026-11-15, the Japan daily `/japan/daily/`) is the news layout with these differences:
- the section is `<section data-section="views" data-tg-section>` = h2(「증권사 견해·시장 의견」) · p+,
  each p exactly one `<span data-tg>` — one item, one paragraph, no linking text (`views_node`);
- outside the section nothing is left out of the comparison. A sentence that repeats a Telegram
  summary (>= 0.7) fails unless an article of **the day's news file** says it at least as closely
  (`_jp_articles`): the prose of a Japan daily is written from that file, and a note about the
  same release would otherwise fail the writer's own sentences (11/16 실측: 발행본 14편 중 11편). A
  sentence closer to the note than to every article is the note's. The page's markup decides
  none of this;
- an opinion with no outlet reads as hearsay (`RELAY_WORDS` — a bare 「평가했다」 is a direct
  statement); a broker name (`tg_jp.RELAY_FIRMS`) is the item's `relay_firm` or stands in its summary;
- 엔 amounts are figures with a unit; every date in a marker is the note's own date or stands in
  the summary, and a note dated before the session names its day.
Design: docs/superpowers/specs/2026-11-15-telegram-japan-daily.md
The overlap floor is not a check of meaning (the same words can say the opposite), and whether a
sentence READS as the right speaker's is not something code can settle; the routine reads every
paragraph in order and each marker next to its summary as its last step (`paras`, `pairs`).
Design: docs/superpowers/specs/2026-11-12-telegram-news-posts.md
"""
import html as _html
import re
from difflib import SequenceMatcher
from html.parser import HTMLParser

from .hidden import VOID, fragment_hidden, is_hidden
from .numbers import strip_comments
from .telegram import CHANNEL_WORDS, FIRM_HANWHA, FIRM_KIWOOM, POST_MAX_OPINIONS, POST_MAX_VIEWS
from . import tg_jp
from .tg_junk import refusal

NOTE_RE = re.compile(r'<section\b[^>]*\bdata-editor-note\s*=\s*"[^"]*"[^>]*>.*?</section>', re.S)
OPEN_RE = re.compile(r'<([a-zA-Z][\w-]*)\b([^>]*?)\bdata-tg\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^\s>]+))([^>]*)>', re.I)
TAG_RE = re.compile(r'<[^>]+>')
BANNED = re.compile(r't\.me/|telegram\.me|텔레그램|Telegram', re.I)
OPINION_WORDS = re.compile(r'의견|시각|관측|해석|전망|평가|주장|지적|우려|분석|목소리|얘기|소식|전해|제기|나왔')
REPORT_WORDS = re.compile(r'따르면|보도|전했|밝혔|의하면|보도했')
MIN_COVERAGE = 0.3       # share of the element's text that matches its summary
OUTSIDE_COVERAGE = 0.7   # a sentence outside the elements this close to a summary is blocked
OUTSIDE_MIN_CHARS = 25

NEWS_TITLE = '증권사 견해·시장 의견'
NEWS_MAX_CHARS = 300            # visible chars of one paragraph, spaces included — a quote, not the summary again
NEWS_MIN_COVERAGE = 0.45        # 기존 인용 14문장의 최저 0.53
# Outside the elements: anything of 25+ chars, and a complete sentence (-다/-요) of 10-24.
# 기존 18편 2,216조각의 최대 겹침 0.64. Without the sentence condition 「11월 11일 종가 기준」 같은
# 10-11자 조각이 0.7 을 넘는다(7건).
NEWS_OUTSIDE_SHORT = 10
NEWS_LINK_MAX_CHARS = 80        # one piece of linking text — a topic sentence, not a paragraph of its own
NEWS_LINK_MAX_SHARE = 0.2       # linking text is what no summary vouches for; keep it a small share
NEWS_LINK_MIN_COMPARE = 10      # 「반면」「이어」 match any summary by two characters
# a quantity in words is still a figure no summary vouches for: 「세 차례」「서너 차례」「스물한 번」「두 배」
# 「수백 건」「수십억 달러」「절반」 (구현 검토 1회 #1, 2회 #2). Measured on the 208 published posts
# (2026-11-14): a one-syllable numeral glued to its counter is far more often another word —
# 「조건」 420 times, 「서명」「조명」「천명」「서해」「이억원」(a name) — so it counts only when written
# apart (「한 번」) or when the numeral has two syllables or more (「서너차례」「다섯개」); 「수」 joins only
# counters it makes no word with (「수주」 is orders, 3회 #2); a Sino-Korean numeral counts only as
# 「수십·수백·수천 …」 — the others come with a digit, which `\d` already stops (「일원」「사원」, 2회 #3).
# 「곳」「가지」 are left out: 「견해는 한 곳으로 모였다」「두 가지로 갈렸다」 are what linking text says.
# This is a net for the common forms, not a boundary — words can state a quantity in ways no list
# ends (「거듭」「연거푸」). Linking text that states a fact is for the routine's reading to delete.
_Q_END = r'(?=$|[^가-힣]|[가이은는을를도의에로와과만나씩째]|으로|까지)'
_NATIVE = r'(?:한|두|세|네|서|너|석|넉|댓|다섯|여섯|일곱|여덟|아홉|열|스무|스물|서른|마흔|쉰|예순|일흔|여든|아흔|몇|여러|대여섯|예닐곱)+'
_NATIVE_Q = re.compile(r'(?<![가-힣])(' + _NATIVE + r')(\s?)(?:차례|번|배|개|건|명|달|주|해|분기|개월|종목|거래일|년)' + _Q_END)
_OTHER_Q = re.compile(
    r'(?<![가-힣])수(?:\s?(?:차례|년|개월|거래일|분기)|\s(?:번|배|개|곳|건|명|달|주|해|종목))' + _Q_END +
    r'|(?<![가-힣])수[십백천만억조]+\s?(?:퍼센트|프로|배|달러|원|포인트|bp|건|명|개|곳|차례|번|종목|년|개월)' + _Q_END +
    r'|(?<![가-힣])(?:절반|갑절|반토막)')      # at a word start: 「거절반응」 is not a half (구현 검토 6회, 한도로 중단된 회차)


def link_quantity(text):
    """The first quantity written in words, or None."""
    for m in _NATIVE_Q.finditer(text or ''):
        if m.group(2) or len(m.group(1)) >= 2:
            return m.group(0)
    m = _OTHER_Q.search(text or '')
    return m.group(0) if m else None
_LEAD = r'^(?:(?:또한|또|이어서|이어|한편|반면|다만|여기에|이와 달리|이에 대해)[,\s]*)?'
_END = r'(?=[\s,])'             # the word really ends here — 「같은 보도자료」「시장은행은」 are other words (설계 검토 3회 #1)
# a back-reference to the outlet / the analyst of the marker right before (설계 검토 2회 #3)
SAME_SOURCE = re.compile(_LEAD + r'(?:같은|이|해당|그)\s?(?:보도|매체|기사|신문|통신)(?:은|는|도|가|이|에 따르면|에 의하면|에서는|에서도)' + _END)
SAME_ANALYST = _LEAD + r'(?:(?:{surname}\s?(?:연구원|애널리스트|위원)|같은 연구원|그 연구원)(?:은|는|도)|그는|그도)' + _END
# a new speaker at the very start of an unsourced item that follows an attributed one (1회 #1, 2회 #1)
NEW_SPEAKER = re.compile(_LEAD + r'(?:(?:시장|업계|증권가|월가|투자자들?)(?:\s?(?:일각|안팎))?(?:에서는|에서도|에서|에는|은|는|\s?사이에서는|\s?사이에서도)'
                                 r'|일각에서(?:는|도)?)' + _END)

_VOID = frozenset(('br', 'img', 'hr', 'input', 'meta', 'link', 'area', 'base', 'col', 'embed', 'source', 'track', 'wbr'))
_INERT = ('template', 'details', 'noscript', 'script', 'style')
_BLOCK = re.compile(r'</?(?:p|h[1-6]|li|ul|ol|div|section|article|header|footer|nav|main|aside|table|tr|td|th|thead|'
                    r'tbody|tfoot|caption|figcaption|figure|blockquote|details|summary|dt|dd|dl|br|hr|title|pre)\b[^>]*>', re.I)
_SUMMARY_P = re.compile(r"""<p\b[^>]*?\bdata-summary\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))[^>]*>(.*?)</p>""", re.S | re.I)
_CONTESTED_OPEN = re.compile(r'<section\b[^>]*\bdata-contested\b[^>]*>', re.I)
_SENT_END = re.compile(r'[다요]["”’)\]]*$')


UNITS = r'%p|%|퍼센트|bp|배|억\s*달러|억\s*원|조\s*원|만\s*달러|달러|원|억|조|만|포인트|pt|년물|bp'
NUM_RE = re.compile(r'(-?\d[\d,]*(?:\.\d+)?)\s*(' + UNITS + r')?')
DATE_MASK = re.compile(r'\d{4}-\d{2}-\d{2}|\d{4}년|\d{1,2}월|\d{1,2}일|\d{1,2}/\d{1,2}|\d{1,2}분기|\d{1,2}시|\d{1,2}분')


# Japan daily only: a yen amount is a figure with a unit (「3,800엔」 is not 「3,800원」)
JP_NUM_RE = re.compile(r'(-?\d[\d,]*(?:\.\d+)?)\s*(억\s*엔|조\s*엔|만\s*엔|엔(?!비디아|진|터|지니어|드)|' + UNITS + r')?')


def number_units(text, num_re=NUM_RE):
    """{(value, unit)} for every figure in the text, dates and clock times masked. Unit-sensitive:
    5.5% and 5.5bp and 5.5달러 are different claims."""
    t = DATE_MASK.sub(' ', text or '')
    t = re.sub(r'(?<=[^\s(\[])-(?=\d)', ' ', t)       # hyphen joining words, not a sign
    out = set()
    for m in num_re.finditer(t):
        try:
            val = round(float(m.group(1).replace(',', '')), 4)
        except ValueError:
            continue
        out.add((val, re.sub(r'\s+', '', m.group(2) or '')))
    return out


def dates_only_in(text, summary):
    """Date and period tokens the text has and the summary does not spell the same way. They are
    masked out of the number check (「1H27」 ↔ 「2027년 상반기」 would fail a literal comparison), so
    the routine reads them (codex 설계 검토 1회 #6). Token against token: 「1월」 is not in 「11월」
    (구현 검토 5회 #2)."""
    have = set(DATE_MASK.findall(summary or ''))
    out = []
    for tok in DATE_MASK.findall(text or ''):
        if tok not in have and tok not in out:
            out.append(tok)
    return out


def _visible(fragment):
    """The text as a browser shows it: tags out, character references restored (`&#32;같은 보도는`
    starts with a space, not with the number 32 — 구현 검토 1회 #4)."""
    t = re.sub(r'<(script|style)\b.*?</\1>', ' ', fragment, flags=re.S)
    return re.sub(r'\s+', ' ', _html.unescape(TAG_RE.sub(' ', t))).strip()


def _squash(s):
    return re.sub(r'\s+', '', s or '')


def coverage(text, summary):
    a, b = _squash(text), _squash(summary)
    if not a or not b:
        return 0.0
    blocks = SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks()
    return sum(m.size for m in blocks if m.size >= 2) / len(a)


def _close_of(html, tag, pos):
    """Offset just past the tag that closes an element opened right before `pos`."""
    depth = 1
    tok = re.compile(r'<(/?)' + re.escape(tag) + r'\b[^>]*?(/?)>', re.I)
    while depth:
        n = tok.search(html, pos)
        if not n:
            return len(html)
        if n.group(1):
            depth -= 1
        elif not n.group(2):
            depth += 1
        pos = n.end()
    return pos


def elements(html):
    """[(id, inner_html, start, end)] for every data-tg element, nested tags balanced."""
    out = []
    for m in OPEN_RE.finditer(html):
        pos = _close_of(html, m.group(1).lower(), m.end())
        tid = next(g for g in (m.group(3), m.group(4), m.group(5)) if g is not None)
        out.append((tid, html[m.end():pos], m.start(), pos))
    return out


# ── news layout ──────────────────────────────────────────────────────────

_OPACITY = re.compile(r'(?:^|;)\s*opacity\s*:\s*([^;!]+)', re.I)


def _hidden_attrs(a):
    """us.news_gate._is_hidden, plus opacity read as a number — its pattern knows `0` and `0.0` but
    not `.0`, `0%` or `0e0` (codex 구현 검토 2회)."""
    from us.news_gate import _is_hidden
    if _is_hidden(a):
        return True
    for m in _OPACITY.finditer(a.get('style') or ''):
        val = m.group(1).strip()
        try:
            if (float(val[:-1]) if val.endswith('%') else float(val)) <= 0:
                return True
        except ValueError:
            pass
    return False


class _Sections(HTMLParser):
    """One pass: every `<section data-tg-section>` with the tags and text inside it, whether an
    ancestor hides it, and how many data-tg elements sit outside such a section."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.sections, self.cur, self.depth, self.outside = [], [], None, 0, 0

    def _open(self, tag, attrs, void):
        a = {k: (v or '') for k, v in attrs}
        hid = _hidden_attrs(a) or is_hidden(attrs)    # 옛 판정식 + 공용 판정(common.hidden) — 여기서 숨김은 위반뿐
        wraps = _hidden_attrs(a) or (hid and tag not in VOID)     # 빈 요소(param 포함)는 공용 판정으로는 아무것도 안 감싼다
        if self.cur is not None:
            self.cur['tokens'].append(('start', tag, a))
            self.cur['hidden'] = self.cur['hidden'] or hid or tag in _INERT
            if not void:
                self.depth += 1
            return
        if tag == 'section' and 'data-tg-section' in a:
            self.cur = {'tokens': [], 'hidden': hid or any(h for _, h in self.stack), 'closed': False}
            self.depth = 1
            return
        if 'data-tg' in a:
            self.outside += 1
        if not void:
            self.stack.append((tag, wraps or tag in _INERT))

    def handle_starttag(self, tag, attrs):
        self._open(tag, attrs, tag in _VOID)

    def handle_startendtag(self, tag, attrs):
        self._open(tag, attrs, True)

    def handle_endtag(self, tag):
        if tag in _VOID:
            return
        if self.cur is not None:
            self.depth -= 1
            if self.depth == 0:
                self.cur['closed'] = tag == 'section'
                self.sections.append(self.cur)
                self.cur = None
            else:
                self.cur['tokens'].append(('end', tag))
            return
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        # as written, runs of white space folded to one space the way a browser shows them — the
        # routine reads the paragraphs printed from these tokens (설계 검토 3회 #2)
        if self.cur is not None and data:
            self.cur['tokens'].append(('text', re.sub(r'\s+', ' ', data)))

    def close(self):
        super().close()
        if self.cur is not None:
            self.sections.append(self.cur)
            self.cur = None


def _section_shape(tokens):
    """(None, paragraphs) when the tokens are exactly h2(title) · div.card · p+ with every p made of
    text and span[data-tg] > text and holding at least one marker; else (a short note on where it
    breaks, []). A paragraph is a list of ('text', chunk) and ('tg', id, text) in reading order,
    white space kept (folded to single spaces) so that it prints the way it reads."""
    i = 0

    def at(kind, tag=None):
        return i < len(tokens) and tokens[i][0] == kind and (tag is None or tokens[i][1] == tag)

    def words():
        nonlocal i
        got = []
        while at('text'):
            got.append(tokens[i][1])
            i += 1
        return re.sub(r' +', ' ', ''.join(got))

    def blank():
        """White space between blocks is not text; anything else stays where it is."""
        nonlocal i
        j = i
        if words().strip():
            i = j

    blank()
    if not at('start', 'h2'):
        return '제목(h2)으로 시작하지 않는다', []
    i += 1
    if words().strip() != NEWS_TITLE or not at('end', 'h2'):
        return f'제목이 「{NEWS_TITLE}」 하나가 아니다', []
    i += 1
    blank()
    if not at('start', 'div') or 'card' not in (tokens[i][2].get('class') or '').split():
        return '제목 다음이 <div class="card"> 가 아니다', []
    i += 1
    blank()
    paras = []
    while at('start', 'p'):
        i += 1
        n, parts = len(paras) + 1, []
        while not at('end', 'p'):
            if at('text'):
                parts.append(('text', words()))
            elif at('start', 'span') and 'data-tg' in tokens[i][2]:
                tid = tokens[i][2]['data-tg']
                i += 1
                text = words()
                if not text.strip():
                    return f'{n}번째 문단의 표식 안이 글자만이 아니다', []
                if not at('end', 'span'):
                    return f'{n}번째 문단의 표식 안에 다른 태그가 있다', []
                i += 1
                parts.append(('tg', tid, text))
            else:
                return f'{n}번째 문단에 글자와 <span data-tg> 가 아닌 것이 있다', []
        i += 1
        if not any(x[0] == 'tg' for x in parts):
            return f'{n}번째 문단에 <span data-tg> 표식이 없다', []
        paras.append(parts)
        blank()
    if not paras:
        return '인용 문단이 하나도 없다', []
    if not at('end', 'div'):
        return f'{len(paras)}번째 문단 뒤에 문단이 아닌 것이 있다', []
    i += 1
    blank()
    if i != len(tokens):
        return '카드 뒤에 다른 것이 있다', []
    return None, paras


def _news_sections(doc):
    """-> (violations, paragraphs of the section when there is exactly one and its shape holds)."""
    v, paras = [], []
    rd = _Sections()
    rd.feed(doc)
    rd.close()
    if len(rd.sections) > 1:
        v.append(f'「{NEWS_TITLE}」 섹션이 {len(rd.sections)}개다 — 하나만 둔다')
    if rd.outside:
        v.append(f'data-tg 표식 {rd.outside}개가 「{NEWS_TITLE}」 섹션 밖에 있다 — 뉴스 글에서는 그 섹션 안에만 쓴다')
    for s in rd.sections:
        if s['hidden']:
            v.append(f'「{NEWS_TITLE}」 섹션이나 그 안·바깥 요소가 숨겨져 있다(hidden·display:none·details 등) — 숨긴 인용은 싣지 않는다')
        why, got = ('섹션이 닫히지 않았다', []) if not s['closed'] else _section_shape(s['tokens'])
        if why:
            v.append(f'「{NEWS_TITLE}」 섹션의 모양이 다르다 — h2 하나, <div class="card"> 하나, 그 안에 글자와 '
                     f'<span data-tg="…">문장</span> 으로 된 <p> 문단만 두고 문단마다 표식을 하나 이상 둔다 ({why})')
        elif len(rd.sections) == 1:
            paras = got
    return v, paras


def _speakers(it):
    return {x for x in (it.get('firm'), it.get('analyst'), (it.get('source') or {}).get('name')) if x}


def _named(text, names):
    """Which of the names the text really carries, as names with their spaces taken out: spaces are
    ignored (「블 룸버그」, and 「로이터 통신」 is 「로이터통신」), the longest name is taken first so that
    「로이터통신」 is not also 「로이터」 — in either direction (구현 검토 1회 #3, 2회 #1, 5회 #1)."""
    t, found = _squash(text), set()
    for sq in sorted({_squash(x) for x in names} - {''}, key=len, reverse=True):
        if sq in t:
            found.add(sq)
            t = t.replace(sq, '\x00')
    return found


def _says(text, name, names):
    """The text carries this name itself — 「로이터통신은 …」 does not name 「로이터」 when 「로이터통신」 is
    another speaker of the file, however it is spaced (「로이터 통신은」) (구현 검토 3회 #1, 4회 #1)."""
    if not name:
        return False
    # only a name that is really longer: 「로이터 통신」 next to 「로이터통신」 in the file is the same name (5회 #1)
    for longer in sorted((x for x in names if _squash(x) != _squash(name) and _squash(name) in _squash(x)),
                         key=lambda x: -len(_squash(x))):
        text = re.sub(r'\s*'.join(re.escape(c) for c in _squash(longer)), '\x00', text)
    return name in text


def _news_context(paras):
    """{id: (the marker before it in the same paragraph or None, the linking text between them)} —
    first occurrence of an id only (a second one fails on its own)."""
    ctx = {}
    for parts in paras:
        prev, gap = None, ''
        for x in parts:
            if x[0] == 'text':
                gap += x[1]
                continue
            ctx.setdefault(x[1], (prev, gap))
            prev, gap = x[1], ''
    return ctx


def _news_links(paras, items, sums, warn=None):
    """Linking text: the words in a paragraph that no marker holds, so no summary vouches for them."""
    v = []
    names = {FIRM_KIWOOM, FIRM_HANWHA}.union(*(_speakers(it) for it in items.values()))
    n_link = n_all = 0
    for parts in paras:
        for x in parts:
            chunk = x[-1].strip()
            n_all += len(chunk)
            if x[0] != 'text' or not chunk:
                continue
            n_link += len(chunk)
            head = f'잇는 말 「{chunk[:30]}{"…" if len(chunk) > 30 else ""}」'
            d = re.search(r'\d', chunk)
            q = d.group(0) if d else link_quantity(chunk)
            if q:
                v.append(f'{head} 에 숫자가 있다(「{q}」) — 수치·수량·날짜는 표식 안에만 쓴다')
            hit = sorted(nm for nm in names if nm in chunk)
            if hit:
                v.append(f'{head} 에 이름 「{hit[0]}」 이 있다 — 증권사·연구원·매체는 표식 안에만 쓴다')
            else:
                # written apart it may be the outlet (「로 이터가 전했다」, 구현 검토 1회 #2) or plain words
                # (「매일 경제 지표가」 next to 매일경제 in the file) — code cannot tell, the reader can
                loose = sorted(_named(chunk, names))
                if loose and warn is not None:
                    warn.append(f'{head} 에 띄어 쓴 이름처럼 보이는 글자가 있다(「{loose[0]}」) — 매체·증권사·연구원을 가리키면 지운다')
            if len(chunk) > NEWS_LINK_MAX_CHARS:
                v.append(f'{head} 이 {len(chunk)}자다(최대 {NEWS_LINK_MAX_CHARS}자) — 잇는 말은 문단이 무엇에 관한 것인지만 말한다')
            if len(_squash(chunk)) >= NEWS_LINK_MIN_COMPARE:
                best = max((coverage(chunk, x) for x in sums), default=0)
                if best >= OUTSIDE_COVERAGE:
                    v.append(f'{head} 이 텔레그램 요약과 겹친다({best:.2f}) — 요약에서 온 내용은 표식 안에 쓴다')
    if n_all and n_link / n_all > NEWS_LINK_MAX_SHARE:
        v.append(f'잇는 말이 섹션의 {n_link / n_all:.0%} 다(최대 {NEWS_LINK_MAX_SHARE:.0%}) — 글의 몸은 표식 안의 인용이다')
    return v


def _news_outside(outside, news):
    """Text outside the data-tg elements, cut into the pieces that are compared with the summaries."""
    guids = {str(it.get('guid')): it for it in (news or {}).get('items') or []}

    def stored(m):
        guid = next(g for g in m.groups()[:3] if g is not None)
        want = re.sub(r'\s+', ' ', (guids.get(guid) or {}).get('summary_ko') or '').strip()
        got = re.sub(r'\s+', ' ', _html.unescape(TAG_RE.sub('', m.group(4)))).strip()
        if want and got.startswith(want):
            return '<p>' + _html.escape(got[len(want):]) + '</p>'      # the link sentence stays
        return m.group(0)

    t = _SUMMARY_P.sub(stored, outside)
    while True:
        m = _CONTESTED_OPEN.search(t)
        if not m:
            break
        t = t[:m.start()] + ' ' + t[_close_of(t, 'section', m.end()):]
    return _pieces(t)


def _pieces(t, line_breaks_end_sentences=True):
    """Markup -> the sentences that are compared with the summaries, block boundaries kept.
    jp passes False: a `<br>`/`<wbr>` inside running text does not end the sentence — cut there,
    a copied sentence fell into fragments too short to compare (구현 검토 5회). US/KR keep the
    reading their published posts were checked with."""
    t = re.sub(r'<(script|style)\b.*?</\1>', ' ', t, flags=re.S)
    if not line_breaks_end_sentences:
        t = re.sub(r'<w?br\b[^>]*>', ' ', t, flags=re.I)
    out = []
    for block in _BLOCK.split(t):
        text = re.sub(r'\s+', ' ', _html.unescape(TAG_RE.sub(' ', block))).strip()
        for sent in re.split(r'(?<=[다요])[.!?]\s*', text):
            sent = sent.strip()
            n = len(_squash(sent))
            if n >= OUTSIDE_MIN_CHARS or (n >= NEWS_OUTSIDE_SHORT and _SENT_END.search(sent)):
                out.append(sent)
    return out


# ── Japan daily layout ───────────────────────────────────────────────────
VIEWS = 'views'
RELAY_WORDS = re.compile(r'전해졌|전해진|전해지|알려졌|알려진|라는\s?(?:의견|시각|관측|해석|전망|평가|주장|지적|우려|분석|얘기|소식)')
JP_DATE = re.compile(r'\d{4}-\d{2}-\d{2}|\d{4}년|\d{1,2}월|\d{1,2}일|\d{1,2}/\d{1,2}|\d{1,2}분기')


class _Offsets(HTMLParser):
    """HTMLParser that knows where in the source the tag it is handling starts and ends."""

    def __init__(self, doc):
        super().__init__(convert_charrefs=True)
        self.doc = doc
        self._lines = [0] + [m.end() for m in re.finditer('\n', doc)]

    def here(self):
        line, col = self.getpos()
        return self._lines[line - 1] + col

    def after_end(self):
        i = self.doc.find('>', self.here())
        return len(self.doc) if i < 0 else i + 1


class _Views(_Offsets):
    """Every `<section data-section="views" data-tg-section>` with its source span and tokens, and
    every marker (data-tg, data-tg-section, data-section="views") that is not one of them or
    inside one."""

    def __init__(self, doc):
        super().__init__(doc)
        self.stack, self.nodes, self.cur, self.depth, self.stray = [], [], None, 0, []

    def _open(self, tag, attrs, void):
        a = {k: (v or '') for k, v in attrs}
        mark, views = 'data-tg-section' in a, a.get('data-section', '').strip() == VIEWS
        hidden = _hidden_attrs(a) or is_hidden(attrs) or tag in _INERT
        if self.cur is not None:
            self.cur['tokens'].append(('start', tag, a))
            self.cur['hidden'] = self.cur['hidden'] or hidden
            self.cur['nested'] = self.cur['nested'] or tag == 'section' or mark or views
            if not void:
                self.depth += 1
            return
        if tag == 'section' and mark and views and not void:
            self.cur = {'start': self.here(), 'end': None, 'tokens': [], 'closed': False, 'nested': False,
                        'hidden': hidden or any(h for _, h, _ in self.stack),
                        'inside': any(sec for _, _, sec in self.stack)}
            self.depth = 1
            return
        for name, on in (('data-tg', 'data-tg' in a), ('data-tg-section', mark), ('data-section="views"', views)):
            if on:
                self.stray.append(f'<{tag} {name}>')
        if not void:
            self.stack.append((tag, (_hidden_attrs(a) or tag in _INERT) if tag in VOID else hidden, tag == 'section'))

    def handle_starttag(self, tag, attrs):
        self._open(tag, attrs, tag in _VOID)

    def handle_startendtag(self, tag, attrs):
        # `<div hidden/>` opens a div: HTML ignores the slash on a non-void element (구현 검토 4회)
        self._open(tag, attrs, tag in _VOID)

    def handle_endtag(self, tag):
        if tag in _VOID:
            return
        if self.cur is not None:
            self.depth -= 1
            if self.depth == 0:
                self.cur.update(closed=tag == 'section', end=self.after_end())
                self.nodes.append(self.cur)
                self.cur = None
            else:
                self.cur['tokens'].append(('end', tag))
            return
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        if self.cur is not None and data:
            self.cur['tokens'].append(('text', re.sub(r'\s+', ' ', data)))

    def close(self):
        super().close()
        if self.cur is not None:
            self.cur['end'] = len(self.doc)
            self.nodes.append(self.cur)
            self.cur = None


def _views_shape(tokens):
    """(None, [(id, text)]) when the tokens are exactly h2(title) · p+ with every p holding one
    span[data-tg] > text and nothing else; else (where it breaks, [])."""
    i = 0

    def at(kind, tag=None):
        return i < len(tokens) and tokens[i][0] == kind and (tag is None or tokens[i][1] == tag)

    def words():
        nonlocal i
        got = []
        while at('text'):
            got.append(tokens[i][1])
            i += 1
        return re.sub(r' +', ' ', ''.join(got))

    def blank():
        nonlocal i
        j = i
        if words().strip():
            i = j

    blank()
    if not at('start', 'h2'):
        return '제목(h2)으로 시작하지 않는다', []
    i += 1
    if words().strip() != NEWS_TITLE or not at('end', 'h2'):
        return f'제목이 「{NEWS_TITLE}」 하나가 아니다', []
    i += 1
    blank()
    paras = []
    while at('start', 'p'):
        i += 1
        n = len(paras) + 1
        blank()
        if not (at('start', 'span') and 'data-tg' in tokens[i][2]):
            return f'{n}번째 문단이 <span data-tg> 하나로 시작하지 않는다', []
        tid = (tokens[i][2]['data-tg'] or '').strip()
        if not tid:
            return f'{n}번째 문단의 data-tg 에 항목 id 가 없다', []
        i += 1
        text = words()
        if not text.strip() or not at('end', 'span'):
            return f'{n}번째 문단의 표식 안이 글자만이 아니다', []
        i += 1
        blank()
        if not at('end', 'p'):
            return f'{n}번째 문단에 표식 하나 말고 다른 것이 있다', []
        i += 1
        paras.append((tid, text))
        blank()
    if not paras:
        return '인용 문단이 하나도 없다', []
    if i != len(tokens):
        return f'{len(paras)}번째 문단 뒤에 문단이 아닌 것이 있다', []
    return None, paras


def views_node(doc):
    """-> (node, violations). node = {'start', 'end', 'source', 'paras'} for the one valid
    `<section data-section="views" data-tg-section>` of a Japan daily, else None. `doc` is the page
    with comments stripped; the span is in that string. A node is returned only when nothing at all
    is wrong with the markers on the page — the Japan daily gate exempts exactly this span."""
    rd = _Views(doc)
    rd.feed(doc)
    rd.close()
    v = []
    if rd.stray:
        v.append(f'「{NEWS_TITLE}」 절 밖에 표식이 있다({", ".join(rd.stray[:3])}) — data-tg·data-tg-section·'
                 f'data-section="views" 는 그 절 하나와 그 안의 문단에만 쓴다')
    if len(rd.nodes) > 1:
        v.append(f'「{NEWS_TITLE}」 절이 {len(rd.nodes)}개다 — 하나만 둔다')
    node = None
    for s in rd.nodes:
        if s['inside'] or s['nested']:
            why = '다른 절 안에 있거나 안에 절·표식을 품고 있다'
        elif not s['closed']:
            why = '절이 닫히지 않았다'
        elif s['hidden']:
            why = '절이나 그 안·바깥 요소가 숨겨져 있다(hidden·display:none·details 등)'
        else:
            why, paras = _views_shape(s['tokens'])
        if why:
            v.append(f'「{NEWS_TITLE}」 절의 모양이 다르다 — <section class="card" data-section="views" data-tg-section> 안에 '
                     f'h2 하나와 <p><span data-tg="…">문장</span></p> 문단만 둔다 ({why})')
        else:
            node = {'start': s['start'], 'end': s['end'], 'source': doc[s['start']:s['end']], 'paras': paras}
    return (None, v) if v else (node, v)


def _jp_articles(news):
    """Japan daily: the summaries of the day's news file that may vouch for a sentence outside the
    section — every publishable one, wherever (or whether) the page shows it.

    An outside sentence that overlaps a Telegram summary is the article's, not the note's, when
    one of these says it at least as closely. It used to matter whether the page 「carried」 the
    article (its summary placed in the news section, or cited by a mover paragraph). That was read
    from markup the writer controls, and each reading had a counterexample: `data-cite` on any
    element, `<P …>`, a hidden ancestor, a hidden child, `<div hidden/>`, a `<p>` inside the `<p>`
    (구현 검토 1회 #2, 2·3·4회). The news file is written by the collector, the writer is handed
    all of it (mover causes already come from any item), and the comparison — closer to the note
    than to every article fails — is what stops a copied note. So nothing here reads the page."""
    from us.news_summary import summary_problem
    out = []
    for it in (news or {}).get('items') or []:
        text = it.get('summary_ko') if isinstance(it, dict) else None
        text = re.sub(r'\s+', ' ', text).strip() if isinstance(text, str) else ''
        if text and summary_problem(text) is None:
            out.append(text)
    return out


def _jp_note_date(it):
    """The note's own date: the date it carries, else the JST day it was posted."""
    if it.get('note_date'):
        return it['note_date']
    try:
        from datetime import datetime
        return datetime.fromisoformat(it['dt_utc']).astimezone(tg_jp.JST).date().isoformat()
    except (KeyError, TypeError, ValueError):
        return None


def _jp_dates(tid, it, text, summ, session):
    v = []
    nd = _jp_note_date(it)
    own = set()
    if nd:
        y, m, d = (int(x) for x in nd.split('-'))
        own = {nd, f'{y}년', f'{m}월', f'{d}일', f'{m}/{d}'}
    norm = lambda tok: re.sub(r'(?<!\d)0+(?=\d)', '', tok) if '-' not in tok else tok     # noqa: E731
    have = {norm(x) for x in JP_DATE.findall(summ or '')}
    bad = [tok for tok in dict.fromkeys(JP_DATE.findall(text)) if norm(tok) not in own and norm(tok) not in have]
    if bad:
        v.append(f'data-tg="{tid}" — 요약에도 메모 날짜({nd or "알 수 없음"})에도 없는 날짜·기간이 있다: {", ".join(bad)}')
    if nd and session and nd < session and not re.search(rf'(?<!\d){m}월\s?{d}일', text):
        v.append(f'data-tg="{tid}" — {m}월 {d}일 메모다(세션 {session} 이전) — 문장에 「{m}월 {d}일」 을 밝힌다')
    return v


class _AttrText(HTMLParser):
    """Every attribute value of a page except the `data-tg` ids (those name the channel by design)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.values = []

    def handle_starttag(self, tag, attrs):
        self.values.extend(v for k, v in attrs if v and k != 'data-tg')

    handle_startendtag = handle_starttag


def word_violations(doc, jp=False):
    """「텔레그램」·t.me·channel names anywhere in the page (`doc` = comments stripped). The raw markup
    is searched too: any attribute quoting, any element (a, img, link, meta). jp: the words are
    banned in the news section as well, and the message says when the hit is there; attribute
    values count too — a `<meta name="description">` is published text (구현 검토 6회)."""
    v = []
    vis = _visible(doc)
    if jp:
        rd = _AttrText()
        rd.feed(doc)
        rd.close()
        attrs = ' '.join(rd.values)
        if BANNED.search(attrs) or any(w.lower() in attrs.lower() for w in CHANNEL_WORDS):
            v.append('「텔레그램」·채널 이름이 태그 속성 안에 있다(meta 설명·alt·title 등) — 발행본 어디에도 쓰지 않는다')
    in_news = ''
    if jp:
        m = re.search(r'<section\b[^>]*\bdata-section\s*=\s*["\']?news\b[^>]*>', doc, re.I)
        in_news = _visible(doc[m.end():_close_of(doc, 'section', m.end())]) if m else ''
    where = lambda hit: (' (일본 경제 뉴스 절 안 — 그 기사의 자리표시를 뺀다)' if hit else '')     # noqa: E731
    if BANNED.search(vis) or re.search(r't\.me/|telegram\.me', doc, re.I):
        v.append('「텔레그램」·t.me 가 발행본에 있다 — 채널 출처는 쓰지 않는다' + where(BANNED.search(in_news)))
    for w in CHANNEL_WORDS:
        if w.lower() in vis.lower():
            v.append(f'채널 이름 「{w}」 이 발행본에 있다' + where(w.lower() in in_news.lower()))
    return v


def check(html, data, warnings=None, layout='brief', news=None, pairs=None, paras=None, session=None, views=None,
          skip=()):
    """layout 'brief' (default), 'news' or 'jp'. `skip` = exact fragments the caller has already verified as
    code output (jp v2: generated sentences and code tables byte-equal to `render(facts)`) — they are left out
    of the outside-the-markers comparison only; nothing else changes, and an empty `skip` is the old behaviour. `news` = the day's news file (news/jp layout: its
    stored summaries are left out of the outside comparison). `pairs` collects (id, marker text,
    summary); `paras` the section's paragraphs in order, each a list of ('text', chunk) /
    ('tg', id, text). jp: `session` = the Tokyo session, `views` receives the `views_node` (or
    nothing when the markers on the page are not exactly one valid section)."""
    v = []
    warn = warnings if warnings is not None else []
    is_jp = layout == 'jp'
    is_news = layout in ('news', 'jp')
    num_re = JP_NUM_RE if is_jp else NUM_RE
    max_views, max_others = (None, None) if is_news else (POST_MAX_VIEWS, POST_MAX_OPINIONS)
    seen = set()
    min_cov = NEWS_MIN_COVERAGE if is_news else MIN_COVERAGE
    # the editor's note is the publisher's own text in a brief; a news post has none, so there the
    # marker exempts nothing (it would be a place to put anything)
    doc = strip_comments(html or '')
    if not is_news:
        doc = NOTE_RE.sub(' ', doc)
    v.extend(word_violations(doc, is_jp))
    els = elements(doc)
    if not is_news:
        # 브리프의 data-tg 는 절 없이 본문에 선다 — 표식 자신·그 안·그 조상에 숨긴 요소가 있으면 막는다(common.hidden)
        for tid, _inner, start, end in els:
            hid = fragment_hidden(doc, start, end)
            if hid:
                v.append(f'data-tg="{tid}" 인용이나 그 안·바깥 요소가 숨겨져 있다({hid}) — 숨긴 인용은 싣지 않는다')
    items = {it['id']: it for it in (data or {}).get('items', [])}
    ctx, sec_paras = {}, []
    node = None
    if is_jp:
        node, got = views_node(doc)
        v.extend(got)
        # what is checked below is what views_node read, not a second reading of the markup: the
        # regex of elements() does not see `<span data-tg>` (no value) or an id written with
        # character references, and a marker only one of the two sees was checked by neither
        # (구현 검토 1회 #1)
        seen_by_parser = [tid for tid, _ in node['paras']] if node else []
        if [tid for tid, _, _, _ in els] != seen_by_parser and not got:
            v.append(f'data-tg 표식을 읽는 두 방식의 결과가 다르다(절 안 {len(seen_by_parser)}개, 원문 {len(els)}개) — '
                     f'<p><span data-tg="채널/번호">문장</span></p> 꼴로만 쓴다')
            node = None
        if node:
            els = [(tid, _html.escape(text), None, None) for tid, text in node['paras']]
        if node and views is not None:
            views.append(node)
        if node and paras is not None:
            paras.extend([('tg', tid, text)] for tid, text in node['paras'])
    elif is_news:
        got, sec_paras = _news_sections(doc)
        v.extend(got)
        ctx = _news_context(sec_paras)
        if paras is not None:
            paras.extend(sec_paras)
    told, said = {}, {}    # id -> who the marker says is speaking (once it does say so) / its text
    all_speakers = set().union(*(_speakers(it) for it in items.values())) if items else set()
    if els and not data:
        return v + ['data-tg 표식이 있는데 텔레그램 파일이 없다']
    if is_news and els and not any('news_use' in it for it in items.values()):
        return v + ['텔레그램 파일에 news_use 표시가 없다 — ' + ('일본 일간은 scripts/fetch_telegram_jp.py 가 만든 파일만 쓴다'
                                                      if is_jp else '뉴스 글은 scripts/tg_news.py input 이 만든 파일만 쓴다')]
    n_view = n_other = 0
    names = {FIRM_KIWOOM, FIRM_HANWHA}
    for it in items.values():
        if it.get('kind') == 'view' and it.get('analyst'):
            names.add(it['analyst'])
    for tid, inner, _, _ in els:
        it = items.get(tid)
        text = _visible(inner)
        if not it or not it.get('summary_ko'):
            v.append(f'data-tg="{tid}" — 파일에 없거나 요약 없는 항목')
            continue
        kind, summ = it.get('kind'), it['summary_ko']
        if refusal(summ):
            v.append(f'data-tg="{tid}" — 그 항목의 요약이 요약이 아니다(모델의 거절·작업 설명문) — 인용하지 않는다')
            continue
        if is_news:
            if tid in seen:
                v.append(f'data-tg="{tid}" — 같은 항목을 두 번 인용했다')
                continue
            seen.add(tid)
            if it.get('news_use') is not True:
                v.append(f'data-tg="{tid}" — 뉴스 글에 쓸 수 없는 항목이다(사유 {it.get("news_skip") or "표시 없음"})')
                continue
            if len(text) > NEWS_MAX_CHARS:
                v.append(f'data-tg="{tid}" — 표식 하나가 {len(text)}자다(최대 {NEWS_MAX_CHARS}자)')
            if pairs is not None:
                pairs.append((tid, text, summ))
        src = (it.get('source') or {}).get('name')
        prev, gap = ctx.get(tid, (None, ''))
        prev_it = items.get(prev) or {}
        # the name may give way to a back-reference only right after a marker that itself says the
        # same speaker — nothing but spaces between, and no other speaker of the file named in it
        # (whose report 「같은 보도」 is would be anyone's guess)
        lends = None
        if is_news and prev and not gap.strip():
            if not _named(said.get(prev, ''), all_speakers) - {_squash(x) for x in _speakers(prev_it)}:
                lends = told.get(prev)
        how = ' — 이름을 쓰거나, 같은 문단 바로 앞 표식이 같은 {0}이면 「{1}」 으로 시작한다' if is_news else ''
        if kind == 'view':
            n_view += 1
            who = ('view', it.get('firm'), it.get('analyst'))
            back = bool(it.get('firm') and it.get('analyst') and lends == who
                        and re.match(SAME_ANALYST.format(surname=re.escape(it['analyst'][0])), text))
            ok = True
            if it.get('firm') and not _says(text, it['firm'], all_speakers) and not back:
                ok = False
                v.append(f'data-tg="{tid}" — 증권사 견해인데 「{it["firm"]}」 이 문장에 없다' + how.format('연구원', '한 연구원은'))
            if it.get('analyst') and not _says(text, it['analyst'], all_speakers) and not back:
                ok = False
                v.append(f'data-tg="{tid}" — 증권사 견해인데 「{it["analyst"]}」 이 문장에 없다' + how.format('연구원', '한 연구원은'))
            if ok and it.get('firm') and it.get('analyst'):
                told[tid] = who
        else:
            n_other += 1
            who = ('source', src)
            back = bool(src and lends == who and SAME_SOURCE.match(text))
            named = bool(src) and (_says(text, src, all_speakers) or back)
            if kind == 'report':
                if not named:
                    v.append(f'data-tg="{tid}" — 원문 출처 「{src}」 를 문장 안에 단다' + how.format('매체', '같은 보도는'))
                if not REPORT_WORDS.search(text):
                    v.append(f'data-tg="{tid}" — 보도 틀(「…에 따르면」·「…라고 보도했다」)이 없다')
            else:
                if is_jp and not src:
                    if not RELAY_WORDS.search(text):
                        v.append(f'data-tg="{tid}" — 전해 들은 말의 틀(「…라는 분석이 전해졌다」)이 없다 — 「…로 평가했다」 처럼 '
                                 f'직접 한 말로 쓰지 않는다')
                elif not OPINION_WORDS.search(text):
                    v.append(f'data-tg="{tid}" — 의견 틀(「…라는 의견도 나왔다」)이 없다')
                if src and not named:
                    v.append(f'data-tg="{tid}" — 글이 밝힌 출처 「{src}」 를 문장 안에 단다' + how.format('매체', '같은 보도는'))
                if (is_news and not src and prev and (prev_it.get('kind') == 'view' or (prev_it.get('source') or {}).get('name'))
                        and not NEW_SPEAKER.match(text)):
                    v.append(f'data-tg="{tid}" — 출처 없는 글이 출처 있는 표식 바로 뒤에 있어 그 출처의 말로 읽힌다 — '
                             f'표식을 「시장에서는」 같은 새 주어로 시작하거나 문단을 나눈다')
            if named:
                told[tid] = who
        said[tid] = text
        extra = number_units(text, num_re) - number_units(summ, num_re)
        if extra:
            v.append(f'data-tg="{tid}" — 요약에 없는 수치 {sorted(extra)[:5]}')
        body = text
        if is_jp:
            firm = it.get('relay_firm')
            other = sorted(tg_jp.firms_in(text) - ({firm} if firm else set()) - tg_jp.firms_in(summ))
            if other:
                v.append(f'data-tg="{tid}" — 증권사 이름 「{other[0]}」 은 이 메모의 것이 아니다(메모의 증권사: {firm or "없음"}) — '
                         f'이름은 그 항목의 relay_firm 이나 요약에 있는 것만 쓴다')
            v.extend(_jp_dates(tid, it, text, summ, session))
            if firm:
                body = body.replace(firm, '')
        for nm in names | ({src} if src else set()):
            body = body.replace(nm, '')
        if coverage(body, summ) < min_cov:
            v.append(f'data-tg="{tid}" — 문장이 그 항목 요약과 맞지 않는다(겹침 {coverage(body, summ):.2f}, 하한 {min_cov})')
    if max_views is not None and n_view > max_views:
        v.append(f'증권사 견해 {n_view}건 — 최대 {max_views}')
    if max_others is not None and n_other > max_others:
        v.append(f'의견·보도 {n_other}건 — 최대 {max_others}')
    # outside the elements
    outside = doc
    if node:                        # jp: the one valid section, whole
        outside = doc[:node['start']] + ' ' + doc[node['end']:]
    else:
        for _, _, s, e in sorted(els, key=lambda x: -x[2]):
            outside = outside[:s] + ' ' + outside[e:]
    for frag in skip or ():
        outside = outside.replace(frag, ' ')
    out_vis = _visible(outside)
    # 키움증권 is also a listed stock, so a bare firm name outside is fine; an analyst name, or the
    # firm as the speaker of a view, is not
    # an analyst named outside the elements is blocked only when that sentence carries the
    # analyst's Telegram view (another source may quote the same person)
    by_analyst = {}
    for it in items.values():
        if it.get('kind') == 'view' and it.get('analyst') and it.get('summary_ko'):
            by_analyst.setdefault(it['analyst'], []).append(it['summary_ko'])
    for sent in re.split(r'(?<=[다요])\.\s*', out_vis):
        for nm, sums_a in by_analyst.items():
            if nm in sent and max(coverage(sent.replace(nm, ''), x) for x in sums_a) >= 0.4:
                warn.append(f'「{nm}」 의 텔레그램 견해와 닮은 문장이 data-tg 표식 밖에 있다 — 텔레그램에서 왔으면 감싼다: 「{sent[:40]}…」')
    sums = [it['summary_ko'] for it in items.values() if it.get('summary_ko')]
    if is_news:
        if not is_jp:
            v.extend(_news_links(sec_paras, items, sums, warn))
        pieces, articles = (_pieces(outside, False), _jp_articles(news)) if is_jp else (_news_outside(outside, news), [])
        for sent in pieces:
            best = max((coverage(sent, s) for s in sums), default=0)
            if best < OUTSIDE_COVERAGE:
                continue
            if is_jp:
                # an article collected that day says it at least as closely: the sentence is that article's
                if max((coverage(sent, n) for n in articles), default=0) >= best:
                    continue
                v.append(f'표식 밖 문장이 텔레그램 요약과 겹친다({best:.2f}) — 일본 일간에서는 「{NEWS_TITLE}」 절 밖에 텔레그램에서 '
                         f'온 내용을 쓰지 않는다(그날 일간 뉴스 파일의 기사 내용이면 그 기사 요약에 맞게 쓴다): 「{sent[:40]}…」')
            else:
                v.append(f'표식 밖 문장이 텔레그램 요약과 겹친다({best:.2f}) — 뉴스 글에서는 「{NEWS_TITLE}」 섹션 밖에 '
                         f'텔레그램에서 온 내용을 쓰지 않는다: 「{sent[:40]}…」')
        return v
    for sent in re.split(r'(?<=[다요])\.\s*', out_vis):
        if len(_squash(sent)) < OUTSIDE_MIN_CHARS:
            continue
        best = max((coverage(sent, s) for s in sums), default=0)
        if best >= OUTSIDE_COVERAGE:
            # an independent source can say the same thing — flag for review, do not block
            warn.append(f'표식 밖 문장이 텔레그램 요약과 겹친다({best:.2f}) — 텔레그램에서 왔으면 data-tg 로 감싼다: 「{sent[:40]}…」')
    return v
