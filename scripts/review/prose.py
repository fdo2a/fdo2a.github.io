"""이 판과 저 판의 차이가 «조판 도구가 한 일»뿐인가.

원장이 blob SHA 하나로만 동일성을 판단하던 탓에, `apply_readability.py` 가 조판 사양을
고칠 때마다 발행본 60여 편이 통째로 큐에 다시 올랐다(2026-08-24·26·28 세 차례, 실측
51건). `.claude/REVIEW_GATE.md` §2 는 codex 검토에서 「레이아웃·HTML·CSS는 보지 마」라고
지시하므로 그 51건은 **정의상 지적을 만들 수 없다.**

**방향이 이 모듈의 전부다.** 초안은 두 판을 각각 손실 정규화해 해시를 맞댔는데, 그 방식은
2026-09-04 codex 검토에서 두 번 뚫렸다 — 마커 뒤에 `html, body { display:none !important; }`
를 넣어도 지문이 같았고(지우는 규칙은 무엇이 지워지는지를 보지 않는다), 서로 다른 CSS 가 같은
정준형으로 합쳐졌다. 그래서 뒤집었다.

**사람이 이미 읽은 판을 조판 변환으로 밀어, 새 판이 바이트 그대로 나오는지만 본다.**
통과하는 새 판은 **단 하나**다 — 옛 판과 블록으로 완전히 결정되므로 그 사이에 무엇도 끼워
넣을 수 없다. 새 판은 어디서도 정규화하지 않는다.

블록은 아무거나 받지 않는다. `known_blocks` 에 등록된 것만 조판으로 인정한다.

설계: /Users/daeyoung/Desktop/AI/report/plan.md
"""

import base64
import os
import re
import sys
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common import adsense, analytics  # noqa: E402
from review.known_blocks import is_known  # noqa: E402
from us.colorize import paint  # noqa: E402
from us.readability import _blank_inert as blank_inert  # noqa: E402
from us.readability import _head_style_spans as head_style_spans  # noqa: E402
from us.readability import (block_labels, demote_card_p_font,  # noqa: E402
                            split_title_sentences, unpin_inline_labels)

_MARKER = re.compile(r'/\*\s*readability-v\d+\s*\*/', re.I)

# **감추는** 선언. 값까지 본다 — `display:inline-block` 은 라벨을 옆에 세울 뿐이고 실제로
# 발행본 CSS 에 흔하다(오탐 19편, 2026-09-04 실측). 문단을 사라지게 하는 것만 센다.
# 감추는 방법을 전부 열거할 수는 없다. 이것은 보안 경계가 아니라 사고 방지용 가드다.
_HIDING = re.compile(
    r'(?:^|[;{])\s*(?:'
    r'display\s*:\s*(?:none|var\()'
    r'|visibility\s*:\s*(?:hidden|collapse|inherit|var\()'
    r'|opacity\s*:\s*(?:0(?:\.0+)?\s*(?:;|$|!)|0\s*%|calc\(|var\()'
    r'|font-size\s*:\s*0'
    r'|content\s*:\s*none'
    r'|(?:max-)?height\s*:\s*0'
    r'|width\s*:\s*0'
    r'|text-indent\s*:\s*-'
    r'|clip(?:-path)?\s*:'
    r'|transform\s*:\s*scale\(\s*0'
    r'|(?:left|top)\s*:\s*-\s*\d{3}'
    r')', re.I)
# 특정도가 내려가는 것만으로 문제가 되는 선언들(값은 무엇이든).
_VISIBILITY = re.compile(
    r'(?i)(?:^|[;{])\s*(display|visibility|opacity|content|position)\s*:')
_FONT_SIZE = re.compile(r'(?i)(?:^|[;{])\s*font-size\s*:')
_LABEL_SEL = re.compile(r'(?i)(?:box|p)-label')
# 제목 문장 원소(`split_title_sentences` 의 `<tl-s>`)에 닿을 수 있는 CSS 는 **보수적으로** 막는다.
# 감추는 선언을 나열하는 방식은 두 번 뚫렸다(codex 11/05 재검토 #2·#3 — `content-visibility`,
# `opacity:.0`, `:nth-child(2n + 1)`, `:has(span)`). 그래서 방향을 뒤집었다 — 그 원소에 닿을 수
# 있는 선택자(전칭 주어 `*`·`:…`, 원소 이름, 그것을 품는 `:has()`)가 있으면, 선언이 아래
# 허용 목록 안일 때만 통과시키고 나머지는 판정 불가로 보낸다. `.doc span` 같은 흔한 규칙은 원소
# 이름이 달라 닿지 않는다.
_SAFE_UNIVERSAL_PROP = re.compile(
    r'(?i)^(?:box-sizing|font-family|-webkit-font-smoothing'
    r'|-moz-osx-font-smoothing|text-rendering|-webkit-tap-highlight-color'
    r'|-webkit-text-size-adjust|text-size-adjust)$')
_NON_REACHING_PSEUDO = re.compile(
    r'(?i)^(?::root|::?(?:-webkit-scrollbar[a-z-]*|selection|-moz-selection|placeholder))$')
_FUNC_PSEUDO = re.compile(r'(?i):(is|where|not|has|matches|-webkit-any|-moz-any)\(')


def _paren_end(text, i):
    """`text[i]` 가 `(` 일 때 짝 `)` 다음 위치. 짝이 없으면 None."""
    depth = 0
    for j in range(i, len(text)):
        if text[j] == '(':
            depth += 1
        elif text[j] == ')':
            depth -= 1
            if depth == 0:
                return j + 1
    return None


def _split_top(text):
    """괄호 밖의 쉼표로만 가른다 — `:is(.doc, .container) .pos` 는 선택자 하나다."""
    out, depth, at = [], 0, 0
    for i, ch in enumerate(text):
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        elif ch == ',' and depth == 0:
            out.append(text[at:i])
            at = i + 1
    out.append(text[at:])
    return out


def _reaches_title_element(selector):
    """True 닿을 수 있다 · False 닿지 않는다 · None 읽을 수 없다."""
    sel = selector.strip()
    if not sel:
        return False
    if re.search(r'(?i)\btl-s\b', sel):
        return True
    inner, flat, at = [], [], 0
    while True:
        m = _FUNC_PSEUDO.search(sel, at)
        if not m:
            flat.append(sel[at:])
            break
        end = _paren_end(sel, m.end() - 1)
        if end is None:
            return None
        kind = m.group(1).lower()
        flat.append(sel[at:m.start()] + (':x' if kind in ('not', 'has') else '.x'))
        inner.append(sel[m.end():end - 1])
        at = end
    flat = ''.join(flat)
    # 그 밖의 괄호(`:nth-child(2n + 1)`, `:lang(ko)`)는 인자를 비운다 — 공백이 결합자로 읽히지 않게.
    while '(' in flat:
        i = flat.index('(')
        end = _paren_end(flat, i)
        if end is None:
            return None
        flat = flat[:i] + flat[end:]
    for compound in re.split(r'\s*[\s>+~]\s*', flat.strip()):
        # 속성만 있는 복합 선택자(`[data-axis]`)는 닿지 않는다 — `<tl-s>` 에는 속성이 없다.
        # `:root` 는 html 만, 스크롤바·선택 영역 의사 원소는 글자를 감추지 못한다.
        if compound and compound[0] in '*:' and not _NON_REACHING_PSEUDO.match(compound):
            return True
    for arg in inner:
        for part in _split_top(arg):
            part = re.sub(r'^\s*[>+~]', '', part)
            got = _reaches_title_element(part)
            if got is None or got:
                return got
    return False


# 페이지에 실려 오는 외부 자원 중 내용을 아는 것. 그 밖의 스타일시트·스크립트는 `<tl-s>` 에
# 무엇을 할지 알 수 없으므로 판정 불가다(codex 11/05 3차 #4·#5). 2026-11-05 발행본 197편 실측.
_KNOWN_STYLESHEETS = frozenset({
    'https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/'
    'pretendardvariable-dynamic-subset.min.css'})
_KNOWN_SCRIPT_HOSTS = frozenset({'pagead2.googlesyndication.com', 'gc.zgo.at'})
_RAW_TEXT_ELEMENTS = ('textarea', 'title')
_ATTR = re.compile(r"""(?is)\b([a-z-]+)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""")
# `inherit` 는 상속 속성에서만 «부모와 같게»다 — `opacity:inherit` 는 곱해진다.
_INHERITED_PROP = re.compile(
    r'(?i)^(?:color|font(?:-[a-z]+)?|line-height|letter-spacing|word-spacing|word-break'
    r'|overflow-wrap|text-align|visibility|white-space)$')
_SCRIPT_EL = re.compile(r"""(?is)<script\b((?:"[^"]*"|'[^']*'|[^>"'])*)>(.*?)</script\s*>""")
_FIRST_PSEUDO = re.compile(r'(?i)([^\s>+~,]*):?:first-(?:letter|line)\b')
# 제목을 품을 수 없는 원소의 첫 글자·첫 줄은 제목과 무관하다(4차 #4 과잉 보류).
_LEAF_TYPE = re.compile(r'(?i)^(?:p|li|td|th|dt|dd|h[2-6]|a|span|strong|em|b|i|label|button|caption|figcaption)\b')
# 제목 자신이 flex·grid 가 되면 문장 원소가 따로 배치된다 — 순서·간격이 바뀐다(4차 #1).
_TITLE_LAYOUT = re.compile(
    r'(?i)(?:^|[;{\s])(?:display\s*:\s*(?:inline-)?(?:flex|grid)\b|display\s*:\s*contents\b'
    r'|(?:flex-direction|flex-wrap|flex-flow|grid-template[a-z-]*|grid-auto-flow|order|direction'
    r'|unicode-bidi|writing-mode)\s*:)')


def _may_select_title(selector, h1_attrs):
    """선택자의 주어(마지막 복합 선택자)가 그 h1 일 수 있는가 — 배치 검사용(5차 #1).

    타입 `h1`, 전칭 주어, 또는 그 h1 이 실제로 가진 class·id·속성을 가리키는 주어만 «그렇다».
    그 밖의 클래스(`.grid-2`, `nav.reading-map`)는 그 h1 에 닿지 않는다.
    """
    classes = set(h1_attrs.get('class', '').split())
    for part in _split_top(selector):
        flat = re.sub(r'\([^()]*\)', '', part).strip()
        subject = re.split(r'\s*[\s>+~]\s*', flat)[-1] if flat else ''
        if not subject:
            continue
        typed = re.match(r'(?i)^([a-z][a-z0-9-]*)', subject)
        if typed and typed.group(1).lower() != 'h1':
            continue
        if typed or subject[0] in '*:':
            return True
        if any(c in classes for c in re.findall(r'\.([\w-]+)', subject)):
            return True
        if '#' in subject and h1_attrs.get('id') in re.findall(r'#([\w-]+)', subject):
            return True
        if any(a.lower() in h1_attrs for a in re.findall(r'\[\s*([\w-]+)', subject)):
            return True
    return False


def _attrs(tag):
    """속성 사전. 이름이 겹치면 **첫 값**을 쓴다 — 브라우저가 그렇게 읽는다(4차 #6)."""
    out = {}
    for m in _ATTR.finditer(tag):
        out.setdefault(m.group(1).lower(), next(g for g in m.groups()[1:] if g is not None))
    return out


_KNOWN_SCRIPTS = None


def _known_inline_scripts():
    """셸이 넣는 실행 스크립트 본문 — 이 밖의 인라인 스크립트는 DOM 을 읽어 제목을 바꿀 수 있다(4차 #2).

    `post_shell` 을 불러오지 않고 소스에서 `_FOOT_JS` 리터럴만 읽는다 — 그 모듈은 `scripts.` 접두
    경로로 이웃을 불러와, 검토 게이트(`scripts/` 만 경로에 둔다)에서 불러오면 ImportError 가 나고
    그 예외가 판정 불가로 삼켜졌다(2026-11-05 실측 21편).
    """
    global _KNOWN_SCRIPTS
    if _KNOWN_SCRIPTS is None:
        import ast
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            'common', 'post_shell.py')
        with open(path, encoding='utf-8') as fh:
            tree = ast.parse(fh.read())
        foot = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                    and any(getattr(t, 'id', None) == '_FOOT_JS' for t in n.targets))
        _KNOWN_SCRIPTS = frozenset(m.group(2).strip() for m in _SCRIPT_EL.finditer(foot))
    return _KNOWN_SCRIPTS


def _mask_raw_text(html):
    """textarea·title 안을 덮는다. **태그 토큰을 따라** 여닫음을 찾는다 — 속성값 속 `<textarea>`
    흉내로 그 사이의 진짜 style 을 덮을 수 없게(4차 #5). 스크립트·주석은 먼저 덮는다."""
    from common.numbers import TAG_RE
    masked = blank_inert(html)
    out, at = [], 0
    for tok in TAG_RE.finditer(masked):
        if tok.start() < at:
            continue  # 이미 덮은 구간 안의 토큰 — 미리 소비하지 않는다(5차 #4)
        name = re.match(r'(?i)<\s*([a-z0-9-]+)', tok.group(0))
        if not name or name.group(1).lower() not in _RAW_TEXT_ELEMENTS:
            continue
        close = re.compile(r'(?i)</%s\s*>' % name.group(1)).search(masked, tok.end())
        end = close.end() if close else len(masked)
        out.append(masked[at:tok.start()] + ' ' * (end - tok.start()))
        at = end
    out.append(masked[at:])
    return ''.join(out)


def _safe_declaration(decl):
    if ':' not in decl:
        return not decl.strip()
    prop, value = (x.strip() for x in decl.split(':', 1))
    value = re.sub(r'(?i)\s*!important$', '', value).strip()
    if re.match(r'(?i)^(?:margin|padding)(?:-[a-z]+)?$', prop):
        return bool(re.match(r'^(?:0(?:px|em|rem|%)?\s*)+$', value))  # 음수 margin 은 글자를 밀어낸다
    if value.lower() in ('inherit', 'unset') and _INHERITED_PROP.match(prop):
        return True
    if re.match(r'(?i)^(?:border|outline)(?:-[a-z]+)?$', prop):
        return value.lower() in ('0', 'none', '0 none', 'none 0')
    return bool(_SAFE_UNIVERSAL_PROP.match(prop))


def _title_css_risky(html, block):
    """`<tl-s>` 를 씌우는 것만으로 무엇이 보이고 안 보일지가 바뀔 수 있는가.

    **태그 토큰을 따라** 실제 `<style>`·`<link>`·`<script>` 만 본다 — 속성값 안의 `<style>` 흉내나
    textarea 안의 글자는 CSS 가 아니다(3차 #1). head 만이 아니라 body 의 style 도 본다(재검토 #4).
    등록된 조판 블록 안은 보지 않는다. 아래는 전부 판정 불가로 보낸다:
    - `<tl-s>` 에 닿는 선택자의 선언이 허용 목록 밖(margin·padding 은 0 만 — 3차 #2)
    - `::first-letter`·`::first-line` — inline-block 안 글자는 조상의 첫 글자가 아니게 된다(3차 #3)
    - 내용을 모르는 스타일시트 링크·`@import`(3차 #4)
    - `customElements`·`tl-s` 를 말하는 스크립트, 모르는 호스트의 외부 스크립트(3차 #5)
    """
    from common.numbers import TAG_RE
    masked = _mask_raw_text(html)
    title = next((t for t in TAG_RE.finditer(masked) if re.match(r'(?i)<h1[\s>/]', t.group(0))), None)
    h1_attrs = _attrs(title.group(0)) if title else {}
    for tok in TAG_RE.finditer(masked):
        tag = tok.group(0)
        name = re.match(r'(?i)<\s*([a-z0-9-]+)', tag)
        name = name.group(1).lower() if name else ''
        if name == 'noscript':
            return True  # 스크립트를 끈 독자에게만 켜지는 CSS 가 있을 수 있다(4차 #3)
        if name and re.search(r'(?i)\son[a-z]+\s*=', tag):
            return True  # 인라인 이벤트 처리기(4차 #2)
        if name == 'h1':
            if _TITLE_LAYOUT.search(';' + _attrs(tag).get('style', '')):
                return True  # 인라인 배치 — 값까지 본다(5차 #3, `display:block` 은 통과)
        if name == 'link':
            attrs = _attrs(tag)
            if 'stylesheet' in attrs.get('rel', '').lower() and attrs.get('href') not in _KNOWN_STYLESHEETS:
                return True
        elif name == 'style':
            close = re.compile(r'(?i)</style\s*>').search(masked, tok.end())
            if close is None:
                return True
            start = tok.end()
            css = _mask_css(html[start:close.start()])
            if _CSS_EXOTIC.search(css) or re.search(r'(?i)@import', css):
                return True
            for rule in _RULE.finditer(css):
                # 선언부의 자리로 가린다 — 블록 첫 규칙의 선택자 앞 공백은 마커보다 앞에서 시작한다.
                if block is not None and block.start <= start + rule.start(2) < block.end:
                    continue
                for first in _FIRST_PSEUDO.finditer(rule.group(1)):
                    if not _LEAF_TYPE.match(first.group(1)):
                        return True
                if (_TITLE_LAYOUT.search('{' + rule.group(2))
                        and _may_select_title(rule.group(1), h1_attrs)):
                    return True
                reach = None
                for part in _split_top(rule.group(1)):
                    got = _reaches_title_element(part)
                    if got is None:
                        return True
                    reach = reach or got
                if reach and not all(_safe_declaration(d) for d in rule.group(2).split(';')):
                    return True
    # 스크립트는 `blank_inert` 가 원소째 덮으므로 원문에서 따로 찾는다. 주석·속성값 속 흉내까지
    # 잡히지만 그 오탐은 판정 불가 쪽이라 안전하다.
    for m in _SCRIPT_EL.finditer(html):
        src = _attrs(m.group(1)).get('src')
        if src is not None:
            host = re.match(r'(?i)^https://([^/]+)/', src)
            if not host or host.group(1).lower() not in _KNOWN_SCRIPT_HOSTS:
                return True
        if re.search(r'(?i)customElements|tl-s', m.group(2)):
            return True
        kind = _attrs(m.group(1)).get('type', '').lower()
        if src is None and kind != 'application/ld+json' and m.group(2).strip() not in _known_inline_scripts():
            return True
    return False


_RULE = re.compile(r'([^{}]*)\{([^{}]*)\}')

# 주석과 문자열은 **규칙을 자르기 전에** 덮어야 한다. 나중에 지우면
# `.p-label{/*{*/display:none/*}*/}` 처럼 주석 안에 중괄호를 넣어 선택자와 선언을 갈라
# 놓을 수 있고, 그러면 가장 기본적인 `display:none` 이 검사를 통과한다(2026-09-04 codex
# 검토가 재현). 길이를 보존해 덮으므로 여기서 얻은 오프셋은 원본에 그대로 쓸 수 있다.
_CSS_INERT = re.compile(r'/\*.*?\*/' r'|"(?:[^"\\]|\\.)*"' r"|'(?:[^'\\]|\\.)*'", re.S)
# CSS 이스케이프와 네이티브 중첩(`&`)은 우리 CSS 에 없다. 나타나면 이 검사가 읽을 수 있는
# 문법이 아니므로 판정을 포기한다. **16진 이스케이프만 막으면 모자란다** — `.p\2d label` 은
# 잡히는데 `.p\-label` 은 빠져나갔다(2026-09-04 실측). 둘 다 `.p-label` 을 가리킨다.
# 문자열 안의 백슬래시는 `_mask_css` 가 이미 덮었으므로 여기 걸리지 않는다.
_CSS_EXOTIC = re.compile(r'\\|&')


def _mask_css(css):
    """주석·문자열 안을 공백으로 덮는다. 길이는 그대로."""
    return _CSS_INERT.sub(lambda m: ' ' * (m.end() - m.start()), css)


@dataclass(frozen=True)
class Block:
    start: int
    end: int
    text: str


def find_block(html):
    """조판 블록의 자리. 확신이 없으면 None — 그 판은 검토로 보낸다.

    **`<style>` 를 문자열로 되짚지 않는다.** 그렇게 하면 `<stylex>` 도, 주석 안의 `<style` 도,
    스크립트 문자열 속 `<style` 도 여는 태그로 읽힌다. 그러면 이식이 엉뚱한 구간을 들어내고
    그 결과가 조판 변경으로 승인된다(2026-09-04 codex 검토가 지적). head 안 **진짜** style
    원소의 범위만 쓰는 `_head_style_spans` 는 조판 도구 자신이 마커를 찾을 때 쓰는 것과 같은
    함수다 — 게이트가 보는 자리와 도구가 고치는 자리가 같아야 한다.

    마커가 둘이면 어느 쪽이 블록인지 정할 수 없다. 블록 안에 `<` 가 있으면 CSS 가 아니다.
    """
    if len(_MARKER.findall(html)) != 1:
        return None
    at = _MARKER.search(html)
    inside = [(a, b) for a, b in head_style_spans(html) if a <= at.start() < b]
    if len(inside) != 1:
        return None
    end = inside[0][1]
    text = html[at.start():end]
    return None if '<' in text else Block(at.start(), end, text)


def _risky_css(html, block):
    """조판 변환이 «보이느냐»를 건드릴 수 있는 CSS 가 있는가.

    두 가지다. ① `demote_card_p_font` 는 `font-size` 가 든 규칙에서 `.card p` 류 선택자를
    떼어 내는데, 같은 규칙에 `display` 가 함께 있으면 그 선언의 특정도까지 내려간다 — 더 약한
    `display:none` 규칙이 이기면 문단이 사라진다. ② `block_labels` 가 붙이는 `p-label` 에
    페이지 자신의 CSS 가 반응하면(`.p-label{display:none}`), 클래스를 붙이는 것만으로 라벨이
    사라진다. 둘 다 2026-09-04 codex 검토가 지목했다.

    등록된 조판 블록 안은 보지 않는다 — 그 내용은 사람이 확인해 등록한 것이다.
    """
    for start, end in head_style_spans(html):
        css = _mask_css(html[start:end])
        if _CSS_EXOTIC.search(css):
            return True
        for rule in _RULE.finditer(css):
            if block is not None and block.start <= start + rule.start() < block.end:
                continue
            selector, declarations = rule.group(1), rule.group(2)
            # 라벨 규칙은 «감추는» 것만 위험하다. 클래스를 붙이는 순간 글이 사라진다.
            if _LABEL_SEL.search(selector) and _HIDING.search(declarations):
                return True
            # 강등 대상 규칙은 특정도가 내려가므로 값과 무관하게 위험하다.
            if (_FONT_SIZE.search(declarations) and _VISIBILITY.search(declarations)
                    and re.search(r'(?:^|[\s,])p(?:[\s,]|$)', selector)):
                return True
    return False


def _inert(html):
    """스크립트·주석 등 «코드가 아닌 것으로 취급되는» 자리의 글자만 이어 붙인다.

    `block_labels`·`unpin_inline_labels` 는 문서 전체에 정규식을 돌리므로 스크립트 문자열
    안의 HTML 흉내까지 고친다. JSON-LD 의 headline 이나 스크립트가 비교하는 문자열이 그렇게
    바뀌면 화면에 나오는 것이 달라진다 — 조판이라 부를 수 없다.
    """
    blanked = blank_inert(html)
    out, at, size = [], 0, len(html)
    while at < size:
        if html[at] == blanked[at]:
            at += 1
            continue
        # 증거(덮인 글자)에서 시작해, 공백을 건너뛰며 마지막 증거까지를 한 구간으로 본다.
        # 증거만 모으면 **원래 공백이 서명에서 사라진다** — 덮인 공백과 구별되지 않기
        # 때문이다. 그러면 스크립트 문자열에 공백 하나를 넣는 변경이 통과한다.
        start = last = at
        while at < size and (html[at] != blanked[at] or html[at].isspace()):
            if html[at] != blanked[at]:
                last = at
            at += 1
        out.append(html[start:last + 1])
    return '\0'.join(out)


def transformed(old_html, new_html):
    """`old_html` 에 «새 판의 조판 블록 + 색칠»을 입힌 결과. 판정 불가면 None.

    `equivalent()` 와 조합 경로가 같은 변환을 쓰게 하려고 갈라 두었다 — 두 변환이 한
    판에 겹쳤을 때(조판·색 + 자산 외부화) 이 결과를 다음 변환의 입력으로 넘긴다.
    """
    if old_html is None or new_html is None:
        return None
    fresh, stale = find_block(new_html), find_block(old_html)
    if fresh is None or stale is None:
        return None
    if not is_known(fresh.text):
        return None  # 등록되지 않은 블록은 조판이라고 부르지 않는다
    grafted = old_html[:stale.start] + fresh.text + old_html[stale.end:]
    try:
        if _risky_css(old_html, stale) or _risky_css(new_html, fresh):
            return None
        # 순서는 `enhance_html()` 과 같다. `inject_css` 자리를 위의 이식이 대신한다.
        # 색칠(`apply_colors.py`)은 그다음 단계라 여기서도 뒤에 온다. 값에서 결정론적으로
        # 다시 계산하므로, 손으로 바꿔 넣은 색은 이 변환을 통과하지 못한다.
        staged = unpin_inline_labels(block_labels(demote_card_p_font(grafted)))
        titled = split_title_sentences(staged)
        if titled != staged and _title_css_risky(old_html, stale):
            return None  # 제목 원소에 닿는 CSS — 감춤·드러남을 확정할 수 없다
        out = paint(titled)
        if _inert(out) != _inert(grafted):
            return None  # 변환이 스크립트·주석을 건드렸다
    except Exception:  # noqa: BLE001 — 못 다루는 페이지는 미검토로 남기는 것이 안전하다
        return None
    return out


def equivalent(old_html, new_html):
    """`old_html` 을 조판 변환으로 밀면 `new_html` 이 바이트 그대로 나오는가.

    True 조판 · False 사람이 읽어야 함 · **None 판정 불가**. None 은 「같다」가 아니다 —
    부르는 쪽은 미검토로 세야 한다.
    """
    out = transformed(old_html, new_html)
    return None if out is None else out == new_html


# 임베드를 파일 참조로 바꾼 판. `equivalent()` 는 CSS 블록만 이식하므로 여기에 닿지
# 못한다. 방향은 이 모듈의 원칙 그대로 — **새 판을 되감아 옛 판이 바이트 그대로 나오는지**
# 만 본다. 수치·태그 비교로는 다른 이미지를 걸어도, 문장을 함께 고쳐도 통과한다.
_SRC_EXTERNAL = re.compile(r'src="([^"]*)"')
_SRC_INLINE = re.compile(r'src="data:(image/[a-z0-9.+-]+);base64,([A-Za-z0-9+/=]+)"', re.I)
_INLINE_URI = re.compile(r'data:(image/[a-z0-9.+-]+);base64,([A-Za-z0-9+/=]+)\Z', re.I)
_MASK = '\x00src\x00'
# 주석은 태그가 아니다 — 먼저 소진시켜 그 안의 `src` 가 속성으로 읽히지 않게 한다.
_TAG_SPAN = re.compile(r'<!--.*?-->|<[^>]*>', re.S)


def asset_externalized(old_html, new_html, read_asset):
    """True 자산 외부화만 한 판 / False 그 밖의 변경이 섞임 / None 판정 불가.

    `read_asset(경로)` 는 새 판이 가리키는 파일의 바이트, 없으면 None 을 돌려준다.

    되감기를 `src` 전부에 걸던 판은 광고 로더 `<script src="https://…">` 까지 파일로
    찾다가 모든 발행본을 「판정 불가」로 만들었다(2026-09-06, 실측 38편 전부). 그래서
    **양쪽의 `src` 를 자리표시자로 가려 나머지 바이트가 같은지 먼저 보고**, 그다음 자리
    별로 짝을 맞춘다 — 안 바뀐 `src` 는 그대로여야 하고, 바뀐 자리는 옛 판이 임베드,
    새 판이 파일이어야 하며 그 파일이 임베드 바이트와 정확히 같아야 한다.
    """
    if old_html is None or new_html is None:
        return None
    if not _SRC_INLINE.search(old_html):
        return None  # 되감을 것이 없다 — 이 변환의 사례가 아니다
    if _SRC_INLINE.search(new_html):
        return None  # 아직 임베드가 남았다면 이 변환이 끝난 판이 아니다

    def mask(html):
        """태그 **안**의 `src` 만 가린다.

        문서 전체에 정규식을 걸던 판은 산문에 `src="data:…"` 라고 쓰여 있기만 해도
        그 글자를 자산으로 읽었다 — 본문을 고치고 「조판」으로 통과시킬 수 있었다
        (2026-09-06 codex 검토 1). 주석 안도 태그가 아니다.
        """
        srcs = []
        out = []
        at = 0
        for tag in _TAG_SPAN.finditer(html):
            out.append(html[at:tag.start()])
            span = tag.group(0)
            out.append(span if span.startswith('<!--') else _SRC_EXTERNAL.sub(
                lambda m: srcs.append(m.group(1)) or _MASK, span))
            at = tag.end()
        out.append(html[at:])
        return ''.join(out), srcs

    masked_old, old_srcs = mask(old_html)
    masked_new, new_srcs = mask(new_html)
    if masked_old != masked_new or len(old_srcs) != len(new_srcs):
        return False  # src 밖의 바이트가 다르다

    for was, now in zip(old_srcs, new_srcs):
        if was == now:
            continue  # 손대지 않은 자리
        m = _INLINE_URI.match(was)
        if not m:
            return False  # 임베드가 아니었는데 바뀌었다
        raw = read_asset(now)
        if raw is None:
            return None
        if base64.b64encode(raw).decode() != m.group(2):
            return False
    return True


def typography(path, old, new, root=None):
    """(경로, 옛 내용, 새 내용) → True 조판 / False 수정 / None 판정 불가.

    `root` 를 주면 자산 외부화(임베드 → 파일 참조)도 같은 자리로 받는다. 그 변환은
    독자가 받는 그림이 바이트 그대로라 조판과 성격이 같은데, `equivalent()` 는 CSS
    블록만 이식하므로 닿지 못한다(2026-09-06).

    방문 통계 로더 삽입(`common.analytics.inject`)도 받는다 — 독자가 읽는 글자는
    그대로다. 방향은 같다: 옛 판에 **삽입을 재연**해 그 결과를 옛 판 삼아 다시 본다.
    로더를 한 글자라도 다르게 넣었거나 다른 자리에 넣은 판은 재연과 맞지 않는다(2026-09-25).

    AdSense 로더 제거(`common.adsense.strip`, 2026-11-05)도 같은 방식으로 받는다. 방향은
    제거뿐이다 — 새 판에 로더가 남아 있으면 재연하지 않는다. 방문 통계 삽입을 **먼저**
    재연한다: `<head>` 없는 초기 글은 방문 통계가 AdSense 로더 뒤에 붙었기 때문이다.
    """
    if old is None or new is None:
        return None
    if not path.endswith('.html'):
        return False  # HTML 이 아닌 원고에는 조판이라는 것이 없다
    verdict = _with_counter(path, old, new, root)
    if verdict is True or adsense.present(new) or not adsense.present(old):
        return verdict
    primed = analytics.inject(old) if analytics.MARKER in new else old
    primed = adsense.strip(primed)
    if primed == new:
        return True
    again = _with_counter(path, primed, new, root)
    return True if again is True else verdict


def _with_counter(path, old, new, root):
    verdict = _typography(path, old, new, root)
    if verdict is True or analytics.MARKER not in new:
        return verdict
    primed = analytics.inject(old)
    if primed == old:
        return verdict  # 옛 판에 이미 있었다 — 재연할 삽입이 없다
    if primed == new:
        return True
    again = _typography(path, primed, new, root)
    return True if again is True else verdict


def _typography(path, old, new, root):
    verdict = equivalent(old, new)
    if verdict:
        return True
    reader = _asset_reader(root, path)
    asset = asset_externalized(old, new, reader)
    if asset is not True:
        # **두 변환이 한 판에 겹친 경우.** 각각으로는 설명되지 않는다 — 색이 섞이면
        # `asset_externalized` 는 src 밖 바이트가 다르다며 False 를 준다 — 조판·색을 먼저
        # 입히고 나서 자산 외부화만 남는지 본다. 2026-09-12 색 소급이 임베드가 남아 있던
        # 옛 판 28편을 한꺼번에 「수정됨」으로 만든 자리다. 방향은 그대로 — 되감아
        # 바이트가 같은지만 본다.
        staged = transformed(old, new)
        if staged is not None:
            composed = asset_externalized(staged, new, reader)
            if composed is not None:
                asset = composed
    if asset is not None:
        return asset
    return verdict


def _asset_reader(root, path):
    """발행본 위치를 기준으로 상대경로를 푸는 읽기 함수. root 가 없으면 늘 None."""
    def read(rel):
        if root is None or rel.startswith(('http:', 'https:', 'data:', '//')):
            return None
        target = os.path.normpath(os.path.join(root, os.path.dirname(path), rel))
        if not os.path.isfile(target):
            return None
        with open(target, 'rb') as fh:
            return fh.read()
    return read
