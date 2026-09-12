"""수치 칸에 방향 색을 입힌다 (2026-09-12 사용자 지시 「가시성을 높혀」).

게이트 체인의 보정 단계다. **작성 에이전트가 손으로 칠하지 않는다** — 매일 칠해야
하는 칸이 수십 개라 사람이 하면 틀리고, 틀린 색은 색이 없는 것보다 나쁘다.

보이는 글자는 한 자도 바꾸지 않는다. `<td>`에 class 만 얹으므로 수치 멀티셋
대조(`verify_post.py`), 분량 계측(`weight.prose_chars`), 문체·매크로·포트폴리오
게이트 전부 이 변경을 보지 못한다 — 전부 태그를 벗긴 텍스트나 `[^>]*` 속성 허용
정규식으로 읽는다(2026-09-12 codex 설계 검토에서 여섯 파일 대조).

**우리 열이 아닌 칸은 속성도 건드리지 않고, 우리 class 이름은 발행본과 겹치지 않는
것으로 쓴다.** 옛 발행본에는 표에 손으로 넣은 `<td class="neg">`가 편당 수십 개
있다(2026-08-18에 73개). 모든 칸의 class 를 다시 쓰던 첫 판은 그 색을 네 편에서
197개 지웠다(2026-09-12 codex 구현 검토).

규칙은 셋이고, **반전과 극성은 섹션 안에서만** 걸린다. 열 이름만 보고 문서 전체를
칠하면 「주간 변화」가 다른 섹션에 생긴 날 거꾸로 칠한다.

* 값 부호 그대로 — 「전일 대비」·「등락」 (오르면 초록)
* 반전 — 채권 섹션의 「전일 변화」·「주간 변화」 (금리가 떨어지면 초록)
* 지표 판정 — 매크로 섹션의 `Actual`. **판정을 다시 계산하지 않는다** — 같은 행의
  「판정」 칸에 `개선`·`악화`·`둔화`·`재가속`이 이미 계산돼 실려 있다. 원시 부호로
  다시 읽으면 실업수당이 **줄어든** 날을 나쁜 방향이라 칠한다(작성 사양 §9가
  판정 어휘를 도입한 바로 그 사고).
* **멀티에셋 섹션은 칠하지 않는다** — 그 표의 「전일대비」는 가격 변화가 아니라
  등급 이동(`유지`·`▲1단계`·`▼1단계`)이다. 부호로 읽으면 `▼1단계`가 초록이 된다.
"""

import re

from .macro_metrics import DIRECTION_WORDS, _POLARITY
from .readability import (_MASKED_ELEMENT, _V5_MARKER_RE, _blank_inert,
                          _find_in_head_css, _head_style_spans)

MARKER = "/* signcolor-v1 */"
CSS = ("\n%s\n"
       "td.sc-up { color: #00A85A; }\n"
       "td.sc-dn { color: #FF4040; }\n" % MARKER)

# `pos`·`neg` 를 쓰지 않는다. 발행본마다 그 이름의 CSS 가 이미 있고 서식이 다르다 —
# 2026-08-18 은 `.pos{color}` 지만 2026-09-11 은 배경까지 깔린 배지다. 이름이 겹치면
# 칸에 초록 배경이 깔리고, 남의 class 를 지우거나 되살리는 문제도 함께 생긴다.
POS, NEG = 'sc-up', 'sc-dn'

# 「전일대비」(붙여 쓴 꼴)는 스탠스 표의 등급 이동 열이라 여기 넣지 않는다.
SIGN_LABELS = ('전일 대비', '등락', '등락률')
YIELD_LABELS = ('전일 변화', '주간 변화')
MACRO_ACTUAL = ('Actual', '최근')
MACRO_PREVIOUS = ('Previous', '이전')
MACRO_VERDICT = ('판정', '추세')
MACRO_NAME = ('지표',)

# 판정 어휘는 `macro_metrics` 가 극성을 이미 반영해 만든 말이다. 성장축은 개선/악화,
# 물가축은 재가속(뜨거워짐)/둔화 — 경제·자산가격에 좋은 쪽은 개선과 둔화다.
_VERDICT_POS = (DIRECTION_WORDS['growth'][1], DIRECTION_WORDS['inflation'][-1])
_VERDICT_NEG = (DIRECTION_WORDS['growth'][-1], DIRECTION_WORDS['inflation'][1])

# 판정 열이 없는 옛 표(「최근 | 이전」)에만 쓰는 대체 경로. `_POLARITY` 는 「오르면
# 성장이 강해지거나 물가가 뜨거워진다」를 +1 로 적어 두었으므로 물가 축만 뒤집는다.
# 축 정보는 `econ_indicators.json` 에만 있고 그 파일은 과거 발행본에 소급할 때 없다.
INFLATION_AXIS = frozenset({
    'CPI YoY', 'CPI MoM', 'Core CPI YoY', 'Core CPI MoM', 'PPI Final Demand MoM',
    'PCE Price Index YoY', 'Core PCE YoY', 'Michigan 1-Yr Inflation Exp',
})

BOND_SECTION = '채권'
MACRO_SECTION = '매크로'
SKIP_SECTION = '멀티에셋'

_H2 = re.compile(r'(?is)<h2\b[^>]*>(.*?)</h2>')
_TD = re.compile(r'(?is)<td\b([^>]*)>(.*?)</td>')
_TR = re.compile(r'(?is)(<tr\b[^>]*>)(.*?)(</tr>)')
_TAG = re.compile(r'(?s)<[^>]+>')
# 따옴표 종류를 가린다. class 를 한 짝만 보면 `class='x'` 인 칸에 두 번째 class 속성을
# 덧붙여 깨진 태그를 만든다 — 색을 못 칠하는 것보다 나쁘다.
_LABEL = re.compile(r'''data-label\s*=\s*("|')(.*?)\1''')
_CLASS = re.compile(r'''\sclass\s*=\s*("|')(.*?)\1''')
# 칸 «맨 앞»의 한 수치만 읽는다. 어디서든 첫 수치를 집으면 각주 표식이 값을 이긴다 —
# `<sup>1</sup>-0.32%` 가 +1 로 읽혀 손실 칸이 초록이 됐다(2026-09-12 구현 검토).
_NUM = re.compile(r'-?\d[\d,]*(?:\.\d+)?')
_NUM_HEAD = re.compile(r'^[+(]?(-?\d[\d,]*(?:\.\d+)?)')
_FOOTNOTE = re.compile(r'(?is)<su[pb]\b[^>]*>.*?</su[pb]\s*>')
_MARKER_RE = re.compile(re.escape(MARKER))
# 0.00%·-0.00% 은 「변화 없음」이다. 부호만 보고 칠하면 움직이지 않은 날 빨강이 뜬다.
_EPS = 1e-9


def _text(html):
    return _TAG.sub('', html).replace('−', '-').replace('－', '-').strip()


def _number(cell):
    m = _NUM_HEAD.match(_text(_FOOTNOTE.sub('', cell)).replace(',', ''))
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def _label_of(attrs):
    m = _LABEL.search(attrs)
    return m.group(2) if m else ''


def good_sign(name):
    """그 지표가 «올라가면» 경제·자산가격에 좋은가. 모르는 지표는 None."""
    pol = _POLARITY.get(name)
    if pol is None:
        return None
    return pol[0] * (-1 if name in INFLATION_AXIS else 1)


def verdict_class(text):
    """판정 어휘 -> 색. 판정이 없거나 보합·교착이면 None."""
    for word in _VERDICT_POS:
        if word in text:
            return POS
    for word in _VERDICT_NEG:
        if word in text:
            return NEG
    return None


def _class_for(value, sign=1):
    if value is None or abs(value) < _EPS:
        return None
    return POS if value * sign > 0 else NEG


def _set_class(attrs, name):
    """`<td>` 속성 문자열에 색 class 를 얹는다. 기존 class 는 보존하고 옛 색은 지운다."""
    m = _CLASS.search(attrs)
    kept = [c for c in (m.group(2).split() if m else []) if c not in (POS, NEG)]
    if name:
        kept.append(name)
    if m:
        return (attrs[:m.start()]
                + (' class="%s"' % ' '.join(kept) if kept else '')
                + attrs[m.end():])
    return attrs + (' class="%s"' % ' '.join(kept) if kept else '')


def _pick(labels, names):
    for n in names:
        if n in labels:
            return labels[n]
    return None


def _macro_class(labels):
    """그 행의 Actual 칸에 줄 색. 판정 칸이 정본이고, 없으면 전기 대비로 대체한다."""
    verdict = _pick(labels, MACRO_VERDICT)
    if verdict is not None:
        return verdict_class(_text(verdict[1]))
    now, before = _pick(labels, MACRO_ACTUAL), _pick(labels, MACRO_PREVIOUS)
    name = _pick(labels, MACRO_NAME)
    if now is None or before is None or name is None:
        return None
    sign = good_sign(_text(name[1]))
    a, b = _number(now[1]), _number(before[1])
    if sign is None or a is None or b is None:
        return None
    return _class_for(a - b, sign)


def _paint_row(row, yields=False, macro=False):
    labels = {_label_of(a): (a, b) for a, b in _TD.findall(row)}
    macro_cls = _macro_class(labels) if macro else None

    def repaint(m):
        attrs, body = m.group(1), m.group(2)
        label = _label_of(attrs)
        if label in SIGN_LABELS:
            name = _class_for(_number(body))
        elif yields and label in YIELD_LABELS:
            name = _class_for(_number(body), -1)
        elif macro and label in MACRO_ACTUAL:
            name = macro_cls
        else:
            return m.group(0)       # 우리 열이 아니다 — 속성도 건드리지 않는다
        return '<td%s>%s</td>' % (_set_class(attrs, name), body)

    return _TD.sub(repaint, row)


def _scan_mask(html):
    """주석·스크립트·style·textarea 를 같은 길이의 공백으로 덮은 사본. 오프셋 보존.

    원문을 그대로 훑으면 주석 안의 가짜 `<h2>` 가 섹션을 끊고(채권 반전이 풀린다),
    `<style>` 문자열 안의 가짜 `<tr>` 이 실제 칸처럼 고쳐진다(2026-09-12 구현 검토).
    """
    return _MASKED_ELEMENT.sub(lambda m: " " * (m.end() - m.start()),
                               _blank_inert(html))


def _sections(mask):
    """[(제목, 시작, 끝)] — 본문을 h2 로 자른다. weight.section_slice 와 같은 seam."""
    heads = [(_text(m.group(1)), m.start()) for m in _H2.finditer(mask)]
    return [(title, start, heads[i + 1][1] if i + 1 < len(heads) else len(mask))
            for i, (title, start) in enumerate(heads)]


def paint(html):
    """섹션별 정책에 따라 셀에 class 를 얹는다. 멱등.

    행을 찾는 것은 가린 사본에서 하고, 고치는 것은 원문 같은 자리에서 한다.
    """
    mask = _scan_mask(html)
    out, cursor = [], 0
    for title, start, end in _sections(mask):
        out.append(html[cursor:start])
        if SKIP_SECTION in title:
            out.append(html[start:end])
        else:
            out.append(_repaint_rows(html, mask, start, end,
                                     BOND_SECTION in title,
                                     title.startswith(MACRO_SECTION)))
        cursor = end
    out.append(html[cursor:])
    return ''.join(out)


def _repaint_rows(html, mask, start, end, yields, macro):
    out, cursor = [], start
    for m in _TR.finditer(mask, start, end):
        out.append(html[cursor:m.start()])
        row = html[m.start():m.end()]
        head = row[:len(m.group(1))]
        body = row[len(m.group(1)):len(row) - len(m.group(3))]
        out.append(head + _paint_row(body, yields, macro) + row[len(head) + len(body):])
        cursor = m.end()
    out.append(html[cursor:end])
    return ''.join(out)


def inject_css(html):
    """head 안 마지막 `<style>` 끝에 색 규칙을 덧붙인다. 멱등.

    본문에도 인라인 `<style>`(섹터 막대)이 있어서 문서 전체의 마지막 것을 고르면
    카드 한복판에 끼어든다 — readability 가 같은 함정을 적어 둔 자리다.
    """
    # 마커는 **head 안 CSS 에서만** 인정한다. 본문 주석 아무 곳의 같은 문자열로도
    # 주입이 생략돼, class 만 있고 색 규칙이 없는 문서가 나갔다(2026-09-12 구현 검토).
    if _find_in_head_css(html, _MARKER_RE) is not None:
        return html
    spans = _head_style_spans(html)
    if spans:
        i = spans[-1][1]
        return html[:i] + CSS + html[i:]
    block = "<style>%s</style>\n" % CSS
    inert = _blank_inert(html)
    for anchor in ("</head>", "<body>"):
        i = inert.find(anchor)
        if i != -1:
            return html[:i] + block + html[i:]
    return block + html


def apply(html):
    return inject_css(paint(html))
