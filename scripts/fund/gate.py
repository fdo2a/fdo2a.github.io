"""Publish gate for the fund sections (US 「트렌드 유닛 점검」, KR 「아시아 세션 유닛 관측」).

What it proves, reading the parsed document (entities decoded, comments ignored):

  - the section exists exactly when the day's data says it is owed;
  - the generated block appears once, inside that section, byte-identical to a fresh
    render of the JSON, with no ancestor that hides it (hidden attribute, inline
    display:none / visibility:hidden, <template>, a <details> without `open`);
  - `data-fund` sits only on visible <p> elements inside the section, required ones
    exactly once, and their controlled attributes agree with the JSON;
  - every %, %p, bp and 위 figure in those paragraphs is a value of the named units
    or of the block (a written sign must match; an unsigned figure matches the
    magnitude, so 「3.5% 내렸다」 passes);
  - no unit-recommendation wording inside the section.

What it does not prove: visibility through CSS classes or external stylesheets, that a
news story caused a move, or that an idea is sound. Those stay with editorial review.
The hash on the block is an integrity tag, not a fact check.
"""

import re
from html.parser import HTMLParser

from fund import kr_view, render
from fund.universe import UNITS

EFFECTIVE = '2026-10-07'
UNDETERMINED = '미판정'

SPEC = {
    'us': {'title': '트렌드 유닛 점검', 'block': 'data-fund-board',
           'required': ('regime', 'shift'), 'optional': ('risk',),
           'render': render.board_html},
    'kr': {'title': '아시아 세션 유닛 관측', 'block': 'data-fund-kr',
           'required': ('fx_cash', 'observe'), 'optional': (),
           'render': kr_view.html},
}

UNIT_IDS = {u[0] for u in UNITS}
PCT_FIELDS = ('ret_1m', 'ret_3m', 'ret_6m', 'ret_12m', 'mom_12_1', 'vol_60', 'var_1d_90',
              'var_1d_95', 'drawdown_52w')
PP_FIELDS = ('rel_3m', 'rel_3m_5d', 'rel_3m_chg_pp')

# 권고형만 막는다. 순매수·순매도·매수세·매도세는 관찰이라 통과한다.
FORBIDDEN = (
    ('편입', r'편입'),
    ('비중 확대·축소', r'비중\s*(확대|축소)'),
    ('비중을 늘·줄', r'비중을\s*(늘|줄)'),
    ('담아', r'담아|담을\s*만'),
    ('매수·매도 권고',
     r'(?<!순)(매수|매도)\s*(를|을)?\s*(권|추천|제안|해야|하라|하자|하는\s*편|할\s*만|하기를|의견)'),
    ('매수·매도가 바람직', r'(?<!순)(매수|매도)\s*(가|는|이)?\s*(바람직|유리|낫|좋)'),
    ('매수 적기·기회', r'(?<!순)(매수|매도)\s*(적기|기회|시점|타이밍)'),
    ('매수하·매도하', r'(?<!순)(매수|매도)하'),
    ('사야·팔아야', r'사야\s*(한|할)|팔아야\s*(한|할)'),
    ('사라·팔아라', r'(를|을)\s*사라(?![가-힣])|팔아라|사들여라|사\s*두라'),
)

VOID = {'br', 'hr', 'img', 'meta', 'link', 'input', 'source', 'wbr', 'area', 'base', 'embed',
        'param', 'track', 'col'}
# Elements whose content a browser does not render as page content (raw text, form
# controls, fallbacks). Anything under them counts as hidden.
NONDISPLAY = {'textarea', 'xmp', 'select', 'option', 'optgroup', 'datalist', 'noscript',
              'script', 'style', 'title', 'iframe', 'noembed', 'noframes', 'plaintext',
              'object', 'template', 'head', 'svg', 'math'}
# A start tag of these closes an open <p> (HTML parsing rules) — so a <div> inside a
# marker paragraph is not the paragraph's text.
P_CLOSERS = {'address', 'article', 'aside', 'blockquote', 'details', 'dialog', 'div', 'dl',
             'fieldset', 'figcaption', 'figure', 'footer', 'form', 'h1', 'h2', 'h3', 'h4',
             'h5', 'h6', 'header', 'hgroup', 'hr', 'main', 'menu', 'nav', 'ol', 'p', 'pre',
             'section', 'table', 'ul'}
_NUM = re.compile(r'(?<![\d.])([+\-]?)\s*(\d[\d,]*(?:\.(\d+))?|\.(\d+))\s*(%포인트|%p|%|bp|위)')
_SIGNS = str.maketrans({'−': '-', '－': '-', '–': '-', '＋': '+'})
_HIDE_STYLE = re.compile(r'display\s*:\s*none|visibility\s*:\s*hidden', re.I)


def _self_hidden(tag, attrs):
    return ('hidden' in attrs or bool(_HIDE_STYLE.search(attrs.get('style', '')))
            or tag in NONDISPLAY or (tag == 'details' and 'open' not in attrs))


class _Node:
    __slots__ = ('tag', 'attrs', 'parent', 'start', 'end', 'text', 'prose', 'raw', 'self_hidden',
                 'dup')

    def __init__(self, tag, attrs, parent, start):
        self.tag, self.attrs, self.parent, self.start = tag, attrs, parent, start
        self.end = None
        self.text, self.prose = [], []          # visible text only
        self.raw = []                           # all text, to find headings even when hidden
        self.self_hidden = _self_hidden(tag, attrs)
        self.dup = False

    def ancestors(self):
        n = self
        while n is not None:
            yield n
            n = n.parent

    def plain(self):
        return re.sub(r'\s+', ' ', ''.join(self.text)).strip()


class _Doc(HTMLParser):
    """Element tree with source offsets, following the browser where it matters for
    hiding: a self-closed non-void tag stays open, a block start tag closes an open <p>,
    duplicate attributes are recorded as errors. Text is entity-decoded, comments are
    dropped, and a node's `text` holds only text with no hidden element above it.
    `prose` is that visible text excluding anything inside the generated block."""

    def __init__(self, html, block_attr):
        super().__init__(convert_charrefs=True)
        self.html, self.block_attr = html, block_attr
        self.offsets = [0]
        for line in html.splitlines(keepends=True):
            self.offsets.append(self.offsets[-1] + len(line))
        self.stack, self.nodes, self.void_dups = [], [], []
        self.feed(html)
        self.close()
        for n in self.stack:
            n.end = len(html)

    def _pos(self):
        row, col = self.getpos()
        return self.offsets[row - 1] + col

    def handle_starttag(self, tag, attrs):
        names = [k for k, _ in attrs]
        dup = len(names) != len(set(names))
        if tag in P_CLOSERS and any(n.tag == 'p' for n in self.stack):
            while self.stack:
                n = self.stack.pop()
                n.end = self._pos()
                if n.tag == 'p':
                    break
        if tag in VOID:
            if dup:
                self.void_dups.append(self._pos())
            return
        node = _Node(tag, {k: (v or '') for k, v in attrs},
                     self.stack[-1] if self.stack else None, self._pos())
        node.dup = dup
        self.stack.append(node)
        self.nodes.append(node)

    def handle_startendtag(self, tag, attrs):
        # `<main hidden/>`: the slash means nothing on a non-void HTML element — it stays
        # open. Inside SVG/MathML (foreign content) `/>` really closes the element.
        self.handle_starttag(tag, attrs)
        if tag in ('svg', 'math') or any(n.tag in ('svg', 'math') for n in self.stack[:-1]):
            if self.stack and self.stack[-1].tag == tag:
                n = self.stack.pop()
                n.end = self.html.find('>', self._pos()) + 1

    def handle_endtag(self, tag):
        if not any(n.tag == tag for n in self.stack):
            return
        end = self.html.find('>', self._pos()) + 1
        while self.stack:
            n = self.stack.pop()
            n.end = end if n.tag == tag else self._pos()
            if n.tag == tag:
                break

    def handle_data(self, data):
        for n in self.stack:
            n.raw.append(data)
        if any(n.self_hidden for n in self.stack):
            return
        in_block = any(self.block_attr in n.attrs for n in self.stack)
        for n in self.stack:
            n.text.append(data)
            if not in_block:
                n.prose.append(data)


def _hidden(node):
    return any(n.self_hidden for n in node.ancestors())


def _owed(data, post_date):
    return bool(data) and data.get('status') in ('ok', 'partial') \
        and data.get('report_date') == post_date


def _figures(text):
    """[(raw, signed value or None, magnitude, decimals, unit)]."""
    out = []
    for m in _NUM.finditer(text.translate(_SIGNS)):
        raw = m.group(2).replace(',', '')
        mag = float('0' + raw if raw.startswith('.') else raw)
        sign = m.group(1)
        signed = None if not sign else (-mag if sign == '-' else mag)
        unit = '%p' if m.group(5) == '%포인트' else m.group(5)
        out.append((m.group(0).strip(), signed, mag, len(m.group(3) or m.group(4) or ''), unit))
    return out


def _matches(signed, mag, dec, allowed):
    for a in allowed:
        if signed is not None:
            if round(a, dec) == round(signed, dec):
                return True
        elif round(abs(a), dec) == round(mag, dec):
            return True
    return False


def _check_figures(label, text, allowed):
    v = []
    for raw, signed, mag, dec, unit in _figures(text):
        if not _matches(signed, mag, dec, allowed.get(unit) or []):
            v.append(f'{label} 문단의 「{raw}」가 근거 자료의 값이 아니다 — 표의 수치를 반올림해 쓴다')
    return v


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _allowed_us_units(data, ids):
    pct, pp, rank = [], [], []
    for u in data.get('units') or []:
        if u['id'] in ids:
            pct += [u[k] for k in PCT_FIELDS if _num(u.get(k))]
            pp += [u[k] for k in PP_FIELDS if _num(u.get(k))]
            rank += [u[k] for k in ('rank', 'rank_5d', 'rank_chg') if _num(u.get(k))]
    return {'%': pct, '%p': pp, 'bp': [], '위': rank}


def _allowed_us_regime(data):
    mr = data.get('market_regime') or {}
    inp = mr.get('inputs') or {}
    pct = [inp[k] for k in ('ret_3m', 'drawdown') if _num(inp.get(k))]
    dd = (mr.get('rules') or {}).get('drawdown_pct')
    if _num(dd):
        pct.append(dd)
    return {'%': pct, '%p': [], 'bp': [], '위': []}


def _allowed_us_risk(data):
    """Liquidity is quoted in 십억 달러 and NFCI points — neither is a % figure."""
    risk = data.get('risk') or {}
    pct, bp = [], []
    vix = risk.get('vix') or {}
    if _num(vix.get('percentile_2y')):
        pct.append(vix['percentile_2y'])
    for k in ('hy_spread', 'real_10y'):
        r = risk.get(k) or {}
        if _num(r.get('level')):
            pct.append(r['level'])
        if _num(r.get('chg_5d_bp')):
            bp.append(r['chg_5d_bp'])
    return {'%': pct, '%p': [], 'bp': bp, '위': []}


def _allowed_kr_observe(data, ids):
    pct = []
    for o in data.get('observations') or []:
        if o['unit_id'] in ids:
            if _num(o.get('change_pct')):
                pct.append(o['change_pct'])
            if _num(o.get('breadth')):
                pct.append(o['breadth'] * 100)
    return {'%': pct, '%p': [], 'bp': [], '위': []}


def _allowed_kr_fx(data):
    rates = data.get('cash_rates') or []
    pct = [r['value'] for r in rates if _num(r.get('value'))]
    pct += [v['pct'] for v in (data.get('us_futures') or {}).values() if _num(v.get('pct'))]
    bp = [r['bp'] for r in rates if _num(r.get('bp'))]
    return {'%': pct, '%p': [], 'bp': bp, '위': []}


def _units_attr(node, label):
    ids = [x.strip() for x in node.attrs.get('data-units', '').split(',') if x.strip()]
    v = []
    if not 1 <= len(ids) <= 3:
        v.append(f'{label} 문단의 data-units 는 유닛 id 1~3개다')
    bad = [x for x in ids if x not in UNIT_IDS]
    if bad:
        v.append(f'{label} 문단의 알 수 없는 유닛 id: {", ".join(bad)}')
    return set(ids), v


def check(html, data, market, post_date, effective=EFFECTIVE):
    if not post_date or post_date < effective:
        return []
    spec = SPEC[market]
    attr, title = spec['block'], spec['title']
    doc = _Doc(html, attr)
    heads = [n for n in doc.nodes
             if n.tag == 'h2' and re.sub(r'\s+', ' ', ''.join(n.raw)).strip() == title]
    markers = [n for n in doc.nodes if 'data-fund' in n.attrs]
    blocks = [n for n in doc.nodes if attr in n.attrs]

    if not _owed(data, post_date):
        if heads or markers or blocks or f'{attr}=' in html:
            return [f'오늘 자료가 없거나 날짜가 다르므로 「{title}」 섹션·표식이 없어야 한다']
        return []

    if len(heads) != 1:
        return [f'「{title}」 섹션이 정확히 하나 있어야 한다(자료 상태 {data.get("status")})']
    section = next((n for n in heads[0].ancestors() if n.tag == 'section'), None)
    if section is None:
        return [f'「{title}」 제목이 <section> 안에 있어야 한다']

    def inside(node):
        return any(a is section for a in node.ancestors())

    v = []
    # duplicate attributes: a browser keeps the first, the parser the last — only where
    # it can decide visibility (the section, its ancestors, everything inside it)
    for n in doc.nodes:
        if n.dup and (inside(n) or any(a is n for a in section.ancestors())):
            v.append(f'<{n.tag}> 에 같은 속성이 두 번 있다 — 브라우저와 해석이 갈린다')
    if any(section.start <= pos < (section.end or len(html)) for pos in doc.void_dups):
        v.append('섹션 안 빈 요소(img 등)에 같은 속성이 두 번 있다')
    if _hidden(section):
        v.append(f'「{title}」 섹션이 보이지 않는다(숨겨진 조상 요소)')

    # the generated block — counted in the raw source too, so a commented copy is caught
    raw_blocks = html.count(f'{attr}=')
    if raw_blocks != 1 or len(blocks) != 1:
        v.append(f'생성 블록({attr})은 문서에 정확히 하나여야 한다 — {raw_blocks}개')
    elif not inside(blocks[0]):
        v.append('생성 블록이 이 섹션 밖에 있다')
    else:
        block = blocks[0]
        if _hidden(block):
            v.append('생성 블록이 보이지 않는다(숨겨진 조상 요소)')
        if html[block.start:block.end] != spec['render'](data):
            v.append('생성 블록이 오늘 자료로 다시 그린 것과 다르다 — 스니펫을 고치지 말고 그대로 넣는다')

    # markers: visible <p> inside the section only
    known = set(spec['required']) | set(spec['optional'])
    paras = {}
    for n in markers:
        name = n.attrs['data-fund']
        if n.tag != 'p':
            v.append(f'data-fund="{name}" 는 <p> 에만 단다 — <{n.tag}> 에 있다')
            continue
        if not inside(n):
            v.append(f'data-fund="{name}" 문단이 섹션 밖에 있다')
            continue
        if name not in known:
            v.append(f'알 수 없는 표식 data-fund="{name}"')
            continue
        if _hidden(n):
            v.append(f'<p data-fund="{name}"> 문단이 보이지 않는다')
        if not n.plain():
            v.append(f'<p data-fund="{name}"> 문단이 비어 있다')
        paras.setdefault(name, []).append(n)
    for name in spec['required']:
        got = len(paras.get(name, []))
        if got != 1:
            v.append(f'<p data-fund="{name}"> 문단이 정확히 하나 있어야 한다 — {got}개')
    for name in spec['optional']:
        if len(paras.get(name, [])) > 1:
            v.append(f'<p data-fund="{name}"> 문단은 하나까지다')
    one = {k: ns[0] for k, ns in paras.items() if len(ns) == 1}

    v += _check_us(one, data) if market == 'us' else _check_kr(one, data)

    prose = re.sub(r'\s+', ' ', ''.join(section.prose))
    for label, pat in FORBIDDEN:
        if re.search(pat, prose):
            v.append(f'「{label}」 — 유닛 편입·비중·매매 권고를 쓰지 않는다. '
                     '「가격 근거가 강해졌다·약해졌다」처럼 관찰로 쓴다')
    return v


def _check_us(paras, data):
    v = []
    if 'regime' in paras:
        n = paras['regime']
        want = (data.get('market_regime') or {}).get('name') or UNDETERMINED
        if n.attrs.get('data-regime') != want:
            v.append(f'regime 문단의 data-regime 이 오늘 국면 「{want}」과 다르다')
        v += _check_figures('regime', n.plain(), _allowed_us_regime(data))
    if 'shift' in paras:
        n = paras['shift']
        ids, vv = _units_attr(n, 'shift')
        v += vv + _check_figures('shift', n.plain(), _allowed_us_units(data, ids))
    if 'risk' in paras:
        v += _check_figures('risk', paras['risk'].plain(), _allowed_us_risk(data))
    return v


def _check_kr(paras, data):
    v = []
    if 'observe' in paras:
        n = paras['observe']
        ids, vv = _units_attr(n, 'observe')
        v += vv + _check_figures('observe', n.plain(), _allowed_kr_observe(data, ids))
    if 'fx_cash' in paras:
        v += _check_figures('fx_cash', paras['fx_cash'].plain(), _allowed_kr_fx(data))
    return v
