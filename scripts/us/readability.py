"""발행본 가독성 — CSS 조판 소급 주입과 산문 계측.

두 가지를 한다.

1. `enhance_html()` — 이미 나간 글의 조판을 갱신하고, 빠른 이동과 긴 문단
   분리를 더한다. 보이는 글자와 수치는 건드리지 않는다. 마커로 멱등.
2. 산문 계측 — 문장 길이·문장당 수치·과잉 정밀도·수치 반복을 센다.
   발행 게이트(`scripts/check_readability.py`)와 회고에 쓴다.

왜 조판인가: 2026-08-24 실측에서 본문 컨테이너가 1120px인데 문단에 폭 제한이
없어 데스크톱 한 줄이 한글 약 65자였다(편한 범위는 35~45자). 줄간격 1.58~1.62,
문단 간격 9px도 한글 장문에는 좁다. 셋 다 CSS 한 덩이로 고쳐진다.

v4는 그 교정이 데스크톱에서 지나쳤던 것을 되돌린다. 2026-08-26 실측에서 뷰포트
1440px든 768px든 문단 폭이 똑같이 672px이었다 — 카드는 1080px인데 글이 672px만
쓰니 오른쪽 408px이 늘 비었고, PC로 봐도 모바일 화면을 늘려 놓은 꼴이었다.
1024px 이상에서만 본문 글자를 17px로 키운다.

v5는 그 폭 제한마저 데스크톱에서 걷어낸다 (2026-08-28 사용자 지시 —
「문장 끝이 네모 전체에 차게, 중간에 줄바꿈 하지 말고」). v4의 50em은 1080px
카드에서 여전히 오른쪽 230px을 비웠다. 단어가 줄 끝에서 잘리지 않는 것은
`word-break: keep-all`이 이미 보장한다. 함께: 문단 첫머리 라벨을 제 줄로 올려
제목 옆에 본문이 이어 붙지 않게 한다(`box-label`·`p-label`).
"""
import html as _html
import re
from collections import Counter

MARKER = "/* readability-v5 */"
V4_MARKER = "/* readability-v4 */"
V3_MARKER = "/* readability-v3 */"
OLD_MARKER = "/* readability-v2 */"
_V5_MARKER_RE = re.compile(r"/\*\s*readability-v5\s*\*/", re.I)
_V4_MARKER_RE = re.compile(r"/\*\s*readability-v4\s*\*/", re.I)
_V3_MARKER_RE = re.compile(r"/\*\s*readability-v3\s*\*/", re.I)
_V2_MARKER_RE = re.compile(r"/\*\s*readability-v2\s*\*/", re.I)
# 데스크톱 본문 — 글자만 키우고 폭은 카드에 맡긴다 (v5).
DESKTOP_MIN_PX = 1024
DESKTOP_FONT = "17px"
READING_MAP_MARKER = "<!-- reading-map-v1 -->"
STRATEGY_FIRST_MARKER = "<!-- strategy-first-v1 -->"

# v2는 조판만 고쳤다. v3는 긴 보고서의 읽는 경로와 문단 경계를 보강한다.
_V2_CSS = """
%s
.card p, .doc p, .panel p, p { line-height: 1.78; margin: 0 0 15px; max-width: 42em; }
.card p:last-child, .doc p:last-child, .panel p:last-child, p:last-child { margin-bottom: 0; }
.card { padding: 20px 22px; }
h2 { line-height: 1.45; margin-bottom: 14px; }
h3, h4 { line-height: 1.45; }
.caption, .sub, .footer-note, .note, .lead, li { max-width: 42em; }
table { font-variant-numeric: tabular-nums; }
@media (max-width: 560px) {
  .card p, .doc p, .panel p, p { line-height: 1.72; margin-bottom: 13px; }
  .card { padding: 16px 16px; }
}
""" % OLD_MARKER

# v3 — 한글 본문 한 줄 42자 안팎. letter-spacing -0.01em을 감안한 값이다.
_V3_CSS = """
%s
.card p, .doc p, .panel p, p { line-height: 1.78; margin: 0 0 15px; max-width: 42em; }
.card p:last-child, .doc p:last-child, .panel p:last-child, p:last-child { margin-bottom: 0; }
.card { padding: 20px 22px; }
h1 { max-width: 34em; }
h2 { line-height: 1.45; margin-bottom: 14px; }
h3, h4 { line-height: 1.45; }
.caption, .sub, .footer-note, .note, .lead, li { max-width: 42em; }
table { font-variant-numeric: tabular-nums; }
section { scroll-margin-top: 20px; }
.reading-map { display: flex; align-items: center; gap: 8px; overflow-x: auto;
  margin: -2px 0 20px; padding: 10px 2px 4px; scrollbar-width: none; }
.reading-map::-webkit-scrollbar { display: none; }
.reading-map-label { flex: 0 0 auto; color: #8B95A1; font-size: 12px; font-weight: 700; }
.reading-map a { flex: 0 0 auto; color: #4E5968; background: #fff; border: 1px solid #E5E8EB;
  border-radius: 9999px; padding: 6px 11px; font-size: 12.5px; font-weight: 700;
  line-height: 1.2; text-decoration: none; }
.reading-map a:first-of-type { color: #0064FF; border-color: #B9D5FF; background: #F5F9FF; }
.reading-map a:focus-visible { outline: 2px solid #0064FF; outline-offset: 2px; }
@media (max-width: 560px) {
  .card p, .doc p, .panel p, p { line-height: 1.72; margin-bottom: 13px; }
  .card { padding: 16px 16px; }
  .reading-map { margin-bottom: 16px; }
}
""" % V3_MARKER

# v4 — 데스크톱만 넓힌다. 기본 조판(모바일·태블릿)은 v3 그대로 42em/16px.
# 폰트 확대는 `p:not([class])`로 한정한다: `.card p`(0,1,1)가 `.caption`(0,1,0)을
# 이기므로 무조건 얹으면 12.5px 캡션이 본문 크기로 튀어오른다.
_DESKTOP_CSS = """
@media (min-width: %dpx) {
  .card p, .doc p, .panel p, p,
  .caption, .sub, .footer-note, .note, .lead, li { max-width: none; }
  .card p:not([class]), .doc p:not([class]), .panel p:not([class]), p:not([class]),
  .doc li { font-size: %s; line-height: 1.8; }
  h1 { font-size: 25px; max-width: 30em; }
  h2 { font-size: 20px; }
  h3 { font-size: 17px; }
}
""" % (DESKTOP_MIN_PX, DESKTOP_FONT)

# 라벨은 본문 옆이 아니라 본문 위에 선다 (2026-08-28 사용자 지시). box-label은
# 알약 모양이라 통짜 block으로 두면 카드 폭만큼 늘어난다 — fit-content로 모양을
# 지키고 줄만 차지하게 한다.
_LABEL_CSS = """
.box-label { display: block; width: fit-content; margin-bottom: 6px; }
.p-label { display: block; margin-bottom: 2px; }
.box-label, .p-label { break-after: avoid-page; page-break-after: avoid; }
"""

CSS = (_V3_CSS.replace(V3_MARKER, MARKER).rstrip("\n")
       + _LABEL_CSS + _DESKTOP_CSS)

_STRIP = re.compile(
    r"(?s)<head.*?</head>|<style.*?</style>|<script.*?</script>|<svg.*?</svg>|"
    r"<section\b[^>]*data-editor-note.*?</section>|<!--.*?-->"
)
_P = re.compile(r"(?s)<p\b([^>]*)>(.*?)</p>")
_TAG = re.compile(r"<[^>]+>")
# 문장 부호가 없는 한국어 종결(…다.)까지 잡는다.
_SENT = re.compile(r"(?<=다\.)\s+|(?<=[.?!])\s+")
_NUM = re.compile(
    r"[+-]?\$?\d[\d,]*(?:\.\d+)?\s*(?:%|bp|bps|억원|조원|원|달러|엔|건|배|년|월|일|시)?"
)
# 1,234.56 처럼 천단위 구분과 소수점을 함께 쓴 값 — 산문에서는 반올림한다.
# 산문에서 명백히 과한 정밀도 — 백만 단위 이상의 소수, 그리고 소수점 붙은 원화.
# (금 종가 $4,661.60처럼 실제 호가는 그대로 두고, 이동평균 2,043,966.67원만 잡는다)
_OVERPRECISE = re.compile(r"\d[\d,]*\.\d+\s*원|\d{1,3}(?:,\d{3}){2,}\.\d+")
_LOOSE_PRECISE = re.compile(r"\d{1,3}(?:,\d{3})+\.\d+")
# 날짜·시각은 읽기 부담으로 세지 않는다 — 수치 밀도는 「시세가 몇 개인가」의 문제다.
_DATEISH = re.compile(r"(19|20)\d{2}년?|\d{1,2}[월일시]")
_TIMEISH_SPAN = re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\s*(?:ET|KST)?\b", re.I)
_DATEISH_SPAN = re.compile(
    r"\b(?:19|20)\d{2}[-./]\d{1,2}(?:[-./]\d{1,2})?\b|"
    r"(?<!\d)\d{1,2}[-/]\d{1,2}(?!\d)|\b\d+s\d+s\b",
    re.I,
)
_INTERVALISH_SPAN = re.compile(r"(?<!\d)\d+\s*(?:분봉|일선|년물)")
_EXCLUDED_P_CLASS = re.compile(
    r"\b(?:caption|sub|muted|footer-note|source|sources|note|disclaimer)\b", re.I
)


# `<script>`와 주석 안 텍스트는 마크업이 아니다. head에는 JSON-LD와 광고 로더가
# 함께 있어서, 그 안의 문자열이 `</head>`나 `<style>`을 품으면 경계 판정이 어긋난다.
_INERT = re.compile(r"(?is)<script\b[^>]*>.*?</script\s*>|<!--.*?-->")


def _blank_inert(html: str) -> str:
    """스크립트·주석 내용을 같은 길이의 공백으로 덮는다. 오프셋은 그대로."""
    return _INERT.sub(lambda m: " " * (m.end() - m.start()), html)


def _head_scope_end(html: str) -> int:
    """Return the first boundary after head CSS, including head-less old posts."""
    inert = _blank_inert(html)
    match = re.search(r"(?i)</head\s*>", inert)
    if match:
        return match.start()
    match = re.search(r"(?i)<body\b", inert)
    return match.start() if match else len(html)


_STYLE_EL = re.compile(r"(?is)<style\b[^>]*>(.*?)</style\s*>")


def _head_style_spans(html: str):
    """head 안 실제 `<style>` 요소의 (내용 시작, 내용 끝) 목록.

    마커도 삽입 지점도 여기서만 찾는다. head에는 JSON-LD와 광고 로더가 함께
    있어서, 바이트 범위를 통째로 훑으면 `<script>` 안 문자열이 CSS로 오인된다
    — 그러면 마이그레이션이 JSON-LD 한복판을 잘라낸다.
    """
    scope_end = _head_scope_end(html)
    # 스크립트 안 `<style>` 문자열은 요소가 아니다. 길이를 보존해 덮었으므로
    # 여기서 얻은 오프셋은 원본 html에 그대로 쓸 수 있다.
    return [
        (m.start(1), m.end(1))
        for m in _STYLE_EL.finditer(_blank_inert(html)[:scope_end])
    ]


def _find_in_head_css(html: str, marker_re):
    """head CSS 안에서 마커를 찾아 (스타일 span, 매치)를 준다. 없으면 None."""
    for start, end in _head_style_spans(html):
        m = marker_re.search(html, start, end)
        if m:
            return (start, end), m
    return None


def has_override(html: str) -> bool:
    return _find_in_head_css(html, _V5_MARKER_RE) is not None


def inject_css(html: str) -> str:
    """조판 오버라이드를 `<head>` 안 마지막 `<style>` 끝에 덧붙인다. 멱등.

    본문에도 인라인 `<style>`(섹터 막대 등)이 있으므로 문서 전체에서 마지막
    것을 찾으면 카드 한복판에 끼어든다. 반드시 head의 `<style>` 안에서만 찾는다.
    """
    if has_override(html):
        return html
    for marker_re, block in ((_V4_MARKER_RE, None), (_V3_MARKER_RE, _V3_CSS),
                             (_V2_MARKER_RE, _V2_CSS)):
        found = _find_in_head_css(html, marker_re)
        if not found:
            continue
        (span_start, span_end), match = found
        style_css = html[span_start:span_end]
        if block and block in style_css:
            return html[:span_start] + style_css.replace(block, CSS, 1) + html[span_end:]
        # 앞선 판은 늘 그 `<style>`의 마지막 CSS였다. 서식 차이도 안전하게 옮긴다.
        return html[:match.start()] + CSS.strip() + "\n" + html[span_end:]
    spans = _head_style_spans(html)
    if spans:
        idx = spans[-1][1]
        return html[:idx] + CSS + html[idx:]
    block = "<style>%s</style>\n" % CSS
    inert = _blank_inert(html)
    for anchor in ("</head>", "<body>"):
        i = inert.find(anchor)
        if i != -1:
            return html[:i] + block + html[i:]
    return block + html


# `.card p`처럼 한정된 선택자에 font-size가 얹히면 특정도 (0,1,1)이 되어
# `.caption`(0,1,0)을 이긴다 — 캡션·각주가 본문 크기로 인쇄된다.
_QUALIFIED_P = re.compile(r"^(?:\.[\w-]+\s+)+p$")
_CSS_NON_CODE = re.compile(
    r"/\*.*?\*/|\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'", re.S
)


def _next_css_open(css: str, start: int) -> int:
    """Find an unquoted, uncommented opening brace."""
    i = start
    while i < len(css):
        if css.startswith("/*", i):
            end = css.find("*/", i + 2)
            if end == -1:
                return -1
            i = end + 2
            continue
        if css[i] in "\"'":
            quote = css[i]
            i += 1
            while i < len(css):
                if css[i] == "\\":
                    i += 2
                elif css[i] == quote:
                    i += 1
                    break
                else:
                    i += 1
            continue
        if css[i] == "\\":
            i += 2
            continue
        if css[i] == "{":
            return i
        i += 1
    return -1


def _matching_css_close(css: str, opening: int) -> int:
    """Find the brace paired with ``opening``, ignoring strings and comments."""
    depth, i = 1, opening + 1
    while i < len(css):
        if css.startswith("/*", i):
            end = css.find("*/", i + 2)
            if end == -1:
                return -1
            i = end + 2
            continue
        if css[i] in "\"'":
            quote = css[i]
            i += 1
            while i < len(css):
                if css[i] == "\\":
                    i += 2
                elif css[i] == quote:
                    i += 1
                    break
                else:
                    i += 1
            continue
        if css[i] == "\\":
            i += 2
            continue
        if css[i] == "{":
            depth += 1
        elif css[i] == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _split_css_selectors(selector: str) -> list[str]:
    """Split only on top-level commas, preserving commas in strings and functions."""
    parts, start, i = [], 0, 0
    square = paren = 0
    while i < len(selector):
        if selector.startswith("/*", i):
            end = selector.find("*/", i + 2)
            i = len(selector) if end == -1 else end + 2
            continue
        if selector[i] in "\"'":
            quote = selector[i]
            i += 1
            while i < len(selector):
                if selector[i] == "\\":
                    i += 2
                elif selector[i] == quote:
                    i += 1
                    break
                else:
                    i += 1
            continue
        if selector[i] == "\\":
            i += 2
            continue
        if selector[i] == "[":
            square += 1
        elif selector[i] == "]":
            square = max(0, square - 1)
        elif selector[i] == "(":
            paren += 1
        elif selector[i] == ")":
            paren = max(0, paren - 1)
        elif selector[i] == "," and square == 0 and paren == 0:
            parts.append(selector[start:i])
            start = i + 1
        i += 1
    parts.append(selector[start:])
    return parts


def _demote_selector(prelude: str, block: str) -> str:
    declarations = _CSS_NON_CODE.sub("", block)
    if not re.search(r"(?i)(?:^|;)\s*font-size\s*:", declarations):
        return prelude
    leading = prelude[:len(prelude) - len(prelude.lstrip())]
    trailing = prelude[len(prelude.rstrip()):]
    core = prelude[len(leading):len(prelude) - len(trailing) if trailing else None]
    parts = [part.strip() for part in _split_css_selectors(core)]
    if "p" not in parts:
        return prelude
    kept = [part for part in parts if not _QUALIFIED_P.fullmatch(part)]
    if kept == parts:
        return prelude
    return leading + ", ".join(kept) + trailing


def _rewrite_css_rules(css: str) -> str:
    """Rewrite qualified paragraph selectors without parsing CSS as flat regex text."""
    out, pos = [], 0
    while True:
        opening = _next_css_open(css, pos)
        if opening == -1:
            out.append(css[pos:])
            break
        closing = _matching_css_close(css, opening)
        if closing == -1:
            out.append(css[pos:])
            break
        prelude, block = css[pos:opening], css[opening + 1:closing]
        code = _CSS_NON_CODE.sub("", prelude).lstrip()
        if code.startswith("@"):
            block = _rewrite_css_rules(block)
        else:
            prelude = _demote_selector(prelude, block)
        out.extend((prelude, "{", block, "}"))
        pos = closing + 1
    return "".join(out)


def demote_card_p_font(html: str) -> str:
    """본문 크기를 정하는 규칙에서 `.card p`류 한정 선택자를 떨어낸다.

    2026-08-26 실측: KR 발행본 5편과 US 5편이 `.card p, p { font-size:16px }`를
    썼고, 그 글들만 12.5px 캡션이 16px로 떴다. 맨 `p`가 같은 규칙에 함께 있을
    때만 떼어내므로 본문 크기는 그대로고 클래스 붙은 문단만 제 크기를 찾는다.
    멱등.
    """

    # 진짜 `<style>` 안에서만 고친다 — 스크립트 문자열 속 CSS 흉내는 CSS가 아니다.
    out = []
    at = 0
    for start, end in _head_style_spans(html):
        out.append(html[at:start])
        out.append(_rewrite_css_rules(html[start:end]))
        at = end
    out.append(html[at:])
    return "".join(out)


def _plain(raw: str) -> str:
    return re.sub(r"\s+", " ", _html.unescape(_TAG.sub("", raw))).strip()


def split_dense_paragraphs(html: str, limit: int = 320) -> str:
    """세 문장 이상인 긴 `<p>`를 두 문장 단위로 나눈다.

    단어·문장부호·수치에는 손대지 않고 블록 경계만 추가한다. 인라인 마크업이
    있는 문단은 태그 쌍을 가로질러 자를 위험이 있어 보수적으로 건너뛴다.
    """

    def repl(m):
        attrs, inner = m.group(1), m.group(2)
        if _EXCLUDED_P_CLASS.search(attrs) or "<" in inner or len(_plain(inner)) <= limit:
            return m.group(0)
        core = inner.rstrip()
        boundaries = list(re.finditer(r"(?<=[.!?])\s+", core))
        if len(boundaries) < 2:  # 문장 셋 미만
            return m.group(0)
        units, start = [], 0
        for boundary in boundaries:
            units.append(inner[start:boundary.end()])
            start = boundary.end()
        units.append(core[start:])
        parts = ["".join(units[i:i + 2]).rstrip() for i in range(0, len(units), 2)]
        parts = [part for part in parts if part]
        if len(parts) < 2:
            return m.group(0)
        return "\n".join("<p%s>%s</p>" % (attrs, part) for part in parts)

    # 위 조합은 첫/끝 태그를 직접 보존하므로 두 문단 이상일 때만 반환된다.
    out = _P.sub(repl, html)
    return out


def inject_reading_map(html: str) -> str:
    """최대 다섯 개 핵심 섹션으로 이동하는 독자용 경로를 헤드라인 뒤에 넣는다."""
    if READING_MAP_MARKER in html:
        return html

    sections = []

    def number_section(m):
        opening, body, closing = m.group(1), m.group(2), m.group(3)
        h = re.search(r"<h2\b[^>]*>(.*?)</h2>", body, re.S)
        if not h:
            return m.group(0)
        label = _plain(h.group(1))
        ident = re.search(r"\bid\s*=\s*['\"]([^'\"]+)", opening)
        if ident:
            sid = ident.group(1)
        else:
            sid = "read-%d" % (len(sections) + 1)
            opening = opening[:-1] + ' id="%s">' % sid
        sections.append((label, sid))
        return opening + body + closing

    out = re.sub(r"(<section\b[^>]*>)(.*?)(</section>)", number_section, html, flags=re.S)
    if len(sections) < 2:
        return out

    wanted = [
        ("전략 코멘트", r"전략 코멘트"),
        ("시장 흐름", r"^(?:주식|지수.*장중|지수)$"),
        ("금리·수급", r"^(?:채권|수급|환율·금리)$"),
        ("거시·포트폴리오", r"^(?:매크로 논리|멀티에셋 매니저 전략)$"),
        ("종목·섹터", r"(?:주목 섹터|특징주|업종·섹터|메모리/DRAM)"),
        ("정책·리스크", r"(?:정책·정치|원자재)"),
    ]
    links, used = [], set()
    for short, pattern in wanted:
        for label, sid in sections:
            if sid not in used and re.search(pattern, label):
                links.append((short, sid))
                used.add(sid)
                break
        if len(links) == 5:
            break
    def short_label(label):
        aliases = [
            (r"일봉", "일봉 차트"), (r"기술적", "기술 전략"),
            (r"거래대금", "거래대금"), (r"특징주", "특징주"),
            (r"환율|FX", "환율·금리"), (r"AI 인프라", "AI 인프라"),
        ]
        for pattern, alias in aliases:
            if re.search(pattern, label):
                return alias
        clean = re.sub(r"\([^)]*\)", "", label)
        clean = re.sub(r"\d", "", clean).split("—", 1)[0].strip()
        return clean[:14] or "세부 분석"

    for label, sid in sections:
        if len(links) == 5:
            break
        if sid not in used:
            links.append((short_label(label), sid))
            used.add(sid)

    nav = (
        "\n" + READING_MAP_MARKER + "\n"
        '<nav class="reading-map" aria-label="보고서 빠른 이동">'
        '<span class="reading-map-label">빠른 이동</span>'
        + "".join('<a href="#%s">%s</a>' % (sid, _html.escape(label)) for label, sid in links)
        + "</nav>\n"
    )
    headline = re.search(r"<section\b[^>]*>(?:(?!</section>).)*?<h1\b.*?</section>", out, re.S)
    if headline:
        return out[:headline.end()] + nav + out[headline.end():]
    headline_box = re.search(
        r'<div\b[^>]*class=["\'][^"\']*\bheadline\b[^"\']*["\'][^>]*>.*?</div>',
        out,
        re.S,
    )
    if headline_box:
        return out[:headline_box.end()] + nav + out[headline_box.end():]
    doc = re.search(r'<div\b[^>]*class=["\'][^"\']*\bdoc\b[^"\']*["\'][^>]*>', out)
    at = doc.end() if doc else 0
    return out[:at] + nav + out[at:]


def move_strategy_first(html: str) -> str:
    """전략 코멘트를 헤드라인·빠른 이동 바로 뒤로 옮긴다.

    문장이나 숫자는 바꾸지 않고 읽는 순서만 판단 우선으로 바꾼다. 바로 뒤에
    붙은 에디터 노트가 있으면 둘을 함께 옮겨 발행자 의견의 위치도 보존한다.
    """
    if STRATEGY_FIRST_MARKER in html:
        return html
    strategy = re.search(
        r'<section\b[^>]*>(?:(?!</section>).)*?<h2\b[^>]*>\s*'
        r'(?:전략 코멘트|Buy-side 종합 해석)\s*</h2>.*?</section>',
        html,
        re.S | re.I,
    )
    if not strategy:
        return html
    start, end = strategy.span()
    trailing = re.match(
        r'\s*<section\b[^>]*data-editor-note[^>]*>.*?</section>',
        html[end:],
        re.S,
    )
    if trailing:
        end += trailing.end()
    block = html[start:end]
    cleaned = html[:start] + html[end:]

    nav_marker = cleaned.find(READING_MAP_MARKER)
    if nav_marker != -1:
        nav_end = cleaned.find("</nav>", nav_marker)
        at = nav_end + len("</nav>") if nav_end != -1 else nav_marker
    else:
        headline = re.search(r"<section\b[^>]*>(?:(?!</section>).)*?<h1\b.*?</section>", cleaned, re.S)
        if headline:
            at = headline.end()
        else:
            headline_box = re.search(
                r'<div\b[^>]*class=["\'][^"\']*\bheadline\b[^"\']*["\'][^>]*>.*?</div>',
                cleaned,
                re.S,
            )
            at = headline_box.end() if headline_box else 0
    return cleaned[:at] + "\n" + STRATEGY_FIRST_MARKER + "\n" + block + "\n" + cleaned[at:]


def visible_numeric_tokens(html: str) -> list:
    """CSS·속성을 뺀 독자 노출 숫자. 구조 보정 전후 불변 확인에 쓴다."""
    body = _STRIP.sub("", html)
    text = _html.unescape(_TAG.sub(" ", body))
    return re.findall(r"[+-]?\$?\d[\d,]*(?:\.\d+)?%?", text)


_LABEL_STRONG = re.compile(r"(?s)(<p\b[^>]*>\s*)<strong>([^<]{1,20})</strong>")
_LABEL_END = re.compile(r"[.:：]$")
_SENTENCE_END = re.compile(r"[다요]\.$")


def block_labels(html: str) -> str:
    """문단 첫머리의 라벨을 제 줄로 올린다. 보이는 글자는 그대로다.

    라벨과 강조된 첫 문장은 **문장부호의 위치**로 갈린다. `<strong>오늘의 행동.</strong>`
    `<strong>동인:</strong>`처럼 마침표·콜론이 안에 있으면 라벨이고,
    `<strong>…지배했습니다</strong>.`처럼 밖에 있으면 그냥 문장이다. 종결어미
    (…다./…요.)로 끝나는 것은 길이가 짧아도 문장으로 본다 — 「고용은 개선 쪽이다.」를
    라벨로 올리면 문단이 두 동강 난다. 부호가 아예 없는 것도 라벨로 치지 않는다:
    `<strong>코스피</strong>는 종가…`의 굵은 말은 라벨이 아니라 문장의 주어다.

    태그 뒤 공백은 남긴다. 블록이라 화면에서는 접히지만, 복사하거나 평문으로
    뽑으면 「오늘의 행동.축소합니다」처럼 붙어 나온다.
    """
    def sub(m):
        text = m.group(2).strip()
        if not _LABEL_END.search(text) or _SENTENCE_END.search(text):
            return m.group(0)
        return '%s<strong class="p-label">%s</strong>' % (m.group(1), m.group(2))

    out = _LABEL_STRONG.sub(sub, html)
    # 이미 붙인 라벨의 잃어버린 공백을 되살린다 — 위 정규식은 class가 붙은
    # `<strong>`을 다시 잡지 않으므로 재적용만으로는 복구되지 않는다.
    return re.sub(r'(<strong class="p-label">[^<]*</strong>)(?=[^\s<])', r"\1 ", out)


_LABEL_EL = re.compile(r'(?is)<(\w+)([^>]*\bclass="[^"]*\b(?:box-label|p-label)\b[^"]*"[^>]*)>')
_INLINE_DISPLAY = re.compile(r'(?i)display\s*:\s*inline(?:-block)?\s*;?')


def unpin_inline_labels(html: str) -> str:
    """라벨의 인라인 `display:inline`을 걷어낸다.

    인라인 스타일은 시트를 이긴다. 소급 판 34건이 `style="display:inline;"`을
    달고 있어 CSS만 고쳐서는 라벨이 여전히 본문 옆에 붙어 있었다
    (2026-08-28 codex 검토에서 발견). 다른 선언(margin-top 등)은 건드리지 않는다.
    """
    def sub(m):
        attrs = m.group(2)

        def style_sub(sm):
            cleaned = _INLINE_DISPLAY.sub("", sm.group(2)).strip()
            if not cleaned.strip("; "):
                return ""
            return '%s"%s"' % (sm.group(1), cleaned)

        return "<%s%s>" % (m.group(1),
                           re.sub(r'(\s*style=)"([^"]*)"', style_sub, attrs))

    return _LABEL_EL.sub(sub, html)


def enhance_html(html: str) -> str:
    """조판·문단·빠른 이동을 한 번에 적용한다. 보이는 숫자는 반드시 불변이다."""
    before = visible_numeric_tokens(html)
    out = inject_css(html)
    out = demote_card_p_font(out)
    out = block_labels(out)
    out = unpin_inline_labels(out)
    out = split_dense_paragraphs(out)
    out = inject_reading_map(out)
    out = move_strategy_first(out)
    if Counter(visible_numeric_tokens(out)) != Counter(before):
        raise ValueError("가독성 보정 중 보이는 숫자가 바뀌었다")
    return out


def paragraphs(html: str) -> list:
    """본문 `<p>`의 순수 텍스트. 표·차트·스타일은 제외."""
    body = _STRIP.sub("", html)
    out = []
    for attrs, raw in _P.findall(body):
        if _EXCLUDED_P_CLASS.search(attrs):
            continue
        text = _html.unescape(_TAG.sub("", raw)).strip()
        if len(text) > 20:
            out.append(re.sub(r"\s+", " ", text))
    return out


def sentences(html: str) -> list:
    out = []
    for para in paragraphs(html):
        for s in _SENT.split(para):
            s = s.strip()
            if len(s) > 10:
                out.append(s)
    return out


def figures(text: str) -> list:
    """문장 안의 수치 토큰. 연도(4자리 정수)는 수치 부담으로 세지 않는다."""
    text = _TIMEISH_SPAN.sub("", text)
    text = _DATEISH_SPAN.sub("", text)
    text = _INTERVALISH_SPAN.sub("", text)
    out = []
    for m in _NUM.finditer(text):
        tok = m.group(0).strip()
        if _DATEISH.fullmatch(tok):
            continue
        if re.fullmatch(r"\d", tok):  # 「세 갈래」류 한 자리 서수
            continue
        out.append(tok)
    return out


def first_heading(html: str, tag: str = "h1") -> str:
    m = re.search(r"<%s\b[^>]*>(.*?)</%s>" % (tag, tag), html, re.S | re.I)
    return _plain(m.group(1)) if m else ""


def long_sentences(html: str, limit: int = 120) -> list:
    return [(s, len(s)) for s in sentences(html) if len(s) > limit]


def dense_sentences(html: str, limit: int = 6) -> list:
    out = []
    for s in sentences(html):
        n = len(figures(s))
        if n > limit:
            out.append((s, n))
    return out


def overprecise(html: str) -> list:
    """산문에 남은 과잉 정밀 수치. 표 안의 값은 대상이 아니다."""
    out = []
    for s in sentences(html):
        out += _OVERPRECISE.findall(s)
    return out


def loosely_precise(html: str) -> list:
    """천단위 + 소수를 함께 쓴 산문 수치. 실제 호가일 수 있어 경고까지만."""
    out = []
    for s in sentences(html):
        out += [x for x in _LOOSE_PRECISE.findall(s) if not _OVERPRECISE.fullmatch(x)]
    return out


def echoed_figures(html: str, limit: int = 3) -> list:
    """산문에서 같은 수치가 몇 번 되풀이됐나. 표 1회 + 본문 1~2회가 정상."""
    c = Counter()
    for s in sentences(html):
        for tok in set(figures(s)):
            c[tok] += 1
    return sorted(
        ((tok, n) for tok, n in c.items() if n > limit),
        key=lambda kv: -kv[1],
    )


def measure(html: str) -> dict:
    ss = sentences(html)
    if not ss:
        return {"sentences": 0}
    lens = sorted(len(s) for s in ss)
    figs = [len(figures(s)) for s in ss]
    ps = paragraphs(html)
    plens = sorted(len(p) for p in ps)
    return {
        "sentences": len(ss),
        "median_len": lens[len(lens) // 2],
        "p90_len": lens[int(len(lens) * 0.9) - 1],
        "over_120": sum(1 for x in lens if x > 120),
        "median_figures": sorted(figs)[len(figs) // 2],
        "p90_figures": sorted(figs)[max(0, int(len(figs) * 0.9) - 1)],
        "paragraphs": len(ps),
        "median_para_len": plens[len(plens) // 2] if plens else 0,
        "p90_para_len": plens[max(0, int(len(plens) * 0.9) - 1)] if plens else 0,
        "over_300_para": sum(1 for x in plens if x > 300),
        "overprecise": len(overprecise(html)),
        "echoed": len(echoed_figures(html)),
    }
