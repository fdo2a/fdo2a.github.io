"""발행본의 산문만 꺼내 주고, 윤문된 것을 제자리에 돌려놓는다.

STEP 2.5(AI 티 제거)에서 쓴다. `humanize-korean` 스킬은 텍스트를 받아 마크다운을
내놓지 HTML을 고쳐 주지 않는다. 그 사이를 사람이 손으로 메우면 — 문단을 세어 가며
되꽂으면 — 조용히 틀어진다. 문단 **수**가 같아도 두 문단이 자리를 바꾸면 수치 멀티셋은
그대로라 verify_post를 통과한다. 그래서 셈이 아니라 **이름**으로 맞춘다.

계약:

- `extract()`가 손댈 수 있는 `<p>`에만 `P001` 같은 이름을 붙여 텍스트로 뽑고, 원문과
  인라인 태그를 사이드카에 적어 둔다. 표 안의 문단, 캡션, 에디터 노트는 애초에 뽑지
  않는다 — 넘기지 않은 것은 훼손될 수 없다.
- `reinsert()`는 이름으로 되꽂는다. 이름이 빠졌거나·겹치거나·모르는 이름이 왔거나,
  인라인 태그가 하나라도 사라졌거나, **그 문단의 숫자가 하나라도 달라졌으면** 통째로
  거부한다. 순서는 검사할 필요조차 없다 — 이름이 자리를 정하므로.
- 거부는 예외로 나가고, 호출자는 아무것도 쓰지 않는다.

Pure — 문자열을 받아 문자열을 돌려준다. 파일은 CLI(`scripts/humanize_prose.py`)가 만진다.
"""

import difflib
import hashlib
import re
from collections import Counter

MARK = '⟦{}⟧'
_MARK_RE = re.compile(r'⟦(\d+)⟧')
_P_RE = re.compile(r'<p\b([^>]*)>(.*?)</p>', re.S)
_TAG_RE = re.compile(r'</?[a-zA-Z][^>]*>')
_NUM_RE = re.compile(r'[+\-−]?\d[\d,]*(?:\.\d+)?%?')
_BLOCK_RE = re.compile(r'<(table|section)\b[^>]*>.*?</\1>', re.S)
_ID_RE = re.compile(r'^\[\[(P\d{3})\]\]\s*$')
# 산문에 나올 일이 없는 마크다운 문법 — 하나라도 보이면 그건 윤문이 아니라 재조판이다.
_MD_LINE_RE = re.compile(r'^\s*(#{1,6}\s|[-*+]\s|\d+[.)]\s|\||```|>\s)')
# `2Y*`처럼 홑별표는 이 프로젝트의 실제 표기다(커브 차트 각주). 짝지어진 강조만 막는다.
_MD_INLINE_RE = re.compile(r'\*\*|\*[^\s*][^*]*\*|__|`|!\[|\]\(|~~')

# 몸통이 제 이름에 묶여 있는지 보는 기준.
# 이 단계가 허락하는 것은 **문법과 말투까지**다. 절을 갈아끼우는 재작성은 허락하지
# 않는다 — 원문에 없던 인과를 넣거나 조건절을 떼어 단정으로 만드는 의미 변화는
# 어떤 사실 검사로도 못 잡기 때문에, 애초에 그만큼 못 바꾸게 막는 편이 낫다.
#
# 08-21 발행본 58문단 실측 (2026-08-25):
#   말투 교체 + 문장 분리 + 주어 복원   최저 0.95 / 중앙 0.99
#   절을 갈아끼운 재작성              하위10% 0.10 / 중앙 0.62
# 두 무리 사이에 선을 긋는다. 긴 문단에서 짧은 절 하나만 갈아끼우는 편집은 이
# 문턱을 넘을 수 있는데, 그건 위의 사실 검사들(숫자·티커·판단 어휘·링크)이 맡는다.
SIM_FLOOR = 0.80
LEN_RATIO = (0.5, 2.0)  # 문장을 나누거나 합칠 수는 있어도 분량이 배로 뛰지는 않는다


class ProseSwapError(Exception):
    """되꽂기를 거부한 이유. 호출자는 이걸 받으면 사본을 버린다."""


# 연준 발언 인용과 성명 변경점 블록. 이 안의 글은 **원문에 글자 그대로 있어야
# 통과하는** 것이라 말투를 다듬는 순간 발행 게이트가 막는다. 애초에 안 넘긴다 —
# 에디터 노트를 안 넘기는 것과 같은 이유다(넘기지 않은 것은 훼손될 수 없다).
_FED_START = re.compile(r'<div[^>]*\bdata-fed-(?:quote|change)\s*=', re.I)
_DIV_TOKEN = re.compile(r'<(/?)div\b', re.I)


def _balanced_div(html, start):
    """`start` 의 <div> 를 닫는 지점. 안 닫혀 있으면 문서 끝.

    표식 사이를 자르는 방식(fed_gate)을 여기서는 쓸 수 없다. 마지막 블록 뒤에 다음
    표식이 없으면 구역이 문서 끝까지 늘어나 **그 뒤 문단이 통째로 윤문에서 빠진다.**
    안 닫힌 경우 문서 끝을 돌려주는 것은 안전한 쪽으로 실패하는 것이다 — 덜 다듬을
    뿐이고, 인용문이 훼손되지는 않는다.
    """
    depth = 0
    for m in _DIV_TOKEN.finditer(html, start):
        depth += -1 if m.group(1) else 1
        if depth == 0:
            close = html.find('>', m.end())
            return len(html) if close < 0 else close + 1
    return len(html)


def _skip_spans(html):
    """뽑지 않을 구역 — 표 안, 에디터 노트 안, 연준 인용·변경점 블록 안."""
    spans = []
    for m in _BLOCK_RE.finditer(html):
        if m.group(1) == 'table' or 'data-editor-note' in m.group(0)[:400] or 'data-research-summary' in m.group(0).split('>', 1)[0]:
            spans.append((m.start(), m.end()))
    for m in _FED_START.finditer(html):
        spans.append((m.start(), _balanced_div(html, m.start())))
    return spans


def _eligible(html):
    """(id, match) 목록. 순서는 문서 순서."""
    skips = _skip_spans(html)
    out = []
    for m in _P_RE.finditer(html):
        if any(a <= m.start() < b for a, b in skips):
            continue
        if 'caption' in m.group(1):
            continue
        if not _NUM_RE.sub('', _TAG_RE.sub('', m.group(2))).strip():
            continue  # 글자가 없는 문단은 윤문할 것이 없다
        out.append(('P%03d' % (len(out) + 1), m))
    return out


def _mask(inner):
    """인라인 태그를 자리표로 바꾼다. 돌아올 때 하나도 빠지면 안 되는 것들."""
    tags = []

    def take(m):
        tags.append(m.group(0))
        return MARK.format(len(tags) - 1)

    return _TAG_RE.sub(take, inner), tags


def _unmask(text, tags):
    order = [int(n) for n in _MARK_RE.findall(text)]
    seen, want = Counter(order), Counter(range(len(tags)))
    if seen != want:
        missing, extra = sorted(want - seen), sorted(seen - want)
        raise ProseSwapError('인라인 표식이 맞지 않는다 — 사라진 것 %s, 늘어난 것 %s' % (missing, extra))
    if order != sorted(order):
        # 여는 태그와 닫는 태그가 자리를 바꾸면 HTML이 깨진다. 보수적으로 막는다.
        raise ProseSwapError('인라인 자리표 순서가 원문과 다르다: %s' % order)
    return _MARK_RE.sub(lambda m: tags[int(m.group(1))], text)


# 윤문이 건드리면 안 되는 것들. 말투는 바꿔도 이 낱말들은 그대로 있어야 한다 —
# 「완만한 개선」을 「뚜렷한 악화」로 바꾸면 3-gram 유사도는 0.8이 넘게 나오지만
# 그건 윤문이 아니라 판단을 뒤집은 것이다 (2026-08-25 codex 검토에서 실증).
CONTROLLED = (
    '개선', '악화', '보합', '둔화', '가속', '재가속', '교착', '완화', '긴축',
    '뚜렷', '완만', '미미', '확대', '축소', '중립',
    '리플레이션', '확장', '과열', '골디락스', '비용압박', '연착륙', '냉각', '스태그플레이션',
    '침체', '상향', '하향', '매파', '비둘기',
)
# 티커·기관 약어·영문 고유명사. 두 문단이 각자 제 원문과 닮은 채로 AAPL과 TSLA만
# 맞바꾸는 편집은 유사도로는 안 잡힌다.
_LATIN_RE = re.compile(r'[A-Za-z][A-Za-z&.\-]{1,}')


def _controlled(text):
    plain = _plain(text)
    return Counter({w: plain.count(w) for w in CONTROLLED if w in plain})


def _latin(text):
    return Counter(_LATIN_RE.findall(_plain(text)))


def _anchor_texts(masked, tags):
    """`<a>`가 감싼 글자. 자리표 순서만 지키면 링크가 다른 말에 가서 붙을 수 있다."""
    out = []
    for i, tag in enumerate(tags):
        if not tag.startswith('<a'):
            continue
        j = next((k for k in range(i + 1, len(tags)) if tags[k] == '</a>'), None)
        if j is None:
            continue
        m = re.search(MARK.format(i) + '(.*?)' + MARK.format(j), masked, re.S)
        if m:
            out.append([i, j, ' '.join(m.group(1).split())])
    return out


def _numbers(text):
    return Counter(_NUM_RE.findall(_MARK_RE.sub('', _TAG_RE.sub('', text))))


def _plain(text):
    return re.sub(r'\s+', ' ', _MARK_RE.sub(' ', _TAG_RE.sub(' ', text))).strip()


# 발행 뒤 codex 문체 수정(`reinsert_partial`)에만 더하는 검사. 사람이 보지 않는 자동 경로라
# 개수만 맞추면 「100에서 200으로」→「200에서 100으로」, 「상승할」→「하락할」, 「않았다」를
# 뺀 문장, 「삼성전자」→「현대전자」가 모두 통과했다(2026-09-30 codex 구현 검토에서 재현).
# 걸린 문단은 원문으로 남을 뿐이라 엄격한 쪽이 안전하다.
_UP = ('상승', '오르', '올랐', '올라', '오른', '올린', '올려', '반등', '급등', '강세', '웃돌',
       '웃돈', '상회', '증가', '늘었', '늘어', '늘린', '늘려', '인상', '순매수', '매수', '높아',
       '높였', '높인', '플러스')
_DOWN = ('하락', '내리', '내렸', '내려', '내린', '떨어', '급락', '약세', '밑돌', '밑돈', '하회',
         '감소', '줄었', '줄어', '줄인', '줄여', '인하', '순매도', '매도', '낮아', '낮췄', '낮춘',
         '마이너스')
_POLAR = sorted(_UP + _DOWN, key=len, reverse=True)
# 독립된 「안」(안 된다·안 올랐다)은 낱말 경계로만 센다 — 「안정」「안에서」는 부정이 아니다.
_NEG_RE = re.compile(r'않|아니|못|없|(?<![가-힣])안(?=\s)')


def _number_order(text):
    return _NUM_RE.findall(_MARK_RE.sub('', _TAG_RE.sub('', text)))


def _stream(text, names):
    """이름·영문 이름·방향어를 나온 순서대로 — 개수가 같아도 짝(누가 올랐나)이 바뀌면 달라진다."""
    alts = [re.escape(n) for n in sorted(names, key=len, reverse=True)]
    parts = ['(?P<n>%s)' % '|'.join(alts)] if alts else []
    parts += [r'(?P<l>[A-Za-z][A-Za-z&.\-]{1,})', '(?P<p>%s)' % '|'.join(_POLAR)]
    pattern = '|'.join(parts)
    out = []
    for m in re.finditer(pattern, _plain(text)):
        if m.group('p'):
            out.append('+' if m.group('p') in _UP else '-')
        else:
            out.append(m.group(0))
    return out


def _negations(text):
    return Counter(m.group(0) for m in _NEG_RE.finditer(_plain(text)))


def _check_strict(pid, before, after, names):
    """문단 안의 관계 — 수치의 순서, 이름·방향어의 순서, 부정어."""
    if _number_order(before) != _number_order(after):
        raise ProseSwapError('%s 의 수치 순서가 달라졌다' % pid)
    was, now = _stream(before, names), _stream(after, names)
    if was != now:
        raise ProseSwapError('%s 의 이름·방향(오름·내림) 순서가 달라졌다 — %s → %s'
                             % (pid, ' '.join(was)[:120] or '없음', ' '.join(now)[:120] or '없음'))
    want, got = _negations(before), _negations(after)
    if want != got:
        raise ProseSwapError('%s 의 부정어가 달라졌다 — 사라진 것 %s, 생긴 것 %s'
                             % (pid, sorted(want - got), sorted(got - want)))


def _similarity(a, b):
    """문자 단위 일치 비율.

    3-gram Jaccard도 써 봤지만 짧은 문단에서 너무 예민했다 — 45자 문단에 주어
    「지수는」을 되살리고 문장을 나눈 것만으로 0.60까지 떨어진다(같은 편집이
    200자 문단에서는 0.90). SequenceMatcher는 삽입에 관대해서 문단 길이에
    덜 휘둘린다 (2026-08-25 실측).
    """
    return difflib.SequenceMatcher(None, _plain(a), _plain(b)).ratio()


def _check_bound(pid, body, known):
    """이름표는 자리만 정한다. 몸통이 제 자리 것인지는 여기서 본다.

    윤문은 말투를 바꾸는 일이라 원문과 많이 닮은 채로 돌아온다. 반대로 두 문단이
    자리를 바꾸면 남의 원문과 더 닮는다 — 그것 하나로 갈린다. 숫자가 없는 문단끼리의
    맞바꿈은 수치 검사로는 절대 못 잡는다(2026-08-25 codex 검토에서 실제로 뚫렸다).
    """
    mine = _similarity(body, known[pid]['inner'])
    ratio = len(_plain(body)) / float(max(len(_plain(known[pid]['inner'])), 1))
    if not LEN_RATIO[0] <= ratio <= LEN_RATIO[1]:
        raise ProseSwapError('%s 의 길이가 %.1f배로 변했다 — 윤문이 아니라 다시 쓴 것이다' % (pid, ratio))
    rivals = [(_similarity(body, rec['inner']), other)
              for other, rec in known.items() if other != pid]
    if rivals:
        best, who = max(rivals)
        if best >= mine:
            raise ProseSwapError('%s 자리에 다른 문단(%s)에 더 가까운 글이 왔다 '
                                 '— 제 원문과 %.2f, %s와 %.2f' % (pid, who, mine, who, best))
    if mine < SIM_FLOOR:
        raise ProseSwapError('%s 를 문법·말투 이상으로 바꿨다 (닮은 정도 %.2f, 하한 %.2f) '
                             '— 이 단계는 다시 쓰는 자리가 아니다' % (pid, mine, SIM_FLOOR))


def fingerprint(html):
    return hashlib.sha256(html.encode('utf-8')).hexdigest()[:16]


def extract(html):
    """뽑는다 → (넘길 텍스트, 사이드카)."""
    items, sidecar = [], {}
    for pid, m in _eligible(html):
        masked, tags = _mask(m.group(2))
        text = re.sub(r'\s+', ' ', masked).strip()
        items.append('[[%s]]\n%s' % (pid, text))
        sidecar[pid] = {'inner': m.group(2), 'tags': tags,
                        'numbers': dict(_numbers(masked)),
                        'controlled': dict(_controlled(masked)),
                        'latin': dict(_latin(masked)),
                        'anchors': _anchor_texts(masked, tags)}
    return '\n\n'.join(items) + '\n', {'fingerprint': fingerprint(html), 'items': sidecar}


def parse_payload(text):
    """윤문된 텍스트를 이름 → 문단으로. 마크다운이 섞여 오면 거부한다."""
    out, pid, buf = {}, None, []

    def flush():
        if pid is None:
            return
        body = ' '.join(' '.join(buf).split())
        if not body:
            raise ProseSwapError('%s 문단이 비어서 돌아왔다' % pid)
        if pid in out:
            raise ProseSwapError('%s 이름이 두 번 나왔다' % pid)
        out[pid] = body

    for line in text.splitlines():
        m = _ID_RE.match(line.strip())
        if m:
            flush()
            pid, buf = m.group(1), []
            continue
        if pid is None:
            if line.strip() and not line.strip().startswith('<!--'):
                raise ProseSwapError('이름 없는 텍스트가 앞에 붙어 있다: %r' % line.strip()[:40])
            continue
        if line.strip().startswith('<!-- HUMANIZE-SUMMARY'):
            break
        if _MD_LINE_RE.match(line) or _MD_INLINE_RE.search(line):
            raise ProseSwapError('%s 에 마크다운 문법이 섞였다: %r' % (pid, line.strip()[:40]))
        if '<' in line or '>' in line:
            raise ProseSwapError('%s 에 HTML이 섞였다: %r' % (pid, line.strip()[:40]))
        buf.append(line)
    flush()
    if not out:
        raise ProseSwapError('되꽂을 문단이 하나도 없다')
    return out


def _check_one(pid, body, known):
    """한 문단의 검사 전부 — 통과하면 되꽂을 inner, 아니면 ProseSwapError."""
    rec = known[pid]
    if _numbers(body) != Counter(rec['numbers']):
        before, after = Counter(rec['numbers']), _numbers(body)
        raise ProseSwapError('%s 의 수치가 달라졌다 — 사라진 것 %s, 생긴 것 %s'
                             % (pid, sorted(before - after), sorted(after - before)))
    for kind, fn, label in (('controlled', _controlled, '판단 어휘'),
                            ('latin', _latin, '영문 이름·티커')):
        want = Counter(rec.get(kind, {}))
        got = fn(body)
        if want != got:
            raise ProseSwapError('%s 의 %s가 달라졌다 — 사라진 것 %s, 생긴 것 %s'
                                 % (pid, label, sorted(want - got), sorted(got - want)))
    for i, j, text in rec.get('anchors', []):
        m = re.search(MARK.format(i) + '(.*?)' + MARK.format(j), body, re.S)
        if not m or ' '.join(m.group(1).split()) != text:
            raise ProseSwapError('%s 의 링크가 감싼 말이 달라졌다 — 원래 %r' % (pid, text))
    _check_bound(pid, body, known)
    return _unmask(body, rec['tags'])


def reinsert(html, payload_text, sidecar):
    """이름으로 되꽂는다. 하나라도 어긋나면 아무것도 쓰지 않고 예외."""
    if sidecar.get('fingerprint') != fingerprint(html):
        raise ProseSwapError('사이드카가 이 HTML에서 뽑힌 것이 아니다')
    rewritten = parse_payload(payload_text)
    known = sidecar['items']
    unknown = sorted(set(rewritten) - set(known))
    if unknown:
        raise ProseSwapError('모르는 이름이 왔다: %s' % ', '.join(unknown))
    missing = sorted(set(known) - set(rewritten))
    if missing:
        raise ProseSwapError('돌아오지 않은 문단이 있다: %s' % ', '.join(missing))

    new_inner = {pid: _check_one(pid, body, known) for pid, body in rewritten.items()}

    return _splice(html, new_inner)


def _splice(html, new_inner):
    """이름 → 새 inner. 없는 이름은 원문 그대로 둔다."""
    out, last = [], 0
    for pid, m in _eligible(html):
        out.append(html[last:m.start(2)])
        out.append(new_inner.get(pid, m.group(2)))
        last = m.end(2)
    out.append(html[last:])
    return ''.join(out)


def _split_payload(text):
    """관대한 파서 → (이름 → 문단, [(이름, 이유)]). 문제가 있는 블록만 뺀다."""
    blocks, order, pid, buf = {}, [], None, []
    for line in text.splitlines():
        m = _ID_RE.match(line.strip())
        if m:
            if pid is not None:
                blocks.setdefault(pid, []).append(buf)
            pid, buf = m.group(1), []
            order.append(pid)
            continue
        if line.strip().startswith('<!-- HUMANIZE-SUMMARY'):
            break
        if pid is not None:
            buf.append(line)
    if pid is not None:
        blocks.setdefault(pid, []).append(buf)
    out, rejected = {}, []
    for pid in dict.fromkeys(order):
        bufs = blocks[pid]
        if len(bufs) > 1:
            rejected.append((pid, '이름이 두 번 나왔다'))
            continue
        lines = bufs[0]
        bad = next((l for l in lines if _MD_LINE_RE.match(l) or _MD_INLINE_RE.search(l)
                    or '<' in l or '>' in l), None)
        if bad is not None:
            rejected.append((pid, '마크다운·HTML 이 섞였다: %r' % bad.strip()[:40]))
            continue
        body = ' '.join(' '.join(lines).split())
        if not body:
            rejected.append((pid, '문단이 비어서 돌아왔다'))
            continue
        out[pid] = body
    return out, rejected


def reinsert_partial(html, payload_text, sidecar, names=()):
    """문단 단위로 되꽂는다 → (새 HTML, [(이름, 이유)]).

    `reinsert` 의 검사에 `_check_strict`(수치 순서·방향·부정어·`names`)를 더한다. 그리고
    **걸린 문단만 원문으로 두고** 나머지를 반영한다. 발행 뒤 codex 문체 수정에서 한 문단
    (닮은 정도 0.79)이 수십 문단의 수정을 통째로 버리게 했다(2026-09-27 실측, 사용자 지시로
    전체 거부를 없앴다). 빠진 문단은 원문 그대로다.

    기대값은 넘겨받은 `sidecar` 가 아니라 **이 HTML 에서 새로 뽑는다** — 사이드카는 codex 가
    쓸 수 있는 작업 폴더에 있었다. 넘겨받은 것은 그 판에서 뽑혔는지(지문)만 본다 — 아니면
    이름이 엉뚱한 자리를 가리키므로 통째로 거부한다.
    """
    if sidecar.get('fingerprint') != fingerprint(html):
        raise ProseSwapError('사이드카가 이 HTML에서 뽑힌 것이 아니다')
    original_text, fresh = extract(html)
    known = fresh['items']
    original, _ = _split_payload(original_text)
    rewritten, rejected = _split_payload(payload_text)
    new_inner = {}
    for pid, body in rewritten.items():
        if pid not in known:
            rejected.append((pid, '모르는 이름'))
            continue
        if pid not in original:
            rejected.append((pid, '원문 문단을 대조할 수 없다'))
            continue
        try:
            _check_strict(pid, original[pid], body, names)
            new_inner[pid] = _check_one(pid, body, known)
        except ProseSwapError as exc:
            rejected.append((pid, str(exc)))
    return _splice(html, new_inner), rejected
