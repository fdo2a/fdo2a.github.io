"""일본 일간 발행 게이트. CLI: scripts/check_japan_daily.py (2026-10-27).

전역 숫자 집합만으로는 만기·단위·주체가 바뀐 문장(「JGB 2년 1.5%, 10년 0.75%」, 「1.5엔」)이 통과한다
(codex 설계 검토 #7 재현). 그래서 핵심 값(닛케이·JGB·콜·엔)은 산문에서 `<span data-ref="필드 경로">` 로
스냅샷 필드에 묶고, 값·단위·기준일을 그 필드와 대조한다. 묶지 않은 채 핵심 값을 쓰면 막는다.
나머지 숫자는 스냅샷 집합 검사(주간 게이트와 같은 정규화). 뉴스 절은 뉴스 게이트가 따로 본다.

막는 것: complete 아님·세션/파일명 불일치·코어 값 없음, da 표식 없음, 미완 표식, 절 순서(코드가 정한
`order()`), data-ref 불일치, 기준일이 다른 값의 날짜 누락, 「오늘 JGB」, 창작 수치, 예상·컨센서스 비교,
주간 신호 어휘, 「지수 기여」, BOJ 크레디트 누락, 움직인 종목 문단, buy-side.
"""
import math
import re

from common import movers as CM
from japan import daily_render as R
from japan.gate import _jo_eok, _text_figures
from us.macro_gate import BANNED_LABELS
from us.period_gate import _numbers, _united_numbers
from us.post_check import body_text

_SEC = re.compile(r'<section\b[^>]*\bdata-section="([a-z]+)"[^>]*>(.*?)</section>', re.S)
_P = re.compile(r'<p\b(?![^>]*class="caption")([^>]*)>(.*?)</p>', re.S)
_TABLE = re.compile(r'<table\b.*?</table>', re.S)
_TAG = re.compile(r'<[^>]+>')
_REF = re.compile(r'<span\b[^>]*\bdata-ref="([^"]+)"[^>]*>(.*?)</span>', re.S)
_NUM = re.compile(r'-?\d[\d,]*(?:\.\d+)?')
_TIME = re.compile(r'\b\d{1,2}:\d{2}\b')
_UNITS = ('%p', '%', 'bp', '엔', '원', '포인트')
_CONSENSUS = re.compile(r'컨센서스|예상치|시장\s*예상|전망치|예상(?:을|보다|과|에)\s*(?:크게\s*)?(?:상회|하회|웃|밑)')
_SIGNALS = re.compile(r'[AB]\s*경로|신호\s*집계|임계값|인상\s*지속\s*쪽|인상\s*중단\s*쪽')
_TODAY_RATE = re.compile(r'오늘[^.。]{0,15}(JGB|국채|콜)')
_UNVERIFIED = ('[확인필요]', '확인 필요]', 'TODO', 'TBD', '{{')
_EXTRA_OK = {'225'}


def _finite(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _plain(fragment):
    return re.sub(r'\s+', ' ', _TAG.sub(' ', fragment)).strip()


def resolve(snap, path):
    cur = snap
    for part in path.split('.'):
        if isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        elif isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def _period_of(snap, path):
    head = path.split('.')
    if head[0] == 'jgb' and len(head) > 1:
        return (resolve(snap, f'jgb.{head[1]}') or {}).get('period')
    if head[0] == 'call_rate':
        return (snap.get('call_rate') or {}).get('period')
    if head[0] == 'macro' and len(head) > 1:
        return (resolve(snap, f'macro.{head[1]}') or {}).get('period')
    return snap.get('session')


def _allowed_units(path):
    last, head = path.split('.')[-1], path.split('.')[0]
    if last == 'chg_bp':
        return {'bp'}
    if last in ('chg_pct', 'yoy'):
        return {'%'}
    if head in ('jgb', 'call_rate'):
        return {'%'}
    if head == 'fx':
        return {'원'} if 'krw' in path else {'엔'}
    if head == 'indices':
        return {'포인트'}
    return set(_UNITS)


def _date_forms(period):
    out = {period, R.day_ko(period)}
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', period or ''):
        y, m, d = period.split('-')
        out.add(f'{int(m)}/{int(d)}')
    return out


def _num(text):
    m = _NUM.search((text or '').replace('−', '-'))
    return float(m.group(0).replace(',', '')) if m else None


def _matches(shown, value):
    nd = len(shown.split('.')[1]) if '.' in shown else 0
    return round(abs(value), nd) == abs(float(shown.replace(',', '')))


def _check_refs(paras, snap, session):
    v = []
    for p in paras:
        for path, inner in _REF.findall(p):
            value = resolve(snap, path)
            text = _plain(inner)
            if not _finite(value):
                v.append(f'data-ref="{path}" 는 스냅샷에 값이 없다 — 「{text}」')
                continue
            m = _NUM.search(text.replace('−', '-'))
            if not m or not _matches(m.group(0).lstrip('-'), value):
                v.append(f'data-ref="{path}" 값이 다르다 — 본문 「{text}」, 스냅샷 {value}')
            unit = next((u for u in _UNITS if u in text), None)
            if unit and unit not in _allowed_units(path):
                v.append(f'data-ref="{path}" 단위가 틀렸다 — 「{text}」(허용 {"·".join(sorted(_allowed_units(path)))})')
            period = _period_of(snap, path)
            if period and period != session and not any(f in _plain(p) for f in _date_forms(period)):
                v.append(f'data-ref="{path}" 는 {R.day_ko(period)} 기준 값이다 — 그 문단에 날짜를 밝힌다')
    return v


def _core_values(snap):
    out = []
    nk = (snap.get('indices') or {}).get('nikkei') or {}
    out.append(('indices.nikkei.value', nk.get('value')))
    for t, r in (snap.get('jgb') or {}).items():
        if isinstance(r, dict):
            out.append((f'jgb.{t}.value', r.get('value')))
    out.append(('call_rate.value', (snap.get('call_rate') or {}).get('value')))
    for k, r in (snap.get('fx') or {}).items():
        out.append((f'fx.{k}.value', (r or {}).get('value')))
    return [(p, x) for p, x in out if _finite(x)]


def _forms(x):
    out = {f'{x:,.2f}', f'{x:.2f}', f'{x:.3f}'}
    if abs(x) >= 1000:
        out |= {f'{x:,.0f}', f'{x:,.1f}'}
    return {f for f in out if f not in ('0.00', '0.000')}


def _check_unbound(paras, snap):
    v = []
    core = _core_values(snap)
    for p in paras:
        rest = _plain(_REF.sub(' ', p))
        for path, x in core:
            for f in _forms(x):
                if re.search(r'(?<![\d.,])' + re.escape(f) + r'(?![\d])', rest):
                    v.append(f'핵심 값 {f}({path})을 data-ref 없이 썼다 — <span data-ref="{path}"> 로 묶는다')
                    break
    return v


def _figures_of(fragment):
    t = _TIME.sub(' ', _plain(_jo_eok(fragment)))
    return _text_figures(t)


def check(html, snap, session, filename=None, news=None):
    v = []
    if not snap.get('complete'):
        v.append('스냅샷 complete 가 거짓이다 — 닛케이 공식 종가를 확인하지 못한 세션은 발행하지 않는다')
    if snap.get('session') != session:
        v.append(f'스냅샷 세션 {snap.get("session")} ≠ 발행 세션 {session}')
    if filename and not filename.endswith(f'{session}.html'):
        v.append(f'파일 이름 {filename} 이 세션 {session} 과 다르다')
    if not _finite(((snap.get('indices') or {}).get('nikkei') or {}).get('value')):
        v.append('코어 값(닛케이 종가)이 없다')
    if 'data-register="da"' not in html:
        v.append('<body data-register="da"> 가 없다 — -다 로 쓰는 데스크 문서다')
    for mark in _UNVERIFIED:
        if mark in html:
            v.append(f'미완 표식 「{mark}」 이 남았다')
    if R.BOJ_CREDIT not in html:
        v.append('일본은행 API 크레디트 문구가 없다(이용 고지 필수)')

    found = _SEC.findall(html)
    names = [n for n, _ in found]
    want = list(R.order((snap.get('calendar') or {}).get('event_day')))
    if [n for n in names if n in R.SECTIONS] != want:
        v.append(f'절 순서가 다르다: {" → ".join(names)} (기대 {" → ".join(want)})')
    for s in R.SECTIONS:
        if names.count(s) != 1:
            v.append(f'data-section="{s}" 절이 {names.count(s)}번 있다')

    prose_secs = [(n, b) for n, b in found if n != 'news']
    paras, mover_paras = [], []
    for _, b in prose_secs:
        for attrs, inner in _P.findall(_TABLE.sub(' ', b)):
            (mover_paras if 'data-mover' in attrs else paras).append(inner)
    head = re.search(r'<section class="card headline-card">(.*?)</section>', html, re.S)
    if head:
        paras += [inner for _, inner in _P.findall(head.group(1))]
    allp = paras + mover_paras
    v += _check_refs(allp, snap, session)
    v += _check_unbound(allp, snap)
    for p in allp:
        t = _plain(p)
        if _CONSENSUS.search(t):
            v.append(f'예상·컨센서스와 비교했다 — 원천이 없다: 「{t[:50]}」')
        if _SIGNALS.search(t):
            v.append(f'주간 보고서의 신호 어휘다 — 일간은 서술만 한다: 「{t[:50]}」')
        if _TODAY_RATE.search(t):
            v.append(f'JGB·콜은 오늘 값이 아니다 — 「{t[:50]}」')
        if '지수 기여' in t or '기여도' in t:
            v.append(f'「지수 기여」 는 쓰지 않는다(표본 시총 계산은 지수 기여가 아니다): 「{t[:50]}」')

    allowed = _numbers(snap) | _EXTRA_OK | {str(y) for y in range(2020, 2036)}
    news_ok = set()
    for it in (news or {}).get('items') or []:
        news_ok |= _text_figures(it.get('summary_ko') or '')
    united = _united_numbers(_jo_eok(html))
    for group, extra in ((paras, set()), (mover_paras, news_ok)):
        for p in group:
            for n in sorted(_figures_of(p) - allowed - extra):
                try:
                    x = abs(float(n))
                except ValueError:
                    continue
                if x <= 12 and x == int(x) and n not in united:
                    continue
                v.append(f'어느 원본에도 없는 수치가 본문에 있다: {n} — 스냅샷 값만 쓴다')
    v += CM.check(html, snap.get('movers'), session)
    low = body_text(html).lower()
    for word in BANNED_LABELS:
        if word in low:
            v.append(f'buy-side 표기("{word}")가 남았다')
    return list(dict.fromkeys(v))
