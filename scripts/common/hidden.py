"""Is this element hidden from the reader? — one answer for every publishing gate.

Each gate used to carry its own list, and a hole closed in one stayed open in the others
(measured 2026-11-19: `opacity:.0` was caught by one gate of five, `inert` by one, `font-size:0`
missed by two; telegram_gate's codex-review opacity fix never reached news_gate). This module is the
union of the hiding techniques every gate caught, plus the neighbours of each (CSS comments in a
declaration, `visibility:collapse`, alpha-0 colours, `transform:scale(0)`, far-off positioning).

Only attributes, classes and inline style live here. Tag-level rules (script/style/template,
non-display containers, a closed `<details>`) stay with each gate — they mean different things to
different gates (us/number_audit streams closed details as a separate kind of text).

**How a gate uses it — two roles, never mixed.** What a gate *reads* (the text, links, markers and
candidates its other checks consume) is still chosen by that gate's own old predicate, frozen as it was
on 2026-11-19. This module only *adds* a violation: an element in the gate's scope that `is_hidden`
calls hidden blocks the page. So a gate's verdict is (its old checks) OR (hidden in scope) and cannot
get weaker. Widening what a gate reads would have: a hidden span dropped from the text silently
removes the wrong link, the excess length or the bad figure another check was going to reject (codex
design review 2026-11-19 #1-#6). The old predicates also matched things that hide nothing
(`min-width:0`, `overflow:hidden`, `title="display:none"`); those stay where they were and are not
in the core, or every gate would refuse ordinary CSS.

**Inline CSS is judged fail-closed, not by a CSS engine** (`style_verdict`). Only what is positively
recognised counts as visible: short lists of keywords and units, plain numbers, no evaluated functions.
A declaration of a judged property (`RELEVANT`) that is invalid, or that would need evaluating
(`var()`, `calc()`, `env()`, `attr()` …), and a style that cannot be cut into declarations with
certainty (escapes, comments, blocks, broken strings) make the element count as hidden. Three rounds of
"resolve it like a browser" each left a case where a later unreadable value masked an earlier hiding
one; refusing the unreadable has no such case. The cost is a refused page with unusual CSS — none of
the 20,976 inline styles published by 2026-11-19 is refused. Do not widen the lists to accept more
without a browser-support reason: a value some browser drops lets an earlier hiding value through.

Design and measurements: plans/2026-11-19-hidden-text.md (outside the repo).
"""

import re
from html.parser import HTMLParser

from .numbers import TAG_RE

HIDDEN_CLASSES = frozenset({'hidden', 'hiden', 'sr-only', 'visually-hidden', 'screen-reader-text'})
# Below this an opacity, font size or box size leaves nothing a reader can read.
NEAR_ZERO = 0.1

UNSURE = '판정할 수 없는 CSS'
_WS = ' \t\n\r\f'                          # CSS whitespace — narrower than str.strip()'s
_GLOBAL = frozenset({'inherit', 'initial', 'unset', 'revert', 'revert-layer'})
_DISPLAY = frozenset({'none', 'block', 'inline', 'inline-block', 'flex', 'inline-flex', 'grid', 'inline-grid',
                      'table', 'inline-table', 'table-row', 'table-cell', 'table-column', 'table-caption',
                      'table-row-group', 'table-header-group', 'table-footer-group', 'table-column-group',
                      'list-item', 'contents', 'flow-root'})
_LENGTH = frozenset({'px', 'pt', 'pc', 'in', 'cm', 'mm', 'em', 'rem', 'ex', 'ch', 'vw', 'vh', 'vmin', 'vmax'})
_ANGLE = frozenset({'deg', 'rad', 'grad', 'turn'})
# CSS pixels per unit, to tell "moved off the page" and "too small to read" in any unit. Absolute units
# are exact. A relative one depends on what this module cannot see (font size, viewport, the box), so
# `_FAR_PX` takes it at the large end (an offset counts as far early) and `_SMALL_PX` at the small end
# (a font size counts as tiny early): both err towards "hidden".
_ABS_PX = {'': 0, 'px': 1, 'pt': 96 / 72, 'pc': 16, 'in': 96, 'cm': 96 / 2.54, 'mm': 96 / 25.4}
_FAR_PX = dict(_ABS_PX, **{u: 40 for u in ('em', 'rem', 'ex', 'ch', 'vw', 'vh', 'vmin', 'vmax', '%')})
_SMALL_PX = dict(_ABS_PX, **{'em': 16, 'rem': 16, 'ex': 8, 'ch': 8, '%': .16, 'vw': 3.2, 'vh': 3.2, 'vmin': 3.2, 'vmax': 3.2})
FAR = 100            # an offset of this many CSS pixels or more, either way, takes the element off the page
TINY_FONT = 4        # below this many CSS pixels text is not readable (smallest published: 5.33pt = 7.1px)
_BOX_WORDS = frozenset({'auto', 'min-content', 'max-content', 'fit-content'})
_MAX_WORDS = frozenset({'none', 'min-content', 'max-content', 'fit-content'})
_FONT_WORDS = frozenset({'xx-small', 'x-small', 'small', 'medium', 'large', 'x-large', 'xx-large',
                         'smaller', 'larger'})
_SIZES = {'font-size': _FONT_WORDS, 'width': _BOX_WORDS, 'height': _BOX_WORDS,
          'max-width': _MAX_WORDS, 'max-height': _MAX_WORDS}
_COLOURS = frozenset('''aliceblue antiquewhite aqua aquamarine azure beige bisque black blanchedalmond blue
blueviolet brown burlywood cadetblue chartreuse chocolate coral cornflowerblue cornsilk crimson cyan darkblue
darkcyan darkgoldenrod darkgray darkgreen darkgrey darkkhaki darkmagenta darkolivegreen darkorange darkorchid
darkred darksalmon darkseagreen darkslateblue darkslategray darkslategrey darkturquoise darkviolet deeppink
deepskyblue dimgray dimgrey dodgerblue firebrick floralwhite forestgreen fuchsia gainsboro ghostwhite gold
goldenrod gray green greenyellow grey honeydew hotpink indianred indigo ivory khaki lavender lavenderblush
lawngreen lemonchiffon lightblue lightcoral lightcyan lightgoldenrodyellow lightgray lightgreen lightgrey
lightpink lightsalmon lightseagreen lightskyblue lightslategray lightslategrey lightsteelblue lightyellow lime
limegreen linen magenta maroon mediumaquamarine mediumblue mediumorchid mediumpurple mediumseagreen
mediumslateblue mediumspringgreen mediumturquoise mediumvioletred midnightblue mintcream mistyrose moccasin
navajowhite navy oldlace olive olivedrab orange orangered orchid palegoldenrod palegreen paleturquoise
palevioletred papayawhip peachpuff peru pink plum powderblue purple rebeccapurple red rosybrown royalblue
saddlebrown salmon sandybrown seagreen seashell sienna silver skyblue slateblue slategray slategrey snow
springgreen steelblue tan teal thistle tomato turquoise violet wheat white whitesmoke yellow yellowgreen
currentcolor'''.split())
# The properties judged. A shorthand that can also hide (`font`, `inset`, `all`) is not expanded.
_OFFSETS = frozenset({'left', 'top', 'right', 'bottom'})
RELEVANT = frozenset(_SIZES) | _OFFSETS | {'display', 'visibility', 'content-visibility', 'opacity', 'color',
                                           'clip', 'clip-path', 'text-indent', 'transform', 'scale', 'translate'}

_N = r'[+-]?(?:[0-9]*\.[0-9]+|[0-9]+)(?:e[+-]?[0-9]+)?'
_DIMENSION = re.compile(rf'({_N})([a-z]*|%)')
_IMPORTANT = re.compile(r' ?! ?important$')
_HEX = re.compile(r'#(?:[0-9a-f]{3,4}|[0-9a-f]{6}|[0-9a-f]{8})')
_C = rf'(?:{_N}%?)'
_COLOUR_FN = re.compile(                         # legacy commas, or spaces with `/ alpha`
    rf'(rgba?|hsla?)\( ?({_N}[a-z%]*)(?: ?, ?({_C}) ?, ?({_C})(?: ?, ?({_C}))?| ({_C}) ({_C})(?: ?/ ?({_C}))?) ?\)')
_FUNCTION = re.compile(r'([a-z0-9]+)\(([^()]*)\) ?')


def split(style):
    """The declarations of an inline style as raw `property:value` pieces, cut at every `;` outside a
    string and outside parentheses — or None when this reader cannot be sure where a browser would
    cut: an escape, a comment, a block (`{}`, `[]`), an at-rule, an unclosed or line-broken string,
    unbalanced parentheses, an unquoted `url(` holding a quote or a parenthesis."""
    style = style or ''
    if '\\' in style or '/*' in style:
        return None
    out, at, depth, quote, i, n = [], 0, 0, None, 0, len(style)
    while i < n:
        ch = style[i]
        if quote:
            if ch == quote:
                quote = None
            elif ch in '\n\r\f':
                return None
        elif ch in '"\'':
            quote = ch
        elif ch == '(':
            depth += 1
            rest = style[i + 1:].lstrip(_WS)
            if style[:i].lower().endswith('url') and rest[:1] not in ('"', "'"):
                close = style.find(')', i)
                if close < 0 or any(c in style[i + 1:close] for c in '"\'('):
                    return None
                i = close
                continue
        elif ch == ')':
            depth -= 1
            if depth < 0:
                return None
        elif ch in '{}[]@':
            return None
        elif ch == ';' and depth == 0:
            out.append(style[at:i])
            at = i + 1
        i += 1
    if quote or depth:
        return None
    out.append(style[at:])
    return out


def declarations(style):
    """[(property, value, important)] in order, or None when `split` cannot read the style. Property
    names and values are lower-cased and whitespace is collapsed — except a custom property (`--X`),
    whose name is case-sensitive and whose value is left as written."""
    pieces = split(style)
    if pieces is None:
        return None
    out = []
    for piece in pieces:
        if ':' not in piece:
            continue                              # a browser drops it too
        prop, value = piece.split(':', 1)
        prop, value = prop.strip(_WS), value.strip(_WS)
        if prop.startswith('--'):
            out.append((prop, value, False))
            continue
        if not prop.isascii():
            continue                              # no judged property has such a name (`ſ`, `K` fold to ASCII)
        value = re.sub(r'[ \t\n\r\f]+', ' ', value)
        if value.isascii():
            value = value.lower()
        important = bool(_IMPORTANT.search(value))
        out.append((prop.lower(), _IMPORTANT.sub('', value), important))
    return out


def _dimension(token):
    """(number, unit) of one numeric token (`0`, `.5`, `12px`, `50%`, `1e3`), else None."""
    m = _DIMENSION.fullmatch(token)
    return (float(m.group(1)), m.group(2)) if m else None


def _length(token, percent=True):
    """The number of a length (`0`, `12px`, `50%`), else None."""
    got = _dimension(token)
    if got and (got[1] in _LENGTH or (got[1] == '' and got[0] == 0) or (percent and got[1] == '%')):
        return got[0]
    return None


def _far(token, percent=True):
    """Whether a length used as an offset moves the element off the page (True/False), None if not a length."""
    got = _dimension(token)
    if _length(token, percent) is None:
        return None
    return abs(got[0]) * _FAR_PX[got[1]] >= FAR


def _ratio(token):
    """A number or a percentage as a fraction (`0.5`, `50%`), else None."""
    got = _dimension(token)
    if got and got[1] in ('', '%'):
        return got[0] / 100 if got[1] == '%' else got[0]
    return None


def _colour(value):
    if value == 'transparent':
        return True
    if value in _COLOURS:
        return False
    if _HEX.fullmatch(value):
        digits = value[1:]
        if len(digits) in (3, 6):
            return False
        alpha = digits[3] * 2 if len(digits) == 4 else digits[6:]
        return int(alpha, 16) / 255 < NEAR_ZERO
    m = _COLOUR_FN.fullmatch(value)
    first = _dimension(m.group(2)) if m else None
    if first is None:
        return None
    rest, alpha = (m.group(3, 4), m.group(5)) if m.group(3) is not None else (m.group(6, 7), m.group(8))
    if m.group(1).startswith('rgb'):
        kinds = {first[1]} | {'%' if c.endswith('%') else '' for c in rest}
        if len(kinds) != 1 or kinds - {'', '%'}:          # all numbers or all percentages
            return None
    elif first[1] not in _ANGLE | {''} or not all(c.endswith('%') for c in rest):
        return None
    return alpha is not None and _ratio(alpha) < NEAR_ZERO


def _clips_nothing(value):
    m = re.fullmatch(r'inset\( ?([^()]*?) ?\)', value)
    sides = m.group(1).split(' ') if m else []
    return value == 'none' or (1 <= len(sides) <= 4 and all(_length(x) == 0 for x in sides))


def _transform(value):
    at, hides = 0, False
    for m in _FUNCTION.finditer(value):
        if m.start() != at:
            return None
        at = m.end()
        name, args = m.group(1), [a.strip(' ') for a in m.group(2).split(',')]
        if name in ('scale', 'scalex', 'scaley') and len(args) <= (2 if name == 'scale' else 1):
            nums = [_dimension(a) for a in args]
            if any(g is None or g[1] for g in nums):
                return None
            hides = hides or any(abs(g[0]) < NEAR_ZERO for g in nums)
        elif name in ('translate', 'translatex', 'translatey') and len(args) <= (2 if name == 'translate' else 1):
            far = [_far(a) for a in args]
            if None in far:
                return None
            hides = hides or any(far)
        elif name == 'rotate' and len(args) == 1:
            got = _dimension(args[0])
            if got is None or not (got[1] in _ANGLE or (got[1] == '' and got[0] == 0)):
                return None
        else:
            return None
    return hides if at == len(value) and at else None


def judge(prop, value):
    """One declaration of a judged property: True = it hides, False = it is valid and shows,
    None = this reader cannot tell what a browser makes of it (invalid, a function it does not
    evaluate such as `var()` `calc()` `env()` `attr()`, a unit or keyword outside the short lists
    above). The lists are deliberately short: what is not positively known is None."""
    if value in _GLOBAL:
        return False                  # the parent's own hiding is caught on the parent
    if not value.isascii() or not value.isprintable():
        return None
    one = value if ' ' not in value else None
    if prop == 'display':
        return one == 'none' if one in _DISPLAY else None
    if prop == 'visibility':
        return one != 'visible' if one in ('visible', 'hidden', 'collapse') else None
    if prop == 'content-visibility':
        return one == 'hidden' if one in ('visible', 'auto', 'hidden') else None
    if prop == 'opacity':
        got = _ratio(one or '')
        return None if got is None else got < NEAR_ZERO
    if prop in _SIZES:
        if one in _SIZES[prop]:
            return False
        got = _length(one or '')
        if got is None or got < 0:
            return None
        return got < NEAR_ZERO or (prop == 'font-size' and got * _SMALL_PX[_dimension(one)[1]] < TINY_FONT)
    if prop == 'text-indent':         # pulled out to the left at all, or pushed out to the right
        got = _length(one or '')
        return None if got is None else got < 0 or _far(one)
    if prop in _OFFSETS:
        return False if one == 'auto' else _far(one or '')
    if prop == 'translate':
        if value == 'none':
            return False
        far = [_far(w, percent=i < 2) for i, w in enumerate(value.split(' '))]
        return None if len(far) > 3 or None in far else any(far[:2])
    if prop == 'color':
        return _colour(value)
    if prop == 'clip':                # an invalid value counts as hiding, never as showing: a later valid
        return value != 'auto'        # one still wins over it exactly as it would in a browser
    if prop == 'clip-path':           # see `clip` — anything but "clips nothing" counts as hiding
        return not _clips_nothing(value)
    if prop == 'transform':
        return False if value == 'none' else _transform(value)
    if prop == 'scale':
        if value == 'none':
            return False
        nums = [_dimension(w) for w in value.split(' ')]
        if len(nums) > 3 or any(g is None or g[1] for g in nums):
            return None
        return any(abs(g[0]) < NEAR_ZERO for g in nums[:2])
    return False


def style_verdict(style):
    """(hides, why) for one inline style. **Fail closed, on purpose**: this is not a CSS engine. If the
    style cannot be cut into declarations with certainty, or *any* declaration of a judged property —
    winning or not — has a value `judge` cannot read, the element counts as hidden and `why` says
    `판정할 수 없는 CSS …`. Otherwise every such declaration is valid, the cascade within one style
    attribute is simple (`!important` beats normal, later beats earlier) and the winners decide.
    A writer who needs `calc()` or `var()` on these properties gets a loud refusal, not a silent pass."""
    decls = declarations(style)
    if decls is None:
        return True, f'{UNSURE}(따옴표·괄호·주석·이스케이프) 「{(style or "")[:40]}」'
    won = {}
    for prop, value, important in decls:
        if prop not in RELEVANT:
            continue
        got = judge(prop, value)
        if got is None:
            return True, f'{UNSURE} 값 「{prop}:{value[:30]}」'
        if important or not won.get(prop, (None, None, False))[2]:
            won[prop] = (got, value, important)
    for prop, (got, value, _imp) in won.items():
        if got:
            return True, f'{prop}:{value[:30]}'
    return False, None


def style_hides(style):
    return style_verdict(style)[0]


def _pairs(attrs):
    items = attrs.items() if isinstance(attrs, dict) else attrs
    return [((k or '').lower(), v or '') for k, v in items]


def is_hidden(attrs):
    """Whether these attributes hide the element (and so its subtree). `attrs` is a dict or a list of
    (name, value) pairs; with a list every duplicate is checked — a browser keeps the first, a dict
    the last, so checking all of them is the side that never misses."""
    for k, v in _pairs(attrs):
        if k in ('hidden', 'inert'):
            return True
        if k == 'aria-hidden' and v.strip().lower().startswith('true'):
            return True
        if k == 'class' and HIDDEN_CLASSES & {c.lower() for c in v.split()}:
            return True
        if k == 'style' and style_hides(v):
            return True
    return False


class _Start(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.got = None

    def handle_starttag(self, tag, attrs):
        if self.got is None:
            self.got = (tag, attrs)

    handle_startendtag = handle_starttag


def start_tag(raw):
    """(tag, [(name, value)]) of one raw start tag, or None for an end tag, comment or junk."""
    if not raw.startswith('<') or raw.startswith(('</', '<!', '<?')):
        return None
    p = _Start()
    try:
        p.feed(raw)
        p.close()
    except Exception:
        return None
    return p.got


def tag_hidden(raw):
    """Whether one raw start tag hides its element."""
    got = start_tag(raw)
    return bool(got) and is_hidden(got[1])


def unsure_note(html):
    """For a gate's message: when some start tag in `html` is hidden only because its CSS could not be
    judged (`style_verdict`), say which — the writer otherwise sees "hidden" on text that shows."""
    for m in TAG_RE.finditer(html or ''):
        got = start_tag(m.group(0)) if 'style' in m.group(0).lower() else None
        for k, v in _pairs(got[1]) if got else ():
            why = style_verdict(v)[1] if k == 'style' else None
            if why and why.startswith(UNSURE):
                return f' [{why} — 확실히 읽을 수 없는 값은 숨김으로 본다. 단순한 값으로 쓴다]'
    return ''


def hidden_tags(html, start=0, end=None):
    """Every start tag in html[start:end] whose attributes hide it — match objects of `TAG_RE`."""
    end = len(html) if end is None else end
    return [m for m in TAG_RE.finditer(html, start, end) if tag_hidden(m.group(0))]


# Elements that can have no content (HTML void elements, plus `param`, which the parser still treats
# as one). The one list for every "does this hidden element enclose what follows" walk.
VOID = frozenset({'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param',
                  'source', 'track', 'wbr'})


def encloses(doc, at, candidates, void_encloses=True):
    """The first candidate start tag (a match object over `doc`) whose element is still open at `at`,
    as its first 60 characters, else None. Elements close at the same-name end tag counted by depth;
    one never closed encloses everything after it. (Was `_hidden_ancestor` in auction_gate and a copy
    in liquidity_gate; their raw regexes stay theirs and are passed in here.) With `void_encloses`
    False an element that can have no content (`<img>`, `<br>` …) encloses nothing; the old walk, kept
    for the old regexes, let one never closed enclose everything after it."""
    for m in candidates:
        name = re.match(r'<\s*([a-zA-Z][\w-]*)', m.group(0))
        if not name:
            continue
        depth, tag = 0, name.group(1).lower()
        if not void_encloses and tag in VOID:
            continue
        for t in TAG_RE.finditer(doc, m.start()):
            nm = re.match(r'<\s*(/?)\s*([a-zA-Z][\w-]*)', t.group(0))
            if not nm or nm.group(2).lower() != tag or t.group(0).endswith('/>'):
                continue
            depth += -1 if nm.group(1) else 1
            if depth == 0:
                if t.start() > at:
                    return m.group(0)[:60]
                break
        else:
            return m.group(0)[:60]
    return None


def hidden_ancestor(doc, at):
    """A start tag before `at` that `is_hidden` calls hidden and whose element is still open at `at`."""
    return encloses(doc, at, hidden_tags(doc, 0, at), void_encloses=False)


def fragment_hidden(doc, start, end):
    """For the element whose source is doc[start:end] (start = its start tag): the first hiding start
    tag that is it, inside it, or open around it — 60 characters of it, else None."""
    inside = hidden_tags(doc, start, end)
    if inside:
        return inside[0].group(0)[:60]
    return hidden_ancestor(doc, start)
