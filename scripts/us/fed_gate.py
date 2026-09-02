"""발행 게이트 — 「연준 이벤트」 섹션.

이 게이트가 막는 것은 수치 창작이 아니라 **인용 창작**이다. 숫자는 데이터 파일과
맞대 볼 수 있지만 따옴표 안의 영어 문장은 그럴듯할수록 안 걸린다 — 의장이 하지 않은
말을 의장의 말로 싣는 것이 이 섹션의 유일하고 가장 큰 실패 방식이다.

그래서 검사가 한 방향으로만 간다. **발행본의 인용문이 수집해 둔 원문에 글자 그대로
있어야 한다.** 원문을 못 받은 이벤트는 인용을 아예 금지한다(삭제 > 창작). 조판된
따옴표·줄표는 표준형으로 맞춰 놓고 대조하므로, 같은 문장을 다른 글자로 적었다는
이유로 막지는 않는다 — 매일 오탐하는 게이트는 결국 꺼진다.

침묵 규율도 함께 건다. **연준 이벤트가 없는 날에는 섹션이 없어야 한다.** thesis
파이프라인의 `check_silence()` 와 같은 이유다 — 매일 뭔가를 쓰게 두면 이벤트 섹션이
아니라 매일 새로 쓰는 논평란이 된다.
"""

import html as _html
import re

from common.numbers import (TAG_RE, measure_numbers, numbers_split_by_tags,
                            numeric_tokens, strip_comments, text_dense, text_of)
from us import fed_events as fe

SECTION_TITLE = '연준 이벤트'

# 이 섹션 안에서만 통하는 최소치. 「표식만 달고 내용을 비워 두는」 우회를 막는 값이다.
EVENT_MIN_CHARS = 100
TRANS_MIN_CHARS = 20
IDEA_MIN_CHARS = 150
INVALIDATION_MIN_CHARS = 30
CHANGE_MIN_CHARS = 150
MIN_QUOTES_PER_EVENT = 2
MIN_IDEAS = 2

_H2 = re.compile(r'<h2\b[^>]*>(.*?)</h2>', re.S | re.I)
_QUOTE_REF = re.compile(r'\bdata-fed-quote-ref\s*=\s*"([A-Za-z0-9_-]+)"', re.I)
_BLOCKQUOTE = re.compile(r'<blockquote\b[^>]*>(.*?)</blockquote>', re.S | re.I)
_TRANS_P = re.compile(r'<p\b[^>]*\bclass\s*=\s*"[^"]*\bfed-trans\b[^"]*"[^>]*>(.*?)</p>',
                      re.S | re.I)
_CAPTION = re.compile(r'class\s*=\s*"[^"]*\bcaption\b[^"]*"', re.I)
_TAG_NAME = re.compile(r'<\s*(/?)\s*([a-zA-Z][\w-]*)')

# 표식은 «태그의 속성»이지 문서 안의 좌표가 아니다. 그래서 속성이 붙은 그 요소가
# 어디서 끝나는지까지 봐야 한다 — 표식에서 다음 표식까지 자르던 방식은 빈 표식이
# 뒤따르는 남의 내용을 제 것처럼 빌리게 했다(2026-09-02 codex 검토에서 실증).
MARKER_ATTRS = {
    'event': 'data-fed-event',
    'quote': 'data-fed-quote',
    'change': 'data-fed-change',
    'idea': 'data-fed-idea',
    'invalidation': 'data-invalidation',
}
# HTML 은 태그 이름과 속성 이름의 대소문자를 가리지 않는다. 우리 정규식이 가리면
# 브라우저에는 그대로 보이는 마크업이 검사에서만 사라진다 — 대문자 `<BLOCKQUOTE>` 로
# 쓴 창작 인용이 표식 밖 검사를 통째로 비켜 갔다(2026-09-02 codex 2차 검토).
_MARKER_VALUE = {k: re.compile(r'\b%s\s*=\s*"([A-Za-z0-9_-]*)"' % v, re.I)
                 for k, v in MARKER_ATTRS.items()}

# 인용문 안에 있어서는 안 되는 것. 태그가 있으면 게이트가 읽는 문장과 독자가 보는
# 문장이 갈릴 수 있다 — `<span hidden>not </span>` 하나로 부정문이 긍정문이 된다
# (2026-09-02 codex 검토에서 실증). 원문 인용에는 마크업이 필요 없으므로 아예 막는다.
_INVISIBLE = re.compile(r'[\u200b-\u200f\u2060\ufeff\u00ad\u180e\u202a-\u202e]')

# 이 섹션 안에서만 통하는 최소치. 「표식만 달고 내용을 비워 두는」 우회를 막는 값이다.
EVENT_MIN_CHARS = 100
TRANS_MIN_CHARS = 20
IDEA_MIN_CHARS = 150
INVALIDATION_MIN_CHARS = 30
CHANGE_MIN_CHARS = 150
MIN_QUOTES_PER_EVENT = 2
MIN_IDEAS = 2

# 내부 사정이 지면에 나오면 안 된다 — 독자는 우리 파일 이름을 모른다.
INTERNAL = ('events.json', 'fed_events', 'statement_diff', 'fed_gate', 'research_notes',
            'data-fed', 'tier 1', 'tier1', 'corpus', 'redline')


def _text(fragment):
    return _html.unescape(TAG_RE.sub(' ', fragment or '')).strip()


def section(html_doc):
    """제목이 「연준 이벤트」로 시작하는 <h2>가 여는 구간. 없으면 None.

    부분일치로 찾지 않는다 — 「연준」은 헤드라인에도 매일 나오는 말이다.
    """
    doc = strip_comments(html_doc or '')
    starts = [m.start() for m in _H2.finditer(doc)
              if _text(m.group(1)).startswith(SECTION_TITLE)]
    if not starts:
        return None
    start = starts[0]
    stops = [m.start() for m in re.finditer(r'<h2\b|<footer\b|</main\b', doc, re.I)
             if m.start() > start]
    return doc[start:stops[0] if stops else len(doc)]


def _element_extent(s, start, name):
    """`start` 에서 열린 `name` 요소가 끝나는 위치.

    `<p>` 는 자기 안에 자기를 담을 수 없으므로 다음 `<p` 나 상위 닫는 태그에서
    끊는다 — 닫지 않은 `<p>` 하나가 문서 끝까지 구역을 늘리면, 무효화 조건 뒤의
    본문이 통째로 수치 검사에서 빠진다.
    """
    name = name.lower()
    if name == 'p':
        stops = [m.start() for m in
                 re.finditer(r'</p\s*>|<p\b|</div\s*>|</section\s*>', s[start + 1:], re.I)]
        if not stops:
            return len(s)
        at = start + 1 + stops[0]
        close = re.match(r'</p\s*>', s[at:], re.I)
        return at + close.end() if close else at
    depth = 0
    for m in _TAG_NAME.finditer(s, start):
        if m.group(2).lower() != name:
            continue
        depth += -1 if m.group(1) else 1
        if depth == 0:
            close = s.find('>', m.end())
            return len(s) if close < 0 else close + 1
    return len(s)


def blocks(section_html):
    """표식 -> [(key, 원본 HTML 조각, (시작, 끝))]. 조각은 **그 요소의 실제 범위**.

    표식이 붙은 태그를 찾고 그 태그가 닫히는 곳까지를 그 블록으로 삼는다. 예전에는
    표식에서 다음 표식까지 잘랐는데, 그러면 `<div data-fed-quote="k"></div>` 뒤에
    맨 `<blockquote>` 를 두는 것만으로 빈 표식이 남의 인용을 제 것으로 만들었다.
    """
    s = section_html or ''
    out = {kind: [] for kind in MARKER_ATTRS}
    for m in TAG_RE.finditer(s):
        tag = m.group(0)
        if tag.startswith('</') or tag.startswith('<!'):
            continue
        name = _TAG_NAME.match(tag)
        if not name:
            continue
        for kind, pat in _MARKER_VALUE.items():
            hit = pat.search(tag)
            if not hit:
                continue
            end = _element_extent(s, m.start(), name.group(2))
            out[kind].append((hit.group(1), s[m.start():end], (m.start(), end)))
    return out


def sweep_scope(section_html, blk):
    """수치 검사 대상 — 무효화 조건 블록을 뺀 나머지.

    무효화 조건에 적는 값은 **우리가 거는 문턱**이지 데이터가 내려보낸 값이 아니다.
    「근원 물가가 3%를 넘으면 접는다」의 3% 는 어느 파일에도 없고 있어서도 안 된다.
    그래서 이 블록만 창작 검사에서 뺀다 — 대신 앞을 내다보는 문턱은 **여기에만**
    쓴다. 아이디어 본문에 미래 목표가를 적으면 검사에 걸리고, 그게 의도다.

    빼는 범위는 **그 요소가 끝나는 곳까지**다. 다음 표식까지 빼던 예전 방식은
    무효화 문단을 닫은 뒤의 일반 본문까지 면제했다(codex 검토에서 실증).
    """
    s = section_html or ''
    keep, at = [], 0
    for _key, _raw, (a, b) in sorted(blk['invalidation'], key=lambda x: x[2]):
        if a < at:
            continue
        keep.append(s[at:a])
        at = b
    keep.append(s[at:])
    return ''.join(keep)


def _corpus(event):
    """그 이벤트로 실제로 받아 둔 문서를 이어 붙인 것. 없으면 ''."""
    return '\n'.join(s.get('text') or '' for s in event.get('sources') or []
                     if s.get('ok') and s.get('text'))


def allowed_numbers(events, *data_blobs):
    """이 섹션이 인용해도 되는 수치.

    데이터 파일이 내려보낸 값에 **그 이벤트로 받아 둔 원문에 적힌 값**을 더한다.
    허용 집합이 넓어지는 것은 사실이고 숨기지 않는다 — 성명문의 「2 percent」를 옮겨
    적는 것이 이 섹션의 일인데 그 값은 어느 데이터 파일에도 없다. 대신 넓히는 근거가
    남의 지표가 아니라 **그 문서 자신**이다.
    """
    out = numeric_tokens(*data_blobs)
    for e in events or []:
        out |= fe.source_numbers(_corpus(e))
    return out


def quote_markup_problem(inner_html):
    """인용문 안의 마크업·보이지 않는 문자. 없으면 None.

    게이트는 태그를 지운 문자열을 원문과 대조하는데, 브라우저는 숨긴 글자를 안
    보여 준다. 그래서 `<span hidden>not </span>` 하나면 **게이트가 읽는 문장과
    독자가 보는 문장이 정반대**가 된다. 원문 인용에 마크업이 필요할 일이 없으므로
    아예 막는 쪽이 낫다 — 무엇을 숨겼는지 판별하려 들면 숨기는 방법마다 쫓아다녀야
    한다(CSS `content`, `font-size:0`, 폭 없는 문자 …).
    """
    if TAG_RE.search(inner_html or ''):
        return '인용 안에 태그가 있다 — 숨긴 글자가 대조를 속일 수 있으므로 글자만 넣는다'
    if _INVISIBLE.search(_html.unescape(inner_html or '')):
        return '인용 안에 보이지 않는 문자가 있다'
    return None


def _quote_ok(raw_block, event, key, v):
    corpus = _corpus(event)
    quotes = _BLOCKQUOTE.findall(raw_block)
    if not quotes:
        v.append(f'연준 이벤트 {key}: 인용 블록에 <blockquote>가 없다 — '
                 '발언은 원문 그대로 싣고 번역을 그 아래에 붙일 것')
        return False
    ok = True
    for q in quotes:
        bad = quote_markup_problem(q)
        if bad:
            v.append(f'연준 이벤트 {key}: {bad}')
            ok = False
            continue
        body = fe.normalize(q)
        if len(body) < fe.QUOTE_MIN:
            v.append(f'연준 이벤트 {key}: 인용이 {len(body)}자로 너무 짧다 — '
                     f'{fe.QUOTE_MIN}자 이상이라야 무슨 말인지 읽힌다')
            ok = False
            continue
        if not corpus:
            v.append(f'연준 이벤트 {key}: 원문을 받아 두지 못한 이벤트인데 인용문이 실렸다 '
                     '— 대조할 수 없는 발언은 싣지 않는다')
            ok = False
            continue
        miss = fe.verify_quote(q, corpus)
        if miss:
            v.append(f'연준 이벤트 {key}: {miss}')
            ok = False
    trans = [t for t in _TRANS_P.findall(raw_block) if len(_text(t)) >= TRANS_MIN_CHARS]
    if not trans:
        v.append(f'연준 이벤트 {key}: 인용에 한국어 번역(<p class="fed-trans">)이 없다')
        ok = False
    if not _CAPTION.search(raw_block):
        v.append(f'연준 이벤트 {key}: 인용에 출처 캡션이 없다 — '
                 '어느 문서 어느 자리에서 나온 말인지 밝힐 것')
        ok = False
    return ok


def _check_orphan_quotes(sec, blk, v):
    """표식 밖의 `<blockquote>`. 하나라도 있으면 발행을 막는다.

    표식이 붙은 블록만 검사하면, 정상 인용 둘을 남겨 둔 채 그 옆에 창작 인용을
    하나 더 놓는 것으로 검사를 통째로 피해 갈 수 있다(codex 검토에서 실증).
    섹션 안의 **모든** 인용문이 검사 대상이어야 한다.
    """
    spans = [span for _k, _r, span in blk['quote']]
    for m in re.finditer(r'<blockquote\b', sec or '', re.I):
        if not any(a <= m.start() < b for a, b in spans):
            v.append('연준 이벤트: 표식 없는 <blockquote>가 있다 — '
                     '인용문은 전부 <div data-fed-quote="KEY"> 안에 넣어야 검사를 받는다')
            return


def _check_change(diff, blk, v):
    """성명문 변경점 블록. 변경점을 계산해 둔 날에만 요구한다."""
    if diff is None:
        return
    changed = [c['after'] for c in diff.get('changed') or []] + list(diff.get('added') or [])
    if not blk['change']:
        v.append('연준 이벤트: 직전 성명 대비 변경점을 계산해 뒀는데 '
                 '<div data-fed-change="1"> 블록이 없다')
        return
    body = ' '.join(_text(raw) for _k, raw, _s in blk['change'])
    if len(body) < CHANGE_MIN_CHARS:
        v.append(f'연준 이벤트: 변경점 블록이 {len(body)}자뿐이다 — '
                 f'{CHANGE_MIN_CHARS}자 이상으로 무엇이 어떻게 바뀌었는지 쓸 것')
    if not changed:
        return
    norm = fe.normalize(' '.join(raw for _k, raw, _s in blk['change']))
    if not any(seg in norm for s in changed for seg in fe.quote_segments(s)):
        v.append('연준 이벤트: 변경점 블록이 바뀐 문장을 하나도 옮기지 않았다 — '
                 '고쳐 쓴 구절을 원문 그대로 보여줄 것')


def _check_ideas(blk, printed_keys, v):
    ideas = blk['idea']
    if len(ideas) < MIN_IDEAS:
        v.append(f'연준 이벤트: 투자 아이디어가 {len(ideas)}개다 — {MIN_IDEAS}개 이상 필요')
    for n, (_key, raw, (a, b)) in enumerate(ideas, 1):
        # 무효화 조건은 **그 아이디어 안에** 있어야 한다. 섹션 어딘가에 개수만
        # 맞춰 두면 어느 아이디어가 무엇으로 무효화되는지 알 수 없다.
        mine = [inv for inv in blk['invalidation'] if a <= inv[2][0] < b]
        body = _text(raw)
        for _k, inv_raw, _s in mine:
            body = body.replace(_text(inv_raw), '')
        if len(body.strip()) < IDEA_MIN_CHARS:
            v.append(f'연준 이벤트: {n}번째 아이디어가 {len(body.strip())}자뿐이다 — '
                     '어느 발언에서 나왔고 어느 경로로 무엇에 닿는지까지 쓸 것')
        ref = _QUOTE_REF.search(raw)
        if not ref:
            v.append(f'연준 이벤트: {n}번째 아이디어에 근거 발언 표식'
                     '(data-fed-quote-ref)이 없다 — 인용에 걸리지 않은 아이디어는 '
                     '이 섹션의 것이 아니다')
        elif ref.group(1) not in printed_keys:
            v.append(f'연준 이벤트: {n}번째 아이디어가 지면에 없는 발언'
                     f'({ref.group(1)})을 근거로 든다')
        if not mine:
            v.append(f'연준 이벤트: {n}번째 아이디어에 무효화 조건이 없다 — '
                     '<p data-invalidation="N">을 그 아이디어 안에 둘 것')
        elif max(len(_text(r)) for _k, r, _s in mine) < INVALIDATION_MIN_CHARS:
            v.append(f'연준 이벤트: {n}번째 무효화 조건이 비어 있다 — '
                     '무엇이 나오면 이 생각을 접는지 수치나 사건으로 쓸 것')


def check(html_doc, book, *data_blobs):
    """위반 목록. 비어 있으면 발행 가능."""
    v = []
    events = (book or {}).get('events') or []
    duty = [e for e in events if e.get('fresh') and e.get('tier') == 1]
    sec = section(html_doc)

    if not duty:
        if sec:
            v.append('오늘은 새로 나온 연준 이벤트가 없는데 「연준 이벤트」 섹션이 실렸다 '
                     '— 이 섹션은 FOMC·잭슨홀 같은 자리가 있는 날에만 연다')
        return v
    if not sec:
        labels = ', '.join(e.get('kind_ko') or e.get('kind') for e in duty)
        v.append(f'오늘 연준 이벤트({labels})가 있는데 「연준 이벤트」 섹션이 없다')
        return v

    blk = blocks(sec)
    by_key = {e.get('key'): e for e in events}

    event_blocks = {k: raw for k, raw, _s in blk['event']}
    for e in duty:
        key = e.get('key')
        raw = event_blocks.get(key)
        label = e.get('kind_ko') or e.get('kind')
        if raw is None:
            v.append(f'연준 이벤트: 「{label}」 도입 문단이 없다 — '
                     f'<p data-fed-event="{key}">로 무슨 자리에서 누가 말했는지 쓸 것')
        elif len(_text(raw)) < EVENT_MIN_CHARS:
            v.append(f'연준 이벤트 {key}: 도입 문단이 {len(_text(raw))}자뿐이다 — '
                     f'{EVENT_MIN_CHARS}자 이상 필요')

    printed = {}
    for key, raw, _span in blk['quote']:
        e = by_key.get(key)
        if e is None:
            v.append(f'연준 이벤트: 오늘 이벤트에 없는 인용 키({key})가 실렸다')
            continue
        if _quote_ok(raw, e, key, v):
            printed[key] = printed.get(key, 0) + 1

    _check_orphan_quotes(sec, blk, v)

    for e in duty:
        key = e.get('key')
        if not _corpus(e):
            continue          # 원문을 못 받은 날은 인용을 요구하지 않는다 (금지할 뿐)
        if printed.get(key, 0) < MIN_QUOTES_PER_EVENT:
            v.append(f'연준 이벤트 {key}: 검증된 인용이 {printed.get(key, 0)}개다 — '
                     f'{MIN_QUOTES_PER_EVENT}개 이상 필요')

    _check_change((book or {}).get('diff'), blk, v)
    _check_ideas(blk, set(printed), v)

    allowed = allowed_numbers(events, *data_blobs)
    for n in sorted(measure_numbers(text_of(sweep_scope(sec, blk)))):
        if n not in allowed:
            v.append(f'연준 이벤트: 데이터에도 원문에도 없는 수치 {n} — '
                     '수치 창작 금지')
    for run in numbers_split_by_tags(sec):
        v.append(f'연준 이벤트: 수치 사이에 태그가 끼어 있다 — 「{run[:40]}」')

    body = text_of(sec) + ' ' + text_dense(sec)
    for word in INTERNAL:
        if word in body:
            v.append(f'연준 이벤트: 내부 용어 「{word}」가 지면에 노출됐다')
    return v
