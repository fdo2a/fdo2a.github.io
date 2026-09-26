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


# 뉴스 블록의 요약 문단(`expand_news_items.py` 가 채운 수집 요약). 문장을 쓴 것은 수집 단계의
# 요약기라 작성자가 어미 반복을 고칠 수 없다. 원문 그대로인지는 뉴스 게이트가 본다(2026-09-26).
_SUMMARY_ATTR = re.compile(r'\bdata-summary\s*=')


def _is_meta_paragraph(attrs):
    m = _CLASS_ATTR.search(attrs)
    if not m:
        return False
    return any(tok.lower() in _META_CLASSES for tok in m.group(1).split())
_PARA_WITH_ATTRS = re.compile(r'<p\b([^>]*)>(.*?)</p>', re.S | re.I)


# 검사 밖에 두는 두 구간. 연구 판단 복기는 원장에서 생성해 바이트로 대조하는 불변 구간이라
# 작성자가 말투를 고칠 수 없고, 근거 블록은 계산 재현용이라 코드·파일명이 제자리다.
# 요소가 **닫히는 곳까지** 지운다 — 다음 표식까지로 자르면 남의 글을 빌린다.
_RESEARCH_SUMMARY = re.compile(
    r'(<section\b[^>]*\bdata-research-summary\b[^>]*>)(.*?)(</section\s*>)', re.S | re.I)
# 구간을 통째로 빼면 가짜 `data-research-summary` 안에 산문을 숨길 수 있다. 그래서
# `research_gate.render_summary` 가 **만드는 것만** 걷어 낸다 — 기대값을 재현하는 쪽이다.
_GENERATED_SUMMARY_PARTS = (
    re.compile(r'<h2>연구 판단 복기</h2>'),
    re.compile(r'<p>검토 대상 \d+건 중 사전 기록 \d+건, 사후 기록 \d+건입니다\. '
               r'진행 중 \d+건이며 확인 기한이 지난 가설은 \d+건입니다\.</p>'),
    re.compile(r'<p>아직 평가할 가설 기록이 없습니다\.</p>'),
    re.compile(r'<div class="tbl-scroll"><table><thead><tr><th>가설</th>.*?</table></div>', re.S),
)
_PROVENANCE = re.compile(
    r'<details\b[^>]*\bdata-provenance\b[^>]*>(.*?)</details\s*>', re.S | re.I)


def _body(html):
    """`<body>` 안에서 스크립트·스타일·불변 생성 구간·근거 블록을 뺀 것."""
    m = re.search(r'<body\b', html, re.I)
    body = html[m.start():] if m else html
    body = _SCRIPT.sub(' ', body)
    body = _RESEARCH_SUMMARY.sub(_strip_generated_summary, body)
    return _PROVENANCE.sub(' ', body)


def _strip_generated_summary(m):
    inner = m.group(2)
    for part in _GENERATED_SUMMARY_PARTS:
        inner = part.sub(' ', inner, count=1)
    return m.group(1) + inner + m.group(3)


def _prose_html(html):
    """산문 문단만. 표·제목·캡션은 뺀다.

    표와 제목은 라벨이 짧아 개조식으로 오탐되고, 캡션·각주는 좁은 칸이라
    줄임말이 오히려 낫다 — 쉬운 말 규칙의 대상이 아니다.
    """
    body = _body(html)
    body = _TABLE.sub(' ', body)
    body = _HEADING.sub(' ', body)
    return [inner for attrs, inner in _PARA_WITH_ATTRS.findall(body)
            if not _is_meta_paragraph(attrs) and not _SUMMARY_ATTR.search(attrs)]


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


def _finding(key, count, message, level='fail'):
    """`level` 은 'fail'(발행을 막는다) 또는 'warn'(보여 주기만 한다)."""
    return {'key': key, 'count': count, 'message': message, 'level': level}


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

    desk = is_desk_register(html)
    worst, tail_word = (_same_ending_run(texts) if desk else (_da_run(texts), '~다'))
    if worst > MAX_SAME_ENDING_RUN:
        out.append(_finding('monotone', worst,
                            f'한 문단에서 「{tail_word}」로 끝나는 문장이 {worst}개 이어졌다'
                            f'({MAX_SAME_ENDING_RUN}개까지). '
                            + ('동사를 바꾸거나 문장을 합친다 — 어미는 -다 그대로 둔다'
                               if desk else '종결을 섞는다')))

    out += _plain_language(texts, whole, gloss=not desk)
    if desk:
        out += _desk_findings(html, texts)
    return out


def _da_run(texts):
    """선언 없는 문서의 옛 규칙 — 「~다」 종결이 몇 개 이어졌나."""
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
    return worst


def _same_ending_run(texts):
    """-다 로 고정한 문서의 단조 — **같은 두 글자 종결**(했다·했다…)이 몇 개 이어졌나.

    「~다 4연속 금지」를 -다 문서에 그대로 걸면 연속을 끊을 방법이 수사의문·-습니다·
    「~죠」밖에 없다. 2026-09-23 KR 발행본의 「나머지 업종은 어땠을까?」가 그 적응이었다.
    """
    worst, word = 0, ''
    for text in texts:
        run, prev = 0, None
        for sentence in sentences(text):
            core = sentence.rstrip().rstrip('.!?')
            tail = core[-2:] if len(core) >= 2 else core
            run = run + 1 if tail == prev else 1
            prev = tail
            if run > worst:
                worst, word = run, tail
    return worst, word


def _plain_language(texts, whole, gloss=True):
    """쉬운 말 검사 — 음차어, 첫 등장 풀이, 한 문장 안 겹침.

    `gloss=False` 는 PM 이 읽는 데스크 문서다 — 기간프리미엄·레짐을 풀어 주면 오히려
    교과서가 된다(2026-09-23 US 「기간프리미엄(만기가 길수록 더 얹어 받는 값)」).
    """
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
            if gloss and _first_use_unglossed(prose_sentences, term)]
    if bare:
        out.append(_finding('jargon_gloss', len(bare),
                            '전문어 %s%s 처음 나올 때 풀이가 없다. '
                            '괄호나 「즉 ~」로 한 번은 뜻을 밝힌다'
                            % ('·'.join(bare), _subject_josa(bare[-1]))))

    all_terms = list(PLAIN) + (list(GLOSS) if gloss else [])
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


# ── 데스크 문체 (`<body data-register="da">`) ─────────────────────────────────
#
# 2026-09-24 사용자 지시 「US독자는 PM으로 통일해. 어미는 다로 고정하자」. 독자가 운용자인
# US·KR 일간·주간·월간이 이 선언을 단다(일간은 `post_shell` 이, 주간·월간은 작성자가 달고
# `check_period` 가 확인한다). 선언이 없는 문서 — 중국 학습 리포트와 그 이전 발행본 — 는
# 아래 검사를 받지 않는다. 교정 러너가 옛 발행본에 이 검사를 돌려도 멀쩡한 글을 막지 않는다.
#
# 근거: 9/23 회차 실측(내부 어휘 US 14·KR 6, KR 수사의문 5, US 어미 혼합 56/105) —
# `docs/superpowers/specs/2026-09-24-desk-prose-design.md`.

_BODY_REGISTER = re.compile(r'<body\b[^>]*\bdata-register\s*=\s*["\']da["\']', re.I)

# 합쇼체·해요체 종결. -다 문서에 섞이면 한 글이 두 목소리가 된다.
_POLITE = re.compile(r'(니다|세요|[어아해여]요|죠|지요)[.!?]?$')
# 문장 끝의 닫는 따옴표·괄호. 「…했습니다.」·(…어땠을까?) 도 그 문장의 종결로 본다.
_CLOSERS = '"\'」』)]’”'
# 폭 없는 문자로 「원\u200b장」처럼 낱말을 쪼개면 화면에는 붙어 보이고 검사에서는 갈린다.
_INVISIBLE = re.compile('[\u00ad\u200b-\u200f\u2060\ufeff]')


def _tail(sentence):
    return sentence.strip().rstrip(_CLOSERS).rstrip()
MAX_POLITE = 2
MAX_QUESTIONS = 1

# 독자 문장에 나오면 안 되는 작업 어휘 — 원장·채점·수집·계산 재현은 검토 자료의 말이다.
# 앞 글자가 한글이면 다른 낱말이다(금감원장·볼린저밴드·분위기).
INTERNAL_PATTERNS = (
    (r'(?<![가-힣])원장', '원장'),
    (r'(?<![가-힣])회차', '회차'),
    (r'기계\s*판정', '기계 판정'),
    (r'판정\s*불가', '판정불가'),
    (r'판단\s*불가', '판단 불가'),
    (r'부트스트랩', '부트스트랩'),
    (r'프로스펙티브', '프로스펙티브'),
    (r'관측\s*창', '관측 창'),
    (r'산출물', '산출물'),
    (r'수집\s*(파일|분)', '수집 파일'),
    (r'퍼센타일', '퍼센타일'),
    (r'\d\s*분위(?!기)', 'N분위'),
    (r'(큼|보통|미미)[»」\'"]?\s*밴드', '크기 밴드 이름'),
    (r'python3?\b|print\(', '실행 코드'),
    (r'\b[\w-]+\.(json|py|md)\b', '파일명'),
    (r'(가설|질문)[을를]?\s*등록|등록을\s*보류', '가설 등록'),
)
_INTERNAL_RE = [(re.compile(p, re.I), label) for p, label in INTERNAL_PATTERNS]

# 「국채 급등」은 국채 **가격**이 뛰었다(금리 하락)로 읽힌다. 금리를 말하려면 「금리」를 쓴다.
_BOND_AMBIGUOUS = re.compile(r'국채\s*(급등|급락|폭등|폭락)')

# 근거 블록은 계산을 재현하는 자리다. 줄글을 숨겨 검사를 비껴가는 자리가 되지 않게 묶는다.
MAX_PROVENANCE_BLOCKS = 2
MAX_PROVENANCE_CHARS = 600

# 경고 — 발행은 막지 않는다. 한두 번은 그 문장에 맞는 표현이고, 잡으려는 것은 반복이다.
MAX_EMDASH = 6
HEDGES = ('가를 자료', '가를 근거', '단정하지', '단정할', '판단을 유보', '유보한다',
          '확정하기는 이르', '쪼갤 수 없', '가리지 못', '특정할 수 없', '겹쳐 읽지')
MAX_HEDGES = 6
MAX_SAME_NUMBER = 3
_NUMBER = re.compile(r'(?<![\d.,])(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d+)(?![\d])')


# 판단을 자기 동사로 말했나 — 증권사 리포트 기준(2026-09-24, `STYLE_EXEMPLARS.md` §0). 전략
# 코멘트에 하나도 없으면 판단을 「~로 보인다」로 흐렸거나 한계만 늘어놓은 것이다. 경고만 한다.
_STRATEGY = re.compile(r'<h2\b[^>]*>\s*전략\s*코멘트\s*</h2\s*>(.*?)(?=<h2\b|$)', re.S | re.I)
_JUDGMENT = re.compile(r'(판단한다|판단이다|(?<![켜려])본다|전망한다|예상한다|추정한다|기대한다)')


def is_desk_register(html):
    """`<body data-register="da">` 로 데스크 문체를 선언한 문서인가. `<body>` 태그에서만 읽는다."""
    return bool(_BODY_REGISTER.search(html or ''))


def _desk_findings(html, texts):
    out = []
    prose_sentences = [sent for text in texts for sent in sentences(text)]

    polite = [s for s in prose_sentences if _POLITE.search(_tail(s))]
    if len(polite) > MAX_POLITE:
        out.append(_finding('register', len(polite),
                            f'-다 로 고정한 문서에 -습니다·-죠 종결이 {len(polite)}개 섞였다'
                            f'({MAX_POLITE}개까지) — 예: 「{polite[0][-30:]}」. 뉴스 요약도 어미를 바꿔 싣는다'))

    questions = [s for s in prose_sentences if _tail(s).endswith('?')]
    if len(questions) > MAX_QUESTIONS:
        out.append(_finding('question', len(questions),
                            f'묻고 답하는 문장이 {len(questions)}개다({MAX_QUESTIONS}개까지) — '
                            f'예: 「{questions[0][-30:]}」. 답을 바로 쓴다'))

    body = _body(html)
    visible = _INVISIBLE.sub('', _text(body))
    hits = []
    for pattern, label in _INTERNAL_RE:
        m = pattern.search(visible)
        if m:
            hits.append(f'{label}(「{visible[max(0, m.start() - 8):m.end() + 8]}」)')
    if hits:
        out.append(_finding('internal', len(hits),
                            '독자 문장에 작업 어휘가 있다 — ' + ', '.join(hits[:4])
                            + '. 계산 재현은 <details data-provenance> 로, 원장·채점 절차는 '
                              '검토 자료로 옮기고 본문은 판단만 말한다'))

    m = _BOND_AMBIGUOUS.search(visible)
    if m:
        out.append(_finding('bond_ambiguous', 1,
                            f'「{m.group(0)}」은 국채 가격이 움직였다로 읽힌다 — '
                            f'금리를 말하면 「국채금리 {m.group(1)}」으로 쓴다'))

    raw = re.search(r'<body\b', html, re.I)
    blocks = _PROVENANCE.findall(html[raw.start():] if raw else html)
    sizes = [len(re.sub(r'\s', '', _text(b))) for b in blocks]
    if len(blocks) > MAX_PROVENANCE_BLOCKS or any(n > MAX_PROVENANCE_CHARS for n in sizes):
        out.append(_finding('provenance', len(blocks),
                            f'근거 블록이 {len(blocks)}개·최대 {max(sizes)}자다'
                            f'({MAX_PROVENANCE_BLOCKS}개·{MAX_PROVENANCE_CHARS}자까지) — '
                            '입력·공식·결과만 둔다. 줄글은 본문으로'))

    m = _STRATEGY.search(body)
    if m and not _JUDGMENT.search(_text(m.group(1))):
        out.append(_finding('judgment_verb', 0,
                            '전략 코멘트에 판단 동사(판단한다·본다·전망한다·예상한다)가 없다 — '
                            '판단을 섹션 첫머리에 자기 동사로 말한다', 'warn'))

    whole = ' '.join(texts)
    dashes = whole.count('—')
    if dashes > MAX_EMDASH:
        out.append(_finding('emdash', dashes,
                            f'줄표(—)로 이은 곳이 {dashes}군데다({MAX_EMDASH}군데까지 권장) — '
                            '문장을 나누거나 「~해서」·「~지만」으로 잇는다', 'warn'))

    hedges = sum(whole.count(h) for h in HEDGES)
    if hedges > MAX_HEDGES:
        out.append(_finding('hedge', hedges,
                            f'「가를 자료가 없다·단정하지 않는다」류 단서가 {hedges}번이다'
                            f'({MAX_HEDGES}번까지 권장) — 한계는 섹션당 한 번, 다음 확인 자료와 '
                            '묶어 쓰고 안 할 말은 그냥 안 한다', 'warn'))

    counts = {}
    for n in _NUMBER.findall(whole):
        counts[n] = counts.get(n, 0) + 1
    repeated = sorted((k for k, v in counts.items() if v > MAX_SAME_NUMBER),
                      key=lambda k: -counts[k])
    if repeated:
        shown = ', '.join(f'{k}({counts[k]}회)' for k in repeated[:4])
        out.append(_finding('repeat_number', len(repeated),
                            f'같은 수치가 {MAX_SAME_NUMBER}번 넘게 나온다 — {shown}. '
                            '다시 부를 때는 수치 없이 「시가가 곧 고가」처럼', 'warn'))
    return out
