"""한국은행·일본은행 이벤트 칸 게이트 — KR 「한국은행 금통위」(`kr/bok_gate.py`)·일본 「일본은행」(`japan/daily_gate.py`)
이 같이 쓰는 검사 (2026-11-27).

미국 「연준 이벤트」 게이트(`us/fed_gate.check`)와 같은 항목을 본다 — 이 칸이 막는 것은 수치 창작이 아니라
**인용 창작**이다. 총재가 하지 않은 말을 총재의 말로 싣는 것이 유일하고 가장 큰 실패 방식이고, 지어낸 인용은
그럴듯할수록 안 걸린다. 그래서 발행본의 인용은 수집해 둔 원문에 글자 그대로 있어야 하고(공백만 무시),
원문을 못 받은 이벤트는 인용을 금지한다.

  · 침묵: 의무 이벤트가 없는 날 칸이 있으면 막는다. 있는데 칸이 없으면 막는다.
  · 도입 문단 `data-cb-event=KEY`(지난 날짜면 그 날짜를 밝힌다), 인용 카드 `data-cb-quote=KEY` 둘 이상(원문 있을 때)
  · 인용 규율 넷 — blockquote 안 태그 금지, 생략 ≤2·조각 하한, 원문 순서·간격 상한, 표식 밖 blockquote 금지
  · 익명 문서(의사록·주요 의견·의사요지)의 인용 캡션에 「총재」 금지
  · 변경점 블록(계산해 둔 변경이 있는 날), 투자 아이디어 4요소, 무효화 블록 안에서만 문턱값, 칸 수치(시장별 콜백)

미국 코드는 고치지 않는다 — 요소 범위·마크업 판정만 가져다 쓴다.
설계: docs/superpowers/specs/2026-11-27-central-bank-events.md
"""
import html as _html
import re

from common import cb_events as CE
from common import cb_quote as CQ
from common.numbers import TAG_RE, numbers_split_by_tags, strip_comments, text_dense, text_of
from us.fed_gate import _element_extent, quote_markup_problem

EVENT_MIN_CHARS = 100
TRANS_MIN_CHARS = 20
IDEA_MIN_CHARS = 150
INVALIDATION_MIN_CHARS = 30
CHANGE_MIN_CHARS = 150
MIN_QUOTES_PER_EVENT = 2

MARKER_ATTRS = {
    'event': 'data-cb-event',
    'quote': 'data-cb-quote',
    'change': 'data-cb-change',
    'idea': 'data-cb-idea',
    'invalidation': 'data-invalidation',
}
_MARKER_VALUE = {k: re.compile(r'\b%s\s*=\s*"([A-Za-z0-9_-]*)"' % v, re.I) for k, v in MARKER_ATTRS.items()}
_TAG_NAME = re.compile(r'<\s*(/?)\s*([a-zA-Z][\w-]*)')
_QUOTE_REF = re.compile(r'\bdata-cb-quote-ref\s*=\s*"([A-Za-z0-9_-]+)"', re.I)
_BLOCKQUOTE = re.compile(r'<blockquote\b[^>]*>(.*?)</blockquote>', re.S | re.I)
_TRANS_P = re.compile(r'<p\b[^>]*\bclass\s*=\s*"[^"]*\bcb-trans\b[^"]*"[^>]*>(.*?)</p>', re.S | re.I)
_CAPTION = re.compile(r'<p\b[^>]*\bclass\s*=\s*"[^"]*\bcaption\b[^"]*"[^>]*>(.*?)</p>', re.S | re.I)
_H2 = re.compile(r'<h2\b[^>]*>(.*?)</h2>', re.S | re.I)
_CHAIR = re.compile(r'총재|総裁')

# 내부 사정이 지면에 나오면 안 된다 — 독자는 우리 파일 이름을 모른다.
INTERNAL = ('events.json', 'schedule.json', 'statements.json', 'covered.json', 'cb_events', 'cb_gate', 'bok_gate',
            'data-cb', 'corpus', 'redline', 'tier 1', 'tier1', 'from_schedule')

CONFIG = {
    'bok': {'lang': 'ko', 'name': 'bok', 'title': '한국은행 금통위', 'trans': False, 'what': 'BOK 금통위'},
    'boj': {'lang': 'ja', 'name': 'boj', 'title': '일본은행', 'trans': True, 'what': '일본은행'},
}


def _text(fragment):
    return _html.unescape(TAG_RE.sub(' ', fragment or '')).strip()


def sections(html_doc, name):
    """[(시작, 끝, HTML)] — `data-section="name"` 이 붙은 <section> 요소의 실제 범위(주석은 지운 문서 기준)."""
    doc = strip_comments(html_doc or '')
    out = []
    for m in re.finditer(r'<section\b[^>]*\bdata-section\s*=\s*"%s"[^>]*>' % re.escape(name), doc, re.I):
        end = _element_extent(doc, m.start(), 'section')
        out.append((m.start(), end, doc[m.start():end]))
    return out


def section(html_doc, name):
    found = sections(html_doc, name)
    return found[0][2] if found else None


def blocks(section_html):
    """표식 -> [(key, 그 요소의 HTML, (시작, 끝))] — 표식이 붙은 태그가 닫히는 곳까지(미국 칸과 같은 규칙)."""
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
            if hit:
                end = _element_extent(s, m.start(), name.group(2))
                out[kind].append((hit.group(1), s[m.start():end], (m.start(), end)))
    return out


def sweep_scope(section_html, blk):
    """수치 검사 대상 — 무효화 조건 블록(그 요소가 끝나는 곳까지)을 뺀 나머지. 문턱값은 거기에만 쓴다."""
    s = section_html or ''
    keep, at = [], 0
    for _k, _r, (a, b) in sorted(blk['invalidation'], key=lambda x: x[2]):
        if a < at:
            continue
        keep.append(s[at:a])
        at = b
    keep.append(s[at:])
    return ''.join(keep)


def corpus(event):
    return '\n'.join(s.get('text') or '' for s in (event or {}).get('sources') or [] if s.get('ok') and s.get('text'))


def _names_date(text, iso):
    y, m, d = (int(x) for x in iso.split('-'))
    forms = (iso, f'{m}월 {d}일', f'{m:02d}월 {d:02d}일', f'{m}/{d}')
    return any(f in text for f in forms)


def _quote_ok(raw, event, key, cfg, v):
    what = cfg['what']
    text = corpus(event)
    quotes = _BLOCKQUOTE.findall(raw)
    if not quotes:
        v.append(f'{what} {key}: 인용 카드에 <blockquote>가 없다 — 발언은 원문 그대로 싣는다')
        return False
    ok = True
    for q in quotes:
        bad = quote_markup_problem(q)
        if bad:
            v.append(f'{what} {key}: {bad}')
            ok = False
            continue
        n = len(CQ.normalize_cjk(q))
        if n < CQ.QUOTE_MIN:
            v.append(f'{what} {key}: 인용이 {n}자로 너무 짧다 — {CQ.QUOTE_MIN}자 이상이라야 무슨 말인지 읽힌다')
            ok = False
            continue
        if not text:
            v.append(f'{what} {key}: 원문을 받아 두지 못한 이벤트인데 인용문이 실렸다 — 대조할 수 없는 발언은 싣지 않는다')
            ok = False
            continue
        miss = CQ.verify_quote(q, text, cfg['lang'])
        if miss:
            v.append(f'{what} {key}: {miss}')
            ok = False
    if cfg['trans'] and not [t for t in _TRANS_P.findall(raw) if len(_text(t)) >= TRANS_MIN_CHARS]:
        v.append(f'{what} {key}: 인용에 한국어 번역(<p class="cb-trans">, {TRANS_MIN_CHARS}자 이상)이 없다')
        ok = False
    caps = _CAPTION.findall(raw)
    if not caps:
        v.append(f'{what} {key}: 인용에 출처 캡션(<p class="caption">)이 없다 — 어느 문서에서 나온 말인지 밝힐 것')
        ok = False
    elif event.get('kind') in CE.ANONYMOUS and any(_CHAIR.search(_text(c)) for c in caps):
        v.append(f'{what} {key}: 위원 이름을 밝히지 않는 문서({event.get("kind_ko")})인데 캡션이 「총재」를 화자로 '
                 '쓴다 — 「위원」 견해로만 쓴다')
        ok = False
    return ok


def _check_orphans(sec, blk, cfg, v):
    spans = [span for _k, _r, span in blk['quote']]
    for m in re.finditer(r'<blockquote\b', sec or '', re.I):
        if not any(a <= m.start() < b for a, b in spans):
            v.append(f'{cfg["what"]}: 표식 없는 <blockquote>가 있다 — 인용문은 전부 '
                     '<div class="cb-quote" data-cb-quote="KEY"> 안에 넣어야 검사를 받는다')
            return


def change_candidates(*diffs):
    """변경점 블록이 원문 그대로 옮겨야 하는 문장 후보. 바뀐 것이 없으면 []."""
    out = []
    for diff in diffs:
        if not diff:
            continue
        for c in diff.get('changed') or []:
            out += list(c.get('sentences') or []) or [c.get('after') or '']
        out += list(diff.get('added') or [])
    return [s for s in out if s]


def _check_change(diffs, blk, cfg, v):
    want = change_candidates(*diffs)
    if not want:
        return
    if not blk['change']:
        v.append(f'{cfg["what"]}: 직전 결정 대비 변경점을 계산해 뒀는데 <div data-cb-change="1"> 블록이 없다')
        return
    body = ' '.join(_text(raw) for _k, raw, _s in blk['change'])
    if len(body) < CHANGE_MIN_CHARS:
        v.append(f'{cfg["what"]}: 변경점 블록이 {len(body)}자뿐이다 — {CHANGE_MIN_CHARS}자 이상으로 무엇이 어떻게 '
                 '바뀌었는지 쓸 것')
    norm = CQ.normalize_cjk(' '.join(raw for _k, raw, _s in blk['change']))
    if not any(CQ.normalize_cjk(s).strip(CQ._EDGE) in norm for s in want):
        v.append(f'{cfg["what"]}: 변경점 블록이 바뀐 문장을 하나도 원문 그대로 옮기지 않았다 — 고쳐 쓴 문장 하나를 '
                 '그대로 보여 줄 것')


def _check_ideas(blk, printed, cfg, v):
    what = cfg['what']
    for n, (_key, raw, (a, b)) in enumerate(blk['idea'], 1):
        mine = [inv for inv in blk['invalidation'] if a <= inv[2][0] < b]
        body = _text(raw)
        for _k, inv_raw, _s in mine:
            body = body.replace(_text(inv_raw), '')
        if len(body.strip()) < IDEA_MIN_CHARS:
            v.append(f'{what}: {n}번째 아이디어가 {len(body.strip())}자뿐이다 — 어느 발언에서 나왔고 어느 경로로 '
                     '무엇에 닿는지까지 쓸 것')
        ref = _QUOTE_REF.search(raw)
        if not ref:
            v.append(f'{what}: {n}번째 아이디어에 근거 발언 표식(data-cb-quote-ref)이 없다 — 인용에 걸리지 않은 '
                     '아이디어는 이 칸의 것이 아니다')
        elif ref.group(1) not in printed:
            v.append(f'{what}: {n}번째 아이디어가 지면에 없는 발언({ref.group(1)})을 근거로 든다')
        if not mine:
            v.append(f'{what}: {n}번째 아이디어에 무효화 조건이 없다 — <p data-invalidation="N">을 그 아이디어 안에 둘 것')
        elif max(len(_text(r)) for _k, r, _s in mine) < INVALIDATION_MIN_CHARS:
            v.append(f'{what}: {n}번째 무효화 조건이 비어 있다 — 무엇이 나오면 이 생각을 접는지 수치나 사건으로 쓸 것')


def check(html_doc, bank, due, report_date, diffs=(), numbers=None):
    """위반 목록. `due` = `cb_events.due_events` 결과(원문 행은 `sources[].text` 가 붙은 것).

    `numbers(scope_html, due)` → 위반 목록 — 칸 수치 검사는 시장마다 다르다(KR 단위 값 / 일본 숫자 토큰).
    `scope_html` 은 무효화 블록을 뺀 칸이다.
    """
    cfg = CONFIG[bank]
    what = cfg['what']
    v = []
    found = sections(html_doc, cfg['name'])
    titled = [m for m in _H2.finditer(strip_comments(html_doc or '')) if _text(m.group(1)).startswith(cfg['title'])]
    if len(found) > 1:
        v.append(f'data-section="{cfg["name"]}" 칸이 {len(found)}개다 — 하나만 둔다')
    sec = found[0][2] if found else None
    if sec is None and titled:
        v.append(f'「{cfg["title"]}」 제목이 있는데 <section data-section="{cfg["name"]}"> 이 없다 — 검사를 받는 칸으로 쓴다')
    if not due:
        if sec is not None:
            v.append(f'오늘은 실을 {what} 이벤트가 없는데 「{cfg["title"]}」 칸이 실렸다 — 이 칸은 결정회의 문서가 '
                     '새로 나온 날에만 연다')
        return v
    if sec is None:
        labels = ', '.join(e.get('kind_ko') or e.get('kind') for e in due)
        v.append(f'오늘 {what} 이벤트({labels})가 있는데 「{cfg["title"]}」 칸(<section data-section="{cfg["name"]}">)이 없다')
        return v

    blk = blocks(sec)
    by_key = {e['key']: e for e in due}
    intro = {k: raw for k, raw, _s in blk['event']}
    for e in due:
        key, raw = e['key'], intro.get(e['key'])
        if raw is None:
            v.append(f'{what}: 「{e.get("kind_ko")}」 도입 문단이 없다 — <p data-cb-event="{key}">로 무슨 자리에서 '
                     '누가 무엇을 정했는지 쓸 것')
        elif len(_text(raw)) < EVENT_MIN_CHARS:
            v.append(f'{what} {key}: 도입 문단이 {len(_text(raw))}자뿐이다 — {EVENT_MIN_CHARS}자 이상 필요')
        elif e.get('date') and e['date'] != report_date and not _names_date(_text(raw), e['date']):
            _y, m, d = e['date'].split('-')
            v.append(f'{what} {key}: {int(m)}월 {int(d)}일에 나온 문서인데 도입 문단이 그 날짜를 밝히지 않았다 — '
                     '오늘 일처럼 읽힌다')
    for key in intro:
        if key not in by_key:
            v.append(f'{what}: 오늘 실을 이벤트가 아닌 도입 표식({key})이 있다')

    printed = {}
    for key, raw, _span in blk['quote']:
        e = by_key.get(key)
        if e is None:
            v.append(f'{what}: 오늘 실을 이벤트에 없는 인용 키({key})가 실렸다')
            continue
        if _quote_ok(raw, e, key, cfg, v):
            printed[key] = printed.get(key, 0) + 1
    _check_orphans(sec, blk, cfg, v)
    for e in due:
        if corpus(e) and printed.get(e['key'], 0) < MIN_QUOTES_PER_EVENT:
            v.append(f'{what} {e["key"]}: 검증된 인용이 {printed.get(e["key"], 0)}개다 — '
                     f'{MIN_QUOTES_PER_EVENT}개 이상 필요')
    _check_change(diffs, blk, cfg, v)
    _check_ideas(blk, set(printed), cfg, v)
    if numbers is not None:
        v += numbers(sweep_scope(sec, blk), due)
    for run in numbers_split_by_tags(sec):
        v.append(f'{what}: 수치 사이에 태그가 끼어 있다 — 「{run[:40]}」')
    body = text_of(sec) + ' ' + text_dense(sec)
    for word in INTERNAL:
        if word in body:
            v.append(f'{what}: 내부 용어 「{word}」가 지면에 노출됐다')
    return v
