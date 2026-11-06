#!/usr/bin/env python3
"""발행 게이트 — 「유동성·수급」 섹션 (US 아침 브리프).

침묵이 기본값이다. 이 세션에 실을 H.4.1 회차·QRA 문서가 없으면 섹션을 열지 않고, 있으면 열어야 한다.
「실을 것」은 책(`liquidity/liquidity.json`)을 믿지 않고 **지금 저장소의 발행본 원장**으로 다시 계산한다 —
수집 뒤 다른 글이 같은 회차를 실었으면 `ledger_changed` 로 실패하고, 오케스트레이터가
`build_liquidity.py --recompute` → 섹션 재작성으로 복구한다.

막는 것: 책 없음·낡음·미완료인데 섹션/표식, 섹션 누락·중복·숨김, 표(회차 집합·머리·셀·캡션)가 책과 다른 것,
이례적 행·QRA 문서마다 표식 문단 정확히 하나가 아닌 것, 문단의 금액이 그 행·문서 값이 아닌 것(필수 값 누락 포함),
방향어가 부호와 반대인 것, 가이던스 표식·인용, 무표식 해석 문단, 「오늘」+수요일 값, 이 섹션 수치로 금리·달러를
단정하는 바닥선 문형, TBAC 견해를 결정으로 쓰는 것.

못 막는 것(명시): 바꿔 쓴 인과·반대 판정 — 발행 후 codex 검토 몫. 설계: docs/superpowers/specs/2026-11-07-us-liquidity-section.md.
"""

import html as _html
import re

from common.numbers import TAG_RE, strip_comments

from . import liquidity as L
from .number_audit import tokens
from .section import locate_section

SECTION_TITLE = '유동성·수급'
LEDGER_CHANGED = 'ledger_changed'

_MARK = re.compile(r'<[^>]*?\sdata-(?:liquidity-day|h41-release|qra-table|qra-doc|qra-guidance|guidance|liq|liq-row)'
                   r'(?=[\s=>/])', re.I)
_HIDDEN = re.compile(r'<[^>]*?(?:\shidden(?=[\s=>/])|aria-hidden\s*=\s*["\']?true'
                     r'|style\s*=\s*(?:"[^"]*|\'[^\']*)(?:display\s*:\s*none|visibility\s*:\s*hidden))[^>]*>', re.I)
# 표식은 정해진 요소에만(구현 검토 #2) — 다른 요소의 표식은 거부한다
_WRONG_HOST = re.compile(r'<(?!p\b)(\w+)\b[^>]*\sdata-(?:liq|qra-doc|qra-guidance)\s*=', re.I)
_P = re.compile(r'<p\b([^>]*)>(.*?)</p\s*>', re.S | re.I)
_ATTR = lambda name: re.compile(r'\b' + name + r'\s*=\s*"([^"]*)"', re.I)  # noqa: E731
_TABLE = re.compile(r'<table\b([^>]*)>(.*?)</table\s*>', re.S | re.I)
_CAPTION = re.compile(r'<div\b[^>]*class\s*=\s*"[^"]*\bcaption\b[^"]*"[^>]*>(.*?)</div\s*>', re.S | re.I)
_ROW = re.compile(r'<tr\b([^>]*)>(.*?)</tr\s*>', re.S | re.I)
_CELL = re.compile(r'<t([dh])\b[^>]*>(.*?)</t[dh]\s*>', re.S | re.I)

_UP = re.compile(r'늘|증가|확대|유입|불어|많아|상향|높')
_DOWN = re.compile(r'줄|감소|축소|유출|빠져|적어|하향|낮')
_CAUSAL = re.compile(r'(지급준비금|지준|TGA|역레포|유동성|재무부 일반계정)[^.。]{0,40}(때문에|탓에|영향으로|여파로)'
                     r'[^.。]{0,30}(금리|수익률|달러)')
_TODAY = re.compile(r'오늘')
_DECISION = re.compile(r'결정|확정')


def _text(fragment):
    return re.sub(r'\s+', ' ', _html.unescape(TAG_RE.sub(' ', fragment or ''))).strip()


def section(doc):
    return locate_section(strip_comments(doc or ''), SECTION_TITLE, exact=True)


def present(doc):
    d = strip_comments(doc or '')
    return section(d) is not None or bool(_MARK.search(d))


def expected(book, ledger):
    """지금 원장으로 다시 계산한 (H.4.1 회차 목록, QRA 문서 {kind: doc})."""
    h41_pool = [k for k in (book.get('h41') or {}).get('pool', []) if k not in ledger[0]][:L.H41_CAP]
    q = book.get('qra') or {}
    docs = {k: d for k, d in (q.get('candidates') or {}).items() if f'{q.get("round")}:{k}' not in ledger[1]}
    if not ({'borrowing', 'refunding'} & set(docs)):
        docs = {}
    return h41_pool, docs


def money_values(text, with_end=False):
    """문단의 금액(억 달러, 절댓값)과 위치. 「2조 9,628억 달러」는 하나로 합친다. 그 밖의 수치 토큰도 돌려준다.
    `with_end` 면 (시작, 값, 부호, 「달러」까지의 끝)."""
    toks = tokens(text)
    money, other = [], []
    i = 0
    while i < len(toks):
        t = toks[i]
        if t.unit == '조':
            v = abs(t.value) * 10000
            nxt = toks[i + 1] if i + 1 < len(toks) else None
            if nxt is not None and nxt.unit == '억' and nxt.start - t.end <= 2:
                v += abs(nxt.value)
                i += 1
                money.append((t.start, round(v, 1), t.sign or nxt.sign, _end(text, nxt.end)))
            else:
                money.append((t.start, round(v, 1), t.sign, _end(text, t.end)))
        elif t.unit == '억':
            money.append((t.start, round(abs(t.value), 1), t.sign, _end(text, t.end)))
        else:
            other.append(t)
        i += 1
    if not with_end:
        money = [m[:3] for m in money]
    return money, other


def _end(text, at):
    m = re.match(r'\s*달러', text[at:])
    return at + (m.end() if m else 0)


def _segments(text, default):
    """(시작, 행 키) — 행 이름이 나올 때마다 구간이 바뀐다. 첫 이름 전은 `default`."""
    hits = []
    for key, names in L.ROW_NAMES.items():
        for n in names:
            for m in re.finditer(re.escape(n), text):
                hits.append((m.start(), key))
    hits.sort()
    out = [(0, default)]
    for pos, key in hits:
        if out[-1][1] != key:
            out.append((pos, key))
    return out


def _seg_of(segs, pos):
    k = segs[0][1]
    for s, key in segs:
        if s <= pos:
            k = key
    return k


def _row_values(rnd, key):
    """{역할: {값}} — level = 잔고·주간 평균, change = 주간 변화 셋(부호 포함 원값은 따로)."""
    r = rnd['rows'][key]
    wc = rnd['flags']['rows'].get(key, {}).get('wed_chg')
    changes = [x for x in (wc, r['chg_wk'], r['chg_yr']) if x is not None]
    return {'level': {L.printed_eok(r['wed']), L.printed_eok(r['avg'])},
            'change': {L.printed_eok(x): x for x in changes}}


_AFTER_DIR = 14       # 금액 뒤 이 글자 안에 방향어가 있으면 변화액으로 읽는다


_NEG_AFTER = re.compile(r'^[가-힣]{0,3}\s*(?:지\s*않|지\s*못|가\s*아니|이\s*아니|은\s*아니|는\s*아니|도\s*아니|않|없)')


def _first_direction(seg):
    """구간에서 처음 나오는 **부정되지 않은** 방향어의 부호(없으면 0).

    「늘었다(감소가 아니다)」→ +1, 「증가하지 않고 100억 달러 줄었다」→ -1, 「감소하지 않고 … 늘었다」→ +1
    (구현 재검토 #2·3차 #1). 부정은 방향어 바로 뒤 몇 글자 안의 「…지 않/…가 아니/없」으로만 본다.
    """
    hits = sorted([(m.start(), m.end(), 1) for m in _UP.finditer(seg)] +
                  [(m.start(), m.end(), -1) for m in _DOWN.finditer(seg)])
    for start, end, sign in hits:
        if _NEG_AFTER.match(seg[end:end + 8]):
            continue
        return sign
    return 0


def _role_of_money(text, end, nxt):
    """금액 뒤(다음 금액·문장 끝 전까지 _AFTER_DIR 자)에 방향어가 있으면 변화액. 단 「…달러로/으로 늘었다」는
    그 수준에 이르렀다는 뜻이라 잔고다(재검토 #1)."""
    tail = text[end:min(end + _AFTER_DIR, nxt)]
    tail = re.split(r'(?<=다)\.', tail, maxsplit=1)[0]
    if re.match(r'\s*(?:으로|로)(?![가-힣])', tail) or re.match(r'\s*(?:으로|로)\s', tail):
        return 'level', 0
    d = _first_direction(tail)
    return ('change', d) if d else ('level', 0)


def _check_liq_paragraph(where, raw, rnd, key):
    """금액마다 역할(잔고 / 변화)을 뒤따르는 방향어로 가리고, 그 구간 행의 같은 역할 값과만 맞댄다.
    변화액은 부호·방향어가 원값의 부호와 같아야 한다(구현 검토 #1)."""
    v = []
    text = _text(raw)
    money, other = money_values(text, with_end=True)
    for t in other:
        v.append(f'{where}: 수치 「{t.raw}」 — 이 문단에는 표의 금액(억·조 달러)만 쓴다')
    segs = _segments(text, key)
    seen = {'level': set(), 'change': set()}
    starts = [m[0] for m in money] + [len(text)]
    for i, (pos, val, sign, end) in enumerate(money):
        k = _seg_of(segs, pos)
        if k not in rnd['rows']:
            v.append(f'{where}: {val:g}억 달러 — 어느 행의 값인지 모른다')
            continue
        role, dirn = _role_of_money(text, end, starts[i + 1])
        vals = _row_values(rnd, k)
        if role == 'level':
            if val not in vals['level']:
                v.append(f'{where}: {val:g}억 달러는 {L.ROW_KO[k]} 의 잔고가 아니다(변화액이면 늘었다·줄었다를 붙여라)')
                continue
            if sign:
                v.append(f'{where}: 잔고 {val:g}억 달러에 부호를 붙였다')
        else:
            if val not in vals['change']:
                v.append(f'{where}: {val:g}억 달러는 {L.ROW_KO[k]} 의 이 회차 변화액이 아니다')
                continue
            actual = vals['change'][val]
            want = 1 if actual > 0 else (-1 if actual < 0 else 0)
            if sign and (1 if sign == '+' else -1) != want:
                v.append(f'{where}: {L.ROW_KO[k]} 변화액 부호가 반대다({sign}{val:g}억 달러)')
            if want and dirn != want:
                v.append(f'{where}: {L.ROW_KO[k]} 이 {"늘었" if want > 0 else "줄었"}는데 반대로 썼다')
        seen[role].add((k, val))
    wc = rnd['flags']['rows'][key]['wed_chg']
    if (key, L.printed_eok(wc)) not in seen['change']:
        v.append(f'{where}: 잔고 주간 변화 {L.fmt_usd(wc, signed=True)} 가 없다(방향어와 함께)')
    if (key, L.printed_eok(rnd['rows'][key]['wed'])) not in seen['level']:
        v.append(f'{where}: 수요일 잔고 {L.fmt_usd(rnd["rows"][key]["wed"])} 가 없다')
    return v


QRA_REQUIRED = {'borrowing': ('borrow_bn', 'cash_bn'), 'refunding': ('total_bn', 'refund_bn', 'new_cash_bn')}


ROLE_WORDS = {
    'borrowing': (('borrow', ('순차입', '차입')), ('cash', ('현금잔고', '현금 잔고', '현금', '잔고')),
                  ('diff', ('추정보다', '전망보다', '보다', '대비'))),
    'refunding': (('total', ('발행', '총')), ('refund', ('만기', '상환', '갚')),
                  ('new_cash', ('신규', '새로', '조달')), ('size', ('년물',))),
}
_WIN = 16


def _qra_roles(doc, kind):
    if kind == 'borrowing':
        nxt = doc.get('next') or {}
        vp = doc.get('vs_prior') or {}
        return {'borrow': {L.printed_eok(x * 1000) for x in (doc['borrow_bn'], nxt.get('borrow_bn')) if x is not None},
                'cash': {L.printed_eok(x * 1000) for x in (doc['cash_bn'], nxt.get('cash_bn')) if x is not None},
                'diff': {L.printed_eok(vp['diff_bn'] * 1000)} if vp else set()}
    out = {r: {L.printed_eok(doc[f'{r}_bn'] * 1000)} for r in ('total', 'refund', 'new_cash')}
    for y, v in (doc.get('sizes_bn') or {}).items():
        out[f'size_{y}'] = {L.printed_eok(v * 1000)}
    return out


def _nearest_role(text, start, end, kind):
    """금액 앞뒤 _WIN 글자 안에서 가장 가까운 역할 낱말. 크기 역할은 바로 앞 「N년물」."""
    m = re.search(r'(\d{1,2})년물\s*$', text[max(0, start - 8):start])
    if kind == 'refunding' and m:
        return f'size_{m.group(1)}'
    best = None
    for role, words in ROLE_WORDS[kind]:
        if role == 'size':
            continue
        for w in words:
            i = text.rfind(w, max(0, start - _WIN), start)
            if i >= 0:
                gap = start - (i + len(w))
                best = min(best, (gap, 1, role)) if best else (gap, 1, role)
            j = text.find(w, end, end + _WIN)
            if j >= 0:
                gap = j - end
                best = min(best, (gap, 0, role)) if best else (gap, 0, role)
    return best[2] if best else None


_MONTH_KO = {m: i for i, m in enumerate(L._MONTHS, 1)}
_CMP_MONTH = re.compile(r'(\d{1,2})월[^.。]{0,8}?(?:보다|대비)')
_CMP_PRIOR = re.compile(r'(?:직전|지난|앞선|이전)[^.。]{0,8}?(?:보다|대비)')


def _check_qra_paragraph(where, raw, kind, doc):
    v = []
    text = _text(raw)
    money, other = money_values(text, with_end=True)
    if kind == 'tbac':
        if money or other:
            v.append(f'{where}: 자문위원회 견해 문단에는 수치를 쓰지 않는다(검증한 값이 아니다)')
        if '자문위원회' not in text:
            v.append(f'{where}: 「자문위원회(TBAC)」의 견해임을 밝혀라')
        if _DECISION.search(text):
            v.append(f'{where}: 자문위원회 견해를 재무부 결정처럼 썼다(결정·확정)')
        return v
    for t in other:
        v.append(f'{where}: 수치 「{t.raw}」 — 이 문단에는 발표문의 금액만 쓴다')
    roles = _qra_roles(doc, kind)
    seen = set()
    for pos, val, sign, end in money:
        role = _nearest_role(text, pos, end, kind)
        if role is None or role not in roles:
            v.append(f'{where}: {val:g}억 달러 — 무엇의 금액인지(차입·현금잔고·발행·상환·신규 조달·만기) 옆에 밝혀라')
            continue
        if val not in roles[role]:
            v.append(f'{where}: {val:g}억 달러는 이 발표문의 {role} 값이 아니다')
            continue
        if sign:
            v.append(f'{where}: 금액 {val:g}억 달러에 부호를 붙이지 않는다')
        seen.add((role, val))
    for k in QRA_REQUIRED[kind]:
        role = k[:-3]
        if (role, L.printed_eok(doc[k] * 1000)) not in seen:
            v.append(f'{where}: 필수 값 {L.fmt_usd(doc[k] * 1000)}({role}) 이 없다')
    if kind == 'borrowing':
        vp = doc.get('vs_prior')
        cmp_ = _CMP_MONTH.search(text) or _CMP_PRIOR.search(text)
        if any(r == 'diff' for r, _ in seen) and not cmp_:
            v.append(f'{where}: 직전 추정 대비 금액을 비교 기준(몇 월 추정보다) 없이 썼다')
        if cmp_ and not vp:
            v.append(f'{where}: 발표문에 직전 추정 대비 문장이 없는데 비교를 썼다')
        if vp and cmp_:
            if cmp_.re is _CMP_MONTH and int(cmp_.group(1)) != _MONTH_KO[vp['month']]:
                v.append(f'{where}: 비교 월이 {cmp_.group(1)}월 — 발표문은 {vp["month"]} 추정과 비교했다')
            tail = re.split(r'(?<=다)\.', text[cmp_.end():], maxsplit=1)[0]
            d = _first_direction(tail)
            if vp['direction'] == 'lower' and d != -1:
                v.append(f'{where}: 직전 추정보다 줄었는데 {"늘었다고" if d == 1 else "방향 없이"} 썼다')
            if vp['direction'] == 'higher' and d != 1:
                v.append(f'{where}: 직전 추정보다 늘었는데 {"줄었다고" if d == -1 else "방향 없이"} 썼다')
    return v


def _hidden_ancestor(doc, at):
    for m in _HIDDEN.finditer(doc, 0, at):
        name = re.match(r'<\s*([a-zA-Z][\w-]*)', m.group(0))
        if not name:
            continue
        depth, tag = 0, name.group(1).lower()
        for t in TAG_RE.finditer(doc, m.start()):
            nm = re.match(r'<\s*(/?)\s*([a-zA-Z][\w-]*)', t.group(0))
            if not nm or nm.group(2).lower() != tag or t.group(0).endswith('/>'):
                continue
            depth += -1 if nm.group(1) else 1
            if depth == 0:
                if t.start() > at:
                    return m.group(0)[:60]
                break
        else:
            return m.group(0)[:60]
    return None


def _table_rows(body):
    out = []
    for m in _ROW.finditer(body):
        cells = [(t, _text(c)) for t, c in _CELL.findall(m.group(2))]
        key = _ATTR('data-liq-row').search(m.group(1))
        out.append((key.group(1) if key else None, [c for t, c in cells if t == 'd'], [c for t, c in cells if t == 'h']))
    return out


def check(doc, book, report_date, ledger):
    """-> [위반]. `ledger` = liquidity.ledger_from_posts(repo, report_date)."""
    raw_doc = doc or ''
    doc = strip_comments(raw_doc)
    v = []
    # 주석·속성값 속 '<' 는 검사(주석 제거)와 화면(브라우저 파싱)을 갈라 놓는다(codex 구현 7·8차).
    # ① 문서 전체: 속성값 안의 주석 기호 — 그것이 있으면 주석 제거가 화면과 다른 구간을 지운다(발행본 60편 실측 0건).
    if re.search(r'=\s*"[^"]*(?:<!--|-->)[^"]*"|=\s*\'[^\']*(?:<!--|-->)[^\']*\'', raw_doc):
        v.append('속성값 안에 HTML 주석 기호(<!-- 또는 -->)가 있다 — 빼라')
    # ② 실제 섹션(주석 밖 제목)에서: 주석과 속성값의 < > 금지
    spans = [(m.start(), m.end()) for m in re.finditer(r'<!--.*?--!?>', raw_doc, re.S)]
    real = [m.start() for m in re.finditer(r'<h[1-4]\b[^>]*>\s*유동성·수급\s*</h[1-4]\s*>', raw_doc)
            if not any(a <= m.start() < b for a, b in spans)]
    raw_sec = locate_section(raw_doc[max(0, raw_doc.rfind('<section', 0, real[0])):], SECTION_TITLE, exact=True) \
        if real else None
    if raw_sec is not None:
        if '<!--' in raw_sec or '-->' in raw_sec:
            v.append('「유동성·수급」 섹션 안에 HTML 주석이 있다 — 빼라')
        if re.search(r'=\s*"[^"]*[<>][^"]*"|=\s*\'[^\']*[<>][^\']*\'', raw_sec):
            v.append('「유동성·수급」 섹션의 속성값에 < 나 > 가 있다 — 빼라')
    usable = (book is not None and book.get('status') == 'complete' and not book.get('disabled')
              and report_date and book.get('report_date') == report_date)
    if not usable:
        if present(doc):
            why = ('유동성 책이 없다' if book is None else
                   f'유동성 책 상태가 {book.get("status")} 다' if book.get('status') != 'complete' else
                   '유동성 섹션이 꺼져 있다' if book.get('disabled') else
                   f'유동성 책이 {book.get("report_date")} 자인데 오늘은 {report_date} 다')
            v.append(f'{why} — 「유동성·수급」 섹션·표식을 실은 채로는 발행할 수 없다')
        return v

    h41_keys, docs = expected(book, ledger)
    book_h41 = [c['release_date'] for c in book['h41']['candidates']]
    book_docs = set((book.get('qra') or {}).get('candidates') or {})
    if h41_keys != book_h41 or set(docs) != book_docs:
        v.append(f'{LEDGER_CHANGED}: 수집 뒤 발행본 원장이 바뀌었다(H.4.1 {book_h41}→{h41_keys}, '
                 f'QRA {sorted(book_docs)}→{sorted(docs)}) — build_liquidity.py --recompute 뒤 섹션을 다시 써라')
        return v
    today = bool(h41_keys) or bool(docs)
    sec = section(doc)
    if not today:
        if present(doc):
            v.append(f'{report_date} 에 실을 H.4.1·분기조달계획이 없다 — 「유동성·수급」 섹션을 빼라')
        return v
    if sec is None:
        v.append(f'실을 발표가 있다(H.4.1 {h41_keys}, QRA {sorted(docs)}) — 「유동성·수급」 섹션이 없다. '
                 'liquidity/table.html 과 표식 문단을 넣어라')
        return v
    if doc.count(sec) != 1 or len(re.findall(r'<h[1-4]\b[^>]*>\s*유동성·수급\s*</h[1-4]>', doc)) != 1:
        v.append('「유동성·수급」 섹션이 하나가 아니다')
    if _MARK.search(doc.replace(sec, '')):
        v.append('유동성 표식이 「유동성·수급」 섹션 밖에 있다')
    for m in re.finditer(r'<(?!div\b)(\w+)\b[^>]*\bclass\s*=\s*["\'][^"\']*\bcaption\b', sec, re.I):
        v.append(f'캡션은 table.html 의 <div class="caption"> 뿐이다 — <{m.group(1)} class="caption"> 를 빼라')
    for m in _WRONG_HOST.finditer(sec):
        v.append(f'유동성 해석 표식은 <p> 에만 — <{m.group(1)}> 에 달았다')
    anc = _hidden_ancestor(doc, doc.find(sec))
    if anc:
        v.append(f'「유동성·수급」 섹션을 숨긴 요소가 감싸고 있다 — {anc}')
    hid = _HIDDEN.search(sec)
    if hid:
        v.append(f'「유동성·수급」 섹션 안에 숨긴 요소가 있다 — {hid.group(0)[:60]}')
    days = _ATTR('data-liquidity-day').findall(sec)
    if days != [report_date]:
        v.append(f'data-liquidity-day 가 {days} 다 — "{report_date}" 하나여야 한다')

    # 표
    rounds = {c['release_date']: c for c in book['h41']['candidates']}
    q = book.get('qra') or {}
    tables = list(_TABLE.finditer(sec))
    seen_h41 = []
    want_caps = [L.h41_caption(rounds[k]) for k in h41_keys] + ([L.qra_caption(q['round_name'], docs)] if docs else [])
    qra_tables = 0
    for m in tables:
        attrs, body = m.group(1), m.group(2)
        h = _ATTR('data-h41-release').search(attrs)
        qt = _ATTR('data-qra-table').search(attrs)
        rows = _table_rows(body)
        if h:
            k = h.group(1)
            seen_h41.append(k)
            if k not in rounds:
                v.append(f'H.4.1 {k} 표는 이번에 실을 회차가 아니다')
                continue
            if k in ledger[0]:
                v.append(f'H.4.1 {k} 는 이미 다른 글에 실렸다')
            if _text(m.group(0)) != _text(L.h41_table_html(rounds[k])):
                v.append(f'H.4.1 {k} 표 글자가 데이터로 다시 그린 표와 다르다(칸 밖 요소·숫자 포함) — table.html 그대로')
            want = {key: L.h41_cells(rounds[k], key) for key in L.TABLE_ROWS}
            heads = [hh for _, _, hh in rows if hh]
            if heads != [L.H41_HEAD]:
                v.append(f'H.4.1 {k} 표 머리가 다르다: {heads}')
            body_rows = [(key, cells) for key, cells, hh in rows if cells]
            if [key for key, _ in body_rows] != list(L.TABLE_ROWS):
                v.append(f'H.4.1 {k} 표 행이 {[key for key, _ in body_rows]} 다 — {list(L.TABLE_ROWS)} 그대로')
            for key, cells in body_rows:
                if key in want and cells != want[key]:
                    v.append(f'H.4.1 {k} 표 {key} 행이 데이터와 다르다: {cells} ≠ {want[key]}')
        elif qt:
            qra_tables += 1
            if not docs or qt.group(1) != q.get('round'):
                v.append(f'분기조달계획 표 {qt.group(1)} 는 이번에 실을 것이 아니다')
                continue
            if _text(m.group(0)) != _text(L.qra_table_html(q, docs)):
                v.append('분기조달계획 표 글자가 데이터로 다시 그린 표와 다르다(칸 밖 요소·숫자 포함) — table.html 그대로')
            want = L.qra_rows(docs)
            body_rows = [(key, cells) for key, cells, hh in rows if cells]
            heads = [hh for _, _, hh in rows if hh]
            if heads != [L.QRA_HEAD]:
                v.append(f'분기조달계획 표 머리가 다르다: {heads}')
            if body_rows != want:
                v.append('분기조달계획 표가 데이터와 다르다 — liquidity/table.html 그대로')
        else:
            v.append('「유동성·수급」 섹션에 정해진 표 밖의 표가 있다')
    if seen_h41 != h41_keys:
        v.append(f'H.4.1 표 회차가 {seen_h41} 다 — {h41_keys} 순서대로 하나씩')
    if qra_tables != (1 if docs else 0):
        v.append(f'분기조달계획 표가 {qra_tables}개다 — {1 if docs else 0}개여야 한다')
    raw_caps = _CAPTION.findall(sec)
    if any('<' in c for c in raw_caps):
        v.append('캡션 안에 태그가 있다 — table.html 의 캡션은 글자뿐이다')
    heads = re.findall(r'<h([1-6])\b[^>]*>(.*?)</h\1\s*>', sec, re.S | re.I)
    if [_text(t) for _, t in heads] != [SECTION_TITLE]:
        v.append(f'「유동성·수급」 섹션의 제목은 하나뿐이어야 한다: {[_text(t) for _, t in heads]}')
    caps = [_text(c) for c in raw_caps]
    if caps != want_caps:
        v.append(f'표 캡션이 데이터에서 만든 문구와 다르다: {caps} — liquidity/table.html 그대로')

    # 문단
    need_liq = {f'{k}:{row}' for k in h41_keys for row in L.FLAG_ROWS
                if rounds[k]['flags']['rows'].get(row, {}).get('big')}
    need_qra = {f'{q["round"]}:{k}' for k in docs if k in ('borrowing', 'refunding')}
    allow_qra = need_qra | ({f'{q["round"]}:tbac'} if 'tbac' in docs and need_qra else set())
    g = q.get('guidance') or {}
    need_guid = 'refunding' in docs and g.get('change') in ('same', 'changed')
    liq, qd, gd = {}, {}, []
    for m in _P.finditer(sec):
        attrs, raw = m.group(1), m.group(2)
        a = _ATTR('data-liq').search(attrs)
        b = _ATTR('data-qra-doc').search(attrs)
        c = _ATTR('data-qra-guidance').search(attrs)
        if a:
            liq.setdefault(a.group(1), []).append(raw)
        elif b:
            qd.setdefault(b.group(1), []).append(raw)
        elif c:
            gd.append((c.group(1), raw))
        elif _text(raw):
            v.append(f'「유동성·수급」의 무표식 문단 — 해석은 data-liq·data-qra-doc 문단으로만: 「{_text(raw)[:40]}」')
    for k in set(liq) - need_liq:
        v.append(f'data-liq="{k}" 는 이례적 행이 아니다 — 이례적이지 않은 행은 표로만')
    for k in need_liq:
        if len(liq.get(k, [])) != 1:
            v.append(f'data-liq="{k}" 문단이 {len(liq.get(k, []))}개다 — 정확히 하나')
            continue
        rel, row = k.split(':')
        v += _check_liq_paragraph(f'data-liq={k}', liq[k][0], rounds[rel], row)
    for k in set(qd) - allow_qra:
        v.append(f'data-qra-doc="{k}" 는 이번에 실을 문서가 아니다')
    for k in allow_qra:
        n = len(qd.get(k, []))
        if (k in need_qra and n != 1) or n > 1:
            v.append(f'data-qra-doc="{k}" 문단이 {n}개다 — 정확히 하나')
            continue
        if n:
            kind = k.split(':')[1]
            v += _check_qra_paragraph(f'data-qra-doc={k}', qd[k][0], kind, docs[kind])
    if need_guid:
        if [r for r, _ in gd] != [q['round']]:
            v.append(f'가이던스 문단 data-qra-guidance="{q["round"]}" 가 정확히 하나여야 한다')
        else:
            raw = gd[0][1]
            marks = re.findall(r'<(\w+)\b[^>]*\bdata-guidance\s*=\s*"([^"]*)"', raw)
            if [x for _, x in marks] != [g['change']]:
                v.append(f'가이던스 표식이 {[x for _, x in marks]} 다 — data-guidance="{g["change"]}" 하나')
            txt = _text(raw)
            if g['change'] == 'changed' and not any(w.lower() in txt.lower() for w in g.get('words') or []):
                v.append(f'가이던스가 바뀌었다 — 바뀐 낱말({", ".join(g["words"])})을 인용하라')
            money, other = money_values(txt)
            if money or other:
                v.append('가이던스 문단에는 수치를 쓰지 않는다')
    elif gd:
        v.append('가이던스 비교 근거(직전 회차 문장)가 없다 — data-qra-guidance 문단을 빼라')

    # 표·캡션·표식 문단·제목 밖에는 글자가 없어야 한다(무표식 <div>·<li> 등으로 해석·수치를 싣는 경로)
    rest = _CAPTION.sub(' ', _TABLE.sub(' ', sec))
    rest = _P.sub(' ', rest)
    rest = re.sub(r'<h([1-6])\b[^>]*>.*?</h\1\s*>', ' ', rest, flags=re.S | re.I)
    if _text(rest):
        v.append(f'「유동성·수급」에 표·캡션·표식 문단 밖의 글자가 있다: 「{_text(rest)[:40]}」')

    # 섹션 전체 바닥선
    body = _text(_CAPTION.sub(' ', _TABLE.sub(' ', sec)))
    for s in re.split(r'(?<=다)\.\s*', body):
        if _TODAY.search(s) and any(n in s for k in L.FLAG_ROWS for n in L.ROW_NAMES[k]):
            v.append(f'「오늘」과 수요일 기준 값을 함께 썼다: 「{s[:50]}」')
    hit = _CAUSAL.search(body)
    if hit:
        v.append(f'유동성 수치로 금리·달러를 단정했다: 「{hit.group(0)[:60]}」 — 근거가 없으면 원인 후보로만')
    return v
