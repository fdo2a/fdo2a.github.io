#!/usr/bin/env python3
"""「다음 발표 일정」이 수집한 것과 어긋나지 않는가.

이 카드는 오래 **에이전트 웹서치 산문**이었다 — 전일 값이 없고, 어떤 게이트도 읽지
않았다(`macro_gate.py` 전수 grep 0건). 그래서 있으면 있고 없으면 없었고, 틀려도
아무도 몰랐다. `data/calendar.json` 이 생긴 뒤로는 대조할 대상이 있다.

**금지형이다.** 카드를 채우라고 요구하지 않는다 — 수집이 실패한 날 요구하면 그날
작성자는 지어내는 수밖에 없다. 막는 것은 셋이다:

  ① 수집한 적 없는 일정을 표식과 함께 인쇄하는 것
  ② 표식이 가리키는 일정과 **다른 날짜**를 적는 것
  ③ 시각을 **모르는** 일정에 시각을 적는 것

셋 다 「지어낸 일정」의 모양이고, 지어낸 일정은 독자를 틀린 시각에 깨운다.

ponytail: 시각 대조는 `HH:MM` 꼴만 읽는다. 「오전 3시」처럼 한글로 쓴 시각은 통과한다 —
표기가 여럿이라 정규식으로 다 잡으려다 정상 문장을 막느니, 잡는 범위를 좁게 적어 둔다.
"""

import re
from html.parser import HTMLParser

MARKER = 'data-calendar'
_HHMM = re.compile(r'(?<!\d)([01]?\d|2[0-3]):([0-5]\d)(?!\d)')
_TAG = re.compile(r'<[^>]+>')


class _Marked(HTMLParser):
    """{key: 그 블록이 독자에게 보여 주는 글자}. 중첩은 가장 안쪽이 임자다."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.found = {}
        self._open = []          # [(tag, key)]

    def handle_starttag(self, tag, attrs):
        got = {}
        for name, value in attrs:
            got.setdefault(name, value)
        key = (got.get(MARKER) or '').strip() or None
        if key:
            self.found.setdefault(key, [])
        self._open.append((tag, key))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for i in range(len(self._open) - 1, -1, -1):
            if self._open[i][0] == tag:
                del self._open[i:]
                return

    def handle_data(self, data):
        for _tag, key in reversed(self._open):
            if key:
                self.found[key].append(data)
                return


def _dates_of(event):
    """그 일정을 가리키는 것으로 인정하는 날짜 표기들."""
    iso = event.get('date') or ''
    year, month, day = iso.split('-') if iso.count('-') == 2 else ('', '', '')
    out = {iso}
    if month and day:
        out.add(f'{int(month)}월 {int(day)}일')
        out.add(f'{int(month)}월{int(day)}일')
        out.add(f'{month}월 {day}일')
    return {x for x in out if x}


def _times_of(event):
    out = set()
    for field in ('time_et', 'time_kst'):
        value = event.get(field) or ''
        m = _HHMM.search(value)
        if m:
            out.add(f'{int(m.group(1)):02d}:{m.group(2)}')
    return out


def check(html, book):
    """-> 위반 목록. 빈 목록이면 발행 가능.

    `book` 이 없거나 낡았으면 빈 장부로 들어온다 — 그러면 표식은 전부 가리키는 곳이
    없는 것이 되어 걸린다. 표식이 없는 글은 그대로 통과한다.
    """
    events = {e.get('key'): e for e in (book or {}).get('events') or [] if e.get('key')}
    reader = _Marked()
    reader.feed(html or '')
    reader.close()

    violations = []
    for key, chunks in sorted(reader.found.items()):
        text = ' '.join(chunks)
        event = events.get(key)
        if not event:
            violations.append(
                f'{MARKER}="{key}" 가 수집한 일정에 없다 — calendar.json 에 있는 '
                f'일정만 표식을 단다(있는 키: {", ".join(sorted(events)) or "없음"})')
            continue
        if not any(form in text for form in _dates_of(event)):
            violations.append(
                f'{MARKER}="{key}" 블록에 그 일정의 날짜({event.get("date")})가 없다 — '
                f'표식이 다른 날을 가리키면 없는 것만 못하다')
        printed = {f'{int(h):02d}:{m}' for h, m in _HHMM.findall(text)}
        known = _times_of(event)
        if printed and not known:
            violations.append(
                f'{MARKER}="{key}" 는 시각을 모르는 일정인데 본문이 '
                f'{sorted(printed)} 를 적었다 — 모르는 시각은 적지 않는다')
        elif printed - known:
            violations.append(
                f'{MARKER}="{key}" 의 시각이 수집값과 다르다: 본문 {sorted(printed - known)} '
                f'· 수집 {sorted(known)} (ET/KST 중 하나를 그대로 옮긴다)')
    return violations
