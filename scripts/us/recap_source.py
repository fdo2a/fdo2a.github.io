"""그 기간 발행본을 총정리용 재료로 줄인다.

주간·월간 정리는 시장을 새로 취재하는 글이 아니라 이미 나간 리포트들을 한 편으로 묶는
글이다. 그런데 발행본 하나가 34K토큰이라 5편을 통째로 넘기면 작성 에이전트의 컨텍스트가
감당하지 못한다. 여기서 «제목 + 첫 문단»만 남긴다 — 각 절이 그날 무엇을 말했는지는
그 둘로 충분하고, 세부가 필요하면 발행본 링크가 있다.

`figures` 는 게이트용이다. 발행본에 이미 실린 숫자는 총정리에 인용해도 창작이 아니므로
허용 집합에 들어간다.
"""

import os
import re

from us.post_check import body_text, data_tokens, mask_dates

_SECTION = re.compile(r'<section\b[^>]*>(.*?)</section>', re.S | re.I)
_HEADING = re.compile(r'<h[1-6]\b[^>]*>(.*?)</h[1-6]>', re.S | re.I)
_PARA = re.compile(r'<p\b[^>]*>(.*?)</p>', re.S | re.I)


def _plain(fragment):
    return body_text(f'<body>{fragment}</body>').strip()


_HYPOTHESIS = re.compile(r'<p\b[^>]*data-hypothesis[^>]*>(.*?)</p>', re.S | re.I)


def _cut(text, n):
    return text if len(text) <= n else text[:n].rstrip() + '…'


SCHEDULE_TITLE = '향후 확인 일정'   # kr.stance_gate.SCHEDULE
_ROW = re.compile(r'<tr\b[^>]*>(.*?)</tr>', re.S | re.I)
_CELL = re.compile(r'<(td|th)\b[^>]*>(.*?)</\1>', re.S | re.I)


def _table_lead(block):
    """문단 없이 표만 있는 절(KR 「향후 확인 일정」)은 본문 행을 「칸 칸 · 칸 칸」으로 잇는다.
    머리 행(thead 안, 또는 칸이 전부 th)은 빼고, 행머리 th 는 칸으로 읽는다(codex 2차 #3)."""
    block = re.sub(r'<!--.*?-->', '', block, flags=re.S)    # 주석 속 폐기 행(codex 3차 #2)
    block = re.sub(r'<thead\b.*?</thead>', '', block, flags=re.S | re.I)
    rows = []
    for tr in _ROW.findall(block):
        cells = _CELL.findall(tr)
        if not cells or all(tag.lower() == 'th' for tag, _ in cells):
            continue
        rows.append(' '.join(_plain(c) for _, c in cells))
    return ' · '.join(r for r in rows if r.strip())


def post_sections(html, max_lead=220):
    out = []
    for block in _SECTION.findall(html or ''):
        h = _HEADING.search(block)
        p = _PARA.search(block)
        if not h:
            continue
        lead = _plain(p.group(1)) if p else ''
        # KR 「향후 확인 일정」은 표가 본문이다 — 캡션이 붙어도 표 행을 리드로(codex 2026-10-20 #5, 2차 #4).
        # 이 절에만 쓴다: 넓히면 옛 US 지표 대시보드 58곳의 리드가 바뀐다(2026-10-20 118편 대조).
        if _plain(h.group(1)) == SCHEDULE_TITLE:
            lead = _table_lead(block) or lead
        hyp = _HYPOTHESIS.search(block) if 'data-lede="review"' in block else None
        if hyp:
            # KR 복기(2026-10-20)는 어제 판정이 첫 문단이다 — 열린 가설 첫 문단을 함께 넘긴다
            half = (max_lead - 5) // 2
            lead = _cut(lead, half) + ' / ' + _cut(_plain(hyp.group(1)), half)
        if len(lead) > max_lead:
            lead = lead[:max_lead].rstrip() + '…'
        out.append({'title': _plain(h.group(1)), 'lead': lead})
    return out


def post_figures(html):
    """발행본에 실린 수치 — 날짜에서 뜯긴 조각은 뺀다.

    가리지 않으면 「2026-08-17」에서 -17 이 허용 토큰이 되어 「포트폴리오는 -17%」
    창작이 게이트를 그대로 지난다(2026-08-30 주간본 회수 사유 중 하나).
    """
    return sorted(data_tokens(mask_dates(html or '')))


def collect(posts_dir, listing, start, end, span, key):
    """{span, key, start_date, end_date, sessions, posts[], missing[]}.

    목록(posts.json)에 있는데 파일이 없으면 `missing` 에 남긴다 — 총정리에서 하루가
    통째로 빠지면 그날 사건이 사라지므로, 조용히 넘어가지 않는다.
    """
    rows, missing = [], []
    for entry in sorted(listing or [], key=lambda e: e.get('date') or ''):
        d = entry.get('date')
        if not d or not (start <= d <= end):
            continue
        path = os.path.join(posts_dir, f'{d}.html')
        if not os.path.exists(path):
            missing.append(d)
            continue
        with open(path, encoding='utf-8') as fh:
            html = fh.read()
        rows.append({'date': d,
                     'headline': entry.get('headline', ''),
                     'sections': post_sections(html),
                     'figures': post_figures(html)})
    if not rows and not missing:
        raise ValueError(f'{start}~{end} 구간에 발행본이 없다 — 총정리할 원본이 없으므로 중단한다')
    return {'span': span, 'key': key, 'start_date': start, 'end_date': end,
            'sessions': len(rows), 'posts': rows, 'missing': missing}
