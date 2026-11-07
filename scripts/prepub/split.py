"""codex 답 → (정확성 몫, 문체 후보).

- 정확성 몫: 사실 검토 부분 전체 + 문체 지적 가운데 확신도에 닿는 것(「판단 세기 흐림」「원문에 없는 관계」).
  오케스트레이터가 근거와 대조해 판정한다(DESK_REPORT 「Causal claims are as strong as their evidence」 —
  근거 없는 원인 단정은 정확성 오류). 의미 검사자는 세기 변화를 「changed」로 막으므로 문체 경로에 넣지 않는다.
- 문체 후보: 나머지 문체 지적(번역투·끊긴 흐름·반복·기타)이 가리킨 문단을 STEP 2.6 의 후보 형식
  (`close.flow.scan` 과 같은 구간·해시)으로. 그 뒤는 `.claude/STYLE_CLOSE.md` A 의 5-12 를 탄다
  (작성자 편집 → guard → 의미 검사 → 반영).
  · 판단 구역(Z)·판단 문장이 든 문단도 후보로 받는다(2026-11-07 사용자 결정 「번역투나 문체수정에 더 무게」).
    판단 문장은 guard 가 **글자 그대로** 지킨다(`locks.locked` 비교) — 같은 문단의 다른 문장만 바뀐다.
  · 「번역투」 지적은 판단 문장의 낱말까지 고칠 수 있다(`relax: "translationese"`) — 대신 판단 뼈대
    (`locks.judgment_skeleton`)가 같아야 하고, 그 묶음은 의미 검사를 두 번 받는다.
  · 따옴표·보호 구간·문단 안 보호 요소는 여전히 뺀다(발언 범위·표식이 바뀌는 길).
"""
import re

import review_gate as gate
from close import flow, locks
from us.prose_swap import _eligible, _mask
from us.translationese import _inline_protected, _protected

ACCURACY_KINDS = frozenset({'판단 세기 흐림', '원문에 없는 관계'})
OPEN = frozenset({'zone', 'locked'})   # 후보로 받는 제외 이유 — guard 가 판단 문장을 지킨다
_TRIM = re.compile(r'^[\s「『"\'“‘…·.]+|[\s」』"\'”’…·.]+$')
PROBE = 18   # 인용 앞머리 글자 수 — codex 인용은 40자 안으로 잘린다


def _norm(text):
    return ' '.join((text or '').split())


def _probe(quote):
    q = _TRIM.sub('', _norm(quote))
    return q[:PROBE] if len(q) >= 8 else None


def _why(html, m, spans, zones, ledger):
    """제외 이유 — 보호 구간·문단 안 보호 요소·따옴표를 **판단 구역보다 먼저** 본다.

    `flow.why_excluded` 는 판단 구역(zone)을 먼저 돌려줘서, 판단 구역을 열면 따옴표 문단까지 열렸다
    (「그는 「금리가 부담이다」라고 말했다」 → 「그는 금리가 기회라고 말했다」가 guard 를 통과, codex 구현 #3).
    """
    if any(a <= m.start() < b for a, b in spans):
        return 'protected'
    masked, tags = _mask(m.group(2))
    if _inline_protected(masked, tags):
        return 'inline_protected'
    if flow.has_quote(masked):
        return 'quote'
    return flow.why_excluded(html, m, spans, zones, ledger)


def split(review, html, ledger=locks.NO_LEDGER):
    """→ {'facts': str, 'accuracy': [지적], 'candidates': dict, 'unplaced': [지적], 'excluded': [지적]}"""
    facts, findings = gate.split_style_findings(review)
    accuracy = [f for f in findings if f['kind'] in ACCURACY_KINDS]
    style = [f for f in findings if f['kind'] not in ACCURACY_KINDS]
    raw = html.encode('utf-8')
    spans, zones = _protected(html), locks.zone_spans(html)
    paras = []
    for pid, m in _eligible(html):
        masked, _ = _mask(m.group(2))
        paras.append((pid, m, _norm(masked)))
    items, unplaced, excluded, by_pid = [], [], [], {}
    for f in style:
        probe = _probe(f.get('quote'))
        hit = next(((pid, m, t) for pid, m, t in paras if probe and probe in t), None)
        if not hit:
            unplaced.append(f)
            continue
        pid, m, text = hit
        why = _why(html, m, spans, zones, ledger)
        if why and why not in OPEN:
            excluded.append(dict(f, why=why))
            continue
        hint = f"{f['kind']}: {f.get('note', '')}".strip()
        relax = f['kind'] == '번역투'
        if pid in by_pid:
            by_pid[pid]['hint'] += ' / ' + hint
            if relax:
                by_pid[pid]['relax'] = 'translationese'
            continue
        start = len(html[:m.start(2)].encode('utf-8'))
        end = start + len(m.group(2).encode('utf-8'))
        item = {'id': 'C%02d' % (len(items) + 1), 'pid': pid, 'start': start, 'end': end,
                'inner_sha1': flow.sha1(raw[start:end]), 'masked': text, 'hint': hint,
                'opened': why or ''}
        if relax:
            item['relax'] = 'translationese'
        items.append(item)
        by_pid[pid] = item
    items.sort(key=lambda it: it['start'])
    for n, it in enumerate(items, 1):
        it['id'] = 'C%02d' % n
    cand = {'source_sha1': flow.sha1(raw), 'source_sha256': flow.sha256(raw),
            'rule': {'source': 'prepub-codex'}, 'items': items, 'skipped': {}}
    return {'facts': facts, 'accuracy': accuracy, 'candidates': cand, 'style': style,
            'unplaced': unplaced, 'excluded': excluded}
