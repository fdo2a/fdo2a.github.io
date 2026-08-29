"""주간·월간 정리의 발행 게이트.

이 리포트는 그 기간 발행본의 총정리다. 그래서 두 가지를 본다 —
**원본에 없던 숫자를 지어내지 않았는가**, 그리고 **원본의 어느 하루를 통째로
빠뜨리지 않았는가**. 뒤쪽은 총정리에만 있는 검사다: 요약은 빠뜨려도 티가 안 나고,
빠진 그날의 사건은 어디에도 남지 않는다.
"""

import re

from us.macro_gate import BANNED_LABELS
from us.post_check import banned_markers, body_text, data_tokens

INTERNAL_TERMS = ('weekly.json', 'monthly.json', 'scorecard.json', 'recap_source.json',
                  'stance.jsonl', 'macro.jsonl', 'market_data.json', 'research_notes.md',
                  'macro_metrics.json', 'kr_flows.json', '_sessions',
                  'signed-z', 'allowed_grades', 'basket_excess_pct')

_NUM = re.compile(r'-?\d+(?:\.\d+)?')


def _canon(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    return str(int(f)) if f == int(f) else f'{f:.10g}'


def _numbers(obj, out=None):
    out = set() if out is None else out
    if isinstance(obj, dict):
        for k, v in obj.items():
            _numbers(k, out)
            _numbers(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _numbers(v, out)
    elif isinstance(obj, bool):
        pass
    elif isinstance(obj, (int, float)):
        out.add(_canon(obj))
    elif isinstance(obj, str):
        for m in _NUM.findall(obj):
            out.add(_canon(m))
    return out


# 날짜는 수치가 아니다. 가리지 않으면 「2026-08-18」에서 -18 이 음수로 뜯겨 나와
# 「어느 원본에도 없는 수치」로 걸린다 — 이 리포트는 날짜를 매 문단에서 부르므로
# 그대로 두면 발행이 매번 막힌다(2026-08-30 실행 중 발견).
# \b 를 쓰지 않는다 — 한글도 단어문자라 「2026-08-17에」에서 경계가 서지 않는다.
_DATE = re.compile(r'(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)'
                   r'|(?<!\d)\d{4}년\s*\d{1,2}월\s*\d{1,2}일'
                   r'|(?<!\d)\d{1,2}/\d{1,2}(?!\d)')


def _mask_dates(text):
    return _DATE.sub(' ', text)


def _html_numbers(html):
    # data_tokens 는 {토큰: 등장횟수} 딕트다 — 여기서는 키만 쓴다
    out = set()
    for tok in data_tokens(_mask_dates(html)):
        for m in _NUM.findall(tok.replace(',', '')):
            out.add(_canon(m))
    return out


def check(html, agg, scorecard, recap, span):
    v = []
    text = body_text(html)

    for marker in banned_markers(html):
        v.append(f'발행본에 미확인 마커가 남았다: {marker} — 확인해 확정하거나 삭제할 것')

    low = text.lower()
    for word in BANNED_LABELS:
        if word in low:
            v.append(f'발행본에 buy-side 표기("{word}")가 남았다 — 전략·리포트·시황 정리로 부를 것')
            break

    for term in INTERNAL_TERMS:
        if term in text:
            v.append(f'내부 용어·파일명이 발행본에 노출됐다: {term}')

    start, end = agg.get('start_date'), agg.get('end_date')
    if not (start and start in text) or not (end and end in text):
        v.append(f'커버 기간이 본문에 없다 — 시작({start})과 종료({end}) 거래일을 명시할 것')

    # 총정리 커버리지 — 원본의 모든 거래일이 본문에 있어야 한다
    for post in ((recap or {}).get('posts') or []):
        d = post.get('date')
        if d and d not in text:
            v.append(f'{d} 발행본이 총정리에서 빠졌다 — 그날 사건이 사라진다. '
                     f'헤드라인: {post.get("headline", "")[:40]}')

    for d in ((recap or {}).get('missing') or []):
        v.append(f'{d} 발행본이 없다 — 목록에는 있는데 파일을 못 찾았다. '
                 '총정리 전에 원본을 확인할 것')

    allowed = _numbers(agg) | _numbers(scorecard or {})
    for post in ((recap or {}).get('posts') or []):
        allowed |= _numbers(post.get('figures') or [])
    allowed |= {str(y) for y in range(2020, 2036)}

    for n in sorted(_html_numbers(html) - allowed):
        try:
            f = abs(float(n))
        except ValueError:
            continue
        if f <= 12 and f == int(f):
            continue        # 섹션 번호·순위·거래일 수 같은 작은 정수는 통과
        v.append(f'어느 원본에도 없는 수치가 본문에 있다: {n} — 창작 금지. '
                 '집계 파일이나 그 기간 발행본에 실린 값만 인용할 것')

    ru = (scorecard or {}).get('rollup') or {}
    if any((ru.get(k) or {}).get('insufficient') for k in ru):
        if '표본 부족' not in text:
            v.append('누적 구간의 표본이 부족한데 본문이 그 사실을 밝히지 않았다 — '
                     '「누적 표본 부족」을 명시하고 당기만 실을 것')
    return v
