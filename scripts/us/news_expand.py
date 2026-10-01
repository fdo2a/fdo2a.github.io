"""뉴스 블록을 수집 요약으로 채운다 — 작성자가 요약 26건을 다시 옮겨 쓰지 않게.

2026-09-26 뉴스·산업 브리프 작성자는 25만 토큰·20분을 썼고, 대부분이 `summary_ko` 를 다듬어
옮기다 게이트(유사도·문체)에 걸려 고치는 반복이었다. 게이트가 요약과 50% 이상 같기를 요구하는
글을 사람 손으로 다시 쓸 이유가 없다. 작성자는 기사마다 한 줄만 쓴다:

    <!--NEWS:<guid>|<한국어 제목>-->
    <!--NEWS:<guid>|<한국어 제목>|<그날 시세와 잇는 한 문장>-->

이 모듈이 캡션·요약을 채운 표준 블록으로 바꾼다. 요약 문단에는 `data-summary` 를 달아
문체 게이트의 어미 반복 검사에서 뺀다(문장을 쓴 것은 수집 단계의 요약기다). 그 대신 뉴스
게이트가 `data-summary` 문단이 요약 원문 그대로인지 본다 — 이 표시 안에 산문을 숨기는 길을 막는다.
`-습니다` 로 끝나는 요약은 채우지 않고 오류로 돌려준다(데스크 문서는 `-다` 고정 — 그 기사만
작성자가 직접 쓴다).
"""
import html as _html
import re

PLACEHOLDER = re.compile(r'<!--NEWS:([^|>]+)\|([^|>]*?)(?:\|([^>]*?))?-->')
_POLITE = re.compile(r'(습니다|니다|어요|아요|해요|세요)[.!?]?\s*$')
LINK_MAX = 80

_ORGS = (('boj.or.jp', '일본은행'), ('nli-research.co.jp', '닛세이기초연구소'))


def caption(item):
    url = item.get('url') or ''
    name = next((ko for dom, ko in _ORGS if dom in url), None)
    if name is None:
        wire = item.get('wire')
        if wire == 'Reuters':
            name = f"로이터({item.get('source') or 'Investing.com'})"
        else:
            name = wire or item.get('source') or ''
    day = (item.get('published') or '')[:10]
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', day):
        _, m, d = day.split('-')
        return f'{name} · {int(m)}월 {int(d)}일'
    return name


def _sentences(text):
    return [s for s in re.split(r'(?<=[.!?])\s+', text.strip()) if s]


def expand(body, news):
    """-> (확장된 본문, 오류 목록). 오류가 있어도 채울 수 있는 것은 채운다."""
    items = {str(it.get('guid')): it for it in (news or {}).get('items') or []}
    errors = []

    def repl(m):
        guid, title, link = m.group(1).strip(), m.group(2).strip(), (m.group(3) or '').strip()
        it = items.get(guid)
        if it is None:
            errors.append(f'NEWS:{guid} — 그날 수집분에 없는 기사다')
            return m.group(0)
        summary = (it.get('summary_ko') or '').strip()
        if not summary:
            errors.append(f'NEWS:{guid} — 요약(summary_ko)이 없다({it.get("summary_note") or "사유 미기록"})')
            return m.group(0)
        if not title:
            errors.append(f'NEWS:{guid} — 한국어 제목이 비었다')
            return m.group(0)
        polite = [s for s in _sentences(summary) if _POLITE.search(s)]
        if polite:
            errors.append(f'NEWS:{guid} — 요약에 -습니다 어미가 있다(「{polite[0][-20:]}」) — '
                          '이 기사는 블록을 직접 쓴다')
            return m.group(0)
        if len(link) > LINK_MAX:
            errors.append(f'NEWS:{guid} — 연결 문장이 {len(link)}자다({LINK_MAX}자까지)')
            return m.group(0)
        text = _html.escape(summary, quote=False)
        if link:
            text += ' ' + _html.escape(link, quote=False)
        return (f'<div class="news-item" data-news="{_html.escape(guid)}">'
                f'<p class="news-head">{_html.escape(title, quote=False)}'
                f'<span class="sub">{_html.escape(caption(it), quote=False)}</span></p>'
                f'<p data-summary="{_html.escape(guid)}">{text}</p></div>')

    return PLACEHOLDER.sub(repl, body), errors


# 표시가 어떤 따옴표 꼴이든 찾는다. 문체 면제는 확장기가 만드는 큰따옴표 꼴에만 주므로(style.py),
# 다른 꼴로 표시한 문단은 면제 없이 문체 검사도 받고 여기서 원문 대조도 받는다(codex #6).
_SUMMARY_P = re.compile(
    r"""<p\b[^>]*?\bdata-summary\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))[^>]*>(.*?)</p>""",
    re.S | re.I)
_TAG = re.compile(r'<[^>]+>')


def _ws(s):
    return re.sub(r'\s+', ' ', s).strip()


def summary_violations(html, news):
    """`data-summary` 문단이 요약 원문(+ 연결 한 문장)인지. 문체 검사 면제를 산문 은신처로 쓰지 못하게.

    원문 요약은 **해제하지 않는다** — 확장기는 원문을 한 번 이스케이프해 넣으므로, 생성 문단만
    한 번 해제하면 화면 글자끼리 같아진다. 둘 다 해제하면 원문에 글자 그대로 있던 `&amp;` 가
    어긋난다(codex #7).
    """
    items = {str(it.get('guid')): it for it in (news or {}).get('items') or []}
    v = []
    for m in _SUMMARY_P.finditer(html or ''):
        guid = next(g for g in m.groups()[:3] if g is not None)
        it = items.get(guid)
        want = _ws((it or {}).get('summary_ko') or '')
        got = _ws(_html.unescape(_TAG.sub('', m.group(4))))
        if not want or not got.startswith(want):
            v.append(f'`data-summary="{guid}"` 문단이 수집 요약 원문이 아니다 — 이 표시는 '
                     'expand_news_items.py 가 채운 문단에만 붙는다. 직접 쓴 문단에서는 뺀다')
        elif len(got) - len(want) > LINK_MAX + 1:
            v.append(f'`data-summary="{guid}"` 문단에 요약 밖 문장이 {len(got) - len(want)}자 붙었다 '
                     f'({LINK_MAX}자까지 — 시세 연결 한 문장)')
    return v
