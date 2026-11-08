"""Where a release-anatomy block starts and ends — by matched tags, not by the next marker.

Until 2026-11-08 `macro_gate._blocks` sliced each `data-release` block to the next marker
of any kind. The last block in an axis card therefore ran on into the next axis's table:
the 10/27 new-home-sales block, cut down to the single sentence 「676K」, still counted
71 figures. Here a block is exactly the `<div data-release=KEY>` element and what it
encloses, found with a real parser.

Rules (violations, not guesses): the marker is on a `div`; the div sits inside a
`div.card` of §9; it closes; it contains no other `data-release` or `data-macro-group`;
a key appears once. Text is entity-decoded and whitespace-collapsed.

The same spans serve the abbreviated-day length check (§9 measured without the
anatomy blocks), so the two can never disagree about what a block is.
"""
import re
from html.parser import HTMLParser

VOID = frozenset({'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link',
                  'meta', 'source', 'track', 'wbr'})
_SPACE = re.compile(r'\s+')


class _Parser(HTMLParser):
    def __init__(self, text, require_card=True):
        super().__init__(convert_charrefs=True)
        self.require_card = require_card
        self.lines = [0]
        for m in re.finditer('\n', text):
            self.lines.append(m.end())
        self.stack = []           # [tag, attrs, block_key | None]
        self.blocks = {}          # key -> {'start', 'end', 'parts'}
        self.order = []
        self.problems = []
        self.implicit_div = False     # a <div> closed by someone else's end tag

    def _offset(self):
        line, col = self.getpos()
        return self.lines[line - 1] + col

    def _open_block(self):
        for tag, _, key in reversed(self.stack):
            if key is not None:
                return key
        return None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        key = a.get('data-release')
        inside = self._open_block()
        if inside is not None and (key is not None or 'data-macro-group' in a):
            what = f'data-release="{key}"' if key is not None else 'data-macro-group'
            self.problems.append(f'「{inside}」 블록 안에 다른 표식({what})이 있다')
        if key is not None:
            if tag != 'div':
                self.problems.append(f'data-release="{key}" 는 div 에만 단다 — <{tag}> 에 있다')
                key = None
            elif key in self.blocks:
                self.problems.append(f'data-release="{key}" 가 두 번 나온다')
                key = None
            elif self.require_card and not any(
                    t == 'div' and 'card' in (at.get('class') or '').split()
                    for t, at, _ in self.stack):
                self.problems.append(f'data-release="{key}" 가 §9 축 카드(div.card) 밖에 있다')
                key = None
            else:
                self.blocks[key] = {'start': self._offset(), 'end': None, 'parts': []}
                self.order.append(key)
        if tag in VOID:
            return
        self.stack.append((tag, a, key))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID and self.stack and self.stack[-1][0] == tag:
            self.stack.pop()

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                for _t, _a, key in self.stack[i + 1:]:
                    if _t == 'div':
                        self.implicit_div = True
                for _t, _a, key in self.stack[i:]:
                    if key is not None:
                        b = self.blocks[key]
                        if _t != tag:
                            self.problems.append(f'「{key}」 블록 안의 <{_t}> 가 닫히지 않았다')
                        b['end'] = self._offset() + len(f'</{tag}>')
                del self.stack[i:]
                return

    def handle_data(self, data):
        key = self._open_block()
        if key is not None:
            self.blocks[key]['parts'].append(data)


def parse(html, require_card=True):
    """-> (blocks {key: {'text', 'start', 'end'}}, problems [str]). Offsets index `html`.

    `require_card=False` for the pre-2026-08-20 layout, whose blocks sat in a separate
    경제지표 section with no axis cards."""
    p = _Parser(html or '', require_card)
    p.feed(html or '')
    p.close()
    problems = list(p.problems)
    if p.order and (p.implicit_div or any(t == 'div' for t, _, _ in p.stack)):
        # A block missing its </div> steals the closing tag of the card around it and runs
        # on to the card's end — the very hole this module closes. Only an imbalance shows it.
        problems.append('div 여닫기 짝이 맞지 않는다 — 해부 블록이 닫히지 않아 뒤 내용까지 '
                        '먹었을 수 있다')
    out = {}
    for key in p.order:
        b = p.blocks[key]
        if b['end'] is None:
            problems.append(f'data-release="{key}" 블록이 닫히지 않았다')
            continue
        out[key] = {'text': _SPACE.sub(' ', ''.join(b['parts'])).strip(),
                    'start': b['start'], 'end': b['end']}
    return out, problems


def without_blocks(html):
    """`html` with every well-formed anatomy block cut out (for the abbreviated-day count)."""
    blocks, _ = parse(html, require_card=False)
    out, last = [], 0
    for b in sorted(blocks.values(), key=lambda b: b['start']):
        if b['start'] < last:
            continue
        out.append(html[last:b['start']])
        last = b['end']
    out.append(html[last:])
    return ''.join(out)
