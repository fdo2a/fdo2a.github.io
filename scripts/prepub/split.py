"""codex 답 → (정확성 몫, 문체 후보).

- 정확성 몫: 사실 검토 부분 전체 + 문체 지적 가운데 확신도에 닿는 것(「판단 세기 흐림」「원문에 없는 관계」).
  오케스트레이터가 근거와 대조해 판정한다(DESK_REPORT 「Causal claims are as strong as their evidence」 —
  근거 없는 원인 단정은 정확성 오류). 의미 검사자는 세기 변화를 「changed」로 막으므로 문체 경로에 넣지 않는다.
- 문체 후보: **「번역투」 지적만**(2026-11-07 사용자 결정 「번역투 고치는것만 검토하는걸로 하자」). 반복·끊긴
  흐름·기타는 문장을 지우거나 옮겨야 풀리는데 STYLE_CLOSE §13 이 그것을 막는다 — 발행 전에는 고치지 않고
  `dropped` 로 세기만 한다(발행 뒤 맥 러너의 지적·주간 묶음이 계속 본다). 번역투가 가리킨 문단을 STEP 2.6 의 후보 형식
  (`close.flow.scan` 과 같은 구간·해시)으로. 그 뒤는 `.claude/STYLE_CLOSE.md` A 의 5-12 를 탄다
  (작성자 편집 → guard → 의미 검사 → 반영).
  · 판단 구역(Z)·판단 문장이 든 문단도 후보로 받는다(2026-11-07 사용자 결정 「번역투나 문체수정에 더 무게」).
    판단 문장은 guard 가 **글자 그대로** 지킨다(`locks.locked` 비교) — 같은 문단의 다른 문장만 바뀐다.
  · 「번역투」 지적은 판단 문장의 낱말까지 고칠 수 있다(`relax: "translationese"`) — 대신 판단 뼈대
    (`locks.judgment_skeleton`)가 같아야 하고, 그 묶음은 의미 검사를 두 번 받는다.
  · 따옴표·보호 구간·문단 안 보호 요소는 여전히 뺀다(발언 범위·표식이 바뀌는 길).
"""
import html as _html
import re

import review_gate as gate
from close import flow, locks
from us.prose_swap import _eligible, _mask
from us.translationese import _inline_protected, _protected

ACCURACY_KINDS = frozenset({'판단 세기 흐림', '원문에 없는 관계'})
OPEN = frozenset({'zone', 'locked'})   # 후보로 받는 제외 이유 — guard 가 판단 문장을 지킨다
_TRIM = re.compile(r'^[\s「『"\'“‘…·.]+|[\s」』"\'”’…·.]+$')
STYLE_KIND = '번역투'
MIN_PROBE = 4   # 「앞단 재가격」(6자) 같은 짧은 번역투 인용도 받는다 — 대신 글 전체에 한 번만 있어야 한다
_TAG = re.compile(r'<[^>]+>')
# 블록 경계 — 제목 끝 「앞단 」과 다음 캡션 첫 「재가격」이 붙어 가짜 중복을 만들지 않게 칸막이를 둔다(codex 구현 재검토 #3)
_BLOCK = re.compile(r'</?(?:p|h[1-6]|li|ul|ol|td|th|tr|table|caption|figcaption|figure|div|section|article|header|'
                    r'footer|nav|aside|details|summary|blockquote|title|br|hr)\b[^>]*>', re.I)
_WALL = '\x00'
# 화면에 안 보이는 것 — 스크립트·스타일·머리·주석 안의 글은 세지 않는다(재검토 3회 #2)
_HIDDEN = re.compile(r'<!--.*?-->|<(script|style|template|noscript|head)\b.*?</\1\s*>', re.S | re.I)


def _visible(html):
    """독자가 보는 글 — 블록 사이에 칸막이, 인라인 태그는 떼고, 엔티티(&nbsp; …)는 풀어서(재검토 #1)."""
    return _norm(_html.unescape(_TAG.sub('', _BLOCK.sub(_WALL, _HIDDEN.sub('', html)))))


def _count(text, probe):
    """겹치는 자리도 센다 — 「금리 금리 금리」의 「금리 금리」는 두 번이다(재검토 #2)."""
    return len(re.findall('(?=%s)' % re.escape(probe), text))


def _norm(text):
    return ' '.join((text or '').split())


def _probe(quote):
    """인용 **전체**(앞뒤 따옴표·말줄임만 뗀다) — 앞머리만 맞추면 뒷부분이 다른 인용도 붙었다(codex 구현 #2)."""
    q = _TRIM.sub('', _norm(quote))
    return q if len(q) >= MIN_PROBE else None


def _place(paras, probe, whole):
    """인용이 든 문단 — 글 전체(캡션·표·제목처럼 후보가 아닌 곳 포함)에 두 번 이상 나오면 고르지 않는다.

    후보 문단만 세면 캡션과 본문에 같은 짧은 인용이 있을 때 본문을 고쳤다 — codex 가 캡션을 짚었을 수 있다
    (codex 구현 #1). 짚은 자리를 짐작하면 엉뚱한 문단을 고친다.
    """
    hits = [p for p in paras if probe in p[3]]
    if not hits:
        return None
    return hits[0] if len(hits) == 1 and _count(whole, probe) == 1 else 'ambiguous'


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
    """→ {'facts', 'accuracy', 'candidates', 'style', 'unplaced', 'excluded', 'dropped'}"""
    facts, findings = gate.split_style_findings(review)
    accuracy = [f for f in findings if f['kind'] in ACCURACY_KINDS]
    style = [f for f in findings if f['kind'] == STYLE_KIND]
    dropped = [f for f in findings if f['kind'] not in ACCURACY_KINDS and f['kind'] != STYLE_KIND]
    raw = html.encode('utf-8')
    spans, zones = _protected(html), locks.zone_spans(html)
    paras = []
    hidden = [(h.start(), h.end()) for h in _HIDDEN.finditer(html)]
    for pid, m in _eligible(html):
        if any(a < m.end() and m.start() < b for a, b in hidden):
            continue   # 스크립트 문자열 속 「<p>…</p>」(재검토 4회 #1)도, 스크립트를 품은 문단(5회 #1)도 고르지 않는다
        masked, _ = _mask(m.group(2))
        # 찾기는 보이는 글로(「앞단 <strong>재가격</strong>」·「앞단&nbsp;재가격」도 붙는다 — 재검토 3회 #1),
        # 고치기는 자리표가 든 masked 로(guard 가 태그 개수·순서를 지킨다)
        paras.append((pid, m, _norm(masked), _visible(m.group(2))))
    whole = _visible(html)
    items, unplaced, excluded, by_pid = [], [], [], {}
    for f in style:
        probe = _probe(f.get('quote'))
        hit = _place(paras, probe, whole) if probe else 'short'
        if not isinstance(hit, tuple):
            unplaced.append(dict(f, why=hit or 'not_found'))
            continue
        pid, m, text, _ = hit
        why = _why(html, m, spans, zones, ledger)
        if why and why not in OPEN:
            excluded.append(dict(f, why=why))
            continue
        hint = f"{f['kind']}: {f.get('note', '')}".strip()
        if pid in by_pid:
            by_pid[pid]['hint'] += ' / ' + hint
            continue
        start = len(html[:m.start(2)].encode('utf-8'))
        end = start + len(m.group(2).encode('utf-8'))
        item = {'id': 'C%02d' % (len(items) + 1), 'pid': pid, 'start': start, 'end': end,
                'inner_sha1': flow.sha1(raw[start:end]), 'masked': text, 'hint': hint,
                'opened': why or '', 'relax': 'translationese',
                # guard 가 비교할 뼈대 — 원장(문턱·날짜)이 판단 문장을 더 잠그므로 원장을 쥔 여기서 뽑는다(codex 구현 #4)
                'held': locks.judgment_skeleton(text, ledger)[1]}
        items.append(item)
        by_pid[pid] = item
    items.sort(key=lambda it: it['start'])
    for n, it in enumerate(items, 1):
        it['id'] = 'C%02d' % n
    cand = {'source_sha1': flow.sha1(raw), 'source_sha256': flow.sha256(raw),
            'rule': {'source': 'prepub-codex'}, 'items': items, 'skipped': {}}
    return {'facts': facts, 'accuracy': accuracy, 'candidates': cand, 'style': style,
            'unplaced': unplaced, 'excluded': excluded, 'dropped': dropped}
