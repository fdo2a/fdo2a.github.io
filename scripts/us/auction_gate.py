#!/usr/bin/env python3
"""발행 게이트 — 「국채 입찰」 섹션 (US 아침 브리프).

연준 이벤트 섹션과 같은 모양이다. **침묵이 기본값이다** — 그날 이표채 입찰 결과가 없으면
섹션을 열지 않는다. 결과가 있는 날은 섹션이 있어야 한다.

막는 것:
1. 입찰 없는 날·책이 없거나 낡았거나 실패한 날의 섹션(과 섹션 밖의 입찰 표식).
2. 입찰 있는 날 섹션 누락, 입찰마다 `<p data-auction=KEY>` 하나가 아닌 것.
3. 표 — 셀 텍스트가 `auctions.cells()` 와 다른 것(숨긴 행도 센다). 조판기가 속성·공백을
   바꿔도 살아남도록 바이트가 아니라 셀 텍스트로 본다.
4. 섹션 산문의 단위 달린 수치가 책에 없는 것.
5. 블록마다 응찰배율·딜러 비중 값이 빠진 것, 판정 표식(`data-demand`)이 책과 다른 것.
6. 평균 대비 방향어(높/낮·웃돌/밑돌)가 차이의 부호와 반대인 것.
7. 테일·스톱스루·WI — WI 금리 원천이 없어 근거 없는 말이다.
"""

import html as _html
import re
from html.parser import HTMLParser

from common.numbers import TAG_RE, measure_numbers, numeric_tokens, strip_comments, text_of

from . import auctions as A
from .section import locate_section

SECTION_TITLE = '국채 입찰'
_H2 = re.compile(r'<h2\b[^>]*>(.*?)</h2>', re.S | re.I)
# 속성 **이름**으로 찾는다 — 값 없는 `<div data-auction-day>` 도 표식이다(codex 구현 검토 #2).
_MARK = re.compile(r'<[^>]*?\sdata-(?:auction(?:-day|-table|-row)?|demand)(?=[\s=>/])', re.I)
# 섹션 안에서는 아무것도 숨기지 않는다. 숨긴 행·문단이 검사를 대신 만족시킨다(#1·#2).
_HIDDEN = re.compile(r'<[^>]*?(?:\shidden(?=[\s=>/])|aria-hidden\s*=\s*["\']?true'
                     r'|display\s*:\s*none|visibility\s*:\s*hidden)', re.I)
_BLOCK = re.compile(r'<p\b[^>]*\bdata-auction\s*=\s*"([^"]*)"[^>]*>(.*?)</p\s*>', re.S | re.I)
_DEMAND = re.compile(r'<(\w+)\b[^>]*\bdata-demand(?:\s*=\s*"[^"]*")?[^>]*>(.*?)</\1\s*>',
                     re.S | re.I)
_DAY = re.compile(r'\bdata-auction-day\s*=\s*"([^"]*)"', re.I)
_TABLE = re.compile(r'<table\b[^>]*\bdata-auction-table\b.*?</table\s*>', re.S | re.I)
_CAPTION = re.compile(r'<div\b[^>]*class\s*=\s*"[^"]*\bcaption\b[^"]*"[^>]*>.*?</div\s*>',
                      re.S | re.I)
BANNED = re.compile(r'테일|스톱\s*스루|\btail|stop-?through|\bWI\b|발행\s*전\s*거래', re.I)

# 방향어. 지표 이름에서 다음 지표 이름(또는 문장 끝)까지가 그 지표의 서술 구간이다.
_METRICS = {'btc': ('응찰배율', '응찰 배율'), 'dealer': ('딜러',),
            'indirect': ('간접',), 'direct': ('직접',)}
_UP = re.compile(r'높|웃돌|넘어|넘었|넘는|많|늘|커')
_DOWN = re.compile(r'낮|밑돌|못\s*미|적었|줄|작')
_NEG = re.compile(r'않|아니|없')
# 「평균」 뒤 그 비교가 끝나는 곳 — 쉼표·연결 어미·문장 끝.
_CLAUSE_END = re.compile(r',|고(?=\s|$)|며|지만|반면|(?<=다)\.|다$')
_SENT = re.compile(r'(?<=다)\.\s*|(?<=[.!?])\s+')
# 판정 문구. 표식 밖 산문에서도 책의 판정과 반대되는 말은 막는다(#3).
_VERDICT_WORDS = {'수요 강함': ('수요 강함', '수요가 강'), '수요 약함': ('수요 약함', '수요가 약'),
                  '엇갈림': ('엇갈림', '엇갈렸', '엇갈린')}


def _text(fragment):
    return _html.unescape(TAG_RE.sub(' ', fragment or '')).strip()


def section(doc):
    """제목이 「국채 입찰」인 <h2> 의 <section> — 닫는 태그를 세어 자른다(공용 헬퍼).

    다음 `<section` 까지 자르면 닫힌 섹션 뒤에 붙인 요소까지 안쪽으로 읽어, 섹션 밖
    표식이 「안」으로 통과한다(codex 구현 검토 #2 재현).
    """
    return locate_section(strip_comments(doc or ''), SECTION_TITLE, exact=True)


def present(doc):
    """섹션이든 표식이든 입찰 내용이 실렸는가."""
    d = strip_comments(doc or '')
    return section(d) is not None or bool(_MARK.search(d))


class _Rows(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows, self._row, self._cell = [], None, None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'tr':
            # 키 없는 행도 센다 — 정상 표 뒤에 덧붙인 행이 검사를 피하면 안 된다(#1).
            self._row = [a.get('data-auction-row'), []]
            self.rows.append(self._row)
        elif tag == 'td' and self._row is not None:
            self._cell = ''

    def handle_data(self, data):
        if self._cell is not None:
            self._cell += data

    def handle_endtag(self, tag):
        if tag == 'td' and self._cell is not None:
            self._row[1].append(re.sub(r'\s+', ' ', self._cell).strip())
            self._cell = None
        elif tag == 'tr':
            self._row = None


def table_rows(sec):
    """`<td>` 가 하나라도 있는 행 전부 — [키 또는 None, 셀들]."""
    p = _Rows()
    p.feed(sec or '')
    return [r for r in p.rows if r[1]]


def allowed(item):
    """그 입찰의 블록이 인쇄해도 되는 수치 — 책의 값과 차이의 절댓값."""
    blob = {k: v for k, v in item.items() if k not in ('cusip',)}
    extra = [abs(item[k]) for k in ('btc_vs_avg', 'dealer_vs_avg_pp', 'indirect_vs_avg_pp')
             if item.get(k) is not None]
    yr = item.get('yield_ref') or {}
    if yr.get('bp') is not None:
        extra.append(abs(yr['bp']))
    if item.get('offering_amt') and item.get('prev_offering_amt'):
        extra.append(abs(item['offering_amt'] - item['prev_offering_amt']) / 1e8)
    return numeric_tokens(blob, extra)


def _segments(text, names):
    """지표 이름마다 그 이름에서 다음 지표 이름·문장 끝까지의 조각."""
    every = [n for ns in _METRICS.values() for n in ns]
    out = []
    for sent in _SENT.split(text):
        for name in names:
            for m in re.finditer(re.escape(name), sent):
                rest = sent[m.end():]
                cut = min([rest.find(o) for o in every if o not in names and rest.find(o) >= 0]
                          + [len(rest)])
                out.append(rest[:cut])
    return out


def _comparisons(seg):
    """조각 안의 「평균」마다 그 비교 구절 — 평균 뒤에서 구절이 끝나는 곳까지."""
    out = []
    for m in re.finditer('평균', seg):
        rest = seg[m.end():]
        cut = _CLAUSE_END.search(rest)
        out.append(rest[:cut.start() if cut else len(rest)])
    return out


def _direction_errors(key, text, item):
    """평균 대비 방향이 부호와 맞는가. 구절에 방향어가 둘 다 있거나 부정이 섞이면
    자동으로 승인하지 않는다 — 「높지 않았다」를 부호로 읽을 수 없다(#4)."""
    v = []
    pairs = (('btc', item.get('btc_vs_avg'), '응찰배율'),
             ('dealer', item.get('dealer_vs_avg_pp'), '딜러 비중'),
             ('indirect', item.get('indirect_vs_avg_pp'), '간접 비중'))
    for metric, delta, label in pairs:
        for seg in _segments(text, _METRICS[metric]):
            if '각각' in seg and '평균' in seg:
                v.append(f'{key}: 「각각 평균보다 …」 — 지표와 방향을 짝지을 수 없다, 지표마다 따로 쓸 것')
                continue
            for cl in _comparisons(seg):
                up, down = bool(_UP.search(cl)), bool(_DOWN.search(cl))
                neg = bool(_NEG.search(cl)) and not re.search(r'못\s*미', cl)
                quote = f'「평균{cl.strip()[:40]}」'
                if not (up or down):
                    continue
                if neg or (up and down):
                    v.append(f'{key}: {label} 평균 비교를 부정·혼합 방향으로 썼다 {quote} — '
                             '높다/낮다 하나로 쓸 것')
                elif delta is None or round(delta, 2) == 0:
                    v.append(f'{key}: {label} 평균 대비 차이가 없는데 방향을 썼다 {quote}')
                elif delta > 0 and down:
                    v.append(f'{key}: {label}가 평균보다 {delta:+} 인데 낮다고 썼다 {quote}')
                elif delta < 0 and up:
                    v.append(f'{key}: {label}가 평균보다 {delta:+} 인데 높다고 썼다 {quote}')
    return v


# 판정 어휘 — 낱말 목록은 **바닥선**이다. 바꿔 쓴 반대 판정(「냉랭했다」류)을 끝까지 막는
# 사전은 없고, 넓힐수록 「국채시장은 견조했다」 같은 정상 문장을 막는다(codex 3·4차).
# 그래서 ① 입찰 평가로만 쓰이는 말은 어디서든, ② 시장 일반에도 쓰는 형용사는 주어가
# 수요·응찰·입찰일 때만 막고, 나머지 의미 모순은 발행 후 codex 검토가 맡는다.
_SUBJ = r'(?:수요|응찰|입찰)[이가는은도의]?\s*(?:더\s*|매우\s*|다소\s*)?'
_FREE_VERDICT = re.compile(
    r'엇갈|부진|저조|호조|실망|흥행|부실|냉랭|미온|미약|취약'
    + r'|' + _SUBJ + r'(?:강(?!세)|약(?!세)|견조|탄탄|양호|좋|나쁘|두터|두껍|두텁|얇|탄탄|튼튼)')


def _verdict_errors(where, text_outside_marker):
    """수요의 강약은 `data-demand` 표식으로만 말한다. 표식 밖 산문의 판정 문구는 부정
    (「약하지 않았다」)·과거 비교(「약했던 직전 입찰」)를 기계가 가를 수 없어, 상반된
    판정을 통과시키거나 정상 문장을 막는다 — 둘 다 피하려고 표식 밖 판정 어휘를 막는다
    (codex 재검토 #3·새 오탐)."""
    hit = _FREE_VERDICT.search(text_outside_marker or '')
    if hit:
        return [f'{where}: 「{hit.group(0)}」 — 수요의 강약은 <b data-demand> 표식 하나로만 쓴다'
                '(표식 밖에서 판정을 다시 말하지 않는다)']
    return []


def _hidden_ancestor(doc, at):
    """`at` 위치를 감싸는 숨긴 요소가 있는가(섹션 통째로 숨기기, 재검토 #2)."""
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
            return m.group(0)[:60]       # 닫히지 않은 숨김 요소는 끝까지 감싼다
    return None


def check(doc, book, report_date):
    """-> [위반]. `book` 은 auctions.json(없으면 None), `report_date` 는 market_data 의 것."""
    doc = strip_comments(doc or '')
    sec = section(doc)
    v = []
    usable = (book is not None and book.get('ok') and report_date
              and book.get('report_date') == report_date)
    if not usable:
        if present(doc):
            why = ('auctions.json 이 없다' if book is None else
                   f'입찰 책이 실패했다({book.get("error")})' if not book.get('ok') else
                   f'입찰 책이 {book.get("report_date")} 자인데 오늘은 {report_date} 다')
            v.append(f'{why} — 「국채 입찰」 섹션·표식을 실은 채로는 발행할 수 없다')
        return v

    today = book.get('today') or []
    if not today:
        if present(doc):
            v.append(f'{report_date} 에는 결과가 나온 이표채 입찰이 없다 — 「국채 입찰」 섹션을 빼라')
        return v
    if sec is None:
        v.append(f'{report_date} 이표채 입찰 {len(today)}건의 결과가 있는데 「국채 입찰」 섹션이 없다 '
                 '— data/auction_table.html 과 입찰마다 <p data-auction="KEY"> 를 넣어라')
        return v

    outside = _MARK.findall(doc.replace(sec, ''))
    if outside:
        v.append('입찰 표식이 「국채 입찰」 섹션 밖에 있다')
    hidden = _HIDDEN.search(sec) or None
    anc = _hidden_ancestor(doc, doc.find(sec))
    if anc:
        v.append(f'「국채 입찰」 섹션을 숨긴 요소가 감싸고 있다 — {anc}')
    if hidden:
        v.append(f'「국채 입찰」 섹션 안에 숨긴 요소가 있다 — {hidden.group(0)[:60]}')
    caps = [_text(m.group(0)) for m in _CAPTION.finditer(sec)]
    if caps != [A.caption(book)]:
        v.append(f'표 캡션이 데이터에서 만든 문구와 다르다: {caps} — auction_table.html 그대로')
    days = _DAY.findall(sec)
    if days != [report_date]:
        v.append(f'섹션의 data-auction-day 가 {days} 다 — "{report_date}" 하나여야 한다')

    # 표
    want = {t['key']: A.cells(t) for t in today}
    rows = table_rows(sec)
    keys = [k for k, _ in rows]
    for k in want:
        if keys.count(k) != 1:
            v.append(f'표에 {k} 행이 {keys.count(k)}개다 — 정확히 하나여야 한다')
    for k, got in rows:
        if k not in want:
            v.append(f'표에 오늘 입찰이 아닌 행 {k} 가 있다')
        elif got != want[k]:
            v.append(f'표 {k} 행이 데이터와 다르다: {got} ≠ {want[k]} — auction_table.html 을 그대로 넣어라')

    # 블록
    by_key = {t['key']: t for t in today}
    found = {}
    for m in _BLOCK.finditer(sec):
        found.setdefault(m.group(1), []).append(m.group(2))
    for k in found:
        if k not in by_key:
            v.append(f'data-auction="{k}" 는 오늘 입찰이 아니다')
    for k, item in by_key.items():
        blocks = found.get(k, [])
        if len(blocks) != 1:
            v.append(f'{item["label_ko"]}({k}) 해석 블록이 {len(blocks)}개다 — 정확히 하나여야 한다')
            continue
        raw = blocks[0]
        text = _text(raw)
        v += _verdict_errors(k, _text(_DEMAND.sub(' ', raw)))
        if f'{item["bid_to_cover"]:.2f}' not in text:
            v.append(f'{k}: 응찰배율 {item["bid_to_cover"]:.2f}배가 블록에 없다')
        if f'{item["dealer_pct"]:.1f}' not in text:
            v.append(f'{k}: 딜러 비중 {item["dealer_pct"]:.1f}%가 블록에 없다')
        labels = [_text(m.group(2)) for m in _DEMAND.finditer(raw)]
        if item.get('demand_ko') is None:
            if labels:
                v.append(f'{k}: 표본이 {item.get("n_hist")}회뿐이라 판정이 없는데 판정 표식을 달았다')
        elif labels != [item['demand_ko']]:
            v.append(f'{k}: 판정 표식이 {labels} 다 — data-demand 하나에 「{item["demand_ko"]}」 그대로')
        v += _direction_errors(k, text, item)
        ok = allowed(item)
        for n in sorted(measure_numbers(text)):
            if n not in ok:
                v.append(f'{k}: 수치 {n} 는 이 입찰의 데이터에 없다')

    # 블록 밖 산문(표·캡션 제외)
    rest = _CAPTION.sub(' ', _TABLE.sub(' ', _BLOCK.sub(' ', sec)))
    pool = set()
    for t in today:
        pool |= allowed(t)
    for n in sorted(measure_numbers(text_of(rest))):
        if n not in pool:
            v.append(f'섹션 수치 {n} 는 오늘 입찰 데이터에 없다')
    v += _verdict_errors('섹션', _text(rest))
    hit = BANNED.search(_text(sec))
    if hit:
        v.append(f'「{hit.group(0)}」 — WI 금리 원천이 없어 테일·스톱스루는 쓸 수 없다')
    return v
