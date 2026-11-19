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
import re

import review_gate as gate
from prepub.public import _HIDDEN, norm as _norm, visible as _visible
from close import flow, locks
from us.prose_swap import _eligible, _mask
from us.translationese import _inline_protected, _protected

# 분류 → 가는 길(2026-11-18, 설계 `../design-clarity-review.md`). 길은 지금 있는 둘뿐이고 새로 만들지 않는다.
#   style_path  — STEP 2.6 의 안전장치(작성자 편집 → guard → 의미 검사)를 번역투와 같은 조건으로 탄다
#   accuracy    — 오케스트레이터가 근거와 대조해 판정한다(`facts.md`)
#   record_only — 발행 전에는 고치지 않는다. guard 가 문장 쪼개기를 받지 않고(문장 구조), 가리키는 대상을 써넣는
#                 것은 뜻을 더하는 일이다(지시 대상 불명확). 기록만 하고 발행한다 — 발행을 막지 않는다.
# `용어` 를 기록만 하는 쪽으로 돌리려면 이 표의 한 줄만 바꾼다.
ROUTES = {'번역투': 'style_path', '용어': 'style_path',
          '문장 구조': 'record_only', '지시 대상 불명확': 'record_only',
          '판단 세기 흐림': 'accuracy', '원문에 없는 관계': 'accuracy', '논리·사실관계 의심': 'accuracy'}
ACCURACY_KINDS = frozenset(k for k, r in ROUTES.items() if r == 'accuracy')
PATH_KINDS = frozenset(k for k, r in ROUTES.items() if r == 'style_path')
RECORD_KINDS = frozenset(k for k, r in ROUTES.items() if r == 'record_only')
# 명료성 분류 — 공개 기록의 `clarity` 에 실린다. 번역투와 옛 확신도 두 분류는 지금 자리(`style_findings`·건수) 그대로다.
CLARITY_KINDS = ('용어', '문장 구조', '지시 대상 불명확', '논리·사실관계 의심')
# 고치는 두 길(정확성 + 문체)에 들어가는 지적의 합은 지금 전체 상한과 같다 — 길에 들어가는 양을 늘리지 않는다.
FIX_MAX = gate.STYLE_FINDINGS_MAX
RECORD_MAX = 5
_KNOWN = frozenset(gate.STYLE_KINDS) | frozenset(ROUTES)
_NONE = frozenset({'없음', '없음.', '- 없음', '지적 없음', '지적 없음.'})
_TELL = re.compile(r'^\s*\(?\s*(가|나|다)\s*\)')
OPEN = frozenset({'zone', 'locked'})   # 후보로 받는 제외 이유 — guard 가 판단 문장을 지킨다
_TRIM = re.compile(r'^[\s「『"\'“‘…·.]+|[\s」』"\'”’…·.]+$')
STYLE_KIND = '번역투'
MIN_PROBE = 4   # 「앞단 재가격」(6자) 같은 짧은 번역투 인용도 받는다 — 대신 글 전체에 한 번만 있어야 한다


def _count(text, probe):
    """겹치는 자리도 센다 — 「금리 금리 금리」의 「금리 금리」는 두 번이다(재검토 #2)."""
    return len(re.findall('(?=%s)' % re.escape(probe), text))


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


def _tell(f):
    """독자가 알 수 없는 것 — 가(무엇이 일어났는지)·나(어떤 판단인지)·다(무엇을 가리키는지). 닫힌 값만 뽑는다."""
    if ROUTES[f['kind']] == 'accuracy':
        return ''
    m = _TELL.match(f.get('note') or '')
    return m.group(1) if m else f.get('tell_in_quote', '')


def read_findings(review):
    """codex 답 → (사실 검토 부분, 고른 지적들, 읽기 요약).

    `review_gate.split_style_findings`(발행 뒤 검토와 공유, 고치지 않는다)와 같은 표식·같은 줄 꼴을 읽되,
    **적힌 순서에 기대지 않는다** — 줄을 끝까지 읽은 뒤 길별로 센다. 옛 함수는 앞 8줄에서 끊어, 기록만 하는
    지적이 앞에 많으면 뒤의 정확성 지적을 읽지 못했다. 고치는 두 길의 합은 `FIX_MAX`(정확성 먼저),
    기록만 하는 것은 `RECORD_MAX`. 길이 없는 분류(반복·끊긴 흐름·기타·모르는 이름)는 지금처럼 세기만 한다(8건까지).
    옛 읽기와 달라지는 곳은 셋이다 — `tests/test_clarity.py::test_the_three_intended_differences_from_the_old_reader`.
    """
    text = review or ''
    at = text.rfind(gate.STYLE_FINDINGS_HEAD)
    meta = {'marker': at >= 0, 'lines_skipped': 0, 'over_cap': 0}
    if at < 0:
        return text, [], meta
    head, tail = text[:at].rstrip() + '\n', text[at + len(gate.STYLE_FINDINGS_HEAD):]
    read = []
    for line in tail.splitlines():
        m = gate._FINDING_RE.match(line)
        if not m:
            if line.strip() and line.strip() not in _NONE:
                meta['lines_skipped'] += 1      # 지적으로 읽히지 않은 줄 — 꼴이 깨진 답의 일부만 잡는다
            continue
        kind = m.group(1).strip()
        f = {'kind': kind if kind in _KNOWN else '기타',
             'quote': (m.group(2) or '').strip()[:80], 'note': m.group(3).strip()[:300]}
        if f['kind'] in CLARITY_KINDS and ROUTES[f['kind']] != 'accuracy':
            # 검토자가 「(나) 이분 사건…」처럼 표식을 인용 안에 넣는 일이 있다(2026-11-18 측정, 엿새 중 이틀) —
            # 그대로면 인용이 글과 맞지 않는다. 표식을 인용에서 떼어 둔다(문제 자리에 적은 표식이 있으면 그쪽이 먼저다).
            inside = _TELL.match(f['quote'])
            if inside:
                f['quote'] = f['quote'][inside.end():].strip()
                f['tell_in_quote'] = inside.group(1)
        read.append(f)
    keep, room = set(), FIX_MAX
    for group, cap in ((ACCURACY_KINDS, None), (PATH_KINDS, None), (RECORD_KINDS, RECORD_MAX)):
        for n, f in enumerate(read):
            if f['kind'] not in group:
                continue
            if cap is None:                     # 고치는 길 — 정확성을 먼저 채우고 남는 자리에 문체 길
                if room > 0:
                    keep.add(n)
                    room -= 1
            elif cap > 0:
                keep.add(n)
                cap -= 1
    other = [n for n, f in enumerate(read) if f['kind'] not in ROUTES][:FIX_MAX]   # 길이 없는 분류 — 옛 읽기의 「앞 8줄」 크기로
    keep.update(other)
    out = [f for n, f in enumerate(read) if n in keep]
    meta['over_cap'] = len(read) - len(out)
    return head, out, meta


def split(review, html, ledger=locks.NO_LEDGER):
    """→ {'facts', 'accuracy', 'candidates', 'style', 'unplaced', 'excluded', 'dropped', 'clarity', 'meta'}

    `style` 은 번역투만이다(공개 기록의 `style_findings` — 주간 묶음이 두 번 세지 않게). 명료성 분류는 `clarity`.
    """
    facts, findings, meta = read_findings(review)
    accuracy = [f for f in findings if f['kind'] in ACCURACY_KINDS]
    style = [f for f in findings if f['kind'] == STYLE_KIND]
    path = [f for f in findings if f['kind'] in PATH_KINDS]
    dropped = [f for f in findings if f['kind'] not in ROUTES]
    # 명료성 지적마다 split 시점에 정해지는 것만 적는다 — 고쳐졌는지는 여기서 알 수 없다(발행 뒤 발행본과 견준다)
    clarity, entry = [], {}
    for f in findings:
        if f['kind'] in CLARITY_KINDS:
            entry[id(f)] = dict(f, route=ROUTES[f['kind']], placed='', cannot_tell=_tell(f))
            entry[id(f)].pop('tell_in_quote', None)
            clarity.append(entry[id(f)])

    def placed(f, where):
        if id(f) in entry:
            entry[id(f)]['placed'] = where

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
    for f in path:
        probe = _probe(f.get('quote'))
        hit = _place(paras, probe, whole) if probe else 'short'
        if not isinstance(hit, tuple):
            unplaced.append(dict(f, why=hit or 'not_found'))
            placed(f, 'not_located')
            continue
        pid, m, text, _ = hit
        why = _why(html, m, spans, zones, ledger)
        if why and why not in OPEN:
            excluded.append(dict(f, why=why))
            placed(f, 'protected')
            continue
        placed(f, 'candidate')
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
            'unplaced': unplaced, 'excluded': excluded, 'dropped': dropped,
            'clarity': clarity, 'meta': meta}
