"""Reading layers for the US/KR daily brief — a header before the first section of each layer.

2026-10-31 external review asked to separate explanation from reference data (summary /
confirmed facts / interpretation / judgment / reference). The judgment stays on top (user
choice): layer 1 is the headline and 전략 코멘트, so it gets no header. Sections keep their
order and their gate contracts; this only labels where a layer starts.

The shell inserts the headers, so only newly rendered posts change — `apply_readability`
replays over the whole archive and would requeue every post for review. A header carries no
number and no <h2>/<p>: gates slice sections up to the next <h2> and count digits.
Design: docs/superpowers/specs/2026-10-31-reading-layers.md
"""
import html as _html
import re

# Posts rendered for this trading day or later get layer headers.
PARTS_FROM = '2026-11-02'

# (layer, header, section titles). A title matches by prefix (「연준 이벤트 — …」).
# Titles not listed stay in the layer that is already open.
LAYERS = {
    'us': (
        (2, '오늘 확인된 것', ('오늘의 장', '주식', '섹터 기간별 수익률', '채권', 'FX', '원자재',
                          '주목 섹터·종목')),
        (3, '해석', ('매크로', '연준 이벤트')),
        (4, '판단과 복기', ('트렌드 유닛 점검', '시장 판단과 복기')),
    ),
    'kr': (
        (2, '오늘 확인된 것', ('오늘의 장', '지수 & 장중', '수급', '거래대금 상위 종목',
                          '업종·섹터 멀티기간 수익률', '특징주·대장주', '환율·금리')),
        (3, '해석', ('아시아 세션 유닛 관측', '정책·정치 촉매')),
        (4, '복기와 확인 일정', ('시장 판단과 복기', '향후 확인 일정')),
        (5, '참고 자료', ('일봉 차트', '기술적 분석 & 트레이딩 전략', '오늘의 뉴스')),
    ),
}

CLASS = 'part-head'
_INERT = re.compile(r'<!--.*?-->|<(script|style|template|textarea)\b[^>]*>.*?</\1\s*>', re.S | re.I)
_SECTION_TAG = re.compile(r'<(/?)section\b[^>]*>', re.I)
_H2 = re.compile(r'<h2\b[^>]*>(.*?)</h2>', re.S | re.I)
_TAG = re.compile(r'<[^>]+>')
_DAY = re.compile(r'\d{4}-\d{2}-\d{2}')


def _blank(text):
    """Comments and script-like elements blanked to spaces, offsets kept — a <section> written
    inside them is not a section (codex implementation review 2026-10-31 #1)."""
    return _INERT.sub(lambda m: ' ' * len(m.group(0)), text)


def top_sections(body):
    """(start, end, title) of every top-level <section>. The title is the section's own <h2> —
    one inside a nested section belongs to that child (codex re-review 2026-10-31 #1)."""
    masked, out, depth, start, inner = _blank(body), [], 0, None, []
    for m in _SECTION_TAG.finditer(masked):
        if not m.group(1):
            if depth == 0:
                start, inner = m.start(), []
            elif depth == 1:
                inner.append([m.start(), None])
            depth += 1
        elif depth:
            depth -= 1
            if depth == 1 and inner:
                inner[-1][1] = m.end()
            elif depth == 0:
                own = masked[start:m.end()]
                for a, b in reversed(inner):
                    own = own[:a - start] + ' ' * ((b or m.end()) - a) + own[(b or m.end()) - start:]
                h = _H2.search(own)
                out.append((start, m.end(), _title(h.group(1)) if h else ''))
    return out


def _title(raw):
    return re.sub(r'\s+', ' ', _html.unescape(_TAG.sub('', raw))).strip()


def layer_of(market, title):
    for layer, _, titles in LAYERS.get(market, ()):
        if any(title == t or title.startswith(t + ' ') for t in titles):
            return layer
    return None


def head(layer, label):
    return f'<div class="{CLASS}" id="part-{layer}" data-part="{layer}">{label}</div>\n'


def applies(market, date):
    # Calendar dates only: '20261101' would otherwise compare as later than PARTS_FROM.
    return market in LAYERS and bool(_DAY.fullmatch(date or '')) and date >= PARTS_FROM


def mark(body, market):
    """Insert a header before the first section of each layer. Layers only move forward:
    a section placed out of order joins the layer already open rather than reopening one."""
    if f'class="{CLASS}"' in _blank(body) or market not in LAYERS:
        return body
    labels = {layer: label for layer, label, _ in LAYERS[market]}
    out, at, current = [], 0, 1
    for start, _, title in top_sections(body):
        layer = layer_of(market, title)
        if layer is not None and layer > current:
            out.append(body[at:start])
            out.append(head(layer, labels[layer]))
            at, current = start, layer
    out.append(body[at:])
    return ''.join(out)


def parts(html):
    """(id, label) of the headers in document order — the reading map links to these."""
    return re.findall(r'<div class="%s" id="(part-\d)" data-part="\d">([^<]+)</div>' % CLASS, _blank(html))
