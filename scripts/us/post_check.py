"""Safety net for hand-editing a published brief.

The rule that matters when a human rewrites a sentence in a shipped report is that
**the numbers must not move** (CLAUDE.md 검증 방법 ②) — past edits flipped an FX
direction and an oil move while "just" polishing prose. So the check is a multiset
comparison of data tokens (figures, percentages, tickers) between two versions of the
same page: anything that appears or disappears is reported, everything else is prose
the editor is free to change.

Pure — takes HTML strings, returns findings.
"""

import re
from common.numbers import TAG_RE

# 주석·속성값 안의 `>` 까지 한 토큰으로 읽는다 — 정본은 common/numbers.py
# (2026-09-01 codex 검토: 필수 문구를 주석 안에 숨기면 검사를 비껴갔다).
_TAG = TAG_RE
_SCRIPT = re.compile(r'<(script|style)\b.*?</\1>', re.S | re.I)
_ENTITY = {'&amp;': '&', '&lt;': '<', '&gt;': '>', '&nbsp;': ' ', '&quot;': '"'}

# A figure (with optional sign, separators, percent) or a short all-caps ticker.
_TOKEN = re.compile(r'[-+]?\d[\d,\.]*%?|\b[A-Z]{2,5}\b')

BANNED = ('[확인필요]', '[확인 필요]', 'TODO', 'TBD')


# 날짜는 수치가 아니다. 가리지 않으면 「2026-08-18」에서 -18 이 음수로 뜯겨 나와
# 창작 수치의 허용 토큰이 되거나(주간 게이트), 없는 수치로 걸린다.
# \b 를 쓰지 않는다 — 한글도 단어문자라 「2026-08-17에」에서 경계가 서지 않는다.
# 「8/21」 꼴은 가리지 않는다 — 「적중은 3/4」 같은 비율까지 지워 창작을 통과시킨다.
_DATE = re.compile(r'(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)'
                   r'|(?<!\d)\d{4}년\s*\d{1,2}월\s*\d{1,2}일')


def mask_dates(text):
    return _DATE.sub(' ', text or '')


def body_text(html):
    """Visible text of the page — no markup, no script/style, entities resolved."""
    s = html[html.index('<body'):] if '<body' in html else html
    s = _SCRIPT.sub(' ', s)
    s = _TAG.sub(' ', s)
    for ent, ch in _ENTITY.items():
        s = s.replace(ent, ch)
    return re.sub(r'\s+', ' ', s)


def data_tokens(html):
    """Figure/ticker multiset. Sentence-final punctuation is not part of the number —
    「14.89.」 and 「14.89」 are the same figure in two positions, and flagging that
    would bury the one diff that matters."""
    counts = {}
    for tok in _TOKEN.findall(body_text(html)):
        tok = tok.rstrip('.,')
        if not tok:
            continue
        counts[tok] = counts.get(tok, 0) + 1
    return counts


_COMMENT = re.compile(r'<!--.*?-->', re.S)

# 게이트들이 이 표식으로 §8·§9를 읽는다. 윤문이 문장을 다시 쓰다 이것을 지우면 그
# 섹션은 검사받지 않은 채로 나간다.
_MARKER = re.compile(r'\b(data-(?:asset|grade|release|reconcile|source)="[^"]*")')


def tag_sequence(html):
    """Opening/closing tag names in order — the page's skeleton, without its words."""
    s = _COMMENT.sub(' ', _SCRIPT.sub(' ', html))
    return [m.group(1).lower()
            for m in re.finditer(r'<\s*(/?[a-zA-Z][a-zA-Z0-9]*)', s)]


def markers(html):
    """게이트가 읽는 data-* 표식의 멀티셋."""
    counts = {}
    for marker in _MARKER.findall(_COMMENT.sub(' ', _SCRIPT.sub(' ', html))):
        counts[marker] = counts.get(marker, 0) + 1
    return counts


def markup_diff(before, after):
    """Findings when the structure moved, not just the words inside it.

    A humanising pass rewrites sentences, and a rewrite that also drops a `</p>` or
    reorders a table turns a good edit into a broken page. Prose is free to change;
    the skeleton is not.
    """
    out = []
    was, now = markers(before), markers(after)
    for marker in sorted(set(was) | set(now)):
        if was.get(marker, 0) != now.get(marker, 0):
            out.append(f'표식이 달라졌다: {marker} '
                       f'{was.get(marker, 0)}개 → {now.get(marker, 0)}개')

    a, b = tag_sequence(before), tag_sequence(after)
    if a == b:
        return out
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            out.append(f'{i + 1}번째 태그가 <{x}>에서 <{y}>로 바뀌었다')
            break
    if len(a) != len(b):
        out.append(f'태그 수가 {len(a)}개에서 {len(b)}개로 바뀌었다')
    return out or ['태그 구조가 달라졌다']


def token_diff(before, after):
    """{'added': {...}, 'removed': {...}} — empty dicts mean the figures held."""
    a, b = data_tokens(before), data_tokens(after)
    added = {k: n - a.get(k, 0) for k, n in b.items() if n > a.get(k, 0)}
    removed = {k: n - b.get(k, 0) for k, n in a.items() if n > b.get(k, 0)}
    return {'added': added, 'removed': removed}


def banned_markers(html):
    """Placeholders that must never reach a published page."""
    text = body_text(html)
    return [m for m in BANNED if m in text]


def report(before, after):
    """Human-readable findings; empty list = the edit is safe on both counts."""
    out = []
    diff = token_diff(before, after) if before is not None else {'added': {}, 'removed': {}}
    for tok, n in sorted(diff['removed'].items()):
        out.append(f'수치가 사라졌다: {tok} ×{n}')
    for tok, n in sorted(diff['added'].items()):
        out.append(f'수치가 생겼다: {tok} ×{n}')
    for marker in banned_markers(after):
        out.append(f'발행 금지 표기: {marker}')
    return out
