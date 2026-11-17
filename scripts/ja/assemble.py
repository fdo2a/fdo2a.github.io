"""일본어 글로 조립 — 뼈대는 한글판 그대로 두고 번역 단위만 바꾼 뒤, 머리 값과 상대 주소를 고친다.

순서: `news.localize` → `extract.split` → `state.plan`(+ 2차의 모델 번역) → `build`.
`build` 의 `source_html` 은 **split 에 넣은 것과 같은 문자열**(localize 뒤 HTML)이다.

바꾸는 것:
- `<html lang>` → ja, `<body data-register="da">` → ja.
- `</head>` 앞에 `<style id="ja-typography">` 한 덩어리(일본어 줄바꿈·글꼴). 원본 body 규칙이
  `</head>` 뒤 `<style>` 에도 있어서(실물 112곳) 선택자를 `html[lang="ja"] body` 로 높여 이긴다.
  원본 `word-break:keep-all` 은 지우지 않는다(뼈대 불변). `overflow-wrap: anywhere` 는 글 문단에만 —
  표 칸(td·th)에 걸면 좁은 화면에서 숫자가 중간에 끊길 수 있어 원본 `break-word` 를 둔다.
- canonical·og:url·og:locale(ja_JP)·JSON-LD `url`/`mainEntityOfPage` → 일본어판 주소, `inLanguage` → ja,
  hreflang ko/ja 링크.
- 상대 주소(href·src·data-index·data-news-index): 일본어판에 없는 대상(`OUT_OF_JA` — 디렉터리 자체 `../kr/`
  도)만 한글판의 실제 자리를 가리키게 다시 계산. `assets/yield_curve_*.png` 는 `ja/assets/` 같은 이름(2차가 만든다).
  `live`(나가 있는 일본어 글 경로 집합)를 주면 `href` 가운데 일본어판 범위의 **글**(`ARTICLE`)인데 집합에 없는
  것도 한글 원문으로 보낸다 — 아직 안 나간 일본어 글로 가는 빈 링크를 막는다. 목록 페이지·자산·목록 json 은
  그대로. `link_targets` 가 그 대상 목록이다(러너가 대상의 발행 여부를 deps 에 넣는다).
- 언어 버튼(`gate.lang_button`) 하나를 `<body>` 바로 뒤에.
- script·style·주석에 남는 한글: script 는 `SCRIPT_STRINGS` 표, 한글이 든 CSS·HTML 주석은 지운다
  (표시되지 않는 글이고, 표식 주석 `<!-- post-shell-v1 -->` 등에는 한글이 없다). 표에 없는 한글이
  script 에 남으면 `gate.check_doc` 이 막는다 — 그게 의도다.
"""
from __future__ import annotations

import html as _html
import json
import posixpath
import re

from . import extract as X
from . import gate

# 조립 규칙의 판. 이 파일(또는 extract·news 의 조립 결과)을 바꿔 이미 나간 일본어 글을 다시 조립해야 하면
# 사람이 올린다 — 러너는 원장의 renderer 가 이 값과 다르면 모델 호출 없이 다시 조립한다.
RENDERER = "r2"
JA_BASE = "https://fdo2a.github.io/ja/"
JA_FONTS = "'Hiragino Sans','Hiragino Kaku Gothic ProN','Noto Sans JP','Yu Gothic'"
DEFAULT_STACK = "-apple-system,BlinkMacSystemFont,sans-serif"

# 주간(`weekly/`, `japan/posts/`)은 일본어판에 없다(2026-11-17) — 한글 글로 보낸다.
OUT_OF_JA_DIRS = ("assets/", "kr/", "thesis/", "china/", "weekly/", "japan/posts/")
OUT_OF_JA_FILES = ("about.html", "privacy.html")
JA_ASSET = re.compile(r"^assets/yield_curve_[^/]*\.png$")
URL_ATTRS = ("href", "src", "data-index", "data-news-index")
_ABS = re.compile(r"[a-zA-Z][a-zA-Z0-9+.\-]*:|#|//|/")
# 일본어판 범위의 글(목록 json 이 있는 세 갈래) — `pipeline.LIST_SOURCES` 와 같은 꼴.
ARTICLE = re.compile(r"(?:posts|news|japan/daily)/[^/]+\.html")

# script 안 한글 고정 문자열(정확히 일치하는 부분 문자열 → 일본어). 2026-11-14 실물 151편에는
# ld+json 밖 script 에 한글이 없다(글 끝 이동 막대의 한글은 HTML 쪽이라 단위가 덮는다).
SCRIPT_STRINGS: dict = {}

NOTICE_TEXT = "韓国語版が更新されました。日本語版は更新待ちです。"
NOTICE_LINK = "韓国語版を読む"
_NOTICE_RE = re.compile(r'\n?<div class="ja-notice" data-ja-notice>.*?</a></div>', re.S)
_BODY_OPEN = re.compile(r"<body\b[^>]*>", re.I)


def ja_url_of(path: str, ja_base: str = JA_BASE) -> str:
    return ja_base + path


def _out_of_ja(target: str) -> bool:
    return (target in OUT_OF_JA_FILES or target.startswith(OUT_OF_JA_DIRS)
            or target + "/" in OUT_OF_JA_DIRS)


def _target(value: str, path: str):
    """(정규화한 대상, 뒤꼬리 ?#…) 또는 None(절대 주소·빈 값·레포 밖)."""
    if not value or _ABS.match(value):
        return None
    m = re.match(r"([^?#]*)(.*)", value, re.S)
    base, rest = m.group(1), m.group(2)
    if not base:
        return None
    target = posixpath.normpath(posixpath.join(posixpath.dirname(path), base))
    if target.startswith("../") or target == "..":
        return None
    return target, rest


def link_targets(source_html: str, path: str) -> list:
    """이 글의 `href` 가 상대 주소로 가리키는 일본어판 범위의 글 경로(자기 자신 제외, 처음 나온 순서)."""
    out = []
    for t in X.tokens(source_html):
        if t.kind not in ("start", "startend"):
            continue
        for n, _s, _e, rv, _q in X.attr_spans(source_html[t.start:t.end]):
            if n != "href":
                continue
            tg = _target(_html.unescape(rv), path)
            if tg and ARTICLE.fullmatch(tg[0]) and tg[0] != path and tg[0] not in out:
                out.append(tg[0])
    return out


def rewrite_relative(value: str, path: str, live=None, attr: str = "href") -> str:
    """한글판 `path` 기준 상대 주소를 `ja/<path>` 자리에서 맞게 고친다. `live` 는 위 머리말."""
    tg = _target(value, path)
    if tg is None:
        return value
    target, rest = tg
    base = re.match(r"[^?#]*", value).group(0)
    d = posixpath.dirname(path)
    unpublished = (live is not None and attr == "href" and ARTICLE.fullmatch(target)
                   and target != path and target not in live)
    if JA_ASSET.match(target) or not (_out_of_ja(target) or unpublished):
        return value
    new = posixpath.relpath(target, posixpath.join("ja", d) if d else "ja")
    if base.endswith("/") and not new.endswith("/"):
        new += "/"
    return new + rest


def _font_stack(source_html: str) -> str:
    stack = None
    for m in re.finditer(r"<style[^>]*>(.*?)</style>", source_html, re.S | re.I):
        css = re.sub(r"/\*.*?\*/", "", m.group(1), flags=re.S)
        for r in re.finditer(r"(?:^|[{};,\s])body\s*\{([^{}]*)\}", css):
            f = re.search(r"font-family\s*:\s*([^;]+)", r.group(1))
            if f:
                stack = f.group(1).strip()
    return stack or DEFAULT_STACK


def typography_block(source_html: str) -> str:
    stack = _font_stack(source_html)
    return ('<style id="ja-typography">\n'
            'html[lang="ja"] body, html[lang="ja"] body * { word-break: normal; line-break: strict; }\n'
            'html[lang="ja"] body :is(p, li, h1, h2, h3, h4, summary, blockquote, .caption) '
            '{ overflow-wrap: anywhere; }\n'
            f'html[lang="ja"] body {{ font-family: {JA_FONTS}, {stack}; }}\n'
            '.ja-lang-bar { max-width: 1120px; margin: 8px auto 0; padding: 0 16px; text-align: right; font-size: 13px; }\n'
            '.ja-notice { max-width: 1120px; margin: 8px auto; padding: 10px 16px; border-radius: 10px; '
            'background: #FFF8E1; color: #5D4300; font-size: 14px; }\n'
            '</style>\n')


def _hreflang(ko_url, ja_url):
    return (f'\n<link rel="alternate" hreflang="ko" href="{_html.escape(ko_url, quote=True)}">'
            f'\n<link rel="alternate" hreflang="ja" href="{_html.escape(ja_url, quote=True)}">')


def _set_attr(raw_tag, name, value):
    """시작 태그 원문에서 속성 값 하나를 바꾸거나(있으면) 더한다(없으면)."""
    esc = _html.escape(value, quote=True)
    for n, s, e, _raw, q in X.attr_spans(raw_tag):
        if n == name:
            if q:
                return raw_tag[:s] + esc + raw_tag[e:]
            return raw_tag[:s] + f'"{esc}"' + raw_tag[e:]
    m = re.match(r"<[^\s/>]+", raw_tag)
    return raw_tag[:m.end()] + f' {name}="{esc}"' + raw_tag[m.end():]


def _attrs(raw_tag):
    return {n: _html.unescape(raw) for n, _s, _e, raw, _q in X.attr_spans(raw_tag)}


def _ldjson(text, ja_url):
    try:
        strings = X.json_strings(text)
    except ValueError:
        return text
    edits = []
    for path, s, e, _v in strings:
        if path in (("url",), ("mainEntityOfPage",), ("mainEntityOfPage", "@id")):
            edits.append((s, e, json.dumps(ja_url, ensure_ascii=False)))
        elif path == ("inLanguage",):
            edits.append((s, e, '"ja"'))
    return _apply(text, edits)


def _apply(text, edits):
    out, pos = [], 0
    for s, e, rep in sorted(edits):
        out.append(text[pos:s])
        out.append(rep)
        pos = e
    out.append(text[pos:])
    return "".join(out)


_CSS_COMMENT = re.compile(r"/\*.*?\*/", re.S)


def _skeleton(html: str, path: str, ko_url: str, ja_url: str, live=None) -> str:
    toks = X.tokens(html)
    edits = []
    canonical_end = None
    raw_mode = None
    for i, t in enumerate(toks):
        raw = html[t.start:t.end]
        if raw_mode:
            if t.kind == "end" and t.tag == raw_mode[0]:
                raw_mode = None
            elif t.kind == "data":
                kind = raw_mode[1]
                if kind == "style":
                    new = _CSS_COMMENT.sub(lambda m: "" if X.HANGUL.search(m.group(0)) else m.group(0), raw)
                elif kind == "ld":
                    new = _ldjson(raw, ja_url)
                else:
                    new = raw
                    for ko, ja in SCRIPT_STRINGS.items():
                        new = new.replace(ko, ja)
                if new != raw:
                    edits.append((t.start, t.end, new))
            continue
        if t.kind == "comment":
            if X.HANGUL.search(raw):
                edits.append((t.start, t.end, ""))
            continue
        if t.kind not in ("start", "startend"):
            continue
        new = raw
        a = _attrs(raw)
        if t.tag == "html":
            new = _set_attr(new, "lang", "ja")
        elif t.tag == "body" and "data-register" in a:
            new = _set_attr(new, "data-register", "ja")
        elif t.tag == "link" and (a.get("rel") or "").lower() == "canonical":
            new = _set_attr(new, "href", ja_url)
            canonical_end = t.end
        elif t.tag == "meta" and (a.get("property") or "").lower() == "og:url":
            new = _set_attr(new, "content", ja_url)
        elif t.tag == "meta" and (a.get("property") or "").lower() == "og:locale":
            new = _set_attr(new, "content", "ja_JP")
        for n, s, e, rv, q in reversed(list(X.attr_spans(new))):
            if n in URL_ATTRS:
                fixed = rewrite_relative(_html.unescape(rv), path, live, n)
                if fixed != _html.unescape(rv):
                    val = _html.escape(fixed, quote=True)
                    # 따옴표 없이 쓴 값은 엔티티가 풀리며 공백이 생기면 거기서 잘린다 — 고쳐 쓸 때는 감싼다
                    new = new[:s] + (val if q else f'"{val}"') + new[e:]
        if new != raw:
            edits.append((t.start, t.end, new))
        if t.kind == "start" and t.tag in X.RAW:
            typ = (a.get("type") or "").strip().lower()
            raw_mode = (t.tag, "style" if t.tag == "style" else "ld" if typ == "application/ld+json" else "script")
    if canonical_end is not None:
        edits.append((canonical_end, canonical_end, _hreflang(ko_url, ja_url)))
    return _apply(html, edits)


def build(source_html: str, path: str, texts, *, ko_url: str, ja_base: str = JA_BASE, live=None) -> str:
    """번역(uid → ja)을 넣어 일본어 글을 만든다. 빠진 단위는 한글로 남고 check_doc 이 막는다."""
    ja_url = ja_url_of(path, ja_base)
    doc = X.split(source_html)
    out = X.join(doc, texts)
    out = _skeleton(out, path, ko_url, ja_url, live)
    head_close = out.lower().find("</head>")
    if head_close >= 0:
        extra = typography_block(source_html)
        if "hreflang=" not in out[:head_close]:
            extra = _hreflang(ko_url, ja_url).lstrip("\n") + "\n" + extra
        out = out[:head_close] + extra + out[head_close:]
    bar = f'<div class="ja-lang-bar">{gate.lang_button(ko_url)}</div>\n'
    m = _BODY_OPEN.search(out)
    if m:
        out = out[:m.end()] + "\n" + bar.rstrip("\n") + out[m.end():]
    else:
        out = bar + out
    return out


def notice_block(ko_url: str) -> str:
    return (f'<div class="ja-notice" data-ja-notice>{NOTICE_TEXT}'
            f'<a href="{_html.escape(ko_url, quote=True)}" hreflang="ko">{NOTICE_LINK}</a></div>\n')


def with_notice(html_ja: str, ko_url: str) -> str:
    """`<body…>` 바로 뒤에 「한국어판이 갱신됐다」 알림. 이미 있으면 그대로(멱등)."""
    if "data-ja-notice" in html_ja:
        return html_ja
    m = _BODY_OPEN.search(html_ja)
    at = m.end() if m else 0
    return html_ja[:at] + "\n" + notice_block(ko_url).rstrip("\n") + html_ja[at:]


def without_notice(html_ja: str) -> str:
    return _NOTICE_RE.sub("", html_ja, count=1)
