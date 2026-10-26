"""일본 일간 「일본 경제 뉴스」 — 그날 16:30 JST 컷까지의 경제 기사 (2026-10-27).

주간 수집 계약(끝난 날만 동결하는 `japan/data/news/<date>.json`)은 건드리지 않는다. 일간은 따로
`japan/data/news/daily/<session>.json` 을 만들고 동결 개념이 없다 — 그날 저녁의 스냅샷이다.
선별(매체 허용 목록·유료·정례 단신·같은 사건)은 `japan.news` 를 그대로 쓰고, 일간만의 차이는 셋이다.
① 갈래는 경제 넷(macro·policy·industry·market) — global·insight 는 뺀다(사용자 「경제 뉴스 위주」).
② 일본은행 공식 연설은 주간에선 insight 지만 일간에선 macro 로 옮긴다 — 공유 분류는 그대로(codex #15).
③ 컷 필터는 갈래별 후보 상한 **전에** 건다(codex #6) — 컷 뒤 기사가 후보 자리를 먹지 않게.

Pure — 네트워크 없음.
"""
import re
from datetime import datetime

from japan import news as N

DAILY_CATEGORIES = ('macro', 'policy', 'industry', 'market')
CUT = '16:30'
PER_CATEGORY = N.PER_CATEGORY
TITLE = '일본 경제 뉴스'
_BOJ = re.compile(r'^https?://(www\.)?boj\.or\.jp/', re.I)


def retag(rows):
    out = []
    for r in rows or []:
        cat = r.get('category')
        if cat == 'insight' and r.get('official') and _BOJ.match(r.get('url') or ''):
            out.append(dict(r, category='macro'))
        elif cat in DAILY_CATEGORIES:
            out.append(r)
    return out


def _hhmm(text):
    m = re.fullmatch(r'(\d{1,2}):(\d{2})', text or '')
    return f'{int(m.group(1)):02d}:{m.group(2)}' if m else None


def published_ok(published, session, cut=CUT):
    try:
        ts = datetime.fromisoformat(published).astimezone(N.JST)
    except (TypeError, ValueError):
        return False
    return ts.date().isoformat() == session and ts.strftime('%H:%M') <= cut


def cut_filter(rows, session, today, cut=CUT):
    """목록 단계 컷. 시각이 있는 목록 행(「15:10」)과 공식 행(`published`)만 판정할 수 있다 —
    날짜만 있는 목록 행(「10/26」)은 그날 시각을 알 수 없어 뺀다."""
    out = []
    for r in rows or []:
        if r.get('published'):
            if published_ok(r['published'], session, cut):
                out.append(r)
            continue
        hm = _hhmm(r.get('created'))
        if hm and N.list_day(r.get('created'), today) == session and hm <= cut:
            out.append(r)
    return out


def finalize_daily(rows, session, per=PER_CATEGORY, cut=CUT):
    """본문을 받은 뒤 확정 — 본문이 있고, 기사면 시각이 세션 날 컷 안이며, 이미 고른 기사와 같은 사건이 아닌 것."""
    taken = []
    for cat in DAILY_CATEGORIES:
        n = 0
        for r in rows or []:
            if r.get('category') != cat or n >= per:
                continue
            if not r.get('body_chars') or not published_ok(r.get('published'), session, cut):
                continue
            if any(N.same_event(r.get('title'), t.get('title')) for t in taken):
                continue
            taken.append(r)
            n += 1
    return taken
