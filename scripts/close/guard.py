"""문체 마감 guard — 결정적 검사(check)·반영(apply)·발행 판 대조(verify)·누출 검사.

흐름(오케스트레이터 STEP 2.6):
  check   pre + candidates + edits → 통과 편집을 끼운 제안 판 → 쓰기 단계(apply_readability,
          US 는 apply_colors) → `proposed_written` 과 검사자에게 줄 묶음(pairs.json·checker_input.txt)
  apply   pairs.json 을 믿지 않고 pre·candidates·edits 로 **다시 만들어** sha256 이 verdicts 와 같고
          모든 묶음이 `same` 일 때만 approved = proposed_written. 아니면 `recheck`(1회) 또는 편집 0
  verify  approved ↔ 대상(작업 파일·HEAD blob·origin/main blob) — 에디터 노트 블록만 뺀 바이트 일치

위협 모델: 비적대적(사고 방지). 서브에이전트의 의도적 우회·프롬프트 인젝션은 보장 범위 밖이다(v4.6).
「guard 를 통과했다」는 「의미가 같다」가 아니다 — 남는 위험은 검사자(close-meaning-checker)가 본다.
"""

import hashlib
import json
import random
import re
from collections import Counter
from html.parser import HTMLParser

from close import locks
from close.flow import sha1, sha256
from us.prose_swap import (ProseSwapError, _check_one, _check_strict, _eligible, _mask, _plain,
                           extract)
from us.translationese import _QUOTE_CHARS, _quote_view

MAX_ROUNDS = 2
VERDICTS = ('same', 'changed', 'unsure')

# 관계 표지(v3 §3) — 원문과 표지별 개수가 같아야 한다. 위험을 줄이는 1차 거름이지 의미 보존의 보증이
# 아니다(목록 밖 표지·같은 개수의 다른 연결은 검사자가 본다).
_NOUN_JA = ('투자', '적자', '흑자', '이자', '숫자', '문자', '기자', '소비자', '사업자', '관계자', '참가자',
            '유권자', '근로자', '생산자', '소유자', '책임자', '당사자', '후자', '전자', '양자', '제자', '자자',
            '의자', '여자', '남자', '환자', '학자', '독자', '저자', '부자', '왕자', '주자', '타자', '혁신자')
_NOUN_SEO = ('보고서', '문서', '순서', '증서', '계약서', '설명서', '신청서', '각서', '서한', '부서', '지점서')
RELATIONS = (
    ('면서', re.compile(r'면서')),
    ('므로', re.compile(r'므로')),
    ('니까', re.compile(r'니까')),
    ('-서', re.compile(r'(?<=[가-힣])(?<!에)(?<!로)(?<!게)(?<!부터)서(?=[\s,])')),
    ('-자', re.compile(r'(?<=[가-힣])자(?=[\s,])')),
    ('바람에', re.compile(r'바람에')),
    ('덕에', re.compile(r'덕에')),
    ('결과', re.compile(r'결과')),
    ('지만', re.compile(r'지만')),
    ('반면', re.compile(r'반면')),
    ('그러나', re.compile(r'그러나')),
    ('하지만', re.compile(r'하지만')),
    ('그런데', re.compile(r'그런데')),
    ('오히려', re.compile(r'오히려')),
    ('되레', re.compile(r'되레')),
)
_WORD = re.compile(r'[가-힣A-Za-z0-9]+')
_MARK_ANY = re.compile(r'⟦\d+⟧')
_ENT = re.compile(r'&(?:#\d+|#[xX][0-9a-fA-F]+|[A-Za-z][A-Za-z0-9]*);?')
_TITLE = re.compile(r'<h([23])\b[^>]*>(.*?)</h\1>', re.S)
_TAGS = re.compile(r'<[^>]+>')


class GuardError(Exception):
    """입력 오류 — 종료 2(오케스트레이터는 편집 0 으로 진행)."""


def relations(text):
    plain = _plain(text)
    out = Counter()
    for key, rx in RELATIONS:
        for m in rx.finditer(plain):
            if key in ('-자', '-서'):
                words = _WORD.findall(plain[:m.end()])
                word = words[-1] if words else ''
                nouns = _NOUN_JA if key == '-자' else _NOUN_SEO
                if any(word.endswith(n) for n in nouns):
                    continue
            out[key] += 1
    return out


def entities(text):
    return Counter(_ENT.findall(_MARK_ANY.sub('', text)))


class _Seq(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=False)
        self.seq = []
        self.feed(html)
        self.close()

    def handle_starttag(self, tag, attrs):
        self.seq.append(('<', tag, tuple(attrs)))

    def handle_startendtag(self, tag, attrs):
        self.seq.append(('<>', tag, tuple(attrs)))

    def handle_endtag(self, tag):
        self.seq.append(('>', tag))


def tag_sequence(html):
    return _Seq(html).seq


def _norm(text):
    return ' '.join(str(text).split())


# ---------------------------------------------------------------- one edit

def check_edit(pid, before, after, known, names=(), ledger=locks.NO_LEDGER, relax=False, scope=False):
    """한 편집 → 새 inner(str). 어기면 ProseSwapError(이유).

    `relax` 는 발행 전 codex 검토의 「번역투」 후보뿐이다(후보의 `relax: "translationese"`): 판단 문장을
    글자 그대로 두는 대신 뼈대(`locks.judgment_skeleton`)만 같으면 된다. 나머지 검사는 그대로다.
    """
    if not isinstance(after, str) or not after.strip():
        raise ProseSwapError('빈 편집')
    after = _norm(after)
    bare = _MARK_ANY.sub('', after)
    if '<' in bare or '>' in bare:
        raise ProseSwapError('자리표 밖에 < 또는 > 가 있다(생 HTML)')
    if entities(before) != entities(after):
        raise ProseSwapError('엔티티(&…;)가 달라졌다')
    if any(c in _QUOTE_CHARS for c in _quote_view(after)):
        raise ProseSwapError('따옴표가 생겼다')
    _check_strict(pid, before, after, names)
    if relations(before) != relations(after):
        a, b = relations(before), relations(after)
        raise ProseSwapError('관계 표지가 달라졌다 — 사라진 것 %s, 생긴 것 %s'
                             % (sorted((a - b).elements()), sorted((b - a).elements())))
    if locks.demonstratives(before) != locks.demonstratives(after):
        raise ProseSwapError('지시어 개수가 달라졌다(D)')
    if locks.ctrl_order(before) != locks.ctrl_order(after):
        raise ProseSwapError('판단 어휘 순서가 달라졌다(C)')
    if scope and locks.scope_marks(before) != locks.scope_marks(after):
        raise ProseSwapError('범위·세기·한계 낱말(일부·모든·일시적·지속적·다만·불확실 …)의 순서·개수가 달라졌다')
    if relax:
        # 쪼개기·합치기 금지 — 「…기본 경로로 굳어지는 앞단 재가격으로 본다」를 「…기본 경로다. 앞단 재가격으로
        # 본다.」로 나누면 판단 어휘 없는 단정문이 생겨 뼈대 검사만으로는 안 걸린다(2026-11-07 시험).
        if len(locks.sentences(before)) != len(locks.sentences(after)):
            raise ProseSwapError('번역투 수정은 문장 수를 바꾸지 않는다(쪼개기·합치기 금지)')
        if locks.judgment_skeleton(before, ledger) != locks.judgment_skeleton(after, ledger):
            raise ProseSwapError('판단 문장의 뼈대(판단 어휘·기간·원장 앵커의 순서·개수, 문장 수)가 달라졌다')
    elif locks.locked(before, ledger) != locks.locked(after, ledger):
        raise ProseSwapError('판단·기간·원장 문장이 생기거나 바뀌었다(V·L·T)')
    return _check_one(pid, after, known)


# ---------------------------------------------------------------- write stage

def write_stage(market):
    """쓰기 단계(게이트 체인의 앞 두 단계) — html(str) → html(str)."""
    from common import analytics
    from us import readability

    def run(html):
        out = analytics.inject(readability.enhance_html(html))
        if market == 'us':
            from us import colorize
            out = colorize.apply(out)
        return out
    return run


def _identity(html):
    return html


def _texts(html):
    return [_norm(_plain(_mask(m.group(2))[0])) for _, m in _eligible(html)]


# ---------------------------------------------------------------- check

def _parse_edits(edits):
    if isinstance(edits, dict) and isinstance(edits.get('edits'), dict):
        edits = edits['edits']
    if not isinstance(edits, dict):
        raise GuardError('edits 는 {id: 텍스트} 객체여야 한다')
    return edits


def _validate_candidates(pre, cand):
    if not isinstance(cand, dict) or not isinstance(cand.get('items'), list):
        raise GuardError('candidates 형식이 아니다')
    if cand.get('source_sha256') != sha256(pre) or cand.get('source_sha1') != sha1(pre):
        return '후보가 다른 판에서 나왔다(source sha 불일치)'
    seen, last = set(), -1
    for it in sorted(cand['items'], key=lambda x: x.get('start', -1)):
        if it.get('id') in seen:
            return '후보 id 중복'
        seen.add(it.get('id'))
        s, e = it.get('start'), it.get('end')
        if not (isinstance(s, int) and isinstance(e, int) and 0 <= s <= e <= len(pre)) or s < last:
            return '후보 구간이 잘못됐거나 겹친다'
        last = e
        if sha1(pre[s:e]) != it.get('inner_sha1'):
            return '%s 구간 해시 불일치' % it.get('id')
    return None


def build(pre, cand, edits, *, market='us', names=(), ledger=locks.NO_LEDGER, exclude=(), write=None):
    """pre(bytes) → 결과 dict. 같은 입력이면 같은 결과(apply 가 다시 만든다)."""
    write = write or _identity
    edits = _parse_edits(edits)
    html = pre.decode('utf-8')
    result = {'source_sha256': sha256(pre), 'candidates_sha256': sha256(_canon(cand)),
              'edits_sha256': sha256(_canon(edits)), 'exclude': sorted(exclude),
              'edits': {}, 'bundles': [], 'proposed_written': None, 'proposed_sha256': None}
    bad = _validate_candidates(pre, cand)
    if bad:
        result['fatal'] = bad
        return result
    items = {it['id']: it for it in cand['items']}
    _, side = extract(html)
    known = side['items']
    order = [pid for pid, _ in _eligible(html)]
    unknown = sorted(str(k) for k in edits if k not in items)
    if unknown:
        result['fatal'] = '모르는 후보 id — %s' % ', '.join(unknown)[:200]
        return result
    accepted = []
    for eid in sorted(edits, key=str):
        text = edits[eid]
        if eid not in items:
            result['edits'][eid] = {'status': 'rejected', 'reason': '모르는 후보 id'}
            continue
        it = items[eid]
        if it.get('pid') not in known:
            result['edits'][eid] = {'status': 'rejected', 'reason': '후보 문단을 찾을 수 없다'}
            continue
        before = it['masked']
        if isinstance(text, str) and _norm(text) == _norm(before):
            result['edits'][eid] = {'status': 'unchanged'}
            continue
        try:
            new_inner = check_edit(it['pid'], before, text, known, names, ledger,
                                   relax=it.get('relax') == 'translationese',
                                   scope=bool(it.get('opened') or it.get('relax')))
        except ProseSwapError as exc:
            result['edits'][eid] = {'status': 'rejected', 'reason': str(exc), 'after': _norm(str(text))}
            continue
        if eid in exclude:
            result['edits'][eid] = {'status': 'excluded', 'after': _norm(text)}
            continue
        result['edits'][eid] = {'status': 'passed', 'after': _norm(text)}
        accepted.append((it, new_inner.encode('utf-8')))
    proposed = splice(pre, accepted)
    if not _outside_equal(pre, proposed, accepted):
        result['fatal'] = '끼운 구간 밖 바이트가 달라졌다'
        return result
    if tag_sequence(proposed.decode('utf-8')) != tag_sequence(html):
        result['fatal'] = '결과 html 의 태그·속성 순서가 원문과 다르다'
        return result
    pre_w = write(html)
    prop_w = write(proposed.decode('utf-8'))
    if _texts(pre_w) != _texts(html) or _texts(prop_w) != _texts(proposed.decode('utf-8')):
        result['fatal'] = '쓰기 단계가 본문 텍스트를 바꿨다'
        return result
    result['proposed_written'] = prop_w
    result['proposed_sha256'] = sha256(prop_w.encode('utf-8'))
    result['bundles'] = bundles(pre_w, prop_w, [it for it, _ in accepted], order, html)
    return result


def _canon(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def splice(pre, accepted):
    out = pre
    for it, new in sorted(accepted, key=lambda x: x[0]['start'], reverse=True):
        out = out[:it['start']] + new + out[it['end']:]
    return out


def _outside_equal(pre, proposed, accepted):
    """끼운 구간을 뺀 바이트열이 같은가(사후 단언)."""
    def cut(raw, spans):
        parts, last = [], 0
        for s, e in spans:
            parts.append(raw[last:s])
            last = e
        parts.append(raw[last:])
        return b''.join(parts)
    spans_pre = sorted((it['start'], it['end']) for it, _ in accepted)
    shift, spans_new = 0, []
    for it, new in sorted(accepted, key=lambda x: x[0]['start']):
        s = it['start'] + shift
        spans_new.append((s, s + len(new)))
        shift += len(new) - (it['end'] - it['start'])
    return cut(pre, spans_pre) == cut(proposed, spans_new)


def _title_before(html, pos):
    title = ''
    for m in _TITLE.finditer(html, 0, pos):
        title = _norm(_TAGS.sub('', m.group(2)))
    return title


def bundles(pre_w, prop_w, accepted_items, order, pre_html):
    """인접(사이에 다른 eligible 문단이 없는) 편집을 한 묶음으로. 문맥은 제안 판 기준."""
    before_ps = {pid: m for pid, m in _eligible(pre_w)}
    after_ps = {pid: m for pid, m in _eligible(prop_w)}
    idx = {pid: i for i, pid in enumerate(order)}
    groups = []
    for it in sorted(accepted_items, key=lambda x: idx[x['pid']]):
        if groups and idx[it['pid']] == idx[groups[-1][-1]['pid']] + 1:
            groups[-1].append(it)
        else:
            groups.append([it])
    out = []

    def text(ps, pid):
        m = ps.get(pid)
        return _norm(_mask(m.group(2))[0]) if m else ''
    pre_pos = {pid: m.start() for pid, m in _eligible(pre_html)}
    for n, g in enumerate(groups, 1):
        first, last = idx[g[0]['pid']], idx[g[-1]['pid']]
        prev_pid = order[first - 1] if first > 0 else None
        next_pid = order[last + 1] if last + 1 < len(order) else None
        b = {'id': 'B%02d' % n, 'edits': [it['id'] for it in g], 'pids': [it['pid'] for it in g],
             # 판단 문장 낱말까지 바뀔 수 있는 묶음 — 의미 검사를 두 번 받는다(PREPUB_REVIEW 3)
             'judgment': any(it.get('relax') == 'translationese' for it in g),
             'title': _title_before(pre_html, pre_pos[g[0]['pid']]),
             'prev': text(after_ps, prev_pid) if prev_pid else '',
             'next': text(after_ps, next_pid) if next_pid else '',
             'before': [text(before_ps, it['pid']) for it in g],
             'after': [text(after_ps, it['pid']) for it in g]}
        b['hash'] = sha256(_canon(b))
        out.append(b)
    return out


def checker_input(result):
    """검사자에게 줄 글 — 묶음 텍스트와 판 해시뿐. 순서는 판 해시로 섞는다(재현 가능)."""
    bs = list(result['bundles'])
    random.Random(result['proposed_sha256']).shuffle(bs)
    lines = ['proposed_sha256: %s' % result['proposed_sha256'], '']
    for b in bs:
        lines.append('=== %s ===' % b['id'])
        if b['title']:
            lines.append('[섹션] %s' % b['title'])
        lines.append('[앞 문단] %s' % (b['prev'] or '(없음)'))
        for i, (x, y) in enumerate(zip(b['before'], b['after']), 1):
            lines.append('[원문 %d] %s' % (i, x))
            lines.append('[수정본 %d] %s' % (i, y))
        lines.append('[뒤 문단] %s' % (b['next'] or '(없음)'))
        lines.append('')
    lines.append('답: {"proposed_sha256": "<위 값>", "verdicts": {"B01": {"verdict": "same|changed|unsure", '
                 '"why": "<한 줄>"}, ...}} — JSON 하나만.')
    return '\n'.join(lines)


def pairs_doc(result):
    return {k: v for k, v in result.items() if k != 'proposed_written'}


# ---------------------------------------------------------------- apply

def parse_verdicts(raw):
    """검사자 응답(JSON 문자열·dict) → dict 또는 None(깨짐). 코드 울타리·앞뒤 말은 걷어 낸다."""
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    m = re.search(r'\{.*\}', text, re.S)
    if not m:
        return None
    try:
        doc = json.loads(m.group(0))
    except ValueError:
        return None
    return doc if isinstance(doc, dict) else None


def decide(result, verdicts, round_no=1):
    """→ (status, exclude_ids, per_bundle). status: applied | recheck | zero."""
    if result.get('fatal') or result.get('proposed_sha256') is None:
        return 'zero', [], {}
    if not result['bundles']:
        return 'zero', [], {}
    doc = parse_verdicts(verdicts)
    if doc is None:
        return 'zero', [], {'_': 'verdicts 를 읽을 수 없다'}
    if doc.get('proposed_sha256') != result['proposed_sha256']:
        return 'zero', [], {'_': 'verdicts 가 다른 판에 대한 것이다'}
    got = doc.get('verdicts')
    if not isinstance(got, dict):
        return 'zero', [], {'_': 'verdicts 형식이 아니다'}
    ids = {b['id'] for b in result['bundles']}
    if set(got) - ids:
        return 'zero', [], {'_': '모르는 묶음 id'}
    per = {}
    for b in result['bundles']:
        v = got.get(b['id'])
        verdict = v.get('verdict') if isinstance(v, dict) else None
        per[b['id']] = verdict if verdict in VERDICTS else 'unsure'
    bad = [b for b in result['bundles'] if per[b['id']] != 'same']
    if not bad:
        return 'applied', [], per
    if round_no >= MAX_ROUNDS:
        return 'zero', [], per
    keep = [b for b in result['bundles'] if per[b['id']] == 'same']
    if not keep:
        return 'zero', [], per
    return 'recheck', sorted(e for b in bad for e in b['edits']), per


# ---------------------------------------------------------------- verify

def same_published(approved, target):
    """대상 = approved 이거나, approved 에 apply_note 로 노트 블록 하나만 더한 판인가(바이트 그대로)."""
    if approved == target:
        return True
    from us.editor_note import _SECTION_RE, apply_note
    m = _SECTION_RE.search(target)
    if not m:
        return False
    block = m.group(0).strip()
    return any(apply_note(approved, b) == target for b in (block, block + '\n'))


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


# ---------------------------------------------------------------- writer prompt

EXEMPLARS = 'STYLE_EXEMPLARS.md'


def closing_rules(path):
    """STYLE_EXEMPLARS 의 §13 만 — 정본은 그 파일 하나다(복제하지 않고 실행 때 뽑는다)."""
    with open(path, encoding='utf-8') as fh:
        text = fh.read()
    m = re.search(r'^## 13\..*?(?=^## |\Z)', text, re.S | re.M)
    if not m:
        raise GuardError('STYLE_EXEMPLARS 에 §13 이 없다')
    return m.group(0).strip()


def _held_marks(text, marks=None):
    """guard 가 지킬 표지를 작성자에게 미리 보인다 — 11/06 US 시험에서 작성자가 번역투를 풀며 「쪽으로」를 새로
    써 뼈대에서 기각됐다(무엇이 판단 표지인지 몰랐다).

    `marks` 는 split 이 원장을 쥐고 뽑은 뼈대다(`item['held']`) — 원장 문턱·날짜가 든 문장도 판단 문장으로 잠기므로
    원장 없이 다시 세면 guard 가 비교하는 표지가 빠진다(codex 구현 #4). 수량어는 대상 명사구까지 보인다 — guard 는
    「일부:반도체 업종은」을 비교한다(codex 구현 #3).
    """
    if marks is None:
        _, marks = locks.judgment_skeleton(text)
    judged = [m.split(':', 1)[1] if m[:2] in ('A:', 'T:', 'L:') else m for m in marks]
    scope = locks.scope_marks(text)
    quants = [m for m in scope if ':' in m]
    words = [m for m in scope if ':' not in m]
    out = (' · 문장 수를 그대로 두고, 판단 표지 %s 는 같은 순서·개수로 남긴다'
           % (''.join(f'「{m}」' for m in judged) or '(없음)'))
    if words:
        out += ' · 범위 낱말 %s 도 같은 순서·개수로' % ''.join(f'「{m}」' for m in words)
    if quants:
        out += (' · 수량어가 걸린 말 %s 은 대상까지 글자 그대로'
                % ''.join('「%s」' % ' '.join(x for x in m.split(':', 1) if x) for m in quants))
    return out + ' · 이 목록에 없는 판단·범위 낱말(쪽·본다·근거·가능성·일부·기대 …)은 새로 쓰지 않는다'


def writer_input(cand, rules):
    """작성자에게 줄 글 — 규칙 절과 후보 문단 텍스트뿐(파일 경로를 주지 않는다).

    발행 전 codex 검토가 만든 후보(`hint` 가 있다)는 그 지적만 고치게 한다 — 짧은 문장 잇기가 아니다.
    뜻을 지키는 규칙(§13 의 1·4·5·6)은 그대로 걸린다.
    """
    hinted = any(it.get('hint') for it in cand.get('items', []))
    head = ('발행 전 검토가 짚은 문체 문제를 고친다. 문단마다 붙은 지적만 고치고, 뜻(사실·수치·출처·판단의 방향과 '
            '세기·한계)은 아래 규칙대로 그대로 둔다. 고치면 뜻이 바뀌는 지적은 고치지 않는다. JSON 하나로만 답한다. '
            '파일을 읽거나 쓰지 않는다.' if hinted else
            '문체 마감(STEP 2.6). 아래 규칙대로 후보 문단을 다듬어 JSON 하나로만 답한다. 파일을 읽거나 쓰지 않는다.')
    lines = [head, '', rules, '', '--- 후보 문단 ---']
    for it in cand.get('items', []):
        if it.get('hint'):
            keep = ''
            if it.get('relax') == 'translationese':
                keep = ' · 판단 문장은 판단 어휘·날짜·수치를 같은 순서로 남기고 낱말만 고친다' + _held_marks(it['masked'], it.get('held'))
            elif it.get('opened'):
                keep = ' · 판단 문장(판단·해석·근거·본다·쪽이다·확인 기준 …이 든 문장)은 글자 그대로 둔다'
            lines.append('[%s] (지적 — %s%s) %s' % (it['id'], it['hint'], keep, it['masked']))
        else:
            lines.append('[%s] %s' % (it['id'], it['masked']))
    lines.append('')
    lines.append('답: {"C01": "<바꾼 글>", ...} — 고친 문단만, 없으면 {}.')
    return '\n'.join(lines)
