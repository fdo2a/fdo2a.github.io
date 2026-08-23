"""발행본 가독성 — CSS 조판 소급 주입과 산문 계측.

두 가지를 한다.

1. `inject_css()` — 이미 나간 글의 `<style>` 끝에 조판 오버라이드를 덧붙인다.
   본문·수치·마크업은 건드리지 않는다. 마커로 멱등.
2. 산문 계측 — 문장 길이·문장당 수치·과잉 정밀도·수치 반복을 센다.
   발행 게이트(`scripts/check_readability.py`)와 회고에 쓴다.

왜 조판인가: 2026-08-24 실측에서 본문 컨테이너가 1120px인데 문단에 폭 제한이
없어 데스크톱 한 줄이 한글 약 65자였다(편한 범위는 35~45자). 줄간격 1.58~1.62,
문단 간격 9px도 한글 장문에는 좁다. 셋 다 CSS 한 덩이로 고쳐진다.
"""
import html as _html
import re
from collections import Counter

MARKER = "/* readability-v2 */"

# 한글 본문 한 줄 42자 안팎. letter-spacing -0.01em을 감안한 값이다.
CSS = """
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
""" % MARKER

_STRIP = re.compile(
    r"(?s)<head.*?</head>|<style.*?</style>|<script.*?</script>|<svg.*?</svg>|<!--.*?-->"
)
_P = re.compile(r"(?s)<p[^>]*>(.*?)</p>")
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


def has_override(html: str) -> bool:
    return MARKER in html


def inject_css(html: str) -> str:
    """조판 오버라이드를 `<head>` 안 마지막 `</style>` 앞에 덧붙인다. 멱등.

    본문에도 인라인 `<style>`(섹터 막대 등)이 있으므로 문서 전체에서 마지막
    것을 찾으면 카드 한복판에 끼어든다. 반드시 head 범위 안에서만 찾는다.
    """
    if has_override(html):
        return html
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


def paragraphs(html: str) -> list:
    """본문 `<p>`의 순수 텍스트. 표·차트·스타일은 제외."""
    body = _STRIP.sub("", html)
    out = []
    for raw in _P.findall(body):
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
    out = []
    for m in _NUM.finditer(text):
        tok = m.group(0).strip()
        if _DATEISH.fullmatch(tok):
            continue
        if re.fullmatch(r"\d", tok):  # 「세 갈래」류 한 자리 서수
            continue
        out.append(tok)
    return out


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
    return {
        "sentences": len(ss),
        "median_len": lens[len(lens) // 2],
        "p90_len": lens[int(len(lens) * 0.9) - 1],
        "over_120": sum(1 for x in lens if x > 120),
        "median_figures": sorted(figs)[len(figs) // 2],
        "overprecise": len(overprecise(html)),
        "echoed": len(echoed_figures(html)),
    }
