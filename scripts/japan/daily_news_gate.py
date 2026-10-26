"""일본 일간 「일본 경제 뉴스」 게이트 (2026-10-27).

공용 `us.news_gate.check` 의 `categories` 는 절을 실을 의무만 정한다 — 블록마다의 갈래·건수·같은 사건·
날짜·컷은 보지 않는다(codex 설계 검토 #6, 재현 4건 통과). 그래서 여기서 더 본다: 블록은 news 절 안에만,
허용 갈래만, 갈래당 3건, 같은 사건 금지, 수집분 기사의 JST 시각이 세션 날 16:30 이하.
"""
from japan import gate as JG
from japan import news as N
from japan.news_daily import CUT, DAILY_CATEGORIES, PER_CATEGORY, TITLE, published_ok
from us import news_gate


def check(html, collected, session):
    v = []
    items = (collected or {}).get('items') or []
    nodes = JG._news_nodes(html)
    outside = [it for it in nodes.items if it['section'] != 'news']
    if outside:
        v.append(f'`data-news` 블록 {len(outside)}개가 「{TITLE}」 절 밖에 있다 — 기사는 그 절 안에만 둔다')
    if nodes.sections.count('news') > 1:
        v.append('news 절이 둘 이상이다')
    if 'news' in nodes.sections:
        titles = [t for t in nodes.titles if t]
        if not titles or titles[0] != TITLE:
            v.append(f'news 절의 제목은 보이는 <h2>「{TITLE}」 이다')
    v += news_gate.check(html, collected, session, categories=DAILY_CATEGORIES, title=TITLE)
    by_guid = {str(r.get('guid')): r for r in items}
    guids = [it['guid'] for it in nodes.items if it['section'] == 'news' and not it['hidden'] and it['guid']]
    chosen = [by_guid[g] for g in dict.fromkeys(guids) if g in by_guid]
    for r in chosen:
        if r.get('category') not in DAILY_CATEGORIES:
            v.append(f'「{r.get("title")}」 은 {r.get("category")} 갈래 — 일간은 경제 갈래'
                     f'({"·".join(N.LABELS[c] for c in DAILY_CATEGORIES)})만 싣는다')
        if not published_ok(r.get('published'), session, CUT):
            v.append(f'「{r.get("title")}」 의 시각 {r.get("published")} 이 {session} {CUT} JST 컷 밖이다')
    for cat in DAILY_CATEGORIES:
        n = sum(1 for r in chosen if r.get('category') == cat)
        if n > PER_CATEGORY:
            v.append(f'{N.LABELS[cat]} 갈래에 {n}건 — 갈래당 {PER_CATEGORY}건까지')
    for i, a in enumerate(chosen):
        for b in chosen[i + 1:]:
            if N.same_event(a.get('title'), b.get('title')):
                v.append(f'같은 사건을 두 번 실었다 — 「{a.get("title")}」 · 「{b.get("title")}」')
    return v
