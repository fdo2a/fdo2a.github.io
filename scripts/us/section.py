#!/usr/bin/env python3
"""발행본에서 섹션 구간을 잘라내는 공용 헬퍼.

2026-09-19 분리. 이 셋은 원래 `stance_gate.py` 에 살았는데 `macro_gate`·`session_gate`
가 거기서 꺼내 쓰고 있었다 — 스탠스와 아무 상관이 없는데도. 같은 날 스탠스 섹션 삭제가
결정되면서(`plan.md` 2026-09-19 A) 얹혀 있을 곳이 사라졌고, 새 뉴스 게이트도 같은 것이
필요하다. 게이트가 늘어날 때마다 구간 자르기를 다시 짜면 **자르는 규칙이 게이트마다
갈라지고, 갈라진 자리가 그대로 우회로가 된다** — 그래서 정본을 하나 둔다.
"""

import re

from common.numbers import TAG_RE

from .weight import _text as _norm_title

_H_ANY = re.compile(r'(?is)<h[1-4]\b[^>]*>(.*?)</h[1-4]\s*>')


def locate_section(html, keyword, exact=False):
    """The <section> whose heading names `keyword`, or None.

    Headings first, body text only as a fallback: the macro section reconciles itself
    against another section by name, so the word legitimately appears in prose
    upstream of the section it labels.

    `exact=True` demands the whole heading text and drops the body fallback. Use it
    where the title **is** the contract — a substring match kept letting the retired
    「매크로 논리」 heading through (2026-09-12 codex implementation review).
    """
    if exact:
        heads = [m.start() for m in _H_ANY.finditer(html)
                 if _norm_title(m.group(1)) == keyword]
        i = heads[0] if heads else -1
    else:
        heads = [m.start() for m in re.finditer(r'<h[1-4]\b[^>]*>(?:(?!</h[1-4]>).)*?'
                                                + re.escape(keyword), html, re.S)]
        i = heads[0] if heads else html.find(keyword)
    if i < 0:
        return None
    start = html.rfind('<section', 0, i)
    start = start if start >= 0 else i
    return html[start:_section_end(html, start, i)]


# **태그 경계는 `TAG_RE` 로 센다** — 순진한 패턴은 속성값 안의 `</section>` 을 닫는
# 태그로 세어 구간을 잘랐다(2026-09-19 codex 2차 검토 #1).
_SECTION_TAG = re.compile(r'^</?section\b', re.I)


def _section_end(html, start, marker):
    """구간의 끝. **닫는 태그를 센다** — 다음 `<section` 에서 자르던 판은 닫힌 섹션
    뒤에 붙은 블록까지 안쪽으로 읽었다(2026-09-19 codex 검토 #16).

    닫는 태그가 모자라면(조판이 깨진 날) 예전처럼 다음 `<section` 에서 자른다 —
    구간이 문서 끝까지 번지면 게이트가 다른 섹션의 내용을 이 섹션 것으로 본다.
    """
    depth = 0
    for m in TAG_RE.finditer(html, start):
        if not _SECTION_TAG.match(m.group(0)):
            continue
        if m.group(0)[1] == '/':
            depth -= 1
            if depth <= 0:
                return m.end()          # TAG_RE 매치는 `>` 까지 포함한다
        else:
            depth += 1
    nxt = html.find('<section', marker)
    return nxt if nxt > 0 else len(html)


def strip_tags(html):
    return re.sub(r'\s+', ' ', TAG_RE.sub(' ', html))


def number_forms(value):
    """String spellings of a metric value a writer might reasonably use."""
    if value is None:
        return []
    forms = {f'{value}', f'{value:.1f}', f'{value:.2f}', f'{abs(value)}',
             f'{abs(value):.1f}', f'{abs(value):.2f}'}
    if float(value) == int(value):
        forms.add(str(int(value)))
        forms.add(str(abs(int(value))))
    return [f for f in forms if f]
