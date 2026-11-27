"""숫자는 코드가 채운다 — US 일간 1차(2026-11-27). `data-ref` 칸 안 글자를 칸 값으로 다시 쓴다.

작성자가 쓴 글자는 **모양**(자릿수·부호·단위·배율·쉼표·한글 수사)과 **대조**에만 쓴다. 칸 값을 그 모양으로 찍은
글자가 쓴 글자와 값이 다르면 덮지 않고 되돌린다(`problems`). 칸은 `us.facts.Book` 이 푼다(숫자 출처 검사와 같은 풀이기).

모양 규칙(설계 §1)
- 반올림은 십진 표기(repr)에서 한 번, half-up.
- 부호를 썼으면 칸 값의 부호를 찍는다. `|abs` 는 **음수 칸에서만** — 양수 칸에 달면 되돌린다. 부호 없이 쓴 음수 칸도 되돌린다.
- 0 이 아닌 값이 쓴 자리에서 0 으로 반올림되면 되돌린다.
- 어림선 `|lvl` 은 쓴 유효 자리로 내린다(7,323.63 → 「7,300선」).
- 단위는 칸의 허용 집합·환산표(`Fact.units`·`Fact.conv`) 안에서만. 배율(억·B)은 쓴 배율 그대로.
- 관측일이 글 날짜와 다른 칸(stale)은 채우고 바로 뒤에 기준일을 찍는다(`<span data-asof="D">(M월 D일 기준)</span>`).
  표 칸(td·th) 안은 찍지 않는다 — 표는 기준일 열과 표 대조(`check_numbers`)가 맡는다.
- invalid·풀 수 없는 칸·표식 하나에 수량이 정확히 하나가 아닌 것은 채우지 않고 되돌린다.
- 제목·og 설명: meta.json 의 `title_refs`·`summary_refs`(숫자 순서대로의 칸 이름) → og:title·og:description meta 의
  `data-refs` 로 옮겨 적고(`<title>` 태그는 맨 꼴 그대로) 본문 칸과 똑같이 채운다. meta 설명은 h1 에서 다시 만든다.

두 번 돌려도 결과가 같다. 설계: docs/superpowers/specs/2026-11-20-number-sources.md 「2026-11-27 숫자는 코드가 채운다」
"""
import html as _html
import json
import math
import re
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal

from common import numsrc as S
from common import post_parts as P
from us import facts as F

_INERT = re.compile(r'<!--.*?-->|<(script|style|template|textarea)\b[^>]*>.*?</\1\s*>', re.S | re.I)
# 칸 표식 — 안에 태그가 없을 때만 채운다(태그가 있으면 표식 오류로 되돌린다)
_REF = re.compile(r'<span\b(?P<attrs>[^>]*\bdata-ref="(?P<ref>[^"]*)"[^>]*)>(?P<inner>.*?)</span>', re.S)
_ASOF = re.compile(r'\A<span data-asof="(\d{4}-\d{2}-\d{2})">[^<]*</span>')
_CELL_OPEN = re.compile(r'<t[dh]\b', re.I)
_CELL_CLOSE = re.compile(r'</t[dh]\s*>', re.I)
MINUS = '-−–'
FORMAT = 'fill/1'


class Shape(Exception):
    """쓴 글자로는 칸 값을 찍을 수 없다(모양 규칙 위반) 또는 쓴 값 ≠ 채운 값."""

    def __init__(self, kind, msg, filled=None):
        super().__init__(msg)
        self.kind, self.msg, self.filled = kind, msg, filled


def asof_text(date):
    return f'({int(date[5:7])}월 {int(date[8:10])}일 기준)'


def asof_span(date):
    return f'<span data-asof="{date}">{asof_text(date)}</span>'


def value_quantities(text, terms):
    """표식 안 글의 값 수량(X-코드 제외) + 한글 개수."""
    qs = [q for q in S.quantities(text, terms) if not q.code]
    return sorted(qs + S.korean_quantities(text), key=lambda q: q.start)


def _fmt(d, decimals, commas):
    s = f'{d:,.{decimals}f}' if commas else f'{d:.{decimals}f}'
    return s


def render(q, text, f, flags):
    """쓴 수량 q(글 text 안) + 칸 f → 채운 글. 어기면 Shape."""
    unit = q.unit
    if unit in f.units:
        conv = 1.0
    elif unit in f.conv:
        conv = f.conv[unit]
    elif 'lvl' in flags and unit in ('선', '대') and ('' in f.units or 'p' in f.units):
        conv = 1.0
    else:
        raise Shape('모양', f'단위 「{unit}」 는 이 칸의 단위가 아니다({"·".join(sorted(x or "없음" for x in f.units))})')
    exp = f.value * f.scale * conv
    if 'abs' in flags:
        if not exp < 0:
            raise Shape('모양', '|abs 는 음수 칸에만 단다 — 이 칸은 음수가 아니다')
        if q.sign:
            raise Shape('모양', '|abs 칸에 부호를 썼다')
        exp = -exp
    elif exp < 0 and not q.sign:
        raise Shape('모양', '부호 없이 쓴 음수 칸 — 「내렸다」로 쓰면 |abs 를 단다')
    if q.korean:
        if exp != int(exp):
            raise Shape('모양', '한글 수사로 쓴 칸이 정수가 아니다')
        word = S.korean_print(int(exp), bool(q.unit))
        if word is None:
            raise Shape('모양', '한글 수사는 1-20 만 찍는다')
        written = int(q.value)
        new = word + text[q.start + _word_len(text, q):q.end]
        if written != int(exp):
            raise Shape('자료와 다름', f'쓴 값 {written} ≠ 칸 값 {int(exp)}', text[:q.start] + new + text[q.end:])
        return text[:q.start] + new + text[q.end:]
    if len(q.runs) != 1:
        raise Shape('모양', '배율 사슬(「265억 3천만」)은 채우지 않는다 — 한 숫자열로 쓴다')
    a, b = q.runs[0]
    run = text[a:b]
    lead = run.startswith('.')
    written_abs = Decimal(('0' + run) if lead else run.replace(',', ''))
    decimals = len(run.split('.')[1]) if '.' in run else 0
    scale = q.scale if q.scale else 1.0
    mag = Decimal(repr(abs(exp) / scale)) if scale != 1.0 else Decimal(repr(abs(exp)))
    if 'lvl' in flags:
        if q.sig == 0 or q.sig > 2 or mag == 0:
            raise Shape('모양', '어림선은 유효숫자 1-2자리(「7,300선」)')
        step = Decimal(10) ** (math.floor(math.log10(float(mag))) - q.sig + 1)
        rounded = (mag / step).to_integral_value(rounding=ROUND_FLOOR) * step
        rounded = rounded.quantize(Decimal(1)) if decimals == 0 else rounded
    else:
        rounded = mag.quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP)
        if rounded == 0 and mag != 0:
            raise Shape('모양', f'0 이 아닌 값({abs(exp):g})이 쓴 자리에서 0 이 된다 — 자리를 늘린다')
    new_run = _fmt(rounded, decimals, ',' in run)
    if lead and new_run.startswith('0.'):
        new_run = new_run[1:]
    out = text[:a] + new_run + text[b:]
    neg = exp < 0
    if q.sign:
        si = next((i for i in range(a - 1, q.start - 1, -1) if text[i] in '+' + MINUS), None)
        if si is None:
            raise Shape('모양', '부호 자리를 찾지 못했다')
        written_neg = text[si] in MINUS
        ch = (text[si] if written_neg else '-') if neg else '+'
        if rounded == 0:
            ch = text[si]
        out = out[:si] + ch + out[si + 1:]
        if written_neg != neg and rounded != 0:
            raise Shape('자료와 다름', f'쓴 부호 {text[si]} ≠ 칸 값 부호', out)
    if written_abs != rounded:
        raise Shape('자료와 다름', f'쓴 값 {run} ≠ 칸 값을 그 자리로 찍은 {new_run}(칸 값 {exp:g})', out)
    return out


def _word_len(text, q):
    """한글 수사 낱말 길이(세는 말 앞까지)."""
    raw = text[q.start:q.end]
    for w in sorted(list(S.KO_STANDALONE) + list(S.KO_DETERMINER), key=len, reverse=True):
        if raw.startswith(w):
            return len(w)
    return len(raw)


def _masked(html):
    return _INERT.sub(lambda m: ' ' * len(m.group(0)), html)


def _in_cell(masked, pos):
    pre = masked[:pos]
    return len(_CELL_OPEN.findall(pre)) > len(_CELL_CLOSE.findall(pre))


def _section_at(sections, pos):
    for s, e, t in sections:
        if s <= pos < e:
            return t
    return ''


def _cycle(html):
    m = re.search(r'data-research-cycle="([^"]+)"', html)
    return m.group(1) if m else None


# 어느 구역에서든 되돌리는 문제(칸을 단 숫자가 칸과 맞지 않음) — `칸 없음` 은 block 구역에서만 되돌린다
ALWAYS = frozenset({'자료와 다름', '표식 오류', '칸 무효', '모양'})


def blocking(kind, mode):
    return kind in ALWAYS or (kind == '칸 없음' and mode == 'block')


def fill(html, datadir, date, repo, meta=None, ledger=None, terms=None, zones=None):
    """→ (새 html, 보고서 사전). 문제(되돌릴 것)는 보고서 `problems`."""
    from us import number_sources as U
    from us import zones as Z
    terms = U.fixed_terms() if terms is None else terms
    zones = Z.load() if zones is None else zones
    book = F.Book(datadir, date, ledger if ledger is not None else F.load_ledger(repo), _cycle(html))
    slots, problems = [], []
    masked = _masked(html)
    sections = P.top_sections(html)
    out, pos = [], 0
    for m in _REF.finditer(masked):
        s, e = m.start(), m.end()
        raw = html[s:e]
        mm = _REF.match(raw)
        ref, inner = _html.unescape(mm.group('ref')), mm.group('inner')
        sec = _section_at(sections, s)
        zname, mode = Z.zone_of(zones, sec)
        slot = {'where': 'body', 'section': sec, 'zone': zname, 'mode': mode, 'ref': ref,
                'written': _html.unescape(inner)}
        out.append(html[pos:s])
        pos = e
        new_inner, asof = inner, None
        try:
            new_inner, fact = _fill_one(ref, inner, book, terms)
            slot.update(_fact_row(fact))
            if fact.status == 'stale' and fact.date[:10] != date and not _in_cell(masked, s):
                asof = fact.date[:10]
            slot['filled'] = _html.unescape(new_inner)
        except Shape as x:
            slot.update(problem=x.kind, why=x.msg, blocking=blocking(x.kind, mode))
            if x.filled is not None:
                slot['filled'] = x.filled
            problems.append(slot)
        out.append(raw[:mm.start('inner')] + new_inner + raw[mm.end('inner'):])
        # 기준일 — 바로 뒤의 옛 표지를 지우고(멱등) 필요하면 새로 찍는다
        old = _ASOF.match(html[pos:])
        if old:
            pos += old.end()
        if asof:
            out.append(asof_span(asof))
            slot['asof'] = asof
        slots.append(slot)
    out.append(html[pos:])
    new = ''.join(out)
    new, head = _fill_head(new, meta, book, terms, date)
    hz, hmode = Z.zone_of(zones, '')
    for h in head:
        h.update(zone=hz, mode=hmode)
        slots.append(h)
        if h.get('problem'):
            h['blocking'] = blocking(h['problem'], hmode)
            problems.append(h)
    rep = {'format': FORMAT, 'date': date,
           'counts': {'slots': len(slots), 'filled': sum(1 for x in slots if not x.get('problem')),
                      'changed': sum(1 for x in slots if not x.get('problem') and x.get('filled') != x.get('written')),
                      'stale_stamped': sum(1 for x in slots if x.get('asof')), 'problems': len(problems),
                      'blocking': sum(1 for x in problems if x.get('blocking'))},
           'problems': problems, 'slots': slots}
    return new, rep


def _fact_row(f):
    return {'asset': f.asset, 'group': '.'.join(str(x) for x in f.group[1:2]) if f.group else '', 'field': f.fld,
            'date': f.date[:10] if isinstance(f.date, str) else None, 'status': f.status, 'value': f.value}


def _fill_one(ref, inner, book, terms):
    """표식 하나 → (새 안쪽 html, 칸). 안쪽에 태그가 있거나 수량이 하나가 아니면 Shape."""
    if '<' in inner:
        raise Shape('표식 오류', '칸 표식 안에 태그가 있다 — 숫자 하나만 감싼다')
    text = _html.unescape(inner)
    qs = value_quantities(text, terms)
    if len(qs) != 1:
        raise Shape('표식 오류', f'칸 표식 하나에 값 수량이 {len(qs)}개다')
    name, *flags = ref.split('|')
    try:
        f = book.resolve(name.strip())
    except F.Miss as e:
        raise Shape(e.kind, e.msg)
    if f.status == 'invalid':
        raise Shape('칸 무효', f.why or '칸이 무효다')
    new = render(qs[0], text, f, set(flags))
    return _html.escape(new, quote=False), f


# ── 제목·설명 ──

_TITLE = re.compile(r'<title(?P<attrs>[^>]*)>(?P<text>.*?)</title>', re.S)
_OGD = re.compile(r'<meta property="og:description" content="(?P<text>[^"]*)"(?P<attrs>[^>]*)>')
_OGT = re.compile(r'<meta property="og:title" content="(?P<text>[^"]*)"(?P<attrs>[^>]*)>')
_DESC = re.compile(r'<meta name="description" content="(?P<text>[^"]*)">')
_H1 = re.compile(r'<h1\b[^>]*>(.*?)</h1>', re.S)
_REFS_ATTR = re.compile(r'\sdata-refs="([^"]*)"')


def head_refs(attrs):
    m = _REFS_ATTR.search(attrs or '')
    if not m:
        return None
    try:
        v = json.loads(_html.unescape(m.group(1)))
    except ValueError:
        return None
    return v if isinstance(v, list) and all(isinstance(x, str) for x in v) else None


def fill_text(text, refs, book, terms):
    """제목·설명 글 하나 → (새 글, [칸 행]). 값 수량 수와 이름표 수가 다르면 전부 문제."""
    qs = value_quantities(text, terms)
    rows = []
    if len(qs) != len(refs):
        return text, [{'ref': '', 'written': text, 'problem': '표식 오류',
                       'why': f'숫자 {len(qs)}개에 이름표 {len(refs)}개'}]
    out, pos = [], 0
    for q, ref in zip(qs, refs):
        piece = text[q.start:q.end]
        row = {'ref': ref, 'written': piece}
        out.append(text[pos:q.start])
        pos = q.end
        name, *flags = ref.split('|')
        try:
            f = book.resolve(name.strip())
            if f.status == 'invalid':
                raise Shape('칸 무효', f.why or '칸이 무효다')
            sub = S.korean_quantities(piece) if q.korean else [x for x in S.quantities(piece, terms) if not x.code]
            new = render(sub[0], piece, f, set(flags))
            row.update(_fact_row(f), filled=new)
            if f.status == 'stale' and f.date[:10] != book.date:
                new += asof_text(f.date[:10])
                row['asof'] = f.date[:10]
            out.append(new)
        except F.Miss as e:
            row.update(problem=e.kind, why=e.msg)
            out.append(piece)
        except Shape as x:
            row.update(problem=x.kind, why=x.msg)
            out.append(piece)
        rows.append(row)
    out.append(text[pos:])
    return ''.join(out), rows


def _strip_asof(text):
    return re.sub(r'\(\d{1,2}월 \d{1,2}일 기준\)', '', text)


def _fill_head(html, meta, book, terms, date):
    rows = []
    title_refs = (meta or {}).get('title_refs')
    summary_refs = (meta or {}).get('summary_refs')
    # 제목 이름표는 og:title meta 의 data-refs 에 둔다 — `<title>` 은 맨 꼴 그대로(다른 검사기가 `<title>(.*?)</title>` 로 읽는다)
    m, ogt = _TITLE.search(html), _OGT.search(html)
    if m:
        refs = title_refs if isinstance(title_refs, list) else head_refs(ogt.group('attrs') if ogt else '')
        text = _strip_asof(_html.unescape(m.group('text')))
        if refs is not None:      # 이름표를 적지 않은 제목은 채우지 않는다(제목은 warn 구역 — 검사가 목록만 낸다)
            new, got = fill_text(text, refs, book, terms)
            for g in got:
                g['where'] = 'title'
            if ogt is None:
                got = [{'ref': '', 'written': text, 'problem': '표식 오류', 'why': 'og:title meta 가 없어 이름표를 적을 곳이 없다'}]
            rows += got
            html = html[:m.start()] + f'<title{m.group("attrs")}>{_html.escape(new, quote=False)}</title>' + html[m.end():]
            ogt = _OGT.search(html)
            if ogt:
                attr = f' data-refs="{_html.escape(json.dumps(refs, ensure_ascii=False))}"'
                html = (html[:ogt.start()] + f'<meta property="og:title" content="{ogt.group("text")}"'
                        f'{attr}{_REFS_ATTR.sub("", ogt.group("attrs"))}>' + html[ogt.end():])
    m = _OGD.search(html)
    if m:
        refs = summary_refs if isinstance(summary_refs, list) else head_refs(m.group('attrs'))
        old_text = _html.unescape(m.group('text'))
        text = _strip_asof(old_text)
        if refs is not None:
            new, got = fill_text(text, refs, book, terms)
            for g in got:
                g['where'] = 'meta'
            rows += got
            attrs = _REFS_ATTR.sub('', m.group('attrs'))
            attr = f' data-refs="{_html.escape(json.dumps(refs, ensure_ascii=False))}"'
            html = (html[:m.start()] + f'<meta property="og:description" content="{_html.escape(new)}"{attr}{attrs}>'
                    + html[m.end():])
            # JSON-LD 설명도 같은 글이다(셸이 summary 로 만든다) — 글자 그대로 바꾼다
            html = html.replace(json.dumps(old_text, ensure_ascii=False).replace('</', '<\\/'),
                                json.dumps(new, ensure_ascii=False).replace('</', '<\\/'), 1)
    # meta 설명 = h1 의 보이는 글 + 날짜(셸 규칙) — 본문 h1 칸이 채워졌으니 다시 만든다
    h1 = _H1.search(html)
    d = _DESC.search(html)
    if h1 and d:
        # post_shell.plain 과 같은 규칙(그 모듈은 레포 뿌리 경로로만 불러진다)
        frag = re.sub(r'<span data-asof="[^"]*">[^<]*</span>', '', h1.group(1))
        plain = re.sub(r'\s+', ' ', _html.unescape(re.sub(r'<[^>]+>', '', frag))).strip()
        tail = _html.unescape(d.group('text'))
        k = tail.rfind(f'. {date} ')
        if k >= 0:
            html = (html[:d.start()] + f'<meta name="description" content="{_html.escape(plain + tail[k:], quote=True)}">'
                    + html[d.end():])
    return html, rows
