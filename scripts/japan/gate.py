"""일본 주간 발행 게이트. CLI: scripts/check_japan.py.

막는 것:
- 수치 창작 — 진단 파일과 그 주 일본 뉴스 요약에 없는 숫자
- 부호 뒤집기 — 「해외채권 순매수」가 실제로는 순매도인 문장(주간/4주 구분)
- 근사를 정밀로 — 헤지를 말하는 문단에 「근사」가 없음
- 기준일 누락 — CFTC 포지션을 말하면서 화요일 기준일을 밝히지 않음
- 한쪽 시나리오만 — 시나리오 절이 두 갈래를 다 말하지 않음
- 못 받은 소스 — 스냅샷 실패가 남아 있음
"""
import re

from japan.render import SECTIONS
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


def _jo_eok(text):
    """「1조 6,065억」 → 「16065억」. 조·억으로 쪼개 쓰면 원천값과 대조되지 않는다."""
    return _JO_EOK.sub(lambda m: f'{int(m.group(1)) * 10000 + int(m.group(2).replace(",", ""))}억', text)


def _figures(html):
    text = _jo_eok(body_text(html))
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


def check(html, diag, news_texts=()):
    v = []
    secs = {n: b for n, b in _SEC.findall(html)}
    names = [n for n, _ in _SEC.findall(html)]
    present = [n for n in names if n in SECTIONS]
    for s in SECTIONS:
        if s not in names:
            v.append(f'data-section="{s}" 절이 없다')
    if present != [s for s in SECTIONS if s in present]:
        v.append(f'절 순서가 다르다: {" → ".join(present)}')
    if 'data-register="da"' not in html:
        v.append('<body data-register="da"> 가 없다 — -다 로 쓰는 데스크 문서다')

    for src, why in (diag.get('fetch_status') or {}).items():
        v.append(f'스냅샷 소스를 못 받았다: {src} ({why}) — 다시 수집한 뒤 발행한다')

    flows_prose = _prose(secs.get('flows', ''))
    for p in flows_prose:
        if '헤지' in p and '근사' not in p:
            v.append(f'헤지 후 금리를 말하는 문단에 「근사」가 없다 — 「{p[:40]}」')
    f = diag.get('flows') or {}
    sents = [s.strip() for p in flows_prose + _prose(secs.get('core', '')) for s in _SENT.findall(p)]
    v += _sign_check(sents, _BOND, f.get('res_foreign_ltdebt_word'),
                     f.get('res_foreign_ltdebt_4w_word'), '거주자 해외채권 방향')
    eq4 = f.get('nonres_jp_equity_4w')
    v += _sign_check(sents, _JPEQ, f.get('nonres_jp_equity_word'),
                     None if eq4 in (None, 0) else ('순매수' if eq4 > 0 else '순매도'),
                     '외국인 일본 주식 방향')

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
        allowed |= _numbers({'t': t})
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
