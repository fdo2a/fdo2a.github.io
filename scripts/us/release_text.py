"""Turn a statistical agency's press release into text an analyst can read.

The dashboard's numbers come from FRED, but FRED redistributes series — not prose.
The things that make a print *interpretable* live only in the release itself: which
line item accounted for how much of the move ("shelter … roughly two-thirds of the
monthly all items increase"), what got revised, which one-off distorted the month.
No component series reproduces that.

So the collector fetches the release and this module flattens it to text. Deliberately
dumb — no per-agency parsing, no number extraction. Agencies restructure their pages
and a brittle parser would silently start returning nothing; a text dump degrades to
"slightly messier text". The reading is the agent's job.
"""

import html as _html
import re

TRUNCATED = '…[이하 생략]'

_DROP = re.compile(r'<(script|style|noscript|svg|head)\b.*?</\1>', re.S | re.I)
_ROW_END = re.compile(
    r'</(tr|p|div|h[1-6]|li|ul|ol|table|tbody|thead|nav|header|footer|section|article)\s*>',
    re.I)
_BR = re.compile(r'<br\s*/?>', re.I)
_CELL = re.compile(r'</(td|th)\s*>', re.I)
_TAG = re.compile(r'<[^>]+>')
_SPACES = re.compile(r'[ \t ]+')
_BLANKS = re.compile(r'\n{3,}')

# Releases open with boilerplate navigation. Anchor on the first line that reads like
# the release's own lede rather than on any one agency's markup.
_LEDE = re.compile(
    r'^.{0,200}?\b(?:index|payroll|sales|income|product|claims|openings|orders)\b.{0,200}?'
    r'\b(?:increased|decreased|rose|fell|declined|changed|was|were|edged)\b',
    re.I)

DEFAULT_MAX_CHARS = 40000


def to_text(raw, max_chars=DEFAULT_MAX_CHARS):
    """Release HTML -> flat text, one logical row per line."""
    if not raw:
        return ''
    s = _DROP.sub(' ', raw)
    s = _BR.sub('\n', s)
    s = _CELL.sub(' \t', s)          # keep cells apart before tags vanish
    s = _ROW_END.sub('\n', s)
    s = _TAG.sub(' ', s)
    s = _html.unescape(s)
    s = _SPACES.sub(' ', s)
    s = '\n'.join(line.strip() for line in s.splitlines())
    s = _BLANKS.sub('\n\n', s).strip()

    for line in s.splitlines():
        if _LEDE.match(line.strip()):
            s = s[s.index(line):].strip()
            break

    if len(s) > max_chars:
        s = s[:max_chars].rstrip() + '\n' + TRUNCATED
    return s
