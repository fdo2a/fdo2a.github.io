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


def _skip_spans(html):
    """뽑지 않을 구역 — 표 안, 에디터 노트 안."""
    spans = []
    for m in _BLOCK_RE.finditer(html):
        if m.group(1) == 'table' or 'data-editor-note' in m.group(0)[:400]:
            spans.append((m.start(), m.end()))
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

    new_inner = {}
    for pid, body in rewritten.items():
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
        new_inner[pid] = _unmask(body, rec['tags'])

    out, last = [], 0
    for pid, m in _eligible(html):
        out.append(html[last:m.start(2)])
        out.append(new_inner[pid])
        last = m.end(2)
    out.append(html[last:])
    return ''.join(out)
