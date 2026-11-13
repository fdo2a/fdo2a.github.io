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
  h2(「증권사 견해·시장 의견」) · div.card · (p · span[data-tg])+ — nothing hidden, no other tag or text;
- the file comes from `scripts/tg_news.py input` and the item is `news_use: true`;
- no cap on how many (2026-11-12 사용자 지시 — 그날 시장을 지배한 이슈·중요한 내용은 싣는다), but an
  item is quoted once, a paragraph is at most 300 chars, and its overlap with the summary >= 0.45;
- a sentence OUTSIDE the elements that repeats any summary in the file (>= 0.7) FAILS — the news
  posts have no post-publish review. Block boundaries are kept when splitting, and only two things
  are left out: the stored news summary inside `p[data-summary]` and `section[data-contested]`.
The overlap floor is not a check of meaning (the same words can say the opposite); the routine
reads each paragraph next to its summary as its last step (`pairs`).
Design: docs/superpowers/specs/2026-11-12-telegram-news-posts.md
"""
import html as _html
import re
from difflib import SequenceMatcher
from html.parser import HTMLParser

from .numbers import strip_comments
from .telegram import CHANNEL_WORDS, FIRM_HANWHA, FIRM_KIWOOM, POST_MAX_OPINIONS, POST_MAX_VIEWS
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


def number_units(text):
    """{(value, unit)} for every figure in the text, dates and clock times masked. Unit-sensitive:
    5.5% and 5.5bp and 5.5달러 are different claims."""
    t = DATE_MASK.sub(' ', text or '')
    t = re.sub(r'(?<=[^\s(\[])-(?=\d)', ' ', t)       # hyphen joining words, not a sign
    out = set()
    for m in NUM_RE.finditer(t):
        try:
            val = round(float(m.group(1).replace(',', '')), 4)
        except ValueError:
            continue
        out.add((val, re.sub(r'\s+', '', m.group(2) or '')))
    return out


def _visible(fragment):
    t = re.sub(r'<(script|style)\b.*?</\1>', ' ', fragment, flags=re.S)
    return re.sub(r'\s+', ' ', TAG_RE.sub(' ', t)).strip()


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
        _is_hidden = _hidden_attrs
        a = {k: (v or '') for k, v in attrs}
        if self.cur is not None:
            self.cur['tokens'].append(('start', tag, a))
            self.cur['hidden'] = self.cur['hidden'] or _is_hidden(a) or tag in _INERT
            if not void:
                self.depth += 1
            return
        if tag == 'section' and 'data-tg-section' in a:
            self.cur = {'tokens': [], 'hidden': _is_hidden(a) or any(h for _, h in self.stack), 'closed': False}
            self.depth = 1
            return
        if 'data-tg' in a:
            self.outside += 1
        if not void:
            self.stack.append((tag, _is_hidden(a) or tag in _INERT))

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
        if self.cur is not None and data.strip():
            self.cur['tokens'].append(('text', data.strip()))

    def close(self):
        super().close()
        if self.cur is not None:
            self.sections.append(self.cur)
            self.cur = None


def _section_shape(tokens):
    """None when the tokens are exactly h2(title) · div.card · (p · span[data-tg] · text)+, else
    a short note on where it breaks."""
    i = 0

    def at(kind, tag=None):
        return i < len(tokens) and tokens[i][0] == kind and (tag is None or tokens[i][1] == tag)

    if not at('start', 'h2'):
        return '제목(h2)으로 시작하지 않는다'
    i += 1
    title = []
    while at('text'):
        title.append(tokens[i][1])
        i += 1
    if ' '.join(title) != NEWS_TITLE or not at('end', 'h2'):
        return f'제목이 「{NEWS_TITLE}」 하나가 아니다'
    i += 1
    if not at('start', 'div') or 'card' not in (tokens[i][2].get('class') or '').split():
        return '제목 다음이 <div class="card"> 가 아니다'
    i += 1
    n = 0
    while at('start', 'p'):
        i += 1
        if not at('start', 'span') or 'data-tg' not in tokens[i][2]:
            return f'{n + 1}번째 문단이 <span data-tg> 로 시작하지 않는다'
        i += 1
        if not at('text'):
            return f'{n + 1}번째 문단의 표식 안이 글자만이 아니다'
        while at('text'):
            i += 1
        if not at('end', 'span'):
            return f'{n + 1}번째 문단의 표식 안에 다른 태그가 있다'
        i += 1
        if not at('end', 'p'):
            return f'{n + 1}번째 문단에 표식 밖 글자나 태그가 있다'
        i += 1
        n += 1
    if not n:
        return '인용 문단이 하나도 없다'
    if not at('end', 'div') or i + 1 != len(tokens):
        return f'{n}번째 문단 뒤에 문단이 아닌 것이 있다'
    return None


def _news_sections(doc):
    v = []
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
        why = None if s['closed'] else '섹션이 닫히지 않았다'
        why = why or _section_shape(s['tokens'])
        if why:
            v.append(f'「{NEWS_TITLE}」 섹션의 모양이 다르다 — h2 하나, <div class="card"> 하나, 그 안에 '
                     f'<p><span data-tg="…">문장</span></p> 문단만 둔다 ({why})')
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
    t = re.sub(r'<(script|style)\b.*?</\1>', ' ', t, flags=re.S)
    out = []
    for block in _BLOCK.split(t):
        text = re.sub(r'\s+', ' ', _html.unescape(TAG_RE.sub(' ', block))).strip()
        for sent in re.split(r'(?<=[다요])[.!?]\s*', text):
            sent = sent.strip()
            n = len(_squash(sent))
            if n >= OUTSIDE_MIN_CHARS or (n >= NEWS_OUTSIDE_SHORT and _SENT_END.search(sent)):
                out.append(sent)
    return out


def check(html, data, warnings=None, layout='brief', news=None, pairs=None):
    """layout 'brief' (default) or 'news'. `news` = the day's news file (news layout: its stored
    summaries are left out of the outside comparison). `pairs` collects (id, paragraph, summary)."""
    v = []
    warn = warnings if warnings is not None else []
    is_news = layout == 'news'
    max_views, max_others = (None, None) if is_news else (POST_MAX_VIEWS, POST_MAX_OPINIONS)
    seen = set()
    min_cov = NEWS_MIN_COVERAGE if is_news else MIN_COVERAGE
    # the editor's note is the publisher's own text in a brief; a news post has none, so there the
    # marker exempts nothing (it would be a place to put anything)
    doc = strip_comments(html or '')
    if not is_news:
        doc = NOTE_RE.sub(' ', doc)
    vis = _visible(doc)
    # raw markup too: any attribute quoting, any element (a, img, link, meta)
    if BANNED.search(vis) or re.search(r't\.me/|telegram\.me', doc, re.I):
        v.append('「텔레그램」·t.me 가 발행본에 있다 — 채널 출처는 쓰지 않는다')
    for w in CHANNEL_WORDS:
        if w.lower() in vis.lower():
            v.append(f'채널 이름 「{w}」 이 발행본에 있다')
    els = elements(doc)
    items = {it['id']: it for it in (data or {}).get('items', [])}
    if is_news:
        v.extend(_news_sections(doc))
    if els and not data:
        return v + ['data-tg 표식이 있는데 텔레그램 파일이 없다']
    if is_news and els and not any('news_use' in it for it in items.values()):
        return v + ['텔레그램 파일에 news_use 표시가 없다 — 뉴스 글은 scripts/tg_news.py input 이 만든 파일만 쓴다']
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
                v.append(f'data-tg="{tid}" — 문단이 {len(text)}자다(최대 {NEWS_MAX_CHARS}자)')
            if pairs is not None:
                pairs.append((tid, text, summ))
        src = (it.get('source') or {}).get('name')
        if kind == 'view':
            n_view += 1
            if it.get('firm') and it['firm'] not in text:
                v.append(f'data-tg="{tid}" — 증권사 견해인데 「{it["firm"]}」 이 문장에 없다')
            if it.get('analyst') and it['analyst'] not in text:
                v.append(f'data-tg="{tid}" — 증권사 견해인데 「{it["analyst"]}」 이 문장에 없다')
        else:
            n_other += 1
            if kind == 'report':
                if not src or src not in text:
                    v.append(f'data-tg="{tid}" — 원문 출처 「{src}」 를 문장 안에 단다')
                if not REPORT_WORDS.search(text):
                    v.append(f'data-tg="{tid}" — 보도 틀(「…에 따르면」·「…라고 보도했다」)이 없다')
            else:
                if not OPINION_WORDS.search(text):
                    v.append(f'data-tg="{tid}" — 의견 틀(「…라는 의견도 나왔다」)이 없다')
                if src and src not in text:
                    v.append(f'data-tg="{tid}" — 글이 밝힌 출처 「{src}」 를 문장 안에 단다')
        extra = number_units(text) - number_units(summ)
        if extra:
            v.append(f'data-tg="{tid}" — 요약에 없는 수치 {sorted(extra)[:5]}')
        body = text
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
    for _, _, s, e in sorted(els, key=lambda x: -x[2]):
        outside = outside[:s] + ' ' + outside[e:]
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
        for sent in _news_outside(outside, news):
            best = max((coverage(sent, s) for s in sums), default=0)
            if best >= OUTSIDE_COVERAGE:
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
