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

MAX_IMPERSONAL = 2
MAX_TRANSLATIONESE = 3
MAX_NOMINAL_LABELS = 2
MAX_NOUN_ENDINGS = 2
MAX_SAME_OPENER = 4
MAX_SAME_ENDING_RUN = 3


def _prose_html(html):
    """산문 문단만. 표와 제목은 라벨이 짧아 개조식으로 오탐된다."""
    body = html[html.index('<body'):] if '<body' in html else html
    body = _SCRIPT.sub(' ', body)
    body = _TABLE.sub(' ', body)
    body = _HEADING.sub(' ', body)
    return _PARA.findall(body)


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
    return out
