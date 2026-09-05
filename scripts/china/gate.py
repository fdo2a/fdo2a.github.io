"""중국 학습 리포트 발행 게이트.

브리프 게이트가 「오늘 하루를 제대로 설명했는가」를 본다면 이쪽은 **「이게 학습인가」**
를 본다. 막으려는 실패가 다르다.

1. **진도** — 정해진 다음 강의를 썼는가. 재탕·건너뛰기·표식 위조를 막는다.
2. **되짚기** — 과거 강의의 «명제»를 이번 데이터로 다시 봤는가.
3. **수치 귀속** — 헤드라인 숫자가 그 지표에 묶여 있는가.
4. **수집 완전성** — 못 받은 릴리스가 「발표 없음」으로 위장되지 않았는가.
5. **시황 상한** — 학습 리포트가 시황으로 미끄러지지 않았는가.
6. **포지션 어휘** — 설명이 매매 신호로 변질되지 않았는가.
7. **용어 풀이** — 중국 고유어를 처음 쓸 때 풀었는가.

검사는 전부 `dom.py` 의 «보이는 트리» 위에서 돈다. 정규식으로 표식을 세면 숨긴 요소와
중복 표식에 뚫린다(codex C4).

Design: docs/superpowers/specs/2026-09-05-china-learning-report-design.md
"""

import re

from china import dom as D
from china import manifest as M
from china import state as ST

VERDICTS = {'valid': '유효', 'revise': '수정', 'retire': '폐기'}

# 헤드라인 지표를 부르는 말. manifest 라벨에서 수식어를 걷어낸 것 — 「소비자물가 전년
# 대비」에서 「소비자물가」. 이 말을 부르는 인용 문단은 바인딩을 요구한다.
HEADLINE_NAMES = tuple(sorted({
    spec.label_ko.split(' ')[0] for spec in M.METRICS.values()
} | {'PMI'}))

# 판정어 뒤에 오면 뜻이 뒤집히는 것들. 「유효하지 않습니다」가 「유효」로 읽히면 통제
# 어휘가 통제하는 게 없어진다(codex C4).
# 판정을 **직접** 뒤집는 것만 센다. 「없」을 넣었더니 「유효하며 추가 수정은 필요가
# 없습니다」가 걸렸다 — 그 부정의 대상은 판정이 아니라 추가 수정이다(codex 3차).
_NEGATION = re.compile(r'하지\s*않|지\s*않|이\s*아니|가\s*아니|아닙|아니다|아니라'
                       r'|한 것은\s*아니|보기\s*어렵|볼 수\s*없')
# 「유효한 것은 아닙니다」처럼 부정이 서너 어절 뒤에 온다. 창을 넓히되 다음 문장까지는
# 넘어가지 않게 문장부호에서 끊는다.
_NEG_WINDOW = 30


def check_progress(html, state, syllabus, man=None):
    v = []
    completed = ST.completed_ids(state)
    expected = syllabus.next_lesson(completed)

    marks = D.find_marked(html, 'data-lesson')
    if not marks:
        return ['data-lesson 표식이 없다 — 이번 편이 어느 강의인지 기계가 못 읽는다']
    if len(marks) > 1:
        ids = ', '.join(m.attrs['data-lesson'] for m in marks)
        return [f'data-lesson 표식이 {len(marks)}개다({ids}) — 강의는 한 편에 하나다']

    el = marks[0]
    lid = el.attrs['data-lesson']

    # 표식은 최상위 <section> 에만 붙는다. 중첩 div 를 허용하면 「강의 구간」의 경계가
    # 글쓴이 마음대로가 되고, 구간 안팎 검사가 전부 흔들린다(codex 2차 검토).
    # 태그만 강제한다. 부모까지 못 박으면 `<div class="container">` 같은 정상 레이아웃
    # 래퍼가 거부된다(codex 3차 오탐).
    if el.tag != 'section':
        v.append(f'data-lesson 표식이 <{el.tag}> 에 붙었다 — <section> 이어야 한다')

    if expected is None:
        v.append('실라버스가 소진됐다 — fixed 강의가 더 없다. draft 승격은 사람이 한다')
        return v

    try:
        lesson = syllabus.get(lid)
    except KeyError:
        return [f'실라버스에 없는 강의 id: {lid}']

    if lid in completed:
        v.append(f'{lid} 은 이미 발행한 강의다 — 재탕은 진도가 아니다')
    if lid != expected:
        v.append(f'이번 강의는 {expected} 여야 한다 — 발행본은 {lid} 을 썼다')
    unmet = [p for p in lesson['prereq'] if p not in completed]
    if unmet:
        v.append(f'{lid} 의 선수 강의가 아직이다: {", ".join(unmet)}')
    if len(el.text().strip()) < 200:
        v.append(f'data-lesson="{lid}" 구간이 비었다 — 표식만 있고 강의가 없다')

    # required_data 는 「이 강의는 이 수치 없이는 성립하지 않는다」는 계약이다. 검사하지
    # 않으면 필수 수치가 하나도 없는 글이 통과한다.
    need = lesson.get('required_data') or []
    if need:
        # 빈 <span data-metric> 만 넣어 요건을 충족시키는 우회를 막는다.
        bound = {e.attrs['data-metric'] for e in D.find_marked(html, 'data-metric')
                 if _NUM.search(e.text())}
        missing = [k for k in need if k not in bound]
        available = [k for k in missing if man is None or k in man]
        if available:
            v.append(f'{lid} 의 필수 지표가 본문에 없다: {", ".join(available)} — '
                     'data-metric 으로 묶어 인용한다')
    return v


def check_revisit(html, state):
    target = ST.revisit_target(state)
    marks = D.find_marked(html, 'data-revisit')

    if target is None:
        return ['첫 편이 아닌데 되짚기 표식이 있다'] if marks else []

    if not marks:
        return [f'data-revisit 블록이 없다 — 이번 편은 {target} 을 되짚어야 한다']
    if len(marks) > 1:
        return [f'data-revisit 표식이 {len(marks)}개다 — 되짚기는 한 편에 하나다']

    el = marks[0]
    v = []
    got = el.attrs['data-revisit']
    if got != target:
        v.append(f'되짚기 대상이 어긋난다 — 큐가 지목한 것은 {target} 인데 {got} 을 썼다')

    verdict = el.attrs.get('data-verdict')
    if verdict not in VERDICTS:
        v.append(f'되짚기 판정이 통제 어휘가 아니다: {verdict!r} '
                 f'(허용: {", ".join(VERDICTS)})')
    else:
        v += _check_verdict_prose(el, verdict)

    claim = el.attrs.get('data-claim')
    if not claim:
        v.append('data-claim 표식이 없다 — 어느 명제를 되짚었는지 기계가 못 읽는다')
    else:
        known = ST.claim_ids(state, got)
        if claim not in known:
            v.append(f'{got} 에 없는 명제 id: {claim} (있는 것: {", ".join(known) or "없음"})')
    return v


def _check_verdict_prose(el, verdict):
    """화면에 보이는 판정어가 부정문에 실려 뒤집히지 않았는가."""
    word = VERDICTS[verdict]
    # 줄바꿈으로 검사창을 끊는 우회를 막는다.
    text = re.sub(r'[ \t\r\n\u00a0]+', ' ', el.text())
    if word not in text:
        return [f'판정 「{word}」 이 본문에 보이지 않는다 — 표식과 지면이 갈린다']
    for m in re.finditer(re.escape(word), text):
        tail = re.split(r'[.。!?\n]', text[m.end():m.end() + _NEG_WINDOW])[0]
        if _NEGATION.search(tail):
            return [f'판정 「{word}」 뒤에 부정이 붙었다 — 표식과 뜻이 반대다: '
                    f'…{text[m.start():m.end() + _NEG_WINDOW]}…']
    return []


# ── 수치 귀속 ──

# 연도·강의 id·날짜는 수치가 아니다. 뜯어내면 「2026」이 허용 토큰이 되고 「-18」 같은
# 조각이 음수 창작을 통과시킨다(period_gate 가 겪은 것과 같은 버그).
_MASK = [
    (re.compile(r'\b(19|20)\d{2}\s*년'), ' '),
    (re.compile(r'\b(19|20)\d{2}-\d{2}(-\d{2})?\b'), ' '),
    (re.compile(r'\b(19|20)\d{2}-W\d{2}\b'), ' '),
    (re.compile(r'\b[AB]\d{2}(-c\d+)?\b'), ' '),
    (re.compile(r'\b\d+\s*(?:월|일|분기|년대)'), ' '),
]
_NUM = re.compile(r'-?\d[\d,]*(?:\.\d+)?')

# 조판용 빼기 기호로 부호를 위장하는 것을 막는다 — 「−0.5」가 「0.5」로 읽히면 부호
# 검사가 통째로 무력해진다(codex 2차 검토).
_MINUS = str.maketrans({'\u2212': '-', '\u2013': '-', '\u2014': '-', '\uff0d': '-'})


def _numbers(text):
    text = text.translate(_MINUS)
    # 「− 0.5」처럼 부호와 수치 사이에 공백을 끼우는 위장.
    text = re.sub(r'-\s+(?=\d)', '-', text)
    for pat, rep in _MASK:
        text = pat.sub(rep, text)
    return {m.group(0).replace(',', '') for m in _NUM.finditer(text)}


# ── 방향어 — 절댓값 표기가 부호를 뒤집지 못하게 ──
_FALL = re.compile(r'하락|내렸|내려|줄었|줄어|감소|축소|떨어|낮아|마이너스|하회')
_RISE = re.compile(r'상승|올랐|올라|늘었|늘어|증가|확대|높아|플러스|상회')


_DIR_WINDOW = 16


def _governing_direction(el):
    """그 수치를 지배하는 방향어. `(하락인가, 상승인가)`.

    한국어에서 수치를 받는 서술어는 **뒤에 온다** — 「0.5% 내렸습니다」. 그래서 뒤를
    먼저 보고, 거기 없을 때만 앞을 본다. 문단 전체를 보면 문단 어딘가에 반대 방향어를
    하나 심는 것만으로 부호 검사가 중화된다(직접 확인).
    """
    node = el
    while node is not None and node.tag not in ('p', 'li', 'td', 'th', 'section',
                                                'div', '#root'):
        node = node.parent
    whole = (node or el).text()
    inner = el.text()
    at = whole.find(inner)
    if at < 0:
        return bool(_FALL.search(whole)), bool(_RISE.search(whole))

    end = at + len(inner)
    after = re.split(r'[.。!?\n]', whole[end:end + _DIR_WINDOW])[0]
    got = _nearest(after)
    if got != (False, False):
        return got
    return _nearest(whole[max(0, at - _DIR_WINDOW):at], last=True)


def _nearest(window, last=False):
    """창 안에서 **가장 가까운** 방향어 하나. 둘 다 있으면 앞의 것(뒤 창) 또는
    뒤의 것(앞 창)을 취한다 — 둘 다 세면 반대말을 하나 심어 검사를 중화할 수 있다."""
    hits = [(m.start(), False) for m in _FALL.finditer(window)]
    hits += [(m.start(), True) for m in _RISE.finditer(window)]
    if not hits:
        return False, False
    _, rising = max(hits) if last else min(hits)
    return (not rising), rising


def _canon(v):
    f = float(v)
    return str(int(f)) if f == int(f) else f'{f:.10g}'


# 이름과 수치가 **같은 구절**에 붙었을 때만 헤드라인 참칭으로 본다. 문단 어디엔가
# 이름이 있다는 것만으로 걸면 「7월 소비자물가 원문을 보면 돼지고기가 13.3% 내렸다」
# 같은 정상 인용이 매번 막힌다 — 이름은 릴리스를 가리키고 수치는 다른 항목이다.
# 이름이 수치의 **주어**로 붙었을 때만 참칭으로 본다. 「소비자물가 원문에서 돼지고기는
# 13.3%」처럼 사이에 다른 주어가 끼면 이름은 릴리스를 가리킬 뿐이다.
_CLAIM_RE = {
    name: re.compile(re.escape(name)
                     + r'(?:은|는|이|가|의)?\s*(?:전년|전월|누계|각각|대비|상승률|증가율)?'
                       r'\s*(?:대비)?\s*[-]?\d')
    for name in ()
}


def _headline_claims(text):
    text = text.translate(_MINUS)
    hits = set()
    for name in HEADLINE_NAMES:
        pat = _CLAIM_RE.get(name)
        if pat is None:
            pat = re.compile(
                re.escape(name)
                + r'(?:은|는|이|가|의)?\s*(?:전년|전월|누계|각각|대비|상승률|증가율)?'
                  r'\s*(?:대비)?\s*[-]?\d')
            _CLAIM_RE[name] = pat
        if pat.search(text):
            hits.add(name)
    return sorted(hits)


def check_numbers(html, man, dumps):
    """헤드라인은 지표에 하드바인딩, 부차 수치는 인용한 릴리스 원문과 집합 대조.

    표식 없는 문단의 수치는 전부 막는다 — 표식 밖으로 도피하면 검사가 없어진다.
    """
    v = []
    root = D.parse(html)

    for el in D.find_marked(root, 'data-metric'):
        mid = el.attrs['data-metric']
        period = el.attrs.get('data-period')
        printed = _numbers(el.text())
        if mid not in M.METRICS:
            v.append(f'알 수 없는 지표 id: {mid}')
            continue
        if mid not in man:
            v.append(f'{mid} 은 이번 수집 manifest 에 없다 — 인용할 수 없다')
            continue
        if not period or period not in man[mid]:
            v.append(f'{mid} 의 기준월 {period!r} 이 수집되지 않았다')
            continue
        fact = man[mid][period]
        allowed = M.allowed_values(man, mid, period)
        bad = [p for p in printed if p not in allowed]
        if bad:
            v.append(f'{mid}({fact["label_ko"]}) 에 붙은 수치가 수집값과 다르다: '
                     f'{", ".join(sorted(bad))} — 수집값 {_canon(fact["value"])}{fact["unit"]}')
            continue
        # 절댓값으로 적는 것은 정상 표기다 — 「1.5% 내렸습니다」. 그러나 방향어가
        # 부호와 어긋나면 원문과 정반대의 문장이 된다. 부호를 지운 표기에는 방향어
        # 정합을 요구한다(codex 2차 검토에서 실제로 뚫렸다).
        if fact.get('kind') == 'change' and fact['value'] != 0:
            signed = {p for p in printed if p.startswith('-')}
            if not signed and printed:
                falling, rising = _governing_direction(el)
                want_fall = fact['value'] < 0
                if want_fall and rising and not falling:
                    v.append(f'{mid}({fact["label_ko"]}) 는 {_canon(fact["value"])}'
                             f'{fact["unit"]} 인데 문단이 상승으로 서술한다')
                elif not want_fall and falling and not rising:
                    v.append(f'{mid}({fact["label_ko"]}) 는 {_canon(fact["value"])}'
                             f'{fact["unit"]} 인데 문단이 하락으로 서술한다')

    for el in D.find_marked(root, 'data-cite'):
        key = el.attrs['data-cite']
        if key not in dumps:
            v.append(f'수집되지 않은 릴리스를 인용했다: {key}')
            continue
        pool = _numbers(dumps[key])
        printed = _numbers(_text_without_marked(el, 'data-metric'))
        bad = [p for p in printed if p not in pool and p.lstrip('-') not in pool]
        if bad:
            v.append(f'{key} 원문에 없는 수치: {", ".join(sorted(bad))}')
        # 부차 수치 층은 원문 대조만 받는다 — 그래서 릴리스 안의 **다른** 값을
        # 헤드라인 이름표에 붙이는 창작이 통과한다(달걀 -14.4% → 「소비자물가 14.4%
        # 상승」). 헤드라인 지표의 이름을 부르는 문단에는 바인딩을 요구해 그 구멍을
        # 좁힌다.
        # 바인딩이 하나 있다고 문단 전체를 면제하지 않는다 — 정상 표식 하나를 곁들여
        # 나머지 참칭 검사를 건너뛰던 우회(codex 3차).
        if printed:
            named = _headline_claims(_text_without_marked(el, 'data-metric'))
            if named:
                v.append(f'{key} 인용 문단이 헤드라인 지표({", ".join(named)})에 수치를 '
                         '붙이면서 data-metric 바인딩이 없다 — 헤드라인 수치는 '
                         '지표에 묶어야 한다')

    loose = _numbers(_text_without_marked(root, 'data-metric', 'data-cite'))
    if loose:
        v.append(f'출처 표식 없는 수치: {", ".join(sorted(loose))} — '
                 'data-metric 또는 data-cite 안에서만 수치를 쓴다')
    return v


def _text_without_marked(el, *attrs):
    """표식이 붙은 가지를 뺀 나머지 텍스트."""
    if el.hidden:
        return ''
    if any(a in el.attrs for a in attrs):
        return ''
    out = []
    for child in el.children:
        if isinstance(child, str):
            out.append(child)
        else:
            body = _text_without_marked(child, *attrs)
            # 블록은 띄우고 구절 요소는 붙인다 — `dom.Element.text()` 와 같은 규칙이다.
            # 전부 띄우면 `14.<b>4</b>%` 가 14 와 4 로 쪼개져 없는 수치가 생기고,
            # 전부 붙이면 인접 표 칸의 0.5·0.9 가 「0.50.9」가 된다.
            out.append(f' {body} ' if child.tag in D._BLOCKISH else body)
    return ''.join(out)


# ── 수집 완전성 ──

def check_release_coverage(index):
    """발견됐는데 못 받은 tier 1 은 발행을 막는다.

    이게 없으면 NBS·PBoC·해관이 전부 WAF 에 막힌 주에도 「이번 주는 발표가 없었다」
    한 문단으로 멀쩡히 발행된다. 이 파이프라인에서 가장 위험한 조용한 실패다.
    """
    v = []
    if index.get('index_ok') is False:
        v.append('릴리스 인덱스를 읽지 못했다 — 「발표 없음」과 구분되지 않으므로 발행을 막는다')
    if not index.get('releases'):
        # 인덱스는 늘 최근 릴리스 십여 건을 싣는다. 0건이면 조용한 주가 아니라 고장이다.
        v.append('릴리스 원장이 비었다 — 인덱스가 깨진 것으로 본다')
    for rel in index.get('releases', []):
        if rel.get('tier') != 1 or not rel.get('discovered'):
            continue
        if rel.get('fetch_status') != 'ok':
            v.append(f'tier 1 릴리스를 받지 못했다: {rel["key"]} '
                     f'(status={rel.get("fetch_status")}, http={rel.get("http_status")}) '
                     '— 「발표 없음」과 구분되지 않으므로 발행을 막는다')
    return v


# ── 시황 상한 ──

RECAP_CAP = 0.25


def _block_chars(root, name):
    total = 0
    for el in D.walk(root):
        if el.attrs.get('data-block') == name and not el.hidden:
            total += len(el.text().strip())
    return total


# 시황은 **상품 이름 + 움직임**이다. 이름만으로 세면 A09 의 「환율이 움직일 수 있는
# 범위를…」 같은 제도 설명이 시황으로 잡히고, 움직임만으로 세면 교재 전체가 잡힌다.
_MARKET_CUE = re.compile(
    r'상해종합|상하이종합|선전성분|심천성분|CSI\s*300|항셍|HSCEI|국채 금리'
    r'|위안(?:화)?\s*환율|역외 위안|역내 위안|달러/위안|CNH|CNY'
    r'|철광석|구리 선물|구리 값|금 선물|유가')
_MOVE_CUE = re.compile(r'올랐|내렸|상승|하락|급등|급락|약세|강세|반등|되돌림|[\d]')

_RECAP_TAGS = ('p', 'li', 'td', 'th', 'h2', 'h3', 'h4', 'blockquote', 'figcaption', 'dd')


def _stray_market_chars(root):
    total = 0
    for el in D.walk(root):
        if el.tag not in _RECAP_TAGS or el.hidden:
            continue
        if _in_block(el, 'markets'):
            continue
        text = el.text().strip()
        if _MARKET_CUE.search(text) and _MOVE_CUE.search(text):
            total += len(text)
    return total


def _in_block(el, name):
    node = el
    while node is not None:
        if node.attrs.get('data-block') == name:
            return True
        node = node.parent
    return False


def check_recap_cap(html):
    root = D.parse(html)
    markets = _block_chars(root, 'markets') + _stray_market_chars(root)
    body = len(root.text().strip())
    if not body:
        return ['본문이 비었다']
    ratio = markets / body
    if ratio > RECAP_CAP:
        return [f'시황 비중이 {ratio:.0%}로 상한 {RECAP_CAP:.0%}를 넘는다 '
                f'({markets}자 / {body}자) — 이건 학습 리포트다']
    return []


# ── 포지션 어휘 ──

# US 의 BANNED_GRADE_WORDS 는 자산군 등급어라 매수·매도·목표주가를 못 잡는다(codex C6).
BANNED_POSITION = (
    '비중확대', '비중축소', '소폭확대', '소폭축소', '오버웨이트', '언더웨이트',
    '목표주가', '매수 추천', '매도 추천', '매수 의견', '매도 의견',
    '손절', '익절', '진입 시점', '롱 포지션', '숏 포지션',
)

# 낱말만으로는 못 가르는 것들. 「목표가」는 목표 + 주격조사와 글자가 같아서
# (「목표가 정해지면」) 뒤에 수치가 올 때만 목표주가로 읽는다.
BANNED_POSITION_RE = (
    ('목표가', re.compile(r'목표가\s*[\d]')),
    ('매수 권유', re.compile(r'매수[^.]{0,14}?(?:권합|권한|권유|추천|제안)')),
    ('매도 권유', re.compile(r'매도[^.]{0,14}?(?:권합|권한|권유|추천|제안)')),
    ('비중 조절 권유', re.compile(r'비중\s*(?:확대|축소)[^.]{0,12}?(?:권합|권한|권유|추천|제안)')),
)
# 「스프레드가 소폭확대됐다」처럼 서술로 쓰인 자리는 뺀다 — 문맥 없는 부분문자열 금지는
# 정상 문장을 매일 잡는다(US 게이트가 codex 검토에서 배운 것).
_DESCRIPTIVE = r'(?![되돼됐된하한할해했로])'
_OW_UW = re.compile(r'(?<![A-Za-z])(OW|UW)(?![A-Za-z])')


def check_position_vocab(html):
    # 공백을 눌러 둔다 — 「매수\n추천」처럼 줄바꿈을 끼워 낱말 검사를 피하는 우회가 있다.
    text = re.sub(r'\s+', ' ', D.visible_text(html))
    found = [w for w in BANNED_POSITION if re.search(re.escape(w) + _DESCRIPTIVE, text)]
    found += [label for label, pat in BANNED_POSITION_RE if pat.search(text)]
    if _OW_UW.search(text):
        found.append('OW/UW')
    if not found:
        return []
    return [f'포지션 어휘가 나왔다({", ".join(sorted(set(found)))}) — '
            '이 리포트는 설명하지 판정하지 않는다. 종목 판정은 thesis 몫이다']


# ── 용어 풀이 ──

# 뉴스에도 잘 안 나오는 중국 고유어. 첫 등장에서 한 번 푼다.
CHINA_GLOSS = (
    '총사회융자', '신용 임펄스', 'LGFV', '후커우', '중간가 고시', '양회',
    '중앙경제공작회의', '이구환신', '반내권', '신3종', '지방정부 특별채',
    '역RP', '지급준비율', '현방판매', '선분양',
)
GLOSS_WINDOW = 60
_GLOSS_CUE = re.compile(r'[(（]|,\s*곧|—\s*|은/는\s*말|이란|라는 말|를 뜻하|을 뜻하'
                        r'|를 말하|을 말하|즉\s')


def check_gloss(html, terms=CHINA_GLOSS):
    text = D.visible_text(html)
    v = []
    for term in terms:
        m = re.search(re.escape(term), text)
        if not m:
            continue
        window = text[m.end():m.end() + GLOSS_WINDOW]
        if not _GLOSS_CUE.search(window):
            v.append(f'「{term}」 을 처음 쓰면서 풀지 않았다 — 첫 등장에서 한 번 푼다')
    return v
