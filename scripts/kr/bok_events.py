"""한국은행 금통위 문서 — 목록 읽기와 결정문 변경점. 네트워크 없음 (2026-11-27).

수집은 `scripts/collect_bok_events.py`, 검사는 `scripts/kr/bok_gate.py`. 원천(2026-11-27 실측):
  · 결정문 RSS `/portal/bbs/P0000559/news.rss?menuNo=200690` — 제목 「통화정책방향(YYYY.M.D)」, description 에 본문 HTML
    (□ 7문단). 결정일 10:30 게시. 회의 일정·자료 표(listYear.do)의 결정문 칸은 다음 날에도 비어 있어 RSS 로만 감지한다.
  · 기자간담회 `listYear.do?mtgSe=A&menuNo=200755&pYear=YYYY` 의 그날 행 — 모두발언 PDF(fileDown.do) + 질의응답 자막
    (`B0000169/view.do … programType=multiCont` 의 `<div class="subtitle">`).
  · 의사록 RSS `/portal/bbs/B0000245/news.rss?menuNo=200789` → view.do 의 첨부 PDF. 게시는 「회의일로부터 2주 경과 후
    첫 화요일」(listYear.do 각주). view.do 의 첨부 링크는 `/fileSrc/` 라 robots 가 막는다 — 같은 첨부 ID 로
    `/portal/cmmn/file/fileDown.do` 주소를 만들어 받는다.
"""
import datetime as _dt
import difflib
import html as _html
import re

from common.cb_quote import normalize_cjk
from us.fed_events import parse_feed

BASE = 'https://www.bok.or.kr'
DECISION_RSS = BASE + '/portal/bbs/P0000559/news.rss?menuNo=200690'
MINUTES_RSS = BASE + '/portal/bbs/B0000245/news.rss?menuNo=200789'
LIST_YEAR = BASE + '/portal/singl/crncyPolicyDrcMtg/listYear.do?mtgSe=A&menuNo=200755&pYear={year}'
FILE_DOWN = BASE + '/portal/cmmn/file/fileDown.do?menuNo={menu}&atchFileId={atch}&fileSn={sn}'
MINUTES_MENU = '200789'

_DECISION_TITLE = re.compile(r'^통화정책방향\((\d{4})\.(\d{1,2})\.(\d{1,2})\)$')
_MINUTES_TITLE = re.compile(r'^금융통화위원회 의사록\(\d{4}년 제\d+차\)\((\d{4})\.(\d{1,2})\.(\d{1,2})\)$')
_TAG = re.compile(r'<[^>]+>')


def _iso(y, m, d):
    return '%04d-%02d-%02d' % (int(y), int(m), int(d))


def flatten(fragment):
    """HTML 조각 → 공백을 하나로 접은 글. 블록 경계는 공백."""
    t = re.sub(r'<(script|style)[^>]*>.*?</\1>', ' ', fragment or '', flags=re.S | re.I)
    return re.sub(r'\s+', ' ', _html.unescape(_TAG.sub(' ', t))).strip()


def decision_items(xml):
    """결정문 RSS → [{meeting_date, link, published, text}]. 의사록 등 다른 글은 뺀다."""
    out = []
    for it in parse_feed(xml):
        m = _DECISION_TITLE.match((it.get('title') or '').strip())
        if m:
            out.append({'meeting_date': _iso(*m.groups()), 'link': it['link'], 'published': it['published'],
                        'title': it['title'], 'text': flatten(it.get('description') or '')})
    return out


def minutes_items(xml):
    """의사록 RSS → [{meeting_date, link, published}]."""
    out = []
    for it in parse_feed(xml):
        m = _MINUTES_TITLE.match((it.get('title') or '').strip())
        if m:
            out.append({'meeting_date': _iso(*m.groups()), 'link': it['link'], 'published': it['published'],
                        'title': it['title']})
    return out


_ROW = re.compile(r'<tr>\s*<th scope="row">\s*(\d{1,2})월\s*(\d{1,2})일\([^)]*\)\s*</th>(.*?)</tr>', re.S)
_SUBTITLE_VIEW = re.compile(r"href='(/portal/bbs/B0000169/view\.do\?[^']*programType=multiCont)'")
_OPENING_PDF = re.compile(r'href="(/portal/cmmn/file/fileDown\.do\?[^"]+)"\s+title="[^"]*모두발언[^"]*\.pdf"')


def presser_row(page, meeting_date):
    """listYear.do 페이지에서 그 회의일 행의 (자막 view.do 주소 | None, 모두발언 PDF fileDown 주소 | None).

    행이 없으면 (None, None). 같은 칸의 첫 PDF 는 「참고자료」 라 제목으로 모두발언을 고른다.
    뷰어 링크(`/static/…/fileSrc/`)는 robots 가 막으므로 쓰지 않는다.
    """
    y, m, d = (int(x) for x in meeting_date.split('-'))
    for row in _ROW.finditer(page or ''):
        if (int(row.group(1)), int(row.group(2))) != (m, d):
            continue
        cells = row.group(3)
        view = _SUBTITLE_VIEW.search(cells)
        pdf = _OPENING_PDF.search(cells)
        return (BASE + _html.unescape(view.group(1)) if view else None,
                BASE + _html.unescape(pdf.group(1)) if pdf else None)
    return None, None


_SUBTITLE = re.compile(r'<div class="subtitle">.*?<div class="con scrollY">(.*?)</div>', re.S)


def subtitle_text(page):
    """자막 HTML → 글(발언 사이는 줄바꿈). 자막 칸이 없거나 비면 None."""
    m = _SUBTITLE.search(page or '')
    if not m:
        return None
    parts = [flatten(p) for p in re.split(r'<br\s*/?>', m.group(1))]
    text = '\n'.join(p for p in parts if p)
    return text or None


_FILESRC = re.compile(r'href="/fileSrc/portal/([0-9a-f]{32})/(\d+)/[^"]+\.pdf"\s+title="([^"]*\.pdf)"')


def minutes_pdf(view_page):
    """의사록 view.do → 첨부 PDF 의 fileDown 주소(robots 허용 경로). 없으면 None."""
    m = _FILESRC.search(view_page or '')
    if not m:
        return None
    return FILE_DOWN.format(menu=MINUTES_MENU, atch=m.group(1), sn=m.group(2))


def minutes_date(meeting_date):
    """의사록 게시 예정일 — 회의일로부터 2주 경과 후 첫 화요일(listYear.do 각주). 2주째 날이 화요일이면 그다음 주."""
    d = _dt.date.fromisoformat(meeting_date) + _dt.timedelta(days=14)
    return (d + _dt.timedelta(days=(1 - d.weekday()) % 7 or 7)).isoformat()


# ── 결정문 변경점: □ 7문단 ────────────────────────────────────────────────────────
# 결정·세계·국내·물가·금융외환·향후 방향·표결 — 2026-02 결정문부터 매번 같은 순서(그 전은 표결 문단이 없는 6문단).
PARAGRAPHS = 7
PARA_NAMES = ('결정', '세계경제', '국내경제', '물가', '금융·외환시장', '향후 운용 방향', '표결')
_SENT = re.compile(r'(?<=다)\s*\.\s*')


def paragraphs(text):
    """결정문 본문 → □ 문단 목록(첫 □ 앞의 제목은 버린다). 7개가 아니면 None — 비교를 포기한다."""
    if not text or '□' not in text:
        return None
    parts = [re.sub(r'\s+', ' ', p).strip() for p in text.split('□')[1:]]
    parts = [p for p in parts if p]
    return parts if len(parts) == PARAGRAPHS else None


def _sentences(par):
    return [s.strip() + '.' for s in _SENT.split(par) if s.strip()]


def paragraph_diff(prev_text, curr_text):
    """직전 결정문 대비 문단 단위 변경점. 어느 쪽이든 7문단으로 자를 수 없으면 None.

    {'changed': [{para, name, before, after, ratio, sentences}], 'kept': n} — `sentences` 는 직전 문단에 없던
    새 문장(공백 무시 대조)이다. 게이트는 변경점 블록이 그 가운데 하나를 원문 그대로 옮겼는지 본다.
    """
    a, b = paragraphs(prev_text), paragraphs(curr_text)
    if a is None or b is None:
        return None
    changed, kept = [], 0
    for i, (old, new) in enumerate(zip(a, b), 1):
        no, nn = normalize_cjk(old), normalize_cjk(new)
        if no == nn:
            kept += 1
            continue
        old_set = {normalize_cjk(s) for s in _sentences(old)}
        changed.append({'para': i, 'name': PARA_NAMES[i - 1], 'before': old, 'after': new,
                        'ratio': round(difflib.SequenceMatcher(None, no, nn, autojunk=False).ratio(), 3),
                        'sentences': [s for s in _sentences(new) if normalize_cjk(s) not in old_set]})
    return {'changed': changed, 'added': [], 'removed': [], 'kept': kept}
