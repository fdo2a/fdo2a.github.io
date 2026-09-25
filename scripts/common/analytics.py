"""Visit counter — the GoatCounter loader every visitor page carries.

GitHub Pages serves static files and keeps no access log we can read, so page views are
counted by a third-party beacon. GoatCounter: no cookies, ~3.5 KB, dashboard at
https://fdo2a.goatcounter.com. The script itself skips localhost and file:// pages, so
local Playwright/PDF renders do not count.

One rule places it: **immediately before the first `</head>`**. The three early posts
that have no `<head>` wrapper get it right after their AdSense loader. Generators that
write the head themselves (`post_shell`, `build_thesis_pages`) put `SNIPPET` in that same
spot, so `inject()` of their output is a no-op — and the review gate can tell a backfill
from an edit by replaying `inject()` on the reviewed version (`review.prose.typography`).

Design: docs/superpowers/specs/2026-09-25-visit-counter.md
"""

import re

CODE = 'fdo2a'
MARKER = '<!-- goatcounter -->'
SNIPPET = (f'{MARKER}<script data-goatcounter="https://{CODE}.goatcounter.com/count" '
           'async src="https://gc.zgo.at/count.js"></script>')

_HEAD_CLOSE = re.compile(r'</head\s*>', re.I)
_ADSENSE = re.compile(r'<!-- adsense-loader -->\s*<script\b[^>]*>\s*</script>', re.I)

# Directories that hold fragments, fixtures, tooling or ledgers — not pages a visitor opens.
_NOT_PAGES = ('data', 'scripts', 'docs', 'assets', 'reviews', 'research', 'notes',
              '_workspace', 'node_modules', '.claude', '.github')


def is_page(rel):
    """True for a repo-relative path that a visitor can open."""
    parts = rel.split('/')
    return rel.endswith('.html') and not any(p in _NOT_PAGES for p in parts[:-1])


def inject(html):
    """`html` with the loader in place. Unchanged if it is already there or there is no
    anchor (a fragment) — callers that must have it check `MARKER in html`."""
    if MARKER in html:
        return html
    m = _HEAD_CLOSE.search(html)
    if m:
        return html[:m.start()] + SNIPPET + '\n' + html[m.start():]
    m = _ADSENSE.search(html)
    if m:
        return html[:m.end()] + '\n' + SNIPPET + html[m.end():]
    return html
