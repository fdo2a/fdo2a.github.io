#!/usr/bin/env python3
r"""Publication gate for the reader's route back to the primary document.

The brief already reads the primary documents — Actions fetches each release and
each Fed transcript and commits the text, and the writer is required to dissect
it. What never reached the page was the *pointer*: measured on
`posts/2026-09-11.html`, the body carried zero external links a reader could
follow, while the workspace held 20,400 characters of the BLS CPI release. The
report read the source and kept it.

So this gate enforced one binding: the block that makes the claim carries the link
to the document it was read from, and no other link gets in.

**The requirement half was withdrawn on 2026-09-14** — the user's direction changed:
「링크 본문으로 들어가는 걸 추가하기보다 그냥 레포트 자체에서 모든 걸 해결할 수 있도록
해줘」. Attribution now belongs in the sentence («BLS 는 … 밝혔습니다»), not in a
footnote a reader has to leave the page for. What remains is the prohibition: the
report is not *required* to link, but a link it does print must be a document we
actually fetched, and must sit in the block it is evidence for. An invented link is
an invented quote.

Why a URL allow-list would not do (codex design review, 2026-09-14). Checking
that a URL appears *somewhere* in the collected files passes all four of the
failures worth catching:

  * `fetch_releases.py` records failed attempts too (`ok:false`). A document we
    could not read is not a source — publishing its URL says we checked when we
    did not.
  * `research_notes.md` is a working memo that also writes 「use nothing from
    this row」 next to a URL. Membership in that file is not permission.
  * A link authorised for one release, pasted next to a different claim, is a
    citation that does not support the sentence it sits beside.
  * A link in a `display:none` div satisfies a text search and nobody else.

The failure being prevented is a link that lies, never a page with too few links.

**Where the reader's eye and the parser part company is where this gate gets
bypassed**, so the second codex pass (implementation, 2026-09-14) is written into
the reader itself. Each of these was demonstrated passing before it was closed:

  * `opacity:0`, `font-size:0`, a `display:none` **class** declared in `<style>` —
    hidden to the reader, visible to a naive parser.
  * a nested `<a>`; an `<a>` never closed; `<a href="evil" href="ok">` (HTML keeps
    the **first** duplicate attribute, `dict(attrs)` keeps the last).
  * `href="https:\\host\path"` — WHATWG reads a host, `urlsplit` reads a relative
    path and waves it through.
  * a marker block nested inside another, so the wrong claim borrows the right
    block's authorisation.

Scope skips navigation chrome (`nav`/`header`/`footer`/`aside`) rather than
counting `<main>`: a self-closing `<main/>` is one tag to a counter and nothing to
a browser, and that alone excluded every body link from checking.
"""

import re
from html.parser import HTMLParser
from urllib.parse import urlsplit

from .price_gate import _INERT_TAGS, _VOID_TAGS

# Where the published site lives. Links here are navigation, not evidence.
SITE_HOSTS = ('fdo2a.github.io',)

# Blocks that may carry a document link. The first is the release anatomy (§9),
# the other two the Fed event section (§10).
RELEASE_MARKER = 'data-release'
FED_EVENT_MARKER = 'data-fed-event'
FED_QUOTE_MARKER = 'data-fed-quote'
MARKERS = (RELEASE_MARKER, FED_EVENT_MARKER, FED_QUOTE_MARKER)

# Chrome, not evidence. Skipped wherever it sits in the document.
CHROME_TAGS = {'nav', 'header', 'footer', 'aside'}

SAFE_SCHEMES = ('http', 'https')
_NON_SOURCE_SCHEMES = ('mailto', 'tel', 'sms')

def _first_attrs(attrs):
    """HTML keeps the FIRST of duplicate attributes; `dict()` keeps the last.

    `<a href="https://evil/x" href="<authorised>">` is one link to a browser and
    a different one to `dict(attrs)` — the gate would approve a URL the reader
    never visits.
    """
    got = {}
    for name, value in attrs:
        got.setdefault(name, value)
    return got


def _norm(url):
    """Compare URLs the way two humans would, and no further.

    Scheme and host are case-insensitive; path, query and fragment are not, and
    stripping them would let two different documents on one host answer for each
    other. The writer copies the URL out of the index, so exact is affordable.

    Backslashes are folded to `/` first: WHATWG reads `https:\\\\host\\path` as a
    host, and Python reads it as a relative path with no host at all.
    """
    parts = urlsplit((url or '').strip().replace('\\', '/'))
    return parts._replace(scheme=parts.scheme.lower(),
                          netloc=parts.netloc.lower()).geturl()


class _Anchors(HTMLParser):
    """Every rendered `<a href>` outside navigation chrome, tagged with its block.

    Same reasoning as `price_gate._Reader`: a regex reads nesting, attribute
    values, tag-name prefixes and entities wrong, and each of those is a way for
    what the gate reads to drift from what the reader sees.

    **A link styled invisible is still checked.** The gate used to skip anything
    it judged hidden, because a hidden anchor must not satisfy a link *requirement*.
    That requirement is gone (2026-09-14), and the leftover turned the judgement
    around: a CSS heuristic that says 「hidden」 now says 「do not look」. Measured
    the same day — `@media (max-width:600px){.src{display:none}}` and a later rule
    that re-shows the class both put an unauthorised link past the gate, and
    `opacity:0.09` did too. No CSS engine here can be right about what renders, so
    the gate stops guessing: it reads every anchor and lets an invisible one cost
    a violation the writer can see. Only `script`/`style`/`template` stay out —
    those are not the document.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.anchors = []          # [(href, text, owner)] — owner: (marker, key) | None
        self._open = []            # [(tag, inert, chrome, key)]
        self._inert = 0
        self._chrome = 0
        self._a = None             # (href, [chunks], owner)

    def _owner(self):
        """The innermost marked block. A claim belongs to the block it is in, not
        to any ancestor that happens to be authorised for something else."""
        for _tag, _h, _c, key in reversed(self._open):
            if key:
                return key
        return None

    # -- parsing ------------------------------------------------------------

    def _flush(self):
        if self._a is None:
            return
        href, chunks, owner = self._a
        self._a = None
        self.anchors.append((href, ''.join(chunks).strip(), owner))

    def handle_starttag(self, tag, attrs):
        if tag in _VOID_TAGS:
            return
        got = _first_attrs(attrs)
        inert = tag in _INERT_TAGS
        chrome = tag in CHROME_TAGS
        key = None
        if not inert and not self._inert:
            for marker in MARKERS:
                value = (got.get(marker) or '').strip()
                if value:
                    key = (marker, value)
                    break
        self._open.append((tag, inert, chrome, key))
        if inert:
            self._inert += 1
        if chrome:
            self._chrome += 1
        if tag == 'a' and (got.get('href') or '').strip():
            # A nested <a> closes the one above it, the way HTML5 does.
            self._flush()
            if not self._inert and not self._chrome:
                self._a = (got['href'].strip(), [], self._owner())

    def handle_startendtag(self, tag, attrs):
        # `<main/>`, `<div/>` and friends are not self-closing in HTML; treating
        # them as a start and an immediate end let one stray slash take every
        # body link out of scope. Only void elements really close themselves.
        if tag in _VOID_TAGS:
            return
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag == 'a':
            self._flush()
        # An unmatched close tag closes back to the nearest element of that name
        # and no further — emptying the stack here deletes the rest of the page.
        for i in range(len(self._open) - 1, -1, -1):
            if self._open[i][0] == tag:
                for _t, h, c, _k in self._open[i:]:
                    if h:
                        self._inert -= 1
                    if c:
                        self._chrome -= 1
                del self._open[i:]
                return

    def handle_data(self, data):
        if self._inert or self._a is None:
            return
        self._a[1].append(data)

    def close(self):
        super().close()
        self._flush()   # an <a> never closed is still a link on the page


def _authorised(releases, fed):
    """-> ({(marker, key): {url}}, {(marker, key): True}).

    A key we tried and failed to fetch is *known* but authorises nothing: the
    page may not link it, and is not asked to.
    """
    urls, known = {}, {}
    for row in ((releases or {}).get('releases') or []):
        key = (row or {}).get('key')
        if not key:
            continue
        slot = (RELEASE_MARKER, key)
        known[slot] = True
        if row.get('ok') and row.get('url'):
            urls.setdefault(slot, set()).add(_norm(row['url']))
    for event in ((fed or {}).get('events') or []):
        key = (event or {}).get('key')
        if not key:
            continue
        # ponytail: one event's documents share a URL set, so a post that quotes
        # the statement and the press conference satisfies both with one link.
        # Per-document binding needs a `data-fed-source` marker in the writer
        # contract — spec 2026-09-14-report-source-provenance-design.md.
        good = {_norm(s['url']) for s in (event.get('sources') or [])
                if s.get('ok') and s.get('url')}
        for marker in (FED_EVENT_MARKER, FED_QUOTE_MARKER):
            known[(marker, key)] = True
            if good:
                urls[(marker, key)] = set(good)
    return urls, known


def check(html, releases=None, fed=None, site_hosts=SITE_HOSTS):
    """-> list of violations, empty when the page is publishable.

    An absent index authorises nothing; it does not switch the gate off. The
    distinction mattered while the gate also *required* a link — you cannot demand
    a citation for a document nobody fetched. With the requirement withdrawn
    (2026-09-14) the exception outlived its reason and turned into the widest hole
    in the gate: on the very day collection failed, every invented link shipped.
    """
    urls, known = _authorised(releases, fed)
    reader = _Anchors()
    reader.feed(html or '')
    reader.close()

    violations = []
    for href, text, owner in reader.anchors:
        scheme = urlsplit(href.replace('\\', '/')).scheme.lower()
        if scheme in _NON_SOURCE_SCHEMES or href.startswith('#'):
            continue
        if scheme and scheme not in SAFE_SCHEMES:
            violations.append(
                f'본문 링크의 스킴이 {scheme}: 이다 — 출처 링크는 http(s) 만 쓴다 ({href})')
            continue
        parts = urlsplit(href.strip().replace('\\', '/'))
        if not parts.netloc:
            if scheme:
                # A scheme with no host is not a relative path, whatever urlsplit says.
                violations.append(f'호스트 없는 외부 링크: {href}')
            continue        # relative navigation inside the site
        if '@' in parts.netloc:
            violations.append(f'본문 링크에 사용자 정보가 들어 있다 — 출처 링크로 쓸 수 없다 ({href})')
            continue
        if parts.netloc.lower().split(':')[0] in site_hosts:
            continue
        if not text:
            violations.append(f'글자 없는 외부 링크가 본문에 있다 — 독자가 볼 수 없다 ({href})')
            continue

        target = _norm(href)
        if owner and target in urls.get(owner, ()):
            continue
        if owner is None:
            violations.append(
                f'표식 없는 외부 링크: {href} — 출처 링크는 그 근거를 쓴 '
                f'data-release / data-fed-quote 블록 «안»에 둔다')
            continue
        marker, key = owner
        where = f'{marker}="{key}"'
        elsewhere = sorted(k for k, got in urls.items() if target in got)
        if elsewhere:
            other = ' · '.join(f'{m}="{k}"' for m, k in elsewhere)
            violations.append(
                f'{where} 블록에 다른 문서({other})의 링크가 붙어 있다: {href} — '
                f'링크는 그 문장의 근거여야 한다')
        elif known.get(owner) and not urls.get(owner):
            violations.append(
                f'{where} 블록이 원문 수집에 실패한 문서를 링크했다: {href} — '
                f'읽지 못한 문서는 출처가 아니다(index 의 ok:false)')
        else:
            violations.append(
                f'{where} 블록의 링크가 수집한 원문 목록에 없다: {href} — '
                f'URL 은 index 에서 그대로 복사한다')

    return violations
