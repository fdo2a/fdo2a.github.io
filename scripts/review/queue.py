"""Which published pages still have not been read by a second pair of eyes.

The cloud routines publish on their own schedule and codex only exists on this laptop,
so review happens *after* publication. A rule that says "remember to review yesterday's
brief" is a rule that gets skipped on a busy morning — the same failure mode §8's macro
logic and the multi-asset stance were both rebuilt to avoid. So the queue is state, not
memory.

Two decisions carry the design.

**Content addressing.** An entry records the blob SHA of the page as reviewed, which
gives us the property that matters most for free: a page someone edits by hand after the
fact stops matching its record and returns to the queue. No dates, no sequence numbers,
no flag anyone has to remember to clear.

**Failure-safe watching.** Every .html that is not demonstrably machine-written or
navigation counts as prose under the gate. A closed allowlist of known directories would
have let /weekly/, /monthly/ and /comment/ — already designed, not yet built — publish
without review, and nobody would have noticed the silence. A page escaping review is the
expensive failure; one extra page in the queue is not.

Pure — no git, no clock, no filesystem. The tree and the timestamp are passed in.

Design: docs/superpowers/specs/2026-08-24-post-publish-review-gate-design.md
"""

import re
from dataclasses import dataclass

# Directories holding generated fragments and test fixtures. Nothing here is an argument
# a reviewer could disagree with.
_EXCLUDED_DIRS = ('data', 'scripts', 'node_modules', 'assets', '_workspace')

# Navigation, not prose.
_EXCLUDED_NAMES = ('index.html', '404.html')

# Pages nobody types. /thesis/ is rendered every day by build_thesis_pages.py — prose out
# of content.py, figures out of a committed watch.json — so the page changes whenever a
# price does. Reviewing the page would put four entries in the queue every weekday and
# bury the one thing worth a second read. What a person actually writes is the source
# below, and that is what the gate follows instead. A page edited by hand is caught by a
# different check: the collector re-renders and compares (build_thesis_pages.py --check).
_RENDERED_DIRS = ('thesis',)

# Authored prose that never becomes a page of its own — the sentences a person wrote
# that end up in front of a reader. thesis_state.json is here because its changelog is
# written by hand on the days a judgment changes, which is exactly when a second read is
# worth the most.
_PROSE_SOURCES = (
    'scripts/thesis/content.py',
    'scripts/thesis/narrative.py',
    'scripts/thesis/render.py',
    'thesis/data/thesis_state.json',
)

_DATE = re.compile(r'(\d{4}-\d{2}(?:-\d{2})?)')

# Sorts after any dated page in the same month, and after every day of it, so an undated
# page (a thesis page that just changed) leads the queue.
_UNDATED = '9999-99-99'


@dataclass(frozen=True)
class Pending:
    path: str
    section: str
    sha: str
    reason: str  # '신규' | '수정됨'


def is_watched(path):
    """True for prose the gate covers — published pages, and the sources pages are
    rendered from."""
    if path in _PROSE_SOURCES:
        return True
    if not path.endswith('.html'):
        return False
    parts = path.split('/')
    if parts[-1] in _EXCLUDED_NAMES:
        return False
    if parts[0] in _RENDERED_DIRS:
        return False
    return not any(part in _EXCLUDED_DIRS for part in parts[:-1])


# The two daily briefs predate the gate and have names people use out loud; everything
# else is called by its directory, which is what a new pipeline will have anyway.
_SECTION_ALIASES = {'posts': 'us', 'kr/posts': 'kr', 'scripts/thesis': 'thesis 원고'}


def section_of(path):
    """Where the page lives, for reading the queue at a glance."""
    head = path.rsplit('/', 1)[0] if '/' in path else ''
    if not head:
        return '사이트'
    return _SECTION_ALIASES.get(head, head)


def watched(tree):
    """Sorted paths in `tree` (path -> blob sha) that the gate covers."""
    return sorted(p for p in tree if is_watched(p))


def _sort_key(path):
    """Newest first. A backlog is worth less than today: readers are on this morning's
    brief right now, and last week's post has already done whatever damage a wrong figure
    was going to do. Sorting by path spelling would rank posts/ above kr/posts/ on the
    letter 'p', which has nothing to do with recency."""
    found = _DATE.search(path.rsplit('/', 1)[-1])
    date = found.group(1) if found else _UNDATED
    return (date if len(date) == 10 else date + '-99', path)


def _reviewed_sha(ledger, path):
    """The SHA recorded for `path`, or None if there is no usable record.

    A damaged entry has to read as unreviewed. Raising here would take down a
    session-start hook and silence the gate, which is the one outcome we cannot have.
    """
    reviewed = ledger.get('reviewed') if isinstance(ledger, dict) else None
    if not isinstance(reviewed, dict):
        return None
    entry = reviewed.get(path)
    if not isinstance(entry, dict):
        return None
    sha = entry.get('sha')
    return sha if isinstance(sha, str) else None


def pending(ledger, tree):
    """Pages in `tree` needing review, newest first."""
    out = []
    for path in sorted(watched(tree), key=_sort_key, reverse=True):
        was = _reviewed_sha(ledger, path)
        if was is None:
            out.append(Pending(path, section_of(path), tree[path], '신규'))
        elif was != tree[path]:
            out.append(Pending(path, section_of(path), tree[path], '수정됨'))
    return out


def union_pending(*groups):
    """One queue out of several views of the same repo, each path once.

    The caller asks separately about what origin publishes and what the working tree
    holds, because either can carry a version the ledger has never seen. A laptop that
    is a few days behind still has the reviewed copy of a post the routine has since
    republished — overlaying one view onto the other would erase exactly that.

    같은 경로라도 **판이 다르면 둘 다 남긴다.** 경로로만 묶으면 원장이 모르는 두 판 중
    하나가 목록에서 사라지고, 사라진 쪽은 아무도 읽지 않은 채로 공개돼 있던 판일 수 있다.
    한 줄이 두 번 뜨는 것이 그 사실을 감추는 것보다 낫다.
    """
    seen, out = set(), []
    for group in groups:
        for item in group:
            key = (item.path, item.sha)
            if key in seen:
                continue
            seen.add(key)
            out.append(item)
    return sorted(out, key=lambda p: (_sort_key(p.path), p.sha), reverse=True)


def seed(tree, at):
    """A ledger that accepts everything currently published as already seen.

    Introducing the gate should not dump fifty past posts into the queue; the point is
    to catch what ships from here on. `baseline: True` keeps that honest — these entries
    record that nobody actually read the page.
    """
    return {'reviewed': {
        path: {'sha': tree[path], 'at': at, 'findings': 0, 'baseline': True}
        for path in watched(tree)
    }}


def mark(ledger, path, sha, at, findings=0):
    """Ledger with `path` recorded as reviewed at `sha`. Returns a new dict."""
    if not is_watched(path):
        raise ValueError(f'감시 대상이 아닌 경로다: {path}')
    reviewed = ledger.get('reviewed') if isinstance(ledger, dict) else None
    reviewed = dict(reviewed) if isinstance(reviewed, dict) else {}
    reviewed[path] = {'sha': sha, 'at': at, 'findings': findings}
    base = ledger if isinstance(ledger, dict) else {}
    return {**base, 'reviewed': reviewed}
