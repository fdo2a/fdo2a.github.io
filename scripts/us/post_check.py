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

_TAG = re.compile(r'<[^>]+>')
_SCRIPT = re.compile(r'<(script|style)\b.*?</\1>', re.S | re.I)
_ENTITY = {'&amp;': '&', '&lt;': '<', '&gt;': '>', '&nbsp;': ' ', '&quot;': '"'}

# A figure (with optional sign, separators, percent) or a short all-caps ticker.
_TOKEN = re.compile(r'[-+]?\d[\d,\.]*%?|\b[A-Z]{2,5}\b')

BANNED = ('[확인필요]', '[확인 필요]', 'TODO', 'TBD')


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
