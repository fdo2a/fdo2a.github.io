"""US 주간 인사이트 게이트 — check_period `--insight` 가 부른다.

작성 규칙에만 있고 게이트가 없어 그대로 발행된 것들을 막는다(W38 실측):
- 표에만 있고 본문에서 설명하지 않은 큰 움직임(원·달러 +3.35%)
- 「오래 안 걸린 트리거 → 문턱이 틀렸다」는 단정(작성자 지시문이 금지하는데 통과)
- 요일마다 문단을 여는 목차형 서사(2026-09-13 지시 뒤에도 월→화·수→목·금)
"""
import re

from scripts.common import commentary
from us.weekly_insight import ALIASES, NEXT_DAYS, event_aliases, merge_next

COMMENTARY_SECTIONS = ('diag', 'positioning', 'next')
SECTIONS_WITH_PROSE = ('question', 'diag', 'positioning', 'review', 'next')

_SEC = re.compile(r'<section\b[^>]*\bdata-section="([a-z]+)"[^>]*>(.*?)</section>', re.S | re.I)
_P = re.compile(r'<p\b[^>]*>(.*?)</p>', re.S | re.I)
_TAG = re.compile(r'<[^>]+>')
_TABLE = re.compile(r'<table\b.*?</table>', re.S | re.I)

# 잠든 트리거를 근거로 문턱이 틀렸다고 단정하는 꼴. 좁게 잡는다 — 「문턱을 다시 확인한다」는 괜찮다.
_THRESHOLD_VERDICT = re.compile(
    r'(문턱|임계|트리거)[^.。]{0,40}(빡빡|느슨|잘못|틀렸|다시\s*봐야|다시\s*손볼|손봐야|낮춰야|높여야)')
# 자금 흐름 자료는 받지 않는다. 가격이 갈린 것을 돈이 옮겨 간 것으로 쓰면 증거를 넘는다(W41
# 「돈은 에너지·필수소비재·가치주로 옮겨 갔다」「빠진 돈이 머문 자리」). 「자금 조달」은 걸리지 않게
# 주어 뒤 동사까지 본다. 부정·인용(「이동했다는 증거는 없다」)과 기업 자금 흐름도 걸리므로 막지 않고
# 경고만 한다(codex 2026-10-17 #5).
_FUND_FLOW = re.compile(
    r'(돈|자금|매수세)(?:이|은|가|도)?\s[^.。]{0,25}?'
    r'(옮겨|이동했|이동한|몰렸|몰려|몰린|머문|머물|흘러|빠져나|빠진|빠졌|빠져)')
_ISO = re.compile(r'(\d{4}-\d{2}-\d{2})')
_MD = re.compile(r'(\d{1,2})월\s*(\d{1,2})일')
_WEEKDAY = re.compile(r'(월|화|수|목|금)요일')
QUESTION_MAX_DAYS = 3
# 서술 본문 분량 경고(막지 않는다). W39 3,043 → W40 5,980 → W41 7,236자(공백 제외)로 불었다.
# 일간 §11 의 4,000~5,000 은 주간에 맞지 않아 따로 둔다(2026-10-17 외부 피드백 — 20~30% 압축 권고).
PROSE_WARN_CHARS = 6000
# 속성 이름이 정확히 같을 때만 — `\b` 는 「data-research-summary-note」에도 걸렸다(codex 5차). 진짜 요약은
# period_gate 가 이 검사 전에 「정확히 하나」로 바이트 대조해 떼어 내므로, 여기 남은 것은 가짜다.
_SUMMARY = re.compile(r'<section\b[^>]*\sdata-research-summary=["\'][^>]*>.*?</section\s*>', re.S | re.I)
_CAPTION = re.compile(r'<p\b[^>]*class="[^"]*\bcaption\b[^"]*"[^>]*>.*?</p>', re.S)
_DAY_OPENER = re.compile(r'^\s*(?:\d{4}-\d{2}-\d{2}|\d{1,2}월\s*\d{1,2}일)?\s*(?:[,(]?\s*)?'
                         r'(월|화|수|목|금)요일')


def _norm(fragment):
    return re.sub(r'\s+', ' ', _TAG.sub(' ', fragment)).strip()


def _all_prose(html, secs):
    """머리 카드(제목·리드)와 산문 절 전부. 제목 `<h1>` 도 넣는다(codex #5)."""
    head = re.search(r'<section\b[^>]*headline-card[^>]*>.*?</section>', html, re.S)
    out = []
    if head:
        out += [_norm(h) for h in re.findall(r'<h1\b[^>]*>(.*?)</h1>', head.group(0), re.S)]
        out += _prose(head.group(0))
    return out + [p for name in SECTIONS_WITH_PROSE for p in _prose(secs.get(name, ''))]


def _prose(fragment):
    frag = _TABLE.sub(' ', fragment)
    return [re.sub(r'\s+', ' ', _TAG.sub(' ', p)).strip() for p in _P.findall(frag)]


def _mentioned(texts, name, label):
    blob = ' '.join(texts)
    for a in ALIASES.get(name, (label,)):
        if a in blob:
            return True
    return False


def _days_named(texts, start, end):
    """그 주 거래일 중 산문이 부른 날들 — ISO·「M월 D일」·「X요일」."""
    from datetime import date, timedelta
    lo, hi = date.fromisoformat(start), date.fromisoformat(end)
    blob = ' '.join(texts)
    got = set()
    for iso in _ISO.findall(blob):
        try:
            d = date.fromisoformat(iso)
        except ValueError:
            continue
        if lo <= d <= hi:
            got.add(d)
    for m, d in _MD.findall(blob):
        try:
            x = date(lo.year, int(m), int(d))
        except ValueError:
            continue
        if lo <= x <= hi:
            got.add(x)
    for w in _WEEKDAY.findall(blob):
        x = lo + timedelta(days=('월화수목금'.index(w) - lo.weekday()) % 7)
        if x <= hi:
            got.add(x)
    return got


# 본문이 다음 주 날짜 **바로 뒤에** 붙여 부르면 표에 있어야 하는 경제지표 → 표 행 이름에 들어 있어야 할 말.
# 2026-10-13~17 일정 수집이 CPI 를 조용히 버렸는데 W41 은 「10월 14일 9월 CPI」를 핵심 변수로 꼽았다.
# FOMC·만기·입찰은 계산·공식 원천에서 오고 「10월 27~28일 FOMC」처럼 표기가 갈려 대조하지 않는다.
_RELEASE_TERMS = {
    'CPI': '소비자물가', '소비자물가': '소비자물가', 'PCE': '개인소비지출', '개인소비지출': '개인소비지출',
    '소매판매': '소매판매', 'GDP': 'GDP', 'PPI': '생산자물가', '생산자물가': '생산자물가',
    '실업수당': '실업수당', 'JOLTS': 'JOLTS', '산업생산': '산업생산', '내구재': '내구재',
    '신규주택': '신규주택', '기존주택': '기존주택', '미시간': '미시간', '고용상황': '고용상황',
}
_SENT = re.compile(r'(?<=[.!?。])\s+')
_DATE = re.compile(r'(\d{4})-(\d{2})-(\d{2})|(\d{1,2})월\s*(\d{1,2})일')
# 날짜와 일정 이름 사이에 끼는 시각 표기 — 「10월 23일 10:00 ET(10월 23일 23:00 KST) 미시간대」.
_CLOCK = re.compile(r'\(\s*\d{1,2}월\s*\d{1,2}일\s*\d{1,2}:\d{2}\s*KST\s*\)|\(?\d{1,2}:\d{2}\)?\s*(?:\(?ET\)?|KST)?')
ADJACENT_WORDS = 3     # 날짜 뒤 이 낱말 수 안에 나온 이름만 그 날의 일정으로 본다
_GENERIC = re.compile(r'^(?:\d{1,2}분기|분기|실적|발표|일정|\d{1,2}월)$')


def _sentences(texts):
    return [x for t in texts for x in _SENT.split(t) if x.strip()]


def _dated_claims(sentence, end, days=NEXT_DAYS):
    """-> [(날짜, 그 날짜 바로 뒤 낱말들)] — 다음 `days`일 안의 날짜만. 날짜마다 따로 묶는다(codex #2:
    한 문장의 날짜들을 합치면 「10월 14일 TSMC 실적과 10월 15일 CPI」가 서로 바뀐 날짜로 통과했다)."""
    from datetime import date, timedelta
    lo = date.fromisoformat(end)
    hi = lo + timedelta(days=days)
    clean = _CLOCK.sub(' ', sentence)
    marks = list(_DATE.finditer(clean))
    out = []
    for k, m in enumerate(marks):
        if m.group(1):
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        else:
            mo, d = int(m.group(4)), int(m.group(5))
            y = lo.year + (1 if mo < lo.month else 0)
        try:
            x = date(y, mo, d)
        except ValueError:
            continue
        if not (lo < x <= hi):
            continue
        tail = clean[m.end(): marks[k + 1].start() if k + 1 < len(marks) else len(clean)]
        if tail[:1] and not tail[:1].isspace():
            continue      # 「10월 15일까지」「10월 15일의」 — 그날의 일정 이름이 아니다
        out.append((x.isoformat(), tail.split()[:ADJACENT_WORDS]))
    return out


def _uncovered(day, words, table):
    """날짜 바로 뒤에 부른 일정 중 그날 표에 없는 것."""
    rows = [r for r in table if r['date'] == day]
    miss = []
    # 날짜 뒤 처음 나온 지표 하나가 그날의 일정이다 — 「10월 15일 생산자물가(PPI)는 CPI가 낸 답을」의 CPI 는 아니다.
    for w in words:
        hit = [(t, label) for t, label in _RELEASE_TERMS.items() if t in w]
        if hit:
            if not any(label in r['name_ko'] or t in r['name_ko'] for t, label in hit for r in rows):
                miss.append(hit[0][0])
            break
    return miss


def _earnings_unlisted(day, words, table):
    """「10월 15일 TSMC 3분기 실적」인데 그날 발행본 예고 행이 없다 — **경고만**. 실적의 주인을 낱말로
    가려내는 일은 「발표되는 실적」「미국 실적」「A·B 실적」에서 계속 틀려(codex 구현 검토 2회) 막지 않는다."""
    if not any(w.startswith('실적') for w in words[1:]):
        return None
    if any(r['date'] == day and r.get('source') == 'post' for r in table):
        return None
    return ' '.join(words)


def _identity(row):
    """발행본에 있어야 할 이름 낱말 — 일반어(분기·실적)를 뺀 낱말 전부, 괄호 안과 「A·B」는 이름마다."""
    words = re.split(r'[\s()·,]+', row['name_ko'])
    return [w for w in words if w and not _GENERIC.match(w)] or [row['name_ko']]


def _in_a_post(row, post_texts, end):
    """발행본 문장에서 그 날짜 **바로 뒤**(세 낱말 안)에 이름 낱말이 전부 있는가. 한 문장 어딘가에
    있는 것으로는 부족하다 — 「10월 22일 웨스턴디지털 실적과 27~28일 FOMC」가 10월 22일 FOMC 를,
    괄호만 보면 「파산 신청(웨스턴디지털)」을 통과시켰다(codex 구현 재검토 #1·#2)."""
    need = _identity(row)
    for text in post_texts.values():
        plain = re.sub(r'\s+', ' ', _TAG.sub(' ', text))
        for sent in _SENT.split(plain):
            for day, words in _dated_claims(sent, end):
                near = ' '.join(words)
                if day == row['date'] and all(n in near for n in need):
                    return True
    return False


def check(html, diag, post_texts=None):
    """`post_texts`({날짜: 발행본 HTML})가 없으면 발행본 예고 행의 출처 대조를 건너뛴다 — 발행 뒤
    재검사(--research-frozen)는 발행 때 대조를 통과한 표를 진단 파일에서 그대로 다시 그린다."""
    v = []
    # 생성된 연구 요약은 안쪽 </section> 이 바깥 절을 일찍 닫아 그 뒤 복기 문단이 검사에서 빠졌다(codex #5).
    secs = {n: body for n, body in _SEC.findall(_SUMMARY.sub(' ', html))}
    # 생성된 연구 요약 말고는 절 안에 절을 두지 않는다 — 안쪽 </section> 에서 절이 끊겨 그 뒤에 끼운
    # 표·문단이 모든 검사를 비껴갔다(codex 구현 3차 검토).
    for n, body in secs.items():
        if re.search(r'<section\b', body, re.I):
            v.append(f'「{n}」 절 안에 다른 <section> 이 있다 — 절은 겹치지 않게 쓴다(연구 요약 블록만 예외)')
    for src, why in (diag.get('fetch_status') or {}).items():
        v.append(f'주간 스냅샷 소스를 못 받았다: {src} ({why}) — 다시 수집한 뒤 발행한다. '
                 '못 받은 것을 조용한 무변화로 쓰지 않는다')

    diag_prose = _prose(secs.get('diag', ''))
    for a in diag.get('anomalies') or []:
        if a.get('flagged') and not _mentioned(diag_prose, a['name'], a.get('label', '')):
            v.append(f'「{a.get("label", a["name"])}」가 평소의 {abs(a["z"]):.1f}배 움직였는데 진단 본문이 '
                     '다루지 않았다 — 왜 움직였는지, 설명이 없으면 없다고 쓴다')

    for p in _prose(secs.get('review', '')):
        m = _THRESHOLD_VERDICT.search(p)
        if m:
            v.append(f'복기가 잠든 조건을 근거로 문턱이 틀렸다고 단정했다(「{m.group(0)[:40]}」) — '
                     '오래 안 걸렸다는 사실만으로 문턱을 판정하지 않는다. 조건이 유효한지를 검토한다')

    openers = [p for s in ('question', 'diag', 'positioning') for p in _prose(secs.get(s, ''))
               if _DAY_OPENER.match(p)]
    if len(openers) >= 2:
        v.append(f'요일로 여는 문단이 {len(openers)}개다 — 요일별 목차가 된다. 문단은 질문의 국면으로 '
                 '나누고 날짜는 문장 안에서 지나가게 쓴다')

    start, end = diag.get('start_date'), diag.get('end_date')
    if start and end:
        named = _days_named(_prose(secs.get('question', '')), start, end)
        if len(named) > QUESTION_MAX_DAYS:
            v.append(f'질문 절이 그 주 날짜를 {len(named)}일(네 날 이상) 짚었다 — 일간을 날짜순으로 다시 쓴 것이다. '
                     '한 주 동안 달라진 것·해석·대안·가를 관측으로 쓰고, 날짜는 판단을 바꾼 날만 '
                     f'{QUESTION_MAX_DAYS}일까지 남긴다(나머지는 부록 일별 기록이 담는다)')

    v += commentary.check(secs, COMMENTARY_SECTIONS)

    end = diag.get('end_date')
    table, errs = merge_next(diag.get('next_week') or [], diag.get('next_events') or [], end) \
        if end else (diag.get('next_week') or [], [])
    v += [f'다음 주 표 추가 일정이 계약에 어긋난다 — {e}' for e in errs]
    if post_texts is not None:
        for r in table:
            if r.get('source') == 'post' and not _in_a_post(r, post_texts, end):
                v.append(f'다음 주 표의 「{r["name_ko"]}」({r["date"]})가 그 기간 발행본 어느 문장에도 그 날짜와 함께 '
                         '없다 — 발행본이 예고한 일정만 더한다')
    if end:
        missing = {}
        for sent in _sentences(_all_prose(html, secs)):
            for day, words in _dated_claims(sent, end):
                for term in _uncovered(day, words, table):
                    missing.setdefault(term, set()).add(day)
        for term, dates in missing.items():
            v.append(f'본문이 {", ".join(sorted(dates))} 일정으로 「{term}」을 꼽았는데 다음 주 표에 없다 — '
                     '일정 수집이 그 지표를 빠뜨렸다. 그 주 발행본이 날짜와 함께 예고했으면 meta.json next_events 로 '
                     '더하고, 아니면 날짜를 붙여 다음 주 변수로 쓰지 않는다')
    # 표는 진단으로 다시 그린 것과 같아야 한다 — 조립 뒤 행을 지우거나 바꾸면 위 대조가 허공을 본다(codex #4).
    # `next_events` 키는 2026-10-17 조립기가 쓴 진단에만 있다 — 그 전 발행본(4열 표)은 다시 검사하지 않는다.
    if end and 'next_events' in diag:
        from us.weekly_insight import _t_next
        want = [_norm(t) for t in _TABLE.findall(_t_next(dict(diag, next_table=table)))]
        have = [_norm(t) for t in _TABLE.findall(secs.get('next', ''))]
        if have != want:      # 표를 더 끼워 넣어도 안 된다(codex 재검토 #5)
            v.append('다음 주 절의 표가 진단 파일로 다시 그린 표와 다르다 — 표는 조립기가 만든 그대로 둔다')

    events = table
    if events:
        nxt = ' '.join(_prose(secs.get('next', '')))
        keys = set().union(*(event_aliases(e) for e in events))
        if not any(k in nxt for k in keys):
            v.append('다음 주 절이 일정표의 어느 일정도 다루지 않았다 — 가를 일정 하나 이상을 '
                     '조건과 함께 쓴다')
    return v


def prose_chars(html):
    """서술 본문 글자 수(공백 제외) — 표·캡션·생성된 복기 블록·부록 제외, 머리 카드 포함."""
    import html as _h
    body = _SUMMARY.sub(' ', html)
    body = _CAPTION.sub(' ', body)
    body = _TABLE.sub(' ', body)
    body = re.sub(r'<section\b[^>]*\bdata-section="appendix".*?</section>', ' ', body, flags=re.S)
    text = ' '.join(_TAG.sub(' ', p) for p in _P.findall(body))
    return len(re.sub(r'\s', '', _h.unescape(text)))


def warnings(html, diag=None):
    """막지 않는 경고. check_period 가 「경고:」 줄로 출력한다."""
    out = []
    amb = (diag or {}).get('calendar_ambiguous') or []
    if amb:
        out.append(f'일정 수집이 이름이 모호한 지표를 뺐다({", ".join(amb)}) — 다음 주 표에 그 지표가 없다. '
                   '그 지표를 본문에서 다음 주 변수로 꼽으면 게이트가 막는다')
    secs = {n: body for n, body in _SEC.findall(_SUMMARY.sub(' ', html))}
    for p in _all_prose(html, secs):
        m = _FUND_FLOW.search(p)
        if m:
            out.append(f'자금 이동을 단정한 것 같다(「{m.group(0)[:30]}」) — 자금 흐름 자료가 없다. 가격이 갈린 것은 '
                       '「상대 성과가 갈렸다」로 쓴다')
            break
    end = (diag or {}).get('end_date')
    if end:
        table, _ = merge_next(diag.get('next_week') or [], diag.get('next_events') or [], end)
        hits = []
        for sent in _sentences(_all_prose(html, secs)):
            for day, words in _dated_claims(sent, end):
                h = _earnings_unlisted(day, words, table)
                if h and h not in hits:
                    hits.append(h)
        if hits:
            out.append(f'본문이 다음 주 실적을 날짜와 함께 꼽았는데 표에 없다(「{hits[0]}」 등 {len(hits)}곳) — 그 주 발행본이 '
                       '예고한 실적이면 meta.json next_events 로 표에 더한다')
    n = prose_chars(html)
    if n > PROSE_WARN_CHARS:
        out.append(f'서술 본문이 {n:,}자다(공백 제외, 표·캡션·생성 복기 제외) — {PROSE_WARN_CHARS:,}자 안을 권한다. '
                   '요일별 재서술, 같은 가설의 재설명, 표에 있는 수익률의 산문 반복부터 줄인다')
    return out
