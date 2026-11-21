"""모든 숫자 발행 전 확인 — 숫자열·수량 문법, 칸 분류, 수정 이력 (2026-11-20, US 루틴 1차).

글에 보이는 숫자 하나하나가 어디서 왔는지 **배타 칸 하나**에 넣는다:
  T 표 대조(기존 check_numbers 가 실제로 맞춰 본 노드) · R 자료 칸(`data-ref`) · A 기사 숫자 목록(`data-src=news`)
  · G 텔레그램 원글 숫자 목록(`data-tg`) · W 검색 발췌(`data-src=web:<id>`) · X 세지 않은 숫자(날짜·이름·`data-nx=enum`·구역)
  · U 확인 불가(나머지 전부 — 모르면 U 다).
세는 단위는 **숫자열**(보이는 글의 `\\d[\\d,]*(\\.\\d+)?` 최대 일치, 앞 0 생략 소수 `.5` 포함), 값·판정 단위는 **수량**
(부호·숫자열·배율 사슬·단위). 숫자열은 정확히 한 수량에 속한다 — 두 층 모두 칸 합 == 총수(어긋나면 InvariantError).

보고서별 부분(칸 풀이기 `us.facts`, 표 대조 노드 = `us.number_audit` 의 trace)은 밖에서 넣는다.
설계: docs/superpowers/specs/2026-11-20-number-sources.md
"""
import hashlib
import html as _html
import json
import os
import re
from dataclasses import dataclass, field

EFFECTIVE = '2099-12-31'          # 자리표시 — 병합 뒤 첫 발행일로 바꾼다(설계 §7.1, 그 전 글은 not_run)
FORMAT = 'numsrc/1'

CLASSES = ('table', 'data', 'level', 'article', 'telegram', 'web', 'excluded', 'unknown')
CLASS_KO = {'table': '자료로 확인', 'data': '자료로 확인', 'level': '어림선', 'article': '기사와 일치', 'telegram': '텔레그램 글과 일치',
            'web': '검색 발췌와 일치', 'excluded': '세지 않은 숫자', 'unknown': '확인 불가'}
# U 의 이유(닫힌 분류 — 설계 §7.1). 기록·알림은 이 이름만 싣는다
U_REASONS = ('표식 없음', '표식 오류', '자료와 다름', '칸 없음', '칸 무효', '기사 목록에 없음', '목록 없음', '발췌에 없음',
             '코드 블록(표식 없음)', '선언 무효')
UNKNOWN_LIST, UNKNOWN_LEN = 60, 80
COMMON_MAX = 31                   # 단위 없는 31 이하 정수 — 「흔한 수」로 따로 센다


class InvariantError(Exception):
    """칸 합이 총수와 다르다 — 검사기 결함이다(exit 2, 통과로 치지 않는다)."""


class InputError(Exception):
    """입력으로 판정할 수 없다(exit 2)."""


# ── 보는 글 ─────────────────────────────────────────────────────────────

# 전각 → 반각(글자 수 같음, us.number_audit._WIDE 와 같은 표)
_WIDE = str.maketrans({**{chr(0xFF10 + i): str(i) for i in range(10)},
                       '．': '.', '，': ',', '％': '%', '＋': '+', '－': '-', '＄': '$'})


def norm(text):
    return (text or '').translate(_WIDE)


# ── 숫자열 ──────────────────────────────────────────────────────────────

# 앞 0 생략 소수는 공백·괄호·부호·$·문두 뒤에서만(us/number_audit.py:40-43 의 규칙 그대로 — 「했다.5%」의 5% 는 5%)
_LEAD = r'(?:(?<=[\s(\[~+\-−－–$])|^)'
RUN = re.compile(r'\d(?:[\d,]*\d)?(?:\.\d+)?|' + _LEAD + r'\.\d+')


def runs(text):
    """[(start, end)] — 보이는 글의 숫자열 전부."""
    return [(m.start(), m.end()) for m in RUN.finditer(norm(text))]


def run_value(s):
    """「1,234.5」→ 1234.5. 천 단위 구분이 아닌 쉼표(「3,4」)는 None(값을 정할 수 없다)."""
    if ',' in s and not re.fullmatch(r'\d{1,3}(?:,\d{3})+(?:\.\d+)?', s):
        return None
    try:
        return float(s.replace(',', ''))
    except ValueError:
        return None


# ── 수량 ────────────────────────────────────────────────────────────────

_SCALE_KO = {'조': 1e12, '억': 1e8, '만': 1e4, '천': 1e3}
_SCALE_EN = {'K': 1e3, 'M': 1e6, 'B': 1e9}
# 배율 한 조각: 천만·백만·천억 같은 합성까지. 뒤 조각은 앞보다 작아야 이어진다
_KO_SCALE = r'(?:[천백](?:조|억|만)|조|억|만|천)'
# 단위 — 닫힌 목록(긴 것부터). 세는 말은 선언(enum)·기사 대조의 「개수」 갈래
UNITS = ('%포인트', '%p', '%', 'bp', '포인트', '거래일', '개월', '배럴', '달러', '유로', '파운드', '위안', '온스',
         '엔', '원', '배', '건', '개', '종', '가지', '곳', '명', '차례', '회', '번', '석', '위', '년', '주', '일', '분기',
         '시간', '분', '초', '월', '시', '세', '선', '대', '층', '호', 'p')
COUNT_WORDS = frozenset({'종', '개', '가지', '곳', '명', '건', '차례'})     # enum 선언이 받는 세는 말(설계 §6)
_UNIT_ALIAS = {'%포인트': '%p', '포인트': 'p'}
_UNIT_RE = re.compile(r'(\s?)(' + '|'.join(re.escape(u) for u in UNITS) + r')(?![A-Za-z])')
_SIGN = '+-−－–'
_RANGE = re.compile(r'\s?(?:[~\-–]|에서)\s?')


@dataclass
class Q:
    """수량 하나 — 위치는 그 블록의 보는 글 기준."""
    start: int
    end: int
    runs: list
    raw: str
    value: object          # float | None(값을 정할 수 없음)
    quantum: float         # 인쇄된 마지막 자리 1단위의 절대 크기(배율 포함)
    sign: str              # '' | '+' | '-'
    unit: str              # 정규화한 단위('' = 없음), '$' 앞붙임은 '달러'
    scale: float = 1.0
    unit_inherited: bool = False
    lead_dot: bool = False
    code: str = ''         # X-코드 갈래(date·time·term·id) — 비면 값 수량
    sig: int = 0           # 유효숫자 수(어림선 |lvl 판정)

    def printed(self):
        return self.raw


def _decimals(s):
    return len(s.split('.')[1]) if '.' in s else 0


def _sig_digits(s):
    d = s.replace(',', '').replace('.', '').lstrip('0')
    return len(d.rstrip('0')) if d else 0


def quantities(text, terms=()):
    """보이는 글 → [Q]. 숫자열마다 정확히 한 수량. terms = 고정 이름(「10년물」「S&P 500」) — 그 안 숫자열은 X-코드."""
    t = norm(text)
    rs = runs(t)
    taken = [False] * len(rs)
    out = []
    # X-코드 먼저 — 고정 이름·날짜·시각·식별자. 숫자열 단위로 덮는다
    spans = _code_spans(t, terms)
    for kind, s, e in spans:
        idx = [i for i, (a, b) in enumerate(rs) if not taken[i] and a >= s and b <= e]
        if not idx:
            continue
        for i in idx:
            taken[i] = True
        out.append(Q(s, e, [rs[i] for i in idx], t[s:e], None, 0.0, '', '', code=kind))
    i = 0
    while i < len(rs):
        if taken[i]:
            i += 1
            continue
        a, b = rs[i]
        comps = [(a, b)]
        num = t[a:b]
        val = run_value(num) if not num.startswith('.') else float('0' + num)
        lead = num.startswith('.')
        pos = b
        scale_last = 1.0
        total = None if val is None else 0.0
        # 배율 사슬: 숫자열 + 한국어 배율, 다음 숫자열이 더 작은 배율로 이어지면 같은 수량
        m = re.match(_KO_SCALE, t[pos:])
        if m:
            sc = _ko_scale(m.group(0))
            scale_last = sc
            if total is not None:
                total += val * sc
            pos += m.end()
            j = i + 1
            while j < len(rs) and not taken[j]:
                gap = t[pos:rs[j][0]]
                if gap not in ('', ' '):
                    break
                m2 = re.match(_KO_SCALE, t[rs[j][1]:])
                nxt = run_value(t[rs[j][0]:rs[j][1]])
                if not m2 or _ko_scale(m2.group(0)) >= scale_last:
                    # 「2억8200」처럼 배율 없는 꼬리 — 같은 수량(마지막 조각 배율 1)
                    # 「80만 3000원」 — 꼬리는 앞 배율보다 작은 정수일 때만
                    if (not m2 and nxt is not None and '.' not in t[rs[j][0]:rs[j][1]]
                            and nxt < scale_last and (gap == '' or nxt >= 100)):
                        comps.append(rs[j])
                        if total is not None:
                            total += nxt
                        scale_last = 1.0
                        pos = rs[j][1]
                        j += 1
                    break
                sc2 = _ko_scale(m2.group(0))
                comps.append(rs[j])
                if total is not None and nxt is not None:
                    total += nxt * sc2
                else:
                    total = None
                scale_last = sc2
                num = t[rs[j][0]:rs[j][1]]
                pos = rs[j][1] + m2.end()
                j += 1
            i = j - 1
        else:
            m = re.match(r'([KMB])(?![A-Za-z])', t[pos:])
            if m:
                scale_last = _SCALE_EN[m.group(1)]
                total = None if val is None else val * scale_last
                pos += m.end()
            else:
                total = val
        quantum = 10 ** -_decimals(num) * scale_last
        # 부호 — 바로 앞 글자, 그 앞이 숫자·글자가 아닐 때만(「3-6개월」은 범위)
        st, sign = a, ''
        if a > 0 and t[a - 1] in _SIGN and _sign_ok(t, a - 1):
            sign = '+' if t[a - 1] == '+' else '-'
            st = a - 1
        dollar = False
        if st > 0 and t[st - 1] == '$':
            dollar, st = True, st - 1
            if st > 0 and t[st - 1] in _SIGN and _sign_ok(t, st - 1) and not sign:
                sign = '+' if t[st - 1] == '+' else '-'
                st -= 1
        unit = ''
        mu = _UNIT_RE.match(t, pos)
        if mu and not (mu.group(2) == 'p' and dollar):
            unit = _UNIT_ALIAS.get(mu.group(2), mu.group(2))
            pos = mu.end()
        if dollar and not unit:
            unit = '달러'
        if total is not None and sign == '-':
            total = -total
        q = Q(st, pos, comps, t[st:pos], total, quantum, sign, unit, scale_last, lead_dot=lead,
              sig=_sig_digits(''.join(t[x:y] for x, y in comps)))
        out.append(q)
        i += 1
    out.sort(key=lambda q: q.start)
    # 범위 「3~6개월」: 앞 수량은 뒤 수량의 단위를 함께 쓴다
    for k in range(len(out) - 1):
        p, n = out[k], out[k + 1]
        if p.code or n.code or p.unit or not n.unit:
            continue
        if _RANGE.fullmatch(t[p.end:n.start] or 'x'):
            p.unit, p.unit_inherited = n.unit, True
    return out


def _sign_ok(t, i):
    """t[i] 의 부호 글자가 부호인가 — `us/number_audit._TOK` 와 같은 경계: 앞이 ASCII 글자·숫자·밑줄이거나 「숫자.」「숫자,」
    이면 부호가 아니다(「3-6개월」은 범위). **한글 뒤는 부호다**(「나스닥-0.42%」 — 화면은 음수다)."""
    if i == 0:
        return True
    p = t[i - 1]
    if p.isascii() and (p.isalnum() or p == '_'):
        return False
    return not (p in '.,' and i >= 2 and t[i - 2].isdigit())


def _ko_scale(word):
    if len(word) == 2:
        return {'천': 1e3, '백': 1e2}[word[0]] * _SCALE_KO[word[1]]
    return _SCALE_KO[word]


# 날짜·시각·분기·회계연도 — 코드가 아는 문법(X-코드, 설계 §6)
_CODE = (
    ('date', re.compile(r'\d{4}-\d{2}-\d{2}')),
    ('date', re.compile(r'\d{4}년\s?\d{1,2}월\s?\d{1,2}일')),
    ('date', re.compile(r'\d{4}년\s?\d{1,2}월')),
    ('date', re.compile(r'\d{1,2}월\s?\d{1,2}일')),
    ('date', re.compile(r'\d{1,2}/\d{1,2}(?=[\s~·,)(]|$)')),
    ('date', re.compile(r'(?:19|20)\d{2}년(?:\s?\d분기|\s?[상하]반기)?')),
    ('date', re.compile(r'(?<!\d)\d{2}년\s?\d분기')),
    ('date', re.compile(r'(?<![\d.])\d분기')),
    ('date', re.compile(r'(?<![\d.])(?:[1-4]Q|Q[1-4])(?:\s?(?:19|20)?\d{2})?(?![A-Za-z\d])')),
    ('date', re.compile(r'FY\s?(?:19|20)?\d{2}')),
    ('date', re.compile(r'(?<![\d.,])\d{1,2}월(?!\s?\d{1,2}일)')),
    ('date', re.compile(r'(?<![\d.,])(?:[12]?\d|3[01])일(?!\s?(?:연속|째|간|동안|만에|이상|이내|거래일))')),
    ('time', re.compile(r'(?<!\d)\d{1,2}:\d{2}(?::\d{2})?(?!\d)')),
    ('time', re.compile(r'(?:오전|오후|새벽|밤|저녁|아침)\s?\d{1,2}시(?:\s?\d{1,2}분)?(?:\s?\d{1,2}초)?')),
    ('time', re.compile(r'(?<![\d.])\d{1,2}시\s?\d{1,2}분')),
    ('time', re.compile(r'(?<![\d.])\d{1,2}시(?=\s?(?:\d|[(]|ET|KST|GMT|기준|현재|무렵|께|쯤|에|부터|까지))')),
)
# 식별자 — 영문자에 붙은 숫자열(「CLF27」「912810UZ9」「H100」「Q3」). 배율 K·M·B 와 단위 p·x·bp 는 값이다
_ID = re.compile(r'(?<![A-Za-z\d])(?:[A-Za-z]+[\d][\dA-Za-z\-]*|[\d]+[A-Za-z][\dA-Za-z\-]*)(?![A-Za-z\d])')
_VALUE_SUFFIX = re.compile(r'^[\d.,]+(?:[KMBx]|bp|p|bps)$')


def _code_spans(t, terms):
    out = []
    for term in sorted({x for x in terms if x}, key=len, reverse=True):
        for m in re.finditer(re.escape(norm(term)), t):
            out.append(('term', m.start(), m.end()))
    for kind, rx in _CODE:
        for m in rx.finditer(t):
            out.append((kind, m.start(), m.end()))
    for m in _ID.finditer(t):
        w = m.group(0)
        if _VALUE_SUFFIX.match(w) or not re.search(r'\d', w):
            continue
        out.append(('id', m.start(), m.end()))
    # 겹치면 앞선(긴 고정 이름 → 날짜 → 식별자 순으로 넣은) 것이 이긴다
    chosen = []
    for kind, s, e in out:
        if any(s < b and a < e for _, a, b in chosen):
            continue
        chosen.append((kind, s, e))
    return sorted(chosen, key=lambda x: x[1])


# ── 블록 ────────────────────────────────────────────────────────────────

@dataclass
class Seg:
    start: int
    end: int
    stack: list
    kind: object


@dataclass
class Block:
    text: str
    segs: list
    where: str = ''                  # 'body' | 'title' | 'meta'

    def stack_at(self, i):
        for s in self.segs:
            if s.start <= i < s.end:
                return s.stack
        return []

    def segs_in(self, a, b):
        return [s for s in self.segs if s.start < b and a < s.end]


def blocks_of(stream):
    """us.number_audit._Stream.stream → [Block]. None 은 블록 경계, 그 밖은 (글, 조상, 갈래)."""
    out, cur, segs = [], [], []
    pos = 0

    def flush():
        nonlocal cur, segs, pos
        if cur:
            out.append(Block(''.join(cur), segs, 'body'))
        cur, segs, pos = [], [], 0

    for idx, item in enumerate(stream):
        if item is None:
            flush()
            continue
        data, stack, kind = item
        data = norm(data)
        segs.append(Seg(pos, pos + len(data), stack, (idx, kind)))
        cur.append(data)
        pos += len(data)
    flush()
    return out


# ── 표식 ────────────────────────────────────────────────────────────────

MARK_ATTRS = ('data-ref', 'data-src', 'data-nx')


def is_marker(n):
    return n.tag == 'span' and any(a in n.attrs for a in MARK_ATTRS)


def markers_over(block, q):
    """수량이 놓인 글자들의 표식 집합들 — 글자마다 (표식 노드들). 경계 판정용."""
    sets = []
    for s in block.segs_in(q.start, q.end):
        sets.append(tuple(n for n in s.stack if is_marker(n)))
    return sets


# ── 분류 결과 ───────────────────────────────────────────────────────────

@dataclass
class Item:
    q: Q
    cls: str
    why: str = ''                    # U 이유 · X 갈래 · R 의 칸 이름
    where: str = 'body'
    sentence: str = ''               # 이력 대조용(가린 문장) — 기록에 싣지 않는다
    sent_index: int = 0
    detail: dict = field(default_factory=dict)


def tally(items):
    """수량 칸·숫자열 칸 집계 + 불변식. 표 칸(T)과 자료 칸(R)은 기록에서 따로 센다."""
    q = {c: 0 for c in CLASSES}
    r = {c: 0 for c in CLASSES}
    for it in items:
        q[it.cls] += 1
        r[it.cls] += len(it.q.runs)
    total_q, total_r = len(items), sum(len(it.q.runs) for it in items)
    if sum(q.values()) != total_q or sum(r.values()) != total_r:
        raise InvariantError('칸 합이 총수와 다르다')
    return dict(q, total=total_q), dict(r, total=total_r)


def check_sums(counts):
    """기록·알림이 받은 칸 사전이 약속한 꼴인가 — 칸이 모두 0 이상 정수이고 합 == total."""
    if not isinstance(counts, dict):
        return False
    vals = [counts.get(c) for c in CLASSES] + [counts.get('total')]
    if any(not isinstance(v, int) or isinstance(v, bool) or v < 0 for v in vals):
        return False
    return sum(vals[:-1]) == vals[-1]


def clip(text, n=UNKNOWN_LEN):
    text = ' '.join((text or '').split())
    return text if len(text) <= n else text[:n - 1] + '…'


# ── 수정 이력(문장 단위, 11/20 사용자 승인 판) ─────────────────────────────
#
# 첫 판에서 U 였던 수량마다 최종본에서 셋 중 하나: 고쳐서 확인(이제 U 가 아닌 칸) / 문장째 사라짐 / 그대로 확인 불가.
# 대응은 문장 단위 — (수량을 가린 문장 글, 문장 안 몇째 수량). 가린 문장이 한쪽에 둘 이상이면 그 수량들은 「이력 확인 불가」다.
# 「변경 없음」으로 적지 않는다. 문장 글은 기록에 싣지 않는다(지운 초안 문장은 공개된 적이 없다) — 건수와 인쇄 꼴만.

HISTORY_KEYS = ('first_unknown', 'fixed', 'gone', 'still', 'ambiguous')
_SENT_END = re.compile(r'(?<=[다요음함됨임])\.(?=\s|$)|[。!?](?=\s|$)')


def sentences(text):
    out, i = [], 0
    for m in _SENT_END.finditer(text):
        out.append((i, m.end()))
        i = m.end()
    if text[i:].strip():
        out.append((i, len(text)))
    return out


def mask_sentence(text, a, b, qs):
    """문장 글에서 **값 수량** 자리를 #로 — 값만 고친 문장을 같은 문장으로 알아본다. 날짜·이름 같은 X-코드 글자는
    그대로 둔다 — 가리면 「S&P 500은 5%」와 「러셀 2000은 5%」가 같은 문장이 된다(codex 리뷰 전 자체 점검)."""
    parts, pos = [], a
    for q in qs:
        if q.code:
            continue
        parts.append(text[pos:q.start])
        parts.append('#')
        pos = q.end
    parts.append(text[pos:b])
    return ' '.join(''.join(parts).split())


def history(first_items, final_items):
    """→ {first_unknown, fixed, gone, still, ambiguous, gone_printed}. 합 == first_unknown 을 확인한다."""
    def index(items):
        by = {}
        for it in items:
            by.setdefault((it.where, it.sentence), []).append(it)
        return by
    f_by, n_by = index(first_items), index(final_items)
    # 한 문장 묶음 = 그 문장의 수량들(자리 순). 같은 가린 문장이 문서에 둘 이상 있으면 묶음이 섞인다
    f_count = _sentence_counts(first_items)
    n_count = _sentence_counts(final_items)
    out = {k: 0 for k in HISTORY_KEYS}
    gone = []
    for it in first_items:
        if it.cls != 'unknown':
            continue
        out['first_unknown'] += 1
        key = (it.where, it.sentence)
        if f_count.get(key, 0) != 1 or n_count.get(key, 0) > 1 or not it.sentence:
            out['ambiguous'] += 1
            continue
        if n_count.get(key, 0) == 0:
            out['gone'] += 1
            gone.append(clip(it.q.raw, 20))
            continue
        cand = [x for x in n_by.get(key, []) if x.sent_index == it.sent_index]
        if len(cand) != 1:
            out['ambiguous'] += 1
        elif cand[0].cls == 'unknown':
            out['still'] += 1
        else:
            out['fixed'] += 1
    if out['fixed'] + out['gone'] + out['still'] + out['ambiguous'] != out['first_unknown']:
        raise InvariantError('수정 이력 합이 첫 판 확인 불가 수와 다르다')
    out['gone_printed'] = gone[:12]
    return out


def _sentence_counts(items):
    """(구역, 가린 문장) → 그 문장이 문서에 나온 횟수. 수량 묶음의 첫 수량(sent_index 0)으로 센다."""
    seen = {}
    for it in items:
        if it.sent_index == 0:
            k = (it.where, it.sentence)
            seen[k] = seen.get(k, 0) + 1
    return seen


def valid_history(h):
    if h == 'unverifiable':
        return True
    if not isinstance(h, dict):
        return False
    vals = [h.get(k) for k in HISTORY_KEYS]
    if any(not isinstance(v, int) or isinstance(v, bool) or v < 0 for v in vals):
        return False
    return vals[1] + vals[2] + vals[3] + vals[4] == vals[0]


def sha256_text(s):
    return hashlib.sha256(s.encode('utf-8')).hexdigest()


def canonical_of(html):
    """(시장 경로 'posts'|'news', 날짜) — 글의 canonical 주소. 첫 판이 같은 글인지 가르는 데 쓴다."""
    m = re.search(r'<link\s+rel="canonical"\s+href="[^"]*/(posts|news)/(\d{4}-\d{2}-\d{2})\.html"', html or '')
    return (m.group(1), m.group(2)) if m else (None, None)


def load_json(path):
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


def unescape(s):
    return _html.unescape(s or '')


def exists(path):
    return bool(path) and os.path.isfile(path)
