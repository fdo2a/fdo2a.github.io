"""일본 주간 발행 게이트. CLI: scripts/check_japan.py.

막는 것:
- 수치 창작 — 진단 파일과 그 주 일본 뉴스 요약에 없는 숫자
- 부호 뒤집기 — 「해외채권 순매수」가 실제로는 순매도인 문장(주간/4주 구분)
- 근사를 정밀로 — 헤지를 말하는 문단에 「근사」가 없음
- 기준일 누락 — CFTC 포지션을 말하면서 화요일 기준일을 밝히지 않음
- 한쪽 시나리오만 — 시나리오 절이 두 갈래를 다 말하지 않음
- 못 받은 소스 — 스냅샷 실패가 남아 있음
- 「이번 주 뉴스」 — 게재 후보(`digest`)만, 그 절 안에서만, 갈래당 3건, 같은 사건 두 번 금지(2026-10-18)
"""
import re
import unicodedata
from html.parser import HTMLParser

from japan.news import DIGEST_CATEGORIES, LABELS, PER_CATEGORY, same_event
from japan.render import NEWS_TITLE, ORDER, SECTIONS
from us import news_gate
from us.news_summary import summary_problem
from scripts.common import commentary

COMMENTARY_SECTIONS = ('curve', 'yen', 'flows', 'equity')
from us.period_gate import _canon, _NUM, _numbers, _united_numbers
from us.post_check import body_text, mask_dates

_SEC = re.compile(r'<section\b[^>]*\bdata-section="([a-z]+)"[^>]*>(.*?)</section>', re.S)
_P = re.compile(r'<p\b(?![^>]*class="caption")[^>]*>(.*?)</p>', re.S)
_TAG = re.compile(r'<[^>]+>')
_TABLE = re.compile(r'<table\b.*?</table>', re.S)
_SENT = re.compile(r'[^.!?。]+[.!?。]?')
_BOND = re.compile(r'해외\s*(중장기)?\s*채권|해외\s*중장기채|외국\s*채권')
_JPEQ = re.compile(r'(외국인|비거주자)[^.。]{0,30}일본\s*주식')


# 「9월 17~18일」「10월 1일」 — 한국어 날짜. 「2026-W39」 — 주 키. 둘 다 수치가 아니다.
_KDATE = re.compile(r'\d{1,2}월\s*\d{1,2}(?:\s*[~∼\-–]\s*\d{1,2})?일')
_WEEKKEY = re.compile(r'\d{4}-W\d{2}')
_JO_EOK = re.compile(r'(\d+)조\s*([\d,]+)억')


_JO_ONLY = re.compile(r'(\d+(?:\.\d+)?)조(?!\s*[\d,]+억)')


def _jo_eok(text):
    """「1조 6,065억」 → 「16065억」, 「2조」 → 「20000억」. 조·억으로 쪼개 쓰면 원천값과 대조되지
    않고, 단독 「조」는 작은 정수로 면제되던 길이다(codex 2026-09-27 #13)."""
    text = _JO_EOK.sub(lambda m: f'{int(m.group(1)) * 10000 + int(m.group(2).replace(",", ""))}억', text)
    return _JO_ONLY.sub(lambda m: f'{float(m.group(1)) * 10000:g}억', text)


def _figures(html):
    return _text_figures(body_text(html))


def _text_figures(text):
    """본문과 뉴스 원천에 **같은** 정규화를 건다 — 요약의 「2조 엔」 이 본문에선 20000억, 원천에선 2 로
    갈려 오탐이 났다(codex 2026-10-18 #6). 일본어 제목의 전각 숫자는 NFKC 로 푼다."""
    text = _jo_eok(unicodedata.normalize('NFKC', text or ''))
    text = _WEEKKEY.sub(' ', _KDATE.sub(' ', text))
    text = mask_dates(text).replace(',', '').replace('−', '-')
    return {_canon(m) for m in _NUM.findall(text)}


def _prose(fragment):
    frag = _TABLE.sub(' ', fragment)
    return [re.sub(r'\s+', ' ', _TAG.sub(' ', p)).strip() for p in _P.findall(frag)]


def _date_forms(iso):
    y, m, d = iso.split('-')
    return (iso, f'{int(m)}월 {int(d)}일', f'{int(m)}/{int(d)}')


def _sign_check(sentences, pattern, weekly_word, four_word, what):
    v = []
    for s in sentences:
        if not pattern.search(s):
            continue
        says = [w for w in ('순매수', '순매도') if w in s]
        if len(says) != 1:
            continue
        expect = four_word if '4주' in s else weekly_word
        if expect and says[0] != expect:
            v.append(f'{what}: 문장은 「{says[0]}」인데 자료는 「{expect}」다 — 「{s[:50]}」')
    return v


_JA_DATE = re.compile(r'(?:\d{1,2}月)?\d{1,2}(?:\s*[~〜\-–]\s*\d{1,2})?日|\d{1,2}月')


def title_source(title):
    """일본어 원제목을 수치 원천으로 넣기 전에 月·日 날짜를 가린다 — 「10月16日」 의 16 이 본문의 창작
    「16%」 를 통과시켰다(codex 구현 #6)."""
    return _JA_DATE.sub(' ', unicodedata.normalize('NFKC', title or ''))


class _NewsNodes(HTMLParser):
    """뉴스 블록과 그 조상 `data-section`, 「이번 주 뉴스」 절의 제목을 파서로 읽는다 — 정규식은 홑따옴표·
    대문자 속성·class 변경으로 비켜 갔다(codex 구현 #1). 숨김 판정은 공용 뉴스 게이트와 같다."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []           # [(tag, section, hidden, item)]
        self.items = []           # [{guid, section, hidden}]
        self.sections = []        # <section data-section> 의 이름, 문서 순서
        self.titles = []          # news 절 h2 의 **보이는** 글자
        self._h2 = None

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or '') for k, v in attrs}
        top = self.stack[-1] if self.stack else ('', None, False, None)
        # 절은 <section> 요소만 정한다 — 블록이 자기 속성으로 절을 자칭하지 못한다(codex 재검토 #1)
        section = top[1]
        if tag == 'section' and 'data-section' in a:
            section = a['data-section']
            self.sections.append(section)
        hidden = top[2] or news_gate._is_hidden(a)
        item = top[3]
        if item is None and news_gate._is_item(a):
            item = {'guid': a.get('data-news') or None, 'section': section, 'hidden': hidden}
            self.items.append(item)
        if tag == 'h2' and section == 'news':
            self._h2 = []
        if tag not in ('br', 'img', 'hr', 'meta', 'link', 'input', 'wbr', 'source'):
            self.stack.append((tag, section, hidden, item))

    def handle_endtag(self, tag):
        if tag == 'h2' and self._h2 is not None:
            self.titles.append(''.join(self._h2).strip())
            self._h2 = None
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        # 자식 요소의 숨김까지 본다 — <h2><span hidden>제목</span></h2> (codex 재검토 #9)
        if self._h2 is not None and not (self.stack and self.stack[-1][2]):
            self._h2.append(data)


def _news_nodes(html):
    r = _NewsNodes()
    try:
        r.feed(html or '')
        r.close()
    except Exception:
        pass
    return r


def check_news(html, secs, names, digest):
    """「이번 주 뉴스」. 후보는 일본 전용 수집분의 `digest` 행뿐이다 — 구형 주(W40·W41)는 후보가 없어 면제."""
    v = []
    rows = [r for r in digest or [] if r.get('summary_ko') and r.get('category') in DIGEST_CATEGORIES]
    # 실을 수 없는 요약(가나·한자·두 문단·자기 정정)은 후보가 아니다. 그래도 그 행을 실으면 뉴스 게이트가
    # 사유를 대고 막도록 행 자체는 넘긴다 — 4a1500c 이전 판정으로 만든 <KEY>.news.json 이 남을 수 있다(2026-10-18)
    usable = [r for r in rows if summary_problem(r['summary_ko']) is None]
    nodes = _news_nodes(html)
    outside = [it for it in nodes.items if it['section'] != 'news']
    if outside:
        v.append(f'`data-news` 블록 {len(outside)}개가 「이번 주 뉴스」 절 밖에 있다 — 기사는 그 절 안에만 둔다')
    # 절 목록은 파서와 정규식이 같아야 한다 — 홑따옴표 절은 정규식이 못 보고 파서만 본다(codex 재검토 #11)
    if nodes.sections.count('news') > 1 or [n for n in nodes.sections if n in ORDER] != \
            [n for n in names if n in ORDER]:
        v.append('data-section 절 표기가 표준이 아니거나 news 절이 둘 이상이다 — '
                 '<section data-section="이름"> 꼴로 한 번씩만')
    if 'news' not in names:
        if usable:
            v.append(f'data-section="news" 절이 없다 — 이번 주 뉴스 후보 {len(usable)}건')
        return v
    visible = [t for t in nodes.titles if t]
    if not visible or visible[0] != NEWS_TITLE:
        v.append(f'news 절의 제목은 보이는 <h2>「{NEWS_TITLE}」 이다')
    v += news_gate.check(html, {'items': rows}, categories=DIGEST_CATEGORIES, title=NEWS_TITLE)
    by_guid = {str(r.get('guid')): r for r in usable}
    guids = [it['guid'] for it in nodes.items if it['section'] == 'news' and not it['hidden'] and it['guid']]
    chosen = [by_guid[g] for g in dict.fromkeys(guids) if g in by_guid]
    for cat in DIGEST_CATEGORIES:
        n = sum(1 for r in chosen if r['category'] == cat)
        if n > PER_CATEGORY:
            v.append(f'{LABELS[cat]} 갈래에 {n}건 — 갈래당 {PER_CATEGORY}건까지')
    for i, a in enumerate(chosen):
        for b in chosen[i + 1:]:
            if same_event(a.get('title'), b.get('title')):
                v.append(f'같은 사건을 두 번 실었다 — 「{a.get("title")}」 · 「{b.get("title")}」')
    return v


def number_sources(news):
    """본문 수치의 원천 — 실을 수 있는 요약(근거 행 포함)과 게재 후보의 일본어 원제목. 실을 수 없는 요약의
    수치는 뺀다 — 「매출은 98765억 엔이다. 아니, 다시 정리합니다」 의 앞 문장이 다른 절의 근거가 됐다(codex 2026-10-18 #4)."""
    return ([n['summary_ko'] for n in news if n.get('summary_ko') and summary_problem(n['summary_ko']) is None]
            + [title_source(n.get('title')) for n in news if n.get('digest')])


def check(html, diag, news_texts=(), digest=None):
    v = []
    secs = {n: b for n, b in _SEC.findall(html)}
    names = [n for n, _ in _SEC.findall(html)]
    present = [n for n in names if n in ORDER]
    for s in SECTIONS:
        if s not in names:
            v.append(f'data-section="{s}" 절이 없다')
    if present != [s for s in ORDER if s in present]:
        v.append(f'절 순서가 다르다: {" → ".join(present)}')
    for s in ORDER:
        if names.count(s) > 1:
            v.append(f'data-section="{s}" 절이 {names.count(s)}번 있다')
    v += check_news(html, secs, names, digest)
    if 'data-register="da"' not in html:
        v.append('<body data-register="da"> 가 없다 — -다 로 쓰는 데스크 문서다')

    for src, why in (diag.get('fetch_status') or {}).items():
        v.append(f'스냅샷 소스를 못 받았다: {src} ({why}) — 다시 수집한 뒤 발행한다')

    flows_prose = _prose(secs.get('flows', ''))
    for p in flows_prose:
        if '헤지' in p and '근사' not in p:
            v.append(f'헤지 후 금리를 말하는 문단에 「근사」가 없다 — 「{p[:40]}」')
    f = diag.get('flows') or {}
    # 방향 어휘는 모든 산문 절에서 본다 — flows·core 만 보면 시나리오 절의 반대 서술이 빠졌다(#13).
    # 「이번 주 뉴스」 는 뺀다 — 기사 요약은 기사 자신의 기준 기간을 말한다(월요일 기사의 지난 공표분 순매수,
    # codex 2026-10-18 #5). 그 요약은 뉴스 게이트가 원천과 대조한다.
    sents = [s.strip() for name in secs if name != 'news'
             for p in _prose(secs[name]) for s in _SENT.findall(p)]
    v += _sign_check(sents, _BOND, f.get('res_foreign_ltdebt_word'),
                     f.get('res_foreign_ltdebt_4w_word'), '거주자 해외채권 방향')
    eq4 = f.get('nonres_jp_equity_4w')
    v += _sign_check(sents, _JPEQ, f.get('nonres_jp_equity_word'),
                     None if eq4 in (None, 0) else ('순매수' if eq4 > 0 else '순매도'),
                     '외국인 일본 주식 방향')

    spread = (diag.get('core') or {}).get('usjp2y') or {}
    if (spread.get('asof_gap_days') or 0) > 3:
        v.append(f"미·일 2년 금리차의 두 다리 기준일이 {spread['asof_gap_days']}일 벌어졌다"
                 f"(미 {spread.get('asof_us')} · 일 {spread.get('asof_jp')}) — 같은 주의 값으로 다시 수집한다(#12)")

    pos = diag.get('positioning')
    yen = ' '.join(_prose(secs.get('yen', '')))
    if pos and re.search(r'CFTC|포지션|투기', yen):
        if not any(f in yen for f in _date_forms(pos['date'])):
            v.append(f'엔 선물 포지션을 말하면서 기준일({pos["date"]}, 화요일)을 밝히지 않았다')

    scen = ' '.join(_prose(secs.get('scenario', '')))
    for w in ('인상 지속', '인상 중단'):
        if w not in scen:
            v.append(f'시나리오 절이 「{w}」 갈래를 말하지 않았다 — 두 갈래를 다 적고 이번 주가 어느 쪽인지 쓴다')

    v += commentary.check(secs, COMMENTARY_SECTIONS)

    events = diag.get('next_events') or []
    if events:
        nxt = ' '.join(_prose(secs.get('next', '')))
        keys = {re.split(r'[\s(]', e['name_ko'])[0] for e in events}
        if not any(k in nxt for k in keys):
            v.append('다음 일정 절이 일정표의 어느 일정도 다루지 않았다')

    allowed = _numbers(diag)
    for t in news_texts:
        allowed |= _numbers({'t': t}) | _text_figures(t)
    allowed |= {str(y) for y in range(2020, 2036)}
    united = _united_numbers(_jo_eok(html))
    for n in sorted(_figures(html) - allowed):
        try:
            x = abs(float(n))
        except ValueError:
            continue
        if x <= 12 and x == int(x) and n not in united:
            continue
        v.append(f'어느 원본에도 없는 수치가 본문에 있다: {n} — 진단 파일이나 그 주 일본 뉴스에 있는 값만 쓴다')
    text = body_text(html).lower()
    for word in ('buy-side', 'buy side', '바이사이드'):
        if word in text:
            v.append('buy-side 표기가 남았다')
    return v
