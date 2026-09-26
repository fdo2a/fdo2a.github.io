"""US 주간 인사이트 게이트 — check_period `--insight` 가 부른다.

작성 규칙에만 있고 게이트가 없어 그대로 발행된 것들을 막는다(W38 실측):
- 표에만 있고 본문에서 설명하지 않은 큰 움직임(원·달러 +3.35%)
- 「오래 안 걸린 트리거 → 문턱이 틀렸다」는 단정(작성자 지시문이 금지하는데 통과)
- 요일마다 문단을 여는 목차형 서사(2026-09-13 지시 뒤에도 월→화·수→목·금)
"""
import re

from scripts.common import commentary
from us.weekly_insight import ALIASES

COMMENTARY_SECTIONS = ('diag', 'positioning', 'next')

_SEC = re.compile(r'<section\b[^>]*\bdata-section="([a-z]+)"[^>]*>(.*?)</section>', re.S)
_P = re.compile(r'<p\b[^>]*>(.*?)</p>', re.S)
_TAG = re.compile(r'<[^>]+>')
_TABLE = re.compile(r'<table\b.*?</table>', re.S)

# 잠든 트리거를 근거로 문턱이 틀렸다고 단정하는 꼴. 좁게 잡는다 — 「문턱을 다시 확인한다」는 괜찮다.
_THRESHOLD_VERDICT = re.compile(
    r'(문턱|임계|트리거)[^.。]{0,40}(빡빡|느슨|잘못|틀렸|다시\s*봐야|다시\s*손볼|손봐야|낮춰야|높여야)')
_DAY_OPENER = re.compile(r'^\s*(?:\d{4}-\d{2}-\d{2}|\d{1,2}월\s*\d{1,2}일)?\s*(?:[,(]?\s*)?'
                         r'(월|화|수|목|금)요일')


def _prose(fragment):
    frag = _TABLE.sub(' ', fragment)
    return [re.sub(r'\s+', ' ', _TAG.sub(' ', p)).strip() for p in _P.findall(frag)]


def _mentioned(texts, name, label):
    blob = ' '.join(texts)
    for a in ALIASES.get(name, (label,)):
        if a in blob:
            return True
    return False


def check(html, diag):
    v = []
    secs = {n: body for n, body in _SEC.findall(html)}
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

    v += commentary.check(secs, COMMENTARY_SECTIONS)

    events = diag.get('next_week') or []
    if events:
        nxt = ' '.join(_prose(secs.get('next', '')))
        keys = {e['name_ko'].split()[0] for e in events if e.get('name_ko')}
        if not any(k in nxt for k in keys):
            v.append('다음 주 절이 일정표의 어느 일정도 다루지 않았다 — 가를 일정 하나 이상을 '
                     '조건과 함께 쓴다')
    return v
