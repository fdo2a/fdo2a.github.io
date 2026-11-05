"""흐름 후보 — 「40자 미만 문장 2개 이상 연속」 문단 중 손대면 안 되는 것을 뺀 나머지.

제외(하나라도 걸리면 후보 아님):
- 번역투 점검의 보호 구간(`translationese._protected`) 안, 문단 안 보호 요소(`_inline_protected`)
- 판단 구역 Z, 판단 문장 잠금 V·L·T 에 걸리는 문장이 하나라도 든 문단
- 따옴표(디코드 뒤 “”‘’「」『』"' 하나라도) — 발언 범위가 바뀌는 길을 닫는다(v4.5 #3)

후보는 pre.html 의 **바이트 구간**(문단 inner)과 그 sha1 로 묶인다. guard 는 이 구간에만 끼운다.
"""

import hashlib

from close import locks
from us.prose_swap import _eligible, _mask
from us.translationese import _QUOTE_CHARS, _inline_protected, _protected, _quote_view

SHORT = 40      # 문장 길이(공백 포함 글자) 문턱
RUN = 2         # 이어진 짧은 문장 수


def sha1(b):
    return hashlib.sha1(b).hexdigest()


def sha256(b):
    return hashlib.sha256(b).hexdigest()


def short_run(text, short=SHORT, run=RUN):
    """짧은 문장이 run 개 이상 이어지는가."""
    streak = 0
    for s in locks.sentences(text):
        streak = streak + 1 if len(s) < short else 0
        if streak >= run:
            return True
    return False


def has_quote(masked):
    return any(c in _QUOTE_CHARS for c in _quote_view(masked))


def why_excluded(html, m, spans, zones, ledger):
    """→ 제외 이유(문자열) 또는 None."""
    if any(a <= m.start() < b for a, b in spans):
        return 'protected'
    if any(a <= m.start() < b for a, b in zones) or locks.zone_p(m.group(1)):
        return 'zone'
    masked, tags = _mask(m.group(2))
    if _inline_protected(masked, tags):
        return 'inline_protected'
    if has_quote(masked):
        return 'quote'
    if locks.locked(masked, ledger):
        return 'locked'
    return None


def scan(html, ledger=locks.NO_LEDGER, short=SHORT, run=RUN):
    """→ candidates dict (JSON 으로 쓸 것). html 은 str, 구간은 UTF-8 바이트."""
    raw = html.encode('utf-8')
    spans, zones = _protected(html), locks.zone_spans(html)
    items, skipped = [], {}
    for pid, m in _eligible(html):
        masked, _ = _mask(m.group(2))
        if not short_run(masked, short, run):
            continue
        why = why_excluded(html, m, spans, zones, ledger)
        if why:
            skipped[why] = skipped.get(why, 0) + 1
            continue
        start = len(html[:m.start(2)].encode('utf-8'))
        end = start + len(m.group(2).encode('utf-8'))
        items.append({'id': 'C%02d' % (len(items) + 1), 'pid': pid, 'start': start, 'end': end,
                      'inner_sha1': sha1(raw[start:end]), 'masked': ' '.join(masked.split())})
    return {'source_sha1': sha1(raw), 'source_sha256': sha256(raw),
            'rule': {'short': short, 'run': run}, 'items': items, 'skipped': skipped}
