"""Did the anatomy block actually name what moved — item and this round's figure together?

2026-11-08 (A단계). The old check asked only whether each component's value appeared
*somewhere* in the block, so 「전월 59.0에서 55.5로」 counted 59.0 and a forecast
counted as a print. Here a component is **evidenced** by a clause that holds exactly one
component name and that component's current figure:

* Sentences are split at full stops, clauses at 「, 」 「; 」 and the connectives
  며·지만·는데·반면 followed by a space (a comma inside 42,000 is not a break).
* A sentence with a forecast word (예상·전망·컨센서스·예측·expected·forecast·consensus)
  is no evidence — component names are taken out first, so 「6개월 뒤 전망」 is not one.
* A figure followed by 「에서」 is where it came *from*; a figure after 전월·지난달·직전·
  앞서·이전 is last period's; a figure followed by %p·포인트·bp·만큼 is a change in size.
  None of them is the current value.
* A name right after 전월·지난달·지난 분기·직전 is last period's item.
* When a component's figure equals a headline figure, the clause must not also name
  the headline — otherwise the headline number would pass as a component.
* A percent component's figure must be followed by 「%」.

What the block owes depends on `anatomy_status` (us.anatomy.cross_check):
complete → 2 evidenced components; partial → 1 and 3 figures in all; text → 3 figures;
none → the canonical figures that exist (actual, previous when different).
"""
import re

from .section import number_forms

_SENT = re.compile(r'(?<=[.!?。])\s+|\n+')
_CLAUSE = re.compile(r'[,;]\s+|(?<=[가-힣])(?:며|고|지만|는데|반면)\s+')
# A clause segment that speaks of last period: 「전월에는 0.4%였고」. 「전월 대비」 is this
# month's change and does not count (codex 구현 1회 #4).
PREV_CONTEXT = re.compile(r'(?:전월|지난달|지난 달|직전|앞서|이전|전분기|지난 분기|previous|prior)'
                          r'(?!\s*대비)')
UP_WORDS = re.compile(r'올|오르|오름|상승|증가|늘|확대|개선|반등|뛰|급등|웃돌|플러스')
DOWN_WORDS = re.compile(r'내리|내렸|내림|내려|떨어|하락|감소|줄|축소|악화|급락|밑돌|마이너스|빠지|빠졌')
FORECAST = re.compile(r'예상|전망|컨센서스|예측|시장 기대|expected|forecast|consensus', re.I)
PREV_BEFORE_NAME = re.compile(r'(?:전월|지난달|지난 달|지난 분기|직전|전분기|previous|prior)\s*$')
PREV_BEFORE_VALUE = re.compile(r'(?:전월|지난달|지난 달|직전|앞서|이전|previous|prior)\s*[+−-]?$')
AFTER_FROM = re.compile(r'^\s*[%a-zA-Z가-힣]{0,3}\s*에서')
AFTER_CHANGE = re.compile(r'^\s*(?:%p|%포인트|p\b|포인트|bp|만큼)')
_NUM = re.compile(r'[+−-]?\d[\d,]*(?:\.\d+)?')


def _forms(value):
    out = set(number_forms(value))
    try:
        f = float(value)
    except (TypeError, ValueError):
        return out
    if f == int(f) and abs(f) >= 1000:
        out |= {f'{int(f):,}', f'{abs(int(f)):,}'}
    return {x for x in out if x}


def _names(comp):
    """Longest first — 「6개월 뒤 전망」 must be taken out before 「6개월 뒤」, or the
    leftover 「전망」 reads as a forecast (a set's order changes with the hash seed)."""
    names = {n for n in (comp.get('label'), *(comp.get('aliases') or ())) if n}
    return sorted(names, key=lambda n: (-len(n), n))


def _find_names(clause, comps):
    """-> [(start, end, comp index)] with overlaps resolved toward the longer name."""
    hits = []
    for i, c in enumerate(comps):
        for n in _names(c):
            for m in re.finditer(re.escape(n), clause):
                hits.append((m.start(), m.end(), i))
    hits.sort(key=lambda h: (-(h[1] - h[0]), h[0]))
    kept = []
    for h in hits:
        if not any(h[0] < k[1] and k[0] < h[1] for k in kept):
            kept.append(h)
    return sorted(kept)


def _current_numbers(clause):
    """Number tokens in the clause that can be a current value -> [(start, end, text)]."""
    out, last = [], 0
    for m in _NUM.finditer(clause):
        before, after = clause[:m.start()], clause[m.end():]
        lead = clause[last:m.start()]
        last = m.end()
        if AFTER_FROM.match(after) or AFTER_CHANGE.match(after):
            continue
        if PREV_BEFORE_VALUE.search(before[-8:]) or PREV_CONTEXT.search(lead):
            continue
        out.append((m.start(), m.end(), m.group(0)))
    return out


def _sign_ok(clause, comp, start, end, tok):
    """The printed figure must carry the confirmed figure's sign (codex 구현 1회 #3).

    A change (MoM %, a level difference) needs a matching explicit sign or a matching
    direction word in the clause; a level needs an explicit minus (or 마이너스) exactly when
    it is negative."""
    try:
        actual = float(comp.get('actual'))
    except (TypeError, ValueError):
        return False
    explicit = tok[0] if tok[0] in '+-−' else None
    negative_word = '마이너스' in clause[max(0, start - 6):start]
    if (comp.get('transform') or 'level') == 'level':
        printed_negative = explicit in ('-', '−') or negative_word
        return printed_negative == (actual < 0)
    if actual == 0:
        return explicit is None
    up, down = bool(UP_WORDS.search(clause)), bool(DOWN_WORDS.search(clause))
    if explicit:
        if (explicit == '+') != (actual > 0):
            return False
        # 「+0.4% 하락」: the sign and the verb disagree — not evidence (codex 구현 2회).
        return not (up != down and up != (actual > 0))
    if up == down:
        return False                       # no direction, or both: cannot tell
    return up == (actual > 0)


_SCALE_WORDS = ('백만', '천', '만', '억')


def _unit_ok(clause, end, word):
    """The figure is followed by its unit word: 4.2 only as 「4.2만」 (codex 구현 2회).
    A bare form must not be followed by a scale word (「42,000만」 is not 42,000)."""
    rest = clause[end:].lstrip()
    if word:
        return rest.startswith(word)
    return not rest.startswith(_SCALE_WORDS)


def _value_in(clause, comp, numbers):
    pairs = comp.get('cite_forms') or [[v, ''] for v in
                                       (comp.get('cite_values') or [comp.get('actual')])]
    by_text = {}
    for v, word in pairs:
        if v is None:
            continue
        for f in _forms(v):
            by_text.setdefault(f, set()).add(word or '')
    for start, end, tok in numbers:
        bare = tok.lstrip('+−-')
        words = by_text.get(bare) or by_text.get(tok.replace('−', '-'))
        if not words or not any(_unit_ok(clause, end, w) for w in words):
            continue
        if comp.get('unit') == '%' and not re.match(r'\s*%(?!p|포인트)', clause[end:]):
            continue
        if not _sign_ok(clause, comp, start, end, tok):
            continue
        return True
    return False


def headline_terms(rel, labels_ko=None):
    """Names and figures of the headline itself — what a component clause must not lean on."""
    names = {rel.get('label') or ''}
    figs = set()
    for ind in rel.get('indicators') or []:
        names.add((labels_ko or {}).get(ind.get('name'), ind.get('name') or ''))
        for k in ('actual', 'previous'):
            if ind.get(k) is not None:
                figs |= _forms(round(float(ind[k]), 1))
                figs |= _forms(ind[k])
    names |= {re.sub(r'\(.*?\)', '', n).strip() for n in list(names)}
    return {n for n in names if len(n) >= 2}, figs


def evidenced(text, rel, labels_ko=None):
    """-> [component labels] evidenced in the block, each at most once."""
    comps = rel.get('components') or []
    if not comps:
        return []
    head_names, head_figs = headline_terms(rel, labels_ko)
    got = []
    for sentence in _SENT.split(text or ''):
        bare = sentence
        for n in sorted({n for c in comps for n in _names(c)}, key=lambda n: (-len(n), n)):
            bare = bare.replace(n, ' ')
        if FORECAST.search(bare):
            continue
        for clause in _CLAUSE.split(sentence):
            names = _find_names(clause, comps)
            if len({i for _, _, i in names}) != 1:
                continue
            start, _, idx = names[0]
            if PREV_BEFORE_NAME.search(clause[:start]):
                continue
            comp = comps[idx]
            if comp['label'] in got:
                continue
            numbers = _current_numbers(clause)
            if not _value_in(clause, comp, numbers):
                continue
            shown = _forms(comp.get('actual'))
            if shown & head_figs and any(n in clause for n in head_names):
                continue
            got.append(comp['label'])
    return got


MIN_EVIDENCED = 2
MIN_FIGURES = 3


def check_block(key, label, text, rel, figures, structured, cited_distinct, labels_ko=None):
    """-> [violations] for one block by its anatomy status. `figures` counts distinct
    figures in the block, `structured` the canonical figures, `cited_distinct(text, values)`
    how many of them are printed."""
    status = rel.get('anatomy_status')
    comps = rel.get('components') or []
    v = []
    shown = ', '.join(f"{c['label']} {c['actual']}{'%' if c.get('unit') == '%' else ''}"
                      for c in comps[:6])
    hint = ('항목 이름과 이번 회차 숫자를 한 구절에 쓸 것(예: 「주거비는 0.4% 올랐다」 — 전월 값·'
            '변화폭·전망은 근거가 아니다)')
    if status == 'complete':
        got = evidenced(text, rel, labels_ko)
        if len(got) < MIN_EVIDENCED:
            v.append(f'§9 {key}: 「{label}」 블록이 구성 항목을 {len(got)}개만 근거로 들었다 — '
                     f'{MIN_EVIDENCED}개 이상 필요. {hint}. 쓸 수 있는 것: {shown}')
    elif status == 'partial':
        got = evidenced(text, rel, labels_ko)
        if not got:
            v.append(f'§9 {key}: 「{label}」 블록에 확인된 구성 항목({shown})이 근거로 없다 — {hint}')
        elif figures < MIN_FIGURES:
            v.append(f'§9 {key}: 「{label}」 블록이 수치 {figures}개에서 멈췄다 — '
                     f'{MIN_FIGURES}개 이상으로 분해할 것')
    elif status == 'text':
        if figures < MIN_FIGURES:
            v.append(f'§9 {key}: 「{label}」 블록이 수치 {figures}개에서 멈췄다 — 원문 발표문에서 '
                     f'무엇이 그 숫자를 만들었는지 {MIN_FIGURES}개 이상으로 분해할 것')
    elif status == 'none':
        need = min(MIN_FIGURES, len(structured))
        got = cited_distinct(text, structured)
        if got < need:
            have = ', '.join(str(x) for x in structured)
            v.append(f'§9 {key}: 「{label}」 원문·구성 확인이 없는 날이라 구조 수치({have}) 중 '
                     f'{need}개를 써야 하는데 {got}개만 있다')
    return v
