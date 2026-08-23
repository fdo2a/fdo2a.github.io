"""발행본 가독성 — CSS 조판 소급 주입과 산문 계측.

두 가지를 한다.

1. `enhance_html()` — 이미 나간 글의 조판을 갱신하고, 빠른 이동과 긴 문단
   분리를 더한다. 보이는 글자와 수치는 건드리지 않는다. 마커로 멱등.
2. 산문 계측 — 문장 길이·문장당 수치·과잉 정밀도·수치 반복을 센다.
   발행 게이트(`scripts/check_readability.py`)와 회고에 쓴다.

왜 조판인가: 2026-08-24 실측에서 본문 컨테이너가 1120px인데 문단에 폭 제한이
없어 데스크톱 한 줄이 한글 약 65자였다(편한 범위는 35~45자). 줄간격 1.58~1.62,
문단 간격 9px도 한글 장문에는 좁다. 셋 다 CSS 한 덩이로 고쳐진다.
"""
import html as _html
import re
from collections import Counter

MARKER = "/* readability-v3 */"
OLD_MARKER = "/* readability-v2 */"
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

# 한글 본문 한 줄 42자 안팎. letter-spacing -0.01em을 감안한 값이다.
CSS = """
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
""" % MARKER

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


def has_override(html: str) -> bool:
    return MARKER in html


def inject_css(html: str) -> str:
    """조판 오버라이드를 `<head>` 안 마지막 `</style>` 앞에 덧붙인다. 멱등.

    본문에도 인라인 `<style>`(섹터 막대 등)이 있으므로 문서 전체에서 마지막
    것을 찾으면 카드 한복판에 끼어든다. 반드시 head 범위 안에서만 찾는다.
    """
    if has_override(html):
        return html
    if OLD_MARKER in html:
        if _V2_CSS in html:
            return html.replace(_V2_CSS, CSS, 1)
        # v2는 항상 head의 마지막 CSS였다. 드문 서식 차이도 안전하게 마이그레이션한다.
        return re.sub(
            r"/\* readability-v2 \*/.*?(?=</style>)",
            CSS.strip() + "\n",
            html,
            count=1,
            flags=re.S,
        )
    head_end = html.find("</head>")
    scope = html[:head_end] if head_end != -1 else html
    idx = scope.rfind("</style>")
    if idx != -1:
        return html[:idx] + CSS + html[idx:]
    block = "<style>%s</style>\n" % CSS
    for anchor in ("</head>", "<body>"):
        i = html.find(anchor)
        if i != -1:
            return html[:i] + block + html[i:]
    return block + html


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


def enhance_html(html: str) -> str:
    """조판·문단·빠른 이동을 한 번에 적용한다. 보이는 숫자는 반드시 불변이다."""
    before = visible_numeric_tokens(html)
    out = inject_css(html)
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
