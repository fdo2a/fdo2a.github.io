"""발행본을 «보이는 것» 기준으로 읽기 위한 최소 DOM.

정규식으로 표식을 세면 세 가지에 뚫린다(codex C4·C7):

- 빈 `<div hidden data-lesson="A02">` 에 정답 표식을 넣고 본문은 딴 얘기를 쓰는 것
- 표식을 두 개 넣어 하나만 맞히는 것
- 시황을 `<h3>`·`<blockquote>`·`alt` 로 옮겨 자수 계산에서 빼는 것

그래서 표준 `html.parser` 로 트리를 세우고 **숨김 상태를 상속**시킨다. `hidden`,
`aria-hidden="true"`, `display:none`, `visibility:hidden` 이 걸린 가지는 통째로 안 보이는
것으로 친다. `script`·`style`·주석·`alt` 는 애초에 본문이 아니다.

**공유 `us/weight.py` 의 `prose_chars` 를 고치지 않고 여기에 따로 둔 것은 의도다.** 그쪽
임계값(recap_min 5500 등)은 현행 계산식에 맞춰 실측 튜닝돼 있어 계산을 바꾸면 US·KR
게이트가 통째로 흔들린다. 관심사 분리.
"""

from html.parser import HTMLParser

# 본문이 아닌 것들. `template` 은 렌더되지 않고, `alt` 는 속성이라 애초에 안 담는다.
_NON_CONTENT = {'script', 'style', 'template', 'head', 'noscript'}

_VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link',
         'meta', 'param', 'source', 'track', 'wbr'}

# 브라우저가 암묵적으로 닫는 블록들. `<p hidden>숨김<p>99%</p>` 에서 둘째 문단은
# 형제이지 자식이 아니다 — 상속시키면 보이는 수치가 검사에서 사라진다.
_IMPLICIT_CLOSE = {
    'p': {'p', 'div', 'section', 'article', 'aside', 'ul', 'ol', 'dl', 'table',
          'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'blockquote', 'pre', 'figure',
          'figcaption', 'address', 'hr', 'main', 'footer', 'header'},
    'li': {'li'},
    'dd': {'dd', 'dt'},
    'dt': {'dd', 'dt'},
    'td': {'td', 'th', 'tr'},
    'th': {'td', 'th', 'tr'},
    'tr': {'tr'},
    'option': {'option'},
}

# 구절 요소는 문단을 담을 수 없다. `<p hidden><span>x<p>99%` 에서 두 번째 p 는
# span 의 자식이 아니라 형제다 — 스택 꼭대기만 보면 span 에 막혀 숨김이 상속된다.
_PHRASING = {'span', 'b', 'i', 'em', 'strong', 'a', 'code', 'small', 'sup', 'sub',
             'mark', 'u', 's', 'abbr', 'cite', 'q', 'time', 'var', 'kbd', 'font'}

# 텍스트를 이을 때 앞뒤로 공백을 넣을 것들. 블록은 띄우고 **구절 요소는 붙인다** —
# `14.<b>4</b>%` 는 한 수치이고 떼면 원문에 없는 14 가 생긴다. 반대로 인접 표 칸을
# 붙이면 0.5 와 0.9 가 「0.50.9」가 된다.
_BLOCKISH = {'p', 'div', 'section', 'article', 'aside', 'li', 'ul', 'ol', 'dl', 'dd',
             'dt', 'table', 'thead', 'tbody', 'tr', 'td', 'th', 'h1', 'h2', 'h3',
             'h4', 'h5', 'h6', 'blockquote', 'pre', 'figure', 'figcaption', 'br',
             'hr', 'main', 'header', 'footer', 'caption'}

_HIDING_STYLE = ('display:none', 'display: none',
                 'visibility:hidden', 'visibility: hidden')


class Element:
    __slots__ = ('tag', 'attrs', 'children', 'parent', 'hidden', 'depth')

    def __init__(self, tag, attrs, parent, hidden, depth):
        self.tag = tag
        self.attrs = attrs
        self.children = []
        self.parent = parent
        self.hidden = hidden
        self.depth = depth

    def text(self):
        """이 요소 아래의 보이는 텍스트. 블록은 띄우고 구절 요소는 붙인다."""
        if self.hidden or self.tag in _NON_CONTENT:
            return ''
        out = []
        for child in self.children:
            if isinstance(child, str):
                out.append(child)
            else:
                body = child.text()
                out.append(f' {body} ' if child.tag in _BLOCKISH else body)
        return ''.join(out)

    def __repr__(self):
        return f'<{self.tag} {self.attrs}>'


# `aria-hidden` 은 **넣지 않는다.** 그것은 보조기술에서만 감추고 화면에는 그대로 보인다.
# 숨김으로 치면 시황을 aria-hidden 으로 감싸 상한 계산에서 빼는 우회가 열린다
# (codex 2차 검토).
def _is_hiding(attrs):
    if 'hidden' in attrs:
        return True
    style = (attrs.get('style') or '').replace(' ', '').lower()
    return any(h.replace(' ', '') in style for h in _HIDING_STYLE)


class _Builder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Element('#root', {}, None, False, -1)
        self.stack = [self.root]

    @property
    def cur(self):
        return self.stack[-1]

    def _implicit_close(self, tag):
        """새 태그가 열릴 때 브라우저가 암묵적으로 닫는 것들을 닫는다.

        구절 요소는 **관통해서** 본다 — `<p><span>x<p>` 의 두 번째 p 는 span 의
        자식이 아니라 형제이고, 꼭대기만 보면 그 사실을 놓친다.
        """
        if tag in _PHRASING:
            return
        while len(self.stack) > 1:
            depth = len(self.stack) - 1
            while depth > 0 and self.stack[depth].tag in _PHRASING:
                depth -= 1
            if depth > 0 and tag in _IMPLICIT_CLOSE.get(self.stack[depth].tag, ()):
                del self.stack[depth:]
                continue
            return

    def handle_starttag(self, tag, attrs):
        self._implicit_close(tag)
        a = {k: (v if v is not None else '') for k, v in attrs}
        el = Element(tag, a, self.cur,
                     self.cur.hidden or _is_hiding(a) or tag in _NON_CONTENT,
                     self.cur.depth + 1)
        self.cur.children.append(el)
        if tag not in _VOID:
            self.stack.append(el)

    def handle_startendtag(self, tag, attrs):
        a = {k: (v if v is not None else '') for k, v in attrs}
        self.cur.children.append(
            Element(tag, a, self.cur, self.cur.hidden or _is_hiding(a),
                    self.cur.depth + 1))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return
        # 짝 없는 닫는 태그는 무시한다 — 조판 게이트가 따로 잡는다.

    def handle_data(self, data):
        self.cur.children.append(data)


def parse(html):
    b = _Builder()
    b.feed(html)
    b.close()
    return b.root


def walk(el):
    for child in el.children:
        if isinstance(child, Element):
            yield child
            yield from walk(child)


def visible_text(html):
    return parse(html).text()


def find_marked(html_or_root, attr):
    """그 속성을 가진 **보이는** 요소들. 개수를 세는 것이 목적이라 중복도 그대로 준다."""
    root = html_or_root if isinstance(html_or_root, Element) else parse(html_or_root)
    return [el for el in walk(root) if attr in el.attrs and not el.hidden]
