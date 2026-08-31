"""주간·월간 발행 게이트.

일간 게이트를 그대로 쓸 수 없다. 인용해도 되는 수치의 출처가 다르기 때문이다 —
일간은 그날의 `bond_market/metrics` 지만, 기간물은 **집계 파일과 그 기간 발행본** 둘뿐이다.
그 밖의 숫자는 전부 창작이다.

일간과 공유하는 것: 금지 어휘 · 내부 용어 노출 · 수치 토큰 추출 방식.
기간물에만 있는 것: 커버 기간 명시 · 구멍 고지 · 표본 부족 고지 · 날짜 누락 검사.
"""

import re

from .gate import BANNED_WORDS, INTERNAL_TOKENS, _numbers, data_tokens, text_of

MIN_SESSIONS_FOR_SCORE = 20   # 이보다 적으면 적중률을 인쇄하지 않는다


def check(html, agg, posts_meta=None):
    """-> 위반 목록. agg 는 build_bond_period 가 남긴 집계 JSON."""
    errs = []
    txt = text_of(html)

    for w in BANNED_WORDS:
        if w.lower() in txt.lower():
            errs.append(f'금지 어휘: {w}')
    for tok in INTERNAL_TOKENS:
        if tok in txt:
            errs.append(f'내부 용어 노출: {tok}')

    # --- 커버 기간을 반드시 밝힌다 -----------------------------------------
    start, end = agg.get('start'), agg.get('end')
    for label, d in (('시작일', start), ('종료일', end)):
        if not d:
            errs.append(f'집계에 {label}이 없다')
        elif d not in txt:
            errs.append(f'커버 기간 {label} {d} 가 본문에 없다')

    # 실제 세션도 밝혀야 한다 — 「8월 정리」인데 19일치라는 사실이 안 보이면 안 된다
    first, last = agg.get('first_session'), agg.get('last_session')
    for d in (first, last):
        if d and d not in txt:
            errs.append(f'실제 세션 경계 {d} 가 본문에 없다')

    # --- 구간을 다 못 덮으면 그 사실을 고지한다 -----------------------------
    if not agg.get('complete'):
        head, tail = agg.get('coverage_gap_days') or (0, 0)
        if '비어 있' not in txt and '덮인 구간' not in txt:
            errs.append(f'구간을 다 덮지 못했는데(앞 {head}·뒤 {tail} 영업일) '
                        f'그 사실을 밝히지 않았다')

    # --- 표본이 모자라면 적중률을 인쇄하지 않는다 ---------------------------
    moves = agg.get('stance_changes') or []
    if len(moves) < MIN_SESSIONS_FOR_SCORE and re.search(r'적중률|승률|정확도', txt):
        if '표본' not in txt:
            errs.append('누적 표본이 모자란데 적중률을 말했다 — '
                        '「표본 부족」을 명시하거나 빼야 한다')

    # --- 그 기간의 발행본을 빠뜨리지 않는다 ---------------------------------
    # 날짜 문자열이 아무 데나 한 번 나오는 것으로는 부족하다 — 커버 기간 표기에
    # 우연히 같은 날짜가 들어 있으면 빠뜨린 글이 검사를 통과한다. 링크를 요구한다.
    for post in (agg.get('posts') or []):
        if f'posts/{post["date"]}.html' not in html:
            errs.append(f'{post["date"]} 발행본이 목록에서 빠졌다')

    # --- 수치 창작 ---------------------------------------------------------
    allowed = data_tokens(agg, posts_meta or {}, {})
    exempt = {2024.0, 2025.0, 2026.0, 2027.0}
    invented = sorted(v for v in _numbers(txt)
                      if v not in allowed and v not in exempt and abs(v) > 0.001)
    if invented:
        errs.append('집계에 없는 수치: ' + ', '.join(str(v) for v in invented[:12]))

    return errs
