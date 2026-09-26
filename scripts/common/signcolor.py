"""부호 색 — CSS 와 범용 칠하기. 주간 글은 이제 표 칸만 칠한다(`us.weekly_insight._cv`).

2026-09-26 두 번째 지시: 「표에 있는 숫자들에만 색상을 표시하고 채권은 부호를 반대로」 — 그래서
조립기는 `paint()` 를 부르지 않는다. 아래는 첫 지시 때의 설명이다.

(첫 지시) 글 전체(표·산문)에서 부호가 붙은 수치를 + 초록, - 빨강으로 칠한다.

2026-09-26 사용자 지시(주간 글): 「전체 글 모두 +는 초록색, -는 빨간색으로 숫자에 색깔」.
일간의 `apply_colors.py` 와 규칙이 다르다 — 그쪽은 표 칸만, 「좋아짐 = 초록」이라 금리 상승이
빨강이다. 여기는 **부호만** 본다. 부호 없이 동사로 방향을 말한 수치(「16.6bp 올랐다」)는
칠하지 않는다 — 문장에서 방향을 추정하면 잘못 칠한다.

보이는 글자는 바꾸지 않고 `<span class="pos|neg">` 로 감싸기만 한다. 태그 속성·`<script>`·
`<style>` 안은 건드리지 않는다. 날짜(2026-09-24)의 하이픈은 앞이 숫자라 부호로 보지 않는다.
"""
import re

CSS = '.pos{color:#00A85A;} .neg{color:#FF4040;}'
_SKIP = re.compile(r'(<script\b.*?</script>|<style\b.*?</style>|<[^>]+>)', re.S | re.I)
_SIGNED = re.compile(r'(?<![\w.\d/])([+\-−])(\d[\d,]*(?:\.\d+)?)(%p|%|bp|계약|억 엔)?')


def _paint_text(text):
    def repl(m):
        sign, num, unit = m.group(1), m.group(2), m.group(3) or ''
        if float(num.replace(',', '')) == 0:
            return m.group(0)
        cls = 'pos' if sign == '+' else 'neg'
        return f'<span class="{cls}">{m.group(0)}</span>'
    return _SIGNED.sub(repl, text)


def paint(html):
    parts = _SKIP.split(html)
    return ''.join(p if _SKIP.fullmatch(p) else _paint_text(p) for p in parts)
