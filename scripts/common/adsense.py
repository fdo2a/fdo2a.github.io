"""Google AdSense loader — taken off the site on 2026-11-05 (user instruction: 「구글 애드센스같은
ads.txt같은건 없애」).

Every page used to carry one loader line in `<head>`, in four spellings: with or without the
`<!-- adsense-loader -->` marker (thesis pages had none), on one line or split after the marker,
and once re-serialised by an HTML parser as `async=""` with the attributes reordered. All of them
sat on a line of their own. `strip()` removes that line and nothing else.

The review gate replays `strip()` on a reviewed version (`review.prose.typography`) to tell this
removal from an edit, the same way it replays `common.analytics.inject()` for the visit counter.
So keep the pattern narrow: it must match the loader and never reader-visible text.
"""

import re

LOADER = re.compile(
    r'(?:<!-- adsense-loader -->[ \t]*\n?[ \t]*)?'
    r'<script\b[^>]*\bsrc="https://pagead2\.googlesyndication\.com/pagead/js/adsbygoogle\.js[^"]*"[^>]*>'
    r'\s*</script>[ \t]*\n?')


def present(html):
    return LOADER.search(html) is not None


def strip(html):
    """`html` without the loader line(s). Unchanged when there is none."""
    return LOADER.sub('', html)
