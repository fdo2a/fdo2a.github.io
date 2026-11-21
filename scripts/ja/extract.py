"""뼈대와 번역 단위 — 한글 발행본 HTML 을 무손실로 쪼개고 다시 합친다.

**무손실**: `join(split(x)) == x` 가 바이트 단위로 성립한다. 원본 문자열을
`html.parser.HTMLParser` 가 알려 주는 토큰 시작 위치로 잘라 쓰고, 파서가 돌려준
값을 다시 직렬화하지 않는다(속성 따옴표·공백·엔티티가 그대로 남는다).

**단위(겹치지 않는 최소 단위)**:
- `text` — 블록 태그·주석·script·style 에서 끊긴 「텍스트 + 인라인 요소」 연속 구간.
  구간 끝의 공백·짝 없는 인라인 태그·빈 요소는 뼈대에 남기고, 안쪽 텍스트에 한글이
  있으면 단위다. 인라인 태그는 숫자 없는 자리표시(`⟦a⟧…⟦/a⟧`, `⟦b/⟧`)가 된다.
  나무 구조를 세우지 않고 평평한 토큰 열에서 끊는다 — 닫히지 않은 `<div>` 가 실물에 있다.
- `attr` — 한글이 있는 속성 값(`aria-label alt title placeholder data-label`, meta
  `content` 등 — `SKIP_ATTRS` 밖 전부). 한글 속성을 단 인라인 태그는 구간을 끊는다
  (태그가 text 단위 안에 들어가면 속성 단위와 범위가 겹치기 때문).
- `jsonld` — `<script type="application/ld+json">` 안 문자열 값 하나하나. 범위는
  JSON 문자열 리터럴(따옴표 포함)이고, 바꿀 때는 그 리터럴만 `json.dumps` 로 바꾼다.
"""
from __future__ import annotations

import html as _html
import json
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

HANGUL = re.compile(r"[가-힣]")

INLINE = frozenset("a b strong em i span sub sup small mark u s abbr code br img wbr tl-s".split())
VOID = frozenset("br img wbr".split())
OPAQUE = frozenset({"code"})
RAW = frozenset({"script", "style"})
# 한글이 있어도 단위로 만들지 않는 속성 — 주소·식별자·기계 표식.
SKIP_ATTRS = frozenset("href src srcset id class style for name rel type http-equiv charset lang "
                       "property data-news data-summary data-key data-index data-news-index".split())

PH_RE = re.compile(r"⟦(/?)([a-z]+)(/?)⟧")


def letter(i: int) -> str:
    """0→a … 25→z, 26→aa, 27→ab …"""
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(97 + r) + s
    return s


@dataclass
class Unit:
    uid: int
    kind: str                 # text | attr | jsonld
    ko: str                   # 모델에 주는 문자열(엔티티를 푼 것, 자리표시 포함)
    start: int                # 원본 범위 [start, end)
    end: int
    ph: dict = field(default_factory=dict)   # 자리표시 → 원본 태그 문자열
    section: str | None = None               # 가장 가까운 조상 section 의 id/data-section
    block: str | None = None                 # 가장 가까운 블록 태그 이름(attr 은 그 태그)
    attr: str | None = None                  # attr 단위의 속성 이름
    quote: str | None = None                 # attr 단위의 따옴표(" ' 또는 '')
    path: tuple | None = None                # jsonld 단위의 JSON 경로

    def render(self, ja: str) -> str:
        """번역문을 원본 자리에 들어갈 문자열로 되돌린다."""
        if self.kind == "jsonld":
            return json.dumps(ja, ensure_ascii=False).replace("</", "<\\/")
        if self.kind == "attr":
            out = ja.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            if self.quote != "'":
                out = out.replace('"', "&quot;")
            if self.quote == "'":
                out = out.replace("'", "&#x27;")
            # 따옴표 없던 값은 따옴표로 감싼다 — 번역의 공백·`=` 가 속성을 쪼개지 않게(범위는 값만이다).
            return out if self.quote else f'"{out}"'
        parts, pos = [], 0
        for m in PH_RE.finditer(ja):
            parts.append(_esc_text(ja[pos:m.start()]))
            if m.group(0) not in self.ph:
                raise ValueError(f"unit {self.uid}: 원문에 없는 자리표시 {m.group(0)}")
            parts.append(self.ph[m.group(0)])
            pos = m.end()
        parts.append(_esc_text(ja[pos:]))
        return "".join(parts)


def _esc_text(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


@dataclass
class Doc:
    source: str
    units: list
    notes: list = field(default_factory=list)


# ── 토큰 ──────────────────────────────────────────────────────────────────

@dataclass
class Tok:
    kind: str        # start end startend data ref comment decl pi
    start: int
    end: int = 0
    tag: str | None = None
    attrs: list | None = None


class _Lexer(HTMLParser):
    def __init__(self, text):
        super().__init__(convert_charrefs=False)
        self._lines = [0] + [m.end() for m in re.finditer("\n", text)]
        self.toks: list[Tok] = []

    def _at(self):
        line, col = self.getpos()
        return self._lines[line - 1] + col

    def _add(self, kind, tag=None, attrs=None):
        self.toks.append(Tok(kind, self._at(), tag=tag, attrs=attrs))

    def handle_starttag(self, tag, attrs):
        self._add("start", tag, attrs)

    def handle_startendtag(self, tag, attrs):
        self._add("startend", tag, attrs)

    def handle_endtag(self, tag):
        self._add("end", tag)

    def handle_data(self, data):
        self._add("data")

    def handle_entityref(self, name):
        self._add("ref")

    def handle_charref(self, name):
        self._add("ref")

    def handle_comment(self, data):
        self._add("comment")

    def handle_decl(self, decl):
        self._add("decl")

    def handle_pi(self, data):
        self._add("pi")

    def unknown_decl(self, data):
        self._add("decl")


def tokens(text: str) -> list[Tok]:
    lx = _Lexer(text)
    lx.feed(text)
    lx.close()
    # 같은 위치에 둘 이상 찍힌 토큰은 마지막 것만 남긴다(앞의 것은 길이 0).
    out: list[Tok] = []
    for t in lx.toks:
        if out and out[-1].start == t.start:
            out[-1] = t
            continue
        out.append(t)
    if not out or out[0].start != 0:
        out.insert(0, Tok("data", 0))
    for a, b in zip(out, out[1:]):
        a.end = b.start
    out[-1].end = len(text)
    return [t for t in out if t.end > t.start]


# ── 속성 위치 ─────────────────────────────────────────────────────────────

_ATTR_RE = re.compile(
    r"""(?:^|(?<=[\s"'/]))([^\s/>"'=]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+)))?""")


def attr_spans(raw_tag: str):
    """`<tag a="v" ...>` 원문에서 (이름, 값 시작, 값 끝, 원문 값, 따옴표) 를 낸다."""
    m = re.match(r"<[^\s/>]+", raw_tag)
    pos = m.end() if m else 1
    for a in _ATTR_RE.finditer(raw_tag, pos):
        name = a.group(1).lower()
        for g, q in ((2, '"'), (3, "'"), (4, "")):
            if a.group(g) is not None:
                yield name, a.start(g), a.end(g), a.group(g), q
                break


# ── JSON 문자열 위치 ──────────────────────────────────────────────────────

_WS = re.compile(r"[ \t\n\r]*")
_NUM = re.compile(r"-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][-+]?\d+)?")


def json_strings(text: str):
    """JSON 문서의 **값** 문자열마다 (경로, 리터럴 시작, 끝, 값). 키는 내지 않는다.
    JSON 이 아니면 ValueError."""
    from json.decoder import scanstring
    out = []

    def ws(i):
        return _WS.match(text, i).end()

    def value(i, path):
        i = ws(i)
        c = text[i:i + 1]
        if c == "{":
            i = ws(i + 1)
            if text[i:i + 1] == "}":
                return i + 1
            while True:
                if text[i:i + 1] != '"':
                    raise ValueError(f"json key at {i}")
                key, i = scanstring(text, i + 1)
                i = ws(i)
                if text[i:i + 1] != ":":
                    raise ValueError(f"json colon at {i}")
                i = value(i + 1, path + (key,))
                i = ws(i)
                c = text[i:i + 1]
                if c == ",":
                    i = ws(i + 1)
                    continue
                if c == "}":
                    return i + 1
                raise ValueError(f"json object at {i}")
        if c == "[":
            i = ws(i + 1)
            if text[i:i + 1] == "]":
                return i + 1
            n = 0
            while True:
                i = value(i, path + (n,))
                n += 1
                i = ws(i)
                c = text[i:i + 1]
                if c == ",":
                    i += 1
                    continue
                if c == "]":
                    return i + 1
                raise ValueError(f"json array at {i}")
        if c == '"':
            s, j = scanstring(text, i + 1)
            out.append((path, i, j, s))
            return j
        for lit in ("true", "false", "null"):
            if text.startswith(lit, i):
                return i + len(lit)
        m = _NUM.match(text, i)
        if m and m.end() > i:
            return m.end()
        raise ValueError(f"json value at {i}")

    end = ws(value(0, ()))
    if end != len(text):
        raise ValueError(f"json trailing at {end}")
    return out


# ── 분해 ──────────────────────────────────────────────────────────────────

def _has_hangul_attr(text, tok):
    return any(name not in SKIP_ATTRS and HANGUL.search(_html.unescape(raw))
               for name, _s, _e, raw, _q in attr_spans(text[tok.start:tok.end]))


class _Ctx:
    """문맥용 조상 스택(근사). 닫는 태그는 스택에 있을 때만 그 자리까지 내린다."""

    def __init__(self):
        self.stack = []   # (tag, section_label)

    def open(self, tag, attrs):
        label = None
        if tag == "section":
            d = dict(attrs or [])
            label = d.get("id") or d.get("data-section") or ""
        self.stack.append((tag, label))

    def close(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                return

    def section(self):
        for tag, label in reversed(self.stack):
            if tag == "section":
                return label or None
        return None

    def block(self):
        return self.stack[-1][0] if self.stack else None


def split(html: str) -> Doc:
    toks = tokens(html)
    units: list[Unit] = []
    notes: list[str] = []
    ctx = _Ctx()
    run: list[Tok] = []

    def flush():
        if run:
            _flush_run(html, run, units, ctx)
            run.clear()

    i, n = 0, len(toks)
    while i < n:
        t = toks[i]
        if t.kind in ("start", "startend"):
            _attr_units(html, t, units, ctx)
        if t.kind == "start" and t.tag in RAW:
            flush()
            j = i + 1
            while j < n and not (toks[j].kind == "end" and toks[j].tag == t.tag):
                j += 1
            d = dict(t.attrs or [])
            if t.tag == "script" and (d.get("type") or "").strip().lower() == "application/ld+json" and j > i + 1:
                _jsonld_units(html, toks[i + 1].start, toks[j - 1].end, units, ctx, notes)
            i = j + 1
            continue
        if t.kind in ("data", "ref"):
            run.append(t)
        elif t.kind in ("start", "end", "startend") and t.tag in INLINE and not (
                t.kind != "end" and _has_hangul_attr(html, t)):
            if t.kind == "start" and t.tag in OPAQUE:
                depth, j = 1, i + 1
                while j < n and depth:
                    if toks[j].tag == t.tag and toks[j].kind == "start":
                        depth += 1
                    elif toks[j].tag == t.tag and toks[j].kind == "end":
                        depth -= 1
                    j += 1
                if depth == 0:
                    run.append(Tok("opaque", t.start, toks[j - 1].end, tag=t.tag))
                    i = j
                    continue
            run.append(t)
        else:
            flush()
            if t.kind == "start" and t.tag not in INLINE:
                ctx.open(t.tag, t.attrs)
            elif t.kind == "end" and t.tag not in INLINE:
                ctx.close(t.tag)
        i += 1
    flush()
    units.sort(key=lambda u: u.start)
    for k, u in enumerate(units):
        u.uid = k
    return Doc(html, units, notes)


def _attr_units(html, t, units, ctx):
    raw_tag = html[t.start:t.end]
    for name, s, e, raw, q in attr_spans(raw_tag):
        if name in SKIP_ATTRS:
            continue
        val = _html.unescape(raw)
        if HANGUL.search(val):
            units.append(Unit(0, "attr", val, t.start + s, t.start + e, section=ctx.section(),
                              block=t.tag, attr=name, quote=q))


def _jsonld_units(html, s, e, units, ctx, notes):
    text = html[s:e]
    try:
        strings = json_strings(text)
    except ValueError as exc:
        notes.append(f"ld+json 을 읽지 못했다({exc}) — 단위 없음")
        return
    for path, a, b, val in strings:
        if HANGUL.search(val):
            units.append(Unit(0, "jsonld", val, s + a, s + b, section=None, block="script", path=path))


def _flush_run(html, run, units, ctx):
    # 짝 맞추기: 같은 이름의 여는·닫는 인라인 태그를 스택으로 잇는다.
    pair = {}
    stack = []
    for k, t in enumerate(run):
        if t.kind == "start" and t.tag not in VOID:
            stack.append(k)
        elif t.kind == "end" and t.tag not in VOID:
            for j in range(len(stack) - 1, -1, -1):
                if run[stack[j]].tag == t.tag:
                    o = stack[j]
                    pair[o], pair[k] = k, o
                    del stack[j:]
                    break

    def trimmable(k):
        t = run[k]
        if t.kind == "data":
            return not html[t.start:t.end].strip()
        if t.kind in ("start", "end", "startend"):
            return k not in pair or t.tag in VOID or t.kind == "startend"
        return False

    lo, hi = 0, len(run)
    while lo < hi and trimmable(lo):
        lo += 1
    while hi > lo and trimmable(hi - 1):
        hi -= 1
    if lo >= hi:
        return
    body = run[lo:hi]
    start = body[0].start
    end = body[-1].end
    if body[0].kind == "data":
        raw = html[body[0].start:body[0].end]
        start += len(raw) - len(raw.lstrip())
    if body[-1].kind == "data":
        raw = html[body[-1].start:body[-1].end]
        end -= len(raw) - len(raw.rstrip())
    # 한글 확인(텍스트 부분만)
    text_has_hangul = any(
        t.kind in ("data", "ref") and HANGUL.search(_html.unescape(html[max(t.start, start):min(t.end, end)]))
        for t in body)
    if not text_has_hangul:
        return

    ph = {}
    names = {}
    parts = []
    buf = []
    counter = 0

    def flush_buf():
        if buf:
            parts.append(_html.unescape("".join(buf)))
            buf.clear()

    for k, t in enumerate(body, lo):
        a, b = max(t.start, start), min(t.end, end)
        if t.kind in ("data", "ref"):
            buf.append(html[a:b])
            continue
        flush_buf()
        raw = html[a:b]
        if t.kind == "start" and k in pair:
            name = letter(counter)
            counter += 1
            names[pair[k]] = name
            key = f"⟦{name}⟧"
        elif t.kind == "end" and k in names:
            key = f"⟦/{names[k]}⟧"
        else:
            key = f"⟦{letter(counter)}/⟧"
            counter += 1
        ph[key] = raw
        parts.append(key)
    flush_buf()
    units.append(Unit(0, "text", "".join(parts), start, end, ph=ph, section=ctx.section(), block=ctx.block()))


# ── 합치기 ────────────────────────────────────────────────────────────────

def join(doc: Doc, texts=None) -> str:
    """`texts` 가 없으면 원본 그대로. dict(uid→번역) 또는 단위 순서의 list."""
    if texts is None:
        return doc.source
    if isinstance(texts, (list, tuple)):
        if len(texts) != len(doc.units):
            raise ValueError(f"texts {len(texts)} != units {len(doc.units)}")
        texts = {u.uid: t for u, t in zip(doc.units, texts)}
    out, pos = [], 0
    src = doc.source
    for u in doc.units:
        ja = texts.get(u.uid)
        if ja is None:
            continue
        out.append(src[pos:u.start])
        out.append(u.render(ja))
        pos = u.end
    out.append(src[pos:])
    return "".join(out)
