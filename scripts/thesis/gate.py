"""Publish gate: what the routine is not allowed to get away with.

Most of these mirror gates that already exist for the brief (controlled vocabulary,
unresolved markers, banned wording). One is specific to this pipeline and is the reason
it exists at all:

    **check_silence** — if nothing triggered, the page must not have been touched.

"Say nothing on a quiet day" cannot live in a prompt. An agent invoked every evening and
asked whether a thesis moved will, given enough evenings, decide that it did. So the day
a page changes without a trigger behind it, publishing fails.

Pure — operates on an HTML string and plain dicts, no filesystem, no git.

Design: docs/superpowers/specs/2026-08-24-thesis-watch-design.md
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from us.macro_gate import BANNED_LABELS          # noqa: E402  「buy-side」 금지
from us.post_check import BANNED as BANNED_MARKERS  # noqa: E402  [확인필요]·TODO·TBD

from .state import GRADES, KILL_AXES             # noqa: E402

STANCES = ('Bullish', 'Bearish', 'Neutral')
REQUIRED_BLOCKS = ('changelog', 'thesis', 'valuation')
REQUIRED_PARTS = ('fact', 'inference', 'delta', 'next')

_ENTRY = re.compile(r'<li\b[^>]*\bdata-date="([^"]+)"[^>]*>(.*?)</li>', re.S)
_ATTR = re.compile(r'\bdata-(\w+)="([^"]*)"')


def _problem(check, message, where=None):
    return {'check': check, 'message': message, 'where': where}


def _attrs(tag_html):
    return dict(_ATTR.findall(tag_html))


def _entries(html):
    """(attrs, inner_html) for each changelog item."""
    out = []
    for match in _ENTRY.finditer(html):
        opening = html[match.start():match.start(2)]
        out.append((_attrs(opening), match.group(2)))
    return out


def check(html, state_grade, kill_evidence=()):
    """Everything wrong with this page, as a list. Empty means publishable."""
    problems = []

    article = re.search(r'<article\b[^>]*\bdata-ticker="[^"]*"[^>]*>', html)
    page_grade = _attrs(article.group(0)).get('grade') if article else None

    # ── 등급 통제 어휘 ──
    if page_grade not in GRADES:
        problems.append(_problem(
            'grade_vocabulary',
            f'등급이 통제 어휘 밖이다: {page_grade!r} (허용: {", ".join(GRADES)})'))

    # ── state ↔ 페이지 정합 ──
    if page_grade != state_grade:
        problems.append(_problem(
            'state_consistency',
            f'thesis_state.json 등급({state_grade!r})과 페이지 표시({page_grade!r})가 다르다'))

    # ── kill 은 두 축이 함께 깨질 때만 ──
    if state_grade == 'kill condition':
        missing = set(KILL_AXES) - set(kill_evidence)
        if missing:
            problems.append(_problem(
                'kill_axes',
                f'kill 등급인데 근거 축이 부족하다 — 없는 축: {", ".join(sorted(missing))}'))

    # ── 필수 블록 ──
    for block in REQUIRED_BLOCKS:
        if f'data-block="{block}"' not in html:
            problems.append(_problem('required_blocks', f'필수 블록 누락: {block}'))

    # ── 변경 이력 항목의 7요소 ──
    for attrs, inner in _entries(html):
        where = attrs.get('date', '?')
        if attrs.get('signal') == 'init':
            continue  # 최초 작성 항목은 사건이 아니므로 면제

        if attrs.get('signal') not in GRADES:
            problems.append(_problem(
                'entry_format',
                f'신호 등급이 통제 어휘 밖이다: {attrs.get("signal")!r}', where))
        if attrs.get('stance') not in STANCES:
            problems.append(_problem(
                'entry_format',
                f'Bullish/Bearish/Neutral 분류가 없거나 잘못됐다: '
                f'{attrs.get("stance")!r}', where))
        if not re.search(r'<h4\b[^>]*>\s*\S', inner):
            problems.append(_problem('entry_format', '이벤트 제목이 비어 있다', where))

        for part in REQUIRED_PARTS:
            block = re.search(rf'<div\b[^>]*\bdata-part="{part}"[^>]*>(.*?)</div>',
                              inner, re.S)
            if not block or not block.group(1).strip():
                problems.append(_problem('entry_format', f'항목 누락: data-part="{part}"', where))
            elif part == 'fact' and '<cite' not in block.group(1):
                problems.append(_problem(
                    'fact_sourcing',
                    '확정 사실에 출처(<cite>)가 없다 — 추론과 구분되지 않는다', where))

    # ── 금칙어 ──
    for marker in BANNED_MARKERS:
        if marker in html:
            problems.append(_problem('banned_markers', f'미완 마커가 남아 있다: {marker}'))
    lowered = html.lower()
    for label in BANNED_LABELS:
        if label.lower() in lowered:
            problems.append(_problem('banned_labels', f'금지 어휘: {label}'))

    return problems


def check_silence(triggers, events, page_changed):
    """The gate that makes a quiet day possible.

    An event only counts once it is confirmed against a primary source; an unconfirmed
    report is an inference, and inferences do not license an edit.
    """
    if not page_changed:
        return None
    if triggers:
        return None
    if any(e.get('confirmed') for e in events):
        return None
    return _problem(
        'silence',
        '트리거도 확정된 사건도 없는데 페이지가 수정됐다 — '
        '변화가 없는 날은 아무것도 건드리지 않는다')
