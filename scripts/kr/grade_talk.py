"""KR 본문의 노출 등급 말투를 찾는다 (2026-10-04 사용자 결정).

「코스피 노출은 다음 세션까지 유지하고, 정유주는 추격하지 않고 관찰에 둔다」를 사용자가
「알 수 없는 멘트」로 지적했다. 그 문장은 계약이 만들었다 — §2 action 이 노출 등급(확대·유지·
축소)과 시계를 매일 밝혀야 했다. 이제 등급·시계는 원장(`kr_stance_next.json`)에만 남고 다음 날
채점도 거기서 한다. 본문은 무엇을 기다리는지·무엇이 판단을 바꾸는지로 말한다.

여기서 막는 것은 계약이 기계적으로 만들던 **선언형**뿐이다. 「대미 노출이 큰 업종」「변동성에
노출된다」 같은 정당한 용례와 섞이지 않게 좁혔고, 나머지(수식어 뒤 맨 「노출을 유지」, 시계 라벨,
「추격하지 않는다·관찰에 둔다」)는 작성 지시문이 맡는다.

호출: `kr.stance_gate.check`(일간 — §12 뉴스 블록 면제, 같은 게이트 묶음의 check_news 가 guid 를
대조한다), `check_period.py --market kr`(주간·월간), `review.corrector`(정정 뒤 원본보다 늘어난 것만).

Pure — HTML 문자열을 받아 걸린 구간 목록을 돌려준다.
"""
import html as _html
from html.parser import HTMLParser
import re

from us.style import _body

VERBS = (r"(?:유지|확대|축소|늘리|늘린|늘렸|늘릴|늘려|줄이|줄인|줄였|줄일|줄여"
         r"|넓히|넓힌|넓혔|넓힐|넓혀)")
SUBJECTS = r"(?:위험|코스피|주식|지수|시장)"
G1 = re.compile(r"노출\s*등급")
G2 = re.compile(r"노출\s*(?:유지|확대|축소)")
G3 = re.compile(SUBJECTS + r"\s*노출(?:은|을|도|의)?\s")
G4 = re.compile(r"노출(?:을|은|도)\s+(?:다시\s+|더\s+)?" + VERBS)
_VERB = re.compile(VERBS)
# 앞 어절이 이것으로 끝나면 「노출」(G4)·주어(G3)를 꾸미는 명사가 없다 — 「대미 노출을 줄인 기업」은
# 앞 어절 「대미」가 명사라 해당 없다.
# 「가」「이」는 뺐다 — 「주가」「국가」「차이」처럼 명사 끝과 갈리지 않는다.
_FREE_BEFORE = ("는", "은", "을", "를", "로", "고", "며", "서", "면", "에", "도", "의", "라",
                "와", "과", "지만", "동안", "때", "뒤", "전")
# 끝 글자가 어미처럼 보이는 명사 — 「재고 노출을 줄인 기업」(2026-10-04 codex 구현 검토).
_NOUNS = ("재고", "광고", "최고", "신고", "경고", "참고", "사고", "잔고", "창고", "원고", "제고")
_CLAUSE_END = re.compile(r"[,;]|\S(?:지만|으며|며|는데|고)(?=\s)")
_NEWS_H2 = re.compile(r"<h2\b[^>]*>\s*오늘의 뉴스\s*</h2\s*>", re.I)
_BLOCK = re.compile(r"</?(?:p|h[1-6]|li|td|th|tr|caption|div|section|ul|ol|table|figcaption)\b[^>]*>",
                    re.I)
_TAG = re.compile(r"<[^>]+>")
_SENT = re.compile(r"(?<=[.!?])\s+|\n+")
_VOID = {"br", "hr", "img", "meta", "link", "input", "source", "wbr", "area", "base", "embed",
         "param", "track", "col"}


class _Extents(HTMLParser):
    """요소마다 (태그, 시작, 끝, 속성) — 중첩을 따라 짝을 맞춘다."""

    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.offsets = [0]
        for line in html.splitlines(keepends=True):
            self.offsets.append(self.offsets[-1] + len(line))
        self.html, self.stack, self.out = html, [], []
        self.feed(html)
        self.close()

    def _pos(self):
        row, col = self.getpos()
        return self.offsets[row - 1] + col

    def handle_starttag(self, tag, attrs):
        if tag not in _VOID:
            self.stack.append((tag, self._pos(), dict(attrs)))

    def handle_endtag(self, tag):
        names = [t for t, _, _ in self.stack]
        if tag not in names:
            return
        while self.stack:
            name, start, attrs = self.stack.pop()
            if name == tag:
                end = self.html.find(">", self._pos()) + 1
                self.out.append((name, start, end, attrs))
                return


def _strip_news(body):
    """§12 「오늘의 뉴스」 구간(그 h2 를 감싼 section, 없으면 다음 h2 까지) 안의 `data-news` 요소만 뺀다.
    같은 게이트 묶음의 check_news 가 그 guid 를 수집분과 대조한다 — 면제는 그 경로에서만 쓴다."""
    h2 = _NEWS_H2.search(body)
    if not h2:
        return body
    elements = _Extents(body).out
    around = [(s, e) for name, s, e, _ in elements if name == "section" and s < h2.start() < e]
    if around:
        lo, hi = max(around)
    else:
        nxt = re.compile(r"<h2\b", re.I).search(body, h2.end())
        lo, hi = h2.start(), nxt.start() if nxt else len(body)
    cut = sorted((s, e) for _, s, e, attrs in elements
                 if "data-news" in attrs and lo <= s and e <= hi)
    out, at = [], 0
    for s, e in cut:
        if s >= at:
            out.append(body[at:s] + " ")
            at = e
    return "".join(out) + body[at:]


def reader_text(html, exempt_news=False):
    """독자가 읽는 텍스트 — 제목·헤드라인 카드·표·캡션 포함, 스크립트·근거 블록·생성 연구 요약 제외.
    소스 줄바꿈은 공백, 블록 경계는 줄바꿈, 인라인 태그(`<br>`·`<strong>`)는 공백으로 본다."""
    body = _body(html)
    if exempt_news:
        body = _strip_news(body)
    body = re.sub(r"\s+", " ", body)
    body = _BLOCK.sub("\n", body)
    return _html.unescape(_TAG.sub(" ", body))


def _free_before(sentence, pos):
    head = sentence[:pos].rstrip()
    word = head.split()
    if not word or head.endswith((",", ";", ":")):
        return True   # 문장 처음이거나 쉼표 뒤 — 꾸미는 명사가 없다
    last = word[-1]
    return last.endswith(_FREE_BEFORE) and not last.endswith(_NOUNS)


def _clause_verb(rest):
    """`rest` 의 첫 절 안에 조정 동사가 있으면 그 끝 위치."""
    clause = rest
    for end in _CLAUSE_END.finditer(rest):
        if end.group(0) not in ",;" and rest[: end.end()].split()[-1].endswith(_NOUNS):
            continue   # 「재고」의 「고」는 연결 어미가 아니다
        clause = rest[: end.start() + 1]
        break
    m = _VERB.search(clause)
    return m.end() if m else None


def find(html, exempt_news=False):
    """걸린 구간(공백 정규화)을 문서 순서대로."""
    out = []
    for sentence in _SENT.split(reader_text(html, exempt_news)):
        s = re.sub(r"\s+", " ", sentence).strip()
        if "노출" not in s:
            continue
        spans = [(m.start(), m.end()) for m in G1.finditer(s)]
        spans += [(m.start(), m.end()) for m in G2.finditer(s)]
        for m in G3.finditer(s):
            stop = _clause_verb(s[m.end():])
            if stop is not None and _free_before(s, m.start()):
                spans.append((m.start(), m.end() + stop))
        for m in G4.finditer(s):
            if _free_before(s, m.start()):
                spans.append((m.start(), m.end()))
        kept = []
        for a, b in sorted(spans):
            if kept and a < kept[-1][1]:
                kept[-1] = (kept[-1][0], max(b, kept[-1][1]))
            else:
                kept.append((a, b))
        out += [s[a:b] for a, b in kept]
    return out


def violations(html, exempt_news=False):
    return [f"본문에 노출 등급 말투가 있다 — 「{span}」. 등급·시계는 kr_stance_next.json 에만 적고, "
            "본문은 무엇을 기다리는지·무엇이 판단을 바꾸는지로 쓴다"
            for span in find(html, exempt_news)]
