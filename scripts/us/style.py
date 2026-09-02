"""말투가 기관 보고서로 굳었는지 기계적으로 재는 검사.

「말하듯이 쓴다」는 기준(`.claude/agents/brief-report-writer.md`)은 대부분 사람이 읽어야
아는 것이지만, 굳은 말투는 몇 가지 **셀 수 있는 자국**을 남긴다. 2026-08-20·21 발행본
415문장을 실측했을 때 나온 것들이 그대로 여기 임계가 됐다 — 개조식 라벨 28회, 비인칭
피동 20회, `~에 따른` 8회, 명사형 종결 7회, 문두 `다만` 14회, `-다` 종결 89.9%.

임계는 넉넉하다. 한두 번은 문체가 아니라 그 문장에 맞는 표현일 수 있고, 매일 걸리는
검사는 곧 무시당한다. 잡으려는 것은 **반복**이다.

Pure — HTML 문자열을 받아 findings를 돌려준다.
"""

import re

_SCRIPT = re.compile(r'<(script|style)\b.*?</\1>', re.S | re.I)
_TABLE = re.compile(r'<table\b.*?</table>', re.S | re.I)
_HEADING = re.compile(r'<h[1-6]\b.*?</h[1-6]>', re.S | re.I)
_PARA = re.compile(r'<p\b[^>]*>(.*?)</p>', re.S | re.I)
_TAG = re.compile(r'<[^>]+>')
_STRONG_LEAD = re.compile(r'^\s*<strong[^>]*>(.*?)</strong>', re.S | re.I)
_SENT = re.compile(r'[^.!?]*[.!?]|[^.!?]+$')

# 한 문장이 끝났다고 볼 종결. 「2,700.15로」의 소수점과 구분하려면 종결어미가 필요하다.
_ENDING = re.compile(r'(다|요|까|죠|오|네|군요|습니다|입니다)[.!?]\s*$')

IMPERSONAL = ('읽힌다', '꼽힌다', '판정된다', '판정됐다', '해석된다', '풀이된다',
              '거론된다', '관찰된다', '분석된다', '평가된다', '전망된다', '관측된다')
TRANSLATIONESE = ('에 따른', '에 기인한', '를 통한', '을 통한', '에 의한')
NOUN_ENDINGS = ('상태다', '모양새다', '국면이다', '상황이다', '모습이다', '분위기다')

# ── 쉬운 말 ────────────────────────────────────────────────────────────────
#
# 2026-08-26 사용자 지시: 「브레드스 확산 트리거같은 뭔 소린지 모르는 용어 사용은
# 자제하고 최대한 풀어서 작성해」.
# 2026-08-28 사용자 지시로 기준을 좁혔다: 「업계용어나 경제뉴스에서 자주 나오는
# 표현은 그냥 그대로 쓰는 걸로 하자」. 걸러야 할 것은 **외래어**가 아니라
# **독자가 처음 보는 말**이다. 경제 뉴스를 읽는 사람이 이미 수없이 본 말까지
# 풀어 쓰면 글이 유치해지고, 매일 걸리는 검사는 곧 무시당한다.
#
# 그래서 세 갈래다.
#
# COMMON — 시장 기사에 늘 나오는 말. 아무 제약 없이 그대로 쓴다. 검사도 안 하고
#          겹침(JARGON_STACK)에도 안 센다. 판정 기준은 «경제 뉴스를 꾸준히 읽는
#          사람이 여러 번 마주쳤을 말인가»이지 «한국어 대응이 있는가»가 아니다.
# PLAIN  — 그 기준을 통과 못 하는 음차. 우리 안에서만 쓰던 말이거나 시장 기사에
#          거의 안 나오는 말이라, 한 번만 나와도 잡고 바꿔 쓸 말을 찍어 준다.
# GLOSS  — 뉴스에도 잘 안 나오면서 옮기면 길어지는 진짜 전문어. 쓰는 것은 되지만
#          **첫 등장에서 한 번은** 풀어야 한다. 괄호든 「즉/다시 말해」든 형식은
#          안 따진다.
#
# 낱말 하나하나보다 **한 문장에 겹쳐 쌓이는 것**이 읽기를 막는다 — 사용자가 든
# 「브레드스 확산 트리거」가 정확히 그 형태다. JARGON_STACK이 그것을 본다.

# 시장 기사에 늘 나오는 말. 검사 대상이 아니다.
COMMON = (
    '컨센서스', '밸류에이션', '가이던스', '멀티플', '모멘텀', '베타', '캐리',
    '리스크온', '리스크오프', '오버웨이트', '언더웨이트', '아웃퍼폼', '언더퍼폼',
    '익스포저', '포지셔닝', '디커플링', '스티프닝', '플래트닝', '숏커버',
    '디레버리징', '리레이팅', '디레이팅', '오버슈팅', '기대인플레',
    '디스인플레이션', '트리거', '스탠스',
)

PLAIN = {
    '브레드스': '상승 종목 비율', '브레스': '상승 종목 비율', 'breadth': '상승 종목 비율',
    '인버전': '장단기 금리 역전', '디스인버전': '금리 역전 해소',
    '컨빅션': '확신', '프록시': '대리 지표',
    '바텀아웃': '바닥 확인', '캐치업': '뒤따라 오름',
    '롤다운': '만기가 짧아지며 붙는 이익',
    # 음차가 아닌데 여기 있는 유일한 말. 통계 용어라 뜻이 정확하지만, 「96.4 백분위」를
    # 읽고 그림이 그려지는 독자는 이 리포트가 상정한 독자가 아니다(2026-09-02 사용자
    # 지적 — 「그렇게 쓰면 아무도 못 알아들을 것 같다」). 데이터가 `plain` 으로 옮긴
    # 말을 내려보내므로 writer 가 옮길 일도 없다.
    '백분위': '이보다 높았던 날은 며칠뿐',
}
# 뜻을 옮기면 문장이 무거워지는 것들. 첫 등장에서 한 번 풀면 그 뒤로는 그냥 쓴다.
GLOSS = ('기간프리미엄', '확산지수', '레짐')
# 풀이는 **그 말이 처음 나온 문장 안에서, 그 말 바로 뒤**에 있어야 한다.
# 문단을 통째로 이어 붙여 훑으면 남의 풀이가 내 풀이로 셈된다(codex 검토 2026-08-26).
GLOSS_WINDOW = 60
# 풀이는 낱말 **바로 뒤**에서 시작해야 한다(`^` 고정). 멀리 떨어진 남의 괄호가
# 이 말의 풀이로 셈되던 오탐을 막는다 — 「레짐은 유지되나 삼성전자(005930)가…」.
# 낱말과 풀이 사이에 조사 한 덩이 정도는 허용한다.
_GLOSS_CUE = re.compile(
    r'^[가-힣]{0,3}\s*(?:'
    r'\(([^)]{4,})\)|,?\s*(?:즉|다시 말해|말하자면)|'
    r'(?:은|는|이|가)\s*(?:뜻|말)|(?:라는|이라는)\s*(?:뜻|말|의미)'
    r')'
)
# 괄호 안이 수치·티커면 풀이가 아니다 — 「기간프리미엄(3.2%)」은 아무것도 안 풀었다.
_HANGUL = re.compile(r'[가-힣]')
MAX_JARGON_PER_SENTENCE = 1

# 뒤에 뭐가 붙든 대개는 여전히 그 말이다 — 「브레드스발」·「프록시성」은 전부
# 잡아야 맞다. 조사 목록을 허용 집합으로 두는 방식은 이것들을 놓쳤다(codex 검토).
# 그래서 **뒤는 열어 두고**, 그 말이 아닌 합성어만 예외로 적는다. 짧고 눈으로
# 검토되는 목록이라 새 오탐이 나오면 여기 한 줄 더한다.
# 2026-08-28: 베타 합성어(베타테스트 등)는 「베타」가 COMMON으로 가면서 필요 없어
# 졌고, 대신 남은 말 중 「프록시서버」가 실제 오탐이라 그쪽으로 갈았다.
NOT_JARGON = ('프록시서버', '프록시 서버')


def _term_pattern(term):
    """낱말 하나를 찾는 정규식. 앞에 한글이 붙으면 다른 말로 본다.

    앞을 막는 이유: 「프레짐」의 「레짐」처럼 남의 낱말 꼬리를 잡지 않으려는 것.
    뒤를 여는 이유: 한국어는 조사·접미사가 그냥 붙어서, 뒤까지 막으면
    「브레드스가」·「밸류에이션발」이 전부 빠져나간다.
    """
    if _HANGUL.search(term):
        return re.compile(r'(?<![가-힣])%s' % re.escape(term))
    return re.compile(r'(?<![A-Za-z])%s(?![A-Za-z])' % re.escape(term), re.I)


def _blank_exceptions(text):
    """그 말이 아닌 합성어를 같은 길이 공백으로 덮는다. 오프셋은 그대로."""
    for word in NOT_JARGON:
        text = text.replace(word, ' ' * len(word))
    return text


_TERM_RE = {}


def _term_re(term):
    if term not in _TERM_RE:
        _TERM_RE[term] = _term_pattern(term)
    return _TERM_RE[term]


def _spans(text, terms):
    """겹치지 않는 매치 목록 [(시작, 끝, 낱말)]. 긴 낱말이 이긴다.

    「디스인버전」을 「인버전」까지 둘로 세면 한 낱말이 겹침 위반을 만든다.
    """
    hits = []
    text = _blank_exceptions(text)
    for term in sorted(terms, key=len, reverse=True):
        for m in _term_re(term).finditer(text):
            if any(m.start() < end and start < m.end() for start, end, _ in hits):
                continue
            hits.append((m.start(), m.end(), term))
    return sorted(hits)


def _count(text, term):
    return len(_term_re(term).findall(_blank_exceptions(text)))

MAX_IMPERSONAL = 2
MAX_TRANSLATIONESE = 3
MAX_NOMINAL_LABELS = 2
MAX_NOUN_ENDINGS = 2
MAX_SAME_OPENER = 4
MAX_SAME_ENDING_RUN = 3


# 클래스는 **토큰 단위**로 본다. 부분 문자열로 보면 `class="my-note-widget"`이
# 각주로 빠지고, 진짜 `class="src"`는 안 빠진다(codex 검토 2026-08-26).
# `fed-trans` 는 연준 발언의 번역이다. 충실도로 판단할 글이지 문체로 판단할 글이
# 아니다 — 「말하듯이」 고치는 순간 의장이 하지 않은 말투가 된다.
_META_CLASSES = frozenset((
    'caption', 'sub', 'muted', 'footer-note', 'source', 'sources', 'src',
    'note', 'disclaimer', 'fed-trans',
))
_CLASS_ATTR = re.compile(r'\bclass\s*=\s*["\']([^"\']*)["\']', re.I)


def _is_meta_paragraph(attrs):
    m = _CLASS_ATTR.search(attrs)
    if not m:
        return False
    return any(tok.lower() in _META_CLASSES for tok in m.group(1).split())
_PARA_WITH_ATTRS = re.compile(r'<p\b([^>]*)>(.*?)</p>', re.S | re.I)


def _prose_html(html):
    """산문 문단만. 표·제목·캡션은 뺀다.

    표와 제목은 라벨이 짧아 개조식으로 오탐되고, 캡션·각주는 좁은 칸이라
    줄임말이 오히려 낫다 — 쉬운 말 규칙의 대상이 아니다.
    """
    body = html[html.index('<body'):] if '<body' in html else html
    body = _SCRIPT.sub(' ', body)
    body = _TABLE.sub(' ', body)
    body = _HEADING.sub(' ', body)
    return [inner for attrs, inner in _PARA_WITH_ATTRS.findall(body)
            if not _is_meta_paragraph(attrs)]


def _text(fragment):
    return re.sub(r'\s+', ' ', _TAG.sub(' ', fragment)).strip()


def sentences(text):
    """마침표로 자르되 소수점에서는 자르지 않는다."""
    out, buf = [], ''
    for chunk in _SENT.findall(text):
        buf += chunk
        if _ENDING.search(buf) or not chunk.strip():
            if buf.strip():
                out.append(buf.strip())
            buf = ''
    if buf.strip():
        out.append(buf.strip())
    return out


def _subject_josa(word):
    """받침 있으면 「이」, 없으면 「가」. 「멀티플가」 같은 자국을 남기지 않는다."""
    if not word:
        return '이'
    last = word[-1]
    if '가' <= last <= '힣':
        return '이' if (ord(last) - 0xAC00) % 28 else '가'
    return '이'


def _finding(key, count, message):
    return {'key': key, 'count': count, 'message': message}


def findings(html):
    paragraphs = _prose_html(html)
    texts = [_text(p) for p in paragraphs]
    whole = ' '.join(texts)
    out = []

    hits = sum(whole.count(w) for w in IMPERSONAL)
    if hits > MAX_IMPERSONAL:
        out.append(_finding('impersonal', hits,
                            f'비인칭 피동 종결이 {hits}회다({MAX_IMPERSONAL}회까지). '
                            f'견해가 있으면 「~라고 볼 수 있습니다」나 능동 인과로 쓴다'))

    hits = sum(whole.count(w) for w in TRANSLATIONESE)
    if hits > MAX_TRANSLATIONESE:
        out.append(_finding('translationese', hits,
                            f'번역투 연결(~에 따른/~를 통한)이 {hits}회다'
                            f'({MAX_TRANSLATIONESE}회까지). 「~해서」·「~이라」로 푼다'))

    labels = 0
    for para in paragraphs:
        lead = _STRONG_LEAD.match(para.strip())
        if lead and not _ENDING.search(_text(lead.group(1)) + '.'):
            labels += 1
    if labels > MAX_NOMINAL_LABELS:
        out.append(_finding('nominal_label', labels,
                            f'서술어 없는 명사형 머리말이 {labels}개다'
                            f'({MAX_NOMINAL_LABELS}개까지). 머리말도 문장으로 쓴다'))

    hits = sum(whole.count(w) for w in NOUN_ENDINGS)
    if hits > MAX_NOUN_ENDINGS:
        out.append(_finding('noun_ending', hits,
                            f'「~한 상태다/모양새다」식 명사형 종결이 {hits}회다'
                            f'({MAX_NOUN_ENDINGS}회까지). 동사로 끝낸다'))

    openers = {}
    for text in texts:
        first = text.split()[0] if text.split() else ''
        if first:
            openers[first] = openers.get(first, 0) + 1
    for word, count in openers.items():
        if count > MAX_SAME_OPENER:
            out.append(_finding('opener', count,
                                f'문단이 「{word}」로 시작한 것이 {count}번이다'
                                f'({MAX_SAME_OPENER}번까지)'))

    worst = 0
    for text in texts:
        run = 0
        for sentence in sentences(text):
            tail = sentence.rstrip()[-2:]
            if tail.startswith('다') or tail == '다.':
                run += 1
                worst = max(worst, run)
            else:
                run = 0
    if worst > MAX_SAME_ENDING_RUN:
        out.append(_finding('monotone', worst,
                            f'한 문단에서 「~다」로 끝나는 문장이 {worst}개 이어졌다'
                            f'({MAX_SAME_ENDING_RUN}개까지). 종결을 섞는다'))

    out += _plain_language(texts, whole)
    return out


def _plain_language(texts, whole):
    """쉬운 말 검사 — 음차어, 첫 등장 풀이, 한 문장 안 겹침."""
    out = []
    prose_sentences = [sent for text in texts for sent in sentences(text)]

    used = [(w, _count(whole, w)) for w in PLAIN]
    used = [(w, n) for w, n in used if n]
    if used:
        used.sort(key=lambda kv: -kv[1])
        shown = ', '.join('%s(%d회) → 「%s」' % (w, n, PLAIN[w]) for w, n in used[:4])
        more = '' if len(used) <= 4 else ' 외 %d개' % (len(used) - 4)
        out.append(_finding('jargon', sum(n for _, n in used),
                            '풀어 쓸 수 있는데 음차한 말이 있다 — %s%s. '
                            '한국어로 바꿔 쓴다' % (shown, more)))

    bare = [term for term in GLOSS
            if _first_use_unglossed(prose_sentences, term)]
    if bare:
        out.append(_finding('jargon_gloss', len(bare),
                            '전문어 %s%s 처음 나올 때 풀이가 없다. '
                            '괄호나 「즉 ~」로 한 번은 뜻을 밝힌다'
                            % ('·'.join(bare), _subject_josa(bare[-1]))))

    all_terms = list(PLAIN) + list(GLOSS)
    stacked = []
    for sentence in prose_sentences:
        hits = _spans(sentence, all_terms)
        # 같은 말을 두 번 쓴 것은 겹침이 아니다. 읽기를 막는 것은 **서로 다른**
        # 낯선 말이 쌓이는 것이다 — 「브레드스 확산 트리거」가 그 형태다.
        distinct = list(dict.fromkeys(term for _, _, term in hits))
        if len(distinct) > MAX_JARGON_PER_SENTENCE:
            stacked.append((sentence, distinct))
    if stacked:
        sentence, terms = stacked[0]
        out.append(_finding('jargon_stack', len(stacked),
                            '한 문장에 낯선 말이 겹친 곳이 %d군데다 — 「%s」에 %s. '
                            '문장을 나누거나 하나는 풀어 쓴다'
                            % (len(stacked), sentence[:40], '·'.join(terms))))
    return out


def _first_use_unglossed(prose_sentences, term):
    """그 말이 처음 나온 문장 안에서, 그 말 바로 뒤에 풀이가 있는가.

    문장 밖을 보지 않는 것이 핵심이다 — 문단을 이어 붙여 훑으면 옆 낱말의
    풀이가 이 낱말의 풀이로 셈된다(codex 검토 2026-08-26).
    """
    pattern = _term_re(term)
    for raw in prose_sentences:
        sentence = _blank_exceptions(raw)
        match = pattern.search(sentence)
        if not match:
            continue
        window = sentence[match.end():match.end() + GLOSS_WINDOW]
        cue = _GLOSS_CUE.search(window)
        if not cue:
            return True
        inner = cue.group(1)
        # 괄호 풀이는 우리말 설명일 때만 인정한다 — 수치·티커는 푼 것이 아니다.
        if inner is not None and not _HANGUL.search(inner):
            return True
        return False
    return False
