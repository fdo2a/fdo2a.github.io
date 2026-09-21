#!/usr/bin/env python3
"""뉴스 섹션 발행 게이트 — 실재하지 않는 기사를 막는다.

이 섹션이 스크립트 수집으로 설계된 이유가 여기 있다(`us/news.py` 참조). 에이전트가
검색해 적은 뉴스는 사후에 확인할 방법이 없지만, 수집분이 파일로 남으면 **발행본이
인용한 기사가 그날 실제로 받아진 것인지** 대조할 수 있다.

막는 실패는 넷이다.

  · 수집되지 않은 기사 — 그럴듯한 헤드라인을 지어내 쓰는 것
  · 본문을 못 받은 기사 — 제목만 보고 300자를 쓰면 그건 요약이 아니라 창작이다
  · RSS 한 줄 요약을 옮긴 것 — 사용자가 「한줄 요약은 좀 짧다」고 한 바로 그것
  · 지어낸 링크 — `source_gate` 와 같은 규율. 링크는 그 블록이 근거로 삼은 기사여야 한다

**이 게이트가 증명하지 못하는 것**(2026-09-19 codex 검토 #9). 표식이 가리키는 기사가
그날 실제로 받아졌다는 것까지가 한계다. **요약이 그 기사에 충실한지는 검사하지 않는다** —
실제 guid 를 달고 전혀 다른 내용을 300자 쓰면 통과한다. 한국어 요약과 영문 원문을 기계로
대조할 방법이 없기 때문이고, 그 자리는 작성 계약과 사후 검토 게이트가 맡는다. 설계 설명에
「지어낸 헤드라인을 막는다」고 쓰더라도 **막는 것은 존재하지 않는 기사이지 부정확한 요약이
아니다** — 이 구분을 흐리면 검사받지 않은 것을 검사받았다고 믿게 된다.

**구조를 정규식으로 읽지 않는다** (2026-09-19 codex 2차 검토). 1차 수정은 정규식으로
`<div>` 깊이를 셌는데, 2차에서 속성값의 `</section>`·script 문자열의 `</div>`·
작은따옴표 속성·`<section hidden>` 조상·`&nbsp;` 패딩이 줄줄이 뚫렸다. 정규식을 한 겹씩
덧대는 동안 매번 새 우회로가 나왔다 — **표준 라이브러리 파서가 이 싸움의 정답이다.**
`html.parser` 는 따옴표·텍스트 문맥·속성을 스스로 가르므로 그 부류가 통째로 닫힌다.

비-코어다. 피드가 죽어 수집분이 비면 **섹션을 실을 의무**는 면제된다. 다만 **실은 것을
대조받을 의무는 면제되지 않는다**(1차 #1) — 수집이 실패한 날이 지어낸 뉴스가 실릴 확률이
가장 높은 날이다.

Pure — `check()` 는 문자열과 dict 를 받아 위반 메시지 목록을 돌려준다.
"""

import re
from html.parser import HTMLParser

from .news import DIGEST_CATEGORIES

TITLE = '오늘의 뉴스'

# 한 항목 300자(2026-09-19 사용자 지시). 밴드로 두는 이유 — 정확히 300자를 요구하면
# 마지막 문장이 분량에 맞춰 잘리거나 늘어난다. 하한은 「RSS 요약을 옮긴 것」을 걸러 내는
# 값이고(영어 description 중앙값 136자 → 한국어 80~100자), 상한은 한 항목이 섹션을
# 삼키는 것을 막는 값이다.
MIN_CHARS = 240
MAX_CHARS = 420

# 뉴스 섹션 안에서 표식 없이 흐르는 산문의 허용치. `<article>`·`<li>` 로 갈아입으면
# 블록 검사를 통째로 비껴갔다(1차 #10). 제목·표·캡션은 조판이므로 세지 않는다(2차 #8b).
STRAY_MAX = 200

# 분량에서 빼는 것 — 제목 줄과 캡션을 늘려 하한을 채우는 우회를 막는다.
_SKIP_CLASSES = ('news-head', 'caption', 'sub')
_SKIP_TAGS = ('script', 'style', 'template', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
              'table', 'figcaption')
_HIDDEN_STYLE = re.compile(r'display\s*:\s*none|visibility\s*:\s*hidden', re.I)


def _is_hidden(attrs):
    if 'hidden' in attrs:
        return True
    return bool(_HIDDEN_STYLE.search(attrs.get('style') or ''))


def _is_item(attrs):
    return 'data-news' in attrs or 'news-item' in (attrs.get('class') or '')


class _Reader(HTMLParser):
    """문서를 한 번 훑어 뉴스 블록과 그 안에서 독자가 보는 글자를 모은다.

    `convert_charrefs` 기본값이 엔티티를 풀어 주므로 `&nbsp;`·`&#44032;` 패딩이
    저절로 잡힌다(2차 #7). 스택은 **모든 요소**를 타므로 `<section hidden>` 같은
    div 아닌 조상의 숨김도 전파된다(2차 #5).
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []          # [(tag, hidden, skip, item_or_None)]
        self.items = []          # [{'guid', 'chars', 'links', 'hidden'}]
        self.section = None      # 「오늘의 뉴스」 구간에서 모은 것
        self._in_title = False
        self._title = ''
        self._title_depth = 0
        self.section_depth = None
        self.section_items = []
        self.section_stray = 0

    # ── 구조 ──────────────────────────────────────────────────────────
    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or '') for k, v in attrs}
        parent = self.stack[-1] if self.stack else None
        hidden = (parent[1] if parent else False) or _is_hidden(a)
        skip = (parent[2] if parent else False) or tag in _SKIP_TAGS or any(
            c in (a.get('class') or '') for c in _SKIP_CLASSES)
        item = parent[3] if parent else None
        if _is_item(a) and item is None:
            item = {'guid': a.get('data-news'), 'chars': 0, 'links': [],
                    'hidden': hidden, 'in_section': self.section_depth is not None}
            self.items.append(item)
            if self.section_depth is not None:
                self.section_items.append(item)
        if tag in ('h2', 'h3') and self.section_depth is None:
            self._in_title, self._title = True, ''
            self._title_depth = len(self.stack)
        if tag == 'a' and item is not None and not hidden:
            item['links'].append(a.get('href') or '')
        if tag not in ('br', 'img', 'hr', 'meta', 'link', 'input'):
            self.stack.append((tag, hidden, skip, item))

    def handle_endtag(self, tag):
        idx = None
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                idx = i
                break
        if tag in ('h2', 'h3'):
            self._in_title = False
            if self._title.strip() == TITLE and self.section_depth is None:
                # 구간은 **제목을 담은 요소**부터 그 요소가 닫힐 때까지다.
                # 제목 자신의 깊이를 잡으면 바로 다음 줄에서 지워진다.
                self.section_depth = max(self._title_depth - 1, 0)
            self._title = ''
        if idx is None:
            return
        if self.section_depth is not None and idx <= self.section_depth:
            self.section_depth = None
        del self.stack[idx:]

    def handle_data(self, data):
        if self._in_title:
            self._title += data
        text = re.sub(r'\s+', '', data)
        if not text:
            return
        top = self.stack[-1] if self.stack else None
        if top is None:
            return
        _, hidden, skip, item = top
        if hidden or skip:
            return
        if item is not None:
            item['chars'] += len(text)
        elif self.section_depth is not None:
            self.section_stray += len(text)


def _read(html):
    r = _Reader()
    try:
        r.feed(html or '')
        r.close()
    except Exception:
        pass                      # 조판이 깨진 날에도 모은 데까지 쓴다
    return r


def check(html, collected, report_date=None):
    """-> 위반 메시지 목록. 빈 목록이면 통과."""
    items = (collected or {}).get('items') or []
    # guid 는 **매체 안에서만** 고유하다 — 게이트도 수집기와 같은 범위를 써야
    # 한쪽에서 가른 것이 다른 쪽에서 합쳐지지 않는다(2차 #9).
    known = {}
    for it in items:
        known.setdefault(_key(it.get('source'), it.get('guid')), it)
        known.setdefault(_key(None, it.get('guid')), it)

    v = []
    got = (collected or {}).get('report_date')
    if items and report_date:
        if not got:
            v.append('수집분에 report_date 가 없다 — 오늘 것인지 확인할 수 없다')
        elif got != report_date:
            v.append(f'수집분이 {got} 자다 — 오늘({report_date}) 발행본의 '
                     f'근거가 될 수 없다')

    doc = _read(html)
    hidden = [it for it in doc.items if it['hidden']]
    if hidden:
        v.append(f'숨겨진 뉴스 블록 {len(hidden)}개 — 독자가 보지 못하는 항목은 '
                 f'실은 것으로 치지 않는다')

    visible = [it for it in doc.items if not it['hidden']]
    unmarked = sum(1 for it in visible if not it['guid'])
    if unmarked:
        v.append(f'`data-news` 가 없는 뉴스 블록 {unmarked}개 — 표식 없는 항목은 '
                 f'수집분과 대조할 수 없다')

    seen = set()
    for it in visible:
        guid = it['guid']
        if not guid:
            continue
        if guid in seen:
            v.append(f'같은 기사를 두 번 실었다 (중복 `data-news="{guid}"`)')
            continue
        seen.add(guid)
        v.extend(_check_one(guid, it, known))

    if doc.section_stray > STRAY_MAX:
        v.append(f'뉴스 섹션에 표식 밖 산문이 {doc.section_stray}자 있다 '
                 f'(허용 {STRAY_MAX}자) — 기사는 `data-news` 블록 안에 둔다')

    # 다이제스트 섹션은 **본문까지 확보된** 갈래 기사가 있는 날에만 요구한다(1차 #5).
    usable = [it for it in items
              if it.get('category') in DIGEST_CATEGORIES and it.get('body_chars')]
    if usable:
        if TITLE not in (html or ''):
            v.append(f'뉴스 섹션(「{TITLE}」)을 찾을 수 없다 — 수집분 {len(usable)}건')
        elif not [i for i in doc.section_items if i['guid'] and not i['hidden']]:
            v.append(f'뉴스 섹션에 항목이 하나도 없다 — `data-news` 를 단 블록이 '
                     f'필요하다 (수집분 {len(usable)}건)')
    return v


def _key(source, guid):
    return f'{source or ""}\x00{guid}'


def _check_one(guid, block, known):
    """항목 하나 — 실재·본문·분량·링크."""
    row = known.get(_key(None, guid))
    if row is None:
        return [f'`data-news="{guid}"` 는 그날 수집분에 없다 — '
                f'수집되지 않은 기사는 인용할 수 없다']
    if not row.get('body_chars'):
        note = row.get('body_note') or '사유 미기재'
        return [f'`data-news="{guid}"` 는 본문을 받지 못했다({note}) — '
                f'제목만 보고 요약을 쓸 수 없다']

    v = []
    n = block['chars']
    if n < MIN_CHARS:
        v.append(f'`data-news="{guid}"` 요약이 {n}자로 짧다 (하한 {MIN_CHARS}자) '
                 f'— RSS 한 줄 요약을 옮긴 것이 아닌지 볼 것')
    elif n > MAX_CHARS:
        v.append(f'`data-news="{guid}"` 요약이 {n}자로 길다 (상한 {MAX_CHARS}자)')

    own = row.get('url')
    for href in block['links']:
        if href.startswith('#') or href == own:
            continue
        v.append(f'`data-news="{guid}"` 블록의 링크 {href} 는 이 기사의 원문이 '
                 f'아니다 — 근거로 삼은 문서만 건다')
    return v
